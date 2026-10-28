"""Every command of the table, its results, and what an invalid one does."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from agent_worlds import GROUND, REST, START_X, STATION, WALL_X, write_arena
from noitabench.agent import AgentSession, InMemoryNotes
from noitabench.agent.engine import position_of
from noitabench.game import Game

Make = Callable[..., AgentSession]


def nearby(s: AgentSession, kind: str) -> list[dict[str, Any]]:
    return [e for e in s.observe()["observation"]["state"]["nearby"] if e["kind"] == kind]


def state(s: AgentSession) -> dict[str, Any]:
    return s.observe()["observation"]["state"]


def events(answer: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [e for e in answer["events"] if e["type"] == kind]


# -- hands and aim ------------------------------------------------------------------------------------


def test_aim_in_all_its_forms_is_remembered(game: Game, make_session: Make) -> None:
    game.spawn_enemy("longleg", START_X + 60, GROUND)
    s = make_session(game)
    frame = s.frame
    r = s.decide("aim(angle=45)")["results"][0]
    assert r["result"]["aim_degrees"] == 45 and s.frame == frame  # no time passes
    s.decide("wait")
    assert state(s)["aim"]["degrees"] == pytest.approx(45, abs=0.1)
    s.decide(f"aim(x={START_X + 50}, y={GROUND - 30})")
    s.decide("wait")
    assert 20 < state(s)["aim"]["degrees"] < 50  # up and to the right
    enemy = nearby(s, "longleg")[0]
    r = s.decide("aim(target=longleg)")["results"][0]["result"]
    assert r["follows"] == enemy["id"]
    s.decide("wait")
    after = state(s)
    assert after["aim"]["follows"] == enemy["id"] and after["aim"]["degrees"] == pytest.approx(
        0, abs=12
    )
    assert any(e.get("aimed") for e in after["nearby"])
    s.decide("aim(angle=90)")
    assert state(s)["aim"]["follows"] is None


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("aim(entity=999)", "not_in_view"),
        ("aim(target=shotgunner)", "not_in_view"),
        ("aim(x=-4, y=10)", "out_of_world"),
    ],
)
def test_aim_at_something_that_is_not_there_is_refused(
    session: AgentSession, text: str, code: str
) -> None:
    a = session.decide(text)
    assert a["stop"]["code"] == code and a["stop"]["frames"] == 0


def test_fire_casts_with_the_held_wand_along_the_aim(session: AgentSession) -> None:
    session.decide("aim(angle=90)")
    a = session.decide("fire(ticks=3)")
    casts = events(a, "cast")
    assert casts and casts[0]["spells"] == "LIGHT_BULLET" and casts[0]["wand"] == 0
    assert a["stop"]["detail"] == "ticks"


def test_fire_with_an_empty_wand_is_refused(game: Game, make_session: Make) -> None:
    game.give_wand(
        {"cast_delay": 5, "recharge": 5, "mana_max": 100, "mana_charge_speed": 10, "capacity": 2},
        [],
    )
    s = make_session(game)
    s.decide("swap_wand(2)")
    a = s.decide("fire")
    assert a["stop"]["code"] == "empty_wand" and a["stop"]["frames"] == 0


def test_swap_wand_takes_a_tick_and_changes_the_held_wand(session: AgentSession) -> None:
    a = session.decide("swap_wand(1)")
    assert a["stop"]["frames"] == 10 and state(session)["active_wand"] == 1
    assert [w["active"] for w in state(session)["wands"]] == [False, True]
    bad = session.decide("swap_wand(5)")
    assert bad["stop"]["code"] == "no_such_wand" and bad["stop"]["frames"] == 0


def test_kick_hits_what_is_in_front(game: Game, make_session: Make) -> None:
    game.spawn_item("bottle", START_X + 5, GROUND, material="water", amount=100)
    s = make_session(game)
    a = s.decide("kick")
    assert a["stop"]["frames"] == 10
    assert events(a, "kick") and events(a, "kick")[0]["hits"] >= 1


# -- bottles -----------------------------------------------------------------------------------------


def bottle(s: AgentSession, i: int = 0) -> dict[str, Any]:
    return state(s)["bottles"][i]


def test_drink_takes_a_sip_by_default(game: Game, make_session: Make) -> None:
    game.give_bottle("water", 400)
    s = make_session(game)
    a = s.decide("drink")
    assert a["stop"]["frames"] == 10 and bottle(s)["amount"] == 300
    assert a["results"][0]["result"] == {"material": "water", "cells": 100}
    b = s.decide("drink(amount=all)")
    assert bottle(s)["amount"] == 0 and b["stop"]["detail"] == "done"
    c = s.decide("drink")
    assert c["stop"]["code"] == "empty_bottle" and c["stop"]["frames"] == 0


def test_pour_empties_the_bottle_in_front_and_fill_scoops_it_up_again(
    game: Game, make_session: Make
) -> None:
    game.give_bottle("water", 200)
    s = make_session(game)
    s.interrupts.disable("status_change")  # splashing makes the player wet
    a = s.decide("pour(angle=0)")
    assert bottle(s)["amount"] == 0
    assert a["results"][0]["result"] == {"material": "water", "cells": 200}
    s.decide("wait(ticks=10)")
    b = s.decide("fill")
    assert bottle(s)["amount"] > 0 and bottle(s)["material"] == "water"
    assert (
        b["results"][0]["result"]["material"] == "water" and b["results"][0]["result"]["cells"] > 0
    )


def test_throw_removes_the_bottle_and_it_spills_where_it_breaks(
    game: Game, make_session: Make
) -> None:
    game.give_bottle("water", 100)
    s = make_session(game)
    a = s.decide("throw(angle=30)")
    assert state(s)["bottles"] == [] and events(a, "throw")
    b = s.decide("wait(ticks=15)")
    assert events(b, "shatter")


def test_a_bottle_that_is_not_there_is_refused_without_time(session: AgentSession) -> None:
    for text in ("drink", "pour", "fill", "throw", "drink(bottle=2)"):
        a = session.decide(text)
        assert a["stop"]["reason"] == "invalid", text
        assert a["stop"]["code"] in {"no_such_bottle", "empty_bottle"} and a["stop"]["frames"] == 0


def test_fill_of_a_full_bottle_is_refused(game: Game, make_session: Make) -> None:
    game.give_bottle("water", 400)
    a = make_session(game).decide("fill")
    assert a["stop"]["code"] == "bottle_full"


def test_a_pour_with_nothing_coming_out_stops_after_a_tick(game: Game, make_session: Make) -> None:
    game.give_bottle("water", 100)
    s = make_session(game)
    s.decide("pour(angle=-90)")  # straight down at the feet: into the ground
    game.give_bottle("water", 100)
    a = s.decide("pour(bottle=1, angle=-90)")
    assert a["stop"]["reason"] == "completed"


# -- pick up, drop, wands ---------------------------------------------------------------------------


def test_pickup_takes_the_nearest_item_and_names_it(session: AgentSession) -> None:
    s = session
    s.decide("walk_to(x=44)")
    spell = nearby(s, "spell")[0]
    wrong = s.decide(f"pickup(item={spell['id'] + 1})")
    assert wrong["stop"]["code"] == "not_nearest"
    a = s.decide(f"pickup(item={spell['id']})")
    assert a["stop"]["frames"] == 10
    assert events(a, "pickup")[0]["item"] == "spell" and events(a, "pickup")[0]["detail"] == "BOMB"
    assert [c["spell"] for c in state(s)["spells"]] == ["BOMB"]
    assert all(e["kind"] != "spell" for e in state(s)["nearby"])


def test_pickup_with_nothing_in_reach_is_refused_without_time(
    game_at: Callable[[int], Game], make_session: Make
) -> None:
    s = make_session(game_at(120))
    far = s.decide("pickup")
    assert far["stop"]["code"] == "nothing_in_reach" and far["stop"]["frames"] == 0


def test_drop_puts_a_wand_a_spell_or_a_bottle_on_the_ground_for_one_tick(
    game: Game, make_session: Make
) -> None:
    game.give_spell("DAMAGE")
    game.give_bottle(
        contents=[{"material": "water", "amount": 30}, {"material": "oil", "amount": 20}]
    )
    s = make_session(game)
    frame = s.frame
    a = s.decide("drop(wand=1)")
    assert a["stop"]["frames"] == 10 and s.frame == frame + 10
    assert events(a, "drop")[0]["text"] == "You dropped a wand."
    assert len(state(s)["wands"]) == 1
    assert len(nearby(s, "wand")) == 1
    s.decide("drop(spell=0)")
    assert state(s)["spells"] == []
    assert nearby(s, "spell")[0]["kind"] == "spell"
    a = s.decide("drop(bottle=0)")
    assert state(s)["bottles"] == [] and events(a, "drop")[0]["detail"] == "water+oil"
    dropped = [e for e in nearby(s, "bottle") if e["dx"] == pytest.approx(0, abs=12)]
    assert dropped, "next to the player"
    contents = inspect(s, f"inspect(entity={dropped[0]['id']})")["contents"]
    assert contents == [{"material": "water", "amount": 30}, {"material": "oil", "amount": 20}]
    # and it can be picked up again, with its contents
    s.decide(f"pickup(item={dropped[0]['id']})")
    assert state(s)["bottles"][0]["contents"] == contents


def test_drop_of_something_that_is_not_there_costs_no_time(session: AgentSession) -> None:
    frame = session.frame
    for text, code in (
        ("drop(wand=5)", "no_such_wand"),
        ("drop(spell=0)", "no_such_spell"),
        ("drop(bottle=0)", "no_such_bottle"),
    ):
        a = session.decide(text)
        assert a["stop"]["reason"] == "invalid" and a["stop"]["code"] == code, text
        assert a["stop"]["frames"] == 0 and a["results"][0]["ok"] is False
    assert session.frame == frame
    a = session.decide("drop(wand=0, bottle=0)")
    assert a["stop"]["code"] == "bad_argument"


# -- edit_wand ---------------------------------------------------------------------------------------


def carry_bomb(s: AgentSession) -> None:
    s.decide("walk_to(x=44)")
    s.decide("pickup")


def test_wands_can_be_edited_in_a_rest_area(session: AgentSession) -> None:
    carry_bomb(session)
    assert state(session)["can_edit_wands"] is True
    frame = session.frame
    a = session.decide("edit_wand(op=place, wand=0, slot=1, spell=0)")
    assert a["results"][0]["ok"] and session.frame == frame
    assert a["results"][0]["result"]["slots"] == ["LIGHT_BULLET", "BOMB", None]
    assert a["results"][0]["result"]["carried"] == []
    assert state(session)["wands"][0]["slots"][1]["spell"] == "BOMB"
    b = session.decide("edit_wand(op=swap, wand=0, a=0, b=1)")
    assert b["results"][0]["result"]["slots"] == ["BOMB", "LIGHT_BULLET", None]
    c = session.decide("edit_wand(op=take, wand=0, slot=0)")
    assert c["results"][0]["result"]["carried"] == ["BOMB"]


def test_wands_cannot_be_edited_outside_a_rest_area_or_station(session: AgentSession) -> None:
    carry_bomb(session)
    session.decide(f"walk_to(x={REST['x'] + REST['w'] - 3})")
    session.decide("move(right, ticks=4)")  # out of the box
    assert state(session)["can_edit_wands"] is False
    frame = session.frame
    a = session.decide("edit_wand(op=place, wand=0, slot=1, spell=0)")
    assert a["stop"]["code"] == "not_here" and "rest area" in a["stop"]["message"]
    assert session.frame == frame
    assert (
        state(session)["wands"][0]["slots"][1] is None
        or state(session)["wands"][0]["slots"][1]["spell"] is None
    )


def test_wands_can_be_edited_at_an_edit_station(
    game_at: Callable[[int], Game], make_session: Make
) -> None:
    game = game_at(STATION["x"] + 5)
    game.give_spell("DAMAGE")
    s = make_session(game)
    assert state(s)["can_edit_wands"] is True
    a = s.decide("edit_wand(op=place, wand=0, slot=2, spell=0)")
    assert a["results"][0]["result"]["slots"][2] == "DAMAGE"


def test_a_world_without_rest_areas_never_allows_edits(tmp_path: Any, make_session: Make) -> None:
    spawn = [{"type": "spawn_player", "x": START_X, "y": GROUND}]
    arena = write_arena(tmp_path / "plain", base_markers=spawn)
    game = arena.game()
    game.step(61)
    game.give_spell("DAMAGE")
    a = make_session(game).decide("edit_wand(op=place, wand=0, slot=1, spell=0)")
    assert a["stop"]["code"] == "not_here"


def test_a_failing_edit_says_why_and_takes_no_time(session: AgentSession) -> None:
    a = session.decide("edit_wand(op=take, wand=0, slot=1)")  # slot 1 is empty
    assert a["stop"]["code"] == "edit_failed" and a["stop"]["frames"] == 0
    b = session.decide("edit_wand(op=place, wand=9, slot=0, spell=0)")
    assert b["stop"]["code"] == "edit_failed"


# -- inspect ------------------------------------------------------------------------------------------


def inspect(s: AgentSession, text: str) -> dict[str, Any]:
    a = s.decide(text)
    assert a["results"][0]["ok"], a["results"]
    return a["results"][0]["result"]


def test_inspect_a_cell(session: AgentSession) -> None:
    r = inspect(session, f"inspect(x=100, y={GROUND + 5})")
    assert r == {"what": "cell", "x": 100, "y": GROUND + 5, "material": "rock", "burning": False}
    far = session.decide("inspect(x=400, y=100)")
    assert far["stop"]["code"] == "out_of_sight"
    assert session.decide("inspect(x=-3, y=1)")["stop"]["code"] == "out_of_sight"


def test_inspect_gives_exact_facts_and_no_properties_of_materials(session: AgentSession) -> None:
    text = str(inspect(session, f"inspect(x=40, y={GROUND + 3})"))
    for word in ("kind", "family", "tags", "density", "flammable", "corrodible"):
        assert word not in text


def test_inspect_a_creature_and_items(game: Game, make_session: Make) -> None:
    game.spawn_enemy("longleg", START_X + 70, GROUND)
    s = make_session(game)
    e = nearby(s, "longleg")[0]
    r = inspect(s, f"inspect(entity={e['id']})")
    assert (r["kind"], r["hp"], r["hp_max"]) == (
        "longleg",
        pytest.approx(2.8, abs=0.1),
        pytest.approx(2.8, abs=0.1),
    )
    spell = nearby(s, "spell")[0]
    card = inspect(s, f"inspect(entity={spell['id']})")["card"]
    assert card["spell"] == "BOMB" and card["mana"] == 25
    assert (card["uses_left"], card["uses_max"]) == (3, 3)
    assert card["explosion_radius"] == 60 and "payload" not in card
    water = nearby(s, "bottle")[0]
    found = inspect(s, f"inspect(entity={water['id']})")
    assert found["contents"] == [{"material": "water", "amount": 400}] and found["amount"] == 400
    assert s.decide("inspect(entity=999)")["stop"]["code"] == "not_in_view"


def test_inspect_wands_slots_spells_and_bottles(game: Game, make_session: Make) -> None:
    game.give_bottle("oil", 150)
    game.give_spell("LIGHT_BULLET_TIMER")
    s = make_session(game)
    wand = inspect(s, "inspect(wand=0)")
    assert wand["active"] and wand["capacity"] == 3 and wand["mana_per_second"] == 30
    assert [x["spell"] for x in wand["slots"]] == ["LIGHT_BULLET", None, None]
    slot = inspect(s, "inspect(wand=0, slot=0)")
    assert slot["name"] == "Spark Bolt" and slot["damage"] == 3.0 and slot["cast_delay"] == 3
    assert slot["uses"] == "unlimited" and "uses_left" not in slot
    card = inspect(s, "inspect(spell=0)")
    assert card["spell"] == "LIGHT_BULLET_TIMER" and card["payload"]["when"] == "timer"
    assert inspect(s, "inspect(bottle=0)") == {
        "what": "bottle", "index": 0, "material": "oil", "amount": 150, "capacity": 400,
        "active": True, "contents": [{"material": "oil", "amount": 150}],
    }  # fmt: skip
    for text, code in (
        ("inspect(wand=7)", "no_such_wand"),
        ("inspect(wand=0, slot=9)", "no_such_slot"),
        ("inspect(spell=5)", "no_such_spell"),
        ("inspect(bottle=3)", "no_such_bottle"),
    ):
        assert s.decide(text)["stop"]["code"] == code


def test_a_spell_card_shows_the_editor_numbers_but_not_the_hidden_durability(
    game: Game, make_session: Make
) -> None:
    game.give_spell("EXPLOSIVE_PROJECTILE")
    s = make_session(game)
    card = inspect(s, "inspect(spell=0)")
    assert card["explosion_radius_added"] == 15 and card["mana"] == 30
    assert "durability" not in str(card)


# -- notes ----------------------------------------------------------------------------------------------


def test_the_memory_commands_forward_to_the_backend(game: Game) -> None:
    from noitabench.agent import AgentSession

    notes = InMemoryNotes(max_chars=60)
    s = AgentSession(game, memory=notes)
    r = s.decide("memory_write('lab.md', 'oil burns')")["results"][0]["result"]
    assert r["chars"] == 9 and r["chars_left"] == 51
    s.decide("memory_write('lab.md', ' fast', append=true)")
    assert s.decide("memory_read('lab.md')")["results"][0]["result"]["text"] == "oil burns fast"
    hit = s.decide("memory_search('BURNS')")["results"][0]["result"]["hits"]
    assert hit == [{"path": "lab.md", "line": 1, "text": "oil burns fast"}]
    s.decide("memory_edit('lab.md', 'fast', 'slowly')")
    assert notes.files["lab.md"] == "oil burns slowly"
    assert s.decide("memory_list")["results"][0]["result"]["files"] == [
        {"path": "lab.md", "chars": 16}
    ]
    full = s.decide("memory_write('big.md', 'x' * 3)")  # an expression is not allowed
    assert full["stop"]["reason"] == "invalid"
    over = s.decide(f"memory_write('big.md', '{'x' * 80}')")
    assert over["stop"]["code"] == "notes_full"
    bad = s.decide("memory_edit('lab.md', 'zzz', 'a')")
    assert bad["stop"]["code"] == "edit_failed"
    assert s.decide("memory_read('nope')")["stop"]["code"] == "no_such_note"


def test_memory_commands_take_no_time_and_without_a_backend_there_is_no_notebook(
    session: AgentSession,
) -> None:
    frame = session.frame
    a = session.decide("memory_list")
    assert a["stop"]["code"] == "no_notebook" and session.frame == frame


# -- invalid commands, the end of the episode ---------------------------------------------------------


def test_an_invalid_decision_counts_takes_no_time_and_is_data(session: AgentSession) -> None:
    frame = session.frame
    a = session.decide("walk_to(x='left')")
    assert a["decision"] == 2 and a["decisions_left"] == 999
    assert a["stop"]["reason"] == "invalid" and a["stop"]["code"] == "bad_argument"
    assert a["results"][0] == {
        "command": "walk_to",
        "ok": False,
        "code": "bad_argument",
        "message": a["stop"]["message"],
    }
    assert session.frame == frame
    assert session.decide("dance")["stop"]["code"] == "unknown_command"
    assert session.decide("walk_to(")["stop"]["code"] == "syntax"
    assert session.decide({"commands": []})["stop"]["code"] == "syntax"
    assert session.decide("wait")["stop"]["reason"] == "completed"  # and play goes on


def test_a_decision_with_a_bad_command_runs_none_of_it(session: AgentSession) -> None:
    frame = session.frame
    a = session.decide("walk_to(x=200); walk_to(x='b'); kick")
    assert a["stop"]["code"] == "bad_argument" and session.frame == frame


def test_a_command_that_fails_while_running_skips_the_rest(session: AgentSession) -> None:
    a = session.decide("kick; swap_wand(9); wait(ticks=5)")
    assert [r.get("code") for r in a["results"]] == [None, "no_such_wand", "skipped"]
    assert a["stop"]["code"] == "no_such_wand"
    assert a["stop"]["frames"] == 10  # the time the kick took before the error


def test_the_episode_ends_at_the_decision_limit(game: Game, make_session: Make) -> None:
    s = make_session(game, max_decisions=2)
    s.decide("wait")
    last = s.decide("wait")
    assert last["over"] == "decision_limit" and last["decisions_left"] == 0
    frame = s.frame
    refused = s.decide("wait")
    assert refused["stop"]["reason"] == "over" and s.frame == frame
    assert refused["decision"] == 3 and s.decisions == 2


def test_the_episode_ends_when_the_player_dies(game: Game, make_session: Make) -> None:
    s = make_session(game)
    x, y = position_of(s.engine.player())
    game.blast(x, y, 20, 100.0)  # far more than the player has
    a = s.decide("wait(ticks=5)")
    assert a["stop"]["reason"] == "dead" and a["over"] == "dead"
    assert a["stop"]["ticks"] == 1  # the world is looked at on the first boundary
    assert s.decide("wait")["stop"]["reason"] == "over"


def test_a_world_boundary_command_far_from_the_player_is_still_valid(session: AgentSession) -> None:
    a = session.decide(f"walk_to(x={WALL_X - 5})")
    assert a["stop"]["detail"] == "reached"
