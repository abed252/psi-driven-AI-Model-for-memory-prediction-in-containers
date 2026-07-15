"""PSI calibration: verify the collected signals behave as the proposal predicts.

Spec requirement: do not claim PSI is useful because the file exists — show
that PSI stays ~0 for steady/file-cache workloads, rises for a constrained
anonymous leak, oscillates for bursty batches, and that OOM events are
detected. Produces per-run plots and a machine-readable JSON report.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from psi_memory.common.units import MIB

log = logging.getLogger(__name__)

# Palette (dataviz skill reference palette, light surface)
COLOR_MEMORY = "#2a78d6"   # categorical slot 1 (blue)
COLOR_SWAP = "#1baf7a"     # slot 2 (aqua)
COLOR_PSI_SOME = "#4a3aa7" # slot 5 (violet)
COLOR_PSI_FULL = "#e34948" # slot 6 (red)
COLOR_LIMIT = "#52514e"    # secondary text/reference
COLOR_OOM = "#d03b3b"      # status: critical

PSI_QUIET_MAX_AVG10 = 1.0      # % — "near zero"
PSI_LOW_MAX_AVG10 = 5.0        # % — "low" (reclaimable cache may tick slightly)
PSI_PRESSURE_MIN_AVG10 = 5.0   # % — genuine pressure must exceed this
QUIET_STALL_BUDGET_US = 200_000     # ≤0.2 s cumulative stall counts as quiet
PRESSURE_STALL_MIN_US = 1_000_000   # ≥1 s cumulative stall counts as pressure


@dataclass
class RunData:
    run_id: str
    workload: str
    meta: dict
    t: list[float] = field(default_factory=list)            # elapsed seconds
    current_mib: list[float] = field(default_factory=list)
    swap_mib: list[float] = field(default_factory=list)
    some_avg10: list[float] = field(default_factory=list)
    full_avg10: list[float] = field(default_factory=list)
    some_total_us: list[int] = field(default_factory=list)
    oom_kill_t: list[float] = field(default_factory=list)   # times of new oom_kills
    limit_mib: float | None = None


def load_run(run_dir: Path) -> RunData:
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    run = RunData(run_id=meta["run_id"], workload=meta["workload"], meta=meta)
    t0 = None
    prev_oom_kills = 0
    with open(run_dir / "samples.jsonl", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if record.get("type") != "sample":
                continue
            if t0 is None:
                t0 = record["mono"]
            elapsed = record["mono"] - t0
            run.t.append(elapsed)
            run.current_mib.append((record.get("current") or 0) / MIB)
            swap = record.get("swap_current")
            run.swap_mib.append(swap / MIB if isinstance(swap, int) else 0.0)
            psi = record.get("pressure") or {}
            run.some_avg10.append(psi.get("some", {}).get("avg10", 0.0))
            run.full_avg10.append(psi.get("full", {}).get("avg10", 0.0))
            run.some_total_us.append(psi.get("some", {}).get("total", 0))
            limit = record.get("max")
            if isinstance(limit, int):
                run.limit_mib = limit / MIB
            oom_kills = (record.get("events") or {}).get("oom_kill", 0)
            if oom_kills > prev_oom_kills:
                run.oom_kill_t.append(elapsed)
                prev_oom_kills = oom_kills
    return run


@dataclass
class Check:
    name: str
    passed: bool
    details: str


def _stall_delta_us(run: RunData) -> int:
    return (run.some_total_us[-1] - run.some_total_us[0]) if run.some_total_us else 0


def _direction_changes(series: list[float], threshold: float) -> int:
    """Count up/down swings larger than `threshold` (oscillation detector)."""
    changes, direction, reference = 0, 0, series[0] if series else 0.0
    for value in series[1:]:
        if value > reference + threshold:
            if direction == -1:
                changes += 1
            direction, reference = 1, value
        elif value < reference - threshold:
            if direction == 1:
                changes += 1
            direction, reference = -1, value
    return changes


def check_run(run: RunData) -> list[Check]:
    """Workload-specific expected-signature checks (proposal §3 table)."""
    checks = [Check("has_samples", len(run.t) >= 10, f"{len(run.t)} samples")]
    peak_psi = max(run.some_avg10, default=0.0)
    stall_us = _stall_delta_us(run)
    oom = bool(run.meta.get("oom_observed"))

    if run.workload == "steady":
        checks.append(Check("psi_near_zero", peak_psi < PSI_QUIET_MAX_AVG10
                            and stall_us < QUIET_STALL_BUDGET_US,
                            f"peak some.avg10={peak_psi:.2f}%, stall={stall_us}us"))
        checks.append(Check("no_oom", not oom, f"oom_observed={oom}"))
    elif run.workload == "file_burst":
        peak_ratio = (max(run.current_mib) / run.limit_mib
                      if run.limit_mib else 0.0)
        checks.append(Check("usage_high", peak_ratio > 0.5,
                            f"peak usage {peak_ratio * 100:.0f}% of limit"))
        checks.append(Check("psi_low", peak_psi < PSI_LOW_MAX_AVG10,
                            f"peak some.avg10={peak_psi:.2f}%"))
        checks.append(Check("no_oom", not oom, f"oom_observed={oom}"))
    elif run.workload == "leak":
        checks.append(Check("psi_rises", peak_psi >= PSI_PRESSURE_MIN_AVG10
                            and stall_us >= PRESSURE_STALL_MIN_US,
                            f"peak some.avg10={peak_psi:.2f}%, stall={stall_us}us"))
        checks.append(Check("oom_detected", oom,
                            f"oom_observed={oom} (flag={run.meta.get('oom_killed_flag')}, "
                            f"events at t={[round(t) for t in run.oom_kill_t]})"))
    elif run.workload == "bursty":
        swings = _direction_changes(run.current_mib,
                                    threshold=max(run.current_mib, default=0) * 0.25)
        checks.append(Check("usage_oscillates", swings >= 2, f"{swings} large swings"))
        checks.append(Check("psi_active", peak_psi >= PSI_PRESSURE_MIN_AVG10
                            or stall_us >= PRESSURE_STALL_MIN_US,
                            f"peak some.avg10={peak_psi:.2f}%, stall={stall_us}us"))
    elif run.workload == "trace_replay":
        target = _replay_targets(run)
        corr = (statistics.correlation(run.current_mib, target)
                if len(set(target)) > 1 and len(set(run.current_mib)) > 1 else 0.0)
        checks.append(Check("tracks_trace", corr >= 0.6, f"correlation={corr:.3f}"))
    return checks


def _replay_targets(run: RunData) -> list[float]:
    """Expected MiB target at each sample time, from the replayed trace."""
    import importlib.util
    import sys

    script = Path("workloads") / "trace_replay.py"
    # The script imports its sibling wl_common, exactly as inside the image.
    if str(script.parent.resolve()) not in sys.path:
        sys.path.insert(0, str(script.parent.resolve()))
    spec = importlib.util.spec_from_file_location("trace_replay", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    trace_file = run.meta["params"].get("trace_file", "workloads/traces/example_trace.csv")
    local = Path(trace_file.replace("/app/", "workloads/"))
    points = module.load_trace(str(local))
    scale = float(run.meta["params"].get("scale", 1.0))
    time_scale = float(run.meta["params"].get("time_scale", 1.0))
    return [module.target_at(points, t / time_scale) * scale for t in run.t]


def plot_run(run: RunData, out_path: Path) -> None:
    """Two stacked panels sharing time: memory (top) and PSI (bottom)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax_mem, ax_psi) = plt.subplots(
        2, 1, sharex=True, figsize=(9, 5.5),
        gridspec_kw={"height_ratios": [3, 2]},
    )
    fig.suptitle(f"{run.run_id}  ({run.workload})", fontsize=11)

    ax_mem.plot(run.t, run.current_mib, color=COLOR_MEMORY, linewidth=2,
                label="memory.current")
    if any(run.swap_mib):
        ax_mem.plot(run.t, run.swap_mib, color=COLOR_SWAP, linewidth=2,
                    label="swap.current")
    if run.limit_mib:
        ax_mem.axhline(run.limit_mib, color=COLOR_LIMIT, linewidth=1,
                       linestyle="--", label="memory.max")
    ax_mem.set_ylabel("MiB")
    ax_mem.legend(loc="best", fontsize=8, framealpha=0.9)

    # `some` is drawn wider beneath `full`: in single-process containers the
    # two curves coincide and the thinner red line would otherwise hide it.
    ax_psi.plot(run.t, run.some_avg10, color=COLOR_PSI_SOME, linewidth=3.5,
                label="PSI some avg10")
    ax_psi.plot(run.t, run.full_avg10, color=COLOR_PSI_FULL, linewidth=1.5,
                label="PSI full avg10")
    ax_psi.set_ylabel("stalled %")
    ax_psi.set_xlabel("elapsed (s)")
    ax_psi.set_ylim(bottom=0)
    ax_psi.legend(loc="best", fontsize=8, framealpha=0.9)

    for ax in (ax_mem, ax_psi):
        ax.grid(True, color="#e6e5e0", linewidth=0.5)
        ax.set_axisbelow(True)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for t_oom in run.oom_kill_t:
            ax.axvline(t_oom, color=COLOR_OOM, linewidth=1, linestyle=":")
    if run.oom_kill_t:
        ax_mem.text(run.oom_kill_t[0], ax_mem.get_ylim()[1] * 0.95, " OOM kill",
                    color=COLOR_OOM, fontsize=8, va="top")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def calibrate(data_dir: Path, batch_manifest: Path | None,
              plots_dir: Path, reports_dir: Path) -> int:
    if batch_manifest is None:
        manifests = sorted(data_dir.glob("batch_*.json"))
        if not manifests:
            log.error("no batch manifest found in %s — run psi-run first", data_dir)
            return 1
        batch_manifest = manifests[-1]
    run_ids = json.loads(batch_manifest.read_text(encoding="utf-8"))["run_ids"]

    results, all_passed = [], True
    for run_id in run_ids:
        run = load_run(data_dir / run_id)
        checks = check_run(run)
        plot_path = plots_dir / f"{run_id}.png"
        plot_run(run, plot_path)
        passed = all(c.passed for c in checks)
        all_passed &= passed
        results.append({
            "run_id": run_id, "workload": run.workload, "passed": passed,
            "checks": [c.__dict__ for c in checks], "plot": str(plot_path),
            "peak_some_avg10": max(run.some_avg10, default=0.0),
            "stall_delta_us": _stall_delta_us(run),
            "oom_observed": bool(run.meta.get("oom_observed")),
        })
        status = "PASS" if passed else "FAIL"
        log.info("[%s] %s (%s): %s", status, run_id, run.workload,
                 "; ".join(f"{c.name}={'ok' if c.passed else 'FAIL'}" for c in checks))

    report = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "batch_manifest": str(batch_manifest),
        "overall_pass": all_passed,
        "runs": results,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"calibration_{time.strftime('%Y%m%d-%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("calibration report: %s (overall %s)", report_path,
             "PASS" if all_passed else "FAIL")
    return 0 if all_passed else 1
