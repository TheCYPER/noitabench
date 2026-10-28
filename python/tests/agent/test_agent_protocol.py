"""The JSON Lines protocol, the tool calls and the command line: all drive one game one way."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_worlds import GROUND, Arena, settle, write_arena
from noitabench.agent import AgentSession, SessionConfig, ViewConfig, call_tool
from noitabench.agent.mcp_adapter import tool_payload
from noitabench.agent.protocol import handle_line, serve
from noitabench.agent.recorder import digest

DECISIONS = [
    ("walk_to", {"x": 44}),
    ("pickup", {}),
    ("inspect", {"spell": 0}),
    ("move", {"direction": "right", "ticks": 4}),
    ("aim", {"angle": 30}),
    ("fire", {"ticks": 3}),
    ("jump", {"direction": "right"}),
    ("walk_to", {"x": "far"}),  # invalid
]


def make(tmp_path: Path, name: str, **view: Any) -> AgentSession:
    arena: Arena = write_arena(tmp_path / name)
    game = arena.game(seed=2)
    settle(game)
    game.spawn_enemy("longleg", 100, GROUND)
    return AgentSession(game, config=SessionConfig(view=ViewConfig(**view)))


def digests(answers: list[dict[str, Any]]) -> list[str]:
    # the protocol adds `ok`, `id` and `text` to an answer; the rest is the answer
    return [digest({k: v for k, v in a.items() if k not in ("ok", "id", "text")}) for a in answers]


def test_the_first_line_is_hello_with_the_tools_and_the_first_observation(tmp_path: Path) -> None:
    out = io.StringIO()
    serve(make(tmp_path, "a"), [], out)
    first = json.loads(out.getvalue().splitlines()[0])
    assert first["op"] == "hello" and first["protocol"] == "cogbench-agent/0"
    assert (first["tick_frames"], first["max_command_frames"], first["max_decisions"]) == (
        10,
        300,
        1000,
    )
    assert [t["name"] for t in first["tools"]][:3] == ["move", "walk_to", "jump"]
    assert first["decision"] == 1 and first["stop"]["reason"] == "start"
    assert "Decision 1" in first["text"] and set(first["observation"]) == {"state", "map"}


def test_requests_in_all_their_forms_are_answered_in_order(tmp_path: Path) -> None:
    lines = [
        json.dumps({"id": 1, "commands": [{"name": "walk_to", "args": {"x": 40}}]}),
        json.dumps({"id": "two", "text": "aim(angle=20); fire(ticks=2)"}),
        json.dumps({"id": 3, "command": "inspect", "args": {"bottle": 0}}),
        "wait(ticks=2)",  # a line that is not JSON is text
        "",
        json.dumps({"id": 5, "op": "observe"}),
        json.dumps({"id": 6, "op": "tools"}),
        json.dumps({"id": 7, "op": "close"}),
        json.dumps({"id": 8, "text": "wait"}),  # after close: never read
    ]
    out = io.StringIO()
    summary = serve(make(tmp_path, "a"), lines, out)
    answers = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [a.get("id") for a in answers] == [None, 1, "two", 3, None, 5, 6, 7]
    _hello, walk, aimfire, inspect, text, observe, tools, closed = answers
    assert walk["ok"] and walk["stop"]["detail"] == "reached" and walk["decision"] == 2
    assert aimfire["ok"] and [r["command"] for r in aimfire["results"]] == ["aim", "fire"]
    assert not inspect["ok"] and inspect["stop"]["code"] == "no_such_bottle"
    assert text["ok"] and text["stop"]["ticks"] == 2
    assert observe["decision"] == text["decision"] and observe["stop"] == text["stop"]
    assert len(tools["tools"]) >= 20 and closed["op"] == "closed"
    assert summary["decisions"] == 4 and closed["summary"]["decisions"] == 4


def test_unreadable_requests_get_an_error_and_are_not_decisions(tmp_path: Path) -> None:
    s = make(tmp_path, "a")
    cases = {
        "{not json": "not valid JSON",
        '{"id": 1}': "needs one of",
        '{"id": 2, "op": "dance"}': "unknown op",
    }
    for line, needle in cases.items():
        answer = handle_line(s, line)
        assert answer is not None and answer["ok"] is False
        assert needle in answer["error"]["message"] and answer["error"]["code"] == "bad_request"
    assert s.decisions == 0
    # a line that does not start with `{` is text; text that is no command is an invalid decision
    text_answer = handle_line(s, "[1, 2]")
    assert text_answer is not None and text_answer["stop"]["reason"] == "invalid"
    assert s.decisions == 1


def test_protocol_tool_calls_and_the_api_give_the_same_game(tmp_path: Path) -> None:
    api = make(tmp_path, "api")
    tools = make(tmp_path, "tools")
    proto = make(tmp_path, "proto")
    by_api = [api.observe(), *(api.decide([{"name": n, "args": a}]) for n, a in DECISIONS)]
    by_tools = [tools.observe(), *(call_tool(tools, n, a) for n, a in DECISIONS)]
    lines = [json.dumps({"id": i, "command": n, "args": a}) for i, (n, a) in enumerate(DECISIONS)]
    out = io.StringIO()
    serve(proto, lines, out)
    by_proto = [json.loads(x) for x in out.getvalue().splitlines()]
    first = {k: v for k, v in by_proto[0].items() if k in by_api[0]}  # hello: the first answer
    by_proto = [first, *by_proto[1:]]
    assert digests(by_api) == digests(by_tools) == digests(by_proto)
    assert api.state_hash() == tools.state_hash() == proto.state_hash()
    assert api.frame == tools.frame == proto.frame


def test_text_requests_equal_dict_requests(tmp_path: Path) -> None:
    a, b = make(tmp_path, "a"), make(tmp_path, "b")
    ra = a.decide("aim(target=longleg); fire(until=target_dead)")
    rb = b.decide(
        [
            {"name": "aim", "args": {"target": "longleg"}},
            {"name": "fire", "args": {"until": {"target_dead": True}}},
        ]
    )
    assert ra == rb and a.state_hash() == b.state_hash()


def test_the_tool_payload_of_an_mcp_call_has_text_and_an_image(tmp_path: Path) -> None:
    s = make(tmp_path, "a", screenshot=True)
    payload = tool_payload(s, "walk_to", {"x": 40})
    assert (
        payload["text"].startswith("Decision 2")
        and payload["answer"]["stop"]["detail"] == "reached"
    )
    assert payload["image_png"][:8] == b"\x89PNG\r\n\x1a\n"
    plain = tool_payload(make(tmp_path, "b"), "kick", {})
    assert plain["image_png"] is None
    bad = tool_payload(make(tmp_path, "c"), "walk_to", {"x": "far"})
    assert bad["answer"]["stop"]["code"] == "bad_argument"
    unknown = call_tool(make(tmp_path, "d"), "dance")
    assert unknown["stop"]["code"] == "unknown_command" and unknown["decision"] == 2


# -- the command line -------------------------------------------------------------------------------


def run_cli(args: list[str], stdin: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONHASHSEED": "random"}
    return subprocess.run(
        [sys.executable, "-m", "noitabench", "agent", "play", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


def test_the_command_line_serves_an_episode_and_records_it(tmp_path: Path) -> None:
    arena = write_arena(tmp_path / "w")
    out = tmp_path / "run"
    stdin = "\n".join(
        [
            json.dumps({"id": 1, "text": "walk_to(x=50)"}),
            json.dumps({"id": 2, "commands": [{"name": "wait", "args": {"ticks": 3}}]}),
            json.dumps({"id": 3, "op": "close"}),
        ]
    )
    done = run_cli(
        ["--world-files", str(arena.png), str(arena.json), "--out", str(out), "--game-seed", "4"],
        stdin,
    )
    assert done.returncode == 0, done.stderr
    answers = [json.loads(x) for x in done.stdout.splitlines()]  # stdout is JSON lines only
    assert [a.get("op") or a["id"] for a in answers] == ["hello", 1, 2, "closed"]
    assert answers[1]["stop"]["detail"] == "reached" and answers[2]["stop"]["ticks"] == 3
    assert "episode finished" in done.stderr
    lines = (out / "decisions.jsonl").read_text().splitlines()
    assert [json.loads(x)["index"] for x in lines] == [1, 2]
    assert (out / "meta.json").exists() and (out / "frames.bin").stat().st_size > 0
    meta = json.loads((out / "meta.json").read_text())
    assert meta["seed"] == 4 and meta["rule_seed"] == 5  # the rule seed of the world file


def test_the_command_line_switches_channels_and_needs_a_world(tmp_path: Path) -> None:
    arena = write_arena(tmp_path / "w")
    done = run_cli(
        [
            "--world-files",
            str(arena.png),
            str(arena.json),
            "--no-ascii",
            "--screenshot",
            "--no-text",
        ],
        json.dumps({"op": "close"}),
    )
    hello = json.loads(done.stdout.splitlines()[0])
    assert set(hello["observation"]) == {"screenshot"}
    none = run_cli([], "")
    assert none.returncode != 0 and "exactly one of --world-seed and --world-files" in none.stderr


def test_agent_is_registered_in_the_cli() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "noitabench", "--help"], capture_output=True, text=True, check=False
    )
    assert "agent" in out.stdout
    helped = subprocess.run(
        [sys.executable, "-m", "noitabench", "agent", "play", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert helped.returncode == 0 and "--world-seed" in helped.stdout
