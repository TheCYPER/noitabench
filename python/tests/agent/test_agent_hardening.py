"""Things an agent (or a plugin it wrote) can send or cause that must never crash a run, and
things that must not give away what is out of sight."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from agent_worlds import GROUND, WALL_W, WALL_X, write_arena
from noitabench.agent import AgentSession, CommandError, parse_decision
from noitabench.agent.cli import open_game
from noitabench.agent.events import EventCollector
from noitabench.agent.protocol import handle_line, serve
from noitabench.agent.tools import call_tool, coerce_request
from noitabench.game import Game

Make = Callable[..., AgentSession]

PLAYER = {"x": 98, "y": 94, "w": 4, "h": 7, "wands": []}  # stands at (100, 100)


# -- requests that cannot be read are answers, not crashes -----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "walk_to(x=1)\x00",
        "\x00",
        "walk_to(x=" + "-" * 3000 + "1)",
        "aim(angle=" + "+" * 20_000 + "1)",
        "-" * 15_000 + "1",
        "wait(until=" + "{'a':" * 190 + "1" + "}" * 190 + ")",
    ],
)
def test_text_the_parser_cannot_take_is_a_syntax_error(text: str) -> None:
    with pytest.raises(CommandError) as err:
        parse_decision(text)
    assert err.value.code in ("syntax", "bad_argument")


def test_a_hostile_request_is_an_invalid_decision_that_costs_no_time(session: AgentSession) -> None:
    frame = session.frame
    nested: Any = {"x": 1}
    for _ in range(3000):
        nested = {"commands": nested}
    for request in ("\x00", "kick\x00", nested, {"name": "wait", "args": _deep_list(3000)}):
        answer = session.decide(request)
        assert answer["stop"]["reason"] == "invalid" and answer["stop"]["frames"] == 0
        assert len(json.dumps(answer["stop"])) < 400  # the message does not echo the request
    assert session.frame == frame and session.decisions == 4


def _deep_list(depth: int) -> Any:
    out: Any = []
    for _ in range(depth):
        out = [out]
    return out


def test_a_deeply_nested_tool_call_or_request_is_refused(session: AgentSession) -> None:
    with pytest.raises(CommandError):
        coerce_request(_deep_list(5000))
    answer = call_tool(session, "wait", {"until": _deep_list(5000)})
    assert answer["stop"]["reason"] == "invalid"


def test_the_protocol_answers_nesting_that_json_cannot_read_with_bad_request(
    session: AgentSession,
) -> None:
    line = '{"commands": ' + "[" * 100_000 + "]" * 100_000 + "}"
    answer = handle_line(session, line)
    assert answer is not None and answer["ok"] is False
    assert answer["error"]["code"] == "bad_request" and session.decisions == 0
    assert handle_line(session, "\x00")["stop"]["reason"] == "invalid"  # type: ignore[index]
    assert session.decisions == 1


def test_an_unknown_name_is_not_echoed_whole(session: AgentSession) -> None:
    answer = session.decide({"name": "x" * 5000, "args": {}})
    assert answer["stop"]["reason"] == "invalid"
    assert len(answer["results"][0]["command"]) <= 40
    assert len(json.dumps(answer["stop"])) < 500


def test_the_failed_command_is_named_not_the_first_one(session: AgentSession) -> None:
    frame = session.frame
    for request, culprit in (
        ("kick; bogus()", "bogus"),
        ("wait(ticks=2); walk_to(x='far'); kick", "walk_to"),
        ("kick; drop()", "drop"),  # nothing runs before a command that cannot be done
        ({"commands": [{"name": "kick"}, {"name": "nope"}]}, "nope"),
        ([{"name": "kick"}, "wait(ticks=0)"], "wait"),
        ("kick;;(", "?"),
    ):
        answer = session.decide(request)
        (result,) = answer["results"]
        assert answer["stop"]["reason"] == "invalid" and answer["stop"]["frames"] == 0, request
        assert (result["command"], result["ok"]) == (culprit, False), request
    assert session.frame == frame


# -- the session is closed even when the server dies ------------------------------------------------


def test_serve_finishes_the_recording_when_the_reader_fails(game: Game, tmp_path: Path) -> None:
    out = tmp_path / "rec"
    session = AgentSession(game, recording_dir=out)

    def lines() -> Iterator[str]:
        yield "kick"
        raise RuntimeError("the pipe broke")

    with pytest.raises(RuntimeError, match="pipe"):
        serve(session, lines(), io.StringIO())
    assert (out / "meta.json").exists()
    assert json.loads((out / "decisions.jsonl").read_text().splitlines()[0])["index"] == 1
    session.close()  # a second close is harmless


# -- old world files --------------------------------------------------------------------------------


def test_a_world_file_with_a_perturbation_strength_still_opens(tmp_path: Path) -> None:
    arena = write_arena(tmp_path / "old")
    doc = json.loads(arena.json.read_text())
    doc["strength"] = 2  # worlds before the reaction table became fixed carried this
    arena.json.write_text(json.dumps(doc))
    session = AgentSession(open_game(arena.png, arena.json))
    assert session.decide("wait")["stop"]["reason"] == "completed"


# -- what happens out of sight is not told ---------------------------------------------------------


def hurt(frame: int = 5) -> list[dict[str, Any]]:
    return [
        {"frame": frame, "type": "damage", "target": "longleg", "id": 7, "amount": 2.0},
        {"frame": frame, "type": "death", "target": "longleg", "id": 7, "source": "fire"},
        {"frame": frame, "type": "explosion", "radius": 9, "destroyed": 3},
    ]


def with_place(raw: list[dict[str, Any]], x: int) -> list[dict[str, Any]]:
    return [{**r, "x": x, "y": 100, "hp": 0.0, "source": r.get("source", "fire")} for r in raw]


def test_events_about_a_creature_out_of_sight_are_dropped_the_rest_stay() -> None:
    c = EventCollector()
    seen = []

    def sees(x: float, y: float) -> bool:
        seen.append((x, y))
        return x < 120  # a wall at 120

    c.add_tick(1, with_place(hurt(), 150), PLAYER, set(), sees)
    events, _ = c.summary(16)
    assert [e["type"] for e in events] == ["explosion"]  # the blast is heard, the creature is not
    assert seen == [(150, 100), (150, 100)]
    c2 = EventCollector()
    c2.add_tick(1, with_place(hurt(), 110), PLAYER, set(), sees)
    assert [e["type"] for e in c2.summary(16)[0]] == ["damage", "death", "explosion"]


def test_without_a_sight_test_creature_events_in_range_are_kept() -> None:
    c = EventCollector()
    c.add_tick(1, with_place(hurt(), 150), PLAYER, set())
    assert len(c.summary(16)[0]) == 3


def test_the_runner_hides_a_death_behind_a_wall(game_at: Callable[[int], Game], make_session: Make):  # type: ignore[no-untyped-def]
    game = game_at(WALL_X - 20)
    s = make_session(game)
    hidden = game.spawn_enemy("longleg", WALL_X + WALL_W + 12, GROUND)
    nearby = s.observe()["observation"]["state"]["nearby"]
    assert all(e["id"] != hidden for e in nearby)  # the wall hides it
    game.blast(WALL_X + WALL_W + 12, GROUND, 14, 100.0)  # a blast on the far side kills it
    answer = s.decide("wait")
    kinds = {(e["type"], e.get("id")) for e in answer["events"]}
    assert ("death", hidden) not in kinds and ("damage", hidden) not in kinds
    assert "longleg" not in json.dumps(answer["events"])


def test_the_aim_does_not_follow_a_creature_out_of_sight(
    game_at: Callable[[int], Game], make_session: Make
) -> None:
    game = game_at(WALL_X - 20)
    s = make_session(game)
    hidden = game.spawn_enemy("longleg", WALL_X + WALL_W + 30, GROUND)  # behind the wall
    state = s.observe()["observation"]["state"]
    assert all(e["id"] != hidden for e in state["nearby"]), "the wall should hide the creature"
    s.decide("aim(angle=45)")
    s.aim.set_entity(hidden)  # as if it had been in view when it was aimed at
    answer = s.decide("wait(ticks=3)")
    aim = answer["observation"]["state"]["aim"]
    assert aim["degrees"] == 45.0  # the angle of the last sight, not the way to the creature
    assert aim["follows"] == hidden


def test_the_aim_follows_a_creature_in_sight(session: AgentSession, game: Game) -> None:
    foe = game.spawn_enemy("longleg", 100, GROUND - 25)  # up and to the right, in plain view
    visible = {e["id"] for e in session.observe()["observation"]["state"]["nearby"]}
    assert foe in visible
    session.decide(f"aim(entity={foe})")
    answer = session.decide("wait(ticks=1)")
    assert answer["observation"]["state"]["aim"]["degrees"] > 10  # it points up at the creature


# -- merged counts stay counts -----------------------------------------------------------------------


def test_merged_casts_keep_whole_numbers_of_projectiles() -> None:
    c = EventCollector()
    raw = [
        {"frame": f, "type": "cast", "wand": 2, "spells": "LIGHT_BULLET", "projectiles": 1}
        for f in range(4)
    ]
    c.add_tick(1, [{**r, "mana": 5.0} for r in raw], {**PLAYER, "wands": [{"id": 2}]}, set())
    (e,), _ = c.summary(16)
    assert e["projectiles"] == 4 and isinstance(e["projectiles"], int)


def test_events_from_before_the_session_are_not_told(
    game: Game, game_at: Callable[[int], Game], make_session: Make
) -> None:
    twin = game_at(30)  # the same world; its pending events are what the session must drop
    for g in (game, twin):
        g.step(10, {"fire": True})  # a shot before the agent layer took over
    assert any(e["type"] == "cast" for e in twin.events())
    answer = make_session(game).decide("wait")
    assert not any(e["type"] == "cast" for e in answer["events"])
