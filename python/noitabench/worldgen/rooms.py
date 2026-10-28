"""Built-structure layout for the brick ruins and the abandoned workshop.

The inner area of the region is cut by a binary space partition into leaves; every leaf
holds one rectangular room (the leaf shrunk by a random margin per side, so the walls
between rooms are 10-18 cells thick). Doors join the two sides of every split, plus a few
extra ones, so the layout is always connected and has loops. Coordinates are region-local
until ``Room.moved``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .canvas import Rect
from .config import RoomsStyle
from .shapes import widen

SPLIT_STOP_PROB = 0.18  # a leaf that could be split is kept whole with this probability
RAGGED_SCALE = 9.0  # size of the bites of crumbling walls
MIN_DOOR_OVERLAP = 2  # a door keeps this far from the corners of the rooms it joins


@dataclass(frozen=True)
class Room:
    """The open interior of a room, ``[x0, x1) x [y0, y1)``."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0

    @property
    def rect(self) -> Rect:
        return (self.x0, self.y0, self.x1, self.y1)

    def moved(self, dx: int, dy: int) -> Room:
        return Room(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)


@dataclass
class _Node:
    rect: Rect
    axis: str = ""  # "v" (a vertical split line) or "h"
    pos: int = 0
    kids: tuple[_Node, _Node] | None = None
    room: Room | None = None


@dataclass
class _Layout:
    cave: np.ndarray
    style: RoomsStyle
    rng: np.random.Generator
    doors: list[Rect] = field(default_factory=list)

    def carve(self, rect: Rect) -> None:
        x0, y0, x1, y1 = rect
        self.cave[y0:y1, x0:x1] = True
        self.doors.append(rect)


def layout_rooms(
    size: tuple[int, int], ring: int, style: RoomsStyle, rng: np.random.Generator
) -> tuple[np.ndarray, list[Room], list[Rect]]:
    """Rooms and doors of a ``size`` = (width, height) region: ``(cave, rooms, doors)``."""
    w, h = size
    cave = np.zeros((h, w), dtype=bool)
    root = _split((ring, ring, w - ring, h - ring), style, rng)
    _make_rooms(root, style, rng)
    lay = _Layout(cave, style, rng)
    rooms = _leaf_rooms(root)
    for room in rooms:
        cave[room.y0 : room.y1, room.x0 : room.x1] = True
    _doors(root, lay)
    if style.ragged:  # crumbling walls: bites out of the rooms' edges
        cave = widen(cave, style.ragged, RAGGED_SCALE, rng)
    return cave, rooms, lay.doors


# --------------------------------------------------------------------- partition


def _split(rect: Rect, style: RoomsStyle, rng: np.random.Generator) -> _Node:
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    can_v, can_h = w >= 2 * style.min_w, h >= 2 * style.min_h
    node = _Node(rect)
    if not (can_v or can_h) or rng.random() < SPLIT_STOP_PROB and max(w, h) < 3 * style.min_h:
        return node
    # prefer to cut along the side that is large compared to its minimum
    vertical = can_v and (
        not can_h or rng.random() < (w / style.min_w) / (w / style.min_w + h / style.min_h)
    )
    if vertical:
        pos = int(rng.integers(x0 + style.min_w, x1 - style.min_w + 1))
        node.axis, node.pos = "v", pos
        node.kids = (
            _split((x0, y0, pos, y1), style, rng),
            _split((pos, y0, x1, y1), style, rng),
        )
    else:
        pos = int(rng.integers(y0 + style.min_h, y1 - style.min_h + 1))
        node.axis, node.pos = "h", pos
        node.kids = (
            _split((x0, y0, x1, pos), style, rng),
            _split((x0, pos, x1, y1), style, rng),
        )
    return node


def _make_rooms(node: _Node, style: RoomsStyle, rng: np.random.Generator) -> None:
    if node.kids is not None:
        for kid in node.kids:
            _make_rooms(kid, style, rng)
        return
    x0, y0, x1, y1 = node.rect
    lo, hi = style.margin
    m = [int(rng.integers(lo, hi + 1)) for _ in range(4)]
    node.room = Room(x0 + m[0], y0 + m[1], x1 - m[2], y1 - m[3])


def _leaf_nodes(node: _Node) -> list[_Node]:
    if node.kids is None:
        return [node]
    return _leaf_nodes(node.kids[0]) + _leaf_nodes(node.kids[1])


def _leaf_rooms(node: _Node) -> list[Room]:
    return [n.room for n in _leaf_nodes(node) if n.room is not None]


# ------------------------------------------------------------------------- doors


def _doors(node: _Node, lay: _Layout) -> None:
    if node.kids is None:
        return
    a, b = node.kids
    first, second = (_leaf_nodes(a), _leaf_nodes(b))
    if node.axis == "v":
        side_a = [n for n in first if n.rect[2] == node.pos]
        side_b = [n for n in second if n.rect[0] == node.pos]
        pairs = [(p.room, q.room) for p in side_a for q in side_b]
        doors = [d for d in (_side_door(p, q, lay) for p, q in pairs) if d is not None]
    else:
        side_a = [n for n in first if n.rect[3] == node.pos]
        side_b = [n for n in second if n.rect[1] == node.pos]
        pairs = [(p.room, q.room) for p in side_a for q in side_b]
        doors = [d for d in (_floor_door(p, q, lay) for p, q in pairs) if d is not None]
    _carve_doors(doors, pairs, lay)
    _doors(a, lay)
    _doors(b, lay)


def _carve_doors(doors: list[Rect], pairs: list[tuple[Room, Room]], lay: _Layout) -> None:
    """One door per split (always), more with probability ``loops``; a corridor if none fits."""
    rng = lay.rng
    if not doors:  # no pair overlaps enough: link two rooms with an L-shaped corridor
        p, q = pairs[int(rng.integers(0, len(pairs)))]
        _corridor(p, q, lay)
        return
    order = [int(i) for i in rng.permutation(len(doors))]
    lay.carve(doors[order[0]])
    for i in order[1:]:
        if rng.random() < lay.style.loops:
            lay.carve(doors[i])


def _side_door(left: Room, right: Room, lay: _Layout) -> Rect | None:
    """A door through the vertical wall between two rooms, its sill on the higher floor."""
    st = lay.style
    floor = min(left.y1, right.y1)
    top = floor - st.door_h
    if top < max(left.y0, right.y0) + MIN_DOOR_OVERLAP:
        return None
    return (left.x1 - 1, top, right.x0 + 1, floor)


def _floor_door(upper: Room, lower: Room, lay: _Layout) -> Rect | None:
    """A hole through the floor of the upper room into the lower one."""
    st = lay.style
    lo = max(upper.x0, lower.x0) + MIN_DOOR_OVERLAP
    hi = min(upper.x1, lower.x1) - MIN_DOOR_OVERLAP
    if hi - lo < st.door_w:
        return None
    x = int(lay.rng.integers(lo, hi - st.door_w + 1))
    return (x, upper.y1 - 1, x + st.door_w, lower.y0 + 1)


def _corridor(a: Room, b: Room, lay: _Layout) -> None:
    """Fallback: an L-shaped corridor, ``door_h`` wide, from the centre of ``a`` to that of ``b``."""
    t = lay.style.door_h
    ax, ay = (a.x0 + a.x1) // 2, (a.y0 + a.y1) // 2
    bx, by = (b.x0 + b.x1) // 2, (b.y0 + b.y1) // 2
    lay.carve((min(ax, bx), ay - t // 2, max(ax, bx) + 1, ay - t // 2 + t))
    lay.carve((bx - t // 2, min(ay, by), bx - t // 2 + t, max(ay, by) + 1))
