"""The harness layers (design 6.2) and the tools each one adds.

    L0  game tools     the commands of the agent layer, plus `budget`
    L1  workspace      the notebook: `workspace_*` tools, the `MemoryBackend` of the session
    L2  Code Mode      `run_code` (codemode.py): a Python program in a box that plays for you
    L3  hooks          `hook_*` (hooks.py): the game reacts to events, and runs scripts
    L4  sub-agents     `spawn_agent`, `fork_agent`, `agent_*`, `wand_range` (subagents.py): helpers
                       that think but never act in the game, and the wand practice range
    L5  plugins        `plugin_*`, `lib_*` (plugins.py, libs.py): tools of your own, extra libraries

L2, L3 and L5 run the player's code in the box of `sandbox.py`; without `sandbox-exec` they
refuse to start (`check_layers`).

A layer is a function `register(context)` that adds tools to `context.toolbox`. To add a layer,
write its function and put it in `LAYER_REGISTRARS`; `DEFAULT_LAYERS` then includes it, and the
minimal setting (`MINIMAL_LAYERS`, L0 and L1 only) stays as it is. Tools are registered once,
before the first model call, and never change during a run (the prompt cache depends on it).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from noitabench.agent import AgentSession, tool_schemas
from noitabench.agent.spec import MEMORY_COMMANDS

from .budget import Budget
from .codemode import register_l2
from .errors import ConfigError
from .hooks import register_l3
from .logs import RunLogs
from .model import ModelAdapter, ToolSpec
from .plugins import register_l5
from .prices import ModelPrice
from .prompt import notebook_tools_note
from .sandbox import check_sandbox
from .subagents import register_l4
from .toolbox import FREE, GAME, ToolBox, ToolDef, object_schema
from .workspace import Workspace


@dataclass
class LayerContext:
    """What a layer may use when it registers its tools. `adapter`, `price` and `logs` are for
    the layers that call a model themselves (sub-agents): they open conversations with
    `adapter`, charge `budget` with what `price` says, and write to `logs`."""

    toolbox: ToolBox
    session: AgentSession
    workspace: Workspace
    budget: Budget
    decisions_cap: int
    with_code_area: bool = False  # plugins/ and scripts/ are in use (Code Mode, plugins)
    adapter: ModelAdapter | None = None
    price: ModelPrice | None = None
    logs: RunLogs | None = None
    wheelhouse: Path | None = None  # the libraries that may be installed (None: this checkout's)
    layers: tuple[str, ...] = ()  # the layers of the run
    extras: dict[str, Any] = field(default_factory=dict)  # what layers share (code runtime...)


_object = object_schema


def register_l0(ctx: LayerContext) -> None:
    """The game commands (not the notes commands: the workspace tools replace them) and
    `budget`."""
    for schema in tool_schemas():
        if schema["name"] in MEMORY_COMMANDS:
            continue
        spec = ToolSpec(schema["name"], schema["description"], schema["inputSchema"])
        ctx.toolbox.register(ToolDef(spec, GAME))
    budget_spec = ToolSpec(
        "budget",
        "Show how much of your allowance is left: money (USD), model calls and steps. "
        "Takes no game time and costs no step.",
        _object({}),
    )
    ctx.toolbox.register(ToolDef(budget_spec, FREE, lambda _args: budget_report(ctx)))


def budget_report(ctx: LayerContext) -> dict[str, Any]:
    left_usd = ctx.budget.remaining_usd()
    steps_left = max(ctx.decisions_cap - ctx.session.decisions, 0)
    report: dict[str, Any] = {
        "steps_left": steps_left,
        "steps_total": ctx.decisions_cap,
        "usd_left": None if left_usd is None else round(left_usd, 4),
        "usd_spent": round(ctx.budget.spent_usd, 4),
        "model_calls": ctx.budget.model_calls,
    }
    if ctx.budget.max_model_calls is not None:
        report["model_calls_left"] = max(ctx.budget.max_model_calls - ctx.budget.model_calls, 0)
    return report


def register_l1(ctx: LayerContext) -> None:
    """The notebook tools."""
    ws = ctx.workspace
    folders = notebook_tools_note(ctx.with_code_area)
    path_doc = "File name, like notes/chemistry.md. A name without a folder goes in notes/."
    tools: list[tuple[ToolSpec, Any]] = [
        (
            ToolSpec(
                "workspace_list",
                "List the files in your notebook with their sizes and how much room is left. "
                "Takes no game time.",
                _object({}),
            ),
            lambda _args: ws.list(),
        ),
        (
            ToolSpec(
                "workspace_read",
                "Read a file from your notebook. Long files are read in parts (`offset`). "
                "Takes no game time.",
                _object(
                    {
                        "path": {"type": "string", "description": path_doc},
                        "offset": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Character to start reading from (default 0).",
                        },
                    },
                    ["path"],
                ),
            ),
            lambda a: ws.read(a["path"], int(a.get("offset", 0))),
        ),
        (
            ToolSpec(
                "workspace_write",
                f"Write a file in your notebook, replacing it, or adding to its end with "
                f"append. {folders} Takes no game time.",
                _object(
                    {
                        "path": {"type": "string", "description": path_doc},
                        "text": {"type": "string", "description": "What to write."},
                        "append": {
                            "type": "boolean",
                            "description": "Add to the end instead of replacing.",
                        },
                    },
                    ["path", "text"],
                ),
            ),
            lambda a: ws.write(a["path"], a["text"], bool(a.get("append", False))),
        ),
        (
            ToolSpec(
                "workspace_edit",
                "Replace one piece of text in a notebook file; `old` must occur exactly once. "
                "Takes no game time.",
                _object(
                    {
                        "path": {"type": "string", "description": path_doc},
                        "old": {"type": "string", "description": "Text to replace."},
                        "new": {"type": "string", "description": "New text."},
                    },
                    ["path", "old", "new"],
                ),
            ),
            lambda a: ws.edit(a["path"], a["old"], a["new"]),
        ),
        (
            ToolSpec(
                "workspace_search",
                "Search all notebook files for a word or phrase. Takes no game time.",
                _object(
                    {"query": {"type": "string", "description": "What to look for."}}, ["query"]
                ),
            ),
            lambda a: ws.search(a["query"]),
        ),
        (
            ToolSpec(
                "workspace_delete",
                "Delete a notebook file to make room. Takes no game time.",
                _object({"path": {"type": "string", "description": path_doc}}, ["path"]),
            ),
            lambda a: ws.delete(a["path"]),
        ),
    ]
    for spec, handler in tools:
        ctx.toolbox.register(ToolDef(spec, FREE, handler))


LAYER_REGISTRARS: dict[str, Callable[[LayerContext], None]] = {
    "L0": register_l0,
    "L1": register_l1,
    "L2": register_l2,
    "L3": register_l3,
    "L4": register_l4,
    "L5": register_l5,
}
MINIMAL_LAYERS = ("L0", "L1")
DEFAULT_LAYERS = tuple(sorted(LAYER_REGISTRARS))
ALL_LAYER_NAMES = ("L0", "L1", "L2", "L3", "L4", "L5")
CODE_LAYERS = ("L2", "L3", "L5")  # the layers that read scripts/ and plugins/
BOX_LAYERS = ("L2", "L3", "L5")  # the layers that run the player's code (in the box)
TOOL_LAYERS = ("L2", "L3", "L4", "L5")  # the layers that give the model tools to call


def check_layers(layers: Iterable[str], *, mode: str = "tools") -> None:
    """Refuse a set of layers that cannot be run as asked.

    Layers whose tools the model has to call (Code Mode, hooks, sub-agents, plugins) need the
    tool-call mode: in text mode the model only writes commands, so they would be switched on
    for nothing. The layers that run the player's code also need the box, and without it they do
    not start (the code is never run without it)."""
    names = tuple(layers)
    if mode == "text":
        wrong = [n for n in names if n in TOOL_LAYERS]
        if wrong:
            raise ConfigError(
                f"layers {', '.join(wrong)} give the model tools to call, and --mode text has no "
                "tool calls: use --mode tools, or --layers L0,L1 (the notebook is reached with "
                "memory_write and friends in text mode)"
            )
    if any(name in BOX_LAYERS for name in names):
        check_sandbox()


def resolve_layers(
    *, minimal: bool = False, requested: str | None = None, mode: str = "tools"
) -> tuple[str, ...]:
    """The layers of a run: the minimal setting, a list like `L0,L1`, or all that exist (all
    that a text-mode run can use, which is the minimal setting, when none are asked for)."""
    if minimal:
        return MINIMAL_LAYERS
    if requested is None:
        return MINIMAL_LAYERS if mode == "text" else DEFAULT_LAYERS
    names = tuple(dict.fromkeys(p.strip().upper() for p in requested.split(",") if p.strip()))
    for name in names:
        if name not in ALL_LAYER_NAMES:
            raise ConfigError(
                f"unknown layer `{name}`; the layers are {', '.join(ALL_LAYER_NAMES)}"
            )
        if name not in LAYER_REGISTRARS:
            raise ConfigError(f"layer {name} is not available yet (it comes with the next batch)")
    missing = [n for n in MINIMAL_LAYERS if n not in names]
    if missing:
        raise ConfigError(f"layers {' and '.join(MINIMAL_LAYERS)} are always needed")
    return tuple(sorted(names))


def build_toolbox(
    session: AgentSession,
    workspace: Workspace,
    budget: Budget,
    *,
    layers: Iterable[str],
    decisions_cap: int,
    adapter: ModelAdapter | None = None,
    price: ModelPrice | None = None,
    logs: RunLogs | None = None,
    wheelhouse: Path | None = None,
) -> ToolBox:
    """A toolbox with the tools of the given layers, in layer order."""
    toolbox = ToolBox(session)
    names = sorted(layers)
    code_area = any(n in CODE_LAYERS for n in names)
    ctx = LayerContext(
        toolbox,
        session,
        workspace,
        budget,
        decisions_cap,
        code_area,
        adapter,
        price,
        logs,
        wheelhouse,
        tuple(names),
        extras=toolbox.extras,
    )
    for name in names:
        LAYER_REGISTRARS[name](ctx)
    return toolbox
