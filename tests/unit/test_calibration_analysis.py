"""Calibration checks against synthetic run data (no Docker, no plots)."""

import json

import pytest

from psi_memory.environment.calibration import (
    Check,
    _direction_changes,
    check_run,
    load_run,
)


def write_run(tmp_path, run_id, workload, samples, meta_extra=None):
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    meta = {"run_id": run_id, "workload": workload, "params": {},
            "oom_observed": False, **(meta_extra or {})}
    (run_dir / "meta.json").write_text(json.dumps(meta))
    with open(run_dir / "samples.jsonl", "w") as f:
        f.write(json.dumps({"type": "header"}) + "\n")
        for s in samples:
            f.write(json.dumps({"type": "sample", **s}) + "\n")
        f.write(json.dumps({"type": "end", "reason": "target_exited"}) + "\n")
    return run_dir


def sample(mono, current_mib, some_avg10=0.0, some_total=0, oom_kill=0):
    return {
        "mono": mono, "wall": mono, "current": current_mib * 1024 * 1024,
        "max": 256 * 1024 * 1024, "high": "max",
        "swap_current": 0, "swap_max": 0,
        "pressure": {"some": {"avg10": some_avg10, "avg60": 0, "avg300": 0,
                              "total": some_total},
                     "full": {"avg10": 0, "avg60": 0, "avg300": 0, "total": 0}},
        "events": {"oom": 0, "oom_kill": oom_kill},
        "missing": [],
    }


def passed(checks: list[Check], name: str) -> bool:
    return next(c for c in checks if c.name == name).passed


def test_steady_quiet_passes(tmp_path):
    samples = [sample(i, 64, some_avg10=0.0, some_total=100) for i in range(30)]
    run = load_run(write_run(tmp_path, "r1", "steady", samples))
    checks = check_run(run)
    assert passed(checks, "psi_near_zero") and passed(checks, "no_oom")


def test_steady_with_pressure_fails(tmp_path):
    samples = [sample(i, 64, some_avg10=8.0, some_total=i * 400_000)
               for i in range(30)]
    checks = check_run(load_run(write_run(tmp_path, "r2", "steady", samples)))
    assert not passed(checks, "psi_near_zero")


def test_leak_rising_psi_and_oom_passes(tmp_path):
    samples = [sample(i, 40 + 8 * i, some_avg10=min(3 * i, 60),
                      some_total=i * 300_000, oom_kill=1 if i > 25 else 0)
               for i in range(30)]
    run = load_run(write_run(tmp_path, "r3", "leak", samples,
                             {"oom_observed": True}))
    checks = check_run(run)
    assert passed(checks, "psi_rises") and passed(checks, "oom_detected")
    assert run.oom_kill_t  # the oom_kill counter increment was located in time


def test_leak_without_pressure_fails(tmp_path):
    samples = [sample(i, 40 + i) for i in range(30)]
    checks = check_run(load_run(write_run(tmp_path, "r4", "leak", samples)))
    assert not passed(checks, "psi_rises")
    assert not passed(checks, "oom_detected")


def test_bursty_oscillation_detected(tmp_path):
    wave = [40, 200, 200, 40, 40, 200, 200, 40, 40, 200, 200, 40]
    samples = [sample(i, mib, some_avg10=20 if mib > 100 else 0,
                      some_total=i * 200_000)
               for i, mib in enumerate(wave * 3)]
    checks = check_run(load_run(write_run(tmp_path, "r5", "bursty", samples)))
    assert passed(checks, "usage_oscillates") and passed(checks, "psi_active")


def test_file_burst_high_usage_low_psi(tmp_path):
    samples = [sample(i, 220, some_avg10=0.5, some_total=1000) for i in range(30)]
    checks = check_run(load_run(write_run(tmp_path, "r6", "file_burst", samples)))
    assert passed(checks, "usage_high") and passed(checks, "psi_low")


def test_direction_changes_counts_swings():
    flat = [10.0] * 20
    assert _direction_changes(flat, 5.0) == 0
    wave = [10.0, 100.0, 10.0, 100.0, 10.0]
    assert _direction_changes(wave, 20.0) >= 3
