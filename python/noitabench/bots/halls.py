"""The rest halls on the way down: the healing pool, the visit and the combat set-up.

Every rest hall (`rest_area` marker) has a pool of healing potion sunk into its floor. A visit
walks to the place where the hit box soaks the most of it and waits until the player is healed.
Wands may be edited in a rest area, so the first visit of a run with enemies also gives the quick
wand the spark bolt (`wands.arm_for_combat`); the edit goes through the zone-checked game
(`editing.ZonedGame`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from .terrain import hit_sum
from .wands import arm_for_combat

if TYPE_CHECKING:
    from noitabench.game import Controls, Game

    from .descend import Summary
    from .gunner import Gunner
    from .terrain import Body, Materials, Terrain

REST_FRAMES = 3000  # most the wait in a healing pool may take
HEAL_UNTIL = 0.97  # the share of health the bot waits for in a healing pool
REST_BELOW = 0.85  # without enemies the bot visits a rest hall only if it is hurt this much
LAST_HALL_BELOW = 0.97  # ... except the second hall, the last before layer 3
REST_MIN_CELLS = 6  # a pool soaks at least this many cells of the hit box to count
REST_WALK_FRAMES = 3000  # most the walk to a hall's pool may take


class Halls:
    """The methods of `Descent` that deal with the rest halls (a mixin)."""

    if TYPE_CHECKING:
        game: Game
        mats: Materials
        body: Body
        doc: dict[str, Any]
        summary: Summary
        gunner: Gunner
        frames: int
        armed: bool
        _p: dict[str, Any]

        def note(self, event: str, **fields: Any) -> None: ...
        def step(self, controls: Controls) -> dict[str, Any]: ...
        def terrain_now(self, *, dig: bool = True) -> Terrain: ...
        def walk_to(
            self, label: str, goal: tuple[int, int], *, tolerance: int = 2, max_frames: int = ...
        ) -> bool: ...

    def hall_marker(self, index: int) -> dict[str, Any] | None:
        """The `rest_area` marker of rest hall `index`."""
        return next(
            (
                m
                for m in self.doc["markers"]
                if m["type"] == "rest_area" and m.get("index") == index
            ),
            None,
        )

    def rest_goal(self, index: int) -> tuple[int, int] | None:
        """The box position in the healing pool of rest hall `index` that soaks the most of it."""
        marker = self.hall_marker(index)
        if marker is None or "potion_heal" not in self.mats.keys:
            return None
        grid = self.game.grid_array()
        terrain = self.terrain_now()
        soak = hit_sum(grid == self.mats.index("potion_heal"), self.body.hit)
        ok = terrain.free & terrain.grounded
        box = np.zeros_like(ok)
        x0, y0, w, h = (int(marker[k]) for k in ("x", "y", "w", "h"))
        box[y0 : y0 + h, x0 : x0 + w] = True
        soak = np.where(ok & box, soak, 0)
        best = int(soak.max())
        if best < REST_MIN_CELLS:
            return None
        ys, xs = np.nonzero(soak == best)
        i = int(np.argmin(np.abs(xs - (x0 + w // 2))))
        return int(xs[i]), int(ys[i])

    def rest(self, index: int) -> bool:
        """Go to rest hall `index` and wait in its healing pool until healed; in the first hall
        of a run with enemies, rearrange the wands for fighting first (`edit_wand` is allowed in
        a rest area). False if the bot died."""
        goal = self.rest_goal(index)
        if goal is None:
            return True
        if not self.walk_to(f"rest_{index}", goal, tolerance=3, max_frames=REST_WALK_FRAMES):
            return not self._p["dead"]
        if self.summary.enemies and not self.armed and arm_for_combat(self.game):
            self.armed = True
            self.note("armed", what="spark bolt in the quick wand, digging bolt in the other")
        start = self.frames
        while self.frames - start < REST_FRAMES and not self._p["dead"]:
            p = self._p
            if p["hp"] >= HEAL_UNTIL * p["hp_max"]:
                break
            controls: Controls = {}
            self.gunner.assist(controls, p, self.game.frame, digging=False)
            self.step(controls)
        self.note(
            "rested", hall=index, hp=round(float(self._p["hp"]), 1), frames=self.frames - start
        )
        return not self._p["dead"]

    def visit_hall(self, index: int) -> None:
        """A stop at a rest hall: always with enemies (to arm and heal), else only if hurt."""
        p = self._p
        below = LAST_HALL_BELOW if index >= 2 else REST_BELOW
        if self.summary.enemies or p["hp"] < below * p["hp_max"]:
            self.rest(index)
