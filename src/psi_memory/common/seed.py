"""Deterministic random-seed utilities.

Every stochastic component of the project must obtain its seed through
these helpers so that runs are reproducible from the recorded base seed.
"""

from __future__ import annotations

import hashlib
import random


def derive_seed(base_seed: int, *scope: str | int) -> int:
    """Derive a stable sub-seed from a base seed and a scope path.

    Example: derive_seed(42, "workload", "leak", 3) always yields the same
    value, and different scopes yield independent values.
    """
    material = ":".join([str(base_seed), *map(str, scope)])
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def seed_everything(seed: int) -> int:
    """Seed all random generators used by the project.

    NumPy and PyTorch are seeded only if they are installed (they arrive in
    later phases); the stdlib generator is always seeded.
    """
    random.seed(seed)
    try:
        import numpy

        numpy.random.seed(seed % (2**32))
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(seed)
    except ImportError:
        pass
    return seed
