"""Live-container controller tests (docker-marked): dry-run writes nothing;
live percentile / Senpai-style write and then restore original limits."""

import pytest

from psi_memory.common.units import parse_cgroup_scalar
from psi_memory.controller.loop import run_live
from psi_memory.environment import probe

pytestmark = pytest.mark.docker

MIB = 1024 * 1024

CONFIG = {
    "controller": {"interval_s": 0.5, "history_samples": 6},
    "safety": {"floor_mib": 16, "min_limit_mib": 32, "max_limit_mib": 1024,
               "max_step_up_mib": 256, "max_step_down_mib": 128,
               "hysteresis_mib": 1, "min_write_interval_s": 1},
    "percentile": {"percentile": 100, "margin_frac": 0.20},
    "senpai": {"target_stall_ms": 10, "step_frac": 0.05,
               "min_frac_of_usage": 0.5},
}


@pytest.fixture()
def steady_container():
    name = probe.start_temp_container(memory_limit="256m",
                                      name_prefix="psi-ctl-itest")
    yield name
    probe.stop_container(name)


def read_limit(name, filename="memory.max"):
    return parse_cgroup_scalar(
        probe.exec_read_files(name, [filename])[filename])


def test_dry_run_changes_nothing(steady_container, tmp_path):
    before = read_limit(steady_container)
    summary = run_live(steady_container, "percentile", CONFIG,
                       duration_s=8, live=False, out_root=tmp_path)
    assert summary["dry_run"] is True
    assert summary["steps"] > 0
    assert read_limit(steady_container) == before  # untouched
    assert (tmp_path / summary["session_id"] / "decisions.jsonl").exists()


def test_live_percentile_writes_and_restores(steady_container, tmp_path):
    before = read_limit(steady_container)
    summary = run_live(steady_container, "percentile", CONFIG,
                       duration_s=10, live=True, out_root=tmp_path)
    assert summary["writes"] > summary["failed_writes"]
    # The sleeping container uses ~2 MiB; p100+20% is far below 256m, so the
    # limit was genuinely changed during the session...
    assert summary["restored"]["memory.max"]["ok"], summary["restored"]
    # ...and restored afterwards.
    assert read_limit(steady_container) == before


def test_live_senpai_writes_memory_high_and_restores(steady_container, tmp_path):
    before_high = read_limit(steady_container, "memory.high")  # None = "max"
    summary = run_live(steady_container, "senpai", CONFIG,
                       duration_s=10, live=True, out_root=tmp_path)
    assert summary["writes"] > 0
    assert summary["failed_writes"] == 0
    assert summary["restored"]["memory.high"]["ok"], summary["restored"]
    assert read_limit(steady_container, "memory.high") == before_high
    assert read_limit(steady_container) == 256 * MIB  # memory.max untouched
