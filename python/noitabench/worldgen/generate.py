"""World generation: biome regions, scenes, layer structure, features, markers, checks.

``generate_world(seed, rule_seed)`` is a pure function of its arguments: every random
choice comes from a named stream derived from the seed (rng.py). The reaction table is the
original one for every seed (the rule seed only seeds the potion recipes), so the terrain and
the scenes depend on ``seed`` alone. If a structural step
or a post-generation check fails, the world is rebuilt with a sub-seed derived from
the seed and the attempt number (world-design 2.5); the result is still a function of
the seed alone.
"""

from __future__ import annotations

import logging
from dataclasses import astuple, dataclass, field

import numpy as np

from . import alchemy, clearance, features, hazards, scenes, settle, structures
from .bowls import BowlSpec
from .canvas import Canvas, GenerationFailure, Rect
from .checks import CheckReport, run_checks
from .clearance import Blast, Lane, lane_of_slot
from .config import BiomeMap, Materials, load_biome_map, load_materials
from .encounter_defs import implemented_ids, single_ids
from .encounter_place import SceneContext
from .fill import RegionInfo, build_biome_region
from .layers import (
    IdPicker,
    LayerInfo,
    build_bands,
    connect_pocket,
    place_slots,
    vertical_gate,
)
from .markers import encounter_marker, place_spawns, station_markers
from .rng import mix64, name_key, stream
from .table import get_rules
from .world import World

log = logging.getLogger(__name__)

VERSION = "0.6.4"
MAX_ATTEMPTS = 8
MAX_SEED = 1 << 64
MARKER_ORDER = {
    "spawn_player": 0,
    "rest_area": 1,
    "edit_station": 2,
    "seal": 3,
    "encounter": 4,
    "spawn_enemy": 5,
    "item": 6,
    "alchemy_bowl": 7,
}
GATE_CANDIDATES = 16
POOL_CLEARANCE = 4  # cells between the exit shaft of a rest hall and its healing pool


def generate_world(seed: int, rule_seed: int = 0, *, max_attempts: int = MAX_ATTEMPTS) -> World:
    """Generate the world of ``(seed, rule_seed)``; re-roll with sub-seeds until the checks pass.

    Every scene is built for the original reaction table (the liquid that turns lava to rock,
    for one); ``rule_seed`` is stored in the world file and seeds the potion recipes in the
    engine. ``max_attempts`` is keyword-only so that a stale call with a third positional
    argument (the old ``strength``) fails loudly instead of changing the number of attempts.
    """
    for name, value in (("seed", seed), ("rule_seed", rule_seed)):
        if not 0 <= value < MAX_SEED:  # the sim reads both as u64
            raise ValueError(f"{name} must be in [0, 2**64), got {value}")
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
    bm, mats = load_biome_map(), load_materials()
    ctx = SceneContext.build(get_rules(rule_seed), mats)
    problems: list[str] = []
    for attempt in range(max_attempts):
        sub = seed if attempt == 0 else mix64(seed, name_key("attempt"), attempt)
        try:
            world = _build(seed, sub, rule_seed, attempt, bm, mats, ctx)
        except GenerationFailure as err:
            problems.append(f"attempt {attempt}: {err}")
            log.info("seed %d attempt %d failed: %s", seed, attempt, err)
            continue
        report = run_checks(world, bm, mats, ctx.rules)
        if report.ok:
            _finish_meta(world, report)
            return world
        problems.append(f"attempt {attempt}: " + "; ".join(report.failures))
        log.info("seed %d attempt %d failed checks: %s", seed, attempt, report.failures)
    raise RuntimeError(
        f"seed {seed}: no valid world in {max_attempts} attempts:\n  " + "\n  ".join(problems)
    )


def _finish_meta(world: World, report: CheckReport) -> None:
    full = report.main_path
    path = full[:: max(1, len(full) // 400)]
    if path and path[-1] != full[-1]:
        path.append(full[-1])  # the polyline must end at the seal front
    world.meta["checks"] = report.stats
    world.meta["main_path"] = [[int(x), int(y)] for x, y in path]


def _gate_candidates(rng: np.random.Generator, lo: int, hi: int) -> list[int]:
    return sorted({int(v) for v in rng.integers(lo, hi + 1, size=GATE_CANDIDATES)})


def _seal_gate_candidates(rng: np.random.Generator, shaft_x: int) -> list[int]:
    """Shaft positions beside the lock of the sealed deep, not over it (a fall into the lava)."""
    left = _gate_candidates(rng, shaft_x - 30, shaft_x - 18)
    return sorted(left + _gate_candidates(rng, shaft_x + 18, shaft_x + 30))


def _avoid(candidates: list[int], pool: Rect, gate_w: int) -> list[int]:
    """Move the shaft positions that would cut the healing pool to its nearer side.

    The exit shaft leaves through the floor of the rest hall; the pool is sunk into that
    floor and would drain down the shaft.
    """
    lo, hi = pool[0] - gate_w - POOL_CLEARANCE, pool[2] + gate_w + POOL_CLEARANCE
    mid = (pool[0] + pool[2]) // 2
    return sorted({(lo if c < mid else hi) if lo <= c <= hi else c for c in candidates})


@dataclass
class _Build:
    """State shared by the build steps of one attempt."""

    sub: int
    bm: BiomeMap
    mats: Materials
    ctx: SceneContext
    canvas: Canvas
    picker: IdPicker
    start: scenes.StartInfo | None = None
    rests: list[scenes.RestInfo] = field(default_factory=list)
    seal: scenes.SealInfo | None = None
    infos: list[LayerInfo] = field(default_factory=list)
    regions: dict[str, RegionInfo] = field(default_factory=dict)
    built: dict[str, dict[str, int]] = field(default_factory=dict)  # what the dressing placed
    settled: dict[str, int] = field(default_factory=dict)  # what the settling pass changed
    deposits: list[dict] = field(default_factory=list)  # ingredient deposits (alchemy.py)
    seal_tunnels: list[Rect] = field(default_factory=list)  # boxes of the shaft above the seal

    def rs(self, name: str, *keys: int) -> np.random.Generator:
        return stream(self.sub, name, *keys)

    @property
    def fixed_slots(self) -> list[dict]:
        return [s for r in self.rests for s in r.slots] + list(self.seal.slots)

    @property
    def lanes(self) -> list[Lane]:
        """The corridors the player has to walk: each must-pass scene and the tunnels to it."""
        size = (self.canvas.w, self.canvas.h)
        lanes = [
            lane_of_slot(s, s["tunnels"], size)
            for info in self.infos
            for s in info.slots
            if s["must_pass"] and not s.get("placeholder", True)
        ]
        return [*lanes, lane_of_slot(self.seal.slots[0], self.seal_tunnels, size)]

    @property
    def blast(self) -> Blast:
        """Where the key of the seal can go off: anywhere in the hall above the plug
        (clearance.py)."""
        fp = self.seal.slots[0]["footprint"]
        scene = (fp["x"], fp["y"], fp["x"] + fp["w"], fp["y"] + fp["h"])
        return Blast.of_seal(self.seal.plug, scene)


def _build(
    seed: int,
    sub: int,
    rule_seed: int,
    attempt: int,
    bm: BiomeMap,
    mats: Materials,
    ctx: SceneContext,
) -> World:
    canvas = Canvas(bm.width, bm.height, mats)
    all_ids = sorted(
        {i for b in bm.biomes.values() for i in b.encounters.pool}
        | {i for lay in bm.layers for i in lay.must_pass}
    )
    st = _Build(sub, bm, mats, ctx, canvas, IdPicker(all_ids, implemented_ids(), single_ids()))
    _build_regions(st)
    _build_scenes_and_bands(st)
    _build_gates(st)
    slots = st.fixed_slots + _build_slots(st)
    markers = _build_dressing_and_markers(st, slots)
    markers += [_rest_marker(r) for r in st.rests] + [encounter_marker(s) for s in slots]
    markers += [m for r in st.rests for m in r.markers]
    markers += [m for s in slots for m in s.get("scene_markers", ())]
    markers += station_markers(slots)
    _fill_border(canvas, bm)
    markers.sort(key=_marker_key)
    seams = [seam.meta() for info in st.infos for seam in info.seams]
    meta = {
        "generator": "noitabench.worldgen",
        "version": VERSION,
        "attempt": attempt,
        "built": st.built,
        "settled": st.settled,
        "seams": seams,
        "seam_brick": sum(seam["added"] for seam in seams),
        "shell_brick": sum(info.shell_brick for info in st.infos),
        "seal_brick": st.seal.brick,
        "deposits": sorted(st.deposits, key=lambda d: (d["y"], d["x"], d["material"])),
        "clearance": {
            "reach": list(astuple(clearance.player_reach())),
            "blast_radius": st.blast.radius,
            "lanes": [lane.record() for lane in st.lanes],
        },
    }
    return World(seed, rule_seed, canvas.grid, bm.cell_size, bm.grid_keys(), markers, meta)


def _fill_border(canvas: Canvas, bm: BiomeMap) -> None:
    """Rock along the world's edge, except where a brick seam runs out to the edge.

    A seam has to reach the very edge of the world: border rock is diggable, so a seam that
    stopped short of it would leave a lane past the scene along the world's side.
    """
    brick = canvas.mats["brick"]
    for edge in (
        canvas.grid[: bm.border],
        canvas.grid[-bm.border :],
        canvas.grid[:, : bm.border],
        canvas.grid[:, -bm.border :],
    ):
        edge[edge != brick] = canvas.mats["rock"]


def _marker_key(m: dict) -> tuple:
    return (
        MARKER_ORDER[m["type"]],
        m["y"],
        m["x"],
        m.get("encounter_id", ""),
        m.get("enemy", m.get("item", "")),
    )


def _rest_marker(r: scenes.RestInfo) -> dict:
    x0, y0, x1, y1 = r.hall
    return {"type": "rest_area", "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "index": r.index}


def _build_regions(st: _Build) -> None:
    """Step 1: tile, smooth and fill every biome region."""
    for key in sorted(st.bm.biomes):
        edge_seed = mix64(st.sub, name_key("edges"), name_key(key))
        st.regions[key] = build_biome_region(
            st.canvas, st.bm, st.bm.biomes[key], edge_seed, st.rs("region", name_key(key))
        )


def _build_scenes_and_bands(st: _Build) -> None:
    """Steps 2-3: global scenes, then the must-pass bands and sections of every layer."""
    bm, ring = st.bm, st.bm.ring
    st.start = scenes.build_start(st.canvas, bm, st.rs("start"))
    st.rests = [scenes.build_rest(st.canvas, bm, i, st.rs("rest", i)) for i in (1, 2)]
    for slot in (s for r in st.rests for s in r.slots):
        st.picker.use(slot["encounter_id"])
    st.picker.use(bm.scenes["seal"]["encounter_id"])
    st.infos = [
        build_bands(st.canvas, bm, lay, st.picker, st.rs("bands", lay.layer), st.ctx)
        for lay in bm.layers
    ]
    # the sealed chamber goes below the place where the last section reaches closest
    last_comp, last_y = st.infos[-1].sections[-1].comp, st.infos[-1].mid_rect[3] - ring - 14

    def reach(gx: int) -> int:
        qx, qy = last_comp.nearest(gx, last_y)
        return abs(qx - gx) + abs(qy - last_y)

    lo, hi = bm.scenes["seal"]["gate_x"]
    seal_x = min(_gate_candidates(st.rs("sealx"), lo, hi), key=reach)
    st.seal = scenes.build_seal(st.canvas, bm, st.rs("seal"), seal_x, st.ctx)


def _build_gates(st: _Build) -> None:
    """Step 4: shafts along the main path: start, layer 1, rest 1, layer 2, rest 2, layer 3, seal."""
    bm, ring, canvas = st.bm, st.bm.ring, st.canvas
    rng = st.rs("gates")
    gw = bm.scenes["gate_w"]
    lo, hi = bm.scenes["rest"]["gate_x"]
    first, last = st.infos[0], st.infos[-1]
    shaft = _gate_candidates(rng, *bm.scenes["start"]["shaft_x"])
    top = int(st.start.ground.min()) - 2
    vertical_gate(
        canvas, shaft, top, first.mid_rect[1] + ring + 10, None, first.sections[0].comp, gw
    )
    for i, info in enumerate(st.infos[:-1]):
        rest, nxt = st.rests[i], st.infos[i + 1]
        down_in = _gate_candidates(rng, lo, hi)
        vertical_gate(
            canvas, down_in, info.mid_rect[3] - ring - 14, rest.hall[1] + 8,
            info.sections[-1].comp, None, gw,
        )  # fmt: skip
        down_out = _avoid(_gate_candidates(rng, lo, hi), rest.pool, bm.scenes["gate_w"])
        vertical_gate(
            canvas, down_out, rest.hall[3] - 16, nxt.mid_rect[1] + ring + 10,
            None, nxt.sections[0].comp, gw,
        )  # fmt: skip
    seal_gate = _seal_gate_candidates(rng, st.seal.shaft_x)
    vertical_gate(
        canvas, seal_gate, last.mid_rect[3] - ring - 14, st.seal.front[1] + 8,
        last.sections[-1].comp, None, gw, st.seal_tunnels,
    )  # fmt: skip


def _build_slots(st: _Build) -> list[dict]:
    """Step 5: connect the side pockets, place the optional encounter slots; returns all band
    and optional slots of the three layers."""
    bm, ring, canvas = st.bm, st.bm.ring, st.canvas
    taken = [tuple(s["rect"]) for info in st.infos for s in info.slots]
    taken += [tuple(s["rect"]) for s in st.fixed_slots]
    # a scene with lava or acid in its art keeps it out of the reach of the corridors of the
    # must-pass scenes and of the blast of the seal's key (clearance.py)
    canvas.keepout = clearance.keepout_mask(canvas.grid, st.mats, st.lanes, st.blast)
    for info in st.infos:
        lay = info.layer
        for side, key in (("left", lay.left), ("right", lay.right)):
            rng = st.rs("pocket", lay.layer, 0 if side == "left" else 1)
            comp = connect_pocket(canvas, bm, info, side, key, rng)
            x0, y0, x1, y1 = bm.region(key)
            cands = [((x0 + ring, y0 + ring, x1 - ring, y1 - ring), comp)]
            rng = st.rs("slots", name_key(key))
            info.slots += place_slots(
                canvas, bm.biomes[key], lay.layer, cands, st.picker, taken, rng, st.ctx
            )
        cands = [(sec.rect, sec.comp) for sec in info.sections]
        rng = st.rs("slots", name_key(lay.mid))
        info.slots += place_slots(
            canvas, bm.biomes[lay.mid], lay.layer, cands, st.picker, taken, rng, st.ctx
        )
    return [s for info in st.infos for s in info.slots]


def _build_dressing_and_markers(st: _Build, slots: list[dict]) -> list[dict]:
    """Step 6: pools, gas, piles, deposits; settle; structures, hazards, bowls; settle; markers.

    The first settling lets the heaps and veins come to rest before anything is built on
    them (a barrel row must see the floor as it stays); the second catches whatever the
    structures bared. The spawn markers come last: they stand on the terrain as it ends up.
    The ingredient deposits (alchemy.py) go in beside the random pools and heaps, before the first
    settling; the bowls and the bottles come after the structures and hazards, when the floor is as
    it stays.
    """
    bm, cfg = st.bm, st.bm.scenes["alchemy"]
    # no lava pool or pocket in reach of a must-pass corridor or of the blast of the seal's key (the
    # scenes stamped since the mask of ``_build_slots`` have changed what is free)
    st.canvas.keepout = clearance.keepout_mask(st.canvas.grid, st.mats, st.lanes, st.blast)
    near = alchemy.walk_reach(st.canvas, st.start.spawn, slots, st.ctx.defs, cfg["reach"])
    by_biome: dict[str, list[dict]] = {}
    for key in sorted(bm.biomes):
        biome, rect = bm.biomes[key], bm.region(key)
        rng, srng = st.rs("features", name_key(key)), st.rs("supply", name_key(key))
        pools = features.place_pools(st.canvas, biome, rect, rng)
        gas = features.place_gas(st.canvas, biome, rect, rng)
        # the pools of the supply go in before the heaps: a heap beside a pool sinks into it
        deposits = alchemy.place_deposits(st.canvas, biome, rect, srng, near, "pool")
        piles = features.place_piles(st.canvas, biome, rect, rng)
        deposits += alchemy.place_deposits(st.canvas, biome, rect, srng, near, "pile")
        by_biome[key] = deposits
        st.deposits += deposits
        st.built[key] = {"pools": pools, "gas": gas, "piles": piles, "deposits": len(deposits)}
    st.settled = settle.settle(st.canvas)
    markers: list[dict] = list(st.start.markers) + list(st.seal.markers)
    avoid = [st.start.spawn]
    for key in sorted(bm.biomes):
        biome, rect = bm.biomes[key], bm.region(key)
        counts, items = structures.place_structures(
            st.canvas, biome, rect, st.rs("decor", name_key(key)), st.regions[key]
        )
        st.built[key].update(counts)
        st.built[key].update(
            hazards.place_hazards(st.canvas, biome, rect, st.rs("hazards", name_key(key)))
        )
        st.built[key]["barrels"] = len(items)
        markers += items
        avoid += [(m["x"], m["y"]) for m in items]
    near = alchemy.walk_reach(st.canvas, st.start.spawn, slots, st.ctx.defs, cfg["reach"])
    bowls = _build_bowls(st, by_biome, near)
    markers += bowls
    for name, n in settle.settle(st.canvas).items():
        st.settled[name] += n
    near = alchemy.walk_reach(st.canvas, st.start.spawn, slots, st.ctx.defs, cfg["reach"])
    for key in sorted(bm.biomes):
        biome, rect = bm.biomes[key], bm.region(key)
        markers += alchemy.place_bottles(
            st.canvas, biome, rect, st.rs("bottles", name_key(key)), near, by_biome[key], avoid
        )
        rng = st.rs("markers", name_key(key))
        markers += place_spawns(st.canvas, biome, rect, rng, avoid)
    return markers


def _build_bowls(st: _Build, deposits: dict[str, list[dict]], near: np.ndarray) -> list[dict]:
    """The cave bowls the biome files ask for, each in a niche near a deposit of its biome.

    A biome builds the ``supply.bowls`` it asks for; one that finds too few sites leaves the rest
    to the next biome of its layer (those that ask for bowls come first). A layer that cannot
    house them all fails the world.
    """
    bm = st.bm
    spec = BowlSpec.from_config(bm.scenes["alchemy"]["bowl"])
    apart = [
        (m["x"] + m["w"] // 2, m["y"])
        for r in st.rests
        for m in r.markers
        if m["type"] == "alchemy_bowl"
    ]
    out: list[dict] = []
    margin = bm.ring + alchemy.EDGE_MARGIN
    for lay in bm.layers:
        keys = sorted((lay.left, lay.mid, lay.right), key=lambda k: -bm.biomes[k].supply.bowls)
        owed, made = 0, []
        for key in keys:
            ask = bm.biomes[key].supply.bowls + owed
            if not ask:
                continue
            x0, y0, x1, y1 = bm.region(key)
            got = alchemy.place_cave_bowls(
                st.canvas, spec, ask, (x0, y0, x1, y1),
                (x0 + margin, y0 + margin, x1 - margin, y1 - margin),
                st.rs("bowls", name_key(key)), near,
                [(d["x"], d["y"]) for d in deposits[key]], apart,
            )  # fmt: skip
            owed = ask - len(got)
            made += got
            apart += [(m["x"] + m["w"] // 2, m["y"]) for m in got]
        if owed:
            raise GenerationFailure(
                f"layer {lay.layer}: room for only {len(made)} of {len(made) + owed} bowls"
            )
        out += made
    return out
