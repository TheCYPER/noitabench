"""The agent layer on a world of the generator (markers with every tooling field)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from noitabench.agent import AgentSession, render_text
from noitabench.agent.cli import build_world, open_game
from noitabench.agent.visibility import FORBIDDEN_KEYS, leaks

WORLD_SEED = 3
RULE_SEED = 0


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    try:
        return build_world(WORLD_SEED, RULE_SEED, tmp_path_factory.mktemp("generated"))
    except Exception as err:  # noqa: BLE001 - the generator is another module's business
        pytest.skip(f"the world generator is not available: {err}")


def test_a_generated_world_plays_and_shows_nothing_hidden(world: tuple[Path, Path]) -> None:
    png, js = world
    doc = json.loads(js.read_text())
    tooling = {k for m in doc["markers"] for k in m} & FORBIDDEN_KEYS
    assert tooling, "the world file should carry tooling fields for this test to mean something"
    s = AgentSession(open_game(png, js))
    answers = [s.observe()]
    for text in (
        "inspect(wand=0)",
        "walk_to(x=200)",
        "move(left)",
        "jump(right)",
        "aim(angle=-90); fire(ticks=3)",
        "wait(ticks=30)",
    ):
        answers.append(s.decide(text))
    for a in answers:
        assert leaks(a) == []
        blob = json.dumps(a) + render_text(a)
        for word in ("encounter_id", "must_pass", "placeholder", "footprint", "rule_seed"):
            assert word not in blob
    first = answers[0]["observation"]
    assert first["state"]["can_edit_wands"] is False  # the start is not a rest area
    assert first["map"]["rows"][16][32] == "@"
    assert all(a["stop"]["frames"] % 10 == 0 for a in answers)


def test_the_same_generated_world_gives_the_same_episode(world: tuple[Path, Path]) -> None:
    png, js = world
    runs = []
    for _ in range(2):
        s = AgentSession(open_game(png, js))
        runs.append([s.decide(t) for t in ("walk_to(x=160)", "jump(right)", "wait(ticks=5)")])
        runs[-1].append(s.state_hash())
    assert runs[0] == runs[1]
