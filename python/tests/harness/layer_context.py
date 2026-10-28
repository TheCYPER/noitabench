"""A `LayerContext` built by hand for the tests of single layers: the arena world, a notebook, a
shared budget and a scripted model, without a loop."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from noitabench.agent import AgentSession, SessionConfig
from noitabench.game import Game
from noitabench.harness import Budget, ToolBox, Workspace
from noitabench.harness.adapters.scripted import Scripted, ScriptedAdapter
from noitabench.harness.layers import LayerContext, register_l0, register_l1
from noitabench.harness.logs import RunLogs
from noitabench.harness.model import ModelAdapter
from noitabench.harness.prices import ModelPrice, custom_price


@dataclass
class Rig:
    ctx: LayerContext
    session: AgentSession
    adapter: ModelAdapter
    budget: Budget
    workspace: Workspace
    logs: RunLogs
    folder: Path

    @property
    def toolbox(self) -> ToolBox:
        return self.ctx.toolbox


def make_rig(
    tmp_path: Path,
    game: Game,
    script: Iterable[Scripted] = (),
    *,
    price: ModelPrice | None = None,
    budget: Budget | None = None,
    adapter: ModelAdapter | None = None,
    register: Callable[[LayerContext], None] | None = None,
    max_decisions: int = 50,
) -> Rig:
    """L0 and L1 are registered; `register` (a layer's function) adds the layer under test."""
    workspace = Workspace(tmp_path / "ws")
    session = AgentSession(
        game, config=SessionConfig(max_decisions=max_decisions), memory=workspace
    )
    budget = budget or Budget(max_usd=50.0, max_model_calls=500)
    adapter = adapter or ScriptedAdapter(script)
    logs = RunLogs(tmp_path / "logs")
    price = price if price is not None else custom_price(1.0, 5.0)
    ctx = LayerContext(
        ToolBox(session), session, workspace, budget, max_decisions, False, adapter, price, logs
    )
    register_l0(ctx)
    register_l1(ctx)
    if register is not None:
        register(ctx)
    return Rig(ctx, session, adapter, budget, workspace, logs, tmp_path)
