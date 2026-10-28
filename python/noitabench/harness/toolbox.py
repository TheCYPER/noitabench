"""The tools the model can call, and the code that runs one turn's tool calls.

A tool is a `ToolDef`: its `ToolSpec` (name, description, schema), a kind and a handler.

- kind `game`: a command of the agent layer. All game calls of one turn run together as **one
  decision**, in the order given (a step of up to four commands). Their results come back
  one per call: each says how its command went, and the last one carries the whole answer.
- kind `free`: anything else (workspace, budget, Code Mode, hooks, plugins, sub-agents). It
  runs at once, takes no game time and costs no decision of its own. Its handler gets the
  arguments and returns a dict (shown as compact JSON), a string, or a `ToolOutput` (text with
  images and an error flag). A `CommandError` becomes an error result. A free tool that plays
  the game itself (`acts=True`: Code Mode, plugin tools) is a barrier: the game calls before
  it in the turn are decided first, so the turn is carried out in the order it was written.

Everything the toolbox hands back to the model passes through the shared `Redactor`
(`redact.py`) as a last net: the results of every tool, the notices of the layers and the
system-prompt suffix. The box and the logs have their own (`sandbox.py`, `logs.py`).

Layers can watch decisions (`on_decision`), leave a note for the end of the turn (`add_notice`:
what a hook printed) and add to the system prompt (`add_system_suffix`: plugin fragments, read
when a conversation is started). `layers.py` decides which tools exist. Later layers add theirs
through `ToolBox.register`.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from noitabench.agent import AgentSession, call_tool, render_text
from noitabench.agent.errors import CommandError

from .errors import HarnessError
from .model import ToolCall, ToolResult, ToolSpec
from .redact import Redactor, default_redactor

log = logging.getLogger(__name__)

GAME = "game"
FREE = "free"
Handler = Callable[[dict[str, Any]], "dict[str, Any] | str | ToolOutput"]
MAX_RESULT_CHARS = 30_000


@dataclass(frozen=True)
class ToolDef:
    spec: ToolSpec
    kind: str
    handler: Handler | None = None  # None for game tools
    acts: bool = False  # a free tool that plays the game by itself (see the module doc)


@dataclass(frozen=True)
class ToolOutput:
    """What a free tool returns when plain text is not enough."""

    text: str
    images: tuple[bytes, ...] = ()
    is_error: bool = False


def object_schema(properties: dict[str, Any], required: Iterable[str] = ()) -> dict[str, Any]:
    """The JSON schema of a tool whose input is an object."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class Executed:
    """The outcome of one turn's tool calls: a result per call, in the order of the calls, and
    the answer of the decision they made (None when no game command was among them)."""

    results: tuple[ToolResult, ...]
    answer: dict[str, Any] | None = None


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def result_line(record: dict[str, Any]) -> str:
    """One command's result as a short line (the agent layer's own wording)."""
    head = record["command"]
    if not record["ok"]:
        return f"{head}: FAILED ({record['code']}) {record['message']}"
    parts: list[str] = []
    stop = record.get("stop")
    if stop:
        parts.append(stop["reason"] + (f" ({stop['detail']})" if stop.get("detail") else ""))
    if "result" in record:
        parts.append(compact_json(record["result"]))
    return f"{head}: " + (" ".join(parts) or "ok")


def screenshot_of(answer: dict[str, Any]) -> tuple[bytes, ...]:
    shot = answer.get("observation", {}).get("screenshot")
    if not shot:
        return ()
    return (base64.b64decode(shot["data_base64"]),)


class ToolBox:
    """The tools of a run, and `execute`."""

    def __init__(self, session: AgentSession, redactor: Redactor | None = None) -> None:
        self.session = session
        self._redactor = redactor
        self._tools: dict[str, ToolDef] = {}
        self._watchers: list[Callable[[dict[str, Any]], None]] = []
        self._notices: list[str] = []
        self._suffixes: list[Callable[[], str]] = []
        self.extras: dict[str, Any] = {}  # what the layers share (`LayerContext.extras`)

    @property
    def redactor(self) -> Redactor:
        """The redactor of this run: the one given, else the shared one."""
        return self._redactor if self._redactor is not None else default_redactor()

    def clean(self, text: str) -> str:
        """`text` with the secrets hidden (see `redact.py`)."""
        return self.redactor.redact(text)

    # -- registration -----------------------------------------------------------------------------

    def register(self, tool: ToolDef) -> None:
        """Add a tool. Tool order is registration order and does not change during a run:
        tools come first in the prompt, so a changed set would drop the prompt cache."""
        if tool.spec.name in self._tools:
            raise ValueError(f"tool `{tool.spec.name}` is already registered")
        if tool.kind not in (GAME, FREE):
            raise ValueError(f"unknown tool kind {tool.kind!r}")
        if tool.kind == FREE and tool.handler is None:
            raise ValueError(f"free tool `{tool.spec.name}` needs a handler")
        self._tools[tool.spec.name] = tool

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> ToolDef | None:
        """The registered tool of that name, if any."""
        return self._tools.get(name)

    # -- what layers can hang on --------------------------------------------------------------------

    def on_decision(self, watcher: Callable[[dict[str, Any]], None]) -> None:
        """Call `watcher(answer)` after every decision made through this toolbox."""
        self._watchers.append(watcher)

    def add_notice(self, text: str) -> None:
        """Say something at the end of the turn that is running (or of the next one)."""
        self._notices.append(text)

    def add_system_suffix(self, source: Callable[[], str]) -> None:
        """Text for the end of the system prompt, asked for whenever a conversation is begun."""
        self._suffixes.append(source)

    def system_suffix(self) -> str:
        return self.clean("".join(part for part in (source() for source in self._suffixes) if part))

    def run_game_command(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """One command as one decision (the way a tool call is run); the watchers hear of it."""
        answer = call_tool(self.session, name, arguments)
        self._announce(answer)
        return answer

    def run_game_request(self, request: Any) -> dict[str, Any]:
        """A request of up to four commands as one decision; the watchers hear of it."""
        answer = self.session.decide(request)
        self._announce(answer)
        return answer

    def _announce(self, answer: dict[str, Any]) -> None:
        for watcher in self._watchers:
            try:
                watcher(answer)
            except HarnessError:
                raise
            except Exception:  # the decision is made: a layer's trouble must not undo the turn
                log.exception("a watcher of decisions failed")

    # -- running a turn ---------------------------------------------------------------------------

    def execute(self, calls: Sequence[ToolCall]) -> Executed:
        slots: list[ToolResult | None] = [None] * len(calls)
        game: list[int] = []
        answer: dict[str, Any] | None = None
        for i, call in enumerate(calls):
            tool = self._tools.get(call.name)
            if call.error is not None:
                slots[i] = _error(call, call.error)
            elif tool is None:
                slots[i] = _error(
                    call, f"There is no tool called `{call.name}`. Tools: {', '.join(self._tools)}."
                )
            elif tool.kind == GAME:
                game.append(i)
            else:
                if tool.acts and game:  # the commands written before it come first
                    answer = self._decide([calls[j] for j in game], game, slots)
                    game = []
                slots[i] = self._run_free(tool, call)
        if game:
            answer = self._decide([calls[j] for j in game], game, slots)
        results = [r for r in slots if r is not None]
        if self._notices and results:
            notes = "\n\n".join(self._notices)
            self._notices.clear()
            last = results[-1]
            results[-1] = replace(last, content=_clip(f"{last.content}\n\n{notes}"))
        return Executed(tuple(self._cleaned(r) for r in results), answer)

    def _cleaned(self, result: ToolResult) -> ToolResult:
        content = self.clean(result.content)
        return result if content == result.content else replace(result, content=content)

    def _run_free(self, tool: ToolDef, call: ToolCall) -> ToolResult:
        assert tool.handler is not None
        try:
            out = tool.handler(dict(call.arguments))
        except CommandError as err:
            return _error(call, f"{err.code}: {err.message}")
        except (TypeError, KeyError, ValueError) as err:
            return _error(call, f"bad_argument: {err}")
        except OSError as err:  # the disk, not the player's mistake: say so, keep going
            log.exception("tool %s failed", call.name)
            return _error(call, f"internal_error: {type(err).__name__}")
        except HarnessError:  # the run itself must stop (budget, configuration...)
            raise
        except Exception as err:  # one failing tool must not end a whole game
            log.exception("tool %s failed", call.name)
            return _error(call, f"internal_error: {type(err).__name__}")
        if isinstance(out, ToolOutput):
            return ToolResult(
                call.id, call.name, _clip(out.text), is_error=out.is_error, images=out.images
            )
        text = out if isinstance(out, str) else compact_json(out)
        return ToolResult(call.id, call.name, _clip(text))

    def _decide(
        self, calls: list[ToolCall], where: list[int], slots: list[ToolResult | None]
    ) -> dict[str, Any]:
        if len(calls) == 1:
            answer = self.run_game_command(calls[0].name, calls[0].arguments)
        else:
            request = [{"name": c.name, "args": dict(c.arguments)} for c in calls]
            answer = self.run_game_request(request)
        text = render_text(answer)
        images = screenshot_of(answer)
        records = _records_by_call(answer, calls)
        total = len(calls)
        for n, (call, slot) in enumerate(zip(calls, where, strict=True)):
            record = records[n]
            last = n == total - 1
            if record is None:
                line = f"{call.name}: not run (another command of this step was not valid)"
                failed = True
            else:
                line = result_line(record)
                failed = not record["ok"] and record.get("code") != "skipped"
            if total == 1:
                content = text
            else:
                content = f"Command {n + 1} of {total} in this step. {line}"
                if last:
                    content += f"\n\nThe whole step:\n{text}"
            slots[slot] = ToolResult(
                call.id, call.name, _clip(content), is_error=failed, images=images if last else ()
            )
        return answer


def _records_by_call(
    answer: dict[str, Any], calls: Sequence[ToolCall]
) -> list[dict[str, Any] | None]:
    """The result record of each call. A step that was refused before it ran (a command that
    could not be read, or more than four) has one record, for the command at fault; the other
    calls get None."""
    records = answer["results"]
    if len(records) == len(calls):
        return list(records)
    out: list[dict[str, Any] | None] = [None] * len(calls)
    if records:
        at_fault = next((i for i, c in enumerate(calls) if c.name == records[0]["command"]), 0)
        out[at_fault] = records[0]
    return out


def _error(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(call.id, call.name, message, is_error=True)


def _clip(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[: MAX_RESULT_CHARS - 40] + "\n... (cut: the answer was too long)"
