"""Post-generation checks (checks.py): connectivity, dig budget, chokepoints, markers."""

from __future__ import annotations

import copy
import dataclasses

import numpy as np
import pytest
from noitabench.worldgen import checks
from noitabench.worldgen.checks import (
    dig_cost_table,
    is_chokepoint,
    run_checks,
    shortest_path,
)
from scipy.ndimage import label


def _mutated(world, grid=None, markers=None):
    return dataclasses.replace(
        world,
        grid=world.grid.copy() if grid is None else grid,
        markers=copy.deepcopy(world.markers) if markers is None else markers,
    )


def test_generated_worlds_pass_all_checks(world_a, world_b, bm, mats):
    for w in (world_a, world_b):
        rep = run_checks(w, bm, mats)
        assert rep.ok, rep.failures
        assert rep.stats["natural_connected"] is True
        assert len(rep.main_path) > 100
        for layer in ("1", "2", "3"):
            assert rep.stats["must_pass_chokepoints"][layer] >= 2


@pytest.mark.parametrize("thickness", [1, 2, 3, 4])
@pytest.mark.parametrize("offset", [0, 1, 2, 3])
def test_a_brick_slab_of_any_thickness_and_alignment_blocks_the_way(
    world_a, bm, mats, thickness, offset
):
    """Brick is never passable. Also slabs thinner than a coarse block must not be crossed
    (an averaging cost grid would let the route through)."""
    w = _mutated(world_a)
    y = 140 + offset  # top of the first layer, full width of the main biome
    w.grid[y : y + thickness, 256:512] = mats["brick"]
    rep = run_checks(w, bm, mats)
    assert not rep.ok
    assert any("digs" in f or "route" in f or "not connected" in f for f in rep.failures)


def test_a_thin_rock_wall_can_be_dug_but_a_thick_one_cannot(world_a, bm, mats, monkeypatch):
    def walled(rows):
        w = _mutated(world_a)
        w.grid[140 : 140 + rows, 256:512] = mats["rock"]
        return w

    # The estimate also counts the rock the walking route runs along (the route has to go through
    # every scene now, no tunnel round it), so the budget is set from a wall of two rows.
    base = run_checks(walled(2), bm, mats).stats["dig_cells"]
    monkeypatch.setattr(checks, "MAX_DIG_CELLS", base + 10)
    thin = run_checks(walled(6), bm, mats)
    assert thin.stats["natural_connected"] is False
    assert base < thin.stats["dig_cells"] <= base + 10  # every row of rock adds about one cell
    assert not any("digs" in f or "route" in f or "even if" in f for f in thin.failures)

    thick = _mutated(world_a)
    thick.grid[140:260, :] = mats["rock"]  # pockets included: no cheaper way round
    thick.markers = [
        m
        for m in thick.markers
        if not (m["type"] in ("spawn_enemy", "item") and 140 <= m["y"] < 260)
    ]
    rep = run_checks(thick, bm, mats)
    assert any("digs" in f for f in rep.failures)


def test_a_world_that_needs_digging_cannot_certify_its_must_pass_slots(world_a, bm, mats):
    """Without natural connectivity every rectangle would trivially "cut" start from target."""
    w = _mutated(world_a)
    w.grid[140:146, 256:512] = mats["rock"]
    rep = run_checks(w, bm, mats)
    assert any("chokepoints cannot be established" in f for f in rep.failures)
    assert rep.stats["must_pass_chokepoints"] == {"1": 0, "2": 0, "3": 0}


def test_the_seal_must_seal(world_a, bm, mats):
    seal = next(m for m in world_a.markers if m["type"] == "seal")
    assert run_checks(world_a, bm, mats).stats["seal_sealed"] is True
    leak = _mutated(world_a)
    # a 1-cell leak through the plug and the brick floor line of the front chamber above it
    leak.grid[seal["y"] - 1 : seal["y"] + seal["h"], seal["x"] + 5] = mats.air
    rep = run_checks(leak, bm, mats)
    assert any("reachable from the spawn" in f for f in rep.failures)
    # a plug of rock (diggable) instead of brick is no seal either
    soft = _mutated(world_a)
    soft.grid[seal["y"] - 1 : seal["y"] + seal["h"], seal["x"] : seal["x"] + seal["w"]] = mats[
        "rock"
    ]
    assert any("reachable from the spawn" in f for f in run_checks(soft, bm, mats).failures)


def _seal_of(world):
    return next(m for m in world.markers if m["type"] == "seal")


def test_nothing_deeper_than_the_plug_is_reachable_without_opening_it(world_a, world_b, bm, mats):
    """Every cell from the plug's top edge down to the bottom row is brick or the vault room.

    Checked independently of ``run_checks``: label the free-or-diggable cells 8-connected and
    follow the spawn's area. Before the band was bricked a digger tunnelled beside the vault down
    to the world's last row.
    """
    for w in (world_a, world_b):
        seal = _seal_of(w)
        top, room = seal["y"], seal["room"]
        deep = w.grid[top:]
        in_room = np.zeros(deep.shape, dtype=bool)
        in_room[
            room["y"] - top : room["y"] - top + room["h"], room["x"] : room["x"] + room["w"]
        ] = 1
        assert (deep[~in_room] == mats["brick"]).all()  # borders and the bottom row included
        passable = checks.passable_mask(w.grid, mats)
        lab, _ = label(passable, structure=np.ones((3, 3), dtype=bool))
        spawn = next(m for m in w.markers if m["type"] == "spawn_player")
        mine = lab == lab[spawn["y"], spawn["x"]]
        assert mine[spawn["y"], spawn["x"]] and not mine[top:].any()
        assert w.meta["seal_brick"] > 50_000
        rep = run_checks(w, bm, mats)
        assert rep.stats["seal_deep_cells"] == 0
        assert rep.stats["deepest_reach_y"] < top
        assert rep.stats["seal_sealed"] is True


def test_with_the_plug_open_the_room_and_only_the_room_is_reached(world_a, bm, mats):
    """The positive control of the seal check: the cut is not vacuous."""
    rep = run_checks(world_a, bm, mats)
    assert rep.stats["seal_opens"] is True
    assert rep.stats["seal_behind_plug"] == 0
    # a tunnel from the vault out through its floor to the bottom of the world: the plug would
    # open onto more than the room
    seal = _seal_of(world_a)
    r = seal["room"]
    w = _mutated(world_a)
    w.grid[r["y"] + r["h"] - 1 :, r["x"] + 30 : r["x"] + 34] = mats.air
    rep = run_checks(w, bm, mats)
    assert rep.stats["seal_sealed"] is True  # nothing leaks without the plug
    assert any("more than the room" in f for f in rep.failures)


@pytest.mark.parametrize("where", ["beside_vault", "vault_side", "left_edge", "right_edge"])
def test_a_tunnel_past_the_plug_to_the_bottom_fails_the_check(world_a, bm, mats, where):
    """A 1-cell column of rock through the new brick, from the band above to the bottom row."""
    seal = _seal_of(world_a)
    top, r = seal["y"], seal["room"]
    x = {
        "beside_vault": r["x"] + r["w"] + 40,  # under the rock east of the vault
        "vault_side": r["x"] - 20,
        "left_edge": 1,  # the world's border column
        "right_edge": world_a.width - 2,
    }[where]
    w = _mutated(world_a)
    w.grid[top - 3 :, x] = mats["rock"]
    rep = run_checks(w, bm, mats)
    assert rep.stats["seal_sealed"] is False
    assert any("deeper than the plug's top edge" in f for f in rep.failures), rep.failures
    assert rep.stats["deepest_reach_y"] == world_a.height - 1


def test_a_diagonal_squeeze_past_the_plug_is_a_leak(world_a, bm, mats):
    """Rock cells that only touch at a corner join for the digger (8-connectivity)."""
    seal = _seal_of(world_a)
    top, r = seal["y"], seal["room"]
    x0 = r["x"] + r["w"] + 20  # under the rock east of the vault
    w = _mutated(world_a)
    for i in range(world_a.height - top):  # a staircase of single rock cells down to the bottom
        w.grid[top + i, x0 + i] = mats["rock"]
    passable = checks.passable_mask(w.grid, mats)
    four, _ = label(passable)
    eight, _ = label(passable, structure=np.ones((3, 3), dtype=bool))
    above, below = (top - 1, x0), (world_a.height - 1, x0 + world_a.height - top - 1)
    assert four[above] != four[below]  # no two staircase cells share an edge
    assert eight[above] == eight[below]
    rep = run_checks(w, bm, mats)
    assert any("deeper than the plug's top edge" in f for f in rep.failures), rep.failures


def test_the_cells_changed_per_world_do_not_depend_on_the_seed(world_a, world_b):
    """The rock and ground under the plug's top edge: everything but the scene and the room."""
    assert world_a.meta["seal_brick"] == world_b.meta["seal_brick"] == 59_352


def test_the_slot_in_front_of_the_seal_does_not_count_as_a_chokepoint(world_a, bm, mats):
    rep = run_checks(world_a, bm, mats)
    bands = sum(
        1
        for m in world_a.markers
        if m["type"] == "encounter" and m["must_pass"] and m["layer"] == 3
    )
    assert bands == rep.stats["must_pass_chokepoints"]["3"] + 1  # the seal front is the extra one


def test_removing_a_band_wall_removes_its_chokepoint(world_a, bm, mats):
    w = _mutated(world_a)
    slot = next(
        m for m in w.markers if m["type"] == "encounter" and m["must_pass"] and m["layer"] == 1
    )
    t = slot["trigger"]
    x0, _y0, x1, _y1 = bm.region(bm.layers[0].mid)
    # a tunnel past the scene, from the cave above it to the cave below it: the band can be bypassed
    lo, hi = (
        (x0 + bm.ring, t["x"] - 2)
        if t["x"] - x0 > x1 - t["x"] - t["w"]
        else (t["x"] + t["w"] + 2, x1 - bm.ring)
    )
    top, bottom = t["y"] - 14, t["y"] + t["h"] + 14
    w.grid[top:bottom, lo:hi] = mats.air
    # the carved rock took the floor away from whatever stood on it: those markers go too (a marker
    # on bare air fails the marker checks first, and the chokepoint statistics are never reached)
    w.markers = [
        m
        for m in w.markers
        if not (
            m["type"] in ("item", "spawn_enemy") and lo <= m["x"] < hi and top <= m["y"] < bottom
        )
    ]
    rep = run_checks(w, bm, mats)
    assert rep.stats["must_pass_chokepoints"]["1"] == 1
    assert any("layer 1" in f for f in rep.failures)


def test_encounter_ids_may_appear_at_most_twice(world_a, bm, mats):
    w = _mutated(world_a)
    extra = next(m for m in w.markers if m["type"] == "encounter" and not m["must_pass"])
    w.markers += [copy.deepcopy(extra) for _ in range(3)]
    assert any("appears" in f for f in run_checks(w, bm, mats).failures)


def test_trigger_rectangles_must_be_inside_the_world_and_apart(world_a, bm, mats):
    w = _mutated(world_a)
    slots = [m for m in w.markers if m["type"] == "encounter"]
    slots[0]["trigger"]["x"] = w.width - 5  # sticks out of the world
    assert any("outside the world" in f for f in run_checks(w, bm, mats).failures)
    w = _mutated(world_a)
    slots = [m for m in w.markers if m["type"] == "encounter"]
    slots[1]["trigger"] = dict(slots[0]["trigger"])
    assert any("overlap" in f for f in run_checks(w, bm, mats).failures)


def test_every_encounter_slot_must_be_reachable_on_foot(world_a, bm, mats):
    w = _mutated(world_a)
    slot = next(m for m in w.markers if m["type"] == "encounter" and not m["must_pass"])
    t = slot["trigger"]
    w.grid[t["y"] : t["y"] + t["h"], t["x"] : t["x"] + t["w"]] = mats["rock"]
    w.markers = [  # nothing may stand in the rock
        m
        for m in w.markers
        if m["type"] == "encounter"
        or not (t["x"] <= m["x"] < t["x"] + t["w"] and t["y"] <= m["y"] < t["y"] + t["h"])
    ]
    rep = run_checks(w, bm, mats)
    assert any("cannot be reached on foot" in f for f in rep.failures)


def test_marker_structure_is_checked(world_a, bm, mats):
    w = _mutated(world_a, markers=[m for m in world_a.markers if m["type"] != "rest_area"])
    assert any("rest_area" in f for f in run_checks(w, bm, mats).failures)
    w = _mutated(world_a, markers=[m for m in world_a.markers if m["type"] != "spawn_player"])
    assert any("spawn_player" in f for f in run_checks(w, bm, mats).failures)
    w = _mutated(world_a)
    enemy = next(m for m in w.markers if m["type"] == "spawn_enemy")
    w.grid[enemy["y"], enemy["x"]] = mats["rock"]
    assert any("not on a free cell" in f for f in run_checks(w, bm, mats).failures)


def test_missing_capability_node_coverage_fails(world_a, bm, mats):
    w = _mutated(world_a)
    w.markers = [
        m
        for m in w.markers
        if not (m["type"] == "encounter" and m["encounter_id"] in ("E21", "E22"))
    ]
    assert any("N9" in f for f in run_checks(w, bm, mats).failures)


def test_dig_cost_table_orders_materials(mats):
    t = dig_cost_table(mats)
    assert t[mats["air"]] < t[mats["ground"]] < t[mats["rock"]] < checks.BLOCKED
    assert t[mats["brick"]] >= checks.BLOCKED  # durability 14: the starting wand cannot dig it
    assert t[mats["lava"]] > t[mats["water"]] and t[mats["acid"]] > t[mats["water"]]


def test_shortest_path_goes_around_expensive_cells():
    cost = np.ones((9, 9), dtype=np.float32)
    cost[4, 1:8] = 50.0  # an expensive wall with gaps at both ends
    path, total = shortest_path(cost, (0, 4), (8, 4))
    assert (4, 0) in path or (4, 8) in path
    assert total < 50
    blocked = np.ones((5, 5), dtype=np.float32)
    blocked[2, :] = checks.BLOCKED
    assert shortest_path(blocked, (0, 2), (4, 2)) is None


def test_chokepoint_detection_on_a_synthetic_map():
    fit = np.ones((40, 60), dtype=bool)
    fit[18:22, :] = False  # a horizontal wall...
    fit[18:22, 28:32] = True  # ...with a doorway
    door = {"x": 20, "y": 14, "w": 20, "h": 12}
    side = {"x": 0, "y": 30, "w": 10, "h": 8}
    start, target = (30, 5), (30, 35)
    assert is_chokepoint(fit, door, start, target)
    assert not is_chokepoint(fit, side, start, target)
    assert is_chokepoint(
        fit, {"x": 25, "y": 30, "w": 10, "h": 10}, start, target
    )  # contains the target


def test_nothing_is_a_chokepoint_when_start_and_target_are_not_connected():
    fit = np.ones((40, 60), dtype=bool)
    fit[18:22, :] = False  # a solid wall, no doorway
    anywhere = {"x": 0, "y": 30, "w": 10, "h": 8}
    assert not is_chokepoint(fit, anywhere, (30, 5), (30, 35))


def _free_air_cell(world, mats):
    """A cave cell above the floor with three more air cells above it, for planting things in
    tests (a sand cell planted three cells up must hang in the air, not sit in the ceiling)."""
    g = world.grid
    air = g == mats.air
    column = air[3:-1] & air[2:-2] & air[1:-3] & air[:-4]  # rows y-3 .. y are free
    ys, xs = np.nonzero(column & (g[4:] == mats["ground"]))
    return int(xs[len(xs) // 2]), int(ys[len(ys) // 2]) + 3


def test_free_acid_is_a_failure(world_a, bm, mats):
    x, y = _free_air_cell(world_a, mats)
    w = _mutated(world_a)
    w.grid[y, x] = mats["acid"]
    assert any("free acid" in f for f in run_checks(w, bm, mats).failures)


def test_a_bottle_of_acid_lying_around_is_a_failure(world_a, bm, mats):
    w = _mutated(world_a)
    bottle = next(m for m in w.markers if m["type"] == "item" and m["item"] == "bottle")
    bottle["contents"] = "acid"
    assert any("free acid" in f for f in run_checks(w, bm, mats).failures)


def test_powder_with_nothing_below_is_a_failure(world_a, bm, mats):
    x, y = _free_air_cell(world_a, mats)
    w = _mutated(world_a)
    w.grid[y - 3, x] = mats["sand"]  # a sand cell hanging in mid-air above the cave floor
    rep = run_checks(w, bm, mats)
    assert any("no support" in f for f in rep.failures)
    assert rep.stats["hanging_powder"] >= 1


def test_sand_resting_on_a_flat_floor_is_fine(world_a, bm, mats):
    x, y = _free_air_cell(world_a, mats)
    w = _mutated(world_a)
    w.grid[y, x - 1 : x + 2] = mats.air
    w.grid[y + 1, x - 1 : x + 2] = mats["ground"]  # a flat floor three cells wide
    w.grid[y, x] = mats["sand"]
    assert not any("no support" in f for f in run_checks(w, bm, mats).failures)


def test_sand_on_the_edge_of_a_step_is_a_failure(world_a, bm, mats):
    """Straight down is blocked, but the lower diagonal is free: the sand slides."""
    x, y = _free_air_cell(world_a, mats)
    w = _mutated(world_a)
    w.grid[y, x - 1 : x + 2] = mats.air
    w.grid[y + 1, x - 1 : x + 1] = mats["ground"]
    w.grid[y + 1, x + 1] = mats.air  # a step down to the right
    w.grid[y, x] = mats["sand"]
    rep = run_checks(w, bm, mats)
    assert any("no support" in f for f in rep.failures)


def test_a_one_cell_gap_in_the_corner_of_a_pool_is_a_failure(world_a, bm, mats):
    """The simulation lets a liquid slide through a diagonal gap: the pool drains."""
    ys, xs = np.nonzero(world_a.grid == mats["water"])
    i = len(ys) // 2
    y, x = int(ys[i]), int(xs[i])
    w = _mutated(world_a)
    below = y
    while w.grid[below, x] == mats["water"]:
        below += 1
    w.grid[below, x : x + 1] = mats["rock"]  # the floor below stays closed ...
    w.grid[below, x - 1] = mats.air  # ... but the lower left diagonal is open
    rep = run_checks(w, bm, mats)
    assert any("liquid cells" in f for f in rep.failures)


def test_a_floating_barrel_is_a_failure(world_a, bm, mats):
    assert run_checks(world_a, bm, mats).stats["bad_barrels"] == 0
    markers = copy.deepcopy(world_a.markers)
    barrel = next(m for m in markers if m["type"] == "item" and m["item"].startswith("barrel_"))
    barrel["y"] -= 3  # three cells above its floor
    rep = run_checks(_mutated(world_a, markers=markers), bm, mats)
    assert any("barrel markers" in f for f in rep.failures)


def test_the_workshop_must_hold_its_barrels(world_a, bm, mats):
    rep = run_checks(world_a, bm, mats)
    assert rep.ok and rep.stats["workshop_barrels"] >= checks.MIN_WORKSHOP_BARRELS
    w = _mutated(
        world_a, markers=[m for m in world_a.markers if not m.get("item", "").startswith("barrel_")]
    )
    assert any("barrels in the workshop" in f for f in run_checks(w, bm, mats).failures)


def test_a_shaft_through_the_healing_pool_is_a_failure(world_a, bm, mats):
    pool = np.argwhere(world_a.grid == mats["potion_heal"])
    y, x = pool[len(pool) // 2]
    assert run_checks(world_a, bm, mats).stats["liquid_leaks"] == 0
    w = _mutated(world_a)
    w.grid[y : y + 40, x - 3 : x + 4] = mats.air  # a shaft right through the pool
    rep = run_checks(w, bm, mats)
    assert any("liquid cells" in f for f in rep.failures)


def test_a_pool_with_a_hole_in_its_wall_is_a_failure(world_a, bm, mats):
    ys, xs = np.nonzero(world_a.grid == mats["water"])
    i = len(ys) // 2
    y, x = int(ys[i]), int(xs[i])
    w = _mutated(world_a)
    below = y
    while w.grid[below, x] == mats["water"]:
        below += 1
    w.grid[below : below + 3, x] = mats.air  # knock a hole in the bottom of the pool
    assert any("liquid cells" in f for f in run_checks(w, bm, mats).failures)
