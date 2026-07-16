"""Prediction-quality metrics (operational metrics arrive in Phase 5)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def underprediction_rate(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Fraction of windows whose true future peak exceeded the prediction —
    the direction that causes OOM kills when the prediction sets the limit."""
    return float(np.mean(y_pred < y_true))


def evaluate(table: pd.DataFrame, y_pred: np.ndarray) -> dict:
    """Overall + per-workload metrics for predictions aligned to `table`."""
    y_true = table["y_mib"].to_numpy(dtype=float)
    result = {
        "n": int(len(y_true)),
        "mae_mib": mae(y_true, y_pred),
        "rmse_mib": rmse(y_true, y_pred),
        "underprediction_rate": underprediction_rate(y_true, y_pred),
        "per_workload": {},
    }
    for workload, group_index in table.groupby("workload").groups.items():
        indexer = table.index.get_indexer(group_index)
        result["per_workload"][workload] = {
            "n": int(len(indexer)),
            "mae_mib": mae(y_true[indexer], y_pred[indexer]),
            "rmse_mib": rmse(y_true[indexer], y_pred[indexer]),
        }
    return result
