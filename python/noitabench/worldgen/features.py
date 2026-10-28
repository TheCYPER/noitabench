"""Terrain dressing on the finished caves: liquid pools, powder piles, gas pockets."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.ndimage import binary_dilation, label

from .canvas import Canvas, Rect
from .clearance import is_hazard
from .config import Biome, FeatureStyle
from .rng import pick_weighted

EIGHT = np.ones((3, 3), dtype=bool)
WINDOW_HALF = 70  # horizontal half-width of the basin search window
WINDOW_DOWN = 26  # how deep a basin may reach below its seed
DEFAULT_GAS_DEPTH = (3, 8)
POOL_GAP = 1  # a pool keeps this many cells from any other liquid (unlike liquids would mix)
GAS_LAVA_GAP = 4  # a gas pocket keeps this far from lava (it would ignite at frame 1)
PILE_LIQUID_GAP = 3  # a powder heap keeps this far from liquids (it would sink or ignite)


def _area_units(rect: Rect) -> float:
    return (rect[2] - rect[0]) * (rect[3] - rect[1]) / 10_000.0


def _weighted_material(style: FeatureStyle, rng: np.random.Generator) -> str:
    return style.options[pick_weighted(float(rng.random()), [o.weight for o in style.options])].key


def floor_points(canvas: Canvas, rect: Rect) -> np.ndarray:
    """Air cells directly above a static or powder cell, as ``(x, y)`` rows (world coordinates)."""
    x0, y0, x1, y1 = canvas.clip(rect)
    sub = canvas.grid[y0:y1, x0:x1]
    air = sub == canvas.mats.air
    ground = canvas.mats.kind_mask(sub, "static") | canvas.mats.kind_mask(sub, "powder")
    mask = air[:-1] & ground[1:] & ~canvas.protected[y0 : y1 - 1, x0:x1]
    ys, xs = np.nonzero(mask)
    return np.stack([xs + x0, ys + y0], axis=1)


def ceiling_points(canvas: Canvas, rect: Rect) -> np.ndarray:
    x0, y0, x1, y1 = canvas.clip(rect)
    sub = canvas.grid[y0:y1, x0:x1]
    air = sub == canvas.mats.air
    solid = canvas.mats.kind_mask(sub, "static")
    mask = air[1:] & solid[:-1] & ~canvas.protected[y0 + 1 : y1, x0:x1]
    ys, xs = np.nonzero(mask)
    return np.stack([xs + x0, ys + y0 + 1], axis=1)


def find_basin(
    canvas: Canvas,
    sx: int,
    sy: int,
    depth: int,
    max_area: int,
    flip: bool = False,
    bounds: Rect | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Cells of a closed container at seed ``(sx, sy)`` filled ``depth`` cells deep.

    The container is the set of air cells connected to the seed that lie at or below
    the surface level; it must not touch the search window's sides or bottom (a leak)
    and must not overlap protected cells. With ``flip`` the container hangs from a
    ceiling instead (gas pockets).
    """
    bx0, by0, bx1, by1 = bounds or (0, 0, canvas.w, canvas.h)
    wx0 = max(bx0, sx - WINDOW_HALF)
    wx1 = min(bx1, sx + WINDOW_HALF + 1)
    if flip:
        wy0, wy1 = max(by0, sy - WINDOW_DOWN), min(by1, sy + depth + 2)
    else:
        wy0, wy1 = max(by0, sy - depth - 1), min(by1, sy + WINDOW_DOWN)
    air = canvas.grid[wy0:wy1, wx0:wx1] == canvas.mats.air
    prot = canvas.protected[wy0:wy1, wx0:wx1]
    if flip:
        air, prot = air[::-1], prot[::-1]
    h = wy1 - wy0
    lx = sx - wx0
    ly = (h - 1 - (sy - wy0)) if flip else (sy - wy0)
    if not air[ly, lx]:
        return None
    for d in range(depth, 1, -1):
        level = ly - d + 1
        if level < 0:
            continue
        region = air.copy()
        region[:level] = False
        lab, _ = label(region, structure=EIGHT)  # liquids also flow through diagonal gaps
        k = lab[ly, lx]
        if k == 0:
            continue
        comp = lab == k
        if comp[:, 0].any() or comp[:, -1].any() or comp[-1, :].any():
            continue
        area = int(comp.sum())
        if area > max_area or area < 12 or (comp & prot).any():
            continue
        ys, xs = np.nonzero(comp)
        if flip:
            ys = h - 1 - ys
        return xs + wx0, ys + wy0
    return None


def place_pools(canvas: Canvas, biome: Biome, rect: Rect, rng: np.random.Generator) -> int:
    """Liquid pools in closed basins; with a ``lining`` the ground around them turns to rock."""
    st = biome.pools

    def apart(cells: tuple[np.ndarray, np.ndarray], material: str) -> bool:
        if is_hazard(material) and canvas.keepout[cells[1], cells[0]].any():
            return False  # a hazard keeps out of reach of the corridors (clearance.py)
        return not any_near(
            canvas, cells, POOL_GAP, lambda sub: canvas.mats.kind_mask(sub, "liquid")
        )

    pools = _place_basins(canvas, st, rect, rng, floor_points(canvas, rect), False, apart)
    if st.lining_depth:
        for xs, ys in pools:
            _line_basin(canvas, xs, ys, canvas.mats[st.lining_material], st.lining_depth)
    return len(pools)


def place_gas(canvas: Canvas, biome: Biome, rect: Rect, rng: np.random.Generator) -> int:
    lava = canvas.mats["lava"]

    def apart(cells: tuple[np.ndarray, np.ndarray], _material: str) -> bool:
        return not any_near(canvas, cells, GAS_LAVA_GAP, lambda sub: sub == lava)

    points = ceiling_points(canvas, rect)
    return len(_place_basins(canvas, biome.gas, rect, rng, points, True, apart))


def any_near(
    canvas: Canvas,
    cells: tuple[np.ndarray, np.ndarray],
    pad: int,
    test: Callable[[np.ndarray], np.ndarray],
) -> bool:
    """True if ``test`` (a mask function) holds anywhere in the box of ``cells`` grown by ``pad``."""
    xs, ys = cells
    x0, y0, x1, y1 = canvas.clip(
        (int(xs.min()) - pad, int(ys.min()) - pad, int(xs.max()) + pad + 1, int(ys.max()) + pad + 1)
    )
    return bool(test(canvas.grid[y0:y1, x0:x1]).any())


def _line_basin(canvas: Canvas, xs: np.ndarray, ys: np.ndarray, material: int, depth: int) -> None:
    """Turn the ground within ``depth`` cells of a basin into ``material`` (rock walls)."""
    x0, x1 = int(xs.min()) - depth - 1, int(xs.max()) + depth + 2
    y0, y1 = int(ys.min()) - depth - 1, int(ys.max()) + depth + 2
    x0, y0, x1, y1 = canvas.clip((x0, y0, x1, y1))
    basin = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    basin[ys - y0, xs - x0] = True
    near = binary_dilation(basin, iterations=depth) & ~basin
    sub = canvas.grid[y0:y1, x0:x1]
    sub[near & (sub == canvas.mats["ground"]) & ~canvas.protected[y0:y1, x0:x1]] = material


def _place_basins(
    canvas: Canvas,
    st: FeatureStyle,
    rect: Rect,
    rng: np.random.Generator,
    points: np.ndarray,
    flip: bool,
    accept: Callable[[tuple[np.ndarray, np.ndarray], str], bool],
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Fill closed basins that ``accept`` allows (it gets the cells and the material key to fill
    them with); returns the ``(xs, ys)`` of every basin filled."""
    n = int(rng.poisson(st.attempts_per_10k * _area_units(rect)))
    if n == 0 or len(points) == 0 or not st.options:
        return []
    dmin, dmax = (st.depth_min, st.depth_max) if st.depth_max else DEFAULT_GAS_DEPTH
    placed: list[tuple[np.ndarray, np.ndarray]] = []
    for i in rng.choice(len(points), size=n, replace=True):
        sx, sy = int(points[i][0]), int(points[i][1])
        depth = int(rng.integers(dmin, dmax + 1))
        state = rng.bit_generator.state
        material = _weighted_material(
            st, rng
        )  # a look only: a basin that is not taken draws nothing
        rng.bit_generator.state = state
        cells = find_basin(canvas, sx, sy, depth, st.max_area, flip, rect)
        if cells is None or not accept(cells, material):
            continue
        canvas.grid[cells[1], cells[0]] = canvas.mats[_weighted_material(st, rng)]
        placed.append(cells)
    return placed


def place_piles(canvas: Canvas, biome: Biome, rect: Rect, rng: np.random.Generator) -> int:
    st = biome.piles
    pts = floor_points(canvas, rect)
    n = int(rng.poisson(st.attempts_per_10k * _area_units(rect)))
    if n == 0 or len(pts) == 0 or not st.options:
        return 0
    placed = 0
    for i in rng.choice(len(pts), size=n, replace=True):
        sx, sy = int(pts[i][0]), int(pts[i][1])
        r = int(rng.integers(st.radius_min, st.radius_max + 1))
        box = (np.array([sx - r, sx + r]), np.array([sy - r, sy + 6]))  # x range, y range
        if any_near(canvas, box, PILE_LIQUID_GAP, lambda sub: canvas.mats.kind_mask(sub, "liquid")):
            continue  # a heap beside a pool sinks into it (and lava would set it off)
        placed += heap(canvas, sx, sy, r, canvas.mats[_weighted_material(st, rng)], rect)
    return placed


def heap(canvas: Canvas, sx: int, sy: int, radius: int, material: int, rect: Rect) -> int:
    """A heap of powder resting on the floor around ``(sx, sy)``; returns 1 if anything was placed."""
    mats, grid = canvas.mats, canvas.grid
    placed = 0
    for x in range(max(rect[0] + 1, sx - radius), min(rect[2] - 1, sx + radius + 1)):
        floor_y = None
        for y in range(max(1, sy - 3), min(canvas.h - 1, sy + 6)):
            if grid[y, x] == mats.air and mats.kind_at_least(grid[y + 1, x], "powder"):
                floor_y = y
                break
        if floor_y is None:
            continue
        height = round(0.55 * radius * (1 - (abs(x - sx) / radius) ** 2))
        headroom = 0
        while (
            floor_y - headroom - 1 > 0
            and grid[floor_y - headroom - 1, x] == mats.air
            and headroom < 30
        ):
            headroom += 1
        if headroom - height < 12:
            continue  # never narrow a tunnel: the player must still fit
        for k in range(height):
            y = floor_y - k
            if y < 1 or grid[y, x] != mats.air or canvas.protected[y, x]:
                break
            grid[y, x] = material
            placed = 1
    return placed
