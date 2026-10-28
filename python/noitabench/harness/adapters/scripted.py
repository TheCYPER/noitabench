"""A model that follows a script: no network, no cost.

Tests use it to drive whole games through the real loop; `--provider fake` uses `demo_policy`
to check the plumbing (world, workspace, logs) without a key. The conversation keeps an
append-only record of what it was sent and what it answered (`history`), so that tests can
check what the loop put in front of a model.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..errors import ModelError
from ..model import (
    END_TURN,
    MAX_TOKENS,
    REFUSAL,
    TOOL_USE,
    Conversation,
    Item,
    ModelAdapter,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from ..usage import Usage

_ids = itertools.count(1)
CHARS_PER_TOKEN = 4


def call(name: str, call_id: str | None = None, **arguments: Any) -> ToolCall:
    """A tool call, with a fresh id unless one is given."""
    return ToolCall(call_id or f"toolu_{next(_ids):04d}", name, arguments)


@dataclass(frozen=True)
class Say:
    """One scripted answer. `usage` is computed from the sizes when left out."""

    text: str = ""
    calls: tuple[ToolCall, ...] = ()
    stop: str | None = None  # default: tool_use if there are calls, else end_turn
    thinking: str = ""
    usage: Usage | None = None
    error: ModelError | None = None  # raised instead of answering

    @staticmethod
    def tools(*calls: ToolCall, **fields: Any) -> Say:
        """An answer that calls tools (`text`, `thinking`, `usage`... as keywords)."""
        return Say(calls=tuple(calls), **fields)


Scripted = Say | Callable[["ScriptedConversation", Sequence[Item]], Say]


@dataclass
class ScriptedConversation(Conversation):
    adapter: ScriptedAdapter
    system: str
    tools: tuple[ToolSpec, ...]
    history: list[dict[str, Any]] = field(default_factory=list)
    sends: int = 0

    def __post_init__(self) -> None:
        self.last_prompt_tokens = 0

    def _prompt_chars(self, items: Sequence[Item]) -> int:
        size = len(self.system) + sum(len(t.description) for t in self.tools)
        for entry in self.history:
            size += _chars(entry)
        return size + sum(_item_chars(i) for i in items)

    def send(self, items: Sequence[Item]) -> ModelTurn:
        if not items:
            raise ValueError("nothing to send")
        self.sends += 1
        say = self.adapter.next_say(self, items)
        if say.error is not None:
            raise say.error
        prompt_chars = self._prompt_chars(items)
        prompt = prompt_chars // CHARS_PER_TOKEN
        previous = self.last_prompt_tokens
        out_chars = (
            len(say.text) + len(say.thinking) + sum(len(str(c.arguments)) for c in say.calls)
        )
        usage = say.usage or Usage(
            input_tokens=max(prompt - previous, 0) if previous else prompt,
            cache_read_tokens=previous if previous else 0,
            output_tokens=max(out_chars // CHARS_PER_TOKEN, 1),
        )
        stop = say.stop or (TOOL_USE if say.calls else END_TURN)
        turn = ModelTurn(
            text=say.text,
            thinking=say.thinking,
            tool_calls=() if stop in (MAX_TOKENS, REFUSAL) else say.calls,
            stop=stop,
            usage=usage,
            latency_s=0.0,
            request_id=f"fake-{self.adapter.calls + 1}",
            raw_stop=stop,
            model=self.adapter.model,
        )
        self.adapter.calls += 1
        if stop == REFUSAL:
            return turn  # nothing is appended
        self.history.append({"role": "user", "items": list(items)})
        self.history.append(
            {"role": "assistant", "text": say.text, "calls": list(turn.tool_calls), "stop": stop}
        )
        self.last_prompt_tokens = usage.prompt_tokens
        return turn


def _item_chars(item: Item) -> int:
    return len(item.content if isinstance(item, ToolResult) else item.text)


def _chars(entry: dict[str, Any]) -> int:
    if entry["role"] == "user":
        return sum(_item_chars(i) for i in entry["items"])
    return len(entry["text"]) + sum(len(str(c.arguments)) for c in entry["calls"])


class ScriptedAdapter(ModelAdapter):
    """Answers from a script: a list of `Say` (or functions making one), used in order."""

    provider = "fake"

    def __init__(self, script: Iterable[Scripted], *, model: str = "fake") -> None:
        self.model = model
        self._script: Iterator[Scripted] = iter(script)
        self.conversations: list[ScriptedConversation] = []
        self.calls = 0

    def new_conversation(self, system: str, tools: Sequence[ToolSpec]) -> ScriptedConversation:
        conversation = ScriptedConversation(self, system, tuple(tools))
        self.conversations.append(conversation)
        return conversation

    def next_say(self, conversation: ScriptedConversation, items: Sequence[Item]) -> Say:
        try:
            step = next(self._script)
        except StopIteration:
            raise AssertionError("the scripted model has no more answers") from None
        return step(conversation, items) if callable(step) else step


def demo_policy(mode: str = "tools", *, note_every: int = 12) -> Iterator[Say]:
    """An endless, harmless policy for `--provider fake`: walk a little, look, write a note."""
    moves = (
        ("move", {"direction": "right", "ticks": 4}),
        ("jump", {"direction": "right"}),
        ("move", {"direction": "left", "ticks": 2}),
        ("inspect", {"x": 0, "y": 0}),  # cells out of view answer with an error: also fine
        ("wait", {"ticks": 2}),
    )
    for n in itertools.count():
        name, args = moves[n % len(moves)]
        if n == 0:
            yield _write_note(mode, "notes/log.md", "walked about\n")
        elif n % note_every == 0:
            yield _write_note(mode, "notes/log.md", f"turn {n}\n", append=True)
        elif mode == "text":
            yield Say(text=f"{name}({', '.join(f'{k}={v}' for k, v in args.items())})")
        else:
            yield Say.tools(call(name, **args))


def _write_note(mode: str, path: str, text: str, append: bool = False) -> Say:
    if mode == "text":
        flag = ", append=true" if append else ""
        return Say(text=f'memory_write(path="{path}", text="{text.strip()}"{flag})')
    return Say.tools(call("workspace_write", path=path, text=text, append=append))
