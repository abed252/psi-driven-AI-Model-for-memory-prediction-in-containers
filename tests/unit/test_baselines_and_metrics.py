import numpy as np
import pandas as pd
import pytest

from psi_memory.models.baselines import heuristic_predict, persistence_predict
from psi_memory.models.metrics import evaluate, mae, rmse, underprediction_rate


def make_table():
    return pd.DataFrame({
        "workload": ["steady", "steady", "leak"],
        "hist_current_last": [30.0, 40.0, 100.0],
        "hist_current_max": [35.0, 45.0, 120.0],
        "hist_current_p95": [34.0, 44.0, 118.0],
        "y_mib": [32.0, 50.0, 130.0],
    })


def test_persistence_is_last_value():
    assert persistence_predict(make_table()).tolist() == [30.0, 40.0, 100.0]


def test_heuristic_percentiles():
    table = make_table()
    assert heuristic_predict(table, 100).tolist() == [35.0, 45.0, 120.0]
    assert heuristic_predict(table, 95).tolist() == [34.0, 44.0, 118.0]
    with pytest.raises(ValueError):
        heuristic_predict(table, 50)


def test_metrics_hand_checked():
    y_true = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([12.0, 18.0, 30.0])
    assert mae(y_true, y_pred) == pytest.approx(4.0 / 3)
    assert rmse(y_true, y_pred) == pytest.approx(np.sqrt(8.0 / 3))
    # Underprediction: pred < true happened once (18 < 20).
    assert underprediction_rate(y_true, y_pred) == pytest.approx(1.0 / 3)


def test_evaluate_groups_by_workload():
    table = make_table()
    result = evaluate(table, persistence_predict(table))
    assert result["n"] == 3
    assert set(result["per_workload"]) == {"steady", "leak"}
    assert result["per_workload"]["leak"]["mae_mib"] == pytest.approx(30.0)
    assert result["per_workload"]["steady"]["mae_mib"] == pytest.approx(6.0)
