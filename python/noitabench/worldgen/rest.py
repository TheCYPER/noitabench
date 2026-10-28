"""Rest rules at frame 0: which powder and liquid cells the simulation would move at once.

The simulation (``crates/sim/src/rules/powder.rs`` and ``liquid.rs``, SIM-R31..R33) lets a
powder or liquid cell fall straight down, then slide into either lower diagonal, and a liquid
also hops sideways. A mover may enter air, gas and fire, and a *lighter* liquid (a denser
cell sinks into it). A cell that can do none of this is at rest.

The checks and the settling pass use these rules and nothing else, so what the generator
guarantees is what the simulation does: a world that passes starts without a landslide and
without a pool running dry. Looking only straight down is not enough: a pool with a one-cell
diagonal gap in its corner drains completely, and a sand heap on a steep slope slides.

Cells on the outer edge of the grid are not examined (the generator makes the edge rock).
"""

from __future__ import annotations

import numpy as np

from .materials import KIND_CODES, Materials

SIM_FREE_KINDS = ("air", "gas", "fire")  # what a moving cell can enter without a density test


def free_table(mats: Materials) -> np.ndarray:
    """Boolean per material: air, gas or fire."""
    return np.isin(mats.kind_code, [KIND_CODES[k] for k in SIM_FREE_KINDS])


def _enterable(mats: Materials, free: np.ndarray, target: np.ndarray, density: np.ndarray):
    """True where a mover of ``density`` can enter the cell ``target`` (material ids)."""
    liquid = mats.kind_code[target] == KIND_CODES["liquid"]
    return free[target] | (liquid & (mats.density[target] < density))


def mobile_cells(grid: np.ndarray, mats: Materials, kind: str) -> tuple[np.ndarray, np.ndarray]:
    """Rows and columns of the ``kind`` ("powder" or "liquid") cells that would move."""
    h, w = grid.shape
    ys, xs = np.nonzero(mats.kind_mask(grid, kind))
    keep = (xs >= 1) & (xs < w - 1) & (ys < h - 1)
    ys, xs = ys[keep], xs[keep]
    density = mats.density[grid[ys, xs]]
    free = free_table(mats)
    mobile = np.zeros(len(ys), dtype=bool)
    for dx in (0, -1, 1):  # below, then the two lower diagonals
        mobile |= _enterable(mats, free, grid[ys + 1, xs + dx], density)
    if kind == "liquid":  # a liquid also hops into free cells beside it
        for dx in (-1, 1):
            mobile |= free[grid[ys, xs + dx]]
    return ys[mobile], xs[mobile]


def mobile_mask(grid: np.ndarray, mats: Materials, kind: str) -> np.ndarray:
    """Boolean mask of the ``kind`` cells that would move (see ``mobile_cells``)."""
    out = np.zeros(grid.shape, dtype=bool)
    out[mobile_cells(grid, mats, kind)] = True
    return out


def is_mobile(grid: np.ndarray, mats: Materials, x: int, y: int, kind: str) -> bool:
    """True if the cell ``(x, y)`` is a ``kind`` cell that would move (a 2 x 3 window suffices)."""
    window = grid[y : y + 2, max(0, x - 1) : x + 2]
    if window.shape != (2, 3) or x < 1:
        return False
    return len(mobile_cells(window, mats, kind)[0]) > 0
