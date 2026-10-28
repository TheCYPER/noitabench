"""The bot's map of the world: which boxes fit, what they cost, and the way to the goal."""

from __future__ import annotations

import numpy as np
import pytest
from noitabench.bots import terrain
from noitabench.bots.navfield import GUIDE_DISCOUNT, NO_NODE, build_field, guide_bias
from noitabench.bots.terrain import Body, Materials, analyse, box_sum, hit_sum

BODY = Body.load()


def grid_of(mats: Materials, rows: list[str]) -> np.ndarray:
    """A grid from text rows: `.` air, `#` rock, `g` ground, `L` lava, `s` sand, `B` brick."""
    key = {".": "air", "#": "rock", "g": "ground", "L": "lava", "s": "sand", "B": "brick"}
    return np.array([[mats.index(key[c]) for c in row] for row in rows], dtype=np.uint8)


def test_the_player_numbers_come_from_the_content_files() -> None:
    assert (BODY.w, BODY.h) == (4, 7) and BODY.hit == (-1, -7, 6, 16)
    assert BODY.accel_ground > BODY.accel_air > 0 and BODY.gravity > 0


def test_box_sum_is_the_sum_over_the_box_and_zero_outside_the_world() -> None:
    a = np.arange(30).reshape(5, 6)
    s = box_sum(a, 2, 3)
    assert s[1, 2] == a[1:4, 2:4].sum() and s[0, 0] == a[0:3, 0:2].sum()
    assert s[4, 5] == a[4, 5]  # only the one cell that exists


def test_hit_sum_shifts_the_box_by_its_offset() -> None:
    a = np.zeros((40, 40), dtype=bool)
    a[20, 20] = True  # one cell
    s = hit_sum(a, (-1, -7, 6, 16))  # hit box of a body whose collision box is at (x, y)
    ys, _xs = np.nonzero(s)
    # the cell is inside the hit box for 6 x 16 positions of the collision box
    assert len(ys) == 6 * 16
    assert s[27, 21] == 1 and s[27, 15] == 0  # (x=21, y=27): hit box x 20..25, y 20..35


def test_free_diggable_and_grounded_boxes(mats: Materials) -> None:
    rows = ["#" * 14] + ["#" + "." * 12 + "#"] * 8 + ["#" * 14] * 2  # a hall of rows 1..8
    grid = grid_of(mats, rows)
    t = analyse(grid, mats, BODY, dig_max_durability=10)
    assert t.free[2, 1] and t.grounded[2, 1]  # rows 2..8, the floor is row 9
    assert t.free[1, 1] and not t.grounded[1, 1]  # a cell above the floor
    assert not t.free[0, 1]  # the box would overlap the roof
    assert not t.free[1, 0]  # ... or the wall
    assert t.diggable[0, 1]  # rock can be dug with a bolt (durability 10)
    brick = analyse(grid_of(mats, ["B" * 8] * 8), mats, BODY, dig_max_durability=10)
    assert not brick.diggable.any()  # brick (durability 14) never


def test_lava_is_never_entered_and_its_surroundings_cost(mats: Materials) -> None:
    rows = ["#" * 30] + ["#" + "." * 28 + "#"] * 20 + ["#" * 30]
    rows[10] = "#" + "." * 13 + "LL" + "." * 13 + "#"
    t = analyse(grid_of(mats, rows), mats, BODY, dig_max_durability=10)
    assert not t.free[8, 14]  # the box would sit in lava
    assert t.contact[8, 12] and t.near_hazard[8, 12]  # the hit box reaches it
    assert t.near_hazard[8, 8] and not t.contact[8, 8]  # within the ring only
    assert t.cost[8, 12] > t.cost[8, 4] + 20 and t.cost[8, 4] >= 0


def test_the_field_leads_around_a_wall_and_down_is_cheaper_than_up(mats: Materials) -> None:
    rows = ["#" * 40] + ["#" + "." * 38 + "#"] * 30 + ["#" * 40]
    for r in range(1, 22):
        rows[r] = rows[r][:20] + "#" + rows[r][21:]  # a wall from the roof down to row 21
    grid = grid_of(mats, rows)
    t = analyse(grid, mats, BODY, dig_max_durability=0)  # nothing can be dug
    down = build_field(t, (30, 23))
    up = build_field(t, (30, 4))
    start = (5, 23)
    assert down.reachable(*start) and up.reachable(*start)
    way = down.path_from(down.node(*start))
    assert way[0] == start and way[-1] == (30, 23)
    assert any(y >= 23 for _, y in way) and all(not (x == 20 and y < 22) for x, y in way)
    # the same detour costs more when it ends up high
    assert up.cost_at(5, 23) > down.cost_at(5, 23)


def test_a_goal_the_box_cannot_stand_in_is_an_error(mats: Materials) -> None:
    t = analyse(grid_of(mats, ["#" * 20] * 20), mats, BODY, dig_max_durability=0)
    with pytest.raises(ValueError, match="not a position"):
        build_field(t, (5, 5))


def test_digging_is_a_last_resort_and_brick_is_a_wall(mats: Materials) -> None:
    rows = ["#" * 30] + ["#" + "." * 28 + "#"] * 12 + ["#" * 30]
    for r in range(1, 13):
        rows[r] = rows[r][:15] + "gg" + rows[r][17:]  # a ground wall across the hall
    t = analyse(grid_of(mats, rows), mats, BODY, dig_max_durability=10)
    f = build_field(t, (24, 5))
    here = f.node(3, 5)
    assert f.reachable(3, 5)
    assert any(not t.free[y, x] for x, y in f.path_from(here))  # through the ground
    rows_b = [r.replace("g", "B") for r in rows]
    tb = analyse(grid_of(mats, rows_b), mats, BODY, dig_max_durability=10)
    fb = build_field(tb, (24, 5))
    assert not fb.reachable(3, 5)
    assert fb.nearest_node(3, 5) == NO_NODE or not np.isfinite(fb.dist[fb.nearest_node(3, 5)])


def test_the_guide_makes_the_marked_way_cheaper() -> None:
    bias = guide_bias((40, 60), [(5, 20), (50, 20)])
    assert bias[2, 30] == 1.0  # far from the line
    assert bias[20, 30] == pytest.approx(1.0 - GUIDE_DISCOUNT)  # on it
    assert (guide_bias((10, 10), []) == 1.0).all()


def test_digging_near_a_lava_pocket_is_expensive(mats: Materials) -> None:
    """A bolt's hole (radius 6) next to lava lets it out: such a box costs far more to dig."""
    rows = ["#" * 60] + ["#" + "." * 58 + "#"] * 14 + ["#" * 60]
    for r in range(1, 15):
        rows[r] = rows[r][:20] + "gggg" + rows[r][24:]  # a wall of ground at x 20..23
        rows[r] = rows[r][:50] + "LLLL" + rows[r][54:]  # lava in a pocket far to the right
    near = list(rows)
    for r in range(1, 15):
        near[r] = near[r][:30] + "LLLL" + near[r][34:]  # ... and a second pocket 6 cells away
    far_cost = analyse(grid_of(mats, rows), mats, BODY, dig_max_durability=10).cost[5, 20]
    near_cost = analyse(grid_of(mats, near), mats, BODY, dig_max_durability=10).cost[5, 20]
    assert near_cost > far_cost + 300  # DIG_DANGER_COST


def pool_hall(mats: Materials) -> np.ndarray:
    """A hall 20 rows high with a lava pool in its floor (rows 18..20, x 25..34)."""
    rows = ["#" * 60] + ["#" + "." * 58 + "#"] * 20 + ["#" * 60]
    for r in range(18, 21):
        rows[r] = rows[r][:25] + "L" * 10 + rows[r][35:]
    return grid_of(mats, rows)


def test_the_way_keeps_the_hit_box_out_of_the_lava(
    mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The collision box never enters the lava, but the hit box is taller: a way that skims the
    pool would still burn the player, so the field takes the way over it."""
    grid = pool_hall(mats)
    start, goal = (5, 14), (50, 14)

    def way() -> tuple[list[tuple[int, int]], np.ndarray]:
        t = analyse(grid, mats, BODY, dig_max_durability=10)
        field = build_field(t, goal)
        return field.path_from(field.node(*start)), t.contact

    path, contact = way()
    assert path[0] == start and path[-1] == goal
    assert not any(contact[y, x] for x, y in path)
    assert min(y for x, y in path if 25 <= x <= 34) <= 9  # over the pool, not along its rim
    # the control: with the hit-box costs off, the cheapest way skims the pool and touches it
    monkeypatch.setattr(terrain, "HIT_COST", 0.0)
    monkeypatch.setattr(terrain, "RING_COST", 0.0)
    skimming, contact = way()
    assert any(contact[y, x] for x, y in skimming)
