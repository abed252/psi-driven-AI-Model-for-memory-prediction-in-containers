"""Steady-state workload: allocate and hold a stable working set.

Expected signal: flat memory.current, PSI ~ 0 (proposal table row 3).
"""

from __future__ import annotations

import argparse
import random

import wl_common as wl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--working-set-mib", type=int, default=64)
    parser.add_argument("--duration-s", type=float, default=60)
    parser.add_argument("--tick-s", type=float, default=1.0,
                        help="interval between touch/churn ticks")
    parser.add_argument("--churn-mib", type=int, default=0,
                        help="optional small buffer allocated+freed each tick")
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    wl.install_signal_handlers()
    rng = random.Random(args.seed)

    working_set = [wl.alloc_chunk(wl.MIB) for _ in range(args.working_set_mib)]
    wl.log(f"steady: holding {args.working_set_mib} MiB for {args.duration_s}s")

    for elapsed in wl.run_loop(args.duration_s, args.tick_s):
        # Touch a small part of the set to look alive without causing pressure.
        wl.touch_random_chunks(working_set, 0.05, rng)
        if args.churn_mib:
            churn = wl.alloc_chunk(args.churn_mib * wl.MIB, fill=2)
            del churn

    wl.exit_clean("steady done")


if __name__ == "__main__":
    main()
