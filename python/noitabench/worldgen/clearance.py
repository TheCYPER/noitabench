"""Hazard clearance: no lava or acid within reach of a corridor the player has to walk.

Two things killed the scripted bot on generated worlds (D2c, 2026-10-27):

* **Lava behind a thin wall.** A must-pass scene is a corridor the player has to walk (the
  seams make it the only way down). The player's hit box is 6 x 16 cells and reaches 7 cells above
  and 2 below the 4 x 7 collision box that stands on the floor, and contact damage and ignition do
  not care about walls: a lava lake three rows of rock above the corridor burns the player to death
  on the intended route (seed 17, E12). The clearance keeps every cell of an ambient hazard out of
  the reach of every free position of the collision box inside a must-pass scene's footprint and
  inside the tunnels that link its doors to the caves (and the shaft above the sealed deep).
* **The key blast lets lava loose.** The breaker spells together make an explosion of radius 75
  that removes everything up to durability 14, brick included. Lava within reach of that crater runs
  into the hall and the sealed room. The bomb is thrown, so it comes to rest (and goes off after
  its fuse) anywhere in the hall above the plug, not only on the plug: a bomb 14 cells beside the
  plug still opens it, and its crater reaches 14 cells farther on that side (seed 21: 27 lava cells
  ran into the vault from a bomb beside the plug, with the zone round the plug alone). Nothing
  hazardous may lie within the blast radius plus a margin of the hall (``Blast``).

*Reach* comes from ``entities.json`` (the collision box and the first hit box of the player):
``player_reach()``. *Free* is "not static": the player digs through powder, wades through liquid.
A position is the top-left cell of the collision box whose 4 x 7 cells are all free and which
overlaps a part of the lane (the footprint, or one of the boxes of its tunnels). The zone is the
union of the hit boxes of those positions. The scene's own art (its footprint) is exempt: its
hazards are the scene's design, each scene is drawn to be survivable on its route.

``Lane`` is what the generator records per must-pass scene (``meta["clearance"]``); ``keepout_mask``
turns lanes and the blast into the mask the dressing steps (pools, lava pockets) keep out of;
``lane_violations`` and ``blast_violations`` are what the post-generation check uses
(``clearance_checks.py``) on the finished grid, where fewer cells are free than when the mask was made.
Toxic sludge poisons but cannot kill (the status has a floor), so it is not a hazard here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .breaker import blast_radius
from .canvas import PLAYER_H, PLAYER_W, Rect
from .config import Materials
from .contentio import CONTENT_DIR, need, read_json
from .encounter_defs import breaker_spells

BLAST_MARGIN = 5  # cells beyond the blast radius that stay free of hazards
WINDOW_MARGIN = PLAYER_H + PLAYER_W + 9  # window round a lane: positions, their hit boxes, a rim


@dataclass(frozen=True)
class Reach:
    """How far the player's hit box reaches beyond its collision box, in cells."""

    left: int
    right: int
    up: int
    down: int


@lru_cache(maxsize=1)
def player_reach() -> Reach:
    """The reach of the hit box, from ``content/entities.json`` (``player.collision`` and ``hitboxes``)."""
    path = CONTENT_DIR / "entities.json"
    p = read_json(path)["player"]
    col, hb = p["collision"], p["hitboxes"][0]
    need(
        (col["w"], col["h"]) == (PLAYER_W, PLAYER_H),
        path,
        "player.collision",
        f"must be {PLAYER_W} x {PLAYER_H}, the box the world generator fits",
    )
    reach = Reach(
        -hb["dx"], hb["dx"] + hb["w"] - col["w"], -hb["dy"], hb["dy"] + hb["h"] - col["h"]
    )
    need(
        min(reach.left, reach.right, reach.up, reach.down) >= 0,
        path,
        "player.hitboxes",
        "must cover the collision box",
    )
    return reach


@lru_cache(maxsize=1)
def hazard_keys() -> tuple[str, ...]:
    """Materials that hurt or ignite a creature that touches them: contact damage, ignition, fire."""
    rows = read_json(CONTENT_DIR / "materials.json")["materials"]
    ignite = set(read_json(CONTENT_DIR / "entities.json")["contact"]["ignite"])
    return tuple(
        r["key"]
        for r in rows
        if (r.get("contact_damage_per_px_frame") or 0) > 0
        or r["key"] in ignite
        or r["kind"] == "fire"
    )


def hazard_mask(mats: Materials, grid: np.ndarray) -> np.ndarray:
    """Boolean mask of the cells of ``grid`` that hold a hazard material."""
    table = np.zeros(256, dtype=bool)
    table[[mats[k] for k in hazard_keys()]] = True
    return table[grid]


def is_hazard(key: str) -> bool:
    return key in hazard_keys()


# ------------------------------------------------------------------------------------ lanes


@dataclass(frozen=True)
class Lane:
    """A corridor the player has to walk: a must-pass scene and the tunnels from its doors."""

    encounter_id: str
    layer: int
    footprint: Rect
    tunnels: tuple[Rect, ...] = ()

    @property
    def parts(self) -> tuple[Rect, ...]:
        return (self.footprint, *self.tunnels)

    def record(self) -> dict:
        """The JSON form (``meta["clearance"]["lanes"]``, boxes as ``{x, y, w, h}``)."""
        return {
            "encounter_id": self.encounter_id,
            "layer": self.layer,
            "footprint": _box_dict(self.footprint),
            "tunnels": [_box_dict(t) for t in self.tunnels],
        }

    @classmethod
    def from_record(cls, d: dict) -> Lane:
        return cls(
            d["encounter_id"],
            int(d["layer"]),
            _box_rect(d["footprint"]),
            tuple(_box_rect(t) for t in d["tunnels"]),
        )


def _box_dict(r: Rect) -> dict:
    return {"x": r[0], "y": r[1], "w": r[2] - r[0], "h": r[3] - r[1]}


def _box_rect(b: dict) -> Rect:
    return b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]


def lane_of_slot(slot: dict, tunnels: list[Rect], size: tuple[int, int]) -> Lane:
    """The lane of a placed must-pass scene; the tunnel boxes are cut to the world ``size``."""
    width, height = size
    fp = slot["footprint"]
    kept = []
    for x0, y0, x1, y1 in tunnels:
        box = (max(0, x0), max(0, y0), min(width, x1), min(height, y1))
        if box[0] < box[2] and box[1] < box[3]:
            kept.append(box)
    rect = (fp["x"], fp["y"], fp["x"] + fp["w"], fp["y"] + fp["h"])
    return Lane(slot["encounter_id"], int(slot["layer"]), rect, tuple(kept))


def _window(parts: tuple[Rect, ...], shape: tuple[int, int]) -> Rect:
    """The box round ``parts`` that holds their positions and the hit boxes of those, clipped."""
    h, w = shape
    return (
        max(0, min(p[0] for p in parts) - WINDOW_MARGIN),
        max(0, min(p[1] for p in parts) - WINDOW_MARGIN),
        min(w, max(p[2] for p in parts) + WINDOW_MARGIN),
        min(h, max(p[3] for p in parts) + WINDOW_MARGIN),
    )


def _fit(free: np.ndarray) -> np.ndarray:
    """``out[y, x]``: the collision box with its top-left cell at ``(x, y)`` lies on free cells."""
    h, w = free.shape
    out = np.zeros_like(free)
    if h >= PLAYER_H and w >= PLAYER_W:
        windows = sliding_window_view(free, (PLAYER_H, PLAYER_W))
        out[: h - PLAYER_H + 1, : w - PLAYER_W + 1] = windows.all(axis=(2, 3))
    return out


def _overlapping(shape: tuple[int, int], origin: tuple[int, int], parts: tuple[Rect, ...]):
    """Top-left cells of collision boxes that overlap one of ``parts`` (window coordinates)."""
    ox, oy = origin
    out = np.zeros(shape, dtype=bool)
    for x0, y0, x1, y1 in parts:
        out[
            max(0, y0 - (PLAYER_H - 1) - oy) : max(0, y1 - oy),
            max(0, x0 - (PLAYER_W - 1) - ox) : max(0, x1 - ox),
        ] = True
    return out


def hit_zone(positions: np.ndarray, reach: Reach | None = None) -> np.ndarray:
    """Cells touched by the hit box at any of the collision-box positions (top-left cells).

    Cell ``(y, x)`` is in the hit box of position ``(cy, cx)`` when
    ``cy - up <= y <= cy + PLAYER_H - 1 + down`` and ``cx - left <= x <= cx + PLAYER_W - 1 + right``;
    a summed-area table counts the positions that satisfy this for every cell at once.
    """
    r = reach or player_reach()
    h, w = positions.shape
    table = np.zeros((h + 1, w + 1), dtype=np.int32)
    table[1:, 1:] = positions.cumsum(axis=0).cumsum(axis=1)
    ys, xs = np.arange(h), np.arange(w)
    r0 = np.clip(ys - (PLAYER_H - 1) - r.down, 0, h)
    r1 = np.clip(ys + r.up + 1, 0, h)
    c0 = np.clip(xs - (PLAYER_W - 1) - r.right, 0, w)
    c1 = np.clip(xs + r.left + 1, 0, w)
    count = table[r1][:, c1] - table[r0][:, c1] - table[r1][:, c0] + table[r0][:, c0]
    return count > 0


def lane_zone(grid: np.ndarray, mats: Materials, lane: Lane) -> tuple[Rect, np.ndarray]:
    """``(window, zone)``: the zone of ``lane`` as a mask over ``grid[window]``.

    The footprint of the lane is part of the zone (the free positions in it reach into it); callers
    that look for ambient hazards leave it out.
    """
    x0, y0, x1, y1 = window = _window(lane.parts, grid.shape)
    free = ~mats.kind_mask(grid[y0:y1, x0:x1], "static")
    positions = _fit(free) & _overlapping(free.shape, (x0, y0), lane.parts)
    return window, hit_zone(positions)


def lane_violations(grid: np.ndarray, mats: Materials, lane: Lane) -> np.ndarray:
    """``(x, y)`` rows of the hazard cells in the zone of ``lane``, outside its own footprint."""
    window, zone = lane_zone(grid, mats, lane)
    x0, y0, _, _ = window
    bad = zone & hazard_mask(mats, grid[_slices(window)])
    fx0, fy0, fx1, fy1 = lane.footprint
    bad[max(0, fy0 - y0) : max(0, fy1 - y0), max(0, fx0 - x0) : max(0, fx1 - x0)] = False
    ys, xs = np.nonzero(bad)
    return np.stack([xs + x0, ys + y0], axis=1)


def _slices(rect: Rect) -> tuple[slice, slice]:
    return slice(rect[1], rect[3]), slice(rect[0], rect[2])


# ------------------------------------------------------------------------------------ blast


@dataclass(frozen=True)
class Blast:
    """Where the key of the seal can go off: anywhere in the hall above the plug.

    ``hall`` is the part of the sealed scene's footprint above the plug's top edge: the open hall,
    its pillars and ledges, and the rock walls around them (a bit more than a bomb can reach, never
    less). The zone is every cell within ``radius`` of it.
    """

    hall: Rect
    radius: int  # cells from the hall that stay free of hazards

    @classmethod
    def of_seal(cls, plug: Rect, footprint: Rect) -> Blast:
        """The blast zone of the seal whose plug lies in the scene ``footprint``."""
        return cls((footprint[0], footprint[1], footprint[2], plug[1]), blast_clear_radius())

    def window(self, shape: tuple[int, int]) -> Rect:
        h, w = shape
        x0, y0, x1, y1 = self.hall
        r = self.radius
        return max(0, x0 - r), max(0, y0 - r), min(w, x1 + r), min(h, y1 + r)

    def zone(self, shape: tuple[int, int]) -> tuple[Rect, np.ndarray]:
        """``(window, mask)``: the cells within ``radius`` of the hall."""
        window = self.window(shape)
        x0, y0, x1, y1 = window
        hx0, hy0, hx1, hy1 = self.hall
        xs = np.arange(x0, x1)[None, :]
        ys = np.arange(y0, y1)[:, None]
        dx = np.maximum(np.maximum(hx0 - xs, xs - (hx1 - 1)), 0)
        dy = np.maximum(np.maximum(hy0 - ys, ys - (hy1 - 1)), 0)
        return window, dx * dx + dy * dy <= self.radius**2


def seal_blasts(markers: list[dict]) -> list[Blast]:
    """The blast zone of every ``seal`` marker: its plug and the placed scene that holds it.

    A seal whose plug lies in no placed scene gets no zone here (``clearance_checks`` fails the
    world: the blast cannot be placed without the hall).
    """
    scenes = [m["footprint"] for m in markers if m["type"] == "encounter" and "footprint" in m]
    out = []
    for seal in (m for m in markers if m["type"] == "seal"):
        plug = (seal["x"], seal["y"], seal["x"] + seal["w"], seal["y"] + seal["h"])
        for fp in scenes:
            box = (fp["x"], fp["y"], fp["x"] + fp["w"], fp["y"] + fp["h"])
            if box[0] <= plug[0] and plug[2] <= box[2] and box[1] <= plug[1] and plug[3] <= box[3]:
                out.append(Blast.of_seal(plug, box))
                break
    return out


def blast_clear_radius() -> int:
    """The blast radius of the seal key (from ``spells.json``) plus ``BLAST_MARGIN``."""
    return blast_radius(breaker_spells()) + BLAST_MARGIN


def blast_violations(grid: np.ndarray, mats: Materials, blast: Blast) -> np.ndarray:
    """``(x, y)`` rows of the hazard cells within the clear radius of the hall above the plug."""
    window, zone = blast.zone(grid.shape)
    x0, y0, _, _ = window
    bad = zone & hazard_mask(mats, grid[_slices(window)])
    ys, xs = np.nonzero(bad)
    return np.stack([xs + x0, ys + y0], axis=1)


# ---------------------------------------------------------------------------------- keepout


def keepout_mask(
    grid: np.ndarray, mats: Materials, lanes: list[Lane], blast: Blast | None
) -> np.ndarray:
    """The cells no hazard may be put into: the zones of ``lanes`` and the blast zone."""
    mask = np.zeros(grid.shape, dtype=bool)
    for lane in lanes:
        window, zone = lane_zone(grid, mats, lane)
        mask[_slices(window)] |= zone
    if blast is not None:
        window, zone = blast.zone(grid.shape)
        mask[_slices(window)] |= zone
    return mask
