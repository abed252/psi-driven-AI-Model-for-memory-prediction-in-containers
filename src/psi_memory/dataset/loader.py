"""Load raw runs (samples.jsonl + meta.json) into validated per-run frames.

Raw data is immutable input: this module only reads. Each run stays a
separate object end to end — runs are never merged or concatenated here,
which is the structural guarantee behind run-level splits.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

MIB = 1024 * 1024

# memory.stat fields carried into the dataset (memory information that a
# usage-only system would also have; PSI stays strictly separate).
STAT_FIELDS = ("anon", "file")


class RawDataError(ValueError):
    """Malformed raw run data — the pipeline must stop, not guess."""


@dataclass
class RunFrame:
    run_id: str
    workload: str
    meta: dict
    df: pd.DataFrame  # one row per sample, columns per _row() below


def _row(sample: dict) -> dict:
    psi = sample.get("pressure") or {}
    some, full = psi.get("some", {}), psi.get("full", {})
    events = sample.get("events") or {}
    stat = sample.get("stat") or {}
    limit = sample.get("max")
    high = sample.get("high")
    return {
        "mono": sample["mono"],
        "wall": sample["wall"],
        "current": sample.get("current"),
        # literal "max" = unlimited -> represented as NaN, never 0
        "limit": limit if isinstance(limit, int) else float("nan"),
        "high": high if isinstance(high, int) else float("nan"),
        "swap_current": sample.get("swap_current"),
        "psi_some_avg10": some.get("avg10"),
        "psi_some_avg60": some.get("avg60"),
        "psi_some_avg300": some.get("avg300"),
        "psi_some_total": some.get("total"),
        "psi_full_avg10": full.get("avg10"),
        "psi_full_avg60": full.get("avg60"),
        "psi_full_avg300": full.get("avg300"),
        "psi_full_total": full.get("total"),
        "ev_oom": events.get("oom"),
        "ev_oom_kill": events.get("oom_kill"),
        "ev_max": events.get("max"),
        "ev_high": events.get("high"),
        **{f"stat_{k}": stat.get(k) for k in STAT_FIELDS},
    }


def load_run(run_dir: Path) -> RunFrame:
    """Load one run directory; raises RawDataError on structural problems."""
    meta_path = run_dir / "meta.json"
    samples_path = run_dir / "samples.jsonl"
    if not meta_path.exists() or not samples_path.exists():
        raise RawDataError(f"{run_dir}: missing meta.json or samples.jsonl")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("run_id") != run_dir.name:
        raise RawDataError(
            f"{run_dir}: meta run_id {meta.get('run_id')!r} != directory name "
            "(possible mixed runs)"
        )

    rows = []
    with open(samples_path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as err:
                raise RawDataError(
                    f"{samples_path}:{line_number}: malformed JSON: {err}"
                ) from err
            if record.get("type") == "sample":
                rows.append(_row(record))
    if not rows:
        raise RawDataError(f"{run_dir}: no samples")

    df = pd.DataFrame(rows)
    if not df["mono"].is_monotonic_increasing:
        raise RawDataError(f"{run_dir}: non-monotonic timestamps")
    if df["current"].isna().any():
        raise RawDataError(f"{run_dir}: memory.current missing in some samples")
    df["t"] = df["mono"] - df["mono"].iloc[0]
    return RunFrame(run_id=meta["run_id"], workload=meta["workload"],
                    meta=meta, df=df)


def discover_runs(raw_dir: Path, run_ids: list[str] | None = None) -> list[Path]:
    """Run directories under raw_dir (all of them, or an explicit subset)."""
    if run_ids:
        dirs = [raw_dir / run_id for run_id in run_ids]
        missing = [d.name for d in dirs if not (d / "meta.json").exists()]
        if missing:
            raise RawDataError(f"requested runs not found in {raw_dir}: {missing}")
        return dirs
    return sorted(
        d for d in raw_dir.iterdir()
        if d.is_dir() and (d / "meta.json").exists()
    )
