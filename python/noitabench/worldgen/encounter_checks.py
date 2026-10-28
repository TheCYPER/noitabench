"""Post-generation checks of the placed encounters (world-design 2.5, "遭遇点可解").

For every encounter marker that has a scene (``placeholder`` is false):

* **Intact.** The cells of the footprint are the cells of the scene instance the marker
  describes (variant, mirror, liquids); a gate shaft or a tunnel that cut it would show here.
  The sealed deep is only compared at its lock.
* **Solvable under the world's rules.** Every predicate the definition ``requires`` holds for the
  reaction table of the world (``rules``), and every ``supply`` it needs (bottles of the right
  liquid) is lying in the world where the player can walk to it.
* **A true gate.** A must-pass scene that is not a dig zone is a closed box whose only ways from
  the top door to the exit lead through its solution regions (``routes.py``): on the cells of
  the placed footprint, with everything outside it impassable, no route of free or diggable cells
  joins the doors when a gate's regions are blocked, and one does when they are open. The roof
  and the bed of a passage the definition lists as ``sealed`` (a river under a roof, a pool in
  a basin) are brick next to the passage, so a digger cannot tunnel round the obstacle from the
  air above it. The sealed deep is only checked on its art (the gate shaft cuts its hall on
  purpose).
* **Reachable.** Every supply the scene marks with a ``role`` (a solvent bottle, a breaker
  spell) can be walked to from the start without digging (except through dig zones of *other*
  scenes: scenes built to be dug through; a supply that lies in a dig-zone scene must be
  reachable without digging that scene's own zone). Prizes behind the scene's puzzle
  (``reward``, ``container`` ...) are not checked: some lie in rooms that only digging reaches.
* **The key of the seal.** The world holds exactly one item of each breaker spell the scenes hand
  out (the BOMB of E02, the EXPLOSIVE_PROJECTILE of E12), and the spells it holds, assembled in the
  starter spark wand, remove brick (``seal_breakable``, see ``breaker.py``).

The helpers ``dig_zone_mask``, ``lock_mask`` and ``acid_allowed_mask`` serve ``checks.py``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

import numpy as np

from .breaker import best_combo, plug_durability
from .config import Materials
from .encounter_defs import (
    EncounterDef,
    Instance,
    breaker_spells,
    instantiate,
    load_encounters,
)
from .routes import route_problems
from .table import Rules
from .world import World

if TYPE_CHECKING:  # checks.py imports this module
    from .checks import CheckReport

MIN_DISSOLVE = 0.2  # acid has to eat rock at least this often
MIN_SPREAD = 0.15  # fire has to light flammable gas at least this often
REACH_RADIUS = 14
OWN_ZONE_RADIUS = 6  # an item of a dig-zone scene must lie on the walking area itself
SUPPLY_ROLES = ("solvent", "breaker")

# Where the player can walk without digging the dig zone of the scene at ``skip`` (a footprint)
# or, with ``None``, with the dig zones as they are: ``(labels, label of the start)``.
Walk = Callable[[dict | None], tuple[np.ndarray, int]]


def placed_encounters(world: World) -> list[dict]:
    """Encounter markers that carry a scene (not a placeholder)."""
    return [m for m in world.markers if m["type"] == "encounter" and not m.get("placeholder", True)]


def _box(fp: dict) -> tuple[slice, slice]:
    return slice(fp["y"], fp["y"] + fp["h"]), slice(fp["x"], fp["x"] + fp["w"])


def dig_zone_mask(world: World, mats: Materials, passable: np.ndarray) -> np.ndarray:
    """Cells the natural route may cross by digging: diggable cells inside dig-zone scenes."""
    mask = np.zeros(world.grid.shape, dtype=bool)
    defs = load_encounters()
    for m in placed_encounters(world):
        d = defs.get(m["encounter_id"])
        if d is not None and d.dig_zone:
            mask[_box(m["footprint"])] = True
    return mask & passable & mats.kind_mask(world.grid, "static")


def plug_mask(world: World, seal: dict) -> np.ndarray:
    """The cells of the seal's plug (the ``seal`` marker's rectangle)."""
    mask = np.zeros(world.grid.shape, dtype=bool)
    mask[seal["y"] : seal["y"] + seal["h"], seal["x"] : seal["x"] + seal["w"]] = True
    return mask


def acid_allowed_mask(world: World) -> np.ndarray:
    """Footprints of scenes whose definition allows acid cells (brick vats)."""
    mask = np.zeros(world.grid.shape, dtype=bool)
    defs = load_encounters()
    for m in placed_encounters(world):
        d = defs.get(m["encounter_id"])
        if d is not None and d.allow_acid:
            mask[_box(m["footprint"])] = True
    return mask


# ----------------------------------------------------------------------------- predicates


def predicate_holds(
    name: str, rules: Rules, breakers: Iterable[str] | None = None
) -> tuple[bool, str]:
    """Whether the table of ``rules`` supports predicate ``name``; with a reason if not.

    ``seal_breakable`` does not depend on the table: it asks whether the spells in ``breakers``
    (default: every spell the scenes hand out as a breaker) can be assembled in the starter wand
    into an explosion that removes brick.
    """
    if name == "lava_solidifier":
        got = rules.solidifiers()
        return bool(got), "no liquid turns lava into rock"
    if name == "extinguisher":
        return bool(rules.extinguishers()), "no plain liquid puts out fire"
    if name == "seal_breakable":
        spells = sorted(breaker_spells() if breakers is None else set(breakers))
        brick, combo = plug_durability(), best_combo(spells)
        reached = 0 if combo is None else combo.durability
        why = f"the breaker spells {spells} reach durability {reached} in the starter wand"
        return reached >= brick, f"{why}, brick has {brick}"
    if name == "acid_dissolves_rock":
        return (rules.acid_dissolves("rock") or 0.0) >= MIN_DISSOLVE, "acid does not eat rock"
    if name == "fire_ignites_gas":
        return (
            rules.ignites("fire", "flammable_gas") or 0.0
        ) >= MIN_SPREAD, "fire does not light gas"
    raise ValueError(f"unknown predicate {name}")


def _supplies(role: str, item: dict, rules: Rules) -> bool:
    """Whether the item marker ``item`` is a working supply of ``role`` under ``rules``."""
    if item.get("role") != role:
        return False
    if role == "solvent":  # a bottle of a liquid that turns lava into rock
        return item.get("contents") in rules.solidifiers()
    if role == "breaker":  # a spell
        return item.get("item") == "spell" and bool(item.get("spell"))
    raise ValueError(f"unknown supply role {role}")


# ----------------------------------------------------------------------------- the check


def check_encounters(
    world: World,
    rules: Rules,
    mats: Materials,
    rep: CheckReport,
    lab: np.ndarray,
    start_label: int,
    walk: Walk | None = None,
) -> None:
    """Add a failure to ``rep`` for every placed encounter that is broken or unsolvable.

    ``lab`` and ``start_label`` are the walking areas of the world (dig zones count as walkable)
    and the area of the start; ``walk`` recomputes them with one dig zone left undug, for the
    supplies that lie inside a dig-zone scene (default: the same areas for everything).
    """
    defs = load_encounters()
    items = [m for m in world.markers if m["type"] == "item" and m.get("role")]
    reach = _Reach(world, lab, start_label, walk)
    _check_breaker_set(rep, items)
    broken = 0
    for m in placed_encounters(world):
        d = defs.get(m["encounter_id"])
        if d is None:
            rep.failures.append(f"encounter {m['encounter_id']} has no definition")
            continue
        before = len(rep.failures)
        inst = instantiate(d, rules, int(m["variant"]), mats)
        _check_intact(world, rep, d, m, inst)
        _check_gates(world, mats, rep, d, m, inst)
        own = _items_of(items, m)
        _check_requires(rep, rules, d, items, own, reach)
        _check_roles(rep, d, own, reach)
        broken += len(rep.failures) > before
    rep.stats["encounter_scenes"] = len(placed_encounters(world))
    rep.stats["gate_scenes"] = sum(
        1 for m in placed_encounters(world) if _has_gates(defs.get(m["encounter_id"]))
    )
    rep.stats["broken_scenes"] = broken


def _check_breaker_set(rep: CheckReport, items: list[dict]) -> None:
    """The world holds exactly one item of each breaker spell, and nothing else is a breaker.

    A scene that hands out a breaker is placed at most once (``IdPicker``), a second copy of the
    same spell would make the key easier to find than the design says, a missing one makes the
    seal impossible to open.
    """
    held = Counter(str(it.get("spell")) for it in items if it["role"] == "breaker")
    for spell in sorted(breaker_spells()):
        if held[spell] != 1:
            rep.failures.append(
                f"{held[spell]} breaker items of {spell} in the world, exactly one is needed"
            )
    for spell in sorted(set(held) - breaker_spells()):
        rep.failures.append(f"a breaker item of {spell}, which no scene definition hands out")
    rep.stats["breakers"] = dict(sorted(held.items()))


def _has_gates(d: EncounterDef | None) -> bool:
    """Whether the placed footprints of ``d`` are checked as gates (the sealed deep is not)."""
    return d is not None and bool(d.gates) and not d.fixed


def _check_gates(
    world: World, mats: Materials, rep: CheckReport, d: EncounterDef, m: dict, inst: Instance
) -> None:
    """The placed footprint is a true gate (``routes.route_problems``) for a digger."""
    if not _has_gates(d):
        return
    fp = m["footprint"]
    cells = world.grid[_box(fp)]
    for problem in route_problems(cells, inst.doors, inst.gate_regions(), mats, sealed=d.sealed):
        rep.failures.append(f"encounter {d.id} at ({fp['x']}, {fp['y']}): {problem}")


def _check_intact(world: World, rep: CheckReport, d: EncounterDef, m: dict, inst: Instance) -> None:
    fp = m["footprint"]
    expect = inst.grid
    here = world.grid[_box(fp)]
    if d.fixed:  # the gate shaft cuts the hall on purpose: compare the plug only
        x, y, w, h = inst.regions.get("plug", (0, 0, 0, 0))
        expect, here = expect[y : y + h, x : x + w], here[y : y + h, x : x + w]
    wrong = int((expect != here).sum())
    if wrong:
        rep.failures.append(
            f"encounter {d.id} at ({fp['x']}, {fp['y']}): {wrong} cells differ from its scene"
        )
    if m.get("params") != dict(sorted(inst.params.items())):
        rep.failures.append(f"encounter {d.id}: its liquids do not match the rules of the world")


def _items_of(items: list[dict], m: dict) -> list[dict]:
    """The role items that lie inside the footprint of the placed scene ``m``.

    Matching by footprint, not by encounter id: a scene may be placed twice in a world and each
    copy has to carry its own supplies.
    """
    fp = m["footprint"]
    return [
        it
        for it in items
        if it.get("encounter_id") == m["encounter_id"]
        and fp["x"] <= it["x"] < fp["x"] + fp["w"]
        and fp["y"] <= it["y"] < fp["y"] + fp["h"]
    ]


class _Reach:
    """Whether the player can walk to an item without digging.

    An item that lies inside a dig-zone scene must be reachable with that scene's own zone left
    undug: the way through the zone is the scene's puzzle, a key behind it would be no key. The
    zones of other scenes (the flooded corridor of layer 1, say) count as walkable.
    """

    def __init__(self, world: World, lab: np.ndarray, start_label: int, walk: Walk | None):
        self.world = world
        self.lab, self.start_label, self.walk = lab, start_label, walk
        defs = load_encounters()
        self.zones = [
            m["footprint"]
            for m in placed_encounters(world)
            if (d := defs.get(m["encounter_id"])) is not None and d.dig_zone
        ]

    def zone_of(self, it: dict) -> dict | None:
        for fp in self.zones:
            if fp["x"] <= it["x"] < fp["x"] + fp["w"] and fp["y"] <= it["y"] < fp["y"] + fp["h"]:
                return fp
        return None

    def can_walk_to(self, it: dict) -> bool:
        zone = self.zone_of(it)
        if zone is None or self.walk is None:
            return _reachable(self.lab, self.start_label, it["x"], it["y"])
        lab, start = self.walk(zone)
        return _reachable(lab, start, it["x"], it["y"], OWN_ZONE_RADIUS)


def _check_requires(
    rep: CheckReport,
    rules: Rules,
    d: EncounterDef,
    items: list[dict],
    own: list[dict],
    reach: _Reach,
) -> None:
    breakers = [str(it.get("spell")) for it in items if it["role"] == "breaker"]
    for req in d.requires:
        if "predicate" in req:
            ok, why = predicate_holds(req["predicate"], rules, breakers)
            if not ok:
                rep.failures.append(f"encounter {d.id} is unsolvable under these rules: {why}")
        if "supply" in req:
            role = req["supply"]
            pool = own if req.get("own") else items
            have = [it for it in pool if _supplies(role, it, rules) and reach.can_walk_to(it)]
            if len(have) < int(req.get("min", 1)):
                rep.failures.append(
                    f"encounter {d.id} needs {req.get('min', 1)} {role} items the player can "
                    f"reach, found {len(have)}"
                )


def _check_roles(rep: CheckReport, d: EncounterDef, own: list[dict], reach: _Reach) -> None:
    for it in own:
        if it.get("role") not in SUPPLY_ROLES:
            continue
        if not reach.can_walk_to(it):
            rep.failures.append(
                f"encounter {d.id}: the {it.get('role')} item at ({it['x']}, {it['y']}) cannot "
                "be reached on foot"
            )


def _reachable(
    lab: np.ndarray, start_label: int, x: int, y: int, radius: int = REACH_RADIUS
) -> bool:
    """True if a cell of the start's walking area lies within ``radius`` of ``(x, y)``."""
    if not start_label:
        return False
    y0, y1 = max(0, y - radius), min(lab.shape[0], y + radius + 1)
    x0, x1 = max(0, x - radius), min(lab.shape[1], x + radius + 1)
    return bool((lab[y0:y1, x0:x1] == start_label).any())
