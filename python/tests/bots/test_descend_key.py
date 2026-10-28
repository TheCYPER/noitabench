"""A key item in the world: fetched, tried on the plug, and the fallback when it is not enough."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mini_world import write_world
from noitabench.bots import keys
from noitabench.bots.breaker import Loadout
from noitabench.bots.descend import Descent
from noitabench.bots.spellinfo import best_reach
from noitabench.bots.terrain import Materials

KEY = {"type": "item", "item": "spell", "spell": "BOMB", "role": "seal_key", "x": 108, "y": 239}


def events(bot: Descent) -> list[str]:
    return [e["event"] for e in bot.log]


def test_a_key_that_is_too_weak_is_fetched_but_not_used(tmp_path: Path, mats: Materials) -> None:
    bot = Descent(write_world(tmp_path, mats, key_item=KEY), enemies=False, max_frames=6000)
    s = bot.run()
    seen = events(bot)
    assert s.seal_key_found and s.reached_bottom and s.fallback_used
    order = ["seal_key", "picked_up", "seal_key_too_weak", "seal_fallback"]
    assert [e for e in seen if e in order] == order
    weak = next(e for e in bot.log if e["event"] == "seal_key_too_weak")
    assert weak["detail"] == "BOMB" and weak["explosion_durability"] == 11
    assert bot.counts["pickup"] == 1 and s.deaths == 0
    assert s.seal_key_result == "too_weak" and s.fallback_tool == "Game.blast"


def test_a_key_that_is_planned_to_open_is_used_before_the_fallback(
    tmp_path: Path, mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The planner is made to claim the bomb breaks brick (it does not: 11 against 14). The bot
    assembles the wand, throws the bomb, stays out of the blast, sees the plug shut, and only
    then falls back to the test API."""
    claim = Loadout(("BOMB",), 14, 60, 25.0, 180, 1, True)
    monkeypatch.setattr(keys, "plan_loadout", lambda *a, **k: claim)
    bot = Descent(write_world(tmp_path, mats, key_item=KEY), enemies=False, max_frames=9000)
    s = bot.run()
    seen = events(bot)
    order = [
        "picked_up",
        "breaker_assembled",
        "blast_thrown",
        "blast",
        "seal_key_used",
        "seal_fallback",
    ]
    assert [e for e in seen if e in order] == order
    used = next(e for e in bot.log if e["event"] == "seal_key_used")
    assert used["opened"] is False  # a bomb cannot break brick: the bot goes on to the fallback
    assert s.seal_key_result == "failed" and s.fallback_used and s.bombs == 1
    assert s.seal_opened and s.reached_bottom and s.deaths == 0
    assert s.hp_min == 100.0  # the bomb went off with the bot out of reach


def test_without_the_fallback_a_weak_key_leaves_the_seal_closed(
    tmp_path: Path, mats: Materials
) -> None:
    bot = Descent(
        write_world(tmp_path, mats, key_item=KEY),
        enemies=False,
        max_frames=6000,
        seal_fallback=False,
    )
    s = bot.run()
    assert s.seal_key_found and not s.seal_opened and not s.fallback_used
    assert s.stop_reason == "the seal stayed closed"


def test_a_bottle_key_that_leaves_the_plug_shut_is_a_failed_key(
    tmp_path: Path, mats: Materials
) -> None:
    """A bottle (or wand) key is thrown (fired) at the plug as it is; water does nothing to brick,
    and the run records that the key was used and failed, not that it was never used."""
    water = {"type": "item", "item": "bottle", "contents": "water", "role": "seal_key"}
    bot = Descent(
        write_world(tmp_path, mats, key_item={**water, "x": 108, "y": 239}),
        enemies=False,
        max_frames=9000,
        seal_fallback=False,
    )
    s = bot.run()
    assert s.seal_keys_fetched == 1 and s.seal_key_result == "failed" and not s.seal_opened
    used = [e for e in bot.log if e["event"] == "seal_key_used"]
    assert [(e["item"], e["opened"]) for e in used] == [("bottle", False)]


def test_a_key_in_solid_rock_is_left_alone(tmp_path: Path, mats: Materials) -> None:
    buried = {**KEY, "x": 20, "y": 120}  # inside the rock below corridor A
    bot = Descent(write_world(tmp_path, mats, key_item=buried), enemies=False, max_frames=6000)
    s = bot.run()
    assert s.seal_key_found and s.seal_key_result == "unreachable"
    assert s.reached_bottom and bot.counts["pickup"] == 0 and s.fallback_used


def test_a_key_over_lava_at_floor_level_is_left_alone(tmp_path: Path, mats: Materials) -> None:
    """The pit of corridor B is lava from the floor row down: every place to stand beside the
    key has the lava in the hit box, which reaches two cells below the feet."""

    def flood(grid, idx) -> None:
        grid[46:52, 108:124] = idx["lava"]

    over_the_pit = {**KEY, "x": 116, "y": 45}
    files = write_world(tmp_path, mats, key_item=over_the_pit, edit=flood)
    bot = Descent(files, enemies=False, max_frames=6000)
    s = bot.run()
    assert s.seal_key_found and s.seal_key_result == "behind_hazard"
    assert s.reached_bottom and bot.counts["pickup"] == 0  # (the way on crosses the lava: it hurts)


def test_a_key_above_a_pit_is_taken_from_its_rim_without_touching_the_lava(
    tmp_path: Path, mats: Materials
) -> None:
    """The lava of the mini world starts two rows below the floor: the pickup reaches 14 cells,
    and the bot picks the key up from the edge of the pit."""
    above_the_pit = {**KEY, "x": 116, "y": 45}
    bot = Descent(
        write_world(tmp_path, mats, key_item=above_the_pit), enemies=False, max_frames=6000
    )
    s = bot.run()
    assert s.key_results[0]["result"] == "fetched" and s.reached_bottom
    assert bot.counts["pickup"] == 1 and s.hp_min == 100.0


def test_a_nearer_item_is_not_taken_for_the_key(tmp_path: Path, mats: Materials) -> None:
    """The nearest item is picked up first. A bottle lies closer to the bot's spot than the key
    spell: the bot has to go on until it holds the spell itself."""
    decoy = {"type": "item", "item": "bottle", "contents": "water", "x": 106, "y": 239}
    files = write_world(tmp_path, mats, key_item=KEY)
    doc = json.loads(files.json.read_text())
    doc["markers"].append(decoy)
    files.json.write_text(json.dumps(doc))
    bot = Descent(files, enemies=False, max_frames=6000)
    s = bot.run()
    taken = [(e["item"], e["detail"]) for e in bot.pickups]
    assert ("spell", "BOMB") in taken, taken
    assert bot.key_in_hand and s.seal_key_result == "too_weak" and s.reached_bottom
    p = bot.game.player()
    assert p is not None
    held = [slot["spell"] for w in p["wands"] for slot in w["slots"] if slot] + [
        c["spell"] for c in p["spells"]
    ]
    assert "BOMB" in held


PAIR_ITEMS = [
    {"type": "item", "item": "spell", "spell": "BOMB", "role": "breaker", "x": 30, "y": 69},
    {
        "type": "item",
        "item": "spell",
        "spell": "EXPLOSIVE_PROJECTILE",
        "role": "breaker",
        "x": 34,
        "y": 69,
    },
]


@pytest.mark.skipif(
    best_reach(["BOMB", "EXPLOSIVE_PROJECTILE"]) != 14,
    reason="the content has no spell that adds to the durability of an explosion yet",
)
def test_the_bomb_and_the_modifier_open_the_brick_without_the_test_api(
    tmp_path: Path, mats: Materials
) -> None:
    """Both breaker items are fetched (in either order), put into the wand with the modifier
    first, and the bomb is thrown onto the plug from out of its reach."""
    bot = Descent(write_world(tmp_path, mats, items=PAIR_ITEMS), enemies=False, max_frames=9000)
    s = bot.run()
    assert s.seal_keys == s.seal_keys_fetched == 2 and s.seal_key_result == "used"
    assert not s.fallback_used and s.fallback_tool == ""
    assert s.reached_bottom and s.deaths == 0 and s.hp_min == 100.0
    assert s.bombs >= 1
    assembled = next(e for e in bot.log if e["event"] == "breaker_assembled")
    assert assembled["spells"] == ["EXPLOSIVE_PROJECTILE", "BOMB"] and assembled["durability"] == 14
    blast = next(e for e in bot.log if e["event"] == "blast")
    assert blast["distance"] > assembled["radius"] and blast["hp"] == 100.0
    p = bot._p
    assert [slot["spell"] for slot in p["wands"][0]["slots"] if slot] == ["LIGHT_BULLET"]


@pytest.mark.skipif(
    best_reach(["BOMB", "EXPLOSIVE_PROJECTILE"]) != 14,
    reason="the content has no spell that adds to the durability of an explosion yet",
)
def test_the_bomb_alone_is_too_weak_and_with_require_key_the_run_fails(
    tmp_path: Path, mats: Materials
) -> None:
    only_the_bomb = PAIR_ITEMS[:1]
    bot = Descent(
        write_world(tmp_path, mats, items=only_the_bomb),
        enemies=False,
        max_frames=9000,
        seal_fallback=False,
    )
    s = bot.run()
    assert s.seal_key_result == "too_weak" and not s.seal_opened and not s.fallback_used
    assert s.stop_reason == "the seal stayed closed" and s.bombs == 0


def test_a_key_that_cannot_be_assembled_for_want_of_an_edit_hall_is_a_failed_key(
    tmp_path: Path, mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An older world file has no edit station by the plug: the wands may not be edited there,
    the bot says so and goes on to the fallback instead of breaking the rule."""
    claim = Loadout(("BOMB",), 14, 60, 25.0, 180, 1, True)
    monkeypatch.setattr(keys, "plan_loadout", lambda *a, **k: claim)
    bot = Descent(write_world(tmp_path, mats, key_item=KEY), enemies=False, max_frames=9000)
    bot.game.zones = []  # no rest area, no edit station
    s = bot.run()
    seen = events(bot)
    assert "edit_not_allowed" in seen and "breaker_assembled" not in seen
    assert s.fallback_used and s.bombs == 0 and s.wand_edits == {}
