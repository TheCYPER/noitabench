"""Biome structures (structures.py): they build only where safe and never cut a passage."""

from __future__ import annotations

import numpy as np
import pytest
from noitabench.worldgen import structures as st
from noitabench.worldgen.biomes import DECOR_NAMES
from noitabench.worldgen.canvas import Canvas
from noitabench.worldgen.fill import RegionInfo
from noitabench.worldgen.rooms import Room

W, H = 220, 140


def _canvas(mats, base="rock") -> Canvas:
    c = Canvas(W, H, mats)
    c.grid[:] = mats[base]
    return c


def _ctx(canvas: Canvas, rooms=(), doors=(), seed=1) -> st.Ctx:
    region = RegionInfo(np.zeros((H, W), dtype=bool), rooms=list(rooms), doors=list(doors))
    return st.Ctx(canvas, (0, 0, W, H), np.random.default_rng(seed), region, [])


def _hall(canvas: Canvas, rect=(20, 20, 200, 100)) -> Room:
    canvas.carve_rect(rect, force=True)
    return Room(*rect)


def test_free_box_needs_air_and_no_protection(mats):
    c = _canvas(mats)
    _hall(c)
    assert st.free_box(c, 30, 30, 60, 60)
    assert not st.free_box(c, 10, 30, 60, 60)  # reaches into the rock
    c.protect((40, 40, 45, 45))
    assert not st.free_box(c, 30, 30, 60, 60)
    c2 = _canvas(mats)
    _hall(c2)
    c2.grid[50, 50] = mats["sand"]
    assert not st.free_box(c2, 30, 30, 60, 60)
    assert st.free_box(c2, 30, 30, 60, 60, powder_ok=True)


def test_mushrooms_have_a_stalk_and_a_wider_cap(mats):
    c = _canvas(mats)
    _hall(c)
    ctx = _ctx(c)
    n = st._mushrooms(ctx, {"per_10k": 400.0, "stalk": [12, 14], "cap_w": [16, 18]})
    assert n >= 1
    wood = c.grid == mats["wood"]
    ys = np.nonzero(wood)[0]
    assert wood[ys.max()].sum() >= 3  # a 3-wide stalk touches the floor
    top = ys.min()
    assert wood[top : top + 3].sum(axis=1).max() > 3  # cap rows are wider than the stalk
    assert not wood[:, :20].any() and not wood[:, 200:].any()  # nothing in the rock


def test_frames_only_replace_rock_never_air(mats):
    c = _canvas(mats)
    c.carve_rect((100, 40, 122, 80), force=True)  # a tunnel 22 wide with a flat ceiling
    before_air = c.grid == mats.air
    ctx = _ctx(c)
    n = st._frames(ctx, {"per_10k": 600.0})
    assert n >= 1
    assert ((c.grid == mats.air) == before_air).all()  # the tunnel is as wide as before
    assert (c.grid == mats["wood"]).any()


def test_seams_are_sealed_oil_in_the_rock(mats):
    c = _canvas(mats, base="ground")
    c.carve_rect((20, 80, 200, 110), force=True)  # a cave with a ceiling to seep from
    ctx = _ctx(c)
    assert st._seams(ctx, {"per_10k": 300.0, "len": [14, 20]}) >= 2
    oil = c.grid == mats["oil"]
    assert oil.sum() > 30
    near = oil.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            near |= np.roll(np.roll(oil, dy, 0), dx, 1)
    around = c.grid[near & ~oil]
    assert set(np.unique(around)) <= {mats["ground"], mats["rock"]}  # no air touches the oil
    ys, _ = np.nonzero(oil)
    assert ys.max() < 80 - 1  # the seal: at least one cell of rock above the cave


def test_pillars_never_reach_both_floor_and_ceiling(mats):
    c = _canvas(mats, base="brick")
    room = _hall(c, (20, 30, 200, 70))
    ctx = _ctx(c, rooms=[room])
    params = {"per_room": [4, 6], "w": [4, 6], "min_room_w": 40, "gap": 10, "broken": 0.3}
    assert st._pillars(ctx, params) >= 3
    inside = c.grid[room.y0 : room.y1, room.x0 : room.x1] == mats["brick"]
    assert inside.any()
    assert not inside.all(axis=0).any()  # every column keeps a gap
    assert (room.h - inside.sum(axis=0).max()) >= 10


def test_a_structure_that_cuts_a_corridor_is_undone(mats):
    c = _canvas(mats)
    c.carve_rect((20, 50, 200, 66), force=True)  # a corridor 16 high
    ctx = _ctx(c)
    before = c.grid.copy()

    def block():
        c.grid[50:66, 100:106] = mats["brick"]  # a wall right across it

    assert ctx.guard((100, 50, 106, 66), block) is False
    assert np.array_equal(c.grid, before)

    def bench():
        c.grid[60:66, 100:112] = mats["brick"]  # a low bench: the corridor stays open above it

    assert ctx.guard((100, 60, 112, 66), bench) is True
    assert (c.grid[60:66, 100:112] == mats["brick"]).all()


def test_platforms_stand_on_a_post_or_stick_out_of_walls(mats):
    c = _canvas(mats)
    _hall(c, (20, 10, 200, 100))
    ctx = _ctx(c)
    assert (
        st._platforms(ctx, {"per_10k": 600.0, "len": [14, 18], "height": [10, 12], "shelf": 0.0})
        >= 1
    )
    assert (c.grid == mats["wood"]).sum() > 40
    c2 = _canvas(mats)
    _hall(c2, (80, 10, 120, 100))  # a shaft 40 wide: the shelf needs a wall within reach
    ctx2 = _ctx(c2)
    assert (
        st._platforms(ctx2, {"per_10k": 600.0, "len": [14, 18], "height": [10, 12], "shelf": 1.0})
        >= 1
    )
    xs = np.nonzero((c2.grid == mats["wood"]).any(axis=0))[0]
    assert xs.min() <= 82 or xs.max() >= 118  # attached to a wall


def test_channels_are_brick_lined_and_flush_with_the_floor(mats):
    c = _canvas(mats, base="brick")
    room = _hall(c, (20, 30, 200, 70))
    ctx = _ctx(c, rooms=[room])
    n = st._channels(ctx, {"per_room": 1.0, "len": [20, 24], "depth": 3, "oil_prob": 1.0})
    assert n == 1
    oil = c.grid == mats["oil"]
    ys, xs = np.nonzero(oil)
    assert ys.min() == room.y1  # flush with the floor: the top row of the trench is the floor row
    assert (c.grid[room.y1 - 1, xs.min() : xs.max() + 1] == mats.air).all()  # open above
    ring = oil.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ring |= np.roll(np.roll(oil, dy, 0), dx, 1)
    # the liquid touches air only from above; its sides and bottom are brick
    sides = c.grid[ring & ~oil & (np.arange(H)[:, None] >= room.y1)]
    assert set(np.unique(sides)) == {mats["brick"]}


def test_barrel_rows_stand_on_the_floor_with_room_above(mats):
    c = _canvas(mats, base="brick")
    room = _hall(c, (20, 30, 200, 70))
    ctx = _ctx(c, rooms=[room])
    params = {
        "per_room": [2, 2],
        "count": [4, 5],
        "spacing": 9,
        "weights": {"barrel_acid": 1.0, "barrel_oil": 1.0, "barrel_gunpowder": 1.0},
    }
    assert st._barrel_rows(ctx, params) >= 6
    assert ctx.markers and all(m["type"] == "item" for m in ctx.markers)
    for m in ctx.markers:
        assert m["item"].startswith("barrel_") and "contents" not in m
        assert c.grid[m["y"], m["x"]] == mats.air and c.grid[m["y"] + 1, m["x"]] == mats["brick"]
        assert (c.grid[m["y"] - st.BARREL_CLEARANCE : m["y"] + 1, m["x"]] == mats.air).all()


def test_breaches_open_the_wall_between_two_rooms(mats):
    c = _canvas(mats, base="brick")
    a, b = _hall(c, (20, 30, 90, 80)), _hall(c, (106, 30, 190, 80))
    ctx = _ctx(c, rooms=[a, b])
    assert st._breaches(ctx, {"per_10k": 40.0}) >= 1
    assert (c.grid[40:70, 90:106] == mats.air).any()


def test_decor_runs_in_a_fixed_order_and_only_what_the_biome_asks_for(bm, mats):
    c = _canvas(mats)
    _hall(c)
    biome = bm.biomes["fungal"]
    region = RegionInfo(np.zeros((H, W), dtype=bool))
    counts, markers = st.place_structures(c, biome, (0, 0, W, H), np.random.default_rng(2), region)
    assert set(counts) == set(biome.decor) and markers == []
    assert [n for n, _ in st.DECOR] == list(dict.fromkeys(n for n, _ in st.DECOR))  # unique names
    assert {n for n, _ in st.DECOR} == DECOR_NAMES


@pytest.mark.parametrize("key", ["mine", "fungal", "oil_cave", "workshop", "brick_ruins"])
def test_every_structure_biome_actually_builds_something(world_a, key):
    built = world_a.meta["built"][key]
    names = {n for n, _ in st.DECOR}
    assert any(v > 0 for k, v in built.items() if k in names), built
