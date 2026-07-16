"""Sliding windows and future-peak labels — the correctness core.

For a window of H samples ending at time t_end:
  target y = max(memory.current) over samples with t strictly greater than
  t_end and t <= t_end + horizon_s.

Hard rules (execution spec):
- the sample at t_end is never part of the target;
- windows are discarded when the run does not extend to t_end + horizon_s
  (incomplete future) or when a sampling gap larger than
  max_gap_factor * interval_s touches the window or its horizon;
- windows never span runs (this module only ever sees one run at a time).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from psi_memory.dataset.signals import ALL_SIGNALS


@dataclass(frozen=True)
class WindowConfig:
    history_samples: int = 30       # H
    horizon_s: float = 30.0         # prediction horizon (seconds)
    interval_s: float = 1.0         # nominal sampling interval
    max_gap_factor: float = 2.5     # gap tolerance, in units of interval_s
    stride: int = 1                 # a window every `stride` samples
    min_horizon_samples: int = 20   # horizon must contain at least this many


@dataclass
class WindowSet:
    """All valid windows of one run."""
    run_id: str
    workload: str
    sequences: np.ndarray           # (n, H, len(ALL_SIGNALS)) float32
    y_mib: np.ndarray               # (n,) future peak of current_mib
    end_t: np.ndarray               # (n,) window-end time (s from run start)
    hist_current_max: np.ndarray    # (n,) baselines: max over history window
    hist_current_p95: np.ndarray
    hist_current_last: np.ndarray
    discarded: dict = field(default_factory=dict)


def build_windows(run_id: str, workload: str, signals: pd.DataFrame,
                  cfg: WindowConfig) -> WindowSet:
    t = signals["t"].to_numpy(dtype=float)
    current = signals["current_mib"].to_numpy(dtype=float)
    matrix = signals[ALL_SIGNALS].to_numpy(dtype=np.float32)
    n = len(t)
    H = cfg.history_samples
    max_gap = cfg.max_gap_factor * cfg.interval_s
    gaps = np.diff(t)

    sequences, ys, end_ts = [], [], []
    hist_max, hist_p95, hist_last = [], [], []
    discarded = {"incomplete_horizon": 0, "gap": 0, "sparse_horizon": 0,
                 "nan_features": 0}

    for end in range(H - 1, n, cfg.stride):
        t_end = t[end]
        horizon_end_t = t_end + cfg.horizon_s
        # Complete-future requirement: the run must reach the horizon's end.
        if t[-1] < horizon_end_t:
            discarded["incomplete_horizon"] += 1
            continue
        # Strictly after t_end, inclusive of horizon end.
        horizon_mask = (t > t_end) & (t <= horizon_end_t)
        horizon_count = int(horizon_mask.sum())
        if horizon_count < cfg.min_horizon_samples:
            discarded["sparse_horizon"] += 1
            continue
        # Gap tolerance across window + horizon.
        last_horizon_index = np.flatnonzero(horizon_mask)[-1]
        span = gaps[end - H + 1 : last_horizon_index]
        if span.size and span.max() > max_gap:
            discarded["gap"] += 1
            continue
        window = matrix[end - H + 1 : end + 1]
        if np.isnan(window).any():
            discarded["nan_features"] += 1
            continue

        sequences.append(window)
        ys.append(current[horizon_mask].max())
        end_ts.append(t_end)
        hist_window = current[end - H + 1 : end + 1]
        hist_max.append(hist_window.max())
        hist_p95.append(np.percentile(hist_window, 95))
        hist_last.append(hist_window[-1])

    return WindowSet(
        run_id=run_id, workload=workload,
        sequences=(np.stack(sequences).astype(np.float32) if sequences
                   else np.empty((0, H, len(ALL_SIGNALS)), dtype=np.float32)),
        y_mib=np.asarray(ys, dtype=float),
        end_t=np.asarray(end_ts, dtype=float),
        hist_current_max=np.asarray(hist_max, dtype=float),
        hist_current_p95=np.asarray(hist_p95, dtype=float),
        hist_current_last=np.asarray(hist_last, dtype=float),
        discarded=discarded,
    )
