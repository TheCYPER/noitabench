"""Bottles hold mixtures: the state and `inspect` show them, the commands move them, the
passive view of a thing never tells what is in it."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agent_worlds import GROUND, START_X, write_arena
from noitabench.agent import AgentSession, SessionConfig
from noitabench.agent.engine import position_of
from noitabench.agent.render import render_text
from noitabench.game import Game

Make = Callable[..., AgentSession]
ALLOWED = {"id", "kind", "x", "y", "w", "h", "dx", "dy", "hostile", "aimed"}


def state(s: AgentSession) -> dict[str, Any]:
    return s.observe()["observation"]["state"]


def nearby(s: AgentSession, kind: str | None = None) -> list[dict[str, Any]]:
    seen = state(s)["nearby"]
    return [e for e in seen if kind is None or e["kind"] == kind]


def inspect(s: AgentSession, text: str) -> dict[str, Any]:
    a = s.decide(text)
    assert a["results"][0]["ok"], a["results"]
    return a["results"][0]["result"]


def mixture(*parts: tuple[str, int]) -> list[dict[str, Any]]:
    return [{"material": m, "amount": n} for m, n in parts]


# -- what is in a bottle ------------------------------------------------------------------------


def test_the_state_lists_what_each_of_your_bottles_holds(game: Game, make_session: Make) -> None:
    game.give_bottle(contents=mixture(("oil", 60), ("water", 100)))
    game.give_bottle("blood", 40)
    game.give_bottle()
    s = make_session(game)
    bottles = state(s)["bottles"]
    assert bottles[0]["contents"] == mixture(("water", 100), ("oil", 60))
    assert (bottles[0]["material"], bottles[0]["amount"]) == ("water", 160)  # the largest share
    assert bottles[1]["contents"] == mixture(("blood", 40))
    assert (bottles[2]["material"], bottles[2]["amount"], bottles[2]["contents"]) == (None, 0, [])
    text = render_text(s.observe())
    assert "[0]* water 100, oil 60 (160/400)" in text and "empty (0/400)" in text
    assert inspect(s, "inspect(bottle=0)")["contents"] == mixture(("water", 100), ("oil", 60))


def test_filling_where_two_liquids_lie_takes_both_and_the_result_says_so(
    game_at: Callable[[int], Game], make_session: Make
) -> None:
    game = game_at(352)  # on the pool of water
    game.paint(352, GROUND - 1, 3, "oil")
    game.give_bottle()
    s = make_session(game)
    a = s.decide("fill(amount=150)")
    result = a["results"][0]["result"]
    held = state(s)["bottles"][0]["contents"]
    assert {part["material"] for part in held} == {"water", "oil"}
    assert result["cells"] == sum(part["amount"] for part in held)
    assert result["material"] == "water+oil"
    assert sorted(p["material"] for p in result["parts"]) == ["oil", "water"]


def test_pouring_a_mixture_reports_every_material(game: Game, make_session: Make) -> None:
    game.give_bottle(contents=mixture(("water", 30), ("oil", 10)))
    s = make_session(game)
    a = s.decide("pour(amount=all)")
    result = a["results"][0]["result"]
    assert result["cells"] == 40 and result["material"] == "water+oil"
    assert result["parts"] == [
        {"material": "water", "cells": 30},
        {"material": "oil", "cells": 10},
    ]
    assert state(s)["bottles"][0]["amount"] == 0


def test_a_single_liquid_reports_as_it_always_did(game: Game, make_session: Make) -> None:
    game.give_bottle("oil", 50)
    s = make_session(game)
    a = s.decide("pour(amount=16)")  # 8 cells a frame
    assert a["results"][0]["result"] == {"material": "oil", "cells": 16}


def test_throwing_a_mixture_is_told_in_words(game: Game, make_session: Make) -> None:
    game.give_bottle(contents=mixture(("water", 30), ("oil", 20)))
    s = make_session(game)
    a = s.decide("throw")
    assert [e["text"] for e in a["events"] if e["type"] == "throw"] == [
        "You threw a bottle of water and oil (50 cells)."
    ]


def test_secret_recipes_work_in_the_bottle_the_agent_carries(tmp_path: Path) -> None:
    arena = write_arena(tmp_path / "recipe")
    recipes = [{"potion": "potion_crit", "inputs": ["water", "blood", "oil"]}]
    game = Game.from_world(arena.png, arena.json, 1, recipes=recipes)
    game.step(61)
    game.events()
    game.give_bottle(contents=mixture(("water", 20), ("blood", 20)))
    s = AgentSession(game)
    s.decide("wait(ticks=5)")
    assert state(s)["bottles"][0]["contents"] == mixture(("water", 20), ("blood", 20))
    game.give_bottle(contents=mixture(("water", 20), ("blood", 20), ("oil", 20)))
    answer = s.decide("wait(ticks=10)")  # 60 frames; 4 cells of each ingredient turn over a frame
    held = {p["material"]: p["amount"] for p in state(s)["bottles"][1]["contents"]}
    assert held == {"potion_crit": 60}
    # the agent is never told how it came about: no `mix` event, in the answer or the log
    assert "mix" not in {e["type"] for e in answer["events"]}
    assert '"mix"' not in json.dumps(answer) and '"mix"' not in json.dumps(s.observe())


# -- the summary events are written when the action ends --------------------------------------------


def test_the_drink_event_is_written_on_the_frame_the_command_ends(
    game: Game, tmp_path: Path
) -> None:
    game.give_bottle("potion_heal", 400)
    out = tmp_path / "rec"
    s = AgentSession(game, recording_dir=out)
    start = s.frame
    a = s.decide("drink(amount=100)")  # 10 cells a frame: the last frame of the tick
    assert a["stop"]["frames"] == 10 and s.frame == start + 10
    s.close()
    events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]
    drinks = [e for e in events if e["type"] == "drink"]
    assert len(drinks) == 1 and drinks[0]["cells"] == 100
    assert drinks[0]["frame"] == start + 10  # not a frame of the next decision


# -- what can be seen of a thing ----------------------------------------------------------------------


def test_the_passive_view_of_a_thing_is_only_its_kind_and_place(
    game: Game, make_session: Make
) -> None:
    game.spawn_item("potion_heal", START_X + 8, GROUND)
    game.spawn_item("bottle", START_X + 12, GROUND, contents=mixture(("water", 10), ("oil", 10)))
    game.spawn_item("wand", START_X + 16, GROUND, tier=2)
    game.spawn_item("barrel_oil", START_X + 22, GROUND)
    game.spawn_enemy("longleg", START_X + 40, GROUND)
    game.spawn_enemy("firemage_weak", START_X + 70, GROUND)
    s = make_session(game)
    seen = nearby(s)
    assert {e["kind"] for e in seen} >= {"bottle", "wand", "spell", "longleg", "barrel_oil"}
    for e in seen:
        assert set(e) <= ALLOWED, e
    # a potion is just a bottle until it is looked at
    assert not any(e["kind"].startswith("potion_") for e in seen)
    potion = next(e for e in seen if e["x"] == START_X + 8 - 2)
    assert potion["kind"] == "bottle"
    assert inspect(s, f"inspect(entity={potion['id']})")["kind"] == "potion_heal"
    # health and conditions of a creature, too
    enemy = next(e for e in seen if e["kind"] == "longleg")
    assert "hp" not in enemy and "statuses" not in enemy
    shown = inspect(s, f"inspect(entity={enemy['id']})")
    assert shown["hp"] > 0 and shown["hp_max"] > 0
    text = render_text(s.observe())
    assert "potion_heal" not in text and "hp 2.8/2.8" not in text


def test_no_command_tells_which_potion_a_bottle_on_the_ground_holds(
    game: Game, make_session: Make
) -> None:
    """Error messages and the `aim` target match by the kind an agent is told (`bottle`)."""
    game.spawn_item("potion_lively", START_X + 6, GROUND)
    s = make_session(game)
    wrong = s.decide("pickup(item=99999)")["results"][0]
    assert wrong["code"] == "not_nearest" and "potion_" not in wrong["message"]
    assert "bottle" in wrong["message"]
    # the raw kind is no handle on it, the public one is
    probe = s.decide("aim(target=potion_lively)")["results"][0]
    assert probe["ok"] is False and probe["code"] == "not_in_view"
    nearest = min(nearby(s, "bottle"), key=lambda e: abs(e["dx"]))
    found = s.decide("aim(target=bottle)")["results"][0]
    assert found["ok"] and found["result"]["follows"] == nearest["id"]


def test_a_spell_card_on_the_ground_hides_its_key_until_inspected(
    game: Game, make_session: Make
) -> None:
    s = make_session(game)
    card = nearby(s, "spell")[0]
    assert set(card) <= ALLOWED
    assert inspect(s, f"inspect(entity={card['id']})")["card"]["spell"] == "BOMB"


def test_a_projectile_in_flight_is_a_dot_without_a_name(game: Game, make_session: Make) -> None:
    game.spawn_enemy("longleg", START_X + 60, GROUND)
    s = make_session(game)
    s.decide("aim(target=longleg); fire(until=ticks, ticks=2)")
    shots = [e for e in nearby(s) if e["kind"] == "projectile"]
    for shot in shots:
        assert set(shot) <= ALLOWED


def test_a_wand_on_the_ground_shows_its_stats_to_inspect_only(
    game: Game, make_session: Make
) -> None:
    game.spawn_item(
        "wand",
        START_X + 14,
        GROUND,
        stats={
            "cast_delay": 7,
            "recharge": 33,
            "mana_max": 250,
            "mana_charge_speed": 44,
            "capacity": 4,
            "spells_per_cast": 2,
        },
        spells=["BOMB", None, "DAMAGE"],
    )
    s = make_session(game)
    wand = nearby(s, "wand")[0]
    assert set(wand) <= ALLOWED
    r = inspect(s, f"inspect(entity={wand['id']})")
    info = r["wand"]
    assert (info["capacity"], info["cast_delay"], info["recharge"]) == (4, 7, 33)
    assert (info["mana_max"], info["mana_per_second"], info["spells_per_cast"]) == (250, 44, 2)
    assert [x["spell"] for x in info["slots"]] == ["BOMB", None, "DAMAGE", None]
    assert info["slots"][0]["mana"] == 25 and info["slots"][0]["explosion_radius"] == 60
    assert "what" not in info and "index" not in info and "active" not in info


def test_a_bottle_on_the_ground_shows_what_it_holds_to_inspect_only(
    game: Game, make_session: Make
) -> None:
    game.spawn_item("bottle", START_X + 12, GROUND, contents=mixture(("oil", 10), ("water", 25)))
    s = make_session(game)
    ours = next(e for e in nearby(s, "bottle") if e["x"] == START_X + 12 - 2)
    r = inspect(s, f"inspect(entity={ours['id']})")
    assert r["contents"] == mixture(("water", 25), ("oil", 10)) and r["amount"] == 35


@pytest.mark.parametrize("channel", ["text", "ascii"])
def test_the_map_does_not_give_a_potion_away_either(
    game: Game, make_session: Make, channel: str
) -> None:
    game.spawn_item("potion_haste", START_X + 8, GROUND)
    s = make_session(game, text=channel == "text", ascii=channel == "ascii")
    out = json.dumps(s.observe()["observation"])
    assert "potion_haste" not in out and "haste" not in out


def test_position_of_still_matches_the_world(game: Game) -> None:
    p = game.player()
    assert p is not None and position_of(p) == (START_X, GROUND)


def test_the_config_default_still_builds(game: Game) -> None:
    AgentSession(game, config=SessionConfig())
