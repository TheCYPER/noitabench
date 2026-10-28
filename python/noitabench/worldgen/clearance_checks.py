"""Post-generation checks of the hazard clearance (D2c, 2026-10-27; see ``clearance.py``).

A world fails if

* **A corridor is in reach of a hazard.** For every must-pass scene, no cell of lava, acid or fire
  outside the scene's own footprint lies where the player's hit box can reach from a free position
  of the collision box inside the scene's footprint or the tunnels that lead to it. Contact damage
  and ignition go through walls, so this is the difference between a route that can be walked and
  one that burns the player to death behind a wall.
* **The key blast reaches a hazard.** No such cell lies within the blast radius of the seal key
  (plus a margin) of the hall above the plug, where the bomb comes to rest: the crater would let
  it loose into the hall and the sealed room.
* **A lane is missing.** Every placed must-pass scene has a record in ``meta["clearance"]`` (the
  check cannot look at a corridor it was not told about).
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from .clearance import Lane, blast_violations, lane_violations, seal_blasts
from .config import Materials
from .world import World

SAMPLE = 3  # cells named in a failure message


def _what(mats: Materials, grid: np.ndarray, cells: np.ndarray) -> str:
    """``"17 lava, 2 acid"`` for the hazard cells at ``cells`` (``(x, y)`` rows)."""
    keys = Counter(mats.keys[grid[y, x]] for x, y in cells)
    return ", ".join(f"{n} {k}" for k, n in sorted(keys.items()))


def _where(cells: np.ndarray) -> str:
    return ", ".join(f"({x}, {y})" for x, y in cells[:SAMPLE])


def lanes_of(world: World) -> list[Lane]:
    """The lanes the generator recorded (empty if the world has no record)."""
    return [Lane.from_record(r) for r in world.meta.get("clearance", {}).get("lanes", [])]


def check_clearance(world: World, mats: Materials, failures: list[str], stats: dict) -> None:
    """Add a failure for every hazard in reach of a corridor or of the key blast."""
    lanes = lanes_of(world)
    recorded = {(lane.encounter_id, lane.footprint) for lane in lanes}
    must_pass = [
        m
        for m in world.markers
        if m["type"] == "encounter" and m["must_pass"] and not m.get("placeholder", True)
    ]
    for m in must_pass:
        fp = m["footprint"]
        rect = (fp["x"], fp["y"], fp["x"] + fp["w"], fp["y"] + fp["h"])
        if (m["encounter_id"], rect) not in recorded:
            failures.append(
                f"must-pass encounter {m['encounter_id']} at ({fp['x']}, {fp['y']}) has no lane "
                "in meta.clearance (a world written before generator 0.6.0 has none; the hazard "
                "clearance cannot look at its corridors)"
            )
    in_reach = 0
    for lane in lanes:
        cells = lane_violations(world.grid, mats, lane)
        in_reach += len(cells)
        if len(cells):
            x, y = lane.footprint[:2]
            failures.append(
                f"must-pass encounter {lane.encounter_id} at ({x}, {y}): {_what(mats, world.grid, cells)}"
                f" cells within reach of the player's hit box from its corridors (e.g. at "
                f"{_where(cells)}): contact damage and fire go through walls"
            )
    blast_cells = 0
    seals = [m for m in world.markers if m["type"] == "seal"]
    blasts = seal_blasts(world.markers)
    if len(blasts) < len(seals):
        failures.append(
            "the plug of the seal lies in no placed scene: the hall where the key goes off "
            "is unknown, so the blast zone cannot be checked"
        )
    for blast in blasts:
        cells = blast_violations(world.grid, mats, blast)
        blast_cells += len(cells)
        if len(cells):
            failures.append(
                f"{_what(mats, world.grid, cells)} cells within the blast radius of the seal key "
                f"round the hall above the plug (e.g. at {_where(cells)}): the crater would let "
                "them loose"
            )
    stats["clearance"] = {
        "lanes": len(lanes),
        "hazard_cells_in_reach": in_reach,
        "hazard_cells_in_blast": blast_cells,
    }
