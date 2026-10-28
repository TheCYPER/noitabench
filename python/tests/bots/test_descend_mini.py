"""The whole bot on a small hand-built world: dig, climb, cross a lava pit, drop down a shaft,
get through the seal and into the sealed room."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mini_world import write_world
from noitabench.bots import descend
from noitabench.bots.descend import Descent, Summary, WorldFiles
from noitabench.bots.terrain import Materials

MAX_FRAMES = 6000


def run(files: WorldFiles, **kwargs) -> tuple[Descent, Summary]:
    bot = Descent(files, max_frames=MAX_FRAMES, **kwargs)
    return bot, bot.run()


@pytest.fixture(scope="module")
def played(tmp_path_factory: pytest.TempPathFactory) -> tuple[Descent, Summary]:
    mats = Materials.load()
    files = write_world(tmp_path_factory.mktemp("mini"), mats)
    return run(files, enemies=False)


def test_the_bot_reaches_the_bottom_of_the_sealed_room(played) -> None:
    _, s = played
    assert s.reached_seal and s.seal_opened and s.reached_bottom, s
    assert s.deaths == 0 and s.stop_reason == "reached the bottom"
    assert s.depth_y >= 270  # the room floor is at y = 272


def test_it_dug_through_the_ground_wall_and_kept_out_of_the_lava(played) -> None:
    _, s = played
    assert s.digs >= 1
    assert s.hp_min == 100.0  # no contact with the lava, no fall damage


def test_it_uses_the_fallback_and_says_so(played) -> None:
    bot, s = played
    assert s.fallback_used and not s.seal_key_found and s.fallback_tool == "Game.blast"
    events = [e["event"] for e in bot.log]
    assert "seal_fallback" in events and events.index("seal_fallback") < events.index("walk", 2)
    fallback = next(e for e in bot.log if e["event"] == "seal_fallback")
    assert fallback["tool"] == "Game.blast" and fallback["max_durability"] == 14


def test_it_climbed_the_step_by_levitating_and_crossed_the_pit_above_the_lava(
    tmp_path: Path, mats: Materials
) -> None:
    """Corridor B lies 24 cells above corridor A (floor 46 against 70) and has a lava pit in its
    floor (x 108..123, lava from row 48): the bot has to rise, and to stay up over the pit."""
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=MAX_FRAMES)
    track: list[tuple[float, float]] = []
    step = bot.step

    def traced(controls):
        p = step(controls)
        track.append((p["x"], p["y"]))
        return p

    bot.step = traced
    s = bot.run()
    assert s.reached_bottom and s.hp_min == 100.0
    stood_in_a = [i for i, (x, y) in enumerate(track) if x < 100 and y >= 60]  # a's floor
    in_b = [i for i, (x, y) in enumerate(track) if 101 <= x <= 107 and y <= 40]  # b's floor
    assert stood_in_a and in_b and stood_in_a[0] < in_b[0]
    assert bot.pilot_stats["fly_frames"] > 0  # a step this high is beyond a hop
    over_the_pit = [y for x, y in track if 110 <= x <= 121]
    assert over_the_pit and max(over_the_pit) <= 40  # the feet stay above the lava's row 48


def test_it_follows_the_main_path(played) -> None:
    _, s = played
    assert s.waypoints == 5 and s.waypoints_passed >= 3


def test_the_seal_stays_closed_without_the_fallback(tmp_path: Path, mats: Materials) -> None:
    files = write_world(tmp_path, mats)
    _, s = run(files, enemies=False, seal_fallback=False)
    assert s.reached_seal and not s.seal_opened and not s.fallback_used
    assert s.stop_reason == "the seal stayed closed" and s.depth_y < 250


def test_two_runs_end_in_the_same_state(tmp_path: Path, mats: Materials) -> None:
    files = write_world(tmp_path, mats)
    a = run(files, enemies=False)[1]
    b = run(files, enemies=False)[1]
    assert a.state_hash == b.state_hash and a.frames == b.frames
    assert json.dumps(a.__dict__) == json.dumps(b.__dict__)


@pytest.mark.parametrize("rule_seed", [3, 9])
def test_the_bot_plays_any_rule_seed(tmp_path: Path, mats: Materials, rule_seed: int) -> None:
    files = write_world(tmp_path, mats)
    plain, _ = run(files, enemies=False)
    bot, s = run(files, enemies=False, rule_seed=rule_seed)
    assert s.reached_bottom and s.hp_min == 100.0 and s.rule_seed == rule_seed
    assert bot.game.content_hash != plain.game.content_hash  # other potion recipes


def test_a_hurt_bot_heals_in_the_pool_of_the_rest_hall(tmp_path: Path, mats: Materials) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=True, max_frames=6000)
    bot.step({})  # the opening invincibility has to run out before anything can hurt
    for _ in range(70):
        bot.step({})
    p = bot._p
    bot.game.blast(int(p["x"]) + 2, int(p["y"]) + 3, 12, 2.0, 20000, 10, 0)  # a bomb at its feet
    bot.step({})
    hurt = bot._p["hp"]
    assert hurt < 90.0
    goal = bot.rest_goal(1)
    assert goal is not None and 104 <= goal[0] <= 112 and 232 <= goal[1] <= 240  # in the pool
    assert bot.rest(1)
    assert bot._p["hp"] >= 0.97 * bot._p["hp_max"] > hurt
    assert any(e["event"] == "rested" and e["hall"] == 1 for e in bot.log)


def test_there_is_no_pool_to_rest_in_without_a_rest_marker(tmp_path: Path, mats: Materials) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=True, max_frames=6000)
    assert bot.rest_goal(2) is None and bot.rest(2)  # nothing to do: no hall number 2


def test_a_breaker_spell_in_the_content_is_tried_before_the_blast(
    tmp_path: Path, mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the content had a spell that breaks brick, the fallback would hand it over and use it.
    Here the name is a stand-in (the bomb does not break brick yet), so the blast follows."""
    monkeypatch.setattr(descend, "breaker_spell", lambda mats: "BOMB")
    bot, s = run(write_world(tmp_path, mats), enemies=False)
    tools = [e["tool"] for e in bot.log if e["event"] == "seal_fallback"]
    assert tools == ["Game.give_spell(BOMB)", "Game.blast"]
    assert s.fallback_tool == "Game.give_spell(BOMB) + Game.blast"
    assert s.reached_bottom  # the blast opened the way
    assert s.shots >= 1  # the bomb was cast at the plug first


def test_a_death_is_counted_wherever_it_happens(tmp_path: Path, mats: Materials) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=True, max_frames=MAX_FRAMES)
    for _ in range(70):  # the opening invincibility has to run out
        bot.step({})
    p = bot._p
    bot.game.blast(int(p["x"]) + 2, int(p["y"]) + 3, 12, 100.0, 20000, 10, 0)  # a lethal one
    bot.phase = "somewhere"
    bot.step({})
    assert bot._p["dead"] and bot.summary.deaths == 1
    assert any(e["event"] == "died" and e["phase"] == "somewhere" for e in bot.log)
    s = bot.run()
    assert s.deaths == 1 and s.stop_reason == "died" and not s.reached_bottom
