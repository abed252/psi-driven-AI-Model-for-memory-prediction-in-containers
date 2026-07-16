"""Safety gate: every mandatory rule, with reasons recorded."""

import math

import pytest

from psi_memory.controller.safety import SafetyConfig, SafetyGate

CFG = SafetyConfig(floor_mib=16, min_limit_mib=32, max_limit_mib=512,
                   max_step_up_mib=100, max_step_down_mib=50,
                   hysteresis_mib=4, min_write_interval_s=5)


def gate():
    return SafetyGate(CFG)


def test_never_below_live_usage_plus_floor():
    verdict = gate().evaluate(requested_mib=100, live_usage_mib=150,
                              previous_limit_mib=200, now_mono=0)
    assert verdict.applied_mib == 166  # 150 + 16
    assert any(r.startswith("usage_floor") for r in verdict.clip_reasons)


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf"), None])
def test_malformed_values_rejected(bad):
    verdict = gate().evaluate(bad, live_usage_mib=100,
                              previous_limit_mib=200, now_mono=0)
    assert verdict.applied_mib is None
    assert verdict.skipped
    assert any("rejected_malformed" in r for r in verdict.clip_reasons)


def test_min_and_max_limits_enforced():
    low = SafetyGate(SafetyConfig(floor_mib=0, min_limit_mib=64,
                                  max_limit_mib=512, max_step_down_mib=1e9,
                                  max_step_up_mib=1e9, hysteresis_mib=0))
    verdict = low.evaluate(10, live_usage_mib=1, previous_limit_mib=128,
                           now_mono=0)
    assert verdict.applied_mib == 64
    verdict = low.evaluate(9999, live_usage_mib=1, previous_limit_mib=500,
                           now_mono=100)
    assert verdict.applied_mib == 512


def test_step_up_and_down_rate_limits():
    g = gate()
    up = g.evaluate(500, live_usage_mib=10, previous_limit_mib=200, now_mono=0)
    assert up.applied_mib == 300  # +100 cap
    assert any("step_up_capped" in r for r in up.clip_reasons)
    down = gate().evaluate(40, live_usage_mib=10, previous_limit_mib=200,
                           now_mono=0)
    assert down.applied_mib == 150  # -50 cap
    assert any("step_down_capped" in r for r in down.clip_reasons)


def test_hysteresis_skips_tiny_changes():
    verdict = gate().evaluate(202, live_usage_mib=10, previous_limit_mib=200,
                              now_mono=0)
    assert verdict.skipped and verdict.applied_mib is None


def test_write_interval_rate_limiting():
    g = gate()
    first = g.evaluate(250, live_usage_mib=10, previous_limit_mib=200, now_mono=100)
    assert first.applied_mib is not None
    second = g.evaluate(300, live_usage_mib=10, previous_limit_mib=250, now_mono=102)
    assert second.rate_limited and second.applied_mib is None
    third = g.evaluate(300, live_usage_mib=10, previous_limit_mib=250, now_mono=106)
    assert third.applied_mib is not None  # 5s elapsed since last write


def test_senpai_mode_skips_usage_floor():
    config = SafetyConfig(floor_mib=16, enforce_usage_floor=False,
                          min_limit_mib=32, max_limit_mib=512,
                          max_step_up_mib=1e9, max_step_down_mib=1e9,
                          hysteresis_mib=0)
    verdict = SafetyGate(config).evaluate(100, live_usage_mib=150,
                                          previous_limit_mib=180, now_mono=0)
    assert verdict.applied_mib == 100  # below usage allowed for memory.high


def test_clean_request_passes_unmodified():
    verdict = gate().evaluate(250, live_usage_mib=100, previous_limit_mib=200,
                              now_mono=0)
    assert verdict.applied_mib == 250
    assert verdict.clip_reasons == []
    assert not verdict.rate_limited and not verdict.skipped
