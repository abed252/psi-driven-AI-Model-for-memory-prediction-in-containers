"""Leakage discipline inside training: train-only scaler, val-only eval,
test only behind the explicit flag, reproducible seeds."""

import numpy as np
import pandas as pd
import pytest

from psi_memory.dataset.features import feature_columns
from psi_memory.models.training import LoadedDataset, train_learned


def make_dataset(train_offset=0.0, val_offset=1000.0) -> LoadedDataset:
    """In-memory dataset whose val features live far from train features."""
    rng = np.random.default_rng(3)
    columns = feature_columns(with_psi=True)
    rows = []
    for split, offset, n_rows, workload in (
        ("train", train_offset, 60, "steady"),
        ("val", val_offset, 20, "steady"),
        ("test", val_offset, 20, "steady"),
    ):
        block = pd.DataFrame(rng.uniform(0, 10, (n_rows, len(columns))) + offset,
                             columns=columns)
        block["y_mib"] = rng.uniform(50, 100, n_rows)
        block["hist_current_last"] = block["y_mib"] - 5
        block["hist_current_max"] = block["y_mib"] - 2
        block["hist_current_p95"] = block["y_mib"] - 3
        block["run_id"] = f"{split}-run"
        block["workload"] = workload
        block["split"] = split
        rows.append(block)
    return LoadedDataset(name="synthetic", meta={"name": "synthetic"},
                         table=pd.concat(rows, ignore_index=True))


def test_scaler_fitted_on_train_only(tmp_path):
    dataset = make_dataset(train_offset=0.0, val_offset=1000.0)
    result = train_learned(dataset, "rf", "with_psi", {"seed": 1}, tmp_path)
    import joblib

    artifact = joblib.load(result["artifact"])
    train_features = dataset.split("train")[artifact["feature_names"]]
    # Scaler means must match TRAIN means (~5), not pooled means (~500+).
    np.testing.assert_allclose(artifact["scaler"].mean_,
                               train_features.mean(axis=0), rtol=1e-9)
    assert artifact["scaler"].mean_.max() < 100


def test_test_split_untouched_without_flag(tmp_path):
    result = train_learned(make_dataset(), "rf", "no_psi", {"seed": 1}, tmp_path)
    assert "test" not in result
    assert "val" in result and "val_persistence" in result


def test_test_split_evaluated_with_flag(tmp_path):
    result = train_learned(make_dataset(), "rf", "no_psi", {"seed": 1},
                           tmp_path, include_test=True)
    assert "test" in result and "test_persistence" in result


def test_reproducible_with_same_seed(tmp_path):
    dataset = make_dataset()
    r1 = train_learned(dataset, "rf", "with_psi", {"seed": 42}, tmp_path / "a")
    r2 = train_learned(dataset, "rf", "with_psi", {"seed": 42}, tmp_path / "b")
    assert r1["seed"] == r2["seed"]
    assert r1["val"]["mae_mib"] == pytest.approx(r2["val"]["mae_mib"], abs=1e-12)


def test_variants_differ_only_in_feature_count(tmp_path):
    dataset = make_dataset()
    with_psi = train_learned(dataset, "rf", "with_psi", {"seed": 42}, tmp_path)
    no_psi = train_learned(dataset, "rf", "no_psi", {"seed": 42}, tmp_path)
    assert with_psi["n_features"] > no_psi["n_features"]
    assert with_psi["val"]["n"] == no_psi["val"]["n"]  # identical rows
