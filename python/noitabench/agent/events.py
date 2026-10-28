"""From the engine's event log to the short facts an agent is told after a command.

The engine logs far more than a player would notice, some of it hidden by design: `reaction`
events carry the id of a row of the reaction table, which would hand over the rules. This module
is a whitelist. Each kept event becomes `{tick, type, ..., text}`; positions become offsets from
the player ("40 px left"); repeated events (a burning lake, a burst of shots) are merged, and at
most `cap` lines are kept, the ones about the player first. What happens to another creature is
only told when the player can see the place (`sees`): no id, kind or health of a creature behind
a wall. Events with a place further away than the view (the extent of the ASCII map, the one
range of everything the player can see) are not noticed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .engine import position_of
from .vocab import EVENT_TYPES, VIEW_HALF

MERGED = {"cast", "hit", "ignite", "extinguish", "explosion", "damage"}
PLAYER_FIRST = {
    "damage",
    "death",
    "status",
    "pickup",
    "pickup_failed",
    "drop",
    "kick",
    "throw",
    "edit_wand",
    "error",
}
WORLD_LAST = {"ignite", "extinguish", "explosion", "shatter", "barrel_break"}


def where(dx: float, dy: float) -> str:
    """Words for an offset from the player: `40 px left, 12 px up`."""
    if abs(dx) <= 3 and abs(dy) <= 3:
        return "right next to you"
    parts = []
    if abs(dx) > 3:
        parts.append(f"{abs(round(dx))} px {'right' if dx > 0 else 'left'}")
    if abs(dy) > 3:
        parts.append(f"{abs(round(dy))} px {'down' if dy > 0 else 'up'}")
    return ", ".join(parts)


def _num(v: Any) -> float:
    return round(float(v), 1)


class EventCollector:
    """The events of one decision, tick by tick."""

    def __init__(self, view_half: tuple[int, int] = VIEW_HALF) -> None:
        self._view_half = view_half
        self._order: list[str] = []
        self._events: dict[str, dict[str, Any]] = {}
        self._serial = 0

    # -- feeding --------------------------------------------------------------------------------

    def add_tick(
        self,
        tick: int,
        raw: list[dict[str, Any]],
        player: dict[str, Any],
        visible_ids: set[int],
        sees: Callable[[float, float], bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Take the engine events of one tick; returns the agent events it contained (not yet
        merged), for the `event=` stop condition. `sees(x, y)` says whether the player can see a
        place: what happens to other creatures is only noticed where it can be seen."""
        px, py = position_of(player)
        wand_index = {w["id"]: i for i, w in enumerate(player["wands"])}
        kept: list[dict[str, Any]] = []
        for r in raw:
            if r.get("type") not in EVENT_TYPES:
                continue
            ev = _convert(r, tick, px, py, wand_index, visible_ids, sees, self._view_half)
            if ev is None:
                continue
            kept.append(ev)
            self._merge(ev)
        return kept

    def _merge(self, ev: dict[str, Any]) -> None:
        key = _merge_key(ev)
        if key is None:
            self._serial += 1
            key = f"#{self._serial}"
        old = self._events.get(key)
        if old is None:
            self._events[key] = ev
            self._order.append(key)
            return
        old["count"] = old.get("count", 1) + ev.get("count", 1)
        old["last_tick"] = ev["tick"]
        for field in ("amount", "damage", "mana"):
            if field in ev:
                old[field] = _num(old.get(field, 0) + ev[field])
        if "projectiles" in ev:  # a count of shots: stays a whole number
            old["projectiles"] = old.get("projectiles", 0) + ev["projectiles"]
        if "hp" in ev:
            old["hp"] = ev["hp"]
        if "dx" in ev:  # the latest place of a moving thing
            old["dx"], old["dy"] = ev["dx"], ev["dy"]
        old["text"] = _text(old)

    # -- reading --------------------------------------------------------------------------------

    def summary(self, cap: int) -> tuple[list[dict[str, Any]], int]:
        """The events to report: up to `cap`, in time order, and how many were left out."""
        events = [self._events[k] for k in self._order]
        ranked = sorted(range(len(events)), key=lambda i: (events[i]["_rank"], i))
        keep = sorted(ranked[:cap])
        out = [{k: v for k, v in events[i].items() if k[0] != "_"} for i in keep]
        return out, len(events) - len(keep)


def _rank(ev: dict[str, Any], on_player: bool) -> int:
    """0: about the player, 1: about others, 2: the world going on."""
    if ev["type"] in WORLD_LAST:
        return 2
    return 0 if ev["type"] in PLAYER_FIRST and on_player else 1


def _merge_key(ev: dict[str, Any]) -> str | None:
    t = ev["type"]
    if t not in MERGED:
        return None
    bits = {
        "cast": ("spells",),
        "hit": ("projectile", "target", "id"),
        "ignite": ("material",),
        "extinguish": ("material",),
        "explosion": ("radius",),
        "damage": ("target", "id", "source"),
    }[t]
    return t + ":" + ":".join(str(ev.get(b)) for b in bits)


def _convert(
    r: dict[str, Any],
    tick: int,
    px: int,
    py: int,
    wand_index: dict[int, int],
    visible_ids: set[int],
    sees: Callable[[float, float], bool] | None = None,
    view_half: tuple[int, int] = VIEW_HALF,
) -> dict[str, Any] | None:
    t = r["type"]
    ev: dict[str, Any] = {"tick": tick, "frame": r["frame"], "type": t}
    target = r.get("target")
    if "x" in r and "y" in r and t not in ("pickup", "kick"):
        dx, dy = r["x"] - px, r["y"] - py
        if abs(dx) > view_half[0] or abs(dy) > view_half[1]:
            return None
        ev["dx"], ev["dy"] = dx, dy
    unseen = t == "enemy_attack" or target not in (None, "player")
    if unseen and "x" not in r and r.get("id") not in visible_ids:
        return None  # something we cannot see happened to something we cannot see
    if unseen and "x" in r and sees is not None and not sees(r["x"], r["y"]):
        return None  # ... or happened out of sight: no id, kind or health of a hidden creature
    if t == "damage" and r.get("source") == "hit":
        return None  # told by the `hit` event of the same shot
    copy = {
        "cast": ("spells", "projectiles", "mana"),
        "hit": ("projectile", "target", "id", "damage", "crit"),
        "damage": ("target", "id", "amount", "source", "hp"),
        "death": ("target", "id", "source"),
        "status": ("target", "id", "status", "active"),
        "pickup": ("item", "detail"),
        "pickup_failed": ("item",),
        "drop": ("item", "detail"),
        "kick": ("hits",),
        "throw": ("material", "cells"),
        "shatter": ("material", "cells"),
        "barrel_break": ("kind", "id", "burning"),
        "enemy_attack": ("enemy", "id", "projectiles"),
        "explosion": ("radius",),
        "ignite": ("material", "by"),
        "extinguish": ("material",),
        "error": ("message",),
    }.get(t, ())
    for name in copy:
        if name in r:
            ev[name] = r[name]
    if t == "damage" and target not in (None, "player"):
        ev.pop("hp", None)  # how much health another creature has left is for `inspect` to say
    if t == "cast" and "wand" in r:
        ev["wand"] = wand_index.get(r["wand"], 0)
    if t == "edit_wand":
        ev["wand"] = wand_index.get(r.get("wand", -1), 0)
    for name in ("amount", "damage", "mana", "hp"):
        if name in ev:
            ev[name] = _num(ev[name])
    ev["_rank"] = _rank(ev, target in (None, "player"))
    ev["text"] = _text(ev)
    return ev


def _who(ev: dict[str, Any]) -> str:
    if ev.get("target") == "player":
        return "you"
    return f"{ev.get('target')} #{ev.get('id')}"


def _stuff(material: str) -> str:
    """`water+oil` (the keys of a mixture) as words."""
    return material.replace("+", " and ")


def _times(ev: dict[str, Any]) -> str:
    n = ev.get("count", 1)
    return f" x{n}" if n > 1 else ""


def _place(ev: dict[str, Any]) -> str:
    return f" {where(ev['dx'], ev['dy'])}" if "dx" in ev else ""


def _text(ev: dict[str, Any]) -> str:
    t = ev["type"]
    if t == "cast":
        return f"You cast {ev['spells']}{_times(ev)} (mana {ev['mana']})."
    if t == "hit":
        crit = " (critical)" if ev.get("crit") else ""
        return f"{ev['projectile']} hit {_who(ev)} for {ev['damage']}{crit}{_times(ev)}."
    if t == "damage":
        who = "You took" if ev["target"] == "player" else f"{_who(ev)} took"
        left = f"; HP {ev['hp']}" if "hp" in ev else ""
        return f"{who} {ev['amount']} damage ({ev['source']}){_times(ev)}{left}."
    if t == "death":
        return "You died." if ev["target"] == "player" else f"{_who(ev)} died."
    if t == "status":
        who = "You are" if ev["target"] == "player" else f"{_who(ev)} is"
        return f"{who} {'now' if ev['active'] else 'no longer'} {ev['status']}."
    if t == "pickup":
        detail = f" ({ev['detail']})" if ev.get("detail") else ""
        return f"You picked up a {ev['item']}{detail}."
    if t == "pickup_failed":
        return f"You cannot carry another {ev['item']}."
    if t == "drop":
        detail = f" ({ev['detail']})" if ev.get("detail") else ""
        return f"You dropped a {ev['item']}{detail}."
    if t == "kick":
        hits = ev["hits"]
        return "You kicked at nothing." if not hits else f"You kicked and hit {hits} thing(s)."
    if t == "throw":
        return f"You threw a bottle of {_stuff(ev['material'])} ({ev['cells']} cells)."
    if t == "shatter":
        return (
            f"A bottle of {_stuff(ev['material'])} broke{_place(ev)}; {ev['cells']} cells spilled."
        )
    if t == "barrel_break":
        burning = ", burning" if ev.get("burning") else ""
        return f"A {ev['kind']} broke{_place(ev)}{burning}."
    if t == "enemy_attack":
        return f"{ev['enemy']} #{ev['id']} attacked."
    if t == "edit_wand":
        return f"You rearranged wand {ev['wand']}."
    if t == "explosion":
        return f"Explosion (radius {ev['radius']}){_place(ev)}{_times(ev)}."
    if t == "ignite":
        return f"{ev['material']} caught fire{_place(ev)}{_times(ev)}."
    if t == "extinguish":
        return f"Fire on {ev['material']} went out{_place(ev)}{_times(ev)}."
    return str(ev.get("message", t))
