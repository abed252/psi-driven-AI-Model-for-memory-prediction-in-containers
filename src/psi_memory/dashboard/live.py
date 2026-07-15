"""Live Rich dashboard for a running container's memory/PSI metrics.

Usage: psi-dashboard <container-name-or-id> [--interval-s 1.0]
Reads the same sampler sidecar stream as the collector, so what you see is
exactly what would be recorded.
"""

from __future__ import annotations

from psi_memory.common.units import MIB


def format_bytes(value) -> str:
    if value is None:
        return "—"
    if value == "max":
        return "max (unlimited)"
    return f"{value / MIB:,.1f} MiB"


def psi_row(psi: dict | None, kind: str) -> str:
    if not psi or kind not in psi:
        return "—"
    line = psi[kind]
    return (f"avg10 {line['avg10']:5.2f}%  avg60 {line['avg60']:5.2f}%  "
            f"avg300 {line['avg300']:5.2f}%")


def stall_delta_ms(sample: dict, previous: dict | None, kind: str) -> float | None:
    """Stall time accumulated since the previous sample, in milliseconds."""
    if previous is None:
        return None
    try:
        return (sample["pressure"][kind]["total"]
                - previous["pressure"][kind]["total"]) / 1000.0
    except (KeyError, TypeError):
        return None


def build_view(sample: dict, previous: dict | None, container_state: str,
               elapsed_s: float):
    """Build the Rich renderable for one sample (pure, unit-testable)."""
    from rich.table import Table

    current, limit = sample.get("current"), sample.get("max")
    ratio = (f"{current / limit * 100:.1f}%"
             if isinstance(current, int) and isinstance(limit, int) and limit
             else "—")
    events = sample.get("events") or {}
    some_ms = stall_delta_ms(sample, previous, "some")
    full_ms = stall_delta_ms(sample, previous, "full")

    table = Table(title=f"container: {container_state}   elapsed: {elapsed_s:6.1f}s",
                  show_header=False, min_width=68)
    table.add_column("metric", style="bold")
    table.add_column("value")
    table.add_row("memory.current", format_bytes(current))
    table.add_row("memory.max (limit)", format_bytes(limit))
    table.add_row("usage ratio", ratio)
    table.add_row("memory.high", format_bytes(sample.get("high")))
    table.add_row("swap current / max",
                  f"{format_bytes(sample.get('swap_current'))} / "
                  f"{format_bytes(sample.get('swap_max'))}")
    table.add_row("PSI some", psi_row(sample.get("pressure"), "some"))
    table.add_row("PSI full", psi_row(sample.get("pressure"), "full"))
    table.add_row("stall Δ (some/full)",
                  "—" if some_ms is None
                  else f"{some_ms:7.1f} ms / {full_ms:7.1f} ms per tick")
    table.add_row("events", "  ".join(f"{k}={events.get(k, '—')}"
                                      for k in ("high", "max", "oom", "oom_kill")))
    if sample.get("missing"):
        table.add_row("missing files", ", ".join(sample["missing"]))
    return table


def run_dashboard(container: str, interval_s: float = 1.0) -> int:
    import time

    from rich.console import Console
    from rich.live import Live

    from psi_memory.collector.stream import stream_samples
    from psi_memory.environment.docker_cli import DockerError, run_docker
    from psi_memory.environment.probe import container_id

    console = Console()
    try:
        cid = container_id(container)
    except DockerError as err:
        console.print(f"[red]cannot inspect container {container!r}: {err}[/red]")
        return 1

    previous = None
    start = time.monotonic()
    state = "running"
    with Live(console=console, refresh_per_second=4) as live:
        for record in stream_samples(cid, interval_s,
                                     sidecar_name=f"psi-dash-{cid[:12]}"):
            if record["type"] == "end":
                console.print(f"stream ended: {record.get('reason')}")
                break
            if record["type"] != "sample":
                continue
            proc = run_docker("inspect", "-f", "{{.State.Status}}", container,
                              check=False)
            state = proc.stdout.strip() if proc.returncode == 0 else "gone"
            live.update(build_view(record, previous, state,
                                   time.monotonic() - start))
            previous = record
    return 0
