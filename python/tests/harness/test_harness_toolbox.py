"""The tools: how a turn's tool calls become one decision, and the free tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from noitabench.agent import AgentSession, SessionConfig, render_text
from noitabench.harness import (
    Budget,
    ToolBox,
    ToolCall,
    ToolDef,
    ToolSpec,
    Workspace,
    build_toolbox,
)
from noitabench.harness.errors import ConfigError
from noitabench.harness.layers import MINIMAL_LAYERS, resolve_layers
from noitabench.harness.toolbox import FREE, GAME


@pytest.fixture
def box(tmp_path: Path, make_game):
    session = AgentSession(make_game(), config=SessionConfig(max_decisions=50))
    ws = Workspace(tmp_path / "ws")
    budget = Budget(max_usd=5.0, max_model_calls=100)
    session.memory = ws
    toolbox = build_toolbox(session, ws, budget, layers=MINIMAL_LAYERS, decisions_cap=50)
    return toolbox, session, ws, budget


def tc(name: str, call_id: str | None = None, **args) -> ToolCall:
    return ToolCall(call_id or f"id-{name}", name, args)


def test_one_game_call_is_one_decision_and_shows_the_whole_answer(box) -> None:
    toolbox, session, *_ = box
    out = toolbox.execute([tc("move", direction="right", ticks=2)])
    assert session.decisions == 1
    assert len(out.results) == 1 and not out.results[0].is_error
    assert out.results[0].content == render_text(out.answer)
    assert "Stopped: " in out.results[0].content


def test_game_calls_of_one_turn_are_run_together_as_one_decision(box) -> None:
    toolbox, session, *_ = box
    calls = [tc("aim", angle=45), tc("kick"), tc("wait", ticks=1)]
    out = toolbox.execute(calls)
    assert session.decisions == 1  # one step for the three commands
    assert [r.call_id for r in out.results] == [c.id for c in calls]
    assert [r.name for r in out.results] == ["aim", "kick", "wait"]
    assert out.results[0].content.startswith("Command 1 of 3 in this step. aim")
    assert out.results[1].content.startswith("Command 2 of 3 in this step. kick")
    assert "The whole step:" not in out.results[0].content
    assert "The whole step:\nDecision" in out.results[2].content
    assert not any(r.is_error for r in out.results)


def test_inspect_costs_a_decision_each_as_in_the_agent_layer(box) -> None:
    toolbox, session, *_ = box
    toolbox.execute([tc("inspect", x=30, y=159), tc("inspect", x=31, y=159), tc("kick")])
    assert session.decisions == 3


def test_an_invalid_command_is_an_error_result_and_still_one_decision(box) -> None:
    toolbox, session, *_ = box
    out = toolbox.execute([tc("walk_to", x="far")])
    assert out.results[0].is_error and "FAILED" in out.results[0].content
    assert session.decisions == 1
    out = toolbox.execute([tc("kick"), tc("jump", direction="sideways")])
    assert session.decisions == 2
    # nothing ran: the step was refused as a whole, and each result says which command was at fault
    assert out.results[0].is_error and "not run" in out.results[0].content
    assert out.results[1].is_error and "FAILED (bad_argument)" in out.results[1].content
    assert "The whole step:" in out.results[1].content


def test_more_than_four_game_calls_are_refused_as_one_invalid_decision(box) -> None:
    toolbox, session, *_ = box
    out = toolbox.execute([tc("wait", f"i{i}", ticks=1) for i in range(5)])
    assert session.decisions == 1
    assert out.answer["stop"]["code"] == "too_many_commands"
    assert len(out.results) == 5


def test_unknown_tools_and_unreadable_arguments_are_errors(box) -> None:
    toolbox, session, *_ = box
    out = toolbox.execute([ToolCall("a", "teleport", {}), ToolCall("b", "move", {}, "bad json")])
    assert all(r.is_error for r in out.results)
    assert "walk_to" in out.results[0].content and "bad json" in out.results[1].content
    assert session.decisions == 0 and out.answer is None


def test_free_tools_cost_no_decision_and_keep_the_order_of_results(box) -> None:
    toolbox, session, ws, _ = box
    calls = [
        tc("workspace_write", "w", path="notes/a.md", text="hi"),
        tc("kick", "k"),
        tc("budget", "b"),
        tc("workspace_read", "r", path="notes/a.md"),
    ]
    out = toolbox.execute(calls)
    assert [r.call_id for r in out.results] == ["w", "k", "b", "r"]
    assert session.decisions == 1
    assert ws.read("notes/a.md")["text"] == "hi"
    assert '"text":"hi"' in out.results[3].content


def test_the_budget_tool_reports_money_calls_and_steps(box) -> None:
    toolbox, _session, _, budget = box
    budget.charge(0.25)
    toolbox.execute([tc("kick")])
    text = toolbox.execute([tc("budget")]).results[0].content
    assert '"steps_left":49' in text and '"steps_total":50' in text
    assert (
        '"usd_left":4.75' in text and '"model_calls":1' in text and '"model_calls_left":99' in text
    )


def test_workspace_errors_are_error_results_with_the_reason(box) -> None:
    toolbox, *_ = box
    big = toolbox.execute([tc("workspace_write", path="notes/a.md", text="x" * 9_000)]).results[0]
    assert big.is_error and big.content.startswith("notes_full: No room")
    evil = toolbox.execute([tc("workspace_write", path="../evil", text="x")]).results[0]
    assert evil.is_error and evil.content.startswith("bad_path")
    missing = toolbox.execute([tc("workspace_read", path="nope.md")]).results[0]
    assert missing.is_error and missing.content.startswith("no_such_note")
    wrong = toolbox.execute([tc("workspace_write", path="a.md")]).results[0]
    assert wrong.is_error and "bad_argument" in wrong.content  # `text` is missing


def test_a_tool_can_be_registered_once(box) -> None:
    toolbox, *_ = box
    spec = ToolSpec("ping", "Answer pong.", {"type": "object", "properties": {}})
    toolbox.register(ToolDef(spec, FREE, lambda _a: {"pong": True}))
    assert toolbox.names()[-1] == "ping"
    assert toolbox.execute([tc("ping")]).results[0].content == '{"pong":true}'
    with pytest.raises(ValueError, match="already"):
        toolbox.register(ToolDef(spec, FREE, lambda _a: {}))
    with pytest.raises(ValueError, match="handler"):
        toolbox.register(ToolDef(ToolSpec("x", "", {}), FREE, None))
    with pytest.raises(ValueError, match="kind"):
        toolbox.register(ToolDef(ToolSpec("y", "", {}), "weird", None))
    assert GAME == "game"


def test_a_failing_tool_does_not_break_the_turn(tmp_path: Path, box) -> None:
    toolbox, *_ = box

    def boom(_args):
        raise OSError("disk gone")

    toolbox.register(ToolDef(ToolSpec("boom", "x", {"type": "object"}), FREE, boom))
    out = toolbox.execute([tc("boom"), tc("kick")])
    assert out.results[0].is_error and "internal_error" in out.results[0].content
    assert not out.results[1].is_error


def test_any_other_failure_of_a_tool_is_an_error_result_but_a_run_stopping_error_is_not(
    box,
) -> None:
    from noitabench.harness.errors import StopRun

    toolbox, session, *_ = box

    def deep(_args):
        raise RecursionError("a value nested too deeply")

    def stop(_args):
        raise StopRun("budget_usd", "no money left")

    toolbox.register(ToolDef(ToolSpec("deep", "x", {"type": "object"}), FREE, deep))
    toolbox.register(ToolDef(ToolSpec("stop", "x", {"type": "object"}), FREE, stop))
    out = toolbox.execute([tc("deep"), tc("kick")])
    assert out.results[0].is_error and out.results[0].content == "internal_error: RecursionError"
    assert not out.results[1].is_error and session.decisions == 1
    with pytest.raises(StopRun):  # the run itself is ending: that is not the tool's failure
        toolbox.execute([tc("stop")])


def test_toolbox_without_a_session_still_lists_specs(tmp_path: Path) -> None:
    toolbox = ToolBox(None)  # type: ignore[arg-type]
    assert toolbox.specs() == []


def test_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    from noitabench.harness import layers as layers_module

    assert resolve_layers(minimal=True) == ("L0", "L1")
    assert resolve_layers() == layers_module.DEFAULT_LAYERS  # every layer that exists
    assert resolve_layers(requested="l1, L0") == ("L0", "L1")
    assert resolve_layers(requested="L5,L3,L0,L1") == ("L0", "L1", "L3", "L5")
    for bad, message in (
        ("L0,L9", "unknown layer"),
        ("L0", "always needed"),
    ):
        with pytest.raises(ConfigError, match=message):
            resolve_layers(requested=bad)
    # a layer of the design that has no code yet is refused with its own message
    registrars = dict(layers_module.LAYER_REGISTRARS)
    del registrars["L5"]
    monkeypatch.setattr(layers_module, "LAYER_REGISTRARS", registrars)
    with pytest.raises(ConfigError, match="not available yet"):
        resolve_layers(requested="L0,L1,L5")
