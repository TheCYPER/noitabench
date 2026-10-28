"""Why a combined scenario failed, traced to a basic node (PRD 2.4: "组合任务失败时归因到具体节点").

Two kinds of failure are attributed from the recording:

- a layer the player entered but did not finish (the C2 part): the last harm before the end of
  the run, the encounter the player was in or last met in that layer, and that encounter's
  nodes;
- the sealed deep (E06, the C3 part) met but not opened: what was missing (a spell never found,
  a long climb back, no blast at the plug) and the nodes of E06.
"""

from __future__ import annotations

from typing import Any

from .encounters import Result
from .metrics.harm import hazard_kind
from .metrics.route import layer_runs
from .recording import RunData
from .worldinfo import encounter_nodes


def _encounter_at_end(run: RunData, results: list[Result], y0: int, y1: int) -> Result | None:
    """The scene the player was in at the end of the run, else the last scene met in the band."""
    end = run.track.samples[-1]
    inside = [r for r in results if r.visit.scene.footprint.has_point(end.x, end.y)]
    if inside:
        return inside[-1]
    here = [r for r in results if y0 <= r.visit.scene.footprint.y < y1]
    return max(here, key=lambda r: r.visit.enter) if here else None


def _last_harm(run: RunData) -> dict[str, Any] | None:
    hurt = [e for e in run.events.of_type("damage") if e.get("target") == "player"]
    if not hurt:
        return None
    last = hurt[-1]
    return {"frame": last["frame"], "source": last.get("source"), "kind": hazard_kind(run, last)}


def attribute(run: RunData, results: list[Result]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    died = run.died_at()
    for span, _t0, t1 in layer_runs(run):
        if t1 is not None:
            continue
        where = _encounter_at_end(run, results, span.y0, span.y1)
        eid = where.visit.scene.eid if where else None
        out.append(
            {
                "capability": "C2",
                "layer": span.layer,
                "outcome": "died" if died is not None else "ended",
                "frame": died if died is not None else run.last_frame,
                "last_harm": _last_harm(run) if died is not None else None,
                "encounter": eid,
                "nodes": list(encounter_nodes(eid)) if eid else [],
            }
        )
    seal = next((r for r in results if r.visit.scene.eid == "E06"), None)
    if seal is not None and not seal.outcome.facts.get("opened"):
        f = seal.outcome.facts
        missing = f.get("parts", 0) - f.get("parts_before", 0) - f.get("parts_late", 0)
        reason = (
            "a key spell was never picked up"
            if missing > 0
            else "the key was complete but no blast of its radius hit the plug"
            if not f.get("key_blast")
            else "the blast went off but the player did not get in"
        )
        out.append(
            {
                "capability": "C3",
                "encounter": "E06",
                "reason": reason,
                "nodes": list(encounter_nodes("E06")),
            }
        )
    return out
