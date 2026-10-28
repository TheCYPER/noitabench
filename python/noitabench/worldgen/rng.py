"""Deterministic randomness for the world generator.

Everything is derived from integers with a SplitMix64-style mixer written in
plain Python integers, so results do not depend on ``PYTHONHASHSEED``, the
platform or the order in which things are generated (DET-R04: named streams).
"""

from __future__ import annotations

import hashlib
from functools import cache

import numpy as np

MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


def mix64(*values: int) -> int:
    """Mix integers into one well-distributed 64-bit integer."""
    h = _GOLDEN
    for v in values:
        h ^= int(v) & MASK64
        h = (h + _GOLDEN) & MASK64
        h = ((h ^ (h >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        h = ((h ^ (h >> 27)) * 0x94D049BB133111EB) & MASK64
        h ^= h >> 31
    return h


@cache
def name_key(name: str) -> int:
    """Stable 64-bit key of a stream name (``worldgen/tiles`` and so on)."""
    return int.from_bytes(hashlib.blake2b(name.encode(), digest_size=8).digest(), "little")


def unit(*values: int) -> float:
    """Stateless uniform number in [0, 1) from integers."""
    return mix64(*values) / float(1 << 64)


def stream(seed: int, name: str, *keys: int) -> np.random.Generator:
    """Independent numpy generator for ``(seed, name, keys...)``."""
    return np.random.Generator(np.random.PCG64(mix64(seed, name_key(name), *keys)))


def pick_weighted(u: float, weights: list[float]) -> int:
    """Index chosen by ``u`` in [0, 1) from non-negative ``weights``."""
    total = float(sum(weights))
    target = u * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if target < acc:
            return i
    return len(weights) - 1
