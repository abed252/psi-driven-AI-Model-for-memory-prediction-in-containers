"""Host-side collector: launch the sampler sidecar and stream its JSONL.

The sampler loop runs inside the Docker Desktop VM (see workloads/sampler.py);
this module starts it, parses the JSON lines from its stdout, optionally
persists them, and hands each record to the caller as a dict. Persisting via
stdout keeps raw data off Windows bind mounts (docs/decisions.md D4).
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Iterator
from pathlib import Path

from psi_memory.environment.docker_cli import run_docker

log = logging.getLogger(__name__)

DEFAULT_IMAGE = "psi-workloads:latest"


def sampler_command(
    target_container_id: str,
    interval_s: float,
    max_samples: int = 0,
    image: str = DEFAULT_IMAGE,
    sidecar_name: str | None = None,
) -> list[str]:
    """The docker command that runs the sampler sidecar for a target container."""
    name_args = ["--name", sidecar_name] if sidecar_name else []
    return [
        "docker", "run", "--rm", *name_args,
        "--privileged", "--cgroupns=host",
        "-v", "/sys/fs/cgroup:/host/cgroup:ro",
        image, "python", "/app/sampler.py",
        "--cgroup-dir", f"/host/cgroup/docker/{target_container_id}",
        "--interval-s", str(interval_s),
        "--max-samples", str(max_samples),
    ]


def stream_samples(
    target_container_id: str,
    interval_s: float = 1.0,
    max_samples: int = 0,
    image: str = DEFAULT_IMAGE,
    output_path: Path | None = None,
    sidecar_name: str | None = None,
) -> Iterator[dict]:
    """Yield sampler records; optionally persist every raw line to output_path.

    The output file (samples.jsonl) is written line-by-line with flushes, so
    a crash loses at most the current line. Ends when the sampler emits its
    "end" record (target exit, max samples) or the caller stops iterating.
    """
    cmd = sampler_command(target_container_id, interval_s, max_samples, image,
                          sidecar_name)
    sink = None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sink = open(output_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8",
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                log.warning("malformed sampler line ignored: %r", line[:200])
                continue
            if sink is not None:
                sink.write(line + "\n")
                sink.flush()
            yield record
            if record.get("type") == "end":
                break
    finally:
        if sink is not None:
            sink.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if sidecar_name:
            run_docker("rm", "-f", sidecar_name, check=False)


def collect_to_file(
    target_container_id: str,
    output_path: Path,
    interval_s: float = 1.0,
    max_samples: int = 0,
    image: str = DEFAULT_IMAGE,
    sidecar_name: str | None = None,
) -> dict:
    """Run a full collection to samples.jsonl; returns summary counts."""
    samples = 0
    end_reason = "unknown"
    for record in stream_samples(
        target_container_id, interval_s, max_samples, image, output_path,
        sidecar_name,
    ):
        if record["type"] == "sample":
            samples += 1
        elif record["type"] == "end":
            end_reason = record.get("reason", "unknown")
    return {"samples": samples, "end_reason": end_reason}
