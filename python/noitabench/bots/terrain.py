"""What the bot knows about the pixel world: which boxes of cells it can stand in, and what
digging and wading cost.

The bot reads the grid the way a person looks at the screen (it is a test and recording tool,
not an agent under evaluation). Every number about a material comes from `content/materials.json`;
the player box and the digger's reach come from `content/entities.json` and `content/spells.json`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation, distance_transform_edt, generate_binary_structure

REPO = Path(__file__).resolve().parents[3]
CONTENT = REPO / "content"

# Kind codes of the material table (contracts section 2).
AIR, GAS, FIRE, LIQUID, POWDER, STATIC = range(6)
KIND_CODE = {
    "air": AIR,
    "gas": GAS,
    "fire": FIRE,
    "liquid": LIQUID,
    "powder": POWDER,
    "static": STATIC,
}

CROSS = generate_binary_structure(2, 1)  # the 4 neighbours of a cell

HAZARD_PER_CELL = {  # extra cost per cell of the box that sits in this material
    "water": 0.4,
    "blood": 0.4,
    "oil": 1.0,
    "whiskey": 1.0,
    "toxic_sludge": 3.0,
    "flammable_gas": 0.3,
}
FORBIDDEN_KEYS = ("lava", "acid", "fire")  # the box never enters them; the hit box keeps off
HIT_COST = 60.0  # per cell of these inside the hit box (contact damage, catching fire)
HIT_CELLS = 6
RING_COST = 3.0  # per cell of these in the ring around the hit box: a fall or a wobble reaches it
RING_CELLS = 12
HIT_MARGIN = (4, 2, 4, 4)  # the ring's width: left, up, right, down
TIGHT_CLEARANCE = 5.0  # mean distance to a wall (cells) from which a box costs nothing extra
DIG_PER_CELL_BASE = 0.8
DIG_HP_DIVISOR = 20000.0
DIG_EVENT_COST = 10.0  # a box that needs digging costs this much more: shots take frames
DIG_DANGER_RADIUS = 8.0  # a bolt's hole (radius 6) and its aim's wobble: keep this far from lava
DIG_DANGER_COST = 5000.0  # ... or the box costs this much more: the hole lets the liquid out


@dataclass(frozen=True)
class Materials:
    keys: tuple[str, ...]
    kind: np.ndarray  # (n,) uint8 kind code
    durability: np.ndarray
    hp: np.ndarray

    @classmethod
    def load(cls, path: Path | None = None) -> Materials:
        data = json.loads((path or CONTENT / "materials.json").read_text(encoding="utf-8"))
        rows = data["materials"]
        if [r["index"] for r in rows] != list(range(len(rows))):
            raise ValueError("the material indices of materials.json are not 0..n")
        return cls(
            keys=tuple(r["key"] for r in rows),
            kind=np.array([KIND_CODE[r["kind"]] for r in rows], dtype=np.uint8),
            durability=np.array([r["durability"] for r in rows], dtype=np.int32),
            hp=np.array([r["hp"] for r in rows], dtype=np.float64),
        )

    def index(self, key: str) -> int:
        return self.keys.index(key)

    def ids(self, keys: tuple[str, ...]) -> np.ndarray:
        """The material indices of some keys (keys this content does not have are skipped)."""
        return np.array([self.index(k) for k in keys if k in self.keys], dtype=np.uint8)


@dataclass(frozen=True)
class Body:
    """The player numbers the bot plans with (entities.json, section `player`)."""

    w: int
    h: int
    accel_ground: float  # share of the gap to the target speed closed per frame
    accel_air: float
    gravity: float  # px/s^2
    hand_dx: int  # the hand, from the box's top-left cell
    hand_dy: int
    pickup_radius: float
    hit: tuple[int, int, int, int]  # the hit box (dx, dy, w, h) from the collision box's corner

    @classmethod
    def load(cls, path: Path | None = None) -> Body:
        data = json.loads((path or CONTENT / "entities.json").read_text(encoding="utf-8"))
        p = data["player"]
        hb = {k: int(v) for k, v in p["hitboxes"][0].items() if k in ("dx", "dy", "w", "h")}
        return cls(
            w=int(p["collision"]["w"]),
            h=int(p["collision"]["h"]),
            accel_ground=float(p["accel_ground"]),
            accel_air=float(p["accel_air"]),
            gravity=float(p["gravity"]),
            hand_dx=int(p["hand"]["dx"]),
            hand_dy=int(p["hand"]["dy"]),
            pickup_radius=float(p["pickup_radius"]),
            hit=(hb["dx"], hb["dy"], hb["w"], hb["h"]),
        )


def hit_sum(a: np.ndarray, hit: tuple[int, int, int, int]) -> np.ndarray:
    """`out[y, x]` = sum of `a` over the hit box of a player whose collision box is at `(x, y)`
    (cells outside the world count as zero)."""
    dx, dy, w, h = hit
    pad = max(abs(dx), abs(dy)) + 1
    s = box_sum(np.pad(a, pad), w, h)
    height, width = a.shape
    return s[pad + dy : pad + dy + height, pad + dx : pad + dx + width]


def _grown(hit: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    dx, dy, w, h = hit
    left, up, right, down = HIT_MARGIN
    return dx - left, dy - up, w + left + right, h + up + down


def box_sum(a: np.ndarray, w: int, h: int) -> np.ndarray:
    """`out[y, x]` = sum of `a[y:y+h, x:x+w]` (zero where the box leaves the grid)."""
    pad = np.pad(a.astype(np.float64), ((0, h), (0, w)))
    c = pad.cumsum(axis=0).cumsum(axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    height, width = a.shape
    ys, xs = np.arange(height), np.arange(width)
    y1, x1 = ys + h, xs + w
    return c[y1][:, x1] - c[ys][:, x1] - c[y1][:, xs] + c[ys][:, xs]


@dataclass(frozen=True)
class Terrain:
    """Masks over box positions `(y, x)` = top-left cell of the player's box."""

    width: int
    height: int
    body: Body
    free: np.ndarray  # box fits, nothing blocking, nothing forbidden (walk/fly/fall/swim)
    diggable: np.ndarray  # box fits if the diggable cells in it were dug out
    grounded: np.ndarray  # a blocking cell right under the box
    contact: np.ndarray  # lava, acid or fire touches the hit box
    near_hazard: np.ndarray  # ... or is within the ring around it (a fall or a wobble reaches it)
    cost: np.ndarray  # extra cost of standing there (float32): hazards, digging, tight walls


def analyse(
    grid: np.ndarray, mats: Materials, body: Body, *, dig_max_durability: int, tight: bool = True
) -> Terrain:
    """Classify every box position of the grid.

    `free` positions hold the box without any blocking cell; `diggable` positions are those
    where every blocking cell could be dug with a digging bolt (durability up to
    `dig_max_durability`, never brick). `cost` adds hazards, the digging effort and a penalty
    for squeezing along walls (`tight=False` leaves that out).
    """
    height, width = grid.shape
    kind = mats.kind[grid]
    blocking = (kind == STATIC) | (kind == POWDER)
    forbidden = np.isin(grid, mats.ids(FORBIDDEN_KEYS))
    undiggable = (kind == STATIC) & (mats.durability[grid] > dig_max_durability)
    w, h = body.w, body.h

    n_block = box_sum(blocking, w, h)
    n_bad = box_sum(forbidden | undiggable, w, h)
    inside = np.zeros((height, width), dtype=bool)
    inside[: height - h + 1, : width - w + 1] = True  # the box must lie in the world
    free = inside & (n_block == 0) & (n_bad == 0)
    diggable = inside & (n_bad == 0)

    row_sum = box_sum(blocking, w, 1)  # blocking cells in the w cells of a row from x on
    grounded = np.zeros((height, width), dtype=bool)
    grounded[: height - h] = row_sum[h:] > 0  # the row right under the box
    grounded &= inside

    core = hit_sum(forbidden, body.hit)
    ring_all = hit_sum(_exposed(forbidden, blocking), _grown(body.hit))
    cost = (
        _wading_cost(grid, mats, body)
        + HIT_COST * np.minimum(core, HIT_CELLS)
        + RING_COST * np.minimum(ring_all - core, RING_CELLS)
        + _digging_cost(grid, mats, body, blocking, forbidden)
        + (_tightness(blocking, body) if tight else 0.0)
    )
    return Terrain(
        width=width,
        height=height,
        body=body,
        free=free,
        diggable=diggable,
        grounded=grounded,
        contact=core > 0,
        near_hazard=ring_all > 0,
        cost=cost.astype(np.float32),
    )


def _exposed(forbidden: np.ndarray, blocking: np.ndarray) -> np.ndarray:
    """The lava, acid and fire cells that touch open space. A fall or a wobble can bring the
    player into those; a seam of lava sealed in rock cannot be walked into (it still burns
    through a thin wall: that is `contact`, which counts every such cell)."""
    open_cells = ~blocking & ~forbidden
    return forbidden & binary_dilation(open_cells, structure=CROSS)


def _wading_cost(grid: np.ndarray, mats: Materials, body: Body) -> np.ndarray:
    """What the cells of the hit box cost to stand in: water slows, sludge poisons, oil burns."""
    per_material = np.zeros(len(mats.keys), dtype=np.float64)
    for key, c in HAZARD_PER_CELL.items():
        if key in mats.keys:
            per_material[mats.index(key)] = c
    return 0.15 * hit_sum(per_material[grid], body.hit)


def _digging_cost(
    grid: np.ndarray, mats: Materials, body: Body, blocking: np.ndarray, forbidden: np.ndarray
) -> np.ndarray:
    """What a box costs that must be dug free: shots take time, hard rock takes many, and a hole
    beside lava, acid or fire lets it out."""
    w, h = body.w, body.h
    per_cell = np.where(
        blocking, DIG_PER_CELL_BASE + np.minimum(mats.hp[grid] / DIG_HP_DIVISOR, 12.0), 0.0
    )
    near_liquid = distance_transform_edt(~forbidden) <= DIG_DANGER_RADIUS
    return (
        0.25 * box_sum(per_cell, w, h)
        + DIG_EVENT_COST * (box_sum(blocking, w, h) > 0)
        + DIG_DANGER_COST * (box_sum(blocking & near_liquid, w, h) > 0)
    )


def _tightness(blocking: np.ndarray, body: Body) -> np.ndarray:
    """A penalty for squeezing along walls: mean distance to a wall over the box, below 5."""
    clearance = box_sum(distance_transform_edt(~blocking), body.w, body.h) / (body.w * body.h)
    return np.clip(TIGHT_CLEARANCE - clearance, 0.0, None)
