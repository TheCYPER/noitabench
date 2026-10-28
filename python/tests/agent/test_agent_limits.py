"""The size and the price of a decision, the one range of sight, and the small rules of the
grammar and the runner that the batch D1b decisions added."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agent_worlds import GROUND, START_X, WALL_X
from noitabench.agent import AgentSession, SessionConfig, ViewConfig
from noitabench.agent.engine import Engine
from noitabench.agent.errors import CommandError
from noitabench.agent.grammar import parse_decision
from noitabench.agent.vocab import MAX_COMMANDS, STALL_FRAMES
from noitabench.game import Game

Make = Callable[..., AgentSession]


# -- at most four commands, and what a decision costs -----------------------------------------------


def test_a_decision_holds_four_commands_and_no_more(session: AgentSession) -> None:
    frame = session.frame
    four = session.decide("aim(angle=10); aim(angle=20); aim(angle=30); aim(angle=40)")
    assert four["stop"]["reason"] != "invalid" and len(four["results"]) == MAX_COMMANDS == 4
    five = session.decide("kick; kick; kick; kick; kick")
    assert five["stop"]["reason"] == "invalid" and five["stop"]["code"] == "too_many_commands"
    assert five["stop"]["frames"] == 0 and "at most 4" in five["stop"]["message"]
    assert session.frame == frame, "nothing ran"
    assert five["decisions_left"] == 1000 - 2  # but it was a decision
    listed = session.decide([{"name": "kick"}] * 5)
    assert listed["stop"]["code"] == "too_many_commands"


def test_the_hello_line_tells_the_limit(session: AgentSession) -> None:
    from noitabench.agent.protocol import hello

    assert hello(session)["max_commands_per_decision"] == 4


@pytest.mark.parametrize(
    ("text", "cost"),
    [
        ("kick", 1),
        ("aim(angle=10)", 1),
        ("inspect(x=40, y=170)", 1),
        ("inspect(x=40, y=170); inspect(x=41, y=170)", 2),
        ("kick; inspect(x=40, y=170)", 2),
        ("kick; inspect(x=40, y=170); inspect(x=41, y=170)", 3),
        ("inspect(x=40, y=170); aim(angle=3); inspect(wand=0); inspect(spell=0)", 4),
        ("aim(angle=3); memory_list", 1),
        ("inspect(entity=999)", 1),  # a look that fails still counts as a look
        ("wait(ticks=2); aim(angle=3); memory_list", 1),
        ("inspect(x=40, y=170); kick; kick; kick", 2),
    ],
)
def test_each_inspect_beyond_the_first_costs_a_decision(
    game: Game, make_session: Make, text: str, cost: int
) -> None:
    game.give_spell("DAMAGE")
    s = make_session(game, max_decisions=100)
    a = s.decide(text)
    assert 100 - a["decisions_left"] == cost, a["results"]
    assert s.decisions == cost


def test_commands_that_were_skipped_cost_nothing(game: Game, make_session: Make) -> None:
    s = make_session(game, max_decisions=100)
    a = s.decide("walk_to(x=4000); inspect(x=40, y=170); inspect(x=41, y=170)")
    assert a["results"][0]["ok"] is False  # the invalid one is found before anything runs
    assert s.decisions == 1
    a = s.decide(f"walk_to(x={WALL_X - 15}); move(right); inspect(wand=0); inspect(wand=1)")
    # the walk was stopped by the wall, so the inspects were never run
    assert [r.get("code") for r in a["results"][2:]] == ["skipped", "skipped"]
    assert s.decisions == 2


def test_the_budget_counts_what_a_decision_costs_and_ends_the_run(
    game: Game, make_session: Make, tmp_path: Path
) -> None:
    s = AgentSession(
        game,
        config=SessionConfig(max_decisions=4, view=ViewConfig()),
        recording_dir=tmp_path / "rec",
    )
    first = s.decide("inspect(wand=0); inspect(wand=1); inspect(spell=0)")  # no spell 0: still 3
    assert first["decisions_left"] == 1
    a = s.decide("kick; inspect(wand=0); inspect(wand=1)")  # costs 3, only 1 left: it still runs
    assert a["decisions_left"] == 0 and a["over"] == "decision_limit"
    assert s.decide("kick")["stop"]["reason"] == "over"
    s.close()
    lines = [json.loads(x) for x in (tmp_path / "rec" / "decisions.jsonl").read_text().splitlines()]
    assert [(x["index"], x["cost"]) for x in lines] == [(3, 3), (6, 3)]


# -- an interrupt on the tick a command completes is told ---------------------------------------------


def test_an_interrupt_on_the_tick_a_command_completes_is_reported_not_swallowed(
    game: Game, make_session: Make
) -> None:
    game.give_bottle("potion_haste", 100)
    s = make_session(game)
    a = s.decide("drink(amount=10)")  # done in one frame; the new condition fires on the tick
    stop = a["stop"]
    assert (stop["reason"], stop["detail"]) == ("completed", "done")
    assert stop["also"] == ["status_change"]


def test_a_completion_without_an_interrupt_has_no_also(session: AgentSession) -> None:
    assert "also" not in session.decide("wait(ticks=2)")["stop"]


# -- walking ends at a wall by itself ----------------------------------------------------------------------


def test_walking_into_a_wall_ends_by_itself_with_the_interrupt_off(
    game: Game, make_session: Make
) -> None:
    s = make_session(game)
    s.interrupts.disable("blocked")
    s.decide(f"walk_to(x={WALL_X - 15})")
    a = s.decide("move(right)")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "blocked")
    assert a["stop"]["frames"] < 100
    b = s.decide(f"walk_to(x={WALL_X + 40})")
    assert (b["stop"]["reason"], b["stop"]["detail"]) == ("completed", "blocked")
    assert b["stop"]["frames"] == STALL_FRAMES, "already at the wall: it takes a tick to feel it"
    # with the interrupt on it is still an interrupt
    s.interrupts.enable("blocked")
    assert s.decide("move(right)")["stop"]["reason"] == "interrupted"


# -- `none` is a direction ---------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["jump(none)", "fly(none)", "jump(NONE)", "jump(direction=none)"])
def test_none_is_a_direction_for_jump_and_fly(text: str) -> None:
    (command,) = parse_decision(text)
    assert command.args["direction"] == "up"


def test_none_is_not_a_direction_for_walking() -> None:
    with pytest.raises(CommandError):
        parse_decision("move(none)")


def test_jump_none_runs(session: AgentSession) -> None:
    a = session.decide("jump(none)")
    assert a["results"][0]["ok"] and a["stop"]["reason"] == "completed"


# -- one range of sight ---------------------------------------------------------------------------------


def fake(kind: str, x: int, y: int) -> dict[str, Any]:
    return {"id": 9000 + x + y, "kind": kind, "x": x, "y": y, "w": 4, "h": 4, "detail": ""}


def test_creatures_and_cells_are_seen_inside_the_extent_of_the_map(session: AgentSession) -> None:
    engine: Engine = session.engine
    p = engine.player()
    assert engine.view_half == (128, 64)
    cx, cy = p["hit"][0] + p["hit"][2] // 2, p["hit"][1] + p["hit"][3] // 2
    near = fake("longleg", cx + 120, GROUND - 4)  # inside, and in the open
    wide = fake("longleg", cx + 140, GROUND - 4)
    assert [e["id"] for e in engine.visible(p, [near, wide])] == [near["id"]]
    assert not engine.in_view(p, cx + 129, cy) and engine.in_view(p, cx + 128, cy)
    assert engine.in_view(p, cx, cy - 64) and not engine.in_view(p, cx, cy - 65)
    assert not engine.sees_point(p, cx + 130, cy)


def test_inspect_a_cell_reaches_as_far_as_the_map_and_no_further(session: AgentSession) -> None:
    ok = session.decide(f"inspect(x={START_X + 120}, y={GROUND + 3})")
    assert ok["results"][0]["ok"]
    far = session.decide(f"inspect(x={START_X + 150}, y={GROUND + 3})")
    assert far["stop"]["code"] == "out_of_sight"


def test_a_smaller_map_means_a_shorter_sight(game: Game, make_session: Make) -> None:
    game.spawn_enemy("longleg", START_X + 80, GROUND)
    wide = make_session(game)
    assert any(e["kind"] == "longleg" for e in wide.observe()["observation"]["state"]["nearby"])
    narrow = make_session(game, ascii_cols=32, ascii_rows=16)  # 128 x 64 cells: +-64 x +-32
    assert narrow.engine.view_half == (64, 32)
    assert not any(
        e["kind"] == "longleg" for e in narrow.observe()["observation"]["state"]["nearby"]
    )


def test_events_are_noticed_inside_the_same_range(game_at: Callable[[int], Game]) -> None:
    from noitabench.agent.events import EventCollector

    c = EventCollector((128, 64))
    player = {"x": 100, "y": 100, "w": 4, "h": 7, "wands": []}
    boom = {"type": "explosion", "frame": 1, "x": 100 + 150, "y": 105, "radius": 10}
    assert c.add_tick(1, [boom], player, set()) == []  # beyond the view: not noticed
    near = {**boom, "x": 100 + 100}
    assert len(c.add_tick(1, [near], player, set())) == 1
    tall = {**boom, "x": 102, "y": 105 + 70}
    assert c.add_tick(1, [tall], player, set()) == []


# -- the engine's own on_ground is used ---------------------------------------------------------------------


def test_on_ground_is_the_games_own_and_follows_a_jump(game: Game, make_session: Make) -> None:
    s = make_session(game)
    a = s.decide("jump(up)")
    assert a["stop"]["detail"] == "landed"
    assert s.engine.player()["on_ground"] is True
    assert s.engine.player()["on_ground"] == game.player()["on_ground"]
    assert a["observation"]["state"]["on_ground"] is True
