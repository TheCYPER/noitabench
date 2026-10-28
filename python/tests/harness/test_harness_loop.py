"""Whole games through the real loop, with a scripted model: no network, no cost."""

from __future__ import annotations

import copy
import itertools
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from noitabench.harness import (
    ConfigError,
    ModelConfig,
    ModelError,
    RunConfig,
    ToolResult,
    Usage,
    UserText,
    run_family,
)
from noitabench.harness.adapters.scripted import Say, ScriptedAdapter, ScriptedConversation, call
from noitabench.harness.model import MAX_TOKENS, REFUSAL
from noitabench.harness.prices import custom_price
from noitabench.harness.prompt import (
    NUDGE_CUT_OFF,
    NUDGE_NO_COMMAND,
    NUDGE_NO_TOOL,
    SUMMARY_REQUEST,
)
from noitabench.harness.redact import HIDDEN, set_default_redactor
from test_harness_redact import fake_value, only_values


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def tree(folder: Path) -> dict[str, str]:
    """The files under `folder` as `{relative path: text}`."""
    return {
        f.relative_to(folder).as_posix(): f.read_text(encoding="utf-8")
        for f in sorted(folder.rglob("*"))
        if f.is_file()
    }


def waits(n: int) -> list[Say]:
    return [Say.tools(call("wait", ticks=1)) for _ in range(n)]


def play(run_config, make_game, script, **overrides):
    cfg = run_config(**overrides)
    adapter = ScriptedAdapter(script)
    summary = run_family(cfg, adapter=adapter, game_factory=make_game, sleep=lambda _s: None)[0]
    return cfg, adapter, summary


# -- a whole game in tools mode -------------------------------------------------------------------


def test_a_game_to_the_step_limit_writes_every_file(run_config, make_game) -> None:
    script = [
        Say.tools(call("workspace_write", path="notes/a.md", text="water is wet"), text="Notes."),
        Say.tools(call("move", direction="right", ticks=3)),
        Say.tools(call("aim", angle=30), call("kick")),
        *waits(30),
    ]
    cfg, _adapter, summary = play(run_config, make_game, script, max_decisions=6)
    result = summary["result"]
    assert result["over"] == "decision_limit" and result["decisions"] == 6
    # model calls: the notebook turn costs none of the six steps, the others cost one each
    assert result["model_calls"] == 7
    for name in (
        "summary.json",
        "harness.jsonl",
        "transcript.jsonl",
        "decisions.jsonl",
        "meta.json",
        "frames.bin",
        "workspace/notes/a.md",
    ):
        assert (cfg.out / name).exists(), name
    assert (cfg.out / "workspace/notes/a.md").read_text() == "water is wet"
    saved = json.loads((cfg.out / "summary.json").read_text())
    assert saved["format"] == "cogbench-harness-run/0" and saved["cost_known"] is True
    assert saved["layers"] == ["L0", "L1"] and saved["mode"] == "tools"
    assert saved["workspace"]["files"] == ["notes/a.md"]
    assert len(lines(cfg.out / "decisions.jsonl")) == 6 - 1 + 1 - 1 + 1  # one line per decision


def test_harness_log_has_one_line_per_call_and_no_prompts_or_keys(run_config, make_game) -> None:
    cfg, _, _ = play(run_config, make_game, waits(10), max_decisions=3)
    rows = lines(cfg.out / "harness.jsonl")
    assert [r["call"] for r in rows] == [1, 2, 3]
    keys = {
        "call", "ts", "purpose", "provider", "model", "decision", "input_tokens",
        "cache_read_tokens", "cache_write_tokens", "output_tokens", "thinking_tokens",
        "prompt_tokens", "cost_usd", "cumulative_usd", "latency_s", "stop_reason", "request_id",
    }  # fmt: skip
    assert keys <= set(rows[0])
    assert rows[0]["provider"] == "fake" and rows[0]["purpose"] == "play"
    raw = (cfg.out / "harness.jsonl").read_text()
    assert "Get as deep" not in raw and "Position x=" not in raw  # no prompts, no observations


def test_transcript_records_what_was_said_done_and_answered(run_config, make_game) -> None:
    script = [
        Say(text="I will wait.", thinking="a quiet start", calls=(call("wait", ticks=1),)),
        *waits(3),
    ]
    cfg, _, _ = play(run_config, make_game, script, max_decisions=2)
    rows = lines(cfg.out / "transcript.jsonl")
    kinds = [r["kind"] for r in rows]
    assert (
        kinds[0] == "opening" and kinds[-1] == "end" and "assistant" in kinds and "results" in kinds
    )
    first = next(r for r in rows if r["kind"] == "assistant")
    assert first["text"] == "I will wait." and first["thinking"] == "a quiet start"
    assert first["tool_calls"][0]["name"] == "wait" and first["tool_calls"][0]["arguments"] == {
        "ticks": 1
    }
    results = next(r for r in rows if r["kind"] == "results")
    assert results["results"][0]["content"].startswith("Decision 2")
    assert rows[-1]["over"] == "decision_limit"
    assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1))


def test_the_model_sees_the_system_prompt_the_tools_and_the_opening_view(
    run_config, make_game
) -> None:
    _cfg, adapter, _ = play(run_config, make_game, waits(3), max_decisions=1)
    conv = adapter.conversations[0]
    assert "Get as deep as you can." in conv.system
    names = [t.name for t in conv.tools]
    assert "walk_to" in names and "workspace_write" in names and "budget" in names
    opening = conv.history[0]["items"][0]
    assert isinstance(opening, UserText)
    assert opening.text.startswith("Decision 1") and "Your notebook is empty" in opening.text


def test_history_is_append_only(run_config, make_game) -> None:
    seen: list[list[dict[str, Any]]] = []

    def watch(conv: ScriptedConversation, _items) -> Say:
        seen.append(copy.deepcopy(conv.history))
        return Say.tools(call("wait", ticks=1))

    play(run_config, make_game, [watch] * 8, max_decisions=7)
    assert len(seen) == 7
    for before, after in itertools.pairwise(seen):
        assert after[: len(before)] == before  # nothing earlier was touched
        assert len(after) == len(before) + 2  # one user message and one answer were added


def test_the_results_of_a_turn_go_back_in_one_message_in_call_order(run_config, make_game) -> None:
    sent: list[list[Any]] = []

    def second(_conv, items) -> Say:
        sent.append(list(items))
        return Say.tools(call("wait", ticks=1))

    script = [
        Say.tools(call("budget", "b1"), call("kick", "k1"), call("workspace_list", "l1")),
        second,
        *waits(3),
    ]
    play(run_config, make_game, script, max_decisions=2)
    items = sent[0]
    assert all(isinstance(i, ToolResult) for i in items)
    assert [i.call_id for i in items] == ["b1", "k1", "l1"]


# -- text mode ------------------------------------------------------------------------------------


def test_text_mode_plays_with_commands_in_prose(run_config, make_game) -> None:
    script = [
        Say(text="Let me look around.\nwalk_to(x=60)"),
        Say(text="```\naim(angle=10); kick\n```"),
        Say(text="budget"),
        Say(text="memory_write(path='notes/t.md', text='ok')"),
        *[Say(text="wait(ticks=1)")] * 10,
    ]
    cfg, adapter, summary = play(run_config, make_game, script, mode="text", max_decisions=5)
    conv = adapter.conversations[0]
    assert conv.tools == ()  # no tools are offered
    assert "walk_to(" in conv.system and "end your message with the commands" in conv.system.lower()
    assert summary["result"]["over"] == "decision_limit"
    replies = [h["items"][0] for h in conv.history if h["role"] == "user"]
    assert replies[1].text.startswith("Decision 2")
    assert '"steps_left"' in replies[3].text  # `budget` answered without a decision
    assert (cfg.out / "workspace/notes/t.md").read_text() == "ok"  # memory_* reaches the workspace


def test_text_mode_prose_that_starts_like_a_command_is_not_sent_to_the_game(
    run_config, make_game
) -> None:
    script = [
        Say(text="wait for the enemy to come closer."),  # prose: nudged, no decision spent
        Say(text="Fire it now!\nmove right"),
        Say(text="wait(ticks=1)"),
        *[Say(text="wait(ticks=1)")] * 5,
    ]
    _, adapter, summary = play(run_config, make_game, script, mode="text", max_decisions=3)
    assert summary["result"]["stalls"] == 2
    sent = [h["items"][0].text for h in adapter.conversations[0].history if h["role"] == "user"]
    assert sent[1] == NUDGE_NO_COMMAND and sent[2] == NUDGE_NO_COMMAND
    assert all("syntax" not in t and "invalid" not in t.lower() for t in sent[1:])
    assert summary["result"]["decisions"] == 3  # the three real commands, nothing wasted


def test_text_mode_notes_commands_cost_no_decision_as_in_tools_mode(run_config, make_game) -> None:
    script = [
        Say(text="memory_write(path='notes/a.md', text='lava is hot')"),
        Say(text="memory_list"),
        Say(text="wait(ticks=1)"),
        *[Say(text="wait(ticks=1)")] * 5,
    ]
    _, _, text_mode = play(run_config, make_game, script, mode="text", max_decisions=3)
    tool_script = [
        Say.tools(call("workspace_write", path="notes/a.md", text="lava is hot")),
        Say.tools(call("workspace_list")),
        Say.tools(call("wait", ticks=1)),
        *waits(5),
    ]
    _, _, tools = play(
        run_config, make_game, tool_script, max_decisions=3, out=run_config().out.parent / "t"
    )
    assert tools["result"]["decisions"] == 3 and tools["result"]["model_calls"] == 5
    assert text_mode["result"]["model_calls"] == tools["result"]["model_calls"]


def test_text_mode_without_a_command_is_nudged_then_stops(run_config, make_game) -> None:
    script = [Say(text="I think I will rest.")] * 5
    _, adapter, summary = play(run_config, make_game, script, mode="text")
    assert summary["result"]["over"] == "stalled"
    sent = [h["items"][0].text for h in adapter.conversations[0].history if h["role"] == "user"]
    assert NUDGE_NO_COMMAND in sent


# -- limits ---------------------------------------------------------------------------------------


def test_the_money_budget_stops_the_game_cleanly(run_config, make_game) -> None:
    dear = Usage(input_tokens=1_000_000)  # $1 a call at $1 per million
    script = [Say(calls=(call("wait", ticks=1),), usage=dear) for _ in range(20)]
    cfg, _, summary = play(
        run_config,
        make_game,
        script,
        price=custom_price(1.0, 1.0),
        budget_usd=2.5,
        max_decisions=50,
        context="none",
    )
    r = summary["result"]
    assert r["over"] == "budget_usd" and r["model_calls"] == 2  # a third call might not fit
    assert r["cost_usd"] == pytest.approx(2.0)
    assert summary["budget"]["spent_usd"] == pytest.approx(2.0)
    rows = lines(cfg.out / "harness.jsonl")
    assert [x["cumulative_usd"] for x in rows] == [1.0, 2.0]
    assert lines(cfg.out / "transcript.jsonl")[-1]["over"] == "budget_usd"
    assert (cfg.out / "summary.json").exists()  # a stopped run is still written up


def test_the_model_call_cap_stops_a_game_that_never_acts(run_config, make_game) -> None:
    script = [Say.tools(call("workspace_list")) for _ in range(20)]  # costs no decision
    _, _, summary = play(run_config, make_game, script, max_model_calls=4, max_decisions=50)
    assert summary["result"]["over"] == "budget_calls"
    assert summary["result"]["decisions"] == 0 and summary["result"]["model_calls"] == 4


def test_all_calls_count_including_the_briefing(run_config, make_game) -> None:
    script = [
        Say.tools(call("wait", ticks=1), usage=Usage(input_tokens=2_000, output_tokens=10)),
        Say(text="briefing", usage=Usage(input_tokens=5_000, output_tokens=10)),
        *waits(5),
    ]
    _, _, summary = play(
        run_config,
        make_game,
        script,
        price=custom_price(1.0, 1.0),
        context_limit=1_000,
        max_decisions=2,
    )
    assert summary["result"]["summaries"] == 1
    assert summary["budget"]["model_calls"] == summary["result"]["model_calls"] >= 3
    assert summary["budget"]["spent_usd"] > (2_000 + 5_000 + 20) / 1e6 - 1e-9


def test_unpriced_models_cannot_run_unless_allowed(run_config, make_game) -> None:
    cfg = run_config(model=ModelConfig("fake", "mystery-model"))
    with pytest.raises(ConfigError, match="no price"):
        run_family(cfg, adapter=ScriptedAdapter([]), game_factory=make_game)
    allowed = run_config(
        model=ModelConfig("fake", "mystery-model"), allow_unpriced=True, max_decisions=2
    )
    summary = run_family(allowed, adapter=ScriptedAdapter(waits(5)), game_factory=make_game)[0]
    assert summary["cost_known"] is False and summary["result"]["cost_usd"] is None
    assert summary["budget"]["unpriced_calls"] == summary["result"]["model_calls"]
    # a cap in dollars cannot be kept without a price
    capped = run_config(
        model=ModelConfig("fake", "mystery-model"), allow_unpriced=True, budget_usd=1.0
    )
    with pytest.raises(ConfigError, match="needs a price"):
        run_family(capped, adapter=ScriptedAdapter([]), game_factory=make_game)


# -- things that go wrong -------------------------------------------------------------------------


def test_a_turn_with_no_tool_call_is_nudged_and_three_in_a_row_stop_the_run(
    run_config, make_game
) -> None:
    script = [
        Say(text="hmm"),
        Say(text="still thinking"),
        *waits(2),
        Say(text="x"),
        Say(text="y"),
        Say(text="z"),
    ]
    _, adapter, summary = play(run_config, make_game, script, max_decisions=50)
    sent = [h["items"][0] for h in adapter.conversations[0].history if h["role"] == "user"]
    assert UserText(NUDGE_NO_TOOL) in sent
    assert summary["result"]["over"] == "stalled" and summary["result"]["stalls"] == 5


def test_a_cut_off_answer_is_followed_by_a_short_request(run_config, make_game) -> None:
    script = [Say(text="a very long thought", stop=MAX_TOKENS, calls=(call("kick"),)), *waits(3)]
    _, adapter, summary = play(run_config, make_game, script, max_decisions=2)
    hist = adapter.conversations[0].history
    assert hist[2]["role"] == "user" and hist[2]["items"] == [UserText(NUDGE_CUT_OFF)]
    assert hist[1]["calls"] == []  # the half-finished tool call was dropped
    assert summary["result"]["over"] == "decision_limit"


def test_a_refusal_is_tried_once_more_then_ends_the_run(run_config, make_game) -> None:
    sent: list[Any] = []

    def refuse(_conv, items) -> Say:
        sent.append(list(items))
        return Say(stop=REFUSAL)

    _cfg, adapter, summary = play(run_config, make_game, [refuse, refuse, refuse])
    assert summary["result"]["over"] == "refusal"
    assert sent[0] == sent[1] and len(sent) == 2  # the same step is sent again, once
    assert adapter.conversations[0].history == []  # a refused answer is never part of it


def test_a_refused_call_is_still_paid_for_and_logged(run_config, make_game) -> None:
    # the refused request was processed (a classifier that fires mid-answer bills normally)
    refused = Say(stop=REFUSAL, usage=Usage(input_tokens=1_000_000))
    cfg, _, summary = play(
        run_config, make_game, [refused, refused, refused], price=custom_price(1.0, 1.0)
    )
    assert summary["result"]["over"] == "refusal" and summary["result"]["model_calls"] == 2
    assert summary["result"]["cost_usd"] == pytest.approx(2.0)
    assert summary["budget"]["spent_usd"] == pytest.approx(2.0)
    rows = lines(cfg.out / "harness.jsonl")
    assert [r["stop_reason"] for r in rows] == ["refusal", "refusal"]


def test_a_refusal_once_does_not_end_the_run(run_config, make_game) -> None:
    script = [Say(stop=REFUSAL), *waits(5)]
    _, adapter, summary = play(run_config, make_game, script, max_decisions=2)
    assert summary["result"]["over"] == "decision_limit"
    assert len(adapter.conversations[0].history) == 4  # the refusal left no trace


def test_a_failing_model_is_retried_with_a_pause_then_given_up(run_config, make_game) -> None:
    pauses: list[float] = []
    busy = ModelError("rate_limit", "slow down", status=429, retryable=True)
    script = [Say(error=busy), Say(error=busy), *waits(3)]
    cfg = run_config(max_decisions=2)
    adapter = ScriptedAdapter(script)
    summary = run_family(cfg, adapter=adapter, game_factory=make_game, sleep=pauses.append)[0]
    assert summary["result"]["over"] == "decision_limit"
    assert pauses == [2.0, 4.0]
    errors = [r for r in lines(cfg.out / "harness.jsonl") if "error" in r]
    assert len(errors) == 2 and errors[0]["error"]["kind"] == "rate_limit"

    pauses.clear()
    script = [Say(error=busy)] * 5
    summary = run_family(
        run_config(max_decisions=2, out=cfg.out.parent / "again"),
        adapter=ScriptedAdapter(script),
        game_factory=make_game,
        sleep=pauses.append,
    )[0]
    assert (
        summary["result"]["over"] == "model_error" and "rate_limit" in summary["result"]["detail"]
    )
    assert len(pauses) == 2  # two more tries after the first failure, then it gives up


def test_a_fatal_error_ends_the_run_at_once_and_is_written_up(run_config, make_game) -> None:
    bad = ModelError("auth", "invalid x-api-key sk-ant-api03-ABCDEFGHIJKLMNOP", status=401)
    cfg, _, summary = play(run_config, make_game, [Say(error=bad)])
    assert summary["result"]["over"] == "model_error"
    assert "auth" in summary["result"]["detail"]
    everything = "".join(p.read_text(errors="ignore") for p in cfg.out.glob("*.json*"))
    assert "ABCDEFGHIJKLMNOP" not in everything and "[redacted]" in everything


@pytest.mark.parametrize(("kind", "status"), [("auth", 401), ("permission", 403)])
def test_a_refused_key_stops_the_family_after_the_first_game(
    run_config, make_game, tmp_path: Path, kind: str, status: int
) -> None:
    refused = ModelError(kind, "Authentication Fails, your api key is invalid", status=status)
    cfg = run_config(max_decisions=3, runs=3, out=tmp_path / "fam")
    adapter = ScriptedAdapter([Say(error=refused)] * 3)
    summaries = run_family(cfg, adapter=adapter, game_factory=make_game, sleep=lambda _s: None)
    assert len(summaries) == 1 and len(adapter.conversations) == 1  # games 2 and 3 never began
    assert summaries[0]["result"]["detail"].startswith(f"{kind}:")
    assert not (cfg.out / "run-02").exists()
    assert len(json.loads((cfg.out / "family.json").read_text())["runs"]) == 1


def test_an_error_that_may_pass_does_not_stop_the_family(
    run_config, make_game, tmp_path: Path
) -> None:
    busy = ModelError("rate_limit", "slow down", status=429, retryable=True)
    cfg = run_config(max_decisions=1, runs=2, out=tmp_path / "fam")
    adapter = ScriptedAdapter([Say(error=busy)] * 3 + waits(3))
    summaries = run_family(cfg, adapter=adapter, game_factory=make_game, sleep=lambda _s: None)
    assert [s["result"]["over"] for s in summaries] == ["model_error", "decision_limit"]


def test_an_interrupted_run_is_still_closed_and_written(run_config, make_game) -> None:
    def interrupt(_conv, _items) -> Say:
        raise KeyboardInterrupt

    cfg = run_config()
    with pytest.raises(KeyboardInterrupt):
        run_family(cfg, adapter=ScriptedAdapter([interrupt]), game_factory=make_game)
    saved = json.loads((cfg.out / "summary.json").read_text())
    assert saved["result"]["over"] == "aborted"
    assert (cfg.out / "meta.json").exists()


# -- the notebook ---------------------------------------------------------------------------------


def test_quota_refusals_reach_the_model_as_errors_and_the_game_goes_on(
    run_config, make_game
) -> None:
    seen: list[ToolResult] = []

    def look(_conv, items) -> Say:
        seen.extend(i for i in items if isinstance(i, ToolResult))
        return Say.tools(call("wait", ticks=1))

    script = [
        Say.tools(call("workspace_write", "w1", path="notes/big.md", text="x" * 9_000)),
        look,
        *waits(3),
    ]
    cfg, _, summary = play(run_config, make_game, script, max_decisions=2)
    assert seen[0].is_error and seen[0].content.startswith("notes_full: No room")
    assert not (cfg.out / "workspace/notes/big.md").exists()
    assert summary["result"]["over"] == "decision_limit"


def test_paths_that_leave_the_workspace_are_refused(run_config, make_game, tmp_path: Path) -> None:
    seen: list[ToolResult] = []

    def look(_conv, items) -> Say:
        seen.extend(i for i in items if isinstance(i, ToolResult))
        return Say.tools(call("wait", ticks=1))

    script = [
        Say.tools(
            call("workspace_write", "e1", path="../escape.md", text="x"),
            call("workspace_write", "e2", path="/tmp/escape.md", text="x"),
            call("workspace_read", "e3", path="notes/../../escape.md"),
        ),
        look,
        *waits(3),
    ]
    cfg, _, _ = play(run_config, make_game, script, max_decisions=2)
    assert [r.call_id for r in seen] == ["e1", "e2", "e3"]
    assert all(r.is_error and r.content.startswith("bad_path") for r in seen)
    assert not (tmp_path / "escape.md").exists() and not (cfg.out.parent / "escape.md").exists()


def test_second_game_opens_with_the_first_games_notes(run_config, make_game) -> None:
    opening_texts: list[str] = []

    def first_turn(conv: ScriptedConversation, items) -> Say:
        opening_texts.append(items[0].text)
        return Say.tools(call("workspace_write", path="notes/lesson.md", text="lava is hot"))

    script = [first_turn, *waits(2), first_turn, *waits(2)]
    cfg = run_config(runs=2, family="fam", max_decisions=2)
    run_family(cfg, adapter=ScriptedAdapter(script), game_factory=make_game, sleep=lambda _s: None)
    assert "Your notebook is empty" in opening_texts[0]
    assert "notes/lesson.md (11 characters)" in opening_texts[1]
    assert (cfg.out / "run-01" / "workspace" / "notes" / "lesson.md").exists()
    assert (cfg.out / "run-02" / "summary.json").exists()
    family = json.loads((cfg.out / "family.json").read_text())
    assert [r["world_seed"] for r in family["runs"]] == [1, 2]
    # each run folder says what its game began with: nothing, then the first game's notebook
    first, second = cfg.out / "run-01", cfg.out / "run-02"
    assert (first / "workspace_start").is_dir() and tree(first / "workspace_start") == {}
    assert tree(second / "workspace_start") == tree(first / "workspace") != {}
    assert tree(second / "workspace_start") == {"notes/lesson.md": "lava is hot"}


def test_control_setting_empties_the_workspace_before_each_game(run_config, make_game) -> None:
    opening_texts: list[str] = []
    systems: list[str] = []

    def first_turn(conv: ScriptedConversation, items) -> Say:
        opening_texts.append(items[0].text)
        systems.append(conv.system)
        return Say.tools(call("workspace_write", path="notes/lesson.md", text="lava is hot"))

    script = [first_turn, *waits(2), first_turn, *waits(2)]
    cfg = run_config(runs=2, family="ctl", clear_workspace=True, max_decisions=2)
    run_family(cfg, adapter=ScriptedAdapter(script), game_factory=make_game, sleep=lambda _s: None)
    assert all("Your notebook is empty" in t for t in opening_texts)
    assert all(
        "kept when the game is over" not in s for s in systems
    )  # nor does it promise to keep
    assert tree(cfg.out / "run-01" / "workspace") == {"notes/lesson.md": "lava is hot"}
    for name in ("run-01", "run-02"):  # the control group begins every game with nothing
        assert tree(cfg.out / name / "workspace_start") == {}


def test_the_start_copy_holds_the_notebook_the_family_folder_already_had(
    run_config, make_game
) -> None:
    cfg = run_config(family="old", max_decisions=2)
    notes = cfg.workspaces_dir / "old" / "notes"
    notes.mkdir(parents=True)
    (notes / "earlier.md").write_text("water puts out fire", encoding="utf-8")
    run_family(
        cfg, adapter=ScriptedAdapter(waits(4)), game_factory=make_game, sleep=lambda _s: None
    )
    assert tree(cfg.out / "workspace_start") == {"notes/earlier.md": "water puts out fire"}
    assert tree(cfg.out / "workspace") == {"notes/earlier.md": "water puts out fire"}


def test_the_start_copy_is_cleaned_of_secrets_like_the_end_copy(run_config, make_game) -> None:
    secret = fake_value("start")
    previous = set_default_redactor(only_values(secret))
    try:
        cfg = run_config(family="sec", max_decisions=2)
        notes = cfg.workspaces_dir / "sec" / "notes"
        notes.mkdir(parents=True)
        (notes / "key.md").write_text(f"token {secret} stays", encoding="utf-8")
        run_family(
            cfg, adapter=ScriptedAdapter(waits(4)), game_factory=make_game, sleep=lambda _s: None
        )
    finally:
        set_default_redactor(previous)
    start = tree(cfg.out / "workspace_start")
    assert start == {"notes/key.md": f"token {HIDDEN} stays"} and secret not in str(start)


def test_game_seeds_follow_the_family(run_config) -> None:
    seeds: list[int] = []

    def factory(seed: int, _folder: Path):
        seeds.append(seed)
        raise RuntimeError("stop here")

    cfg = run_config(runs=3, world_seed=40)
    with pytest.raises(RuntimeError):
        run_family(cfg, adapter=ScriptedAdapter([]), game_factory=factory)
    assert seeds == [40]


# -- long games -----------------------------------------------------------------------------------


def test_a_long_conversation_is_replaced_by_a_briefing_and_a_new_conversation(
    run_config, make_game
) -> None:
    requests: list[Any] = []

    def briefing(_conv, items) -> Say:
        requests.append(list(items))
        return Say(text="I am in the arena. The wall is to the right. I carry two wands.")

    # the scripted model reports a prompt of ~4 characters per token of everything said: the
    # system prompt and the tools alone are over the small limit, so a briefing is due as soon as
    # a conversation has had three turns (the loop never writes them back to back)
    script = [Say.tools(call("wait", ticks=1)), briefing, *waits(12)]
    cfg, adapter, summary = play(
        run_config, make_game, script, context_limit=1_000, max_decisions=4, family="long"
    )
    assert summary["result"]["summaries"] >= 1
    assert len(adapter.conversations) >= 2
    old, new = adapter.conversations[0], adapter.conversations[1]
    assert (new.system, new.tools) == (old.system, old.tools)  # the cached prefix is shared
    # the briefing was asked for inside the old conversation, together with the pending results
    assert requests[0][-1] == UserText(SUMMARY_REQUEST)
    assert all(isinstance(i, ToolResult) for i in requests[0][:-1])
    # the new conversation opens with the briefing and the current view, and nothing else
    opening = new.history[0]["items"][0]
    assert opening.text.startswith("You are carrying on a game in progress.")
    assert "I am in the arena." in opening.text and "Goal: Get as deep as you can." in opening.text
    assert len(new.history[0]["items"]) == 1
    rows = lines(cfg.out / "transcript.jsonl")
    assert next(r for r in rows if r["kind"] == "summary")["text"].startswith("I am in the arena")
    assert [r["purpose"] for r in lines(cfg.out / "harness.jsonl")].count("summary") >= 1


def test_without_a_briefing_the_fallback_is_used(run_config, make_game) -> None:
    script = [*waits(1), Say(text="", stop=REFUSAL), *waits(10)]
    _, adapter, summary = play(
        run_config, make_game, script, context_limit=1_000, max_decisions=3, family="fb"
    )
    assert summary["result"]["summaries"] >= 1
    assert "could not be written" in adapter.conversations[1].history[0]["items"][0].text


def test_context_none_never_compacts(run_config, make_game) -> None:
    _, adapter, summary = play(
        run_config, make_game, waits(30), context="none", context_limit=10, max_decisions=8
    )
    assert summary["result"]["summaries"] == 0 and len(adapter.conversations) == 1


def test_server_compaction_is_only_for_anthropic(run_config, make_game) -> None:
    cfg = run_config(context="server")
    with pytest.raises(ConfigError, match="Anthropic"):
        run_family(cfg, adapter=ScriptedAdapter([]), game_factory=make_game)


# -- secrets --------------------------------------------------------------------------------------


def test_no_key_reaches_any_file(run_config, make_game, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-ant-api03-TOPSECRETVALUE0123456789"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    cfg = run_config(
        model=ModelConfig(
            "fake", "fake", base_url="https://user:pw@example.test:8443/v1", api_key_env="MY_KEY"
        ),
        max_decisions=3,
    )
    summary = run_family(
        cfg, adapter=ScriptedAdapter(waits(5)), game_factory=make_game, sleep=lambda _s: None
    )[0]
    for path in cfg.out.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}:
            text = path.read_text(errors="ignore")
            assert secret not in text and "TOPSECRET" not in text, path
    assert summary["model"]["base_url"] == "https://example.test:8443/v1"  # no user info
    assert summary["model"]["api_key_env"] == "MY_KEY"  # the name of the variable, not its value
    assert os.environ["ANTHROPIC_API_KEY"] == secret


def test_briefings_are_never_written_back_to_back(run_config, make_game) -> None:
    # a limit below the size of the system prompt and the tools would otherwise ask for one
    # briefing after every call
    script = [
        Say(text="a briefing") if i % 4 == 1 else Say.tools(call("wait", ticks=1))
        for i in range(40)
    ]
    _, adapter, summary = play(
        run_config, make_game, script, context_limit=100, max_decisions=9, family="tiny"
    )
    plays = summary["result"]["model_calls"] - summary["result"]["summaries"]
    assert summary["result"]["summaries"] <= 1 + plays // 3
    assert len(adapter.conversations) == summary["result"]["summaries"] + 1


def test_screenshots_go_with_the_view_and_stay_out_of_the_logs(run_config, make_game) -> None:
    from noitabench.agent import ViewConfig

    seen: list[Any] = []

    def look(_conv, items) -> Say:
        seen.append(list(items))
        return Say.tools(call("wait", ticks=1))

    view = ViewConfig(text=True, ascii=False, screenshot=True)
    cfg, adapter, _ = play(run_config, make_game, [look] * 4, view=view, max_decisions=3)
    opening = adapter.conversations[0].history[0]["items"][0]
    assert len(opening.images) == 1 and opening.images[0].startswith(b"\x89PNG")
    results = seen[1]
    assert isinstance(results[0], ToolResult) and results[0].images[0].startswith(b"\x89PNG")
    assert (
        "picture" in adapter.conversations[0].system
        and "4 by 4" not in adapter.conversations[0].system
    )
    for name in ("transcript.jsonl", "harness.jsonl"):
        assert "data_base64" not in (cfg.out / name).read_text()


def test_nothing_the_model_sees_names_the_tooling_the_seeds_or_the_markers(
    run_config, make_game
) -> None:
    """Everything sent to the model in a whole game, scanned."""
    from agent_worlds import SENTINELS
    from noitabench.harness.prompt import FORBIDDEN_STEMS

    script = [
        Say.tools(call("inspect", entity=4), call("budget"), call("workspace_list")),
        Say.tools(call("workspace_write", path="notes/a.md", text="hi"), call("aim", angle=10)),
        Say.tools(call("pickup", item=4)),
        Say.tools(call("walk_to", x=60)),
        Say.tools(call("inspect", x=70, y=159), call("inspect", wand=0)),
        *waits(10),
    ]
    _cfg, adapter, _ = play(
        run_config,
        make_game,
        script,
        max_decisions=9,
        world_seed=912345,
        rule_seed=778899,
        context_limit=100_000,
    )
    conv = adapter.conversations[0]
    sent = [conv.system, *(t.description for t in conv.tools)]
    for entry in conv.history:
        if entry["role"] == "user":
            sent += [getattr(i, "text", None) or getattr(i, "content", "") for i in entry["items"]]
    text = "\n".join(sent)
    assert len(text) > 20_000
    stems = re.compile(r"\b(" + "|".join(FORBIDDEN_STEMS) + ")", re.IGNORECASE)
    assert stems.findall(text) == []
    for hidden in (*SENTINELS, "912345", "778899", "rule_seed", "must_pass", "encounter_id"):
        assert hidden not in text, hidden


def _walking_script():
    """Endless: looks, moves, fires, writes a note, with several game calls in one turn."""
    yield Say.tools(call("workspace_list"), call("budget"))
    yield Say.tools(call("inspect", x=0, y=0))
    steps = (
        lambda: Say.tools(call("move", direction="right", until={"ticks": 30, "edge": True})),
        lambda: Say.tools(call("inspect", x=20, y=0), call("inspect", x=-20, y=10)),
        lambda: Say.tools(call("jump", direction="right"), call("fly", direction="up", ticks=5)),
        lambda: Say.tools(call("aim", angle=45), call("fire", until={"ticks": 5})),
        lambda: Say.tools(
            call("inspect", wand=0), call("workspace_write", path="notes/a.md", text="x" * 50)
        ),
        lambda: Say.tools(call("move", direction="left", until={"ticks": 30, "edge": True})),
        lambda: Say.tools(call("kick")),
        lambda: Say.tools(call("walk_to", x=300, until={"edge": True})),
        lambda: Say.tools(call("drop", wand=0)),
        lambda: Say.tools(call("drink"), call("pour")),
        lambda: Say.tools(call("wait", until={"ticks": 10})),
    )
    for n in itertools.count():
        yield steps[n % len(steps)]()


def test_nothing_the_model_sees_in_a_game_on_a_generated_world_names_hidden_things(
    tmp_path: Path,
) -> None:
    """The same scan as above on a real generated cave: the descriptions of every tool, the
    system prompt and every answer the model gets in 60 decisions."""
    from noitabench.harness.prompt import FORBIDDEN_STEMS

    cfg = RunConfig(
        model=ModelConfig("fake", "fake"),
        out=tmp_path / "run",
        workspaces_dir=tmp_path / "ws",
        world_seed=3,
        rule_seed=2,
        max_decisions=60,
    )
    adapter = ScriptedAdapter(_walking_script())
    summary = run_family(cfg, adapter=adapter, sleep=lambda _s: None)[0]
    assert summary["result"]["over"] == "decision_limit"
    conv = adapter.conversations[0]
    sent = [conv.system, *(f"{t.description} {t.schema}" for t in conv.tools)]
    for entry in conv.history:
        if entry["role"] == "user":
            sent += [getattr(i, "text", None) or getattr(i, "content", "") for i in entry["items"]]
    text = "\n".join(sent)
    assert len(text) > 100_000
    stems = re.compile(r"\b(" + "|".join(FORBIDDEN_STEMS) + ")", re.IGNORECASE)
    assert stems.findall(text) == []
    hidden = (
        "seed", "recipe", "reaction", "marker", "must_pass", "encounter", "placeholder",
        "footprint", "regions", "perturb", "xml_", "workspaces/", "runs/",
    )  # fmt: skip
    for word in hidden:
        assert word not in text.lower(), word


def test_a_secret_that_has_no_recognisable_shape_is_hidden_by_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from noitabench.harness.errors import scrub

    monkeypatch.setenv("MY_GATEWAY_TOKEN", "plain-words-with-no-key-shape")
    monkeypatch.setenv("SHORT_KEY", "abc")  # too short to hunt for
    monkeypatch.setenv("HOME_DIRECTORY", "/Users/someone-with-a-long-name")  # not secret-like
    text = scrub("401 for plain-words-with-no-key-shape in /Users/someone-with-a-long-name abc")
    assert "plain-words" not in text and "[redacted]" in text
    assert "/Users/someone-with-a-long-name" in text and text.endswith(" abc")
