"""The sampler script tested against a fake cgroup directory (no Docker)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SAMPLER_PATH = Path(__file__).parents[2] / "workloads" / "sampler.py"


@pytest.fixture()
def sampler():
    spec = importlib.util.spec_from_file_location("sampler", SAMPLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def fake_cgroup(tmp_path):
    (tmp_path / "memory.current").write_text("104857600\n")
    (tmp_path / "memory.max").write_text("268435456\n")
    (tmp_path / "memory.high").write_text("max\n")
    (tmp_path / "memory.swap.current").write_text("512\n")
    (tmp_path / "memory.swap.max").write_text("268435456\n")
    (tmp_path / "memory.pressure").write_text(
        "some avg10=1.50 avg60=0.20 avg300=0.00 total=98765\n"
        "full avg10=0.10 avg60=0.00 avg300=0.00 total=123\n"
    )
    (tmp_path / "memory.events").write_text("low 0\nhigh 2\nmax 5\noom 1\noom_kill 1\n")
    (tmp_path / "memory.stat").write_text("anon 90000000\nfile 10000000\n")
    return tmp_path


def test_take_sample_full(sampler, fake_cgroup):
    sample = sampler.take_sample(str(fake_cgroup))
    assert sample["type"] == "sample"
    assert sample["current"] == 104857600
    assert sample["high"] == "max"          # preserved, not zeroed
    assert sample["swap_current"] == 512
    assert sample["pressure"]["some"]["avg10"] == 1.50
    assert sample["pressure"]["some"]["total"] == 98765
    assert sample["events"]["oom_kill"] == 1
    assert sample["stat"]["anon"] == 90000000
    assert sample["missing"] == []
    assert sample["mono"] > 0 and sample["wall"] > 0


def test_missing_files_reported(sampler, fake_cgroup):
    (fake_cgroup / "memory.swap.current").unlink()
    (fake_cgroup / "memory.stat").unlink()
    sample = sampler.take_sample(str(fake_cgroup))
    assert sample["swap_current"] is None
    assert sample["stat"] is None
    assert "memory.swap.current" in sample["missing"]
    assert "memory.stat" in sample["missing"]


def test_sample_is_json_serializable(sampler, fake_cgroup):
    sample = sampler.take_sample(str(fake_cgroup))
    round_tripped = json.loads(json.dumps(sample))
    assert round_tripped["current"] == sample["current"]


def test_cli_end_record_when_cgroup_missing(sampler, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv",
                        ["sampler.py", "--cgroup-dir", str(tmp_path / "gone"),
                         "--interval-s", "0.1", "--max-samples", "2"])
    with pytest.raises(SystemExit):
        sampler.main()
    lines = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    assert lines[0]["type"] == "header"
    assert lines[-1] == {"type": "end", "reason": "cgroup_dir_not_found"}
