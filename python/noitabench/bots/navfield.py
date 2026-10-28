"""A cost-to-goal field over the positions of the player's box, and the way down it.

Nodes are the box positions the bot could be at (`Terrain.diggable`); an edge is one cell of
movement in one of the 8 directions. Going up costs more than going down (levitation spends the
meter, a fall is free), standing on something is cheaper than hovering, and cells whose box holds
hazards, diggable terrain or squeezes along walls carry the extra cost of `Terrain.cost`.

One Dijkstra run from the goal gives, for every node, the cost to reach the goal and the next node
on the cheapest way. The driver then only has to keep going to the next few nodes: whatever
pushes the player off its route (a bump, a fall, a fight) leaves it somewhere that still has a
way on, with no replanning.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
from scipy.ndimage import distance_transform_edt
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from .terrain import Terrain

UP_MULT = 2.2  # climbing is levitation: slower to afford than walking
DOWN_MULT = 0.6  # falling is quick and free
AIR_MULT = 3.0  # hovering or sideways in the air spends the meter too
NO_NODE = -1

DIRS = tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx, dy) != (0, 0))


def _shift(a: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """`out[y, x] = a[y + dy, x + dx]`, False outside."""
    out = np.zeros_like(a)
    h, w = a.shape
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[ys, xs] = a[yd, xd]
    return out


@dataclass(frozen=True)
class NavField:
    """Cost to the goal of every node, and the next node toward it."""

    width: int
    height: int
    node_of: np.ndarray  # (height, width) int32: node id of a position, or NO_NODE
    xs: np.ndarray  # (n,) x of every node
    ys: np.ndarray
    dist: np.ndarray  # (n,) cost to the goal (inf if unreachable)
    succ: np.ndarray  # (n,) next node toward the goal (NO_NODE at the goal / unreachable)

    def node(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return int(self.node_of[y, x])
        return NO_NODE

    def cost_at(self, x: int, y: int) -> float:
        n = self.node(x, y)
        return float("inf") if n == NO_NODE else float(self.dist[n])

    def reachable(self, x: int, y: int) -> bool:
        return math.isfinite(self.cost_at(x, y))

    def nearest_node(self, x: int, y: int, radius: int = 12) -> int:
        """The reachable node nearest to a position (the node itself if it is one)."""
        n = self.node(x, y)
        if n != NO_NODE and math.isfinite(self.dist[n]):
            return n
        x0, x1 = max(0, x - radius), min(self.width, x + radius + 1)
        y0, y1 = max(0, y - radius), min(self.height, y + radius + 1)
        win = self.node_of[y0:y1, x0:x1]
        ids = win[win != NO_NODE]
        ids = ids[np.isfinite(self.dist[ids])]
        if len(ids) == 0:
            return NO_NODE
        d2 = (self.xs[ids] - x) ** 2 + (self.ys[ids] - y) ** 2
        return int(ids[int(np.argmin(d2))])

    def path_from(self, node: int, limit: int = 100_000) -> list[tuple[int, int]]:
        """Positions from `node` along the cheapest way to the goal."""
        out: list[tuple[int, int]] = []
        while node != NO_NODE and len(out) < limit:
            out.append((int(self.xs[node]), int(self.ys[node])))
            node = int(self.succ[node])
        return out

    def exposure(self, node: int, contact: np.ndarray) -> int:
        """Nodes of the way from `node` where the hit box touches a hazard (`Terrain.contact`)."""
        return sum(int(contact[y, x]) for x, y in self.path_from(node))

    def ahead(self, node: int, hops: int) -> tuple[int, int]:
        """The position `hops` nodes down the way from `node` (the goal if it is nearer)."""
        last = node
        for _ in range(hops):
            nxt = int(self.succ[last])
            if nxt == NO_NODE:
                break
            last = nxt
        return int(self.xs[last]), int(self.ys[last])


GUIDE_REACH = 16.0  # cells from the guide line within which walking is cheaper
GUIDE_DISCOUNT = 0.6  # share of the walking cost saved on the guide line


def guide_bias(shape: tuple[int, int], waypoints: list[tuple[int, int]]) -> np.ndarray:
    """A multiplier (1 far away, `1 - GUIDE_DISCOUNT` on the line) for the walking cost of
    nodes near a polyline of waypoints: the way the world generator marked as the main path."""
    height, width = shape
    line = np.zeros(shape, dtype=bool)
    pts = [(min(max(int(x), 0), width - 1), min(max(int(y), 0), height - 1)) for x, y in waypoints]
    for (x0, y0), (x1, y1) in pairwise(pts):
        n = max(abs(x1 - x0), abs(y1 - y0)) + 1
        line[
            np.rint(np.linspace(y0, y1, n)).astype(int), np.rint(np.linspace(x0, x1, n)).astype(int)
        ] = True
    if not line.any():
        return np.ones(shape, dtype=np.float32)
    near = distance_transform_edt(~line) <= GUIDE_REACH
    return np.where(near, 1.0 - GUIDE_DISCOUNT, 1.0).astype(np.float32)


def build_field(
    terrain: Terrain, goal: tuple[int, int], guide: np.ndarray | None = None
) -> NavField:
    """Run Dijkstra from `goal` (a box position) over the nodes of `terrain`.

    `guide` (see `guide_bias`) makes the nodes near a marked way cheaper to walk."""
    height, width = terrain.height, terrain.width
    ok = terrain.diggable
    node_of = np.full((height, width), NO_NODE, dtype=np.int32)
    ys, xs = np.nonzero(ok)
    node_of[ys, xs] = np.arange(len(ys), dtype=np.int32)
    gx, gy = goal
    if not (0 <= gx < width and 0 <= gy < height) or node_of[gy, gx] == NO_NODE:
        raise ValueError(f"the goal {goal} is not a position the player's box can take")

    cost = terrain.cost
    src_parts, dst_parts, w_parts = [], [], []
    for dx, dy in DIRS:
        valid = ok & _shift(ok, dx, dy)
        if dx and dy:  # no cutting of corners: both ways round must be open without digging
            valid &= _shift(terrain.free, dx, 0) & _shift(terrain.free, 0, dy)
        vy, vx = np.nonzero(valid)
        step = math.hypot(dx, dy)
        if dy < 0:
            mult = np.full(len(vy), UP_MULT)
        elif dy > 0:
            mult = np.full(len(vy), DOWN_MULT)
        else:
            mult = np.where(terrain.grounded[vy, vx], 1.0, AIR_MULT)
        bias = 1.0 if guide is None else guide[vy + dy, vx + dx]
        w = step * mult * bias + cost[vy + dy, vx + dx] * step
        src_parts.append(node_of[vy, vx])
        dst_parts.append(node_of[vy + dy, vx + dx])
        w_parts.append(w.astype(np.float64))
    src = np.concatenate(src_parts)
    dst = np.concatenate(dst_parts)
    wts = np.concatenate(w_parts)
    n = len(ys)
    # reversed graph: the edge dst -> src costs what src -> dst costs
    graph = csr_matrix((wts, (dst, src)), shape=(n, n))
    dist, pred = dijkstra(
        graph, directed=True, indices=int(node_of[gy, gx]), return_predecessors=True
    )
    succ = np.where(pred < 0, NO_NODE, pred).astype(np.int32)
    return NavField(
        width=width,
        height=height,
        node_of=node_of,
        xs=xs.astype(np.int32),
        ys=ys.astype(np.int32),
        dist=dist,
        succ=succ,
    )
