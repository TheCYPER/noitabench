"""Staying alive: drink a healing potion when hurt.

The world has healing potions lying about (a `potion_heal` item is a bottle of 400 cells; a drink
of all of it heals to full). When the health drops under `HEAL_BELOW` the bot drinks the one it
carries; if it carries none, it fetches the nearest within reach first. This is the only thing
the bot does about burns and poison on a long way down: the pools of the rest halls are far
apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .bottles import bottle_total, holding

if TYPE_CHECKING:
    from noitabench.game import Controls, Game

HEAL_BELOW = 0.55  # share of the health under which the bot looks for a drink
HEAL_UNTIL = 0.9  # ... and drinks until it is this healthy
POTION_REACH = 40.0  # cells: a potion further away than this is not worth a detour
DRINK_FRAMES = 90  # most a drink may take
POTION = "potion_heal"


class Healer:
    """The methods of `Descent` that heal it (a mixin)."""

    if TYPE_CHECKING:
        game: Game
        _p: dict[str, Any]
        healing: bool

        def note(self, event: str, **fields: Any) -> None: ...
        def step(self, controls: Controls) -> dict[str, Any]: ...
        def fetch_entity(self, entity: dict[str, Any], *, label: str, key: Any = None) -> str: ...

    def wants_heal(self) -> bool:
        p = self._p
        return not self.healing and not p["dead"] and p["hp"] < HEAL_BELOW * p["hp_max"]

    def potion_in_hand(self) -> int | None:
        return holding(self._p, frozenset({POTION}))

    def nearest_potion(self) -> dict[str, Any] | None:
        """The healing potion lying nearest to the player, within `POTION_REACH`."""
        p = self._p
        cx, cy = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
        best, best_d = None, POTION_REACH
        for e in self.game.entities():
            if e["kind"] != POTION:
                continue
            d = ((e["x"] + e["w"] / 2 - cx) ** 2 + (e["y"] + e["h"] / 2 - cy) ** 2) ** 0.5
            if d < best_d:
                best, best_d = e, d
        return best

    def heal(self) -> bool:
        """Drink a healing potion (fetching one near by if none is carried). True if the bot
        drank. Not re-entered by the walks it makes to fetch."""
        self.healing = True
        try:
            index = self.potion_in_hand()
            if index is None:
                potion = self.nearest_potion()
                if potion is None or self.fetch_entity(potion, label="potion") != "fetched":
                    return False
                index = self.potion_in_hand()
                if index is None:
                    return False
            hp0 = float(self._p["hp"])
            for _ in range(DRINK_FRAMES):
                p = self.step({"select_bottle": index, "drink": True})
                if (
                    p["dead"]
                    or p["hp"] >= HEAL_UNTIL * p["hp_max"]
                    or bottle_total(p["bottles"][index]) == 0
                ):
                    break
            self.step({})  # let go of the key: the drink is written up
            self.note("healed", hp_before=round(hp0, 1), hp_after=round(float(self._p["hp"]), 1))
            return True
        finally:
            self.healing = False
