"""Rest rules and settling (rest.py, settle.py): a world must not move when the sim starts."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from noitabench.worldgen import features, settle
from noitabench.worldgen.canvas import Canvas
from noitabench.worldgen.rest import is_mobile, mobile_cells, mobile_mask

LEGEND = {
    " ": "air",
    "#": "rock",
    "s": "sand",
    "c": "coal",
    "g": "gunpowder",
    "w": "water",
    "o": "oil",
    "l": "lava",
    "^": "flammable_gas",
}


def _grid(mats, rows: list[str]) -> np.ndarray:
    return np.array([[mats[LEGEND[ch]] for ch in row] for row in rows], dtype=np.uint8)


def _mobile(mats, rows: list[str], kind: str) -> set[tuple[int, int]]:
    ys, xs = mobile_cells(_grid(mats, rows), mats, kind)
    return set(zip(xs.tolist(), ys.tolist()))


def test_powder_on_a_flat_floor_is_at_rest(mats):
    rows = ["#####", "# s #", "#####"]
    assert _mobile(mats, rows, "powder") == set()


def test_powder_with_air_below_falls(mats):
    rows = ["#####", "# s #", "#   #", "#####"]
    assert _mobile(mats, rows, "powder") == {(2, 1)}


def test_powder_slides_off_a_step_through_the_lower_diagonal(mats):
    """Straight down is rock, but the lower right diagonal is free: the cell slides."""
    rows = ["######", "# s  #", "# ## #", "######"]
    assert _mobile(mats, rows, "powder") == {(2, 1)}


def test_a_heap_with_gentle_slopes_is_at_rest_and_a_steep_one_is_not(mats):
    gentle = ["#######", "#  s  #", "# sss #", "#sssss#", "#######"]
    column = ["#######", "#  s  #", "#  s  #", "#  s  #", "#  s  #", "#######"]
    assert _mobile(mats, gentle, "powder") == set()
    assert _mobile(mats, column, "powder") == {(3, 1), (3, 2), (3, 3)}  # all but the bottom one


def test_a_denser_powder_sinks_into_a_lighter_liquid_but_equal_density_does_not(mats):
    over_water = ["###", "#s#", "#w#", "###"]  # sand 6 > water 4
    over_lava = ["###", "#c#", "#l#", "###"]  # coal 6 == lava 6: never swaps
    gunpowder_on_lava = ["###", "#g#", "#l#", "###"]  # gunpowder 7 > lava 6
    assert _mobile(mats, over_water, "powder") == {(1, 1)}
    assert _mobile(mats, over_lava, "powder") == set()
    assert _mobile(mats, gunpowder_on_lava, "powder") == {(1, 1)}


def test_a_closed_pool_is_at_rest_with_its_top_open(mats):
    rows = ["#####", "#   #", "#www#", "#www#", "#####"]
    assert _mobile(mats, rows, "liquid") == set()


def test_a_liquid_runs_out_through_air_below_beside_or_diagonally(mats):
    below = ["#####", "# w #", "#   #", "#####"]
    beside = ["#####", "#w  #", "#####", "#####"]
    diagonal = ["#####", "#w###", "##  #", "#####"]  # only the lower right diagonal is free
    assert _mobile(mats, below, "liquid") == {(2, 1)}
    assert _mobile(mats, beside, "liquid") == {(1, 1)}
    assert _mobile(mats, diagonal, "liquid") == {(1, 1)}


def test_a_heavier_liquid_over_a_lighter_one_is_not_at_rest(mats):
    water_over_oil = ["###", "#w#", "#o#", "###"]
    oil_over_water = ["###", "#o#", "#w#", "###"]
    assert _mobile(mats, water_over_oil, "liquid") == {(1, 1)}
    assert _mobile(mats, oil_over_water, "liquid") == set()


def test_is_mobile_agrees_with_the_whole_grid_function(mats):
    g = _grid(mats, ["#######", "# s s #", "#  s  #", "#######"])
    mask = mobile_mask(g, mats, "powder")
    for y in range(g.shape[0]):
        for x in range(g.shape[1]):
            assert is_mobile(g, mats, x, y, "powder") == bool(mask[y, x]), (x, y)


# ---------------------------------------------------------------------------- settle


def _canvas(mats, rows: list[str]) -> Canvas:
    g = _grid(mats, rows)
    c = Canvas(g.shape[1], g.shape[0], mats)
    c.grid[:] = g
    return c


def test_a_heap_on_a_steep_slope_slides_to_rest_without_losing_grains(mats):
    rows = [
        "###########",
        "#         #",
        "#s        #",
        "#s        #",
        "#ss       #",
        "#ss       #",
        "###########",
    ]
    c = _canvas(mats, rows)
    before = int((c.grid == mats["sand"]).sum())
    counts = settle.settle(c)
    assert counts["slid"] > 0 and counts["removed"] == 0 and counts["to_rock"] == 0
    assert int((c.grid == mats["sand"]).sum()) == before
    assert not len(mobile_cells(c.grid, mats, "powder")[0])


def test_powder_that_would_sink_into_a_pool_vanishes(mats):
    rows = ["#######", "#     #", "#  s  #", "#wwwww#", "#######"]
    c = _canvas(mats, rows)
    counts = settle.settle(c)
    assert counts["removed"] == 1
    assert not (c.grid == mats["sand"]).any()
    assert (c.grid == mats["water"]).sum() == 5  # the pool itself is untouched


def test_powder_that_may_be_the_wall_of_a_pool_turns_to_rock(mats):
    rows = ["#######", "#     #", "#cwwww#", "# #####", "#######"]
    c = _canvas(mats, rows)  # the coal cell has air below it and water beside it
    settle.settle(c)
    assert c.grid[2, 1] == mats["rock"]  # it stays put as a wall instead of opening the pool
    assert (c.grid == mats["water"]).sum() == 4
    assert not len(mobile_cells(c.grid, mats, "powder")[0])
    assert not len(mobile_cells(c.grid, mats, "liquid")[0])  # the new rock closed the corner


def test_a_diagonal_gap_in_a_pool_corner_is_plugged_but_straight_leaks_are_not(mats):
    corner = _canvas(mats, ["#####", "#w###", "##  #", "#####"])
    assert settle.settle(corner)["plugged"] == 1
    assert not len(mobile_cells(corner.grid, mats, "liquid")[0])
    leak = _canvas(mats, ["#####", "# w #", "#   #", "#####"])
    assert settle.settle(leak)["plugged"] == 0
    assert len(mobile_cells(leak.grid, mats, "liquid")[0]) == 1


def test_protected_cells_are_never_plugged(mats):
    c = _canvas(mats, ["#####", "#w###", "##  #", "#####"])
    c.protected[2, 2] = True
    assert settle.settle(c)["plugged"] == 0


def test_a_world_comes_out_of_the_generator_at_rest(world_a, mats):
    assert not len(mobile_cells(world_a.grid, mats, "powder")[0])
    assert not len(mobile_cells(world_a.grid, mats, "liquid")[0])
    assert world_a.meta["settled"]["slid"] > 0  # the heaps did settle


# ----------------------------------------------------------------- where things are put


def _cave(mats, rect=(20, 40, 180, 90)) -> Canvas:
    c = Canvas(200, 130, mats)
    c.carve_rect(rect, force=True)
    return c


def test_a_basin_with_a_diagonal_leak_is_not_a_container(mats):
    """4-connected labelling would call this bowl closed; a liquid slips out diagonally."""
    c = _cave(mats, (60, 50, 80, 60))  # a bowl: floor row 60
    assert features.find_basin(c, 70, 57, 4, 5000) is not None
    c.grid[60, 80] = mats.air  # a pinhole touching the bowl's lower right corner ...
    c.grid[61:100, 80] = mats.air  # ... and a shaft running down out of the window
    assert features.find_basin(c, 70, 57, 4, 5000) is None


def _dense(biome, field: str):
    """The biome with a very high attempt rate for one feature style (pools, gas, piles)."""
    style = dataclasses.replace(
        getattr(biome, field), attempts_per_10k=400.0, max_area=5000, depth_min=2, depth_max=3
    )
    return dataclasses.replace(biome, **{field: style})


WORLD = (0, 0, 200, 130)


def _hall(mats, lava_pit: bool) -> Canvas:
    """A cave 100 wide with a flat floor at row 90, and optionally a lava-filled pit in it."""
    c = _cave(mats, (50, 40, 150, 90))
    if lava_pit:
        c.carve_rect((95, 90, 105, 94), force=True)
        c.fill_rect((95, 90, 105, 94), "lava", force=True)
    return c


def test_pools_keep_away_from_other_liquids(bm, mats):
    biome = _dense(bm.biomes["mine"], "pools")
    with_lava = _hall(mats, lava_pit=True)
    features.place_pools(with_lava, biome, WORLD, np.random.default_rng(1))
    assert (with_lava.grid == mats["lava"]).sum() == 40  # the lava is not touched ...
    other = mats.kind_mask(with_lava.grid, "liquid") & (with_lava.grid != mats["lava"])
    assert not other.any()  # ... and no pool of another liquid was put next to it
    plain = _hall(mats, lava_pit=False)  # the same hall without the pit takes pools
    assert features.place_pools(plain, biome, WORLD, np.random.default_rng(1)) > 0


def test_gas_pockets_keep_away_from_lava(bm, mats):
    biome = _dense(bm.biomes["lava_deeps"], "gas")
    near = _cave(mats, (50, 40, 150, 47))  # a low cave: the lava lies close under the ceiling
    near.grid[45:47, 50:150] = mats["lava"]
    far = _cave(mats, (50, 40, 150, 90))
    far.grid[88:90, 50:150] = mats["lava"]
    assert features.place_gas(near, biome, WORLD, np.random.default_rng(2)) == 0
    assert features.place_gas(far, biome, WORLD, np.random.default_rng(2)) > 0


def test_heaps_keep_away_from_liquids(bm, mats):
    biome = _dense(bm.biomes["brick_ruins"], "piles")
    c = _hall(mats, lava_pit=True)
    assert features.place_piles(c, biome, WORLD, np.random.default_rng(3)) > 0
    xs = np.nonzero(c.grid == mats["gunpowder"])[1]
    assert len(xs) > 0
    assert not ((xs >= 92) & (xs <= 107)).any()  # nothing within 3 cells of the pit (95..104)


def test_the_simulation_does_not_move_a_generated_world(world_a, mats, tmp_path):
    """The rules in rest.py are the simulation's own: nothing but gas moves in the first 200 frames."""
    core = pytest.importorskip("noitabench_core")
    png, js = world_a.write(tmp_path, "w", mats)
    env = core.Env.from_world(str(png), str(js), 1)
    if hasattr(env, "set_all_dirty"):
        env.set_all_dirty(True)  # no chunk may sleep through the test
    env.step_frames(200)
    after = np.frombuffer(env.grid(), dtype=np.uint8).reshape(world_a.grid.shape)
    gas = mats.kind_mask(world_a.grid, "gas")  # a gas pocket drifts and decays: not the point
    moved = (after != world_a.grid) & ~gas
    assert not moved.any(), np.argwhere(moved)[:5].tolist()
