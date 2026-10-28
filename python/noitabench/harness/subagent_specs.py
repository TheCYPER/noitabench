"""What helpers (L4) are told and what they are called: tool names, prompts, tool specs and
the settings that limit them. Part of `subagents.py`."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .adapters import make_adapter
from .model import ModelAdapter, ModelConfig, ToolSpec
from .prices import DEFAULT_CONTEXT_LIMIT, LIMIT_MARGIN, ModelPrice
from .wandrange import PROMPT_WAND_RANGE

MAIN = "main"
VIEW = "view"
WAND_RANGE = "wand_range"
# The tools of the player's own toolbox that a helper may be given: the notebook and the practice
# range, by name (a prefix such as `workspace_` would also pick up a tool added later).
WORKSPACE_TOOLS = (
    "workspace_list",
    "workspace_read",
    "workspace_write",
    "workspace_edit",
    "workspace_search",
    "workspace_delete",
)
OUTSIDE_TOOLS = frozenset((*WORKSPACE_TOOLS, WAND_RANGE))
SPAWN, FORK, MESSAGE, LIST = "spawn_agent", "fork_agent", "agent_message", "agent_list"
HELPER_TOOLS = (SPAWN, FORK, MESSAGE, LIST)
EFFORTS = ("low", "medium", "high")
MAX_DEPTH = 2
MAX_TASK_CHARS = 8_000
MAX_PERSONA_CHARS = 300
MAX_VIEW_CHARS = 30_000
MAX_LOGGED_THINKING = 20_000
FORK_PROMPT_SHARE = 0.97  # of the first price boundary: a helper stops before it

PROMPT_HELPERS = """\
HELPERS
You can ask helpers to think for you while the game waits. A helper cannot act in the game: it \
can read and write your notebook, try wands on the practice range, and look at your latest view. \
`spawn_agent` starts one with a fresh mind (put everything it needs in `task`); `fork_agent` \
starts one that has read everything said so far in this game. A helper answers in a short text, \
you can give it more to do with `agent_message`, and `agent_list` shows your helpers. There are \
only so many helpers and steps, and what they use comes out of your allowance. Asking a helper \
takes no game time and no step.
"""
PROMPT_L4 = PROMPT_HELPERS + "\n" + PROMPT_WAND_RANGE

_HELPER_SYSTEM = """\
You are a helper of a player in a cave-exploration game. The player controls an explorer in a \
deep cave made of single cells of material: liquids flow, powders fall, gases rise, fire spreads, \
materials change when they touch. The goal of the game is to get as deep as possible.

You cannot act in the game and cannot see it unless you use `view`. You can think, read and write \
the player's notebook (it is the player's: keep what you write short and useful), try wands on \
the practice range, and ask your own helpers if you have the tools for it. The player asked you \
for one thing. Work in a few steps, then answer in plain text. Your answer is all the player \
reads, so make it short and exact: names, numbers, coordinates.
"""
_FORK_NOTE = """\
You are now a helper of the player, started by this `fork_agent` call. The conversation above is \
the player's and stops here for you. You cannot act in the game: game commands do not work for \
you. You can use {tools}. The player wants this from you: {task}
Work in a few steps, then answer in plain text; your answer is all the player reads."""
WRAP_UP = "This is your last step for now. Give your answer in plain text, without a tool."
NOT_RUN = "(not run: this is a helper's copy of the conversation, which stops at this turn)"
NOT_AVAILABLE = (
    "`{name}` is not available to a helper. A helper can use: {tools}. It cannot act in the game."
)


def helper_system(persona: str) -> str:
    """The system prompt of a fresh helper."""
    return _HELPER_SYSTEM + (f"\nYour role: {persona}\n" if persona else "")


def fork_note(tools: str, task: str) -> str:
    """What a forked helper is told when its copy of the conversation ends."""
    return _FORK_NOTE.format(tools=tools, task=task)


# -- settings -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SubModel:
    """A model helpers may be started on besides the player's own (same provider)."""

    config: ModelConfig
    price: ModelPrice | None


@dataclass(frozen=True)
class SubAgentSettings:
    models: Mapping[str, SubModel] = field(default_factory=dict)  # offered as `model`
    max_depth: int = MAX_DEPTH
    calls_per_agent: int = 12
    steps_per_message: int = 8
    max_agents: int = 8
    total_calls: int = 60
    answer_chars: int = 6_000
    prompt_limit: int | None = None  # tokens; default: just under the price boundary
    adapter_factory: Callable[[ModelConfig, ModelAdapter], ModelAdapter] | None = None


def default_factory(config: ModelConfig, base: ModelAdapter) -> ModelAdapter:
    return make_adapter(config, client=getattr(base, "client", None))


def prompt_limit(settings: SubAgentSettings, price: ModelPrice | None) -> int:
    if settings.prompt_limit:
        return settings.prompt_limit
    if price is not None:
        for tier in price.tiers:
            if tier.max_prompt_tokens is not None:
                return int(tier.max_prompt_tokens * FORK_PROMPT_SHARE)
    return int(DEFAULT_CONTEXT_LIMIT / LIMIT_MARGIN * FORK_PROMPT_SHARE)


# -- tool specs -----------------------------------------------------------------------------------


def _object(properties: dict[str, Any], required: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def view_spec() -> ToolSpec:
    return ToolSpec(
        VIEW,
        "Look at the player's latest view again: where the explorer is, what it carries, what is "
        "around, as text. Read-only; it shows what the player last saw.",
        _object({}),
    )


def helper_specs(settings: SubAgentSettings) -> list[ToolSpec]:
    tools_doc = (
        f"Which tools the helper gets: any of {', '.join(WORKSPACE_TOOLS)}, {WAND_RANGE}, {VIEW}. "
        "Default: all of them."
    )
    spawn_props: dict[str, Any] = {
        "task": {
            "type": "string",
            "description": "What you want, with everything the helper needs to know: it starts "
            "knowing nothing of your game.",
        },
        "persona": {
            "type": "string",
            "description": "Who the helper is, in a few words (for example a careful note keeper).",
        },
        "tools": {"type": "array", "items": {"type": "string"}, "description": tools_doc},
        "effort": {
            "type": "string",
            "enum": list(EFFORTS),
            "description": "How hard the helper thinks (lower costs less).",
        },
    }
    if settings.models:
        spawn_props["model"] = {
            "type": "string",
            "enum": ["same", *settings.models],
            "description": "Which model the helper runs on (default: yours).",
        }
    return [
        ToolSpec(
            SPAWN,
            "Start a helper with a fresh mind. It cannot act in the game; it can use your "
            "notebook, the practice range and a look at your latest view, and answers in text. "
            "Takes no game time and no step; its model calls come out of your allowance.",
            _object(spawn_props, ["task"]),
        ),
        ToolSpec(
            FORK,
            "Start a helper that has read everything said so far in this game, up to now. It "
            "cannot act in the game. Cheaper than it looks when the conversation is long, since "
            "that part is already stored. Takes no game time and no step.",
            _object(
                {
                    "task": {"type": "string", "description": "What you want from the helper."},
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": tools_doc,
                    },
                },
                ["task"],
            ),
        ),
        ToolSpec(
            MESSAGE,
            "Give a helper you started more to do (or answer what it said). Returns its answer.",
            _object(
                {
                    "id": {"type": "string", "description": "The helper's id, like a1."},
                    "text": {"type": "string", "description": "What to tell it."},
                },
                ["id", "text"],
            ),
        ),
        ToolSpec(LIST, "List the helpers you started, with their state.", _object({})),
    ]
