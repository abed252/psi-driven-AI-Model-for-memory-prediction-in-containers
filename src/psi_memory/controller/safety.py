"""Safety rules for limit changes — pure logic, exhaustively unit-tested.

Every mandatory rule from the execution spec is implemented here and every
intervention is recorded as a human-readable reason, so decision logs show
not only what was applied but why it differs from what was requested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class SafetyConfig:
    floor_mib: float = 16.0            # keep limit >= live usage + this
    min_limit_mib: float = 32.0
    max_limit_mib: float = 4096.0
    max_step_up_mib: float = 128.0     # per applied write
    max_step_down_mib: float = 64.0
    hysteresis_mib: float = 4.0        # skip writes smaller than this
    min_write_interval_s: float = 5.0  # rate limit on actual writes
    enforce_usage_floor: bool = True   # False for memory.high (Senpai squeezes
                                       # below usage by design)


@dataclass
class SafetyVerdict:
    requested_mib: float
    applied_mib: float | None     # None = no write this step
    clip_reasons: list[str] = field(default_factory=list)
    rate_limited: bool = False
    skipped: bool = False         # no write needed (hysteresis / no change)


class SafetyGate:
    """Stateful gate: applies the rules and tracks write times per target."""

    def __init__(self, config: SafetyConfig):
        self.config = config
        self._last_write_mono: float | None = None

    def evaluate(
        self,
        requested_mib: float,
        live_usage_mib: float,
        previous_limit_mib: float,
        now_mono: float,
    ) -> SafetyVerdict:
        cfg = self.config
        verdict = SafetyVerdict(requested_mib=requested_mib, applied_mib=None)
        value = requested_mib

        # Malformed / nonpositive requests are rejected outright.
        if value is None or not math.isfinite(value) or value <= 0:
            verdict.clip_reasons.append(f"rejected_malformed:{requested_mib!r}")
            verdict.skipped = True
            return verdict

        if cfg.enforce_usage_floor:
            floor = live_usage_mib + cfg.floor_mib
            if value < floor:
                verdict.clip_reasons.append(
                    f"usage_floor:{value:.1f}->{floor:.1f}")
                value = floor

        if value < cfg.min_limit_mib:
            verdict.clip_reasons.append(f"min_limit:{value:.1f}->{cfg.min_limit_mib}")
            value = cfg.min_limit_mib
        if value > cfg.max_limit_mib:
            verdict.clip_reasons.append(f"max_limit:{value:.1f}->{cfg.max_limit_mib}")
            value = cfg.max_limit_mib

        step = value - previous_limit_mib
        if step > cfg.max_step_up_mib:
            value = previous_limit_mib + cfg.max_step_up_mib
            verdict.clip_reasons.append(f"step_up_capped:+{step:.1f}->+{cfg.max_step_up_mib}")
        elif -step > cfg.max_step_down_mib:
            value = previous_limit_mib - cfg.max_step_down_mib
            verdict.clip_reasons.append(f"step_down_capped:{step:.1f}->-{cfg.max_step_down_mib}")

        # Hysteresis: avoid excessive cgroup writes for negligible changes.
        if abs(value - previous_limit_mib) < cfg.hysteresis_mib:
            verdict.skipped = True
            return verdict

        # Rate limit on actual writes.
        if (self._last_write_mono is not None
                and now_mono - self._last_write_mono < cfg.min_write_interval_s):
            verdict.rate_limited = True
            return verdict

        verdict.applied_mib = value
        self._last_write_mono = now_mono
        return verdict
