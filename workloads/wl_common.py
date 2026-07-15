"""Shared helpers for the container workload scripts.

These scripts run INSIDE the workload container image with no installed
package, so this module is plain stdlib and lives next to them in /app/.
"""

from __future__ import annotations

import random
import signal
import sys
import time

MIB = 1024 * 1024
PAGE = 4096

_stop_requested = False


def install_signal_handlers() -> None:
    """Make SIGTERM/SIGINT request a clean stop (docker stop sends SIGTERM)."""

    def _handler(signum, frame):
        global _stop_requested
        _stop_requested = True

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def stop_requested() -> bool:
    return _stop_requested


def log(message: str) -> None:
    """Timestamped, immediately flushed log line (collected via docker logs)."""
    print(f"[{time.monotonic():10.3f}] {message}", flush=True)


def alloc_chunk(size_bytes: int, fill: int = 1) -> bytearray:
    """Allocate a chunk and touch every page so it is actually resident.

    bytearray() gets zero pages from the kernel that are not committed until
    written; without the touch loop "allocated" memory would never create
    real memory pressure.
    """
    buf = bytearray(size_bytes)
    for offset in range(0, size_bytes, PAGE):
        buf[offset] = fill
    return buf


def touch_chunk(buf: bytearray, fill: int) -> None:
    """Re-write one byte per page: faults swapped-out pages back in (refault,
    which is what PSI measures) and keeps them dirty."""
    for offset in range(0, len(buf), PAGE):
        buf[offset] = fill


def touch_random_chunks(chunks: list[bytearray], fraction: float, rng: random.Random) -> int:
    """Touch a random subset of previously allocated chunks."""
    if not chunks or fraction <= 0:
        return 0
    count = max(1, int(len(chunks) * fraction))
    for index in rng.sample(range(len(chunks)), min(count, len(chunks))):
        touch_chunk(chunks[index], rng.randrange(1, 255))
    return count


def run_loop(duration_s: float, tick_s: float):
    """Generator yielding elapsed seconds every tick until duration or stop.

    Uses absolute monotonic deadlines so ticks do not drift.
    """
    start = time.monotonic()
    deadline = start
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= duration_s or stop_requested():
            return
        yield elapsed
        deadline += tick_s
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)


def exit_clean(reason: str) -> None:
    log(f"exiting: {reason}")
    sys.exit(0)
