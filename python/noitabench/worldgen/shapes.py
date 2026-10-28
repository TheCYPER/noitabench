"""Cave shape variety on top of the tiled caves (cp1-feedback section 2, row 2).

The Wang tiles give worm-like tunnels of similar width. This module varies them:
tunnels swell and narrow, and large halls, vertical shafts, long horizontal passages,
alcoves under rock overhangs, rock ledges and hair-thin cracks are added. Everything is
attached to an existing cave cell, so connectivity can only improve; ledges are only
placed where plenty of room is left around them. Coordinates are region-local.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
from scipy.ndimage import distance_transform_edt

from .carve import stamp_segment
from .config import Rate, ShapeStyle
from .noise import rank_normalize, value_noise

LEDGE_CLEAR_ABOVE = 9  # free rows above a ledge
LEDGE_CLEAR_BELOW = 9  # free rows below a ledge
LEDGE_CLEAR_BESIDE = 14  # free columns left beside a ledge (the player must pass)
CRACK_RADIUS = 1.0  # cracks are two cells wide: the player (4 wide) cannot enter
MAX_TRIES = 25


def shape_cave(cave: np.ndarray, st: ShapeStyle, ring: int, rng: np.random.Generator) -> np.ndarray:
    """A varied copy of the tiled cave mask (True = open)."""
    h, w = cave.shape
    out = widen(cave, st.widen_max, st.widen_scale, rng)
    inner = (ring + 2, ring + 2, w - ring - 2, h - ring - 2)
    units = h * w / 10_000.0
    yy, xx = np.mgrid[0:h, 0:w]
    sh = _Shaper(out, inner, (xx + 0.5, yy + 0.5), rng)
    for name, fn in (
        ("halls", sh.hall),
        ("shafts", sh.shaft),
        ("passages", sh.passage),
        ("alcoves", sh.alcove),
        ("cracks", sh.crack),
    ):
        rate: Rate = getattr(st, name)
        for _ in range(int(rng.poisson(rate.per_10k * units))):
            fn(rate)
    sh.refresh()  # ledges look for the roomy places the halls and passages made
    for _ in range(int(rng.poisson(st.ledges.per_10k * units))):
        sh.ledge(st.ledges)
    return out


def widen(cave: np.ndarray, widen_max: int, scale: float, rng: np.random.Generator) -> np.ndarray:
    """Caves swell by up to ``widen_max`` cells where a noise of size ``scale`` is high."""
    if widen_max <= 0:
        return cave.copy()
    dist = distance_transform_edt(~cave)
    rank = rank_normalize(value_noise(cave.shape, scale, rng, octaves=2).ravel())
    rank = rank.reshape(cave.shape)
    grow = np.rint(widen_max * np.clip((rank - 0.45) / 0.55, 0.0, 1.0) ** 1.5)
    return cave | (dist <= grow)


def _clip_to(mask: np.ndarray, inner: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = inner
    keep = np.zeros_like(mask)
    keep[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    return keep


def _wobbly(
    start: tuple[int, int], end: tuple[int, int], wobble: float, rng: np.random.Generator
) -> list[np.ndarray]:
    """Three joints from ``start`` to ``end`` with a sideways wobble of up to ``wobble`` cells."""
    a, b = np.array(start, dtype=float), np.array(end, dtype=float)
    d = b - a
    perp = np.array([-d[1], d[0]]) / (np.hypot(*d) or 1.0)
    mid1 = a + d / 3 + perp * rng.uniform(-wobble, wobble)
    mid2 = a + 2 * d / 3 + perp * rng.uniform(-wobble, wobble)
    return [a, mid1, mid2, b]


@dataclass
class _Shaper:
    """The cave mask being shaped, the allowed area and the open cells shapes attach to."""

    cave: np.ndarray
    inner: tuple[int, int, int, int]
    grid: tuple[np.ndarray, np.ndarray]
    rng: np.random.Generator
    cells: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Take the open cells of the cave as it is now."""
        x0, y0, x1, y1 = self.inner
        self.cells = np.argwhere(self.cave[y0:y1, x0:x1]) + [y0, x0]  # (y, x) rows

    def pick(self) -> tuple[int, int] | None:
        """A random open cell (of the cave as it was before shaping) as ``(x, y)``."""
        if len(self.cells) == 0:
            return None
        y, x = self.cells[int(self.rng.integers(0, len(self.cells)))]
        return int(x), int(y)

    def stamp(self, pts: list[np.ndarray], radius: float) -> None:
        xc, yc = self.grid
        mask = np.zeros_like(self.cave)
        for a, c in pairwise(pts):
            stamp_segment(mask, xc, yc, a, c, radius, False)
        self.cave |= _clip_to(mask, self.inner)

    def hall(self, rate: Rate) -> None:
        """A big chamber with a flat-ish floor (a super-ellipse) centred on an open cell."""
        c = self.pick()
        if c is None:
            return
        rx = int(self.rng.integers(rate.a[0], rate.a[1] + 1)) / 2
        ry = int(self.rng.integers(rate.b[0], rate.b[1] + 1)) / 2
        p = float(self.rng.uniform(2.2, 3.2))
        xc, yc = self.grid
        mask = (np.abs((xc - c[0]) / rx) ** p + np.abs((yc - c[1]) / ry) ** p) <= 1.0
        self.cave |= _clip_to(mask, self.inner)

    def shaft(self, rate: Rate) -> None:
        c = self.pick()
        if c is None:
            return
        width = int(self.rng.integers(rate.a[0], rate.a[1] + 1))
        length = int(self.rng.integers(rate.b[0], rate.b[1] + 1))
        end = (c[0], c[1] + (length if self.rng.random() < 0.5 else -length))
        self.stamp(_wobbly(c, end, 6.0, self.rng), width / 2)

    def passage(self, rate: Rate) -> None:
        c = self.pick()
        if c is None:
            return
        width = int(self.rng.integers(rate.a[0], rate.a[1] + 1))
        length = int(self.rng.integers(rate.b[0], rate.b[1] + 1))
        end = (c[0] + (length if self.rng.random() < 0.5 else -length), c[1])
        self.stamp(_wobbly(c, end, 5.0, self.rng), width / 2)

    def alcove(self, rate: Rate) -> None:
        """A recess cut sideways into a wall, under the rock that stays above it: an overhang."""
        c = self.pick()
        if c is None:
            return
        x, y = c
        side = 1 if self.rng.random() < 0.5 else -1
        wall = x
        while 0 < wall < self.cave.shape[1] - 1 and self.cave[y, wall]:
            wall += side
            if abs(wall - x) > 40:
                return
        height = int(self.rng.integers(rate.a[0], rate.a[1] + 1))
        depth = int(self.rng.integers(rate.b[0], rate.b[1] + 1))
        xa, xb = sorted((wall, wall + side * depth))
        ya = y - height // 2
        mask = np.zeros_like(self.cave)
        mask[ya : ya + height, xa:xb] = True
        self.cave |= _clip_to(mask, self.inner)

    def crack(self, rate: Rate) -> None:
        """A thin jagged crack from a cave wall into the rock (decoration, not passable)."""
        c = self.pick()
        if c is None:
            return
        ang = float(self.rng.uniform(0, 2 * np.pi))
        step = np.array([np.cos(ang), np.sin(ang)])
        pos = np.array(c, dtype=float)
        # walk out of the cave first, then into the rock for ``length`` cells
        x0, y0, x1, y1 = self.inner
        while self.cave[int(pos[1]), int(pos[0])]:
            pos = pos + step
            if not (x0 < pos[0] < x1 and y0 < pos[1] < y1):
                return
        length = int(self.rng.integers(rate.b[0], rate.b[1] + 1))
        pts = [pos - step]
        for _ in range(max(2, length // 4)):
            ang += float(self.rng.normal(0.0, 0.5))
            pos = pos + 4 * np.array([np.cos(ang), np.sin(ang)])
            pts.append(pos.copy())
        self.stamp(pts, CRACK_RADIUS)

    def ledge(self, rate: Rate) -> None:
        """A rock slab sticking out of a wall into a roomy chamber (the one subtractive shape).

        Only placed where ``LEDGE_CLEAR_*`` cells stay free above, below and beside it.
        """
        x0, y0, x1, y1 = self.inner
        cave = self.cave
        for _ in range(MAX_TRIES):
            c = self.pick()
            if c is None:
                return
            x, y = c
            side = (
                1 if self.rng.random() < 0.5 else -1
            )  # the ledge grows away from the wall at x - side
            length = int(self.rng.integers(rate.a[0], rate.a[1] + 1))
            thick = int(self.rng.integers(rate.b[0], rate.b[1] + 1))
            far = x + side * (length + LEDGE_CLEAR_BESIDE)
            xa, xb = sorted((x, far))
            if not (
                x0 <= xa
                and xb < x1
                and y0 + LEDGE_CLEAR_ABOVE <= y < y1 - thick - LEDGE_CLEAR_BELOW
            ):
                continue
            attached = not cave[y : y + thick, x - side].any()
            room = cave[y - LEDGE_CLEAR_ABOVE : y + thick + LEDGE_CLEAR_BELOW, xa : xb + 1].all()
            if attached and room:
                ea, eb = sorted((x, x + side * (length - 1)))
                cave[y : y + thick, ea : eb + 1] = False
                return
