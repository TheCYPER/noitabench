"""The pilot in small arenas: a wall it does not know about, and the recovery that gets past it."""

from __future__ import annotations

import numpy as np
from noitabench.bots.navfield import build_field
from noitabench.bots.pilot import Pilot
from noitabench.bots.terrain import FORBIDDEN_KEYS, Body, Materials, analyse
from noitabench.game import Game

W, H, FLOOR = 200, 80, 20
GROUND = H - FLOOR - 1
BODY = Body.load()


def arena() -> Game:
    game = Game(W, H, 7)
    game.fill_rect(0, 0, W, 4, "rock")  # roof
    game.fill_rect(0, H - FLOOR, W, FLOOR, "rock")
    game.fill_rect(0, 0, 4, H, "rock")
    game.fill_rect(W - 4, 0, 4, H, "rock")
    game.spawn_player(15, GROUND)
    game.step(61)
    return game


def pilot_for(game: Game, mats: Materials, goal: tuple[int, int]) -> Pilot:
    def plan() -> tuple:
        terrain = analyse(game.grid_array(), mats, BODY, dig_max_durability=10)
        return terrain, build_field(terrain, goal)

    terrain, field = plan()
    return Pilot(
        mats, terrain, field, game.grid_array(), rebuild=plan, hazard_ids=mats.ids(FORBIDDEN_KEYS)
    )


def drive(game: Game, pilot: Pilot, goal: tuple[int, int], frames: int, *, refresh: bool) -> bool:
    for _ in range(frames):
        p = game.player()
        assert p is not None
        if abs(p["x"] - goal[0]) <= 2 and abs(p["y"] - goal[1]) <= 2 and p["on_ground"]:
            return True
        if refresh:
            pilot.grid = game.grid_array()
        game.step(1, pilot.decide(p, game.frame))
    return False


def test_the_pilot_walks_across_a_flat_arena(mats: Materials) -> None:
    game = arena()
    goal = (170, GROUND + 1 - BODY.h)
    pilot = pilot_for(game, mats, goal)
    assert drive(game, pilot, goal, 400, refresh=True)
    assert pilot.stats["recoveries"] == 0 and game.player()["hp"] == 100.0


def test_a_wall_it_does_not_know_about_is_dug_through_by_the_recovery(mats: Materials) -> None:
    game = arena()
    goal = (170, GROUND + 1 - BODY.h)
    pilot = pilot_for(game, mats, goal)  # planned on the open arena ...
    game.fill_rect(90, 4, 6, H - FLOOR - 4, "ground")  # ... then a ground wall appears
    stale = pilot.grid.copy()
    for _ in range(600):
        p = game.player()
        assert p is not None
        if abs(p["x"] - goal[0]) <= 2 and p["on_ground"]:
            break
        pilot.grid = stale  # the pilot never sees the wall, so it cannot dig on purpose
        game.step(1, pilot.decide(p, game.frame))
    modes = [what for _, _, _, what in pilot.log]
    assert modes and modes[0] == "wiggle"  # the recoveries come in a fixed order
    assert pilot.stats["recoveries"] >= 1
    # the recovery rebuilt the field from the real grid; from there the pilot digs on purpose
    assert drive(game, pilot, goal, 900, refresh=True)
    assert np.all(game.grid_array()[GROUND - 3 : GROUND, 92:94] == mats.index("air"))


def test_a_ground_wall_the_pilot_can_see_is_dug_at_once(mats: Materials) -> None:
    game = arena()
    game.fill_rect(90, 4, 6, H - FLOOR - 4, "ground")
    goal = (170, GROUND + 1 - BODY.h)
    pilot = pilot_for(game, mats, goal)
    assert drive(game, pilot, goal, 900, refresh=True)
    assert pilot.stats["dig_frames"] > 0 and pilot.stats["recoveries"] == 0


def lava_arena() -> Game:
    """The flat arena with a lava pool in its floor: 14 wide, level with the floor around it."""
    game = arena()
    game.fill_rect(90, H - FLOOR, 14, 3, "lava")
    return game


def test_a_walker_that_ignores_the_lava_burns() -> None:
    """The control of the next test: the pool does hurt a player who just walks on."""
    game = lava_arena()
    game.step(400, {"move": 1})
    p = game.player()
    assert p is not None and p["hp"] < 100.0


def test_the_pilot_hovers_across_a_lava_pool_without_touching_it(mats: Materials) -> None:
    """(That the field steers clear of lava on purpose is tested in test_terrain_navfield: a
    gap this wide is flown over anyway.)"""
    game = lava_arena()
    goal = (170, GROUND + 1 - BODY.h)
    pilot = pilot_for(game, mats, goal)
    assert drive(game, pilot, goal, 900, refresh=True)
    assert game.player()["hp"] == 100.0
    assert pilot.stats["fly_frames"] > 0  # a pool that wide is crossed by levitating
