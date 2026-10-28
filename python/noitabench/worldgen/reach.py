"""Where the player can walk: the player-fit areas of a grid, shared by generation and checks.

A cell is *fit* if the player's collision box (4 x 7) centred on it lies wholly in cells that are
not static (or, with ``dug``, in static cells of a scene that is built to be dug through). The
fit cells fall into connected areas; the area that holds the spawn is the one the player walks.
The post-generation checks (``checks.py``) use exactly this, and so does the placement of
ingredient deposits and bowls, so that what the generator puts "where the player can walk to" is
what the checks later find reachable.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion, label

from .canvas import PLAYER_H, PLAYER_W
from .config import Materials

PLAYER_BOX = np.ones((PLAYER_H, PLAYER_W), dtype=bool)
DEFAULT_DIG_MAX_DURABILITY = 10  # what the starting digger removes (``checks.py`` repeats it)


def label_at(lab: np.ndarray, x: int, y: int, radius: int = 14) -> int:
    """Label of the nearest labelled cell within ``radius`` of ``(x, y)`` (0 if none)."""
    y0, y1 = max(0, y - radius), min(lab.shape[0], y + radius + 1)
    x0, x1 = max(0, x - radius), min(lab.shape[1], x + radius + 1)
    win = lab[y0:y1, x0:x1]
    ys, xs = np.nonzero(win)
    if len(ys) == 0:
        return 0
    d = (ys + y0 - y) ** 2 + (xs + x0 - x) ** 2
    i = int(np.argmin(d))
    return int(win[ys[i], xs[i]])


def fit_labels(grid: np.ndarray, mats: Materials, dug: np.ndarray | None = None) -> np.ndarray:
    """Labels of the connected areas where the player's box fits (static cells block)."""
    static = mats.kind_mask(grid, "static")
    open_ = ~static if dug is None else (~static | dug)
    return label(binary_erosion(open_, structure=PLAYER_BOX))[0]


def dig_zone_cells(
    grid: np.ndarray,
    mats: Materials,
    footprints: list[tuple[int, int, int, int]],
    max_durability: int = DEFAULT_DIG_MAX_DURABILITY,
) -> np.ndarray:
    """Diggable static cells inside the footprints ``(x, y, w, h)`` of dig-zone scenes."""
    inside = np.zeros(grid.shape, dtype=bool)
    for x, y, w, h in footprints:
        inside[y : y + h, x : x + w] = True
    durability = np.array(mats.durability)[grid]
    return inside & mats.kind_mask(grid, "static") & (durability <= max_durability)


def walk_area(
    grid: np.ndarray, mats: Materials, start: tuple[int, int], dug: np.ndarray | None = None
) -> np.ndarray:
    """Mask of the fit cells in the area of ``start`` (all False if ``start`` is in none)."""
    lab = fit_labels(grid, mats, dug)
    k = label_at(lab, *start)
    return lab == k if k else np.zeros(grid.shape, dtype=bool)


def grow(mask: np.ndarray, radius: int) -> np.ndarray:
    """``mask`` dilated by ``radius`` cells in every direction (a square, done in two passes)."""
    size = 2 * radius + 1
    wide = binary_dilation(mask, structure=np.ones((1, size), dtype=bool))
    return binary_dilation(wide, structure=np.ones((size, 1), dtype=bool))


def reach_mask(grid: np.ndarray, mats: Materials, walk: np.ndarray, radius: int) -> np.ndarray:
    """Cells the player can touch from the walking area ``walk``: within ``radius`` of it and
    joined to it through cells that are not static (a pool behind a rock wall is not reachable
    just because it lies within ``radius`` of a floor)."""
    open_ = ~mats.kind_mask(grid, "static")
    lab, _ = label(open_, structure=np.ones((3, 3), dtype=bool))
    touched = np.unique(lab[walk & open_])
    touched = touched[touched > 0]
    return grow(walk, radius) & np.isin(lab, touched)
