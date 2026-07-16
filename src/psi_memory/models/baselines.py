"""Non-learned baselines.

- Persistence: predicted future peak = memory.current at the window's end.
  The floor every model must beat (proposal §2).
- Autopilot-style percentile heuristic: predicted future peak = a high
  percentile (default 95) or the maximum of usage over the history window.
  Named "Autopilot-style" deliberately: it mirrors the moving-window
  peak/percentile idea of Google Autopilot's rule-based recommender, not the
  published system itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def persistence_predict(table: pd.DataFrame) -> np.ndarray:
    return table["hist_current_last"].to_numpy(dtype=float)


def heuristic_predict(table: pd.DataFrame, percentile: int = 95) -> np.ndarray:
    if percentile >= 100:
        return table["hist_current_max"].to_numpy(dtype=float)
    if percentile == 95:
        return table["hist_current_p95"].to_numpy(dtype=float)
    raise ValueError("heuristic supports percentile 95 or 100 "
                     "(stored at dataset build time)")
