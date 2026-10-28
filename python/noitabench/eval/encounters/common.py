"""Helpers the encounter rules share, and the numbers they are calibrated with.

Every constant here is a calibration choice (what counts as "a lot of damage"): the rules state
them in their reasons so a report reader can see why a visit scored what it did.
"""

from __future__ import annotations

from collections.abc import Callable

from ..context import Ctx
from ..geometry import Rect, Sample
from ..worldinfo import marker_things

HURT_SMALL = 25.0  # HP (displayed) that is a scratch, not a lesson
HURT_LARGE = 60.0  # HP that is most of a life (100)
SMALL_POUR = 60  # cells: a splash to see what a liquid does, a bottle holds 400
CRUST_CELLS = 3  # lava cells turned to rock that count as a crust being made
RIVER_SIDE = 3  # cells beyond the river's ends that count as "the other side"


def center_x(sample: Sample) -> float:
    return sample.x + sample.w / 2


def crossed(ctx: Ctx, region: Rect, *, near: int = 40) -> bool:
    """True if the player was left of `region` and later right of it (or the reverse), near its
    height: it got across, whether by walking on a crust, wading or flying."""
    seen: list[int] = []  # -1 left of the region, +1 right of it, in order
    for s in ctx.run.track.between(ctx.enter, ctx.run.last_frame):
        if abs(s.y + s.h / 2 - region.y) > near + s.h:
            continue
        cx = center_x(s)
        side = -1 if cx < region.x - RIVER_SIDE else 1 if cx >= region.right + RIVER_SIDE else 0
        if side and (not seen or seen[-1] != side):
            seen.append(side)
    return len(seen) >= 2


def first_over(ctx: Ctx, region: Rect, *, near: int = 40) -> int | None:
    """The first frame of the visit at which the player was above, in or under `region` (its
    centre within the region's width, at about its height): flying over a hazard counts as
    getting to it although the hit box never touches it."""
    for s in ctx.run.track.between(ctx.enter, ctx.run.last_frame):
        if abs(s.y + s.h / 2 - region.y) <= near + s.h and (
            region.x - RIVER_SIDE <= center_x(s) < region.right + RIVER_SIDE
        ):
            return s.frame
    return None


def first_frame_with(ctx: Ctx, predicate: Callable[[Sample], bool]) -> int | None:
    """The first frame of the visit at which `predicate(sample)` holds for the player."""
    for s in ctx.run.track.between(ctx.enter, ctx.end):
        if predicate(s):
            return s.frame
    return None


def role_things(ctx: Ctx, role: str) -> set[str]:
    """What the scene's item markers of `role` hold, by its definition, with the slot liquids
    (`$A`) of the placed scene filled in: E21's remedy is the healing potion wherever it stands
    on the bench, E24's the bottle of water."""
    out = set()
    for thing in marker_things(ctx.scene.eid, role):
        value = ctx.scene.params.get(thing[1:], "") if thing.startswith("$") else thing
        if value:
            out.add(value)
    return out
