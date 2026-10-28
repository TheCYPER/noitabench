"""The budget of a run: dollars, model calls and decisions, all model calls counted.

One `Budget` is shared by everything that calls a model in a run (the main agent now, sub-agents
later), so the cap holds for the whole. A call is allowed while what is left covers the dearest
of the last few calls; the run therefore stops before the cap and not after it.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field

RECENT_CALLS = 5
TOLERANCE_USD = 1e-9  # float sums of many small costs must not decide a call by a hair


@dataclass
class Budget:
    max_usd: float | None = None
    max_model_calls: int | None = None
    spent_usd: float = 0.0
    model_calls: int = 0
    unpriced_calls: int = 0
    _recent: deque[float] = field(default_factory=lambda: deque(maxlen=RECENT_CALLS), repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def charge(self, cost_usd: float | None) -> None:
        """Count one finished model call; `cost_usd` is None when the model has no price."""
        with self._lock:
            self.model_calls += 1
            if cost_usd is None:
                self.unpriced_calls += 1
                return
            self.spent_usd += cost_usd
            self._recent.append(cost_usd)

    def remaining_usd(self) -> float | None:
        if self.max_usd is None:
            return None
        return max(self.max_usd - self.spent_usd, 0.0)

    def next_call_estimate(self) -> float:
        with self._lock:
            return max(self._recent, default=0.0)

    def exhausted(self) -> str | None:
        """`budget_usd` or `budget_calls` when the next call must not be made, else None."""
        with self._lock:
            if self.max_model_calls is not None and self.model_calls >= self.max_model_calls:
                return "budget_calls"
            if self.max_usd is not None:
                estimate = max(self._recent, default=0.0)
                if self.spent_usd + estimate > self.max_usd + TOLERANCE_USD or self.max_usd <= 0:
                    return "budget_usd"
        return None

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "max_usd": self.max_usd,
            "spent_usd": round(self.spent_usd, 6),
            "model_calls": self.model_calls,
            "max_model_calls": self.max_model_calls,
            "unpriced_calls": self.unpriced_calls,
        }
