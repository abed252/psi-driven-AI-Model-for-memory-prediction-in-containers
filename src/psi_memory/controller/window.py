"""Online signal window for the controller.

Maintains a rolling buffer of raw sampler records and converts them to the
SAME per-timestep signal matrix the dataset builder produces offline — by
reusing loader._row and signals.compute_signals directly, so online/offline
parity is structural, not reimplemented (and it is verified by test).
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pandas as pd

from psi_memory.dataset.loader import RunFrame, _row
from psi_memory.dataset.signals import ALL_SIGNALS, compute_signals


class SignalWindow:
    def __init__(self, history_samples: int):
        self.history_samples = history_samples
        # +1 raw sample so the oldest row's diff-based signals are exact.
        self._raw: deque[dict] = deque(maxlen=history_samples + 1)

    def push(self, sample: dict) -> None:
        self._raw.append(sample)

    @property
    def ready(self) -> bool:
        return len(self._raw) >= self.history_samples + 1

    def latest(self) -> dict:
        return self._raw[-1]

    def matrix(self) -> np.ndarray:
        """(H, len(ALL_SIGNALS)) float32 for the most recent H samples."""
        df = pd.DataFrame([_row(s) for s in self._raw])
        df["t"] = df["mono"] - df["mono"].iloc[0]
        frame = RunFrame(run_id="live", workload="live", meta={}, df=df)
        signals = compute_signals(frame)
        return (signals[ALL_SIGNALS]
                .to_numpy(dtype=np.float32)[-self.history_samples:])

    def current_history_mib(self) -> np.ndarray:
        index = ALL_SIGNALS.index("current_mib")
        return self.matrix()[:, index]
