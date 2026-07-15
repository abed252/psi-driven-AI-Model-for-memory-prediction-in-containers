"""cgroup reader tested against a fake cgroup directory (no Docker needed)."""

from pathlib import Path

from psi_memory.collector.cgroup_reader import read_memory_snapshot

PSI_TEXT = (
    "some avg10=2.50 avg60=1.00 avg300=0.20 total=999000\n"
    "full avg10=0.10 avg60=0.05 avg300=0.00 total=1000\n"
)


def make_fake_cgroup(tmp_path: Path, **overrides) -> Path:
    files = {
        "memory.current": "104857600\n",
        "memory.max": "268435456\n",
        "memory.high": "max\n",
        "memory.swap.current": "0\n",
        "memory.swap.max": "268435456\n",
        "memory.pressure": PSI_TEXT,
        "memory.events": "low 0\nhigh 0\nmax 2\noom 1\noom_kill 1\noom_group_kill 0\n",
        "memory.stat": "anon 90000000\nfile 10000000\n",
    }
    files.update(overrides)
    for name, content in files.items():
        if content is not None:
            (tmp_path / name).write_text(content)
    return tmp_path


def test_full_snapshot(tmp_path):
    snap = read_memory_snapshot(make_fake_cgroup(tmp_path))
    assert snap.current_bytes == 104857600
    assert snap.max_bytes == 268435456
    assert snap.high_bytes is None
    assert "memory.high" in snap.unlimited_fields  # "max", not missing
    assert snap.swap_current_bytes == 0
    assert snap.pressure.some.avg10 == 2.50
    assert snap.pressure.full.total_us == 1000
    assert snap.events["oom_kill"] == 1
    assert snap.stat["anon"] == 90000000
    assert snap.missing_fields == []


def test_missing_files_are_reported_not_zeroed(tmp_path):
    snap = read_memory_snapshot(
        make_fake_cgroup(tmp_path, **{"memory.swap.current": None, "memory.stat": None})
    )
    assert snap.swap_current_bytes is None
    assert "memory.swap.current" in snap.missing_fields
    assert "memory.stat" in snap.missing_fields
    # A missing file must not appear as unlimited.
    assert "memory.swap.current" not in snap.unlimited_fields


def test_oom_events_visible(tmp_path):
    snap = read_memory_snapshot(make_fake_cgroup(tmp_path))
    assert snap.events["oom"] == 1
    assert snap.events["max"] == 2
