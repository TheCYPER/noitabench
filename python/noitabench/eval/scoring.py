"""Capability scores, the depth score and the composite (capability graph section 5).

Per capability (0 to 100): the weighted mean of its parts, where a part is a scored encounter
visit (weight 1 for the encounter's main node, 0.5 for its second node; E06 also feeds C3 and
E07 C1 with weight 1, being the combined scenes) or a measured global metric (weight 1).

Opportunities `n`: one per scored visit plus the number of trials each metric was computed from.
A capability with fewer than `MIN_OPPORTUNITIES` is `covered: false` (reported as such).
C is the mean of the combined capabilities C1 to C4 that have a score.

Discount (user decision 2026-10-28): a capability counts `score x n / (n + 2)`, so one that was
met once counts a third, one met five times five sevenths, and one never met (no score) counts 0.
Leaving the thinly covered ones out and re-weighting the rest, the earlier rule, paid a run for
meeting little: a bot cut at frame 800 scored above the same bot cut at frame 2400.

Ability = the mean of the discounted scores of all 11 capabilities (N1 to N10 and C).
Composite = 0.8 x ability + 0.2 x the depth score.

Depth score = how far down the player got, from the start (0) to the floor of the sealed room
(100), by the lowest point its hit box reached. Below the top of the seal plug only the samples in
which the hit box is inside the sealed room count: a tunnel dug past the vault to the bottom of
the world does not open the seal and is not depth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .encounters import Result
from .metrics import Metric
from .recording import RunData
from .rubric import clamp01
from .worldinfo import encounter_nodes

NODES = tuple(f"N{i}" for i in range(1, 11))
COMBINED = ("C1", "C2", "C3", "C4")
MIN_OPPORTUNITIES = 2
SECONDARY_WEIGHT = 0.5
OPPORTUNITY_OFFSET = 2  # discount of a capability = n / (n + OPPORTUNITY_OFFSET)
ABILITY_SHARE, DEPTH_SHARE = 0.8, 0.2
THIN_COMPOSITE = 5  # fewer covered capabilities than this: the composite is flagged as thin
SCENE_FEEDS = {"E06": "C3", "E07": "C1"}  # combined scenes: they also score a combined capability


def discount(opportunities: int) -> float:
    """What a capability met `opportunities` times counts for: n / (n + 2); 0 when never met."""
    n = max(0, opportunities)
    return n / (n + OPPORTUNITY_OFFSET)


@dataclass
class Capability:
    name: str
    score: float | None
    opportunities: int
    covered: bool
    encounters: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    parts: dict[str, Capability] = field(default_factory=dict)
    note: str = ""

    @property
    def discount(self) -> float:
        return discount(self.opportunities)

    @property
    def discounted(self) -> float:
        """The score times the discount; a capability without a score counts 0."""
        return 0.0 if self.score is None else self.score * self.discount

    def as_dict(self, *, with_discount: bool = True) -> dict[str, Any]:
        """The profile entry. The parts C1 to C4 of C are not in the mean: no discount for them."""
        out: dict[str, Any] = {
            "score": None if self.score is None else round(self.score, 2),
            "opportunities": self.opportunities,
            "covered": self.covered,
        }
        if with_discount:
            out["discount"] = round(self.discount, 4)
            out["discounted_score"] = round(self.discounted, 2)
        if self.parts:
            out["parts"] = {k: v.as_dict(with_discount=False) for k, v in self.parts.items()}
        else:
            out["encounters"] = self.encounters
            out["metrics"] = self.metrics
        if self.note:
            out["note"] = self.note
        return out


def _node_capability(
    name: str, results: list[Result], metrics: list[Metric], *, minimum: int
) -> Capability:
    weighted, total = 0.0, 0.0
    encounters: list[dict[str, Any]] = []
    for r in results:
        if r.outcome.score is None:
            continue
        eid = r.visit.scene.eid
        nodes = encounter_nodes(eid)
        if name in nodes:
            role = "main" if nodes.index(name) == 0 else "secondary"
            weight = 1.0 if role == "main" else SECONDARY_WEIGHT
        elif SCENE_FEEDS.get(eid) == name:
            role, weight = "scene", 1.0
        else:
            continue
        weighted += weight * r.outcome.score
        total += weight
        encounters.append(
            {
                "id": eid,
                "instance": r.visit.scene.key,
                "role": role,
                "weight": weight,
                "score": round(r.outcome.score, 3),
            }
        )
    used: list[dict[str, Any]] = []
    trials = 0
    for m in metrics:
        if m.value is None or name not in m.capabilities:
            continue
        weighted += m.value
        total += 1.0
        trials += m.opportunities
        used.append(
            {"name": m.name, "weight": 1.0, "value": round(m.value, 3), "n": m.opportunities}
        )
    opportunities = len(encounters) + trials
    if total == 0:
        return Capability(name, None, 0, False, note="no encounter met and no metric measured")
    covered = opportunities >= minimum
    note = "" if covered else f"coverage too low ({opportunities} opportunities, need {minimum})"
    return Capability(
        name, 100.0 * weighted / total, opportunities, covered, encounters, used, note=note
    )


def capability_scores(results: list[Result], metrics: list[Metric]) -> dict[str, Capability]:
    out = {n: _node_capability(n, results, metrics, minimum=MIN_OPPORTUNITIES) for n in NODES}
    parts = {c: _node_capability(c, results, metrics, minimum=1) for c in COMBINED}
    scored = [p for p in parts.values() if p.score is not None]
    opportunities = sum(p.opportunities for p in parts.values())
    c_score = sum(p.score for p in scored) / len(scored) if scored else None  # type: ignore[misc]
    covered = bool(scored) and opportunities >= MIN_OPPORTUNITIES
    note = ""
    if not scored:
        note = "no combined scene met and no metric measured"
    elif not covered:
        note = f"coverage too low ({opportunities} opportunities, need {MIN_OPPORTUNITIES})"
    out["C"] = Capability("C", c_score, opportunities, covered, parts=parts, note=note)
    return out


def depth_score(run: RunData) -> dict[str, Any]:
    """How far down the player got, 0 (the start) to 100 (the floor of the sealed room).

    Samples below the top of the seal plug count only while the hit box is inside the sealed
    room; any other sample counts at most the plug's top edge. Without a seal and room in the
    world file nothing is capped."""
    samples = run.track.samples
    start = samples[0].feet
    raw_deepest = run.track.deepest_feet()
    bottom = run.world.bottom
    room = run.world.seal_room
    plug = run.world.seal_plug
    deepest = raw_deepest
    if room is not None and plug is not None:
        deepest = max(
            (a.feet if a.feet <= plug.y or a.box().overlaps(room) else float(plug.y))
            for a in samples
        )
    span = max(1.0, bottom - start)
    fraction = clamp01((deepest - start) / span)
    reached = bool(room and run.track.touched(room, 0, run.last_frame))
    return {
        "score": round(100.0 * fraction, 2),
        "fraction": round(fraction, 4),
        "start_y": round(start, 1),
        "deepest_y": round(deepest, 1),
        "deepest_raw_y": round(raw_deepest, 1),
        "capped_at_seal": deepest < raw_deepest,
        "bottom_y": round(bottom, 1),
        "reached_sealed_room": reached,
    }


def composite(capabilities: dict[str, Capability], depth: dict[str, Any]) -> dict[str, Any]:
    """Composite = 0.8 x ability + 0.2 x depth; ability = the mean of the discounted scores of
    all the capabilities (a capability without a score counts 0)."""
    covered = {k: c for k, c in capabilities.items() if c.covered and c.score is not None}
    left_out = sorted(k for k in capabilities if k not in covered)
    count = max(1, len(capabilities))
    ability = sum(c.discounted for c in capabilities.values()) / count
    scored = [c.score for c in capabilities.values() if c.score is not None]
    raw_mean = sum(scored) / len(scored) if scored else None
    note: str | None = None
    if not scored:
        note = "no capability was scored: the ability share counts as 0"
    elif len(covered) < THIN_COMPOSITE:
        note = (
            f"thin: only {len(covered)} of {len(capabilities)} capabilities were covered "
            f"({MIN_OPPORTUNITIES} or more opportunities); the others count at a discount, "
            "so this composite is not comparable with a fuller run"
        )
    return {
        "composite": round(ABILITY_SHARE * ability + DEPTH_SHARE * depth["score"], 2),
        "ability_mean": round(ability, 2),
        "ability_raw_mean": None if raw_mean is None else round(raw_mean, 2),
        "covered": sorted(covered),
        "left_out": left_out,
        "note": note,
    }
