"""A game with a toolbox, for the tests of the layers that run the player's code: the arena of
the agent-interface tests, a notebook, and tool calls made by hand (no model)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_worlds import START_X, settle, write_arena
from noitabench.agent import AgentSession, SessionConfig
from noitabench.game import Game
from noitabench.harness import Budget, Workspace, build_toolbox
from noitabench.harness.layers import DEFAULT_LAYERS
from noitabench.harness.logs import RunLogs
from noitabench.harness.model import ToolCall, ToolResult
from noitabench.harness.toolbox import Executed, ToolBox

_ids = itertools.count(1)


def arena_game(folder: Path, spawn_x: int = START_X) -> Game:
    game = write_arena(folder, spawn_x=spawn_x).game(seed=3)
    settle(game)
    return game


@dataclass
class Rig:
    session: AgentSession
    workspace: Workspace
    toolbox: ToolBox
    logs: RunLogs
    game: Game
    folder: Path
    calls_made: list[str] = field(default_factory=list)

    @property
    def decisions(self) -> int:
        return self.session.decisions

    def turn(self, *calls: tuple[str, dict[str, Any]]) -> Executed:
        built = [ToolCall(f"call_{next(_ids)}", name, args) for name, args in calls]
        return self.toolbox.execute(built)

    def call(self, tool: str, /, **args: Any) -> ToolResult:
        return self.turn((tool, args)).results[0]

    def write(self, path: str, text: str) -> None:
        self.workspace.write(path, text, False)

    def transcript(self) -> list[dict[str, Any]]:
        import json

        path = self.folder / "transcript.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def make_rig(
    folder: Path,
    *,
    spawn_x: int = START_X,
    layers: tuple[str, ...] = DEFAULT_LAYERS,
    max_decisions: int = 1000,
    game: Game | None = None,
    wheelhouse: Path | None = None,
    **view: Any,
) -> Rig:
    from noitabench.agent import ViewConfig

    folder.mkdir(parents=True, exist_ok=True)
    game = game or arena_game(folder / "arena", spawn_x)
    config = SessionConfig(max_decisions=max_decisions, view=ViewConfig(**view))
    workspace = Workspace(folder / "ws")
    session = AgentSession(game, config=config, memory=workspace)
    logs = RunLogs(folder / "logs")
    toolbox = build_toolbox(
        session,
        workspace,
        Budget(),
        layers=layers,
        decisions_cap=max_decisions,
        logs=logs,
        wheelhouse=wheelhouse,
    )
    return Rig(session, workspace, toolbox, logs, game, folder / "logs")
