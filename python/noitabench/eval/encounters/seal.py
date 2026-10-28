"""E06 The sealed deep (N3, N5, must pass; the combined scene C3).

Capability graph section 3.2: "最深的区域被神殿砖封住，破封需要前面才能找到的东西 ... 看是否提前
收集、回头路多长". The key is the two spells marked `role: breaker` in the world (BOMB at E02 and
EXPLOSIVE_PROJECTILE at E12), built into one wand with the modifier first and thrown on the plug.

    parts_before (0.40)  the share of the key's spells picked up before the player first touched
                         the front hall;
    no_backtrack (0.20)  1.0 if none was missing; if some were fetched after arriving, how far the
                         player climbed back up for them: 0 cells is 1.0, 300 or more is 0; 0 if
                         some were never fetched;
    opened (0.40)        reached the sealed room under the plug (1.0), or blasted the plug with
                         the key's radius (>= 70) without getting in (0.5).
"""

from __future__ import annotations

from ..context import Ctx
from ..geometry import Rect
from ..rubric import Outcome, Rubric, linear
from . import rule

DEFAULT_PARTS = ("BOMB", "EXPLOSIVE_PROJECTILE")
KEY_RADIUS = 70  # [EXPLOSIVE_PROJECTILE, BOMB] blasts with radius 75, the bomb alone with 60
PLUG_REACH = 90  # cells from the plug's centre within which a blast counts as aimed at it


def pickup_frames(ctx: Ctx, spells: tuple[str, ...]) -> dict[str, int]:
    """The frame at which each of `spells` was first picked up in the whole run."""
    found: dict[str, int] = {}
    for e in ctx.run.events.of_type("pickup"):
        if e.get("item") == "spell" and e.get("detail") in spells:
            found.setdefault(str(e["detail"]), int(e["frame"]))
    return found


def plug_of(ctx: Ctx) -> Rect:
    """The brick plug: the world's `seal` box, else the scene's own `plug` region."""
    return ctx.run.world.seal_plug or ctx.region("plug")


def got_in(ctx: Ctx) -> bool:
    """True if the player got below the plug (into the sealed room) after arriving."""
    room = ctx.run.world.seal_room
    if room is not None and ctx.reached(room, ctx.enter, ctx.run.last_frame):
        return True
    plug = plug_of(ctx)
    return any(
        s.y >= plug.bottom - 8 and plug.x - 20 <= s.x <= plug.right + 20
        for s in ctx.run.track.between(ctx.enter, ctx.run.last_frame)
    )


def key_blast(ctx: Ctx) -> bool:
    """True if a blast of the key's radius went off near the plug during or after the visit."""
    plug = plug_of(ctx)
    return any(
        e["radius"] >= KEY_RADIUS
        and (e["x"] - plug.cx) ** 2 + (e["y"] - plug.cy) ** 2 <= PLUG_REACH**2
        for e in ctx.events("explosion", f0=ctx.enter, f1=ctx.run.last_frame)
    )


@rule("E06")
def e06(ctx: Ctx) -> Outcome:
    parts = tuple(ctx.run.world.breaker_spells()) or DEFAULT_PARTS
    picked = pickup_frames(ctx, parts)
    before = [p for p in parts if picked.get(p, ctx.enter) < ctx.enter]
    missing = [p for p in parts if p not in before]
    late = [p for p in missing if p in picked]
    r = Rubric()
    r.add(
        "parts_before",
        0.40,
        len(before) / len(parts),
        f"{len(before)} of {len(parts)} key spells in hand on arrival ({', '.join(parts)})",
    )
    climbed = 0.0
    if not missing:
        r.add("no_backtrack", 0.20, 1.0, "nothing to fetch")
    elif len(late) == len(missing):
        t_last = max(picked[p] for p in late)
        arrival = ctx.run.track.at(ctx.enter)
        low = min(s.feet for s in ctx.run.track.between(ctx.enter, t_last))
        climbed = max(0.0, (arrival.feet if arrival else low) - low)
        r.add("no_backtrack", 0.20, linear(climbed, 0, 300), f"climbed back {climbed:.0f} cells")
    else:
        r.add("no_backtrack", 0.20, 0.0, f"never fetched {sorted(set(missing) - set(late))}")
    inside = got_in(ctx)
    blasted = key_blast(ctx)
    r.add(
        "opened",
        0.40,
        1.0 if inside else 0.5 if blasted else 0.0,
        "reached the sealed room"
        if inside
        else "blasted the plug with the key but did not get in"
        if blasted
        else "the seal stayed shut",
    )
    return Outcome.of(
        r,
        parts_before=len(before),
        parts=len(parts),
        parts_late=len(late),
        climbed=round(climbed, 1),
        key_blast=blasted,
        opened=inside,
    )
