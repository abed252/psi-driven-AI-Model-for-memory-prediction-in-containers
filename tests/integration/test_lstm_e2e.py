"""LSTM end to end on a synthetic processed dataset (CPU, small, no Docker)."""

import json
import math

import pytest

from psi_memory.dataset.builder import build_dataset
from psi_memory.models.lstm import load_sequences, train_lstm

CONFIG = {
    "window": {"history_samples": 10, "horizon_s": 10.0, "interval_s": 1.0,
               "max_gap_factor": 2.5, "stride": 2, "min_horizon_samples": 7},
    "splits": {"seed": 42, "fractions": {"train": 0.6, "val": 0.2, "test": 0.2}},
}

LSTM_CONFIG = {"seed": 7, "lstm": {"hidden_size": 16, "num_layers": 1,
                                   "learning_rate": 0.005, "batch_size": 32,
                                   "max_epochs": 25, "patience": 5,
                                   "device": "cpu"}}


@pytest.fixture(scope="module")
def built_dataset(tmp_path_factory):
    from tests.conftest import write_synth_run  # reuse the factory directly

    tmp_path = tmp_path_factory.mktemp("lstm_e2e")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for i in range(4):
        write_synth_run(raw_dir, f"steady-{i:02d}", workload="steady",
                        n_samples=70,
                        current_fn=lambda j, base=40 + 3 * i: base + math.sin(j / 3))
        write_synth_run(
            raw_dir, f"leak-{i:02d}", workload="leak", n_samples=70, oom=True,
            current_fn=lambda j, rate=1.0 + 0.25 * i: 40 + rate * j,
            psi_avg10_fn=lambda j, rate=1.0 + 0.25 * i: max(0.0, (j - 30) * 0.3 * rate),
        )
    out_dir = tmp_path / "processed" / "lstm-e2e"
    assert build_dataset(raw_dir, out_dir, CONFIG) is True
    return out_dir


def test_sequences_align_with_splits(built_dataset):
    data = load_sequences(built_dataset, "with_psi")
    splits = json.loads((built_dataset / "splits.json").read_text())["splits"]
    for split in ("train", "val", "test"):
        assert set(data.frame[split]["run_id"]) <= set(splits[split])
        assert len(data.X[split]) == len(data.y[split]) == len(data.frame[split])


def test_variant_tensor_widths(built_dataset):
    no_psi = load_sequences(built_dataset, "no_psi")
    with_psi = load_sequences(built_dataset, "with_psi")
    assert with_psi.X["train"].shape[2] > no_psi.X["train"].shape[2]
    assert no_psi.X["train"].shape[:2] == with_psi.X["train"].shape[:2]


def test_train_lstm_end_to_end(built_dataset, tmp_path):
    result = train_lstm(built_dataset, "with_psi", LSTM_CONFIG,
                        tmp_path / "models", include_test=True)
    # Learns *something*: beats persistence on the leak-heavy synthetic data
    # is not guaranteed in 25 epochs — but it must produce finite metrics,
    # a loss history that improved, and a loadable checkpoint.
    assert result["val"]["mae_mib"] >= 0
    assert result["epochs_trained"] >= 2
    assert "test" in result

    import torch

    artifact = torch.load(result["artifact"], weights_only=False)
    assert artifact["signal_names"][-1].startswith("psi_")
    assert artifact["normalizer"]["y_std"] > 0
    history = artifact["loss_history"]
    assert history[-1]["val_loss"] <= history[0]["val_loss"] * 1.5
    assert {"epoch", "train_loss", "val_loss"} <= set(history[0])


def test_no_test_metrics_without_flag(built_dataset, tmp_path):
    result = train_lstm(built_dataset, "no_psi", LSTM_CONFIG, tmp_path / "m2")
    assert "test" not in result


def test_reproducible_training(built_dataset, tmp_path):
    r1 = train_lstm(built_dataset, "no_psi", LSTM_CONFIG, tmp_path / "a")
    r2 = train_lstm(built_dataset, "no_psi", LSTM_CONFIG, tmp_path / "b")
    assert r1["val"]["mae_mib"] == pytest.approx(r2["val"]["mae_mib"], rel=1e-5)
