"""Alchemy bowls: metal basins sunk into the floor where the player can mix ingredients.

CP2 (2026-10-27): only the recipes of the secret potions change from seed to seed, so an agent has
to find them by trying. It needs a place to try: a bowl of ``metal`` (static, durability 15, never
corroded, burnt or dug out) that holds what is poured into it. A bowl is **sunk**: its rim is level
with the floor, so the player can stand on the rim, pour straight down into it and scoop the
result up again (``pour`` lands about 8 cells from the hand, which is inside the bowl from the
rim and well below the rim of a raised bowl).

Geometry (``scenes.alchemy.bowl`` in ``biome_map.json``, interior ``w`` x ``h``, wall thickness
``wall``)::

    rim row ->  MM..........MM          M = metal (walls, bottom),  . = the open interior
                MM..........MM
                MMMMMMMMMMMMMM          outer box: (w + 2 wall) x (h + wall)

The ``alchemy_bowl`` marker (contracts section 4) is the *interior* box ``{x, y, w, h}``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # canvas.py imports config.py, which imports this module
    from .canvas import Canvas

Rect = tuple[int, int, int, int]  # x0, y0, x1, y1 (end exclusive), as in canvas.py

PILLAR_END = 8  # a rest hall's end pillar covers this many cells at each end of the hall
SIDE_GAP = 3  # free cells between a rest hall's pillar and its bowl
BOTTLE_ROOM = 12  # room beside the bowl for the empty bottles that lie there
HEAD_ROOM = 14  # open rows above a cave bowl: the player's box (7) twice over
FLAT_MARGIN = 4  # flat floor beside a cave bowl, so the rim is reached without a climb
FLAT_FILL = 3  # rows below the rim that levelling the margins may fill


@dataclass(frozen=True)
class BowlSpec:
    """Size of a bowl: the open interior and the thickness of its walls and bottom."""

    w: int
    h: int
    wall: int

    @classmethod
    def from_config(cls, d: dict) -> BowlSpec:
        return cls(int(d["w"]), int(d["h"]), int(d["wall"]))

    @property
    def outer_w(self) -> int:
        return self.w + 2 * self.wall

    @property
    def outer_h(self) -> int:
        return self.h + self.wall

    def outer(self, bx: int, rim: int) -> Rect:
        """The whole bowl, walls included: ``bx`` is its left edge, ``rim`` its top row."""
        return bx, rim, bx + self.outer_w, rim + self.outer_h

    def interior(self, bx: int, rim: int) -> Rect:
        return bx + self.wall, rim, bx + self.wall + self.w, rim + self.h


def hall_spans(rest: dict) -> tuple[tuple[int, int], tuple[int, int]]:
    """Free floor beside a rest hall's slots, left and right: ``(a0, a1)``, ``(b0, b1)``.

    The spans lie between the end pillars and the two encounter slots; a bowl goes into one of
    them (``scenes.build_rest``). The arithmetic is that of ``build_rest``.
    """
    hx0, hx1 = rest["hall"]["x"]
    edges = []
    for s in rest["slots"]:
        cx = hx0 + int(s["anchor"] * (hx1 - hx0))
        edges.append((cx - s["w"] // 2, cx + s["w"] // 2))
    return (hx0 + PILLAR_END, min(e[0] for e in edges)), (
        max(e[1] for e in edges),
        hx1 - PILLAR_END,
    )


def span_room(spec: BowlSpec) -> int:
    """The width a hall span needs for a bowl, its gap to the pillar and the bottles beside it."""
    return SIDE_GAP + spec.outer_w + BOTTLE_ROOM


def hall_bowl_x(spec: BowlSpec, span: tuple[int, int], side: str) -> int:
    """Left edge of the bowl in a hall span: against the pillar, the bottles on the slot side."""
    if side == "left":
        return span[0] + SIDE_GAP
    return span[1] - SIDE_GAP - spec.outer_w


def hall_bottle_xs(spec: BowlSpec, bx: int, side: str, count: int) -> list[int]:
    """Floor columns for ``count`` empty bottles on the slot side of a hall bowl."""
    if side == "left":
        return [bx + spec.outer_w + 4 + 4 * i for i in range(count)]
    return [bx - 5 - 4 * i for i in range(count)]


def stamp_bowl(canvas: Canvas, spec: BowlSpec, bx: int, rim: int, place: str) -> dict:
    """Build a bowl with its rim row at ``rim``; returns its ``alchemy_bowl`` marker.

    Metal replaces whatever stood in the outer box (force: this is deliberate building), the
    interior is cleared to air. The caller has checked the site.
    """
    x0, y0, x1, y1 = spec.outer(bx, rim)
    ix0, iy0, ix1, iy1 = spec.interior(bx, rim)
    canvas.grid[y0:y1, x0:x1] = canvas.mats["metal"]
    canvas.grid[iy0:iy1, ix0:ix1] = canvas.mats.air
    return {
        "type": "alchemy_bowl",
        "x": ix0,
        "y": iy0,
        "w": ix1 - ix0,
        "h": iy1 - iy0,
        "place": place,
    }


def bowl_cells(spec: BowlSpec, marker: dict) -> tuple[Rect, Rect]:
    """``(outer, interior)`` boxes of a bowl, rebuilt from its marker."""
    ix0, iy0 = marker["x"], marker["y"]
    return (
        (ix0 - spec.wall, iy0, ix0 + spec.w + spec.wall, iy0 + spec.h + spec.wall),
        (ix0, iy0, ix0 + marker["w"], iy0 + marker["h"]),
    )


def bowl_intact(grid: np.ndarray, metal: int, air: int, spec: BowlSpec, marker: dict) -> str:
    """'' if the bowl at ``marker`` is whole (metal walls and bottom, open interior), else why not."""
    (x0, y0, x1, y1), (ix0, iy0, ix1, iy1) = bowl_cells(spec, marker)
    if (marker["w"], marker["h"]) != (spec.w, spec.h):
        return f"size {marker['w']}x{marker['h']} instead of {spec.w}x{spec.h}"
    if x0 < 0 or y0 < 0 or x1 > grid.shape[1] or y1 > grid.shape[0]:
        return "reaches outside the world"
    box = grid[y0:y1, x0:x1]
    inside = np.zeros(box.shape, dtype=bool)
    inside[iy0 - y0 : iy1 - y0, ix0 - x0 : ix1 - x0] = True
    if (box[inside] != air).any():
        return "the interior is not empty"
    if (box[~inside] != metal).any():
        return "a wall or the bottom is not metal"
    return ""
