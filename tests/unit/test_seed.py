import random

from psi_memory.common.seed import derive_seed, seed_everything


def test_derive_seed_is_deterministic():
    assert derive_seed(42, "workload", "leak", 3) == derive_seed(42, "workload", "leak", 3)


def test_derive_seed_differs_by_scope_and_base():
    base = derive_seed(42, "workload", "leak", 3)
    assert base != derive_seed(42, "workload", "leak", 4)
    assert base != derive_seed(43, "workload", "leak", 3)


def test_seed_everything_makes_stdlib_reproducible():
    seed_everything(1234)
    first = [random.random() for _ in range(5)]
    seed_everything(1234)
    second = [random.random() for _ in range(5)]
    assert first == second
