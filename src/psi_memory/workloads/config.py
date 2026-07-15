"""Batch-run configuration: YAML parsing and run-matrix expansion."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from psi_memory.common.seed import derive_seed

WORKLOAD_SCRIPTS = {
    "steady": "steady.py",
    "leak": "leak.py",
    "file_burst": "file_burst.py",
    "bursty": "bursty.py",
    "trace_replay": "trace_replay.py",
}


@dataclass(frozen=True)
class RunSpec:
    workload: str
    seed: int
    duration_s: float
    interval_s: float          # collector sampling interval
    memory_limit: str          # docker --memory value, e.g. "256m"
    memory_swap: str           # docker --memory-swap value (limit+swap)
    memory_high: str | None    # optional memory.high written via sidecar
    params: dict = field(default_factory=dict)
    entry_index: int = 0
    repeat_index: int = 0

    def workload_args(self) -> list[str]:
        """CLI arguments for the workload script inside the container."""
        args = ["--duration-s", str(self.duration_s), "--seed", str(self.seed)]
        for key, value in sorted(self.params.items()):
            args.extend([f"--{key.replace('_', '-')}", str(value)])
        return args


@dataclass
class BatchConfig:
    base_seed: int
    interval_s: float
    image: str
    runs: list[RunSpec]


def load_batch_config(path: Path) -> BatchConfig:
    """Parse a batch YAML file and expand repeats into concrete RunSpecs.

    Every repeat gets an independent, deterministically derived seed, so a
    config file fully determines the whole batch.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "runs" not in raw:
        raise ValueError(f"{path}: expected a mapping with a 'runs' list")
    defaults = raw.get("defaults", {})
    base_seed = int(defaults.get("base_seed", 42))
    default_interval = float(defaults.get("interval_s", 1.0))
    image = defaults.get("image", "psi-workloads:latest")

    specs: list[RunSpec] = []
    for entry_index, entry in enumerate(raw["runs"]):
        workload = entry.get("workload")
        if workload not in WORKLOAD_SCRIPTS:
            raise ValueError(
                f"{path}: runs[{entry_index}]: unknown workload {workload!r} "
                f"(expected one of {sorted(WORKLOAD_SCRIPTS)})"
            )
        for field_name in ("duration_s", "memory_limit", "memory_swap"):
            if field_name not in entry:
                raise ValueError(f"{path}: runs[{entry_index}]: missing {field_name!r}")
        repeats = int(entry.get("repeats", 1))
        for repeat in range(repeats):
            specs.append(
                RunSpec(
                    workload=workload,
                    seed=derive_seed(base_seed, workload, entry_index, repeat) % 2**31,
                    duration_s=float(entry["duration_s"]),
                    interval_s=float(entry.get("interval_s", default_interval)),
                    memory_limit=str(entry["memory_limit"]),
                    memory_swap=str(entry["memory_swap"]),
                    memory_high=entry.get("memory_high"),
                    params=dict(entry.get("params", {})),
                    entry_index=entry_index,
                    repeat_index=repeat,
                )
            )
    return BatchConfig(base_seed=base_seed, interval_s=default_interval,
                       image=image, runs=specs)
