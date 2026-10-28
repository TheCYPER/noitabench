"""Routes through a must-pass scene: can a digger get past its obstacle without solving it?

A must-pass band scene is a closed box with two doors (contracts section 4): a player who digs but
cannot break brick or metal (durability 14 and 15, the starter digger removes up to 10) gets from
the top door to the exit only through the scene itself. This module says what that "through"
is made of, so that the cells which separate the intended route from every other one (the brick
bulkheads, the brick lining of the outer wall) are checked and not just drawn.

* A **gate** is an obstacle in series with the others (the acid trough, the lava river). It is a
  list of named boxes of the scene's ``regions``, its **solution regions**: every intended way
  past the obstacle crosses one of them. A gate with several regions offers alternatives (the
  short corridor and the long lane of E22): blocking all of them cuts the scene, any one of them
  alone is a way through.
* A solution region is a **cross-section of the passage**: the air, the liquid and the floor of
  the obstacle, wall to wall. The rock around the passage (the roof of a river, the bed under a
  trough) is not part of it: that rock is exactly what a digger would tunnel through, so it must
  be brick (or metal) where it separates the two sides. A bulkhead meets the region flush: it
  starts in the column (or row) where the region starts, because a rock cell that is diagonal
  to a cell of the passage joins it for 8-neighbours.

The model (the same for the art at load time and for the footprint of a placed scene):

* a cell is *passable* if it is not static (air, gas, liquid, powder, fire) or if the starter
  digger removes it (``reach.DEFAULT_DIG_MAX_DURABILITY``): rock and ground are passable, brick and
  metal are not; a hazard is passable too (the player can wade through acid and burn);
* everything outside the footprint is impassable, and the footprint's outer wall is made so: no
  passable cell touches the boundary except the door cells;
* two cells are joined if they are 8-neighbours (a diagonal squeeze between two bricks counts as a
  leak, as in the bypass check of ``checks.py``);
* the entry is the top door, the exit is the bottom door (a scene without one, the sealed deep,
  ends in the bottom row of its footprint, under the plug).

The checks, each with its positive control:

0. *sealed*: a region the definition lists as ``sealed`` is a horizontal passage whose top and
   bottom are walled: in the rows just above and below its box no passable cell touches a
   passable cell of the box's own top or bottom row (the corners belong to the entry and exit
   faces). Without it a cut is no proof that the obstacle has to be crossed: a digger who reaches
   the air above a river of lava, or the pool of a basin, tunnels through the roof or the bed
   from there, which joins the far side again, and never goes near the lava. (Blocking the
   whole region cuts the scene all the same, since that blocks the way into the roof too.)
1. *closed*: no passable boundary cell outside the door cells;
2. *open*: with the gates as drawn the top door and the exit are joined (a scene whose gate is a
   brick plug, the sealed deep, forces its region passable: ``force_open``); without it the other
   checks would prove nothing;
3. *every region is a way through*: with all other gates open and, in this gate, only one region
   open (the others blocked), they are joined;
4. *every gate is a cut*: with all other gates open and all regions of this gate blocked (forced
   impassable) they are not joined. A violation names a few of the cells the route digs.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Collection, Sequence

import numpy as np
from scipy.ndimage import label

from .config import Materials
from .reach import DEFAULT_DIG_MAX_DURABILITY

Box = tuple[int, int, int, int]  # x, y, w, h (top-left corner)
Gate = Sequence[tuple[str, Box]]  # the named solution regions of one gate
EIGHT = np.ones((3, 3), dtype=bool)
SHOWN_CELLS = 4  # dug cells named in a message


def digger_mask(
    grid: np.ndarray, mats: Materials, max_durability: float = DEFAULT_DIG_MAX_DURABILITY
) -> np.ndarray:
    """Cells a player can be in or dig out: not static, or static with durability <= the digger's."""
    static = mats.kind_mask(grid, "static")
    return ~static | (np.array(mats.durability, dtype=np.float32)[grid] <= max_durability)


def _fill(mask: np.ndarray, boxes: Sequence[Box], value: bool) -> None:
    for x, y, w, h in boxes:
        mask[y : y + h, x : x + w] = value


def _joined(
    ok: np.ndarray, entry: Sequence[tuple[int, int]], goal: Sequence[tuple[int, int]]
) -> bool:
    lab, _ = label(ok, structure=EIGHT)
    reached = {int(lab[y, x]) for x, y in entry if ok[y, x]} - {0}
    return any(int(lab[y, x]) in reached for x, y in goal if ok[y, x])


def _route(
    ok: np.ndarray, entry: Sequence[tuple[int, int]], goal: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    """A shortest 8-connected route of passable cells from the entry to the goal ([] if none)."""
    h, w = ok.shape
    targets = {c for c in goal if ok[c[1], c[0]]}
    prev: dict[tuple[int, int], tuple[int, int] | None] = {}
    queue: deque[tuple[int, int]] = deque()
    for c in entry:
        if ok[c[1], c[0]]:
            prev[c] = None
            queue.append(c)
    while queue:
        cur = queue.popleft()
        if cur in targets:
            path = []
            node: tuple[int, int] | None = cur
            while node is not None:
                path.append(node)
                node = prev[node]
            return path[::-1]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nxt = (cur[0] + dx, cur[1] + dy)
                if 0 <= nxt[0] < w and 0 <= nxt[1] < h and nxt not in prev and ok[nxt[1], nxt[0]]:
                    prev[nxt] = cur
                    queue.append(nxt)
    return []


def entry_and_exit(
    doors: dict[str, list[tuple[int, int]]], height: int, width: int
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """The cells a route starts and ends in: the top door and the bottom door (else the bottom row)."""
    entry = list(doors.get("top", ()))
    goal = list(doors["bottom"]) if "bottom" in doors else [(x, height - 1) for x in range(width)]
    return entry, goal


def boundary_holes(
    ok: np.ndarray, doors: dict[str, list[tuple[int, int]]]
) -> list[tuple[int, int]]:
    """Passable cells on the outer edge of the footprint that are not door cells."""
    edge = np.zeros_like(ok)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    door = np.zeros_like(ok)
    for cells in doors.values():
        for x, y in cells:
            door[y, x] = True
    ys, xs = np.nonzero(edge & ok & ~door)
    return [(int(x), int(y)) for x, y in zip(xs, ys, strict=True)]


def _name(gate: Gate) -> str:
    return "+".join(n for n, _ in gate)


def _dug(grid: np.ndarray, mats: Materials, path: Sequence[tuple[int, int]]) -> str:
    """The first few static cells a route digs, as ``rock (12, 30)`` entries."""
    static = mats.kind_mask(grid, "static")
    cells = [(x, y) for x, y in path if static[y, x]]
    shown = ", ".join(f"{mats.keys[grid[y, x]]} ({x}, {y})" for x, y in cells[:SHOWN_CELLS])
    return f"digs {len(cells)} cells ({shown}{' ...' if len(cells) > SHOWN_CELLS else ''})"


def _unsealed(base: np.ndarray, box: Box) -> dict[str, list[tuple[int, int]]]:
    """Passable cells in the row above and the row below ``box`` that touch its passable cells.

    Only the columns of the box count: the cells beside it are the entry and the exit.
    """
    x, y, bw, bh = box
    h = base.shape[0]
    found: dict[str, list[tuple[int, int]]] = {}
    for side, row, edge_row in (("above", y - 1, y), ("below", y + bh, y + bh - 1)):
        if not 0 <= row < h:
            continue  # outside the footprint: nothing to tunnel in
        edge = base[edge_row, x : x + bw]
        near = edge.copy()
        near[1:] |= edge[:-1]
        near[:-1] |= edge[1:]
        cols = np.nonzero(base[row, x : x + bw] & near)[0]
        if len(cols):
            found[side] = [(x + int(c), row) for c in cols]
    return found


def _sealed_problems(
    grid: np.ndarray,
    base: np.ndarray,
    mats: Materials,
    gates: Sequence[Gate],
    sealed: Collection[str],
) -> list[str]:
    out: list[str] = []
    for gate in gates:
        for name, box in gate:
            if name not in sealed:
                continue
            for side, cells in _unsealed(base, box).items():
                shown = ", ".join(
                    f"{mats.keys[grid[y, x]]} ({x}, {y})" for x, y in cells[:SHOWN_CELLS]
                )
                out.append(
                    f"region {name} is not sealed {side}: {len(cells)} diggable cells in row "
                    f"{cells[0][1]} ({shown}{' ...' if len(cells) > SHOWN_CELLS else ''}) touch the "
                    "passage; a digger tunnels there round the obstacle"
                )
    return out


def route_problems(
    grid: np.ndarray,
    doors: dict[str, list[tuple[int, int]]],
    gates: Sequence[Gate],
    mats: Materials,
    force_open: bool = False,
    sealed: Collection[str] = (),
) -> list[str]:
    """Everything wrong with the routes through a scene; the empty list when it is a true gate.

    ``grid`` holds the cells of the footprint, ``doors`` the door cells by side (``top``,
    ``bottom``), ``gates`` the solution regions in footprint coordinates (module docstring).
    With ``force_open`` an open region is passable whatever it is made of (a brick plug); else
    open means as drawn. ``sealed`` names the regions whose top and bottom must be walled.
    """
    h, w = grid.shape
    base = digger_mask(grid, mats)
    entry, goal = entry_and_exit(doors, h, w)
    problems: list[str] = []
    if not entry or not goal:
        return ["the scene has no top door or no exit to route between"]
    problems += _sealed_problems(grid, base, mats, gates, sealed)
    holes = boundary_holes(base, doors)
    if holes:
        shown = ", ".join(f"{mats.keys[grid[y, x]]} ({x}, {y})" for x, y in holes[:SHOWN_CELLS])
        problems.append(
            f"the outer wall is not closed: {len(holes)} diggable cells on the edge of the "
            f"footprint besides the doors ({shown}); a digger leaves the scene there"
        )

    def view(open_gates: Sequence[Gate], blocked: Sequence[Box] = ()) -> np.ndarray:
        ok = base.copy()
        if force_open:
            for gate in open_gates:
                _fill(ok, [b for _, b in gate], True)
        _fill(ok, blocked, False)
        return ok

    if not _joined(view(gates), entry, goal):
        problems.append(
            "with every solution region open the top door and the exit are not joined "
            "(control of the route check): something walls the passage"
        )
        return problems
    for i, gate in enumerate(gates):
        others = [g for j, g in enumerate(gates) if j != i]
        if len(gate) > 1:
            for k, (name, _) in enumerate(gate):
                rest = [b for j, (_, b) in enumerate(gate) if j != k]
                if not _joined(view([*others, [gate[k]]], rest), entry, goal):
                    problems.append(f"region {name} of gate {_name(gate)} is no way through")
        shut = view(others, [b for _, b in gate])
        if _joined(shut, entry, goal):
            path = _route(shut, entry, goal)
            problems.append(
                f"gate {_name(gate)} can be bypassed: a route from the top door to the exit "
                f"{_dug(grid, mats, path)} without crossing it"
            )
    return problems
