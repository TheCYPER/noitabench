"""Running games: one game (`play_game`) and a family of games that share a workspace
(`run_family`).

A *family* is a run of games with the same rules: the rule seed is fixed, each game gets a new
cave (`world_seed + i`), and the workspace folder `workspaces/<family>/` is kept between games,
or, in the control setting, emptied before each one. Files of a run (all in its folder):

    recording files and decisions.jsonl   from the agent layer (the game, step by step)
    harness.jsonl, transcript.jsonl       from the loop (`logs.py`)
    summary.json                          how the run ended, tokens, dollars; `result.models_seen`
                                          lists the model ids the answers of the player's own
                                          calls named, in order of first sight (a name such as
                                          `deepseek-flash` can point at another model one day;
                                          helpers' calls name theirs in `harness.jsonl`)
    world/                                the world files of the game
    workspace_start/                      the workspace as the game began (the notebook it
                                          started with; the evaluation reads it, agents never)
    workspace/                            the workspace as the game left it
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from noitabench.agent import AgentSession, SessionConfig, ViewConfig
from noitabench.game import Game

from .adapters import make_adapter
from .adapters.deepseek_adapter import refuse_screenshot
from .budget import Budget
from .errors import ConfigError
from .layers import CODE_LAYERS, MINIMAL_LAYERS, build_toolbox, check_layers
from .logs import RunLogs
from .loop import SERVER, SUMMARY, AgentLoop, LoopConfig, LoopResult
from .model import ModelAdapter, ModelConfig
from .prices import ModelPrice, default_context_limit, resolve_price
from .prompt import system_prompt
from .redact import default_redactor
from .toolbox import ToolBox
from .workspace import Workspace, family_name

log = logging.getLogger(__name__)

SUMMARY_FORMAT = "cogbench-harness-run/0"
MIN_SERVER_TRIGGER = 50_000  # the API's lowest compaction trigger
CALLS_PER_DECISION = 3  # default cap on model calls, in multiples of the step limit

GameFactory = Callable[[int, Path], Game]


@dataclass(frozen=True)
class RunConfig:
    model: ModelConfig
    out: Path
    world_seed: int = 1
    rule_seed: int = 0
    game_seed: int | None = None
    budget_usd: float | None = None
    family_budget_usd: float | None = None
    max_decisions: int = 1000
    max_model_calls: int | None = None
    mode: str = "tools"
    context: str = SUMMARY
    context_limit: int | None = None
    layers: tuple[str, ...] = MINIMAL_LAYERS
    family: str | None = None
    workspaces_dir: Path = Path("workspaces")
    clear_workspace: bool = False
    runs: int = 1
    view: ViewConfig = field(default_factory=ViewConfig)
    allow_unpriced: bool = False
    price: ModelPrice | None = None  # replaces the table
    wheelhouse: Path | None = None  # libraries that may be installed (None: this checkout's)

    def __post_init__(self) -> None:
        check_layers(self.layers, mode=self.mode)
        if self.runs < 1:
            raise ConfigError("runs must be at least 1")
        if self.max_decisions < 1:
            raise ConfigError("max_decisions must be at least 1")
        if self.budget_usd is not None and self.budget_usd <= 0:
            raise ConfigError("the budget in dollars must be positive")
        if self.view.screenshot:
            refuse_screenshot(self.model)

    @property
    def family_name(self) -> str:
        return family_name(self.family or self.out.name)

    @property
    def calls_cap(self) -> int:
        return self.max_model_calls or max(50, CALLS_PER_DECISION * self.max_decisions)


def _loop_config(config: RunConfig, price: ModelPrice | None) -> LoopConfig:
    limit = config.context_limit or default_context_limit(price)
    return LoopConfig(mode=config.mode, context=config.context, context_limit=limit)


def _model_config(config: RunConfig, loop: LoopConfig) -> ModelConfig:
    """The model config with the server-side compaction trigger, when that strategy is chosen."""
    if config.context != SERVER:
        return config.model
    if config.model.provider != "anthropic":
        raise ConfigError("server-side compaction is only available for Anthropic models")
    return replace(config.model, server_compaction=max(loop.context_limit, MIN_SERVER_TRIGGER))


def _default_game(config: RunConfig) -> GameFactory:
    def make(world_seed: int, folder: Path) -> Game:
        from noitabench.agent.cli import build_world, open_game

        png, js = build_world(world_seed, config.rule_seed, folder)
        return open_game(png, js, game_seed=config.game_seed, rule_seed=config.rule_seed)

    return make


def play_game(
    *,
    game: Game,
    adapter: ModelAdapter,
    run_dir: Path,
    workspace: Workspace,
    config: RunConfig,
    price: ModelPrice | None,
    budget: Budget,
    meta: dict[str, Any] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Play one game with the model; write the run folder; return the summary dict."""
    default_redactor().track(config.model.api_key_env)  # a key whose variable has an odd name
    run_dir.mkdir(parents=True, exist_ok=True)
    _save_start_notebook(workspace, run_dir)
    loop_cfg = _loop_config(config, price)
    session = AgentSession(
        game,
        config=SessionConfig(max_decisions=config.max_decisions, view=config.view),
        memory=workspace,
        recording_dir=run_dir,
        notes="harness game",
    )
    logs: RunLogs | None = None
    result: LoopResult | None = None
    error: BaseException | None = None
    toolbox: ToolBox | None = None
    try:
        logs = RunLogs(run_dir)
        toolbox = build_toolbox(
            session,
            workspace,
            budget,
            layers=config.layers,
            decisions_cap=config.max_decisions,
            adapter=adapter,
            price=price,
            logs=logs,
            wheelhouse=config.wheelhouse,
        )
        system = system_prompt(
            mode=config.mode,
            notes_kept=not config.clear_workspace,
            view=config.view,
            layers=config.layers,
        )
        extra = {} if sleep is None else {"sleep": sleep}
        loop = AgentLoop(
            session=session,
            adapter=adapter,
            toolbox=toolbox,
            workspace=workspace,
            budget=budget,
            price=price,
            logs=logs,
            system=system,
            config=loop_cfg,
            system_suffix=toolbox.system_suffix,
            **extra,
        )
        result = loop.run()
    except BaseException as exc:
        error = exc
        raise
    finally:
        closed = session.close()
        if logs is not None:
            logs.close()
        summary = _summary(config, loop_cfg, price, budget, result, error, workspace, closed, meta)
        hub = toolbox.extras.get("subagent_hub") if toolbox is not None else None
        if hub is not None:
            summary["helpers"] = hub.summary()
        summary = default_redactor().redact_value(summary)
        (run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        redactor = default_redactor()
        redactor.refresh()  # whatever the game came to know about, the notebook is cleaned of it
        workspace.scrub(redactor.redact)
        workspace.copy_to(run_dir / "workspace", redactor.redact)
    return summary


def _save_start_notebook(workspace: Workspace, run_dir: Path) -> None:
    """Copy the notebook the game starts with to `<run>/workspace_start/`, cleaned like the end
    copy, so that a run folder tells on its own what the agent began with (the notes evaluation
    compares it with `workspace/`). The workspace itself is left as it is."""
    redactor = default_redactor()
    redactor.refresh()
    workspace.copy_to(run_dir / "workspace_start", redactor.redact)


def _summary(
    config: RunConfig,
    loop_cfg: LoopConfig,
    price: ModelPrice | None,
    budget: Budget,
    result: LoopResult | None,
    error: BaseException | None,
    workspace: Workspace,
    closed: dict[str, Any],
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    outcome = result.as_dict() if result else {"over": "aborted", "detail": type(error).__name__}
    return {
        "format": SUMMARY_FORMAT,
        **(meta or {}),
        "model": _model_config(config, loop_cfg).as_log(),
        "mode": config.mode,
        "layers": list(config.layers),
        "context": {"strategy": config.context, "limit_tokens": loop_cfg.context_limit},
        "family": config.family_name,
        "workspace_cleared_each_game": config.clear_workspace,
        "price": None
        if price is None
        else {
            "tiers": [
                {"max_prompt_tokens": t.max_prompt_tokens, "input": t.input, "output": t.output}
                for t in price.tiers
            ],
            "cache_read_factor": price.cache_read_factor,
            "cache_write_factor": price.cache_write_factor,
            "source": price.source,
        },
        "cost_known": price is not None,
        "result": outcome,
        "budget": budget.as_dict(),
        "limits": {"max_decisions": config.max_decisions, "max_usd": config.budget_usd},
        "session": {k: v for k, v in closed.items() if k != "recording"},
        "workspace": {"files": workspace.file_names(), "usage": workspace.usage()},
    }


# Model errors that the next game would hit at its first call in the same way, so the family stops.
FAMILY_STOPPERS = {
    "balance": "the account balance is used up",
    "auth": "the provider refused the API key",
    "permission": "the API key may not use this model",
}


def _family_stopper(summary: dict[str, Any]) -> str | None:
    """Why no later game of the family can work, or None. `AgentLoop._call` is the only place that
    makes a `model_error` result, and it writes the detail as `<ModelError.kind>: <message>`."""
    result = summary.get("result", {})
    if result.get("over") != "model_error":
        return None
    kind = str(result.get("detail", "")).split(":", 1)[0]
    return FAMILY_STOPPERS.get(kind)


def run_family(
    config: RunConfig,
    *,
    adapter: ModelAdapter | None = None,
    game_factory: GameFactory | None = None,
    sleep: Callable[[float], None] | None = None,
) -> list[dict[str, Any]]:
    """Play `config.runs` games of one family and return their summaries."""
    default_redactor().track(config.model.api_key_env)
    price = resolve_price(
        config.model.model, override=config.price, allow_unpriced=config.allow_unpriced
    )
    if price is None and (config.budget_usd is not None or config.family_budget_usd is not None):
        raise ConfigError(
            "a budget in dollars needs a price: give --price-input and --price-output"
        )
    loop_cfg = _loop_config(config, price)
    model_cfg = _model_config(config, loop_cfg)
    adapter = adapter or make_adapter(model_cfg, mode=config.mode)
    factory = game_factory or _default_game(config)
    # plugins/ and scripts/ are offered only to the layers that read them
    code_area = any(name in CODE_LAYERS for name in config.layers)
    workspace = Workspace(config.workspaces_dir / config.family_name, code_area=code_area)
    summaries: list[dict[str, Any]] = []
    family_spent = 0.0
    for index in range(config.runs):
        if config.family_budget_usd is not None and family_spent >= config.family_budget_usd:
            log.warning("family budget used up after %d game(s)", index)
            break
        if config.clear_workspace:
            workspace.clear()
        run_dir = config.out if config.runs == 1 else config.out / f"run-{index + 1:02d}"
        world_seed = config.world_seed + index
        game = factory(world_seed, run_dir / "world")
        cap = config.budget_usd
        if config.family_budget_usd is not None:
            left = config.family_budget_usd - family_spent
            cap = left if cap is None else min(cap, left)
        budget = Budget(max_usd=cap, max_model_calls=config.calls_cap)
        meta = {"run_index": index + 1, "runs": config.runs, "world_seed": world_seed}
        meta["rule_seed"] = config.rule_seed
        summary = play_game(
            game=game,
            adapter=adapter,
            run_dir=run_dir,
            workspace=workspace,
            config=config,
            price=price,
            budget=budget,
            meta=meta,
            sleep=sleep,
        )
        family_spent += budget.spent_usd
        summaries.append(summary)
        stopper = _family_stopper(summary)
        if stopper:
            log.warning("%s: no more games after game %d", stopper, index + 1)
            break
    if config.runs > 1:
        config.out.mkdir(parents=True, exist_ok=True)
        family = {
            "family": config.family_name,
            "runs": summaries,
            "spent_usd": round(family_spent, 6),
        }
        (config.out / "family.json").write_text(
            json.dumps(default_redactor().redact_value(family), indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
    return summaries
