"""Spawn, item and encounter markers (contracts section 4)."""

from __future__ import annotations

import numpy as np

from .canvas import Canvas, Rect
from .config import Biome
from .rng import pick_weighted

ENEMY_CLEARANCE = 14  # free cells above an enemy or item spawn
BARREL_CLEARANCE = 10  # free cells above a barrel marker (contracts section 4)
ENEMY_SPACING = 26
ITEM_SPACING = 14


def spawn_candidates(canvas: Canvas, rect: Rect) -> np.ndarray:
    """Standing cells: air above solid ground with ``ENEMY_CLEARANCE`` free cells above."""
    x0, y0, x1, y1 = canvas.clip(rect)
    sub = canvas.grid[y0:y1, x0:x1]
    air = sub == canvas.mats.air
    ground = canvas.mats.kind_mask(sub, "static") | canvas.mats.kind_mask(sub, "powder")
    stand = np.zeros_like(air)
    stand[:-1] = air[:-1] & ground[1:]
    clear = air.copy()
    for k in range(1, ENEMY_CLEARANCE):
        clear[k:] &= air[:-k]
    stand &= clear & ~canvas.protected[y0:y1, x0:x1]
    ys, xs = np.nonzero(stand)
    return np.stack([xs + x0, ys + y0], axis=1)


def _greedy(
    points: np.ndarray, count: int, spacing: float, taken: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    chosen: list[tuple[int, int]] = []
    existing = np.array(taken, dtype=float).reshape(-1, 2)
    for p in points:
        if len(chosen) >= count:
            break
        q = np.array([[p[0], p[1]]], dtype=float)
        if len(existing) and np.min(np.hypot(*(existing - q).T)) < spacing:
            continue
        existing = np.vstack([existing, q])
        chosen.append((int(p[0]), int(p[1])))
    return chosen


def place_spawns(
    canvas: Canvas, biome: Biome, rect: Rect, rng: np.random.Generator, avoid: list[tuple[int, int]]
) -> list[dict]:
    """Enemy and item markers for one biome region (deterministic given ``rng``)."""
    cand = spawn_candidates(canvas, rect)
    if len(cand) == 0:
        return []
    area = (rect[2] - rect[0]) * (rect[3] - rect[1]) / 10_000.0
    mk = biome.markers
    out: list[dict] = []
    taken = list(avoid)
    n_enemy = int(rng.poisson(mk.enemy_per_10k * area))
    for x, y in _greedy(cand[rng.permutation(len(cand))], n_enemy, ENEMY_SPACING, taken):
        e = mk.enemies[pick_weighted(float(rng.random()), [w.weight for w in mk.enemies])]
        out.append({"type": "spawn_enemy", "x": x, "y": y, "enemy": e.key})
        taken.append((x, y))
    n_item = int(rng.poisson(mk.item_per_10k * area))
    for x, y in _greedy(cand[rng.permutation(len(cand))], n_item, ITEM_SPACING, taken):
        it = mk.items[pick_weighted(float(rng.random()), [w.weight for w in mk.items])]
        m = {"type": "item", "x": x, "y": y, "item": it.key}
        if it.extra:
            m["contents"] = it.extra
        if it.key == "wand":
            m["tier"] = biome.layer
        out.append(m)
        taken.append((x, y))
    return out


def encounter_marker(slot: dict) -> dict:
    """The ``encounter`` marker of a slot (contracts section 4).

    A slot with a scene also carries ``params`` (the liquid of every slot letter), ``mirror``,
    ``footprint`` and named ``regions``; a placeholder carries ``placeholder: true``.
    """
    x0, y0, x1, y1 = slot["rect"]
    marker = {
        "type": "encounter",
        "x": (x0 + x1) // 2,
        "y": (y0 + y1) // 2,
        "encounter_id": slot["encounter_id"],
        "variant": slot.get("variant", 0),
        "trigger": slot.get("trigger") or {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
        "must_pass": bool(slot["must_pass"]),
        "placeholder": bool(slot.get("placeholder", True)),
        "layer": slot["layer"],
        "biome": slot["biome"],
    }
    for key in ("params", "mirror", "footprint", "regions"):
        if key in slot:
            marker[key] = slot[key]
    return marker


def station_markers(slots: list[dict]) -> list[dict]:
    """``edit_station`` markers: the places where ``edit_wand`` is allowed besides the rest areas.

    A scene names such a place with the region ``edit_station`` of its definition (the hall in
    front of the sealed deep); the box moves and mirrors with the scene.
    """
    out = []
    for s in slots:
        box = s.get("regions", {}).get("edit_station")
        if box is not None:
            out.append(
                {"type": "edit_station", "x": box["x"], "y": box["y"], "w": box["w"], "h": box["h"]}
            )
    return out
