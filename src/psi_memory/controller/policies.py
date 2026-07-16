"""Controller decision policies.

Each policy inspects the rolling signal window and proposes a value (MiB)
for its target cgroup file. The safety gate and actuator are elsewhere:
policies are pure proposal logic.

- fixed: keep a constant memory.max (the do-nothing baseline).
- percentile: Autopilot-style — a high percentile of recent usage plus a
  safety margin, applied to memory.max.
- senpai: Senpai-style reactive PSI control of memory.high — squeeze while
  observed stall time stays under a target, back off when it exceeds it.
  (Named "-style": it mirrors the published mechanism, not the exact system.)
- learned: a trained model artifact predicts the future peak; margin added,
  applied to memory.max. Supports tabular joblib artifacts (rf/xgb) and
  LSTM .pt checkpoints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from psi_memory.controller.window import SignalWindow
from psi_memory.dataset.signals import ALL_SIGNALS

log = logging.getLogger(__name__)

MIB = 1024 * 1024


@dataclass
class Proposal:
    target: str            # "memory.max" | "memory.high"
    raw_prediction_mib: float | None  # model/heuristic output before margin
    value_mib: float       # proposed value for the target file
    detail: str = ""


class FixedPolicy:
    name = "fixed"
    target = "memory.max"

    def __init__(self, config: dict):
        self.limit_mib = float(config.get("limit_mib", 256))

    def propose(self, window: SignalWindow) -> Proposal:
        return Proposal(self.target, None, self.limit_mib, "fixed limit")


class PercentilePolicy:
    name = "percentile"
    target = "memory.max"

    def __init__(self, config: dict):
        self.percentile = float(config.get("percentile", 95))
        self.margin_frac = float(config.get("margin_frac", 0.15))

    def propose(self, window: SignalWindow) -> Proposal:
        history = window.current_history_mib()
        base = float(np.percentile(history, self.percentile))
        value = base * (1.0 + self.margin_frac)
        return Proposal(self.target, base, value,
                        f"p{self.percentile:.0f}={base:.1f} +{self.margin_frac:.0%}")


class SenpaiPolicy:
    name = "senpai"
    target = "memory.high"

    def __init__(self, config: dict):
        # Stall budget: how much memory stall (ms per sampling interval) we
        # accept before backing off. Senpai probes for the smallest footprint
        # that keeps pressure at a low, nonzero level.
        self.target_stall_ms = float(config.get("target_stall_ms", 10.0))
        self.step_frac = float(config.get("step_frac", 0.02))
        self.min_frac_of_usage = float(config.get("min_frac_of_usage", 0.5))

    def propose(self, window: SignalWindow) -> Proposal:
        matrix = window.matrix()
        stall_index = ALL_SIGNALS.index("psi_some_stall_ms")
        recent_stall = float(matrix[-3:, stall_index].mean())
        sample = window.latest()
        usage_mib = sample["current"] / MIB
        high = sample.get("high")
        current_high_mib = (high / MIB if isinstance(high, int)
                            else usage_mib * 1.2)  # "max" -> start near usage
        if recent_stall > self.target_stall_ms:
            value = current_high_mib * (1.0 + self.step_frac)
            detail = f"stall {recent_stall:.1f}ms > {self.target_stall_ms}ms: relief"
        else:
            value = current_high_mib * (1.0 - self.step_frac)
            detail = f"stall {recent_stall:.1f}ms <= {self.target_stall_ms}ms: squeeze"
        value = max(value, usage_mib * self.min_frac_of_usage)
        return Proposal(self.target, recent_stall, value, detail)


class LearnedPolicy:
    name = "learned"
    target = "memory.max"

    def __init__(self, config: dict, artifact_path: Path):
        self.margin_frac = float(config.get("margin_frac", 0.15))
        self.artifact_path = artifact_path
        self.kind, self._predict = self._load(artifact_path)

    @staticmethod
    def _load(path: Path):
        if path.suffix == ".pt":
            import torch

            from psi_memory.models.lstm import build_model

            artifact = torch.load(path, weights_only=False)
            model = build_model(len(artifact["signal_names"]), artifact["config"])
            model.load_state_dict(artifact["state_dict"])
            model.eval()
            norm = artifact["normalizer"]
            mean = np.asarray(norm["mean"], dtype=np.float32)
            std = np.asarray(norm["std"], dtype=np.float32)
            indices = [ALL_SIGNALS.index(s) for s in artifact["signal_names"]]

            def predict(matrix: np.ndarray) -> float:
                x = (matrix[:, indices] - mean) / std
                with torch.no_grad():
                    out = model(torch.from_numpy(x[None].astype(np.float32)))
                return float(out.item() * norm["y_std"] + norm["y_mean"])

            return "lstm", predict

        import joblib

        from psi_memory.dataset.features import AGGREGATES, _aggregate

        artifact = joblib.load(path)
        model, scaler = artifact["model"], artifact["scaler"]
        feature_names = artifact["feature_names"]
        all_columns = [f"{s}__{a}" for s in ALL_SIGNALS for a in AGGREGATES]
        indices = [all_columns.index(name) for name in feature_names]

        def predict(matrix: np.ndarray) -> float:
            row = _aggregate(matrix[None], interval_s=1.0)[0][indices]
            return float(model.predict(scaler.transform(row[None]))[0])

        return "tabular", predict

    def propose(self, window: SignalWindow) -> Proposal:
        prediction = self._predict(window.matrix())
        value = prediction * (1.0 + self.margin_frac)
        return Proposal(self.target, prediction, value,
                        f"{self.kind} peak={prediction:.1f} +{self.margin_frac:.0%}")


def make_policy(mode: str, config: dict, artifact_path: Path | None = None):
    if mode == "fixed":
        return FixedPolicy(config.get("fixed", {}))
    if mode == "percentile":
        return PercentilePolicy(config.get("percentile", {}))
    if mode == "senpai":
        return SenpaiPolicy(config.get("senpai", {}))
    if mode == "learned":
        if artifact_path is None:
            raise ValueError("learned mode requires --model <artifact>")
        return LearnedPolicy(config.get("learned", {}), artifact_path)
    raise ValueError(f"unknown controller mode {mode!r}")
