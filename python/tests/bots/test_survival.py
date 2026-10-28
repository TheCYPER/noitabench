"""Staying alive on the way down: drinking a healing potion, waiting for a fire to burn out,
letting go of a hover, reading a hazard only near the item, digging a safe plug."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from mini_world import BREAKER, dig_river, write_world
from noitabench.bots import descend, healing, keys
from noitabench.bots.bottles import bottle_total
from noitabench.bots.crossing import clear_lava
from noitabench.bots.descend import FIRE_PATIENCE, FIRE_WAIT, Descent
from noitabench.bots.navfield import build_field
from noitabench.bots.pilot import Pilot, PilotConfig
from noitabench.bots.seal import find_seal_keys
from noitabench.bots.terrain import (
    DIG_DANGER_COST,
    DIG_DANGER_RADIUS,
    FORBIDDEN_KEYS,
    Body,
    Materials,
    analyse,
)

BODY = Body.load()
POTION = {"type": "item", "item": "potion_heal", "x": 30, "y": 69}


def hurt(bot: Descent, damage: float = 10.0) -> None:
    """A blast at the player's feet, after the opening invincibility."""
    for _ in range(70):
        bot.step({})
    p = bot._p
    bot.game.blast(int(p["x"]) + 2, int(p["y"]) + 3, 12, damage, 20000, 10, 0)
    bot.step({})


# -- healing --------------------------------------------------------------------------------------


def test_a_hurt_bot_walks_to_a_potion_near_by_and_drinks_it(
    tmp_path: Path, mats: Materials
) -> None:
    bot = Descent(write_world(tmp_path, mats, items=[POTION]), enemies=False, max_frames=4000)
    assert not bot.wants_heal()
    hurt(bot)
    assert bot._p["hp"] < healing.HEAL_BELOW * bot._p["hp_max"] and bot.wants_heal()
    assert bot.potion_in_hand() is None and bot.nearest_potion() is not None
    assert bot.heal()
    assert bot._p["hp"] >= healing.HEAL_UNTIL * bot._p["hp_max"]
    left = bot._p["bottles"][-1]  # (the drink stops when the bot is healthy: some is left)
    assert bottle_total(left) < 400
    done = next(e for e in bot.log if e["event"] == "healed")
    assert done["hp_after"] > done["hp_before"] and not bot.healing


def test_a_potion_in_hand_is_drunk_on_the_spot(tmp_path: Path, mats: Materials) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=4000)
    bot.game.give_bottle("potion_heal", 400)
    hurt(bot)
    x = bot._p["x"]
    assert bot.potion_in_hand() is not None and bot.heal()
    assert abs(bot._p["x"] - x) <= 6 and bot._p["hp"] >= healing.HEAL_UNTIL * bot._p["hp_max"]


def test_without_a_potion_in_reach_nothing_is_done(tmp_path: Path, mats: Materials) -> None:
    far = POTION | {"x": 30 + int(healing.POTION_REACH) + 20}
    bot = Descent(write_world(tmp_path, mats, items=[far]), enemies=False, max_frames=4000)
    hurt(bot)
    assert bot.nearest_potion() is None and not bot.heal()
    assert not bot.healing and not any(e["event"] == "healed" for e in bot.log)


def test_a_healthy_bot_does_not_look_for_a_potion(tmp_path: Path, mats: Materials) -> None:
    bot = Descent(write_world(tmp_path, mats, items=[POTION]), enemies=False, max_frames=4000)
    assert not bot.wants_heal()
    bot.healing = True  # (a drink under way is not started again)
    hurt(bot)
    assert not bot.wants_heal()


def test_a_walk_heals_the_bot_when_it_is_hurt(tmp_path: Path, mats: Materials) -> None:
    bot = Descent(write_world(tmp_path, mats, items=[POTION]), enemies=False, max_frames=6000)
    hurt(bot)
    s = bot.run()
    assert any(e["event"] == "healed" for e in bot.log) and s.reached_bottom
    assert bot.summary.hp_min < 60.0 < bot._p["hp"]  # it was hurt on the way and is healthy again


# -- waiting for a fire -----------------------------------------------------------------------------


def test_no_fire_no_wait(tmp_path: Path, mats: Materials) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=4000)
    assert bot.fire_cells() == 0 and bot.wait_out_fire("test") == -1
    assert bot.frames == 0


def test_a_fire_is_waited_for_in_steps_until_the_patience_is_used_up(
    tmp_path: Path, mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=40000)
    monkeypatch.setattr(bot, "fire_cells", lambda: 7)  # a fire that does not go out
    assert bot.wait_out_fire("test") == FIRE_WAIT and bot.frames == FIRE_WAIT
    assert sum(e["event"] == "fire_wait" for e in bot.log) == 1  # noted once
    assert bot.wait_out_fire("test", FIRE_WAIT) == 2 * FIRE_WAIT
    assert sum(e["event"] == "fire_wait" for e in bot.log) == 1
    assert bot.wait_out_fire("test", FIRE_PATIENCE) == -1  # no patience left


def test_a_walk_waits_for_a_fire_that_cuts_the_way(tmp_path: Path, mats: Materials) -> None:
    """Fire all round the player: no box position to stand in. The bot waits (and does not
    declare the goal unreachable) until the fire has burnt away, then walks."""
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=6000)
    for _ in range(70):
        bot.step({})
    p = bot._p
    bot.game.fill_rect(int(p["x"]) - 14, int(p["y"]) - 20, 32, 40, "fire")
    start = bot.frames
    bot.walk_to("test", (50, 63), tolerance=3)
    assert any(e["event"] == "fire_wait" for e in bot.log)
    assert not any(e["event"] == "unreachable" for e in bot.log)
    assert bot.frames - start >= FIRE_WAIT


# -- letting go of a hover ----------------------------------------------------------------------------


def hover_pilot(mats: Materials) -> Pilot:
    """A hall with lava under its floor-less middle: a fall there is a hazard below."""
    grid = np.full((60, 60), mats.index("rock"), dtype=np.uint8)
    grid[5:40, 5:55] = mats.index("air")
    grid[40:50, 5:55] = mats.index("lava")
    terrain = analyse(grid, mats, BODY, dig_max_durability=10)
    goal = (10, 20)
    return Pilot(
        mats,
        terrain,
        build_field(terrain, goal),
        grid,
        rebuild=lambda: (terrain, build_field(terrain, goal)),
        hazard_ids=mats.ids(FORBIDDEN_KEYS),
    )


def test_thrust_that_goes_nowhere_is_let_go_for_a_moment(mats: Materials) -> None:
    pilot = hover_pilot(mats)
    cfg = PilotConfig()
    p = {"x": 30, "y": 20, "vx": 0.0, "vy": 0.0}
    target = (30, 20)  # the box is where it wants to be, over lava, and thrust holds it there
    pilot.flying = True
    answers = []
    for frame in range(1, cfg.hover_limit + cfg.hover_release + 8):
        pilot.frame = frame
        answers.append(pilot._airborne_fly(p, target))
        pilot.flying = answers[-1]
    assert all(answers[: cfg.hover_limit])  # it holds the hover for a while ...
    release = answers[cfg.hover_limit : cfg.hover_limit + cfg.hover_release]
    assert release and not any(release)  # ... lets go (the box drops) ...
    pilot.frame = cfg.hover_limit + cfg.hover_release + 2
    assert pilot._airborne_fly(p | {"vy": 60.0}, target)  # ... and takes hold of the fall again
    assert pilot.stats["hover_releases"] == 1


def test_a_climb_or_a_crossing_is_not_a_hover(mats: Materials) -> None:
    pilot = hover_pilot(mats)
    pilot.flying = True
    for frame in range(1, 80):
        pilot.frame = frame
        crossing = {"x": 30, "y": 20, "vx": 40.0, "vy": 0.0}  # sideways at speed: a crossing
        assert pilot._airborne_fly(crossing, (50, 24))
    assert pilot.stats.get("hover_releases", 0) == 0


# -- a hazard at the item, not on the way to it ---------------------------------------------------


def test_lava_far_before_the_item_does_not_make_it_unreachable(
    tmp_path: Path, mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = write_world(
        tmp_path, mats, items=[BREAKER], edit=lambda g, i: dig_river(g, i, sealed=True)
    )
    bot = Descent(files, enemies=False, max_frames=4000)
    (key,) = find_seal_keys(bot.doc["markers"], bot.game.entities())
    centre = (key.entity["x"] + key.entity["w"] / 2, key.entity["y"] + key.entity["h"] / 2)
    status, _, exposure = bot.reach(centre)
    assert status == "hazard" and exposure > 0  # the river is the last stretch of the way
    monkeypatch.setattr(keys, "HAZARD_TAIL", 1)  # only the very last step is looked at
    status, _, exposure = bot.reach(centre)
    assert status == "ok" and exposure == 0


# -- a plug dug without letting out the lava ----------------------------------------------------


def test_the_safe_boxes_of_a_plug_are_the_ones_far_from_the_lava(mats: Materials) -> None:
    """A rock plug 20 wide between two seams of lava: only a band in the middle is farther
    from the lava than a bolt's hole (and its aim's wobble) reaches."""
    rock, air, lava = (mats.index(k) for k in ("rock", "air", "lava"))
    g = np.full((30, 80), rock, dtype=np.uint8)
    g[2:10, 2:78] = air  # the corridor above
    g[10:13, 2:78] = rock  # the slab: the plug is the part between the lava
    g[13:16, 2:30] = lava
    g[13:16, 50:78] = lava  # the plug between them is x 30..49
    g[16:24, 2:78] = air
    t = analyse(g, mats, BODY, dig_max_durability=10)
    centre = float(t.cost[8, 38])  # a box over the middle of the plug (cells 38..41)
    edge = float(t.cost[8, 31])  # a box over the edge of the plug (cells 31..34)
    assert edge >= centre + DIG_DANGER_COST - 1
    assert DIG_DANGER_RADIUS >= 6 + 1  # the bolt's radius and a margin
    safe = [x for x in range(30, 47) if t.cost[8, x] < DIG_DANGER_COST]
    assert safe and min(safe) >= 30 + 4 and max(safe) + BODY.w <= 50 - 4


def test_play_world_gives_none_where_the_generator_makes_no_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("seed 1: no valid world in 8 attempts")

    monkeypatch.setattr(descend, "prepare_world", refuse)
    assert descend.play_world(1, 0, tmp_path) is None


def test_a_walk_whose_goal_is_taken_by_the_fire_is_a_walk_that_fails(
    tmp_path: Path, mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=6000)
    for _ in range(70):
        bot.step({})
    p = bot._p
    bot.game.fill_rect(int(p["x"]) - 14, int(p["y"]) - 20, 32, 40, "fire")
    waits = []

    def lose_the_goal(why: str, waited: int = 0) -> int:
        bot.game.fill_rect(46, 56, 12, 14, "lava")  # the goal is under lava by now
        waits.append(why)
        return waited + FIRE_WAIT

    monkeypatch.setattr(bot, "wait_out_fire", lose_the_goal)
    assert not bot.walk_to("test", (50, 63), tolerance=3)  # (no ValueError out of the planner)
    assert waits == ["test"]
    assert any(e["event"] == "unreachable" and e.get("why") for e in bot.log)


def test_fire_on_the_way_is_waited_for_not_poured_at(tmp_path: Path, mats: Materials) -> None:
    """The gas of a crust burns: the way touches fire, no lava is near it. The crossing stands
    by until the fire is out and then finds the way clear (it does not give up)."""
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=6000)
    for _ in range(70):
        bot.step({})
    bot.game.give_bottle("water", 200)
    bot.game.fill_rect(30, 30, 8, 40, "fire")  # a wall of fire across the corridor
    assert bot.fire_cells() > 0
    assert clear_lava(bot, (50, 63), {"water"})
    assert any(e["event"] == "fire_wait" for e in bot.log)
    assert any(e["event"] == "crossing_clear" for e in bot.log)
    assert not any(e["event"] == "crossing_failed" for e in bot.log)
