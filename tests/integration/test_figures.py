"""Figure generation from synthetic stored reports (no Docker)."""

import numpy as np
import pytest

from psi_memory.evaluation import figures


def synth_heldout_report():
    rng = np.random.default_rng(0)
    y_true = rng.uniform(50, 250, 200)

    def preds(noise):
        return {"y_true": y_true.tolist(),
                "y_pred": (y_true + rng.normal(0, noise, 200)).tolist(),
                "workload": (["leak"] * 100 + ["steady"] * 100)}

    def row(model, variant, mae, noise):
        return {"model": model, "variant": variant,
                "test_mae_across_seeds": {"mean": mae, "std": mae * 0.1,
                                          "min": mae * 0.9, "max": mae * 1.1,
                                          "n_seeds": 3, "values": [mae] * 3},
                "test_rmse_across_seeds": {"mean": mae * 2, "std": 0.1,
                                           "min": 0, "max": 0, "n_seeds": 3,
                                           "values": [mae * 2] * 3},
                "per_workload": {"leak": {"mae_mib": mae, "n": 100},
                                 "steady": {"mae_mib": mae / 2, "n": 100}},
                "underprediction_rate": 0.4,
                "predictions": preds(noise)}

    return {"experiment": "heldout_multi_seed", "seeds": [1, 2, 3],
            "summary": [row("persistence", "n/a", 30.0, 30),
                        row("heuristic", "n/a", 15.0, 15),
                        row("rf", "no_psi", 3.0, 3),
                        row("rf", "with_psi", 2.5, 2.5),
                        row("xgb", "no_psi", 1.0, 1),
                        row("xgb", "with_psi", 0.9, 0.9),
                        row("lstm", "no_psi", 2.0, 2),
                        row("lstm", "with_psi", 1.8, 1.8)]}


def synth_closed_loop_report():
    sessions = []
    for scenario in ("leak", "bursty"):
        sessions.append({"scenario": scenario, "label": "fixed", "mode": "fixed",
                         "margin": None, "avg_headroom_mib": 300.0,
                         "p95_headroom_mib": 350.0, "oom_kill_events": 0,
                         "demand_above_limit_events": 0,
                         "time_under_pressure_frac": 0.0})
        for label in ("percentile", "learned_no_psi", "learned_with_psi"):
            for margin, headroom, ooms in ((0.05, 30, 2), (0.15, 60, 1),
                                           (0.30, 120, 0)):
                sessions.append({"scenario": scenario, "label": label,
                                 "mode": label, "margin": margin,
                                 "avg_headroom_mib": headroom,
                                 "p95_headroom_mib": headroom * 1.4,
                                 "oom_kill_events": ooms,
                                 "demand_above_limit_events": ooms * 3,
                                 "time_under_pressure_frac": 0.1})
    return {"experiment": "closed_loop_comparison", "margins": [0.05, 0.15, 0.3],
            "sessions": sessions}


def test_ablation_bars(tmp_path):
    figures.fig_ablation_bars(synth_heldout_report(), tmp_path / "a.png")
    assert (tmp_path / "a.png").stat().st_size > 10_000


def test_error_cdf(tmp_path):
    figures.fig_error_cdf(synth_heldout_report(), tmp_path / "c.png")
    assert (tmp_path / "c.png").exists()


def test_pred_vs_actual(tmp_path):
    figures.fig_pred_vs_actual(synth_heldout_report(), "xgb", "with_psi",
                               tmp_path / "p.png")
    assert (tmp_path / "p.png").exists()


def test_per_workload(tmp_path):
    figures.fig_per_workload(
        synth_heldout_report(),
        [("persistence", "n/a"), ("rf", "no_psi"), ("rf", "with_psi")],
        tmp_path / "w.png")
    assert (tmp_path / "w.png").exists()


def test_tradeoff(tmp_path):
    figures.fig_tradeoff(synth_closed_loop_report(), tmp_path / "t.png")
    assert (tmp_path / "t.png").stat().st_size > 10_000


def test_generalization(tmp_path):
    heldout = synth_heldout_report()
    shift = {"results": [
        {"model": m, "variant": v, "mae_mib": 5.0}
        for m in ("rf", "xgb") for v in ("no_psi", "with_psi")]}
    lowo = {"folds": [
        {"held_out_workload": "leak", "results": [
            {"model": m, "variant": v, "mae_mib": 20.0}
            for m in ("rf", "xgb") for v in ("no_psi", "with_psi")]},
        {"held_out_workload": "steady", "results": [
            {"model": m, "variant": v, "mae_mib": 10.0}
            for m in ("rf", "xgb") for v in ("no_psi", "with_psi")]}]}
    figures.fig_generalization(heldout, shift, lowo, tmp_path / "g.png")
    assert (tmp_path / "g.png").exists()
