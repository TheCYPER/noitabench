"""N2 cross_game_gain and C4 growth_depth / growth_harm / growth_pace: is a later game of a family
better than game 1? (design: `.trellis/tasks/10-16-noita-cogbench/research/2026-10-28-cross-game-design.md`)

Memory across games is only the workspace; the caves change every game and the rules do not
(PRD 2.5). So game k >= 2 of a family folder (`runs/<name>/run-NN/`) is compared with game 1 of
the same folder, the lowest `run-NN`. Game 1 and a run outside a family folder have nothing to be
compared with and are `not_measured`, as are two games that differ in rule seed or model, and a
family whose game 1 cannot be read. Game 1's encounter results and depth are recomputed from its
recording with the evaluator's own code (never read from an old `profile.json`) and kept for the
next games of the family (`baseline_of`).

**From two numbers to a value.** `a` is game 1, `b` is game k.

- A score bounded by 0..1 (an encounter, the depth score / 100): `b >= a` gives
  `g = (b - a) / (1 - a)`, the share of the room to improve that was used; `b < a` gives
  `g = (b - a) / a`, the share of game 1's score that was lost. `a = b = 1` is skipped (nothing to
  gain, nothing to lose); `a = b = 0` gives 0.
- A cost where less is better (HP lost, decisions spent): `g = (a - b) / max(a, b)`, 0 when both
  are 0.

`g` lies in -1..1; the value of a metric is `(1 + mean g) / 2`: 0.5 is no change, 1 is all the room
used, 0 is everything lost. No change maps to 0.5 and not 0 because the map is new each game:
an encounter goes up or down by chance, and clamping losses to 0 would turn that chance into a
positive score.

**Metrics.**

- `cross_game_gain` (N2): one opportunity per encounter id scored in both games (the mean of its
  scored visits in each game, any variant) that was not perfect in both. Encounters game 1 never
  reached are not compared (depth covers them).
- `growth_depth` (C4): the depth score of game k against game 1; one opportunity.
- `growth_harm` (C4): HP lost (the player's `damage` events) from the start until the player first
  reached the shared depth `d* = min(depth_1, depth_k)` (depth on the 0..100 scale of
  `depth.py`, the first frame found by interpolating between the samples, `depth.reach_frame`);
  less is better; one opportunity.
- `growth_pace` (C4): decisions spent (the cost rule of `decisions.jsonl`) before that moment;
  fewer is better; one opportunity; not measured without `decisions.jsonl` in both games.

Both of the last two need `d* >= MIN_SHARED_DEPTH`. Comparing over the stretch both games walked
keeps a game that died early from looking efficient (few decisions) or careful (little harm).

Every metric's `detail` holds the numbers it was made from.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..depth import deepest, depth_curve, reach_frame
from ..encounters import Result, evaluate_visits
from ..games import first_game, model_of, model_text, rule_seed_of, run_number
from ..recording import RunData, as_float, load_run
from ..rubric import clamp01
from . import Metric, metric_group

MIN_SHARED_DEPTH = 5.0  # depth points: a shared stretch shorter than this is not worth comparing
FULL = 1.0 - 1e-9  # a score this high counts as 1
CACHE_SIZE = 4  # games kept for the next evaluations of the same family

NAMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cross_game_gain", ("N2",)),
    ("growth_depth", ("C4",)),
    ("growth_harm", ("C4",)),
    ("growth_pace", ("C4",)),
)
GROWTH_METRICS = tuple(name for name, _caps in NAMES)


# ------------------------------------------------------------------------------- the formulas
def bounded_gain(a: float, b: float) -> float | None:
    """Change of a score bounded by 0..1 from `a` (game 1) to `b` (game k), -1..1; None when both
    are 1 (nothing to gain, nothing to lose)."""
    a, b = clamp01(a), clamp01(b)
    if a >= FULL and b >= FULL:
        return None
    g = (b - a) / (1.0 - a) if b >= a else (b - a) / a
    return max(-1.0, min(1.0, g))


def cost_gain(a: float, b: float) -> float:
    """Change of a cost (less is better) from `a` to `b`, -1..1; 0 when both are 0."""
    worst = max(a, b)
    return 0.0 if worst <= 0 else (a - b) / worst


def growth_value(gains: list[float]) -> float:
    """`(1 + mean g) / 2`: 0.5 no change, 1 all the room used, 0 everything lost."""
    return (1.0 + sum(gains) / len(gains)) / 2.0


# ----------------------------------------------------------------------------------- game 1
def scene_scores(results: list[Result]) -> dict[str, float]:
    """Encounter id -> the mean of the scores of its scored visits (any variant)."""
    by_id: dict[str, list[float]] = {}
    for r in results:
        if r.outcome.score is not None:
            by_id.setdefault(r.visit.scene.eid, []).append(r.outcome.score)
    return {eid: sum(v) / len(v) for eid, v in sorted(by_id.items())}


@dataclass(frozen=True)
class Baseline:
    """Game 1 of a family, evaluated once. `files` are the files it was made from."""

    name: str
    run: RunData
    scenes: dict[str, float]
    curve: list[tuple[int, float]]
    depth: float
    files: tuple[Path, ...] = ()


_READ = ("meta.json", "entities.jsonl", "events.jsonl", "decisions.jsonl", "summary.json")
_CACHE: OrderedDict[str, tuple[tuple[Any, ...], Baseline]] = OrderedDict()


def _stamp(files: tuple[Path, ...]) -> tuple[Any, ...]:
    """Modification time and size of each file (None for one that is not there)."""
    out: list[Any] = []
    for path in files:
        try:
            st = path.stat()
        except OSError:
            out.append(None)
        else:
            out.append((st.st_mtime_ns, st.st_size))
    return tuple(out)


def baseline_of(folder: Path) -> Baseline:
    """Game 1 read and scored from its recording. Kept in a small cache (by folder; a changed
    recording or world file is read again), so that the games of a family do not rescore it each.
    Raises what `load_run` raises when the folder cannot be read."""
    key = str(folder.resolve())
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == _stamp(hit[1].files):
        _CACHE.move_to_end(key)
        return hit[1]
    run = load_run(folder)
    curve = depth_curve(run)
    world = (run.world.json_path, run.world.png_path)
    files = (*(run.root / name for name in _READ), *(p for p in world if p is not None))
    base = Baseline(
        folder.name, run, scene_scores(evaluate_visits(run)), curve, deepest(curve), files
    )
    _CACHE[key] = (_stamp(files), base)
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_SIZE:
        _CACHE.popitem(last=False)
    return base


def clear_baselines() -> None:
    _CACHE.clear()


def _baseline_for(run: RunData) -> Baseline | str:
    """Game 1 of this run's family, or the reason there is none to compare with."""
    n = run_number(run.root)
    first = first_game(run.root)
    if n is None or first is None:
        return (
            "not a game of a family folder (its folder is not named run-NN): "
            "there is no game 1 to compare with"
        )
    if (run_number(first) or 0) >= n:
        return "this is game 1 of its family folder: there is no earlier game to compare with"
    try:
        base = baseline_of(first)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as err:
        return f"game 1 ({first.name}) cannot be read: {err}"
    unlike = []
    if rule_seed_of(base.run) != rule_seed_of(run):
        unlike.append(f"rule seed {rule_seed_of(base.run)} in game 1, {rule_seed_of(run)} here")
    if model_of(base.run) != model_of(run):
        unlike.append(
            f"{model_text(model_of(base.run))} played game 1, {model_text(model_of(run))} here"
        )
    if unlike:
        return f"not comparable with game 1 ({first.name}): " + "; ".join(unlike)
    return base


# ---------------------------------------------------------------------------------- metrics
def _lacking(reason: str) -> list[Metric]:
    return [Metric(name, caps, None, 0, reason) for name, caps in NAMES]


def _gain(base: Baseline, results: list[Result]) -> Metric:
    name, caps = NAMES[0]
    mine = scene_scores(results)
    shared = sorted(set(base.scenes) & set(mine))
    scenes, gains = [], []
    for eid in shared:
        a, b = base.scenes[eid], mine[eid]
        g = bounded_gain(a, b)
        scenes.append(
            {
                "id": eid,
                "game_1": round(a, 4),
                "this_game": round(b, 4),
                "g": None if g is None else round(g, 4),
            }
        )
        if g is not None:
            gains.append(g)
    detail: dict[str, Any] = {
        "baseline": base.name,
        "scenes": scenes,
        "mean_g": None if not gains else round(sum(gains) / len(gains), 4),
        "only_game_1": sorted(set(base.scenes) - set(mine)),
        "only_this_game": sorted(set(mine) - set(base.scenes)),
    }
    if not shared:
        return Metric(name, caps, None, 0, "no encounter was scored in both games", detail)
    if not gains:
        why = "every encounter scored in both games was perfect in both: nothing to gain or lose"
        return Metric(name, caps, None, 0, why, detail)
    mean = sum(gains) / len(gains)
    reason = (
        f"{len(gains)} encounter(s) scored in both games, mean change {mean:+.2f} "
        "(-1 all lost, 0 none, +1 all the room used)"
    )
    return Metric(name, caps, growth_value(gains), len(gains), reason, detail)


def _depth_metric(base: Baseline, depth: float) -> Metric:
    name, caps = NAMES[1]
    detail: dict[str, Any] = {
        "baseline": base.name,
        "game_1": round(base.depth, 2),
        "this_game": round(depth, 2),
    }
    g = bounded_gain(base.depth / 100.0, depth / 100.0)
    detail["g"] = None if g is None else round(g, 4)
    if g is None:
        return Metric(
            name, caps, None, 0, "the sealed room's floor was reached in both games", detail
        )
    reason = f"depth {base.depth:.1f} in game 1, {depth:.1f} here (change {g:+.2f})"
    return Metric(name, caps, growth_value([g]), 1, reason, detail)


def hp_lost(run: RunData, frame: float) -> float:
    """HP the player lost (the `damage` events to the player) up to and including `frame`."""
    return sum(as_float(e.get("amount")) for e in run.events.player_damage(0, int(frame)))


def decisions_before(run: RunData, frame: float) -> int:
    """Decisions spent before `frame`: the cost of those asked at an earlier frame."""
    return run.decisions.cost_between(0, math.ceil(frame))


def _stretch(
    which: int,
    base: Baseline,
    run: RunData,
    shared: float,
    frames: tuple[float, float],
    cost: Callable[[RunData, float], float],
    unit: str,
    key: str,
) -> Metric:
    """One cost (`cost(run, frame)`: HP lost, decisions spent) of game 1 and of this game up to
    the moment each first reached the shared depth; `which` indexes `NAMES`."""
    name, caps = NAMES[which]
    a, b = cost(base.run, frames[0]), cost(run, frames[1])
    g = cost_gain(a, b)
    detail = {
        "baseline": base.name,
        "shared_depth": round(shared, 2),
        "game_1": {"frame": round(frames[0], 1), key: round(a, 2)},
        "this_game": {"frame": round(frames[1], 1), key: round(b, 2)},
        "g": round(g, 4),
    }
    reason = (
        f"{unit} until depth {shared:.1f} was first reached: {a:.4g} in game 1, {b:.4g} here "
        f"(change {g:+.2f})"
    )
    return Metric(name, caps, growth_value([g]), 1, reason, detail)


def _shared_stretch(
    base: Baseline, run: RunData, depth: float, curve: list[tuple[int, float]]
) -> list[Metric]:
    shared = min(base.depth, depth)
    if shared < MIN_SHARED_DEPTH:
        why = (
            f"the depth both games reached ({shared:.1f}) is under {MIN_SHARED_DEPTH:g}: "
            "no shared stretch worth comparing"
        )
        return [Metric(n, c, None, 0, why) for n, c in NAMES[2:]]
    f1, fk = reach_frame(base.curve, shared), reach_frame(curve, shared)
    if f1 is None or fk is None:
        why = "the moment the shared depth was reached cannot be found in the recording"
        return [Metric(n, c, None, 0, why) for n, c in NAMES[2:]]
    frames = (f1, fk)
    harm = _stretch(2, base, run, shared, frames, hp_lost, "HP lost", "hp_lost")
    if base.run.decisions.present and run.decisions.present:
        pace = _stretch(3, base, run, shared, frames, decisions_before, "decisions", "decisions")
    else:
        which = "game 1" if not base.run.decisions.present else "this game"
        pace = Metric(*NAMES[3], None, 0, f"no decisions.jsonl in {which}")
    return [harm, pace]


@metric_group
def cross_game(run: RunData, results: list[Result]) -> list[Metric]:
    base = _baseline_for(run)
    if isinstance(base, str):
        return _lacking(base)
    curve = depth_curve(run)
    depth = deepest(curve)
    return [
        _gain(base, results),
        _depth_metric(base, depth),
        *_shared_stretch(base, run, depth, curve),
    ]
