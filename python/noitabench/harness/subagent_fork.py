"""Forking a conversation, and finding the conversation of the player to fork.

Part of L4 (`subagents.py`). A fork is a *new* conversation over a copy of the parent's whole
history, including the assistant turn that asked for the fork; it keeps the parent's system prompt
and tool list, so the provider's prompt cache stays warm. That last turn has tool calls without
results yet: the fork's first message answers them (the caller builds it), so the copy is a valid
history for every provider (a tool result for every tool call, user and assistant turns
alternating). Nothing of the parent is written to.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from noitabench.agent.errors import CommandError

from .model import Conversation, ModelAdapter, ToolSpec

HISTORY_ATTRS = ("messages", "contents", "history")  # where the adapters keep the history
ASSISTANT_ROLES = ("assistant", "model")


class ParentLink:
    """Where the helpers find the conversation of the player (the main loop's)."""

    def __init__(self) -> None:
        self.conversation: Conversation | None = None
        self.system = ""
        self.tools: tuple[ToolSpec, ...] = ()
        self._muted = False

    def bind(self, conversation: Conversation, system: str, tools: Sequence[ToolSpec]) -> None:
        self.conversation, self.system, self.tools = conversation, system, tuple(tools)

    def follow(self, adapter: ModelAdapter) -> None:
        """Remember every conversation `adapter` opens, except those opened inside `muted()`.

        An adapter that is followed already (a family of games shares one adapter) is handed to
        this link instead of being wrapped again, so the wrappers do not pile up and the earlier
        games' links stop being fed."""
        current = adapter.new_conversation
        holder: list[ParentLink] | None = getattr(current, "holder", None)
        if holder is not None:
            holder[0] = self
            return
        holder = [self]

        def new_conversation(system: str, tools: Sequence[ToolSpec]) -> Conversation:
            conversation = current(system, tools)
            link = holder[0]
            if not link._muted:
                link.bind(conversation, system, tools)
            return conversation

        new_conversation.holder = holder  # type: ignore[attr-defined]
        adapter.new_conversation = new_conversation  # type: ignore[method-assign]

    @contextmanager
    def muted(self) -> Iterator[None]:
        """Conversations opened inside are the helpers' own, not the player's."""
        was, self._muted = self._muted, True
        try:
            yield
        finally:
            self._muted = was


def _role(entry: Any) -> Any:
    return entry.get("role") if isinstance(entry, dict) else getattr(entry, "role", None)


def fork_conversation(
    adapter: ModelAdapter,
    parent: Conversation,
    system: str,
    tools: Sequence[ToolSpec],
) -> Conversation:
    """A new conversation over a copy of `parent`'s history (see the module doc).

    Nothing of `parent` is written to: the list is copied, its entries (never edited by the
    adapters) are shared. The last entry must be an assistant turn, the one that asked for the
    fork."""
    attr = next((a for a in HISTORY_ATTRS if isinstance(getattr(parent, a, None), list)), None)
    history: list[Any] = getattr(parent, attr, []) if attr else []
    if attr is None or not history or _role(history[-1]) not in ASSISTANT_ROLES:
        raise CommandError(
            "cannot_fork", "fork_agent: this conversation cannot be forked; use spawn_agent."
        )
    child = adapter.new_conversation(system, tools)
    setattr(child, attr, list(history))
    child.last_prompt_tokens = parent.last_prompt_tokens
    return child
