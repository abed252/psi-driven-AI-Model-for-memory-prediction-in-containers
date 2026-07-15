"""Phase 0 completion gate: a temporary container can be started and its
memory.current and memory.pressure sampled reliably."""

import pytest

from psi_memory.collector.parsers import parse_psi
from psi_memory.common.units import parse_cgroup_scalar
from psi_memory.environment import probe

pytestmark = pytest.mark.docker


def test_exec_read_inside_container(temp_container):
    contents = probe.exec_read_files(temp_container)
    assert contents["memory.current"] is not None
    assert parse_cgroup_scalar(contents["memory.current"]) > 0
    sample = parse_psi(contents["memory.pressure"])
    assert sample.some.total_us >= 0
    assert sample.full is not None  # memory controller always has `full`
    assert contents["memory.events"] is not None
    assert contents["memory.stat"] is not None


def test_sidecar_sampling_reliable(temp_container):
    samples = probe.sidecar_sample(temp_container, num_samples=5, interval_s=0.5)
    assert len(samples) == 5
    uptimes = [s.uptime_s for s in samples]
    assert all(b > a for a, b in zip(uptimes, uptimes[1:])), "non-monotonic timestamps"
    # ~0.5 s spacing, generous tolerance for VM scheduling.
    gaps = [b - a for a, b in zip(uptimes, uptimes[1:])]
    assert all(0.2 < g < 3.0 for g in gaps), f"sampling gaps out of tolerance: {gaps}"
    assert all(s.current_bytes > 0 for s in samples)


def test_dynamic_memory_max_update(temp_container):
    probe.update_memory_limit(temp_container, "512m", "1g")
    after = parse_cgroup_scalar(
        probe.exec_read_files(temp_container, ["memory.max"])["memory.max"]
    )
    assert after == 512 * 2**20
    probe.update_memory_limit(temp_container, "256m", "512m")


def test_memory_high_write_and_restore(temp_container):
    probe.sidecar_write_memory_high(temp_container, str(128 * 2**20))
    high = parse_cgroup_scalar(
        probe.exec_read_files(temp_container, ["memory.high"])["memory.high"]
    )
    assert high == 128 * 2**20
    probe.sidecar_write_memory_high(temp_container, "max")
    restored = parse_cgroup_scalar(
        probe.exec_read_files(temp_container, ["memory.high"])["memory.high"]
    )
    assert restored is None
