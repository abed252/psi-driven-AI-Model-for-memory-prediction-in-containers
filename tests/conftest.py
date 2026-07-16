"""Shared test helpers: synthetic raw runs (no Docker required)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

MIB = 1024 * 1024


def default_current(i: int) -> float:
    """Gentle ramp with a wiggle, in MiB."""
    return 40 + 0.8 * i + 5 * math.sin(i / 5)


def write_synth_run(
    raw_dir: Path,
    run_id: str,
    workload: str = "steady",
    n_samples: int = 120,
    current_fn=default_current,          # i -> MiB
    psi_avg10_fn=lambda i: 0.0,          # i -> % (also drives stall totals)
    limit_mib: int = 256,
    interval_s: float = 1.0,
    drop_indices: frozenset[int] = frozenset(),
    oom: bool = False,
) -> Path:
    """Write a synthetic-but-schema-faithful raw run directory."""
    run_dir = raw_dir / run_id
    run_dir.mkdir(parents=True)
    some_total = 0
    lines = [json.dumps({"type": "header", "interval_s": interval_s,
                         "cgroup_dir": "/synthetic", "sampler_version": 1})]
    for i in range(n_samples):
        if i in drop_indices:
            continue
        avg10 = psi_avg10_fn(i)
        some_total += int(avg10 * 10_000 * interval_s)  # crude but monotonic
        current_mib = current_fn(i)
        lines.append(json.dumps({
            "type": "sample",
            "mono": 1000.0 + i * interval_s,
            "wall": 1.75e9 + i * interval_s,
            "missing": [],
            "current": int(current_mib * MIB),
            "max": limit_mib * MIB,
            "high": "max",
            "swap_current": int(max(0.0, current_mib - limit_mib * 0.8) * MIB),
            "swap_max": limit_mib * MIB,
            "pressure": {
                "some": {"avg10": avg10, "avg60": avg10 / 2, "avg300": avg10 / 4,
                         "total": some_total},
                "full": {"avg10": avg10 / 2, "avg60": avg10 / 4, "avg300": 0.0,
                         "total": some_total // 2},
            },
            "events": {"low": 0, "high": 0, "max": 0, "oom": int(oom),
                       "oom_kill": int(oom)},
            "stat": {"anon": int(current_mib * 0.8 * MIB),
                     "file": int(current_mib * 0.2 * MIB)},
        }))
    lines.append(json.dumps({"type": "end", "reason": "target_exited"}))
    (run_dir / "samples.jsonl").write_text("\n".join(lines) + "\n",
                                           encoding="utf-8")
    meta = {
        "run_id": run_id, "workload": workload, "params": {}, "seed": 1,
        "image": "psi-workloads:synthetic", "image_digest": "sha256:synthetic",
        "memory_limit": f"{limit_mib}m", "memory_swap": f"{limit_mib * 2}m",
        "memory_high": None, "duration_s": n_samples * interval_s,
        "started_wall": 1.75e9, "finished_wall": 1.75e9 + n_samples,
        "exit_code": 137 if oom else 0, "completed_within_timeout": True,
        "oom_killed_flag": oom, "final_memory_events": {"oom_kill": int(oom)},
        "oom_observed": oom, "collector": {"interval_s": interval_s,
                                           "samples": n_samples,
                                           "end_reason": "target_exited"},
        "env_validation_id": "synthetic-test", "spec": {},
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2),
                                       encoding="utf-8")
    return run_dir


@pytest.fixture()
def synth_raw(tmp_path):
    """A raw-data directory factory: call it to add runs, use .dir to build."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    class Factory:
        dir = raw_dir

        @staticmethod
        def add(run_id: str, **kwargs) -> Path:
            return write_synth_run(raw_dir, run_id, **kwargs)

    return Factory
