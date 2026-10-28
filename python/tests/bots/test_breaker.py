"""The wand that breaks brick: planned from the spells in hand, assembled in the right order, and
a bomb thrown onto the plug with the thrower out of the blast."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mini_world import SEAL_THICK, SEAL_TOP, SEAL_W, SEAL_X, patched_spells, write_world
from noitabench.bots.breaker import (
    SAFETY,
    Loadout,
    assemble,
    break_with_loadout,
    plan_loadout,
    stow,
)
from noitabench.bots.descend import Descent
from noitabench.bots.spellinfo import best_reach, load_spells
from noitabench.bots.terrain import Materials
from noitabench.game import Game

PAIR = ("EXPLOSIVE_PROJECTILE", "BOMB")


def pair_loadout(**changes: object) -> Loadout:
    base = {"spells": PAIR, "durability": 14, "radius": 75, "mana": 55.0, "fuse": 180}
    return Loadout(**{**base, "uses": 3, "thrown": True, **changes})  # type: ignore[arg-type]


# -- planning ---------------------------------------------------------------------------------


def test_the_modifier_and_the_bomb_together_reach_brick(tmp_path: Path) -> None:
    path = patched_spells(tmp_path, 3)
    loadout = plan_loadout(["BOMB", "EXPLOSIVE_PROJECTILE"], 14, path=path)
    assert loadout == Loadout(PAIR, 14, 75, 55.0, 180, 3, True)  # the modifier first
    assert best_reach(["BOMB", "EXPLOSIVE_PROJECTILE"], path) == 14


def test_neither_spell_alone_reaches_brick(tmp_path: Path) -> None:
    path = patched_spells(tmp_path, 3)
    assert plan_loadout(["BOMB"], 14, path=path) is None
    assert best_reach(["BOMB"], path) == 11
    assert plan_loadout(["EXPLOSIVE_PROJECTILE"], 14, path=path) is None
    assert best_reach(["EXPLOSIVE_PROJECTILE"], path) is None  # a modifier has no explosion
    assert plan_loadout(["BOMB"], 10, path=path) == Loadout(("BOMB",), 11, 60, 25.0, 180, 3, True)


def test_content_without_the_bonus_counts_it_as_zero(tmp_path: Path) -> None:
    path = patched_spells(tmp_path, None)
    assert load_spells(path)["EXPLOSIVE_PROJECTILE"].bonus_durability == 0
    assert plan_loadout(list(PAIR), 14, path=path) is None
    assert best_reach(list(PAIR), path) == 11


def test_the_wand_must_have_room_and_the_mana(tmp_path: Path) -> None:
    path = patched_spells(tmp_path, 3)
    assert plan_loadout(list(PAIR), 14, slots=1, path=path) is None
    assert plan_loadout(list(PAIR), 14, slots=2, mana_max=50.0, path=path) is None
    assert plan_loadout(list(PAIR), 14, slots=2, mana_max=55.0, path=path) is not None


def test_two_modifiers_do_not_stack(tmp_path: Path) -> None:
    """The bonus is the largest of the modifiers, and one modifier is all the plan uses."""
    data = json.loads(patched_spells(tmp_path, 3).read_text())
    twin = json.loads(
        json.dumps(next(s for s in data["spells"] if s["key"] == "EXPLOSIVE_PROJECTILE"))
    )
    twin["key"] = "EXPLOSIVE_TWIN"
    data["spells"].append(twin)
    path = tmp_path / "twins.json"
    path.write_text(json.dumps(data))
    loadout = plan_loadout(["EXPLOSIVE_PROJECTILE", "EXPLOSIVE_TWIN", "BOMB"], 14, path=path)
    assert loadout is not None and loadout.durability == 14 and len(loadout.spells) == 2
    assert plan_loadout(["EXPLOSIVE_PROJECTILE", "EXPLOSIVE_TWIN", "BOMB"], 15, path=path) is None


# -- the wand ---------------------------------------------------------------------------------


def starter_game(tmp_path: Path, mats: Materials) -> Game:
    files = write_world(tmp_path, mats)
    return Game.from_world(files.png, files.json)


def slots(game: Game, wand: int) -> list[str | None]:
    p = game.player()
    assert p is not None
    return [s["spell"] if s else None for s in p["wands"][wand]["slots"]]


def test_assembling_puts_the_modifier_before_the_bomb_and_stow_puts_it_back(
    tmp_path: Path, mats: Materials
) -> None:
    game = starter_game(tmp_path, mats)
    for spell in ("BOMB", "EXPLOSIVE_PROJECTILE"):  # the order they were found in
        game.give_spell(spell)
    done = assemble(game, pair_loadout())
    assert done is not None and done.wand == 0
    assert slots(game, 0) == ["EXPLOSIVE_PROJECTILE", "BOMB", "LIGHT_BULLET"]
    assert slots(game, 1) == ["DIGGER"]  # the digger wand is not touched
    stow(game, pair_loadout(), done)
    p = game.player()
    assert p is not None
    assert slots(game, 0) == ["LIGHT_BULLET", None, None]
    assert sorted(s["spell"] for s in p["spells"]) == ["BOMB", "EXPLOSIVE_PROJECTILE"]


def test_the_assembled_wand_casts_the_pair_as_one_bomb(tmp_path: Path, mats: Materials) -> None:
    game = starter_game(tmp_path, mats)
    for spell in PAIR:
        game.give_spell(spell)
    done = assemble(game, pair_loadout())
    assert done is not None
    game.step(70)  # the opening settles
    game.step(2, {"select_wand": done.wand, "aim": -45.0, "fire": True})
    casts = [e for e in game.events() if e["type"] == "cast"]
    assert [c["spells"] for c in casts] == ["EXPLOSIVE_PROJECTILE+BOMB"]
    assert any(e["kind"] == "bomb" for e in game.entities())


def test_assembling_fails_cleanly_when_a_spell_is_missing(tmp_path: Path, mats: Materials) -> None:
    game = starter_game(tmp_path, mats)
    game.give_spell("BOMB")
    assert assemble(game, pair_loadout()) is None
    assert slots(game, 0) == ["LIGHT_BULLET", None, None]  # nothing was placed


def test_no_wand_with_room_means_no_assembly(tmp_path: Path, mats: Materials) -> None:
    game = starter_game(tmp_path, mats)
    for spell in PAIR:
        game.give_spell(spell)
    game.edit_wand({"op": "place", "wand": 0, "slot": 1, "from": 0})
    game.edit_wand({"op": "place", "wand": 0, "slot": 2, "from": 0})
    assert assemble(game, pair_loadout()) is None  # three slots taken, the other wand has one


# -- the throw --------------------------------------------------------------------------------


def rock_plug_bot(tmp_path: Path, mats: Materials, **kwargs: object) -> Descent:
    """The mini world with the plug made of rock (a bomb breaks rock) and a bomb in hand, the
    bot standing on the plug."""
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=20000, **kwargs)  # type: ignore[arg-type]
    bot.game.fill_rect(SEAL_X, SEAL_TOP, SEAL_W, SEAL_THICK, "rock")
    bot.game.give_spell("BOMB")
    assert bot.walk_to("to_seal", bot.front_goal())
    return bot


def test_a_bomb_opens_a_plug_and_the_thrower_is_out_of_the_blast(
    tmp_path: Path, mats: Materials
) -> None:
    bot = rock_plug_bot(tmp_path, mats)
    loadout = Loadout(("BOMB",), 11, 60, 25.0, 180, 3, True)
    assert break_with_loadout(bot, loadout, bot.geometry)
    assert bot.seal_open() and bot._p["hp"] == 100.0 and bot.summary.hp_min == 100.0
    blast = next(e for e in bot.log if e["event"] == "blast")
    assert blast["distance"] > loadout.radius and blast["frames"] == 180
    thrown = [e for e in bot.log if e["event"] == "blast_thrown"]
    assert len(thrown) == 1 and thrown[0]["away"] == loadout.radius + SAFETY
    p = bot.game.player()
    assert p is not None
    assert [[s["spell"] if s else None for s in w["slots"]] for w in p["wands"]] == [
        ["LIGHT_BULLET", None, None],
        ["DIGGER"],
    ]  # the wand is as it was, the bomb is back in the inventory
    assert [s["spell"] for s in p["spells"]] == ["BOMB"]


def test_a_second_bomb_follows_when_the_plug_stays_shut(tmp_path: Path, mats: Materials) -> None:
    """Brick beats the bomb (11 against 14): each cast leaves it closed, and the bot goes back
    for the next one until the casts it planned for are used up, without a scratch."""
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=20000)
    bot.game.give_spell("BOMB")
    assert bot.walk_to("to_seal", bot.front_goal())
    loadout = Loadout(("BOMB",), 14, 60, 25.0, 180, 2, True)  # claims 14, has 11
    assert not break_with_loadout(bot, loadout, bot.geometry)
    assert sum(e["event"] == "blast_thrown" for e in bot.log) == 2
    assert not bot._p["dead"] and bot.summary.hp_min == 100.0


def test_without_a_safe_place_nothing_is_thrown(
    tmp_path: Path, mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = rock_plug_bot(tmp_path, mats)
    monkeypatch.setattr(bot, "escape_goal", lambda centre, distance, budget: None)
    loadout = Loadout(("BOMB",), 11, 60, 25.0, 180, 3, True)
    assert not break_with_loadout(bot, loadout, bot.geometry)
    assert any(e["event"] == "blast_no_safe_place" for e in bot.log)
    assert not any(e["event"] == "blast_thrown" for e in bot.log)
    assert all(e["kind"] != "bomb" for e in bot.game.entities())
    assert bot.summary.hp_min == 100.0
    assert [s["spell"] for s in bot._p["spells"]] == ["BOMB"]  # stowed again


def test_the_escape_is_far_enough_and_reached_in_time(tmp_path: Path, mats: Materials) -> None:
    bot = rock_plug_bot(tmp_path, mats)
    centre = (float(bot.geometry.plug.cx), float(bot.geometry.plug.y))
    spot = bot.escape_goal(centre, 72.0, 140)
    assert spot is not None
    assert ((spot[0] + 2 - centre[0]) ** 2 + (spot[1] + 3 - centre[1]) ** 2) ** 0.5 >= 72.0
    assert bot.escape_goal(centre, 72.0, 20) is None  # nowhere that far in 20 frames


def test_the_spells_leave_the_wand_as_soon_as_the_bomb_is_thrown(
    tmp_path: Path, mats: Materials, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the bot runs, its digging wand must not hold a bomb: a bolt fired from it to clear
    the way would throw a second one."""
    bot = rock_plug_bot(tmp_path, mats)
    walk_to = bot.walk_to
    seen: dict[str, object] = {}

    def spy(label: str, goal: tuple[int, int], **kwargs: object) -> bool:
        if label == "flee":
            seen["slots"] = slots(bot.game, 0)
            seen["bombs"] = [e for e in bot.game.entities() if e["kind"] == "bomb"]
        return walk_to(label, goal, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(bot, "walk_to", spy)
    loadout = Loadout(("BOMB",), 11, 60, 25.0, 180, 1, True)
    assert break_with_loadout(bot, loadout, bot.geometry)
    assert seen["slots"] == ["LIGHT_BULLET", None, None] and len(seen["bombs"]) == 1  # type: ignore[arg-type]
