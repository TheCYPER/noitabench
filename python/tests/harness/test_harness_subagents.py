"""L4: helpers (sub-agents) started with spawn_agent and fork_agent."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from layer_context import make_rig
from noitabench.agent import render_text, tool_schemas
from noitabench.agent.errors import CommandError
from noitabench.harness import AgentLoop, Budget, LoopConfig, ModelConfig, ToolCall, UserText
from noitabench.harness.adapters.scripted import Say, ScriptedAdapter, call
from noitabench.harness.errors import ConfigError, ModelError
from noitabench.harness.model import REFUSAL, ToolResult
from noitabench.harness.prices import ModelPrice, PriceTier
from noitabench.harness.prompt import FORBIDDEN_STEMS, system_prompt
from noitabench.harness.subagent_specs import NOT_RUN, fork_note, helper_system
from noitabench.harness.subagents import (
    HELPER_TOOLS,
    NOT_AVAILABLE,
    PROMPT_L4,
    WRAP_UP,
    ParentLink,
    SubAgentSettings,
    SubModel,
    fork_conversation,
    helper_specs,
    register_l4,
    view_spec,
)
from noitabench.harness.wandrange import PROMPT_WAND_RANGE, wand_range_spec

_STEMS = re.compile(r"\b(" + "|".join(FORBIDDEN_STEMS) + r")", re.IGNORECASE)
GAME_COMMANDS = {"move", "walk_to", "jump", "fly", "fire", "wait", "kick", "aim", "inspect"}


def tc(name: str, call_id: str | None = None, **args: Any) -> ToolCall:
    return ToolCall(call_id or f"id-{name}", name, args)


def run(rig, *calls: ToolCall) -> list[ToolResult]:
    return list(rig.toolbox.execute(list(calls)).results)


def data(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    return json.loads(result.content)


def harness_rows(rig) -> list[dict[str, Any]]:
    rig.logs.close()
    lines = (rig.folder / "logs" / "harness.jsonl").read_text().splitlines()
    return [json.loads(x) for x in lines]


def transcript_rows(rig) -> list[dict[str, Any]]:
    rig.logs.close()
    lines = (rig.folder / "logs" / "transcript.jsonl").read_text().splitlines()
    return [json.loads(x) for x in lines]


def tool_names(conversation) -> set[str]:
    return {t.name for t in conversation.tools}


def assert_no_dangling_calls(conversation, *, last_open: bool = False) -> None:
    """Every assistant turn with tool calls is answered by the next user message (the very last
    turn of a game that has ended may be open: `last_open`)."""
    history = conversation.history
    for i, entry in enumerate(history):
        if entry["role"] != "assistant" or not entry["calls"]:
            continue
        if last_open and i + 1 == len(history):
            continue
        assert i + 1 < len(history), "a tool call without any result"
        answered = {x.call_id for x in history[i + 1]["items"] if isinstance(x, ToolResult)}
        assert {c.id for c in entry["calls"]} <= answered


def assert_no_orphan_results(conversation) -> None:
    """Every tool result in the history answers a call of the assistant turn just before it, once
    (a provider answers a result without its call with a 400)."""
    history = conversation.history
    for i, entry in enumerate(history):
        if entry["role"] != "user":
            continue
        results = [x.call_id for x in entry["items"] if isinstance(x, ToolResult)]
        if not results:
            continue
        before = history[i - 1] if i else None
        assert before is not None and before["role"] == "assistant", "results with no turn before"
        assert sorted(results) == sorted(c.id for c in before["calls"]), (i, results)


@pytest.fixture
def game(make_game):
    return make_game()


# -- registration ---------------------------------------------------------------------------------


def test_l4_adds_the_helper_tools_and_the_practice_range(tmp_path: Path, game) -> None:
    rig = make_rig(tmp_path, game, register=register_l4)
    assert rig.toolbox.names()[-5:] == ["wand_range", *HELPER_TOOLS]
    assert "view" not in rig.toolbox.names(), "the player has no use for a view of its own view"
    before = (rig.session.decisions, rig.session.frame)
    assert data(run(rig, tc("agent_list"))[0]) == {"helpers": [], "helpers_left": 8}
    assert (rig.session.decisions, rig.session.frame) == before


def test_wand_range_is_not_registered_twice(tmp_path: Path, game) -> None:
    from noitabench.harness.wandrange import register_wand_range

    def both(ctx) -> None:
        register_wand_range(ctx)
        register_l4(ctx)

    rig = make_rig(tmp_path, game, register=both)
    assert rig.toolbox.names().count("wand_range") == 1


def test_every_text_helpers_read_is_clean() -> None:
    texts = [PROMPT_L4, PROMPT_WAND_RANGE, WRAP_UP, NOT_AVAILABLE, NOT_RUN]
    texts += [helper_system(""), helper_system("a careful note keeper")]
    texts += [fork_note("workspace_list, view", "Plan the wand.")]
    for settings in (
        SubAgentSettings(),
        SubAgentSettings(models={"cheap": SubModel(ModelConfig("fake", "m"), None)}),
    ):
        for spec in [*helper_specs(settings), view_spec(), wand_range_spec()]:
            texts += [spec.name, spec.description, json.dumps(spec.schema)]
    for text in texts:
        assert _STEMS.findall(text) == [], text
    assert "game" in PROMPT_L4.lower() or "helper" in PROMPT_L4.lower()


# -- spawn ----------------------------------------------------------------------------------------


def test_a_spawned_helper_works_in_the_notebook_and_answers(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("workspace_write", path="notes/water.md", text="water puts out fire")),
        Say(text="Wrote notes/water.md."),
    ]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    frame = rig.session.frame
    out = data(
        run(rig, tc("spawn_agent", task="Note that water puts out fire.", persona="note keeper"))[0]
    )
    assert out["agent"] == "a1" and out["state"] == "done"
    assert out["answer"] == "Wrote notes/water.md." and out["calls_used"] == 2
    assert rig.workspace.read("notes/water.md")["text"] == "water puts out fire"
    # a helper's work is free for the game
    assert rig.session.decisions == 0 and rig.session.frame == frame
    conv = rig.adapter.conversations[0]
    assert "note keeper" in conv.system and "helper" in conv.system
    first = conv.history[0]["items"][0]
    assert isinstance(first, UserText) and first.text == "Note that water puts out fire."


def test_a_helper_has_no_hands_and_only_the_tools_it_was_given(tmp_path: Path, game) -> None:
    script = [Say.tools(call("move", direction="right", ticks=3)), Say(text="I could not move.")]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    frame = rig.session.frame
    out = data(run(rig, tc("spawn_agent", task="Walk right."))[0])
    conv = rig.adapter.conversations[0]
    assert tool_names(conv) == {
        *(n for n in rig.toolbox.names() if n.startswith("workspace_")),
        "wand_range",
        "view",
        *HELPER_TOOLS,
    }
    assert not tool_names(conv) & (GAME_COMMANDS | {"budget"})
    refusal = conv.history[2]["items"][0]
    assert refusal.is_error and "not available to a helper" in refusal.content
    assert rig.session.frame == frame and rig.session.decisions == 0
    assert out["state"] == "done"


def test_no_route_leads_from_a_helper_to_the_game(tmp_path: Path, game) -> None:
    """Every game command, the notes commands, `budget` and the tools of the other layers: asked
    for as a tool, or called without being offered, they are refused and cost nothing."""
    others = ["budget", "run_code", "plugin_call", "plugin_list", "hook_add", "lib_install"]
    names = [*(s["name"] for s in tool_schemas()), *others]
    assert GAME_COMMANDS <= set(names)
    script = [
        Say.tools(*(call(n, f"id-{i}") for i, n in enumerate(names))),
        Say(text="Nothing worked."),
    ]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    state = (rig.session.decisions, rig.session.frame, rig.session.state_hash())
    for n in names:  # asking for the tool when starting a helper
        bad = run(rig, tc("spawn_agent", task="x", tools=[n]))[0]
        assert bad.is_error and "bad_argument" in bad.content, n
        bad = run(rig, tc("fork_agent", task="x", tools=[n]))[0]
        assert bad.is_error and "bad_argument" in bad.content, n
    out = data(run(rig, tc("spawn_agent", task="Try everything."))[0])
    assert out["state"] == "done"
    results = rig.adapter.conversations[0].history[2]["items"]
    assert [r.call_id for r in results] == [f"id-{i}" for i in range(len(names))]
    assert all(r.is_error and "not available to a helper" in r.content for r in results)
    assert (rig.session.decisions, rig.session.frame, rig.session.state_hash()) == state
    assert rig.budget.model_calls == 2, "only the helper's own two calls were made"


def test_the_tools_a_helper_gets_can_be_narrowed(tmp_path: Path, game) -> None:
    script = [Say.tools(call("workspace_write", path="notes/x.md", text="x")), Say(text="done")]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    run(rig, tc("spawn_agent", task="Look.", tools=["view", "workspace_read"]))
    conv = rig.adapter.conversations[0]
    assert tool_names(conv) == {"view", "workspace_read"}
    # it asked for a tool it was not given
    assert conv.history[2]["items"][0].is_error
    assert rig.workspace.list()["files"] == []
    bad = run(rig, tc("spawn_agent", task="Go.", tools=["move"]))[0]
    assert bad.is_error and "bad_argument" in bad.content
    assert len(rig.adapter.conversations) == 1, "nothing was started"


def test_a_helper_cannot_start_one_that_can_do_more_than_it_can(tmp_path: Path, game) -> None:
    script = [
        # a1 may only look and start helpers; it starts a2 with the default tools
        Say.tools(call("spawn_agent", "in-1", task="Write it down.")),
        Say.tools(call("workspace_write", path="notes/x.md", text="x")),  # a2 tries the notebook
        Say(text="a2 done"),
        # and asks for tools it does not have itself
        Say.tools(call("spawn_agent", "in-2", task="Write.", tools=["workspace_write"])),
        Say(text="a1 done"),
    ]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    out = data(run(rig, tc("spawn_agent", task="Look.", tools=["view", "spawn_agent"]))[0])
    assert out["answer"] == "a1 done"
    a1, a2 = rig.adapter.conversations
    assert tool_names(a1) == {"view", *HELPER_TOOLS}
    assert tool_names(a2) == {"view"}, "a2 got what a1 had, not the player's everything"
    assert a2.history[2]["items"][0].is_error
    assert rig.workspace.list()["files"] == []
    asked = a1.history[-2]["items"][0]
    assert asked.is_error and "bad_argument" in asked.content and "workspace_write" in asked.content
    assert len(rig.ctx.extras["subagent_hub"].helpers) == 2, "the refused spawn started nobody"


def test_only_the_notebook_and_the_practice_range_are_offered_to_helpers(
    tmp_path: Path, game
) -> None:
    from noitabench.harness.model import ToolSpec
    from noitabench.harness.toolbox import FREE, ToolDef

    def with_lookalikes(ctx) -> None:
        register_l4(ctx)
        # tools of other layers may share a prefix with the notebook's
        for name in ("workspace_run", "wand_range_plus", "view_all"):
            spec = ToolSpec(name, "x", {"type": "object", "properties": {}})
            ctx.toolbox.register(ToolDef(spec, FREE, lambda _a: "ran"))

    rig = make_rig(tmp_path, game, [Say(text="ok")], register=with_lookalikes)
    run(rig, tc("spawn_agent", task="Look."))
    names = tool_names(rig.adapter.conversations[0])
    assert names.isdisjoint({"workspace_run", "wand_range_plus", "view_all"})
    assert {"workspace_read", "wand_range", "view"} <= names


def test_a_failing_tool_is_an_error_for_the_helper_not_a_crash(tmp_path: Path, game) -> None:
    script = [Say.tools(call("workspace_read", path="notes/x.md")), Say(text="could not read")]
    rig = make_rig(tmp_path, game, script, register=register_l4)

    def broken(*_a: Any, **_k: Any) -> Any:
        raise OSError("disk gone")

    rig.workspace.read = broken  # type: ignore[method-assign]
    out = data(run(rig, tc("spawn_agent", task="Read the note."))[0])
    assert out["state"] == "done"
    failed = rig.adapter.conversations[0].history[2]["items"][0]
    assert failed.is_error and "internal_error" in failed.content


def test_a_number_too_big_for_the_engine_is_an_answer_for_the_helper(tmp_path: Path, game) -> None:
    huge = {"mana_max": 9, "mana_per_second": 1, "cast_delay": 2**40, "recharge": 1, "capacity": 2}
    script = [
        Say.tools(call("wand_range", stats=huge, slots=[])),
        Say.tools(call("wand_range", wand=float("inf"))),
        Say(text="ok"),
    ]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    assert data(run(rig, tc("spawn_agent", task="Try a wand."))[0])["state"] == "done"
    history = rig.adapter.conversations[0].history
    assert history[2]["items"][0].is_error and history[4]["items"][0].is_error


def test_other_models_for_helpers_must_be_of_the_players_provider(tmp_path: Path, game) -> None:
    other = SubModel(ModelConfig("anthropic", "claude-haiku-5-5"), None)
    with pytest.raises(ConfigError, match="provider"):
        make_rig(
            tmp_path,
            game,
            [],
            register=lambda c: register_l4(c, SubAgentSettings(models={"cheap": other})),
        )


def test_view_shows_the_latest_answer_without_costing_anything(tmp_path: Path, game) -> None:
    script = [Say.tools(call("view")), Say(text="seen")]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    run(rig, tc("spawn_agent", task="Describe what is around the explorer."))
    conv = rig.adapter.conversations[0]
    shown = conv.history[2]["items"][0]
    assert not shown.is_error and shown.content == render_text(rig.session.observe())
    assert rig.session.decisions == 0


def test_bad_arguments_are_error_results(tmp_path: Path, game) -> None:
    rig = make_rig(tmp_path, game, register=register_l4)
    for args in (
        {},
        {"task": ""},
        {"task": 5},
        {"task": "x", "effort": "huge"},
        {"task": "x", "model": "big"},
    ):
        bad = run(rig, tc("spawn_agent", **args))[0]
        assert bad.is_error and "bad_argument" in bad.content, args
    assert rig.budget.model_calls == 0 and not rig.adapter.conversations


# -- money and logs -------------------------------------------------------------------------------


def test_every_helper_call_is_charged_to_the_shared_budget_and_logged(tmp_path: Path, game) -> None:
    script = [Say.tools(call("workspace_list")), Say(text="nothing there")]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    run(rig, tc("spawn_agent", task="List the notebook."))
    assert rig.budget.model_calls == 2 and rig.budget.spent_usd > 0
    hub = rig.ctx.extras["subagent_hub"]
    summary = hub.summary()
    assert summary["model_calls"] == 2 and summary["helpers"] == 1
    assert summary["cost_usd"] == pytest.approx(rig.budget.spent_usd, abs=1e-6)
    rows = harness_rows(rig)
    assert [r["agent"] for r in rows] == ["a1", "a1"] and [r["call"] for r in rows] == [1, 2]
    assert all(r["purpose"] == "helper" and r["cost_usd"] is not None for r in rows)
    assert rows[-1]["cumulative_usd"] == pytest.approx(rig.budget.spent_usd, abs=1e-6)
    kinds = [(r["kind"], r.get("agent"), r.get("event")) for r in transcript_rows(rig)]
    assert ("helper", "a1", "spawn") in kinds and ("helper", "a1", "answer") in kinds
    assert ("assistant", "a1", None) in kinds and ("results", "a1", None) in kinds


def test_the_allowance_stops_a_helper_before_its_next_call(tmp_path: Path, game) -> None:
    script = [Say.tools(call("workspace_list")), Say(text="never sent")]
    rig = make_rig(
        tmp_path, game, script, budget=Budget(max_usd=50.0, max_model_calls=1), register=register_l4
    )
    out = data(run(rig, tc("spawn_agent", task="Look around."))[0])
    assert out["state"] == "stopped" and "model calls" in out["stopped_because"]
    assert rig.budget.model_calls == 1


def test_unpriced_helpers_cost_nothing_and_say_so(tmp_path: Path, game) -> None:
    rig = make_rig(tmp_path, game, [Say(text="ok")], register=register_l4)
    rig.ctx.price = None
    run(rig, tc("spawn_agent", task="Say ok."))
    assert rig.budget.unpriced_calls == 1
    assert rig.ctx.extras["subagent_hub"].summary()["cost_usd"] is None


# -- limits ---------------------------------------------------------------------------------------


def test_a_helper_that_never_stops_is_stopped_and_can_be_sent_on(tmp_path: Path, game) -> None:
    script = [Say.tools(call("workspace_list")) for _ in range(3)] + [Say(text="Finished.")]
    rig = make_rig(
        tmp_path,
        game,
        script,
        register=lambda ctx: register_l4(ctx, SubAgentSettings(steps_per_message=3)),
    )
    out = data(run(rig, tc("spawn_agent", task="Keep looking."))[0])
    assert out["state"] == "stopped" and out["calls_used"] == 3
    assert "send it another" in out["stopped_because"]
    conv = rig.adapter.conversations[0]
    # the last allowed call was told to wrap up
    last = conv.history[-2]["items"]
    assert any(isinstance(i, UserText) and i.text == WRAP_UP for i in last)
    # going on sends the unanswered results first, then the message
    out = data(run(rig, tc("agent_message", id="a1", text="Now answer."))[0])
    assert out["state"] == "done" and out["answer"] == "Finished."
    assert_no_dangling_calls(conv)
    assert_no_orphan_results(conv)
    again = conv.history[-2]["items"]
    assert isinstance(again[0], ToolResult) and isinstance(again[-1], UserText)
    assert data(run(rig, tc("agent_list"))[0])["helpers"][0]["state"] == "done"


def test_a_helper_that_answered_is_not_sent_its_old_results_again(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("workspace_list", "c-1")),
        Say(text="first answer"),
        Say.tools(call("workspace_list", "c-2")),
        Say(text="second answer"),
        Say(text="third answer"),
    ]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    assert data(run(rig, tc("spawn_agent", task="Look."))[0])["answer"] == "first answer"
    out = data(run(rig, tc("agent_message", id="a1", text="Again."))[0])
    assert out["answer"] == "second answer"
    assert data(run(rig, tc("agent_message", id="a1", text="Once more."))[0])["state"] == "done"
    conv = rig.adapter.conversations[0]
    assert_no_orphan_results(conv)
    assert_no_dangling_calls(conv)
    sent = [
        [x.call_id for x in e["items"] if isinstance(x, ToolResult)]
        for e in conv.history
        if e["role"] == "user"
    ]
    assert sent == [[], ["c-1"], [], ["c-2"], []]


def test_the_number_of_helpers_and_their_calls_is_capped(tmp_path: Path, game) -> None:
    settings = SubAgentSettings(max_agents=2, total_calls=3, calls_per_agent=2)
    script = [Say(text="one"), Say.tools(call("workspace_list")), Say.tools(call("workspace_list"))]
    rig = make_rig(tmp_path, game, script, register=lambda c: register_l4(c, settings))
    assert data(run(rig, tc("spawn_agent", task="a"))[0])["state"] == "done"
    second = data(run(rig, tc("spawn_agent", task="b"))[0])
    assert second["state"] == "stopped" and second["calls_used"] == 2  # its own cap
    third = run(rig, tc("spawn_agent", task="c"))[0]
    assert third.is_error and "too_many_helpers" in third.content
    assert rig.budget.model_calls == 3


def test_a_refusing_model_stops_the_helper_without_spoiling_its_history(
    tmp_path: Path, game
) -> None:
    script = [Say(stop=REFUSAL), Say(text="back again")]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    out = data(run(rig, tc("spawn_agent", task="Do something."))[0])
    assert out["state"] == "stopped" and out["stopped_because"] == "the model declined"
    assert rig.adapter.conversations[0].history == []  # a refusal is not appended
    assert (
        data(run(rig, tc("agent_message", id="a1", text="Try again."))[0])["answer"] == "back again"
    )


def test_a_helper_stopped_before_it_was_told_its_task_is_still_told_it(
    tmp_path: Path, game
) -> None:
    script = [Say(error=ModelError("overloaded", "busy", retryable=True)), Say(text="Done now.")]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    out = data(run(rig, tc("spawn_agent", task="Note down the lava depth."))[0])
    assert out["state"] == "stopped" and "model_error" in out["stopped_because"]
    assert rig.budget.model_calls == 0, "a failed call is not charged"
    again = data(run(rig, tc("agent_message", id="a1", text="Try again."))[0])
    assert again["answer"] == "Done now."
    conv = rig.adapter.conversations[0]
    first = conv.history[0]["items"]
    assert [i.text for i in first] == ["Note down the lava depth.", "Try again."]
    assert_no_orphan_results(conv)


def test_only_the_starter_may_message_a_helper(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("spawn_agent", task="Inner job.")),  # a1 starts a2
        Say(text="inner done"),
        Say(text="outer done"),
    ]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    assert data(run(rig, tc("spawn_agent", task="Outer job."))[0])["answer"] == "outer done"
    assert data(run(rig, tc("agent_list"))[0])["helpers"][0]["id"] == "a1"  # a2 is a1's
    bad = run(rig, tc("agent_message", id="a2", text="hello"))[0]
    assert bad.is_error and "no_such_helper" in bad.content


def test_helpers_go_two_levels_deep(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("spawn_agent", task="level two")),  # a1 (depth 1) starts a2 (depth 2)
        Say.tools(call("spawn_agent", task="level three")),  # a2 tries; it was not given the tool
        Say(text="a2 done"),
        Say(text="a1 done"),
    ]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    out = data(run(rig, tc("spawn_agent", task="level one"))[0])
    assert out["answer"] == "a1 done"
    a1, a2 = rig.adapter.conversations
    assert set(HELPER_TOOLS) <= tool_names(a1)
    assert not set(HELPER_TOOLS) & tool_names(a2)
    refused = a2.history[2]["items"][0]
    assert refused.is_error and "not available to a helper" in refused.content
    assert len(rig.ctx.extras["subagent_hub"].helpers) == 2


# -- models and effort ----------------------------------------------------------------------------


class ConfiguredAdapter(ScriptedAdapter):
    """A scripted adapter that, like the real ones, keeps its `config` and `client`."""

    def __init__(self, script, config: ModelConfig) -> None:
        super().__init__(script, model=config.model)
        self.config = config
        self.client = object()


def test_effort_and_a_cheaper_model_come_from_sibling_adapters(tmp_path: Path, game) -> None:
    base = ModelConfig("fake", "big-model", effort="high")
    made: list[tuple[ModelConfig, Any]] = []
    siblings = iter([Say(text="low answer"), Say(text="cheap answer")])

    def factory(config: ModelConfig, shared: Any) -> ScriptedAdapter:
        made.append((config, shared))
        return ScriptedAdapter(siblings, model=config.model)

    cheap = SubModel(ModelConfig("fake", "small-model"), ModelPrice((PriceTier(None, 0.0, 0.0),)))
    settings = SubAgentSettings(models={"cheap": cheap}, adapter_factory=factory)
    adapter = ConfiguredAdapter([Say(text="big answer")], base)
    rig = make_rig(tmp_path, game, adapter=adapter, register=lambda c: register_l4(c, settings))
    run(rig, tc("spawn_agent", task="Same model.", effort="low"))
    assert made[0][0].model == "big-model" and made[0][0].effort == "low"
    assert made[0][1] is adapter, "the factory is given the player's adapter to share its client"
    spent = rig.budget.spent_usd
    out = data(run(rig, tc("spawn_agent", task="Cheaper model.", model="cheap"))[0])
    assert made[1][0].model == "small-model" and out["answer"] == "cheap answer"
    assert rig.budget.spent_usd == spent, "the cheap model's price (zero) is the one charged"
    schema = next(s for s in helper_specs(settings) if s.name == "spawn_agent").schema
    assert schema["properties"]["model"]["enum"] == ["same", "cheap"]
    plain = next(s for s in helper_specs(SubAgentSettings()) if s.name == "spawn_agent").schema
    assert "model" not in plain["properties"]
    assert made[0][0].provider == "fake"
    assert not adapter.conversations, "the player's own adapter was not used for the sibling"


# -- fork -----------------------------------------------------------------------------------------


def started_main(adapter: ScriptedAdapter, rig, opening: str = "Decision 1 ...") -> Any:
    """The player's conversation as the loop makes it, with its first turn already answered."""
    conv = adapter.new_conversation("PLAYER SYSTEM PROMPT", rig.toolbox.specs())
    return conv


def test_a_fork_is_a_new_conversation_over_a_copy_of_the_players(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("workspace_list"), text="Let me think."),  # the player's first turn
        Say.tools(call("fork_agent", "fk-1", task="Plan the wand."), text="I will ask a fork."),
        Say.tools(call("workspace_write", path="notes/plan.md", text="plan")),  # the fork's turns
        Say(text="Plan written."),
    ]
    adapter = ScriptedAdapter(script)
    rig = make_rig(tmp_path, game, adapter=adapter, register=register_l4)
    main = adapter.new_conversation("PLAYER SYSTEM PROMPT", rig.toolbox.specs())
    t1 = main.send([UserText("Decision 1: the cave.")])
    results = rig.toolbox.execute(t1.tool_calls).results
    t2 = main.send(list(results))
    before = copy.copy(main.history)
    before_deep = copy.deepcopy(main.history)
    out = data(rig.toolbox.execute(t2.tool_calls).results[0])
    assert out["answer"] == "Plan written." and out["state"] == "done"
    child = adapter.conversations[-1]
    assert child is not main
    # the same system prompt and tool list: the provider's cache prefix is the player's
    assert child.system == main.system and child.tools == main.tools
    # the whole history is copied (entries shared, not edited), the turn that asked for the fork
    # included; the fork's first message answers that turn's tool call
    assert len(before) == 4
    assert all(a is b for a, b in zip(child.history[:4], main.history, strict=True))
    briefing = child.history[4]["items"]
    assert [(r.call_id, r.name) for r in briefing] == [("fk-1", "fork_agent")]
    assert not briefing[0].is_error and "Plan the wand." in briefing[0].content
    assert "helper" in briefing[0].content
    assert "move" not in briefing[0].content.split("You can use")[1]
    assert_no_dangling_calls(child)
    # the player's conversation did not change
    assert main.history == before_deep and len(main.history) == 4
    assert all(a is b for a, b in zip(main.history, before, strict=True))
    assert rig.workspace.read("notes/plan.md")["text"] == "plan"


def test_a_fork_answers_every_call_of_the_turn_that_asked_for_it(tmp_path: Path, game) -> None:
    script = [
        Say.tools(
            call("workspace_list", "c-1"),
            call("fork_agent", "c-2", task="First opinion."),
            call("walk_to", "c-3", x=40),
            call("fork_agent", "c-4", task="Second opinion."),
        ),
        Say(text="first"),
        Say(text="second"),
    ]
    adapter = ScriptedAdapter(script)
    rig = make_rig(tmp_path, game, adapter=adapter, register=register_l4)
    main = adapter.new_conversation("SYS", rig.toolbox.specs())
    turn = main.send([UserText("opening")])
    out = rig.toolbox.execute(turn.tool_calls)
    first, second = adapter.conversations[1:]
    for child, mine in ((first, "c-2"), (second, "c-4")):
        briefing = child.history[2]["items"]
        assert [r.call_id for r in briefing] == ["c-1", "c-2", "c-3", "c-4"]
        for r in briefing:
            assert r.is_error == (r.call_id != mine), r
            assert ("not run" in r.content) == (r.call_id != mine)
        assert_no_dangling_calls(child)
    assert "First opinion." in first.history[2]["items"][1].content
    assert "Second opinion." in second.history[2]["items"][3].content
    # the player's own walk then ran: one decision, and the helpers cost none
    assert rig.session.decisions == 1
    assert [data(r)["answer"] for r in out.results if r.name == "fork_agent"] == ["first", "second"]


def test_a_fork_sees_the_game_tools_but_cannot_use_them(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("fork_agent", task="Walk for me.")),
        Say.tools(call("walk_to", x=10), call("budget"), call("workspace_list")),
        Say(text="Could not."),
    ]
    adapter = ScriptedAdapter(script)
    rig = make_rig(tmp_path, game, adapter=adapter, register=register_l4)
    main = adapter.new_conversation("SYS", rig.toolbox.specs())
    t = main.send([UserText("opening")])
    frame = rig.session.frame
    out = data(rig.toolbox.execute(t.tool_calls).results[0])
    child = adapter.conversations[-1]
    assert "walk_to" in tool_names(child), "the tool list is the player's own"
    walk, budget, ls = child.history[4]["items"]
    assert walk.is_error and "not available" in walk.content
    assert budget.is_error and "not available" in budget.content
    assert not ls.is_error
    assert rig.session.frame == frame and rig.session.decisions == 0
    assert out["state"] == "done"


def test_a_fork_can_be_given_fewer_tools(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("fork_agent", task="Only look.", tools=["view"])),
        Say.tools(call("workspace_list"), call("view")),
        Say(text="ok"),
    ]
    adapter = ScriptedAdapter(script)
    rig = make_rig(tmp_path, game, adapter=adapter, register=register_l4)
    main = adapter.new_conversation("SYS", rig.toolbox.specs())
    t = main.send([UserText("opening")])
    rig.toolbox.execute(t.tool_calls)
    listing, view = adapter.conversations[-1].history[4]["items"]
    assert listing.is_error and not view.is_error


def test_a_fork_needs_a_conversation_and_not_too_long_a_one(tmp_path: Path, game) -> None:
    rig = make_rig(tmp_path, game, [], register=register_l4)
    none = run(rig, tc("fork_agent", task="x"))[0]
    assert none.is_error and "cannot_fork" in none.content
    adapter = ScriptedAdapter([Say.tools(call("fork_agent", task="x"))])
    rig = make_rig(
        tmp_path / "b",
        game,
        adapter=adapter,
        register=lambda c: register_l4(c, SubAgentSettings(prompt_limit=5)),
    )
    main = adapter.new_conversation("A SYSTEM PROMPT OF SOME LENGTH", rig.toolbox.specs())
    t = main.send([UserText("opening " * 50)])
    long = rig.toolbox.execute(t.tool_calls).results[0]
    assert long.is_error and "too_long_to_fork" in long.content
    assert len(adapter.conversations) == 1, "no child was opened"


def test_a_forked_helper_can_fork_in_turn_once(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("fork_agent", task="level one")),
        Say.tools(call("fork_agent", task="level two")),  # a1 forks its own conversation
        Say.tools(call("fork_agent", task="level three")),  # a2 is at depth 2: not allowed
        Say(text="two done"),
        Say(text="one done"),
    ]
    adapter = ScriptedAdapter(script)
    rig = make_rig(tmp_path, game, adapter=adapter, register=register_l4)
    main = adapter.new_conversation("SYS", rig.toolbox.specs())
    t = main.send([UserText("opening")])
    out = data(rig.toolbox.execute(t.tool_calls).results[0])
    assert out["answer"] == "one done"
    _main, a1, a2 = adapter.conversations
    assert a2.history[:4] == a1.history[:4], "a2 copies a1's history, not the player's"
    refused = a2.history[6]["items"][0]
    assert refused.is_error and "not available" in refused.content
    helpers = rig.ctx.extras["subagent_hub"].helpers
    assert [h.depth for h in helpers.values()] == [1, 2]


def test_fork_conversation_refuses_what_it_cannot_copy() -> None:
    adapter = ScriptedAdapter([])
    odd = adapter.new_conversation("S", [])
    odd.history = [{"role": "user", "items": []}]  # no turn to cut off
    with pytest.raises(CommandError) as err:
        fork_conversation(adapter, odd, "S", [])
    assert err.value.code == "cannot_fork"

    class Bare:
        last_prompt_tokens = 0

    with pytest.raises(CommandError):
        fork_conversation(adapter, Bare(), "S", [])  # type: ignore[arg-type]


def test_the_link_follows_the_players_conversations_and_ignores_the_helpers() -> None:
    adapter = ScriptedAdapter([])
    link = ParentLink()
    link.follow(adapter)
    first = adapter.new_conversation("one", [])
    assert link.conversation is first and link.system == "one"
    with link.muted():
        adapter.new_conversation("helper", [])
    assert link.conversation is first
    second = adapter.new_conversation("two", [])  # a briefing started a new conversation
    assert link.conversation is second and link.system == "two"
    link.bind(first, "explicit", [])
    assert link.conversation is first and link.system == "explicit"


def test_a_second_game_on_the_same_adapter_takes_over_the_link() -> None:
    adapter = ScriptedAdapter([])
    first, second = ParentLink(), ParentLink()
    first.follow(adapter)
    wrapper = adapter.new_conversation
    second.follow(adapter)
    assert adapter.new_conversation is wrapper, "not wrapped a second time"
    conversation = adapter.new_conversation("S", [])
    assert second.conversation is conversation and first.conversation is None
    with second.muted():
        adapter.new_conversation("helper", [])
    assert second.conversation is conversation


# -- inside the real loop -------------------------------------------------------------------------


def test_helpers_work_inside_the_real_loop(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("fork_agent", task="What do I carry?"), text="Asking."),
        Say.tools(call("view")),  # the fork looks
        Say(text="You carry two wands."),
        Say.tools(call("wait", ticks=1)),
        Say.tools(call("wait", ticks=1)),
    ]
    adapter = ScriptedAdapter(script)
    rig = make_rig(tmp_path, game, adapter=adapter, register=register_l4, max_decisions=2)
    loop = AgentLoop(
        session=rig.session,
        adapter=adapter,
        toolbox=rig.toolbox,
        workspace=rig.workspace,
        budget=rig.budget,
        price=rig.ctx.price,
        logs=rig.logs,
        system=system_prompt(mode="tools", notes_kept=True),
        config=LoopConfig(context="none"),
    )
    result = loop.run()
    assert result.over == "decision_limit" and result.decisions == 2
    main, child = adapter.conversations
    assert child.system == main.system and child.tools == main.tools
    # the fork was made of the player's first message
    assert child.history[0] is main.history[0]
    assert child.history[0]["items"][0].text.startswith("Decision 1")
    # the loop's own accounting and the helper's both reach the one budget: 4 + 2 model calls...
    assert rig.budget.model_calls == 5
    assert result.model_calls == 5 and rig.ctx.extras["subagent_hub"].summary()["model_calls"] == 2
    assert result.cost_usd < rig.budget.spent_usd, "the loop's cost is the player's own"
    rows = harness_rows(rig)
    assert [r.get("agent") for r in rows].count("a1") == 2
    assert_no_dangling_calls(child)
    assert_no_dangling_calls(main, last_open=True)


def test_what_helpers_spend_counts_against_the_players_allowance(tmp_path: Path, game) -> None:
    script = [
        Say.tools(call("fork_agent", task="Think.")),  # the player's call 1
        Say(text="Thought."),  # the fork's call 2
        Say.tools(call("wait", ticks=1)),  # never made: the allowance is used up
    ]
    adapter = ScriptedAdapter(script)
    budget = Budget(max_usd=50.0, max_model_calls=2)
    rig = make_rig(tmp_path, game, adapter=adapter, budget=budget, register=register_l4)
    loop = AgentLoop(
        session=rig.session,
        adapter=adapter,
        toolbox=rig.toolbox,
        workspace=rig.workspace,
        budget=rig.budget,
        price=rig.ctx.price,
        logs=rig.logs,
        system=system_prompt(mode="tools", notes_kept=True),
        config=LoopConfig(context="none"),
    )
    result = loop.run()
    assert result.over == "budget_calls", "the player made one call; the helper's made two"
    assert rig.budget.model_calls == 2 and result.decisions == 0
    assert result.cost_usd < rig.budget.spent_usd, "the loop's own cost leaves the helper's out"
    assert rig.budget.spent_usd == pytest.approx(
        result.cost_usd + rig.ctx.extras["subagent_hub"].summary()["cost_usd"], abs=1e-9
    )


def test_money_alone_stops_a_helper_too(tmp_path: Path, game) -> None:
    script = [Say.tools(call("workspace_list")) for _ in range(5)]
    rig = make_rig(tmp_path, game, script, budget=Budget(max_usd=1e-9), register=register_l4)
    out = data(run(rig, tc("spawn_agent", task="Look."))[0])
    assert out["state"] == "stopped" and "money" in out["stopped_because"]
    assert rig.budget.model_calls == 1, "the first call is made; the next one does not fit"


def test_a_helper_does_not_take_the_notices_meant_for_the_players_turn(
    tmp_path: Path, game
) -> None:
    script = [Say.tools(call("workspace_list")), Say(text="listed")]
    rig = make_rig(tmp_path, game, script, register=register_l4)
    rig.toolbox.add_notice("A hook says: the water is rising.")
    out = run(rig, tc("spawn_agent", task="List the notebook."))[0]
    helper_result = rig.adapter.conversations[0].history[2]["items"][0]
    assert "water is rising" not in helper_result.content
    # the notice reaches the end of the player's own turn
    assert "water is rising" in out.content


def test_the_hub_and_the_link_are_left_in_the_context_for_the_runner(tmp_path: Path, game) -> None:
    rig = make_rig(tmp_path, game, register=register_l4)
    assert isinstance(rig.ctx.extras["parent_link"], ParentLink)
    assert rig.ctx.extras["subagent_hub"].summary()["helpers"] == 0
