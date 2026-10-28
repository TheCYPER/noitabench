"""Shooting at enemies on the way: the spark wand at the nearest enemy that can be seen.

The gunner only adds `aim`, `fire` and `select_wand` to the controls the pilot built, so the
bot keeps walking while it shoots. It never fires while the pilot is digging, and it holds fire
when a barrel stands in the line of fire (an oil or gunpowder barrel hit by a bolt spills or
blows up around the bot).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from noitabench.game import Controls, Game, aim_at

from .terrain import CONTENT
from .wands import SPARK, wand_with

BARREL_CLEARANCE = 9.0  # px: a barrel this near the line of fire stops the shot
DROP_PER_PX2 = (
    0.00022  # a spark bolt drops about this much per px of range squared (5 cells at 150)
)


def weak_points(path: Path | None = None) -> dict[str, tuple[float, float]]:
    """Where to aim at each enemy kind, from the top-left of its visible box.

    The hit box with the highest damage multiplier (a head), else the middle of the body.
    (`content/entities.json`, `enemies.<kind>.hitboxes`, relative to the collision box.)
    """
    data = json.loads((path or CONTENT / "entities.json").read_text(encoding="utf-8"))
    out: dict[str, tuple[float, float]] = {}
    for kind, spec in data["enemies"].items():
        boxes = spec["hitboxes"]
        left = min(b["dx"] for b in boxes)
        top = min(b["dy"] for b in boxes)
        best = max(boxes, key=lambda b: b.get("mult", 1.0))
        if best.get("mult", 1.0) <= 1.0:  # no weak point: the middle of everything
            right = max(b["dx"] + b["w"] for b in boxes)
            bottom = max(b["dy"] + b["h"] for b in boxes)
            out[kind] = ((right - left) / 2.0, (bottom - top) / 2.0)
        else:
            out[kind] = (best["dx"] + best["w"] / 2.0 - left, best["dy"] + best["h"] / 2.0 - top)
    return out


def _near_segment(
    a: tuple[float, float], b: tuple[float, float], p: tuple[float, float], tol: float
) -> bool:
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    nx, ny = ax + t * dx, ay + t * dy
    return (p[0] - nx) ** 2 + (p[1] - ny) ** 2 <= tol * tol


@dataclass
class Gunner:
    game: Game
    enemy_kinds: frozenset[str]
    hand_dx: int
    hand_dy: int
    aim_offsets: dict[str, tuple[float, float]] = field(default_factory=weak_points)
    range: float = 230.0  # px: nearer than this and in the clear, it is shot at
    refresh: int = 3  # frames between looks at the entity list
    fire_frames: int = 0
    _enemies: list[dict[str, Any]] = field(default_factory=list)
    _barrels: list[dict[str, Any]] = field(default_factory=list)
    _last_look: int = -1000

    def assist(self, controls: Controls, p: dict[str, Any], frame: int, *, digging: bool) -> bool:
        """Add the keys for a shot to `controls`; True if the player is shooting."""
        if digging:
            return False
        if frame - self._last_look >= self.refresh:
            entities = self.game.entities()
            self._enemies = [e for e in entities if e["kind"] in self.enemy_kinds and e["hp"] > 0]
            self._barrels = [e for e in entities if e["kind"].startswith("barrel_")]
            self._last_look = frame
        if not self._enemies:
            return False
        hand = (p["x"] + self.hand_dx + 0.5, p["y"] + self.hand_dy + 0.5)
        target = self._pick(hand)
        if target is None:
            return False
        point = self._aim_point(target)
        distance = ((point[0] - hand[0]) ** 2 + (point[1] - hand[1]) ** 2) ** 0.5
        controls["select_wand"] = wand_with(p, SPARK, 0)
        controls["aim"] = aim_at(hand, (point[0], point[1] - DROP_PER_PX2 * distance * distance))
        controls["fire"] = True
        self.fire_frames += 1
        return True

    def _aim_point(self, e: dict[str, Any]) -> tuple[float, float]:
        ox, oy = self.aim_offsets.get(e["kind"], (e["w"] / 2.0, e["h"] / 2.0))
        return e["x"] + ox, e["y"] + oy

    def _pick(self, hand: tuple[float, float]) -> dict[str, Any] | None:
        best, best_d = None, self.range
        for e in self._enemies:
            point = self._aim_point(e)
            d = ((point[0] - hand[0]) ** 2 + (point[1] - hand[1]) ** 2) ** 0.5
            if d >= best_d:
                continue
            if self.game.raycast(
                int(hand[0]), int(hand[1]), int(point[0]), int(point[1]), "blocking"
            ):
                continue
            if any(
                _near_segment(
                    hand, point, (b["x"] + b["w"] / 2.0, b["y"] + b["h"] / 2.0), BARREL_CLEARANCE
                )
                for b in self._barrels
            ):
                continue
            best, best_d = e, d
        return best
