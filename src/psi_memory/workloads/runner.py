"""Batch runner: execute workload runs and collect their metrics.

For each RunSpec it starts the workload container, attaches the sampler
sidecar (collector), waits for completion or timeout, captures exit/OOM
state, and writes data/raw/<run_id>/{samples.jsonl, workload.log, meta.json}.
Runs are never merged: one directory per run, one metadata record per run.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from psi_memory.collector.stream import collect_to_file
from psi_memory.environment import probe
from psi_memory.environment.docker_cli import DockerError, run_docker
from psi_memory.workloads.config import WORKLOAD_SCRIPTS, BatchConfig, RunSpec

log = logging.getLogger(__name__)

RUN_TIMEOUT_GRACE_S = 45  # extra wall time beyond duration_s before force-stop


def latest_validation_id(reports_dir: Path = Path("artifacts/reports")) -> str | None:
    """The validation_id of the most recent environment report, if any."""
    reports = sorted(reports_dir.glob("env_validation_*.json"))
    if not reports:
        return None
    try:
        return json.loads(reports[-1].read_text(encoding="utf-8"))["validation_id"]
    except (json.JSONDecodeError, KeyError):
        return None


def image_digest(image: str) -> str:
    return run_docker("image", "inspect", "--format", "{{.Id}}", image).stdout.strip()


def _wait_for_exit(container_name: str, timeout_s: float) -> bool:
    """Poll until the container stops. Returns False if it had to be killed."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        proc = run_docker("inspect", "-f", "{{.State.Running}}", container_name,
                          check=False)
        if proc.returncode != 0 or proc.stdout.strip() != "true":
            return True
        time.sleep(1.0)
    log.warning("%s exceeded timeout, stopping it", container_name)
    run_docker("stop", "-t", "5", container_name, check=False)
    return False


def execute_run(
    spec: RunSpec,
    data_dir: Path,
    image: str,
    validation_id: str | None,
) -> dict:
    """Execute one run end-to-end; returns the metadata record."""
    run_id = (f"{spec.workload}-{time.strftime('%Y%m%d-%H%M%S')}-"
              f"{uuid.uuid4().hex[:6]}")
    out_dir = data_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    container = f"psi-run-{run_id}"
    started_wall = time.time()
    log.info("run %s: workload=%s seed=%d limit=%s swap=%s",
             run_id, spec.workload, spec.seed, spec.memory_limit, spec.memory_swap)

    run_docker(
        "run", "-d", "--name", container,
        "--memory", spec.memory_limit, "--memory-swap", spec.memory_swap,
        image, "python", f"/app/{WORKLOAD_SCRIPTS[spec.workload]}",
        *spec.workload_args(),
    )
    collector_summary: dict = {}
    try:
        cid = probe.container_id(container)
        if spec.memory_high:
            probe.sidecar_write_memory_high(container, spec.memory_high)

        collector = threading.Thread(
            target=lambda: collector_summary.update(
                collect_to_file(
                    cid, out_dir / "samples.jsonl", spec.interval_s,
                    image=image, sidecar_name=f"psi-col-{run_id}",
                )
            ),
            daemon=True,
        )
        collector.start()

        completed = _wait_for_exit(container, spec.duration_s + RUN_TIMEOUT_GRACE_S)
        # The sampler notices the cgroup vanish and ends on its own.
        collector.join(timeout=30)
        if collector.is_alive():
            run_docker("rm", "-f", f"psi-col-{run_id}", check=False)
            collector.join(timeout=15)

        state = json.loads(
            run_docker("inspect", "-f", "{{json .State}}", container).stdout
        )
        (out_dir / "workload.log").write_text(
            run_docker("logs", container, check=False).stdout, encoding="utf-8"
        )
    finally:
        run_docker("rm", "-f", container, check=False)

    last_events = _last_sample_events(out_dir / "samples.jsonl")
    meta = {
        "run_id": run_id,
        "workload": spec.workload,
        "params": spec.params,
        "workload_args": spec.workload_args(),
        "seed": spec.seed,
        "image": image,
        "image_digest": image_digest(image),
        "memory_limit": spec.memory_limit,
        "memory_swap": spec.memory_swap,
        "memory_high": spec.memory_high,
        "duration_s": spec.duration_s,
        "started_wall": started_wall,
        "finished_wall": time.time(),
        "docker_started_at": state.get("StartedAt"),
        "docker_finished_at": state.get("FinishedAt"),
        "exit_code": state.get("ExitCode"),
        "completed_within_timeout": completed,
        "oom_killed_flag": bool(state.get("OOMKilled")),
        "final_memory_events": last_events,
        "oom_observed": bool(state.get("OOMKilled"))
                         or bool(last_events and last_events.get("oom_kill", 0) > 0),
        "collector": {"interval_s": spec.interval_s, **collector_summary},
        "env_validation_id": validation_id,
        "spec": asdict(spec),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.info("run %s: exit=%s oom=%s samples=%s", run_id, meta["exit_code"],
             meta["oom_observed"], collector_summary.get("samples"))
    return meta


def _last_sample_events(samples_path: Path) -> dict | None:
    """memory.events counters from the last collected sample, if any."""
    if not samples_path.exists():
        return None
    events = None
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") == "sample" and record.get("events") is not None:
                events = record["events"]
    return events


def execute_batch(config: BatchConfig, data_dir: Path = Path("data/raw")) -> list[dict]:
    """Execute every run in a batch sequentially; writes a batch manifest."""
    validation_id = latest_validation_id()
    if validation_id is None:
        log.warning("no environment validation report found — "
                    "run psi-validate-env first; recording env_validation_id=null")
    metas = []
    for spec in config.runs:
        try:
            metas.append(execute_run(spec, data_dir, config.image, validation_id))
        except DockerError:
            log.exception("run failed (workload=%s entry=%d repeat=%d); continuing",
                          spec.workload, spec.entry_index, spec.repeat_index)
    manifest = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "image": config.image,
        "base_seed": config.base_seed,
        "run_ids": [m["run_id"] for m in metas],
    }
    manifest_path = data_dir / f"batch_{time.strftime('%Y%m%d-%H%M%S')}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("batch complete: %d/%d runs, manifest %s",
             len(metas), len(config.runs), manifest_path)
    return metas
