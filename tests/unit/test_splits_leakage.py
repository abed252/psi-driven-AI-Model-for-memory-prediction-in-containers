"""Run-level split assignment and leakage protection."""

import pytest

from psi_memory.dataset.splits import assign_splits, load_manifest, save_manifest, validate_assignment

FRACTIONS = {"train": 0.6, "val": 0.2, "test": 0.2}


def make_runs(per_workload: dict[str, int]) -> list[tuple[str, str]]:
    return [(f"{wl}-{i:02d}", wl) for wl, n in per_workload.items()
            for i in range(n)]


def test_every_run_in_exactly_one_split():
    runs = make_runs({"steady": 5, "leak": 5, "bursty": 4})
    assignment = assign_splits(runs, FRACTIONS, seed=42)
    assigned = assignment["train"] + assignment["val"] + assignment["test"]
    assert sorted(assigned) == sorted(r[0] for r in runs)
    assert len(set(assigned)) == len(assigned)


def test_stratified_each_workload_in_each_split():
    runs = make_runs({"steady": 4, "leak": 4, "bursty": 4, "file_burst": 4})
    assignment = assign_splits(runs, FRACTIONS, seed=7)
    for split in ("train", "val", "test"):
        workloads = {run_id.rsplit("-", 1)[0] for run_id in assignment[split]}
        assert workloads == {"steady", "leak", "bursty", "file_burst"}, \
            f"{split} missing workloads"


def test_deterministic_for_seed():
    runs = make_runs({"steady": 6, "leak": 6})
    assert assign_splits(runs, FRACTIONS, 42) == assign_splits(runs, FRACTIONS, 42)
    assert assign_splits(runs, FRACTIONS, 42) != assign_splits(runs, FRACTIONS, 43)


def test_two_runs_never_gives_empty_train():
    assignment = assign_splits(make_runs({"steady": 2}), FRACTIONS, 1)
    assert len(assignment["train"]) == 1
    assert len(assignment["test"]) == 0  # honest: not enough runs for test


def test_duplicate_assignment_detected():
    with pytest.raises(ValueError, match="LEAKAGE"):
        validate_assignment({"train": ["r1", "r2"], "val": ["r1"], "test": []})


def test_manifest_round_trip(tmp_path):
    assignment = assign_splits(make_runs({"steady": 3, "leak": 3}), FRACTIONS, 42)
    path = tmp_path / "splits.json"
    save_manifest(assignment, 42, FRACTIONS, path)
    assert load_manifest(path) == assignment


def test_bad_fractions_rejected():
    with pytest.raises(ValueError, match="sum to 1"):
        assign_splits(make_runs({"steady": 3}), {"train": 0.9, "val": 0.2,
                                                 "test": 0.2}, 1)
