"""The scoring rules of the encounters: one function per encounter id.

A rule reads a `Ctx` (one visit) and returns an `Outcome`: a 0 to 1 score (or None if the visit
cannot be scored), the reasons, and `facts` other rules may use. `late_rule`s also get the
outcomes of all the other visits (E04 is judged on what the run did with lava afterwards).

Encounters 'implemented' in the game are the ones with a rule here (`content/encounters/`);
placeholders in a world file are never visited, never scored.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..context import Ctx, Visit, find_visits
from ..recording import RunData
from ..rubric import Outcome
from ..worldinfo import MissingRegion

Rule = Callable[[Ctx], Outcome]
LateRule = Callable[[Ctx, list["Result"]], Outcome]

RULES: dict[str, Rule] = {}
LATE_RULES: dict[str, LateRule] = {}


@dataclass(frozen=True)
class Result:
    """One scored visit."""

    visit: Visit
    outcome: Outcome


def rule(eid: str) -> Callable[[Rule], Rule]:
    def register(fn: Rule) -> Rule:
        RULES[eid] = fn
        return fn

    return register


def late_rule(eid: str) -> Callable[[LateRule], LateRule]:
    def register(fn: LateRule) -> LateRule:
        LATE_RULES[eid] = fn
        return fn

    return register


def implemented() -> list[str]:
    return sorted(set(RULES) | set(LATE_RULES))


def _run_rule(fn, run: RunData, visit: Visit, *others) -> Outcome:
    """Run one rule; a scene that lacks a region the rule needs, or a recording row that lacks a
    field the rule reads, is reported in the visit's reasons and not scored."""
    try:
        return fn(Ctx(run, visit), *others)
    except MissingRegion as err:
        return Outcome.unscored(f"not scored: {err}")
    except (KeyError, TypeError, ValueError, IndexError) as err:
        return Outcome.unscored(f"not scored: damaged recording data ({type(err).__name__}: {err})")


def evaluate_visits(run: RunData) -> list[Result]:
    """Score every visit of an implemented encounter, in order of first entry."""
    visits = [v for v in find_visits(run) if v.scene.eid in RULES or v.scene.eid in LATE_RULES]
    results: list[Result] = []
    late: list[Visit] = []
    for visit in visits:
        if visit.scene.eid in RULES:
            results.append(Result(visit, _run_rule(RULES[visit.scene.eid], run, visit)))
        else:
            late.append(visit)
    for visit in late:
        outcome = _run_rule(LATE_RULES[visit.scene.eid], run, visit, list(results))
        results.append(Result(visit, outcome))
    return sorted(results, key=lambda r: (r.visit.enter, r.visit.scene.key))


# the modules register their rules on import
from . import hazards, lava, physics, routes, seal, unknowns  # noqa: F401
