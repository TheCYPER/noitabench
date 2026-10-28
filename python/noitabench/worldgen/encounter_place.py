"""Putting encounter scenes into a world: choose the variant, stamp the cells, make the markers.

A scene is stamped over whatever the terrain was; its outer ring is solid except at the doors
(the art guarantees it), so it needs no blending (cp1-feedback section 2 item 5: edges stay plain).
The footprint is protected afterwards, so the dressing steps (pools, structures, hazards) leave
it alone; the doors are linked to the caves by the callers (``layers.py``, ``generate.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .canvas import Canvas, Rect
from .config import Materials
from .encounter_defs import EncounterDef, Instance, instantiate, load_encounters
from .table import Rules

OUTSIDE = {"top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0)}


@dataclass(frozen=True)
class SceneContext:
    """What scene placement needs besides the canvas: the rules of the world and the content."""

    rules: Rules
    mats: Materials
    defs: dict[str, EncounterDef]

    @classmethod
    def build(cls, rules: Rules, mats: Materials) -> SceneContext:
        return cls(rules, mats, load_encounters())

    def has(self, eid: str) -> bool:
        return eid in self.defs

    def instance(self, eid: str, rng: np.random.Generator) -> Instance:
        d = self.defs[eid]
        variant = int(rng.integers(0, d.variants))
        return instantiate(d, self.rules, variant, self.mats)


def footprint(inst: Instance, x0: int, y0: int) -> Rect:
    return x0, y0, x0 + inst.w, y0 + inst.h


def door_point(inst: Instance, side: str, x0: int, y0: int) -> tuple[int, int]:
    """The cell just outside the door on ``side`` for a scene stamped at ``(x0, y0)``."""
    cx, cy = inst.door_center(side)
    dx, dy = OUTSIDE[side]
    return x0 + cx + dx, y0 + cy + dy


def stamp(canvas: Canvas, inst: Instance, x0: int, y0: int) -> Rect:
    """Write the cells over the terrain, protect and seal the footprint; returns the footprint."""
    rect = footprint(inst, x0, y0)
    if not (0 <= rect[0] and rect[2] <= canvas.w and 0 <= rect[1] and rect[3] <= canvas.h):
        raise ValueError(f"{inst.defn.id}: footprint {rect} reaches outside the world")
    canvas.grid[rect[1] : rect[3], rect[0] : rect[2]] = inst.grid
    canvas.protect(rect)
    canvas.sealed[rect[1] : rect[3], rect[0] : rect[2]] = True
    return rect


def world_markers(inst: Instance, x0: int, y0: int) -> list[dict]:
    """The item and enemy markers of the scene in world coordinates."""
    out = []
    for m in inst.markers:
        w = dict(m)
        w["x"], w["y"] = x0 + m["x"], y0 + m["y"]
        out.append(w)
    return out


def encounter_slot(
    inst: Instance,
    rect: Rect,
    layer: int,
    biome: str,
    scene_markers: list[dict],
    must_pass: bool | None = None,
) -> dict:
    """The slot dict the generator keeps for a placed scene (``markers.encounter_marker`` reads it).

    ``must_pass`` says whether this placement is a chokepoint of the main path; by default the
    definition's own flag. A must-pass scene that is placed in a side pocket as an optional
    encounter is not one.
    """
    d = inst.defn
    tx, ty, tw, th = inst.trigger
    return {
        "encounter_id": d.id,
        "rect": rect,
        "must_pass": d.must_pass if must_pass is None else must_pass,
        "layer": layer,
        "biome": biome,
        "variant": inst.variant,
        "trigger": {"x": rect[0] + tx, "y": rect[1] + ty, "w": tw, "h": th},
        "placeholder": False,
        "params": dict(sorted(inst.params.items())),
        "mirror": inst.mirror,
        "footprint": {"x": rect[0], "y": rect[1], "w": inst.w, "h": inst.h},
        "regions": {
            k: {"x": rect[0] + b[0], "y": rect[1] + b[1], "w": b[2], "h": b[3]}
            for k, b in sorted(inst.regions.items())
        },
        "scene_markers": scene_markers,
    }
