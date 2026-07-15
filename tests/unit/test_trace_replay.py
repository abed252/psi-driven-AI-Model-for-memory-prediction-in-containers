"""Trace parsing and interpolation logic of the replay workload (no Docker)."""

import importlib.util
from pathlib import Path

import pytest

TRACE_SCRIPT = Path(__file__).parents[2] / "workloads" / "trace_replay.py"
EXAMPLE_TRACE = Path(__file__).parents[2] / "workloads" / "traces" / "example_trace.csv"


@pytest.fixture()
def replay(monkeypatch):
    # The script imports its sibling wl_common, so its directory must be
    # importable exactly as it is inside the container image (/app).
    monkeypatch.syspath_prepend(str(TRACE_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("trace_replay", TRACE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_trace_loads(replay):
    points = replay.load_trace(str(EXAMPLE_TRACE))
    assert len(points) >= 5
    assert points[0] == (0.0, 10.0)


def test_interpolation_midpoint(replay, tmp_path):
    trace = tmp_path / "t.csv"
    trace.write_text("0,100\n10,200\n")
    points = replay.load_trace(str(trace))
    assert replay.target_at(points, 5) == 150.0
    assert replay.target_at(points, 0) == 100.0
    assert replay.target_at(points, 10) == 200.0


def test_clamped_outside_range(replay, tmp_path):
    trace = tmp_path / "t.csv"
    trace.write_text("5,50\n10,80\n")
    points = replay.load_trace(str(trace))
    assert replay.target_at(points, 0) == 50.0     # before first point
    assert replay.target_at(points, 999) == 80.0   # after last point


def test_rejects_non_increasing_offsets(replay, tmp_path):
    trace = tmp_path / "t.csv"
    trace.write_text("0,10\n5,20\n5,30\n")
    with pytest.raises(ValueError, match="strictly increasing"):
        replay.load_trace(str(trace))


def test_rejects_malformed_line(replay, tmp_path):
    trace = tmp_path / "t.csv"
    trace.write_text("0,10\nbogus line\n")
    with pytest.raises(ValueError, match="expected"):
        replay.load_trace(str(trace))
