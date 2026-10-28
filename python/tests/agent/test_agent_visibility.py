"""What agents may never see (contracts section 11): no marker tooling fields, no rule seed, no
reaction events or row ids, no recipe - in any answer of a whole scripted episode."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import noitabench_core
import pytest
from agent_worlds import GROUND, SENTINELS, START_X, write_arena
from noitabench.agent import AgentSession, InMemoryNotes, render_text, tool_schemas
from noitabench.agent.mcp_adapter import tool_payload
from noitabench.agent.protocol import hello, with_text
from noitabench.agent.visibility import FORBIDDEN_KEYS, check_clean, leaks, strings
from noitabench.game import Game

SCRIPT = [
    f"inspect(x={START_X + 10}, y={GROUND})",
    "walk_to(x=44)",
    "pickup",
    "inspect(spell=0)",
    "edit_wand(op=place, wand=0, slot=1, spell=0)",
    "inspect(wand=0)",
    "walk_to(x=54)",
    "pickup",
    "inspect(bottle=0)",
    "drink(amount=50)",
    "aim(angle=10); fire(ticks=4)",
    "swap_wand(1); swap_wand(0); kick",
    "aim(target=longleg); fire(until=target_dead)",
    "walk_to(x=100)",
    "wait(ticks=8)",
    "jump(right)",
    "fly(up, ticks=2)",
    "memory_write('lab.md', 'notes with the word role and params'); memory_read('lab.md')",
    "memory_search('role'); memory_list",
    "throw",
    "walk_to(x=110)",
    "edit_wand(op=take, wand=0, slot=1)",  # outside the rest area: refused
    "drop(wand=0)",
    "bogus()",
    "walk_to(x=-3)",
    "move(right)",
    "wait(ticks=30)",
]
BANNED_WORDS = (
    "rule_seed", "reaction", "recipe", "ingredient", "perturb", "must_pass", "placeholder",
    "footprint", "encounter", "breaker", "solvent", *SENTINELS,
)  # fmt: skip
ROW_ID = re.compile(r"\br\d\d(\.[a-z_]+)?\b")


def recipes() -> list[tuple[list[str], str]]:
    """The secret recipes of the rule seed of the arena."""
    return [(list(r["inputs"]), r["potion"]) for r in noitabench_core.recipes(5)]


def episode_game(tmp: Path) -> Game:
    """The arena, with lava next to water (raw `reaction` events), oil on fire (`ignite`) and a
    creature close by - all in view of the player."""

    def edit(grid: Any, keys: dict[str, int]) -> None:
        grid[GROUND - 6 : GROUND + 1, 112:118] = keys["lava"]
        grid[GROUND - 6 : GROUND + 1, 118:124] = keys["water"]
        grid[GROUND - 3 : GROUND + 1, 126:132] = keys["oil"]

    game = write_arena(tmp, edit=edit).game(seed=3)
    game.spawn_enemy("longleg", 95, GROUND)
    game.ignite(128, GROUND)
    return game


def all_texts(answer: dict[str, Any]) -> list[str]:
    """Every string an agent could read in an answer: keys and values, and the rendered text,
    without the map rows (a legend lists names that sit side by side)."""
    texts = list(strings({k: v for k, v in answer.items() if k != "observation"}))
    obs = answer.get("observation", {})
    if "state" in obs:
        texts += list(strings(obs["state"]))
    if "map" in obs:
        texts += [str(v) for v in obs["map"]["legend"].values()]
    texts += render_text(answer).splitlines()
    return texts


def test_a_whole_episode_shows_nothing_hidden(tmp_path: Path) -> None:
    game = episode_game(tmp_path / "w")
    rec = tmp_path / "rec"
    with AgentSession(game, memory=InMemoryNotes(), recording_dir=rec) as session:
        first = hello(session)
        answers = [with_text(session.observe())]
        answers += [with_text(session.decide(text)) for text in SCRIPT]
        answers.append(first)
        for name, args in (("inspect", {"wand": 0}), ("kick", {}), ("walk_to", {"x": "far"})):
            tool = tool_payload(session, name, args)  # the MCP route
            answers.append(with_text(tool["answer"]))
            assert not any(word in tool["text"] for word in BANNED_WORDS)
    notes_only = sum(1 for text in SCRIPT if text.startswith("memory_"))  # notes cost nothing
    assert answers[1]["decision"] == 2
    assert answers[len(SCRIPT)]["decision"] == len(SCRIPT) + 1 - notes_only
    known = recipes()
    for a in answers:
        assert leaks(a) == [], leaks(a)
        check_clean(a)
        texts = all_texts(a)
        blob = json.dumps(a)
        for word in BANNED_WORDS:
            assert word not in blob, (word, a["decision"])
            assert not any(word in t for t in texts), (word, a["decision"])
        assert not ROW_ID.search(blob), ROW_ID.search(blob)
        for ingredients, potion in known:  # no line says what makes what
            for t in texts:
                assert not (potion in t and sum(i in t for i in ingredients) >= 2), t
    # the run did contain what must stay hidden: the engine logged it, the agent was not told
    raw = [json.loads(line) for line in (rec / "events.jsonl").read_text().splitlines()]
    kinds = {e["type"] for e in raw}
    assert {"reaction", "ignite", "cast", "death"} <= kinds
    assert any(e["type"] == "reaction" and ROW_ID.fullmatch(e["id"]) for e in raw)
    told = {e["type"] for a in answers for e in a.get("events", [])}
    assert "reaction" not in told and {"cast", "ignite"} <= told


def test_the_tool_schemas_and_the_first_line_hide_the_rules_too(game: Game) -> None:
    session = AgentSession(game)
    first = hello(session)
    text = json.dumps(first) + json.dumps(tool_schemas())
    assert leaks(first) == [] and leaks(tool_schemas()) == []
    for word in ("rule_seed", "recipe", "reaction", *SENTINELS):
        assert word not in text


def test_the_session_gives_no_way_to_the_game_or_the_markers(game: Game) -> None:
    session = AgentSession(game)
    for obj in (session, session.engine):
        public = [n for n in dir(obj) if not n.startswith("_")]
        assert not {"game", "markers", "rule_seed", "recipes", "reactions"} & set(public)
    assert not any(
        isinstance(getattr(session, n), Game) for n in dir(session) if not n.startswith("_")
    )


def test_a_leak_in_an_answer_is_caught() -> None:
    assert leaks({"a": [{"role": "breaker"}], "b": {"rule_seed": 1}}) == [
        "$.a[0].role",
        "$.b.rule_seed",
    ]
    with pytest.raises(AssertionError, match="hidden fields"):
        check_clean({"observation": {"state": {"trigger": {"x": 1}}}})
    assert leaks({"notes": "the role of params"}) == []  # words in text are not keys
    assert {"role", "params", "regions", "encounter_id", "placeholder", "must_pass", "footprint",
            "trigger", "strength", "rule_seed"} <= FORBIDDEN_KEYS  # fmt: skip
