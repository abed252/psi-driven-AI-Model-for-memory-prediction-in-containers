"""Statistical helpers: bootstrap confidence intervals, seed aggregation."""

from __future__ import annotations

import numpy as np


def bootstrap_ci_mae(y_true, y_pred, n_boot: int = 2000, alpha: float = 0.05,
                     seed: int = 0) -> dict:
    """Percentile-bootstrap CI for the mean absolute error (windows resampled)."""
    errors = np.abs(np.asarray(y_true, dtype=float)
                    - np.asarray(y_pred, dtype=float))
    rng = np.random.default_rng(seed)
    n = len(errors)
    samples = rng.choice(errors, size=(n_boot, n), replace=True).mean(axis=1)
    lo, hi = np.percentile(samples, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {"mae_mib": float(errors.mean()), "ci_low": float(lo),
            "ci_high": float(hi), "n": int(n), "n_boot": n_boot,
            "alpha": alpha}


def across_seeds(values: list[float]) -> dict:
    """Mean/std/min/max across independent seeds."""
    arr = np.asarray(values, dtype=float)
    return {"mean": float(arr.mean()), "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
            "min": float(arr.min()), "max": float(arr.max()),
            "n_seeds": int(len(arr)), "values": [float(v) for v in arr]}


def normalized_mae(y_true, y_pred) -> float:
    """MAE divided by the mean true value — comparable across scales."""
    y_true = np.asarray(y_true, dtype=float)
    denominator = float(np.abs(y_true).mean())
    if denominator == 0:
        return float("nan")
    return float(np.abs(y_true - np.asarray(y_pred, dtype=float)).mean()
                 / denominator)
