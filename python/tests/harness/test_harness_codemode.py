"""L2, Code Mode: a program that plays for the player, in the box."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_worlds import GROUND, START_X
from noitabench.agent.visibility import leaks
from noitabench.harness.layers import DEFAULT_LAYERS
from noitabench.harness.sandbox import Limits, sandbox_available
from rig import arena_game, make_rig

pytestmark = pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")


@pytest.fixture
def rig(tmp_path: Path):
    return make_rig(tmp_path / "rig")


def test_a_program_plays_and_each_game_call_is_one_step(rig) -> None:
    code = (
        "a = game.walk_to(x=60)\n"
        "print(a['stop']['reason'], a['stop']['detail'])\n"
        "b = game.move(direction='right', ticks=2)\n"
        "print(b['ok'], b['decision'])\n"
        "print(game.observe()['decision'])\n"
    )
    result = rig.call("run_code", code=code)
    assert not result.is_error, result.content
    assert rig.decisions == 2  # two commands; observe is free
    text = result.content
    assert text.startswith("The program finished.")
    assert "completed reached" in text and "True 3" in text
    assert "Game commands run: 2. Steps used: 2." in text
    assert "The last command stopped: completed (ticks)." in text
    assert "Decision 3 (frame" in text  # the view after the last command is part of the result


def test_inspect_and_the_four_command_rule_are_charged_like_the_tool_calls(rig) -> None:
    code = (
        "game.inspect(x=60, y=159)\n"  # one step
        "game.decide('aim(angle=10); kick; aim(angle=20); kick')\n"  # four commands, one step
        "game.decide('inspect(x=60, y=159); inspect(x=61, y=159)')\n"  # two looks, two steps
    )
    result = rig.call("run_code", code=code)
    assert not result.is_error, result.content
    assert rig.decisions == 1 + 1 + 2
    assert "Game commands run: 7. Steps used: 4." in result.content  # seven commands count


def test_invalid_commands_cost_a_step_and_come_back_as_answers(rig) -> None:
    code = "a = game.walk_to(x='left')\nprint(a['ok'], a['stop']['reason'])\nprint(a['text'][:40])"
    result = rig.call("run_code", code=code)
    assert not result.is_error
    assert "False invalid" in result.content
    assert rig.decisions == 1


def test_the_program_stops_after_two_hundred_game_commands(rig) -> None:
    code = (
        "n = 0\n"
        "try:\n"
        "    while True:\n"
        "        game.wait(ticks=1)\n"
        "        n += 1\n"
        "except game.LimitReached as e:\n"
        "    print('stopped after', n, '|', e)\n"
        "game.observe()\n"  # looking is still allowed
    )
    result = rig.call("run_code", code=code)
    assert "stopped after 200 |" in result.content and "At most 200" in result.content
    assert rig.decisions == 200
    # the same limit ends a program that does not catch it
    again = rig.call("run_code", code="while True:\n    game.wait(ticks=1)")
    assert again.is_error and "LimitReached" in again.content and "At most 200" in again.content
    assert rig.decisions == 400


def test_a_four_command_step_counts_four_against_the_limit(rig) -> None:
    code = "for i in range(60):\n    game.decide('kick; aim(angle=1); kick; aim(angle=2)')"
    result = rig.call("run_code", code=code)
    assert "LimitReached" in result.content
    assert "Game commands run: 200." in result.content  # 50 steps of four


def test_the_program_stops_when_the_game_ends(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "short", max_decisions=5)
    code = (
        "count = 0\n"
        "try:\n"
        "    while True:\n"
        "        game.wait(ticks=1)\n"
        "        count += 1\n"
        "except game.GameOver as over:\n"
        "    print('over after', count, over.answer['over'])\n"
        "    raise\n"
    )
    result = rig.call("run_code", code=code)
    assert rig.session.over and rig.decisions == 5
    assert "The game ended while it was running (decision_limit)." in result.content
    assert "over after 4 decision_limit" in result.content  # the fifth call raised
    assert not result.is_error or "GameOver" not in result.content.split("It printed")[0]
    assert "The game is over: decision_limit." in result.content  # the view says so too


def test_an_error_in_the_program_is_reported_with_its_own_lines(rig) -> None:
    result = rig.call("run_code", code="x = 1\ngame.wait(ticks=1)\nraise ValueError('boom')\n")
    assert result.is_error and rig.decisions == 1
    assert result.content.startswith("The program stopped with an error.")
    assert 'File "<run_code>", line 3' in result.content and "ValueError: boom" in result.content
    # what it did before the error still happened, and the view says where things stand
    assert "Game commands run: 1." in result.content and "Decision 2" in result.content


def test_a_program_that_does_not_play_returns_no_view(rig) -> None:
    result = rig.call("run_code", code="print(sum(range(10)))")
    assert result.content == "The program finished.\nIt printed:\n45"
    assert rig.decisions == 0


def test_empty_or_oversized_programs_are_refused_before_they_run(rig) -> None:
    for code in ("", "   \n", None, 12):
        assert rig.call("run_code", code=code).content.startswith("bad_argument")
    huge = rig.call("run_code", code="x = 1\n" * 5_000)
    assert huge.content.startswith("bad_argument") and "too long" in huge.content
    assert rig.decisions == 0


def test_numpy_and_scipy_are_available(rig) -> None:
    code = (
        "import numpy as np, scipy.linalg\n"
        "print(int(np.linalg.det(np.eye(3)) * 10), round(float(scipy.linalg.norm([3, 4])), 1))\n"
    )
    assert "It printed:\n10 5.0" in rig.call("run_code", code=code).content


def test_the_notebook_is_available_and_its_quota_applies(rig) -> None:
    code = (
        "notes.write('notes/a.md', 'lava is hot')\n"
        "print(notes.read('notes/a.md')['text'])\n"
        "print(notes.search('lava')['hits'][0]['path'])\n"
        "notes.edit('notes/a.md', 'hot', 'very hot')\n"
        "notes.write('scripts/s.py', 'print(1)')\n"
        "print([f['path'] for f in notes.list()['files']])\n"
        "try:\n"
        "    notes.write('notes/big.md', 'x' * 9000)\n"
        "except notes.NotesError as e:\n"
        "    print('refused:', str(e)[:40])\n"
        "try:\n"
        "    notes.read('../escape')\n"
        "except notes.NotesError as e:\n"
        "    print('refused:', str(e)[:20])\n"
        "notes.delete('notes/a.md')\n"
    )
    result = rig.call("run_code", code=code)
    assert not result.is_error, result.content
    assert "lava is hot" in result.content and "notes/a.md" in result.content
    assert "refused: notes_full: No room: notes and" in result.content
    assert "refused: bad_path" in result.content
    assert rig.workspace.file_names() == ["scripts/s.py"]
    assert rig.decisions == 0  # notes cost nothing


def test_the_program_sees_only_what_an_agent_sees(rig) -> None:
    code = (
        "import json\n"
        "a = game.observe()\n"
        "print(sorted(a['observation']))\n"
        "b = game.inspect(x=60, y=159)\n"
        "dump = json.dumps([a, b])\n"
        "for word in ('rule_seed', 'must_pass', 'encounter_id', 'placeholder', 'E99', 'recipe'):\n"
        "    print(word, word in dump)\n"
        "print([n for n in dir(game) if not n.startswith('_')])\n"
        "for name in ('noitabench', 'noitabench_core', 'noitabench.game'):\n"
        "    try:\n"
        "        __import__(name)\n"
        "        print(name, 'IMPORTED')\n"
        "    except ImportError:\n"
        "        print(name, 'not available')\n"
        "import sys, gc\n"
        "print(any(type(o).__name__ in ('Game', 'AgentSession', 'Engine') for o in gc.get_objects()))\n"
    )
    result = rig.call("run_code", code=code)
    assert not result.is_error, result.content
    for word in ("rule_seed", "must_pass", "encounter_id", "placeholder", "E99", "recipe"):
        assert f"{word} False" in result.content
    assert "IMPORTED" not in result.content and "noitabench_core not available" in result.content
    assert "False\n" in result.content.split("not available")[-1][:30]  # no game objects at all
    assert "'walk_to'" in result.content and "'decide'" in result.content
    assert "memory_write" not in result.content  # the notebook commands are `notes` here


def test_answers_given_to_programs_hold_no_hidden_fields(rig) -> None:
    seen: list[dict] = []
    original = rig.toolbox.run_game_command

    def spy(name, arguments):
        answer = original(name, arguments)
        seen.append(answer)
        return answer

    rig.toolbox.run_game_command = spy  # type: ignore[method-assign]
    rig.call("run_code", code="game.inspect(x=60, y=159)\ngame.walk_to(x=70)")
    assert seen and all(leaks(a) == [] for a in seen)


def test_a_program_cannot_reach_beyond_the_box(rig, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    code = (
        "import socket\n"
        "for label, fn in [\n"
        f"    ('read', lambda: open({str(secret)!r}).read()),\n"
        "    ('net', lambda: socket.create_connection(('1.1.1.1', 80), timeout=1)),\n"
        "    ('write', lambda: open('/tmp/cave-codemode-write', 'w').write('x')),\n"
        "]:\n"
        "    try:\n"
        "        fn()\n"
        "        print(label, 'ALLOWED')\n"
        "    except OSError:\n"
        "        print(label, 'refused')\n"
    )
    result = rig.call("run_code", code=code)
    assert "read refused" in result.content and "net refused" in result.content
    assert "write refused" in result.content and "ALLOWED" not in result.content


# What a program can do beyond the functions it was given: it can write to the pipe itself, so
# the answers of the host must hold whatever it sends. `ask` is a raw request, `finish` the final
# message of a program that did not say what the box would have said.
FORGE = """
import os, sys
chan = sys.modules["game"].decide.__closure__[0].cell_contents.channel
def ask(target, name, args):
    chan.send({"op": "call", "id": 1, "target": target, "name": name, "args": args})
    return chan.receive()
def finish(**fields):
    chan.send({"op": "done", "ok": True, **fields})
    os._exit(0)
"""


def test_a_forged_final_message_cannot_crash_the_host(rig) -> None:
    for fields in (
        {"value_json": "[" * 900 + "]" * 900},  # reads, but is too deep to show
        {"value_json": "[" * 200_000},  # does not read
        {"value_json": 7, "stdout": 123, "error": ["a"], "load_errors": {"a": 1}},
        {"stdout": "x" * 5_000_000, "stdout_truncated": "yes", "described": [1, 2]},
        {"ok": "yes", "error": {"deep": [[[]]]}, "ended": True, "commands": -5},
    ):
        result = rig.call("run_code", code=FORGE + f"finish(**{fields!r})")
        assert isinstance(result.content, str) and len(result.content) <= 31_000
    assert rig.decisions == 0
    deep = rig.call("run_code", code=FORGE + "finish(value_json='[' * 900 + ']' * 900)")
    assert deep.content.startswith("The program finished.")


def test_only_the_game_commands_and_the_notebook_can_be_asked_for(rig) -> None:
    code = FORGE + (
        "for target, name, args in [\n"
        "    ('game', 'session', {}), ('game', 'memory_write', {'path': 'a', 'text': 'b'}),\n"
        "    ('game', '__class__', {}), ('game', 'snapshot', {}), ('game', 'close', {}),\n"
        "    ('notes', 'clear', {}), ('notes', 'snapshot', {}), ('notes', 'restore', {}),\n"
        "    ('notes', '__init__', {}), ('session', 'decide', {'text': 'wait'}),\n"
        "    ('budget', 'remaining_usd', {}), (None, None, {}), ('game', 'decide', {'text': 5}),\n"
        "    ('game', 'decide', {'text': ['wait']}), ('game', 'walk_to', 'x'),\n"
        "    ('notes', 'write', {'path': 'a', 'text': 5}), ('notes', 'read', {'path': 'a'}),\n"
        "    ('notes', 'edit', {'path': 'a', 'old': 1, 'new': 2}), ('notes', 'read', {}),\n"
        "]:\n"
        "    chan.send({'op': 'call', 'id': 1, 'target': target, 'name': name, 'args': args})\n"
        "    print(chan.receive().get('ok'))\n"
    )
    result = rig.call("run_code", code=code)
    assert result.content.count("False") == 19 and "True" not in result.content, result.content
    assert rig.decisions == 0 and rig.workspace.file_names() == []


def test_the_game_counts_the_steps_whatever_the_program_asks_for(rig) -> None:
    code = FORGE + (
        "for args in [{'x': 10**400}, {'x': float('inf')}, {'x': float('nan')}, {'x': [1]},\n"
        "             {'ticks': 10**30}, {'until': {'ticks': 10**30}}, {'x': None}, {}]:\n"
        "    chan.send({'op': 'call', 'id': 1, 'target': 'game', 'name': 'walk_to', 'args': args})\n"
        "    reply = chan.receive()\n"
        "    print(reply.get('ok'), reply['value']['decision'] if reply.get('ok') else reply)\n"
        "print(ask('game', 'decide', {'text': 'wait; wait; wait; wait; wait'})['value']['decision'])\n"
    )
    result = rig.call("run_code", code=code)
    assert not result.is_error, result.content
    assert rig.decisions == 9  # eight bad calls and one bad step, a step each and no more
    assert "Game commands run: 13." in result.content  # the five commands of the step count five


def test_forged_requests_cannot_get_past_the_limit_of_commands(rig) -> None:
    code = FORGE + (
        "ok = limited = 0\n"
        "for _ in range(260):\n"
        "    reply = ask('game', 'wait', {'ticks': 1})\n"
        "    ok += bool(reply.get('ok'))\n"
        "    limited += reply.get('error', {}).get('type') == 'LimitReached'\n"
        "print(ok, limited)\n"
    )
    result = rig.call("run_code", code=code)
    assert "200 60" in result.content and rig.decisions == 200, result.content


def test_a_program_that_keeps_going_after_the_game_ended_costs_nothing_more(tmp_path) -> None:
    rig = make_rig(tmp_path / "rig", max_decisions=3)
    code = (
        "for _ in range(50):\n"
        "    try:\n"
        "        game.wait(ticks=1)\n"
        "    except Exception as err:\n"
        "        last = type(err).__name__\n"
        "print(last)\n"
    )
    result = rig.call("run_code", code=code)
    assert "GameOver" in result.content and rig.decisions == 3


def test_a_runaway_program_is_stopped_and_the_game_goes_on(rig, monkeypatch) -> None:
    runtime = rig.toolbox  # the runtime hangs off the layers; reach it through the tool handler
    from noitabench.harness import codemode

    runtime_obj = rig.toolbox._tools["run_code"].handler.__self__  # type: ignore[union-attr]
    assert isinstance(runtime_obj, codemode.CodeRuntime)
    runtime_obj.limits = Limits(cpu_seconds=1, wall_seconds=30)
    result = rig.call("run_code", code="game.wait(ticks=1)\nwhile True:\n    pass")
    assert result.is_error
    assert (
        "The program was stopped: it used more than 1 seconds of processor time." in result.content
    )
    assert rig.decisions == 1
    assert "Game commands run: 1." in result.content
    runtime_obj.limits = Limits(memory_mb=200)
    bomb = rig.call("run_code", code="x = [0] * 10**9")
    assert bomb.is_error and "200 MB of memory" in bomb.content
    ok = rig.call("run_code", code="print('still fine')")
    assert "still fine" in ok.content and not ok.is_error
    assert runtime is not None


def test_the_turn_is_carried_out_in_the_order_it_was_written(rig) -> None:
    out = rig.turn(
        ("kick", {}),
        ("run_code", {"code": "print(game.observe()['decision'])"}),
        ("aim", {"angle": 5}),
    )
    assert [r.name for r in out.results] == ["kick", "run_code", "aim"]
    # the kick was decided before the program looked, so the program saw decision 2
    assert "\n2" in out.results[1].content
    assert rig.decisions == 2  # the kick, then the aim


def test_screenshots_are_attached_to_the_result_but_not_given_to_the_program(tmp_path) -> None:
    rig = make_rig(tmp_path / "shot", screenshot=True)
    code = "a = game.wait(ticks=1)\nprint(sorted(a['observation']['screenshot']))"
    result = rig.call("run_code", code=code)
    assert "data_base64" not in result.content
    assert len(result.images) == 1 and result.images[0].startswith(b"\x89PNG")


def test_runs_are_written_to_the_transcript(rig) -> None:
    rig.call("run_code", code="game.wait(ticks=1)\ngame.wait(ticks=1)")
    rig.call("run_code", code="1/0")
    rig.logs.close()
    runs = [r for r in rig.transcript() if r["kind"] == "code_run"]
    assert [(r["ok"], r["commands"], r["steps"]) for r in runs] == [(True, 2, 2), (False, 0, 0)]
    assert runs[0]["first_decision"] == 1 and runs[0]["label"] == "run_code"
    assert "ZeroDivisionError" in runs[1]["error"]
    assert "code" not in runs[0]  # the program itself is in the tool call, not repeated


def test_without_the_layer_there_is_no_tool(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "plain", layers=("L0", "L1"))
    assert "run_code" not in rig.toolbox.names()
    assert make_rig(tmp_path / "all", layers=DEFAULT_LAYERS).toolbox.names().count("run_code") == 1


def test_the_arena_helper_matches_the_agent_tests() -> None:
    assert START_X == 30 and GROUND == 159
    assert json.dumps({"x": 1})
    assert arena_game  # imported for the other test modules
