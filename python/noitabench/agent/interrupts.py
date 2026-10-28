"""Interrupts (tick-design 4.4): events that stop a running command on a tick boundary.

Four are on by default: damage, a new hostile creature in view (once per creature), a new
status of the player, and a command that cannot go on (blocked by a wall). Three are
off until something turns them on (the harness hooks of layer L3, or a script): falling into a
liquid, HP dropping below a threshold, a material in view that was never seen before. The game
never reacts for the agent: it only stops and hands the control back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .vocab import ALL_INTERRUPTS, DEFAULT_INTERRUPTS, WALL_MESSAGE

# Order in which simultaneous interrupts are reported (the first is the main reason).
ORDER = (
    "damage",
    "new_enemy",
    "status_change",
    "blocked",
    "fell_in_liquid",
    "hp_low",
    "new_material",
)


@dataclass
class Triggered:
    name: str
    message: str


@dataclass
class Interrupts:
    """Which interrupts are on, and what the agent has already been told."""

    enabled: set[str] = field(default_factory=lambda: set(DEFAULT_INTERRUPTS))
    hp_threshold: float = 30.0
    seen_hostiles: set[int] = field(default_factory=set)
    seen_materials: set[int] = field(default_factory=set)
    statuses: set[str] = field(default_factory=set)
    submerged: bool = False
    hp: float | None = None
    material_sync: bool = False  # `new_material` was just turned on: what is in view is not new

    # -- switches (the hook interface) ------------------------------------------------------------

    def enable(self, name: str, *, hp_below: float | None = None) -> None:
        if name not in ALL_INTERRUPTS:
            raise ValueError(f"unknown interrupt {name!r}; choose from {', '.join(ALL_INTERRUPTS)}")
        self.enabled.add(name)
        if name == "new_material":
            self.material_sync = True
        if hp_below is not None:
            self.hp_threshold = float(hp_below)

    def disable(self, name: str) -> None:
        if name not in ALL_INTERRUPTS:
            raise ValueError(f"unknown interrupt {name!r}; choose from {', '.join(ALL_INTERRUPTS)}")
        self.enabled.discard(name)

    # -- the check --------------------------------------------------------------------------------

    def observe(
        self,
        player: dict[str, Any],
        visible: list[dict[str, Any]],
        hostile_ids: set[int],
        raw_events: list[dict[str, Any]],
        materials_in_view: set[int],
        submerged: bool,
        blocked: str | None,
        material_names: tuple[str, ...],
    ) -> list[Triggered]:
        """Compare the state at a tick boundary with the one before; returns what fired."""
        fired: dict[str, str] = {}
        hp = float(player["hp"])
        hurt = any(
            e.get("type") == "damage" and e.get("target") == "player" and e.get("amount", 0) > 0
            for e in raw_events
        )
        if hurt or (self.hp is not None and hp < self.hp - 1e-6):
            fired["damage"] = "You took damage."
        newcomers = sorted(i for i in hostile_ids if i not in self.seen_hostiles)
        if newcomers:
            fired["new_enemy"] = _newcomers_message(newcomers, visible)
        new_status = sorted(set(player["statuses"]) - self.statuses)
        if new_status:
            fired["status_change"] = "You are now " + ", ".join(new_status) + "."
        if blocked is not None:  # a command that cannot go on: it is stuck against a wall
            fired["blocked"] = WALL_MESSAGE
        if submerged and not self.submerged:
            fired["fell_in_liquid"] = "You are in a liquid."
        if self.hp is not None and hp < self.hp_threshold <= self.hp:
            fired["hp_low"] = f"Your HP is below {self.hp_threshold:g}."
        fresh = sorted(materials_in_view - self.seen_materials)
        if self.material_sync and materials_in_view:
            fresh, self.material_sync = [], False
        if fresh:
            fired["new_material"] = "You see " + ", ".join(material_names[i] for i in fresh) + "."
        self.seen_hostiles |= hostile_ids
        self.seen_materials |= materials_in_view
        self.statuses = set(player["statuses"])
        self.submerged = submerged
        self.hp = hp
        return [Triggered(n, fired[n]) for n in ORDER if n in fired and n in self.enabled]

    # -- snapshots --------------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": sorted(self.enabled),
            "hp_threshold": self.hp_threshold,
            "seen_hostiles": sorted(self.seen_hostiles),
            "seen_materials": sorted(self.seen_materials),
            "statuses": sorted(self.statuses),
            "submerged": self.submerged,
            "hp": self.hp,
            "material_sync": self.material_sync,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Interrupts:
        return cls(
            enabled=set(d["enabled"]),
            hp_threshold=float(d["hp_threshold"]),
            seen_hostiles=set(d["seen_hostiles"]),
            seen_materials=set(d["seen_materials"]),
            statuses=set(d["statuses"]),
            submerged=bool(d["submerged"]),
            hp=d["hp"],
            material_sync=bool(d.get("material_sync", False)),
        )


def _newcomers_message(ids: list[int], visible: list[dict[str, Any]]) -> str:
    from .events import where

    by_id = {e["id"]: e for e in visible}
    parts = []
    for i in ids:
        e = by_id.get(i)
        if e is not None:
            parts.append(f"{e['kind']} #{i} {where(e['dx'], e['dy'])}")
    return "Came into view: " + "; ".join(parts) + "."
