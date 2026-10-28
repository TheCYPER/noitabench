"""Encounters about a hazard in the way: E16 acid film, E12 strata, E18 thick wall, E03 guard.

Capability graph section 3.2:

E16 Thin acid layer (N7, N9, must pass): "是否先 inspect；受伤多少".
    inspected (0.30) an `inspect` of a cell at the trough (within 12 cells) before the hit box
                     first touched it or flew over it (needs decisions.jsonl);
    unhurt (0.50)    HP lost to contact in the scene: 0 is 1.0, 60 or more is 0 (0 if the
                     player neither reached the trough nor flew over it nor got through);
    passed (0.20)    left through the doorway under the scene.
E12 Layered rock (N5, N3, must pass): "挖路避开岩浆夹层，碰到岩浆的次数".
    passed (0.40)    left through the doorway under the scene;
    lava (0.30)      HP lost to contact and fire: 0 is 1.0, 40 or more is 0;
    plugs (0.30)     no digging bolt exploded in the ground plugs beside the lava seams
                     (regions trap1, trap2): their blast reaches the lava.
    lava and plugs count only if the player went at the strata (got to the second corridor, or
    dug in the scene): not digging at all is not avoiding the traps.
E18 Treasure behind the thick wall (N8, N1): "组出能打穿的法杖；改法杖次数".
    room (0.50)      reached the brick room under the rock;
    safe (0.30)      HP lost to contact, fire and explosions: 0 is 1.0, 40 or more is 0 (0 if
                     the player never dug or blasted in the hall or got to the room);
    quick (0.20)     frames from entering to the room: 600 or fewer is 1.0, 3600 or more is 0.
    (Wand edits happen at rest areas, outside the scene; see the global N8 metric.)
E03 Fire-proof guard (N1, N6): "火球对斯滕达里无效后，多快换手段".
    success (0.40)   the mage died or the reward wand was picked up;
    switched (0.30)  fireball casts before the first other means (water, or the mage's death):
                     one is 1.0, six or more is 0;
    water (0.20)     poured or threw water;
    unhurt (0.10)    HP lost: 0 is 1.0, 60 or more is 0.
    switched, water and unhurt count only if the player engaged (cast a fireball, threw
    something or won).
"""

from __future__ import annotations

from ..context import Ctx
from ..rubric import Outcome, Rubric, linear
from . import rule
from .common import HURT_LARGE, crossed, first_over


@rule("E16")
def e16(ctx: Ctx) -> Outcome:
    trough = ctx.region("trough")
    touched = ctx.run.track.first_touch(trough.grow(2), ctx.enter, ctx.run.last_frame)
    over = first_over(ctx, trough)
    first = min((f for f in (touched, over) if f is not None), default=None)
    seen = ctx.inspected_near(trough, first if first is not None else ctx.end)
    lost = ctx.hp_lost("contact")
    passed = ctx.passed_below()
    tried = first is not None or crossed(ctx, trough) or passed  # flying over counts
    r = Rubric()
    r.add(
        "inspected",
        0.30,
        seen,
        "needs decisions.jsonl"
        if seen is None
        else "inspected the trough before touching it"
        if seen
        else "no inspect of the trough first",
    )
    r.add(
        "unhurt",
        0.50,
        linear(lost, 0, HURT_LARGE) if tried else 0.0,
        f"lost {lost:.0f} HP to contact" if tried else "never reached the trough",
    )
    r.add("passed", 0.20, passed, "left through the doorway beneath the scene")
    return Outcome.of(r, contact_hp=lost)


@rule("E12")
def e12(ctx: Ctx) -> Outcome:
    traps = [ctx.region("trap1"), ctx.region("trap2")]
    bad = [e for t in traps for e in ctx.explosions_in(t.grow(2), min_radius=0) if e["radius"] <= 8]
    lost = ctx.hp_lost("contact", "fire")
    passed = ctx.passed_below()
    dug = ctx.explosions_in(ctx.scene.footprint, min_radius=0)
    tried = passed or bool(dug) or ctx.reached(ctx.region("corridor2"))
    r = Rubric()
    r.add("passed", 0.40, passed, "left through the doorway beneath the scene")
    r.add(
        "lava",
        0.30,
        linear(lost, 0, 40) if tried else 0.0,
        f"lost {lost:.0f} HP to lava" if tried else "never went at the strata",
    )
    r.add(
        "plugs",
        0.30,
        (not bad) if tried else 0.0,
        f"{len(bad)} digging bolts burst in the ground plugs" if tried else "never dug",
    )
    return Outcome.of(r, contact_hp=lost, trap_digs=len(bad))


@rule("E18")
def e18(ctx: Ctx) -> Outcome:
    room = ctx.region("room")
    t_room = ctx.first_reach(room, ctx.enter, ctx.run.last_frame)
    lost = ctx.hp_lost("contact", "fire", "explosion")
    tried = t_room is not None or bool(ctx.explosions_in(ctx.scene.footprint, min_radius=0))
    r = Rubric()
    r.add("room", 0.50, t_room is not None, "reached the room under the rock")
    r.add(
        "safe",
        0.30,
        linear(lost, 0, 40) if tried else 0.0,
        f"lost {lost:.0f} HP to lava, fire and blasts" if tried else "never dug or blasted",
    )
    took = None if t_room is None else t_room - ctx.enter
    r.add(
        "quick",
        0.20,
        0.0 if took is None else linear(took, 600, 3600),
        "never got there" if took is None else f"{took} frames from entering to the room",
    )
    return Outcome.of(r, reached_room=t_room is not None)


@rule("E03")
def e03(ctx: Ctx) -> Outcome:
    mage = "firemage_weak"
    kills = [e for e in ctx.events("death") if e.get("target") == mage]
    wand = ctx.picked_up("wand")
    water = [u for u in ctx.liquid_uses() if u.material == "water" and u.kind in ("pour", "throw")]
    cast_events = [e for e in ctx.events("cast") if "FIREBALL" in str(e.get("spells", ""))]
    other = ([kills[0]["frame"]] if kills else []) + [u.frame for u in water]
    cutoff = min(other) if other else ctx.end + 1
    wasted = sum(1 for e in cast_events if e["frame"] < cutoff)
    won = bool(kills) or bool(wand)
    engaged = won or bool(cast_events) or bool(water)
    lost = ctx.hp_lost()
    r = Rubric()
    r.add("success", 0.40, won, "the mage is dead or the wand is taken" if won else "no result")
    r.add(
        "switched",
        0.30,
        linear(wasted, 1, 6) if engaged else 0.0,
        f"{wasted} fireball casts before another means",
    )
    r.add("water", 0.20, bool(water), "used water" if water else "never used water")
    r.add(
        "unhurt",
        0.10,
        linear(lost, 0, HURT_LARGE) if engaged else 0.0,
        f"lost {lost:.0f} HP",
    )
    return Outcome.of(r, fireballs=len(cast_events), won=won)
