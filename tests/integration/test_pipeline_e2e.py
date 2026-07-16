"""Raw -> processed -> trained models -> ablation, end to end on synthetic
raw runs. No Docker needed; exercises the same code paths as the real CLIs.
"""

import json
import math

import numpy as np
import pytest

from psi_memory.dataset.builder import build_dataset
from psi_memory.models.ablation import render_table, run_ablation
from psi_memory.models.training import load_dataset, train_learned

CONFIG = {
    "window": {"history_samples": 10, "horizon_s": 10.0, "interval_s": 1.0,
               "max_gap_factor": 2.5, "stride": 1, "min_horizon_samples": 7},
    "splits": {"seed": 42, "fractions": {"train": 0.6, "val": 0.2, "test": 0.2}},
}

MODELS_CONFIG = {"seed": 42, "heuristic": {"percentile": 95},
                 "rf": {"n_estimators": 30}, "xgb": {"n_estimators": 30}}


@pytest.fixture()
def built_dataset(synth_raw, tmp_path):
    # 4 runs x 2 workloads: leaky runs rise (with PSI), steady runs are flat.
    for i in range(4):
        synth_raw.add(f"steady-{i:02d}", workload="steady", n_samples=80,
                      current_fn=lambda j, base=40 + 4 * i: base + math.sin(j / 3))
        synth_raw.add(
            f"leak-{i:02d}", workload="leak", n_samples=80, oom=True,
            current_fn=lambda j, rate=1.0 + 0.2 * i: 40 + rate * j,
            psi_avg10_fn=lambda j, rate=1.0 + 0.2 * i: max(0.0, (j - 40) * 0.3 * rate),
        )
    out_dir = tmp_path / "processed" / "e2e"
    assert build_dataset(synth_raw.dir, out_dir, CONFIG) is True
    return out_dir


def test_dataset_artifacts_complete(built_dataset):
    for filename in ("tabular.csv", "sequences.npz", "splits.json",
                     "dataset.json", "data_quality.json"):
        assert (built_dataset / filename).exists(), filename

    meta = json.loads((built_dataset / "dataset.json").read_text())
    assert len(meta["source_runs"]) == 8
    assert meta["counts"]["train"] > 0 and meta["counts"]["val"] > 0
    assert meta["window_config"]["history_samples"] == 10
    assert "strictly after" in meta["target"]
    assert meta["code_version"]["psi_memory"]

    quality = json.loads((built_dataset / "data_quality.json").read_text())
    assert quality["overall"] == "pass"

    arrays = np.load(built_dataset / "sequences.npz", allow_pickle=False)
    assert arrays["X"].shape[1:] == (10, 16)  # H x n_signals
    assert len(arrays["X"]) == len(arrays["y"]) == len(arrays["run_id"])


def test_windows_respect_split_assignment(built_dataset):
    dataset = load_dataset(built_dataset)
    splits = json.loads((built_dataset / "splits.json").read_text())["splits"]
    for split_name, run_ids in splits.items():
        rows = dataset.table[dataset.table["split"] == split_name]
        assert set(rows["run_id"]) <= set(run_ids)


def test_rebuild_is_identical(synth_raw, tmp_path, built_dataset):
    out2 = tmp_path / "processed" / "e2e2"
    assert build_dataset(synth_raw.dir, out2, CONFIG) is True
    s1 = json.loads((built_dataset / "splits.json").read_text())
    s2 = json.loads((out2 / "splits.json").read_text())
    assert s1["splits"] == s2["splits"]
    a1 = np.load(built_dataset / "sequences.npz")
    a2 = np.load(out2 / "sequences.npz")
    np.testing.assert_array_equal(a1["y"], a2["y"])


def test_training_end_to_end(built_dataset, tmp_path):
    dataset = load_dataset(built_dataset)
    result = train_learned(dataset, "rf", "with_psi", MODELS_CONFIG,
                           tmp_path / "models")
    assert result["val"]["mae_mib"] >= 0
    assert result["feature_importances"]
    assert (tmp_path / "models").glob("*.joblib")


def test_ablation_end_to_end(built_dataset, tmp_path):
    report = run_ablation(built_dataset, MODELS_CONFIG, tmp_path / "models",
                          tmp_path / "metrics", include_test=True)
    names = [(r["model"], r["variant"]) for r in report["results"]]
    assert ("persistence", "n/a") in names and ("heuristic", "n/a") in names
    assert ("rf", "no_psi") in names and ("rf", "with_psi") in names
    assert ("xgb", "no_psi") in names and ("xgb", "with_psi") in names
    table = render_table(report)
    assert "persistence" in table and "with_psi" in table
    saved = list((tmp_path / "metrics").glob("ablation_*.json"))
    assert len(saved) == 1
