"""Shape helpers for the tile templates: tunnels, capsules and boxes, roughening."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter


def tunnel_points(
    p: np.ndarray,
    hub: np.ndarray,
    side: str,
    wobble: float,
    rng: np.random.Generator,
    rect: bool,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Segments of a tunnel from edge anchor ``p`` to the hub."""
    if rect:
        corner = np.array([p[0], hub[1]]) if side in ("top", "bottom") else np.array([hub[0], p[1]])
        return [(p, corner), (corner, hub)]
    mid = (p + hub) / 2
    d = hub - p
    perp = np.array([-d[1], d[0]])
    norm = float(np.hypot(*perp)) or 1.0
    mid = mid + perp / norm * rng.uniform(-1, 1) * wobble * float(np.hypot(*d))
    return [(p, mid), (mid, hub)]


def stamp_segment(
    cave: np.ndarray,
    xc: np.ndarray,
    yc: np.ndarray,
    a: np.ndarray,
    c: np.ndarray,
    radius: float,
    rect: bool,
) -> None:
    """Stamp a capsule (organic) or a box-ended bar (rect) into ``cave``."""
    x0 = int(max(0, np.floor(min(a[0], c[0]) - radius - 1)))
    x1 = int(min(cave.shape[1], np.ceil(max(a[0], c[0]) + radius + 2)))
    y0 = int(max(0, np.floor(min(a[1], c[1]) - radius - 1)))
    y1 = int(min(cave.shape[0], np.ceil(max(a[1], c[1]) + radius + 2)))
    if x0 >= x1 or y0 >= y1:
        return
    px, py = xc[y0:y1, x0:x1], yc[y0:y1, x0:x1]
    if rect:
        inside = (
            (px >= min(a[0], c[0]) - radius)
            & (px <= max(a[0], c[0]) + radius)
            & (py >= min(a[1], c[1]) - radius)
            & (py <= max(a[1], c[1]) + radius)
        )
    else:
        dx, dy = c[0] - a[0], c[1] - a[1]
        len2 = dx * dx + dy * dy
        t = (
            np.zeros_like(px)
            if len2 == 0
            else np.clip(((px - a[0]) * dx + (py - a[1]) * dy) / len2, 0, 1)
        )
        inside = (px - (a[0] + t * dx)) ** 2 + (py - (a[1] + t * dy)) ** 2 <= radius * radius
    cave[y0:y1, x0:x1] |= inside


def roughen(cave: np.ndarray, rng: np.random.Generator, roughness: float, iters: int) -> np.ndarray:
    f = cave.astype(np.float32)
    for _ in range(iters):
        nb = uniform_filter(f, size=3, mode="constant", cval=0.0)
        f = ((nb + (rng.random(f.shape, dtype=np.float32) - 0.5) * roughness) > 0.5).astype(
            np.float32
        )
    return f > 0.5
