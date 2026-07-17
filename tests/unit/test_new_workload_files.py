"""New Phase 5 assets: mixed workload registration and trace validity."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def test_mixed_workload_registered():
    from psi_memory.workloads.config import WORKLOAD_SCRIPTS

    assert WORKLOAD_SCRIPTS["mixed"] == "mixed.py"
    assert (ROOT / "workloads" / "mixed.py").exists()


def test_mixed_is_pressure_workload_for_quality_gates():
    from psi_memory.dataset.quality import PRESSURE_WORKLOADS

    assert "mixed" in PRESSURE_WORKLOADS


@pytest.mark.parametrize("trace", ["example_trace.csv", "spiky.csv",
                                   "plateau_steps.csv"])
def test_all_traces_parse(monkeypatch, trace):
    script = ROOT / "workloads" / "trace_replay.py"
    monkeypatch.syspath_prepend(str(script.parent))
    spec = importlib.util.spec_from_file_location("trace_replay", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    points = module.load_trace(str(ROOT / "workloads" / "traces" / trace))
    assert len(points) >= 5
    assert all(v >= 0 for _, v in points)
