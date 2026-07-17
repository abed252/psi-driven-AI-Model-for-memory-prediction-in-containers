"""Regression tests for the docker-stall crash that killed the first full
collection batch (2026-07-16): transient inspect timeouts must be retried,
and one failing run must never abort the batch."""

import subprocess

import pytest

from psi_memory.workloads import runner


class FakeProc:
    def __init__(self, stdout="false\n", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_wait_for_exit_survives_inspect_stall(monkeypatch):
    calls = {"n": 0}

    def fake_run_docker(*args, check=True, timeout=120.0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd=list(args), timeout=timeout)
        return FakeProc(stdout="false\n")  # container has exited

    monkeypatch.setattr(runner, "run_docker", fake_run_docker)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    assert runner._wait_for_exit("c", timeout_s=60) is True
    assert calls["n"] == 2  # stalled once, then succeeded


def test_force_remove_gives_up_gracefully(monkeypatch):
    def always_stalls(*args, check=True, timeout=120.0):
        raise subprocess.TimeoutExpired(cmd=list(args), timeout=timeout)

    monkeypatch.setattr(runner, "run_docker", always_stalls)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    runner._force_remove("c")  # must not raise


def test_batch_continues_past_failing_run(monkeypatch, tmp_path):
    from psi_memory.workloads.config import BatchConfig, RunSpec

    specs = [RunSpec(workload="steady", seed=i, duration_s=1, interval_s=1,
                     memory_limit="64m", memory_swap="128m", memory_high=None)
             for i in range(3)]
    executed = []

    def fake_execute_run(spec, data_dir, image, validation_id):
        executed.append(spec.seed)
        if spec.seed == 1:
            raise subprocess.TimeoutExpired(cmd=["docker"], timeout=120)
        return {"run_id": f"r{spec.seed}"}

    monkeypatch.setattr(runner, "execute_run", fake_execute_run)
    monkeypatch.setattr(runner, "latest_validation_id", lambda: "test")
    config = BatchConfig(base_seed=1, interval_s=1.0, image="img", runs=specs)
    metas = runner.execute_batch(config, tmp_path)
    assert executed == [0, 1, 2]          # run 1 failed, 2 still executed
    assert [m["run_id"] for m in metas] == ["r0", "r2"]
    assert list(tmp_path.glob("batch_*.json"))  # manifest still written
