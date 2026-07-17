"""Offline experiment series (spec §Phase 5, experiments 1-5 and 7).

- heldout: the main PSI ablation on held-out test runs, across multiple
  independent seeds, with bootstrap CIs and per-window predictions saved
  (which also provides the error-CDF data, experiment 7).
- param_shift: models trained on the full dataset's train split, evaluated
  on a batch collected with out-of-range parameters (experiment 3).
- lowo: leave-one-workload-out folds (experiment 4). Trace-replay evaluation
  (experiment 5) falls out of per-workload reporting in all of the above.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd
from sklearn.preprocessing import StandardScaler

from psi_memory.common.seed import derive_seed
from psi_memory.dataset.features import feature_columns
from psi_memory.models import baselines, metrics
from psi_memory.models.ablation import run_ablation
from psi_memory.models.training import load_dataset, make_model
from psi_memory.evaluation.stats import across_seeds, bootstrap_ci_mae, normalized_mae

log = logging.getLogger(__name__)


def _save(report: dict, metrics_dir: Path, name: str) -> Path:
    metrics_dir.mkdir(parents=True, exist_ok=True)
    path = metrics_dir / f"{name}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("%s report: %s", name, path)
    return path


def heldout_multi_seed(dataset_dir: Path, config: dict, seeds: list[int],
                       models_dir: Path, metrics_dir: Path,
                       include_lstm: bool = True) -> dict:
    """Experiment 1+2+7: multi-seed ablation on held-out runs with CIs."""
    per_seed = []
    for seed in seeds:
        seed_config = {**config, "seed": seed}
        report = run_ablation(dataset_dir, seed_config, models_dir,
                              metrics_dir / "per_seed", include_test=True,
                              include_lstm=include_lstm)
        per_seed.append({"seed": seed, "results": report["results"]})

    # Aggregate across seeds per (model, variant); baselines are seed-free.
    aggregated: dict[str, dict] = {}
    for seed_run in per_seed:
        for result in seed_run["results"]:
            key = f"{result['model']}/{result['variant']}"
            entry = aggregated.setdefault(key, {
                "model": result["model"], "variant": result["variant"],
                "test_mae": [], "test_rmse": [], "predictions": None})
            if "test" in result:
                entry["test_mae"].append(result["test"]["mae_mib"])
                entry["test_rmse"].append(result["test"]["rmse_mib"])
                entry["per_workload"] = result["test"]["per_workload"]
                entry["underprediction_rate"] = result["test"]["underprediction_rate"]
            if result.get("test_predictions") and entry["predictions"] is None:
                entry["predictions"] = result["test_predictions"]

    summary = []
    for key, entry in aggregated.items():
        row = {"model": entry["model"], "variant": entry["variant"],
               "test_mae_across_seeds": across_seeds(entry["test_mae"]),
               "test_rmse_across_seeds": across_seeds(entry["test_rmse"]),
               "per_workload": entry.get("per_workload", {}),
               "underprediction_rate": entry.get("underprediction_rate")}
        if entry["predictions"]:
            preds = entry["predictions"]
            row["bootstrap_ci"] = bootstrap_ci_mae(preds["y_true"], preds["y_pred"])
            row["normalized_mae"] = normalized_mae(preds["y_true"], preds["y_pred"])
            row["predictions"] = preds  # kept for CDF / scatter figures
        summary.append(row)

    dataset_meta = json.loads((dataset_dir / "dataset.json").read_text(encoding="utf-8"))
    report = {
        "experiment": "heldout_multi_seed",
        "dataset": str(dataset_dir), "seeds": seeds,
        "run_counts": {s: len(r) for s, r in dataset_meta["splits"].items()},
        "window_counts": dataset_meta["counts"],
        "summary": summary,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _save(report, metrics_dir, "heldout")
    return report


def _train_eval_frame(train_frame: pd.DataFrame, eval_frame: pd.DataFrame,
                      model_name: str, variant: str, config: dict, seed_scope: str):
    """Fit on train_frame, evaluate on eval_frame (shared helper)."""
    columns = feature_columns(with_psi=(variant == "with_psi"))
    seed = derive_seed(int(config.get("seed", 42)), seed_scope, model_name,
                       variant) % 2**31
    scaler = StandardScaler().fit(train_frame[columns].to_numpy(dtype=float))
    model = make_model(model_name, seed, dict(config.get(model_name, {})))
    model.fit(scaler.transform(train_frame[columns].to_numpy(dtype=float)),
              train_frame["y_mib"].to_numpy(dtype=float))
    predictions = model.predict(
        scaler.transform(eval_frame[columns].to_numpy(dtype=float)))
    result = metrics.evaluate(eval_frame, predictions)
    result["normalized_mae"] = normalized_mae(eval_frame["y_mib"], predictions)
    result["bootstrap_ci"] = bootstrap_ci_mae(eval_frame["y_mib"], predictions)
    return result


def param_shift(train_dataset_dir: Path, shift_dataset_dir: Path, config: dict,
                metrics_dir: Path) -> dict:
    """Experiment 3: train on the full dataset, test on shifted parameters."""
    train_ds = load_dataset(train_dataset_dir)
    shift_ds = load_dataset(shift_dataset_dir)
    train_frame = train_ds.split("train")
    shift_frame = shift_ds.table  # every shift window is unseen

    overlap = set(train_ds.table["run_id"]) & set(shift_frame["run_id"])
    if overlap:
        raise ValueError(f"LEAKAGE: runs shared between datasets: {overlap}")

    results = []
    for model_name in ("rf", "xgb"):
        for variant in ("no_psi", "with_psi"):
            evaluated = _train_eval_frame(train_frame, shift_frame, model_name,
                                          variant, config, "param_shift")
            results.append({"model": model_name, "variant": variant, **evaluated})
    for name, predict in (("persistence", baselines.persistence_predict),
                          ("heuristic", lambda t: baselines.heuristic_predict(t, 95))):
        evaluated = metrics.evaluate(shift_frame, predict(shift_frame))
        results.append({"model": name, "variant": "n/a", **evaluated})

    report = {"experiment": "param_shift",
              "train_dataset": str(train_dataset_dir),
              "shift_dataset": str(shift_dataset_dir),
              "shift_runs": sorted(set(shift_frame["run_id"])),
              "n_shift_windows": int(len(shift_frame)),
              "results": results,
              "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save(report, metrics_dir, "param_shift")
    return report


def leave_one_workload_out(dataset_dir: Path, config: dict,
                           metrics_dir: Path) -> dict:
    """Experiment 4: train on all other workloads, test on the held-out one."""
    dataset = load_dataset(dataset_dir)
    table = dataset.table
    folds = []
    for workload in sorted(table["workload"].unique()):
        test_frame = table[table["workload"] == workload]
        train_frame = table[table["workload"] != workload]
        assert not set(test_frame["run_id"]) & set(train_frame["run_id"])
        fold = {"held_out_workload": workload,
                "n_train_windows": int(len(train_frame)),
                "n_test_windows": int(len(test_frame)),
                "results": []}
        for model_name in ("rf", "xgb"):
            for variant in ("no_psi", "with_psi"):
                evaluated = _train_eval_frame(train_frame, test_frame,
                                              model_name, variant, config,
                                              f"lowo:{workload}")
                fold["results"].append({"model": model_name,
                                        "variant": variant, **evaluated})
        persistence = metrics.evaluate(test_frame,
                                       baselines.persistence_predict(test_frame))
        fold["results"].append({"model": "persistence", "variant": "n/a",
                                **persistence})
        folds.append(fold)
        log.info("LOWO %s: done (%d test windows)", workload, len(test_frame))

    report = {"experiment": "leave_one_workload_out",
              "dataset": str(dataset_dir), "folds": folds,
              "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save(report, metrics_dir, "lowo")
    return report
