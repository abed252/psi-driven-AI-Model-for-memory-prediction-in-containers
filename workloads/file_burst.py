"""File-read burst: repeatedly read a large file through the page cache.

Memory usage looks HIGH (file-backed page cache counts toward the cgroup)
but the cache is cleanly reclaimable, so PSI stays low (proposal table
row 1). Data is read in small chunks and immediately discarded — this must
NOT retain anonymous memory.
"""

from __future__ import annotations

import argparse
import os
import random

import wl_common as wl

READ_CHUNK = wl.MIB


def create_file(path: str, size_mib: int, seed: int) -> None:
    """Write incompressible-ish content once; read passes then hit page cache."""
    rng = random.Random(seed)
    block = bytes(rng.randrange(256) for _ in range(4096)) * 256  # 1 MiB
    with open(path, "wb") as f:
        for _ in range(size_mib):
            f.write(block)
        f.flush()
        os.fsync(f.fileno())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-mib", type=int, default=256)
    parser.add_argument("--pause-s", type=float, default=1.0,
                        help="pause between full read passes")
    parser.add_argument("--duration-s", type=float, default=60)
    parser.add_argument("--path", default="/tmp/burst.dat")
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    wl.install_signal_handlers()
    wl.log(f"file_burst: creating {args.file_mib} MiB file")
    create_file(args.path, args.file_mib, args.seed)
    wl.log("file_burst: starting read passes")

    passes = 0
    for _ in wl.run_loop(args.duration_s, args.pause_s):
        with open(args.path, "rb") as f:
            while f.read(READ_CHUNK):
                if wl.stop_requested():
                    break
        passes += 1
        wl.log(f"file_burst: completed pass {passes}")

    wl.exit_clean(f"file_burst done ({passes} passes)")


if __name__ == "__main__":
    main()
