"""Bring the finished terrain to rest (see ``rest.py``): nothing moves at frame 0.

Run after the pools and heaps are placed and again after all structures and hazards are
built, because carving can bare a powder cell (a coal vein in a shaft wall) or open a
diagonal gap at a pool's corner after the place that made them was done.

* Powder that would move slides down to where it stays, the way the simulation would
  move it: straight down, else to a lower diagonal. It never slides into a protected cell
  (the footprint of a scene): there it stops. A tunnel to a scene may fill up.
* A powder cell that would sink into a liquid below it disappears (a heap that slid onto a
  pool is gone, as if it had dissolved; rock on the water would block the way). A powder
  cell with a liquid beside it, which may be the pool's wall, turns to rock where it is,
  as does one that cannot go anywhere.
* A liquid that would run out only through a free cell on a lower diagonal gets that cell
  plugged with rock. Other leaks (air straight below or beside a pool) are never patched
  here: the check fails and the world is built again.
"""

from __future__ import annotations

import numpy as np

from .canvas import Canvas
from .rest import free_table, is_mobile, mobile_cells

MAX_SWEEPS = 400  # every sweep lowers or removes powder: this is only a safety net


def settle(canvas: Canvas) -> dict[str, int]:
    """Make the grid rest; returns how many cells slid, vanished, turned to rock or were plugged."""
    counts = _settle_powder(canvas)
    counts["plugged"] = _plug_liquid_corners(canvas)
    return counts


def _liquid_contact(canvas: Canvas, x: int, y: int) -> str:
    """'side' if a liquid lies beside the cell, 'below' if only below it, else ''."""
    mats, g = canvas.mats, canvas.grid
    if mats.kind_mask(g[y, x - 1 : x + 2], "liquid").any():
        return "side"
    return "below" if mats.kind_mask(g[y + 1, x - 1 : x + 2], "liquid").any() else ""


def _fall_to_rest(canvas: Canvas, free: np.ndarray, x: int, y: int) -> bool:
    """Move the powder cell at ``(x, y)`` down and sideways until it rests; True if it moved.

    The diagonal it prefers depends on the cell's position, so heaps do not lean one way.
    """
    g, prot, (h, w) = canvas.grid, canvas.sealed, canvas.grid.shape
    start = (x, y)
    while y + 1 < h:
        if free[g[y + 1, x]] and not prot[y + 1, x]:  # a scene is never filled by a heap
            step = 0
        else:
            first = -1 if (x + y) & 1 else 1
            step = next(
                (
                    d
                    for d in (first, -first)
                    if 0 < x + d < w - 1 and free[g[y + 1, x + d]] and not prot[y + 1, x + d]
                ),
                None,
            )
            if step is None:
                break
        g[y, x], g[y + 1, x + step] = g[y + 1, x + step], g[y, x]
        x, y = x + step, y + 1
    return (x, y) != start


def _would_fall_into_scene(canvas: Canvas, free: np.ndarray, x: int, y: int) -> bool:
    """True if the powder cell at ``(x, y)`` is held back only by a scene's footprint below it."""
    g, w = canvas.grid, canvas.grid.shape[1]
    cells = [(y + 1, x)] + [(y + 1, x + d) for d in (-1, 1) if 0 < x + d < w - 1]
    return any(free[g[cy, cx]] and canvas.sealed[cy, cx] for cy, cx in cells)


def _settle_powder(canvas: Canvas) -> dict[str, int]:
    mats, g = canvas.mats, canvas.grid
    free = free_table(mats)
    counts = {"slid": 0, "removed": 0, "to_rock": 0}
    for _ in range(MAX_SWEEPS):
        ys, xs = mobile_cells(g, mats, "powder")
        if len(ys) == 0:
            return counts
        for y, x in sorted(zip(ys.tolist(), xs.tolist()), key=lambda p: (-p[0], p[1])):
            if not is_mobile(g, mats, x, y, "powder"):  # an earlier move changed things here
                continue
            contact = _liquid_contact(canvas, x, y)
            if contact == "below":
                g[y, x] = mats.air
                counts["removed"] += 1
            elif contact == "side":
                g[y, x] = mats["rock"]
                counts["to_rock"] += 1
            elif _fall_to_rest(canvas, free, x, y):
                counts["slid"] += 1
            elif _would_fall_into_scene(canvas, free, x, y):
                g[y, x] = mats.air  # the heap that would pour into a scene is not there
                counts["removed"] += 1
            else:
                g[y, x] = mats["rock"]
                counts["to_rock"] += 1
    ys, xs = mobile_cells(g, mats, "powder")  # out of sweeps: stop the rest where they are
    g[ys, xs] = mats["rock"]
    counts["to_rock"] += len(ys)
    return counts


def _plug_liquid_corners(canvas: Canvas) -> int:
    """Rock into the free lower-diagonal cells of liquid cells that are closed otherwise."""
    mats, g = canvas.mats, canvas.grid
    free = free_table(mats)
    plugged = 0
    for _ in range(MAX_SWEEPS):
        ys, xs = mobile_cells(g, mats, "liquid")
        todo = []
        for y, x in zip(ys.tolist(), xs.tolist()):
            if free[g[y + 1, x]] or free[g[y, x - 1]] or free[g[y, x + 1]]:
                continue  # leaks straight down or sideways: not a corner, not ours to patch
            todo += [(y + 1, x + d) for d in (-1, 1) if free[g[y + 1, x + d]]]
        todo = sorted({(y, x) for y, x in todo if not canvas.protected[y, x]})
        if not todo:
            return plugged
        for y, x in todo:
            g[y, x] = mats["rock"]
        plugged += len(todo)
    return plugged
