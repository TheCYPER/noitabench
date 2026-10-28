"""Biome-specific structures (cp1-feedback section 2, row 3): what makes a biome look built.

Each structure reads its parameters from the biome's ``decor`` section (``per_10k`` is the
number of *attempts* per 10,000 cells of region; most attempts are rejected). A structure
only replaces cells it has checked first: wood and brick go into free boxes of air, wood
frames only replace rock, carving never opens a pool. Whatever puts solid cells into open
space runs through ``Ctx.guard``: if it would cut a passage for the player, it is undone.
All of them are counted for ``meta["built"]``.

* mine: wooden frames (posts and a lintel) outlining tunnels, ceiling beams, platforms
* fungal caverns: mushrooms (stalk and cap, wood)
* oil caverns: oil seams, thin sealed cracks full of oil
* brick ruins: pillars, broken walls, breaches, collapsed walls, rubble
* workshop: ceiling and wall pipes, catwalks, oil and water channels, rows of barrels
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
from scipy.ndimage import binary_erosion, label

from .canvas import PLAYER_H, PLAYER_W, Canvas, Rect
from .carve import stamp_segment
from .config import Biome
from .features import ceiling_points, floor_points
from .fill import RegionInfo
from .markers import BARREL_CLEARANCE
from .rng import pick_weighted
from .rooms import Room

MARGIN = 3  # structures stay this far from the edge of the world
SEAM_RADIUS = 1.0
SEAM_STEP = 4
MIN_SPLIT_CELLS = 8  # a structure may cut off at most this many player-fit cells
GUARD_PAD = 20  # the window around a structure that is checked for cut passages
PLAYER_BOX = np.ones((PLAYER_H, PLAYER_W), dtype=bool)


@dataclass
class Ctx:
    canvas: Canvas
    rect: Rect
    rng: np.random.Generator
    region: RegionInfo
    markers: list[dict]

    @property
    def units(self) -> float:
        return (self.rect[2] - self.rect[0]) * (self.rect[3] - self.rect[1]) / 10_000.0

    def count(self, params: dict) -> int:
        return int(self.rng.poisson(params.get("per_10k", 0.0) * self.units))

    def pick(self, params: dict, key: str) -> int:
        lo, hi = params[key]
        return int(self.rng.integers(lo, hi + 1))

    def chance(self, p: float) -> bool:
        return bool(self.rng.random() < p)

    def guard(self, box: Rect, apply: Callable[[], None]) -> bool:
        """Run ``apply`` (it changes cells inside ``box``); undo it if it cuts a passage."""
        return guarded(self.canvas, box, apply)


def guarded(canvas: Canvas, box: Rect, apply: Callable[[], None]) -> bool:
    """Run ``apply`` (it changes cells inside ``box``); undo it if it cuts a passage.

    The check looks at the player-fit areas in a window around the box, before and after.
    """
    x0, y0, x1, y1 = canvas.clip(
        (box[0] - GUARD_PAD, box[1] - GUARD_PAD, box[2] + GUARD_PAD, box[3] + GUARD_PAD)
    )
    window = canvas.grid[y0:y1, x0:x1]
    before, snapshot = _fit_labels(canvas, window), window.copy()
    apply()
    if cuts_passage(before, _fit_labels(canvas, window)):
        window[:] = snapshot
        return False
    return True


def _inside(canvas: Canvas, x0: int, y0: int, x1: int, y1: int) -> bool:
    return x0 >= MARGIN and y0 >= MARGIN and x1 <= canvas.w - MARGIN and y1 <= canvas.h - MARGIN


def free_box(canvas: Canvas, x0: int, y0: int, x1: int, y1: int, powder_ok: bool = False) -> bool:
    """True if the whole box is air (or loose powder, with ``powder_ok``) and unprotected."""
    if not _inside(canvas, x0, y0, x1, y1) or x0 >= x1 or y0 >= y1:
        return False
    sub = canvas.grid[y0:y1, x0:x1]
    free = sub == canvas.mats.air
    if powder_ok:
        free |= canvas.mats.kind_mask(sub, "powder")
    return bool(free.all() and not canvas.protected[y0:y1, x0:x1].any())


def near_fluid(canvas: Canvas, x0: int, y0: int, x1: int, y1: int, pad: int = 2) -> bool:
    """True if a liquid or gas cell lies in the box grown by ``pad`` (never open a pool's wall)."""
    x0, y0, x1, y1 = canvas.clip((x0 - pad, y0 - pad, x1 + pad, y1 + pad))
    sub = canvas.grid[y0:y1, x0:x1]
    return bool((canvas.mats.kind_mask(sub, "liquid") | canvas.mats.kind_mask(sub, "gas")).any())


def _hits(boxes: list[Rect], x0: int, y0: int, x1: int, y1: int) -> bool:
    return any(not (b[2] <= x0 or x1 <= b[0] or b[3] <= y0 or y1 <= b[1]) for b in boxes)


def _fill(canvas: Canvas, x0: int, y0: int, x1: int, y1: int, material: int) -> None:
    canvas.grid[y0:y1, x0:x1] = material


def _fill_air_only(canvas: Canvas, x0: int, y0: int, x1: int, y1: int, material: int) -> None:
    sub = canvas.grid[y0:y1, x0:x1]
    sub[(sub == canvas.mats.air) & ~canvas.protected[y0:y1, x0:x1]] = material


def _embed(canvas: Canvas, cells: list[tuple[int, int]]) -> int:
    """Turn ground and rock cells among ``cells`` into wood; returns 1 if any changed."""
    mats, grid = canvas.mats, canvas.grid
    soft = (mats["ground"], mats["rock"])
    changed = 0
    for cx, cy in cells:
        inside = 3 <= cx < canvas.w - 3 and 3 <= cy < canvas.h - 3
        if inside and not canvas.protected[cy, cx] and grid[cy, cx] in soft:
            grid[cy, cx] = mats["wood"]
            changed = 1
    return changed


def _open_side(canvas: Canvas, room: Room, side: str) -> bool:
    """True if the wall behind ``side`` ('left', 'right', 'top', 'bottom') has an opening."""
    g, air = canvas.grid, canvas.mats.air
    strips = {
        "left": g[room.y0 : room.y1, room.x0 - 2 : room.x0],
        "right": g[room.y0 : room.y1, room.x1 : room.x1 + 2],
        "top": g[room.y0 - 2 : room.y0, room.x0 : room.x1],
        "bottom": g[room.y1 : room.y1 + 2, room.x0 : room.x1],
    }
    return bool((strips[side] == air).any())


# ------------------------------------------------------------------------- mine


def _timber(ctx: Ctx, params: dict) -> int:
    """Wooden beams set into the ceiling rock (they never narrow a passage)."""
    pts = ceiling_points(ctx.canvas, ctx.rect)
    if len(pts) == 0:
        return 0
    placed = 0
    for i in ctx.rng.choice(len(pts), size=ctx.count(params), replace=True):
        x, y = int(pts[i][0]), int(pts[i][1])
        cells = [(cx, cy) for cx in range(x - 8, x + 9) for cy in (y - 1, y - 2, y - 3)]
        cells += [(cx, cy) for cx in (x - 7, x + 7) for cy in range(y - 11, y - 3)]
        placed += _embed(ctx.canvas, cells)
    return placed


def _air_run(row: np.ndarray, x: int, air: int, limit: int = 30) -> tuple[int, int] | None:
    """First and last air column of the run around ``x``; None if it is longer than ``limit``."""
    if not limit + 2 <= x < len(row) - limit - 2:
        return None
    lo, hi = x, x
    while x - lo < limit and row[lo - 1] == air:
        lo -= 1
    while hi - x < limit and row[hi + 1] == air:
        hi += 1
    if row[lo - 1] == air or row[hi + 1] == air:
        return None
    return lo, hi


def _air_top(col: np.ndarray, y: int, air: int, limit: int = 20) -> int | None:
    """Row of the highest air cell of the air run above row ``y`` (None if it runs on)."""
    top = y
    while y - top < limit:
        if col[top - 1] != air:
            return top
        top -= 1
    return None


def _frames(ctx: Ctx, params: dict) -> int:
    """Mine supports: a lintel in the ceiling rock and a post in each wall, all in wood.

    The frame outlines a tunnel 8-30 wide from the inside of the rock (it only replaces
    ground and rock cells), so it never narrows the passage.
    """
    canvas = ctx.canvas
    g, mats = canvas.grid, canvas.mats
    pts = ceiling_points(canvas, ctx.rect)
    if len(pts) == 0:
        return 0
    placed = 0
    for i in ctx.rng.choice(len(pts), size=ctx.count(params), replace=True):
        x, y = int(pts[i][0]), int(pts[i][1])
        yy = y + 5
        if not MARGIN + 3 <= y < canvas.h - 60:
            continue
        run = _air_run(g[yy], x, mats.air)
        if run is None or not 8 <= run[1] - run[0] + 1 <= 30:
            continue
        lo, hi = run
        tops = [_air_top(g[:, c], yy, mats.air) for c in range(lo, hi + 1)]
        if None in tops or max(tops) - min(tops) > 5:
            continue
        floors = [yy + int(np.argmax(g[yy:, c] != mats.air)) for c in (lo, hi)]
        if not all(8 <= f - min(tops) <= 45 for f in floors):
            continue
        cells = [(c, r) for c, t in zip(range(lo, hi + 1), tops) for r in (t - 1, t - 2)]
        for c, f in (
            (lo - 1, floors[0]),
            (lo - 2, floors[0]),
            (hi + 1, floors[1]),
            (hi + 2, floors[1]),
        ):
            cells += [(c, r) for r in range(min(tops) - 2, f)]
        placed += _embed(canvas, cells)
    return placed


def _platforms(ctx: Ctx, params: dict) -> int:
    """Wooden platforms: a shelf nailed to a wall, or a plank on a post standing on the floor."""
    canvas = ctx.canvas
    pts = floor_points(canvas, ctx.rect)
    if len(pts) == 0:
        return 0
    placed = 0
    for i in ctx.rng.choice(len(pts), size=ctx.count(params), replace=True):
        x, y = int(pts[i][0]), int(pts[i][1])
        length, height = ctx.pick(params, "len"), ctx.pick(params, "height")
        if ctx.chance(params.get("shelf", 0.7)):
            placed += _shelf(ctx, x, y, length, height)
        else:
            placed += _scaffold(ctx, x, y, length, height)
    return placed


def _scaffold(ctx: Ctx, x: int, y: int, length: int, height: int) -> int:
    """A plank on one central post (a table): everything must stand in air.

    One post, not two: a plank on two posts would close off the air under it.
    """
    canvas, wood = ctx.canvas, ctx.canvas.mats["wood"]
    x0, x1, top = x - length // 2, x - length // 2 + length, y - height
    parts = ((x0, top - 6, x1, top + 2), (x - 1, top + 2, x + 2, y + 1))
    if not all(free_box(canvas, *box) for box in parts):
        return 0
    if not canvas.mats.kind_mask(canvas.grid[y + 1, x - 1 : x + 2], "static").all():
        return 0

    def build() -> None:
        _fill(canvas, x0, top, x1, top + 2, wood)
        _fill(canvas, *parts[1], wood)

    return int(ctx.guard((x0, top, x1, y + 1), build))


def _shelf(ctx: Ctx, x: int, y: int, length: int, height: int, material: str = "wood") -> int:
    """A slab sticking out of the nearer wall at ``height`` above the floor, with a bracket."""
    canvas, wood, g = ctx.canvas, ctx.canvas.mats[material], ctx.canvas.grid
    top = y - height
    run = _air_run(g[top], x, canvas.mats.air, limit=24)
    if run is None or run[1] - run[0] + 1 < length + 8:
        return 0
    lo, hi = run
    left = x - lo <= hi - x
    x0, x1 = (lo, lo + length) if left else (hi + 1 - length, hi + 1)
    bx = x0 if left else x1 - 2  # the bracket: a short post under the wall end
    parts = ((x0, top - 6, x1, top + 2), (bx, top + 2, bx + 2, top + 6))
    if not all(free_box(canvas, *box) for box in parts):
        return 0

    def build() -> None:
        _fill(canvas, x0, top, x1, top + 2, wood)
        _fill(canvas, *parts[1], wood)

    return int(ctx.guard((x0, top, x1, top + 6), build))


def _catwalks(ctx: Ctx, params: dict) -> int:
    """Brick catwalks along the walls of the workshop rooms."""
    pts = floor_points(ctx.canvas, ctx.rect)
    if len(pts) == 0:
        return 0
    placed = 0
    for i in ctx.rng.choice(len(pts), size=ctx.count(params), replace=True):
        x, y = int(pts[i][0]), int(pts[i][1])
        placed += _shelf(ctx, x, y, ctx.pick(params, "len"), ctx.pick(params, "height"), "brick")
    return placed


# ----------------------------------------------------------------------- fungal


def _mushrooms(ctx: Ctx, params: dict) -> int:
    """A wooden mushroom: a 3-wide stalk on the floor and a dome cap on top."""
    canvas = ctx.canvas
    pts = floor_points(canvas, ctx.rect)
    if len(pts) == 0:
        return 0
    wood, placed = canvas.mats["wood"], 0
    for i in ctx.rng.choice(len(pts), size=ctx.count(params), replace=True):
        x, y = int(pts[i][0]), int(pts[i][1])
        stalk, cap_w = ctx.pick(params, "stalk"), ctx.pick(params, "cap_w")
        cap_h = max(3, cap_w // 4)
        top = y - stalk
        cx0, cx1 = x - cap_w // 2, x + cap_w // 2 + 1
        # stalk and cap volume (with a cell of air above the cap) must be free
        if not (
            free_box(canvas, x - 1, top, x + 2, y + 1)
            and free_box(canvas, cx0, top - cap_h - 1, cx1, top + 1)
        ):
            continue
        if not canvas.mats.kind_mask(canvas.grid[y + 1, x - 1 : x + 2], "static").all():
            continue

        def build(x=x, y=y, top=top, cx0=cx0, cx1=cx1, cap_w=cap_w, cap_h=cap_h):
            _fill(canvas, x - 1, top, x + 2, y + 1, wood)
            for cx in range(cx0, cx1):
                rel = (cx - x) / max(1.0, cap_w / 2)
                col_h = round(cap_h * np.sqrt(max(0.0, 1.0 - rel * rel)))
                _fill(canvas, cx, top - col_h, cx + 1, top + 1, wood)

        placed += ctx.guard((cx0, top - cap_h, cx1, y + 1), build)
    return placed


# -------------------------------------------------------------------------- oil


def _seams(ctx: Ctx, params: dict) -> int:
    """Oil seams: thin cracks in the ceiling rock, full of oil and sealed by one cell of rock.

    The seam starts just above a ceiling cell (that cell stays rock, the seal), wanders up
    for ``len`` cells and must be wrapped in rock everywhere (8-neighbourhood), so the
    oil is stable until somebody digs the seal open.
    """
    canvas = ctx.canvas
    g, mats = canvas.grid, canvas.mats
    pts = ceiling_points(canvas, ctx.rect)
    if len(pts) == 0:
        return 0
    soft = np.zeros(256, dtype=bool)
    soft[[mats["ground"], mats["rock"]]] = True
    placed = 0
    for i in ctx.rng.choice(len(pts), size=ctx.count(params), replace=True):
        x, y = int(pts[i][0]), int(pts[i][1]) - 1  # (x, y): the ceiling rock cell: the seal
        length = ctx.pick(params, "len")
        tilt = float(ctx.rng.normal(0.0, 0.45))
        pos = np.array([x + 0.5, y - 1.5])
        path = [pos.copy()]
        for _ in range(max(2, length // SEAM_STEP)):
            tilt = 0.7 * tilt + float(ctx.rng.normal(0.0, 0.35))
            pos = pos + SEAM_STEP * np.array([np.sin(tilt), -np.cos(tilt)])
            path.append(pos.copy())
        xs = [int(p[0]) for p in path]
        ys = [int(p[1]) for p in path]
        x0, x1, y0, y1 = min(xs) - 4, max(xs) + 5, min(ys) - 4, y + 3
        if not _inside(canvas, x0, y0, x1, y1):
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        mask = np.zeros(yy.shape, dtype=bool)
        for a, c in pairwise(path):
            stamp_segment(
                mask, xx + 0.5 - x0, yy + 0.5 - y0, a - [x0, y0], c - [x0, y0], SEAM_RADIUS, False
            )
        mask[y - y0 :, :] = False  # never reach the seal or the cave
        ring = _dilate(mask, 1)
        sub = g[y0:y1, x0:x1]
        if (
            mask.sum() < 8
            or not soft[sub[ring]].all()
            or canvas.protected[y0:y1, x0:x1][ring].any()
        ):
            continue
        sub[mask] = mats["oil"]
        placed += 1
    return placed


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """``mask`` grown by ``r`` cells in the 8-neighbourhood (the mask itself included)."""
    out = mask.copy()
    for _ in range(r):
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        grown[1:, 1:] |= out[:-1, :-1]
        grown[:-1, :-1] |= out[1:, 1:]
        grown[1:, :-1] |= out[:-1, 1:]
        grown[:-1, 1:] |= out[1:, :-1]
        out = grown
    return out


# ------------------------------------------------------------------ rooms (ruins)


def _rooms(ctx: Ctx, min_w: int = 0, min_h: int = 0):
    return [r for r in ctx.region.rooms if r.w >= min_w and r.h >= min_h]


def _pillars(ctx: Ctx, params: dict) -> int:
    """Brick pillars that stand on the floor or hang from the ceiling of the bigger rooms.

    ``gap`` cells stay open between a pillar and the opposite wall, so a pillar never cuts
    a room in two; with probability ``broken`` a pillar is a ragged stump.
    """
    canvas, brick = ctx.canvas, ctx.canvas.mats["brick"]
    gap, placed = params.get("gap", 10), 0
    for room in _rooms(ctx, params.get("min_room_w", 56), gap + 14):
        for _ in range(ctx.pick(params, "per_room")):
            pw = ctx.pick(params, "w")
            x = int(ctx.rng.integers(room.x0 + 14, max(room.x0 + 15, room.x1 - 14 - pw)))
            if not free_box(canvas, x, room.y0, x + pw, room.y1, powder_ok=True):
                continue
            length = room.h - gap
            broken = ctx.chance(params.get("broken", 0.0))
            if broken:
                length = int(ctx.rng.integers(room.h // 3, max(room.h // 3 + 1, length)))
            standing = ctx.chance(0.5)
            cuts = [int(ctx.rng.integers(0, 4)) if broken else 0 for _ in range(pw)]

            def build(x=x, length=length, standing=standing, cuts=cuts, room=room):
                for k, cx in enumerate(range(x, x + len(cuts))):
                    if standing:  # on the floor
                        _fill(canvas, cx, room.y1 - length + cuts[k], cx + 1, room.y1, brick)
                    else:  # hanging from the ceiling
                        _fill(canvas, cx, room.y0, cx + 1, room.y0 + length - cuts[k], brick)

            placed += ctx.guard((x, room.y0, x + pw, room.y1), build)
    return placed


def _broken_walls(ctx: Ctx, params: dict) -> int:
    """Low brick wall stumps with ragged tops standing in the big rooms."""
    canvas, brick = ctx.canvas, ctx.canvas.mats["brick"]
    placed = 0
    for room in _rooms(ctx, params.get("min_room_w", 50), 26):
        if not ctx.chance(params.get("chance", 0.6)):
            continue
        x = int(ctx.rng.integers(room.x0 + 14, max(room.x0 + 15, room.x1 - 17)))
        height = ctx.pick(params, "height")
        if not free_box(canvas, x, room.y1 - height - 3, x + 3, room.y1, powder_ok=True):
            continue
        heights = [height + int(ctx.rng.integers(-3, 4)) for _ in range(3)]

        def build(x=x, heights=heights, room=room):
            for cx, h in zip(range(x, x + 3), heights):
                _fill(canvas, cx, room.y1 - h, cx + 1, room.y1, brick)

        placed += ctx.guard((x, room.y1 - height - 3, x + 3, room.y1), build)
    return placed


def _breaches(ctx: Ctx, params: dict) -> int:
    """Ragged holes knocked through the walls between neighbouring rooms."""
    canvas = ctx.canvas
    pairs = _neighbours(ctx, 16)
    if not pairs:
        return 0
    placed = 0
    for _ in range(ctx.count(params)):
        a, b = pairs[int(ctx.rng.integers(0, len(pairs)))]
        lo, hi = max(a.y0, b.y0) + 6, min(a.y1, b.y1) - 6
        cy = int(ctx.rng.integers(lo, max(lo + 1, hi)))
        r = float(ctx.rng.uniform(4.5, 6.5))
        if near_fluid(canvas, a.x1 - 2, cy - 12, b.x0 + 2, cy + 12):
            continue  # a pool or a gas pocket lies against this wall
        canvas.capsule((a.x1 - 2, cy), (b.x0 + 2, cy + int(ctx.rng.integers(-3, 4))), r)
        for _ in range(3):  # a ragged rim
            px = float(ctx.rng.uniform(a.x1 - 1, b.x0 + 1))
            canvas.capsule(
                (px, cy + ctx.rng.uniform(-6, 6)), (px, cy), float(ctx.rng.uniform(2, 4))
            )
        placed += 1
    return placed


def _neighbours(ctx: Ctx, min_overlap: int) -> list[tuple[Room, Room]]:
    """Pairs ``(left, right)`` of rooms side by side behind a wall of at most 20 cells."""
    out = []
    for a in ctx.region.rooms:
        for b in ctx.region.rooms:
            overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
            if 0 < b.x0 - a.x1 <= 20 and overlap >= min_overlap:
                out.append((a, b))
    return out


def _collapses(ctx: Ctx, params: dict) -> int:
    """A wall between two rooms has fallen down: the gap is open from floor to ceiling.

    What is left are lumps of the wall standing on the higher floor and fragments hanging
    from the ceiling (a collapse that would cut a passage is undone).
    """
    canvas, brick = ctx.canvas, ctx.canvas.mats["brick"]
    pairs = _neighbours(ctx, 22)
    if not pairs:
        return 0
    placed = 0
    for _ in range(ctx.count(params)):
        a, b = pairs[int(ctx.rng.integers(0, len(pairs)))]
        lo, hi = max(a.y0, b.y0), min(a.y1, b.y1)
        x0, x1 = a.x1 - 1, b.x0 + 1
        removable = not canvas.protected[lo:hi, x0:x1].any()
        if hi - lo < 22 or not removable or near_fluid(canvas, x0, lo, x1, hi):
            continue
        lumps = [  # (from_floor, start, width, length)
            (
                from_floor,
                int(ctx.rng.integers(x0, max(x0 + 1, x1 - 6))),
                int(ctx.rng.integers(3, 7)),
                ctx.pick(params, key),
            )
            for key, from_floor in (("stump", True), ("hang", False))
            for _ in range(int(ctx.rng.integers(0, 3)))
        ]
        jitter = [int(ctx.rng.integers(-2, 3)) for _ in range(len(lumps) * 6)]

        def build(lo=lo, hi=hi, x0=x0, x1=x1, lumps=lumps, jitter=jitter):
            canvas.grid[lo:hi, x0:x1] = canvas.mats.air
            for k, (from_floor, start, width, length) in enumerate(lumps):
                for j, cx in enumerate(range(start, min(x1, start + width))):
                    n = max(1, length + jitter[k * 6 + j])
                    rows = slice(hi - n, hi) if from_floor else slice(lo, lo + n)
                    canvas.grid[rows, cx] = brick

        placed += ctx.guard((x0, lo, x1, hi), build)
    return placed


def _rubble(ctx: Ctx, params: dict) -> int:
    """Heaps of fallen brick and rock on the floors of big rooms."""
    canvas, mats = ctx.canvas, ctx.canvas.mats
    placed = 0
    for room in _rooms(ctx, 40, 24):
        for _ in range(ctx.pick(params, "per_room")):
            r = ctx.pick(params, "radius")
            x = int(ctx.rng.integers(room.x0 + r + 8, max(room.x0 + r + 9, room.x1 - r - 8)))
            y = room.y1 - 1
            if not free_box(canvas, x - r - 8, y - r - 10, x + r + 9, y + 1, powder_ok=True):
                continue
            if not mats.kind_mask(canvas.grid[y + 1, x - r : x + r + 1], "static").all():
                continue
            material = mats["brick"] if ctx.chance(0.6) else mats["rock"]

            def build(x=x, y=y, r=r, material=material):
                for dx in range(-r, r + 1):
                    h = round(0.7 * r * np.sqrt(1.0 - (dx / (r + 0.5)) ** 2))
                    _fill(canvas, x + dx, y - h + 1, x + dx + 1, y + 1, material)

            placed += ctx.guard((x - r, y - r, x + r + 1, y + 1), build)
    return placed


# --------------------------------------------------------------------- workshop


def _pipes(ctx: Ctx, params: dict) -> int:
    """Brick pipes: a bar under the ceiling of a room and a column along one of its walls."""
    canvas, brick = ctx.canvas, ctx.canvas.mats["brick"]
    doors, placed = ctx.region.doors, 0
    for room in _rooms(ctx, 40, 30):
        if (
            ctx.chance(params.get("ceiling", 0.7))
            and not _open_side(canvas, room, "top")
            and not _hits(doors, room.x0 - 2, room.y0 - 2, room.x1 + 2, room.y0 + 9)
        ):
            thick = ctx.pick(params, "thick")

            def bar(room=room, thick=thick):
                _fill_air_only(canvas, room.x0 - 1, room.y0, room.x1 + 1, room.y0 + thick, brick)
                for jx in (room.x0, room.x1 - 6):  # flanges
                    _fill_air_only(canvas, jx, room.y0 + thick, jx + 6, room.y0 + thick + 2, brick)

            placed += ctx.guard((room.x0, room.y0, room.x1, room.y0 + thick + 2), bar)
        if ctx.chance(params.get("wall", 0.5)):
            left = ctx.chance(0.5)
            x0 = room.x0 if left else room.x1 - 4
            side = "left" if left else "right"
            if not _open_side(canvas, room, side) and not _hits(
                doors, x0 - 3, room.y0 - 2, x0 + 7, room.y1 + 2
            ):

                def column(x0=x0, room=room):
                    _fill_air_only(canvas, x0, room.y0, x0 + 4, room.y1, brick)

                placed += ctx.guard((x0, room.y0, x0 + 4, room.y1), column)
    return placed


def _channels(ctx: Ctx, params: dict) -> int:
    """A brick-lined trench in a room floor, filled flush with oil or water."""
    canvas, mats, g = ctx.canvas, ctx.canvas.mats, ctx.canvas.grid
    placed = 0
    for room in _rooms(ctx, 44, 24):
        if not ctx.chance(params.get("per_room", 0.6)):
            continue
        length, depth = ctx.pick(params, "len"), params.get("depth", 3)
        x = int(ctx.rng.integers(room.x0 + 6, max(room.x0 + 7, room.x1 - 6 - length)))
        y = room.y1
        sub = g[y : y + depth + 2, x - 2 : x + length + 2]
        solid = mats.kind_mask(sub, "static").all()
        if (
            x + length > room.x1 - 4
            or not solid
            or canvas.protected[y : y + depth + 2, x - 2 : x + length + 2].any()
        ):
            continue
        if not (g[y - 1, x - 1 : x + length + 1] == mats.air).all():
            continue
        _fill(canvas, x - 1, y, x + length + 1, y + depth + 1, mats["brick"])
        liquid = mats["oil"] if ctx.chance(params.get("oil_prob", 0.5)) else mats["water"]
        _fill(canvas, x, y, x + length, y + depth, liquid)
        placed += 1
    return placed


def _stand_row(canvas: Canvas, x: int, y_hint: int) -> int | None:
    """Row of the standing cell above the floor in column ``x`` (scanning down from ``y_hint``)."""
    g, mats = canvas.grid, canvas.mats
    for y in range(y_hint, min(canvas.h - 2, y_hint + 12)):
        if (
            g[y, x] == mats.air
            and mats.kind_at_least(g[y + 1, x], "powder")
            and g[y + 1, x] != mats.air
        ):
            return y
    return None


def _barrel_rows(ctx: Ctx, params: dict) -> int:
    """Rows of same-kind barrels along the floors of the rooms."""
    canvas, mats = ctx.canvas, ctx.canvas.mats
    weights = params["weights"]
    keys = sorted(weights)
    spacing, placed = params.get("spacing", 9), 0
    for room in _rooms(ctx, 40, 24):
        for _ in range(ctx.pick(params, "per_room")):
            kind = keys[pick_weighted(float(ctx.rng.random()), [weights[k] for k in keys])]
            n = ctx.pick(params, "count")
            span = (n - 1) * spacing
            if room.w < span + 24:
                continue
            x0 = int(ctx.rng.integers(room.x0 + 8, room.x1 - 8 - span + 1))
            row = []
            for k in range(n):
                x = x0 + k * spacing
                y = _stand_row(canvas, x, room.y1 - 3)
                free = (
                    y is not None
                    and y >= BARREL_CLEARANCE
                    and (canvas.grid[y - BARREL_CLEARANCE : y + 1, x] == mats.air).all()
                )
                if free and not canvas.protected[y, x]:
                    row.append((x, y))
            for x, y in row:
                ctx.markers.append({"type": "item", "x": x, "y": y, "item": kind})
            placed += len(row)
    return placed


# ---------------------------------------------------------------------- driver

# fixed order: carving first, then solids, then markers
DECOR: tuple[tuple[str, Callable[[Ctx, dict], int]], ...] = (
    ("channels", _channels),
    ("breaches", _breaches),
    ("collapses", _collapses),
    ("seams", _seams),
    ("pillars", _pillars),
    ("broken_walls", _broken_walls),
    ("rubble", _rubble),
    ("pipes", _pipes),
    ("catwalks", _catwalks),
    ("timber", _timber),
    ("frames", _frames),
    ("platforms", _platforms),
    ("mushrooms", _mushrooms),
    ("barrel_rows", _barrel_rows),
)


def _fit_labels(canvas: Canvas, window: np.ndarray) -> np.ndarray:
    """Labels of the connected areas where the player's box fits (static cells block).

    Outside the window counts as open, so the edge of the window does not cut a passage.
    """
    open_ = ~canvas.mats.kind_mask(window, "static")
    return label(binary_erosion(open_, structure=PLAYER_BOX, border_value=1))[0]


def cuts_passage(before: np.ndarray, after: np.ndarray) -> bool:
    """True if a connected player-fit area of ``before`` falls apart in ``after``.

    Cells that stopped being fit (a structure stands there) are ignored; what is left of
    each earlier area must lie in one later area, apart from ``MIN_SPLIT_CELLS`` strays.
    """
    still_fit = after > 0
    for k in range(1, int(before.max()) + 1):
        part = after[(before == k) & still_fit]
        if part.size < 2 * MIN_SPLIT_CELLS:
            continue
        counts = np.bincount(part)
        counts[0] = 0
        if part.size - int(counts.max()) > MIN_SPLIT_CELLS:
            return True
    return False


def place_structures(
    canvas: Canvas, biome: Biome, rect: Rect, rng: np.random.Generator, region: RegionInfo
) -> tuple[dict[str, int], list[dict]]:
    """Run the biome's ``decor``; returns the number placed of each and the item markers."""
    ctx = Ctx(canvas, rect, rng, region, [])
    counts: dict[str, int] = {}
    for name, fn in DECOR:
        params = biome.decor.get(name)
        if params is not None:
            counts[name] = fn(ctx, params)
    return counts, ctx.markers
