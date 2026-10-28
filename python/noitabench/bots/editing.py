"""Where the bot may rearrange its wands: the same rule the agent layer enforces.

`edit_wand` is a player-level action that is allowed only while the centre of the player's
collision box lies in a `rest_area` or `edit_station` box of the world file (contracts section 4;
`agent/engine.py` `edit_zone_at`). Agents are held to it by the agent layer. The bot talks to the
`Game` directly, so it holds itself to the same rule: `ZonedGame` is a `Game` whose `edit_wand`
refuses to run anywhere else (`EditNotAllowed`), and the places that edit (the combat set-up in
the first rest hall, the assembling of the seal key in the hall above the plug) walk there first.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from noitabench.game import Game

EDIT_ZONE_TYPES = ("rest_area", "edit_station")

Zone = tuple[str, int, int, int, int]  # (marker type, x, y, w, h)


class EditNotAllowed(RuntimeError):
    """The wands were to be edited outside a rest area and an edit station."""


def edit_zones(markers: Iterable[dict[str, Any]]) -> list[Zone]:
    """The boxes where wands may be edited, from the markers of the world file."""
    return [
        (str(m["type"]), int(m["x"]), int(m["y"]), int(m["w"]), int(m["h"]))
        for m in markers
        if m.get("type") in EDIT_ZONE_TYPES and all(k in m for k in ("x", "y", "w", "h"))
    ]


def zone_at(zones: Iterable[Zone], p: dict[str, Any]) -> Zone | None:
    """The zone the centre of the player's collision box lies in, if any."""
    x, y = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
    for zone in zones:
        _, bx, by, bw, bh = zone
        if bx <= x < bx + bw and by <= y < by + bh:
            return zone
    return None


class ZonedGame(Game):
    """A `Game` that lets the wands be edited only inside the `zones` (set after loading), and
    keeps a log of the edits: `(frame, zone type, op)`. Without `zones` (None) there is no rule,
    like a bare `Game`."""

    zones: list[Zone] | None = None
    _edit_log: list[tuple[int, str, str]] | None = None

    def edits(self) -> list[tuple[int, str, str]]:
        """The wand edits so far: `(frame, zone type, op)`."""
        return list(self._edit_log or [])

    def edit_wand(self, action: dict[str, Any]) -> None:
        if self.zones is not None:
            p = self.player()
            zone = None if p is None else zone_at(self.zones, p)
            if zone is None:
                where = (
                    "nowhere"
                    if p is None
                    else f"({p['x'] + p['w'] / 2:.0f}, {p['y'] + p['h'] / 2:.0f})"
                )
                raise EditNotAllowed(f"edit_wand {action.get('op')} at {where}: not in a rest area")
            if self._edit_log is None:
                self._edit_log = []
            self._edit_log.append((self.frame, zone[0], str(action.get("op"))))
        super().edit_wand(action)
