"""Tabular window summaries for the classical models.

Every signal in a window is summarized by the same fixed aggregate set, so
the with-PSI feature matrix is exactly the without-PSI matrix plus the PSI
signals' columns — identical rows, identical non-PSI values (tested).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from psi_memory.dataset.signals import ALL_SIGNALS, NO_PSI_SIGNALS, PSI_SIGNALS
from psi_memory.dataset.windows import WindowSet

AGGREGATES = ["last", "mean", "max", "std", "slope", "delta"]


def feature_columns(with_psi: bool) -> list[str]:
    signals = NO_PSI_SIGNALS + (PSI_SIGNALS if with_psi else [])
    return [f"{signal}__{agg}" for signal in signals for agg in AGGREGATES]


def _aggregate(seq: np.ndarray, interval_s: float) -> np.ndarray:
    """(n, H, d) -> (n, d*len(AGGREGATES)) in AGGREGATES-per-signal order."""
    n, H, d = seq.shape
    t = np.arange(H, dtype=float) * interval_s
    t_centered = t - t.mean()
    denominator = (t_centered**2).sum()
    last = seq[:, -1, :]
    mean = seq.mean(axis=1)
    maximum = seq.max(axis=1)
    std = seq.std(axis=1)
    slope = np.einsum("h,nhd->nd", t_centered, seq) / denominator
    delta = seq[:, -1, :] - seq[:, 0, :]
    # -> (n, d, n_aggs) -> flatten with signal-major order to match columns
    stacked = np.stack([last, mean, maximum, std, slope, delta], axis=2)
    return stacked.reshape(n, d * len(AGGREGATES))


def windows_to_table(window_sets: list[WindowSet], interval_s: float) -> pd.DataFrame:
    """One tabular DataFrame for all runs' windows (rows keep their run_id)."""
    frames = []
    all_columns = [f"{s}__{a}" for s in ALL_SIGNALS for a in AGGREGATES]
    for ws in window_sets:
        if len(ws.y_mib) == 0:
            continue
        table = pd.DataFrame(_aggregate(ws.sequences, interval_s),
                             columns=all_columns)
        table.insert(0, "run_id", ws.run_id)
        table.insert(1, "workload", ws.workload)
        table.insert(2, "window_end_t", ws.end_t)
        table["hist_current_max"] = ws.hist_current_max
        table["hist_current_p95"] = ws.hist_current_p95
        table["hist_current_last"] = ws.hist_current_last
        table["y_mib"] = ws.y_mib
        frames.append(table)
    if not frames:
        raise ValueError("no windows produced by any run")
    return pd.concat(frames, ignore_index=True)
