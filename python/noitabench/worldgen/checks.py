"""Post-generation checks (world-design 2.5) and the main-path search.

* **Connectivity.** Start to the cell in front of the seal. A cell is *passable* if it is
  not static, or if it is static and the *starting wand* can dig it (durability <=
  ``STARTER_DIG_MAX_DURABILITY``). Brick (durability 14) is never passable, so the seal
  itself blocks. The world passes if the player's box fits along a passable route from the
  start to the seal front (fine resolution, same cells the player would occupy) and the
  cheapest route (coarse grid, brick-conservative) needs at most ``MAX_DIG_CELLS`` dug
  cells.
* **The seal seals.** Nothing deeper than the plug's top edge is connected to the start through
  passable cells (8-connected, so not even through a diagonal squeeze): the sealed room, but also
  the rock and ground of the band round and under it, down to the world's bottom row and edges
  (``scenes.brick_deep`` turns them into brick). With the plug forced passable the room is
  reached, and nothing but the room (the positive control).
* **No bypass.** Every must-pass scene (the sealed deep apart: its plug is the cut) is the only
  way down for a player who digs but cannot break brick (``_check_bypass``): with the scene's
  footprint walled off, the diggable cells no longer connect the start to the seal front; with
  every footprint open they do (the positive control, so the cut is not vacuous). The brick
  seams of ``layers.build_seam`` make this true. Inside a footprint the same question is asked of
  the scene's own gates (``encounter_checks.py``, ``routes.py``): its outer wall is brick and the
  rock round each obstacle is walled off, so the doors are joined only through the solution
  regions.
* **The key completes last.** In a layer whose ``last`` scene ``biome_map.json`` names (E12 in
  layer 3) that scene is the deepest must-pass scene and holds its part of the seal key, and the
  other part lies above it (``key_order.py``): nobody can blast round a must-pass scene with the
  complete key.
* **Must-pass slots.** A must-pass encounter slot is a chokepoint if blocking its trigger
  rectangle cuts start from target in the natural (no digging) graph. That is only
  meaningful when start and target are connected naturally; otherwise nothing counts. The
  slot in front of the seal contains the target by construction and is not counted. Each
  layer needs at least ``MIN_MUST_PASS_PER_LAYER`` chokepoint slots.
* **Slots and markers.** Every slot can be walked to from the start; same encounter id at most twice, every capability node covered,
  triggers inside the world and apart from each other, exactly one player spawn, two rest
  areas, one seal, spawns on free cells.
* **No free acid.** There is no acid cell in the grid and no bottle of acid lying around;
  acid comes from barrels (``barrel_acid`` item markers) only.
* **Hazard clearance** (``clearance_checks.py``). No lava, acid or fire within reach of the player's
  hit box from a free position inside a must-pass scene or the tunnels that lead to it, and none
  within the blast radius of the seal key round the hall above the plug (the bomb may come to rest
  anywhere in it).
* **Everything is at rest** (``rest.py``, the simulation's own movement rules). No liquid
  cell (pools, channels, the healing pools) can run out: no free cell, and no lighter liquid,
  below it, on a lower diagonal or beside it. No powder cell can fall or slide: no free cell
  and no lighter liquid below it or on a lower diagonal. A pool with a one-cell gap in its
  corner drains, a heap on a steep slope slides; looking straight down only misses both.
* **Barrels stand on something.** A ``barrel_*`` marker is a free cell on a powder or static
  cell with ``BARREL_CLEARANCE`` free cells above it (contracts section 4).

Soft statistics (not failures) are reported in ``stats``: encounter coverage per
capability node, natural connectivity and so on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import binary_erosion, label
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from .alchemy_checks import check_alchemy
from .canvas import PLAYER_H, PLAYER_W
from .clearance_checks import check_clearance
from .config import BiomeMap, Materials, load_biome_map, load_materials
from .encounter_checks import acid_allowed_mask, check_encounters, dig_zone_mask, plug_mask
from .encounters import BASE_NODES, node_of
from .key_order import check_key_order
from .markers import BARREL_CLEARANCE
from .reach import label_at as _label_at
from .rest import mobile_cells
from .table import Rules, get_rules
from .world import World

STARTER_DIG_MAX_DURABILITY = 10  # DIGGER: max_durability_to_destroy 10 (spells.md KN-2 #15)
MAX_DIG_CELLS = 30
MIN_MUST_PASS_PER_LAYER = 2
MAX_SLOTS_PER_ID = 2
MIN_NODE_COVERAGE = 3  # encounters per capability node, optional ones included
COARSE = 4
BLOCKED = 1.0e6
HAZARD_COST = {"acid": 40.0, "lava": 80.0, "toxic_sludge": 20.0, "flammable_gas": 3.0}
MIN_ENEMIES, MIN_ITEMS = 25, 12
BARREL_KEYS = ("barrel_gunpowder", "barrel_acid", "barrel_oil")
MIN_WORKSHOP_BARRELS = 12  # the workshop is the barrel biome (world-design: chain reactions)
FREE_KINDS = ("air", "gas")  # a spawn or item marker must sit on one of these
SEAL_PROBE_DEPTH = 3  # the leak probe sits this many cells below the room's ceiling
PLAYER_BOX = np.ones((PLAYER_H, PLAYER_W), dtype=bool)
EIGHT = np.ones((3, 3), dtype=bool)  # 8-connectivity: a diagonal squeeze counts as a leak


@dataclass
class CheckReport:
    failures: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    main_path: list[tuple[int, int]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


# ------------------------------------------------------------------- cost model


def dig_cost_table(mats: Materials) -> np.ndarray:
    """Cost to enter a cell of each material, as float32 (256 entries)."""
    table = np.full(256, BLOCKED, dtype=np.float32)
    for i, (key, kind) in enumerate(zip(mats.keys, mats.kinds)):
        if kind in ("air", "gas"):
            table[i] = HAZARD_COST.get(key, 1.0)
        elif kind == "fire":
            table[i] = 40.0
        elif kind == "liquid":
            table[i] = HAZARD_COST.get(key, 2.0)
        elif kind == "powder":
            table[i] = 4.0
        elif kind == "static" and mats.durability[i] <= STARTER_DIG_MAX_DURABILITY:
            table[i] = min(40.0, 2.0 + float(np.ceil(mats.hp[i] / 5000.0)))
    return table


def passable_mask(grid: np.ndarray, mats: Materials) -> np.ndarray:
    """Cells the player can stand in or dig out with the starting wand (brick never)."""
    return dig_cost_table(mats)[grid] < BLOCKED


def _blocks(a: np.ndarray, f: int) -> np.ndarray:
    """View ``a`` as ``(rows/f, f, cols/f, f)`` blocks (edges that do not fill a block are cut)."""
    h, w = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    return a[:h, :w].reshape(h // f, f, w // f, f)


def _coarse_cost(grid: np.ndarray, table: np.ndarray, f: int) -> np.ndarray:
    """Cost grid of ``f`` x ``f`` blocks. A block holding any unpassable cell is BLOCKED.

    Conservative on purpose: averaging would let a route cross a thin brick wall that
    covers only part of a block.
    """
    c = table[grid]
    blocked = _blocks(c >= BLOCKED, f).any(axis=(1, 3))
    cost = _blocks(np.minimum(c, 60.0), f).mean(axis=(1, 3))
    cost[blocked] = BLOCKED
    return cost.astype(np.float32)


def shortest_path(
    cost: np.ndarray, src: tuple[int, int], dst: tuple[int, int]
) -> tuple[list[tuple[int, int]], float] | None:
    """Cheapest 4-connected path on a cost grid; cells are ``(row, col)``."""
    h, w = cost.shape
    idx = np.arange(h * w).reshape(h, w)
    a = np.concatenate(
        [idx[:, :-1].ravel(), idx[:, 1:].ravel(), idx[:-1, :].ravel(), idx[1:, :].ravel()]
    )
    b = np.concatenate(
        [idx[:, 1:].ravel(), idx[:, :-1].ravel(), idx[1:, :].ravel(), idx[:-1, :].ravel()]
    )
    graph = csr_matrix((cost.ravel()[b], (a, b)), shape=(h * w, h * w))
    s, t = src[0] * w + src[1], dst[0] * w + dst[1]
    dist, pred = dijkstra(graph, directed=True, indices=s, return_predecessors=True)
    if not np.isfinite(dist[t]) or dist[t] >= BLOCKED / 2:
        return None
    path, cur = [], t
    while cur != s and cur >= 0:
        path.append((cur // w, cur % w))
        cur = pred[cur]
    path.append((s // w, s % w))
    return path[::-1], float(dist[t])


def _fit_connected(mask: np.ndarray, start: tuple[int, int], target: tuple[int, int]) -> bool:
    """True if the player's box fits along a route of ``mask`` cells from start to target."""
    lab, _ = label(binary_erosion(mask, structure=PLAYER_BOX))
    a, b = _label_at(lab, *start), _label_at(lab, *target)
    return a != 0 and a == b


# ------------------------------------------------------------------- entry point


def run_checks(
    world: World,
    bm: BiomeMap | None = None,
    mats: Materials | None = None,
    rules: Rules | None = None,
) -> CheckReport:
    """Run every post-generation check; ``report.ok`` is False if any failed.

    ``rules`` is the table the encounters were built for (default: the one of the world's own
    ``rule_seed``).
    """
    bm = bm or load_biome_map()
    mats = mats or load_materials()
    rules = rules or get_rules(world.rule_seed)
    rep = CheckReport()
    start = [m for m in world.markers if m["type"] == "spawn_player"]
    seal = [m for m in world.markers if m["type"] == "seal"]
    slots = [m for m in world.markers if m["type"] == "encounter"]
    front = [m for m in slots if m.get("biome") == "seal"]
    _check_markers(world, mats, rep, start, seal, slots)
    if not front:
        rep.failures.append("no encounter slot in front of the seal")
    if rep.failures:
        return rep
    sx, sy = start[0]["x"], start[0]["y"]
    t = front[0]["trigger"]
    target = (t["x"] + t["w"] // 2, t["y"] + t["h"] - 3)

    # natural connectivity (no digging, except where a scene is built to be dug through)
    dug = dig_zone_mask(world, mats, passable_mask(world.grid, mats))
    static = mats.kind_mask(world.grid, "static")
    fit = binary_erosion(~static | dug, structure=PLAYER_BOX)
    lab, _ = label(fit)
    a, b = _label_at(lab, sx, sy), _label_at(lab, *target)
    natural = a != 0 and a == b
    rep.stats["natural_connected"] = natural
    if natural:
        _check_slots_reachable(rep, slots, lab, a)
    passable = passable_mask(world.grid, mats)
    _check_seal(rep, passable, (sx, sy), seal[0], plug_mask(world, seal[0]))
    _check_bypass(rep, passable, (sx, sy), target, slots)
    zones: dict[tuple[int, int, int, int], tuple[np.ndarray, int]] = {}

    def walk(skip: dict | None) -> tuple[np.ndarray, int]:
        """Walking areas with the dig zone inside footprint ``skip`` left undug (cached)."""
        if skip is None:
            return lab, a if natural else 0
        key = (skip["x"], skip["y"], skip["w"], skip["h"])
        if key not in zones:
            undug = dug.copy()
            undug[skip["y"] : skip["y"] + skip["h"], skip["x"] : skip["x"] + skip["w"]] = False
            area, _ = label(binary_erosion(~static | undug, structure=PLAYER_BOX))
            zones[key] = (area, _label_at(area, sx, sy) if natural else 0)
        return zones[key]

    check_encounters(world, rules, mats, rep, lab, a if natural else 0, walk)
    check_key_order(world, bm, rep)
    check_alchemy(
        world, mats, rules, bm, rep.failures, rep.stats, (lab == a) if natural else lab < 0
    )
    if not natural and not _fit_connected(passable, (sx, sy), target):
        rep.failures.append(
            "spawn and seal front are not connected even if the starting wand digs "
            "(brick is never diggable)"
        )
        return rep
    if _check_route(rep, world.grid, mats, (sx, sy), target, natural):
        _check_chokepoints(rep, bm, slots, fit, (sx, sy), target, natural)
    return rep


# ------------------------------------------------------------------------ route


def _dig_estimate(grid: np.ndarray, mats: Materials, path: list[tuple[int, int]]) -> int:
    """Static cells the route crosses: the static share of every block on it, times its length."""
    share = _blocks(mats.kind_mask(grid, "static"), COARSE).mean(axis=(1, 3))
    return int(np.ceil(sum(float(share[r, c]) for r, c in path) * COARSE))


def _check_route(
    rep: CheckReport,
    grid: np.ndarray,
    mats: Materials,
    start: tuple[int, int],
    target: tuple[int, int],
    natural: bool,
) -> bool:
    """Cheapest route (digging allowed) on the coarse grid: main path and dig budget."""
    cost = _coarse_cost(grid, dig_cost_table(mats), COARSE)
    src = (start[1] // COARSE, start[0] // COARSE)
    dst = (target[1] // COARSE, target[0] // COARSE)
    for end in (src, dst):  # the end cells are free cells (checked at full resolution)
        cost[end] = min(cost[end], 1.0)
    res = shortest_path(cost, src, dst)
    if res is None:
        rep.failures.append(
            "no route from the player spawn to the seal front even with digging "
            f"(coarse {COARSE}-px grid: no corridor of passable {COARSE}x{COARSE} blocks)"
        )
        return False
    path, total = res
    # the coarse estimate only measures how close a natural route runs to walls
    dig = 0 if natural else _dig_estimate(grid, mats, path)
    rep.main_path = [(c * COARSE + COARSE // 2, r * COARSE + COARSE // 2) for r, c in path]
    rep.stats.update(dig_cells=dig, route_cost=round(total, 1), route_length=len(path) * COARSE)
    if dig > MAX_DIG_CELLS:
        rep.failures.append(
            f"spawn and seal front are not connected; the cheapest route digs {dig} cells "
            f"(limit {MAX_DIG_CELLS})"
        )
    return True


def _check_seal(
    rep: CheckReport,
    passable: np.ndarray,
    start: tuple[int, int],
    seal: dict,
    plug: np.ndarray,
) -> None:
    """Nobody gets deeper than the plug's top edge without opening the plug.

    ``plug`` marks the cells of the seal's plug (the brick the breaker has to remove). With it in
    place, no cell of the room, nor any cell at all in the rows from the plug's top edge down to
    the world's bottom, is connected to the start through free or diggable cells (8-connected:
    a diagonal squeeze counts). That is stronger than "the room is closed": a digger could
    otherwise tunnel through the rock beside the vault to the world's last row. The positive
    control: with the plug forced passable the room is reached, and what lies deeper than the
    plug's top edge and is reached is the plug and the room only.
    """
    r = seal["room"]
    cx, cy = r["x"] + r["w"] // 2, r["y"] + SEAL_PROBE_DEPTH
    if not passable[cy, cx]:
        rep.failures.append(f"the sealed room is not open at its probe cell ({cx}, {cy})")
        return
    top = seal["y"]
    sx, sy = start
    lab, _ = label(passable, structure=EIGHT)
    mine = (lab == lab[sy, sx]) & passable if lab[sy, sx] else np.zeros_like(passable)
    deep = mine[top:]
    n_deep = int(deep.sum())
    rep.stats["seal_deep_cells"] = n_deep
    rep.stats["deepest_reach_y"] = int(np.nonzero(mine.any(axis=1))[0].max()) if mine.any() else -1
    rep.stats["seal_sealed"] = not mine[cy, cx] and n_deep == 0
    if mine[cy, cx]:
        rep.failures.append("the sealed room is reachable from the spawn without breaking the seal")
    if n_deep:
        ys, xs = np.nonzero(deep)
        i = int(np.argmax(ys))
        rep.failures.append(
            f"{n_deep} free or diggable cells deeper than the plug's top edge (y >= {top}) are "
            f"joined to the spawn without opening the plug, down to ({int(xs[i])}, "
            f"{int(ys[i]) + top}): a digger gets past the seal there"
        )
    lab, _ = label(passable | plug, structure=EIGHT)
    reached = (lab == lab[sy, sx]) & (passable | plug) if lab[sy, sx] else np.zeros_like(passable)
    opens = bool(reached[cy, cx])
    rep.stats["seal_opens"] = opens
    if not opens:
        rep.failures.append("the sealed room cannot be reached even with the plug removed")
        return
    room = np.zeros_like(passable)
    room[r["y"] : r["y"] + r["h"], r["x"] : r["x"] + r["w"]] = True
    behind = reached[top:] & ~plug[top:] & ~room[top:]
    rep.stats["seal_behind_plug"] = int(behind.sum())
    if behind.any():
        ys, xs = np.nonzero(behind)
        rep.failures.append(
            f"{int(behind.sum())} free or diggable cells besides the sealed room lie behind the "
            f"plug (e.g. ({int(xs[0])}, {int(ys[0]) + top})): the plug opens onto more than the room"
        )


def _check_bypass(
    rep: CheckReport,
    passable: np.ndarray,
    start: tuple[int, int],
    target: tuple[int, int],
    slots: list[dict],
) -> None:
    """No must-pass scene can be walked or dug around (brick is never diggable).

    ``passable`` holds every cell the player can stand in or dig out with the starting wand
    (``passable_mask``: brick never). For each must-pass scene the cells of its footprint are
    removed; the start and the seal front must then lie in different areas (8-connected: a
    diagonal squeeze between two bricks counts as a leak). The control: with nothing removed
    they are connected, so each scene is on every route, not on none. The sealed deep is left
    out: its plug is the cut (``_check_seal``).
    """
    sx, sy = start
    tx, ty = target
    chokes = [s for s in slots if s["must_pass"] and not _contains(s["trigger"], target)]
    rep.stats["bypass_checked"] = len(chokes)
    if not (passable[sy, sx] and passable[ty, tx]):
        rep.failures.append("the spawn or the seal front is not a free cell (bypass check)")
        return
    lab, _ = label(passable, structure=EIGHT)
    if lab[sy, sx] != lab[ty, tx]:
        rep.failures.append(
            "no route of free and diggable cells from the spawn to the seal front, even with "
            "every scene open (control of the bypass check)"
        )
        return
    for s in chokes:
        fp = s.get("footprint") or s["trigger"]
        cut = passable.copy()
        cut[fp["y"] : fp["y"] + fp["h"], fp["x"] : fp["x"] + fp["w"]] = False
        lab, _ = label(cut, structure=EIGHT)
        if lab[sy, sx] != 0 and lab[sy, sx] == lab[ty, tx]:
            rep.failures.append(
                f"must-pass encounter {s['encounter_id']} at ({fp['x']}, {fp['y']}) can be "
                "bypassed: free and diggable cells lead from the spawn to the seal front "
                "around it (no brick seam closes the world there)"
            )


def _check_slots_reachable(
    rep: CheckReport, slots: list[dict], lab: np.ndarray, start_label: int
) -> None:
    """Every encounter slot must be walkable from the start without digging."""
    for s in slots:
        t = s["trigger"]
        inside = lab[t["y"] : t["y"] + t["h"], t["x"] : t["x"] + t["w"]]
        if not (inside == start_label).any():
            rep.failures.append(f"encounter {s['encounter_id']} at {t} cannot be reached on foot")


# ------------------------------------------------------------------ chokepoints


def _contains(trigger: dict, point: tuple[int, int]) -> bool:
    return (
        trigger["x"] <= point[0] < trigger["x"] + trigger["w"]
        and trigger["y"] <= point[1] < trigger["y"] + trigger["h"]
    )


def _check_chokepoints(
    rep: CheckReport,
    bm: BiomeMap,
    slots: list[dict],
    fit: np.ndarray,
    start: tuple[int, int],
    target: tuple[int, int],
    natural: bool,
) -> None:
    """Each layer needs ``MIN_MUST_PASS_PER_LAYER`` must-pass slots that cannot be bypassed."""
    per_layer = {str(lay.layer): 0 for lay in bm.layers}
    rep.stats["must_pass_chokepoints"] = per_layer
    if not natural:
        rep.failures.append(
            "must-pass chokepoints cannot be established: spawn and seal front are not "
            "connected without digging"
        )
        return
    must_pass = [s for s in slots if s["must_pass"] and not _contains(s["trigger"], target)]
    for s in must_pass:
        if is_chokepoint(fit, s["trigger"], start, target, connected=True):
            per_layer[str(s["layer"])] += 1
    for lay in bm.layers:
        n = per_layer.get(str(lay.layer), 0)
        if n < MIN_MUST_PASS_PER_LAYER:
            rep.failures.append(
                f"layer {lay.layer}: only {n} must-pass chokepoint slots "
                f"(need {MIN_MUST_PASS_PER_LAYER})"
            )


def is_chokepoint(
    fit: np.ndarray,
    trigger: dict,
    start: tuple[int, int],
    target: tuple[int, int],
    connected: bool | None = None,
) -> bool:
    """True if blocking the trigger rectangle cuts ``start`` from ``target`` without digging.

    Only defined when the two are connected without the block (``connected``; computed
    here if not given): otherwise every rectangle would "cut" them and the answer is False.
    """
    if connected is None:
        lab0, _ = label(fit)
        a0, b0 = _label_at(lab0, *start), _label_at(lab0, *target)
        connected = a0 != 0 and a0 == b0
    if not connected:
        return False
    x0, y0, w, h = trigger["x"], trigger["y"], trigger["w"], trigger["h"]
    if _contains(trigger, target):
        return True
    blocked = fit.copy()
    blocked[y0 : y0 + h, x0 : x0 + w] = False
    lab, _ = label(blocked)
    a, b = _label_at(lab, *start), _label_at(lab, *target)
    return not (a != 0 and a == b)


# ---------------------------------------------------------------------- markers


def _check_markers(world: World, mats: Materials, rep: CheckReport, start, seal, slots) -> None:
    if len(start) != 1:
        rep.failures.append(f"expected 1 spawn_player, found {len(start)}")
    if len(seal) != 1:
        rep.failures.append(f"expected 1 seal, found {len(seal)}")
    rests = [m for m in world.markers if m["type"] == "rest_area"]
    if len(rests) != 2:
        rep.failures.append(f"expected 2 rest_area markers, found {len(rests)}")
    enemies = [m for m in world.markers if m["type"] == "spawn_enemy"]
    items = [m for m in world.markers if m["type"] == "item"]
    if len(enemies) < MIN_ENEMIES:
        rep.failures.append(f"only {len(enemies)} enemy spawns (need {MIN_ENEMIES})")
    if len(items) < MIN_ITEMS:
        rep.failures.append(f"only {len(items)} items (need {MIN_ITEMS})")
    barrels = {k: sum(1 for m in items if m["item"] == k) for k in BARREL_KEYS}
    rep.stats.update(enemies=len(enemies), items=len(items), barrels=barrels)
    _check_marker_cells(world, mats, rep)
    _check_slots(world, rep, slots)
    _check_acid(world, mats, rep, items)
    check_clearance(world, mats, rep.failures, rep.stats)
    _check_at_rest(world, mats, rep)
    _check_barrels(world, mats, rep, items)
    _check_workshop_barrels(world, rep, items)


def _check_marker_cells(world: World, mats: Materials, rep: CheckReport) -> None:
    """Every marker lies inside the world; spawns and items stand on free cells."""
    for m in world.markers:
        x, y = m["x"], m["y"]
        if not (0 <= x < world.width and 0 <= y < world.height):
            rep.failures.append(f"marker {m['type']} at ({x}, {y}) is outside the world")
            continue
        on_free_cell = mats.kinds[world.grid[y, x]] in FREE_KINDS
        if m["type"] in ("spawn_player", "spawn_enemy", "item") and not on_free_cell:
            rep.failures.append(f"marker {m['type']} at ({x}, {y}) is not on a free cell")


def _apart(a: dict, b: dict) -> bool:
    return (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )


def _check_slots(world: World, rep: CheckReport, slots: list[dict]) -> None:
    """Encounter slots: id limit, capability coverage, triggers inside the world and apart."""
    ids: dict[str, int] = {}
    node_count: dict[str, int] = {}
    for s in slots:
        ids[s["encounter_id"]] = ids.get(s["encounter_id"], 0) + 1
        node = node_of(s["encounter_id"])
        node_count[node] = node_count.get(node, 0) + 1
    for eid, n in sorted(ids.items()):
        if n > MAX_SLOTS_PER_ID:
            rep.failures.append(f"encounter {eid} appears {n} times (max {MAX_SLOTS_PER_ID})")
    for node in BASE_NODES:
        if node_count.get(node, 0) < MIN_NODE_COVERAGE:
            rep.failures.append(
                f"capability node {node} has only {node_count.get(node, 0)} encounters"
            )
    triggers = [(s["encounter_id"], s["trigger"]) for s in slots]
    for i, (eid, t) in enumerate(triggers):
        inside = 0 <= t["x"] and t["x"] + t["w"] <= world.width
        inside = inside and 0 <= t["y"] and t["y"] + t["h"] <= world.height
        if not inside:
            rep.failures.append(f"encounter {eid} trigger {t} reaches outside the world")
        for other, u in triggers[i + 1 :]:
            if not _apart(t, u):
                rep.failures.append(f"encounter triggers {eid} and {other} overlap")
    rep.stats.update(
        encounters=len(slots),
        must_pass=sum(1 for s in slots if s["must_pass"]),
        node_coverage=dict(sorted(node_count.items())),
    )


def _check_acid(world: World, mats: Materials, rep: CheckReport, items: list[dict]) -> None:
    """No free acid: none in the grid outside the brick vats of scenes, none in a bottle."""
    acid = world.grid == mats["acid"]
    loose = int((acid & ~acid_allowed_mask(world)).sum())
    bottles = sum(1 for m in items if m["item"] == "bottle" and m.get("contents") == "acid")
    rep.stats["vat_acid_cells"] = int(acid.sum()) - loose
    if loose or bottles:
        rep.failures.append(
            f"free acid: {loose} acid cells outside scene vats and {bottles} bottles of acid "
            "(acid comes from barrels and brick vats only)"
        )


def _check_workshop_barrels(world: World, rep: CheckReport, items: list[dict]) -> None:
    """The abandoned workshop holds the barrels: at least ``MIN_WORKSHOP_BARRELS`` of them."""
    cs = world.biome_cell_size
    cells = world.biome_map
    inside = []
    for m in items:
        if m["item"] in BARREL_KEYS and cells[m["y"] // cs][m["x"] // cs] == "workshop":
            inside.append(m)
    rep.stats["workshop_barrels"] = len(inside)
    if len(inside) < MIN_WORKSHOP_BARRELS:
        rep.failures.append(
            f"only {len(inside)} barrels in the workshop (need {MIN_WORKSHOP_BARRELS})"
        )


def _check_at_rest(world: World, mats: Materials, rep: CheckReport) -> None:
    """No powder or liquid cell would move as soon as the simulation starts (``rest.py``)."""
    powder = len(mobile_cells(world.grid, mats, "powder")[0])
    liquid = len(mobile_cells(world.grid, mats, "liquid")[0])
    rep.stats["hanging_powder"] = powder
    rep.stats["liquid_leaks"] = liquid
    if powder:
        rep.failures.append(
            f"{powder} powder cells have no support: they would fall or slide when the "
            "simulation starts"
        )
    if liquid:
        rep.failures.append(
            f"{liquid} liquid cells have a free cell below, beside or diagonally below them "
            "(a pool would run out)"
        )


def _check_barrels(world: World, mats: Materials, rep: CheckReport, items: list[dict]) -> None:
    """A barrel marker stands on a floor cell with room above it (contracts section 4)."""
    g = world.grid
    bad = 0
    for m in items:
        if m["item"] not in BARREL_KEYS:
            continue
        x, y = m["x"], m["y"]
        free = y >= BARREL_CLEARANCE and y + 1 < world.height
        free = free and bool((g[y - BARREL_CLEARANCE : y + 1, x] == mats.air).all())
        if not (free and mats.kinds[g[y + 1, x]] in ("powder", "static")):
            bad += 1
    rep.stats["bad_barrels"] = bad
    if bad:
        rep.failures.append(
            f"{bad} barrel markers do not stand on a floor with {BARREL_CLEARANCE} free cells above"
        )
