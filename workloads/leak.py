"""Anonymous memory leak: allocate steadily and never free.

Under a tight memory.max with swap the kernel must swap anonymous pages;
re-touching old chunks forces refaults, so PSI rises until the container is
OOM-killed (proposal table row 2: rising PSI).
"""

from __future__ import annotations

import argparse
import random

import wl_common as wl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step-mib", type=int, default=8,
                        help="MiB allocated per step")
    parser.add_argument("--tick-s", type=float, default=1.0,
                        help="seconds between allocation steps")
    parser.add_argument("--duration-s", type=float, default=120)
    parser.add_argument("--retouch-fraction", type=float, default=0.3,
                        help="fraction of old chunks re-touched every step "
                             "(drives swap refaults once past the limit)")
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    wl.install_signal_handlers()
    rng = random.Random(args.seed)
    leaked: list[bytearray] = []

    wl.log(f"leak: +{args.step_mib} MiB every {args.tick_s}s, never freed")

    for elapsed in wl.run_loop(args.duration_s, args.tick_s):
        for _ in range(args.step_mib):
            leaked.append(wl.alloc_chunk(wl.MIB, fill=rng.randrange(1, 255)))
        touched = wl.touch_random_chunks(leaked, args.retouch_fraction, rng)
        wl.log(f"leak: t={elapsed:.0f}s held={len(leaked)} MiB retouched={touched}")

    wl.exit_clean("leak done (survived without OOM)")


if __name__ == "__main__":
    main()
