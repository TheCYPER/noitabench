"""The river of lava of E02 on a small world: the bot takes the encounter's solvent bottles,
crusts the lava, crosses and takes the key spell. The decoy bottle is left alone."""

from __future__ import annotations

from pathlib import Path

from mini_world import BREAKER, dig_river, river_items, solvent, write_world
from noitabench.bots.crossing import solvent_bottle
from noitabench.bots.descend import Descent, Summary
from noitabench.bots.seal import find_seal_keys
from noitabench.bots.terrain import Materials

MAX_FRAMES = 6000


def play(tmp_path: Path, mats: Materials, items: list[dict], **kwargs) -> tuple[Descent, Summary]:
    files = write_world(tmp_path, mats, items=items, edit=dig_river)
    bot = Descent(files, enemies=False, max_frames=MAX_FRAMES, **kwargs)
    return bot, bot.run()


def bottles(bot: Descent) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for b in bot._p["bottles"]:
        out.setdefault(b["material"], []).append(b["amount"])
    return out


def test_the_bot_crusts_the_river_and_takes_the_key(tmp_path: Path, mats: Materials) -> None:
    bot, s = play(tmp_path, mats, river_items())
    assert s.hazard_solved and s.seal_keys_fetched == 1 and s.deaths == 0
    assert s.key_results == [{"item": "spell", "detail": "BOMB", "result": "fetched"}]
    assert s.hp_min == 100.0 and s.reached_bottom
    held = [slot["spell"] for w in bot._p["wands"] for slot in w["slots"] if slot] + [
        c["spell"] for c in bot._p["spells"]
    ]
    assert "BOMB" in held
    events = [e["event"] for e in bot.log]
    order = ["crossing_start", "picked_up", "picked_up", "pour", "crossing_clear", "picked_up"]
    assert [e for e in events if e in set(order)] == order


def test_the_lava_is_gone_after_the_pour(tmp_path: Path, mats: Materials) -> None:
    bot, _ = play(tmp_path, mats, river_items())
    grid = bot.game.grid_array()
    assert (grid[60:72, 24:48] == mats.index("lava")).sum() == 0  # the pit further on is lava still
    row = grid[70, 28:44]  # the trench is stone now
    assert {mats.keys[i] for i in row} <= {"rock", "ground"}


def test_the_decoy_is_never_poured(tmp_path: Path, mats: Materials) -> None:
    bot, _ = play(tmp_path, mats, river_items(decoy="oil"))
    held = bottles(bot)
    assert held["oil"] == [400]  # full: the bot took it along but never tipped it out
    assert sum(held["blood"]) < 800  # the solvent was used


def test_the_bot_takes_the_bottle_that_works_whatever_the_liquid(
    tmp_path: Path, mats: Materials
) -> None:
    """Water instead of blood as the solvent, whiskey as the decoy: the markers say which."""
    bot, s = play(tmp_path, mats, river_items(solvents="water", decoy="whiskey"))
    assert s.hazard_solved and s.seal_keys_fetched == 1 and s.hp_min == 100.0
    held = bottles(bot)
    assert held["whiskey"] == [400] and sum(held["water"]) < 800


def test_without_a_solvent_the_key_behind_the_river_is_left_alone(
    tmp_path: Path, mats: Materials
) -> None:
    """With brick over and under the passage the river is the only way to the bomb."""
    files = write_world(
        tmp_path, mats, items=[BREAKER], edit=lambda g, i: dig_river(g, i, sealed=True)
    )
    bot = Descent(files, enemies=False, max_frames=MAX_FRAMES)
    (key,) = find_seal_keys(bot.doc["markers"], bot.game.entities())
    assert bot.fetch(key) == "behind_hazard"
    assert not bot.fetched and bot.counts["pickup"] == 0 and not bot.summary.hazard_solved
    assert bot._p["hp"] == 100.0


def test_with_a_solvent_the_same_river_is_crossed(tmp_path: Path, mats: Materials) -> None:
    files = write_world(
        tmp_path, mats, items=river_items(), edit=lambda g, i: dig_river(g, i, sealed=True)
    )
    bot = Descent(files, enemies=False, max_frames=MAX_FRAMES)
    (key,) = find_seal_keys(bot.doc["markers"], bot.game.entities())
    assert bot.fetch(key) == "fetched"
    assert bot.summary.hazard_solved and bot._p["hp"] == 100.0


def test_a_river_that_can_be_dug_around_is_not_a_reason_to_stay_away(
    tmp_path: Path, mats: Materials
) -> None:
    """The planner prefers the hole through the rock to wading in lava: the key is fetched (the
    pilot's steering may still brush the lava at the mouth of the passage on the way)."""
    files = write_world(tmp_path, mats, items=[BREAKER], edit=dig_river)
    bot = Descent(files, enemies=False, max_frames=MAX_FRAMES)
    (key,) = find_seal_keys(bot.doc["markers"], bot.game.entities())
    assert bot.fetch(key) == "fetched" and not bot.summary.hazard_solved
    # known limit of the pilot, not of the rule: tunnelling round the river it drops into the
    # passage and catches fire (about 19 HP in the current build). This only guards the worst.
    assert not bot._p["dead"] and bot.summary.hp_min >= 70.0


def test_a_solvent_of_another_encounter_is_not_this_ones(tmp_path: Path, mats: Materials) -> None:
    files = write_world(
        tmp_path,
        mats,
        items=[
            {**solvent("blood", 13), "encounter_id": "E14"},
            {**BREAKER, "encounter_id": "E02"},
            {**solvent("water", 15), "encounter_id": "E02"},
        ],
        edit=dig_river,
    )
    bot = Descent(files, enemies=False, max_frames=MAX_FRAMES)
    (key,) = find_seal_keys(bot.doc["markers"], bot.game.entities())
    found = bot.solvent_items(key)
    assert [m["contents"] for m, _ in found] == ["water"]
    assert found[0][1]["detail"] == "water"


def test_the_bottle_with_solvent_in_it_is_the_one_to_pour() -> None:
    player = {
        "bottles": [
            {"material": "oil", "amount": 400},
            {"material": "blood", "amount": 0},
            {"material": "blood", "amount": 120},
        ]
    }
    assert solvent_bottle(player, {"blood"}) == 2  # the empty one is skipped
    assert solvent_bottle(player, {"water"}) is None
    assert solvent_bottle({"bottles": []}, {"blood"}) is None
