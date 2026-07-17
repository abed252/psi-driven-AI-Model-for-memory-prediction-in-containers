"""Data-quality gates: refuse to build datasets from bad collections.

Critical failures stop the pipeline (exit nonzero); warnings are recorded.
The report is written next to the processed dataset.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from psi_memory.dataset.loader import RunFrame

log = logging.getLogger(__name__)

PRESSURE_WORKLOADS = ("leak", "bursty", "mixed")


@dataclass
class QualityReport:
    checks: list[dict] = field(default_factory=list)

    def add(self, name: str, level: str, passed: bool, details: str) -> None:
        assert level in ("critical", "warning")
        self.checks.append({"name": name, "level": level,
                            "passed": bool(passed), "details": details})
        if not passed:
            (log.error if level == "critical" else log.warning)(
                "quality %s [%s]: %s", name, level, details)

    @property
    def ok(self) -> bool:
        return not any(c["level"] == "critical" and not c["passed"]
                       for c in self.checks)

    def to_dict(self) -> dict:
        return {"overall": "pass" if self.ok else "fail", "checks": self.checks}


def check_runs(runs: list[RunFrame], interval_s: float,
               max_gap_factor: float) -> QualityReport:
    """Pre-windowing gates on the loaded raw runs."""
    report = QualityReport()
    report.add("runs_present", "critical", len(runs) > 0, f"{len(runs)} runs")
    if not runs:
        return report

    ids = [r.run_id for r in runs]
    report.add("unique_run_ids", "critical", len(set(ids)) == len(ids),
               "run IDs are unique" if len(set(ids)) == len(ids)
               else f"duplicates: {sorted({i for i in ids if ids.count(i) > 1})}")

    worst_gap = 0.0
    for run in runs:
        gaps = run.df["t"].diff().dropna()
        if len(gaps):
            worst_gap = max(worst_gap, float(gaps.max()))
    tolerance = max_gap_factor * interval_s
    report.add("sampling_gaps", "warning", worst_gap <= tolerance,
               f"worst gap {worst_gap:.2f}s (tolerance {tolerance:.2f}s; "
               "windows crossing bad gaps are discarded)")

    psi_present = [not r.df["psi_some_avg10"].isna().all() for r in runs]
    report.add("psi_not_universally_missing", "critical", any(psi_present),
               f"{sum(psi_present)}/{len(runs)} runs have PSI data")

    pressure_runs = [r for r in runs if r.workload in PRESSURE_WORKLOADS]
    if pressure_runs:
        peaks = {r.run_id: float(np.nanmax([r.df["psi_some_avg10"].max(), 0.0]))
                 for r in pressure_runs}
        any_pressure = any(v > 0 for v in peaks.values())
        report.add("pressure_workloads_show_psi", "critical", any_pressure,
                   f"peak some.avg10 per pressure run: "
                   f"{ {k: round(v, 2) for k, v in peaks.items()} }")
        quiet_runs = [r for r in runs if r.workload not in PRESSURE_WORKLOADS]
        report.add("mixed_pressure_states", "critical",
                   bool(quiet_runs) and any_pressure,
                   f"{len(pressure_runs)} pressured + {len(quiet_runs)} quiet runs")
    else:
        report.add("pressure_workloads_show_psi", "warning", False,
                   "no leak/bursty runs in this collection")

    for run in runs:
        if run.meta.get("oom_observed") and run.meta.get("exit_code") == 0:
            report.add(f"oom_consistency:{run.run_id}", "warning", False,
                       "oom_observed but exit_code 0 — check interpretation")
    return report


def check_windows(table: pd.DataFrame,
                  assignment: dict[str, list[str]],
                  report: QualityReport) -> QualityReport:
    """Post-windowing gates on the assembled dataset."""
    y = table["y_mib"]
    report.add("target_nontrivial", "critical", float(y.std()) > 1.0,
               f"y std {y.std():.2f} MiB over {len(y)} windows "
               f"(range {y.min():.1f}..{y.max():.1f})")

    run_split = {run_id: split for split, run_ids in assignment.items()
                 for run_id in run_ids}
    window_splits = table["run_id"].map(run_split)
    for split in ("train", "val", "test"):
        count = int((window_splits == split).sum())
        report.add(f"split_nonempty:{split}", "critical" if split == "train"
                   else "warning", count > 0, f"{count} windows")
    unassigned = int(window_splits.isna().sum())
    report.add("all_windows_assigned", "critical", unassigned == 0,
               f"{unassigned} windows from unassigned runs")
    return report
