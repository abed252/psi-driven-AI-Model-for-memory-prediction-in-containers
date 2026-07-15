"""Container probing: start temporary containers and sample their cgroup files.

Two access paths were validated on this machine (see docs/decisions.md):

1. inside-container: `docker exec <target> cat /sys/fs/cgroup/<file>` —
   works because cgroup namespaces make the container's own cgroup appear
   as the root of its /sys/fs/cgroup mount. One process spawn per sample
   from Windows (~100-300 ms), so it is used for validation only.

2. sidecar: a privileged helper container started with `--cgroupns=host`
   and `-v /sys/fs/cgroup:/host/cgroup:ro` sees the Docker Desktop VM's
   full cgroup tree; a target container's directory is
   /host/cgroup/docker/<container-id>/. Sampling loops run *inside* the
   VM at native speed. This is the collection path for Phase 1.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from psi_memory.collector.parsers import PsiSample, parse_psi
from psi_memory.common.units import parse_cgroup_scalar
from psi_memory.environment.docker_cli import run_docker

PROBE_IMAGE = "alpine:3.20"
CGROUP_FILES = [
    "memory.current",
    "memory.max",
    "memory.high",
    "memory.swap.current",
    "memory.swap.max",
    "memory.pressure",
    "memory.events",
    "memory.stat",
]


@dataclass(frozen=True)
class ProbeSample:
    uptime_s: float  # VM monotonic time (from /proc/uptime)
    current_bytes: int
    pressure: PsiSample


def start_temp_container(memory_limit: str = "256m", name_prefix: str = "psi-probe") -> str:
    """Start a disposable sleeping container; returns its name."""
    name = f"{name_prefix}-{uuid.uuid4().hex[:8]}"
    run_docker(
        "run", "-d", "--rm", "--name", name, "--memory", memory_limit,
        PROBE_IMAGE, "sleep", "600",
    )
    return name


def stop_container(name: str) -> None:
    run_docker("stop", "-t", "1", name, check=False)


def container_id(name: str) -> str:
    return run_docker("inspect", "-f", "{{.Id}}", name).stdout.strip()


def exec_read_files(name: str, files: list[str] | None = None) -> dict[str, str | None]:
    """Read cgroup files from inside the target container (path 1).

    Returns file -> content, or None when the file does not exist.
    """
    files = files or CGROUP_FILES
    results: dict[str, str | None] = {}
    for filename in files:
        proc = run_docker(
            "exec", name, "cat", f"/sys/fs/cgroup/{filename}", check=False
        )
        results[filename] = proc.stdout if proc.returncode == 0 else None
    return results


def sidecar_sample(
    target_name: str, num_samples: int = 5, interval_s: float = 1.0
) -> list[ProbeSample]:
    """Sample memory.current + memory.pressure via a one-shot sidecar (path 2).

    The whole sampling loop runs inside the Docker Desktop VM, so the
    per-sample cost is a couple of file reads, not a Windows process spawn.
    Timestamps come from the VM's /proc/uptime (monotonic).
    """
    cid = container_id(target_name)
    script = (
        f'D=/host/cgroup/docker/{cid}; '
        f'i=0; while [ $i -lt {num_samples} ]; do '
        f'echo "SAMPLE $(cut -d\' \' -f1 /proc/uptime)"; '
        f'cat "$D/memory.current" "$D/memory.pressure"; '
        f'echo END; i=$((i+1)); sleep {interval_s}; done'
    )
    proc = run_docker(
        "run", "--rm", "--privileged", "--cgroupns=host",
        "-v", "/sys/fs/cgroup:/host/cgroup:ro",
        PROBE_IMAGE, "sh", "-c", script,
        timeout=60 + num_samples * (interval_s + 2),
    )
    return _parse_probe_output(proc.stdout)


def _parse_probe_output(text: str) -> list[ProbeSample]:
    samples: list[ProbeSample] = []
    block: list[str] = []
    uptime: float | None = None
    for line in text.splitlines():
        if line.startswith("SAMPLE "):
            uptime = float(line.split()[1])
            block = []
        elif line == "END":
            if uptime is None or len(block) < 3:
                raise ValueError(f"malformed probe block before END: {block!r}")
            current = parse_cgroup_scalar(block[0])
            if current is None:
                raise ValueError("memory.current reported 'max'")
            samples.append(
                ProbeSample(
                    uptime_s=uptime,
                    current_bytes=current,
                    pressure=parse_psi("\n".join(block[1:])),
                )
            )
        else:
            block.append(line)
    return samples


def update_memory_limit(name: str, memory: str, memory_swap: str) -> None:
    """Dynamically change a running container's memory.max via docker update."""
    run_docker("update", "--memory", memory, "--memory-swap", memory_swap, name)


def sidecar_write_memory_high(target_name: str, value: str) -> None:
    """Write the target's memory.high through a privileged rw sidecar.

    `value` is either a byte count or "max". Used later by the Senpai-style
    controller; validated here because docker CLI cannot set memory.high.
    """
    cid = container_id(target_name)
    run_docker(
        "run", "--rm", "--privileged", "--cgroupns=host",
        "-v", "/sys/fs/cgroup:/host/cgroup",
        PROBE_IMAGE, "sh", "-c",
        f'echo {value} > /host/cgroup/docker/{cid}/memory.high',
    )


def wait_monotonic(interval_s: float, last_deadline: float | None = None) -> float:
    """Monotonic-clock scheduling helper: returns the next deadline and sleeps.

    Using absolute deadlines instead of `sleep(interval)` prevents drift
    accumulating across samples (spec requirement for the collector).
    """
    now = time.monotonic()
    deadline = (last_deadline or now) + interval_s
    if deadline > now:
        time.sleep(deadline - now)
    return deadline
