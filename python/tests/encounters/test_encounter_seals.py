"""The roof and the bed of a sealed passage hold against what the player has early.

``routes.py`` proves on the grid that the rows just above and below a sealed passage are brick.
These tests show it in the simulation: the bomb (durability 11, radius 60) goes off all along the
passage and the rock above and below stays where it was, because the brick row stops every ray.
With that row made of rock the same blasts open the roof (the negative control), which is what a
digger who hovers up from the bank into a hole of the roof would do with a few digging bolts.
"""

from __future__ import annotations

import numpy as np
import pytest
from driver import start
from noitabench.worldgen.encounter_defs import load_encounters

BOMB = {"radius": 60, "ray_energy": 6_000_000, "max_durability": 11, "fire_percent": 0}
STRIDE_X, STRIDE_Y = 6, 4


def _blast_along(r, box) -> None:
    """The bomb at every free cell of a lattice inside ``box`` (world coordinates)."""
    x, y, w, h = box
    free = r.g.grid_array() == 0
    for by in range(y + 1, y + h - 1, STRIDE_Y):
        for bx in range(x + 1, x + w - 1, STRIDE_X):
            if free[by, bx]:
                r.g.blast(bx, by, **BOMB)


def _beyond(grid: np.ndarray, box) -> tuple[np.ndarray, np.ndarray]:
    """The cells above the row over ``box`` and below the row under it, in its columns."""
    x, y, w, h = box
    return grid[: y - 1, x : x + w], grid[y + h + 1 :, x : x + w]


CASES = [(eid, name) for eid, d in sorted(load_encounters().items()) for name in d.sealed]
LAVA_OR_POOL = [("E02", "river_gate"), ("E07", "lava_gate"), ("E23", "pool_gate")]


def test_every_sealed_passage_is_one_of_the_cases():
    assert {eid for eid, _ in CASES} == {"E02", "E07", "E16", "E22", "E23"}
    assert set(LAVA_OR_POOL) <= set(CASES)


@pytest.mark.parametrize("eid,name", CASES)
def test_the_bomb_along_a_sealed_passage_leaves_the_roof_and_the_bed_whole(eid, name):
    r = start(eid, 0, 0, settle=False)
    box = r.meta["regions"][name]
    before = r.g.grid_array()
    _blast_along(r, box)
    after = r.g.grid_array()
    assert (before != after).any(), "the blasts did nothing"
    for was, now in zip(_beyond(before, box), _beyond(after, box), strict=True):
        assert (was == now).all(), f"{int((was != now).sum())} cells of {eid} {name} changed"


@pytest.mark.parametrize("eid,name", LAVA_OR_POOL)
def test_with_rock_in_the_row_above_the_passage_the_same_blasts_open_the_roof(eid, name):
    r = start(eid, 0, 0, settle=False)
    x, y, w, _h = box = r.meta["regions"][name]
    r.g.fill_rect(x, y - 1, w, 1, "rock")
    before = r.g.grid_array()
    _blast_along(r, box)
    roof_before, _ = _beyond(before, box)
    roof_after, _ = _beyond(r.g.grid_array(), box)
    assert (roof_before != roof_after).sum() > 100, "a rock row does not stop the bomb"
