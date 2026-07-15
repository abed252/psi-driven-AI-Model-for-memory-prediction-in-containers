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
