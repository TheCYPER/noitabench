"""Routes through the must-pass scenes (routes.py, encounter_defs gates, encounter_checks).

A must-pass scene that is not dug through is a closed brick box: a digger who cannot break brick
or metal gets from its top door to its exit only through its solution regions. The toy scenes
below show the check bites (every positive control comes with a negative one); the real scenes
are held to it for every variant, and mutated worlds show the post-generation check notices a
bulkhead that is missing."""

from __future__ import annotations

import copy
import dataclasses
import json

import numpy as np
import pytest
from noitabench.worldgen import generate_world
from noitabench.worldgen.breaker import best_combo, plug_durability
from noitabench.worldgen.checks import run_checks
from noitabench.worldgen.config import load_materials
from noitabench.worldgen.encounter_checks import placed_encounters
from noitabench.worldgen.encounter_defs import instantiate, load_encounters
from noitabench.worldgen.reach import DEFAULT_DIG_MAX_DURABILITY
from noitabench.worldgen.routes import digger_mask, route_problems
from noitabench.worldgen.table import get_rules

GATE_SCENES = ["E02", "E06", "E07", "E16", "E22", "E23"]
DIG_ZONES = {"E08", "E12"}

# A closed box 20 wide: the top door at the upper left, the exit at the bottom right, a passage
# (rows 5-8) between the entry room and the exit room, and a mass ``F`` above and below the
# passage that the digger can tunnel through if it is rock.
TOY = [
    "bbb^^bbbbbbbbbbbbbbb",
    "bbb..bbbbbbbbbbbbbbb",
    "bb.....FFFFFF.....bb",
    "bb.....FFFFFF.....bb",
    "bb.....FFFFFF.....bb",
    "bb................bb",
    "bb................bb",
    "bb................bb",
    "bb................bb",
    "bb.....FFFFFF.....bb",
    "bb.....FFFFFF.....bb",
    "bb.....FFFFFF.....bb",
    "bbbbbbbbbbbbbb..bbbb",
    "bbbbbbbbbbbbbbvvbbbb",
]
TOY_GATE = [("pass", (7, 5, 6, 4))]
CHARS = {".": "air", "b": "brick", "#": "rock", "m": "metal", "g": "ground", "^": "air", "v": "air"}


@pytest.fixture(scope="module")
def mats():
    return load_materials()


def toy(mats, filler: str = "b", rows: list[str] | None = None):
    """The grid and the doors of a toy scene made of ``rows`` with ``F`` replaced by ``filler``."""
    rows = [r.replace("F", filler) for r in (rows or TOY)]
    grid = np.array([[mats[CHARS[c]] for c in r] for r in rows], dtype=np.uint8)
    doors: dict[str, list[tuple[int, int]]] = {}
    for y, r in enumerate(rows):
        for x, c in enumerate(r):
            if c in "^v":
                doors.setdefault("top" if c == "^" else "bottom", []).append((x, y))
    return grid, doors


def problems(mats, filler="b", gates=None, rows=None, mutate=None, force_open=False, sealed=()):
    grid, doors = toy(mats, filler, rows)
    if mutate:
        mutate(grid)
    return route_problems(grid, doors, [gates or TOY_GATE], mats, force_open, sealed)


# ------------------------------------------------------------------------- toy scenes


def test_a_passage_walled_in_brick_is_a_true_gate(mats):
    assert problems(mats, "b") == []


def test_metal_walls_are_as_good_as_brick(mats):
    assert problems(mats, "m") == []


@pytest.mark.parametrize("filler", ["#", "g"])
def test_rock_or_ground_round_the_passage_is_a_bypass(mats, filler):
    """The negative control: the same scene with a diggable mass round the passage."""
    found = problems(mats, filler)
    assert len(found) == 1 and "gate pass can be bypassed" in found[0], found
    assert "digs" in found[0] and ("rock" in found[0] or "ground" in found[0])


def test_the_digger_is_the_starter_digger(mats):
    ok = digger_mask(np.array([[mats["rock"], mats["brick"], mats["metal"], mats["air"]]]), mats)
    assert ok.tolist() == [[True, False, False, True]]
    assert digger_mask(np.array([[mats["brick"]]]), mats, max_durability=14).all()


def test_no_static_material_sits_between_the_digger_and_the_brick(mats):
    """The route model calls a static cell a wall when the starter digger (10) cannot remove it.
    The bomb (11) and the explosive modifier on a dig bolt or a fireball (13) are found before the
    key is whole, so a material of durability 11 to 13 would be a wall for the model and a door
    for them. Brick (14) and metal (15) are the only walls."""
    harder = {
        int(d)
        for d, kind in zip(mats.durability, mats.kinds, strict=True)
        if kind == "static" and d > DEFAULT_DIG_MAX_DURABILITY
    }
    assert harder == {plug_durability(), int(mats.durability[mats["metal"]])}, harder
    assert DEFAULT_DIG_MAX_DURABILITY < best_combo(["BOMB"]).durability < plug_durability()


def test_the_gate_is_cut_by_blocking_it_not_by_walling_what_is_round_it(mats):
    """With the brick mass the doors are joined through the passage and only through it."""
    grid, doors = toy(mats, "b")
    assert route_problems(grid, doors, [TOY_GATE], mats) == []
    x, y, _w, h = TOY_GATE[0][1]
    grid[y : y + h, x + 2] = mats["brick"]  # a wall across the passage
    found = route_problems(grid, doors, [TOY_GATE], mats)
    assert len(found) == 1 and "not joined" in found[0], found  # the control fails: no route


def test_a_diagonal_squeeze_through_the_brick_is_a_leak(mats):
    """A chain of rock cells that touch only at their corners joins two rooms for 8-neighbours."""

    def tunnel(grid):
        for x, y in [(7, 4), (8, 3), (9, 2), (10, 3), (11, 4), (12, 3)]:
            grid[y, x] = mats["rock"]

    found = problems(mats, "b", mutate=tunnel)
    assert len(found) == 1 and "can be bypassed" in found[0], found


def test_a_one_cell_slit_that_stops_short_is_no_leak(mats):
    def slit(grid):
        grid[4, 7:12] = mats["rock"]  # five of the six cells: the sixth is still brick

    assert problems(mats, "b", mutate=slit) == []


def test_a_hole_in_the_outer_wall_is_noticed(mats):
    def hole(grid):
        grid[8, 0] = mats["rock"]  # the left edge, beside the entry room, not a door

    found = problems(mats, "b", mutate=hole)
    assert any("outer wall is not closed" in f and "(0, 8)" in f for f in found), found


def test_a_hole_in_the_outer_wall_that_leads_nowhere_still_counts(mats):
    def corner(grid):
        grid[0, 0] = mats["rock"]  # an isolated cell on the edge: no digger reaches it, but the
        # wall is not closed there and the next scene edit might join it

    assert any("outer wall is not closed" in f for f in problems(mats, "b", mutate=corner))


def test_the_door_cells_are_not_holes(mats):
    grid, doors = toy(mats)
    assert any(grid[y, x] == mats.air for x, y in doors["top"] + doors["bottom"])
    assert route_problems(grid, doors, [TOY_GATE], mats) == []


def test_a_gate_whose_region_lies_off_the_passage_is_a_bypass(mats):
    """A region box that does not sit on the passage: blocking it cuts nothing, so the passage
    is a way round a gate that is not there."""
    found = problems(mats, "b", gates=[("pass", (7, 9, 6, 2))])
    assert any("can be bypassed" in f for f in found), found


def test_a_scene_without_a_route_fails_the_control(mats):
    rows = [r.replace("bb................bb", "bb.....bbbbbb.....bb") for r in TOY]
    found = problems(mats, "b", rows=rows)
    assert len(found) == 1 and "control of the route check" in found[0], found


def test_a_scene_without_a_top_door_is_rejected(mats):
    grid, _ = toy(mats)
    found = route_problems(grid, {}, [TOY_GATE], mats)
    assert len(found) == 1 and "no top door" in found[0], found


# a river under a roof: the passage (box x 7-12, rows 5-8) has a bulkhead of brick at its entry
# end (column 7) and a mass ``F`` of roof above it that joins the exit side
ROOF = [
    "bbb^^bbbbbbbbbbbbbbb",
    "bbb..bbbbbbbbbbbbbbb",
    "bb.....bbbbbb.....bb",
    "bb.....bFFFFF.....bb",
    "bb.....bFFFFF.....bb",
    "bb................bb",
    "bb................bb",
    "bb................bb",
    "bb................bb",
    "bb.....bFFFFF.....bb",
    "bb.....bFFFFF.....bb",
    "bb.....bbbbbb.....bb",
    "bbbbbbbbbbbbbb..bbbb",
    "bbbbbbbbbbbbbbvvbbbb",
]


def test_a_roof_over_the_passage_is_a_way_round_that_the_cut_does_not_see(mats):
    """Blocking the passage cuts the scene (the roof is walled off at the entry end), yet a
    digger who gets into the air of the passage tunnels through the roof to the exit side."""
    assert problems(mats, "#", rows=ROOF) == []  # the cut is there, nothing to complain about
    found = problems(mats, "#", rows=ROOF, sealed=["pass"])
    assert len(found) == 2 and "not sealed above" in found[0], found
    assert "not sealed below" in found[1], found
    assert "5 diggable cells in row 4 (rock (8, 4)" in found[0], found
    assert "5 diggable cells in row 9 (rock (8, 9)" in found[1], found


def test_a_passage_with_brick_above_and_below_is_sealed(mats):
    assert problems(mats, "b", rows=ROOF, sealed=["pass"]) == []
    assert problems(mats, "m", rows=ROOF, sealed=["pass"]) == []


@pytest.mark.parametrize("side,row", [("above", 4), ("below", 9)])
def test_one_cell_of_rock_next_to_the_passage_is_enough_to_unseal_it(mats, side, row):
    def nick(grid):
        grid[row, 10] = mats["rock"]

    found = problems(mats, "b", rows=ROOF, sealed=["pass"], mutate=nick)
    assert len(found) == 1 and f"not sealed {side}" in found[0], found
    assert "1 diggable cells" in found[0] and f"rock (10, {row})" in found[0], found


def test_the_corners_beside_the_passage_belong_to_its_entry_and_exit(mats):
    """The cells diagonal to the passage's first and last column are the entry and the exit."""

    def corners(grid):
        grid[4, 6] = grid[4, 13] = grid[9, 6] = grid[9, 13] = mats["rock"]

    assert problems(mats, "b", rows=ROOF, sealed=["pass"], mutate=corners) == []


def test_a_cell_above_a_wall_of_the_passage_does_not_touch_it(mats):
    """Only cells that touch a passable cell of the passage's own top row count."""

    def wall(grid):
        grid[5, 8:11] = mats["brick"]  # the passage's top row has a wall here
        grid[4, 9] = mats["rock"]  # ... and the rock above it touches only the wall

    assert problems(mats, "b", rows=ROOF, sealed=["pass"], mutate=wall) == []

    def wall_and_open_neighbours(grid):
        wall(grid)
        grid[4, 11] = mats["rock"]  # next to the wall, above open cells

    found = problems(mats, "b", rows=ROOF, sealed=["pass"], mutate=wall_and_open_neighbours)
    assert len(found) == 1 and "not sealed above" in found[0], found
    assert "rock (11, 4)" in found[0], found


# a scene with two passages: a gate with two alternatives
TWO = [
    "bbb^^bbbbbbbbbbbbbbb",
    "bbb..bbbbbbbbbbbbbbb",
    "bb.....FFFFFF.....bb",
    "bb................bb",
    "bb................bb",
    "bb.....FFFFFF.....bb",
    "bb.....FFFFFF.....bb",
    "bb.....FFFFFF.....bb",
    "bb................bb",
    "bb................bb",
    "bb.....FFFFFF.....bb",
    "bb.....FFFFFF.....bb",
    "bbbbbbbbbbbbbb..bbbb",
    "bbbbbbbbbbbbbbvvbbbb",
]
UP, DOWN = ("up", (7, 3, 6, 2)), ("down", (7, 8, 6, 2))


def test_a_gate_with_alternatives_is_cut_only_by_blocking_all_of_them(mats):
    grid, doors = toy(mats, "b", TWO)
    assert route_problems(grid, doors, [[UP, DOWN]], mats) == []
    # blocking only one of the two passages leaves the other: a one-region gate is bypassed
    found = route_problems(grid, doors, [[UP]], mats)
    assert len(found) == 1 and "gate up can be bypassed" in found[0], found


def test_an_alternative_that_is_not_a_way_through_is_named(mats):
    def close_down(grid):
        grid[8:10, 7:13] = mats["brick"]

    grid, doors = toy(mats, "b", TWO)
    close_down(grid)
    found = route_problems(grid, doors, [[UP, DOWN]], mats)
    assert found == ["region down of gate up+down is no way through"], found


def test_gates_in_series_are_each_cut_and_each_walled(mats):
    """Two obstacles one after the other; a bulkhead missing at the second one is reported for
    it alone."""
    rows = [
        "bbb^^bbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "bbb..bbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "bb.....FFFFFF......FFFFFF.....bbb",
        "bb.....FFFFFF......FFFFFF.....bbb",
        "bb.....FFFFFF......FFFFFF.....bbb",
        "bb...........................bbbb",
        "bb...........................bbbb",
        "bb.....FFFFFF......FFFFFF.....bbb",
        "bb.....FFFFFF......FFFFFF.....bbb",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbb..bb",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbvvbb",
    ]
    rows = [r.ljust(33, "b") for r in rows]
    first, second = ("first", (7, 5, 6, 2)), ("second", (19, 5, 6, 2))
    grid, doors = toy(mats, "b", rows)
    assert route_problems(grid, doors, [[first], [second]], mats) == []
    grid[2:5, 19:25] = mats["rock"]  # the mass above the second obstacle is rock
    found = route_problems(grid, doors, [[first], [second]], mats)
    assert len(found) == 1 and "gate second can be bypassed" in found[0], found


def test_a_plug_is_forced_open_only_when_asked(mats):
    """The sealed deep: the gate is a brick plug. As drawn it joins nothing; forced open it does."""
    rows = [
        "bbb^^bbbbbbb",
        "bbb..bbbbbbb",
        "bb........bb",
        "bb........bb",
        "bbbbbbbbbbbb",
        "bbbbbbbbbbbb",
    ]
    plug = [("plug", (4, 4, 4, 2))]
    grid, doors = toy(mats, "b", rows)
    assert route_problems(grid, doors, [plug], mats)[0].startswith("with every solution region")
    assert route_problems(grid, doors, [plug], mats, force_open=True) == []


# ------------------------------------------------------------------------ real scenes


@pytest.fixture(scope="module")
def defs():
    return load_encounters()


def test_every_must_pass_scene_that_is_not_dug_through_names_its_gates(defs):
    named = {i for i, d in defs.items() if d.gates}
    assert named == set(GATE_SCENES)
    assert {i for i, d in defs.items() if d.must_pass and not d.dig_zone} == named
    assert {i for i, d in defs.items() if d.dig_zone} == DIG_ZONES


SEALED = {
    "E02": ["river_gate"],
    "E07": ["acid_gate", "lava_gate"],
    "E16": ["crossing"],
    "E22": ["short_gate"],
    "E23": ["pool_gate"],
}


def test_the_passages_through_a_diggable_mass_are_sealed(defs):
    """A passage the player crosses over or through a liquid, with rock round it: the river of
    E02 and E07, the pool of E23, the trough of E16, the corridor of E22. The long lane of E22 is
    walked, its obstacle is an enemy, so it is not on the list; the plug of E06 is a floor."""
    assert {i: list(d.sealed) for i, d in defs.items() if d.sealed} == SEALED


@pytest.mark.parametrize("eid", sorted(SEALED))
@pytest.mark.parametrize("side", ["above", "below"])
def test_dissolving_the_brick_beside_a_sealed_passage_is_noticed(defs, mats, eid, side):
    """The roof of a river, the bed under a lake: brick turned to rock in the row next to the
    passage (and in the passage's own edge row, where that is the brick) is a way round."""
    d = defs[eid]
    inst = instantiate(d, get_rules(0), 0, mats)
    for name in d.sealed:
        x, y, w, h = inst.regions[name]
        grid = inst.grid.copy()
        for row in (y - 1, y) if side == "above" else (y + h, y + h - 1):
            seg = grid[row, x : x + w]
            seg[seg == mats["brick"]] = mats["rock"]
        found = route_problems(grid, inst.doors, inst.gate_regions(), mats, d.fixed, d.sealed)
        assert any(f"region {name} is not sealed {side}" in f for f in found), (name, found)


@pytest.mark.parametrize("eid", GATE_SCENES)
def test_every_variant_of_a_gate_scene_is_a_true_gate(defs, mats, eid):
    d = defs[eid]
    rules = get_rules(0)
    for v in range(d.variants):
        inst = instantiate(d, rules, v, mats)
        gates = inst.gate_regions()
        found = route_problems(inst.grid, inst.doors, gates, mats, d.fixed, d.sealed)
        assert found == [], (eid, v, found)


@pytest.mark.parametrize("eid", GATE_SCENES)
def test_the_regions_of_a_gate_keep_their_names_and_do_not_swallow_the_doors(defs, eid):
    d = defs[eid]
    names = [n for g in d.gates for n in g]
    assert names and set(names) <= set(d.regions)
    inst = instantiate(d, get_rules(0), 1, load_materials())  # the mirror image
    for name in names:
        x, y, w, h = inst.regions[name]
        assert all(
            not (x <= dx < x + w and y <= dy < y + h) for c in inst.doors.values() for dx, dy in c
        )


@pytest.mark.parametrize("eid", [e for e in GATE_SCENES if e != "E06"])
def test_dissolving_the_bulkheads_of_a_scene_opens_a_bypass(defs, mats, eid):
    """Every brick that is neither on the outer wall nor in a solution region matters: turned to
    rock (the digger removes it) the scene can be bypassed."""
    d = defs[eid]
    inst = instantiate(d, get_rules(0), 0, mats)
    h, w = inst.grid.shape
    yy, xx = np.mgrid[0:h, 0:w]
    inner = np.minimum.reduce([xx, yy, w - 1 - xx, h - 1 - yy]) >= 4
    grid = inst.grid.copy()
    grid[(grid == mats["brick"]) & inner] = mats["rock"]
    found = route_problems(grid, inst.doors, inst.gate_regions(), mats)
    assert any("can be bypassed" in f for f in found), (eid, found)


def test_dissolving_the_floor_of_the_sealed_deep_outside_the_plug_opens_a_bypass(defs, mats):
    d = defs["E06"]
    inst = instantiate(d, get_rules(0), 0, mats)
    grid = inst.grid.copy()
    px, py, pw, ph = inst.regions["plug"]
    floor = grid[py:, :].copy()
    floor[:, px : px + pw] = mats["brick"]
    grid[py:, :] = np.where(floor == mats["brick"], mats["rock"], floor)
    grid[py : py + ph, px : px + pw] = mats["brick"]  # the plug itself stays whole
    found = route_problems(grid, inst.doors, inst.gate_regions(), mats, True)
    assert any("can be bypassed" in f for f in found), found


@pytest.mark.parametrize("eid", GATE_SCENES)
def test_the_outer_wall_of_a_gate_scene_is_closed_and_a_hole_in_it_is_noticed(defs, mats, eid):
    d = defs[eid]
    inst = instantiate(d, get_rules(0), 0, mats)
    grid = inst.grid.copy()
    door = {c for cells in inst.doors.values() for c in cells}
    h, w = grid.shape
    edge = [(x, y) for y in range(h) for x in range(w) if min(x, y, w - 1 - x, h - 1 - y) == 0]
    assert all(grid[y, x] in (mats["brick"], mats.air) for x, y in edge)
    assert {(x, y) for x, y in edge if grid[y, x] == mats.air} == door
    x, y = next(c for c in edge if c not in door and c[0] == 0 and c[1] > 4)
    grid[y, x] = mats["rock"]
    found = route_problems(grid, inst.doors, inst.gate_regions(), mats, d.fixed)
    assert any("outer wall is not closed" in f for f in found), found


def test_the_pier_under_the_guards_of_e22_is_two_cells_thick_and_all_the_way(defs, mats):
    """E22: the block between the corridor and the lane is cut by a brick pier (x 54-55, rows 16-33)."""
    inst = instantiate(defs["E22"], get_rules(0), 0, mats)
    gates = inst.gate_regions()
    nick = inst.grid.copy()
    nick[25, 54] = mats["rock"]  # one cell: the other one still holds
    assert route_problems(nick, inst.doors, gates, mats) == []
    cut = inst.grid.copy()
    cut[25, 54:56] = mats["rock"]  # a whole row of the pier
    found = route_problems(cut, inst.doors, gates, mats)
    assert len(found) == 1 and "can be bypassed" in found[0], found


# --------------------------------------------------------------------- bad definitions

GOOD_ART = TOY
GOOD_DEF = {
    "format": "cogbench-encounter/0",
    "id": "E99",
    "name_zh": "x",
    "name_en": "x",
    "nodes": ["N1"],
    "must_pass": True,
    "layer": 1,
    "biomes": ["mine"],
    "art": "E99.scene",
    "variants": 2,
    "markers": {},
    "trap": "t",
    "cue": "c",
    "anchor_y": 7,
    "regions": {"pass": [7, 5, 6, 4]},
    "gates": [["pass"]],
}


def _load(tmp_path, filler="b", **changes):
    art = [r.replace("F", filler) for r in GOOD_ART]
    (tmp_path / "E99.scene").write_text("\n".join(art) + "\n", encoding="utf-8")
    data = {**GOOD_DEF, **changes}
    data = {k: v for k, v in data.items() if v is not None}
    (tmp_path / "E99.json").write_text(json.dumps(data), encoding="utf-8")
    return load_encounters.__wrapped__(tmp_path)


def test_a_toy_scene_with_gates_loads(tmp_path):
    d = _load(tmp_path)["E99"]
    assert d.gates == (("pass",),) and d.must_pass


def test_the_loader_runs_the_route_check_on_the_art(tmp_path):
    with pytest.raises(ValueError, match="gate pass can be bypassed"):
        _load(tmp_path, filler="#")


BAD = [
    ("a must-pass scene without gates", {"gates": None}, "solution regions"),
    ("a gate with an unknown region", {"gates": [["nowhere"]]}, "not one of the regions"),
    ("a gate that is not a list of names", {"gates": [[1]]}, "list of lists"),
    ("an empty gate", {"gates": [[]]}, "list of lists"),
    (
        "a region in two gates",
        {"gates": [["pass"], ["pass"]]},
        "belongs to one gate",
    ),
    (
        "overlapping regions of two gates",
        {"regions": {"pass": [7, 5, 6, 4], "other": [9, 6, 6, 3]}, "gates": [["pass"], ["other"]]},
        "overlap",
    ),
    (
        "a region over a door",
        {"regions": {"pass": [3, 0, 3, 3]}},
        "covers a top door",
    ),
]


@pytest.mark.parametrize("name,changes,message", BAD, ids=[b[0] for b in BAD])
def test_bad_gate_definitions_are_rejected_with_a_clear_message(tmp_path, name, changes, message):
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, **changes)


def test_a_dig_zone_needs_no_gates(tmp_path):
    d = _load(tmp_path, gates=None, dig_zone=True)["E99"]
    assert d.gates == () and d.dig_zone


# ------------------------------------------------------------------ the placed scenes


def _mutated(world, **changes):
    return dataclasses.replace(
        world, grid=world.grid.copy(), markers=copy.deepcopy(world.markers), **changes
    )


@pytest.fixture(scope="module")
def checked_world():
    return generate_world(3)


def _gate_scenes(world, defs):
    return [m for m in placed_encounters(world) if defs[m["encounter_id"]].gates]


def test_every_placed_gate_scene_is_checked_and_passes(checked_world, bm, mats, defs):
    rep = run_checks(checked_world, bm, mats)
    assert rep.ok, rep.failures
    scenes = _gate_scenes(checked_world, defs)
    assert rep.stats["gate_scenes"] == len([m for m in scenes if not defs[m["encounter_id"]].fixed])
    assert {m["encounter_id"] for m in scenes} >= {"E02", "E07", "E16", "E22", "E23"}


@pytest.mark.parametrize("eid", ["E02", "E07", "E16", "E22", "E23"])
def test_a_missing_bulkhead_in_a_placed_scene_is_noticed(checked_world, bm, mats, defs, eid):
    w = _mutated(checked_world)
    m = next(s for s in placed_encounters(w) if s["encounter_id"] == eid)
    fp = m["footprint"]
    box = w.grid[fp["y"] : fp["y"] + fp["h"], fp["x"] : fp["x"] + fp["w"]]
    yy, xx = np.mgrid[0 : fp["h"], 0 : fp["w"]]
    inner = np.minimum.reduce([xx, yy, fp["w"] - 1 - xx, fp["h"] - 1 - yy]) >= 4
    box[(box == mats["brick"]) & inner] = mats["rock"]
    fails = run_checks(w, bm, mats).failures
    here = f"encounter {eid} at ({fp['x']}, {fp['y']}): "
    assert any(f.startswith(here) and "can be bypassed" in f for f in fails), fails


def test_a_hole_in_the_outer_wall_of_a_placed_scene_is_noticed(checked_world, bm, mats):
    w = _mutated(checked_world)
    m = next(s for s in placed_encounters(w) if s["encounter_id"] == "E16" and s["must_pass"])
    fp = m["footprint"]
    w.grid[fp["y"] + 20, fp["x"]] = mats["rock"]
    fails = run_checks(w, bm, mats).failures
    assert any("outer wall is not closed" in f for f in fails), fails


@pytest.mark.parametrize("eid", ["E02", "E07", "E23"])
def test_rock_for_the_roof_of_a_placed_passage_is_noticed(checked_world, bm, mats, defs, eid):
    w = _mutated(checked_world)
    m = next(s for s in placed_encounters(w) if s["encounter_id"] == eid and s["must_pass"])
    gate = defs[eid].sealed[-1]  # the lava of E07 (its second gate), the river, the pool
    r = m["regions"][gate]
    row = w.grid[r["y"] - 1, r["x"] : r["x"] + r["w"]]
    row[row == mats["brick"]] = mats["rock"]
    fp = m["footprint"]
    fails = run_checks(w, bm, mats).failures
    here = f"encounter {eid} at ({fp['x']}, {fp['y']}): region {gate} is not sealed above"
    assert any(f.startswith(here) for f in fails), fails


def test_the_sealed_deep_is_not_gate_checked_in_the_world(checked_world, defs):
    fixed = [m for m in placed_encounters(checked_world) if defs[m["encounter_id"]].fixed]
    assert [m["encounter_id"] for m in fixed] == ["E06"]


# ------------------------------------------------------- the whole world, end to end


def _cut_by(world, mats, defs, scene, gate_index: int, ground=None) -> bool:
    """Whether blocking gate ``gate_index`` of the placed ``scene`` in the real world grid (the
    other gates of the scene open) cuts every route of free or diggable cells from the player's
    spawn to the front of the seal; ``ground`` replaces the world's cells."""
    from noitabench.worldgen.checks import EIGHT, passable_mask
    from scipy.ndimage import label

    grid = world.grid if ground is None else ground
    ok = passable_mask(grid, mats)
    d = defs[scene["encounter_id"]]
    for other, gate in enumerate(d.gates):
        for name in gate:
            r = scene["regions"][name]
            ok[r["y"] : r["y"] + r["h"], r["x"] : r["x"] + r["w"]] = other != gate_index
    spawn = next(m for m in world.markers if m["type"] == "spawn_player")
    front = next(m for m in world.markers if m["type"] == "encounter" and m["biome"] == "seal")
    t = front["trigger"]
    lab, _ = label(ok, structure=EIGHT)
    a, b = lab[spawn["y"], spawn["x"]], lab[t["y"] + t["h"] - 3, t["x"] + t["w"] // 2]
    return not (a and a == b)


def _band_gates(world, defs):
    return [
        (m, i)
        for m in placed_encounters(world)
        if m["must_pass"] and defs[m["encounter_id"]].gates and not defs[m["encounter_id"]].fixed
        for i in range(len(defs[m["encounter_id"]].gates))
    ]


def test_every_gate_of_a_generated_world_cuts_the_whole_world(world_a, world_b, mats, defs):
    """The end-to-end form of the gate check: in the real grid, with a gate's solution regions
    blocked, no route of free or diggable cells leads from the spawn to the seal front (the
    outer wall, the seams and the shells make the footprint the only way)."""
    for w in (world_a, world_b):
        gates = _band_gates(w, defs)
        assert len(gates) >= 7  # E16, E07 (two gates), E23, E22, E02 and the second layer's
        for scene, i in gates:
            assert _cut_by(w, mats, defs, scene, i), (scene["encounter_id"], i)


def test_the_end_to_end_check_bites_when_the_bulkheads_are_rock(world_a, mats, defs):
    """The negative control: the bricks inside the outer wall of every band scene turned to rock
    and every gate of every scene becomes a bypass (the rock is what a digger tunnels)."""
    grid = world_a.grid.copy()
    for scene, _ in _band_gates(world_a, defs):
        fp = scene["footprint"]
        box = grid[fp["y"] : fp["y"] + fp["h"], fp["x"] : fp["x"] + fp["w"]]
        yy, xx = np.mgrid[0 : fp["h"], 0 : fp["w"]]
        inner = np.minimum.reduce([xx, yy, fp["w"] - 1 - xx, fp["h"] - 1 - yy]) >= 4
        box[(box == mats["brick"]) & inner] = mats["rock"]
    for scene, i in _band_gates(world_a, defs):
        assert not _cut_by(world_a, mats, defs, scene, i, ground=grid), (scene["encounter_id"], i)
