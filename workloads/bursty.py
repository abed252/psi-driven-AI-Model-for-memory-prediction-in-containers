"""Bursty batch: alternate allocation/compute bursts with idle phases.

Under a tight limit each burst forces reclaim/swap, then the idle phase
frees everything: usage and PSI oscillate (proposal table rows 3-4).
"""

from __future__ import annotations

import argparse
import random
import time

import wl_common as wl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--burst-mib", type=int, default=200)
    parser.add_argument("--hold-s", type=float, default=8,
                        help="how long each burst is held and actively touched")
    parser.add_argument("--idle-s", type=float, default=8,
                        help="idle time between bursts (memory freed)")
    parser.add_argument("--touch-tick-s", type=float, default=0.5,
                        help="touch cadence while holding the burst")
    parser.add_argument("--duration-s", type=float, default=120)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    wl.install_signal_handlers()
    rng = random.Random(args.seed)
    start = time.monotonic()
    cycle = 0

    def elapsed() -> float:
        return time.monotonic() - start

    while elapsed() < args.duration_s and not wl.stop_requested():
        cycle += 1
        wl.log(f"bursty: cycle {cycle} allocating {args.burst_mib} MiB")
        burst = [wl.alloc_chunk(wl.MIB, fill=rng.randrange(1, 255))
                 for _ in range(args.burst_mib)]

        hold_end = min(elapsed() + args.hold_s, args.duration_s)
        while elapsed() < hold_end and not wl.stop_requested():
            wl.touch_random_chunks(burst, 0.5, rng)
            time.sleep(args.touch_tick_s)

        del burst
        wl.log(f"bursty: cycle {cycle} freed, idling {args.idle_s}s")
        idle_end = min(elapsed() + args.idle_s, args.duration_s)
        while elapsed() < idle_end and not wl.stop_requested():
            time.sleep(0.2)

    wl.exit_clean(f"bursty done ({cycle} cycles)")


if __name__ == "__main__":
    main()
