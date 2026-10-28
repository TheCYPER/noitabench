"""Fixtures for the agent-interface tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agent_worlds import Arena, settle, write_arena
from noitabench.agent import AgentSession, SessionConfig, ViewConfig
from noitabench.game import Game


@pytest.fixture
def arena(tmp_path: Path) -> Arena:
    return write_arena(tmp_path / "arena")


@pytest.fixture
def game(arena: Arena) -> Game:
    g = arena.game()
    settle(g)
    return g


@pytest.fixture
def game_at(tmp_path: Path) -> Callable[[int], Game]:
    """A settled game with the player starting at the given column."""

    def make(x: int) -> Game:
        g = write_arena(tmp_path / f"arena{x}", spawn_x=x).game()
        settle(g)
        return g

    return make


@pytest.fixture
def make_session() -> Callable[..., AgentSession]:
    """A session on a game; view and config can be given as keywords."""

    def make(game: Game, *, max_decisions: int = 1000, **view: Any) -> AgentSession:
        config = SessionConfig(max_decisions=max_decisions, view=ViewConfig(**view))
        return AgentSession(game, config=config)

    return make


@pytest.fixture
def session(game: Game, make_session: Callable[..., AgentSession]) -> AgentSession:
    return make_session(game)
