"""What a run is going to cost, worked out before it starts (no model call).

The estimate replays the loop's own economics: a conversation whose prompt grows with every
step, read from the cache after it has been written once, until it is compacted at
`context_limit` and starts again from the system prompt and tools (which stay cached). The
inputs are measured where they can be (the system prompt, the tool schemas, one real
observation) and assumed where they cannot (output tokens per call, calls per step).

Three figures come out: `typical`, `low` and `high` (the output and the number of calls per step
vary), plus `without_cache` for the case where the provider does not cache at all.
"""

from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .budget import Budget
from .layers import MINIMAL_LAYERS, build_toolbox
from .prices import ModelPrice, default_context_limit
from .prompt import SUMMARY_INTRO, SUMMARY_REQUEST, system_prompt
from .usage import Usage
from .workspace import Workspace

CHARS_PER_TOKEN = 3.0  # careful: the newer tokenizers count ~30% more tokens for the same text
DEFAULT_OBSERVATION_CHARS = 3_200  # a real observation of the default view, measured
DEFAULT_OUTPUT_TOKENS = 600  # per call, thinking included
DEFAULT_CALLS_PER_DECISION = 1.15  # notebook and budget calls add to the one call per step
RESULT_OVERHEAD_TOKENS = 60  # tool_result wrappers and the like, per call
SUMMARY_TOKENS = 700


def tokens_of(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


@dataclass(frozen=True)
class Inputs:
    system_tokens: int
    tools_tokens: int
    observation_tokens: int
    output_tokens: int = DEFAULT_OUTPUT_TOKENS
    calls_per_decision: float = DEFAULT_CALLS_PER_DECISION


@dataclass(frozen=True)
class Estimate:
    calls: int
    summaries: int
    usage: Usage
    cost_usd: float
    low_usd: float
    high_usd: float
    without_cache_usd: float
    peak_prompt_tokens: int
    decisions: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "decisions": self.decisions,
            "model_calls": self.calls,
            "summaries": self.summaries,
            "usage": self.usage.as_dict(),
            "peak_prompt_tokens": self.peak_prompt_tokens,
            "typical_usd": round(self.cost_usd, 4),
            "low_usd": round(self.low_usd, 4),
            "high_usd": round(self.high_usd, 4),
            "without_cache_usd": round(self.without_cache_usd, 4),
            "per_decision_usd": round(self.cost_usd / max(self.decisions, 1), 6),
        }


def measure_inputs(
    *,
    mode: str = "tools",
    layers: tuple[str, ...] = MINIMAL_LAYERS,
    observation_chars: int = DEFAULT_OBSERVATION_CHARS,
    output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    calls_per_decision: float = DEFAULT_CALLS_PER_DECISION,
) -> Inputs:
    """The inputs of the estimate, measured from the real system prompt and tool schemas."""
    system = system_prompt(mode=mode, notes_kept=True, layers=layers)
    tools_chars = 0
    if mode == "tools":
        with tempfile.TemporaryDirectory() as tmp:
            # the specs do not need a game; only running a tool does
            box = build_toolbox(
                None,  # type: ignore[arg-type]
                Workspace(Path(tmp)),
                Budget(),
                layers=layers,
                decisions_cap=1,
            )
            tools_chars = sum(
                len(s.name) + len(s.description) + len(json.dumps(s.schema)) for s in box.specs()
            )
    return Inputs(
        system_tokens=tokens_of(len(system)),
        tools_tokens=tokens_of(tools_chars),
        observation_tokens=tokens_of(observation_chars),
        output_tokens=output_tokens,
        calls_per_decision=calls_per_decision,
    )


def _simulate(
    price: ModelPrice, inputs: Inputs, decisions: int, limit: int
) -> tuple[int, int, Usage, float, int]:
    base = inputs.system_tokens + inputs.tools_tokens
    calls_total = max(math.ceil(decisions * inputs.calls_per_decision), 1)
    step_tokens = inputs.observation_tokens + RESULT_OVERHEAD_TOKENS
    usage = Usage()
    dollars = 0.0
    summaries = peak = 0
    context = 0  # prompt tokens already in the conversation (cached after the first call)
    pending = inputs.observation_tokens  # tokens the next call adds (the opening view)
    warm = False  # the system prompt and tools are in the cache
    fresh = True  # the conversation has made no call yet
    for _ in range(calls_total):
        if fresh:
            read = base if warm else 0
            write = pending + (0 if warm else base)
            context = base
            fresh = False
        else:
            read, write = context, pending
        call = Usage(
            cache_read_tokens=read, cache_write_tokens=write, output_tokens=inputs.output_tokens
        )
        usage += call
        dollars += price.cost(call)
        warm = True
        context += pending + inputs.output_tokens
        peak = max(peak, call.prompt_tokens)
        pending = step_tokens
        if context >= limit:  # write the briefing, start again
            note = Usage(
                cache_read_tokens=context,
                cache_write_tokens=pending + tokens_of(len(SUMMARY_REQUEST)),
                output_tokens=SUMMARY_TOKENS,
            )
            usage += note
            dollars += price.cost(note)
            summaries += 1
            fresh = True
            pending = SUMMARY_TOKENS + tokens_of(len(SUMMARY_INTRO)) + inputs.observation_tokens
    return calls_total, summaries, usage, dollars, peak


def estimate_run(
    price: ModelPrice,
    inputs: Inputs,
    *,
    decisions: int,
    context_limit: int | None = None,
) -> Estimate:
    limit = context_limit or default_context_limit(price)
    calls, summaries, usage, typical, peak = _simulate(price, inputs, decisions, limit)
    lean = Inputs(
        inputs.system_tokens,
        inputs.tools_tokens,
        inputs.observation_tokens,
        max(inputs.output_tokens // 2, 1),
        inputs.calls_per_decision,
    )
    heavy = Inputs(
        inputs.system_tokens,
        inputs.tools_tokens,
        inputs.observation_tokens,
        inputs.output_tokens * 2,
        inputs.calls_per_decision * 1.5,
    )
    low = _simulate(price, lean, decisions, limit)[3]
    high = _simulate(price, heavy, decisions, limit)[3]
    plain = ModelPrice(price.tiers, cache_read_factor=1.0, cache_write_factor=1.0)
    uncached = _simulate(plain, inputs, decisions, limit)[3]
    return Estimate(calls, summaries, usage, typical, low, high, uncached, peak, decisions)
