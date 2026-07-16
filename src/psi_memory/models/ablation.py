"""The PSI ablation: every model with and without PSI features, same data.

Persistence and the percentile heuristic never see PSI, so they appear once;
RF and XGBoost are trained twice on identical rows/splits/params, differing
only in the presence of PSI columns. Any metric gap is attributable to the
PSI features alone.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from psi_memory.models.training import (
    BASELINE_MODELS,
    LEARNED_MODELS,
    VARIANTS,
    eval_baseline,
    load_dataset,
    train_learned,
)

log = logging.getLogger(__name__)


def run_ablation(dataset_dir: Path, config: dict, models_dir: Path,
                 metrics_dir: Path, include_test: bool = False,
                 include_lstm: bool = False) -> dict:
    dataset = load_dataset(dataset_dir)
    results = []
    for model_name in BASELINE_MODELS:
        results.append(eval_baseline(dataset, model_name, config, include_test))
    for model_name in LEARNED_MODELS:
        for variant in VARIANTS:
            results.append(train_learned(dataset, model_name, variant, config,
                                         models_dir, include_test))
    if include_lstm:
        from psi_memory.models.lstm import train_lstm

        for variant in VARIANTS:
            result = train_lstm(dataset_dir, variant, config, models_dir,
                                include_test)
            results.append({k: v for k, v in result.items()
                            if k != "loss_history"})

    report = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dataset": dataset.name,
        "dataset_dir": str(dataset_dir),
        "include_test": include_test,
        "config": config,
        "results": results,
    }
    metrics_dir.mkdir(parents=True, exist_ok=True)
    out = metrics_dir / f"ablation_{dataset.name}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("ablation report: %s", out)
    return report


def render_table(report: dict) -> str:
    """Plain-text ablation summary (also printed by the CLI)."""
    lines = [
        f"PSI ablation — dataset {report['dataset']} "
        f"({'val+test' if report['include_test'] else 'val only'})",
        f"{'model':<12} {'variant':<9} {'val MAE':>9} {'val RMSE':>9} "
        f"{'test MAE':>9} {'test RMSE':>9}",
    ]
    for result in report["results"]:
        val = result["val"]
        test = result.get("test", {})
        lines.append(
            f"{result['model']:<12} {result['variant']:<9} "
            f"{val['mae_mib']:>9.2f} {val['rmse_mib']:>9.2f} "
            f"{test.get('mae_mib', float('nan')):>9.2f} "
            f"{test.get('rmse_mib', float('nan')):>9.2f}"
        )
    return "\n".join(lines)
