"""Ambient hazards (hazards.py): sealed pockets that leave a cue."""

from __future__ import annotations

import numpy as np
import pytest
from noitabench.worldgen import hazards as hz
from noitabench.worldgen.canvas import Canvas
from noitabench.worldgen.rest import mobile_cells

W, H = 200, 160


def _world(mats, solid="ground") -> Canvas:
    c = Canvas(W, H, mats)
    c.grid[:] = mats[solid]
    c.carve_rect((20, 40, 180, 110), force=True)  # a wide cave with flat floor and ceiling
    return c


def _ctx(c: Canvas, seed=1) -> hz.Ctx:
    return hz.Ctx(c, (0, 0, W, H), np.random.default_rng(seed))


def _neighbours(mask: np.ndarray) -> np.ndarray:
    out = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out |= np.roll(np.roll(mask, dy, 0), dx, 1)
    return out & ~mask


LAVA = {"per_10k": 120.0, "w": [8, 14], "depth": [5, 8], "crust": [2, 3]}
POCKET = {"per_10k": 120.0, "w": [14, 24], "h": [5, 8], "crust": [3, 4]}
PIT = {"per_10k": 120.0, "w": [12, 20], "depth": [12, 18]}


@pytest.mark.parametrize("solid, crust", [("ground", "rock"), ("rock", "ground")])
def test_lava_is_sealed_under_a_crust_of_the_other_material(mats, solid, crust):
    c = _world(mats, solid)
    assert hz.lava_crust(_ctx(c), LAVA) >= 1
    lava = c.grid == mats["lava"]
    assert lava.sum() >= 20
    touching = c.grid[_neighbours(lava)]
    assert set(np.unique(touching)) <= {mats[solid], mats[crust]}  # nothing open, nothing else
    # the cue: a crust of the contrasting material between the cave floor and the lava
    cols = np.nonzero(lava.any(axis=0))[0]
    x = int(cols[len(cols) // 2])
    top = int(np.nonzero(lava[:, x])[0].min())
    assert c.grid[top - 1, x] == mats[crust] and c.grid[top - 2, x] == mats[crust]
    assert 2 <= int((c.grid[:top, x] == mats[crust]).sum()) <= 3
    floor = 110
    assert (c.grid[floor : floor + 2, 2:10] == mats[solid]).all()  # elsewhere the floor is plain


def test_a_sand_pocket_hangs_over_the_cave_behind_a_thin_crust(mats):
    c = _world(mats)
    assert hz.sand_pocket(_ctx(c), POCKET) >= 1
    sand = c.grid == mats["sand"]
    assert sand.sum() >= 40
    ys, xs = np.nonzero(sand)
    assert ys.max() < 40  # above the cave ceiling (row 40)
    around = c.grid[_neighbours(sand)]
    assert set(np.unique(around)) <= {mats["ground"], mats["rock"]}  # sealed in
    x = int(xs[len(xs) // 2])
    below = int(np.nonzero(sand[:, x])[0].max())
    crust = c.grid[below + 1 : 40, x]
    assert 3 <= len(crust) <= 4 and (crust == mats["rock"]).all()  # contrasting crust


def test_a_sand_pit_is_flush_with_the_floor_and_sealed(mats):
    c = _world(mats)
    assert hz.sand_pit(_ctx(c), PIT) >= 1
    sand = c.grid == mats["sand"]
    assert sand.sum() >= 100
    ys, xs = np.nonzero(sand)
    assert ys.min() == 110  # the top of the sand is the floor level
    assert set(np.unique(c.grid[_neighbours(sand)])) <= {mats["ground"], mats.air, mats["rock"]}
    above = c.grid[ys.min() - 1, xs.min() : xs.max() + 1]
    assert (above == mats.air).all()  # open to the cave: dig it and it flows
    side_cells = _neighbours(sand) & (np.arange(H)[:, None] > ys.min())
    assert not (c.grid[side_cells] == mats.air).any()


def test_a_crust_that_blends_into_the_floor_beside_it_is_no_cue(mats):
    c = _world(mats)  # ground all around, the cave floor at row 110
    s = hz._surface(c, (c.grid, c.protected), 100, 109, 12)
    assert s is not None and s.old == mats["ground"]
    assert not hz._crust_blends_in(c, s)  # rock on ground: the crust stands out
    c.grid[110, s.x0 - 1] = c.grid[110, s.x1] = mats["rock"]
    assert hz._crust_blends_in(c, s)  # rock beside it too: nobody would see it
    c.grid[110, s.x1] = mats["ground"]
    assert not hz._crust_blends_in(c, s)  # one side different is enough


def test_hazards_leave_nothing_that_falls(mats):
    c = _world(mats)
    ctx = _ctx(c)
    hz.lava_crust(ctx, LAVA)
    hz.sand_pocket(ctx, POCKET)
    hz.sand_pit(ctx, PIT)
    g = c.grid
    assert not len(mobile_cells(g, mats, "powder")[0])
    assert not len(mobile_cells(g, mats, "liquid")[0])  # nothing slides or runs out
    assert (g == mats["sand"]).sum() > 100 and (g == mats["lava"]).sum() > 20


def test_hazards_avoid_protected_cells_and_uneven_floors(mats):
    c = _world(mats)
    c.protect((0, 0, W, H))
    ctx = _ctx(c)
    assert hz.lava_crust(ctx, LAVA) == hz.sand_pocket(ctx, POCKET) == hz.sand_pit(ctx, PIT) == 0
    rough = _world(mats)
    rough.grid[110:117, 20:180:2] = mats.air  # a floor with deep teeth: no flat stretch
    assert hz.sand_pit(_ctx(rough), PIT) == 0


def test_hazards_are_deterministic(mats):
    a, b = _world(mats), _world(mats)
    hz.lava_crust(_ctx(a, 5), LAVA)
    hz.lava_crust(_ctx(b, 5), LAVA)
    assert np.array_equal(a.grid, b.grid)


def test_place_hazards_runs_what_the_biome_lists(bm, mats):
    c = _world(mats)
    biome = bm.biomes["lava_deeps"]
    counts = hz.place_hazards(c, biome, (0, 0, W, H), np.random.default_rng(3))
    assert set(counts) == set(biome.hazards)
    assert hz.place_hazards(c, bm.biomes["workshop"], (0, 0, W, H), np.random.default_rng(3)) == {}
