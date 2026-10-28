"""A scripted bot that plays a generated world from the start to its deepest point.

    python -m noitabench.bots.descend --world-seed 42 --no-enemies --record runs/descend-42

It follows the way to the sealed bottom with per-frame controls only (walking, hops, levitation,
the digging wand, filling and pouring a bottle). The way down leads through the footprint of
every must-pass scene (the generator walls the rest off with brick seams and shells), and the bot
goes through each: it plans without tunnelling inside the footprints of the scenes that are not
dig zones (`scenes.no_dig_mask`), digs through E08 and E12 (the dig zones, mind the plugs next to
lava), fills a bottle at the pool of E07 and crusts its river of lava (`chain.py`), takes the
solvent bottles of E02 and crusts that river (`crossing.py`), fetches the items that open the
seal (the `role: "breaker"` spells), builds the wand that breaks brick in the edit hall above the
plug, throws the bomb onto the plug from a safe distance (`breaker.py`), waits for the lava the
blast may let out to drain, and walks down into the sealed room. If the world has no usable key,
a documented fallback in `seal.py` opens the plug (unless `--require-key`).

The nine must-pass scenes, as the bot plays them:

    E16  levitates over the acid trough (the planner keeps the hit box out of the acid)
    E08  digs through the thin floor of the flooded room; the water runs out (a dig zone)
    E07  takes the empty bottle, fills it at the pool from the rim, crusts the lava (`chain.py`)
    E23  crosses the pool low over the surface (the passage is as high as the player: the hit
         box wets itself, and a pool of sludge poisons)
    E22  the long way: drops through the hole in the floor and walks the lane under it
    E12  digs down through the plugs of rock between the corridors, never the plugs of ground
         beside the lava seams, and walks the corridors on their floors (a dig zone)
    E02  takes the scene's solvent bottles, crusts the river of lava, fetches the bomb
    E06  assembles `[EXPLOSIVE_PROJECTILE, BOMB]` in the edit hall, throws the bomb, runs out of
         its reach, waits for the lava the blast lets out and goes down the breach

The wands are edited only where a player may edit them: the centre of the collision box inside a
`rest_area` or `edit_station` box (`editing.py`, the rule of the agent layer, enforced here by
`ZonedGame`). The combat set-up (spark bolt into the quick wand) happens in the first rest hall,
and only in runs with enemies; the key is assembled in the hall of the plug.

The recording is the one the web viewer plays; next to it go `descend.json` (the summary,
including the must-pass scenes entered and passed) and `bot_log.jsonl` (what the bot decided:
stops, phases, recoveries, the key items, the fallback).

Reading is allowed: this is a test and recording tool, not an agent under evaluation, so it
plans on the whole grid and on the world file: `meta.main_path`, the `seal`, `rest_area` and
`edit_station` markers, the `item` markers with their `role`, and the `encounter` markers with
their `encounter_id`, footprint and `regions` (never shown to an agent). It never reads the rules
(the reaction table, the rule seed): what a liquid does to lava is seen on the grid. Writing is
not allowed: the only calls that are not controls, observation or the wand editor are the seal
fallback's `Game.blast` and `Game.give_spell`, and those are logged as `seal_fallback`.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

from noitabench.game import Controls

from .chain import ChainSolver
from .editing import EditNotAllowed, ZonedGame, edit_zones
from .escape import route_points
from .gunner import Gunner
from .halls import Halls
from .healing import Healer
from .keys import KeyHunt
from .navfield import NO_NODE, NavField, build_field, guide_bias
from .pilot import Pilot
from .scenes import SceneTracker, no_dig_mask, read_scenes
from .seal import (
    SealGeometry,
    SealKey,
    blast_open,
    breaker_spell,
    hand_over_breaker,
)
from .terrain import CONTENT, FORBIDDEN_KEYS, Body, Materials, Terrain, analyse
from .wands import DIGGER, active_wand_has

DEFAULT_STRIDE = 12
DEFAULT_MAX_FRAMES = 24000
EVENT_DRAIN = 30  # frames between reads of the event list
PHASE_FRAMES = 12000  # most any one walk may take
WAYPOINT_REACH = 14.0  # cells: a waypoint of the main path counts as passed this near
FALLBACK_REASON = {  # why the seal is blasted: what became of the key item of the world
    "": "the world has no seal-breaking item (and no spell of the content breaks brick)",
    "unreachable": "the key item cannot be reached",
    "behind_hazard": "the key item lies behind lava or fire",
    "failed": "the key item could not be fetched or did not open the seal",
    "fetched": "the key item was not used",
    "too_weak": "the key item cannot break brick (its explosion is weaker than the seal)",
}
HEAL_CHECK = 15  # frames between looks at the health during a walk
FIRE_WAIT = 60  # frames between two looks at a fire that blocks the way
FIRE_PATIENCE = 1800  # frames the bot waits for a fire to burn out, at most, before it gives up
BOTTOM_TRIES = 4  # walks to the bottom of the sealed room (the way may be on fire at first)
BOTTOM_WAIT = 90  # frames between two of them
CALM_CELLS = 12  # cells of lava, acid and fire on the way down that are not worth waiting for
BOTTOM_PATIENCE = 1800  # frames the bot waits for a way to the bottom that touches no lava
END_HOLD = 90  # frames the bot stands in the sealed room before the run ends


def dig_limit(path: Path | None = None) -> int:
    """The hardest durability the digging bolt removes (spells.json, `DIGGER` explosion)."""
    data = json.loads((path or CONTENT / "spells.json").read_text(encoding="utf-8"))
    for spell in data["spells"]:
        if spell["key"] == "DIGGER":
            return int(spell["projectile"]["explosion"]["max_durability"])
    raise ValueError("spells.json has no DIGGER")


# -- the world ----------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class WorldFiles:
    png: Path
    json: Path


def prepare_world(
    seed: int,
    rule_seed: int,
    out_dir: Path,
    *,
    enemies: bool = True,
    existing: WorldFiles | None = None,
) -> WorldFiles:
    """The world files of `seed` in `out_dir`, without enemy spawns if `enemies` is off.

    The world is generated unless `existing` (a file pair of an earlier generation) is given.
    Every world runs the original reaction table; `rule_seed` only seeds the potion recipes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if existing is None:
        from noitabench.worldgen import generate_world
        from noitabench.worldgen.config import load_materials

        world = generate_world(seed, rule_seed)
        if not enemies:
            world = dataclasses.replace(
                world, markers=[m for m in world.markers if m["type"] != "spawn_enemy"]
            )
        png, js = world.write(out_dir, f"world_{seed}", load_materials())
        return WorldFiles(png, js)
    png = out_dir / f"world_{seed}.png"
    if existing.png.resolve() != png.resolve():
        shutil.copyfile(existing.png, png)
    doc = json.loads(existing.json.read_text(encoding="utf-8"))
    if not enemies:
        doc["markers"] = [m for m in doc["markers"] if m["type"] != "spawn_enemy"]
    js = out_dir / f"world_{seed}.json"
    js.write_text(json.dumps(doc), encoding="utf-8")
    return WorldFiles(png, js)


# -- the run ------------------------------------------------------------------------------------


@dataclasses.dataclass
class Summary:
    world_seed: int
    rule_seed: int
    enemies: bool
    frames: int = 0
    reached_seal: bool = False
    seal_opened: bool = False
    seal_key_found: bool = False
    seal_keys: int = 0  # `role: "breaker"` items the world has
    seal_keys_fetched: int = 0
    seal_key_result: str = ""  # fetched / unreachable / behind_hazard / too_weak / used / failed
    key_results: list[dict[str, str]] = dataclasses.field(default_factory=list)
    hazard_solved: bool = False  # a river of lava was crusted with the encounter's own solvent
    bombs: int = 0  # bombs thrown at the plug
    fallback_used: bool = False
    fallback_tool: str = ""
    reached_bottom: bool = False
    depth_y: int = 0  # deepest row the player's feet reached
    depth_fraction: float = 0.0
    deaths: int = 0
    digs: int = 0  # digging-bolt casts
    shots: int = 0  # other casts
    hp_min: float = 100.0
    hp_final: float = 100.0
    recoveries: int = 0
    replans: int = 0
    hops: int = 0
    waypoints: int = 0  # points of the generator's main path
    waypoints_passed: int = 0  # ... the player came within WAYPOINT_REACH of
    scenes: list[dict[str, Any]] = dataclasses.field(default_factory=list)  # must-pass scenes
    scenes_passed: int = 0  # ... the bot entered and left downwards
    wand_edits: dict[str, int] = dataclasses.field(default_factory=dict)  # edits per zone type
    stop_reason: str = ""
    state_hash: str = ""


class Stop(NamedTuple):
    """A thing the bot does on its way down, placed at the depth `y` where it happens."""

    y: float
    label: str
    run: Callable[[], None]


class Descent(KeyHunt, ChainSolver, Healer, Halls):
    """One run of the bot on one world."""

    def __init__(
        self,
        files: WorldFiles,
        *,
        rule_seed: int | None = None,
        enemies: bool = True,
        max_frames: int = DEFAULT_MAX_FRAMES,
        seal_fallback: bool = True,
    ) -> None:
        self.mats = Materials.load()
        self.body = Body.load()
        self.dig_durability = dig_limit()
        self.doc = json.loads(files.json.read_text(encoding="utf-8"))
        # the potion recipes of the rule seed the world was built for, unless asked for others
        rule_seed = int(self.doc.get("rule_seed", 0)) if rule_seed is None else rule_seed
        self.game = ZonedGame.from_world(files.png, files.json, rule_seed=rule_seed)
        self.game.zones = edit_zones(self.doc["markers"])  # wands are edited in these, nowhere else
        self.max_frames = max_frames
        self.seal_fallback = seal_fallback
        self.summary = Summary(
            world_seed=int(self.doc["seed"]), rule_seed=rule_seed, enemies=enemies
        )
        self.frames = 0
        self.log: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()
        self.pickups: list[dict[str, Any]] = []  # the `pickup` events of the run
        self.key_in_hand = False  # a key item of the world was picked up
        self.fetched: list[SealKey] = []  # ... the ones that were
        self.phase = "start"  # what the bot is doing, for the log
        self._p: dict[str, Any] = self._player()
        self.waypoints: list[tuple[int, int]] = [
            (int(x), int(y)) for x, y in self.doc.get("meta", {}).get("main_path", [])
        ]
        self.guide = guide_bias((self.game.height, self.game.width), self.waypoints)
        self.route = route_points(self.waypoints)
        self._wp = np.array(self.waypoints, dtype=float).reshape(-1, 2)
        self._passed: set[int] = set()
        self.scenes = read_scenes(self.doc["markers"])  # the must-pass ones
        self.all_scenes = read_scenes(self.doc["markers"], must_pass=False)
        self.tracker = SceneTracker(self.scenes)
        self._no_dig = no_dig_mask(
            (self.game.height, self.game.width), self.scenes, (self.body.w, self.body.h)
        )
        self.armed = False  # the spark bolt sits in the quick wand
        self.healing = False  # a drink (and the walk to fetch it) is under way
        self.pilot: Pilot | None = None
        self.pilot_stats: Counter[str] = Counter()
        self.gunner = Gunner(
            self.game, frozenset(self.game.enemy_kinds()), self.body.hand_dx, self.body.hand_dy
        )
        seal_marker = next((m for m in self.doc["markers"] if m["type"] == "seal"), None)
        if seal_marker is None:
            raise ValueError("the world has no seal marker")
        self.geometry = SealGeometry.read(self.game.grid_array(), self.mats, seal_marker)

    # -- Driver interface (seal.py) -------------------------------------------------------------

    def note(self, event: str, **fields: Any) -> None:
        self.log.append({"frame": self.game.frame, "event": event, **fields})

    def seal_open(self) -> bool:
        return self.geometry.is_open(self.game.grid_array(), self.mats, self.body.w)

    def step(self, controls: Controls) -> dict[str, Any]:
        """One frame under `controls`; returns the player afterwards."""
        self.game.step(1, controls)
        self.frames += 1
        self._p = self._player()
        p = self._p
        s = self.summary
        s.depth_y = max(s.depth_y, int(p["y"]) + int(p["h"]))
        s.hp_min = min(s.hp_min, float(p["hp"]))
        if p["dead"] and not s.deaths:
            s.deaths = 1
            self.note("died", phase=self.phase, x=p["x"], y=p["y"])
        self.tracker.update(self.game.frame, p)
        if controls.get("fire") and active_wand_has(p, DIGGER):  # (whoever asked for the cast)
            self.tracker.note_dig(p)
        if self.frames % EVENT_DRAIN == 0:
            self._drain()
        if self.frames % 4 == 0 and len(self._wp):
            near = (
                np.hypot(self._wp[:, 0] - (p["x"] + 2), self._wp[:, 1] - (p["y"] + 3))
                <= WAYPOINT_REACH
            )
            self._passed.update(int(i) for i in np.nonzero(near)[0])
        return p

    def _player(self) -> dict[str, Any]:
        p = self.game.player()
        if p is None:
            raise RuntimeError("the game has no player")
        return p

    def _drain(self) -> None:
        for e in self.game.events():
            if e["type"] == "cast":
                self.counts["digs" if "DIGGER" in e["spells"] else "shots"] += 1
            elif e["type"] in ("death", "pickup"):
                self.counts[e["type"]] += 1
                if e["type"] == "pickup":
                    self.pickups.append(e)
            elif e["type"] == "overflow":  # the sim's event buffer was full: some were lost
                self.note("event_overflow", dropped=e.get("dropped"))

    # -- planning -------------------------------------------------------------------------------

    def terrain_now(self, *, dig: bool = True) -> Terrain:
        """The terrain as it is now. With `dig` the box may take positions that need digging,
        except where a scene is to be passed without a tunnel (`scenes.no_dig_mask`); with it off
        nowhere."""
        terrain = analyse(
            self.game.grid_array(), self.mats, self.body, dig_max_durability=self.dig_durability
        )
        if not dig:
            return dataclasses.replace(terrain, diggable=terrain.free)
        return dataclasses.replace(
            terrain, diggable=np.where(self._no_dig, terrain.free, terrain.diggable)
        )

    def plan(self, goal: tuple[int, int], *, dig: bool = True) -> tuple[Terrain, NavField]:
        """The terrain as it is now and the way to `goal` (a box position); with `dig` off the
        way is one a walker, hopper and flier can take without the digging wand."""
        terrain = self.terrain_now(dig=dig)
        return terrain, build_field(terrain, goal, self.guide)

    def front_goal(self) -> tuple[int, int]:
        """The box position standing on the seal plug."""
        plug = self.geometry.plug
        terrain = self.terrain_now()
        return self._stand_near(terrain, plug.cx - self.body.w // 2, plug.y - self.body.h)

    def bottom_goal(self) -> tuple[int, int]:
        """The lowest floor of the sealed room, nearest to the breach, and clear of lava, acid
        and fire where the room has such a place (a blast can let lava run into the room)."""
        room, w, h = self.geometry.room, self.body.w, self.body.h
        terrain = self.terrain_now()
        ok = terrain.free & terrain.grounded
        for mask in (ok & ~terrain.near_hazard, ok):
            sub = mask[room.y : room.bottom - h + 1, room.x : room.x + room.w - w + 1]
            ys, xs = np.nonzero(sub)
            if len(ys):
                break
        else:
            raise ValueError("the sealed room has no floor to stand on")
        deepest = ys.max()
        row = xs[ys == deepest]
        x = int(row[np.argmin(np.abs(row + room.x - (self.geometry.plug.cx - w // 2)))]) + room.x
        return x, int(deepest) + room.y

    def hazard_in_the_way(self) -> int:
        """Cells of lava, acid and fire between the front of the plug and the sealed room, around
        the breach (a blast can let a lava lake run down the hole: it is not safe to go down
        while it flows)."""
        plug, room = self.geometry.plug, self.geometry.room
        grid = self.game.grid_array()
        window = grid[plug.y - 30 : room.y, max(0, plug.x - 45) : plug.x + plug.w + 45]
        return int(np.isin(window, self.mats.ids(FORBIDDEN_KEYS)).sum())

    def wait_for_calm(self) -> None:
        """Stand by until little lava, acid or fire is left on the way down
        (`hazard_in_the_way` at most `CALM_CELLS`, or the same count three times in a row: what
        is left sits still), at most `BOTTOM_PATIENCE` frames."""
        last, same = -1, 0
        for _ in range(BOTTOM_PATIENCE // BOTTOM_WAIT):
            cells = self.hazard_in_the_way()
            same = same + 1 if cells == last else 0
            if cells <= CALM_CELLS or same >= 2:
                return
            last = cells
            self.note("bottom_hazard", cells=cells)
            for _ in range(BOTTOM_WAIT):
                self.step({})

    @staticmethod
    def _stand_near(terrain: Terrain, x: int, y: int, radius: int = 12) -> tuple[int, int]:
        ok = terrain.free & terrain.grounded
        best = None
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < terrain.width and 0 <= yy < terrain.height and ok[yy, xx]:
                    d = dx * dx + 3 * dy * dy
                    if best is None or d < best[0]:
                        best = (d, xx, yy)
        if best is None:
            raise ValueError(f"nowhere to stand near {(x, y)}")
        return best[1], best[2]

    # -- fire -----------------------------------------------------------------------------------

    def fire_cells(self) -> int:
        """Cells of fire in the world: a burning pool of oil or a cloud of gas blocks a way until
        it has burnt out (the planner takes fire for lava)."""
        return int(np.count_nonzero(self.game.grid_array() == self.mats.index("fire")))

    def wait_out_fire(self, why: str, waited: int = 0) -> int:
        """Stand by for `FIRE_WAIT` frames if fire burns anywhere and `waited` frames of
        patience are left; returns the patience used up (`waited` + the wait), or -1 if there
        is no fire to wait for or no patience left."""
        cells = self.fire_cells()
        if cells == 0 or waited >= FIRE_PATIENCE or self._p["dead"]:
            return -1
        if waited == 0:
            self.note("fire_wait", why=why, cells=cells)
        for _ in range(FIRE_WAIT):
            self.step({})
        return waited + FIRE_WAIT

    # -- walking --------------------------------------------------------------------------------

    def _start_pilot(self, label: str, goal: tuple[int, int]) -> Pilot | None:
        """The pilot for a walk to `goal`, made the current one; None if the player is somewhere
        the way to the goal does not lead (the walk is noted as unreachable). A fire that cut the
        way is waited out first."""
        terrain, field = self.plan(goal)
        waited = 0
        while field.nearest_node(int(self._p["x"]), int(self._p["y"])) == NO_NODE:
            waited = self.wait_out_fire(label, waited)  # (a fire may have cut the way)
            if waited < 0:
                break
            try:
                terrain, field = self.plan(goal)
            except ValueError:  # the fire or a flow took the goal itself
                self.note("unreachable", phase=label, goal=goal, why="the goal was lost")
                return None
        pilot = Pilot(
            self.mats,
            terrain,
            field,
            self.game.grid_array(),
            rebuild=lambda: self.plan(goal),
            hazard_ids=self.mats.ids(FORBIDDEN_KEYS),
        )
        self._retire_pilot()
        self.pilot = pilot
        if field.nearest_node(int(self._p["x"]), int(self._p["y"])) == NO_NODE:
            self.note("unreachable", phase=label, goal=goal)
            return None
        return pilot

    def walk_to(
        self,
        label: str,
        goal: tuple[int, int],
        *,
        tolerance: int = 2,
        max_frames: int = PHASE_FRAMES,
        stop: Callable[[], bool] | None = None,
        arrive: bool = True,
    ) -> bool:
        """Walk to the box position `goal`; False if the player died, ran out of frames or the
        goal cannot be reached. `stop`, asked once per frame, ends the walk early (True). With
        `arrive` off, getting there does not end the walk: the pilot holds the place (and goes
        back to it if something moves the player) until `stop` or the frames are up."""
        pilot = self._start_pilot(label, goal)
        if pilot is None:
            return False
        self.note("walk", phase=label, goal=goal)
        self.phase = label
        start = self.frames
        while self.frames < self.max_frames and self.frames - start < max_frames:
            p = self._p
            if p["dead"]:
                return False
            if self.frames % HEAL_CHECK == 0 and self.wants_heal() and self.heal():
                self.pilot = pilot  # (the walk to a potion made its own)
                continue
            if (
                arrive
                and abs(p["x"] - goal[0]) <= tolerance
                and abs(p["y"] - goal[1]) <= tolerance
                and p["on_ground"]
            ):
                self.note("arrived", phase=label, x=p["x"], y=p["y"])
                return True
            if stop is not None and stop():
                self.note("stopped", phase=label, x=p["x"], y=p["y"])
                return True
            if self.frames % pilot.config.grid_refresh == 0 or pilot.digging:
                pilot.grid = self.game.grid_array()
            controls = pilot.decide(p, self.game.frame)
            self.gunner.assist(controls, p, self.game.frame, digging=pilot.digging)
            self.step(controls)
        self.note("gave_up", phase=label, x=self._p["x"], y=self._p["y"])
        return False

    def _retire_pilot(self) -> None:
        """Add the stats of the pilot that is done to the run's totals."""
        if self.pilot is not None:
            self.pilot_stats.update(self.pilot.stats)
            self.log += [
                {"frame": f, "event": "stuck", "x": x, "y": y, "recovery": what}
                for f, x, y, what in self.pilot.log
            ]
            self.pilot.stats = dict.fromkeys(self.pilot.stats, 0)  # (counted: not twice)
            self.pilot.log = []
            self.pilot = None

    # -- the whole run --------------------------------------------------------------------------

    def run(self) -> Summary:
        s = self.summary
        try:
            self._run()
        finally:
            self._drain()
            s.frames = self.frames
            s.digs, s.shots = self.counts["digs"], self.counts["shots"]
            s.bombs = sum(e["event"] == "blast_thrown" for e in self.log)
            s.depth_fraction = round(s.depth_y / self.game.height, 4)
            s.waypoints, s.waypoints_passed = len(self.waypoints), len(self._passed)
            s.scenes = [v.asdict() for v in self.tracker.visits]
            s.scenes_passed = len(self.tracker.passed)
            s.wand_edits = dict(Counter(zone for _, zone, _ in self.game.edits()))
            s.hp_final = float(self._p["hp"])
            self._retire_pilot()
            st = self.pilot_stats
            s.recoveries, s.replans, s.hops = st["recoveries"], st["replans"], st["hops"]
            s.state_hash = f"{self.game.state_hash():016x}"
        return s

    def tour(self, keys: list[SealKey]) -> list[Stop]:
        """What the bot does on the way to the seal, shallowest first: rest in the halls, solve
        the chain of E07, fetch the key items."""
        stops: list[Stop] = []
        for index in (1, 2):
            marker = self.hall_marker(index)
            if marker is not None:
                stops.append(
                    Stop(
                        marker["y"] + marker["h"] / 2,
                        f"rest_{index}",
                        lambda i=index: self.visit_hall(i),  # type: ignore[misc]
                    )
                )
        for scene in self.scenes:
            if scene.eid == "E07":
                stops.append(
                    Stop(
                        scene.footprint.y,
                        "chain",
                        lambda sc=scene: self.solve_chain(sc),  # type: ignore[misc]
                    )
                )
        for key in keys:
            stops.append(
                Stop(
                    key.center[1],
                    f"key_{key.detail or key.kind}",
                    lambda k=key: self.fetch_one(k),  # type: ignore[misc]
                )
            )
        return sorted(stops, key=lambda st: st.y)

    def _run(self) -> None:
        s = self.summary
        for stop in self.tour(self.find_keys()):
            self.note("stop", label=stop.label, y=stop.y)
            stop.run()
            if self._p["dead"]:
                s.stop_reason = "died"
                return
        self.sum_up_keys()
        try:
            front = self.front_goal()
        except ValueError as err:  # no place to stand on top of the seal
            s.stop_reason = f"no way to the seal: {err}"
            return
        if not self.walk_to("to_seal", front):
            s.stop_reason = "died" if s.deaths else "could not reach the seal"
            return
        s.reached_seal = True
        if not self.seal_open():
            self._break_seal()
        s.seal_opened = self.seal_open()
        if not s.seal_opened:
            s.stop_reason = "died" if s.deaths else "the seal stayed closed"
            return
        for attempt in range(BOTTOM_TRIES):  # a blast leaves fires and gas: the way clears soon
            self.wait_for_calm()
            try:
                bottom = self.bottom_goal()
            except ValueError as err:  # the sealed room has no floor to stand on
                s.stop_reason = f"no way to the bottom: {err}"
                return
            if self.walk_to("to_bottom", bottom, tolerance=3):
                break
            if s.deaths or attempt == BOTTOM_TRIES - 1:
                s.stop_reason = "died" if s.deaths else "could not reach the bottom"
                return
            for _ in range(BOTTOM_WAIT):
                self.step({})
        s.reached_bottom = True
        s.stop_reason = "reached the bottom"
        for _ in range(END_HOLD):  # a moment of standing there, for the recording
            self.step({})

    def _break_seal(self) -> None:
        """Open the plug: with the key items of the world if they are enough, else the fallback."""
        self.phase = "seal"
        try:
            opened = self._try_keys()
        except EditNotAllowed as err:  # no edit station by the plug (an older world file)
            self.note("edit_not_allowed", why=str(err))
            opened = False
        if opened or not self.seal_fallback:
            return
        self.summary.fallback_used = True
        tools: list[str] = []
        opened = False
        spell = breaker_spell(self.mats)  # the content may have a spell that breaks brick by now
        if spell is not None:
            tools.append(f"Game.give_spell({spell})")
            opened = hand_over_breaker(self, spell, self.geometry)
        if not opened:
            tools.append("Game.blast")
            reason = FALLBACK_REASON.get(self.summary.seal_key_result, FALLBACK_REASON[""])
            self.note(
                "seal_fallback_done", blasts=blast_open(self, self.geometry, self.mats, reason)
            )
        self.summary.fallback_tool = " + ".join(tools)
        for _ in range(20):  # the plug is open: let the player drop
            self.step({})


def play_world(
    seed: int,
    rule_seed: int,
    out_dir: Path,
    *,
    enemies: bool = False,
    max_frames: int = DEFAULT_MAX_FRAMES,
    seal_fallback: bool = True,
) -> tuple[Summary, list[dict[str, Any]]] | None:
    """Generate the world of `(seed, rule_seed)`, play it and return the summary and the bot's
    log; None if the generator cannot make that world. Module-level and picklable-in/out, so a
    test can run several seeds in processes."""
    try:
        files = prepare_world(seed, rule_seed, out_dir, enemies=enemies)
    except RuntimeError:  # generate_world: no valid world in its attempts
        return None
    bot = Descent(files, enemies=enemies, max_frames=max_frames, seal_fallback=seal_fallback)
    summary = bot.run()
    return summary, bot.log


# -- command line -------------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m noitabench.bots.descend",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--world-seed", type=int, required=True)
    p.add_argument("--rule-seed", type=int, default=None, help="default: 0, or the world file's")
    p.add_argument("--no-enemies", action="store_true", help="leave out every enemy spawn")
    p.add_argument("--record", type=Path, help="directory for the recording (runs/descend-N)")
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE, help="frames per recorded frame")
    p.add_argument("--max-frames", type=int, default=DEFAULT_MAX_FRAMES)
    p.add_argument(
        "--world-files",
        nargs=2,
        type=Path,
        metavar=("PNG", "JSON"),
        help="play this world file pair instead of generating the world of --world-seed",
    )
    p.add_argument(
        "--no-seal-fallback",
        "--require-key",
        dest="no_seal_fallback",
        action="store_true",
        help="fail the run at the seal if the world's key items do not open it (do not blast "
        "the plug with the test API)",
    )
    return p.parse_args(argv)


def one_line(s: Summary) -> str:
    fallback = f"fallback used ({s.fallback_tool})" if s.fallback_used else "no fallback"
    keys = f"keys {s.seal_keys_fetched}/{s.seal_keys} ({s.seal_key_result or 'none'})"
    return (
        f"world {s.world_seed}: {s.stop_reason}; depth {s.depth_y} ({s.depth_fraction:.1%}), "
        f"{s.frames} frames, {s.deaths} deaths, {s.digs} digs, {keys}, {fallback}"
    )


def run_cli(args: argparse.Namespace, work: Path) -> int:
    existing = WorldFiles(*args.world_files) if args.world_files else None
    files = prepare_world(
        args.world_seed,
        args.rule_seed or 0,
        work,
        enemies=not args.no_enemies,
        existing=existing,
    )
    bot = Descent(
        files,
        rule_seed=args.rule_seed,
        enemies=not args.no_enemies,
        max_frames=args.max_frames,
        seal_fallback=not args.no_seal_fallback,
    )
    if args.record:
        notes = f"scripted descent, world seed {args.world_seed}"
        notes += ", no enemies" if args.no_enemies else ", with enemies"
        version = bot.doc.get("meta", {}).get("version")
        notes += f", world generator {version}" if version else ""
        bot.game.start_recording(args.record, args.stride, run_id=args.record.name, notes=notes)
    summary = bot.run()
    if args.record:
        bot.game.stop_recording()
        (args.record / "descend.json").write_text(
            json.dumps(dataclasses.asdict(summary), indent=2) + "\n", encoding="utf-8"
        )
        (args.record / "bot_log.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in bot.log), encoding="utf-8"
        )
    print(one_line(summary), file=sys.stderr)
    print(json.dumps(dataclasses.asdict(summary), indent=2))
    return 0 if summary.reached_bottom else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.record:  # the world files stay next to the recording, to replay the same world
        return run_cli(args, args.record / "world")
    with tempfile.TemporaryDirectory(prefix="descend-") as tmp:
        return run_cli(args, Path(tmp))


if __name__ == "__main__":
    sys.exit(main())
