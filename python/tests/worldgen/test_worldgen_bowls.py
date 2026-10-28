"""Alchemy bowls (bowls.py, alchemy.place_cave_bowls): metal basins sunk into the floor."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from noitabench.worldgen import alchemy, bowls
from noitabench.worldgen.bowls import BowlSpec, bowl_intact, stamp_bowl
from noitabench.worldgen.canvas import Canvas
from noitabench.worldgen.config import CONTENT_DIR, load_biome_map

SPEC = BowlSpec(20, 10, 2)
W, H = 200, 140
FLOOR = 80  # the first solid row of the test cave


def _cave(mats, x0=20, x1=180, y0=30, floor=FLOOR) -> Canvas:
    """Ground all through, with a cave whose flat floor starts at row ``floor``."""
    c = Canvas(W, H, mats)
    c.grid[:] = mats["ground"]
    c.carve_rect((x0, y0, x1, floor), force=True)
    return c


def _build(c: Canvas, mats, count=1, near=None, inner=(10, 10, W - 10, H - 10), anchors=(), seed=1):
    near = np.ones(c.grid.shape, dtype=bool) if near is None else near
    rect = (0, 0, W, H)
    rng = np.random.default_rng(seed)
    return alchemy.place_cave_bowls(c, SPEC, count, rect, inner, rng, near, anchors, [])


# ----------------------------------------------------------------------------- geometry


def test_a_bowl_is_an_open_basin_in_metal():
    assert (SPEC.outer_w, SPEC.outer_h) == (24, 12)
    assert SPEC.outer(100, 50) == (100, 50, 124, 62)
    assert SPEC.interior(100, 50) == (
        102,
        50,
        122,
        60,
    )  # open to the top, walls beside, bottom below


def test_stamping_a_bowl_leaves_metal_walls_and_bottom_and_an_open_interior(mats):
    c = Canvas(60, 40, mats)
    marker = stamp_bowl(c, SPEC, 10, 5, "rest")
    assert marker == {"type": "alchemy_bowl", "x": 12, "y": 5, "w": 20, "h": 10, "place": "rest"}
    metal, air = mats["metal"], mats.air
    assert (c.grid[5:15, 12:32] == air).all()  # the interior
    assert (c.grid[5:17, 10:12] == metal).all() and (c.grid[5:17, 32:34] == metal).all()  # walls
    assert (c.grid[15:17, 10:34] == metal).all()  # the bottom
    assert c.grid[4, 10] == mats["rock"] and c.grid[5, 9] == mats["rock"]  # nothing outside
    assert bowl_intact(c.grid, metal, air, SPEC, marker) == ""


def test_damage_to_a_bowl_is_named(mats):
    c = Canvas(60, 40, mats)
    marker = stamp_bowl(c, SPEC, 10, 5, "cave")
    metal, air = mats["metal"], mats.air
    broken = c.grid.copy()
    broken[8, 11] = mats["rock"]
    assert "wall or the bottom" in bowl_intact(broken, metal, air, SPEC, marker)
    dirty = c.grid.copy()
    dirty[14, 20] = mats["sand"]
    assert "interior is not empty" in bowl_intact(dirty, metal, air, SPEC, marker)
    assert "size" in bowl_intact(c.grid, metal, air, BowlSpec(20, 10, 2), {**marker, "w": 18})
    assert "outside" in bowl_intact(c.grid[:12], metal, air, SPEC, marker)


# -------------------------------------------------------------------------- the rest halls


def test_the_rest_hall_has_room_for_a_bowl_at_each_end(bm):
    spec = BowlSpec.from_config(bm.scenes["alchemy"]["bowl"])
    left, right = bowls.hall_spans(bm.scenes["rest"])
    hx0, hx1 = bm.scenes["rest"]["hall"]["x"]
    assert left[0] == hx0 + bowls.PILLAR_END and right[1] == hx1 - bowls.PILLAR_END
    for span in (left, right):
        assert span[1] - span[0] >= bowls.span_room(spec)
    bx_left = bowls.hall_bowl_x(spec, left, "left")
    bx_right = bowls.hall_bowl_x(spec, right, "right")
    assert bx_left == left[0] + bowls.SIDE_GAP
    assert bx_right + spec.outer_w == right[1] - bowls.SIDE_GAP
    for xs, side, bx in (
        (bowls.hall_bottle_xs(spec, bx_left, "left", 2), "left", bx_left),
        (bowls.hall_bottle_xs(spec, bx_right, "right", 2), "right", bx_right),
    ):
        span = left if side == "left" else right
        assert all(span[0] <= x < span[1] for x in xs) and len(set(xs)) == 2
        assert all(not (bx <= x < bx + spec.outer_w) for x in xs)  # beside the bowl, not on it


def test_a_rest_hall_too_narrow_for_its_bowl_is_rejected(tmp_path):
    dst = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, dst)
    path = dst / "biome_map.json"
    data = json.loads(path.read_text())
    data["scenes"]["rest"]["hall"]["x"] = [252, 516]  # the old hall: 11 free cells beside the slots
    for slot, anchor in zip(data["scenes"]["rest"]["slots"], (0.2, 0.8)):
        slot["anchor"] = anchor
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=r"scenes\.rest\.hall\.x.*bowl"):
        load_biome_map(dst)


@pytest.mark.parametrize(
    "edit, field",
    [
        (lambda a: a["bowl"].update(w=8), "scenes.alchemy.bowl"),
        (lambda a: a["bowl"].update(wall=1), "scenes.alchemy.bowl"),
        (lambda a: a.update(early_empty_bottles=99), "early_empty_bottles"),
        (lambda a: a.update(min_cells=0), "scenes.alchemy.min_cells"),
        (lambda a: a.pop("reach"), "scenes.alchemy.reach"),
    ],
)
def test_bad_alchemy_settings_name_their_field(tmp_path, edit, field):
    dst = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, dst)
    path = dst / "biome_map.json"
    data = json.loads(path.read_text())
    edit(data["scenes"]["alchemy"])
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=field.replace(".", r"\.")):
        load_biome_map(dst)


def test_the_generated_rest_halls_hold_a_bowl_and_two_bottles_each(world_a, bm, mats):
    spec = BowlSpec.from_config(bm.scenes["alchemy"]["bowl"])
    for hall in (m for m in world_a.markers if m["type"] == "rest_area"):
        floor = hall["y"] + hall["h"]
        inside = [
            m
            for m in world_a.markers
            if m["type"] == "alchemy_bowl"
            and m["place"] == "rest"
            and hall["x"] <= m["x"] + m["w"] // 2 < hall["x"] + hall["w"]
            and m["y"] == floor  # sunk: the interior starts at the floor row
        ]
        assert len(inside) == 1
        bowl = inside[0]
        assert bowl_intact(world_a.grid, mats["metal"], mats.air, spec, bowl) == ""
        bottles = [
            m
            for m in world_a.markers
            if m["type"] == "item"
            and m["item"] == "bottle"
            and "contents" not in m
            and hall["x"] <= m["x"] < hall["x"] + hall["w"]
            and m["y"] == floor - 1
        ]
        assert len(bottles) == bm.scenes["alchemy"]["rest_bottles"]
        # the bottles stand beside the bowl on the floor, not over its opening
        assert all(not (bowl["x"] - 2 <= b["x"] < bowl["x"] + bowl["w"] + 2) for b in bottles)
    assert (world_a.grid == mats["potion_heal"]).any()  # the healing pools are still there


# --------------------------------------------------------------------------- cave bowls


def test_a_bowl_is_sunk_into_a_flat_cave_floor_with_its_rim_level_with_it(mats):
    c = _cave(mats)
    [marker] = _build(c, mats)
    assert marker["place"] == "cave" and (marker["w"], marker["h"]) == (20, 10)
    assert marker["y"] == FLOOR  # the rim is the first solid row
    assert bowl_intact(c.grid, mats["metal"], mats.air, SPEC, marker) == ""
    x0 = marker["x"] - SPEC.wall
    # the open box above the rim and the flat floor beside the bowl
    span = slice(x0 - bowls.FLAT_MARGIN, x0 + SPEC.outer_w + bowls.FLAT_MARGIN)
    assert (c.grid[FLOOR - bowls.HEAD_ROOM : FLOOR, span] == mats.air).all()
    side = c.grid[FLOOR, x0 - bowls.FLAT_MARGIN : x0]
    assert (side == mats["ground"]).all()
    assert c.protected[FLOOR : FLOOR + SPEC.outer_h, x0 : x0 + SPEC.outer_w].all()


def test_a_bowl_is_cut_into_the_wall_of_a_low_cave_and_levels_a_lower_floor(mats):
    c = Canvas(W, H, mats)
    c.grid[:] = mats["rock"]
    c.carve_rect((20, 72, 180, FLOOR), force=True)  # a cave only 8 rows high
    c.carve_rect((20, FLOOR, 50, FLOOR + 2), force=True)  # the floor dips by two rows at one end
    [marker] = _build(c, mats, anchors=[(35, FLOOR)])
    x0 = marker["x"] - SPEC.wall
    assert (c.grid[FLOOR - bowls.HEAD_ROOM : FLOOR, x0 : x0 + SPEC.outer_w] == mats.air).all()
    assert bowl_intact(c.grid, mats["metal"], mats.air, SPEC, marker) == ""
    # the low floor beside the bowl has been filled up to the rim
    assert not (c.grid[FLOOR : FLOOR + 3, x0 - bowls.FLAT_MARGIN : x0] == mats.air).any()


@pytest.mark.parametrize(
    "blocker",
    ["water", "flammable_gas", "fire", "sand", "coal", "brick"],
)
def test_a_niche_never_opens_a_pocket_or_cuts_into_brick_or_veins(mats, blocker):
    """A bowl is refused wherever liquid, gas, fire or powder (a coal vein falls into the bowl)
    lies within three cells of its working area, or brick inside it; the cave is too narrow to
    go round the blocker."""
    c = _cave(mats, x0=80, x1=100)  # every site's neighbourhood holds the middle of the cave
    c.grid[FLOOR - 1, 90] = mats[blocker]
    assert _build(c, mats) == []


def test_a_protected_cell_or_the_edge_of_the_region_refuses_a_site(mats):
    c = _cave(mats, x0=80, x1=100)
    c.protected[FLOOR - 5, 90] = True  # a scene wall, a seam or a shaft
    assert _build(c, mats) == []
    d = _cave(mats, x0=80, x1=100)
    assert _build(d, mats, inner=(75, 10, 105, H - 10)) == []  # the region is too narrow
    assert len(_build(_cave(mats, x0=80, x1=100), mats)) == 1  # while the cave alone is fine


def test_a_bowl_that_would_block_a_tunnel_is_undone(mats):
    c = _cave(mats, x0=60, x1=120)
    c.carve_rect((20, FLOOR + 4, 180, FLOOR + 16), force=True)  # a 12-high tunnel under the floor
    before = c.grid.copy()
    near = np.zeros(c.grid.shape, dtype=bool)
    near[:FLOOR] = True  # only the upper cave is within the player's reach
    assert _build(c, mats, near=near) == []
    assert (c.grid == before).all() and not c.protected.any()  # nothing of it stayed


def test_bowls_keep_apart_and_prefer_the_neighbourhood_of_an_anchor(mats):
    c = _cave(mats)
    markers = _build(c, mats, count=2, anchors=[(30, FLOOR)])
    assert len(markers) == 2
    centres = [m["x"] + m["w"] // 2 for m in markers]
    assert abs(centres[0] - centres[1]) >= alchemy.BOWL_APART
    first = _build(_cave(mats), mats, anchors=[(30, FLOOR)])[0]
    assert abs(first["x"] + 10 - 30 - alchemy.BOWL_ANCHOR) <= 8  # about 40 cells from the anchor
    assert _build(_cave(mats), mats, count=0) == []


def test_a_bowl_needs_the_player_to_be_able_to_walk_up_to_it(mats):
    c = _cave(mats)
    near = np.zeros(c.grid.shape, dtype=bool)
    assert _build(c, mats, near=near) == []


def test_the_generated_caves_hold_the_bowls_the_biome_files_ask_for(world_a, bm, mats):
    spec = BowlSpec.from_config(bm.scenes["alchemy"]["bowl"])
    want = sum(b.supply.bowls for b in bm.biomes.values())
    cave = [m for m in world_a.markers if m["type"] == "alchemy_bowl" and m["place"] == "cave"]
    assert len(cave) == want == 3
    for lay in bm.layers:  # a layer holds the bowls its biome files ask for (one, two, none)
        _x0, y0, _x1, y1 = bm.region(lay.mid)
        asked = sum(bm.biomes[k].supply.bowls for k in (lay.left, lay.mid, lay.right))
        assert sum(1 for m in cave if y0 <= m["y"] < y1) == asked
    assert [
        sum(1 for m in cave if bm.region(lay.mid)[1] <= m["y"] < bm.region(lay.mid)[3])
        for lay in bm.layers
    ] == [1, 2, 0]
    for m in cave:
        assert bowl_intact(world_a.grid, mats["metal"], mats.air, spec, m) == ""
        x0 = m["x"] - spec.wall
        assert (world_a.grid[m["y"] - 8 : m["y"], x0 : x0 + spec.outer_w] == mats.air).all()
