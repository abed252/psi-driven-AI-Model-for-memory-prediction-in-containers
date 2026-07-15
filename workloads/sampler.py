"""Sidecar sampler: read a container's cgroup v2 memory files at a fixed
interval and emit one JSON line per sample on stdout.

Runs inside a privileged helper container started with --cgroupns=host and
-v /sys/fs/cgroup:/host/cgroup:ro, so the sampling loop pays only local
file reads per tick (no per-sample process spawn from the host). The host
side (psi_memory.collector.stream) captures stdout and persists it.

Output protocol (JSON Lines):
  {"type": "header", ...}    once, describes the sampler configuration
  {"type": "sample", ...}    every tick
  {"type": "end", "reason": ...}  once, on shutdown / target exit

Missing files are listed in the sample's "missing" array — never zeroed.
Kernel PSI averages are copied as-is; deltas of the cumulative totals are
derived later in feature engineering, not here.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

_stop = False


def _handle_stop(signum, frame):
    global _stop
    _stop = True


def read_scalar(path: str):
    """Returns int bytes, the string 'max', or raises OSError."""
    with open(path) as f:
        value = f.read().strip()
    return value if value == "max" else int(value)


def read_psi(path: str) -> dict:
    psi: dict = {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0] not in ("some", "full"):
                continue
            fields = dict(token.split("=", 1) for token in parts[1:])
            psi[parts[0]] = {
                "avg10": float(fields["avg10"]),
                "avg60": float(fields["avg60"]),
                "avg300": float(fields["avg300"]),
                "total": int(fields["total"]),
            }
    return psi


def read_keyed(path: str) -> dict:
    with open(path) as f:
        return {k: int(v) for k, v in (line.split() for line in f if line.strip())}


SCALAR_FILES = ["memory.current", "memory.max", "memory.high",
                "memory.swap.current", "memory.swap.max"]


def take_sample(cgroup_dir: str) -> dict:
    sample = {"type": "sample", "mono": time.monotonic(), "wall": time.time(),
              "missing": []}
    for name in SCALAR_FILES:
        key = name.replace("memory.", "").replace(".", "_")
        try:
            sample[key] = read_scalar(os.path.join(cgroup_dir, name))
        except OSError:
            sample[key] = None
            sample["missing"].append(name)
    for name, reader in (("memory.pressure", read_psi),
                         ("memory.events", read_keyed),
                         ("memory.stat", read_keyed)):
        key = name.replace("memory.", "")
        try:
            sample[key] = reader(os.path.join(cgroup_dir, name))
        except OSError:
            sample[key] = None
            sample["missing"].append(name)
    return sample


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cgroup-dir", required=True,
                        help="target's cgroup directory as seen by this sidecar")
    parser.add_argument("--interval-s", type=float, default=1.0)
    parser.add_argument("--max-samples", type=int, default=0, help="0 = unlimited")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    emit({"type": "header", "cgroup_dir": args.cgroup_dir,
          "interval_s": args.interval_s, "sampler_version": 1,
          "mono": time.monotonic(), "wall": time.time()})

    if not os.path.isdir(args.cgroup_dir):
        emit({"type": "end", "reason": "cgroup_dir_not_found"})
        sys.exit(1)

    count = 0
    deadline = time.monotonic()
    reason = "stopped"
    while not _stop:
        if not os.path.isdir(args.cgroup_dir):
            reason = "target_exited"
            break
        try:
            emit(take_sample(args.cgroup_dir))
        except OSError:
            # Directory vanished between the isdir check and the reads.
            reason = "target_exited"
            break
        count += 1
        if args.max_samples and count >= args.max_samples:
            reason = "max_samples"
            break
        deadline += args.interval_s
        now = time.monotonic()
        if deadline <= now:  # fell behind; resynchronize instead of bursting
            deadline = now
        else:
            time.sleep(deadline - now)

    emit({"type": "end", "reason": reason, "samples": count})


if __name__ == "__main__":
    main()
