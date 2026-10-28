"""Metrics about looking and trying: N6 new liquids tried, N7 inspect before hazards, N8 the key.

N6 new_liquids_tried ("对新材料、新物品做试验的比例"): each different non-empty liquid the player
    picked up in a bottle (`pickup` events) is one opportunity; it counts as tried if the player
    poured, threw or drank that liquid afterwards. value = tried / picked up.
N7 inspect_before_hazard ("进入危险前是否 inspect"): for each hazard region of an encounter the
    player came within `NEAR` cells of (the acid trough of E16, the lava river of E02, E05, E07
    and E14, the lava seams of E12, the pool of E23, the second pool of E24, the acid of E07),
    was a cell near it `inspect`ed before the first approach? value = inspected / approached.
    Needs decisions.jsonl.
    Whether the result of an inspect was used afterwards is not measured.
N8/C3 key_assembly ("组出的法杖是否解决了当时的问题"): if the player had every spell of the seal
    key by the time it left the sealed deep's hall (from the E06 visit), did a blast of the key's
    radius go off at the plug? One opportunity; no value if the key was never complete.
"""

from __future__ import annotations

from ..context import Ctx
from ..encounters import Result
from ..recording import RunData
from ..worldinfo import MissingRegion
from . import Metric, metric_group

NEAR = 8  # cells: coming this close to a hazard region is approaching it
INSPECT_MARGIN = 14
HAZARDS = {
    "E02": ("river",),
    "E05": ("river",),
    "E07": ("acid", "lava"),
    "E12": ("seam1", "seam2"),
    "E14": ("river",),
    "E16": ("trough",),
    "E23": ("pool",),
    "E24": ("pool_b",),
}


@metric_group
def new_liquids_tried(run: RunData, _results: list[Result]) -> list[Metric]:
    picked: dict[str, int] = {}
    for e in run.events.of_type("pickup"):
        detail = str(e.get("detail", ""))
        if e.get("item") == "bottle" and detail:
            picked.setdefault(detail, int(e["frame"]))
    if not picked:
        return [Metric("new_liquids_tried", ("N6",), None, 0, "no bottle with a liquid was taken")]
    used = {
        (e.get("material"), e["frame"])
        for e in run.events.of_type("pour", "throw", "drink")
        if e.get("material")
    }
    tried = [m for m, t0 in picked.items() if any(mm == m and f >= t0 for mm, f in used)]
    return [
        Metric(
            "new_liquids_tried",
            ("N6",),
            len(tried) / len(picked),
            len(picked),
            f"tried {len(tried)} of {len(picked)} liquids picked up",
            {"picked": sorted(picked), "tried": sorted(tried)},
        )
    ]


@metric_group
def inspect_before_hazard(run: RunData, results: list[Result]) -> list[Metric]:
    if not run.decisions.present:
        return [Metric("inspect_before_hazard", ("N7",), None, 0, "no decisions.jsonl")]
    approached, inspected = 0, 0
    notes = []
    for r in results:
        names = HAZARDS.get(r.visit.scene.eid, ())
        ctx = Ctx(run, r.visit)
        for name in names:
            try:
                region = r.visit.scene.region(name)
            except MissingRegion:
                continue
            first = run.track.first_touch(region.grow(NEAR), ctx.enter, run.last_frame)
            if first is None:
                continue
            approached += 1
            seen = ctx.inspected_near(region, first, margin=INSPECT_MARGIN)
            inspected += bool(seen)
            notes.append(f"{r.visit.scene.eid}.{name}: {'inspected' if seen else 'not inspected'}")
    if approached == 0:
        return [
            Metric("inspect_before_hazard", ("N7",), None, 0, "no hazard region was approached")
        ]
    return [
        Metric(
            "inspect_before_hazard",
            ("N7",),
            inspected / approached,
            approached,
            "; ".join(notes),
        )
    ]


@metric_group
def key_assembly(run: RunData, results: list[Result]) -> list[Metric]:
    visit = next((r for r in results if r.visit.scene.eid == "E06"), None)
    names = ("key_assembly", ("N8", "C3"))
    if visit is None:
        return [Metric(*names, None, 0, "the sealed deep was never reached")]
    facts = visit.outcome.facts
    complete = facts.get("parts_before", 0) + facts.get("parts_late", 0) >= facts.get("parts", 1)
    if not complete:
        return [Metric(*names, None, 0, "the key was never complete (a spell was never picked up)")]
    edits = len(run.events.of_type("edit_wand"))
    return [
        Metric(
            *names,
            1.0 if facts.get("key_blast") else 0.0,
            1,
            "the key was built and blasted at the plug"
            if facts.get("key_blast")
            else "the key spells were in hand but no blast of the key's radius hit the plug",
            {"edit_wand_events": edits},
        )
    ]
