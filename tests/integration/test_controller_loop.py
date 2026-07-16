"""Full control-loop sessions on fake sources and the fake cgroup actuator
(the spec's required pre-live testing), no Docker."""

import json
from pathlib import Path

import pytest

from psi_memory.controller.actuator import DryRunActuator, FakeCgroupActuator
from psi_memory.controller.loop import run_session
from psi_memory.controller.policies import make_policy
from psi_memory.controller.safety import SafetyConfig, SafetyGate

from tests.unit.test_controller_policies import make_sample

MIB = 1024 * 1024

CONFIG = {"percentile": {"percentile": 100, "margin_frac": 0.10},
          "senpai": {"target_stall_ms": 10, "step_frac": 0.05,
                     "min_frac_of_usage": 0.5},
          "fixed": {"limit_mib": 256}}


def sample_stream(n, current_fn=lambda i: 100.0 + i, end_reason=None, **kw):
    for i in range(n):
        yield make_sample(i, current_mib=current_fn(i), **kw)
    if end_reason:
        yield {"type": "end", "reason": end_reason}


def run(tmp_path, mode, samples, actuator=None, safety=None, history=5):
    policy = make_policy(mode, CONFIG)
    gate = SafetyGate(safety or SafetyConfig(
        floor_mib=8, min_limit_mib=32, max_limit_mib=1024,
        max_step_up_mib=1e9, max_step_down_mib=1e9, hysteresis_mib=0.5,
        min_write_interval_s=0,
        enforce_usage_floor=(mode != "senpai")))
    out_dir = tmp_path / f"session-{mode}"
    summary = run_session(samples, policy, gate,
                          actuator if actuator is not None else DryRunActuator(),
                          out_dir, {"session_id": f"test-{mode}"},
                          dry_run=isinstance(actuator, (DryRunActuator, type(None))),
                          history_samples=history)
    decisions = [json.loads(l) for l in
                 (out_dir / "decisions.jsonl").read_text().splitlines()]
    return summary, decisions


def test_percentile_session_decision_log_complete(tmp_path):
    summary, decisions = run(tmp_path, "percentile", sample_stream(15))
    assert summary["steps"] == len(decisions) > 0
    required = {"ts_wall", "ts_mono", "step", "mode", "target", "observed",
                "prediction_mib", "requested_mib", "applied_mib",
                "clip_reasons", "rate_limited", "skipped", "prev_limit_mib",
                "live_usage_mib", "safety", "model", "dry_run", "write"}
    assert required <= set(decisions[0])
    assert decisions[0]["observed"]["current_mib"] > 0
    assert decisions[0]["mode"] == "percentile"


def test_fake_cgroup_writes_applied(tmp_path):
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    summary, decisions = run(tmp_path, "percentile", sample_stream(15),
                             actuator=FakeCgroupActuator(cgroup))
    assert summary["writes"] > 0 and summary["failed_writes"] == 0
    written = int((cgroup / "memory.max").read_text())
    last_applied = [d["applied_mib"] for d in decisions if d["applied_mib"]][-1]
    assert written == pytest.approx(last_applied * MIB, rel=1e-6)


def test_senpai_session_targets_memory_high(tmp_path):
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    summary, decisions = run(tmp_path, "senpai",
                             sample_stream(15, high=220 * MIB),
                             actuator=FakeCgroupActuator(cgroup))
    assert all(d["target"] == "memory.high" for d in decisions)
    assert (cgroup / "memory.high").exists()
    assert not (cgroup / "memory.max").exists()


def test_stops_safely_when_target_exits(tmp_path):
    summary, decisions = run(tmp_path, "percentile",
                             sample_stream(10, end_reason="target_exited"))
    assert summary["end_reason"] == "target:target_exited"
    assert summary["steps"] == len(decisions)


def test_failed_writes_recorded_not_raised(tmp_path):
    actuator = FakeCgroupActuator(tmp_path / "never-created")
    summary, decisions = run(tmp_path, "percentile", sample_stream(15),
                             actuator=actuator)
    assert summary["failed_writes"] > 0
    failures = [d for d in decisions if d["write"] and not d["write"]["ok"]]
    assert failures and failures[0]["write"]["error"]


def test_dry_run_touches_nothing(tmp_path):
    actuator = DryRunActuator()
    summary, decisions = run(tmp_path, "fixed",
                             sample_stream(10, current_fn=lambda i: 50.0),
                             actuator=actuator)
    assert summary["dry_run"] is True
    assert all(w.dry_run for w in actuator.writes)


def test_rate_limited_steps_do_not_write(tmp_path):
    safety = SafetyConfig(floor_mib=8, min_limit_mib=32, max_limit_mib=1024,
                          max_step_up_mib=1e9, max_step_down_mib=1e9,
                          hysteresis_mib=0.5, min_write_interval_s=4)
    summary, decisions = run(tmp_path, "percentile",
                             sample_stream(20), safety=safety)
    limited = [d for d in decisions if d["rate_limited"]]
    assert limited, "expected some rate-limited steps at 1s samples / 4s min interval"
    assert all(d["applied_mib"] is None for d in limited)
    assert summary["writes"] < summary["steps"]


def test_initial_limits_recorded_for_restore(tmp_path):
    summary, _ = run(tmp_path, "percentile", sample_stream(12))
    assert summary["initial_limits"]["memory.max"] == str(256 * MIB)
    assert summary["initial_limits"]["memory.high"] == "max"
