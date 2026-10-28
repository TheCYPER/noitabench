"""Harm metrics: N1 repeat harm, N9 low-health discipline.

N1 repeat_harm (capability graph section 4: "同一种危险第一次吃亏之后再次吃亏的比例"):
    The player's `damage` events from the environment (contact, fire, explosion) are grouped into
    episodes per kind of hazard; events of one kind less than `EPISODE_GAP` frames apart are one
    episode. The kind of a contact hurt is the hazard in the player's hit box at that frame
    (lava, acid, toxic sludge; read from the recorded grid), or `poison` while poisoned. Enemy
    attacks are not environment hazards and are left out. value = 1 - repeats / episodes, where a
    repeat is an episode of a kind that already hurt once. No episode: not measured.
N9 low_hp_discipline (a proxy for "冒不必要的险扣分"):
    Each time health falls to 35 % or less (after having been above 50 %) is one opportunity. It
    is good if health climbs back to 50 % before the player is hurt again (it stopped to heal),
    bad if a new harm episode begins (after a calm of `EPISODE_GAP` frames; poison or burning
    that goes on from the same blow is not new) or the player dies while still low; a fall that
    ends the run with no further harm is not counted. value = good / (good + bad).
"""

from __future__ import annotations

from ..encounters import Result
from ..recording import RunData
from ..worldinfo import material_keys
from . import Metric, metric_group

EPISODE_GAP = 180  # frames: harm of one kind this close together is one episode
HAZARD_MATERIALS = ("lava", "acid", "toxic_sludge")
ENVIRONMENT = ("contact", "fire", "explosion")
LOW, SAFE = 0.35, 0.50  # health shares
LOW_GRACE = 120  # frames after the fall below which more harm is the same fall


def hazard_kind(run: RunData, event: dict) -> str:
    """The kind of hazard that hurt the player in `event` (a `damage` event)."""
    source = str(event.get("source", ""))
    if source != "contact":
        return source
    me = run.track.at(int(event["frame"]))
    grid = run.frames.grid_at(int(event["frame"]))
    if me is not None and grid is not None:
        keys = material_keys()
        x0, y0 = max(0, int(me.x) - 1), max(0, int(me.y) - 1)
        patch = grid[y0 : int(me.y + me.h) + 2, x0 : int(me.x + me.w) + 2]
        best, kind = 0, ""
        for index in sorted(set(patch.ravel().tolist())):
            if index < len(keys) and keys[index] in HAZARD_MATERIALS:
                count = int((patch == index).sum())
                if count > best:
                    best, kind = count, keys[index]
        if kind:
            return kind
    poisoned = [
        e
        for e in run.events.between(
            max(0, int(event["frame"]) - 900), int(event["frame"]), "status"
        )
        if e.get("target") == "player" and e.get("status") == "poisoned"
    ]
    if poisoned and poisoned[-1].get("active"):
        return "poison"
    return "contact"


@metric_group
def repeat_harm(run: RunData, _results: list[Result]) -> list[Metric]:
    hurt = [
        e
        for e in run.events.of_type("damage")
        if e.get("target") == "player" and e.get("source") in ENVIRONMENT
    ]
    episodes: dict[str, list[list[int]]] = {}
    for e in hurt:
        kind = hazard_kind(run, e)
        starts = episodes.setdefault(kind, [])
        if not starts or e["frame"] - starts[-1][1] > EPISODE_GAP:
            starts.append([e["frame"], e["frame"]])
        else:
            starts[-1][1] = e["frame"]
    counts = {k: len(v) for k, v in episodes.items()}
    total = sum(counts.values())
    if total == 0:
        return [
            Metric(
                "repeat_harm",
                ("N1",),
                None,
                0,
                "no environmental harm happened, so there was nothing to repeat",
            )
        ]
    repeats = sum(n - 1 for n in counts.values())
    return [
        Metric(
            "repeat_harm",
            ("N1",),
            1 - repeats / total,
            total,
            f"{repeats} of {total} harm episodes were of a kind that had already hurt",
            {"episodes_by_kind": counts},
        )
    ]


@metric_group
def low_hp_discipline(run: RunData, _results: list[Result]) -> list[Metric]:
    samples = run.track.samples
    damage = [e["frame"] for e in run.events.of_type("damage") if e.get("target") == "player"]
    died = run.died_at()
    armed, good, bad = True, 0, 0
    for i, s in enumerate(samples):
        share = s.hp / s.hp_max if s.hp_max else 1.0
        if armed and share <= LOW and s.hp > 0:
            armed = False
            outcome = _after_fall(samples, i, damage, died)
            good += outcome == "good"
            bad += outcome == "bad"
        elif not armed and share >= SAFE:
            armed = True
    n = good + bad
    if n == 0:
        return [
            Metric(
                "low_hp_discipline",
                ("N9",),
                None,
                0,
                "health never fell low and then settled (nothing to judge)",
            )
        ]
    return [
        Metric(
            "low_hp_discipline",
            ("N9",),
            good / n,
            n,
            f"{good} of {n} falls to low health were followed by healing before more harm",
            {"good": good, "bad": bad},
        )
    ]


def _after_fall(samples, i: int, damage: list[int], died: int | None) -> str:
    """'good', 'bad' or 'open' for the fall below LOW at samples[i].

    Harm that goes on from the same blow (poison, burning) is the same fall; harm that starts
    after a calm of `EPISODE_GAP` frames, while health is still low, is pressing on."""
    t0 = samples[i].frame
    t_heal = None
    for s in samples[i + 1 :]:
        if s.hp_max and s.hp / s.hp_max >= SAFE:
            t_heal = s.frame
            break
    horizon = t_heal if t_heal is not None else samples[-1].frame
    starts = [f for k, f in enumerate(damage) if k == 0 or f - damage[k - 1] > EPISODE_GAP]
    again = [f for f in starts if t0 < f <= horizon]
    if again or (died is not None and died > t0 + LOW_GRACE and t_heal is None):
        return "bad"
    return "good" if t_heal is not None else "open"
