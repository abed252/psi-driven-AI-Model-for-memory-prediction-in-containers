"""Config-driven training and evaluation of the classical models.

Leakage discipline enforced here:
- features come from the dataset's stored split assignment (run-level);
- the scaler is fitted on the training split only;
- evaluation uses the validation split; the test split is touched only when
  the caller explicitly passes include_test=True.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

from psi_memory.common.seed import derive_seed
from psi_memory.dataset.features import feature_columns
from psi_memory.models import baselines, metrics

log = logging.getLogger(__name__)

VARIANTS = ("no_psi", "with_psi")
LEARNED_MODELS = ("rf", "xgb")
BASELINE_MODELS = ("persistence", "heuristic")


@dataclass
class LoadedDataset:
    name: str
    meta: dict
    table: pd.DataFrame

    def split(self, name: str) -> pd.DataFrame:
        part = self.table[self.table["split"] == name]
        if part.empty:
            raise ValueError(f"split {name!r} is empty in dataset {self.name}")
        return part


def load_dataset(dataset_dir: Path) -> LoadedDataset:
    meta = json.loads((dataset_dir / "dataset.json").read_text(encoding="utf-8"))
    table = pd.read_csv(dataset_dir / "tabular.csv")
    return LoadedDataset(name=meta["name"], meta=meta, table=table)


def make_model(model_name: str, seed: int, params: dict):
    if model_name == "rf":
        defaults = {"n_estimators": 200, "max_depth": None, "n_jobs": -1}
        return RandomForestRegressor(**{**defaults, **params}, random_state=seed)
    if model_name == "xgb":
        from xgboost import XGBRegressor

        defaults = {"n_estimators": 300, "max_depth": 6, "learning_rate": 0.1,
                    "n_jobs": 4, "verbosity": 0}
        return XGBRegressor(**{**defaults, **params}, random_state=seed)
    raise ValueError(f"unknown learned model {model_name!r}")


def train_learned(
    dataset: LoadedDataset,
    model_name: str,
    variant: str,
    config: dict,
    models_dir: Path,
    include_test: bool = False,
) -> dict:
    """Train one learned model variant; saves artifact + returns metrics."""
    assert variant in VARIANTS
    columns = feature_columns(with_psi=(variant == "with_psi"))
    seed = derive_seed(int(config.get("seed", 42)), model_name, variant) % 2**31
    params = dict(config.get(model_name, {}))

    train, val = dataset.split("train"), dataset.split("val")
    scaler = StandardScaler().fit(train[columns].to_numpy(dtype=float))
    model = make_model(model_name, seed, params)
    model.fit(scaler.transform(train[columns].to_numpy(dtype=float)),
              train["y_mib"].to_numpy(dtype=float))

    result = {
        "model": model_name, "variant": variant, "seed": seed,
        "params": params, "dataset": dataset.name,
        "n_features": len(columns),
        "val": metrics.evaluate(
            val, model.predict(scaler.transform(val[columns].to_numpy(dtype=float)))),
        "val_persistence": metrics.evaluate(val, baselines.persistence_predict(val)),
    }
    if include_test:
        test = dataset.split("test")
        result["test"] = metrics.evaluate(
            test, model.predict(scaler.transform(test[columns].to_numpy(dtype=float))))
        result["test_persistence"] = metrics.evaluate(
            test, baselines.persistence_predict(test))

    importances = getattr(model, "feature_importances_", None)
    if importances is not None:
        ranked = sorted(zip(columns, importances.tolist()),
                        key=lambda pair: pair[1], reverse=True)
        result["feature_importances"] = dict(ranked)

    models_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = models_dir / f"{dataset.name}__{model_name}__{variant}.joblib"
    joblib.dump({
        "model": model, "scaler": scaler, "feature_names": columns,
        "variant": variant, "seed": seed, "params": params,
        "dataset_meta": dataset.meta, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, artifact_path)
    result["artifact"] = str(artifact_path)
    log.info("%s/%s: val MAE %.2f MiB (persistence %.2f)", model_name, variant,
             result["val"]["mae_mib"], result["val_persistence"]["mae_mib"])
    return result


def eval_baseline(dataset: LoadedDataset, model_name: str, config: dict,
                  include_test: bool = False) -> dict:
    """Persistence / heuristic need no training; evaluated per split."""
    percentile = int(config.get("heuristic", {}).get("percentile", 95))

    def predict(part: pd.DataFrame) -> np.ndarray:
        if model_name == "persistence":
            return baselines.persistence_predict(part)
        return baselines.heuristic_predict(part, percentile)

    result = {"model": model_name, "variant": "n/a", "dataset": dataset.name,
              "params": {"percentile": percentile} if model_name == "heuristic" else {},
              "val": metrics.evaluate(dataset.split("val"), predict(dataset.split("val")))}
    if include_test:
        result["test"] = metrics.evaluate(dataset.split("test"),
                                          predict(dataset.split("test")))
    return result
