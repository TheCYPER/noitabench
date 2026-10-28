"""Room layout of the brick ruins and the abandoned workshop (rooms.py)."""

from __future__ import annotations

import numpy as np
import pytest
from noitabench.worldgen.canvas import PLAYER_H, PLAYER_W
from noitabench.worldgen.rooms import layout_rooms
from scipy.ndimage import binary_erosion, label

SIZE = (256, 384)
RING = 6


def _layout(bm, key, seed):
    return layout_rooms(SIZE, RING, bm.biomes[key].rooms, np.random.default_rng(seed))


@pytest.mark.parametrize("key", ["workshop", "brick_ruins"])
@pytest.mark.parametrize("seed", range(5))
def test_every_room_can_be_reached_from_every_other(bm, key, seed):
    cave, rooms, doors = _layout(bm, key, seed)
    fit = binary_erosion(cave, structure=np.ones((PLAYER_H, PLAYER_W), dtype=bool))
    n = label(fit)[1]
    assert n == 1, f"{n} separate areas"
    assert len(rooms) >= 6 and doors


@pytest.mark.parametrize("key", ["workshop", "brick_ruins"])
def test_rooms_are_walled_apart_and_inside_the_ring(bm, key):
    style = bm.biomes[key].rooms
    for seed in range(5):
        rooms = _layout(bm, key, seed)[1]
        for r in rooms:
            assert r.x0 >= RING + style.margin[0] and r.y0 >= RING + style.margin[0]
            assert r.x1 <= SIZE[0] - RING - style.margin[0] and r.y1 <= SIZE[1] - RING
            assert r.h >= 20 and r.w >= 30  # roomy: the player and its decor fit
        for i, a in enumerate(rooms):
            for b in rooms[i + 1 :]:
                apart_x = a.x1 + 2 * style.margin[0] <= b.x0 or b.x1 + 2 * style.margin[0] <= a.x0
                apart_y = a.y1 + 2 * style.margin[0] <= b.y0 or b.y1 + 2 * style.margin[0] <= a.y0
                assert apart_x or apart_y, f"rooms {a} and {b} are too close"


def test_doors_are_wide_enough_for_the_player(bm):
    style = bm.biomes["workshop"].rooms
    _, _, doors = _layout(bm, "workshop", 1)
    for x0, y0, x1, y1 in doors:
        assert min(x1 - x0, y1 - y0) >= min(style.door_w, style.door_h) - 1


def test_the_layout_is_deterministic_and_seed_dependent(bm):
    a = _layout(bm, "workshop", 3)[0]
    assert np.array_equal(a, _layout(bm, "workshop", 3)[0])
    assert not np.array_equal(a, _layout(bm, "workshop", 4)[0])


def test_ruins_crumble_at_the_edges_and_the_workshop_does_not(bm):
    assert bm.biomes["brick_ruins"].rooms.ragged > 0
    assert bm.biomes["workshop"].rooms.ragged == 0
    cave, rooms, _ = _layout(bm, "workshop", 2)
    outside = cave.copy()
    for r in rooms:
        outside[r.y0 : r.y1, r.x0 : r.x1] = False
    assert outside.sum() > 0  # doors only
    ragged, rooms, _ = _layout(bm, "brick_ruins", 2)
    inside = np.zeros_like(ragged)
    for r in rooms:
        inside[r.y0 : r.y1, r.x0 : r.x1] = True
    assert (ragged & ~inside).sum() > outside.sum()
