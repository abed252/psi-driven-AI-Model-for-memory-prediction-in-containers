"""Byte-unit handling for cgroup v2 pseudo-file values.

Raw values are always kept as exact integers (bytes). Conversion to MiB is
explicit and never silently lossy: `bytes_to_mib` is exact for multiples of
1 MiB and otherwise returns a float that is only used for display, while the
stored value remains the integer byte count.
"""

from __future__ import annotations

MIB = 1024 * 1024


def parse_cgroup_scalar(text: str) -> int | None:
    """Parse a cgroup v2 scalar file value.

    Returns the integer byte count, or None when the value is the literal
    string "max" (meaning: no limit configured). Raises ValueError on
    anything else so malformed records are detected instead of becoming 0.
    """
    value = text.strip()
    if value == "max":
        return None
    if not value.lstrip("-").isdigit():
        raise ValueError(f"malformed cgroup scalar: {value!r}")
    number = int(value)
    if number < 0:
        raise ValueError(f"negative cgroup scalar: {value!r}")
    return number


def bytes_to_mib(num_bytes: int) -> float:
    """Convert bytes to MiB. Exact when num_bytes is a multiple of 1 MiB."""
    return num_bytes / MIB


def mib_to_bytes(mib: float) -> int:
    """Convert MiB to an integer byte count, rejecting fractional bytes."""
    raw = mib * MIB
    if raw != int(raw):
        raise ValueError(f"{mib} MiB is not a whole number of bytes")
    return int(raw)
