"""Encounters about lava: E02 the river, E07 the chain, E14 three bottles, E05 the vault, E04 the
lesson.

Capability graph section 3.2 (what each one looks at):

E02 Lava river (N1, must pass): "同层更早的地方有某液体滴到岩浆上凝固的景象；过河时是否用同族液体".
    crossed (0.25)  the hit box reached the far ledge;
    crust (0.40)    1.0 if >= 3 lava cells turned to rock inside the river (reaction rows
                    that make lava rock), 0.3 if a liquid of the water family was poured on the
                    river but no crust formed, else 0;
    unhurt (0.20)   HP lost to contact and fire: 0 HP is 1.0, 50 HP or more is 0 (0 if the
                    player did not try: neither poured on the river nor crossed);
    no_decoy (0.15) 0 if a liquid that does not solidify lava was poured on the river, 1.0 if
                    only the right liquid was; left out if nothing was poured.
E07 Chain (N3, N1, must pass; a combined scene, C1): "装水、穿火区、倒在岩浆上，顺序决定资源够不够".
    filled (0.15)   a `fill` of >= 20 cells at the pool;
    acid (0.20)     got across the acid trough;
    lava (0.35)     crust on the river (0.2: >= 3 cells turned to rock) and across it (0.15);
    passed (0.15)   left through the doorway under the scene;
    unhurt (0.15)   HP lost: 0 is 1.0, 60 or more is 0 (0 if the player never went at the scene:
                    filled the bottle, reached the acid or the lava, or got through).
E14 Three bottles (N6, N1): "是否先少量试；试验次数和浪费".
    sample (0.30)   the first pour or throw of any of the three liquids was a splash (<= 60
                    cells) rather than a bottle's worth (0.2 if it was a lot, 0 if none);
    crust (0.25)    >= 3 lava cells turned to rock;
    crossed (0.20)  reached the alcove beyond the river;
    waste (0.25)    cells of liquids that do not solidify lava poured or thrown on the river:
                    <= 60 is 1.0, >= 300 is 0.
E05 Locked vault (N2, N5; optional): "早先路过钥匙；到门口时是否记得回去拿". The key is a bottle
    of a liquid that crusts lava (marker role `solvent`: water or blood) on a pedestal in the
    first hall, beside a decoy (role `decoy`, a fuel); the vault lies down a shaft, behind a lava
    river under a low roof. The question is put when the player first reaches the foot of the
    shaft (`landing`) or the river (`river_gate`): there the vault and the river come into view.
    A visit that never gets there is not scored (the key was never needed: it shows nothing about
    memory).
    key (0.45)      1.0 if the key liquid was in hand on that arrival: this scene's key bottle
                    picked up before it, or a bottle of the same liquid picked up or filled
                    elsewhere earlier (and not thrown away since); 0.6 if the player went back
                    up for the key afterwards (picked it up after the arrival); 0 if never;
    crust (0.25)    1.0 if >= 3 lava cells of the river turned to rock, 0.3 if the key liquid
                    was poured on the river but no crust formed, else 0;
    vault (0.15)    reached the vault (or took one of its rewards);
    unhurt (0.15)   HP lost to contact and fire: 0 is 1.0, 50 or more is 0 (0 if the player
                    neither poured on the river, nor went into its passage, nor got across:
                    giving up at the shaft is not "unhurt").
E04 Laboratory ruin (N2, N1): "遗迹里展示一条反应；同一局后面遇到需要它的地方时，用没用上".
    looked (0.3)    took the exhibit bottle or inspected the bench;
    used (0.7)      of the lava rivers (E02, E05, E07, E14) the player went at later in the run (it
                    poured on the river, filled a bottle or crossed it), the share that were
                    crossed on a crust. Not scored if it never went at one: a river dug round
                    is no chance to apply the lesson.
"""

from __future__ import annotations

from ..context import FILL_CELLS, Ctx, liquid_in_hand
from ..rubric import Outcome, Rubric, linear
from ..worldinfo import lava_rows, lava_solidifiers
from . import late_rule, rule
from .common import CRUST_CELLS, HURT_LARGE, SMALL_POUR, crossed, role_things

LAVA_IDS = ("E02", "E05", "E07", "E14")
KEY_LATE = 0.6  # the key fetched after the river was seen: remembered, at the price of a climb


def _kinds(uses, kinds=("pour", "throw")):
    return [u for u in uses if u.kind in kinds]


@rule("E02")
def e02(ctx: Ctx) -> Outcome:
    river, far = ctx.region("river"), ctx.region("far")
    right = lava_solidifiers()
    uses = [u for u in _kinds(ctx.liquid_uses()) if ctx.near(u, river, 40)]
    wrong = [u for u in uses if u.material not in right]
    poured_right = [u for u in uses if u.material in right]
    crust = ctx.reactions_in(river, lava_rows())
    got_across = ctx.reached(far, ctx.enter, ctx.run.last_frame)
    tried = bool(uses) or got_across
    lost = ctx.hp_lost("contact", "fire")
    r = Rubric()
    r.add("crossed", 0.25, got_across, "reached the far ledge" if got_across else "did not cross")
    crust_value = 1.0 if crust >= CRUST_CELLS else 0.3 if poured_right else 0.0
    r.add("crust", 0.40, crust_value, f"{crust} lava cells turned to rock")
    r.add(
        "unhurt",
        0.20,
        linear(lost, 0, 50) if tried else 0.0,
        f"lost {lost:.0f} HP to contact and fire" if tried else "did not try",
    )
    r.add(
        "no_decoy",
        0.15,
        0.0 if wrong else (1.0 if poured_right else None),
        f"poured {[u.material for u in wrong]} on the river" if wrong else "only the right liquid",
    )
    return Outcome.of(
        r, lava_attempted=tried, lava_solidified=crust >= CRUST_CELLS, crossed=got_across
    )


@rule("E07")
def e07(ctx: Ctx) -> Outcome:
    acid, lava = ctx.region("acid"), ctx.region("lava")
    fills = [e for e in ctx.events("fill") if e.get("cells", 0) >= FILL_CELLS]
    crust = ctx.reactions_in(lava, lava_rows())
    lost = ctx.hp_lost()
    over_lava = crossed(ctx, lava)
    over_acid = crossed(ctx, acid)
    passed = ctx.passed_below()
    tried = (
        bool(fills) or crust > 0 or over_acid or over_lava or passed
        or ctx.reached(acid.grow(2)) or ctx.reached(lava.grow(2))
    )  # fmt: skip
    r = Rubric()
    r.add("filled", 0.15, bool(fills), "filled the bottle at the pool" if fills else "never filled")
    r.add("acid", 0.20, over_acid, "got across the acid trough")
    r.add("crust", 0.20, crust >= CRUST_CELLS, f"{crust} lava cells turned to rock")
    r.add("lava", 0.15, over_lava, "got across the lava river")
    r.add("passed", 0.15, passed, "left through the doorway beneath the scene")
    r.add(
        "unhurt",
        0.15,
        linear(lost, 0, HURT_LARGE) if tried else 0.0,
        f"lost {lost:.0f} HP in the scene" if tried else "did not go at the scene",
    )
    return Outcome.of(
        r,
        lava_attempted=bool(fills) or crust > 0 or over_lava,
        lava_solidified=crust >= CRUST_CELLS,
        crossed=over_lava,
    )


@rule("E14")
def e14(ctx: Ctx) -> Outcome:
    river, alcove = ctx.region("river"), ctx.region("alcove")
    bottles = set(ctx.scene.params.values())
    right = lava_solidifiers()
    tries = [u for u in _kinds(ctx.liquid_uses()) if u.material in bottles]
    on_river = [u for u in tries if ctx.near(u, river, 40)]
    waste = sum(u.cells for u in on_river if u.material not in right)
    crust = ctx.reactions_in(river, lava_rows())
    r = Rubric()
    if tries:
        first = tries[0]
        splash = first.cells <= SMALL_POUR
        r.add(
            "sample",
            0.30,
            1.0 if splash else 0.2,
            f"first tried {first.material}: {first.cells} cells"
            + (" (a splash)" if splash else " (a lot)"),
        )
    else:
        r.add("sample", 0.30, 0.0, "tried none of the three liquids")
    r.add("crust", 0.25, crust >= CRUST_CELLS, f"{crust} lava cells turned to rock")
    r.add("crossed", 0.20, ctx.reached(alcove, ctx.enter, ctx.run.last_frame), "reached the alcove")
    r.add(
        "waste",
        0.25,
        linear(waste, SMALL_POUR, 300) if tries else 0.0,
        f"{waste} cells of liquid that does not solidify lava poured on the river",
    )
    return Outcome.of(
        r,
        lava_attempted=bool(on_river),
        lava_solidified=crust >= CRUST_CELLS,
        tried_liquids=sorted({u.material for u in tries}),
    )


def _key_in_hand(ctx: Ctx, solvent: str, keys: frozenset[int], t_arrive: int) -> str | None:
    """How the key liquid came to be in hand before `t_arrive`: 'key' (this scene's bottle),
    'own' (a bottle of it picked up or filled elsewhere and not thrown since), or None."""
    if not solvent:
        return None
    picks = ctx.run.events.between(0, t_arrive - 1, "pickup")
    if any(e.get("id") in keys for e in picks):
        return "key"
    return "own" if liquid_in_hand(ctx.run, solvent, t_arrive) is not None else None


@rule("E05")
def e05(ctx: Ctx) -> Outcome:
    landing, gate, river, vault = (
        ctx.region("landing"), ctx.region("river_gate"), ctx.region("river"), ctx.region("vault"),
    )  # fmt: skip
    arrivals = [ctx.first_reach(r, ctx.enter, ctx.end) for r in (landing, gate)]
    t_arrive = min((t for t in arrivals if t is not None), default=None)
    if t_arrive is None:
        return Outcome.unscored(
            "not scored: never went down to the river in front of the vault (the key was never "
            "needed, so nothing shows whether it was remembered)"
        )
    solvent = min(role_things(ctx, "solvent"), default="")  # the key bottle's liquid
    decoy = min(role_things(ctx, "decoy"), default="")
    keys = frozenset(i.id for i in ctx.items_in(ctx.region("key"), "bottle"))
    held = _key_in_hand(ctx, solvent, keys, t_arrive)
    late = [
        e for e in ctx.run.events.between(t_arrive, ctx.run.last_frame, "pickup")
        if e.get("id") in keys
    ]  # fmt: skip
    if held == "key":
        key_value, key_why = 1.0, "had the key in hand on reaching the river"
    elif held:
        key_value, key_why = 1.0, f"brought {solvent} from elsewhere to the river"
    elif late:
        key_value, key_why = KEY_LATE, "went back up for the key after seeing the river"
    else:
        key_value, key_why = 0.0, "never fetched the key"
    uses = [u for u in _kinds(ctx.liquid_uses()) if ctx.near(u, river, 40)]
    poured_key = [u for u in uses if u.material == solvent]
    poured_decoy = [u for u in uses if u.material == decoy and decoy]
    crust = ctx.reactions_in(river, lava_rows())
    rewards = frozenset(i.id for i in ctx.items_in(vault))
    took = any(e.get("id") in rewards for e in ctx.events("pickup", f0=ctx.enter, f1=ctx.end))
    in_vault = took or ctx.reached(vault, ctx.enter, ctx.run.last_frame)
    tried = bool(uses) or in_vault or ctx.reached(gate, ctx.enter, ctx.end)
    lost = ctx.hp_lost("contact", "fire")
    r = Rubric()
    r.add("key", 0.45, key_value, key_why)
    crust_value = 1.0 if crust >= CRUST_CELLS else 0.3 if poured_key else 0.0
    crust_why = f"{crust} lava cells turned to rock"
    if poured_decoy:
        crust_why += f"; poured the decoy ({decoy}) on the river"
    r.add("crust", 0.25, crust_value, crust_why)
    r.add("vault", 0.15, in_vault, "reached the vault" if in_vault else "never got into the vault")
    r.add(
        "unhurt",
        0.15,
        linear(lost, 0, 50) if tried else 0.0,
        f"lost {lost:.0f} HP to contact and fire" if tried else "gave up at the shaft",
    )
    return Outcome.of(
        r,
        key_in_hand=bool(held),
        key_fetched_late=bool(late) and not held,
        crust=crust,
        reached_vault=in_vault,
        lava_attempted=tried,
        lava_solidified=crust >= CRUST_CELLS,
    )


@late_rule("E04")
def e04(ctx: Ctx, others: list) -> Outcome:
    """Scored from what the run did with lava afterwards (needs the other visits)."""
    liquid = ctx.scene.params.get("A", "")
    bench = ctx.region("bench")
    took = bool(ctx.picked_up("bottle", liquid)) if liquid else False
    inspected = ctx.inspected_near(bench, ctx.end, margin=24)
    looked = True if took or inspected else (None if inspected is None else False)
    later = [
        o
        for o in others
        if o.visit.scene.eid in LAVA_IDS
        and o.visit.enter > ctx.enter
        and o.outcome.facts.get("lava_attempted")
    ]
    if not later:
        return Outcome.unscored("no lava river was tackled after the ruin: nothing to apply it to")
    used = sum(1 for o in later if o.outcome.facts.get("lava_solidified"))
    r = Rubric()
    r.add("looked", 0.3, looked, "took the exhibit bottle or inspected the bench")
    r.add(
        "used",
        0.7,
        used / len(later),
        f"{used} of {len(later)} later lava rivers crossed on a crust "
        f"({', '.join(o.visit.scene.eid for o in later)})",
    )
    return Outcome.of(r, later=len(later), used=used)
