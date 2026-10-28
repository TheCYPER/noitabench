"""Alchemy supplies (D2b, CP2 decision of 2026-10-27): ingredients, bottles and metal bowls.

Only the secret recipes change from seed to seed; an agent finds them by trying. For that every
world has to hand out the twelve ingredient materials (tag ``ingredient``: water, blood, oil,
whiskey, toxic sludge, sand, coal, gunpowder, gold dust, bone dust, fungus powder, slime), the
means to carry them, and a place to try them:

* **Deposits** (``supply.deposits`` of a biome file): piles of powder and pools of liquid that
  the biome is guaranteed to hold, built where the player can stand beside them, resting at frame
  0, and kept ``DEPOSIT_GAP`` cells away from other ingredients (two ingredients touching is
  harmless, but there is no reason to give three of a recipe the chance to meet). The gap holds
  where a deposit is put; the settling pass may still carry a heap down a ledge, and coal veins
  are everywhere in the coal pits, so what guarantees that no three ingredients touch (no potion
  at frame 0 for any rule seed) is the check of ``alchemy_checks.py`` (``mixing.py``): a world
  that fails it is rebuilt.
* **Bottles** (``supply.bottles``, the start area and the rest halls): the only way to carry a
  powder is a bottle that is already full of it (``fill`` scoops liquids only), so every
  ingredient has a full bottle lying about; empty bottles lie in the start area, the rest halls
  and every biome of the first two layers.
* **Bowls** (``bowls.py``): metal basins sunk into the floor, one in every rest hall (built by
  ``scenes.build_rest``) and ``supply.bowls`` per biome in caves, in a niche carved beside a
  deposit.

Nothing here ever places a secret potion: a potion exists only as the product of a recipe
(``alchemy_checks.py`` verifies this on every world).

The numbers (data: ``supply`` of ``content/biomes/*.json``, ``scenes.alchemy`` of
``content/biome_map.json``):

* every ingredient has a required deposit of 60 to 70 cells or more in one biome (layer 1: gold
  dust, blood and water in the mine, bone dust, gunpowder, coal and oil in the coal pits, sand in
  the sand caves; layer 2: toxic sludge and fungus powder in the fungal caverns, slime and fungus
  powder in the swamp, whiskey in the oil caverns) and optional extra heaps of gold dust and bone
  dust in layer 3 and of bone dust and fungus powder in the fungal caverns; a pile is 70 to 146
  cells, a pool 60 to 570;
* one full bottle (400 cells) of every ingredient lies in the biome of its deposit;
* empty bottles: 2 in the start area, 2 beside the bowl of each rest hall, 1 in each biome of
  layers 1 and 2 (12 of them, 7 before the second layer, plus the containers of the E07 scenes);
* bowls: 1 per rest hall, 1 in layer 1 (the mine) and 2 in layer 2 (the fungal and oil caverns);
* a world fails unless every ingredient has 40 cells and a full bottle within reach of where the
  player can walk (``alchemy_checks.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from .bowls import FLAT_FILL, FLAT_MARGIN, HEAD_ROOM, BowlSpec, stamp_bowl
from .canvas import Canvas, GenerationFailure, Rect
from .config import KIND_CODES, Biome, DepositSpec
from .features import PILE_LIQUID_GAP, POOL_GAP, any_near, find_basin, floor_points, heap
from .markers import ITEM_SPACING, spawn_candidates
from .reach import dig_zone_cells, reach_mask, walk_area
from .structures import guarded

MAX_TRIES = 120  # floor points tried for one bottle or one bowl
NATURAL_TRIES = 60  # heaps and basins tried before the deposit is dug as a pit instead
PIT_TRIES = 1500  # floor points tried for a pit (about all of a biome's)
PIT_WIDTH = (12, 22)  # width of a pit, wall to wall
PIT_SAFETY = 2  # no loose cell this near a pit's walls
PIT_OPEN_SHARE = 0.6  # at least this share of a pit's columns have air above them
DEPOSIT_GAP = 10  # cells between a deposit and any loose cell of another ingredient
BOTTLE_NEAR = (8, 45)  # a full bottle lies this far from a deposit of its material, if there is one
BOWL_ANCHOR = 40  # a cave bowl lies about this far from a deposit of its biome
BOWL_APART = 70  # cells between two cave bowls
BOWL_SAFETY = 3  # no liquid, gas, fire or powder this near a cave bowl's working area
BOWL_SHIFTS = (0, -6, 6, -12, 12)  # the bowl may sit this far off a floor point (cells)
SITE_SAMPLE = 400  # floor points whose sites are examined first (all of them if too few fit)
MIN_OPEN_SHARE = 0.4  # at least this much of a cave bowl's open box is cave already
EDGE_MARGIN = 6  # a cave bowl keeps this far inside the ring of its region


def walk_reach(
    canvas: Canvas, spawn: tuple[int, int], slots: Sequence[dict], defs: dict, reach: int
) -> np.ndarray:
    """Mask of the cells within ``reach`` of where the player can walk, from the spawn.

    ``slots`` are the slot dicts of the generator; those that carry a dig-zone scene (E08, E12)
    may be crossed by digging, as in the post-generation check.
    """
    zones = [
        (f["x"], f["y"], f["w"], f["h"])
        for s in slots
        if not s.get("placeholder", True)
        and (d := defs.get(s["encounter_id"])) is not None
        and d.dig_zone
        and (f := s.get("footprint")) is not None
    ]
    dug = dig_zone_cells(canvas.grid, canvas.mats, zones)
    walk = walk_area(canvas.grid, canvas.mats, spawn, dug)
    return reach_mask(canvas.grid, canvas.mats, walk, reach)


# ----------------------------------------------------------------------------- deposits


def _loose_table(canvas: Canvas, material: int) -> np.ndarray:
    """Per material: a loose ingredient other than ``material`` (coal veins are left out)."""
    mats = canvas.mats
    table = np.zeros(256, dtype=bool)
    for key in mats.with_tag("ingredient"):
        if key != "coal":
            table[mats[key]] = True
    table[material] = False
    return table


def _ingredient_near(canvas: Canvas, material: int, box: Rect, pad: int = DEPOSIT_GAP) -> bool:
    x0, y0, x1, y1 = canvas.clip((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))
    return bool(_loose_table(canvas, material)[canvas.grid[y0:y1, x0:x1]].any())


def _liquid_test(canvas: Canvas) -> Callable[[np.ndarray], np.ndarray]:
    """The mask function ``features.any_near`` wants: which cells of a window are liquid."""

    def test(sub: np.ndarray) -> np.ndarray:
        return canvas.mats.kind_mask(sub, "liquid")

    return test


def _try_pile(
    canvas: Canvas, spec: DepositSpec, sx: int, sy: int, rng: np.random.Generator, rect: Rect
) -> int:
    """Heap powder around ``(sx, sy)``; returns the cells placed (0 if the site was refused)."""
    mat = canvas.mats[spec.material]
    r = int(rng.integers(spec.size[0], spec.size[1] + 1))
    xs, ys = np.array([sx - r, sx + r]), np.array([sy - r, sy + 6])
    if any_near(canvas, (xs, ys), PILE_LIQUID_GAP, _liquid_test(canvas)):
        return 0
    if _ingredient_near(canvas, mat, (sx - r, sy - r, sx + r + 1, sy + 7)):
        return 0
    x0, y0, x1, y1 = canvas.clip((sx - r, sy - r, sx + r + 1, sy + 7))
    snapshot = canvas.grid[y0:y1, x0:x1].copy()
    before = int((snapshot == mat).sum())
    heap(canvas, sx, sy, r, mat, rect)
    cells = int((canvas.grid[y0:y1, x0:x1] == mat).sum()) - before
    if cells < spec.min_cells:
        canvas.grid[y0:y1, x0:x1] = snapshot
        return 0
    return cells


def _try_pool(
    canvas: Canvas, spec: DepositSpec, sx: int, sy: int, rng: np.random.Generator, rect: Rect
) -> int:
    """Fill a closed basin at ``(sx, sy)`` with liquid; returns the cells placed (0 if refused)."""
    mat = canvas.mats[spec.material]
    depth = int(rng.integers(spec.size[0], spec.size[1] + 1))
    cells = find_basin(canvas, sx, sy, depth, spec.max_area, False, rect)
    if cells is None or len(cells[0]) < spec.min_cells:
        return 0
    xs, ys = cells
    if any_near(canvas, cells, POOL_GAP, _liquid_test(canvas)):
        return 0
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    if _ingredient_near(canvas, mat, box):
        return 0
    canvas.grid[ys, xs] = mat
    return len(xs)


def _try_pit(
    canvas: Canvas, spec: DepositSpec, sx: int, sy: int, rng: np.random.Generator, rect: Rect
) -> int:
    """Dig a pit into the floor at ``(sx, sy)`` and fill it level with the floor: a bin of the
    ingredient (a pool of liquid, a bed of powder), walled in by solid ground on every side.

    The fallback when no natural heap or basin is found. The pit is ``w`` wide and deep enough
    for ``min_cells`` cells; the cells under its row of surface and its walls must be ground,
    rock or coal; nothing loose lies within ``PIT_SAFETY`` of it; most of its surface is open to
    the air. Returns the cells filled (0 if the site was refused).
    """
    g, mats = canvas.grid, canvas.mats
    mat = mats[spec.material]
    lo, hi = PIT_WIDTH
    w = int(rng.integers(lo, hi + 1))
    d = max(spec.size[0], -(-spec.min_cells // w))
    d = min(d, spec.size[1] + 2)
    x0, top = sx - w // 2, sy + 1
    x1, bottom = x0 + w, top + d
    if w * d < spec.min_cells:
        return 0
    bx0, by0, bx1, by1 = x0 - 1, top, x1 + 1, bottom + 1
    cx0, cy0, cx1, cy1 = canvas.clip(
        (bx0 - PIT_SAFETY, by0 - 3, bx1 + PIT_SAFETY, by1 + PIT_SAFETY)
    )
    if (cx0, cy0, cx1, cy1) != (bx0 - PIT_SAFETY, by0 - 3, bx1 + PIT_SAFETY, by1 + PIT_SAFETY):
        return 0
    if (
        bx0 <= rect[0]
        or bx1 >= rect[2]
        or by1 >= rect[3]
        or canvas.protected[by0:by1, bx0:bx1].any()
    ):
        return 0
    around = g[cy0:cy1, cx0:cx1]
    kinds = mats.kind_code[around]
    loose = [KIND_CODES[k] for k in ("liquid", "gas", "fire")]
    if (np.isin(kinds, loose) | ((kinds == KIND_CODES["powder"]) & (around != mats["coal"]))).any():
        return 0
    # solid below the surface row and in the walls; the surface row itself may hold air
    body = g[top + 1 : by1, bx0:bx1]
    surface = g[top, x0:x1]
    walls = np.concatenate([g[top : bottom + 1, bx0], g[top : bottom + 1, bx1 - 1]])
    if not (_carvable(canvas, body).all() and _carvable(canvas, walls).all()):
        return 0
    if not (_carvable(canvas, surface) | (surface == mats.air)).all():
        return 0
    if (g[top - 3 : top, x0:x1] == mats.air).all(axis=0).mean() < PIT_OPEN_SHARE:
        return 0
    if _ingredient_near(canvas, mat, (x0, top, x1, bottom)):
        return 0
    g[top:bottom, x0:x1] = mat
    return w * d


def _standing_points(canvas: Canvas, rect: Rect, near: np.ndarray) -> np.ndarray:
    pts = floor_points(canvas, rect)
    return pts[near[pts[:, 1], pts[:, 0]]] if len(pts) else pts


def place_deposits(
    canvas: Canvas,
    biome: Biome,
    rect: Rect,
    rng: np.random.Generator,
    near: np.ndarray,
    form: str,
) -> list[dict]:
    """The ``form`` ("pool" or "pile") deposits ``biome.supply`` demands, each on a floor point
    within reach of the player.

    The generator places the pools of a biome before its heaps (a heap beside a pool sinks into
    it), so it calls this twice. Raises ``GenerationFailure`` if a required deposit finds no place
    (the world is rebuilt).
    """
    out: list[dict] = []
    for spec in biome.supply.deposits:
        if spec.form != form:
            continue
        for _ in range(spec.count):
            found = _one_deposit(canvas, biome.key, spec, rect, rng, near)
            if found is not None:
                out.append(found)
            elif not spec.optional:
                raise GenerationFailure(
                    f"{biome.key}: no place for a deposit of {spec.material} "
                    f"(at least {spec.min_cells} cells within the player's reach)"
                )
    return out


def _one_deposit(
    canvas: Canvas,
    biome: str,
    spec: DepositSpec,
    rect: Rect,
    rng: np.random.Generator,
    near: np.ndarray,
) -> dict | None:
    pts = _standing_points(canvas, rect, near)
    if len(pts) == 0:
        return None
    natural = _try_pile if spec.form == "pile" else _try_pool
    for shape, try_one, tries in (
        ("heap" if spec.form == "pile" else "basin", natural, NATURAL_TRIES),
        ("pit", _try_pit, PIT_TRIES),
    ):
        for i in rng.permutation(len(pts))[:tries]:
            sx, sy = int(pts[i][0]), int(pts[i][1])
            cells = try_one(canvas, spec, sx, sy, rng, rect)
            if cells:
                return {
                    "material": spec.material,
                    "form": spec.form,
                    "shape": shape,
                    "biome": biome,
                    "x": sx,
                    "y": sy,
                    "cells": cells,
                }
    return None


# ----------------------------------------------------------------------------- bottles


def bottle_marker(x: int, y: int, contents: str = "") -> dict:
    """An ``item`` marker for a bottle: full of ``contents``, or empty."""
    marker = {"type": "item", "x": int(x), "y": int(y), "item": "bottle"}
    if contents:
        marker["contents"] = contents
    return marker


def _free_of(taken: np.ndarray, x: int, y: int, spacing: float) -> bool:
    return len(taken) == 0 or float(np.min(np.hypot(taken[:, 0] - x, taken[:, 1] - y))) >= spacing


def place_bottles(
    canvas: Canvas,
    biome: Biome,
    rect: Rect,
    rng: np.random.Generator,
    near: np.ndarray,
    deposits: Sequence[dict],
    taken: list[tuple[int, int]],
) -> list[dict]:
    """The bottles ``biome.supply`` demands, standing within reach; full ones near their deposit.

    ``taken`` lists the spots of other markers (kept ``ITEM_SPACING`` away); it grows by every
    bottle placed here.
    """
    cand = spawn_candidates(canvas, rect)
    if len(cand):
        cand = cand[near[cand[:, 1], cand[:, 0]]]
    out: list[dict] = []
    for spec in biome.supply.bottles:
        homes = [(d["x"], d["y"]) for d in deposits if d["material"] == spec.contents]
        for _ in range(spec.count):
            site = _bottle_site(cand, rng, taken, homes)
            if site is None:
                raise GenerationFailure(
                    f"{biome.key}: no place for a bottle of {spec.contents or 'nothing'}"
                )
            out.append(bottle_marker(*site, spec.contents))
            taken.append(site)
    return out


def _bottle_site(
    cand: np.ndarray,
    rng: np.random.Generator,
    taken: list[tuple[int, int]],
    homes: list[tuple[int, int]],
) -> tuple[int, int] | None:
    """A standing point beside a deposit (``homes``) if there is one, else anywhere."""
    if len(cand) == 0:
        return None
    spots = np.array(taken, dtype=float).reshape(-1, 2)
    order = rng.permutation(len(cand))
    if homes:
        lo, hi = BOTTLE_NEAR
        pts = np.array(homes, dtype=float)
        dist = np.min(
            np.hypot(cand[:, None, 0] - pts[None, :, 0], cand[:, None, 1] - pts[None, :, 1]), axis=1
        )
        mid = (lo + hi) / 2
        order = sorted(order, key=lambda i: (not lo <= dist[i] <= hi, abs(dist[i] - mid)))
    for i in order[: MAX_TRIES * 4]:
        x, y = int(cand[i][0]), int(cand[i][1])
        if _free_of(spots, x, y, ITEM_SPACING):
            return x, y
    return None


# ------------------------------------------------------------------------------- bowls


def _carvable(canvas: Canvas, sub: np.ndarray) -> np.ndarray:
    """Cells a niche may be cut into: ground, rock and timber (coal veins are left alone: a vein
    cut from its support falls into the bowl when the terrain settles)."""
    mats = canvas.mats
    return (sub == mats["ground"]) | (sub == mats["rock"]) | (sub == mats["wood"])


def _site_problem(canvas: Canvas, spec: BowlSpec, bx: int, rim: int, inner: Rect) -> str:
    """Why a cave bowl with its left edge at ``bx`` and its rim at row ``rim`` cannot be built.

    Empty if it can. Working area: ``FLAT_MARGIN`` cells of flat floor beside the bowl and
    ``HEAD_ROOM`` open rows above the rim. It may hold air, ground, rock and timber only (brick is
    a scene's or a seam's); no protected cell, and no liquid, gas, fire or powder (coal veins
    included: they would fall into the bowl) within ``BOWL_SAFETY`` of it (a niche must never open
    a pool or a sealed pocket of sand or lava). Whatever the bowl's box held (a thin floor over a
    cave, say) is replaced by metal; the floor beside the bowl is levelled up to ``FLAT_FILL``
    rows, so it must be solid just below that.
    """
    g, mats = canvas.grid, canvas.mats
    ow, oh = spec.outer_w, spec.outer_h
    x0, x1 = bx - FLAT_MARGIN, bx + ow + FLAT_MARGIN
    top, bottom = rim - HEAD_ROOM, rim + oh
    ix0, iy0, ix1, iy1 = inner
    if x0 - BOWL_SAFETY < ix0 or x1 + BOWL_SAFETY > ix1:
        return "edge"
    if top - BOWL_SAFETY < iy0 or bottom + BOWL_SAFETY > iy1:
        return "edge"
    work = g[top:bottom, x0:x1]
    around = g[top - BOWL_SAFETY : bottom + BOWL_SAFETY, x0 - BOWL_SAFETY : x1 + BOWL_SAFETY]
    kinds = mats.kind_code[around]
    loose = [KIND_CODES[k] for k in ("liquid", "gas", "fire", "powder")]
    if np.isin(kinds, loose).any():
        return "pocket"
    if canvas.protected[top:bottom, x0:x1].any():
        return "protected"
    if not (_carvable(canvas, work) | (work == mats.air)).all():
        return "material"
    if (work[:HEAD_ROOM] == mats.air).mean() < MIN_OPEN_SHARE:
        return "closed"
    margin = np.r_[np.arange(x0, bx), np.arange(bx + ow, x1)]
    return "" if _carvable(canvas, g[rim + FLAT_FILL, margin]).all() else "margin"


def _build_site(canvas: Canvas, spec: BowlSpec, bx: int, rim: int) -> dict:
    """Carve the open box, level the margins and stamp the bowl; returns its marker."""
    g, mats = canvas.grid, canvas.mats
    ow = spec.outer_w
    x0, x1 = bx - FLAT_MARGIN, bx + ow + FLAT_MARGIN
    box = g[rim - HEAD_ROOM : rim, x0:x1]
    box[_carvable(canvas, box)] = mats.air
    for xs in (slice(x0, bx), slice(bx + ow, x1)):
        floor = g[rim : rim + FLAT_FILL, xs]
        floor[floor == mats.air] = mats["ground"]
    return stamp_bowl(canvas, spec, bx, rim, "cave")


def place_cave_bowls(
    canvas: Canvas,
    spec: BowlSpec,
    count: int,
    rect: Rect,
    inner: Rect,
    rng: np.random.Generator,
    near: np.ndarray,
    anchors: Sequence[tuple[int, int]],
    apart: Sequence[tuple[int, int]],
) -> list[dict]:
    """Up to ``count`` bowls in niches beside floor points within reach, near ``anchors``.

    ``inner`` is the box the whole working area must lie in, ``apart`` the centres of bowls
    already built (kept ``BOWL_APART`` away). Of the sites that fit, those about ``BOWL_ANCHOR``
    cells from an anchor (a deposit of the biome) come first; a niche that would cut a passage is
    undone (``structures.guarded``). Returns the markers of the bowls built; the caller decides
    whether a shortfall fails the world.
    """
    placed: list[dict] = []
    pts = _standing_points(canvas, rect, near)
    if len(pts) == 0 or count <= 0:
        return placed
    sites = _bowl_sites(canvas, spec, pts, inner, rng, SITE_SAMPLE)
    if len(sites) < 3 * count:  # a sparse biome: look at every floor point
        sites = _bowl_sites(canvas, spec, pts, inner, rng, None)
    if anchors and sites:
        a = np.array(anchors, dtype=float)
        at = np.array([(bx + spec.outer_w // 2, rim) for bx, rim in sites], dtype=float)
        dx, dy = at[:, None, 0] - a[None, :, 0], at[:, None, 1] - a[None, :, 1]
        dist = np.min(np.hypot(dx, dy), axis=1)
        sites = [sites[k] for k in np.argsort(np.abs(dist - BOWL_ANCHOR), kind="stable")]
    centres = list(apart)
    for bx, rim in sites:
        if len(placed) >= count:
            break
        px, py = bx + spec.outer_w // 2, rim - 1
        if any(np.hypot(px - cx, py - cy) < BOWL_APART for cx, cy in centres):
            continue
        area = (
            bx - FLAT_MARGIN,
            rim - HEAD_ROOM,
            bx + spec.outer_w + FLAT_MARGIN,
            rim + spec.outer_h,
        )
        if marker := _guarded_site(canvas, spec, bx, rim, area):
            canvas.protect((bx, rim - 2, bx + spec.outer_w, rim + spec.outer_h))
            placed.append(marker)
            centres.append((px, py))
    return placed


def _bowl_sites(
    canvas: Canvas,
    spec: BowlSpec,
    pts: np.ndarray,
    inner: Rect,
    rng: np.random.Generator,
    sample: int | None,
) -> list[tuple[int, int]]:
    """Every ``(bx, rim)`` that fits, in random order: each floor point of a random ``sample`` of
    them (all if ``None``) with ``BOWL_SHIFTS``."""
    out: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for i in rng.permutation(len(pts))[:sample]:
        px, py = int(pts[i][0]), int(pts[i][1])
        for shift in BOWL_SHIFTS:
            site = (px - spec.outer_w // 2 + shift, py + 1)
            if site not in seen:
                seen.add(site)
                if not _site_problem(canvas, spec, *site, inner):
                    out.append(site)
    return out


def _guarded_site(canvas: Canvas, spec: BowlSpec, bx: int, rim: int, area: Rect) -> dict | None:
    """Build the site; ``None`` (and the terrain as it was) if that would cut a passage."""
    made: list[dict] = []

    def build() -> None:
        made.append(_build_site(canvas, spec, bx, rim))

    return made[0] if guarded(canvas, area, build) else None
