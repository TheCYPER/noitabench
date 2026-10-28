"""Structure of one layer: must-pass bands, brick seams, sections, gates, side pockets, slots.

The middle biome of each layer is the main path. Full-width rock *bands* cut it into
sections; each band has one chamber (a must-pass encounter slot) through which the way
down leads. The side biomes are dead-end pockets with a single gate into the middle biome.

Each chamber is also a true chokepoint (CP2 decision, 2026-10-27): the starting digger can
remove rock but not brick (durability 14), so the layer is built from brick where the rock
alone would let a player dig around a scene.

* a **seam**: brick rows across the whole width of the middle biome at the height of the
  chamber's anchor row, with a hole exactly as wide as the scene's footprint;
* a **shell**: the outer cells of every side biome are brick, except where the pocket's single
  gate leaves it. A pocket is thus a vault with one door, attached to one section; nobody gets
  into it, or from it into another section, by digging.

Seams run from shell to shell, so everything above a seam (the section above, the pockets
attached to it or to sections higher up, the start) is cut off from everything below it except
through the scene.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .canvas import Canvas, Component, GenerationFailure, Rect, capsule_rect
from .clearance import hazard_mask
from .config import Biome, BiomeMap, Layer
from .encounter_defs import Instance
from .encounter_place import (
    OUTSIDE,
    SceneContext,
    door_point,
    encounter_slot,
    stamp,
    world_markers,
)
from .encounters import node_of
from .noise import noise_1d

MIN_SECTION_CELLS = 250
MIN_POCKET_CELLS = 700
MAX_SLOT_PER_ID = 2
POCKET_GATE_TRIES = 40
MAX_SLOT_TRIES = 400
POSITION_TRIES = 10  # places tried for one id before the picker draws again
MAX_ID_FAILS = 20  # tries one id may fail in a biome before the picker leaves it out
MAX_DOOR_DISTANCE = 60  # from a scene door to the cave it opens into
CHAMBER_LINK_W = 14  # width of the tunnels from a must-pass scene to the caves above and below


@dataclass
class Section:
    rect: Rect
    comp: Component


@dataclass(frozen=True)
class Seam:
    """The brick floor across the whole world around one must-pass scene (see ``build_seam``)."""

    layer: int
    encounter_id: str
    y: int  # first brick row
    thick: int
    hole: tuple[int, int]  # x range of the scene's footprint, end exclusive: no brick there
    added: int  # brick cells written that were not brick before

    def meta(self) -> dict:
        return {
            "layer": self.layer,
            "encounter_id": self.encounter_id,
            "y": self.y,
            "thick": self.thick,
            "hole": list(self.hole),
            "added": self.added,
        }


@dataclass
class LayerInfo:
    layer: Layer
    mid_rect: Rect
    sections: list[Section]
    walls: list[Rect]
    slots: list[dict] = field(default_factory=list)
    seams: list[Seam] = field(default_factory=list)
    shell_brick: int = 0  # brick cells the shells of the two side biomes added


class IdPicker:
    """Hands out placeholder encounter ids.

    At most two of a kind (one for the ids in ``single``: a scene that hands out the breaker of
    the seal must not appear twice, contracts section 4, nor one whose definition says
    ``once``). Among the ids of a biome's pool, prefer an implemented scene (a placeholder only
    fills what no scene covers), then the one whose capability node has been used least so far
    (every node should get several encounters), then the least used id.
    """

    def __init__(
        self,
        all_ids: list[str],
        implemented: frozenset[str] = frozenset(),
        single: frozenset[str] = frozenset(),
    ):
        self.count: dict[str, int] = {}
        self.node_count: dict[str, int] = {}
        self.all_ids = sorted(set(all_ids))
        self.implemented = implemented
        self.single = single

    def _room_left(self, eid: str) -> bool:
        limit = 1 if eid in self.single else MAX_SLOT_PER_ID
        return self.count.get(eid, 0) < limit

    def use(self, eid: str) -> None:
        self.count[eid] = self.count.get(eid, 0) + 1
        node = node_of(eid)
        self.node_count[node] = self.node_count.get(node, 0) + 1

    def unuse(self, eid: str) -> None:
        self.count[eid] -= 1
        self.node_count[node_of(eid)] -= 1

    def pick(
        self, pool: tuple[str, ...], rng: np.random.Generator, skip: frozenset[str] = frozenset()
    ) -> str:
        for ids in (list(pool), self.all_ids):
            ok = [i for i in ids if self._room_left(i) and i not in skip]
            if ok:
                score = {
                    i: (
                        i not in self.implemented,
                        self.node_count.get(node_of(i), 0),
                        self.count.get(i, 0),
                    )
                    for i in ok
                }
                low = min(score.values())
                best = [i for i in ok if score[i] == low]
                eid = best[int(rng.integers(0, len(best)))]
                self.use(eid)
                return eid
        raise GenerationFailure("no encounter id left under the per-id limit")


def _slot(
    eid: str, rect: Rect, must_pass: bool, layer: int, biome: str, rng: np.random.Generator
) -> dict:
    return {
        "encounter_id": eid,
        "rect": rect,
        "must_pass": must_pass,
        "layer": layer,
        "biome": biome,
        "variant": int(rng.integers(0, 4)),
        "placeholder": True,
    }


# ----------------------------------------------------------------------- bands


def band_order(layer: Layer, rng: np.random.Generator) -> list[str]:
    """The layer's must-pass ids from the top band to the bottom one.

    A random order, except that the layer's ``last`` scene (``biome_map.json``) is always the
    deepest: the layer-3 key is complete only with the spell E12 hands out, so no must-pass
    scene may come after E12 and be skipped by blasting round it. The shuffle is drawn the same
    way for every layer; ``last`` only moves its scene to the end.
    """
    ids = list(layer.must_pass)
    rng.shuffle(ids)
    if layer.last is not None:
        ids.remove(layer.last)
        ids.append(layer.last)
    return ids


def build_bands(
    canvas: Canvas,
    bm: BiomeMap,
    layer: Layer,
    picker: IdPicker,
    rng: np.random.Generator,
    ctx: SceneContext,
) -> LayerInfo:
    """Cut the layer's main biome into sections by full-width rock walls with one chamber each."""
    rect = bm.region(layer.mid)
    ids = band_order(layer, rng)
    centers, walls = _carve_walls(canvas, bm, layer, len(ids), rng)
    sections = _make_sections(canvas, bm, rect, centers)
    info = LayerInfo(layer, rect, sections, walls)
    info.shell_brick = build_shell(canvas, bm, layer.left) + build_shell(canvas, bm, layer.right)
    for i, yc in enumerate(centers):
        picker.use(ids[i])
        slot = _place_chamber(canvas, bm, sections[i], sections[i + 1], yc, ids[i], layer, rng, ctx)
        info.slots.append(slot)
        info.seams.append(build_seam(canvas, bm, layer, slot, yc))
        canvas.protect(walls[i])
    return info


def build_seam(canvas: Canvas, bm: BiomeMap, layer: Layer, slot: dict, yc: int) -> Seam:
    """Close the middle biome around a must-pass chamber with a brick floor.

    Brick rows (``bands.seam`` thick, centred on the band's centre line ``yc``) run across the
    whole width of the middle biome (its ring included, up to the shells of the side biomes)
    except over the chamber's footprint. The rows lie inside the footprint's own rows (the art's
    ``anchor_y`` sits on ``yc``), so the scene's outer rock meets the seam on both sides. The
    seam is protected: later dressing keeps out of it.
    """
    thick = bm.scenes["bands"]["seam"]
    top = yc - thick // 2
    x0, fy0, x1, fy1 = slot["rect"]
    mx0, _, mx1, _ = bm.region(layer.mid)
    if top < fy0 or top + thick > fy1:
        raise GenerationFailure(
            f"{slot['encounter_id']}: the brick seam rows {top}..{top + thick} lie outside "
            f"the scene rows {fy0}..{fy1}"
        )
    added = _brick(canvas, [(mx0, top, x0, top + thick), (x1, top, mx1, top + thick)])
    return Seam(layer.layer, slot["encounter_id"], top, thick, (x0, x1), added)


def build_shell(canvas: Canvas, bm: BiomeMap, key: str) -> int:
    """Wrap the side biome ``key`` in brick (``bands.seam`` thick along its whole boundary).

    The shell lies in the outermost cells of the region, inside its ring (no cave reaches it).
    The pocket's gate (``connect_pocket``) is cut through it later. Returns the brick cells
    written that were not brick before.
    """
    t = bm.scenes["bands"]["seam"]
    x0, y0, x1, y1 = bm.region(key)
    return _brick(
        canvas,
        [(x0, y0, x1, y0 + t), (x0, y1 - t, x1, y1), (x0, y0, x0 + t, y1), (x1 - t, y0, x1, y1)],
    )


def _brick(canvas: Canvas, rects: list[Rect]) -> int:
    """Write brick into ``rects`` and protect them; returns how many cells were not brick yet."""
    brick = canvas.mats["brick"]
    fresh = np.zeros(canvas.grid.shape, dtype=bool)
    for r in rects:
        x0, y0, x1, y1 = canvas.clip(r)
        if x0 < x1 and y0 < y1:
            fresh[y0:y1, x0:x1] = True
    added = int((fresh & (canvas.grid != brick)).sum())
    canvas.grid[fresh] = brick
    canvas.protected |= fresh
    return added


def _carve_walls(
    canvas: Canvas, bm: BiomeMap, layer: Layer, n: int, rng: np.random.Generator
) -> tuple[list[int], list[Rect]]:
    """Rock walls across the whole inner width; returns their centre rows and rectangles."""
    x0, y0, x1, y1 = bm.region(layer.mid)
    cfg = bm.scenes["bands"]
    thick, amp, margin = cfg["wall"], cfg["wave"], cfg["margin"]
    per_wall = thick + 2 * amp + 2 * margin
    section_h = ((y1 - y0) - 2 * bm.ring - n * per_wall) / (n + 1)
    if section_h < 50:
        raise GenerationFailure(
            f"layer {layer.layer}: sections would be only {section_h:.0f} px tall"
        )
    xa, xb = x0 + bm.ring, x1 - bm.ring
    centers, walls = [], []
    for i in range(n):
        jitter = float(rng.uniform(-0.12, 0.12)) * section_h
        yc = round(y0 + bm.ring + (i + 1) * section_h + i * per_wall + per_wall / 2 + jitter)
        wave = np.round(amp * noise_1d(xb - xa, 48, rng)).astype(int)
        top = yc - thick // 2 + wave
        ys = np.arange(y0, y1)[:, None]
        mask = (ys >= top[None, :]) & (ys < (top + thick)[None, :])
        canvas.grid[y0:y1, xa:xb][mask] = canvas.mats["rock"]
        centers.append(yc)
        walls.append((x0, yc - thick // 2 - amp - 1, x1, yc + thick // 2 + amp + 1))
    return centers, walls


def _make_sections(canvas: Canvas, bm: BiomeMap, rect: Rect, centers: list[int]) -> list[Section]:
    """The open areas between the walls (and above the first, below the last)."""
    x0, y0, x1, y1 = rect
    cfg = bm.scenes["bands"]
    reach = cfg["wall"] // 2 + cfg["wave"] + cfg["margin"]
    sections = []
    for i in range(len(centers) + 1):
        ya = y0 + bm.ring if i == 0 else centers[i - 1] + reach
        yb = y1 - bm.ring if i == len(centers) else centers[i] - reach
        area = (x0 + bm.ring, ya, x1 - bm.ring, yb)
        sections.append(Section(area, canvas.largest_fit_component(area, MIN_SECTION_CELLS)))
    return sections


def _place_chamber(
    canvas: Canvas,
    bm: BiomeMap,
    above: Section,
    below: Section,
    yc: int,
    eid: str,
    layer: Layer,
    rng: np.random.Generator,
    ctx: SceneContext,
) -> dict:
    """The must-pass slot of one wall: the encounter's scene if there is one, else a bare chamber."""
    if ctx.has(eid):
        return _place_scene_chamber(canvas, bm, above, below, yc, eid, layer, rng, ctx)
    chamber = _bare_chamber(canvas, bm, above, below, yc, rng)
    canvas.protect(chamber)
    return _slot(eid, chamber, True, layer.layer, layer.mid, rng)


def _bare_chamber(
    canvas: Canvas, bm: BiomeMap, above: Section, below: Section, yc: int, rng: np.random.Generator
) -> Rect:
    """Carve the wall's chamber where both neighbouring sections reach closest and link it."""
    cfg = bm.scenes["bands"]
    cw = int(rng.integers(cfg["chamber_w"][0], cfg["chamber_w"][1] + 1))
    ch = int(rng.integers(cfg["chamber_h"][0], cfg["chamber_h"][1] + 1))
    cy0 = yc - ch // 2
    xa, xb = above.rect[0], above.rect[2]
    cands = sorted({int(v) for v in rng.integers(xa + 16, xb - 16 - cw + 1, size=40)})

    def cost(cx: int) -> int:
        mid = cx + cw // 2
        qa = above.comp.nearest(mid, cy0 + 1)
        qb = below.comp.nearest(mid, cy0 + ch - 2)
        return abs(qa[0] - mid) + abs(qa[1] - cy0) + abs(qb[0] - mid) + abs(qb[1] - cy0 - ch)

    cx = min(cands, key=cost)
    chamber = (cx, cy0, cx + cw, cy0 + ch)
    canvas.carve_rect(chamber, force=True)
    canvas.link((cx + cw // 2, chamber[1] + 1), above.comp, 14, vertical_first=True)
    canvas.link((cx + cw // 2, chamber[3] - 2), below.comp, 14, vertical_first=True)
    return chamber


def _place_scene_chamber(
    canvas: Canvas,
    bm: BiomeMap,
    above: Section,
    below: Section,
    yc: int,
    eid: str,
    layer: Layer,
    rng: np.random.Generator,
    ctx: SceneContext,
) -> dict:
    """Stamp a must-pass scene across the wall and link its top and bottom doors to the sections."""
    inst = ctx.instance(eid, rng)
    y0 = yc - inst.defn.anchor_y
    x_lo, x_hi = above.rect[0] + 2, above.rect[2] - 2 - inst.w
    ry0, ry1 = bm.region(layer.mid)[1] + bm.ring, bm.region(layer.mid)[3] - bm.ring
    if x_hi < x_lo or y0 < ry0 or y0 + inst.h > ry1:
        raise GenerationFailure(f"{eid}: the {inst.w}x{inst.h} scene does not fit its band")
    cands = sorted({int(v) for v in rng.integers(x_lo, x_hi + 1, size=40)})

    def cost(x0: int) -> int:
        pa, pb = door_point(inst, "top", x0, y0), door_point(inst, "bottom", x0, y0)
        qa, qb = above.comp.nearest(*pa), below.comp.nearest(*pb)
        return abs(qa[0] - pa[0]) + abs(qa[1] - pa[1]) + abs(qb[0] - pb[0]) + abs(qb[1] - pb[1])

    for x0 in sorted(cands, key=cost):  # the cheapest place where the scene cuts no cave off
        fp = (x0, y0, x0 + inst.w, y0 + inst.h)
        snap = canvas.snapshot(fp)
        stamp(canvas, inst, x0, y0)
        ca, cb = canvas.refit(above.comp), canvas.refit(below.comp)
        if (
            ca.size
            and cb.size
            and canvas.keeps_terminals(above.comp, ca)
            and canvas.keeps_terminals(below.comp, cb)
        ):
            top = canvas.plan_door_link(
                door_point(inst, "top", x0, y0), OUTSIDE["top"], ca, CHAMBER_LINK_W
            )
            bottom = canvas.plan_door_link(
                door_point(inst, "bottom", x0, y0), OUTSIDE["bottom"], cb, CHAMBER_LINK_W
            )
            if top and bottom:
                canvas.carve_link(top, CHAMBER_LINK_W)
                canvas.carve_link(bottom, CHAMBER_LINK_W)
                above.comp, below.comp = ca, cb
                slot = encounter_slot(
                    inst, fp, layer.layer, layer.mid, world_markers(inst, x0, y0), must_pass=True
                )
                # the corridors the player walks in and out by (clearance.py)
                slot["tunnels"] = [
                    capsule_rect(a, c, CHAMBER_LINK_W / 2) for a, c in (*top[0], *bottom[0])
                ]
                return slot
        canvas.restore(fp, snap)
    raise GenerationFailure(f"{eid}: no place in the band where the scene leaves the caves whole")


# ----------------------------------------------------------------------- gates


def vertical_gate(
    canvas: Canvas,
    candidates: list[int],
    ya: int,
    yb: int,
    up: Component | None,
    down: Component | None,
    width: int = 14,
    record: list[Rect] | None = None,
) -> int:
    """Cut a shaft of ``width`` from row ``ya`` to ``yb`` at the best of ``candidates``.

    The best x is the one whose two ends are closest to the components they must reach.
    Returns the chosen x. With ``record`` the boxes of the shaft and of its links are appended
    to it (``clearance.py`` keeps hazards away from the way the player walks).
    """

    def cost(gx: int) -> float:
        c = 0.0
        for comp, y in ((up, ya + 1), (down, yb - 1)):
            if comp is not None:
                q = comp.nearest(gx, y)
                c += abs(q[0] - gx) + abs(q[1] - y)
        return c

    gx = min(candidates, key=cost)
    shaft = (gx - width // 2, ya, gx + width // 2, yb)
    canvas.carve_rect(shaft, force=True)
    canvas.protect(shaft)
    if record is not None:
        record.append(shaft)
    if up is not None:
        canvas.link((gx, ya + 1), up, width, vertical_first=True, record=record)
    if down is not None:
        canvas.link((gx, yb - 1), down, width, vertical_first=True, record=record)
    return gx


def connect_pocket(
    canvas: Canvas,
    bm: BiomeMap,
    info: LayerInfo,
    side: str,
    key: str,
    rng: np.random.Generator,
) -> Component:
    """Give a side biome its single gate into the middle biome."""
    x0, y0, x1, y1 = bm.region(key)
    ring = bm.ring
    comp = canvas.largest_fit_component(
        (x0 + ring, y0 + ring, x1 - ring, y1 - ring), MIN_POCKET_CELLS
    )
    mx0, _, mx1, _ = info.mid_rect
    half = ring + 8
    shell = bm.scenes["bands"]["seam"]  # the pocket's brick shell: the gate leads through it
    if side == "left":
        bx, p_side, m_side = mx0, (mx0 - half, 0), (mx0 + half, 0)
        shell_x = (mx0 - shell, mx0)
    else:
        bx, p_side, m_side = mx1, (mx1 + half, 0), (mx1 - half, 0)
        shell_x = (mx1, mx1 + shell)

    def cuts_something(gy: int) -> bool:
        """True if the gate tunnel at row ``gy`` would cut a scene or a shaft (not the shell)."""
        window = canvas.protected[gy - 7 : gy + 7, bx - half : bx + half].copy()
        window[:, shell_x[0] - (bx - half) : shell_x[1] - (bx - half)] = False
        return bool(window.any())

    def pick(_: int) -> tuple[float, int, Section]:
        sec = info.sections[int(rng.integers(0, len(info.sections)))]
        gy = int(rng.integers(sec.rect[1] + 12, sec.rect[3] - 12))
        if cuts_something(gy):
            return (float("inf"), gy, sec)
        qp = comp.nearest(p_side[0], gy)
        qm = sec.comp.nearest(m_side[0], gy)
        return (
            abs(qp[0] - p_side[0]) + abs(qm[0] - m_side[0]) + abs(qp[1] - gy) + abs(qm[1] - gy),
            gy,
            sec,
        )

    cost, gy, sec = min((pick(i) for i in range(POCKET_GATE_TRIES)), key=lambda t: t[0])
    if cost == float("inf"):
        raise GenerationFailure(f"no free place for the gate into {key}")
    canvas.carve_rect((bx - half, gy - 7, bx + half, gy + 7), force=True)
    canvas.link((p_side[0], gy), comp, 14, vertical_first=False)
    canvas.link((m_side[0], gy), sec.comp, 14, vertical_first=False)
    return comp


# ----------------------------------------------------------------- optional slots


def place_slots(
    canvas: Canvas,
    biome: Biome,
    layer: int,
    cands: list[tuple[Rect, Component]],
    picker: IdPicker,
    taken: list[Rect],
    rng: np.random.Generator,
    ctx: SceneContext,
) -> list[dict]:
    """Place ``biome.encounters.slots`` optional encounters inside the candidate areas.

    An encounter that has a scene is stamped with its door linked to the cave; any other gets a
    bare placeholder chamber. A biome holds one copy of an id at most (a scene is drawn twice in a
    world only in two different biomes). A scene whose art holds a hazard (lava, acid) is never
    put where a cell of the hazard would fall into ``canvas.keepout`` (the reach of the player's
    hit box round the corridors of the must-pass scenes and the zone of the seal key's blast,
    ``clearance.py``).
    """
    enc = biome.encounters
    slots: list[dict] = []
    weights = np.array([max(1, (r[2] - r[0]) * (r[3] - r[1])) for r, _ in cands], dtype=float)
    weights /= weights.sum()
    tries = 0
    fails: dict[str, int] = {}
    while len(slots) < enc.slots and tries < MAX_SLOT_TRIES:
        tries += 1
        skip = frozenset(i for i, n in fails.items() if n >= MAX_ID_FAILS)
        skip |= {s["encounter_id"] for s in slots}  # one copy of a scene per biome
        eid = picker.pick(enc.pool, rng, skip)
        area, comp = cands[int(rng.choice(len(cands), p=weights))]
        slot = _try_slot(canvas, biome, layer, eid, area, comp, taken, rng, ctx)
        if slot is None:
            picker.unuse(eid)
            fails[eid] = fails.get(eid, 0) + 1
            continue
        taken.append(slot["rect"])
        slots.append(slot)
    if len(slots) < enc.slots:
        raise GenerationFailure(
            f"{biome.key}: only {len(slots)} of {enc.slots} encounter slots fit"
        )
    return slots


def _try_slot(
    canvas: Canvas,
    biome: Biome,
    layer: int,
    eid: str,
    area: Rect,
    comp: Component,
    taken: list[Rect],
    rng: np.random.Generator,
    ctx: SceneContext,
) -> dict | None:
    """One attempt to put encounter ``eid`` somewhere in ``area``; ``None`` if it does not fit."""
    enc = biome.encounters
    inst = ctx.instance(eid, rng) if ctx.has(eid) else None
    hazards = None if inst is None else hazard_mask(canvas.mats, inst.grid)
    if inst is None:
        w = int(rng.integers(enc.w_min, enc.w_max + 1))
        h = int(rng.integers(enc.h_min, enc.h_max + 1))
    else:
        w, h = inst.w, inst.h
    if area[2] - area[0] < w + 12 or area[3] - area[1] < h + 8:
        return None
    for _ in range(POSITION_TRIES):
        x = int(rng.integers(area[0] + 6, area[2] - 6 - w + 1))
        y = int(rng.integers(area[1] + 4, area[3] - 4 - h + 1))
        slot_rect = (x, y, x + w, y + h)
        if (
            any(_overlap(slot_rect, t, 10) for t in taken)
            or canvas.protected[y : y + h, x : x + w].any()
            or (hazards is not None and canvas.keepout[y : y + h, x : x + w][hazards].any())
        ):
            continue
        if inst is None:
            slot = _bare_slot(canvas, eid, slot_rect, comp, biome, layer, rng)
        else:
            slot = _stamp_scene(canvas, inst, slot_rect, comp, biome, layer, rng)
        if slot is not None:
            return slot
    return None


def _stamp_scene(
    canvas: Canvas,
    inst: Instance,
    slot_rect: Rect,
    comp: Component,
    biome: Biome,
    layer: int,
    rng: np.random.Generator,
) -> dict | None:
    """Stamp ``inst`` at ``slot_rect`` and open one of its doors to ``comp``; ``None`` (and the
    terrain as it was) if no door can be linked or the scene cuts a cave in two."""
    x, y = slot_rect[0], slot_rect[1]
    side = sorted(inst.doors)[int(rng.integers(0, len(inst.doors)))]
    door = door_point(inst, side, x, y)
    q = comp.without(slot_rect).nearest(*door)
    if abs(q[0] - door[0]) + abs(q[1] - door[1]) > MAX_DOOR_DISTANCE:
        return None
    snap = canvas.snapshot(slot_rect)
    stamp(canvas, inst, x, y)
    free = canvas.refit(comp)
    plan = None
    if free.size and canvas.keeps_terminals(comp, free):
        plan = canvas.plan_door_link(door, OUTSIDE[side], free, 12, MAX_DOOR_DISTANCE)
    if plan is None:
        canvas.restore(slot_rect, snap)
        return None
    canvas.carve_link(plan, 12)
    return encounter_slot(
        inst, slot_rect, layer, biome.key, world_markers(inst, x, y), must_pass=False
    )


def _bare_slot(
    canvas: Canvas,
    eid: str,
    rect: Rect,
    comp: Component,
    biome: Biome,
    layer: int,
    rng: np.random.Generator,
) -> dict | None:
    """The placeholder chamber of an encounter that has no scene yet."""
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    free = canvas.refit(comp)  # scenes stamped earlier may have cut the cave
    if not free.size:
        return None
    q = free.nearest(cx, cy)
    if abs(q[0] - cx) + abs(q[1] - cy) > 70:
        return None
    canvas.carve_rect(rect, force=True)
    canvas.link(
        (x0 + (x1 - x0) // 2, y0 + (y1 - y0) // 2),
        free,
        12,
        vertical_first=bool(rng.integers(0, 2)),
    )
    canvas.protect(rect)
    return _slot(eid, rect, False, layer, biome.key, rng)


def _overlap(a: Rect, b: Rect, pad: int = 0) -> bool:
    return not (
        a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1]
    )
