"""The only module of the agent layer that touches `noitabench.game.Game`.

It steps the game one frame at a time with the controls of the current command, and answers the
questions the commands and the observations ask: where the player is, what is in view, what the
grid looks like around. The `Game` object itself never leaves this class (contracts section 11,
"What agents may see").

Coordinates: world cells, origin top left, y grows down. The *position* of the player is the
free cell it stands in: the column of the middle of its collision box and the row of its feet
(what `spawn_player` takes).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from noitabench.game import Game

from .content import Content
from .vocab import STEP_UP, VIEW_HALF

OUTSIDE = 255  # in a grid window: not part of the world
EDIT_ZONE_TYPES = ("rest_area", "edit_station")
POINT_SLACK = 2  # cells: a wall this close to a place does not hide it


def position_of(p: dict[str, Any]) -> tuple[int, int]:
    """The `(x, y)` cell a player dict stands in."""
    return p["x"] + p["w"] // 2, p["y"] + p["h"] - 1


def hit_center(p: dict[str, Any]) -> tuple[float, float]:
    x, y, w, h = p["hit"]
    return x + w / 2, y + h / 2


def box_center(e: dict[str, Any]) -> tuple[float, float]:
    return e["x"] + e["w"] / 2, e["y"] + e["h"] / 2


def public_kind(kind: str) -> str:
    """The kind an agent is told for something in view: a bottle of a potion is just a bottle
    (what is in it comes only from `inspect`)."""
    return "bottle" if kind.startswith("potion_") else kind


class Engine:
    """A game seen through the questions of the agent layer."""

    def __init__(
        self, game: Game, content: Content, view_half: tuple[int, int] = VIEW_HALF
    ) -> None:
        self._game = game
        self.content = content
        self.view_half = view_half  # how far the player sees: the extent of the ASCII map
        built = tuple(game.material_keys())
        if content.material_keys[: len(built)] != built:  # a module older than the file is fine
            raise ValueError(
                "content/materials.json does not match the built game module: rebuild "
                "noitabench_core (maturin develop) or point the session at the matching content"
            )
        if game.player() is None:
            raise ValueError("the world has no player: nothing to play")
        self.width, self.height = game.width, game.height
        self.enemy_kinds = frozenset(game.enemy_kinds())
        self._zones = _edit_zones(game.markers())

    # -- time and controls ----------------------------------------------------------------------

    @property
    def frame(self) -> int:
        return self._game.frame

    def step(self, controls: dict[str, Any]) -> None:
        self._game.step(1, controls)

    def drain_events(self) -> list[dict[str, Any]]:
        return self._game.events()

    # -- the player -----------------------------------------------------------------------------

    def player(self) -> dict[str, Any]:
        """The player dict of the game (its `on_ground` is read from the grid as it is now)."""
        p = self._game.player()
        assert p is not None  # checked at construction; the player is never removed
        return p

    def end_bottle_action(self) -> None:
        """A drink, pour or fill has stopped: let the game write its summary now."""
        self._game.end_bottle_action()

    def edit_zone_at(self, p: dict[str, Any]) -> str | None:
        """Type of the rest area or edit station the player stands in, if any."""
        x, y = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
        for kind, bx, by, bw, bh in self._zones:
            if bx <= x < bx + bw and by <= y < by + bh:
                return kind
        return None

    def edit_wand(self, action: dict[str, Any]) -> None:
        self._game.edit_wand(action)

    # -- looking around -------------------------------------------------------------------------

    def entities(self) -> list[dict[str, Any]]:
        return self._game.entities()

    def entity(self, entity_id: int) -> dict[str, Any] | None:
        return next((e for e in self._game.entities() if e["id"] == entity_id), None)

    def in_view(self, p: dict[str, Any], x: float, y: float) -> bool:
        """Is the cell `(x, y)` inside the view rectangle (no wall test)?"""
        px, py = hit_center(p)
        return abs(x - px) <= self.view_half[0] and abs(y - py) <= self.view_half[1]

    def visible(self, p: dict[str, Any], entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """What the player can see of `entities`, nearest first: inside the view rectangle (the
        extent of the ASCII map, `view_half`) and
        with a line to it that no wall blocks. Each gets `cx, cy` (centre), `dx, dy` (from the
        player) and `dist`."""
        px, py = hit_center(p)
        out: list[dict[str, Any]] = []
        for e in entities:
            if e["kind"] == "player":
                continue
            cx, cy = box_center(e)
            dx, dy = cx - px, cy - py
            if abs(dx) > self.view_half[0] or abs(dy) > self.view_half[1]:
                continue
            if not self._line_clear(px, py, e):
                continue
            out.append(
                {
                    **e,
                    "cx": cx,
                    "cy": cy,
                    "dx": round(dx),
                    "dy": round(dy),
                    "dist": (dx * dx + dy * dy) ** 0.5,
                }
            )
        out.sort(key=lambda e: (e["dist"], e["id"]))
        return out

    def sees(self, p: dict[str, Any], e: dict[str, Any]) -> bool:
        """Can the player see this one entity (the test `visible` applies to a whole list)?"""
        return bool(self.visible(p, [e]))

    def sees_point(self, p: dict[str, Any], x: float, y: float) -> bool:
        """Can the player see the place `(x, y)`: inside the view rectangle with no wall on the
        line to it (a wall cell right at the place itself does not hide it)?"""
        px, py = hit_center(p)
        if abs(x - px) > self.view_half[0] or abs(y - py) > self.view_half[1]:
            return False
        hit = self._game.raycast(int(px), int(py), int(x), int(y), "blocking")
        return hit is None or (
            abs(hit["x"] - x) <= POINT_SLACK and abs(hit["y"] - y) <= POINT_SLACK
        )

    def _line_clear(self, px: float, py: float, e: dict[str, Any]) -> bool:
        cx, cy = box_center(e)
        hit = self._game.raycast(int(px), int(py), int(cx), int(cy), "blocking")
        if hit is None:
            return True
        # a wall cell that is part of the target's own box does not hide it
        return (
            e["x"] - 1 <= hit["x"] <= e["x"] + e["w"] and e["y"] - 1 <= hit["y"] <= e["y"] + e["h"]
        )

    def window(self, x0: int, y0: int, w: int, h: int) -> np.ndarray:
        """Material indices of a rectangle of the world, `OUTSIDE` where it leaves the world."""
        grid = np.frombuffer(self._game.grid(), dtype=np.uint8).reshape(self.height, self.width)
        out = np.full((h, w), OUTSIDE, dtype=np.uint8)
        gx0, gy0 = max(x0, 0), max(y0, 0)
        gx1, gy1 = min(x0 + w, self.width), min(y0 + h, self.height)
        if gx0 < gx1 and gy0 < gy1:
            out[gy0 - y0 : gy1 - y0, gx0 - x0 : gx1 - x0] = grid[gy0:gy1, gx0:gx1]
        return out

    def burning(self, x0: int, y0: int, w: int, h: int) -> np.ndarray:
        """Which cells of a rectangle of the world are burning, as a `(h, w)` array of 0 and 1
        (`Game.burning_rect`; 0 outside the world). Read-only; the same rectangle as `window`."""
        flat = np.frombuffer(self._game.burning_rect(x0, y0, w, h), dtype=np.uint8)
        return flat.reshape(h, w)

    def cell(self, x: int, y: int) -> dict[str, Any]:
        return self._game.cell(x, y)

    def in_world(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    # -- questions about walking ----------------------------------------------------------------

    def has_ground(self, x: int, y: int, w: int, h: int, depth: int) -> bool:
        """Is there something to stand on in the columns of a box at `(x, y)` within `depth`
        cells below its feet (or a step up to its feet)?"""
        area = self._game.overlap(x, y + h - STEP_UP, w, STEP_UP + depth)
        kinds = area["kinds"]
        return bool(kinds.get("static", 0) or kinds.get("powder", 0))

    def submerged(self, p: dict[str, Any]) -> bool:
        area = self._game.overlap(p["x"], p["y"], p["w"], p["h"])
        return area["kinds"].get("liquid", 0) * 2 >= p["w"] * p["h"]

    def overlap(self, x: int, y: int, w: int, h: int) -> dict[str, Any]:
        return self._game.overlap(x, y, w, h)

    # -- state ----------------------------------------------------------------------------------

    def snapshot(self) -> bytes:
        return self._game.snapshot()

    def restore(self, blob: bytes) -> None:
        self._game.restore(blob)

    def state_hash(self) -> int:
        return self._game.state_hash()

    def start_recording(self, directory: str, stride: int, notes: str) -> None:
        self._game.start_recording(directory, stride, notes=notes)

    def stop_recording(self) -> dict[str, Any]:
        return self._game.stop_recording()

    def hostile(self, e: dict[str, Any]) -> bool:
        return e["kind"] in self.enemy_kinds


def _edit_zones(markers: list[dict[str, Any]]) -> list[tuple[str, int, int, int, int]]:
    """Boxes where wands may be edited. Read from the world markers and never passed on."""
    zones: list[tuple[str, int, int, int, int]] = []
    for m in markers:
        if m.get("type") in EDIT_ZONE_TYPES and all(k in m for k in ("x", "y", "w", "h")):
            zones.append((m["type"], int(m["x"]), int(m["y"]), int(m["w"]), int(m["h"])))
    return zones
