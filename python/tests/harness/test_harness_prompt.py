"""What the player is told: a game, a goal, nothing about tests or scores."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from noitabench.agent import ViewConfig, render_text
from noitabench.agent.visibility import strings
from noitabench.harness import Budget, Workspace, build_toolbox, system_prompt
from noitabench.harness.layers import MINIMAL_LAYERS
from noitabench.harness.prompt import (
    FORBIDDEN_STEMS,
    NUDGE_CUT_OFF,
    NUDGE_NO_COMMAND,
    NUDGE_NO_TOOL,
    SERVER_COMPACTION_INSTRUCTIONS,
    SUMMARY_FALLBACK,
    SUMMARY_INTRO,
    SUMMARY_REQUEST,
    command_reference,
    opening_message,
)

_STEMS = re.compile(r"\b(" + "|".join(FORBIDDEN_STEMS) + r")", re.IGNORECASE)
_DATES = re.compile(r"\b(19|20)\d\d[-/]\d\d[-/]\d\d\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}\b")


def forbidden_in(text: str) -> list[str]:
    return [m.group(0) for m in _STEMS.finditer(text)]


def all_prompts() -> Iterator[tuple[str, str]]:
    for mode in ("tools", "text"):
        for kept in (True, False):
            for view in (
                ViewConfig(),
                ViewConfig(ascii=False, screenshot=True),
                ViewConfig(text=False),
            ):
                yield f"{mode}/{kept}", system_prompt(mode=mode, notes_kept=kept, view=view)


def test_every_system_prompt_is_clean() -> None:
    for name, text in all_prompts():
        assert forbidden_in(text) == [], (name, forbidden_in(text))
        assert _DATES.search(text) is None, name  # nothing that changes from day to day
        for placeholder in ("{goal}", "{max_commands}", "{commands}"):
            assert placeholder not in text, name


def test_the_goal_is_get_as_deep_as_you_can_and_it_is_a_game() -> None:
    text = system_prompt(mode="tools", notes_kept=True)
    assert "Get as deep as you can." in text
    assert "game" in text.lower()
    # there is no strategy advice and no word about hidden structure
    for word in ("encounter", "seal", "recipe", "rule seed", "scene", "marker", "bomb"):
        assert word not in text.lower()


def test_prompts_are_byte_identical_between_calls() -> None:
    a = system_prompt(mode="tools", notes_kept=True, view=ViewConfig())
    b = system_prompt(mode="tools", notes_kept=True, view=ViewConfig())
    assert a == b


def test_the_notebook_paragraph_follows_the_setting() -> None:
    kept = system_prompt(mode="tools", notes_kept=True)
    scratch = system_prompt(mode="tools", notes_kept=False)
    assert "kept when the game is over" in kept
    assert "kept when the game is over" not in scratch and "during the game" in scratch


def test_the_view_paragraph_follows_the_channels() -> None:
    assert "4 by 4 cells" in system_prompt(mode="tools", notes_kept=True)
    shot = system_prompt(
        mode="tools", notes_kept=True, view=ViewConfig(ascii=False, screenshot=True)
    )
    assert "picture" in shot and "map" not in shot


def test_text_mode_lists_the_commands() -> None:
    text = system_prompt(mode="text", notes_kept=True)
    for name in ("walk_to", "fire", "inspect", "memory_write", "budget"):
        assert name in text
    assert "walk_to(" in command_reference()


def test_every_other_text_is_clean() -> None:
    texts = [
        SUMMARY_REQUEST,
        SUMMARY_INTRO.format(summary="s", observation="o"),
        SERVER_COMPACTION_INSTRUCTIONS,
        SUMMARY_FALLBACK,
        NUDGE_CUT_OFF,
        NUDGE_NO_COMMAND,
        NUDGE_NO_TOOL,
        opening_message("view", [("notes/a.md", 3)], 7_997),
        opening_message("view", [], 8_000),
    ]
    for text in texts:
        assert forbidden_in(text) == [], text


def test_tool_names_descriptions_and_schemas_are_clean(tmp_path: Path) -> None:
    box = build_toolbox(
        None,  # type: ignore[arg-type]
        Workspace(tmp_path / "w"),
        Budget(),
        layers=MINIMAL_LAYERS,
        decisions_cap=10,
    )
    names = [s.name for s in box.specs()]
    assert "budget" in names and "workspace_write" in names and "walk_to" in names
    assert not [n for n in names if n.startswith("memory_")]  # the notebook tools replace them
    assert len(names) == len(set(names))
    for spec in box.specs():
        for text in strings({"d": spec.description, "s": spec.schema}):
            assert forbidden_in(text) == [], (spec.name, text)


def test_the_first_real_view_is_clean(make_game) -> None:
    from noitabench.agent import AgentSession

    session = AgentSession(make_game())
    text = render_text(session.observe())
    assert forbidden_in(text) == []
    with tempfile.TemporaryDirectory() as tmp:
        assert (
            forbidden_in(opening_message(text, [], Workspace(Path(tmp)).quota("notes").left)) == []
        )


@pytest.mark.parametrize("word", ["test", "benchmark", "score", "evaluation", "capabilities"])
def test_the_checker_itself_finds_the_words(word: str) -> None:
    assert forbidden_in(f"this is a {word} of you")
    assert forbidden_in("the latest contest of attestation") == []
