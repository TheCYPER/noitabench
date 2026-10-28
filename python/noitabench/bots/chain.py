"""E07, the chain: a pool and an empty bottle, a trough of acid, a river of lava under a roof.

The pool is the only supply of liquid in the scene. The acid trough is flown over; the river of
lava is crusted with the pool's liquid. So the bot takes the empty bottle, wades to a spot where
the bottle's scoop reaches the pool and fills it (`fill`), then on its way to the exit pours the
bottle onto the lava (`crossing.clear_lava`) and walks over the crust. It only reads the grid
(what the liquid in the pool is and where the scoop reaches it); what the liquid does to the
lava is seen on the grid after the pour, as in `crossing.py`.

Test tool: the empty bottle is found by its marker (`role: "container"`, the world file's item
markers, never shown to an agent) and the pool by the scene's `regions` of the same file.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

import numpy as np

from .bottles import bottle_total, empty_bottle
from .crossing import clear_lava
from .scenes import Scene, exit_spot
from .seal import nearest_item
from .terrain import LIQUID, hit_sum

if TYPE_CHECKING:
    from noitabench.game import Controls, Game

    from .terrain import Body, Materials, Terrain

SCOOP = (14, 12)  # cells a fill reaches: wide and tall, centred on the player's feet
FILL_FRAMES = 150  # most a fill may take
FILL_STALL = 25  # frames without more liquid in the bottle that end a fill
BURST = 6  # frames of one pour (about 50 cells): the pool's liquid is all there is
ENOUGH = 40  # cells in the bottle that are enough to crust a river
MIN_SCOOP = 12  # liquid cells within the scoop that make a spot worth filling at
DRIFT = 3  # cells the player may stand off the place it walks to (the walk's tolerance)
RIM_REACH = 12  # cells around the pool where the bot looks for a spot to fill at


def pool_liquid(grid: np.ndarray, mats: Materials, scene: Scene) -> str | None:
    """The liquid most of the pool's region holds (a material key), or None."""
    pool = scene.regions.get("pool")
    if pool is None:
        return None
    cells = grid[pool.y : pool.y + pool.h, pool.x : pool.x + pool.w]
    liquid = cells[mats.kind[cells] == LIQUID]
    if liquid.size == 0:
        return None
    return mats.keys[Counter(liquid.tolist()).most_common(1)[0][0]]


def fill_spot(
    grid: np.ndarray,
    mats: Materials,
    terrain: Terrain,
    scene: Scene,
    material: str,
    *,
    dry_only: bool = False,
    wading: bool = False,
) -> tuple[int, int] | None:
    """The standing place (a box position) near the pool from where a scoop reaches the most
    cells of `material`, preferring places where the hit box stays out of the liquid (a pool of
    sludge poisons whoever wades in it; `dry_only` takes no other; `wading` does not mind where
    the hit box is); of equal ones the nearest to the pool."""
    pool = scene.regions["pool"]
    body: Body = terrain.body
    sw, sh = SCOOP
    wanted = grid == mats.index(material)
    others = (mats.kind[grid] == LIQUID) & ~wanted  # a scoop takes every liquid it reaches
    # the liquid the hit box touches, for the positions of the window around the pool
    x0, y0 = max(0, pool.x - RIM_REACH - 20), max(0, pool.y - body.h - RIM_REACH - 20)
    x1, y1 = (
        min(terrain.width, pool.x + pool.w + RIM_REACH + 20),
        min(terrain.height, pool.bottom + 20),
    )
    touch = hit_sum(wanted[y0:y1, x0:x1], body.hit)
    ok = terrain.free & terrain.grounded
    best_key: tuple[int, int, float] | None = None
    best_spot: tuple[int, int] | None = None
    for y in range(max(0, pool.y - body.h - RIM_REACH), min(terrain.height, pool.bottom + 1)):
        for x in range(max(0, pool.x - RIM_REACH), min(terrain.width, pool.x + pool.w + RIM_REACH)):
            if not ok[y, x]:
                continue
            ax, ay = x + body.w // 2 - sw // 2, y + body.h - sh // 2
            window = (slice(max(0, ay), ay + sh), slice(max(0, ax), ax + sw))
            n = int(wanted[window].sum())
            if n < MIN_SCOOP:
                continue
            wide = (  # the player may stop a little off the place: keep other liquids out of reach
                slice(max(0, ay - DRIFT), ay + sh + DRIFT),
                slice(max(0, ax - DRIFT), ax + sw + DRIFT),
            )
            if others[wide].any():
                continue
            dry = int(touch[y - y0, x - x0] == 0)  # the hit box is out of the liquid
            if dry_only and not dry:
                continue
            d = abs(x + body.w / 2 - (pool.x + pool.w / 2)) + abs(y + body.h - pool.y)
            key = (0 if wading else dry, n, -d)
            if best_key is None or key > best_key:
                best_key, best_spot = key, (x, y)
    return best_spot


class ChainSolver:
    """The methods of `Descent` that solve E07 (a mixin)."""

    if TYPE_CHECKING:
        game: Game
        mats: Materials
        body: Body
        doc: dict[str, Any]
        _p: dict[str, Any]

        def note(self, event: str, **fields: Any) -> None: ...
        def step(self, controls: Controls) -> dict[str, Any]: ...
        def terrain_now(self, *, dig: bool = True) -> Terrain: ...
        def walk_to(
            self, label: str, goal: tuple[int, int], *, tolerance: int = 2, max_frames: int = ...
        ) -> bool: ...
        def fetch_entity(self, entity: dict[str, Any], *, label: str, key: Any = None) -> str: ...

    def container_bottle(self, scene: Scene) -> dict[str, Any] | None:
        """The empty bottle of the scene, still lying in the world."""
        entities = self.game.entities()
        for m in self.doc["markers"]:
            if m.get("type") != "item" or m.get("role") != "container":
                continue
            if m.get("encounter_id") not in (None, scene.eid) or not scene.contains(m["x"], m["y"]):
                continue  # (the world may hold another E07 as an optional scene)
            found = nearest_item(m, entities)
            if found is not None:
                return found
        return None

    def fill_up(self, scene: Scene, material: str) -> bool:
        """Fill the empty bottle at the pool: first from the rim, with the hit box out of the
        liquid; if that gets too little, wading in. True if the bottle holds something."""
        held = 0
        index = empty_bottle(self._p)
        for rim in (True, False):
            spot = fill_spot(
                self.game.grid_array(),
                self.mats,
                self.terrain_now(),
                scene,
                material,
                dry_only=rim,
                wading=not rim,
            )
            if spot is None or index is None:
                continue
            if not self.walk_to("to_pool", spot, tolerance=2, max_frames=3000):
                return False
            held = self.scoop(index)
            self.note("filled", material=material, cells=held, at=spot, rim=rim)
            if held >= ENOUGH:
                break
        return held > 0

    def scoop(self, index: int) -> int:
        """Hold the fill key until the bottle `index` is full or stops getting more; the cells
        it holds."""
        held, stalled = 0, 0
        for _ in range(FILL_FRAMES):
            p = self.step({"select_bottle": index, "fill": True})
            total = bottle_total(p["bottles"][index])
            stalled = stalled + 1 if total <= held else 0
            held = max(held, total)
            if stalled >= FILL_STALL or p["dead"]:
                break
        self.step({})  # let go of the key: the fill is written up
        return held

    def solve_chain(self, scene: Scene) -> None:
        """Take the bottle, fill it at the pool, crust the lava on the way to the exit."""
        bottle = self.container_bottle(scene)
        material = pool_liquid(self.game.grid_array(), self.mats, scene)
        self.note("chain_start", bottle=bottle is not None, pool=material)
        if bottle is None or material is None:
            return
        if self.fetch_entity(bottle, label="container") != "fetched":
            return
        if not self.fill_up(scene, material):
            return
        goal = exit_spot(self.game.grid_array(), self.mats, self.terrain_now(), scene)
        if goal is None:
            self.note("chain_no_exit")
            return
        cleared = clear_lava(self, goal, {material}, burst=BURST)  # type: ignore[arg-type]
        self.note("chain_lava", cleared=cleared)
        self.walk_to("leave_chain", goal, tolerance=3, max_frames=4000)
