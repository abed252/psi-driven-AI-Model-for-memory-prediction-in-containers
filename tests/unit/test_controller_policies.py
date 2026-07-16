"""Policy proposal math + online/offline signal parity + fake-cgroup writes."""

import numpy as np
import pytest

from psi_memory.controller.actuator import FakeCgroupActuator
from psi_memory.controller.policies import (
    FixedPolicy,
    PercentilePolicy,
    SenpaiPolicy,
    make_policy,
)
from psi_memory.controller.window import SignalWindow

MIB = 1024 * 1024


def make_sample(i, current_mib=100.0, high="max", stall_total_us=0):
    return {
        "type": "sample", "mono": 1000.0 + i, "wall": 2e9 + i, "missing": [],
        "current": int(current_mib * MIB), "max": 256 * MIB, "high": high,
        "swap_current": 0, "swap_max": 256 * MIB,
        "pressure": {"some": {"avg10": 0.0, "avg60": 0.0, "avg300": 0.0,
                              "total": stall_total_us},
                     "full": {"avg10": 0.0, "avg60": 0.0, "avg300": 0.0,
                              "total": stall_total_us // 2}},
        "events": {"oom": 0, "oom_kill": 0, "max": 0, "high": 0, "low": 0},
        "stat": {"anon": int(current_mib * 0.8 * MIB),
                 "file": int(current_mib * 0.2 * MIB)},
    }


def filled_window(n=6, current_fn=lambda i: 100.0, **kw):
    window = SignalWindow(history_samples=n)
    for i in range(n + 1):
        window.push(make_sample(i, current_mib=current_fn(i), **kw))
    assert window.ready
    return window


def test_fixed_policy_constant():
    policy = FixedPolicy({"limit_mib": 300})
    assert policy.propose(filled_window()).value_mib == 300


def test_percentile_policy_max_plus_margin():
    policy = PercentilePolicy({"percentile": 100, "margin_frac": 0.10})
    window = filled_window(6, current_fn=lambda i: 100.0 + 10 * i)
    proposal = policy.propose(window)
    # history = last 6 samples: i=1..6 -> 110..160; max=160; +10% = 176
    assert proposal.raw_prediction_mib == pytest.approx(160.0)
    assert proposal.value_mib == pytest.approx(176.0)
    assert proposal.target == "memory.max"


def test_senpai_squeezes_when_quiet():
    policy = SenpaiPolicy({"target_stall_ms": 10, "step_frac": 0.05,
                           "min_frac_of_usage": 0.5})
    window = filled_window(6, high=200 * MIB)  # zero stall everywhere
    proposal = policy.propose(window)
    assert proposal.target == "memory.high"
    assert proposal.value_mib == pytest.approx(190.0)  # 200 * (1 - 0.05)
    assert "squeeze" in proposal.detail


def test_senpai_relieves_under_pressure():
    policy = SenpaiPolicy({"target_stall_ms": 10, "step_frac": 0.05,
                           "min_frac_of_usage": 0.5})
    window = SignalWindow(6)
    for i in range(7):
        # 50 ms stall per tick accumulates in the cumulative total.
        window.push(make_sample(i, high=200 * MIB, stall_total_us=i * 50_000))
    proposal = policy.propose(window)
    assert proposal.value_mib == pytest.approx(210.0)  # 200 * 1.05
    assert "relief" in proposal.detail


def test_senpai_respects_usage_fraction_floor():
    policy = SenpaiPolicy({"target_stall_ms": 10, "step_frac": 0.9,
                           "min_frac_of_usage": 0.5})
    window = filled_window(6, current_fn=lambda i: 100.0, high=110 * MIB)
    proposal = policy.propose(window)
    assert proposal.value_mib == pytest.approx(50.0)  # 0.5 * usage


def test_online_signals_match_offline_builder(synth_raw):
    """The controller's window matrix must equal the dataset builder's."""
    from psi_memory.dataset.loader import load_run
    from psi_memory.dataset.signals import ALL_SIGNALS, compute_signals

    run_dir = synth_raw.add("leak-parity", workload="leak", n_samples=40,
                            current_fn=lambda i: 40 + 2 * i,
                            psi_avg10_fn=lambda i: i * 0.5)
    offline = compute_signals(load_run(run_dir))[ALL_SIGNALS].to_numpy(np.float32)

    import json

    window = SignalWindow(history_samples=39)
    with open(run_dir / "samples.jsonl", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if record.get("type") == "sample":
                window.push(record)
    online = window.matrix()
    np.testing.assert_allclose(online, offline[1:], rtol=1e-5)


def test_learned_policy_tabular_artifact(tmp_path):
    import joblib
    from sklearn.linear_model import LinearRegression
    from sklearn.preprocessing import StandardScaler

    from psi_memory.dataset.features import feature_columns

    columns = feature_columns(with_psi=True)
    rng = np.random.default_rng(0)
    X = rng.uniform(0, 1, (50, len(columns)))
    scaler = StandardScaler().fit(X)
    model = LinearRegression().fit(scaler.transform(X), np.full(50, 123.0))
    artifact = tmp_path / "m.joblib"
    joblib.dump({"model": model, "scaler": scaler, "feature_names": columns},
                artifact)

    policy = make_policy("learned", {"learned": {"margin_frac": 0.20}}, artifact)
    proposal = policy.propose(filled_window())
    assert proposal.raw_prediction_mib == pytest.approx(123.0, abs=1e-6)
    assert proposal.value_mib == pytest.approx(123.0 * 1.2, abs=1e-4)


def test_learned_mode_requires_artifact():
    with pytest.raises(ValueError, match="requires"):
        make_policy("learned", {}, None)


def test_fake_cgroup_actuator_roundtrip(tmp_path):
    actuator = FakeCgroupActuator(tmp_path)
    result = actuator.apply("memory.max", 256.0)
    assert result.ok
    assert (tmp_path / "memory.max").read_text().strip() == str(256 * MIB)


def test_fake_cgroup_actuator_records_failure(tmp_path):
    actuator = FakeCgroupActuator(tmp_path / "gone")
    result = actuator.apply("memory.max", 256.0)
    assert not result.ok
    assert result.error and "gone" in result.error
