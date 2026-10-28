"""Encounters about finding the way: E08 flooded passage, E22 two roads, E23 the vial.

Capability graph section 3.2:

E08 Flooded passage (N4, N5, must pass): "是否想到挖开地板让水流走".
    passed (0.40)    reached the cellar under the floor;
    dug (0.30)       a digging bolt burst in the floor (the thin ground under the water);
    quick (0.20)     frames from entering to the first dig: 300 or fewer is 1.0, 1800 or more 0;
    unhurt (0.10)    HP lost (drowning): 0 is 1.0, 50 or more is 0 (0 if the player never went
                     into the water, dug or got through: nothing was tried).
E22 Short way, long way (N9, N3, must pass): "选穿过火力的近路还是安全的远路，结果如何".
    route (0.40)     the safe lane under the floor is 1.0, the raised corridor up to the guards 0.3
                     (risk taken for nothing is not rewarded even if it works), neither 0;
    unhurt (0.30)    HP lost: 0 is 1.0, 60 or more is 0 (0 if neither road was taken);
    passed (0.30)    left through the doorway beneath the scene.
E23 The vial and the deep pool (N10, N6, must pass): "先用小瓶试（倒在地上、泼向敌人）再决定怎么过".
    tried (0.50)     before the first touch of the pool: poured, thrown or drank the sample
                     liquid (1.0); inspected a bottle only (0.5; needs decisions.jsonl); neither (0);
    unhurt (0.30)    HP lost in the scene: 0 is 1.0, 40 or more is 0 (sludge poisons, oil and
                     whiskey burn); 0 if the player never went at the pool or tried the liquid;
    passed (0.20)    reached the far side.

A part that rewards the absence of harm counts only if the player went at the scene: standing
at the door and leaving would otherwise score on "no damage taken".
"""

from __future__ import annotations

from ..context import Ctx
from ..rubric import Outcome, Rubric, linear
from . import rule
from .common import HURT_LARGE


@rule("E08")
def e08(ctx: Ctx) -> Outcome:
    floor, cellar = ctx.region("floor"), ctx.region("cellar")
    digs = ctx.explosions_in(floor.grow(6), f0=ctx.enter, f1=ctx.run.last_frame)
    digs = [e for e in digs if e["radius"] <= 8]
    t_dig = digs[0]["frame"] - ctx.enter if digs else None
    lost = ctx.hp_lost()
    got_down = ctx.reached(cellar, ctx.enter, ctx.run.last_frame)
    tried = bool(digs) or got_down or ctx.reached(ctx.region("water"))
    r = Rubric()
    r.add("passed", 0.40, got_down, "reached the cellar")
    r.add("dug", 0.30, bool(digs), f"{len(digs)} digging bolts burst in the floor")
    r.add(
        "quick",
        0.20,
        0.0 if t_dig is None else linear(t_dig, 300, 1800),
        "never dug" if t_dig is None else f"first dig {t_dig} frames after entering",
    )
    r.add(
        "unhurt",
        0.10,
        linear(lost, 0, 50) if tried else 0.0,
        f"lost {lost:.0f} HP" if tried else "never went into the water",
    )
    return Outcome.of(r, dug=bool(digs))


@rule("E22")
def e22(ctx: Ctx) -> Outcome:
    short = ctx.reached(ctx.region("guards").grow(10), ctx.enter, ctx.end)
    long_way = ctx.reached(ctx.region("long_route"), ctx.enter, ctx.run.last_frame)
    if short:
        route, why = 0.3, "went up to the guards in the raised corridor"
    elif long_way:
        route, why = 1.0, "took the safe lane under the floor"
    else:
        route, why = 0.0, "took neither road"
    lost = ctx.hp_lost()
    passed = ctx.passed_below()
    tried = short or long_way or passed
    r = Rubric()
    r.add("route", 0.40, route, why)
    r.add(
        "unhurt",
        0.30,
        linear(lost, 0, HURT_LARGE) if tried else 0.0,
        f"lost {lost:.0f} HP" if tried else "took neither road",
    )
    r.add("passed", 0.30, passed, "left through the doorway beneath the scene")
    return Outcome.of(r, route="short" if short else "long" if long_way else "none")


@rule("E23")
def e23(ctx: Ctx) -> Outcome:
    pool, far = ctx.region("pool"), ctx.region("far")
    sample = ctx.scene.params.get("A", "")
    t_pool = ctx.first_reach(pool, ctx.enter, ctx.run.last_frame)
    t_far = ctx.first_reach(far, ctx.enter, ctx.run.last_frame)
    before = t_pool if t_pool is not None else t_far if t_far is not None else ctx.end
    tests = [
        u
        for u in ctx.liquid_uses(ctx.enter, before)
        if u.material == sample and u.kind in ("pour", "throw", "drink")
    ]
    looked = None
    if ctx.run.decisions.present:
        looked = any(
            c.args.get("bottle") is not None or c.args.get("entity") is not None
            for c in ctx.commands("inspect", f0=ctx.enter, f1=before)
        )
    if tests:
        tried, why = 1.0, f"{tests[0].kind} of {sample} before the pool"
    elif looked:
        tried, why = 0.5, "inspected a bottle but never tried the liquid"
    elif looked is None:
        tried, why = 0.0, "no test of the liquid seen (no decisions.jsonl: inspects not visible)"
    else:
        tried, why = 0.0, "did not try the liquid first"
    lost = ctx.hp_lost()
    went_at = t_pool is not None or t_far is not None or bool(tests)
    r = Rubric()
    r.add("tried", 0.50, tried, why)
    r.add(
        "unhurt",
        0.30,
        linear(lost, 0, 40) if went_at else 0.0,
        f"lost {lost:.0f} HP" if went_at else "never went at the pool",
    )
    r.add("passed", 0.20, t_far is not None, "reached the far side")
    return Outcome.of(r, tested_first=bool(tests), crossed=t_far is not None)
