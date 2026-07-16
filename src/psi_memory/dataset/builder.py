"""Dataset builder: immutable raw runs -> reproducible processed dataset.

Output directory layout (data/processed/<name>/):
  tabular.csv        windowed aggregate features + baselines + y_mib + keys
  sequences.npz      X (n, H, d) float32, y, run_ids, end_t, signal names
  splits.json        run-level split manifest (seed, fractions, assignment)
  dataset.json       full provenance: source runs, schema, target definition,
                     window config, code version, counts
  data_quality.json  gate report (pipeline fails on critical gate failures)
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import yaml

import psi_memory
from psi_memory.dataset.features import AGGREGATES, windows_to_table
from psi_memory.dataset.loader import discover_runs, load_run
from psi_memory.dataset.quality import check_runs, check_windows
from psi_memory.dataset.signals import ALL_SIGNALS, NO_PSI_SIGNALS, PSI_SIGNALS, compute_signals
from psi_memory.dataset.splits import assign_splits, save_manifest
from psi_memory.dataset.windows import WindowConfig, build_windows

log = logging.getLogger(__name__)


def code_version() -> dict:
    version = {"psi_memory": psi_memory.__version__}
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10)
        if proc.returncode == 0:
            version["git_commit"] = proc.stdout.strip()
    except OSError:
        pass
    return version


def load_dataset_config(path: Path) -> dict:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("window", "splits"):
        if key not in config:
            raise ValueError(f"{path}: missing '{key}' section")
    return config


def build_dataset(raw_dir: Path, out_dir: Path, config: dict,
                  run_ids: list[str] | None = None) -> bool:
    """Build a processed dataset; returns True when all critical gates pass."""
    window_cfg = WindowConfig(**config["window"])
    split_cfg = config["splits"]
    out_dir.mkdir(parents=True, exist_ok=True)

    run_dirs = discover_runs(raw_dir, run_ids)
    runs = [load_run(d) for d in run_dirs]
    log.info("loaded %d runs from %s", len(runs), raw_dir)

    report = check_runs(runs, window_cfg.interval_s, window_cfg.max_gap_factor)

    window_sets, per_run_counts = [], {}
    for run in runs:
        ws = build_windows(run.run_id, run.workload, compute_signals(run),
                           window_cfg)
        per_run_counts[run.run_id] = {"windows": len(ws.y_mib), **ws.discarded}
        window_sets.append(ws)
        log.info("run %s: %d windows (discarded: %s)", run.run_id,
                 len(ws.y_mib), ws.discarded)

    table = windows_to_table(window_sets, window_cfg.interval_s)

    assignment = assign_splits([(r.run_id, r.workload) for r in runs
                                if per_run_counts[r.run_id]["windows"] > 0],
                               split_cfg["fractions"], split_cfg["seed"])
    check_windows(table, assignment, report)

    (out_dir / "data_quality.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    if not report.ok:
        log.error("critical data-quality gates FAILED — dataset not written")
        return False

    run_split = {rid: split for split, rids in assignment.items() for rid in rids}
    table["split"] = table["run_id"].map(run_split)
    table.to_csv(out_dir / "tabular.csv", index=False)

    np.savez_compressed(
        out_dir / "sequences.npz",
        X=np.concatenate([ws.sequences for ws in window_sets if len(ws.y_mib)]),
        y=np.concatenate([ws.y_mib for ws in window_sets if len(ws.y_mib)]),
        run_id=np.concatenate([np.full(len(ws.y_mib), ws.run_id)
                               for ws in window_sets if len(ws.y_mib)]),
        end_t=np.concatenate([ws.end_t for ws in window_sets if len(ws.y_mib)]),
        signals=np.array(ALL_SIGNALS),
    )
    save_manifest(assignment, split_cfg["seed"], split_cfg["fractions"],
                  out_dir / "splits.json")

    dataset_meta = {
        "name": out_dir.name,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "raw_dir": str(raw_dir),
        "source_runs": {r.run_id: {"workload": r.workload,
                                   "env_validation_id": r.meta.get("env_validation_id"),
                                   "image_digest": r.meta.get("image_digest"),
                                   **per_run_counts[r.run_id]}
                        for r in runs},
        "target": ("max(memory.current) [MiB] over samples strictly after the "
                   "window-end time, within horizon_s"),
        "window_config": asdict(window_cfg),
        "feature_schema": {"no_psi_signals": NO_PSI_SIGNALS,
                           "psi_signals": PSI_SIGNALS,
                           "aggregates": AGGREGATES,
                           "baseline_columns": ["hist_current_max",
                                                "hist_current_p95",
                                                "hist_current_last"]},
        "splits": assignment,
        "counts": {split: int((table["split"] == split).sum())
                   for split in ("train", "val", "test")},
        "code_version": code_version(),
        "config": config,
    }
    (out_dir / "dataset.json").write_text(json.dumps(dataset_meta, indent=2),
                                          encoding="utf-8")
    log.info("dataset %s: %s windows (train/val/test %s)", out_dir.name,
             len(table), dataset_meta["counts"])
    return True
