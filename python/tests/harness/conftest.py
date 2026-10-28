"""Fixtures for the harness tests: a small hand-built world (the one of the agent-interface
tests), a scripted model, no network."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

# the world builder of the agent-interface tests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from agent_worlds import settle, write_arena
from noitabench.game import Game
from noitabench.harness import ModelConfig, RunConfig

# the adapter tests need the provider SDKs (the `harness` extra) and skip without them
_NEEDS = {
    "test_harness_anthropic.py": ("anthropic", "httpx2"),
    "test_harness_openai.py": ("openai", "httpx2"),
    "test_harness_deepseek.py": ("openai", "httpx2"),
    "test_harness_gemini.py": ("google.genai", "httpx"),
}


def _missing(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is None
    except ModuleNotFoundError:
        return True


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    needs = _NEEDS.get(collection_path.name, ())
    return True if any(_missing(m) for m in needs) else None


@pytest.fixture
def make_game(tmp_path: Path) -> Callable[[int], Game]:
    """A settled game in the arena; `world_seed` is ignored (the arena is always the same)."""
    counter = iter(range(1000))

    def make(_world_seed: int = 0, _folder: Path | None = None) -> Game:
        arena = write_arena(tmp_path / f"arena{next(counter)}")
        game = arena.game(seed=3)
        settle(game)
        return game

    return make


@pytest.fixture
def run_config(tmp_path: Path) -> Callable[..., RunConfig]:
    def make(**overrides: object) -> RunConfig:
        values: dict[str, object] = {
            "model": ModelConfig("fake", "fake"),
            "out": tmp_path / "run",
            "workspaces_dir": tmp_path / "workspaces",
            "max_decisions": 10,
        }
        values.update(overrides)
        return RunConfig(**values)  # type: ignore[arg-type]

    return make
