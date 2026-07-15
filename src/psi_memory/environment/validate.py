"""Non-mutating environment validator (Phase 0).

Reports — without changing any persistent system state — whether this
machine can support the project: Docker Desktop, cgroup v2, per-container
PSI, readable cgroup paths, swap, and dynamic limit updates.

The only side effects are temporary, project-owned containers that are
removed before returning, and a `docker update` applied to one of those
temporary containers (never to anything pre-existing).
"""

from __future__ import annotations

import logging
import platform
import sys

from psi_memory.collector.parsers import parse_psi
from psi_memory.common.units import parse_cgroup_scalar
from psi_memory.environment import probe
from psi_memory.environment.docker_cli import (
    DockerError,
    daemon_running,
    docker_available,
    docker_json,
    run_docker,
)
from psi_memory.environment.report import EnvReport, new_report

log = logging.getLogger(__name__)

DOCKER_DESKTOP_LIMITATIONS = (
    "Containers run inside Docker Desktop's WSL2 utility VM, not on the "
    "Windows host: (1) global /proc/pressure reflects the VM, not Windows; "
    "(2) VM RAM/swap are capped by Docker Desktop settings; (3) host-tree "
    "cgroup access needs a privileged sidecar with --cgroupns=host, target "
    "path /sys/fs/cgroup/docker/<container-id>/; (4) per-sample `docker "
    "exec` from Windows costs ~100-300 ms, so sampling loops must run "
    "inside the VM; (5) bind mounts from Windows paths are slow and this "
    "project's path contains non-ASCII characters — prefer stdout/`docker "
    "cp` for moving data out of containers."
)


def check_host(report: EnvReport) -> None:
    report.add(
        "host.os", "pass",
        f"{platform.system()} {platform.release()} ({platform.version()})",
        system=platform.system(), release=platform.release(),
    )
    py = sys.version.split()[0]
    status = "pass" if sys.version_info[:2] >= (3, 11) else "fail"
    report.add("host.python", status, f"Python {py}", version=py)


def check_docker(report: EnvReport) -> bool:
    """Docker client/daemon checks. Returns False if container checks must be skipped."""
    if not docker_available():
        report.add("docker.client", "fail", "docker CLI not found on PATH")
        return False
    if not daemon_running():
        report.add(
            "docker.daemon", "fail",
            "Docker daemon not reachable — start Docker Desktop and re-run",
        )
        return False

    version = docker_json("version", "--format", "{{json .}}")
    client = version.get("Client", {}).get("Version", "?")
    server = version.get("Server", {}).get("Version", "?")
    report.add("docker.version", "pass", f"client {client}, server {server}",
               client=client, server=server)

    context = run_docker("context", "show").stdout.strip()
    report.add("docker.context", "pass", f"active context: {context}", context=context)

    info = docker_json("info", "--format", "{{json .}}")
    cgroup_version = str(info.get("CgroupVersion", "?"))
    report.add(
        "docker.cgroup_version",
        "pass" if cgroup_version == "2" else "fail",
        f"cgroup v{cgroup_version} (driver: {info.get('CgroupDriver', '?')})",
        cgroup_version=cgroup_version, driver=info.get("CgroupDriver"),
    )
    report.add(
        "docker.vm", "pass",
        f"kernel {info.get('KernelVersion', '?')}, "
        f"{info.get('NCPU', '?')} CPUs, "
        f"{round(info.get('MemTotal', 0) / 2**30, 1)} GiB VM memory",
        kernel=info.get("KernelVersion"), ncpu=info.get("NCPU"),
        mem_total_bytes=info.get("MemTotal"),
    )
    return cgroup_version == "2"


def check_vm_psi_and_swap(report: EnvReport) -> None:
    """Global (VM-level) PSI availability and swap status."""
    proc = run_docker(
        "run", "--rm", probe.PROBE_IMAGE, "sh", "-c",
        "cat /proc/pressure/memory; echo ---; free -b | tail -1",
        check=False, timeout=180,
    )
    if proc.returncode != 0:
        report.add("vm.psi_global", "fail", f"probe container failed: {proc.stderr.strip()}")
        return
    psi_text, _, swap_line = proc.stdout.partition("---")
    try:
        parse_psi(psi_text)
        report.add("vm.psi_global", "pass", "/proc/pressure/memory present and parseable")
    except ValueError as err:
        report.add("vm.psi_global", "fail", f"global PSI unparseable: {err}")
    swap_fields = swap_line.split()
    if len(swap_fields) >= 2 and swap_fields[0].lower().startswith("swap"):
        total = int(swap_fields[1])
        status = "pass" if total > 0 else "warn"
        report.add(
            "vm.swap", status,
            f"VM swap total {round(total / 2**30, 1)} GiB"
            + ("" if total else " — pressure workloads need swap"),
            swap_total_bytes=total,
        )
    else:
        report.add("vm.swap", "warn", f"could not parse swap line: {swap_line.strip()!r}")


def check_container_cgroup(report: EnvReport) -> None:
    """Per-container checks on a temporary container (started and removed here)."""
    name = probe.start_temp_container()
    try:
        cid = probe.container_id(name)
        report.add("container.started", "pass", f"temp container {name} ({cid[:12]})")

        # Path 1: readable files from inside the container.
        contents = probe.exec_read_files(name)
        readable = [f for f, text in contents.items() if text is not None]
        missing = [f for f, text in contents.items() if text is None]
        report.add(
            "container.readable_files",
            "pass" if "memory.current" in readable and "memory.pressure" in readable else "fail",
            f"readable from inside container: {', '.join(readable)}"
            + (f"; missing: {', '.join(missing)}" if missing else ""),
            readable=readable, missing=missing,
        )

        psi_text = contents.get("memory.pressure")
        if psi_text:
            sample = parse_psi(psi_text)
            report.add(
                "container.psi", "pass",
                f"per-container PSI parseable (some avg10={sample.some.avg10})",
            )
        else:
            report.add("container.psi", "fail", "memory.pressure not readable in container")

        swap_max = contents.get("memory.swap.max")
        if swap_max is not None:
            value = parse_cgroup_scalar(swap_max)
            report.add(
                "container.swap", "pass" if value is None or value > 0 else "warn",
                f"memory.swap.max = {'max' if value is None else value}",
            )

        # Path 2: sidecar sampling from the host cgroup tree.
        samples = probe.sidecar_sample(name, num_samples=5, interval_s=1.0)
        uptimes = [s.uptime_s for s in samples]
        monotonic = all(b > a for a, b in zip(uptimes, uptimes[1:]))
        ok = len(samples) == 5 and monotonic and all(s.current_bytes > 0 for s in samples)
        report.add(
            "container.sidecar_sampling",
            "pass" if ok else "fail",
            f"{len(samples)}/5 samples via privileged sidecar, "
            f"monotonic timestamps: {monotonic}, "
            f"memory.current ~{samples[-1].current_bytes if samples else '?'} B",
            num_samples=len(samples), monotonic=monotonic,
            currents=[s.current_bytes for s in samples],
            psi_some_avg10=[s.pressure.some.avg10 for s in samples],
        )

        # Dynamic memory.max via docker update (applied to our temp container only).
        before = parse_cgroup_scalar(probe.exec_read_files(name, ["memory.max"])["memory.max"])
        probe.update_memory_limit(name, "512m", "1g")
        after = parse_cgroup_scalar(probe.exec_read_files(name, ["memory.max"])["memory.max"])
        report.add(
            "container.dynamic_memory_max",
            "pass" if after == 512 * 2**20 and after != before else "fail",
            f"docker update changed memory.max {before} -> {after} without restart",
            before=before, after=after,
        )

        # memory.high write via privileged sidecar, then restored to "max".
        probe.sidecar_write_memory_high(name, str(128 * 2**20))
        high = parse_cgroup_scalar(probe.exec_read_files(name, ["memory.high"])["memory.high"])
        probe.sidecar_write_memory_high(name, "max")
        restored = parse_cgroup_scalar(probe.exec_read_files(name, ["memory.high"])["memory.high"])
        report.add(
            "container.memory_high_write",
            "pass" if high == 128 * 2**20 and restored is None else "fail",
            f"sidecar wrote memory.high={high}, restored to "
            f"{'max' if restored is None else restored}",
            written=high, restored="max" if restored is None else restored,
        )
    except DockerError as err:
        report.add("container.checks", "fail", f"docker error during container checks: {err}")
    finally:
        probe.stop_container(name)


def validate_environment(skip_docker: bool = False) -> EnvReport:
    report = new_report()
    check_host(report)
    if skip_docker:
        report.add("docker", "skip", "docker checks skipped (--skip-docker)")
    else:
        cgroup_v2 = check_docker(report)
        if cgroup_v2:
            check_vm_psi_and_swap(report)
            check_container_cgroup(report)
    report.add("docker_desktop.limitations", "warn", DOCKER_DESKTOP_LIMITATIONS)
    return report
