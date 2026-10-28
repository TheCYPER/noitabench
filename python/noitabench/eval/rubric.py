"""A score built from weighted parts, with a reason for every part.

Every encounter rule and every global metric states its parts the same way:

    rubric = Rubric()
    rubric.add("crossed", 0.3, 1.0 if crossed else 0.0, "reached the far ledge")
    rubric.add("no_waste", 0.2, None, "needs decisions.jsonl")      # None: not measurable here

A part whose value is `None` is left out and the weights of the others are scaled up, so a run
without `decisions.jsonl` (the scripted bot) is judged on what its recording can show.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def linear(value: float, good: float, bad: float) -> float:
    """1.0 at `good`, 0.0 at `bad`, straight in between (either order of the two)."""
    if good == bad:
        return 1.0 if value == good else 0.0
    return clamp01((value - bad) / (good - bad))


@dataclass(frozen=True)
class Part:
    name: str
    weight: float
    value: float | None
    why: str


@dataclass
class Rubric:
    parts: list[Part] = field(default_factory=list)

    def add(self, name: str, weight: float, value: float | bool | None, why: str = "") -> None:
        if isinstance(value, bool):
            value = 1.0 if value else 0.0
        self.parts.append(Part(name, weight, None if value is None else clamp01(value), why))

    def score(self) -> float | None:
        """The weighted mean of the parts that could be measured; None if none could."""
        measured = [p for p in self.parts if p.value is not None]
        total = sum(p.weight for p in measured)
        if total <= 0:
            return None
        return sum(p.weight * (p.value or 0.0) for p in measured) / total

    def reasons(self) -> list[str]:
        total = sum(p.weight for p in self.parts if p.value is not None) or 1.0
        out = []
        for p in self.parts:
            if p.value is None:
                out.append(f"{p.name}: not measured ({p.why})")
            else:
                share = p.weight / total
                out.append(f"{p.name}: {p.value * share:+.2f} of {share:.2f} ({p.why})")
        return out


@dataclass
class Outcome:
    """What an encounter rule says about one visit."""

    score: float | None
    reasons: list[str]
    facts: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def of(rubric: Rubric, **facts: Any) -> Outcome:
        return Outcome(rubric.score(), rubric.reasons(), dict(facts))

    @staticmethod
    def unscored(reason: str, **facts: Any) -> Outcome:
        return Outcome(None, [reason], dict(facts))
