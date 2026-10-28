"""The default interrupts (damage, new enemy, new status, blocked) and the optional ones."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from agent_worlds import GROUND, PIT_X, POOL_X, START_X, WALL_X
from noitabench.agent import AgentSession, Interrupts
from noitabench.agent.vocab import (
    ALL_INTERRUPTS,
    DEFAULT_INTERRUPTS,
    OPTIONAL_INTERRUPTS,
    STALL_FRAMES,
)
from noitabench.game import Game

Make = Callable[..., AgentSession]
NAMES = ("air", "rock", "water", "ground")


def player(hp: float = 100.0, statuses: dict[str, int] | None = None) -> dict[str, Any]:
    return {"hp": hp, "statuses": statuses or {}}


def look(
    it: Interrupts,
    p: dict[str, Any],
    *,
    hostiles: dict[int, str] | None = None,
    events: list[dict[str, Any]] | None = None,
    materials: set[int] | None = None,
    submerged: bool = False,
    blocked: str | None = None,
) -> list[str]:
    hostiles = hostiles or {}
    visible = [
        {"id": i, "kind": k, "dx": 40, "dy": 0, "hp": 1.0, "hp_max": 1.0}
        for i, k in hostiles.items()
    ]
    fired = it.observe(
        p, visible, set(hostiles), events or [], materials or set(), submerged, blocked, NAMES
    )
    return [t.name for t in fired]


def test_four_interrupts_are_on_by_default_and_three_are_off() -> None:
    assert DEFAULT_INTERRUPTS == ("damage", "new_enemy", "status_change", "blocked")
    assert OPTIONAL_INTERRUPTS == ("fell_in_liquid", "hp_low", "new_material")
    it = Interrupts()
    assert it.enabled == set(DEFAULT_INTERRUPTS)
    with pytest.raises(ValueError, match="unknown interrupt"):
        it.enable("boredom")


def test_damage_fires_on_a_damage_event_or_a_drop_in_hp() -> None:
    it = Interrupts(hp=100.0)
    hit = {"type": "damage", "target": "player", "amount": 6.0}
    assert look(it, player(94), events=[hit]) == ["damage"]
    assert look(it, player(94)) == []  # hp is steady now
    assert look(it, player(80)) == ["damage"]  # a drop alone is enough
    other = {"type": "damage", "target": "longleg", "amount": 3.0}
    assert look(it, player(80), events=[other]) == []
    assert look(it, player(90)) == []  # healing is not damage


def test_a_hostile_interrupts_once_when_it_comes_into_view() -> None:
    it = Interrupts(hp=100.0)
    assert look(it, player(), hostiles={4: "longleg"}) == ["new_enemy"]
    assert look(it, player(), hostiles={4: "longleg"}) == []  # the same one: not again
    assert look(it, player(), hostiles={}) == []
    assert look(it, player(), hostiles={4: "longleg"}) == []  # out and back: still the same one
    assert look(it, player(), hostiles={4: "longleg", 9: "shotgunner"}) == ["new_enemy"]


def test_the_message_names_the_newcomer_and_where() -> None:
    it = Interrupts(hp=100.0)
    visible = [{"id": 4, "kind": "longleg", "dx": 60, "dy": -3}]
    (fired,) = it.observe(player(), visible, {4}, [], set(), False, None, NAMES)
    assert fired.message == "Came into view: longleg #4 60 px right."


def test_a_new_status_interrupts_but_one_that_ends_does_not() -> None:
    it = Interrupts(hp=100.0)
    assert look(it, player(statuses={"wet": 700})) == ["status_change"]
    assert look(it, player(statuses={"wet": 600})) == []
    assert look(it, player(statuses={"wet": 500, "on_fire": 300})) == ["status_change"]
    assert look(it, player()) == []


def test_blocked_fires_for_a_wall() -> None:
    it = Interrupts(hp=100.0)
    (wall,) = it.observe(player(), [], set(), [], set(), False, "wall", NAMES)
    assert (wall.name, wall.message) == ("blocked", "A wall is in the way.")


def test_simultaneous_interrupts_are_reported_in_a_fixed_order() -> None:
    it = Interrupts(hp=100.0)
    hit = {"type": "damage", "target": "player", "amount": 6.0}
    got = look(
        it, player(90, {"on_fire": 300}), hostiles={4: "longleg"}, events=[hit], blocked="wall"
    )
    assert got == ["damage", "new_enemy", "status_change", "blocked"]


def test_the_optional_interrupts_are_silent_until_enabled() -> None:
    it = Interrupts(hp=20.0)
    assert look(it, player(20), submerged=True, materials={2}) == []
    for name in OPTIONAL_INTERRUPTS:
        it.enable(name, hp_below=50.0) if name == "hp_low" else it.enable(name)
    assert it.enabled == set(ALL_INTERRUPTS)
    it.submerged, it.hp = False, 60.0
    got = look(it, player(40), submerged=True, materials={2})
    assert got == ["damage", "fell_in_liquid", "hp_low"]


def test_hp_low_fires_when_the_threshold_is_crossed_not_while_below_it() -> None:
    it = Interrupts(hp=100.0)
    it.enable("hp_low", hp_below=50.0)
    it.disable("damage")
    assert look(it, player(70)) == []
    assert look(it, player(45)) == ["hp_low"]
    assert look(it, player(40)) == []


def test_new_material_ignores_what_was_in_view_when_it_was_switched_on() -> None:
    it = Interrupts(hp=100.0)
    it.enable("new_material")
    assert look(it, player(), materials={1, 2}) == []  # the first look only learns
    assert look(it, player(), materials={1, 2}) == []
    assert look(it, player(), materials={1, 2, 3}) == ["new_material"]
    assert look(it, player(), materials={1, 2, 3}) == []


def test_interrupts_survive_a_round_trip() -> None:
    it = Interrupts(hp=77.0)
    it.enable("hp_low", hp_below=40.0)
    look(it, player(77, {"wet": 5}), hostiles={4: "longleg"})
    again = Interrupts.from_dict(it.to_dict())
    assert again == it


# -- in a world -------------------------------------------------------------------------------------


def test_the_blocked_interrupt_can_be_switched_off(game: Game, make_session: Make) -> None:
    s = make_session(game)
    s.decide(f"walk_to(x={WALL_X - 15})")
    s.interrupts.disable("blocked")
    a = s.decide("move(right)")
    # the walk does not stand against the wall for the rest of the decision: it ends by itself
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "blocked")
    assert a["stop"]["frames"] < 100
    # and a second one, already against the wall, is over after the frames it takes to feel it
    assert s.decide("move(right)")["stop"]["frames"] == STALL_FRAMES


def test_a_creature_walking_into_view_interrupts_once(
    game_at: Callable[[int], Game], make_session: Make
) -> None:
    game = game_at(WALL_X + 20)
    game.spawn_enemy("longleg", WALL_X + 20 + 150, GROUND)  # beyond the 128 cells of view
    s = make_session(game)
    assert all(e["kind"] != "longleg" for e in s.observe()["observation"]["state"]["nearby"])
    a = s.decide(f"walk_to(x={WALL_X + 80})")
    assert a["stop"]["detail"] == "new_enemy", a["stop"]
    assert "longleg" in a["stop"]["message"]
    b = s.decide("wait(ticks=1)")
    assert b["stop"].get("detail") != "new_enemy"


def test_damage_interrupts_and_is_listed_in_the_events(game: Game, make_session: Make) -> None:
    game.spawn_enemy("longleg", START_X + 18, GROUND)
    s = make_session(game)
    a = s.decide("wait(ticks=25)")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("interrupted", "damage")
    hurt = [e for e in a["events"] if e["type"] == "damage" and e["target"] == "player"]
    assert hurt and hurt[0]["text"].startswith("You took")
    assert a["stop"]["frames"] % 10 == 0


def test_drinking_something_new_stops_the_drink_with_a_status(
    game: Game, make_session: Make
) -> None:
    game.give_bottle("oil", 400)
    s = make_session(game)
    a = s.decide("drink(amount=400)")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("interrupted", "status_change")
    assert "oiled" in a["stop"]["message"]
    assert a["stop"]["ticks"] < 4  # the whole bottle would have taken four ticks


def test_a_command_that_finishes_wins_over_an_interrupt(game: Game, make_session: Make) -> None:
    game.give_bottle("oil", 400)
    s = make_session(game)
    a = s.decide("drink(amount=50)")  # done within the first tick, which also brings 'oiled'
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "done")
    assert any(e["type"] == "status" for e in a["events"])


def test_fell_in_liquid_is_off_by_default_and_works_when_enabled(
    game_at: Callable[[int], Game], make_session: Make
) -> None:
    s = make_session(game_at(POOL_X - 12))
    s.interrupts.enable("fell_in_liquid")
    s.interrupts.disable("status_change")
    a = s.decide("jump(right)")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("interrupted", "fell_in_liquid")
    s2 = make_session(game_at(POOL_X - 12))
    s2.interrupts.disable("status_change")
    b = s2.decide("jump(right)")
    assert b["stop"]["detail"] != "fell_in_liquid"


def test_new_material_interrupts_when_the_view_reaches_something_new(
    game_at: Callable[[int], Game], make_session: Make
) -> None:
    s = make_session(game_at(WALL_X + 20))
    s.interrupts.enable("new_material")
    s.decide("wait")  # learns what is in view
    a = s.decide(f"walk_to(x={PIT_X - 15})")
    assert a["stop"]["detail"] == "new_material", a["stop"]
    assert "You see" in a["stop"]["message"]


def test_hp_low_interrupts_when_the_threshold_is_crossed(game: Game, make_session: Make) -> None:
    game.give_bottle("acid", 400)
    s = make_session(game)
    s.interrupts.disable("damage")
    s.interrupts.enable("hp_low", hp_below=95)
    a = s.decide("drink(amount=400)")
    assert a["stop"]["detail"] == "hp_low"
