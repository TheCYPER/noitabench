"""Herringbone Wang tiles (Sean Barrett's method), generated from a biome style.

Geometry
--------
With unit ``s`` (the tile's short side) the plane is covered by horizontal tiles
``2s x s`` and vertical tiles ``s x 2s`` in a herringbone pattern: in unit row
``v`` a horizontal tile starts at columns ``u = v (mod 4)`` and a vertical tile
(anchored at its top cell) at ``u = v + 3 (mod 4)``.

Edges
-----
Every tile has six edge segments of length ``s``. An edge segment has a *colour*
(0 = closed wall, 1..4 = openings of different width and offset). A segment is
shared by exactly two tiles and both see the same colour, so the cross-section of
the cave along the seam is identical on both sides. A tile's interior is a pure
function of ``(kind, six edge colours, variant)``, so the tile set is complete:
for any assignment of colours to the segments there is a tile. Choosing the
colours of unplaced segments at random is exactly Barrett's scan-line algorithm,
without dead ends.

Near each edge a strip ``band`` pixels deep carries the opening cross-section;
that strip is what neighbouring tiles agree on. Openings keep ``margin`` pixels
away from the segment ends, so strips never collide in tile corners.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from .carve import roughen, stamp_segment, tunnel_points
from .config import TileStyle
from .rng import mix64, name_key, pick_weighted, unit

KIND_H = 0  # 2s x s
KIND_V = 1  # s x 2s
TB, LR = 0, 1  # segment orientation: horizontal line (top/bottom edge) or vertical line
N_COLORS = 5  # 0 closed, 1 narrow centre, 2 wide centre, 3 left/upper, 4 right/lower


@dataclass(frozen=True)
class Slot:
    name: str
    side: str  # top | bottom | left | right
    offset: int  # in units of s along the side
    orient: int


SLOTS: dict[int, tuple[Slot, ...]] = {
    KIND_H: (
        Slot("top0", "top", 0, TB),
        Slot("top1", "top", 1, TB),
        Slot("bot0", "bottom", 0, TB),
        Slot("bot1", "bottom", 1, TB),
        Slot("left", "left", 0, LR),
        Slot("right", "right", 0, LR),
    ),
    KIND_V: (
        Slot("top", "top", 0, TB),
        Slot("bot", "bottom", 0, TB),
        Slot("left0", "left", 0, LR),
        Slot("left1", "left", 1, LR),
        Slot("right0", "right", 0, LR),
        Slot("right1", "right", 1, LR),
    ),
}

Seg = tuple[int, int, int]  # (orientation, x unit, y unit)


def segment_ids(kind: int, u: int, v: int) -> tuple[Seg, ...]:
    """Global ids of the six edge segments of the tile anchored at unit ``(u, v)``.

    ``(TB, x, y)`` is the horizontal unit segment ``[x, x+1) x {y}``;
    ``(LR, x, y)`` is the vertical unit segment ``{x} x [y, y+1)``.
    """
    if kind == KIND_H:
        return (
            (TB, u, v),
            (TB, u + 1, v),
            (TB, u, v + 1),
            (TB, u + 1, v + 1),
            (LR, u, v),
            (LR, u + 2, v),
        )
    return (
        (TB, u, v),
        (TB, u, v + 2),
        (LR, u, v),
        (LR, u, v + 1),
        (LR, u + 1, v),
        (LR, u + 1, v + 1),
    )


def tile_size_units(kind: int) -> tuple[int, int]:
    return (2, 1) if kind == KIND_H else (1, 2)


def layout(u0: int, u1: int, v0: int, v1: int) -> Iterator[tuple[int, int, int]]:
    """Tiles ``(kind, u, v)`` of the herringbone tiling that intersect the unit window."""
    for v in range(v0 - 1, v1):
        for u in range(u0 - 1, u1 + 1):
            if (u - v) % 4 == 0:
                if v0 <= v < v1 and u + 2 > u0 and u < u1:
                    yield KIND_H, u, v
            elif (u - v - 3) % 4 == 0 and u0 <= u < u1 and v + 2 > v0 and v < v1:
                yield KIND_V, u, v


# ------------------------------------------------------------------ edge colours


def opening_pattern(style: TileStyle, color: int) -> np.ndarray:
    """Cross-section (bool, length ``s``) of an edge colour: True = open cell."""
    s, m = style.short_side, style.margin
    usable = s - 2 * m
    pat = np.zeros(s, dtype=bool)
    if color == 0:
        return pat
    wide = min(style.tunnel_max, usable)
    narrow = min(style.tunnel_min, usable)
    mid = min((style.tunnel_min + style.tunnel_max) // 2, usable)
    if color == 1:
        a = (s - narrow) // 2
        pat[a : a + narrow] = True
    elif color == 2:
        a = (s - wide) // 2
        pat[a : a + wide] = True
    elif color == 3:
        pat[m : m + mid] = True
    else:
        pat[s - m - mid : s - m] = True
    return pat


def edge_color(style: TileStyle, edge_seed: int, seg: Seg) -> int:
    weights = style.weights_tb if seg[0] == TB else style.weights_lr
    return pick_weighted(unit(edge_seed, seg[0], seg[1], seg[2]), list(weights))


# ----------------------------------------------------------------------- tile set


class TileSet:
    """The (lazily built, complete) tile set of one biome.

    ``seed`` fixes the "art": the same biome always has the same templates, only
    the placement (which edge colours meet where) depends on the world seed.
    """

    def __init__(self, style: TileStyle, seed: int):
        self.style = style
        self.seed = seed
        self.patterns = [opening_pattern(style, c) for c in range(N_COLORS)]
        self._tiles: dict[tuple, np.ndarray] = {}
        self._bands: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}

    # tile geometry ------------------------------------------------------
    def size(self, kind: int) -> tuple[int, int]:
        """Width and height in pixels."""
        s = self.style.short_side
        return (2 * s, s) if kind == KIND_H else (s, 2 * s)

    def band(self, kind: int, edges: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
        """``(band_mask, band_open)``: the edge strips and what they contain."""
        key = (kind, edges)
        hit = self._bands.get(key)
        if hit is not None:
            return hit
        s, b = self.style.short_side, self.style.band
        w, h = self.size(kind)
        mask = np.zeros((h, w), dtype=bool)
        opened = np.zeros((h, w), dtype=bool)
        for slot, color in zip(SLOTS[kind], edges):
            pat = self.patterns[color]
            o = slot.offset * s
            if slot.side == "top":
                sl = (slice(0, b), slice(o, o + s))
                val = pat[None, :]
            elif slot.side == "bottom":
                sl = (slice(h - b, h), slice(o, o + s))
                val = pat[None, :]
            elif slot.side == "left":
                sl = (slice(o, o + s), slice(0, b))
                val = pat[:, None]
            else:
                sl = (slice(o, o + s), slice(w - b, w))
                val = pat[:, None]
            mask[sl] = True
            opened[sl] |= val
        self._bands[key] = (mask, opened)
        return mask, opened

    def strip(self, tile: np.ndarray, kind: int, slot_index: int) -> np.ndarray:
        """The band strip of ``tile`` at one slot, as an (s,) cross-section."""
        slot = SLOTS[kind][slot_index]
        s, b = self.style.short_side, self.style.band
        w, h = self.size(kind)
        o = slot.offset * s
        if slot.side == "top":
            return tile[0:b, o : o + s].copy()
        if slot.side == "bottom":
            return tile[h - b : h, o : o + s].copy()
        if slot.side == "left":
            return tile[o : o + s, 0:b].T.copy()
        return tile[o : o + s, w - b : w].T.copy()

    # tile content -------------------------------------------------------
    def tile(self, kind: int, edges: tuple[int, ...], variant: int) -> np.ndarray:
        key = (kind, edges, variant)
        hit = self._tiles.get(key)
        if hit is None:
            hit = self._carve(kind, edges, variant)
            hit.flags.writeable = False
            self._tiles[key] = hit
        return hit

    def _carve(self, kind: int, edges: tuple[int, ...], variant: int) -> np.ndarray:
        st = self.style
        w, h = self.size(kind)
        rng = np.random.Generator(
            np.random.PCG64(mix64(self.seed, name_key("tile"), kind, variant, *edges))
        )
        band_mask, band_open = self.band(kind, edges)
        yy, xx = np.mgrid[0:h, 0:w]
        xc, yc = xx + 0.5, yy + 0.5
        cave = np.zeros((h, w), dtype=bool)
        hub = np.array([w * (0.3 + 0.4 * rng.random()), h * (0.3 + 0.4 * rng.random())])
        rect = st.shape == "rect"

        anchors = self._anchors(kind, edges)
        for p, side, radius in anchors:
            for a, c in tunnel_points(p, hub, side, st.wobble, rng, rect):
                stamp_segment(cave, xc, yc, a, c, radius, rect)
        if anchors or rng.random() < st.isolated_prob:
            if anchors and not rect and rng.random() < st.cavern_prob:
                self._cavern(cave, xc, yc, hub, rng, w, h)
            elif rng.random() < st.chamber_prob or not anchors:
                self._chamber(cave, xc, yc, hub, rng, w, h)
            if rng.random() < st.nook_prob:
                self._nook(cave, xc, yc, hub, rng, w, h)
        if st.smooth_iters > 0 and not rect:
            cave = roughen(cave, rng, st.roughness, st.smooth_iters)
        cave[band_mask] = band_open[band_mask]
        return cave

    def _anchors(self, kind: int, edges: tuple[int, ...]) -> list[tuple[np.ndarray, str, float]]:
        st = self.style
        s, b = st.short_side, st.band
        w, h = self.size(kind)
        out = []
        for slot, color in zip(SLOTS[kind], edges):
            if color == 0:
                continue
            xs = np.flatnonzero(self.patterns[color])
            c = (xs[0] + xs[-1] + 1) / 2 + slot.offset * s
            half = len(xs) / 2
            if slot.side == "top":
                p = (c, b + 0.5)
            elif slot.side == "bottom":
                p = (c, h - b - 0.5)
            elif slot.side == "left":
                p = (b + 0.5, c)
            else:
                p = (w - b - 0.5, c)
            out.append((np.array(p), slot.side, half))
        return out

    def _chamber(self, cave, xc, yc, hub, rng, w, h) -> None:
        st = self.style
        b = st.band
        r = rng.uniform(st.chamber_min, st.chamber_max)
        k = st.chamber_aspect**0.5
        room = b + 2
        avail_x = max(2.0, min(hub[0] - room, w - room - hub[0]))
        avail_y = max(2.0, min(hub[1] - room, h - room - hub[1]))
        rx, ry = min(r * k, avail_x), min(r / k, avail_y)
        if st.shape == "rect":
            cave |= (np.abs(xc - hub[0]) <= rx) & (np.abs(yc - hub[1]) <= ry)
        else:
            cave |= ((xc - hub[0]) / rx) ** 2 + ((yc - hub[1]) / ry) ** 2 <= 1.0

    def _cavern(self, cave, xc, yc, hub, rng, w, h) -> None:
        """A large blobby cavern: a few overlapping ellipses filling most of the tile."""
        room = self.style.band + 2
        for _ in range(int(rng.integers(2, 5))):
            cx = hub[0] + rng.uniform(-1, 1) * w * 0.22
            cy = hub[1] + rng.uniform(-1, 1) * h * 0.18
            rx = rng.uniform(0.55, 1.0) * max(3.0, min(cx - room, w - room - cx))
            ry = rng.uniform(0.55, 1.0) * max(3.0, min(cy - room, h - room - cy))
            cave |= ((xc - cx) / rx) ** 2 + ((yc - cy) / ry) ** 2 <= 1.0

    def _nook(self, cave, xc, yc, hub, rng, w, h) -> None:
        st = self.style
        b = st.band
        ang = rng.uniform(0, 2 * np.pi)
        length = rng.uniform(8, 16)
        end = hub + length * np.array([np.cos(ang), np.sin(ang)])
        room = b + 3
        end = np.array([np.clip(end[0], room, w - room), np.clip(end[1], room, h - room)])
        if st.shape == "rect":
            horizontal = abs(end[0] - hub[0]) >= abs(end[1] - hub[1])
            end = np.array([end[0], hub[1]]) if horizontal else np.array([hub[0], end[1]])
        stamp_segment(cave, xc, yc, hub, end, st.tunnel_min / 2 * 0.9, st.shape == "rect")


# -------------------------------------------------------------------- tiling


@dataclass(frozen=True)
class Placement:
    kind: int
    u: int
    v: int
    x: int  # world pixel of the tile's top-left corner
    y: int
    w: int
    h: int
    edges: tuple[int, ...]
    variant: int


def tile_region(
    tileset: TileSet,
    edge_seed: int,
    rect: tuple[int, int, int, int],
    phase: tuple[int, int],
) -> tuple[np.ndarray, list[Placement]]:
    """Tile the pixel rectangle ``rect`` (x0, y0, x1, y1); True = cave (open) cell.

    ``phase`` shifts the herringbone lattice in pixels (use ``(0..4s, 0..4s)``).
    """
    st = tileset.style
    s = st.short_side
    x0, y0, x1, y1 = rect
    ox, oy = phase
    out = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    u0, u1 = (x0 - ox) // s, -((ox - x1) // s)
    v0, v1 = (y0 - oy) // s, -((oy - y1) // s)
    placements: list[Placement] = []
    for kind, u, v in layout(u0, u1, v0, v1):
        edges = tuple(edge_color(st, edge_seed, seg) for seg in segment_ids(kind, u, v))
        variant = mix64(edge_seed, name_key("variant"), kind, u, v) % st.variants
        tile = tileset.tile(kind, edges, variant)
        tw, th = tileset.size(kind)
        px, py = ox + u * s, oy + v * s
        placements.append(Placement(kind, u, v, px, py, tw, th, edges, variant))
        cx0, cy0 = max(px, x0), max(py, y0)
        cx1, cy1 = min(px + tw, x1), min(py + th, y1)
        if cx0 < cx1 and cy0 < cy1:
            out[cy0 - y0 : cy1 - y0, cx0 - x0 : cx1 - x0] = tile[
                cy0 - py : cy1 - py, cx0 - px : cx1 - px
            ]
    return out, placements


def seam_errors(
    region: np.ndarray,
    rect: tuple[int, int, int, int],
    placements: list[Placement],
    style: TileStyle,
) -> int:
    """Count seam cells where the two sides of a shared segment disagree.

    Only segments whose two tiles lie fully inside ``rect`` are examined. Cells on
    both sides of the seam must be either both open or both closed.
    """
    s = style.short_side
    x0, y0, x1, y1 = rect
    inside = {
        (p.kind, p.u, p.v): p
        for p in placements
        if p.x >= x0 and p.y >= y0 and p.x + p.w <= x1 and p.y + p.h <= y1
    }
    owners: dict[Seg, list[tuple[Placement, int]]] = {}
    for p in inside.values():
        for i, seg in enumerate(segment_ids(p.kind, p.u, p.v)):
            owners.setdefault(seg, []).append((p, i))
    errors = 0
    for seg, own in owners.items():
        if len(own) != 2:
            continue
        orient, ux, uy = seg
        ref = own[0][0]
        base_x = ref.x - ref.u * s  # lattice origin in pixels
        base_y = ref.y - ref.v * s
        if orient == TB:
            xs = np.arange(base_x + ux * s, base_x + (ux + 1) * s)
            y = base_y + uy * s
            a = region[y - 1 - y0, xs - x0]
            c = region[y - y0, xs - x0]
        else:
            ys = np.arange(base_y + uy * s, base_y + (uy + 1) * s)
            x = base_x + ux * s
            a = region[ys - y0, x - 1 - x0]
            c = region[ys - y0, x - x0]
        errors += int(np.count_nonzero(a != c))
    return errors
