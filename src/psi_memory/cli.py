"""Console entry points (see pyproject.toml [project.scripts])."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from psi_memory.common.logging import setup_logging

REPORTS_DIR = Path("artifacts/reports")


def main_validate_env(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psi-validate-env",
        description="Validate that this machine supports per-container PSI collection.",
    )
    parser.add_argument("--skip-docker", action="store_true",
                        help="only run host-level checks (no containers started)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR,
                        help="directory for the saved JSON report")
    args = parser.parse_args(argv)
    setup_logging()

    from psi_memory.environment.validate import validate_environment

    report = validate_environment(skip_docker=args.skip_docker)
    print(report.to_json() if args.json else report.render_text())
    saved = report.save(args.reports_dir)
    print(f"\nJSON report saved: {saved}", file=sys.stderr)
    return 0 if report.ok else 1


def main_version_report(argv: list[str] | None = None) -> int:
    """Print versions of everything the project depends on."""
    import platform

    import psi_memory
    from psi_memory.environment.docker_cli import daemon_running, run_docker

    print(f"psi-memory      {psi_memory.__version__}")
    print(f"python          {sys.version.split()[0]} ({platform.platform()})")
    from importlib.metadata import PackageNotFoundError, version

    for dist in ("rich", "pyyaml", "pytest", "numpy", "pandas", "scikit-learn",
                 "xgboost", "torch", "matplotlib"):
        try:
            print(f"{dist:<15} {version(dist)}")
        except PackageNotFoundError:
            print(f"{dist:<15} not installed")
    if daemon_running():
        client = run_docker("version", "--format", "{{.Client.Version}}").stdout.strip()
        server = run_docker("version", "--format", "{{.Server.Version}}").stdout.strip()
        print(f"docker          client {client}, server {server}")
    else:
        print("docker          daemon not running")
    return 0


def main_run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psi-run",
        description="Execute a batch of workload runs defined in a YAML config.",
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args(argv)
    setup_logging()

    from psi_memory.environment.docker_cli import daemon_running
    from psi_memory.workloads.config import load_batch_config
    from psi_memory.workloads.runner import execute_batch

    if not daemon_running():
        print("Docker daemon not running — start Docker Desktop first",
              file=sys.stderr)
        return 1
    config = load_batch_config(args.config)
    metas = execute_batch(config, args.data_dir)
    return 0 if len(metas) == len(config.runs) else 1


def main_dashboard(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psi-dashboard",
        description="Live memory/PSI dashboard for a running container.",
    )
    parser.add_argument("container", help="container name or ID")
    parser.add_argument("--interval-s", type=float, default=1.0)
    args = parser.parse_args(argv)

    from psi_memory.dashboard.live import run_dashboard

    return run_dashboard(args.container, args.interval_s)


def main_calibrate(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psi-calibrate",
        description="Analyze calibration runs: check expected PSI signatures, "
                    "write plots and a machine-readable report.",
    )
    parser.add_argument("--batch-manifest", type=Path, default=None,
                        help="batch_*.json produced by psi-run "
                             "(default: newest in --data-dir)")
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--plots-dir", type=Path, default=Path("artifacts/plots/calibration"))
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    args = parser.parse_args(argv)
    setup_logging()

    from psi_memory.environment.calibration import calibrate

    return calibrate(args.data_dir, args.batch_manifest, args.plots_dir,
                     args.reports_dir)


def main_build_dataset(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psi-build-dataset",
        description="Build a processed windowed dataset from raw runs.",
    )
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, required=True,
                        help="output directory, e.g. data/processed/mini")
    parser.add_argument("--config", type=Path, default=Path("configs/dataset.yaml"))
    parser.add_argument("--runs", type=str, default=None,
                        help="comma-separated run IDs (default: all in --raw)")
    parser.add_argument("--batch-manifest", type=Path, default=None,
                        help="use the run IDs from a psi-run batch manifest")
    args = parser.parse_args(argv)
    setup_logging()

    import json

    from psi_memory.dataset.builder import build_dataset, load_dataset_config

    run_ids = args.runs.split(",") if args.runs else None
    if args.batch_manifest:
        run_ids = json.loads(args.batch_manifest.read_text(encoding="utf-8"))["run_ids"]
    ok = build_dataset(args.raw, args.out, load_dataset_config(args.config), run_ids)
    return 0 if ok else 1


def main_train(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psi-train",
        description="Train/evaluate one model on a processed dataset.",
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model", required=True,
                        choices=["persistence", "heuristic", "rf", "xgb", "lstm"])
    parser.add_argument("--variant", default="with_psi",
                        choices=["no_psi", "with_psi"])
    parser.add_argument("--config", type=Path, default=Path("configs/models.yaml"))
    parser.add_argument("--models-dir", type=Path, default=Path("artifacts/models"))
    parser.add_argument("--include-test", action="store_true",
                        help="also evaluate on the test split (final runs only)")
    args = parser.parse_args(argv)
    setup_logging()

    import json

    import yaml

    from psi_memory.models.training import eval_baseline, load_dataset, train_learned

    config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    if args.model == "lstm":
        from psi_memory.models.lstm import train_lstm

        result = train_lstm(args.dataset, args.variant, config,
                            args.models_dir, args.include_test)
        result = {k: v for k, v in result.items() if k != "loss_history"}
    else:
        dataset = load_dataset(args.dataset)
        if args.model in ("persistence", "heuristic"):
            result = eval_baseline(dataset, args.model, config, args.include_test)
        else:
            result = train_learned(dataset, args.model, args.variant, config,
                                   args.models_dir, args.include_test)
            result = {k: v for k, v in result.items() if k != "feature_importances"}
    print(json.dumps(result, indent=2))
    return 0


def main_ablate(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psi-ablate",
        description="Run the with/without-PSI ablation across all models.",
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/models.yaml"))
    parser.add_argument("--models-dir", type=Path, default=Path("artifacts/models"))
    parser.add_argument("--metrics-dir", type=Path, default=Path("artifacts/metrics"))
    parser.add_argument("--include-test", action="store_true")
    parser.add_argument("--with-lstm", action="store_true",
                        help="also train the LSTM variants (slower)")
    args = parser.parse_args(argv)
    setup_logging()

    import yaml

    from psi_memory.models.ablation import render_table, run_ablation

    config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    report = run_ablation(args.dataset, config, args.models_dir,
                          args.metrics_dir, args.include_test,
                          include_lstm=args.with_lstm)
    print(render_table(report))
    return 0


def main_control(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psi-control",
        description="Closed-loop memory-limit controller (DRY-RUN by default).",
    )
    parser.add_argument("container", help="target container name or ID")
    parser.add_argument("--mode", required=True,
                        choices=["fixed", "percentile", "senpai", "learned"])
    parser.add_argument("--model", type=Path, default=None,
                        help="model artifact for --mode learned (.joblib or .pt)")
    parser.add_argument("--duration-s", type=float, default=120)
    parser.add_argument("--live", action="store_true",
                        help="actually write limits (default: dry-run)")
    parser.add_argument("--config", type=Path,
                        default=Path("configs/controller.yaml"))
    parser.add_argument("--out-root", type=Path,
                        default=Path("artifacts/controller"))
    args = parser.parse_args(argv)
    setup_logging()

    import json

    import yaml

    from psi_memory.controller.loop import run_live
    from psi_memory.environment.docker_cli import daemon_running

    if not daemon_running():
        print("Docker daemon not running", file=sys.stderr)
        return 1
    config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    summary = run_live(args.container, args.mode, config, args.duration_s,
                       live=args.live, model_artifact=args.model,
                       out_root=args.out_root)
    print(json.dumps(summary, indent=2))
    return 0 if summary["failed_writes"] == 0 else 1


def main_smoke(argv: list[str] | None = None) -> int:
    """Minimal end-to-end smoke test: start a container, sample it, clean up."""
    setup_logging()
    from psi_memory.environment import probe
    from psi_memory.environment.docker_cli import daemon_running

    if not daemon_running():
        print("SMOKE FAIL: Docker daemon not running", file=sys.stderr)
        return 1
    name = probe.start_temp_container()
    try:
        samples = probe.sidecar_sample(name, num_samples=3, interval_s=1.0)
    finally:
        probe.stop_container(name)
    for s in samples:
        print(f"uptime={s.uptime_s:.2f}s memory.current={s.current_bytes}B "
              f"psi_some_avg10={s.pressure.some.avg10}")
    ok = len(samples) == 3
    print("SMOKE PASS" if ok else "SMOKE FAIL")
    return 0 if ok else 1
