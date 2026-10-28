"""The screenshot: a PNG of the cells around the player in the material colours of
`materials.json`, with a coloured box for each creature and item in view.

It shows what the map shows, as pixels. Burning cells are tinted orange, as the play page tints
them. Nothing is added that the player could not see: no labels, no legend, no properties.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image

from .content import Content
from .engine import OUTSIDE

OUTSIDE_COLOR = (0, 0, 0)
PLAYER_COLOR = (255, 255, 255)
ENEMY_COLOR = (230, 40, 40)
ITEM_COLOR = (255, 230, 60)
POTION_COLOR = (240, 120, 200)
BARREL_COLOR = (230, 140, 40)
PROJECTILE_COLOR = (255, 0, 255)
BURNING_TINT = (255, 150, 30)  # laid over a burning cell ...
BURNING_ALPHA = 0.6  # ... at this strength (the play page's `rgba(255, 150, 30, 0.6)`)


def entity_color(kind: str, hostile: bool) -> tuple[int, int, int]:
    if kind == "player":
        return PLAYER_COLOR
    if hostile:
        return ENEMY_COLOR
    if kind == "projectile":
        return PROJECTILE_COLOR
    if kind.startswith("potion_"):
        return POTION_COLOR
    if kind.startswith("barrel_") or kind == "bomb":
        return BARREL_COLOR
    return ITEM_COLOR


def render_png(
    window: np.ndarray,
    content: Content,
    origin: tuple[int, int],
    entities: list[dict[str, Any]],
    hostile_kinds: frozenset[str],
    scale: int = 1,
    burning: np.ndarray | None = None,
) -> bytes:
    """PNG bytes of a material window whose top-left world cell is `origin`. `burning` (same
    shape as `window`, 0 or 1) marks the cells that are on fire."""
    h, w = window.shape
    lut = np.array([*content.material_colors, OUTSIDE_COLOR], dtype=np.uint8)
    idx = np.where(window == OUTSIDE, len(content.material_colors), window)
    image = lut[idx]
    if burning is not None:
        on_fire = burning.astype(bool)
        tint = np.array(BURNING_TINT, dtype=np.float32)
        mixed = image[on_fire] * (1.0 - BURNING_ALPHA) + tint * BURNING_ALPHA
        image[on_fire] = np.rint(mixed).astype(np.uint8)
    for e in entities:
        color = entity_color(e["kind"], e["kind"] in hostile_kinds)
        x0, y0 = e["x"] - origin[0], e["y"] - origin[1]
        x1, y1 = x0 + max(e["w"], 1), y0 + max(e["h"], 1)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if x0 < x1 and y0 < y1:
            image[y0:y1, x0:x1] = color
    img = Image.fromarray(image, "RGB")
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
