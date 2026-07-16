"""Per-timestep signals derived from raw samples, split into two groups.

The ablation contract: NO_PSI_SIGNALS contains only information a
conventional usage-based system has (proposal's "memory features");
PSI_SIGNALS contains only memory.pressure-derived information. The
with-PSI feature set is exactly the without-PSI set plus PSI columns —
nothing else may differ.
"""

from __future__ import annotations

import pandas as pd

from psi_memory.dataset.loader import MIB, RunFrame

NO_PSI_SIGNALS = [
    "current_mib",        # memory.current
    "limit_mib",          # memory.max (NaN if unlimited)
    "usage_ratio",        # current / limit
    "delta_current_mib",  # per-step usage change
    "swap_mib",           # memory.swap.current
    "delta_swap_mib",
    "anon_mib",           # memory.stat anon
    "file_mib",           # memory.stat file (page cache)
]

PSI_SIGNALS = [
    "psi_some_avg10", "psi_some_avg60", "psi_some_avg300",
    "psi_full_avg10", "psi_full_avg60", "psi_full_avg300",
    "psi_some_stall_ms",  # delta of cumulative some total, ms per step
    "psi_full_stall_ms",
]

ALL_SIGNALS = NO_PSI_SIGNALS + PSI_SIGNALS


def compute_signals(run: RunFrame) -> pd.DataFrame:
    """Signal matrix for one run: columns ALL_SIGNALS + t, one row per sample."""
    df = run.df
    out = pd.DataFrame({"t": df["t"]})
    out["current_mib"] = df["current"] / MIB
    out["limit_mib"] = df["limit"] / MIB
    out["usage_ratio"] = df["current"] / df["limit"]
    out["delta_current_mib"] = out["current_mib"].diff().fillna(0.0)
    out["swap_mib"] = df["swap_current"] / MIB
    out["delta_swap_mib"] = out["swap_mib"].diff().fillna(0.0)
    out["anon_mib"] = df["stat_anon"] / MIB
    out["file_mib"] = df["stat_file"] / MIB
    for kind in ("some", "full"):
        for horizon in ("avg10", "avg60", "avg300"):
            out[f"psi_{kind}_{horizon}"] = df[f"psi_{kind}_{horizon}"]
        # Cumulative µs of stall -> ms accumulated since the previous sample.
        out[f"psi_{kind}_stall_ms"] = (
            df[f"psi_{kind}_total"].diff().fillna(0.0) / 1000.0
        )
    return out
