"""L4: helpers (sub-agents), design 6.2 and 7.

The player may start *helpers*: other model conversations that think for it while the game waits.
A helper never touches the game (design 7, "c"): it can read and write the notebook
(`workspace_*`), try wands on the practice range (`wand_range`) and look at the player's latest
view (`view`, read-only). Four tools, all free for the game (no game time, no step):

    spawn_agent(task, persona?, tools?, effort?, model?)   a fresh mind: it knows only `task`
    fork_agent(task, tools?)         a mind that has read the whole conversation so far
    agent_message(id, text)          give a helper more to do
    agent_list()                     the helpers this conversation started

**Forking.** A fork is a *new* conversation whose history is a copy of the parent's whole history,
including the assistant turn that asked for the fork. That turn's tool calls have no results yet;
the fork's first message answers all of them (its own `fork_agent` call with the helper's briefing,
every other call of the turn with "not run"), so the copy is a valid history for every provider
and the parent's turn is not touched. The system prompt and the tool list are the parent's own,
byte for byte, so the provider's prompt cache stays warm: the child pays cache-read prices for
everything the parent said. The parent's conversation is never written to; the child only appends
to its own copy, as every conversation does. Because the tool list is the parent's, a fork *sees*
the game commands; asking for one is answered with an error (a helper has no hands).

**Where the parent's conversation and turn come from.** The loop does not hand them to the tools.
`ParentLink` follows the adapter: `follow(adapter)` wraps `adapter.new_conversation`, so the latest
conversation the main loop opens (also after a briefing starts a new one) is the one a fork copies,
with the system prompt and tools it was opened with. `register_l4` also wraps `toolbox.execute` to
note the calls of the turn being run. If the loop binds the conversation explicitly with
`ParentLink.bind(conversation, system, tools)`, that wins and the wrapper is not needed. A helper's
tool calls (notebook, practice range) are run directly on the player's tools, not through
`toolbox.execute`, so they never take the notices meant for the player's turn.

**Tools.** A helper is given some of: the notebook tools and `wand_range` (by exact name,
`OUTSIDE_TOOLS`), `view`, the helper tools. A helper can start one only with tools it has itself.
Anything else it calls (a game command, `budget`, the tools of other layers) is an error result.

**Limits.** Depth 2 (the player's helpers, and theirs); one helper runs at a time (the tool call
returns when it has answered); at most `calls_per_agent` model calls per helper and `total_calls`
for all, `steps_per_message` per message, `max_agents` helpers; a helper stops before its prompt
passes `prompt_limit` tokens (the price boundary). Every call of every helper is charged to the
one shared `Budget` and written to `harness.jsonl` and `transcript.jsonl` with the helper's id.
When a helper is stopped before it has answered, what it was not yet sent (the results of its
last tool calls, the words of the player) is kept, and the next `agent_message` sends it first, so
its history never has an unanswered tool call, and a result is never sent twice.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from typing import TYPE_CHECKING, Any

from noitabench.agent import render_text
from noitabench.agent.errors import CommandError

from .errors import ConfigError, ModelError
from .model import (
    MAX_TOKENS,
    REFUSAL,
    Conversation,
    Item,
    ModelAdapter,
    ModelConfig,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolSpec,
    UserText,
)
from .prices import ModelPrice
from .prompt import NUDGE_CUT_OFF
from .subagent_fork import ParentLink, fork_conversation
from .subagent_specs import (
    EFFORTS,
    FORK,
    HELPER_TOOLS,
    LIST,
    MAIN,
    MAX_LOGGED_THINKING,
    MAX_PERSONA_CHARS,
    MAX_TASK_CHARS,
    MAX_VIEW_CHARS,
    MESSAGE,
    NOT_AVAILABLE,
    NOT_RUN,
    OUTSIDE_TOOLS,
    PROMPT_L4,
    SPAWN,
    VIEW,
    WRAP_UP,
    SubAgentSettings,
    SubModel,
    default_factory,
    fork_note,
    helper_specs,
    helper_system,
    prompt_limit,
    view_spec,
)
from .toolbox import FREE, Executed, ToolBox, ToolDef, ToolOutput, compact_json
from .usage import Usage
from .wandrange import register_wand_range

if TYPE_CHECKING:  # layers.py imports the layer modules: no import cycle at run time
    from .layers import LayerContext

log = logging.getLogger(__name__)

__all__ = [
    "HELPER_TOOLS",
    "NOT_AVAILABLE",
    "PROMPT_L4",
    "WRAP_UP",
    "ParentLink",
    "SubAgentHub",
    "SubAgentSettings",
    "SubModel",
    "fork_conversation",
    "helper_specs",
    "register_l4",
    "view_spec",
]

# -- one helper -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Grant:
    """What a helper may call: tools of the player's toolbox, `view`, the helper tools."""

    outside: frozenset[str]
    view: bool
    helpers: bool

    def names(self) -> list[str]:
        return sorted(
            self.outside
            | ({VIEW} if self.view else set())
            | (set(HELPER_TOOLS) if self.helpers else set())
        )


@dataclass
class Helper:
    id: str
    kind: str  # spawn or fork
    parent: str  # MAIN or the id of the helper that started it
    depth: int
    persona: str
    adapter: ModelAdapter
    price: ModelPrice | None
    conversation: Conversation
    system: str
    tools: tuple[ToolSpec, ...]  # what the conversation was opened with
    grant: Grant
    calls: int = 0
    pending: list[Item] = field(default_factory=list)  # tool results not yet sent
    answer: str = ""
    state: str = "new"  # new, done or stopped
    stopped_because: str | None = None
    usage: Usage = field(default_factory=Usage)
    cost_usd: float | None = 0.0


class _Stop(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _text_arg(args: Mapping[str, Any], name: str, limit: int, *, required: bool = True) -> str:
    value = args.get(name)
    if value is None or value == "":
        if required:
            raise CommandError("bad_argument", f"{name}: say what you want.")
        return ""
    if not isinstance(value, str):
        raise CommandError("bad_argument", f"{name} is text.")
    if len(value) > limit:
        raise CommandError("bad_argument", f"{name} is longer than {limit} characters.")
    return value.strip()


class PendingTurn:
    """The tool calls of the assistant turn that is being answered: a fork's first message
    answers all of them (its own `fork_agent` call with the helper's briefing, the others with
    "not run"), because its copy of the conversation ends with that turn."""

    def __init__(self) -> None:
        self.calls: tuple[ToolCall, ...] = ()
        self._served: set[str] = set()

    def set(self, calls: Sequence[ToolCall]) -> None:
        self.calls, self._served = tuple(calls), set()

    def claim_fork(self, args: Mapping[str, Any]) -> ToolCall | None:
        """The `fork_agent` call that is being run now: the next one with these arguments, else
        the next one not served yet."""
        forks = [c for c in self.calls if c.name == FORK and c.id not in self._served]
        mine = next((c for c in forks if dict(c.arguments) == dict(args)), None) or next(
            iter(forks), None
        )
        if mine is not None:
            self._served.add(mine.id)
        return mine


class SubAgentHub:
    """The helpers of one game."""

    def __init__(self, ctx: LayerContext, settings: SubAgentSettings, link: ParentLink) -> None:
        _check_models(settings, ctx.adapter)
        self.ctx = ctx
        self.settings = settings
        self.link = link
        self.helpers: dict[str, Helper] = {}
        self.total_calls = 0
        self.usage = Usage()
        self.cost_usd: float | None = 0.0
        self._adapters: dict[tuple[str, str, str | None], ModelAdapter] = {}
        self._turns: dict[str, PendingTurn] = {}

    # -- the turn being answered ----------------------------------------------------------------

    def note_player_turn(self, calls: Sequence[ToolCall]) -> None:
        """The player's toolbox is about to run `calls`: one assistant turn."""
        self._turns.setdefault(MAIN, PendingTurn()).set(calls)

    def _briefing(self, owner: str, args: Mapping[str, Any], note: str) -> list[ToolResult]:
        """The first message of a fork: a result for every call of the turn that started it."""
        turn = self._turns.get(owner)
        mine = turn.claim_fork(args) if turn is not None else None
        if turn is None or mine is None:
            raise CommandError(
                "cannot_fork", "fork_agent: there is no turn to fork from; use spawn_agent."
            )
        return [
            ToolResult(c.id, c.name, note)
            if c.id == mine.id
            else ToolResult(c.id, c.name, NOT_RUN, is_error=True)
            for c in turn.calls
        ]

    # -- what a helper may use ----------------------------------------------------------------

    def _outside_names(self) -> list[str]:
        """Tools of the player's toolbox that helpers may call: notebook and practice range."""
        return [n for n in self.ctx.toolbox.names() if n in OUTSIDE_TOOLS]

    def _ceiling(self, owner: str) -> Grant:
        """What `owner` may hand on: everything for the player, a helper's own tools for a helper
        (a helper cannot start one that can do more than it can)."""
        if owner == MAIN:
            return Grant(frozenset(self._outside_names()), True, True)
        return self.helpers[owner].grant

    def _choose(self, wanted: Any, depth: int, owner: str) -> Grant:
        """What a new helper of `owner` at `depth` may call: everything `owner` may give, or what
        `wanted` names."""
        ceiling = self._ceiling(owner)
        deeper = ceiling.helpers and depth < self.settings.max_depth
        if wanted is None:
            return Grant(ceiling.outside, ceiling.view, deeper)
        if not isinstance(wanted, list) or not all(isinstance(n, str) for n in wanted):
            raise CommandError("bad_argument", "tools is a list of tool names.")
        outside = [n for n in self._outside_names() if n in ceiling.outside]
        allowed = [*outside, *([VIEW] if ceiling.view else []), *(HELPER_TOOLS if deeper else ())]
        unknown = [n for n in wanted if n not in allowed]
        if unknown:
            raise CommandError(
                "bad_argument",
                f"a helper can be given: {', '.join(allowed)}; not {', '.join(unknown)}.",
            )
        return Grant(
            frozenset(n for n in wanted if n in outside),
            VIEW in wanted,
            deeper and any(n in HELPER_TOOLS for n in wanted),
        )

    def _specs(self, grant: Grant) -> tuple[ToolSpec, ...]:
        """The tool list of a fresh helper, in the player's order, then `view` and the helper
        tools."""
        specs = [s for s in self.ctx.toolbox.specs() if s.name in grant.outside]
        if grant.view:
            specs.append(view_spec())
        if grant.helpers:
            specs += [s for s in helper_specs(self.settings) if s.name in HELPER_TOOLS]
        return tuple(specs)

    # -- who is asking ------------------------------------------------------------------------

    def _owner_depth(self, owner: str) -> int:
        return 0 if owner == MAIN else self.helpers[owner].depth

    def _room(self, owner: str) -> None:
        if self._owner_depth(owner) >= self.settings.max_depth:
            raise CommandError("too_deep", "helpers can go two levels deep, no further.")
        if len(self.helpers) >= self.settings.max_agents:
            raise CommandError(
                "too_many_helpers", f"at most {self.settings.max_agents} helpers in a game."
            )
        if self.total_calls >= self.settings.total_calls:
            raise CommandError("helpers_used_up", "the helpers' steps for this game are used up.")

    def _owner_model(self, owner: str) -> tuple[ModelAdapter, ModelPrice | None]:
        if owner == MAIN:
            if self.ctx.adapter is None:
                raise CommandError("helper_unavailable", "no model is available for helpers.")
            return self.ctx.adapter, self.ctx.price
        h = self.helpers[owner]
        return h.adapter, h.price

    def _adapter_for(
        self, owner: str, args: Mapping[str, Any]
    ) -> tuple[ModelAdapter, ModelPrice | None]:
        """The adapter and price for a fresh helper: the owner's, another model of the same
        provider from the settings, or the owner's model at another effort."""
        model, effort = args.get("model"), args.get("effort")
        if effort is not None and effort not in EFFORTS:
            raise CommandError("bad_argument", f"effort is one of {', '.join(EFFORTS)}.")
        base, price = self._owner_model(owner)
        if model in (None, "same"):
            config = getattr(base, "config", None)
            if effort is None or not isinstance(config, ModelConfig) or config.effort == effort:
                return base, price
            return self._sibling(config, effort, base), price
        sub = self.settings.models.get(model) if isinstance(model, str) else None
        if sub is None:
            names = ", ".join(["same", *self.settings.models])
            raise CommandError("bad_argument", f"model is one of {names}.")
        return self._sibling(sub.config, effort, base), sub.price

    def _sibling(self, config: ModelConfig, effort: str | None, base: ModelAdapter) -> ModelAdapter:
        """An adapter for `config` (at `effort`) that shares `base`'s client; built once."""
        key = (config.provider, config.model, effort)
        if key not in self._adapters:
            wanted = replace(config, effort=effort) if effort else config
            factory = self.settings.adapter_factory or default_factory
            try:
                self._adapters[key] = factory(wanted, base)
            except ConfigError as err:
                raise CommandError(
                    "helper_unavailable", f"cannot start that helper: {err}"
                ) from err
        return self._adapters[key]

    # -- the four tools -----------------------------------------------------------------------

    def spawn(self, owner: str, args: Mapping[str, Any]) -> dict[str, Any]:
        task = _text_arg(args, "task", MAX_TASK_CHARS)
        persona = _text_arg(args, "persona", MAX_PERSONA_CHARS, required=False)
        self._room(owner)
        depth = self._owner_depth(owner) + 1
        grant = self._choose(args.get("tools"), depth, owner)
        adapter, price = self._adapter_for(owner, args)
        system = helper_system(persona)
        tools = self._specs(grant)
        with self.link.muted():
            conversation = adapter.new_conversation(system, tools)
        helper = self._add(SPAWN, owner, depth, persona, adapter, price, conversation, system)
        helper.tools, helper.grant = tools, grant
        self._log_event("spawn", helper, task)
        return self._converse(helper, [UserText(task)])

    def fork(self, owner: str, args: Mapping[str, Any]) -> dict[str, Any]:
        task = _text_arg(args, "task", MAX_TASK_CHARS)
        self._room(owner)
        depth = self._owner_depth(owner) + 1
        grant = self._choose(args.get("tools"), depth, owner)
        adapter, price = self._owner_model(owner)
        parent, system, tools = self._parent_state(owner)
        if parent.last_prompt_tokens >= prompt_limit(self.settings, price):
            raise CommandError(
                "too_long_to_fork",
                "fork_agent: the conversation is too long to copy; use spawn_agent.",
            )
        briefing = self._briefing(owner, args, fork_note(", ".join(grant.names()), task))
        with self.link.muted():
            conversation = fork_conversation(adapter, parent, system, tools)
        helper = self._add(FORK, owner, depth, "", adapter, price, conversation, system)
        helper.tools, helper.grant = tuple(tools), grant
        self._log_event("fork", helper, task)
        return self._converse(helper, briefing)

    def message(self, owner: str, args: Mapping[str, Any]) -> dict[str, Any]:
        helper = self._own(owner, args.get("id"))
        text = _text_arg(args, "text", MAX_TASK_CHARS)
        self._log_event("message", helper, text)
        return self._converse(helper, [UserText(text)])

    def listing(self, owner: str) -> dict[str, Any]:
        mine = [h for h in self.helpers.values() if h.parent == owner]
        return {
            "helpers": [self._line(h) for h in mine],
            "helpers_left": max(self.settings.max_agents - len(self.helpers), 0),
        }

    def _line(self, h: Helper) -> dict[str, Any]:
        line: dict[str, Any] = {
            "id": h.id,
            "kind": h.kind,
            "state": h.state,
            "calls_left": max(self.settings.calls_per_agent - h.calls, 0),
        }
        if h.persona:
            line["persona"] = h.persona
        if h.answer:
            line["last_answer"] = h.answer[:100] + ("..." if len(h.answer) > 100 else "")
        return line

    def _own(self, owner: str, ident: Any) -> Helper:
        helper = self.helpers.get(ident) if isinstance(ident, str) else None
        if helper is None or helper.parent != owner:
            raise CommandError("no_such_helper", f"agent_message: you have no helper `{ident}`.")
        return helper

    def _parent_state(self, owner: str) -> tuple[Conversation, str, tuple[ToolSpec, ...]]:
        if owner == MAIN:
            if self.link.conversation is None:
                raise CommandError(
                    "cannot_fork", "fork_agent: there is no conversation to copy; use spawn_agent."
                )
            return self.link.conversation, self.link.system, self.link.tools
        h = self.helpers[owner]
        return h.conversation, h.system, h.tools

    def _add(
        self,
        kind: str,
        owner: str,
        depth: int,
        persona: str,
        adapter: ModelAdapter,
        price: ModelPrice | None,
        conversation: Conversation,
        system: str,
    ) -> Helper:
        helper = Helper(
            id=f"a{len(self.helpers) + 1}",
            kind=kind,
            parent=owner,
            depth=depth,
            persona=persona,
            adapter=adapter,
            price=price,
            conversation=conversation,
            system=system,
            tools=(),
            grant=Grant(frozenset(), False, False),
            cost_usd=0.0 if price is not None else None,
        )
        self.helpers[helper.id] = helper
        return helper

    # -- a helper at work ---------------------------------------------------------------------

    def _converse(self, helper: Helper, message: Sequence[Item]) -> dict[str, Any]:
        """Give `helper` a message (items for its next turn) and run it until it answers or is
        stopped."""
        calls_before = helper.calls
        try:
            answer = self._work(helper, message)
            helper.state, helper.stopped_because = "done", None
        except _Stop as stop:
            answer = ""
            helper.state, helper.stopped_because = "stopped", stop.reason
        helper.answer = answer or helper.answer
        result: dict[str, Any] = {
            "agent": helper.id,
            "answer": (helper.answer or "(no answer)")[: self.settings.answer_chars],
            "state": helper.state,
            "calls_used": helper.calls - calls_before,
            "calls_left": max(self.settings.calls_per_agent - helper.calls, 0),
        }
        if helper.stopped_because:
            why = helper.stopped_because
            result["stopped_because"] = _STOP_TEXT.get(why, why)
        self._log_event("answer", helper, helper.answer, state=helper.state)
        return result

    def _work(self, helper: Helper, message: Sequence[Item]) -> str:
        """Send `message` (after whatever an earlier stop left unsent), run the tools the helper
        asks for, and go on until it answers in text or a limit stops it. What was not sent when
        it stopped (tool results, the player's words) is kept in `helper.pending`."""
        items: list[Item] = [*helper.pending, *message]
        helper.pending = []
        steps = 0
        while True:
            try:
                self._check(helper, steps)
                last = steps + 1 >= self.settings.steps_per_message or self._last_call(helper)
                turn = self._send(helper, [*items, UserText(WRAP_UP)] if last else items)
            except _Stop:
                helper.pending = items
                raise
            steps += 1
            if turn.stop == REFUSAL:
                helper.pending = items  # a refusal is not in the conversation: send it again
                raise _Stop("refused")
            if turn.stop == MAX_TOKENS:
                items = [UserText(NUDGE_CUT_OFF)]
                continue
            if not turn.tool_calls:
                return turn.text.strip()
            self._turns.setdefault(helper.id, PendingTurn()).set(turn.tool_calls)
            items = list(self._execute(helper, turn.tool_calls))

    def _last_call(self, helper: Helper) -> bool:
        s = self.settings
        return helper.calls + 1 >= s.calls_per_agent or self.total_calls + 1 >= s.total_calls

    def _check(self, helper: Helper, steps: int) -> None:
        s = self.settings
        if steps >= s.steps_per_message:
            raise _Stop("steps")
        if helper.calls >= s.calls_per_agent:
            raise _Stop("calls")
        if self.total_calls >= s.total_calls:
            raise _Stop("total_calls")
        why = self.ctx.budget.exhausted()
        if why:
            raise _Stop(why)
        if helper.conversation.last_prompt_tokens >= prompt_limit(s, helper.price):
            raise _Stop("context")

    def _send(self, helper: Helper, items: Sequence[Item]) -> ModelTurn:
        try:
            turn = helper.conversation.send(items)
        except ModelError as err:
            self._log_call(helper, {"call": helper.calls + 1, "error": err.as_dict()})
            raise _Stop(f"model_error ({err.kind})") from err
        helper.calls += 1
        self.total_calls += 1
        cost = self._charge(helper, turn)
        self._log_turn(helper, turn, cost)
        return turn

    def _charge(self, helper: Helper, turn: ModelTurn) -> float | None:
        """Charge a finished call to the shared budget and to the helper's and the hub's totals."""
        cost = helper.price.cost(turn.usage) if helper.price is not None else None
        self.ctx.budget.charge(cost)
        helper.usage += turn.usage
        self.usage += turn.usage
        if cost is None:
            helper.cost_usd = self.cost_usd = None
        else:
            helper.cost_usd = None if helper.cost_usd is None else helper.cost_usd + cost
            self.cost_usd = None if self.cost_usd is None else self.cost_usd + cost
        return cost

    def _log_turn(self, helper: Helper, turn: ModelTurn, cost: float | None) -> None:
        decision = self.ctx.session.decisions
        self._log_call(
            helper,
            {
                "call": helper.calls,
                "purpose": "helper",
                "provider": helper.adapter.provider,
                "model": turn.model or helper.adapter.model,
                "decision": decision,
                **turn.usage.as_dict(),
                "prompt_tokens": turn.usage.prompt_tokens,
                "cost_usd": None if cost is None else round(cost, 6),
                "cumulative_usd": round(self.ctx.budget.spent_usd, 6),
                "latency_s": round(turn.latency_s, 3),
                "stop_reason": turn.raw_stop or turn.stop,
                "request_id": turn.request_id,
            },
        )
        if self.ctx.logs is not None:
            self.ctx.logs.transcript(
                "assistant",
                agent=helper.id,
                call=helper.calls,
                purpose="helper",
                decision=decision,
                text=turn.text,
                thinking=turn.thinking[:MAX_LOGGED_THINKING],
                tool_calls=[
                    {"id": c.id, "name": c.name, "arguments": c.arguments} for c in turn.tool_calls
                ],
                stop=turn.stop,
            )

    # -- a helper's tools ---------------------------------------------------------------------

    def _execute(self, helper: Helper, calls: Sequence[ToolCall]) -> list[ToolResult]:
        """The results of one turn's tool calls, in order. Only what the helper was granted runs:
        a game command, the budget or anything else is an error result."""
        grant = helper.grant
        out: list[ToolResult] = []
        for call in calls:
            if call.error is not None:
                out.append(ToolResult(call.id, call.name, call.error, is_error=True))
            elif call.name == VIEW and grant.view:
                out.append(self._answer(call, self.view))
            elif call.name in HELPER_TOOLS and grant.helpers:
                out.append(self._answer(call, partial(self._helper_tool, helper.id, call)))
            elif call.name in grant.outside and (tool := _free_tool(self.ctx.toolbox, call.name)):
                out.append(self._answer(call, partial(_run_tool, tool, call)))
            else:
                text = NOT_AVAILABLE.format(name=call.name, tools=", ".join(grant.names()))
                out.append(ToolResult(call.id, call.name, text, is_error=True))
        out = [self._cleaned(r) for r in out]
        if self.ctx.logs is not None:
            self.ctx.logs.transcript(
                "results",
                agent=helper.id,
                call=helper.calls,
                results=[
                    {"id": r.call_id, "name": r.name, "is_error": r.is_error, "content": r.content}
                    for r in out
                ],
            )
        return out

    def _cleaned(self, result: ToolResult) -> ToolResult:
        """A helper's tool result with the secrets hidden (the player's results get the same
        last net in `ToolBox.execute`)."""
        content = self.ctx.toolbox.clean(result.content)
        return result if content == result.content else replace(result, content=content)

    @staticmethod
    def _answer(call: ToolCall, run: Callable[[], dict[str, Any] | str | ToolOutput]) -> ToolResult:
        try:
            out = run()
        except CommandError as err:
            return ToolResult(call.id, call.name, f"{err.code}: {err.message}", is_error=True)
        except (TypeError, KeyError, ValueError, OverflowError) as err:
            return ToolResult(call.id, call.name, f"bad_argument: {err}", is_error=True)
        except OSError as err:  # the disk, not the helper's mistake: say so, keep going
            log.exception("a helper's tool %s failed", call.name)
            return ToolResult(
                call.id, call.name, f"internal_error: {type(err).__name__}", is_error=True
            )
        if isinstance(out, ToolOutput):
            return ToolResult(call.id, call.name, out.text, out.is_error, out.images)
        return ToolResult(call.id, call.name, out if isinstance(out, str) else compact_json(out))

    def _helper_tool(self, owner: str, call: ToolCall) -> dict[str, Any]:
        args = dict(call.arguments)
        if call.name == SPAWN:
            return self.spawn(owner, args)
        if call.name == FORK:
            return self.fork(owner, args)
        if call.name == MESSAGE:
            return self.message(owner, args)
        return self.listing(owner)

    def view(self) -> str:
        """The latest view the player has, as text: what `observe()` shows again. Takes no time
        and is not a decision."""
        text = render_text(self.ctx.session.observe())
        return text if len(text) <= MAX_VIEW_CHARS else text[: MAX_VIEW_CHARS - 40] + "\n... (cut)"

    # -- logs and totals ----------------------------------------------------------------------

    def _log_call(self, helper: Helper, fields: dict[str, Any]) -> None:
        if self.ctx.logs is not None:
            self.ctx.logs.call({"agent": helper.id, **fields})

    def _log_event(self, event: str, helper: Helper, text: str, **more: Any) -> None:
        if self.ctx.logs is not None:
            self.ctx.logs.transcript(
                "helper",
                event=event,
                agent=helper.id,
                parent=helper.parent,
                depth=helper.depth,
                text=text[:2_000],
                **more,
            )

    def summary(self) -> dict[str, Any]:
        """What the helpers used in all, for the run summary."""
        return {
            "helpers": len(self.helpers),
            "model_calls": self.total_calls,
            "usage": self.usage.as_dict(),
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 6),
            "by_helper": {
                h.id: {
                    "kind": h.kind,
                    "parent": h.parent,
                    "depth": h.depth,
                    "model": h.adapter.model,
                    "calls": h.calls,
                    "state": h.state,
                    "cost_usd": None if h.cost_usd is None else round(h.cost_usd, 6),
                }
                for h in self.helpers.values()
            },
        }


def _check_models(settings: SubAgentSettings, base: ModelAdapter | None) -> None:
    """The other models helpers may run on are of the player's provider: they share its client
    (its endpoint and its key)."""
    for name, sub in settings.models.items():
        if base is not None and sub.config.provider != base.provider:
            raise ConfigError(
                f"helper model `{name}` is a {sub.config.provider} model, but the player's is "
                f"{base.provider}: helpers use the player's provider"
            )


def _free_tool(toolbox: ToolBox, name: str) -> ToolDef | None:
    """The tool `name` of the player's toolbox if it is a plain free tool. A helper's call is run
    here, not through `toolbox.execute`: that would also hand the helper the notices meant for
    the player's turn. (`ToolBox` has no public lookup yet; `get` is used when it gets one.)"""
    get = getattr(toolbox, "get", None)
    tool = get(name) if callable(get) else toolbox._tools.get(name)
    ok = tool is not None and tool.kind == FREE and tool.handler is not None and not tool.acts
    return tool if ok else None


def _run_tool(tool: ToolDef, call: ToolCall) -> dict[str, Any] | str | ToolOutput:
    assert tool.handler is not None
    return tool.handler(dict(call.arguments))


_STOP_TEXT = {
    "steps": "it used the steps allowed for one message; send it another to go on",
    "calls": "it used all the steps it has",
    "total_calls": "the helpers' steps for this game are used up",
    "context": "its conversation is full",
    "refused": "the model declined",
    "budget_usd": "the allowance of money is used up",
    "budget_calls": "the allowance of model calls is used up",
}


# -- registration ---------------------------------------------------------------------------------


def register_l4(ctx: LayerContext, settings: SubAgentSettings | None = None) -> None:
    """Add the helper tools and the practice range to the player's toolbox.

    Reads `ctx.extras["parent_link"]` (a `ParentLink`) if the loop provides one; otherwise it
    follows `ctx.adapter` (see the module doc). The hub is left in `ctx.extras["subagent_hub"]`
    (its `summary()` is for the run summary)."""
    settings = settings or SubAgentSettings()
    link = ctx.extras.get("parent_link")
    if link is None:
        link = ParentLink()
        if ctx.adapter is not None:
            link.follow(ctx.adapter)
        ctx.extras["parent_link"] = link
    hub = SubAgentHub(ctx, settings, link)
    ctx.extras["subagent_hub"] = hub
    run_turn = ctx.toolbox.execute

    def execute(calls: Sequence[ToolCall]) -> Executed:
        hub.note_player_turn(calls)  # a fork answers every call of the turn that asked for it
        return run_turn(calls)

    ctx.toolbox.execute = execute  # type: ignore[method-assign]
    if "wand_range" not in ctx.toolbox.names():
        register_wand_range(ctx)
    handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        SPAWN: lambda args: hub.spawn(MAIN, args),
        FORK: lambda args: hub.fork(MAIN, args),
        MESSAGE: lambda args: hub.message(MAIN, args),
        LIST: lambda _args: hub.listing(MAIN),
    }
    for spec in helper_specs(settings):
        ctx.toolbox.register(ToolDef(spec, FREE, handlers[spec.name]))
