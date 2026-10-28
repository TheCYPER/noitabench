"""Small seeded noise helpers (value noise, rank normalisation)."""

from __future__ import annotations

import numpy as np


def _upsample(
    grid: np.ndarray, sx: float, sy: float, shape: tuple[int, int], oy: float, ox: float
) -> np.ndarray:
    """Smoothstep interpolation of a coarse grid to ``shape`` (cell size ``sx`` x ``sy``)."""
    h, w = shape
    ys = (np.arange(h, dtype=np.float32) + oy) / sy
    xs = (np.arange(w, dtype=np.float32) + ox) / sx
    iy, ix = ys.astype(np.int64), xs.astype(np.int64)
    fy, fx = ys - iy, xs - ix
    fy = fy * fy * (3 - 2 * fy)
    fx = fx * fx * (3 - 2 * fx)
    top = grid[iy][:, ix] * (1 - fx)[None, :] + grid[iy][:, ix + 1] * fx[None, :]
    bot = grid[iy + 1][:, ix] * (1 - fx)[None, :] + grid[iy + 1][:, ix + 1] * fx[None, :]
    return top * (1 - fy)[:, None] + bot * fy[:, None]


def value_noise(
    shape: tuple[int, int],
    scale: float,
    rng: np.random.Generator,
    octaves: int = 1,
    stretch: float = 1.0,
) -> np.ndarray:
    """Smooth noise in [0, 1] (not exactly uniform) with features of ``scale`` pixels.

    ``stretch`` > 1 elongates the features horizontally (``scale * stretch`` wide, ``scale``
    tall): layered, strata-like patterns.
    """
    h, w = shape
    total = np.zeros(shape, dtype=np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        sc = max(2.0, scale / (2**o))
        scx = sc * stretch
        gh, gw = int(h / sc) + 4, int(w / scx) + 4
        grid = rng.random((gh, gw), dtype=np.float32)
        oy, ox = float(rng.uniform(0, sc)), float(rng.uniform(0, scx))
        total += amp * _upsample(grid, scx, sc, shape, oy, ox)
        norm += amp
        amp *= 0.5
    return np.clip(total / norm, 0.0, 1.0)


def rank_normalize(values: np.ndarray) -> np.ndarray:
    """Replace values by their rank in (0, 1): a uniform distribution, same order."""
    n = values.size
    out = np.empty(n, dtype=np.float32)
    if n == 0:
        return out
    order = np.argsort(values, kind="stable")
    out[order] = (np.arange(n, dtype=np.float32) + 0.5) / n
    return out


def noise_1d(length: int, period: float, rng: np.random.Generator) -> np.ndarray:
    """Smooth 1D noise in [-1, 1] with control points every ``period`` pixels."""
    n = int(length / period) + 3
    ctrl = rng.uniform(-1, 1, n)
    xs = np.arange(length) / period + rng.uniform(0, 1)
    i = np.floor(xs).astype(int)
    f = xs - i
    f = f * f * (3 - 2 * f)  # smoothstep
    return ctrl[i] * (1 - f) + ctrl[i + 1] * f
