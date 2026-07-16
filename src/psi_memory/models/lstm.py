"""LSTM sequence regressor (Phase 3).

Contract with the classical pipeline (execution spec):
- consumes the SAME processed dataset: sequences.npz windows, splits.json
  run-level assignment, dataset.json schema — same target, same splits;
- with_psi / no_psi variants differ only in which signal columns of the
  stored window tensor are fed to the network;
- per-signal normalization (and target normalization) fitted on the
  training split only;
- reproducible initialization from a derived seed; CPU-compatible;
- early stopping on validation loss with best-weights checkpointing;
- the test split is evaluated only when the caller passes include_test.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from psi_memory.common.seed import derive_seed, seed_everything
from psi_memory.models import baselines, metrics

log = logging.getLogger(__name__)

DEFAULTS = {
    "hidden_size": 64,
    "num_layers": 1,
    "dropout": 0.0,
    "learning_rate": 1e-3,
    "batch_size": 64,
    "max_epochs": 200,
    "patience": 15,
    "min_delta": 1e-4,
    "device": "cpu",
}


@dataclass
class SequenceSplits:
    """Window tensors grouped by split, with per-window bookkeeping."""
    signal_names: list[str]
    X: dict[str, np.ndarray]        # split -> (n, H, d_variant)
    y: dict[str, np.ndarray]        # split -> (n,)
    frame: dict[str, pd.DataFrame]  # split -> columns run_id, workload,
                                    #          y_mib, hist_current_last


def variant_signal_indices(all_signals: list[str], schema: dict,
                           variant: str) -> tuple[list[int], list[str]]:
    wanted = list(schema["no_psi_signals"])
    if variant == "with_psi":
        wanted += list(schema["psi_signals"])
    missing = [s for s in wanted if s not in all_signals]
    if missing:
        raise ValueError(f"dataset lacks signals {missing}")
    indices = [all_signals.index(s) for s in wanted]
    return indices, wanted


def load_sequences(dataset_dir: Path, variant: str) -> SequenceSplits:
    meta = json.loads((dataset_dir / "dataset.json").read_text(encoding="utf-8"))
    arrays = np.load(dataset_dir / "sequences.npz", allow_pickle=False)
    all_signals = [str(s) for s in arrays["signals"]]
    indices, names = variant_signal_indices(all_signals,
                                            meta["feature_schema"], variant)

    run_split = {run_id: split
                 for split, run_ids in meta["splits"].items()
                 for run_id in run_ids}
    run_workload = {run_id: info["workload"]
                    for run_id, info in meta["source_runs"].items()}
    window_runs = [str(r) for r in arrays["run_id"]]
    window_splits = np.array([run_split.get(r, "") for r in window_runs])

    X_full = arrays["X"][:, :, indices]
    y_full = arrays["y"].astype(np.float32)
    current_index = all_signals.index("current_mib")
    last_current = arrays["X"][:, -1, current_index].astype(float)

    result = SequenceSplits(signal_names=names, X={}, y={}, frame={})
    for split in ("train", "val", "test"):
        mask = window_splits == split
        if not mask.any():
            raise ValueError(f"split {split!r} has no windows")
        result.X[split] = X_full[mask]
        result.y[split] = y_full[mask]
        result.frame[split] = pd.DataFrame({
            "run_id": [r for r, m in zip(window_runs, mask) if m],
            "workload": [run_workload[r] for r, m in zip(window_runs, mask) if m],
            "y_mib": y_full[mask].astype(float),
            "hist_current_last": last_current[mask],
        })
    return result


class Normalizer:
    """Per-signal (and target) standardization, fitted on train only."""

    def __init__(self, X_train: np.ndarray, y_train: np.ndarray):
        self.mean = X_train.mean(axis=(0, 1))
        self.std = np.maximum(X_train.std(axis=(0, 1)), 1e-6)
        self.y_mean = float(y_train.mean())
        self.y_std = max(float(y_train.std()), 1e-6)

    def transform(self, X: np.ndarray) -> np.ndarray:
        return ((X - self.mean) / self.std).astype(np.float32)

    def transform_y(self, y: np.ndarray) -> np.ndarray:
        return ((y - self.y_mean) / self.y_std).astype(np.float32)

    def invert_y(self, y_norm: np.ndarray) -> np.ndarray:
        return y_norm * self.y_std + self.y_mean

    def state(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist(),
                "y_mean": self.y_mean, "y_std": self.y_std}


def build_model(n_signals: int, config: dict):
    import torch.nn as nn

    hidden = int(config["hidden_size"])
    layers = int(config["num_layers"])

    class LSTMRegressor(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=n_signals, hidden_size=hidden, num_layers=layers,
                batch_first=True,
                dropout=float(config["dropout"]) if layers > 1 else 0.0,
            )
            self.head = nn.Sequential(
                nn.Linear(hidden, hidden // 2), nn.ReLU(),
                nn.Linear(hidden // 2, 1),
            )

        def forward(self, x):
            output, _ = self.lstm(x)
            return self.head(output[:, -1, :]).squeeze(-1)

    return LSTMRegressor()


def train_lstm(dataset_dir: Path, variant: str, config: dict,
               models_dir: Path, include_test: bool = False) -> dict:
    import torch
    from torch.utils.data import DataLoader, TensorDataset

    cfg = {**DEFAULTS, **config.get("lstm", {})}
    seed = derive_seed(int(config.get("seed", 42)), "lstm", variant) % 2**31
    seed_everything(seed)

    data = load_sequences(dataset_dir, variant)
    normalizer = Normalizer(data.X["train"], data.y["train"])
    device = torch.device(cfg["device"])
    model = build_model(len(data.signal_names), cfg).to(device)

    def tensors(split: str) -> TensorDataset:
        return TensorDataset(
            torch.from_numpy(normalizer.transform(data.X[split])),
            torch.from_numpy(normalizer.transform_y(data.y[split])),
        )

    generator = torch.Generator().manual_seed(seed)
    train_loader = DataLoader(tensors("train"), batch_size=int(cfg["batch_size"]),
                              shuffle=True, generator=generator, num_workers=0)
    val_X = torch.from_numpy(normalizer.transform(data.X["val"])).to(device)
    val_y = torch.from_numpy(normalizer.transform_y(data.y["val"])).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=float(cfg["learning_rate"]))
    loss_fn = torch.nn.MSELoss()
    history: list[dict] = []
    best_val, best_state, bad_epochs = float("inf"), None, 0

    for epoch in range(int(cfg["max_epochs"])):
        model.train()
        train_loss_sum, batches = 0.0, 0
        for batch_X, batch_y in train_loader:
            optimizer.zero_grad()
            loss = loss_fn(model(batch_X.to(device)), batch_y.to(device))
            loss.backward()
            optimizer.step()
            train_loss_sum += float(loss.detach())
            batches += 1
        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(val_X), val_y))
        history.append({"epoch": epoch, "train_loss": train_loss_sum / batches,
                        "val_loss": val_loss})
        log.info("lstm/%s epoch %d: train %.5f val %.5f", variant, epoch,
                 history[-1]["train_loss"], val_loss)
        if val_loss < best_val - float(cfg["min_delta"]):
            best_val, bad_epochs = val_loss, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad_epochs += 1
            if bad_epochs >= int(cfg["patience"]):
                log.info("lstm/%s early stop at epoch %d (best val %.5f)",
                         variant, epoch, best_val)
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    def predict(split: str) -> np.ndarray:
        model.eval()
        with torch.no_grad():
            X = torch.from_numpy(normalizer.transform(data.X[split])).to(device)
            return normalizer.invert_y(model(X).cpu().numpy())

    result = {
        "model": "lstm", "variant": variant, "seed": seed,
        "params": {k: cfg[k] for k in ("hidden_size", "num_layers", "dropout",
                                       "learning_rate", "batch_size",
                                       "max_epochs", "patience")},
        "dataset": dataset_dir.name,
        "n_signals": len(data.signal_names),
        "epochs_trained": len(history),
        "best_val_loss": best_val,
        "val": metrics.evaluate(data.frame["val"], predict("val")),
        "val_persistence": metrics.evaluate(
            data.frame["val"], baselines.persistence_predict(data.frame["val"])),
    }
    if include_test:
        result["test"] = metrics.evaluate(data.frame["test"], predict("test"))
        result["test_persistence"] = metrics.evaluate(
            data.frame["test"],
            baselines.persistence_predict(data.frame["test"]))

    models_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = models_dir / f"{dataset_dir.name}__lstm__{variant}.pt"
    torch.save({
        "state_dict": model.state_dict(),
        "normalizer": normalizer.state(),
        "signal_names": data.signal_names,
        "config": cfg, "seed": seed, "variant": variant,
        "loss_history": history,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, artifact_path)
    result["artifact"] = str(artifact_path)
    log.info("lstm/%s: val MAE %.2f MiB (persistence %.2f), %d epochs",
             variant, result["val"]["mae_mib"],
             result["val_persistence"]["mae_mib"], len(history))
    return result
