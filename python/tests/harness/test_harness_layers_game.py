"""Whole games with every layer on, played by a scripted model: what the model is shown stays
clean, plugins reach the next conversation, and the layers refuse to start without the box."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_worlds import GROUND, START_X
from noitabench.harness import ConfigError, ModelConfig, RunConfig, run_family
from noitabench.harness.adapters.scripted import Say, ScriptedAdapter, call
from noitabench.harness.layers import DEFAULT_LAYERS, MINIMAL_LAYERS
from noitabench.harness.model import ToolCall, ToolResult
from noitabench.harness.prompt import system_prompt
from noitabench.harness.sandbox import check_sandbox, sandbox_available
from rig import arena_game
from test_harness_prompt import forbidden_in
from wheels import toy_wheelhouse

needs_box = pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")

PLUGIN = """\
prompt_fragment = "Fire spreads along oil."

@tool("Step right", {"type": "object", "properties": {"ticks": {"type": "integer"}}})
def step_right(args):
    a = game.move(direction="right", ticks=int(args.get("ticks", 1)))
    return a["stop"]["reason"]
"""
HOOK = "print('ouch at decision', event['decision'])\ngame.inspect(x=60, y=159)\n"
PROGRAM = """\
import tinylib
a = game.walk_to(x=70)
print(tinylib.NAME, a['stop']['reason'])
n = notes.list()['quota']['notes']['left']
print('room', n)
game.decide('aim(angle=20); kick')
"""


def hurting_game(world_seed: int, folder: Path):
    game = arena_game(folder.parent / f"arena{world_seed}", START_X)
    game.spawn_enemy("longleg", START_X + 18, GROUND)
    return game


def play(tmp_path: Path, script, **overrides) -> tuple[RunConfig, ScriptedAdapter, dict[str, Any]]:
    values: dict[str, Any] = {
        "model": ModelConfig("fake", "fake"),
        "out": tmp_path / "run",
        "workspaces_dir": tmp_path / "workspaces",
        "max_decisions": 12,
        "layers": DEFAULT_LAYERS,
        "wheelhouse": toy_wheelhouse(tmp_path),
    }
    values.update(overrides)
    cfg = RunConfig(**values)
    adapter = ScriptedAdapter(script)
    summaries = run_family(cfg, adapter=adapter, game_factory=hurting_game, sleep=lambda _s: None)
    return cfg, adapter, summaries[0]


def texts_shown(adapter: ScriptedAdapter) -> list[str]:
    """Everything a model was shown in a game: system prompts, tools, user messages."""
    shown: list[str] = []
    for conv in adapter.conversations:
        shown.append(conv.system)
        for spec in conv.tools:
            shown += [spec.name, spec.description, json.dumps(spec.schema)]
        for entry in conv.history:
            if entry["role"] != "user":
                continue
            for item in entry["items"]:
                shown.append(item.content if isinstance(item, ToolResult) else item.text)
    return shown


def full_script() -> list[Say]:
    return [
        Say.tools(
            call("workspace_write", "w1", path="plugins/p.py", text=PLUGIN),
            call("workspace_write", "w2", path="scripts/ouch.py", text=HOOK),
            call("plugin_list", "w3"),
            call("hook_set", "w4", event="damage", action="run", script="ouch"),
            call("lib_list", "w5"),
            ToolCall("w6", "lib_install", {"name": "tinylib"}),
        ),
        Say.tools(call("run_code", code=PROGRAM)),
        Say.tools(ToolCall("p1", "plugin_call", {"name": "step_right", "args": {"ticks": 2}})),
        Say.tools(call("hook_list")),
        *[Say.tools(call("wait", ticks=5)) for _ in range(30)],
    ]


@needs_box
def test_everything_the_model_is_shown_in_a_game_with_every_layer_is_clean(tmp_path: Path) -> None:
    _cfg, adapter, summary = play(tmp_path, full_script())
    assert summary["layers"] == list(DEFAULT_LAYERS)
    shown = texts_shown(adapter)
    assert len(shown) > 40
    for text in shown:
        assert forbidden_in(text) == [], (forbidden_in(text), text[:200])
    joined = "\n".join(shown)
    # the pieces really were exercised
    assert "The program finished." in joined and "tiny" in joined
    assert "The plugin tool finished." in joined
    assert "Hook h1 (damage" in joined and "ouch at decision" in joined
    assert '"installed":["tinylib 0.1"]' in joined
    for secret in ("rule_seed", "must_pass", "encounter_id", "placeholder", "wheelhouse"):
        assert secret not in joined, secret


@needs_box
def test_a_run_with_every_layer_leaves_its_marks_in_the_run_folder(tmp_path: Path) -> None:
    cfg, _, summary = play(tmp_path, full_script())
    rows = [json.loads(x) for x in (cfg.out / "transcript.jsonl").read_text().splitlines()]
    kinds = [r["kind"] for r in rows]
    assert "code_run" in kinds and "lib_install" in kinds
    labels = [r["label"] for r in rows if r["kind"] == "code_run"]
    assert "run_code" in labels and "plugin step_right" in labels and "hook h1" in labels
    assert (cfg.out / "workspace" / "plugins" / "p.py").is_file()
    assert (cfg.out / "workspace" / "scripts" / "ouch.py").is_file()
    assert summary["workspace"]["usage"]["code"]["used"] > 0
    # the game itself was recorded as usual
    assert (cfg.out / "decisions.jsonl").is_file()


@needs_box
def test_the_step_limit_holds_exactly_whatever_the_code_layers_do(tmp_path: Path) -> None:
    """Steps are counted by the game alone: a program, a hook script and a plugin tool that all
    try to play more than is left end the game at the limit, not after it."""
    spend = "import sys\nfor _ in range(30):\n    try:\n        game.wait(ticks=1)\n    except Exception: pass\n"
    plugin = "@tool('spend')\ndef spend(args):\n" + "".join(
        f"    {line}\n" for line in spend.splitlines()
    )
    script = [
        Say.tools(
            call("workspace_write", "w1", path="plugins/p.py", text=plugin),
            call("workspace_write", "w2", path="scripts/h.py", text=spend),
            call("hook_set", "w3", event="damage", action="run", script="h"),
        ),
        Say.tools(call("run_code", code=spend)),
        Say.tools(ToolCall("p1", "plugin_call", {"name": "spend", "args": {}})),
        Say.tools(call("wait", ticks=5)),
    ]
    cfg, _adapter, summary = play(tmp_path, script, max_decisions=7)
    assert summary["result"]["over"] == "decision_limit"
    assert summary["result"]["decisions"] == 7 and summary["session"]["decisions"] == 7
    rows = [json.loads(x) for x in (cfg.out / "decisions.jsonl").read_text().splitlines()]
    assert len(rows) <= 7 and sum(r["cost"] for r in rows) == 7


@needs_box
def test_prompt_fragments_reach_the_next_conversation_and_the_next_game(tmp_path: Path) -> None:
    def briefing(_conv, _items) -> Say:
        return Say(text="I am in the arena.")

    script = [
        Say.tools(call("workspace_write", path="plugins/p.py", text=PLUGIN)),
        briefing,
        *[Say.tools(call("wait", ticks=1)) for _ in range(20)],
        Say.tools(call("wait", ticks=1)),
    ]
    cfg, adapter, _ = play(
        tmp_path,
        script,
        context_limit=1_000,
        max_decisions=4,
        family="frag",
        clear_workspace=False,
    )
    first, second = adapter.conversations[0], adapter.conversations[1]
    assert "NOTES YOU LEFT IN YOUR PLUGINS" not in first.system  # the one that ran keeps its prompt
    assert second.system.endswith("- Fire spreads along oil.\n")
    assert second.system.startswith(first.system)
    assert second.tools == first.tools  # the tool list never changes

    # the next game of the family starts with the fragment, as the plugin stays in the notebook
    nxt = ScriptedAdapter([Say.tools(call("wait", ticks=1)) for _ in range(6)])
    again = RunConfig(
        model=ModelConfig("fake", "fake"),
        out=tmp_path / "second",
        workspaces_dir=tmp_path / "workspaces",
        max_decisions=2,
        layers=DEFAULT_LAYERS,
        family="frag",
    )
    run_family(again, adapter=nxt, game_factory=hurting_game, sleep=lambda _s: None)
    assert nxt.conversations[0].system.endswith("- Fire spreads along oil.\n")

    # the control setting empties the notebook, plugins and libraries included
    ctl = ScriptedAdapter([Say.tools(call("wait", ticks=1)) for _ in range(6)])
    cleared = RunConfig(
        model=ModelConfig("fake", "fake"),
        out=tmp_path / "third",
        workspaces_dir=tmp_path / "workspaces",
        max_decisions=2,
        layers=DEFAULT_LAYERS,
        family="frag",
        clear_workspace=True,
    )
    run_family(cleared, adapter=ctl, game_factory=hurting_game, sleep=lambda _s: None)
    assert "NOTES YOU LEFT" not in ctl.conversations[0].system
    assert cfg.workspaces_dir.joinpath("frag", "plugins").is_dir()
    assert not any(cfg.workspaces_dir.joinpath("frag", "plugins").iterdir())


def test_the_minimal_setting_is_what_it_was(tmp_path: Path) -> None:
    before = system_prompt(mode="tools", notes_kept=True)
    assert system_prompt(mode="tools", notes_kept=True, layers=MINIMAL_LAYERS) == before
    assert "PROGRAMS AND PLUGINS" not in before
    full = system_prompt(mode="tools", notes_kept=True, layers=DEFAULT_LAYERS)
    assert full.startswith(before.split("\nALLOWANCE")[0]) and "run_code" in full
    for text in (full, system_prompt(mode="tools", notes_kept=False, layers=DEFAULT_LAYERS)):
        assert forbidden_in(text) == []
    # text mode has no tools, so it says nothing about them
    assert "PROGRAMS" not in system_prompt(mode="text", notes_kept=True, layers=DEFAULT_LAYERS)

    cfg = RunConfig(
        model=ModelConfig("fake", "fake"),
        out=tmp_path / "min",
        workspaces_dir=tmp_path / "ws",
        max_decisions=3,
    )
    adapter = ScriptedAdapter([Say.tools(call("wait", ticks=1)) for _ in range(5)])
    summary = run_family(cfg, adapter=adapter, game_factory=hurting_game)[0]
    names = [t.name for t in adapter.conversations[0].tools]
    assert summary["layers"] == ["L0", "L1"]
    assert names[-7:] == [
        "budget", "workspace_list", "workspace_read", "workspace_write", "workspace_edit",
        "workspace_search", "workspace_delete",
    ]  # fmt: skip
    assert not [n for n in names if n.startswith(("run_", "hook_", "plugin_", "lib_"))]


@needs_box
def test_every_layer_adds_its_tools_in_a_fixed_order(tmp_path: Path) -> None:
    _, adapter, _ = play(
        tmp_path, [Say.tools(call("wait", ticks=1)) for _ in range(3)], max_decisions=1
    )
    names = [t.name for t in adapter.conversations[0].tools]
    tail = names[names.index("workspace_delete") + 1 :]
    assert tail == [
        "run_code", "hook_set", "hook_list", "hook_clear",
        "wand_range", "spawn_agent", "fork_agent", "agent_message", "agent_list",
        "plugin_list", "plugin_call", "lib_list", "lib_install",
    ]  # fmt: skip


def test_the_layers_that_run_code_refuse_to_start_without_the_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from noitabench.__main__ import main as top_main
    from noitabench.harness import sandbox

    check_sandbox.cache_clear()
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: False)
    try:
        for layers in (("L0", "L1", "L2"), ("L0", "L1", "L3"), ("L0", "L1", "L5"), DEFAULT_LAYERS):
            check_sandbox.cache_clear()
            with pytest.raises(ConfigError, match="never run without the box"):
                RunConfig(model=ModelConfig("fake", "fake"), out=tmp_path / "x", layers=layers)
        RunConfig(model=ModelConfig("fake", "fake"), out=tmp_path / "x", layers=MINIMAL_LAYERS)
        check_sandbox.cache_clear()
        code = top_main(
            [
                "harness",
                "run",
                "--provider",
                "fake",
                "--world-seed",
                "1",
                "--out",
                str(tmp_path / "y"),
            ]
        )
        assert code == 2 and "never run without the box" in capsys.readouterr().err
        assert not (tmp_path / "y").exists()
        assert top_main(
            ["harness", "run", "--provider", "fake", "--world-seed", "1", "--minimal",
             "--max-decisions", "2", "--workspaces-dir", str(tmp_path / "w"),
             "--out", str(tmp_path / "z")]
        ) == 0  # fmt: skip
    finally:
        check_sandbox.cache_clear()


def test_text_mode_has_no_tool_calls_so_layers_with_tools_are_a_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from noitabench.__main__ import main as top_main
    from noitabench.harness.layers import check_layers, resolve_layers

    for layers in (("L0", "L1", "L2"), ("L0", "L1", "L3"), ("L0", "L1", "L5"), DEFAULT_LAYERS):
        with pytest.raises(ConfigError, match="--mode text has no tool calls"):
            RunConfig(
                model=ModelConfig("fake", "fake"), out=tmp_path / "x", mode="text", layers=layers
            )
    with pytest.raises(ConfigError, match="L4"):
        check_layers(("L0", "L1", "L4"), mode="text")  # when the sub-agent layer is wired in
    RunConfig(model=ModelConfig("fake", "fake"), out=tmp_path / "x", mode="text")  # minimal: fine
    # on the command line, text mode without a list of layers means the layers it can use
    assert resolve_layers(mode="text") == MINIMAL_LAYERS
    assert resolve_layers(mode="tools") == DEFAULT_LAYERS
    with pytest.raises(ConfigError, match="--mode text has no tool calls"):
        RunConfig(
            model=ModelConfig("fake", "fake"),
            out=tmp_path / "x",
            mode="text",
            layers=resolve_layers(requested="L0,L1,L2", mode="text"),
        )
    base = ["harness", "run", "--provider", "fake", "--world-seed", "1", "--mode", "text"]
    asked = top_main([*base, "--layers", "L0,L1,L3", "--out", str(tmp_path / "y")])
    assert asked == 2 and "--mode text has no tool calls" in capsys.readouterr().err
    assert not (tmp_path / "y").exists()
    plain = top_main(
        [
            *base,
            "--max-decisions",
            "2",
            "--workspaces-dir",
            str(tmp_path / "w"),
            "--out",
            str(tmp_path / "z"),
        ]
    )
    assert plain == 0
    summary = json.loads((tmp_path / "z" / "summary.json").read_text())
    assert summary["layers"] == ["L0", "L1"] and summary["mode"] == "text"
