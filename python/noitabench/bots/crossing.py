"""Crossing a river of lava the way a player would: tip a liquid onto it that turns it to stone.

The river of E02 lies in the floor of a low passage (a flying player's hit box touches the lava
all the way) and the world gives two bottles of a liquid that solidifies lava next to a third
that does not. `clear_lava` uses the bottles it is told are the solvent: it walks to a spot a
few cells before the lava, pours at the lava's edge, waits, and looks at the grid. It goes on
(further along the way, with the next bottle) until no step of the way to the goal touches
lava. What the liquid does to the lava is only read from the grid, never from the rules.

Controls only: `pour`, `aim`, `select_bottle` and the walking the pilot does.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Protocol

import numpy as np

from noitabench.game import Controls, Game, aim_at

from .bottles import bottle_total, holding
from .navfield import NO_NODE, NavField
from .terrain import Body, Materials, Terrain

POUR_FRAMES = 12  # frames of one pour: about 100 cells of liquid
SETTLE_FRAMES = 45  # frames for the liquid to flow and react, and the steam to clear
MAX_ROUNDS = 10
STAND_DISTANCE = 9.0  # cells from the hand to the lava's edge where the bot pours from
MIN_STAND_DISTANCE = 4.0  # ... at least this far, where there is no room for that
MAX_STAND_DISTANCE = 14.0  # a pour from further away than this does not reach the lava
STALLED_ROUNDS = 3  # rounds in which the lava does not shrink before the bot gives up
WINDOW = 14  # cells around the lava of the way that are counted and searched


class CrossingDriver(Protocol):
    """What the crossing needs from the bot."""

    game: Game
    mats: Materials
    body: Body

    def step(self, controls: Controls) -> dict[str, Any]: ...

    def note(self, event: str, **fields: Any) -> None: ...

    def plan(self, goal: tuple[int, int], *, dig: bool = True) -> tuple[Terrain, NavField]: ...

    def wait_out_fire(self, why: str, waited: int = 0) -> int: ...

    def walk_to(
        self, label: str, goal: tuple[int, int], *, tolerance: int = 2, max_frames: int = ...
    ) -> bool: ...


def solvent_bottle(player: dict[str, Any], solvents: Collection[str]) -> int | None:
    """Index of a held bottle that still holds one of the `solvents` (material keys)."""
    return holding(player, frozenset(solvents))


def exposed_steps(terrain: Terrain, path: list[tuple[int, int]]) -> list[int]:
    """Indices of the steps of a way where the hit box touches lava, acid or fire."""
    return [i for i, (x, y) in enumerate(path) if terrain.contact[y, x]]


def window_of(
    path: list[tuple[int, int]], idx: list[int], shape: tuple[int, int]
) -> tuple[slice, slice]:
    """The rectangle of the grid around the exposed steps, with a margin."""
    xs = [path[i][0] for i in idx]
    ys = [path[i][1] for i in idx]
    height, width = shape
    return (
        slice(max(0, min(ys) - WINDOW), min(height, max(ys) + WINDOW)),
        slice(max(0, min(xs) - WINDOW), min(width, max(xs) + WINDOW)),
    )


def lava_target(
    grid: np.ndarray, lava: int, around: tuple[int, int], body: Body
) -> tuple[int, int] | None:
    """The lava cell nearest to the box at `around`: where the first pour is aimed."""
    cx, cy = around[0] + body.w / 2, around[1] + body.h
    y0, x0 = max(0, int(cy) - WINDOW), max(0, int(cx) - WINDOW)
    sub = grid[y0 : int(cy) + WINDOW, x0 : int(cx) + WINDOW] == lava
    ys, xs = np.nonzero(sub)
    if len(ys) == 0:
        return None
    k = int(np.argmin((xs + x0 - cx) ** 2 + 2.0 * (ys + y0 - cy) ** 2))
    return int(xs[k]) + x0, int(ys[k]) + y0


def pour_stand(
    terrain: Terrain, path: list[tuple[int, int]], first: int, target: tuple[int, int], body: Body
) -> tuple[int, int]:
    """The step of the way (before the first exposed one) to stand at for the pour.

    The best is a place on the ground, out of reach of the lava (clear of the ring a fall or a
    wobble reaches) and `STAND_DISTANCE` to `MAX_STAND_DISTANCE` cells from the target (the nearest
    one to the lava); failing that the nearest place to
    the lava where the hit box touches nothing and the hand is `MIN_STAND_DISTANCE` cells from
    it (a short ledge beside a trough); failing that the start of the way."""
    near: tuple[int, int] | None = None
    for j in range(first, -1, -1):
        x, y = path[j]
        if not terrain.grounded[y, x]:
            continue
        hand = (x + body.hand_dx + 0.5, y + body.hand_dy + 0.5)
        distance = float(np.hypot(hand[0] - target[0] - 0.5, hand[1] - target[1] - 0.5))
        if not terrain.near_hazard[y, x] and STAND_DISTANCE <= distance <= MAX_STAND_DISTANCE:
            return x, y
        if near is None and not terrain.contact[y, x] and distance >= MIN_STAND_DISTANCE:
            near = (x, y)
    return near if near is not None else path[0]


def pour(
    driver: CrossingDriver, bottle: int, target: tuple[int, int], burst: int = POUR_FRAMES
) -> int:
    """Tip the bottle at the target cell for a burst of `burst` frames; the number of frames
    it ran."""
    game = driver.game
    ran = 0
    for _ in range(burst):
        p = game.player()
        if p is None or p["dead"] or bottle_total(p["bottles"][bottle]) <= 0:
            break
        hand = (p["x"] + driver.body.hand_dx + 0.5, p["y"] + driver.body.hand_dy + 0.5)
        driver.step(
            {
                "select_bottle": bottle,
                "pour": True,
                "aim": aim_at(hand, (target[0] + 0.5, target[1] + 0.5)),
            }
        )
        ran += 1
    return ran


def locate(
    driver: CrossingDriver, goal: tuple[int, int], waited: int
) -> tuple[Terrain, NavField, dict[str, Any], int, int] | None:
    """The plan of a walk (no digging: the walk is the puzzle, not a tunnel) to `goal`, the
    player and its node in the plan, and the patience used up; None if the player is dead or
    stands where the plan has no way (fire around it, burning gas: waited out first, until the
    patience of `wait_out_fire` runs out)."""
    terrain, field = driver.plan(goal, dig=False)
    while True:
        p = driver.game.player()
        if p is None or p["dead"]:
            return None
        here = field.nearest_node(int(p["x"]), int(p["y"]))
        if here != NO_NODE:
            return terrain, field, p, here, waited
        waited = driver.wait_out_fire("crossing", waited)
        if waited < 0:
            return None
        terrain, field = driver.plan(goal, dig=False)


def clear_lava(
    driver: CrossingDriver,
    goal: tuple[int, int],
    solvents: Collection[str],
    *,
    burst: int = POUR_FRAMES,
) -> bool:
    """Pour the `solvents` onto the lava that the way to `goal` crosses until nothing on the way
    touches lava, in bursts of `burst` frames (a short burst spares a small supply). True if the
    way is clear; False if the bottles ran out, the lava does not shrink, the way is not lava,
    or the bot cannot get to where it pours from."""
    lava = driver.mats.index("lava")
    last = -1
    stalled = 0
    waited = 0
    round_ = -1
    while round_ < MAX_ROUNDS:  # (the last look only checks the way)
        round_ += 1
        found = locate(driver, goal, waited)
        if found is None:
            return False
        terrain, field, p, here, waited = found
        path = field.path_from(here)
        exposed = exposed_steps(terrain, path)
        if not exposed:
            driver.note("crossing_clear", rounds=round_)
            return True
        if round_ == MAX_ROUNDS:
            driver.note("crossing_failed", rounds=round_)
            return False
        grid = driver.game.grid_array()
        target = lava_target(grid, lava, path[exposed[0]], driver.body)
        bottle = solvent_bottle(p, solvents)
        if target is None and bottle is not None:  # what the way touches is not lava: fire
            waited = driver.wait_out_fire("crossing", waited)  # (burning gas of the last pour)
            if waited >= 0:
                round_ -= 1  # (a look, not a round)
                continue
        if target is None or bottle is None:
            driver.note("crossing_failed", lava=target is not None, bottle=bottle is not None)
            return False
        rows, cols = window_of(path, exposed, grid.shape)
        left = int(np.count_nonzero(grid[rows, cols] == lava))
        stalled = stalled + 1 if last >= 0 and left >= last else 0
        if stalled >= STALLED_ROUNDS:
            driver.note("crossing_stalled", lava_cells=left)
            return False
        last = left
        stand = pour_stand(terrain, path, exposed[0], target, driver.body)
        far_from_stand = abs(stand[0] - p["x"]) > 2 or abs(stand[1] - p["y"]) > 2
        if far_from_stand and not driver.walk_to("to_pour", stand, tolerance=2, max_frames=3000):
            return False
        driver.note("pour", round=round_, target=target, lava_cells=left, stand=stand)
        pour(driver, bottle, target, burst)
        for _ in range(SETTLE_FRAMES):
            driver.step({})
    return False
