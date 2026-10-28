"""Global metrics: what the whole run shows, whether or not an encounter was met.

Capability graph section 4 lists a global indicator for every capability. Each metric here is
computed from the recording files alone and returns a `Metric`: a value from 0 to 1 and the
number of opportunities it was computed from, or `value=None` with the reason it could not be
measured. A metric with `value=None` never enters a capability score (no signal is invented).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..encounters import Result
from ..recording import RunData


@dataclass
class Metric:
    name: str
    capabilities: tuple[str, ...]
    value: float | None
    opportunities: int = 0
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capabilities": list(self.capabilities),
            "value": None if self.value is None else round(self.value, 4),
            "opportunities": self.opportunities,
            "status": "measured" if self.value is not None else "not_measured",
            "reason": self.reason,
            "detail": self.detail,
        }


MetricFn = Callable[[RunData, list[Result]], list[Metric]]
METRICS: list[MetricFn] = []


def metric_group(fn: MetricFn) -> MetricFn:
    METRICS.append(fn)
    return fn


def compute_metrics(run: RunData, results: list[Result]) -> list[Metric]:
    """Every metric group; a group that meets a recording row it cannot read reports itself as
    not measured, with the error, instead of stopping the evaluation."""
    out: list[Metric] = []
    for fn in METRICS:
        try:
            out.extend(fn(run, results))
        except (KeyError, TypeError, ValueError, IndexError) as err:
            reason = f"not measured: damaged recording data ({type(err).__name__}: {err})"
            out.append(Metric(fn.__name__, (), None, 0, reason))
    return out


from . import harm, knowledge, notes, notes_use, physics, route, senses, unmeasured  # noqa: F401
