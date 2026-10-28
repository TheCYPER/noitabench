"""Ambient hazards of the map (cp1-feedback section 3.2): not scored, but they make the map hostile.

Three kinds are placed here (flammable gas pockets are ``features.place_gas``):

* ``lava_crust``: a lava pocket sealed under a thin crust that is flush with the floor.
* ``sand_pocket``: a hanging layer of sand held back by a thin crust: the *ceiling* of the
  cave. Dig the crust and the sand pours down.
* ``sand_pit``: a pit in the floor filled to the brim with sand: dig into it and it flows.

Every hazard leaves a cue: the thin crust is made of the *other* soft material than the
rock around it (rock in a ground floor, ground in a rock one), so it shows as a patch in
the map and ``inspect`` tells what lies behind it. A sand pit shows as a patch of sand in
the floor. Everything is sealed: all cells around the pocket are ground or rock, so
nothing runs out when the simulation starts.

All three work on a *surface*: a stretch of floor, or of ceiling seen upside down (the
grid is read through a vertically flipped view, so "down" is always into the rock).
The stretch is first flattened (the floor is carved down to its lowest cell) so that the
crust or the sand lies flat.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .canvas import Canvas, Rect
from .config import Biome
from .features import ceiling_points, floor_points

SEAL_BORDER = 2  # solid cells all around a pocket
MAX_SLOPE = 3  # the stretch of floor may vary this much in height
SCAN_UP, SCAN_DOWN = 3, 7  # rows scanned around the seed for the floor of each column


@dataclass
class Ctx:
    canvas: Canvas
    rect: Rect
    rng: np.random.Generator

    def count(self, params: dict) -> int:
        units = (self.rect[2] - self.rect[0]) * (self.rect[3] - self.rect[1]) / 10_000.0
        return int(self.rng.poisson(params.get("per_10k", 0.0) * units))

    def pick(self, params: dict, key: str) -> int:
        lo, hi = params[key]
        return int(self.rng.integers(lo, hi + 1))


@dataclass
class Surface:
    """A stretch of floor in a (possibly flipped) view: columns ``x0:x1`` whose floors lie at
    ``rows`` (the first solid row of every column); ``top`` is the lowest of them, the level
    the stretch is flattened to."""

    g: np.ndarray  # view of the grid: rows grow into the rock
    prot: np.ndarray
    x0: int
    x1: int
    rows: np.ndarray
    old: int  # the most common material of the old floor

    @property
    def top(self) -> int:
        return int(self.rows.max())


def contrast(canvas: Canvas, material: int) -> int:
    """The soft material that differs from ``material`` (rock <-> ground)."""
    rock, ground = canvas.mats["rock"], canvas.mats["ground"]
    return rock if material == ground else ground


def _soft_ids(canvas: Canvas) -> np.ndarray:
    soft = np.zeros(256, dtype=bool)
    soft[[canvas.mats["ground"], canvas.mats["rock"]]] = True
    return soft


def _surface(
    canvas: Canvas, view: tuple[np.ndarray, np.ndarray], x: int, y: int, width: int
) -> Surface | None:
    """The floor stretch of ``width`` columns around ``x`` seen from the air cell ``(x, y)``."""
    g, prot = view
    x0, x1 = x - width // 2, x - width // 2 + width
    if x0 < 4 or x1 > canvas.w - 4 or y < SCAN_UP + 1 or y + SCAN_DOWN >= canvas.h - 4:
        return None
    window = g[y - SCAN_UP : y + SCAN_DOWN, x0:x1]
    solid = window != canvas.mats.air
    if not solid.any(axis=0).all():
        return None
    first = np.argmax(solid, axis=0)  # first non-air row of every column
    if first.min() == 0 or int(first.max() - first.min()) > MAX_SLOPE:
        return None  # a ceiling right above, or a floor that is too uneven
    cells = window[first, np.arange(window.shape[1])]
    if not _soft_ids(canvas)[cells].all():
        return None  # the floor is liquid, powder, wood or brick somewhere
    return Surface(g, prot, x0, x1, y - SCAN_UP + first, int(np.bincount(cells).argmax()))


def _near_fluid(canvas: Canvas, s: Surface) -> bool:
    """True if a liquid or gas touches the stretch (flattening would open a pool's rim)."""
    box = s.g[int(s.rows.min()) - 2 : s.top + 2, s.x0 - 2 : s.x1 + 2]
    return bool((canvas.mats.kind_mask(box, "liquid") | canvas.mats.kind_mask(box, "gas")).any())


def _crust_blends_in(canvas: Canvas, s: Surface) -> bool:
    """True if both cells beside the stretch are of the crust material (an invisible crust)."""
    crust = contrast(canvas, s.old)
    return bool(s.g[s.top, s.x0 - 1] == crust and s.g[s.top, s.x1] == crust)


def _sealed(canvas: Canvas, s: Surface, depth: int) -> bool:
    """True if everything from the flat floor down ``depth`` rows (plus the seal border) and
    ``SEAL_BORDER`` columns to each side is ground or rock and unprotected."""
    r0, r1 = s.top, s.top + depth + SEAL_BORDER
    c0, c1 = s.x0 - SEAL_BORDER, s.x1 + SEAL_BORDER
    if r1 >= canvas.h - 3:
        return False
    box = (slice(r0, r1), slice(c0, c1))
    return bool(_soft_ids(canvas)[s.g[box]].all() and not s.prot[box].any())


def _flatten(s: Surface, air: int) -> int:
    """Carve every column of the stretch down to ``s.top``; returns the old floor material."""
    top = s.top
    for c, row in enumerate(s.rows):
        s.g[row:top, s.x0 + c] = air
    return s.old


def _views(canvas: Canvas) -> tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    return (canvas.grid, canvas.protected), (canvas.grid[::-1], canvas.protected[::-1])


def _seeds(canvas: Canvas, rect: Rect, ceiling: bool) -> np.ndarray:
    """Standing points as ``(x, y)`` in the (possibly flipped) view."""
    if not ceiling:
        return floor_points(canvas, rect)
    pts = ceiling_points(canvas, rect).copy()
    pts[:, 1] = canvas.h - 1 - pts[:, 1]
    return pts


def _each_site(
    ctx: Ctx, params: dict, ceiling: bool, depth_key: str, depth_of: Callable[[int], int]
):
    """Yield ``(Surface, parameters)`` for every attempt whose site is sealed."""
    canvas = ctx.canvas
    pts = _seeds(canvas, ctx.rect, ceiling)
    if len(pts) == 0:
        return
    view = _views(canvas)[1 if ceiling else 0]
    for i in ctx.rng.choice(len(pts), size=ctx.count(params), replace=True):
        x, y = int(pts[i][0]), int(pts[i][1])
        width = ctx.pick(params, "w")
        s = _surface(canvas, view, x, y, width)
        if s is None or _near_fluid(canvas, s):
            continue
        size = ctx.pick(params, depth_key)
        if "crust" in params and _crust_blends_in(canvas, s):
            continue  # the crust must stand out from the floor beside it, or it is no cue
        if _sealed(canvas, s, depth_of(size)):
            yield s, size


def lava_crust(ctx: Ctx, params: dict) -> int:
    """A lava pocket under a floor of ground or rock, sealed by a thin contrasting crust."""
    canvas, placed = ctx.canvas, 0
    for s, depth in _each_site(ctx, params, False, "depth", lambda d: d + params["crust"][1]):
        crust = ctx.pick(params, "crust")
        pocket = (slice(s.top + crust, s.top + crust + depth), slice(s.x0 + 1, s.x1 - 1))
        if canvas.keepout[pocket].any():
            continue  # lava keeps out of reach of the corridors (clearance.py)
        old = _flatten(s, canvas.mats.air)
        s.g[s.top : s.top + crust, s.x0 : s.x1] = contrast(canvas, old)
        s.g[s.top + crust : s.top + crust + depth, s.x0 + 1 : s.x1 - 1] = canvas.mats["lava"]
        placed += 1
    return placed


def sand_pocket(ctx: Ctx, params: dict) -> int:
    """A layer of sand above a cave ceiling, held by a thin contrasting crust."""
    canvas, placed = ctx.canvas, 0
    for s, height in _each_site(ctx, params, True, "h", lambda h: h + params["crust"][1]):
        crust = ctx.pick(params, "crust")
        old = _flatten(s, canvas.mats.air)
        s.g[s.top : s.top + crust, s.x0 : s.x1] = contrast(canvas, old)
        s.g[s.top + crust : s.top + crust + height, s.x0 + 1 : s.x1 - 1] = canvas.mats["sand"]
        placed += 1
    return placed


def sand_pit(ctx: Ctx, params: dict) -> int:
    """A pit in the floor filled with sand up to floor level."""
    canvas, placed = ctx.canvas, 0
    for s, depth in _each_site(ctx, params, False, "depth", lambda d: d):
        _flatten(s, canvas.mats.air)
        s.g[s.top : s.top + depth, s.x0 : s.x1] = canvas.mats["sand"]
        placed += 1
    return placed


HAZARDS: tuple[tuple[str, Callable[[Ctx, dict], int]], ...] = (
    ("lava_crust", lava_crust),
    ("sand_pocket", sand_pocket),
    ("sand_pit", sand_pit),
)


def place_hazards(
    canvas: Canvas, biome: Biome, rect: Rect, rng: np.random.Generator
) -> dict[str, int]:
    """Place the biome's ``hazards``; returns how many of each were placed."""
    ctx = Ctx(canvas, rect, rng)
    counts: dict[str, int] = {}
    for name, fn in HAZARDS:
        params = biome.hazards.get(name)
        if params is not None:
            counts[name] = fn(ctx, params)
    return counts
