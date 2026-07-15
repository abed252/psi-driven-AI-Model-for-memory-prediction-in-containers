"""Trace replay: track a memory-demand curve from a trace file.

Trace format (CSV, comments with '#'):  offset_s,target_mib
The workload grows/shrinks a pool of 1 MiB anonymous chunks so that its
allocation follows the linearly-interpolated target. Real public-cloud
traces are converted to this format by a separate, documented step; a small
synthetic example ships in workloads/traces/example_trace.csv for testing.
"""

from __future__ import annotations

import argparse
import random

import wl_common as wl


def load_trace(path: str) -> list[tuple[float, float]]:
    """Parse a trace file into sorted (offset_s, target_mib) points."""
    points: list[tuple[float, float]] = []
    with open(path, encoding="utf-8") as f:
        for line_number, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) != 2:
                raise ValueError(f"{path}:{line_number}: expected 'offset_s,target_mib'")
            points.append((float(parts[0]), float(parts[1])))
    if len(points) < 2:
        raise ValueError(f"{path}: trace needs at least 2 points")
    if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        raise ValueError(f"{path}: offsets must be strictly increasing")
    return points


def target_at(points: list[tuple[float, float]], t: float) -> float:
    """Linear interpolation, clamped to the trace's ends."""
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-file", default="/app/traces/example_trace.csv")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="multiply trace targets by this factor")
    parser.add_argument("--time-scale", type=float, default=1.0,
                        help="multiply trace offsets (0.5 = replay twice as fast)")
    parser.add_argument("--tick-s", type=float, default=1.0)
    parser.add_argument("--duration-s", type=float, default=0,
                        help="0 = replay the whole trace once")
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    wl.install_signal_handlers()
    rng = random.Random(args.seed)
    points = load_trace(args.trace_file)
    duration = args.duration_s or points[-1][0] * args.time_scale
    pool: list[bytearray] = []

    wl.log(f"trace_replay: {len(points)} points, duration {duration:.0f}s, "
           f"scale {args.scale}x")

    for elapsed in wl.run_loop(duration, args.tick_s):
        target = int(target_at(points, elapsed / args.time_scale) * args.scale)
        while len(pool) < target:
            pool.append(wl.alloc_chunk(wl.MIB, fill=rng.randrange(1, 255)))
        while len(pool) > target:
            pool.pop()
        wl.touch_random_chunks(pool, 0.1, rng)

    wl.exit_clean("trace_replay done")


if __name__ == "__main__":
    main()
