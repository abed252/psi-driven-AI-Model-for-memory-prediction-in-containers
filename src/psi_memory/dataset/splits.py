"""Run-level train/validation/test splits.

Splitting happens at the granularity of complete runs — never individual
windows — which is the project's primary leakage defense. Assignment is
deterministic from the seed and stratified by workload so every split sees
every workload when enough runs exist.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from psi_memory.common.seed import derive_seed

log = logging.getLogger(__name__)

SPLITS = ("train", "val", "test")


def assign_splits(
    runs: list[tuple[str, str]],  # (run_id, workload)
    fractions: dict[str, float],
    seed: int,
) -> dict[str, list[str]]:
    """Assign whole runs to splits, stratified by workload.

    Guarantees: every run in exactly one split; train is never empty for a
    workload; with >= 3 runs of a workload, each split gets at least one.
    """
    if abs(sum(fractions[s] for s in SPLITS) - 1.0) > 1e-6:
        raise ValueError(f"split fractions must sum to 1: {fractions}")
    import random

    rng = random.Random(derive_seed(seed, "split"))
    by_workload: dict[str, list[str]] = defaultdict(list)
    for run_id, workload in sorted(runs):
        by_workload[workload].append(run_id)

    assignment: dict[str, list[str]] = {s: [] for s in SPLITS}
    for workload in sorted(by_workload):
        run_ids = by_workload[workload]
        rng.shuffle(run_ids)
        n = len(run_ids)
        if n >= 3:
            n_test = max(1, round(fractions["test"] * n))
            n_val = max(1, round(fractions["val"] * n))
            n_train = n - n_val - n_test
            if n_train < 1:
                n_train, n_val, n_test = n - 2, 1, 1
        elif n == 2:
            n_train, n_val, n_test = 1, 1, 0
            log.warning("workload %s has 2 runs: test split gets none", workload)
        else:
            n_train, n_val, n_test = 1, 0, 0
            log.warning("workload %s has 1 run: only train gets it", workload)
        assignment["train"].extend(run_ids[:n_train])
        assignment["val"].extend(run_ids[n_train:n_train + n_val])
        assignment["test"].extend(run_ids[n_train + n_val:])

    validate_assignment(assignment)
    return assignment


def validate_assignment(assignment: dict[str, list[str]]) -> None:
    """A run appearing in two splits is data leakage — hard error."""
    seen: dict[str, str] = {}
    for split, run_ids in assignment.items():
        for run_id in run_ids:
            if run_id in seen:
                raise ValueError(
                    f"LEAKAGE: run {run_id} in both {seen[run_id]} and {split}"
                )
            seen[run_id] = split


def save_manifest(assignment: dict[str, list[str]], seed: int,
                  fractions: dict[str, float], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"seed": seed, "fractions": fractions, "splits": assignment},
        indent=2), encoding="utf-8")


def load_manifest(path: Path) -> dict[str, list[str]]:
    assignment = json.loads(path.read_text(encoding="utf-8"))["splits"]
    validate_assignment(assignment)
    return assignment
