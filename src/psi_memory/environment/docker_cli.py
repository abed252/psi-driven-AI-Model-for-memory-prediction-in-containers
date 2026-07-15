"""Thin wrapper around the docker CLI.

The project deliberately talks to Docker through the CLI (not docker-py):
it works identically from Windows and WSL, avoids SDK/daemon API version
coupling, and every action is reproducible by hand from the README.
"""

from __future__ import annotations

import json
import shutil
import subprocess


class DockerError(RuntimeError):
    pass


def docker_available() -> bool:
    return shutil.which("docker") is not None


def run_docker(
    *args: str, check: bool = True, timeout: float = 120.0
) -> subprocess.CompletedProcess[str]:
    """Run `docker <args>` and capture output."""
    cmd = ["docker", *args]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8"
    )
    if check and proc.returncode != 0:
        raise DockerError(
            f"{' '.join(cmd)} failed (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return proc


def docker_json(*args: str, timeout: float = 120.0):
    """Run a docker command that emits JSON and parse it."""
    proc = run_docker(*args, timeout=timeout)
    return json.loads(proc.stdout)


def daemon_running() -> bool:
    if not docker_available():
        return False
    try:
        run_docker("info", "--format", "{{.ServerVersion}}", timeout=30)
        return True
    except (DockerError, subprocess.TimeoutExpired):
        return False
