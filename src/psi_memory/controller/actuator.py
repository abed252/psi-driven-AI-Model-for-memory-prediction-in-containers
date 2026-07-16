"""Actuators: apply a limit value to a target, or pretend to (dry-run).

Failed writes are returned as results, never raised through the control
loop — the spec requires recording failures rather than hiding them (or
crashing the experiment).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from psi_memory.common.units import MIB, mib_to_bytes

log = logging.getLogger(__name__)


@dataclass
class WriteResult:
    ok: bool
    target: str
    value_mib: float
    error: str | None = None
    dry_run: bool = False


class DryRunActuator:
    """Records what would have been written; touches nothing."""

    def __init__(self):
        self.writes: list[WriteResult] = []

    def apply(self, target: str, value_mib: float) -> WriteResult:
        result = WriteResult(ok=True, target=target, value_mib=value_mib,
                             dry_run=True)
        self.writes.append(result)
        return result

    def read_current_limits(self) -> dict:
        return {}


class FakeCgroupActuator:
    """Writes to a fake cgroup directory — the spec's pre-live test harness."""

    def __init__(self, cgroup_dir: Path):
        self.cgroup_dir = Path(cgroup_dir)

    def apply(self, target: str, value_mib: float) -> WriteResult:
        try:
            path = self.cgroup_dir / target
            if not self.cgroup_dir.is_dir():
                raise FileNotFoundError(f"cgroup dir gone: {self.cgroup_dir}")
            path.write_text(f"{mib_to_bytes(round(value_mib * MIB) / MIB)}\n")
            return WriteResult(ok=True, target=target, value_mib=value_mib)
        except OSError as err:
            return WriteResult(ok=False, target=target, value_mib=value_mib,
                               error=f"{type(err).__name__}: {err}")

    def read_current_limits(self) -> dict:
        limits = {}
        for name in ("memory.max", "memory.high"):
            path = self.cgroup_dir / name
            if path.exists():
                limits[name] = path.read_text().strip()
        return limits


class DockerActuator:
    """Live actuation on a docker container.

    memory.max goes through `docker update` (docker's bookkeeping stays
    consistent; memory-swap is scaled alongside). memory.high is not exposed
    by docker, so it is written through the privileged sidecar (see D2).
    """

    def __init__(self, container: str, swap_factor: float = 2.0):
        self.container = container
        self.swap_factor = swap_factor

    def apply(self, target: str, value_mib: float) -> WriteResult:
        from psi_memory.environment.docker_cli import DockerError
        from psi_memory.environment.probe import (
            sidecar_write_memory_high,
            update_memory_limit,
        )

        try:
            if target == "memory.max":
                limit = f"{int(round(value_mib))}m"
                swap = f"{int(round(value_mib * self.swap_factor))}m"
                update_memory_limit(self.container, limit, swap)
            elif target == "memory.high":
                sidecar_write_memory_high(
                    self.container, str(mib_to_bytes(int(round(value_mib)))))
            else:
                return WriteResult(ok=False, target=target, value_mib=value_mib,
                                   error=f"unknown target {target!r}")
            return WriteResult(ok=True, target=target, value_mib=value_mib)
        except DockerError as err:
            log.warning("write failed (%s=%.1f MiB): %s", target, value_mib, err)
            return WriteResult(ok=False, target=target, value_mib=value_mib,
                               error=str(err))

    def restore(self, target: str, original: str,
                original_swap: str | None = None) -> WriteResult:
        """Restore an original raw cgroup value recorded before the session."""
        from psi_memory.environment.docker_cli import DockerError
        from psi_memory.environment.probe import (
            sidecar_write_memory_high,
            update_memory_limit,
        )

        try:
            if target == "memory.high":
                sidecar_write_memory_high(self.container, original)
                return WriteResult(ok=True, target=target, value_mib=-1)
            if target == "memory.max" and original.isdigit():
                swap = (original_swap if original_swap and original_swap.isdigit()
                        else str(int(original) * 2))
                update_memory_limit(self.container, f"{int(original)}b",
                                    f"{int(swap)}b")
                return WriteResult(ok=True, target=target,
                                   value_mib=int(original) / MIB)
            return WriteResult(ok=False, target=target, value_mib=-1,
                               error=f"cannot restore {target}={original!r}")
        except DockerError as err:
            return WriteResult(ok=False, target=target, value_mib=-1,
                               error=str(err))
