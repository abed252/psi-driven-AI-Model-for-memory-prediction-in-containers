"""Mixed workload: page-cache activity plus a slow anonymous leak.

The scientifically sharpest case: usage quickly fills toward the limit with
reclaimable cache while true (anonymous) demand grows underneath. A
usage-only observer sees a constant near-limit footprint the whole time; the
kernel's pressure tells the real story as the leak squeezes the cache out
and swapping begins.
"""

from __future__ import annotations

import argparse
import os
import random

import wl_common as wl

READ_CHUNK = wl.MIB


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-mib", type=int, default=150,
                        help="size of the file cycled through the page cache")
    parser.add_argument("--leak-step-mib", type=int, default=2,
                        help="anonymous MiB leaked per tick, never freed")
    parser.add_argument("--tick-s", type=float, default=1.0)
    parser.add_argument("--retouch-fraction", type=float, default=0.3)
    parser.add_argument("--duration-s", type=float, default=200)
    parser.add_argument("--path", default="/tmp/mixed.dat")
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    wl.install_signal_handlers()
    rng = random.Random(args.seed)

    # Reuse file_burst's creation logic for incompressible content.
    block = bytes(rng.randrange(256) for _ in range(4096)) * 256  # 1 MiB
    with open(args.path, "wb") as f:
        for _ in range(args.file_mib):
            f.write(block)
        f.flush()
        os.fsync(f.fileno())

    leaked: list[bytearray] = []
    read_offset_mib = 0
    wl.log(f"mixed: {args.file_mib} MiB cache cycle + "
           f"{args.leak_step_mib} MiB/tick leak")

    with open(args.path, "rb") as f:
        for elapsed in wl.run_loop(args.duration_s, args.tick_s):
            # Cache side: read a slice of the file each tick (wraps around),
            # keeping file pages hot without retaining anonymous copies.
            f.seek((read_offset_mib % args.file_mib) * wl.MIB)
            for _ in range(min(32, args.file_mib)):
                if not f.read(READ_CHUNK):
                    f.seek(0)
            read_offset_mib += 32
            # Leak side: grow and re-touch anonymous memory.
            for _ in range(args.leak_step_mib):
                leaked.append(wl.alloc_chunk(wl.MIB, fill=rng.randrange(1, 255)))
            wl.touch_random_chunks(leaked, args.retouch_fraction, rng)
            wl.log(f"mixed: t={elapsed:.0f}s leaked={len(leaked)} MiB")

    wl.exit_clean(f"mixed done ({len(leaked)} MiB leaked)")


if __name__ == "__main__":
    main()
