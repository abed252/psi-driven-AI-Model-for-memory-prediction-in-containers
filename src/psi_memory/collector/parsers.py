"""Parsers for cgroup v2 pseudo-file formats.

Rules from the execution spec:
- `memory.pressure` averages are kernel-computed 10/60/300s windows, not
  instantaneous values; both the averages and the cumulative `total`
  (microseconds stalled) are preserved so deltas can be derived later.
- Missing or unsupported fields must surface as None / raised errors,
  never silently become zero.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PsiLine:
    """One line of a PSI file: `some` or `full`."""

    kind: str  # "some" | "full"
    avg10: float
    avg60: float
    avg300: float
    total_us: int  # cumulative stall time in microseconds


@dataclass(frozen=True)
class PsiSample:
    some: PsiLine
    full: PsiLine | None  # `full` is absent for the CPU controller


def parse_psi(text: str) -> PsiSample:
    """Parse the content of a cgroup v2 `*.pressure` file."""
    lines: dict[str, PsiLine] = {}
    for raw_line in text.strip().splitlines():
        parts = raw_line.split()
        if not parts:
            continue
        kind = parts[0]
        if kind not in ("some", "full"):
            raise ValueError(f"unexpected PSI line kind: {raw_line!r}")
        fields: dict[str, str] = {}
        for token in parts[1:]:
            key, _, value = token.partition("=")
            if not value:
                raise ValueError(f"malformed PSI token {token!r} in {raw_line!r}")
            fields[key] = value
        try:
            lines[kind] = PsiLine(
                kind=kind,
                avg10=float(fields["avg10"]),
                avg60=float(fields["avg60"]),
                avg300=float(fields["avg300"]),
                total_us=int(fields["total"]),
            )
        except KeyError as missing:
            raise ValueError(f"PSI line missing field {missing} in {raw_line!r}")
    if "some" not in lines:
        raise ValueError(f"PSI content has no 'some' line: {text!r}")
    return PsiSample(some=lines["some"], full=lines.get("full"))


def parse_keyed_counters(text: str) -> dict[str, int]:
    """Parse `key value` files such as `memory.events` and `memory.stat`."""
    counters: dict[str, int] = {}
    for raw_line in text.strip().splitlines():
        parts = raw_line.split()
        if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
            raise ValueError(f"malformed counter line: {raw_line!r}")
        counters[parts[0]] = int(parts[1])
    return counters
