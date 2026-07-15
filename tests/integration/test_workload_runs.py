"""End-to-end workload runs through the batch runner (docker-marked, slow).

Uses short durations; asserts the collection pipeline, not PSI magnitudes
(those are the calibration's job — PSI assertions here would be flaky).
"""

import json
from pathlib import Path

import pytest

from psi_memory.environment.docker_cli import run_docker
from psi_memory.workloads.config import RunSpec
from psi_memory.workloads.runner import execute_run

pytestmark = pytest.mark.docker

IMAGE = "psi-workloads:latest"


@pytest.fixture(scope="module", autouse=True)
def build_image():
    root = Path(__file__).parents[2]
    run_docker("build", "-q", "-f", str(root / "docker" / "Dockerfile.workloads"),
               "-t", IMAGE, str(root), timeout=300)


def spec(workload, duration_s=10, interval_s=0.5, params=None, **kw):
    return RunSpec(
        workload=workload, seed=123, duration_s=duration_s,
        interval_s=interval_s, memory_limit=kw.get("memory_limit", "256m"),
        memory_swap=kw.get("memory_swap", "512m"),
        memory_high=kw.get("memory_high"), params=params or {},
    )


def read_samples(run_dir: Path) -> list[dict]:
    lines = (run_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines]


def test_steady_run_end_to_end(tmp_path):
    meta = execute_run(
        spec("steady", params={"working_set_mib": 32}),
        tmp_path, IMAGE, validation_id="itest",
    )
    run_dir = tmp_path / meta["run_id"]
    assert (run_dir / "meta.json").exists()
    assert (run_dir / "workload.log").exists()

    records = read_samples(run_dir)
    samples = [r for r in records if r["type"] == "sample"]
    assert records[0]["type"] == "header"
    assert records[-1]["type"] == "end"
    assert len(samples) >= 10  # ~10 s at 0.5 s interval, generous
    monos = [s["mono"] for s in samples]
    assert all(b > a for a, b in zip(monos, monos[1:]))
    assert all(s["current"] > 32 * 1024 * 1024 for s in samples[4:])

    # Metadata must satisfy every spec-required field.
    for field in ("run_id", "workload", "params", "seed", "image_digest",
                  "memory_limit", "memory_swap", "memory_high",
                  "started_wall", "finished_wall", "exit_code",
                  "oom_observed", "env_validation_id", "collector"):
        assert field in meta, f"meta.json missing {field}"
    assert meta["exit_code"] == 0
    assert meta["oom_observed"] is False
    assert meta["env_validation_id"] == "itest"


def test_collector_survives_early_target_exit(tmp_path):
    # 4-second workload: the collector must notice the cgroup vanish and
    # end with reason=target_exited rather than hanging or crashing.
    meta = execute_run(
        spec("steady", duration_s=4, params={"working_set_mib": 8}),
        tmp_path, IMAGE, validation_id=None,
    )
    records = read_samples(tmp_path / meta["run_id"])
    assert records[-1]["type"] == "end"
    assert records[-1]["reason"] == "target_exited"
    assert meta["collector"]["end_reason"] == "target_exited"


def test_leak_run_records_growth_and_oom(tmp_path):
    # Aggressive leak under a tiny limit: must OOM well within the timeout.
    meta = execute_run(
        spec("leak", duration_s=60, memory_limit="64m", memory_swap="96m",
             params={"step_mib": 16, "tick_s": 0.5, "retouch_fraction": 0.5}),
        tmp_path, IMAGE, validation_id=None,
    )
    samples = [r for r in read_samples(tmp_path / meta["run_id"])
               if r["type"] == "sample"]
    assert len(samples) >= 3
    currents = [s["current"] for s in samples]
    assert max(currents) > currents[0]  # growth was captured
    assert meta["oom_observed"] is True
    assert meta["exit_code"] not in (0, None)


def test_memory_high_applied(tmp_path):
    meta = execute_run(
        spec("steady", duration_s=8, memory_high="128m",
             params={"working_set_mib": 16}),
        tmp_path, IMAGE, validation_id=None,
    )
    samples = [r for r in read_samples(tmp_path / meta["run_id"])
               if r["type"] == "sample"]
    assert any(s["high"] == 128 * 1024 * 1024 for s in samples)
