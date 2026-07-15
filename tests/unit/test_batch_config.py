import pytest

from psi_memory.workloads.config import load_batch_config

GOOD_YAML = """
defaults:
  base_seed: 7
  interval_s: 0.5
  image: psi-workloads:test
runs:
  - workload: steady
    repeats: 3
    duration_s: 60
    memory_limit: 256m
    memory_swap: 512m
    params: {working_set_mib: 64}
  - workload: leak
    duration_s: 90
    interval_s: 2.0
    memory_limit: 192m
    memory_swap: 384m
    memory_high: 128m
"""


def write_config(tmp_path, text):
    path = tmp_path / "batch.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_expansion_and_defaults(tmp_path):
    config = load_batch_config(write_config(tmp_path, GOOD_YAML))
    assert config.image == "psi-workloads:test"
    assert len(config.runs) == 4  # 3 steady repeats + 1 leak
    steady = config.runs[:3]
    assert all(s.workload == "steady" for s in steady)
    assert all(s.interval_s == 0.5 for s in steady)  # default interval
    leak = config.runs[3]
    assert leak.interval_s == 2.0  # per-entry override
    assert leak.memory_high == "128m"
    assert steady[0].memory_high is None


def test_repeats_get_distinct_deterministic_seeds(tmp_path):
    config1 = load_batch_config(write_config(tmp_path, GOOD_YAML))
    config2 = load_batch_config(write_config(tmp_path, GOOD_YAML))
    seeds1 = [s.seed for s in config1.runs]
    seeds2 = [s.seed for s in config2.runs]
    assert seeds1 == seeds2                    # deterministic
    assert len(set(seeds1)) == len(seeds1)     # all distinct


def test_workload_args_are_stable_and_dashified(tmp_path):
    config = load_batch_config(write_config(tmp_path, GOOD_YAML))
    args = config.runs[0].workload_args()
    assert args[:4] == ["--duration-s", "60.0", "--seed", str(config.runs[0].seed)]
    assert "--working-set-mib" in args


def test_unknown_workload_rejected(tmp_path):
    bad = GOOD_YAML.replace("workload: leak", "workload: fork_bomb")
    with pytest.raises(ValueError, match="unknown workload"):
        load_batch_config(write_config(tmp_path, bad))


def test_missing_required_field_rejected(tmp_path):
    bad = GOOD_YAML.replace("    memory_swap: 384m\n", "")
    with pytest.raises(ValueError, match="memory_swap"):
        load_batch_config(write_config(tmp_path, bad))
