"""Post-generation checks of the alchemy supplies (D2b, CP2 decision of 2026-10-27).

Only the secret recipes change from seed to seed, so every world has to let the agent find them
by trying (``alchemy.py``). A world fails if:

* **An ingredient is missing.** Each of the twelve ingredient materials (tag ``ingredient``) needs
  at least ``scenes.alchemy.min_cells`` cells within ``scenes.alchemy.reach`` of where the player
  can walk (the player-fit area of the spawn, ``reach.py``), and at least one full bottle of it
  must stand there too (powders can only be carried in a bottle that is already full of them).
* **A recipe cannot be made.** For every recipe of the world's rule seed all three ingredients are
  obtainable (this follows from the twelve checks above; it is kept as its own message so that a
  failure names the potion).
* **Too few empty bottles.** At least ``early_empty_bottles`` lie up to the first rest area (the
  start area, layer 1 and the first rest hall) and ``min_empty_bottles`` in the whole world.
* **A bowl is wrong.** Every ``alchemy_bowl`` marker is intact (metal walls and bottom, an empty
  interior) and the player can stand on its rim; each rest hall holds one sunk into its floor
  (centre inside the ``rest_area`` box's columns, rim at the box's bottom edge) and the caves
  hold one for each ``supply.bowls`` of the biome files. Metal
  occurs nowhere else but in bowls and scene footprints.
* **A secret potion lies about.** No cell of a ``secret_potion`` material and no bottle or potion
  item of one (they exist only as the product of a recipe).
* **Three ingredients touch.** No triple of ingredient materials meets the way the simulation's
  mixing rule reads a recipe (``mixing.py``): the terrain does not depend on the rule seed, so a
  world where, say, sand, coal and gunpowder touch would make a potion at frame 0 for every rule
  seed whose recipes include that triple. Pairs that react when they touch (water and toxic
  sludge) are no recipe and do not count.

The checks are skipped when the spawn does not reach the seal front on foot: the world fails
anyway (``checks.run_checks``).
"""

from __future__ import annotations

import itertools

import numpy as np

from .bowls import BowlSpec, bowl_cells, bowl_intact
from .config import BiomeMap, Materials
from .mixing import touching_triples
from .reach import reach_mask
from .table import Rules
from .world import World

RIM_STAND = 8  # rows above a bowl's rim in which the player must be able to stand


def _in_hall(hall: dict, x: int, rim: int) -> bool:
    """A bowl is in a rest hall if its centre column lies in the hall and its rim is the floor.

    The bowl is sunk into the floor, so its interior lies below the hall's box; the rim row is the
    box's bottom edge (``y + h``). A player standing on the rim is inside the box.
    """
    return hall["x"] <= x < hall["x"] + hall["w"] and hall["y"] + hall["h"] == rim


def check_alchemy(
    world: World,
    mats: Materials,
    rules: Rules,
    bm: BiomeMap,
    failures: list[str],
    stats: dict,
    walk: np.ndarray,
) -> None:
    """Run every alchemy check; append the problems to ``failures`` and statistics to ``stats``.

    ``walk`` is the mask of the fit cells in the spawn's area (``reach.walk_area``), or all False
    if the spawn does not reach the seal front on foot.
    """
    cfg = bm.scenes["alchemy"]
    _check_secret_potions(world, mats, failures)
    _check_accidental_mixes(world, mats, rules, failures)
    _check_metal(world, mats, BowlSpec.from_config(cfg["bowl"]), failures)
    if not walk.any():
        stats["alchemy"] = {"skipped": "the spawn's area is empty"}
        return
    reach = reach_mask(world.grid, mats, walk, cfg["reach"])
    items = [m for m in world.markers if m["type"] == "item" and m["item"] == "bottle"]
    got = _check_ingredients(world, mats, rules, cfg, reach, items, failures)
    empties = _check_empty_bottles(world, bm, cfg, reach, items, failures)
    bowls = _check_bowls(world, mats, bm, cfg, walk, failures)
    stats["alchemy"] = {
        "ingredient_cells": got,
        "empty_bottles": empties,
        "bowls": bowls,
        "recipes": len(rules.recipes()),
    }


def _reachable(reach: np.ndarray, m: dict) -> bool:
    return bool(reach[m["y"], m["x"]])


def _check_ingredients(
    world: World,
    mats: Materials,
    rules: Rules,
    cfg: dict,
    reach: np.ndarray,
    bottles: list[dict],
    failures: list[str],
) -> dict[str, int]:
    """Cells and a full bottle for every ingredient, then every recipe of the rule seed."""
    ingredients = mats.with_tag("ingredient")
    got: dict[str, int] = {}
    missing: dict[str, str] = {}
    for key in ingredients:
        cells = int(((world.grid == mats[key]) & reach).sum())
        got[key] = cells
        full = [m for m in bottles if m.get("contents") == key and _reachable(reach, m)]
        if cells < cfg["min_cells"]:
            missing[key] = f"only {cells} cells within reach (need {cfg['min_cells']})"
        elif not full:
            missing[key] = "no full bottle of it the player can walk to"
    failures += [f"ingredient {key}: {why}" for key, why in missing.items()]
    for potion, trio in rules.recipes():
        unknown = [i for i in trio if i not in ingredients]
        lacking = [i for i in trio if i in missing]
        if unknown:
            failures.append(f"recipe {potion} uses {unknown}, which are not ingredient materials")
        if lacking:
            failures.append(f"recipe {potion} cannot be made: {lacking} cannot be obtained")
    return got


def _check_empty_bottles(
    world: World,
    bm: BiomeMap,
    cfg: dict,
    reach: np.ndarray,
    bottles: list[dict],
    failures: list[str],
) -> dict[str, int]:
    empty = [m for m in bottles if not m.get("contents")]
    walkable = [m for m in empty if _reachable(reach, m)]
    after_rest_1 = bm.region("rest_1")[3]
    early = [m for m in walkable if m["y"] < after_rest_1]
    counts = {"all": len(empty), "reachable": len(walkable), "early": len(early)}
    if len(early) < cfg["early_empty_bottles"]:
        failures.append(
            f"only {len(early)} empty bottles the player can walk to up to the first rest "
            f"area (need {cfg['early_empty_bottles']})"
        )
    if len(walkable) < cfg["min_empty_bottles"]:
        failures.append(
            f"only {len(walkable)} empty bottles the player can walk to (need "
            f"{cfg['min_empty_bottles']})"
        )
    return counts


def _check_bowls(
    world: World,
    mats: Materials,
    bm: BiomeMap,
    cfg: dict,
    walk: np.ndarray,
    failures: list[str],
) -> dict[str, int]:
    spec = BowlSpec.from_config(cfg["bowl"])
    bowls = [m for m in world.markers if m["type"] == "alchemy_bowl"]
    halls = [m for m in world.markers if m["type"] == "rest_area"]
    for m in bowls:
        why = bowl_intact(world.grid, mats["metal"], mats.air, spec, m)
        if why:
            failures.append(f"alchemy bowl at ({m['x']}, {m['y']}): {why}")
        rim = walk[max(0, m["y"] - RIM_STAND) : m["y"], m["x"] : m["x"] + m["w"]]
        if not rim.any():
            failures.append(
                f"alchemy bowl at ({m['x']}, {m['y']}): the player cannot stand on its rim"
            )
    in_halls = [sum(1 for m in bowls if _in_hall(h, m["x"] + m["w"] // 2, m["y"])) for h in halls]
    if in_halls != [1] * len(halls):
        failures.append(f"each rest area needs exactly one alchemy bowl, found {in_halls}")
    cave = sum(1 for m in bowls if m.get("place") == "cave")
    want = sum(b.supply.bowls for b in bm.biomes.values())
    if cave < want:
        failures.append(f"only {cave} alchemy bowls in caves (the biome files ask for {want})")
    return {"rest": len(bowls) - cave, "cave": cave}


def _check_metal(world: World, mats: Materials, spec: BowlSpec, failures: list[str]) -> None:
    """Metal lies in bowls and in the footprints of scenes (E04's vessels) and nowhere else."""
    metal = world.grid == mats["metal"]
    for m in world.markers:
        if m["type"] == "alchemy_bowl":
            x0, y0, x1, y1 = bowl_cells(spec, m)[0]
            metal[y0:y1, x0:x1] = False
        elif m["type"] == "encounter" and not m.get("placeholder", True):
            f = m["footprint"]
            metal[f["y"] : f["y"] + f["h"], f["x"] : f["x"] + f["w"]] = False
    if metal.any():
        failures.append(f"{int(metal.sum())} metal cells outside the bowls and the scenes")


def _check_secret_potions(world: World, mats: Materials, failures: list[str]) -> None:
    """A secret potion is made by a recipe, never found: not as a cell, not in a bottle."""
    secret = mats.with_tag("secret_potion")
    cells = int(np.isin(world.grid, [mats[k] for k in secret]).sum())
    items = [
        m
        for m in world.markers
        if m["type"] == "item" and (m["item"] in secret or m.get("contents") in secret)
    ]
    if cells or items:
        failures.append(
            f"secret potions lie about: {cells} cells and {len(items)} items "
            "(they only come from a recipe)"
        )


def _check_accidental_mixes(
    world: World, mats: Materials, rules: Rules, failures: list[str]
) -> None:
    """No three ingredients meet where the mixing rule would make a potion by itself."""
    ingredients = mats.with_tag("ingredient")
    reacting = {frozenset(p) for p in itertools.combinations(ingredients, 2) if rules.reacts(*p)}
    meetings = {
        trio: pos
        for trio, pos in touching_triples(world.grid, mats, ingredients).items()
        if not any(frozenset(p) in reacting for p in itertools.combinations(trio, 2))
    }
    for (a, b, c), (x, y) in list(meetings.items())[:3]:
        failures.append(
            f"ingredients {a}, {b} and {c} touch at ({x}, {y}): a recipe of those three would "
            "make a potion at frame 0"
        )
    if len(meetings) > 3:
        failures.append(f"... and {len(meetings) - 3} more triples of ingredients that touch")
