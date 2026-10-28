"""Which three ingredients touch in a grid: where the simulation would mix a potion by itself.

The mixing rule of the simulation (``crates/sim/src/rules/recipe_mix.rs``) turns three cells into
a potion where three ingredients of one recipe meet: a cell of ingredient ``A`` with a 4-neighbour
of another ingredient ``N`` looks along its four axes through its own material, up to
``MIX_REACH`` cells, and notes the first cell that is not ``A`` in each direction; if the third
ingredient ``C`` of a recipe ``{A, N, C}`` is among them, the three cells become the potion.

A generated world must hold no such meeting for *any* triple, because the rule seed, and with it
the recipes, never changes the terrain (contracts section 10): a world where sand, coal and
gunpowder touch would hand out a potion at frame 0 for every rule seed whose recipes include
those three. ``touching_triples`` finds the meetings; ``alchemy_checks.py`` fails the world.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .materials import Materials

MIX_REACH = 6  # crates/sim/src/consts.rs
AXES = ((1, 0), (-1, 0), (0, 1), (0, -1))  # (dx, dy)


def _ingredient_codes(grid: np.ndarray, mats: Materials, ingredients: Sequence[str]) -> np.ndarray:
    """Per cell: the index of its material in ``ingredients``, or -1 if it is none of them."""
    table = np.full(256, -1, dtype=np.int8)
    for i, key in enumerate(ingredients):
        table[mats[key]] = i
    return table[grid]


def _contact_cells(code: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rows and columns of the ingredient cells with a 4-neighbour of another ingredient."""
    inner = code[1:-1, 1:-1]
    touching = np.zeros(inner.shape, dtype=bool)
    for dx, dy in AXES:
        nb = code[1 + dy : code.shape[0] - 1 + dy, 1 + dx : code.shape[1] - 1 + dx]
        touching |= (inner >= 0) & (nb >= 0) & (nb != inner)
    ys, xs = np.nonzero(touching)
    return ys + 1, xs + 1


def _first_foreign(
    grid: np.ndarray, code: np.ndarray, ys: np.ndarray, xs: np.ndarray, dx: int, dy: int
) -> np.ndarray:
    """Per cell ``(ys, xs)``: the ingredient index of the first cell of another material along
    ``(dx, dy)`` within ``MIX_REACH`` (-1 if that cell is no ingredient or none lies within reach).
    Cells outside the grid count as a wall (no ingredient)."""
    h, w = grid.shape
    own = grid[ys, xs]
    found = np.full(len(ys), -1, dtype=np.int8)
    open_ = np.ones(len(ys), dtype=bool)
    for k in range(1, MIX_REACH + 1):
        yy, xx = ys + dy * k, xs + dx * k
        inside = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
        cy, cx = np.clip(yy, 0, h - 1), np.clip(xx, 0, w - 1)
        foreign = open_ & (~inside | (grid[cy, cx] != own))
        found[foreign & inside] = code[cy, cx][foreign & inside]
        open_ &= ~foreign
    return found


def touching_triples(
    grid: np.ndarray, mats: Materials, ingredients: Sequence[str]
) -> dict[tuple[str, str, str], tuple[int, int]]:
    """Every triple of ingredient materials the mixing rule would turn into a potion if it were
    a recipe, as ``{(a, b, c): (x, y)}`` with the keys sorted by ``ingredients`` order and the
    position of one cell where they meet. Empty if no three ingredients touch."""
    code = _ingredient_codes(grid, mats, ingredients)
    ys, xs = _contact_cells(code)
    if len(ys) == 0:
        return {}
    here = code[ys, xs].astype(np.int64)
    seen = [_first_foreign(grid, code, ys, xs, dx, dy).astype(np.int64) for dx, dy in AXES]
    h, w = grid.shape
    found: dict[int, tuple[int, int]] = {}
    for a, (dx, dy) in enumerate(AXES):
        nb = code[np.clip(ys + dy, 0, h - 1), np.clip(xs + dx, 0, w - 1)].astype(np.int64)
        contact = (nb >= 0) & (nb != here)
        for e in range(len(AXES)):
            third = seen[e]
            hit = contact & (e != a) & (third >= 0) & (third != here) & (third != nb)
            bits = (1 << here[hit]) | (1 << nb[hit]) | (1 << third[hit])
            keys, first = np.unique(bits, return_index=True)
            for key, i in zip(keys.tolist(), first.tolist()):
                found.setdefault(key, (int(xs[hit][i]), int(ys[hit][i])))
    return {
        tuple(ingredients[i] for i in range(len(ingredients)) if key >> i & 1): pos  # type: ignore[misc]
        for key, pos in sorted(found.items())
    }
