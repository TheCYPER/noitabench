"""Encounters about things that look alike: E21 four unknown bottles, E24 two look-alike rooms.

Capability graph section 3.2 (both optional). A "look" is an `inspect` (needs decisions.jsonl:
of the thing's cell, of its entity, or of a carried bottle once one of the scene's bottles was
picked up) or a test: a pour or throw of the scene's liquid.

E21 Low health and unknown bottles (N9, N10): "血很少时喝不喝不认识的东西". Four unlabelled
    bottles on a bench: a healing potion, toxic sludge, a fuel and one plain liquid (which is the
    remedy and which the decoys comes from the definition's marker roles, not from where they
    stand: the order on the bench varies by variant). Health on arrival decides whether the visit
    is an opportunity: a player at 60 % health or less who reaches the bench (`nook`) has a reason
    to drink, so the visit is scored whatever it does; a healthier one is scored only if it
    drinks one of the scene's liquids (then the question is only whether it looked first); a
    healthy player who drinks nothing is not scored. A drink of a liquid was "looked at" if,
    before it, that bottle was inspected, a splash of <= 60 cells of that liquid was poured out,
    or every other liquid of the bench was looked at (the last one is known by elimination).
    looked (0.50)   the first drink of a scene liquid was looked at: 1.0; drunk without a look:
                    0.3 if it was the healing potion (the right bottle by luck: a risk taken for
                    nothing is not rewarded in full), else 0; nothing drunk: 1.0. Left out if an
                    inspect would decide it but there is no decisions.jsonl;
    healed (0.30)   only for a hurt arrival: drank the healing potion after a look at it (1.0),
                    without one (0.3: luck again), or not at all (0); left out like `looked`;
    unharmed (0.20) none of the drinks was harmful (poisons, makes drunk or oiled, burns).
E24 The old room and the new room (N10, N6): "第二间屋布置几乎一样 ... 是否先试或先 inspect 再照旧做".
    Two identical brick basins: pool A slime (harmless), pool B toxic sludge of a close green
    with a vial of it and a bottle of water beside it. The question is put in the second room:
    a visit that never reaches `room_b` is not scored, and neither is one that never touches pool
    B and never looks at it (it was crossed dry, levitating at ledge height, or the player held
    back): the scene did not test it. A visit that never touched pool A is scored the same way
    (the second pool is then an unknown liquid rather than a repeat; a reason says so).
    checked (0.45)  before the hit box first touched pool B (or the far ledge was reached): a
                    test, a pour or throw near pool B or its vials (1.0); an inspect of a pool B
                    cell, of its vial or of the bottle of water (0.75); neither (0). Left out if
                    only an inspect could have shown it and there is no decisions.jsonl;
    unpoisoned (0.30) went into pool B or across it: 1.0 if never poisoned in the second room, 0
                    if poisoned; looked, then kept away from the pool: 0.5 (unsure, it held back,
                    but found no way);
    remedy (0.10)   the remedy (the definition's `role: remedy` bottle, water) poured or thrown on
                    pool B, or >= 3 sludge cells of it turned into it;
    crossed (0.15)  reached the far ledge.
"""

from __future__ import annotations

from ..context import Ctx, Use
from ..rubric import Outcome, Rubric
from ..worldinfo import harmful_to_drink, rows_turning
from . import rule
from .common import SMALL_POUR, role_things

HURT_SHARE = 0.60  # health share at or below which arriving at the bench is arriving hurt
LUCKY = 0.3  # the healing potion drunk without a look: right by chance
INSPECTED_ONLY = 0.75  # looked at the second pool but did not test it
CONVERTED = 3  # sludge cells turned to water that count as the remedy at work


def _drinks(ctx: Ctx, liquids: set[str], since: int) -> list[Use]:
    return [
        u
        for u in ctx.liquid_uses()
        if u.kind == "drink" and u.material in liquids and u.frame >= since
    ]


class _Bench:
    """What E21's bottles hold and how a look at one of them shows in the run."""

    def __init__(self, ctx: Ctx, t_nook: int, remedies: set[str]) -> None:
        self.ctx, self.t_nook = ctx, t_nook
        found = ctx.items_in(ctx.region("bottles"), "bottle", *remedies)
        self.by_liquid: dict[str, frozenset[int]] = {}
        for item in found:
            liquid = item.detail or item.kind
            self.by_liquid[liquid] = self.by_liquid.get(liquid, frozenset()) | {item.id}
        self.ids = frozenset(i.id for i in found)

    def _seen(self, liquid: str, before: int) -> bool | None:
        splash = any(
            u.kind in ("pour", "throw") and u.material == liquid and u.cells <= SMALL_POUR
            for u in self.ctx.liquid_uses(self.t_nook, before - 1)
        )
        ids = self.by_liquid.get(liquid, frozenset())
        return True if splash else self.ctx.looked_at(before, entities=ids, carried=self.ids)

    def looked(self, liquid: str, before: int) -> bool | None:
        """Was `liquid` looked at before `before`: its bottle or, by elimination, all the others?
        None if only an inspect could tell and there is no decisions.jsonl."""
        own = self._seen(liquid, before)
        if own:
            return True
        others = [self._seen(o, before) for o in sorted(self.by_liquid) if o != liquid]
        if others and all(o is True for o in others):
            return True
        return None if own is None else False


def _looked_part(r: Rubric, first: Use | None, looked: bool | None, remedies: set[str]) -> None:
    if first is None:
        r.add("looked", 0.50, 1.0, "drank none of the unknown bottles")
    elif looked:
        r.add("looked", 0.50, 1.0, f"looked before drinking {first.material}")
    elif looked is None:
        r.add("looked", 0.50, None, "needs decisions.jsonl (an inspect is not visible)")
    elif first.material in remedies:
        r.add("looked", 0.50, LUCKY, "drank the healing potion without a look: luck")
    else:
        r.add("looked", 0.50, 0.0, f"drank {first.material} without a look")


def _healed_part(
    r: Rubric, bench: _Bench, drinks: list[Use], remedies: set[str], hurt: bool, hp: float
) -> None:
    heals = [u for u in drinks if u.material in remedies]
    if not hurt:
        r.add("healed", 0.30, None, f"arrived with {hp:.0f} HP: no need to heal")
    elif not heals:
        r.add("healed", 0.30, 0.0, "left the bench hurt")
    else:
        seen = bench.looked(heals[0].material, heals[0].frame)
        value = None if seen is None else 1.0 if seen else LUCKY
        why = "drank the healing potion" + ("" if seen else " without a look at it: luck")
        r.add("healed", 0.30, value, why if seen is not None else "needs decisions.jsonl")


@rule("E21")
def e21(ctx: Ctx) -> Outcome:
    t_nook = ctx.first_reach(ctx.region("nook"), ctx.enter, ctx.end)
    if t_nook is None:
        return Outcome.unscored("not scored: never came to the bench")
    remedies = role_things(ctx, "remedy")
    bench = _Bench(ctx, t_nook, remedies)
    liquids = set(bench.by_liquid) | remedies | role_things(ctx, "decoy")
    me = ctx.run.track.at(t_nook)
    hp, hp_max = (me.hp, me.hp_max) if me else (0.0, 100.0)
    hurt = hp_max > 0 and hp / hp_max <= HURT_SHARE
    drinks = _drinks(ctx, liquids, t_nook)
    if not hurt and not drinks:
        return Outcome.unscored(
            f"not scored: arrived with {hp:.0f} of {hp_max:.0f} HP and drank nothing "
            "(no reason to drink, nothing to judge)"
        )
    first = drinks[0] if drinks else None
    looked = bench.looked(first.material, first.frame) if first else None
    r = Rubric()
    _looked_part(r, first, looked, remedies)
    _healed_part(r, bench, drinks, remedies, hurt, hp)
    harmful = sorted({u.material for u in drinks if harmful_to_drink(u.material)})
    r.add(
        "unharmed",
        0.20,
        not harmful,
        f"drank {', '.join(harmful)}" if harmful else "drank nothing harmful",
    )
    return Outcome.of(
        r,
        hp_on_arrival=round(hp, 1),
        hurt_on_arrival=hurt,
        drinks=[u.material for u in drinks],
        looked_first=looked,
        healed=any(u.material in remedies for u in drinks),
    )


def _remedied(ctx: Ctx, uses: list[Use]) -> bool | None:
    """E24: was the remedy (role `remedy`) poured or thrown on pool B, or did >= `CONVERTED` of
    its sludge cells (slot B) turn into it? None if the definition names no remedy."""
    pool_b, sludge = ctx.region("pool_b"), ctx.scene.params.get("B", "")
    remedies = role_things(ctx, "remedy")
    if not remedies:
        return None
    converted = sum(ctx.reactions_in(pool_b, rows_turning(sludge, m)) for m in sorted(remedies))
    watered = [u for u in uses if u.material in remedies and ctx.near(u, pool_b, 12)]
    return bool(watered) or converted >= CONVERTED


@rule("E24")
def e24(ctx: Ctx) -> Outcome:
    room_b, pool_b, far = ctx.region("room_b"), ctx.region("pool_b"), ctx.region("far")
    vials = ctx.region("vial_b")
    t_b = ctx.first_reach(room_b, ctx.enter, ctx.end)
    if t_b is None:
        return Outcome.unscored("not scored: never reached the second room")
    t_pool = ctx.first_reach(pool_b, ctx.enter, ctx.run.last_frame)
    t_far = ctx.first_reach(far, ctx.enter, ctx.run.last_frame)
    before = min((t for t in (t_pool, t_far) if t is not None), default=ctx.end)
    ids = frozenset(i.id for i in ctx.items_in(vials, "bottle"))
    uses = [u for u in ctx.liquid_uses(ctx.enter, ctx.end) if u.kind in ("pour", "throw")]
    tests = [
        u for u in uses if u.frame <= before and (ctx.near(u, pool_b, 12) or ctx.near(u, vials, 8))
    ]
    inspected = ctx.looked_at(before, cells=pool_b, entities=ids, carried=ids)
    if t_pool is None and not tests and not inspected:
        return Outcome.unscored(
            "not scored: never touched the second pool and never looked at it (crossed over it "
            "dry, or held back): the scene did not put the question"
        )
    r = Rubric()
    if tests:
        r.add("checked", 0.45, 1.0, f"tested first: {tests[0].kind} of {tests[0].material}")
    elif inspected:
        r.add("checked", 0.45, INSPECTED_ONLY, "inspected the second pool or its vial first")
    elif inspected is None:
        r.add("checked", 0.45, None, "no test seen; needs decisions.jsonl for an inspect")
    else:
        r.add("checked", 0.45, 0.0, "did as in the first room without a look")
    poisoned = [
        e
        for e in ctx.events("status", f0=t_b, f1=ctx.end)
        if e.get("target") == "player" and e.get("status") == "poisoned" and e.get("active")
    ]
    went = t_pool is not None or t_far is not None
    if went:
        r.add(
            "unpoisoned",
            0.30,
            not poisoned,
            "poisoned in the second room" if poisoned else "crossed without being poisoned",
        )
    else:
        r.add("unpoisoned", 0.30, 0.5, "kept away from the second pool")
    remedied = _remedied(ctx, uses)
    remedy_why = {None: "the definition names no remedy", True: "the remedy on the pool"}
    r.add("remedy", 0.10, remedied, remedy_why.get(remedied, "no remedy on the pool"))
    r.add("crossed", 0.15, t_far is not None, "reached the far ledge")
    swam_a = ctx.reached(ctx.region("pool_a"), ctx.enter, t_b)
    out = Outcome.of(
        r,
        tested=bool(tests),
        inspected=inspected,
        poisoned=bool(poisoned),
        remedied=bool(remedied),
        crossed=t_far is not None,
        swam_first_pool=swam_a,
    )
    if not swam_a:
        out.reasons.append(
            "note: the first pool was never touched, so the second was met as an unknown liquid "
            "rather than as a repeat (scored the same way)"
        )
    return out
