"""Biome regions: build the cave layer, shape it and fill the solid cells with strata.

The cave layer is either a herringbone Wang tiling (smoothed, then varied by ``shapes.py``)
or a room layout of built structures (``rooms.py``). The solid cells are filled in large
strata of one dominant material with dithered transitions; minerals are thin elongated
veins on top (cp1-feedback section 2, rows 1-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter

from .canvas import Canvas, Rect
from .carve import stamp_segment
from .config import Biome, BiomeMap, FillStyle, Materials, TileStyle, VeinStyle
from .noise import rank_normalize, value_noise
from .rng import mix64, name_key
from .rooms import Room, layout_rooms
from .shapes import shape_cave
from .tiles import Placement, TileSet, tile_region

_TILESETS: dict[tuple[str, TileStyle], TileSet] = {}
VEIN_STEP = 6  # cells between the joints of a vein
EDGE_PATCH = 7.0  # size of the patches of the cave-edge lining


@dataclass
class RegionInfo:
    """What the later build steps need to know about a built region (world coordinates)."""

    cave: np.ndarray  # region-local mask of the caves as built (before bands and gates)
    placements: list[Placement] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    doors: list[Rect] = field(default_factory=list)


def tileset_for(biome: Biome) -> TileSet:
    """The biome's tile templates (fixed per biome, independent of the world seed)."""
    assert biome.tile is not None, f"{biome.key} has no tile layout"
    key = (biome.key, biome.tile)
    ts = _TILESETS.get(key)
    if ts is None:
        ts = TileSet(biome.tile, mix64(name_key("tileset"), name_key(biome.key)))
        _TILESETS[key] = ts
    return ts


def smooth_cave(cave: np.ndarray, style: TileStyle, rng: np.random.Generator) -> np.ndarray:
    """Blur the tile layer to round corners and hide the tile seams (organic styles only)."""
    if style.smooth_sigma <= 0:
        return cave
    blurred = gaussian_filter(cave.astype(np.float32), style.smooth_sigma)
    noise = value_noise(cave.shape, 9.0, rng, octaves=2)
    return blurred > 0.5 + (noise - 0.5) * style.smooth_noise


# ---------------------------------------------------------------------------- strata


def _vein_mask(
    solid: np.ndarray, dist: np.ndarray, vein: VeinStyle, rng: np.random.Generator
) -> np.ndarray:
    """Cells of thin, mostly horizontal, tapering veins that keep ``buried`` cells from caves."""
    h, w = solid.shape
    mask = np.zeros(solid.shape, dtype=bool)
    n = int(rng.poisson(vein.per_10k * float(solid.sum()) / 10_000.0))
    starts = np.argwhere(solid & (dist >= max(1, vein.buried)))
    if n == 0 or len(starts) == 0:
        return mask
    yy, xx = np.mgrid[0:h, 0:w]
    xc, yc = xx + 0.5, yy + 0.5
    for _ in range(n):
        y, x = starts[int(rng.integers(0, len(starts)))]
        length = int(rng.integers(vein.length[0], vein.length[1] + 1))
        thick = float(rng.uniform(*vein.thickness))
        side = 1.0 if rng.random() < 0.5 else -1.0  # veins run left or right ...
        tilt = float(rng.normal(0.0, 0.3))  # ... and wander around the horizontal
        pos = np.array([x, y], dtype=float)
        steps = max(2, length // VEIN_STEP)
        for k in range(steps):
            tilt = 0.8 * tilt + float(rng.normal(0.0, 0.3))
            nxt = pos + VEIN_STEP * np.array([side * np.cos(tilt), np.sin(tilt)])
            taper = 0.55 + 0.45 * np.sin(np.pi * (k + 0.5) / steps)
            stamp_segment(mask, xc, yc, pos, nxt, thick / 2 * taper, False)
            pos = nxt
    return mask & solid & (dist >= vein.buried)


def fill_solid(
    cave: np.ndarray, fill: FillStyle, mats: Materials, rng: np.random.Generator
) -> np.ndarray:
    """Material grid of a region: air in caves, strata of solids elsewhere.

    The strata are rank-normalised stretched noise (plus a vertical bias, so the first
    entries tend to lie on top): material proportions follow the weights exactly and
    every material forms wide layers. ``speckle`` dithers the transitions. ``buried``
    entries only appear at least that many cells away from any cave. Veins are laid
    over the strata, and the skin next to caves is partly replaced by ``edge_material``
    in patches (not cell by cell).
    """
    solid = ~cave
    grid = np.full(cave.shape, mats.air, dtype=np.uint8)
    n = int(solid.sum())
    if n == 0:
        return grid
    h, _ = cave.shape
    entries = fill.materials
    noise = value_noise(cave.shape, fill.scale, rng, octaves=2, stretch=fill.stretch)
    if fill.depth_bias > 0:
        noise = (1 - fill.depth_bias) * noise + fill.depth_bias * (np.arange(h) / h)[:, None]
    rank = rank_normalize(noise[solid])
    rank = np.clip(rank + (rng.random(n, dtype=np.float32) - 0.5) * fill.speckle, 0.0, 0.999999)
    weights = np.array([e.weight for e in entries], dtype=np.float64)
    cum = np.cumsum(weights) / weights.sum()
    idx = np.minimum(np.searchsorted(cum, rank, side="right"), len(entries) - 1)
    ids = np.array([mats[e.material] for e in entries], dtype=np.uint8)
    dist_all = distance_transform_edt(solid)
    dist = dist_all[solid]
    primary = max(
        (k for k, e in enumerate(entries) if e.buried == 0), key=lambda k: entries[k].weight
    )
    for k, e in enumerate(entries):
        if e.buried:
            idx[(idx == k) & (dist < e.buried)] = primary
    material = ids[idx]
    if fill.edge_depth > 0:
        patch = rank_normalize(value_noise(cave.shape, EDGE_PATCH, rng, octaves=2)[solid])
        material[(dist <= fill.edge_depth) & (patch < fill.edge_prob)] = mats[fill.edge_material]
    grid[solid] = material
    brick = mats["brick"]
    for vein in fill.veins:
        cells = _vein_mask(solid, dist_all, vein, rng) & (grid != brick)
        grid[cells] = mats[vein.material]
    return grid


# --------------------------------------------------------------------------- regions


def build_biome_region(
    canvas: Canvas,
    bm: BiomeMap,
    biome: Biome,
    edge_seed: int,
    rng: np.random.Generator,
) -> RegionInfo:
    """Build the caves of ``biome``'s region and fill it; returns what later steps need."""
    x0, y0, x1, y1 = bm.region(biome.key)
    r = bm.ring
    info = RegionInfo(np.zeros((y1 - y0, x1 - x0), dtype=bool))
    if biome.layout == "rooms":
        assert biome.rooms is not None
        cave, rooms, doors = layout_rooms((x1 - x0, y1 - y0), r, biome.rooms, rng)
        info.rooms = [room.moved(x0, y0) for room in rooms]
        info.doors = [(a + x0, b + y0, c + x0, d + y0) for a, b, c, d in doors]
    else:
        st = biome.tile
        phase = (int(rng.integers(0, 4 * st.short_side)), int(rng.integers(0, 4 * st.short_side)))
        cave, info.placements = tile_region(tileset_for(biome), edge_seed, (x0, y0, x1, y1), phase)
        cave = shape_cave(smooth_cave(cave, st, rng), biome.shape, r, rng)
    cave[:r, :] = False
    cave[-r:, :] = False
    cave[:, :r] = False
    cave[:, -r:] = False
    info.cave = cave
    canvas.grid[y0:y1, x0:x1] = fill_solid(cave, biome.fill, canvas.mats, rng)
    return info
