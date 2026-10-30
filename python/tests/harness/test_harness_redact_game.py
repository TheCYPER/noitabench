"""Whole games with every layer on and secrets in reach of the box: what the model is shown and
what the run writes stay clean, and games without a secret come out exactly as they did before.

Only made-up secrets are planted. The real environment of the machine is part of these runs
(the shared redactor learns it, as in a real run), but no test prints or compares it."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from noitabench.harness import ModelConfig, RunConfig, run_family
from noitabench.harness.adapters.scripted import Say, ScriptedAdapter, call
from noitabench.harness.layers import DEFAULT_LAYERS
from noitabench.harness.logs import RunLogs
from noitabench.harness.model import ToolCall, ToolSpec
from noitabench.harness.redact import (
    HIDDEN,
    Redactor,
    default_redactor,
    set_default_redactor,
)
from noitabench.harness.sandbox import Limits, Sandbox, sandbox_available
from noitabench.harness.toolbox import FREE, ToolDef, ToolOutput, object_schema
from rig import make_rig
from test_harness_layers_game import full_script, hurting_game, play, texts_shown
from test_harness_loop import _walking_script
from test_harness_redact import fake_value, holder_process, leaked
from test_harness_redact_box import SHOW, everything_in, read_code, refuse

pytestmark = pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")
darwin = pytest.mark.skipif(sys.platform != "darwin", reason="reads other programs on macOS")


class Spy(Redactor):
    """A redactor that remembers every text it changed (as the changed text, which holds no
    secret any more)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.changes: list[str] = []
        self.calls = 0

    def redact(self, text: str, marker: str = HIDDEN, *, shapes: bool = True) -> str:
        self.calls += 1
        out = super().redact(text, marker, shapes=shapes)
        if out != text:
            self.changes.append(out[:160])
        return out


@pytest.fixture
def shared() -> Iterator[Redactor]:
    mine = Redactor()
    previous = set_default_redactor(mine)
    yield mine
    set_default_redactor(previous)


@pytest.fixture
def spy() -> Iterator[Spy]:
    watcher = Spy()
    previous = set_default_redactor(watcher)
    yield watcher
    set_default_redactor(previous)


def leak_script(pid: int, ours: str) -> list[Any]:
    """A game in which the model writes a plugin and a hook script that read the secret of the
    holder program, runs a program that leaks in every way it can think of, calls the plugin tool
    and waits for the hook."""
    read = read_code(pid)
    plugin = (
        read
        + SHOW
        + (
            "prompt_fragment = 'remember ' + secret\n"
            "@tool('tool that knows ' + secret,\n"
            "      {'type': 'object', 'properties': {'a': {'type': 'string', 'description': secret}}})\n"
            "def leaky(args):\n"
            "    show(secret)\n"
            "    return {'v': secret, 'r': secret[::-1], 'h': raw.hex()}\n"
            "@hook('damage')\n"
            "def on_damage(event):\n"
            "    print('plugin hook saw', secret)\n"
        )
    )
    hook = read + "print('hook script saw', secret)\nnotes.write('notes/hook.md', secret)\n"
    half = len(ours) // 2
    program = (
        read
        + SHOW
        + (
            f"mine = {ours[:half]!r} + {ours[half:]!r}\n"
            "for v in (secret, mine):\n"
            "    show(v)\n"
            "    notes.write('notes/leak.md', 'key: ' + v + ' ' + raw.hex(), append=True)\n"
            "    game.walk_to(x=v)\n"
            "raise RuntimeError('failed with ' + secret + ' and ' + mine)\n"
        )
    )

    def briefing(_conversation: Any, _items: Any) -> Say:
        return Say(text="I am in the arena.")

    return [
        Say.tools(
            call("workspace_write", "w1", path="plugins/leak.py", text=plugin),
            call("workspace_write", "w2", path="scripts/leak.py", text=hook),
            call("plugin_list", "w3"),
            call("hook_set", "w4", event="damage", action="run", script="leak"),
        ),
        briefing,
        Say.tools(call("run_code", code=program)),
        Say.tools(ToolCall("p1", "plugin_call", {"name": "leaky", "args": {"a": "x"}})),
        *[Say.tools(call("wait", ticks=5)) for _ in range(30)],
    ]


@darwin
def test_a_whole_game_with_secrets_in_reach_leaves_none_in_front_of_the_model_or_on_disk(
    tmp_path: Path, shared: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = fake_value("elsewhere")
    ours = fake_value("harness")
    monkeypatch.setenv("FAKE_HARNESS_API_KEY", ours)
    child = holder_process(FAKE_SERVICE_API_KEY=elsewhere)
    try:
        cfg, adapter, summary = play(
            tmp_path,
            leak_script(child.pid, ours),
            context_limit=1_000,  # a briefing after the first turn: the plugin joins the prompt
            max_decisions=14,
            family="leak",
        )
    finally:
        child.kill()
        child.wait()
    assert summary["result"]["decisions"] >= 8

    shown = "\n".join(texts_shown(adapter))
    for value in (elsewhere, ours):
        assert leaked(shown, value) == [], leaked(shown, value)
    # the pieces really ran, and what they said came out with the secret taken out
    assert "The program stopped with an error." in shown and "failed with" in shown
    assert "The plugin tool finished." in shown and "hook script saw" in shown
    assert "plugin hook saw" in shown and shown.count(HIDDEN) > 20
    second = adapter.conversations[1]
    assert "NOTES YOU LEFT IN YOUR PLUGINS" in second.system and "remember" in second.system
    assert leaked(second.system, elsewhere) == []
    assert not any(
        leaked(spec.description + json.dumps(spec.schema), elsewhere) for spec in second.tools
    )

    written = everything_in(cfg.out, cfg.workspaces_dir)
    for value in (elsewhere, ours):
        assert leaked(written, value) == [], leaked(written, value)
    notes = (cfg.workspaces_dir / "leak" / "notes" / "leak.md").read_text()
    assert notes.count(HIDDEN) == 4  # two secrets, in clear and in hex
    assert (cfg.workspaces_dir / "leak" / "notes" / "hook.md").read_text() == HIDDEN
    decisions = (cfg.out / "decisions.jsonl").read_text()
    assert "walk_to" in decisions and HIDDEN in decisions


# -- nothing else changes --------------------------------------------------------------------------


def test_games_without_a_secret_are_not_touched(tmp_path: Path, spy: Spy) -> None:
    """The redactor knows every key-like value of this machine and the shapes of keys; a whole
    game with every layer shows the model, and writes, exactly what it did without it."""
    spy.add([fake_value("planted") for _ in range(5)])
    cfg_on, on, summary_on = play(tmp_path / "on", full_script())
    assert spy.count() >= 5 and spy.calls > 300  # it was in the way of everything
    spy_changes = list(spy.changes)

    previous = set_default_redactor(Redactor(enabled=False))
    try:
        cfg_off, off, summary_off = play(tmp_path / "off", full_script())
    finally:
        set_default_redactor(previous)

    assert spy_changes == [], spy_changes[:3]
    assert texts_shown(on) == texts_shown(off)
    assert len(texts_shown(on)) > 40
    for name in ("decisions.jsonl",):
        assert (cfg_on.out / name).read_text() == (cfg_off.out / name).read_text()
    assert everything_in(cfg_on.out / "workspace") == everything_in(cfg_off.out / "workspace")
    assert summary_on["result"]["decisions"] == summary_off["result"]["decisions"]
    rows_on, rows_off = (
        [
            re.sub(r"toolu_\d+", "toolu_N", line)  # the numbers of tool calls run on across games
            for line in (cfg.out / "transcript.jsonl").read_text().splitlines()
            if json.loads(line)["kind"] in ("opening", "assistant", "results", "end")
        ]
        for cfg in (cfg_on, cfg_off)
    )
    assert rows_on == rows_off and len(rows_on) > 10
    kinds = [
        json.loads(x)["kind"] for x in (cfg_on.out / "transcript.jsonl").read_text().splitlines()
    ]
    assert "code_run" in kinds and "lib_install" in kinds  # the layers did run


def test_a_game_on_a_generated_world_is_not_touched_either(tmp_path: Path, spy: Spy) -> None:
    """Real maps, real materials and sixty decisions: nothing the redactor does changes a
    character (its shapes and key values would show up here as a changed text)."""
    cfg = RunConfig(
        model=ModelConfig("fake", "fake"),
        out=tmp_path / "run",
        workspaces_dir=tmp_path / "ws",
        world_seed=3,
        rule_seed=2,
        max_decisions=60,
        layers=DEFAULT_LAYERS,
    )
    adapter = ScriptedAdapter(_walking_script())
    summary = run_family(cfg, adapter=adapter, sleep=lambda _s: None)[0]
    assert summary["result"]["over"] == "decision_limit"
    assert len("".join(texts_shown(adapter))) > 100_000
    assert spy.calls > 300 and spy.changes == [], spy.changes[:3]


# -- the last nets -----------------------------------------------------------------------------------


def test_the_logs_and_the_toolbox_hide_a_known_secret_even_when_nothing_else_did(
    tmp_path: Path, shared: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = fake_value("net")
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", value)
    shared.sync_environment()

    logs = RunLogs(tmp_path / "logs")
    logs.transcript(
        "assistant",
        text=f"I will print {value}",
        tool_calls=[{"arguments": {"code": f"x='{value}'"}}],
    )
    logs.call({"call": 1, "error": {"message": f"bad key {value[::-1]}"}})
    logs.close()
    text = everything_in(tmp_path / "logs")
    assert leaked(text, value) == [] and text.count(HIDDEN) == 3

    from agent_worlds import START_X
    from rig import arena_game

    rig = make_rig(
        tmp_path / "rig", game=arena_game(tmp_path / "arena", START_X), layers=("L0", "L1")
    )
    rig.toolbox.register(
        ToolDef(
            ToolSpec("leaky", "A tool that returns what it should not.", object_schema({})),
            FREE,
            lambda _a: ToolOutput(f"text {value} and {value[::-1]}", is_error=True),
        )
    )
    rig.toolbox.register(
        ToolDef(
            ToolSpec("leaky_data", "Another.", object_schema({})),
            FREE,
            lambda _a: {"v": value, "list": [value.upper()]},
        )
    )
    rig.toolbox.add_system_suffix(lambda: f"\nsuffix {value}\n")
    rig.toolbox.add_notice(f"a notice with {value}")
    turn = rig.turn(("leaky", {}), ("leaky_data", {}), ("budget", {}))
    shown = "\n".join(r.content for r in turn.results)
    assert leaked(shown, value) == [] and shown.count(HIDDEN) >= 5
    assert "a notice with" in turn.results[-1].content  # the notice itself is kept
    assert leaked(rig.toolbox.system_suffix(), value) == []
    assert rig.toolbox.system_suffix().startswith("\nsuffix ")
    # an error from a tool that raises with the secret in its message
    rig.toolbox.register(
        ToolDef(
            ToolSpec("raises", "Raises.", object_schema({})),
            FREE,
            lambda _a: (_ for _ in ()).throw(ValueError(f"cannot use {value}")),
        )
    )
    assert leaked(rig.call("raises").content, value) == []


@darwin
def test_a_program_that_starts_between_two_jobs_is_found_by_the_second(tmp_path: Path) -> None:
    """The secrets are looked for again before every job, not once."""
    redactor = Redactor(shapes=False)
    sandbox = Sandbox(limits=Limits(), redactor=redactor)
    first = sandbox.run({"kind": "code", "code": "print('nothing yet')", "limits": {}}, refuse)
    assert first.done is not None and first.done["stdout"] == "nothing yet\n"
    value = fake_value("late")
    child = holder_process(FAKE_SERVICE_API_KEY=value)
    try:
        code = read_code(child.pid) + "print('got', secret)\nprint('and', secret[::-1])\n"
        second = sandbox.run({"kind": "code", "code": code, "limits": {}}, refuse)
    finally:
        child.kill()
        child.wait()
    assert second.done is not None and second.done["ok"], second.done
    assert second.done["stdout"] == f"got {HIDDEN}\nand {HIDDEN}\n"


def test_a_scan_that_fails_does_not_fail_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from noitabench.harness import redact

    def broken(_pid: int) -> Any:
        raise RuntimeError("the scan broke")

    monkeypatch.setattr(redact, "other_environments", broken)
    sandbox = Sandbox(limits=Limits(), redactor=Redactor())
    result = sandbox.run({"kind": "code", "code": "print(1 + 1)", "limits": {}}, refuse)
    assert result.done is not None and result.done["stdout"] == "2\n"


def test_the_variable_named_by_api_key_env_counts_as_a_secret(
    tmp_path: Path, shared: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = fake_value("gateway")
    monkeypatch.setenv("FAKE_GATEWAY_PASSPHRASE", value)  # a name that does not look like a key
    assert shared.redact(f"x {value} y") == f"x {value} y"
    cfg = RunConfig(
        model=ModelConfig("fake", "fake", api_key_env="FAKE_GATEWAY_PASSPHRASE"),
        out=tmp_path / "run",
        workspaces_dir=tmp_path / "ws",
        max_decisions=2,
    )
    adapter = ScriptedAdapter([Say.tools(call("wait", ticks=1)) for _ in range(4)])
    run_family(cfg, adapter=adapter, game_factory=hurting_game, sleep=lambda _s: None)
    shared.sync_environment()
    assert default_redactor() is shared
    assert shared.redact(f"x {value} y") == f"x {HIDDEN} y"
    summary = json.loads((cfg.out / "summary.json").read_text())
    assert summary["model"]["api_key_env"] == "FAKE_GATEWAY_PASSPHRASE"  # the name stays


def test_library_tools_and_their_log_lines_are_cleaned_too(
    tmp_path: Path, shared: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_worlds import START_X
    from rig import arena_game, make_rig

    value = fake_value("lib")
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", value)
    shared.sync_environment()
    rig = make_rig(tmp_path / "rig", game=arena_game(tmp_path / "arena", START_X))
    asked = rig.call("lib_install", name=value)  # the name comes back in the refusal
    assert asked.is_error and "not one of the libraries" in asked.content
    assert leaked(asked.content, value) == [] and HIDDEN in asked.content
    assert leaked(rig.call("lib_list").content, value) == []
    rig.logs.close()
    assert leaked(everything_in(rig.folder), value) == []
    row = next(r for r in rig.transcript() if r["kind"] == "lib_install")
    assert row["ok"] is False and HIDDEN in row["name"] + row["detail"]
