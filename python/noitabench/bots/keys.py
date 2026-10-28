"""Fetching the items that open the seal and using them: the `KeyHunt` mixin of `Descent`.

The world gives the bot `role: "breaker"` spells (E02's bomb, E12's modifier). For each one, shallowest
first, it walks to the item and takes it; if the item's encounter provides `role: "solvent"` bottles
it takes those first and crusts the river of lava that lies in the way (`crossing.py`). At the seal
the spells in hand are put into a wand and the bomb is thrown (`breaker.py`); `escape_goal` is what
that module asks the bot for: a place to run to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from .breaker import break_with_loadout, plan_loadout
from .crossing import clear_lava
from .escape import candidates, far_places, frames_between
from .navfield import NO_NODE, build_field
from .seal import SealKey, find_seal_keys, nearest_item, use_key
from .spellinfo import best_reach

if TYPE_CHECKING:
    from noitabench.game import Controls, Game

    from .descend import Summary
    from .scenes import Scene
    from .seal import SealGeometry
    from .terrain import Body, Materials, Terrain

FRAMES_PER_NODE = 1.0  # frames a step of a planned way takes (walking, hopping, levitating)
ESCAPE_TRIES = 6  # places on the way back that are looked at before others are
FAR_TRIES = 12  # ... and others (any standing place far enough)
HAZARD_TAIL = 70  # steps at the end of the way to an item that are looked at for lava and acid
FETCH_FRAMES = 4000  # most the detour for the key item may take


def _is_pickup_of(event: dict[str, Any], entity: dict[str, Any]) -> bool:
    """Whether a `pickup` event is the taking of this very item (by id when the event has one)."""
    if "id" in event and "id" in entity:
        return int(event["id"]) == int(entity["id"])
    return event["item"] == entity["kind"] and event["detail"] == entity.get("detail")


class KeyHunt:
    """The methods of `Descent` that deal with the seal's key items (a mixin)."""

    if TYPE_CHECKING:  # what Descent provides
        game: Game
        mats: Materials
        body: Body
        dig_durability: int
        guide: np.ndarray
        route: list[tuple[int, int]]
        doc: dict[str, Any]
        summary: Summary
        fetched: list[SealKey]
        key_in_hand: bool
        pickups: list[dict[str, Any]]
        geometry: SealGeometry
        all_scenes: list[Scene]
        phase: str
        _p: dict[str, Any]

        def note(self, event: str, **fields: Any) -> None: ...
        def terrain_now(self, *, dig: bool = True) -> Terrain: ...
        def wait_out_fire(self, why: str, waited: int = 0) -> int: ...
        def step(self, controls: Controls) -> dict[str, Any]: ...
        def _drain(self) -> None: ...
        def walk_to(
            self, label: str, goal: tuple[int, int], *, tolerance: int = 2, max_frames: int = ...
        ) -> bool: ...
        @staticmethod
        def _stand_near(terrain: Any, x: int, y: int, radius: int = 12) -> tuple[int, int]: ...

    def reach(self, centre: tuple[float, float]) -> tuple[str, tuple[int, int] | None, int]:
        """Whether the item at `centre` can be got to on foot: `("ok" | "unreachable" |
        "hazard", where to stand, steps of the cheapest way where the hit box touches lava,
        acid or fire)`. The planner keeps clear of hazards where it can, so a way that still
        touches one has no other: the item is behind it. A hazard that only lies near the way
        (a lava seam under a thin floor) is the pilot's business, not a reason to stay away."""
        terrain = self.terrain_now()
        cx, cy = centre
        try:
            goal = self._stand_near(terrain, int(cx) - self.body.w // 2, int(cy) - self.body.h + 2)
        except ValueError:  # the item lies in rock, brick or lava: nowhere to stand beside it
            return "unreachable", None, 0
        field = build_field(terrain, goal, self.guide)
        here = field.nearest_node(int(self._p["x"]), int(self._p["y"]))
        if here == NO_NODE:
            return "unreachable", goal, 0
        # only the end of the way counts: lava beside the way far from the item (a pocket over a
        # corridor, say) is a cost of getting there, not a reason to stay away from the item
        path = field.path_from(here)[-HAZARD_TAIL:]
        exposure = sum(int(terrain.contact[y, x]) for x, y in path)
        return ("hazard" if exposure else "ok"), goal, exposure

    def take(self, entity: dict[str, Any]) -> bool:
        """Press the pick-up key beside an item until that item is in hand (the nearest item is
        taken first: press again for the next one)."""
        self.phase = "pick_up"
        for i in range(30):
            self.step({"interact": i % 2 == 0})
            self._drain()
            if any(_is_pickup_of(e, entity) for e in self.pickups):
                self.note("picked_up", item=entity["kind"], detail=entity.get("detail", ""))
                return True
        self.note("pickup_failed", item=entity["kind"])
        return False

    def fetch_entity(
        self, entity: dict[str, Any], *, label: str, key: SealKey | None = None
    ) -> str:
        """Walk to an item and pick it up: `"fetched"`, `"unreachable"`, `"behind_hazard"` or
        `"failed"`. Lava or fire around the item is the encounter's puzzle: for a key whose
        encounter gives a solvent the bot takes the bottles and crusts the lava first
        (`cross_hazard`). It only walks, hops, flies, pours and digs."""
        centre = (entity["x"] + entity["w"] / 2, entity["y"] + entity["h"] / 2)
        event = "seal_key" if key is not None else label  # the names of the notes in the log
        status, goal, exposure = self.reach(centre)
        waited = 0
        while status != "ok" and waited >= 0:  # a fire may have cut the way: wait for it
            waited = self.wait_out_fire(label, waited)
            if waited >= 0:
                status, goal, exposure = self.reach(centre)
        if key is not None and goal is not None and self.solvent_items(key):
            self.cross_hazard(key, goal)
            status, goal, exposure = self.reach(centre)
        if status == "unreachable" or goal is None:
            self.note(
                f"{event}_unreachable", item=entity["kind"], at=(int(centre[0]), int(centre[1]))
            )
            return "unreachable"
        if status == "hazard":
            self.note(f"{event}_behind_hazard", goal=goal, hazard_nodes=exposure)
            return "behind_hazard"
        if not self.walk_to(f"fetch_{label}", goal, tolerance=3, max_frames=FETCH_FRAMES):
            return "failed"
        return "fetched" if self.take(entity) else "failed"

    def fetch(self, key: SealKey) -> str:
        """Fetch a key item of the seal; the status of `fetch_entity`."""
        status = self.fetch_entity(key.entity, label="key", key=key)
        if status == "fetched":
            self.key_in_hand = True
            self.fetched.append(key)
        return status

    def solvent_items(self, key: SealKey) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """The bottles the encounter of `key` gives to solve its puzzle: `(marker, bottle)` for
        every `role: "solvent"` item marker of the same scene (the footprint that holds the key's
        marker, else the world near it) whose bottle is still lying in the world."""
        entities = self.game.entities()
        eid = key.marker.get("encounter_id")
        kx, ky = key.marker["x"], key.marker["y"]
        scene = next((s for s in self.all_scenes if s.eid == eid and s.contains(kx, ky)), None)
        taken: set[int] = set()
        out: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for m in self.doc["markers"]:
            if m.get("type") != "item" or m.get("role") != "solvent" or not m.get("contents"):
                continue
            if scene is not None:
                elsewhere = not scene.contains(m["x"], m["y"])
            elif eid is not None:
                elsewhere = m.get("encounter_id") != eid
            else:
                elsewhere = abs(m["x"] - kx) > 150 or abs(m["y"] - ky) > 150
            if elsewhere:
                continue
            bottle = nearest_item(m, entities, taken)
            if bottle is not None:
                taken.add(int(bottle["id"]))
                out.append((m, bottle))
        return out

    def cross_hazard(self, key: SealKey, goal: tuple[int, int]) -> bool:
        """Take the encounter's solvent bottles and crust the lava that a walk (no digging) from
        here to `goal` crosses (`crossing.clear_lava`); True once such a walk touches no lava.
        The cheapest way with the digging wand goes around the chamber through the rock, which
        is not the puzzle: the walk is what the encounter is built for."""
        items = self.solvent_items(key)
        if not items:
            return False
        self.note("crossing_start", solvents=sorted({m["contents"] for m, _ in items}))
        for _, bottle in items:
            if self.fetch_entity(bottle, label="solvent") != "fetched":
                self.note("solvent_missed", at=(bottle["x"], bottle["y"]))
        cleared = clear_lava(self, goal, {m["contents"] for m, _ in items})
        self.summary.hazard_solved = self.summary.hazard_solved or cleared
        return cleared

    def find_keys(self) -> list[SealKey]:
        """The key items of the world, the shallowest first (the way down passes them in that
        order); notes how many there are in the summary."""
        keys = find_seal_keys(self.doc["markers"], self.game.entities())
        self.summary.seal_keys, self.summary.seal_key_found = len(keys), bool(keys)
        return sorted(keys, key=lambda k: k.center[1])

    def fetch_one(self, key: SealKey) -> None:
        """Fetch one key item and record how that went in the summary."""
        self.note("seal_key", item=key.kind, detail=key.detail)
        status = self.fetch(key)
        self.summary.key_results.append({"item": key.kind, "detail": key.detail, "result": status})

    def sum_up_keys(self) -> None:
        """Say in the summary how many key items were fetched and what became of the others."""
        s = self.summary
        s.seal_keys_fetched = len(self.fetched)
        missed = [r["result"] for r in s.key_results if r["result"] != "fetched"]
        s.seal_key_result = (missed[0] if missed else "fetched") if s.seal_keys else ""

    def fetch_keys(self) -> None:
        """Fetch every key item of the world in one go and sum up in the summary."""
        for key in self.find_keys():
            self.fetch_one(key)
            if self._p["dead"]:
                break
        self.sum_up_keys()

    def _try_keys(self) -> bool:
        """Use the key items in hand on the plug; True if it opened. Spells are combined into
        one wand (`breaker.plan_loadout`); a wand or bottle is tried as it is."""
        if not self.fetched:
            return False
        s = self.summary
        spells = [k.detail for k in self.fetched if k.kind == "spell"]
        brick = int(self.mats.durability[self.mats.index("brick")])
        wands = self._p["wands"]
        loadout = plan_loadout(
            spells,
            brick,
            slots=max((sum(slot is None for slot in w["slots"]) for w in wands), default=0),
            mana_max=max((float(w["stats"]["mana_max"]) for w in wands), default=0.0),
        )
        opened = False
        if loadout is not None:
            opened = break_with_loadout(self, loadout, self.geometry)
            self.note("seal_key_used", opened=opened, spells=list(loadout.spells))
        elif spells:
            self.note(
                "seal_key_too_weak",
                item="spell",
                detail=",".join(spells),
                explosion_durability=best_reach(spells),
            )
            s.seal_key_result = "too_weak"
        tried = loadout is not None
        for key in self.fetched:
            if opened or key.kind == "spell":
                continue
            tried = True
            opened = use_key(self, key, self.geometry)
            self.note("seal_key_used", opened=opened, item=key.kind)
        if opened or tried:  # (a spell too weak for brick was not tried: "too_weak" stays)
            s.seal_key_result = "used" if opened else "failed"
        return opened

    # -- BlastDriver (breaker.py) -----------------------------------------------------------

    def escape_goal(
        self, centre: tuple[float, float], distance: float, budget: int
    ) -> tuple[int, int] | None:
        """A place `distance` cells from `centre` that the bot gets to in `budget` frames: first
        on the way it came (`escape.candidates`), then anywhere standing (`escape.far_places`);
        None if there is none."""
        terrain = self.terrain_now()
        p = self._p
        here = (int(p["x"]), int(p["y"]))
        tries, too_far = 0, False
        for spot, standing in candidates(terrain, self.route, centre, distance):
            if standing and too_far:  # the later ones are further along the way
                continue
            if tries >= ESCAPE_TRIES:
                break
            tries += 1
            frames = frames_between(terrain, here, spot, FRAMES_PER_NODE)
            if frames is not None and frames <= budget:
                return spot
            too_far = too_far or standing
        for spot in far_places(terrain, centre, distance, here)[:FAR_TRIES]:
            frames = frames_between(terrain, here, spot, FRAMES_PER_NODE)
            if frames is not None and frames <= budget:
                return spot
        return None
