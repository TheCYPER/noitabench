"""A small world around one encounter scene: the lab for tests, previews and reference solutions.

``scene_world`` stamps one encounter into a block of rock, adds a corridor and a room to every
door (the player spawns in the room of the top door, or of the only door) and returns a
``World`` that loads with ``Game.from_world`` like a generated one. The room of the bottom door
is the exit; its floor cell is ``meta["exit"]``.
"""

from __future__ import annotations

from .canvas import Canvas
from .config import Materials, load_materials
from .encounter_defs import Instance, instantiate, load_encounters
from .encounter_place import encounter_slot, stamp, world_markers
from .markers import encounter_marker, station_markers
from .table import get_rules
from .world import World

MARGIN = 24  # rock around the scene
CORRIDOR = 22  # length of the corridor from a door to its room
ROOM_W, ROOM_H = 60, 36  # roomy: a flooded scene empties into the exit room
FLOOR = 4  # thickness of a room's floor
BORDER = 3


def scene_world(
    eid: str,
    variant: int = 0,
    rule_seed: int = 0,
    seed: int = 1,
    mats: Materials | None = None,
) -> World:
    """A world holding encounter ``eid`` as ``variant`` (the rule seed only seeds the recipes)."""
    mats = mats or load_materials()
    defn = load_encounters()[eid]
    inst = instantiate(defn, get_rules(rule_seed), variant, mats)
    doors = inst.doors
    pad_l = MARGIN + (ROOM_W + CORRIDOR if "left" in doors else 0)
    pad_r = MARGIN + (ROOM_W + CORRIDOR if "right" in doors else 0)
    pad_t = MARGIN + (ROOM_H + CORRIDOR if "top" in doors else 0)
    pad_b = MARGIN + (ROOM_H + CORRIDOR if "bottom" in doors else 0)
    width, height = pad_l + inst.w + pad_r, pad_t + inst.h + pad_b
    canvas = Canvas(width, height, mats)
    x0, y0 = pad_l, pad_t
    rect = stamp(canvas, inst, x0, y0)
    exits: dict[str, tuple[int, int]] = {}
    for side in doors:
        exits[side] = _attach(canvas, inst, side, x0, y0, mats)
    _carve_lab(canvas, inst, x0, y0, mats)
    spawn_side = "top" if "top" in doors else min(doors)
    spawn = exits[spawn_side]
    canvas.grid[:BORDER] = mats["rock"]
    canvas.grid[-BORDER:] = mats["rock"]
    canvas.grid[:, :BORDER] = mats["rock"]
    canvas.grid[:, -BORDER:] = mats["rock"]
    slot = encounter_slot(inst, rect, defn.layer or 0, "lab", world_markers(inst, x0, y0))
    markers = [{"type": "spawn_player", "x": spawn[0], "y": spawn[1]}]
    markers += slot["scene_markers"]
    markers.append(encounter_marker(slot))
    markers += station_markers([slot])
    meta = _lab_meta(inst, slot, x0, y0, exits, spawn_side, rule_seed)
    return World(seed, rule_seed, canvas.grid, 128, [["lab"]], markers, meta)


def _lab_meta(
    inst: Instance,
    slot: dict,
    x0: int,
    y0: int,
    exits: dict[str, tuple[int, int]],
    spawn_side: str,
    rule_seed: int,
) -> dict:
    """What the tests and previews read about the lab world: regions, doors, rooms, goal, exit."""
    defn = inst.defn
    doors = inst.doors
    meta: dict = {
        "generator": "noitabench.worldgen.scene_world",
        "encounter": defn.id,
        "variant": inst.variant,
        "rule_seed": rule_seed,
        "params": inst.params,
        "footprint": slot["footprint"],
        "spawn": list(exits[spawn_side]),
        "regions": {k: [x0 + b[0], y0 + b[1], b[2], b[3]] for k, b in sorted(inst.regions.items())},
        "mirror": inst.mirror,
        "rooms": {s: list(p) for s, p in exits.items()},
        "doors": {s: [x0 + inst.door_center(s)[0], y0 + inst.door_center(s)[1]] for s in doors},
    }
    if "bottom" in doors and spawn_side != "bottom":
        meta["exit"] = list(exits["bottom"])
    if defn.lab_goal is not None:
        gx = defn.w - defn.lab_goal[0] - 1 if inst.mirror else defn.lab_goal[0]
        meta["goal"] = [x0 + gx, y0 + defn.lab_goal[1]]
    return meta


def _attach(
    canvas: Canvas, inst: Instance, side: str, x0: int, y0: int, mats: Materials
) -> tuple[int, int]:
    """Corridor and room at the door on ``side``; returns the standing cell on the room's floor."""
    cx, _cy = inst.door_center(side)
    xs = [c[0] for c in inst.doors[side]]
    ys = [c[1] for c in inst.doors[side]]
    air = mats.air
    g = canvas.grid
    if side in ("top", "bottom"):
        lo, hi = x0 + min(xs), x0 + max(xs) + 1
        room_x0 = x0 + cx - ROOM_W // 2
        if side == "top":
            floor_top = y0 - CORRIDOR - FLOOR
            g[floor_top - ROOM_H : floor_top, room_x0 : room_x0 + ROOM_W] = air
            g[floor_top : floor_top + FLOOR, room_x0 : room_x0 + ROOM_W] = mats["ground"]
            g[floor_top:y0, lo:hi] = air
            return x0 + cx + ROOM_W // 3, floor_top - 1
        ry0 = y0 + inst.h + CORRIDOR
        g[y0 + inst.h : ry0, lo:hi] = air
        g[ry0 : ry0 + ROOM_H, room_x0 : room_x0 + ROOM_W] = air
        g[ry0 + ROOM_H - FLOOR : ry0 + ROOM_H, room_x0 : room_x0 + ROOM_W] = mats["ground"]
        return x0 + cx + ROOM_W // 3, ry0 + ROOM_H - FLOOR - 1
    lo, hi = y0 + min(ys), y0 + max(ys) + 1
    if side == "left":
        rx1 = x0 - CORRIDOR
        g[lo:hi, rx1:x0] = air
        g[hi - ROOM_H : hi, rx1 - ROOM_W : rx1] = air
        g[hi : hi + FLOOR, rx1 - ROOM_W : rx1] = mats["ground"]
        return rx1 - ROOM_W // 3, hi - 1
    rx0 = x0 + inst.w + CORRIDOR
    g[lo:hi, x0 + inst.w : rx0] = air
    g[hi - ROOM_H : hi, rx0 : rx0 + ROOM_W] = air
    g[hi : hi + FLOOR, rx0 : rx0 + ROOM_W] = mats["ground"]
    return rx0 + ROOM_W // 3, hi - 1


def _carve_lab(canvas: Canvas, inst: Instance, x0: int, y0: int, mats: Materials) -> None:
    """The extra air of the definition's ``lab.carve`` boxes (a room under a lock, say)."""
    for bx, by, bw, bh in inst.defn.lab_carve:
        if inst.mirror:
            bx = inst.w - bx - bw
        canvas.carve_rect((x0 + bx, y0 + by, x0 + bx + bw, y0 + by + bh), force=True)
