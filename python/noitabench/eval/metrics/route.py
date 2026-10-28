"""Route metrics: N3 backtracking and decisions per layer, N5 route and hit rate, C1/C2 layers.

N3 backtracking ("回头路长度"): each climb back from the deepest point reached so far, once it
    is at least `RETURN_ABOVE` cells above it, counts by how far above it gets; a new deepest
    point starts afresh. value = 1 - retreat / descent (0 when the retreats add up to the whole
    descent). Needs a descent of `MIN_DESCENT` cells.
N3 decisions_per_layer ("每层用的决策数"): for each layer the player went through (from first
    reaching it to first reaching the band below), the decisions spent (the `cost` of
    decisions.jsonl): `DECISIONS_GOOD` or fewer is 1.0, `DECISIONS_BAD` or more is 0; the mean
    over the finished layers. Needs decisions.jsonl.
N5 route_efficiency ("实际路线长度和最短可行路线的比"): the generator's main path from the start to
    the point nearest to the deepest depth reached, divided by the length the player actually
    walked, at most 1 (digging a shortcut cannot score above 1).
N5 hit_rate ("射击命中率"): of the projectiles of the player's direct-fire spells cast with a
    living creature within `ENGAGE` cells and a clear line to it (checked on the recorded grid),
    the share that hit a creature (`hit` events). The aim is not recorded per cast, so a shot
    at a wall with a creature in sight counts as a miss. Needs `MIN_SHOTS` such casts.
C2 layer_completion ("在陌生群系里活下来并找到出口"): per layer entered, 1.0 if the player reached
    the band below, else its progress through the layer (halved if it died there).
C1 layer_end_hp ("瓶子、法力、血量在一整层里的分配"): per finished layer, the player's health on
    reaching the band below: 50 % of the maximum or more is 1.0, linear below.
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from ..encounters import Result
from ..recording import RunData, is_creature
from ..rubric import clamp01, linear
from ..worldinfo import CONTENT, Span, blocking_indices
from . import Metric, metric_group

RETURN_ABOVE = 40  # cells above the deepest point: going up from there is a retreat
MIN_DESCENT = 150  # cells of descent below which a retreat ratio means nothing
DECISIONS_GOOD, DECISIONS_BAD = 80, 300  # decisions to get through one layer
ENGAGE = 220  # cells: a creature this close makes a cast an attack
MIN_SHOTS = 3


def _entered(run: RunData, span: Span) -> int | None:
    for s in run.track.samples:
        if s.feet >= span.y0:
            return s.frame
    return None


def _finished(run: RunData, span: Span) -> int | None:
    for s in run.track.samples:
        if s.feet >= span.y1:
            return s.frame
    return None


def layer_runs(run: RunData) -> list[tuple[Span, int, int | None]]:
    """`(layer, frame entered, frame the band below was reached or None)` for each entered layer."""
    out = []
    for span in run.world.layers():
        start = _entered(run, span)
        if start is not None:
            out.append((span, start, _finished(run, span)))
    return out


@metric_group
def backtracking(run: RunData, _results: list[Result]) -> list[Metric]:
    samples = run.track.samples
    if not samples:
        return []
    start = samples[0].feet
    descent = run.track.deepest_feet() - start
    if descent < MIN_DESCENT:
        return [Metric("backtracking", ("N3",), None, 0, f"descent under {MIN_DESCENT} cells")]
    deepest, counted, retreat = start, 0.0, 0.0
    for s in samples:
        if s.feet > deepest:
            deepest, counted = s.feet, 0.0
            continue
        gap = deepest - s.feet
        if gap >= RETURN_ABOVE and gap > counted:
            retreat += gap - counted
            counted = gap
    return [
        Metric(
            "backtracking",
            ("N3",),
            1 - min(1.0, retreat / descent),
            1,
            f"climbed back {retreat:.0f} cells in a descent of {descent:.0f}",
            {"retreat": round(retreat, 1), "descent": round(descent, 1)},
        )
    ]


@metric_group
def decisions_per_layer(run: RunData, _results: list[Result]) -> list[Metric]:
    if not run.decisions.present:
        return [Metric("decisions_per_layer", ("N3",), None, 0, "no decisions.jsonl")]
    spent = [
        (span.layer, run.decisions.cost_between(t0, t1))
        for span, t0, t1 in layer_runs(run)
        if t1 is not None
    ]
    if not spent:
        return [Metric("decisions_per_layer", ("N3",), None, 0, "no layer was finished")]
    values = [linear(d, DECISIONS_GOOD, DECISIONS_BAD) for _, d in spent]
    return [
        Metric(
            "decisions_per_layer",
            ("N3",),
            sum(values) / len(values),
            len(spent),
            ", ".join(f"layer {k}: {d} decisions" for k, d in spent),
            {"decisions": dict(spent)},
        )
    ]


@metric_group
def route_efficiency(run: RunData, _results: list[Result]) -> list[Metric]:
    descent = run.track.deepest_feet() - run.track.samples[0].feet
    if descent < MIN_DESCENT:
        return [Metric("route_efficiency", ("N5",), None, 0, f"descent under {MIN_DESCENT} cells")]
    reference = run.world.route_length_to(run.track.deepest_feet())
    if not reference:
        return [Metric("route_efficiency", ("N5",), None, 0, "the world has no main path")]
    walked = run.track.path_length()
    value = clamp01(reference / walked) if walked > 0 else 0.0
    return [
        Metric(
            "route_efficiency",
            ("N5",),
            value,
            1,
            f"main path {reference:.0f} cells against {walked:.0f} walked",
            {"reference": round(reference, 1), "walked": round(walked, 1)},
        )
    ]


@lru_cache(maxsize=1)
def attack_spells() -> frozenset[str]:
    """Spells whose projectile hurts what it hits directly (not the digger, bombs or sprays)."""
    data = json.loads((CONTENT / "spells.json").read_text(encoding="utf-8"))
    return frozenset(
        s["key"]
        for s in data["spells"]
        if s.get("projectile")
        and s["projectile"].get("body") == "projectile"
        and (s["projectile"].get("hit_damage") or 0) > 0
        and s["key"] != "DIGGER"
    )


def target_in_sight(run: RunData, frame: int, px: float, py: float) -> bool:
    """True if a living creature within `ENGAGE` cells has a clear line from the player.

    The line is checked on the recorded grid; without a grid every creature near counts."""
    near = run.creatures_around(frame, px, py, ENGAGE)
    if not near:
        return False
    grid = run.frames.grid_at(frame)
    if grid is None:
        return True
    blocking = np.zeros(256, dtype=bool)
    blocking[list(blocking_indices())] = True
    height, width = grid.shape
    for _kind, cx, cy in near:
        n = int(max(abs(cx - px), abs(cy - py)))
        xs = np.linspace(px, cx, n + 1).round().astype(int).clip(0, width - 1)
        ys = np.linspace(py, cy, n + 1).round().astype(int).clip(0, height - 1)
        if not blocking[grid[ys, xs]].any():
            return True
    return False


@metric_group
def hit_rate(run: RunData, _results: list[Result]) -> list[Metric]:
    attacks = attack_spells()
    casts, fired = 0, 0
    used: set[str] = set()
    for e in run.events.of_type("cast"):
        keys = set(str(e.get("spells", "")).split("+")) & attacks
        me = run.track.at(int(e["frame"]))
        if not keys or me is None:
            continue
        if not target_in_sight(run, int(e["frame"]), me.x + me.w / 2, me.y + me.h / 2):
            continue
        casts += 1
        fired += int(e.get("projectiles", 1))
        used |= keys
    if casts < MIN_SHOTS:
        return [
            Metric(
                "hit_rate",
                ("N5",),
                None,
                casts,
                f"only {casts} attack casts with a creature near (need {MIN_SHOTS})",
            )
        ]
    hits = sum(
        1
        for e in run.events.of_type("hit")
        if is_creature(str(e.get("target", ""))) and e.get("projectile") in used
    )
    return [
        Metric(
            "hit_rate",
            ("N5",),
            min(1.0, hits / max(1, fired)),
            casts,
            f"{hits} hits from {fired} projectiles in {casts} attack casts",
            {"hits": hits, "projectiles": fired},
        )
    ]


@metric_group
def layer_completion(run: RunData, _results: list[Result]) -> list[Metric]:
    runs = layer_runs(run)
    if not runs:
        return [Metric("layer_completion", ("C2",), None, 0, "the player never reached a layer")]
    died = run.player_died
    deepest = run.track.deepest_feet()
    values, notes = [], []
    for span, _t0, t1 in runs:
        if t1 is not None:
            values.append(1.0)
            notes.append(f"layer {span.layer}: finished")
        else:
            progress = clamp01((deepest - span.y0) / (span.y1 - span.y0))
            values.append(progress * (0.5 if died else 1.0))
            notes.append(f"layer {span.layer}: {progress:.0%} through" + (", died" if died else ""))
    return [
        Metric(
            "layer_completion",
            ("C2",),
            sum(values) / len(values),
            len(values),
            "; ".join(notes),
        )
    ]


@metric_group
def layer_end_hp(run: RunData, _results: list[Result]) -> list[Metric]:
    finished = [(span, t1) for span, _t0, t1 in layer_runs(run) if t1 is not None]
    if not finished:
        return [Metric("layer_end_hp", ("C1",), None, 0, "no layer was finished")]
    values, notes = [], []
    for span, t1 in finished:
        s = run.track.at(t1)
        share = s.hp / s.hp_max if s and s.hp_max else 0.0
        values.append(clamp01(share / 0.5))
        notes.append(f"layer {span.layer}: {share:.0%} health on leaving")
    return [
        Metric("layer_end_hp", ("C1",), sum(values) / len(values), len(values), "; ".join(notes))
    ]
