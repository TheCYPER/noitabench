"""Where to run to from a bomb: places far enough from the blast, along the way the bot came.

The bomb's blast hurts everything within its radius that has a line to it and carves too much
for cover to count, so the thrower needs distance. The way back along the generator's main path
is known to be walkable (the bot has just walked it), so the candidates lie on it: the first
places at least `distance` cells from the blast, going back toward the start. Standing places
(on the ground) come first; a place in the air (a shaft) is the fallback.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Sequence
from itertools import pairwise

import numpy as np

from .navfield import NO_NODE, build_field
from .terrain import Terrain

REACH = 10  # cells around a point of the route that are searched for a place to stand
MAX_POINTS = 400  # route points that are looked at


def route_points(waypoints: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """The polyline of the main path with a point in every cell."""
    pts = [(int(x), int(y)) for x, y in waypoints]
    out: list[tuple[int, int]] = []
    for (x0, y0), (x1, y1) in pairwise(pts):
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        xs = np.rint(np.linspace(x0, x1, n, endpoint=False)).astype(int)
        ys = np.rint(np.linspace(y0, y1, n, endpoint=False)).astype(int)
        out += list(zip(xs.tolist(), ys.tolist(), strict=True))
    if pts:
        out.append(pts[-1])
    return out


def way_back(
    route: Sequence[tuple[int, int]], centre: tuple[float, float]
) -> list[tuple[int, int]]:
    """The route from the point nearest to `centre` back toward the start. With no route, the
    cells straight above `centre`."""
    if not route:
        return [(int(centre[0]), int(centre[1]) - k) for k in range(MAX_POINTS)]
    pts = np.array(route, dtype=float)
    nearest = int(np.argmin((pts[:, 0] - centre[0]) ** 2 + (pts[:, 1] - centre[1]) ** 2))
    return list(route[nearest::-1])


def candidates(
    terrain: Terrain,
    route: Sequence[tuple[int, int]],
    centre: tuple[float, float],
    distance: float,
) -> Iterator[tuple[tuple[int, int], bool]]:
    """Box positions at least `distance` cells from `centre`, nearest to the start of the way
    back first; `(position, standing)`. Standing places come out first, then the others."""
    w, h = terrain.body.w, terrain.body.h
    back = way_back(route, centre)[:MAX_POINTS]
    for want_standing in (True, False):
        seen: set[tuple[int, int]] = set()
        for px, py in back:
            x0, y0 = max(0, px - REACH), max(0, py - REACH)
            x1, y1 = min(terrain.width, px + REACH + 1), min(terrain.height, py + REACH + 1)
            ok = terrain.free[y0:y1, x0:x1] & ~terrain.near_hazard[y0:y1, x0:x1]
            if want_standing:
                ok &= terrain.grounded[y0:y1, x0:x1]
            ys, xs = np.nonzero(ok)
            if len(ys) == 0:
                continue
            xs, ys = xs + x0, ys + y0
            far = np.hypot(xs + w / 2 - centre[0], ys + h / 2 - centre[1]) >= distance
            if not far.any():
                continue
            xs, ys = xs[far], ys[far]
            k = int(np.argmin((xs - px) ** 2 + (ys - py) ** 2))
            spot = (int(xs[k]), int(ys[k]))
            if spot not in seen:
                seen.add(spot)
                yield spot, want_standing


FAR_SPACING = 5  # cells between the far places that are looked at
FAR_LIMIT = 40  # far places that are listed
CROP_MARGIN = 25  # cells around the thrower and a place that the bot's way to it is looked for in


def far_places(
    terrain: Terrain,
    centre: tuple[float, float],
    distance: float,
    origin: tuple[float, float],
    *,
    reach: float = 190.0,
) -> list[tuple[int, int]]:
    """Standing places (on the ground, clear of hazards) at least `distance` cells from `centre`
    and within `reach` cells of `origin`, those nearest to `origin` first, thinned out to one in
    every `FAR_SPACING` by `FAR_SPACING` cells. Where the route back offers no place far enough
    that the bot reaches in time, a place beside it (a chamber off the shaft) may."""
    w, h = terrain.body.w, terrain.body.h
    ok = terrain.free & terrain.grounded & ~terrain.near_hazard
    ys, xs = np.nonzero(ok)
    if len(ys) == 0:
        return []
    far = np.hypot(xs + w / 2 - centre[0], ys + h / 2 - centre[1]) >= distance
    near = np.hypot(xs - origin[0], ys - origin[1]) <= reach
    xs, ys = xs[far & near], ys[far & near]
    order = np.argsort((xs - origin[0]) ** 2 + (ys - origin[1]) ** 2, kind="stable")
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for i in order:
        cell = (int(xs[i]) // FAR_SPACING, int(ys[i]) // FAR_SPACING)
        if cell in seen:
            continue
        seen.add(cell)
        out.append((int(xs[i]), int(ys[i])))
        if len(out) >= FAR_LIMIT:
            break
    return out


def cropped(terrain: Terrain, x0: int, y0: int, x1: int, y1: int) -> Terrain:
    """The part `[x0, x1) x [y0, y1)` of the terrain (clamped to the world) as a terrain of its
    own, for a cheap look at the ways within a window."""
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(terrain.width, x1), min(terrain.height, y1)
    window = (slice(y0, y1), slice(x0, x1))
    return dataclasses.replace(
        terrain,
        width=x1 - x0,
        height=y1 - y0,
        free=terrain.free[window],
        diggable=terrain.diggable[window],
        grounded=terrain.grounded[window],
        contact=terrain.contact[window],
        near_hazard=terrain.near_hazard[window],
        cost=terrain.cost[window],
    )


def frames_between(
    terrain: Terrain, start: tuple[int, int], goal: tuple[int, int], per_node: float = 1.0
) -> float | None:
    """Frames the cheapest way from `start` to `goal` takes (`per_node` frames a step), looked
    for in a window around both; None if there is none."""
    x0 = min(start[0], goal[0]) - CROP_MARGIN
    y0 = min(start[1], goal[1]) - CROP_MARGIN
    x1 = max(start[0], goal[0]) + CROP_MARGIN + terrain.body.w
    y1 = max(start[1], goal[1]) + CROP_MARGIN + terrain.body.h
    x0, y0 = max(0, x0), max(0, y0)
    window = cropped(terrain, x0, y0, x1, y1)
    gx, gy = goal[0] - x0, goal[1] - y0
    try:
        field = build_field(window, (gx, gy))
    except ValueError:
        return None
    node = field.nearest_node(start[0] - x0, start[1] - y0)
    if node == NO_NODE:
        return None
    return len(field.path_from(node)) * per_node
