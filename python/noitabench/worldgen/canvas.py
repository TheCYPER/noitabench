"""World canvas: the material grid plus carving, linking and component helpers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_erosion, label

from .config import Materials

PLAYER_H, PLAYER_W = 7, 4  # collision box of the player (entities-damage.md): 4 x 6.6 px
MAX_LINK = 140  # longest tunnel a link may carve (px)
CENTRE_CLEARANCE = 2.0  # a door tunnel's centre line must clear scene walls by this much (px)
Rect = tuple[int, int, int, int]  # x0, y0, x1, y1 (end exclusive)


def capsule_rect(a: tuple[float, float], c: tuple[float, float], radius: float) -> Rect:
    """The box around the round-ended bar from ``a`` to ``c`` (square ends, a little too big).

    Not clipped to the world. The hazard clearance records the corridors a scene opens into by
    such boxes (``clearance.py``).
    """
    return (
        int(np.floor(min(a[0], c[0]) - radius)),
        int(np.floor(min(a[1], c[1]) - radius)),
        int(np.ceil(max(a[0], c[0]) + radius)) + 1,
        int(np.ceil(max(a[1], c[1]) + radius)) + 1,
    )


class GenerationFailure(Exception):
    """A structural step failed for this sub-seed; the caller re-rolls."""


@dataclass
class Component:
    """A connected set of cells (a boolean mask over ``rect``)."""

    mask: np.ndarray
    x0: int
    y0: int

    @property
    def size(self) -> int:
        return int(self.mask.sum())

    def without(self, rect: Rect) -> Component:
        """The same component minus the cells inside ``rect`` (a scene stamped over it)."""
        x0, y0, x1, y1 = rect
        mask = self.mask.copy()
        h, w = mask.shape
        mask[
            max(0, y0 - self.y0) : max(0, min(h, y1 - self.y0)),
            max(0, x0 - self.x0) : max(0, min(w, x1 - self.x0)),
        ] = False
        return Component(mask, self.x0, self.y0)

    def nearest(self, x: float, y: float) -> tuple[int, int]:
        ys, xs = np.nonzero(self.mask)
        d2 = (xs + self.x0 - x) ** 2 + (ys + self.y0 - y) ** 2
        i = int(np.argmin(d2))
        return int(xs[i]) + self.x0, int(ys[i]) + self.y0


class Canvas:
    def __init__(self, width: int, height: int, mats: Materials):
        self.w, self.h, self.mats = width, height, mats
        self.grid = np.full((height, width), mats["rock"], dtype=np.uint8)
        self.protected = np.zeros((height, width), dtype=bool)
        self.sealed = np.zeros((height, width), dtype=bool)  # scene footprints: nothing flows in
        # cells where no contact hazard (lava, acid) may be put: the reach of the player's hit box
        # round the corridors of the must-pass scenes and of the seal key's blast (clearance.py)
        self.keepout = np.zeros((height, width), dtype=bool)
        self.terminals: list[tuple[int, int]] = []  # cave cells that links and gates end in

    # basic drawing ----------------------------------------------------
    def clip(self, rect: Rect) -> Rect:
        x0, y0, x1, y1 = rect
        return max(0, x0), max(0, y0), min(self.w, x1), min(self.h, y1)

    def fill_rect(self, rect: Rect, material: int | str, force: bool = False) -> None:
        mat = self.mats[material] if isinstance(material, str) else material
        x0, y0, x1, y1 = self.clip(rect)
        if x0 >= x1 or y0 >= y1:
            return
        sub = self.grid[y0:y1, x0:x1]
        if force:
            sub[:] = mat
        else:
            sub[~self.protected[y0:y1, x0:x1]] = mat

    def carve_rect(self, rect: Rect, force: bool = False) -> None:
        self.fill_rect(rect, self.mats.air, force)

    def protect(self, rect: Rect) -> None:
        x0, y0, x1, y1 = self.clip(rect)
        self.protected[y0:y1, x0:x1] = True

    def _capsule_cells(
        self, a: tuple[float, float], c: tuple[float, float], radius: float
    ) -> tuple[int, int, np.ndarray] | None:
        """``(x0, y0, mask)`` of the round-ended bar from ``a`` to ``c``; ``None`` outside the grid."""
        x0 = int(max(0, np.floor(min(a[0], c[0]) - radius - 1)))
        x1 = int(min(self.w, np.ceil(max(a[0], c[0]) + radius + 2)))
        y0 = int(max(0, np.floor(min(a[1], c[1]) - radius - 1)))
        y1 = int(min(self.h, np.ceil(max(a[1], c[1]) + radius + 2)))
        if x0 >= x1 or y0 >= y1:
            return None
        px = np.arange(x0, x1)[None, :] + 0.5
        py = np.arange(y0, y1)[:, None] + 0.5
        dx, dy = c[0] - a[0], c[1] - a[1]
        len2 = dx * dx + dy * dy
        t = (
            np.zeros((y1 - y0, x1 - x0))
            if len2 == 0
            else np.clip(((px - a[0]) * dx + (py - a[1]) * dy) / len2, 0, 1)
        )
        inside = (px - (a[0] + t * dx)) ** 2 + (py - (a[1] + t * dy)) ** 2 <= radius * radius
        return x0, y0, inside

    def capsule(
        self,
        a: tuple[float, float],
        c: tuple[float, float],
        radius: float,
        material: int | None = None,
        force: bool = False,
        protect: bool = False,
    ) -> None:
        """Round-ended bar from ``a`` to ``c`` of ``radius`` (default: carve air).

        With ``protect`` the cells of the bar also become protected (later scenes and dressing
        keep out of a tunnel that must stay open).
        """
        mat = self.mats.air if material is None else material
        cells = self._capsule_cells(a, c, radius)
        if cells is None:
            return
        x0, y0, inside = cells
        y1, x1 = y0 + inside.shape[0], x0 + inside.shape[1]
        if not force:
            inside &= ~self.protected[y0:y1, x0:x1]
        self.grid[y0:y1, x0:x1][inside] = mat
        if protect:
            self.protected[y0:y1, x0:x1][inside] = True

    def bar_blocked(
        self, bars: list[tuple[tuple[float, float], tuple[float, float]]], radius: float
    ) -> bool:
        """True if a bar would run into a protected cell that is not open (a scene's wall)."""
        for a, c in bars:
            cells = self._capsule_cells(a, c, radius)
            if cells is None:
                continue
            x0, y0, inside = cells
            y1, x1 = y0 + inside.shape[0], x0 + inside.shape[1]
            solid = self.protected[y0:y1, x0:x1] & (self.grid[y0:y1, x0:x1] != self.mats.air)
            if (inside & solid).any():
                return True
        return False

    # components -------------------------------------------------------
    def air(self, rect: Rect) -> np.ndarray:
        x0, y0, x1, y1 = self.clip(rect)
        return self.grid[y0:y1, x0:x1] == self.mats.air

    def largest_fit_component(self, rect: Rect, min_size: int) -> Component:
        """Largest connected set of cells where the player's box fits, inside ``rect``."""
        x0, y0, _, _ = self.clip(rect)
        fit = binary_erosion(self.air(rect), structure=np.ones((PLAYER_H, PLAYER_W), bool))
        lab, n = label(fit)
        if n == 0:
            raise GenerationFailure(f"no open space in {rect}")
        sizes = np.bincount(lab.ravel())[1:]
        k = int(np.argmax(sizes)) + 1
        if sizes[k - 1] < min_size:
            raise GenerationFailure(
                f"largest open component in {rect} has only {sizes[k - 1]} cells"
            )
        return Component(lab == k, x0, y0)

    def snapshot(self, rect: Rect) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Copies of the cells and the masks of ``rect`` (to undo a trial stamp)."""
        x0, y0, x1, y1 = rect
        return (
            self.grid[y0:y1, x0:x1].copy(),
            self.protected[y0:y1, x0:x1].copy(),
            self.sealed[y0:y1, x0:x1].copy(),
        )

    def restore(self, rect: Rect, snap: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
        x0, y0, x1, y1 = rect
        self.grid[y0:y1, x0:x1] = snap[0]
        self.protected[y0:y1, x0:x1] = snap[1]
        self.sealed[y0:y1, x0:x1] = snap[2]

    def keeps_terminals(self, old: Component, new: Component) -> bool:
        """True if every link end that lay in ``old`` still lies in ``new`` (nothing was cut off)."""
        h, w = old.mask.shape
        for x, y in self.terminals:
            inside = 0 <= x - old.x0 < w and 0 <= y - old.y0 < h
            if inside and old.mask[y - old.y0, x - old.x0] and not new.mask[y - old.y0, x - old.x0]:
                return False
        return True

    def refit(self, comp: Component) -> Component:
        """The largest piece of ``comp`` that still fits the player's box on the current grid.

        A scene stamped over a cave cuts it: the cells of the old component that no longer fit
        are dropped and what is left may fall into pieces; a door linked to a piece the cave
        has been cut off from would lead nowhere, so only the largest piece is kept.
        """
        h, w = comp.mask.shape
        rect = (comp.x0, comp.y0, comp.x0 + w, comp.y0 + h)
        fit = binary_erosion(self.air(rect), structure=np.ones((PLAYER_H, PLAYER_W), bool))
        lab, n = label(comp.mask & fit)
        if n == 0:
            return Component(np.zeros_like(comp.mask), comp.x0, comp.y0)
        k = int(np.argmax(np.bincount(lab.ravel())[1:])) + 1
        return Component(lab == k, comp.x0, comp.y0)

    def link(
        self,
        p: tuple[float, float],
        comp: Component,
        width: float,
        vertical_first: bool,
        protect: bool = False,
        record: list[Rect] | None = None,
    ) -> tuple[int, int]:
        """Carve an L-shaped tunnel from ``p`` to the nearest cell of ``comp`` (``protect``: keep it).

        With ``record`` the boxes of the two bars are appended to it (``capsule_rect``).
        """
        q = comp.nearest(p[0], p[1])
        if abs(q[0] - p[0]) + abs(q[1] - p[1]) > MAX_LINK:
            raise GenerationFailure(f"link from {p} to the component is longer than {MAX_LINK} px")
        corner = (p[0], q[1]) if vertical_first else (q[0], p[1])
        self.capsule(p, corner, width / 2, protect=protect)
        self.capsule(corner, q, width / 2, protect=protect)
        if record is not None:
            record += [capsule_rect(p, corner, width / 2), capsule_rect(corner, q, width / 2)]
        self.terminals.append(q)
        return q

    def plan_door_link(
        self,
        door: tuple[int, int],
        outward: tuple[int, int],
        comp: Component,
        width: float,
        max_dist: int = MAX_LINK,
        stub: int = 10,
    ) -> tuple[list[tuple[tuple[float, float], tuple[float, float]]], tuple[int, int]] | None:
        """The bars of a tunnel from a scene's door to ``comp``: straight out of the door, then an L.

        The L is tried both ways round; ``None`` if the cave is too far or every way runs into a
        scene wall (the caller takes the scene back). Nothing is carved here.
        """
        out = (door[0] + outward[0] * stub, door[1] + outward[1] * stub)
        q = comp.nearest(*out)
        if abs(q[0] - door[0]) + abs(q[1] - door[1]) > max_dist:
            return None
        for corner in ((out[0], q[1]), (q[0], out[1])):
            bars = [(door, out), (out, corner), (corner, q)]
            if not self.bar_blocked(bars, CENTRE_CLEARANCE):
                return bars, q
        return None

    def carve_link(
        self,
        plan: tuple[list[tuple[tuple[float, float], tuple[float, float]]], tuple[int, int]],
        width: float,
    ) -> None:
        """Carve (and protect) a tunnel planned by ``plan_door_link``."""
        bars, q = plan
        for a, c in bars:
            self.capsule(a, c, width / 2, protect=True)
        self.terminals.append(q)
