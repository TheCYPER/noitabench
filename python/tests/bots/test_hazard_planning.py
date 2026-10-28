"""How the planner treats lava: the stand for a pour, the ring a fall can reach, a fall that a
floor stops, the room the blast opens."""

from __future__ import annotations

import numpy as np
import pytest
from mini_world import write_world
from noitabench.bots.crossing import MIN_STAND_DISTANCE, STAND_DISTANCE, pour_stand
from noitabench.bots.descend import Descent
from noitabench.bots.navfield import build_field
from noitabench.bots.pilot import Pilot
from noitabench.bots.terrain import FORBIDDEN_KEYS, Body, Materials, analyse

BODY = Body.load()


def grid_of(mats: Materials, rows: list[str]) -> np.ndarray:
    key = {".": "air", "#": "rock", "g": "ground", "L": "lava", "B": "brick", "w": "water"}
    return np.array([[mats.index(key[c]) for c in row] for row in rows], dtype=np.uint8)


# -- the ring only counts what a fall or a wobble can reach ---------------------------------------


def test_lava_sealed_in_rock_adds_no_ring_cost_but_still_burns_through_the_wall(
    mats: Materials,
) -> None:
    rock, air, lava = (mats.index(k) for k in ("rock", "air", "lava"))
    open_hall = np.full((30, 40), rock, dtype=np.uint8)
    open_hall[1:25, 1:39] = air
    sealed = open_hall.copy()
    open_hall[5, 18:21] = lava  # lava in the hall
    sealed[2:5, 1:39] = rock  # a seam of lava over the hall, in rock
    sealed[3, 18:21] = lava
    t_open = analyse(open_hall, mats, BODY, dig_max_durability=10)
    t_sealed = analyse(sealed, mats, BODY, dig_max_durability=10)
    assert t_open.near_hazard.any()  # the ring: a fall into the hall's lava
    assert not t_sealed.near_hazard.any()  # nothing a wobble can reach
    assert t_sealed.contact.any()  # but the hit box (14 above the feet) still burns through rock


def test_a_lava_cell_that_touches_open_space_counts_for_the_ring(mats: Materials) -> None:
    rows = ["#" * 40] + ["#" + "." * 38 + "#"] * 12 + ["#" * 40]
    rows[10] = "#" + "." * 18 + "L" + "." * 19 + "#"
    t = analyse(grid_of(mats, rows), mats, BODY, dig_max_durability=10)
    assert t.near_hazard[8, 14] and t.near_hazard[8, 23]  # (the ring is wide at the sides)


# -- where to stand for a pour ----------------------------------------------------------------------


def ledge(mats: Materials, width: int) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """A floor at row 20 with lava from x = 40 on, and `width` cells of floor before it; a way
    from the far left that climbs along it."""
    g = np.full((40, 80), mats.index("rock"), dtype=np.uint8)
    g[8:20, 2:78] = mats.index("air")
    g[19, 40:] = mats.index("lava")
    g[20:, 40:] = mats.index("rock")
    path = [(x, 12) for x in range(40 - width, 3, -1)][::-1]  # box tops 12..18: feet at row 19
    return g, path


def test_the_stand_is_the_nearest_place_that_is_far_enough_and_clear_of_the_ring(
    mats: Materials,
) -> None:
    g, _ = ledge(mats, 40)
    t = analyse(g, mats, BODY, dig_max_durability=10)
    path = [(x, 13) for x in range(4, 38)]
    first = len(path) - 1  # (the last step, next to the lava, is the exposed one)
    target = (40, 19)
    x, y = pour_stand(t, path, first, target, BODY)
    hand = (x + BODY.hand_dx + 0.5, y + BODY.hand_dy + 0.5)
    distance = float(np.hypot(hand[0] - 40.5, hand[1] - 19.5))
    assert distance >= STAND_DISTANCE and t.grounded[y, x] and not t.near_hazard[y, x]
    assert distance < STAND_DISTANCE + 2  # the nearest such place, not the start of the way


def test_on_a_short_ledge_the_stand_is_the_nearest_place_that_touches_nothing(
    mats: Materials,
) -> None:
    g, _ = ledge(mats, 40)
    # a ledge only 8 cells wide before the lava: the rest of the way is flown over a pit
    g[19:30, 2:32] = mats.index("air")
    t = analyse(g, mats, BODY, dig_max_durability=10)
    path = [(x, 13) for x in range(4, 38)]
    x, y = pour_stand(t, path, len(path) - 1, (40, 19), BODY)
    assert t.grounded[y, x] and not t.contact[y, x]
    hand_dx = x + BODY.hand_dx + 0.5 - 40.5
    assert abs(hand_dx) >= MIN_STAND_DISTANCE - 1  # in reach of the lava, nowhere near the start
    assert x >= 29


def test_with_no_ground_at_all_the_stand_is_the_start_of_the_way(mats: Materials) -> None:
    g = np.full((40, 80), mats.index("rock"), dtype=np.uint8)
    g[8:30, 2:78] = mats.index("air")
    t = analyse(g, mats, BODY, dig_max_durability=10)
    path = [(x, 10) for x in range(4, 30)]
    assert pour_stand(t, path, len(path) - 1, (60, 25), BODY) == path[0]


# -- a fall that a floor stops ---------------------------------------------------------------------


def pilot_over(mats: Materials, rows: list[str]) -> Pilot:
    grid = grid_of(mats, rows)
    terrain = analyse(grid, mats, BODY, dig_max_durability=10)
    goal = next(
        (x, y) for y in range(terrain.height) for x in range(terrain.width) if terrain.free[y, x]
    )
    return Pilot(
        mats,
        terrain,
        build_field(terrain, goal),
        grid,
        rebuild=lambda: (terrain, build_field(terrain, goal)),
        hazard_ids=mats.ids(FORBIDDEN_KEYS),
    )


def test_lava_under_a_floor_is_not_a_hazard_below(mats: Materials) -> None:
    hall = ["#" * 30] + ["#" + "." * 28 + "#"] * 10
    behind_floor = [*hall, "#" * 30, "#" * 30, "#LLLLLLLLLLLLLLLLLLLLLLLLLLLL#", "#" * 30]
    open_pit = [*hall, "#" + "." * 28 + "#", "#" + "L" * 28 + "#", "#" * 30]
    assert not pilot_over(mats, behind_floor)._hazard_below(10, 3)
    assert pilot_over(mats, open_pit)._hazard_below(10, 3)
    assert not pilot_over(mats, hall + ["#" * 30])._hazard_below(10, 3)


# -- the room the blast opens -----------------------------------------------------------------------


def test_the_hazard_on_the_way_down_is_counted_around_the_breach(tmp_path, mats: Materials) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=3000)
    assert bot.hazard_in_the_way() == 0
    plug, room = bot.geometry.plug, bot.geometry.room
    bot.game.fill_rect(plug.x, plug.y + 2, 3, 4, "lava")  # 12 cells in the channel
    bot.game.fill_rect(plug.x - 80, plug.y - 5, 5, 5, "lava")  # far to the side: not counted
    assert bot.hazard_in_the_way() == 12
    bot.game.fill_rect(plug.x, room.y + 5, 6, 3, "lava")  # inside the room: not counted either
    assert bot.hazard_in_the_way() == 12


def test_the_bot_waits_for_a_flowing_hazard_but_not_for_a_still_one(
    tmp_path, mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=3000)
    counts = iter([300, 200, 100, 20, 5, 5, 5])
    monkeypatch.setattr(bot, "hazard_in_the_way", lambda: next(counts))
    bot.wait_for_calm()
    assert sum(e["event"] == "bottom_hazard" for e in bot.log) == 4  # 300, 200, 100, 20
    still = iter([60, 60, 60, 60])
    monkeypatch.setattr(bot, "hazard_in_the_way", lambda: next(still))
    bot.log.clear()
    bot.wait_for_calm()
    assert sum(e["event"] == "bottom_hazard" for e in bot.log) == 2  # the same count three times


def test_the_bottom_goal_keeps_clear_of_lava_where_the_room_allows(
    tmp_path, mats: Materials
) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=3000)
    room = bot.geometry.room
    plain = bot.bottom_goal()
    assert plain[1] + BODY.h == room.bottom  # the floor of the room
    # lava over the floor next to the breach: the goal moves off to where nothing is near
    bot.game.fill_rect(room.x, room.bottom - 2, room.w - 20, 2, "lava")
    x, y = bot.bottom_goal()
    terrain = bot.terrain_now()
    assert terrain.free[y, x] and not terrain.near_hazard[y, x]
    assert x > room.x + room.w - 24
