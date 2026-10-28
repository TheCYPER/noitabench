"""Where the player aims. It is part of the session, stays between commands, and can follow a
creature: every frame the angle is worked out again from the player's hand to the creature, for
as long as the player can see it (the runner passes `None` out of sight and the angle holds)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def angle_between(from_xy: tuple[float, float], to_xy: tuple[float, float]) -> float:
    """Degrees from one point to another: 0 is right, 90 is up (y grows downward)."""
    return math.degrees(math.atan2(-(to_xy[1] - from_xy[1]), to_xy[0] - from_xy[0]))


def normalize_angle(degrees: float) -> float:
    a = math.fmod(degrees, 360.0)
    if a > 180.0:
        a -= 360.0
    elif a <= -180.0:
        a += 360.0
    return a


@dataclass
class Aim:
    """`angle` (a fixed direction), `point` (a world point) or `entity` (follow an id)."""

    mode: str = "angle"
    angle: float = 0.0
    point: tuple[float, float] | None = None
    entity: int | None = None

    def set_angle(self, degrees: float) -> None:
        self.mode, self.angle = "angle", normalize_angle(degrees)
        self.point = self.entity = None

    def set_point(self, x: float, y: float) -> None:
        self.mode, self.point, self.entity = "point", (x, y), None

    def set_entity(self, entity_id: int) -> None:
        self.mode, self.entity, self.point = "entity", entity_id, None

    def resolve(
        self, hand: tuple[float, float], entity_center: tuple[float, float] | None
    ) -> float:
        """The angle for this frame. `entity_center` is where the followed creature is now
        (`None`: it is gone, the last angle holds)."""
        if self.mode == "point" and self.point is not None:
            self.angle = angle_between(hand, self.point)
        elif self.mode == "entity" and entity_center is not None:
            self.angle = angle_between(hand, entity_center)
        return self.angle

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "angle": self.angle,
            "point": list(self.point) if self.point else None,
            "entity": self.entity,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Aim:
        point = tuple(d["point"]) if d.get("point") else None
        return cls(d["mode"], float(d["angle"]), point, d.get("entity"))  # type: ignore[arg-type]
