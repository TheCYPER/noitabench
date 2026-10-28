"""Global scenes (world-design 2.1): the start area, two rest areas and the sealed chamber.

They are drawn procedurally; the layout parameters live in ``content/biome_map.json``
under ``scenes``. Gate shafts to the neighbouring biomes are cut by ``layers.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .alchemy import bottle_marker
from .bowls import BowlSpec, hall_bottle_xs, hall_bowl_x, hall_spans, stamp_bowl
from .canvas import Canvas, Rect
from .config import BiomeMap
from .encounter_place import SceneContext, encounter_slot, stamp, world_markers
from .noise import noise_1d, value_noise
from .reach import DEFAULT_DIG_MAX_DURABILITY


@dataclass
class StartInfo:
    rect: Rect
    ground: np.ndarray  # surface row of every column
    spawn: tuple[int, int]
    markers: list[dict]


@dataclass
class RestInfo:
    index: int
    rect: Rect
    hall: Rect
    slots: list[dict]
    pool: Rect
    markers: list[dict]  # the alchemy bowl and the empty bottles beside it


@dataclass
class SealInfo:
    rect: Rect
    shaft_x: int
    front: Rect
    plug: Rect
    room: Rect
    markers: list[dict]
    slots: list[dict]
    brick: int  # cells of rock and ground under the plug's top edge that were turned into brick


def _surface_profile(width: int, lo: int, hi: int, rng: np.random.Generator) -> np.ndarray:
    """Ground surface row per column: smooth noise, at most 1 px step between neighbours."""
    prof = lo + (hi - lo) * (noise_1d(width, 90, rng) * 0.5 + 0.5)
    g = np.round(prof).astype(int)
    for x in range(1, width):
        g[x] = min(max(g[x], g[x - 1] - 1), g[x - 1] + 1)
    for x in range(width - 2, -1, -1):
        g[x] = min(max(g[x], g[x + 1] - 1), g[x + 1] + 1)
    return g


def build_start(canvas: Canvas, bm: BiomeMap, rng: np.random.Generator) -> StartInfo:
    sc = bm.scenes["start"]
    cell = bm.cell_size
    mats = canvas.mats
    lo, hi = sc["ground_level"]
    ground = _surface_profile(canvas.w, lo, hi, rng)
    ys = np.arange(cell)[:, None]
    below = ys >= ground[None, :]
    noise = value_noise((cell, canvas.w), 14.0, rng, octaves=2)
    deep = (ys >= ground[None, :] + 14) & (noise > 0.62)
    region = np.full((cell, canvas.w), mats.air, dtype=np.uint8)
    region[below] = mats["ground"]
    region[deep | (ys >= cell - 14)] = mats["rock"]
    region[~below] = mats.air
    canvas.grid[0:cell, :] = region
    # decoration: wooden fences and a few rock outcrops on the surface
    shaft_lo, shaft_hi = sc["shaft_x"]
    spawn_x = int(rng.integers(sc["spawn_x"][0], sc["spawn_x"][1] + 1))
    for _ in range(5):
        x = int(rng.integers(20, canvas.w - 60))
        if shaft_lo - 40 < x < shaft_hi + 40 or spawn_x - 20 < x < spawn_x + 50:
            continue
        g = int(ground[x])
        canvas.fill_rect((x, g - 9, x + 2, g), "wood", force=True)
        canvas.fill_rect((x + 12, g - 9, x + 14, int(ground[x + 12])), "wood", force=True)
        canvas.fill_rect((x, g - 7, x + 14, g - 5), "wood", force=True)
    for _ in range(6):
        x = int(rng.integers(10, canvas.w - 10))
        if shaft_lo - 30 < x < shaft_hi + 30 or spawn_x - 20 < x < spawn_x + 50:
            continue
        canvas.capsule(
            (x, int(ground[x]) - 1),
            (x + int(rng.integers(0, 6)), int(ground[x]) - 1),
            float(rng.integers(3, 6)),
            mats["rock"],
        )
    spawn = (spawn_x, int(ground[spawn_x]) - 1)
    markers = [
        {"type": "spawn_player", "x": spawn[0], "y": spawn[1]},
        {
            "type": "item",
            "x": spawn_x + 24,
            "y": int(ground[spawn_x + 24]) - 1,
            "item": "potion_heal",
        },
    ]
    for k in range(bm.scenes["alchemy"]["start_bottles"]):  # empty bottles to carry things in
        x = spawn_x + 34 + 8 * k
        markers.append(bottle_marker(x, int(ground[x]) - 1))
    return StartInfo((0, 0, canvas.w, cell), ground, spawn, markers)


def build_rest(canvas: Canvas, bm: BiomeMap, index: int, rng: np.random.Generator) -> RestInfo:
    """A small brick hall (pillars, a healing pool, the two encounter slots, an alchemy bowl).

    The rest of the band stays solid rock: the way in comes from above and the way out
    leaves through the floor (``generate._build_gates``). The metal bowl is sunk into the floor
    between an end pillar and an encounter slot, on the left or the right (the seed decides), with
    empty bottles beside it; the shafts of ``gate_x`` never come near.
    """
    sc = bm.scenes["rest"]
    cell = bm.cell_size
    y0 = sc["rows"][index - 1] * cell
    rect = (0, y0, canvas.w, y0 + cell)
    hx0, hx1 = sc["hall"]["x"]
    wall = sc["wall"]
    hall = (hx0, y0 + sc["hall"]["top"], hx1, y0 + sc["hall"]["top"] + sc["hall"]["h"])
    canvas.fill_rect(rect, "rock", force=True)
    canvas.fill_rect(
        (hall[0] - wall, hall[1] - wall, hall[2] + wall, hall[3] + wall + 6), "brick", force=True
    )
    canvas.carve_rect(hall, force=True)
    # healing pool: a basin sunk into the floor in the middle, filled to floor level
    pool_w = sc["hall"]["pool_w"]
    px0 = (hx0 + hx1) // 2 - pool_w // 2
    pool = (px0, hall[3], px0 + pool_w, hall[3] + 8)
    canvas.carve_rect(pool, force=True)
    canvas.fill_rect(pool, "potion_heal", force=True)
    slots = []
    for s in sc["slots"]:
        cx = hx0 + int(s["anchor"] * (hx1 - hx0))
        slot_rect = (cx - s["w"] // 2, hall[3] - s["h"], cx + s["w"] // 2, hall[3])
        slots.append(
            {
                "encounter_id": s["encounter_id"],
                "rect": slot_rect,
                "must_pass": False,
                "layer": index,
                "biome": f"rest_{index}",
            }
        )
    _rest_pillars(canvas, hall, pool, [s["rect"] for s in slots], rng)
    markers = _rest_bowl(canvas, bm, hall, rng)
    return RestInfo(index, rect, hall, slots, pool, markers)


def _rest_bowl(canvas: Canvas, bm: BiomeMap, hall: Rect, rng: np.random.Generator) -> list[dict]:
    """The hall's alchemy bowl (rim level with the floor) and the empty bottles beside it."""
    cfg = bm.scenes["alchemy"]
    spec = BowlSpec.from_config(cfg["bowl"])
    left, right = hall_spans(bm.scenes["rest"])
    side = "left" if rng.random() < 0.5 else "right"
    bx = hall_bowl_x(spec, left if side == "left" else right, side)
    floor = hall[3]
    marker = stamp_bowl(canvas, spec, bx, floor, "rest")
    canvas.protect(spec.outer(bx, floor))
    bottles = [
        bottle_marker(x, floor - 1) for x in hall_bottle_xs(spec, bx, side, cfg["rest_bottles"])
    ]
    return [marker, *bottles]


def _rest_pillars(
    canvas: Canvas, hall: Rect, pool: Rect, slots: list[Rect], rng: np.random.Generator
) -> None:
    """Floor-to-ceiling pillars in the end margins, low posts beside the pool, brick blocks above.

    Nothing may split the hall: the pillars stand where nobody walks, the posts are low.
    """
    x0, y0, x1, y1 = hall
    for px in (x0 + 2, x1 - 8):
        if not any(px < s[2] + 2 and px + 6 > s[0] - 2 for s in slots):
            canvas.fill_rect((px, y0, px + 6, y1), "brick", force=True)
    for px in (pool[0] - 7, pool[2] + 2):
        canvas.fill_rect((px, y1 - 16, px + 5, y1), "brick", force=True)
    for _ in range(6):  # hanging blocks, above the slots' reach
        x = int(rng.integers(x0 + 20, x1 - 30))
        width, length = int(rng.integers(5, 10)), int(rng.integers(6, 15))
        canvas.fill_rect((x, y0, x + width, y0 + length), "brick", force=True)


def build_seal(
    canvas: Canvas, bm: BiomeMap, rng: np.random.Generator, gx: int, ctx: SceneContext
) -> SealInfo:
    """The sealed deep: a brick vault below the last layer, closed by the E06 scene.

    The scene (``content/encounters/E06``) holds the front hall and the brick over the vault;
    this draws the rock band around it and the vault room under it. Everything deeper than the
    plug's top edge that a digger could remove is then made brick (``brick_deep``), so that the
    plug is the only way down.
    """
    sc = bm.scenes["seal"]
    cell = bm.cell_size
    y0 = sc["row"] * cell
    rect = (0, y0, canvas.w, y0 + cell)
    canvas.fill_rect(rect, "rock", force=True)
    noise = value_noise((cell, canvas.w), 18.0, rng, octaves=2)
    ground = canvas.grid[y0 : y0 + cell]
    ground[noise > 0.66] = canvas.mats["ground"]
    inst = ctx.instance(sc["encounter_id"], rng)
    top = y0 + sc["top"]
    sx = gx - inst.w // 2
    r = sc["room"]
    room_top = top + inst.h
    room = (gx - r["w"] // 2, room_top, gx + r["w"] // 2, room_top + r["h"])
    wall = r["wall"]
    canvas.fill_rect(
        (room[0] - wall, room[1] - wall, room[2] + wall, room[3] + wall - 2), "brick", force=True
    )
    canvas.carve_rect(room, force=True)
    fp = stamp(canvas, inst, sx, top)
    reg = {
        k: (fp[0] + b[0], fp[1] + b[1], fp[0] + b[0] + b[2], fp[1] + b[1] + b[3])
        for k, b in inst.regions.items()
    }
    front, plug = reg["front"], reg["plug"]
    altar = (gx - 12, room[3] - 6, gx + 12, room[3])
    canvas.fill_rect(altar, "brick", force=True)
    markers = [{"type": "item", "x": gx, "y": altar[1] - 1, "item": "spell"}]
    markers.append(
        {
            "type": "seal",
            "x": plug[0],
            "y": plug[1],
            "w": plug[2] - plug[0],
            "h": plug[3] - plug[1],
            "room": {"x": room[0], "y": room[1], "w": room[2] - room[0], "h": room[3] - room[1]},
        }
    )
    slot = encounter_slot(inst, fp, 3, "seal", world_markers(inst, sx, top))
    brick = brick_deep(canvas, plug[1])
    return SealInfo(rect, gx, front, plug, room, markers, [slot], brick)


def brick_deep(canvas: Canvas, top: int) -> int:
    """Brick every diggable cell from row ``top`` (the plug's top edge) to the world's bottom.

    The rock and ground of the seal band round the vault, under it and along the world's edges
    would let a digger tunnel past the plug to the bottom of the world (it removes durability 10
    and less; brick is 14). The rows run across the whole width, the 3-cell border included
    (``generate._fill_border`` leaves brick alone). Air stays: the vault room is carved out. The
    new brick is protected. Returns the number of cells that were not brick before.
    """
    mats = canvas.mats
    below = canvas.grid[top:]
    soft = np.array(mats.durability, dtype=np.float32)[below] <= DEFAULT_DIG_MAX_DURABILITY
    diggable = mats.kind_mask(below, "static") & soft
    below[diggable] = mats["brick"]
    canvas.protected[top:][diggable] = True
    return int(diggable.sum())
