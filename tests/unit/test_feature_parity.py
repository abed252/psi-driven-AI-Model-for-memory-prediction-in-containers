"""With-PSI and without-PSI feature sets: identical rows, PSI columns only added."""

import numpy as np
import pandas as pd

from psi_memory.dataset.features import AGGREGATES, feature_columns, windows_to_table
from psi_memory.dataset.signals import ALL_SIGNALS, NO_PSI_SIGNALS, PSI_SIGNALS
from psi_memory.dataset.windows import WindowConfig, build_windows


def test_column_sets():
    without = feature_columns(with_psi=False)
    with_psi = feature_columns(with_psi=True)
    assert set(without) < set(with_psi)
    added = set(with_psi) - set(without)
    # Every added column derives from a PSI signal, nothing else.
    assert added == {f"{s}__{a}" for s in PSI_SIGNALS for a in AGGREGATES}
    assert len(without) == len(NO_PSI_SIGNALS) * len(AGGREGATES)


def test_no_psi_column_values_identical_between_variants():
    rng = np.random.default_rng(0)
    signals = pd.DataFrame(
        rng.uniform(0, 100, size=(50, len(ALL_SIGNALS))), columns=ALL_SIGNALS)
    signals.insert(0, "t", np.arange(50, dtype=float))
    cfg = WindowConfig(history_samples=5, horizon_s=5.0, interval_s=1.0,
                       min_horizon_samples=3)
    table = windows_to_table(
        [build_windows("r", "steady", signals, cfg)], cfg.interval_s)
    # Both variants read from the same table: selecting the no-PSI columns
    # from the with-PSI set must give bit-identical values.
    without = table[feature_columns(with_psi=False)]
    with_psi = table[feature_columns(with_psi=True)]
    pd.testing.assert_frame_equal(with_psi[without.columns], without)
    assert len(without) == len(with_psi)


def test_aggregates_hand_checked():
    signals = pd.DataFrame(0.0, index=range(6), columns=["t", *ALL_SIGNALS])
    signals["t"] = np.arange(6, dtype=float)
    signals["current_mib"] = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    signals["limit_mib"] = 100.0
    cfg = WindowConfig(history_samples=5, horizon_s=1.0, interval_s=1.0,
                       min_horizon_samples=1)
    table = windows_to_table(
        [build_windows("r", "steady", signals, cfg)], cfg.interval_s)
    row = table.iloc[0]  # window over currents [10..50]
    assert row["current_mib__last"] == 50.0
    assert row["current_mib__mean"] == 30.0
    assert row["current_mib__max"] == 50.0
    assert row["current_mib__delta"] == 40.0
    assert row["current_mib__slope"] == 10.0  # +10 MiB per second, exactly
    assert row["y_mib"] == 60.0
