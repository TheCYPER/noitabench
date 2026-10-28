"""The agent loop: a model plays one game through an `AgentSession`.

    opening view -> model turn -> tool calls (or text commands) -> results -> model turn -> ...

until the game ends (death, step limit) or the harness stops it (money, model calls, a failing
model, a refusal, a model that never acts). Every model call is counted against the one `Budget`.

Long games do not fit in one conversation without cost: when the prompt of the latest call reaches
`context_limit` tokens the loop asks the model for a briefing in the same conversation (the prefix
is cached, so it is cheap), starts a **new** conversation and opens it with the briefing and the
current view. Nothing earlier is edited or replayed, so nothing breaks the signed thinking blocks
or the prompt cache of the system prompt and tools, which the new conversation shares.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from noitabench.agent import AgentSession, render_text
from noitabench.agent.protocol import with_text

from .budget import Budget
from .errors import ModelError, StopRun
from .logs import RunLogs
from .model import (
    MAX_TOKENS,
    REFUSAL,
    Conversation,
    Item,
    ModelAdapter,
    ModelTurn,
    ToolCall,
    ToolSpec,
    UserText,
)
from .prices import ModelPrice
from .prompt import (
    NUDGE_CUT_OFF,
    NUDGE_NO_COMMAND,
    NUDGE_NO_TOOL,
    SUMMARY_FALLBACK,
    SUMMARY_INTRO,
    SUMMARY_REQUEST,
    opening_message,
)
from .textmode import extract_decision, is_budget_request
from .toolbox import ToolBox, screenshot_of
from .usage import Usage
from .workspace import Workspace

log = logging.getLogger(__name__)

TOOLS, TEXT = "tools", "text"
SUMMARY, SERVER, NONE = "summary", "server", "none"
MAX_SUMMARY_CHARS = 8_000
MIN_PLAYS_BETWEEN_BRIEFINGS = 3  # a limit below the size of the prompt prefix cannot loop on it
MAX_TRANSCRIPT_THINKING = 20_000


@dataclass(frozen=True)
class LoopConfig:
    mode: str = TOOLS  # tools or text
    context: str = SUMMARY  # summary (the loop's own), server (Anthropic compaction) or none
    context_limit: int = 100_000  # prompt tokens at which a briefing is written
    max_stalls: int = 3  # turns in a row without a usable command
    max_refusal_retries: int = 1
    call_retries: int = 2  # more tries after a retryable error (the SDK has retried already)
    backoff_s: float = 2.0
    progress_every: int = 25  # model calls between progress lines in the diagnostic log

    def __post_init__(self) -> None:
        if self.mode not in (TOOLS, TEXT):
            raise ValueError(f"mode must be {TOOLS} or {TEXT}")
        if self.context not in (SUMMARY, SERVER, NONE):
            raise ValueError(f"context must be {SUMMARY}, {SERVER} or {NONE}")


@dataclass
class LoopResult:
    over: str  # dead, decision_limit, budget_usd, budget_calls, model_error, refusal, stalled
    detail: str = ""
    decisions: int = 0
    frames: int = 0
    model_calls: int = 0
    summaries: int = 0
    stalls: int = 0
    usage: Usage = field(default_factory=Usage)
    cost_usd: float | None = 0.0  # None when the model has no price
    wall_seconds: float = 0.0
    models_seen: list[str] = field(default_factory=list)  # the model ids the answers named

    def as_dict(self) -> dict[str, Any]:
        return {
            "over": self.over,
            "detail": self.detail,
            "decisions": self.decisions,
            "frames": self.frames,
            "model_calls": self.model_calls,
            "summaries": self.summaries,
            "stalls": self.stalls,
            "usage": self.usage.as_dict(),
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 6),
            "wall_seconds": round(self.wall_seconds, 2),
            "models_seen": list(self.models_seen),
        }


class AgentLoop:
    def __init__(
        self,
        *,
        session: AgentSession,
        adapter: ModelAdapter,
        toolbox: ToolBox,
        workspace: Workspace,
        budget: Budget,
        price: ModelPrice | None,
        logs: RunLogs,
        system: str,
        config: LoopConfig | None = None,
        sleep: Callable[[float], None] = time.sleep,
        system_suffix: Callable[[], str] | None = None,
    ) -> None:
        self.session = session
        self.adapter = adapter
        self.toolbox = toolbox
        self.workspace = workspace
        self.budget = budget
        self.price = price
        self.logs = logs
        self.system = system
        self._system_suffix = system_suffix
        self.cfg = config or LoopConfig()
        self._sleep = sleep
        self.usage = Usage()
        self.cost_usd: float | None = 0.0 if price is not None else None
        self.summaries = 0
        self.models_seen: list[str] = []  # a floating alias (`deepseek-flash`) can change under us
        self.stalls_total = 0
        self._stalls = 0
        self._refusals = 0
        self._call_no = 0
        self._plays_since_briefing = MIN_PLAYS_BETWEEN_BRIEFINGS
        self._tools: list[ToolSpec] = []

    # -- the run ----------------------------------------------------------------------------------

    def run(self) -> LoopResult:
        started = time.monotonic()
        try:
            over, detail = self._play()
        except StopRun as stop:
            over, detail = stop.reason, stop.detail
        self.logs.transcript("end", over=over, detail=detail)
        return LoopResult(
            over=over,
            detail=detail,
            decisions=self.session.decisions,
            frames=self.session.frame,
            model_calls=self.budget.model_calls,
            summaries=self.summaries,
            stalls=self.stalls_total,
            usage=self.usage,
            cost_usd=self.cost_usd,
            wall_seconds=time.monotonic() - started,
            models_seen=list(self.models_seen),
        )

    def _play(self) -> tuple[str, str]:
        self._tools = [] if self.cfg.mode == TEXT else self.toolbox.specs()
        conversation = self.adapter.new_conversation(self._system(), self._tools)
        items: list[Item] = [self._opening()]
        while True:
            self._check_limits()
            conversation, items = self._maybe_compact(conversation, items)
            self._check_limits()  # the briefing was a model call too
            turn = self._call(conversation, items, "play")
            items = self._react(turn, items)
            if self.session.over:
                return self.session.over_reason or "over", ""

    def _check_limits(self) -> None:
        why = self.budget.exhausted()
        if why:
            raise StopRun(why, f"spent ${self.budget.spent_usd:.4f}")

    # -- one model call ---------------------------------------------------------------------------

    def _call(self, conversation: Conversation, items: list[Item], purpose: str) -> ModelTurn:
        attempt = 0
        self._call_no += 1
        while True:
            try:
                turn = conversation.send(items)
                break
            except ModelError as err:
                self.logs.call(
                    {
                        "call": self._call_no,
                        "attempt": attempt,
                        "purpose": purpose,
                        "provider": self.adapter.provider,
                        "model": self.adapter.model,
                        "error": err.as_dict(),
                    }
                )
                if not err.retryable or attempt >= self.cfg.call_retries:
                    raise StopRun("model_error", f"{err.kind}: {err}") from err
                attempt += 1
                log.warning("model call failed (%s), retry %d", err.kind, attempt)
                self._sleep(self.cfg.backoff_s * 2 ** (attempt - 1))
        if purpose == "play":
            self._plays_since_briefing += 1
        served = turn.model or self.adapter.model
        if served not in self.models_seen:
            self.models_seen.append(served)
        cost = self.price.cost(turn.usage) if self.price is not None else None
        self.budget.charge(cost)
        self.usage += turn.usage
        if cost is not None and self.cost_usd is not None:
            self.cost_usd += cost
        self.logs.call(
            {
                "call": self._call_no,
                "purpose": purpose,
                "provider": self.adapter.provider,
                "model": served,
                "decision": self.session.decisions,
                **turn.usage.as_dict(),
                "prompt_tokens": turn.usage.prompt_tokens,
                "cost_usd": None if cost is None else round(cost, 6),
                "cumulative_usd": round(self.budget.spent_usd, 6),
                "latency_s": round(turn.latency_s, 3),
                "stop_reason": turn.raw_stop or turn.stop,
                "request_id": turn.request_id,
            }
        )
        self.logs.transcript(
            "assistant",
            call=self._call_no,
            purpose=purpose,
            decision=self.session.decisions,
            text=turn.text,
            thinking=turn.thinking[:MAX_TRANSCRIPT_THINKING],
            tool_calls=[
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in turn.tool_calls
            ],
            stop=turn.stop,
        )
        if self.cfg.progress_every and self._call_no % self.cfg.progress_every == 0:
            log.info(
                "call %d | decision %d/%d | $%.4f | prompt %d tokens",
                self._call_no,
                self.session.decisions,
                self.session.config.max_decisions,
                self.budget.spent_usd,
                turn.usage.prompt_tokens,
            )
        return turn

    # -- what the model did -----------------------------------------------------------------------

    def _react(self, turn: ModelTurn, sent: list[Item]) -> list[Item]:
        """The items for the next call, after executing `turn`."""
        if turn.stop == REFUSAL:
            self._refusals += 1
            if self._refusals > self.cfg.max_refusal_retries:
                raise StopRun("refusal", turn.raw_stop or "")
            self.logs.transcript("note", text="refused; the same step is sent again")
            return sent  # nothing was appended to the conversation: send the same items again
        self._refusals = 0
        if turn.stop == MAX_TOKENS:
            return self._stall([UserText(NUDGE_CUT_OFF)])
        if self.cfg.mode == TEXT:
            return self._react_text(turn)
        if not turn.tool_calls:
            return self._stall([UserText(NUDGE_NO_TOOL)])
        executed = self.toolbox.execute(turn.tool_calls)
        self._stalls = 0
        self.logs.transcript(
            "results",
            call=self._call_no,
            decision=self.session.decisions,
            results=[
                {"id": r.call_id, "name": r.name, "is_error": r.is_error, "content": r.content}
                for r in executed.results
            ],
        )
        return list(executed.results)

    def _react_text(self, turn: ModelTurn) -> list[Item]:
        decision = extract_decision(turn.text)
        if decision is None:
            return self._stall([UserText(NUDGE_NO_COMMAND)])
        self._stalls = 0
        if is_budget_request(decision):
            result = self.toolbox.execute([ToolCall("text-budget", "budget", {})]).results[0]
            reply = UserText(result.content)
        else:
            answer = self.session.decide(decision)
            reply = UserText(self.toolbox.clean(with_text(answer)["text"]), screenshot_of(answer))
        self.logs.transcript(
            "results", call=self._call_no, decision=self.session.decisions, text=reply.text
        )
        return [reply]

    def _stall(self, items: list[Item]) -> list[Item]:
        self._stalls += 1
        self.stalls_total += 1
        if self._stalls >= self.cfg.max_stalls:
            raise StopRun("stalled", f"{self._stalls} turns in a row without a command")
        self.logs.transcript("note", text="no usable command", nudge=items[0].text)
        return items

    # -- long games -------------------------------------------------------------------------------

    def _maybe_compact(
        self, conversation: Conversation, items: list[Item]
    ) -> tuple[Conversation, list[Item]]:
        if self.cfg.context != SUMMARY or conversation.last_prompt_tokens < self.cfg.context_limit:
            return conversation, items
        if self._plays_since_briefing < MIN_PLAYS_BETWEEN_BRIEFINGS:
            return conversation, items
        self._plays_since_briefing = 0
        self._check_limits()
        turn = self._call(conversation, [*items, UserText(SUMMARY_REQUEST)], "summary")
        summary = turn.text.strip() if turn.stop not in (REFUSAL, MAX_TOKENS) else ""
        summary = summary[:MAX_SUMMARY_CHARS] or SUMMARY_FALLBACK
        self.summaries += 1
        self.logs.transcript("summary", call=self._call_no, text=summary)
        now = self.session.observe()
        opening = self.toolbox.clean(
            SUMMARY_INTRO.format(summary=summary, observation=render_text(now))
        )
        fresh = self.adapter.new_conversation(self._system(), self._tools)
        return fresh, [UserText(opening, screenshot_of(now))]

    def _system(self) -> str:
        """The system prompt for a conversation that is being started: the fixed text, and what
        layers add to it (the prompt fragments of plugins, which may have changed)."""
        extra = self._system_suffix() if self._system_suffix is not None else ""
        return self.system + extra

    def _opening(self) -> UserText:
        first = self.session.observe()
        files = [(f["path"], f["chars"]) for f in self.workspace.list()["files"]]
        text = self.toolbox.clean(
            opening_message(render_text(first), files, self.workspace.quota("notes").left)
        )
        self.logs.transcript("opening", text=text)
        return UserText(text, screenshot_of(first))
