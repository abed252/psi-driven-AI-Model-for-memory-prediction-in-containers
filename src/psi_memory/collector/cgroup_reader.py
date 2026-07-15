"""Read a container's memory metrics from a cgroup v2 directory.

The reader is path-based so it works identically on a real cgroup mount
(inside the Docker Desktop VM) and on a fake directory tree in unit tests.
Fields that do not exist on the running kernel are reported as None and
listed in `missing_fields` — never silently zeroed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from psi_memory.collector.parsers import PsiSample, parse_keyed_counters, parse_psi
from psi_memory.common.units import parse_cgroup_scalar


@dataclass
class MemorySnapshot:
    current_bytes: int | None = None
    max_bytes: int | None = None  # None = file said "max" (unlimited)
    high_bytes: int | None = None
    swap_current_bytes: int | None = None
    swap_max_bytes: int | None = None
    pressure: PsiSample | None = None
    events: dict[str, int] | None = None
    stat: dict[str, int] | None = None
    missing_fields: list[str] = field(default_factory=list)
    unlimited_fields: list[str] = field(default_factory=list)


SCALAR_FILES = {
    "memory.current": "current_bytes",
    "memory.max": "max_bytes",
    "memory.high": "high_bytes",
    "memory.swap.current": "swap_current_bytes",
    "memory.swap.max": "swap_max_bytes",
}


def read_memory_snapshot(cgroup_dir: Path) -> MemorySnapshot:
    """Read one snapshot of every memory metric the project collects."""
    snap = MemorySnapshot()

    for filename, attr in SCALAR_FILES.items():
        path = cgroup_dir / filename
        if not path.exists():
            snap.missing_fields.append(filename)
            continue
        value = parse_cgroup_scalar(path.read_text())
        if value is None:
            snap.unlimited_fields.append(filename)
        setattr(snap, attr, value)

    psi_path = cgroup_dir / "memory.pressure"
    if psi_path.exists():
        snap.pressure = parse_psi(psi_path.read_text())
    else:
        snap.missing_fields.append("memory.pressure")

    for filename, attr in (("memory.events", "events"), ("memory.stat", "stat")):
        path = cgroup_dir / filename
        if path.exists():
            setattr(snap, attr, parse_keyed_counters(path.read_text()))
        else:
            snap.missing_fields.append(filename)

    return snap
