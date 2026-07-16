"""Future-peak label indexing on tiny hand-calculated series.

Sample layout used below: interval 1 s, t = 0..9,
current_mib =            [10, 20, 30, 40, 50, 40, 30, 20, 10, 5]
With H=3 (history) and horizon 3 s, a window ending at t=k targets
max(current) over t in (k, k+3] — the sample AT k is excluded.
"""

import numpy as np
import pandas as pd
import pytest

from psi_memory.dataset.signals import ALL_SIGNALS
from psi_memory.dataset.windows import WindowConfig, build_windows

CURRENTS = [10, 20, 30, 40, 50, 40, 30, 20, 10, 5]


def make_signals(currents=CURRENTS, times=None) -> pd.DataFrame:
    times = times if times is not None else list(range(len(currents)))
    df = pd.DataFrame(0.0, index=range(len(currents)), columns=["t", *ALL_SIGNALS])
    df["t"] = [float(x) for x in times]
    df["current_mib"] = [float(c) for c in currents]
    df["limit_mib"] = 256.0
    return df


CFG = WindowConfig(history_samples=3, horizon_s=3.0, interval_s=1.0,
                   max_gap_factor=2.5, stride=1, min_horizon_samples=3)


def test_hand_calculated_targets():
    ws = build_windows("r", "steady", make_signals(), CFG)
    # Window ends at t=2..6 (t=7 would need samples up to t=10 — run ends at 9).
    assert ws.end_t.tolist() == [2.0, 3.0, 4.0, 5.0, 6.0]
    # t=2 -> max(40,50,40)=50 | t=3 -> max(50,40,30)=50 | t=4 -> max(40,30,20)=40
    # t=5 -> max(30,20,10)=30 | t=6 -> max(20,10,5)=20
    assert ws.y_mib.tolist() == [50.0, 50.0, 40.0, 30.0, 20.0]


def test_current_sample_never_in_target():
    # The window ending at t=4 sits ON the peak (50); its target must be 40 —
    # the strictly-after maximum — not 50. This is the classic off-by-one.
    ws = build_windows("r", "steady", make_signals(), CFG)
    window_at_peak = list(ws.end_t).index(4.0)
    assert ws.y_mib[window_at_peak] == 40.0


def test_incomplete_horizon_discarded():
    ws = build_windows("r", "steady", make_signals(), CFG)
    assert 7.0 not in ws.end_t  # t=7 + horizon 3 = 10 > last sample t=9
    assert ws.discarded["incomplete_horizon"] == 3  # t=7, 8, 9


def test_gap_discards_touching_windows():
    # Remove the sample at t=4: windows whose window+horizon span crosses
    # the 3..5 gap (size 2 > 2.5*1? no — gap=2 <= 2.5) stay. Use factor 1.5.
    currents = [10, 20, 30, 40, 40, 30, 20, 10, 5]
    times = [0, 1, 2, 3, 5, 6, 7, 8, 9]  # t=4 missing
    cfg = WindowConfig(history_samples=3, horizon_s=3.0, interval_s=1.0,
                       max_gap_factor=1.5, stride=1, min_horizon_samples=2)
    ws = build_windows("r", "steady", make_signals(currents, times), cfg)
    # Every window whose [start, end+horizon] includes the 3->5 gap is dropped.
    for end_t in ws.end_t:
        assert not (end_t - 2 <= 3 and end_t + 3 >= 5), \
            f"window ending {end_t} spans the gap but survived"
    assert ws.discarded["gap"] > 0


def test_sparse_horizon_discarded():
    # Samples get sparse at the tail: horizon exists (last t >= end+3) but
    # contains fewer than min_horizon_samples samples.
    currents = [10, 20, 30, 40, 50, 40, 30]
    times = [0, 1, 2, 3, 4, 5.5, 8]      # only 2 samples in (4, 7]
    cfg = WindowConfig(history_samples=3, horizon_s=3.0, interval_s=1.0,
                       max_gap_factor=10, stride=1, min_horizon_samples=3)
    ws = build_windows("r", "steady", make_signals(currents, times), cfg)
    assert 4.0 not in ws.end_t
    assert ws.discarded["sparse_horizon"] >= 1


def test_nan_features_discarded():
    signals = make_signals()
    signals.loc[3, "usage_ratio"] = np.nan  # e.g. unlimited memory.max
    ws = build_windows("r", "steady", signals, CFG)
    assert ws.discarded["nan_features"] > 0
    for end_t in ws.end_t:  # no surviving window contains index 3 (t=3)
        assert not (end_t - 2 <= 3 <= end_t)


def test_short_run_produces_no_windows():
    ws = build_windows("r", "steady", make_signals(CURRENTS[:4]), CFG)
    assert len(ws.y_mib) == 0
    assert ws.sequences.shape == (0, 3, len(ALL_SIGNALS))


def test_stride():
    cfg = WindowConfig(history_samples=3, horizon_s=3.0, interval_s=1.0,
                       max_gap_factor=2.5, stride=2, min_horizon_samples=3)
    ws = build_windows("r", "steady", make_signals(), cfg)
    assert ws.end_t.tolist() == [2.0, 4.0, 6.0]


def test_baseline_columns_hand_checked():
    ws = build_windows("r", "steady", make_signals(), CFG)
    first = list(ws.end_t).index(2.0)  # history = [10, 20, 30]
    assert ws.hist_current_last[first] == 30.0
    assert ws.hist_current_max[first] == 30.0
    assert ws.hist_current_p95[first] == pytest.approx(29.0)  # np.percentile
