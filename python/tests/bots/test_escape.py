"""Where to run to from a bomb: places along the way back, and any standing place far enough."""

from __future__ import annotations

import dataclasses

import numpy as np
from noitabench.bots.escape import (
    FAR_SPACING,
    cropped,
    far_places,
    frames_between,
)
from noitabench.bots.terrain import Body, Materials, analyse

BODY = Body.load()


def two_halls(mats: Materials) -> np.ndarray:
    """Rock with a hall at the bottom (x 10..110, y 80..99) and a chamber of its own, high up
    and to the left (x 10..50, y 20..39), joined by a shaft at x 14..21."""
    g = np.full((120, 130), mats.index("rock"), dtype=np.uint8)
    air = mats.index("air")
    g[80:100, 10:110] = air
    g[20:40, 10:50] = air
    g[40:80, 14:22] = air
    return g


def test_far_places_are_standing_places_beyond_the_distance_nearest_to_the_origin_first(
    mats: Materials,
) -> None:
    terrain = analyse(two_halls(mats), mats, BODY, dig_max_durability=10)
    centre = (90.0, 95.0)
    spots = far_places(terrain, centre, 60.0, origin=(30.0, 90.0))
    assert spots
    for x, y in spots:
        assert terrain.free[y, x] and terrain.grounded[y, x]
        assert np.hypot(x + BODY.w / 2 - centre[0], y + BODY.h / 2 - centre[1]) >= 60.0
    near_origin = [np.hypot(x - 30, y - 90) for x, y in spots]
    assert near_origin == sorted(near_origin)
    cells = {(x // FAR_SPACING, y // FAR_SPACING) for x, y in spots}
    assert len(cells) == len(spots)  # one per cell of the thinning grid
    assert not far_places(terrain, centre, 500.0, origin=(30.0, 90.0))  # nowhere that far


def test_a_place_in_a_chamber_beside_the_way_is_found_when_the_way_has_none(
    mats: Materials,
) -> None:
    terrain = analyse(two_halls(mats), mats, BODY, dig_max_durability=10)
    spots = far_places(terrain, (100.0, 95.0), 70.0, origin=(15.0, 92.0))
    assert any(y < 40 for _, y in spots)  # the chamber up the shaft


def test_the_frames_to_a_place_are_the_nodes_of_the_cheapest_way(mats: Materials) -> None:
    terrain = analyse(two_halls(mats), mats, BODY, dig_max_durability=10)
    start, goal = (60, 92), (16, 32)
    n = frames_between(terrain, start, goal)
    assert n is not None and 60 <= n <= 160  # along the hall, up the shaft: about 44 + 60 cells
    assert frames_between(terrain, start, goal, per_node=2.0) == 2.0 * n
    # a chamber that cannot be reached without tunnelling (the field of a bot that may not dig)
    g = two_halls(mats)
    g[40:80, 14:22] = mats.index("brick")
    walled = analyse(g, mats, BODY, dig_max_durability=10)
    walled = dataclasses.replace(walled, diggable=walled.free)
    assert frames_between(walled, start, goal) is None


def test_a_cropped_terrain_is_a_window_of_the_masks(mats: Materials) -> None:
    terrain = analyse(two_halls(mats), mats, BODY, dig_max_durability=10)
    window = cropped(terrain, 5, 15, 60, 50)
    assert (window.width, window.height) == (55, 35)
    assert window.free.shape == (35, 55) and window.cost.shape == (35, 55)
    assert np.array_equal(window.free, terrain.free[15:50, 5:60])
    clamped = cropped(terrain, -10, -10, 1000, 1000)
    assert (clamped.width, clamped.height) == (terrain.width, terrain.height)
