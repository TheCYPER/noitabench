"""Hazard clearance (clearance.py, clearance_checks.py; D2c, 2026-10-27).

Ambient lava and acid keep out of reach of the corridors the player has to walk (the footprint of
every must-pass scene, the tunnels from its doors, the shaft above the sealed deep), and out of
the blast radius of the seal key round the hall above the plug. The geometry is the player's hit box
(``entities.json``); the tests compare it with the engine itself.
"""

from __future__ import annotations

import copy
import dataclasses

import numpy as np
import pytest
from noitabench.game import Game
from noitabench.worldgen import clearance, features, generate, layers
from noitabench.worldgen import hazards as hz
from noitabench.worldgen.canvas import PLAYER_H, PLAYER_W, Canvas, Component, capsule_rect
from noitabench.worldgen.checks import run_checks
from noitabench.worldgen.clearance import (
    Blast,
    Lane,
    blast_clear_radius,
    blast_violations,
    hazard_keys,
    hit_zone,
    keepout_mask,
    lane_violations,
    lane_zone,
    player_reach,
    seal_blasts,
)
from noitabench.worldgen.clearance_checks import check_clearance, lanes_of
from noitabench.worldgen.config import load_materials
from noitabench.worldgen.encounter_place import SceneContext
from noitabench.worldgen.layers import vertical_gate
from noitabench.worldgen.table import get_rules
from scipy.ndimage import binary_dilation


def _mutated(world):
    return dataclasses.replace(
        world,
        grid=world.grid.copy(),
        markers=copy.deepcopy(world.markers),
        meta=copy.deepcopy(world.meta),
    )


def _clearance_failures(world, bm, mats) -> list[str]:
    return [
        f
        for f in run_checks(world, bm, mats).failures
        if "within reach" in f or "blast radius" in f or "meta.clearance" in f
    ]


# ------------------------------------------------------------------------------- the geometry


def test_the_reach_is_the_hit_box_of_the_game():
    """6 x 16 hit box round the 4 x 7 collision box: one cell to each side, 7 up, 2 down."""
    g = Game(60, 80, 1)
    g.fill_rect(0, 60, 60, 20, "rock")
    g.spawn_player(30, 59)
    g.step(2)
    p = g.player()
    hx, hy, hw, hh = p["hit"]
    r = player_reach()
    assert (p["w"], p["h"]) == (PLAYER_W, PLAYER_H)
    assert (p["x"] - hx, hx + hw - (p["x"] + p["w"])) == (r.left, r.right) == (1, 1)
    assert (p["y"] - hy, hy + hh - (p["y"] + p["h"])) == (r.up, r.down) == (7, 2)


def test_the_hazards_are_what_burns_or_sets_alight():
    assert set(hazard_keys()) == {"lava", "acid", "fire"}


def test_the_zone_of_positions_is_the_union_of_their_hit_boxes():
    r = player_reach()
    rng = np.random.default_rng(5)
    for density in (0.003, 0.02, 0.1):
        positions = rng.random((40, 50)) < density
        expect = np.zeros_like(positions)
        for cy, cx in zip(*np.nonzero(positions)):
            expect[
                max(0, cy - r.up) : cy + PLAYER_H + r.down,
                max(0, cx - r.left) : cx + PLAYER_W + r.right,
            ] = True
        assert (hit_zone(positions) == expect).all()


# ------------------------------------------- the zone against the engine, on a corridor of one row


FLOOR, TOP = 60, 53  # a corridor 7 rows high (rows 53..59) over a floor that starts at row 60
LEFT, RIGHT = 20, 41  # its columns 20..40


def _corridor(mats, lava: tuple[int, int, int, int]):
    """A grid and a game: rock, a corridor the player just fits, and a slab of lava (x, y, w, h)
    sealed inside the rock."""
    grid = np.full((80, 60), mats["rock"], dtype=np.uint8)
    grid[TOP:FLOOR, LEFT:RIGHT] = mats.air
    x, y, w, h = lava
    grid[y : y + h, x : x + w] = mats["lava"]
    g = Game(60, 80, 1)
    g.fill_rect(0, 0, 60, 80, "rock")
    g.fill_rect(LEFT, TOP, RIGHT - LEFT, FLOOR - TOP, "air")
    g.fill_rect(x, y, w, h, "lava")
    lane = Lane("E99", 3, (LEFT, TOP, RIGHT, FLOOR))
    return grid, g, lane


def _hurts(g: Game, standing: tuple[int, int]) -> bool:
    g.spawn_player(*standing)
    g.step(4)
    p = g.player()
    return p["hp"] < p["hp_max"] or "on_fire" in p["statuses"]


# a slab of lava in the rock round the corridor, and the place the player stands in;
# ``hurt``: the engine burns him there (and so the lane check must call the slab a violation)
@pytest.mark.parametrize(
    "name, slab, standing, hurt",
    [
        ("7 rows above the head, in reach", (24, 46, 12, 1), (30, 59), True),
        ("8 rows above the head, out of reach", (24, 45, 12, 1), (30, 59), False),
        ("2 rows into the floor, in reach", (24, 61, 12, 1), (30, 59), True),
        ("3 rows into the floor, out of reach", (24, 62, 12, 1), (30, 59), False),
        ("1 cell beside the box, in reach", (19, 54, 1, 5), (22, 59), True),
        ("2 cells beside the box, out of reach", (18, 54, 1, 5), (22, 59), False),
    ],
)
def test_the_zone_agrees_with_the_engine(mats, name, slab, standing, hurt):
    """The lane check calls a lava cell a violation exactly when the engine burns the player who
    stands where the corridor lets him (this corridor leaves one standing place per column)."""
    grid, game, lane = _corridor(mats, slab)
    # a slab beside the box must touch the hit box of the leftmost standing place: 3 cells of lava
    assert _hurts(game, standing) == hurt, name
    assert (len(lane_violations(grid, mats, lane)) > 0) == hurt, name


def test_the_footprint_is_exempt_and_other_cells_count(mats):
    grid, _, lane = _corridor(mats, (24, 46, 12, 1))
    grid[TOP + 2, 25] = mats["lava"]  # lava in the scene itself: its design
    cells = lane_violations(grid, mats, lane)
    assert {(int(x), int(y)) for x, y in cells} == {(x, 46) for x in range(24, 36)}


def test_a_corridor_that_is_taller_than_the_box_lets_the_head_reach_higher(mats):
    """Free positions are everywhere in the corridor, not only on its floor (a jump, a levitation)."""
    grid = np.full((80, 60), mats["rock"], dtype=np.uint8)
    grid[50:FLOOR, LEFT:RIGHT] = mats.air  # 10 rows: the box can hang under the ceiling
    grid[43, 24:36] = mats["lava"]  # 7 rows above row 50
    grid[42, 24:36] = mats["lava"]
    lane = Lane("E99", 3, (LEFT, 50, RIGHT, FLOOR))
    cells = lane_violations(grid, mats, lane)
    assert {int(y) for _, y in cells} == {43}


def test_no_position_where_the_box_does_not_fit(mats):
    """A corridor too low for the box has no position: nothing is in reach of it."""
    grid = np.full((80, 60), mats["rock"], dtype=np.uint8)
    grid[55:FLOOR, LEFT:RIGHT] = mats.air  # 5 rows: the 7-row box does not fit
    grid[50, 24:36] = mats["lava"]
    lane = Lane("E99", 3, (LEFT, 55, RIGHT, FLOOR))
    assert len(lane_violations(grid, mats, lane)) == 0


def test_a_tunnel_counts_like_the_footprint(mats):
    """Lava behind the wall of a door tunnel is in reach of the player walking it."""
    grid = np.full((100, 100), mats["rock"], dtype=np.uint8)
    grid[10:30, 40:60] = mats.air  # the footprint
    grid[30:78, 45:55] = mats.air  # a tunnel down from its door: 10 wide, tall enough
    grid[60, 55:65] = mats["lava"]  # lava in the wall beside the tunnel (the hit box reaches it)
    lane = Lane("E99", 3, (40, 10, 60, 30))
    assert len(lane_violations(grid, mats, lane)) == 0  # the tunnel is not told about yet
    lane = Lane("E99", 3, (40, 10, 60, 30), ((45, 30, 55, 78),))
    assert len(lane_violations(grid, mats, lane)) > 0


def test_a_lane_survives_its_record():
    lane = Lane("E12", 3, (10, 20, 90, 76), ((40, 0, 54, 20), (40, 76, 54, 100)))
    assert Lane.from_record(lane.record()) == lane
    assert lane.record()["footprint"] == {"x": 10, "y": 20, "w": 80, "h": 56}


def test_capsule_rect_covers_the_bar():
    c = Canvas(120, 120, load_materials())
    c.capsule((30, 30), (30, 80), 7)
    ys, xs = np.nonzero(c.grid != load_materials()["rock"])
    x0, y0, x1, y1 = capsule_rect((30, 30), (30, 80), 7)
    assert x0 <= xs.min() and xs.max() < x1 and y0 <= ys.min() and ys.max() < y1


def test_a_gate_records_its_shaft_and_links(mats):
    c = Canvas(200, 200, mats)
    c.carve_rect((60, 20, 140, 60), force=True)  # a cave above
    comp = Component(np.ones((40, 80), dtype=bool), 60, 20)
    boxes: list = []
    gx = vertical_gate(c, [100], 70, 150, comp, None, 14, boxes)
    assert gx == 100 and boxes[0] == (93, 70, 107, 150)  # the shaft first
    assert len(boxes) == 3  # then the two bars of the link up to the cave
    assert all(b[2] > b[0] and b[3] > b[1] for b in boxes)


# --------------------------------------------------------------------------------- the blast


def test_the_clear_radius_is_the_blast_of_the_key_and_a_margin():
    # BOMB 60 + EXPLOSIVE_PROJECTILE 15 = 75 (contracts section 14), and 5 cells more
    assert blast_clear_radius() == 80


def test_the_blast_zone_is_a_stadium_round_the_hall_above_the_plug(mats):
    grid = np.full((400, 400), mats["rock"], dtype=np.uint8)
    footprint = (100, 100, 180, 128)  # a scene 80 wide; its plug 16 wide in the floor rows
    plug = (132, 122, 148, 128)
    blast = Blast.of_seal(plug, footprint)
    assert blast.hall == (100, 100, 180, 122)  # the rows above the plug, the whole width
    r = blast.radius
    grid[110, 100 - r] = mats["lava"]  # on the circle round the left side of the hall
    grid[110, 179 + r] = mats["lava"]
    grid[100 - r, 140] = mats["lava"]  # straight above
    grid[121 + r, 140] = mats["lava"]  # straight below the last row of the hall
    grid[110, 99 - r] = mats["lava"]  # one cell beyond
    grid[99 - r, 140] = mats["lava"]
    grid[121 + r + 1, 140] = mats["lava"]
    inside = {(int(x), int(y)) for x, y in blast_violations(grid, mats, blast)}
    assert inside == {(100 - r, 110), (179 + r, 110), (140, 100 - r), (140, 121 + r)}


def test_a_bomb_beside_the_plug_is_in_the_zone_though_it_is_far_from_the_plug(mats):
    """The hall is 80 wide, the plug 16: a bomb that comes to rest at the side of the hall still
    opens the plug, and its crater reaches far beyond a stadium round the plug alone."""
    footprint, plug = (100, 100, 180, 128), (132, 122, 148, 128)
    blast = Blast.of_seal(plug, footprint)
    x, y = footprint[2] - 1 + blast.radius, 110  # on the circle round the hall's right side
    grid = np.full((400, 400), mats["rock"], dtype=np.uint8)
    grid[y, x] = mats["lava"]
    assert len(blast_violations(grid, mats, blast)) == 1
    from_plug = float(np.hypot(x - (plug[2] - 1), y - plug[1]))
    assert from_plug > blast.radius + 30  # clear of the plug's top edge by a wide margin


def test_the_seal_markers_give_the_blast_zone_of_the_scene_that_holds_the_plug():
    scene = {"type": "encounter", "footprint": {"x": 100, "y": 100, "w": 80, "h": 28}}
    seal = {"type": "seal", "x": 132, "y": 122, "w": 16, "h": 6}
    other = {"type": "encounter", "footprint": {"x": 300, "y": 40, "w": 80, "h": 40}}
    placeholder = {"type": "encounter", "placeholder": True}
    blasts = seal_blasts([other, placeholder, scene, seal])
    assert [b.hall for b in blasts] == [(100, 100, 180, 122)]
    assert seal_blasts([other, placeholder, seal]) == []  # no scene round the plug: no zone


# ------------------------------------------------------------------------- generated worlds


def test_the_world_records_its_lanes(world_a, world_b):
    for w in (world_a, world_b):
        rec = w.meta["clearance"]
        assert rec["reach"] == [1, 1, 7, 2] and rec["blast_radius"] == 80
        lanes = lanes_of(w)
        assert len(lanes) == 9  # the 8 band scenes and the sealed deep
        must_pass = {
            (m["encounter_id"], (m["footprint"]["x"], m["footprint"]["y"]))
            for m in w.markers
            if m["type"] == "encounter" and m["must_pass"]
        }
        assert {(lane.encounter_id, lane.footprint[:2]) for lane in lanes} == must_pass
        for lane in lanes:
            if lane.encounter_id == "E06":
                assert len(lane.tunnels) == 3  # the shaft and the two bars of its link
            else:
                assert len(lane.tunnels) == 6  # three bars up, three down
            for t in lane.tunnels:
                assert 0 <= t[0] < t[2] <= w.width and 0 <= t[1] < t[3] <= w.height


def test_no_hazard_is_in_reach_of_a_lane_or_of_the_blast(world_a, world_b, bm, mats):
    for w in (world_a, world_b):
        rep = run_checks(w, bm, mats)
        assert rep.ok, rep.failures
        assert rep.stats["clearance"] == {
            "lanes": 9,
            "hazard_cells_in_reach": 0,
            "hazard_cells_in_blast": 0,
        }
        for lane in lanes_of(w):
            assert len(lane_violations(w.grid, mats, lane)) == 0, lane.encounter_id


def test_the_keepout_is_what_removes_the_hazards(mats, bm, monkeypatch):
    """Seed 17 without the keepout has lava in reach of E12 and in the blast zone (the bot found
    it dead on the corridor floor); with it, the same attempt has none."""
    ctx = SceneContext.build(get_rules(17), mats)

    def counts(world) -> tuple[int, int]:
        lane = sum(len(lane_violations(world.grid, mats, ln)) for ln in lanes_of(world))
        blast = sum(len(blast_violations(world.grid, mats, b)) for b in seal_blasts(world.markers))
        return lane, blast

    with monkeypatch.context() as m:
        m.setattr(clearance, "keepout_mask", lambda grid, *_: np.zeros(grid.shape, dtype=bool))
        lane, blast = counts(generate._build(17, 17, 17, 0, bm, mats, ctx))
    assert lane > 0 and blast > 0
    assert counts(generate._build(17, 17, 17, 0, bm, mats, ctx)) == (0, 0)


def test_the_keepout_covers_the_zones_and_nothing_hazardous_is_in_it(world_a, mats):
    lanes = lanes_of(world_a)
    mask = keepout_mask(world_a.grid, mats, lanes, _blast_of(world_a))
    assert mask.any()
    for lane in lanes:  # the zone is inside the mask
        (x0, y0, x1, y1), zone = lane_zone(world_a.grid, mats, lane)
        assert (mask[y0:y1, x0:x1] | ~zone).all()
    # outside the scenes themselves no hazard lies in the mask
    inside = np.zeros(mask.shape, dtype=bool)
    for lane in lanes:
        fx0, fy0, fx1, fy1 = lane.footprint
        inside[fy0:fy1, fx0:fx1] = True
    assert not (mask & ~inside & clearance.hazard_mask(mats, world_a.grid)).any()


# --------------------------------------------------------------------- negative controls


def _quiet_rock_cells(world, mats, mask: np.ndarray) -> np.ndarray:
    """Cells of ``mask`` that are rock with only static cells around them (so a cell of lava
    there is at rest and sealed: only the clearance can complain about it)."""
    static = mats.kind_mask(world.grid, "static")
    around = binary_dilation(~static, structure=np.ones((5, 5), dtype=bool))
    return mask & (world.grid == mats["rock"]) & ~around


def _lane_zone_outside(world, mats, lane: Lane) -> np.ndarray:
    """The zone of ``lane`` as a mask over the whole grid, without the scene's own footprint."""
    (x0, y0, x1, y1), zone = lane_zone(world.grid, mats, lane)
    full = np.zeros(world.grid.shape, dtype=bool)
    full[y0:y1, x0:x1] = zone
    fx0, fy0, fx1, fy1 = lane.footprint
    full[fy0:fy1, fx0:fx1] = False
    return full


def _blast_of(world) -> Blast:
    (blast,) = seal_blasts(world.markers)
    return blast


@pytest.mark.parametrize("scene", ["E12", "E02", "E06"])
def test_lava_painted_into_the_zone_of_a_lane_is_noticed(world_a, bm, mats, scene):
    w = _mutated(world_a)
    lane = next(ln for ln in lanes_of(w) if ln.encounter_id == scene)
    cells = np.argwhere(_quiet_rock_cells(w, mats, _lane_zone_outside(w, mats, lane)))
    assert len(cells), f"no quiet rock cell in the zone of {scene}"
    y, x = (int(v) for v in cells[len(cells) // 2])
    assert _clearance_failures(w, bm, mats) == []
    w.grid[y, x] = mats["lava"]
    fails = [f for f in _clearance_failures(w, bm, mats) if scene in f]  # E06 is in the blast too
    assert len(fails) == 1 and "1 lava" in fails[0] and f"({x}, {y})" in fails[0], fails


def test_lava_just_outside_the_zone_is_not_a_violation(world_a, bm, mats):
    w = _mutated(world_a)
    lanes = lanes_of(w)
    mask = keepout_mask(w.grid, mats, lanes, _blast_of(w))
    lane = next(ln for ln in lanes if ln.encounter_id == "E12")
    (x0, y0, x1, y1), zone = lane_zone(w.grid, mats, lane)
    rim = np.zeros(w.grid.shape, dtype=bool)
    rim[y0:y1, x0:x1] = binary_dilation(zone, iterations=2) & ~zone
    cells = np.argwhere(_quiet_rock_cells(w, mats, rim & ~mask))
    assert len(cells), "no quiet rock cell just outside the zone of E12"
    y, x = (int(v) for v in cells[len(cells) // 2])
    w.grid[y, x] = mats["lava"]
    assert _clearance_failures(w, bm, mats) == []


def test_lava_painted_into_the_blast_zone_is_noticed(world_a, bm, mats):
    w = _mutated(world_a)
    (x0, y0, x1, y1), zone = _blast_of(w).zone(w.grid.shape)
    others = keepout_mask(w.grid, mats, lanes_of(w), None)  # the lane zones: not the point here
    # a cell inside, near the rim (79 or 80 cells from the hall above the plug), and one beyond it
    rim = np.zeros(w.grid.shape, dtype=bool)
    rim[y0:y1, x0:x1] = binary_dilation(~zone, iterations=3) & zone
    inside = np.argwhere(_quiet_rock_cells(w, mats, rim & ~others))
    assert len(inside), "no quiet rock cell near the rim of the blast zone"
    y, x = (int(v) for v in inside[len(inside) // 2])
    w.grid[y, x] = mats["lava"]
    fails = _clearance_failures(w, bm, mats)
    assert len(fails) == 1 and "blast radius" in fails[0] and f"({x}, {y})" in fails[0], fails
    w.grid[y, x] = mats["rock"]
    beyond = np.zeros(w.grid.shape, dtype=bool)
    beyond[y0:y1, x0:x1] = binary_dilation(zone, iterations=3) & ~zone
    out = np.argwhere(_quiet_rock_cells(w, mats, beyond & ~others))
    assert len(out), "no quiet rock cell just outside the blast zone"
    y, x = (int(v) for v in out[len(out) // 2])
    w.grid[y, x] = mats["lava"]
    assert _clearance_failures(w, bm, mats) == []


def test_acid_and_fire_count_like_lava(world_a, bm, mats):
    for key in ("acid", "fire"):
        w = _mutated(world_a)
        lane = next(ln for ln in lanes_of(w) if ln.encounter_id == "E12")
        cells = np.argwhere(_quiet_rock_cells(w, mats, _lane_zone_outside(w, mats, lane)))
        y, x = (int(v) for v in cells[0])
        w.grid[y, x] = mats[key]
        fails = [f for f in _clearance_failures(w, bm, mats) if "E12" in f]
        assert len(fails) == 1 and f"1 {key}" in fails[0], fails


def test_a_lane_that_was_not_recorded_is_noticed(world_a, bm, mats):
    w = _mutated(world_a)
    lanes = w.meta["clearance"]["lanes"]
    w.meta["clearance"]["lanes"] = [r for r in lanes if r["encounter_id"] != "E02"]
    fails = _clearance_failures(w, bm, mats)
    assert len(fails) == 1 and "E02" in fails[0] and "no lane" in fails[0], fails
    del w.meta["clearance"]  # a world with no record at all misses every lane
    assert len(_clearance_failures(w, bm, mats)) == 9


def test_the_check_names_what_lies_in_reach(world_a, mats):
    w = _mutated(world_a)
    lane = next(ln for ln in lanes_of(w) if ln.encounter_id == "E12")
    cells = np.argwhere(_quiet_rock_cells(w, mats, _lane_zone_outside(w, mats, lane)))[:3]
    for (y, x), key in zip(cells, ("lava", "lava", "acid")):
        w.grid[y, x] = mats[key]
    failures: list[str] = []
    stats: dict = {}
    check_clearance(w, mats, failures, stats)
    assert any("1 acid, 2 lava" in f for f in failures), failures
    assert stats["clearance"]["hazard_cells_in_reach"] == 3


# ---------------------------------------------------------------- the keepout in placement


def _cave(mats) -> Canvas:
    """Two caves with flat floors at row 90, a rock wall between them (a basin each)."""
    c = Canvas(200, 130, mats)
    c.carve_rect((30, 40, 80, 90), force=True)
    c.carve_rect((120, 40, 170, 90), force=True)
    return c


def _dense_pools(biome):
    style = dataclasses.replace(
        biome.pools, attempts_per_10k=400.0, max_area=5000, depth_min=2, depth_max=3
    )
    return dataclasses.replace(biome, pools=style)


def test_lava_pools_keep_out_of_the_keepout_and_other_pools_do_not(bm, mats):
    lava_biome = _dense_pools(bm.biomes["lava_deeps"])  # its pools are lava only
    free = _cave(mats)
    assert features.place_pools(free, lava_biome, (0, 0, 200, 130), np.random.default_rng(1)) > 0
    assert (free.grid == mats["lava"]).any()
    kept = _cave(mats)
    kept.keepout[:, :100] = True  # the left cave is within reach of a corridor
    features.place_pools(kept, lava_biome, (0, 0, 200, 130), np.random.default_rng(1))
    lava = kept.grid == mats["lava"]
    assert lava[:, 100:].any() and not lava[:, :100].any()  # lava in the right cave only
    water_biome = _dense_pools(bm.biomes["mine"])  # a harmless liquid may lie anywhere
    wet = _cave(mats)
    wet.keepout[:, :] = True
    assert features.place_pools(wet, water_biome, (0, 0, 200, 130), np.random.default_rng(1)) > 0


def test_a_lava_pocket_keeps_out_of_the_keepout(mats):
    params = {"per_10k": 120.0, "w": [8, 14], "depth": [5, 8], "crust": [2, 3]}
    c = Canvas(200, 160, mats)
    c.grid[:] = mats["ground"]
    c.carve_rect((20, 40, 180, 110), force=True)
    c.keepout[:, :100] = True
    ctx = hz.Ctx(c, (0, 0, 200, 160), np.random.default_rng(1))
    assert hz.lava_crust(ctx, params) >= 1
    lava = c.grid == mats["lava"]
    assert lava.any() and not (lava & c.keepout).any()


def _scene_slot(bm, mats, keepout: bool, scene: str):
    ctx = SceneContext.build(get_rules(1), mats)
    c = Canvas(500, 420, mats)
    c.carve_rect((10, 10, 490, 410), force=True)
    c.keepout[:, :] = keepout
    comp = Component(np.ones((400, 480), dtype=bool), 10, 10)
    biome = bm.biomes["lava_deeps"]
    rng = np.random.default_rng(2)
    return layers._try_slot(c, biome, 3, scene, (10, 10, 490, 410), comp, [], rng, ctx)


def test_a_scene_with_lava_in_its_art_is_not_stamped_into_the_keepout(bm, mats):
    assert _scene_slot(bm, mats, False, "E02") is not None  # E02: a river of lava
    assert _scene_slot(bm, mats, True, "E02") is None
    assert _scene_slot(bm, mats, True, "E08") is not None  # E08: water only, harmless anywhere


# ----------------------------------------------------------- the engine, on real terrain


def _attempt(seed: int, mats, bm, monkeypatch, keepout: bool):
    """The first attempt of ``seed`` (what the generator builds before any check), with or
    without the keepout for hazards."""
    if not keepout:
        monkeypatch.setattr(
            clearance, "keepout_mask", lambda grid, *_: np.zeros(grid.shape, dtype=bool)
        )
    return generate._build(seed, seed, seed, 0, bm, mats, SceneContext.build(get_rules(seed), mats))


def _standing_places(world, mats, lane: Lane) -> list[tuple[int, int, int]]:
    """``(x, y, hazard cells in its hit box)`` for every place in the lane's footprint where the
    collision box (top-left cell ``(x, y)``) fits on free cells and stands on a static one."""
    r = player_reach()
    x0, y0, x1, y1 = lane.footprint
    free = ~mats.kind_mask(world.grid, "static")
    hazard = clearance.hazard_mask(mats, world.grid)
    places = []
    for y in range(y0, y1 - PLAYER_H):
        for x in range(x0, x1 - PLAYER_W):
            if free[y : y + PLAYER_H, x : x + PLAYER_W].all() and not free[y + PLAYER_H, x]:
                box = hazard[y - r.up : y + PLAYER_H + r.down, x - r.left : x + PLAYER_W + r.right]
                places.append((x, y, int(box.sum())))
    return places


def _game_at(world, mats, tmp_path, window: tuple[int, int, int, int], spawn=None) -> Game:
    """A game in a window of the world; the player stands with his collision box at ``spawn``
    (top-left cell), or nobody does."""
    x0, y0, x1, y1 = window
    markers = (
        []
        if spawn is None
        else [
            {
                "type": "spawn_player",
                "x": spawn[0] + PLAYER_W // 2 - x0,
                "y": spawn[1] + PLAYER_H - 1 - y0,
            }
        ]
    )
    crop = type(world)(1, 0, world.grid[y0:y1, x0:x1].copy(), 128, [["lab"]], markers, {})
    png, js = crop.write(tmp_path, "crop", mats)
    return Game.from_world(png, js, 1)


def _hurt_at(world, mats, tmp_path, x: int, y: int) -> bool:
    window = (max(0, x - 70), max(0, y - 60), min(world.width, x + 70), min(world.height, y + 60))
    g = _game_at(world, mats, tmp_path, window, (x, y))
    g.step(120)
    p = g.player()
    return p["hp"] < p["hp_max"] or "on_fire" in p["statuses"]


def test_a_player_in_the_strata_of_seed_1_is_burnt_without_the_keepout_and_safe_with_it(
    mats, bm, monkeypatch, tmp_path
):
    """The bot died on the floor of E12's first corridor on a seed like this one: a lava lake lay
    three rows of rock above it (seed 17 until the scenes of batch G1 moved the layouts; seed 1
    now). Without the keepout the engine burns the player standing there; with it, nobody who
    stands anywhere in the strata (every third place) takes damage in 2 seconds."""
    with monkeypatch.context() as m:
        world = _attempt(1, mats, bm, m, keepout=False)
    lane = next(ln for ln in lanes_of(world) if ln.encounter_id == "E12")
    x, y, cells = max(_standing_places(world, mats, lane), key=lambda p: p[2])
    assert cells >= 6, "pick another seed: E12 has no lava in reach of its floor on this one"
    assert _hurt_at(world, mats, tmp_path, x, y)

    world = _attempt(1, mats, bm, monkeypatch, keepout=True)
    lane = next(ln for ln in lanes_of(world) if ln.encounter_id == "E12")
    places = _standing_places(world, mats, lane)
    assert len(places) > 100 and max(c for _, _, c in places) == 0
    assert not [p for p in places[::3] if _hurt_at(world, mats, tmp_path, p[0], p[1])]


def _blast_leaks(world, mats, tmp_path, bombs: list[int]) -> list[tuple[int, int]]:
    """``(vault, hall)`` lava cells after the key's explosion (radius 75, durability 14) went off
    one cell above the floor of the hall at each x of ``bombs``, one world each."""
    seal = next(m for m in world.markers if m["type"] == "seal")
    room = seal["room"]
    window = (
        max(0, bombs[0] - 200),
        seal["y"] - 160,
        min(world.width, bombs[-1] + 200),
        world.height,
    )
    leaks = []
    for x in bombs:
        g = _game_at(world, mats, tmp_path, window)
        g.blast(x - window[0], seal["y"] - 2 - window[1], 75, 0.0, 6_000_000, 14, 40)
        g.step(900)
        grid = np.frombuffer(g.grid(), dtype=np.uint8).reshape(
            window[3] - window[1], window[2] - window[0]
        )
        lava = grid == mats["lava"]
        vault = lava[room["y"] - window[1] : room["y"] + room["h"] - window[1]].sum()
        hall = lava[seal["y"] - window[1] - 22 : seal["y"] - window[1]].sum()
        leaks.append((int(vault), int(hall)))
    return leaks


def test_the_blast_of_the_key_lets_no_lava_into_the_hall_or_the_vault(
    mats, bm, monkeypatch, tmp_path
):
    """The bomb with the explosive modifier (radius 75, durability 14) may come to rest anywhere
    on the hall floor, not only on the plug: on seed 21 without the keepout lava runs into the
    sealed room from a bomb at the side of the hall (the zone round the plug alone missed it);
    with it, no bomb from one end of the hall to the other lets any lava loose."""
    with monkeypatch.context() as m:
        loose = _attempt(21, mats, bm, m, keepout=False)
    seal = next(m for m in loose.markers if m["type"] == "seal")
    (blast,) = seal_blasts(loose.markers)
    left, right = blast.hall[0] + 4, blast.hall[2] - 4  # inside the walls of the hall
    bombs = [left, seal["x"] + seal["w"] // 2, right]
    assert sum(sum(leak) for leak in _blast_leaks(loose, mats, tmp_path, bombs)) > 0, (
        "pick another seed: no lava is within the blast on this one"
    )
    safe = _attempt(21, mats, bm, monkeypatch, keepout=True)
    assert _blast_leaks(safe, mats, tmp_path, bombs) == [(0, 0)] * 3
