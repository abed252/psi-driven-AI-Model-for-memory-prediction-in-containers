"""Phase 5 evaluation logic: closed-loop metrics, CIs, fold integrity."""

import json

import numpy as np
import pytest

from psi_memory.evaluation.closed_loop import session_metrics
from psi_memory.evaluation.stats import across_seeds, bootstrap_ci_mae, normalized_mae

MIB = 1024 * 1024


def write_session(tmp_path, decisions, mode="percentile", writes=3):
    session = tmp_path / "session"
    session.mkdir()
    with open(session / "decisions.jsonl", "w") as f:
        for d in decisions:
            f.write(json.dumps(d) + "\n")
    (session / "meta.json").write_text(json.dumps(
        {"mode": mode, "writes": writes, "failed_writes": 0,
         "end_reason": "max_steps"}))
    return session


def decision(step, current_mib, limit_mib, psi=0.0, ev_max=0, oom_kill=0,
             target="memory.max"):
    return {
        "step": step, "target": target, "mode": "percentile",
        "observed": {"current_mib": current_mib,
                     "memory_max": int(limit_mib * MIB),
                     "memory_high": "max",
                     "psi_some_avg10": psi,
                     "events": {"max": ev_max, "oom_kill": oom_kill}},
    }


def test_session_metrics_headroom_and_events(tmp_path):
    decisions = [decision(1, 100, 200), decision(2, 120, 200, psi=8.0),
                 decision(3, 150, 260, psi=2.0, ev_max=5),
                 decision(4, 150, 260, ev_max=9, oom_kill=1)]
    metrics = session_metrics(write_session(tmp_path, decisions))
    assert metrics["avg_headroom_mib"] == pytest.approx((100 + 80 + 110 + 110) / 4)
    assert metrics["oom_kill_events"] == 1
    assert metrics["demand_above_limit_events"] == 9  # 9 - 0
    assert metrics["time_under_pressure_frac"] == pytest.approx(0.25)
    assert metrics["limit_changes"] == 1  # 200 -> 260 once
    assert metrics["steps"] == 4


def test_session_metrics_memory_high_target(tmp_path):
    decisions = [
        {"step": 1, "target": "memory.high", "mode": "senpai",
         "observed": {"current_mib": 100, "memory_max": 512 * MIB,
                      "memory_high": 150 * MIB, "psi_some_avg10": 0.0,
                      "events": {"max": 0, "oom_kill": 0}}},
        {"step": 2, "target": "memory.high", "mode": "senpai",
         "observed": {"current_mib": 100, "memory_max": 512 * MIB,
                      "memory_high": 140 * MIB, "psi_some_avg10": 1.0,
                      "events": {"max": 0, "oom_kill": 0}}},
    ]
    metrics = session_metrics(write_session(tmp_path, decisions, mode="senpai"))
    # Headroom measured against memory.high, not memory.max.
    assert metrics["avg_headroom_mib"] == pytest.approx((50 + 40) / 2)
    assert metrics["target"] == "memory.high"


def test_bootstrap_ci_brackets_true_mae():
    rng = np.random.default_rng(0)
    y_true = rng.uniform(50, 250, 400)
    y_pred = y_true + rng.normal(0, 5, 400)
    ci = bootstrap_ci_mae(y_true, y_pred, n_boot=500)
    assert ci["ci_low"] < ci["mae_mib"] < ci["ci_high"]
    assert ci["ci_high"] - ci["ci_low"] < 2.0  # tight for n=400, sigma=5


def test_across_seeds_stats():
    stats = across_seeds([1.0, 2.0, 3.0])
    assert stats["mean"] == 2.0 and stats["n_seeds"] == 3
    assert stats["std"] == pytest.approx(1.0)


def test_normalized_mae():
    assert normalized_mae([100, 100], [110, 90]) == pytest.approx(0.1)


def test_lowo_folds_have_no_workload_overlap(synth_raw, tmp_path):
    import math

    from psi_memory.dataset.builder import build_dataset
    from psi_memory.evaluation.experiments import leave_one_workload_out

    for i in range(3):
        synth_raw.add(f"steady-{i}", workload="steady", n_samples=60,
                      current_fn=lambda j, b=40 + 5 * i: b + math.sin(j / 3))
        synth_raw.add(f"leak-{i}", workload="leak", n_samples=60, oom=True,
                      current_fn=lambda j, r=1 + 0.3 * i: 40 + r * j,
                      psi_avg10_fn=lambda j: max(0.0, (j - 25) * 0.4))
    out = tmp_path / "ds"
    config = {"window": {"history_samples": 8, "horizon_s": 8.0,
                         "interval_s": 1.0, "max_gap_factor": 2.5,
                         "stride": 2, "min_horizon_samples": 5},
              "splits": {"seed": 1, "fractions": {"train": 0.6, "val": 0.2,
                                                  "test": 0.2}}}
    assert build_dataset(synth_raw.dir, out, config)
    report = leave_one_workload_out(
        out, {"seed": 1, "rf": {"n_estimators": 20},
              "xgb": {"n_estimators": 20}}, tmp_path / "metrics")
    assert {f["held_out_workload"] for f in report["folds"]} == {"steady", "leak"}
    for fold in report["folds"]:
        assert fold["n_test_windows"] > 0 and fold["n_train_windows"] > 0
        rf_no = next(r for r in fold["results"]
                     if r["model"] == "rf" and r["variant"] == "no_psi")
        assert rf_no["mae_mib"] >= 0


def test_param_shift_rejects_shared_runs(synth_raw, tmp_path):
    import math

    from psi_memory.dataset.builder import build_dataset
    from psi_memory.evaluation.experiments import param_shift

    for i in range(3):
        synth_raw.add(f"steady-{i}", workload="steady", n_samples=60,
                      current_fn=lambda j, b=40 + 5 * i: b + math.sin(j / 3))
        synth_raw.add(f"leak-{i}", workload="leak", n_samples=60,
                      current_fn=lambda j: 40 + j,
                      psi_avg10_fn=lambda j: max(0.0, (j - 25) * 0.4))
    config = {"window": {"history_samples": 8, "horizon_s": 8.0,
                         "interval_s": 1.0, "max_gap_factor": 2.5,
                         "stride": 2, "min_horizon_samples": 5},
              "splits": {"seed": 1, "fractions": {"train": 0.6, "val": 0.2,
                                                  "test": 0.2}}}
    out = tmp_path / "ds"
    assert build_dataset(synth_raw.dir, out, config)
    # Same directory as both train and shift => same run IDs => leakage.
    with pytest.raises(ValueError, match="LEAKAGE"):
        param_shift(out, out, {"seed": 1, "rf": {"n_estimators": 10},
                               "xgb": {"n_estimators": 10}},
                    tmp_path / "metrics")
