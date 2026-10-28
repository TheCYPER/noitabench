"""Encounters about everyday physics: E09 fire on wood, E10 deep water against walkers.

Capability graph section 3.2 (both optional; the scene's own guard, barrel and pack are told
apart from others of their kind by where the entity list first saw them):

E09 Enemy on a wooden platform (N4, N1): "是否想到烧木头让它掉下去". A shotgunner in a bunker of
    planks on posts; a gunpowder barrel on a pedestal 32 cells from the door lights an oil gutter
    that runs to the posts. The question is put once the player is in the hall (in the guard's
    sight), or the barrel blew, the planks burned or the guard died; a visit that only touched
    the doorway is not scored. The barrel and the guard are judged on what happened to them at
    any time up to the end of the visit: the best play blows the barrel from outside the door,
    before the visit begins.
    fire (0.45)     1.0 if the planks of the bunker or its posts caught fire before the guard
                    died (or it died by fire), 0 if it was shot down first (a duel) or nothing
                    burned; 0 too if the fire came from a barrel the guard's own buckshot set off
                    (the last `hit` on the barrel in the 3 frames before it blew names an enemy
                    projectile): that is not the player's solution;
    won (0.20)      the guard is dead or the wand beyond the bunker was taken (a guard that
                    died in the fire its own buckshot started counts only if the wand was taken);
    clear (0.15)    when the player set the barrel off: its blast damage to the player 0 is
                    1.0, 30 HP or more 0 (left out if the barrel never blew, or the guard set it
                    off: being out of its reach then was luck; the blast still counts in unhurt);
    unhurt (0.20)   HP the player lost inside the hall (damage events placed in it) and to the
                    blast: 0 is 1.0, 50 or more is 0 (0 if the player did nothing to the bunker,
                    the barrel or the guard and never got past them; a fire the guard's own shot
                    started, and the guard's death in it, are not something the player did).
E10 Moat (N4, N1): "会不会利用深水甩掉追兵、从水面游过去". A pit of water 32 wide and 22 deep
    between the door and a wand; three Hämis wait on the far ledge, and one that falls into the
    pit cannot climb out. The question is put once the player is on the near ledge, in the pit
    or beyond it; a visit that only touched the doorway is not scored.
    crossed (0.40)  reached the far ledge (or took the wand);
    water (0.20)    the share of the pack that ended in the pit (feet more than 3 cells below the
                    surface over it), not killed on dry ground: the water did the fighting; 0 if
                    the player died (left out without a pack, e.g. a run with the enemies off);
    unhurt (0.40)   HP lost in the scene: 25 or less is 1.0 (the swimmer pays for what leaps at
                    it before it falls), 70 or more is 0; 0 if the player died or neither went
                    into the pit nor got across.
"""

from __future__ import annotations

from typing import Any

from ..context import Ctx
from ..geometry import Rect
from ..rubric import Outcome, Rubric, linear
from ..worldinfo import enemy_projectiles, spell_projectiles
from . import rule

BLAST_FRAMES = 5  # frames after a barrel blows during which explosion damage is its blast
SET_OFF_FRAMES = 3  # frames before a barrel blows in which a hit on it is what set it off
TRAPPED_DEPTH = 3  # cells below the pit's surface at which a Hämis can no longer climb out
SWIM_TOLL, SWIM_BAD = 25.0, 70.0  # HP: what crossing the moat costs at best, and too much


def _first(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    return events[0] if events else None


def _set_off_by_enemy(
    events: list[dict[str, Any]], burst: dict[str, Any], barrels: frozenset[int]
) -> bool:
    """True if the last `hit` on the barrel just before it blew was an enemy's shot (the guard's
    buckshot can set it off by itself). A break with no hit before it (fire, a blast, a kick) was
    not the guard's: its only weapon is buckshot."""
    t = burst["frame"]
    hits = [
        e
        for e in events
        if e["type"] == "hit"
        and t - SET_OFF_FRAMES <= e["frame"] <= t
        and (e.get("id") in barrels or e.get("id") == burst.get("id"))
    ]
    return bool(hits) and hits[-1].get("projectile") in enemy_projectiles()


def _clear_part(
    ctx: Ctx, r: Rubric, burst: dict[str, Any] | None, by_guard: bool
) -> list[dict[str, Any]]:
    """E09 `clear`: the blast damage of a barrel the player set off. Returns the player's damage
    events of the blast (whoever set it off)."""
    if burst is None:
        r.add("clear", 0.15, None, "the barrel never blew")
        return []
    t0 = burst["frame"]
    blast = ctx.run.events.player_damage(t0, t0 + BLAST_FRAMES, "explosion")
    hit = sum(float(e.get("amount", 0.0)) for e in blast)
    me = ctx.run.track.at(t0)
    where = ""
    if me is not None:
        gap = ((me.x + me.w / 2 - burst["x"]) ** 2 + (me.y + me.h / 2 - burst["y"]) ** 2) ** 0.5
        where = f" {gap:.0f} cells away"
    if by_guard:
        r.add("clear", 0.15, None, f"the guard set the barrel off{where} ({hit:.0f} HP)")
    else:
        r.add("clear", 0.15, linear(hit, 0, 30), f"the barrel blew{where}: {hit:.0f} HP")
    return blast


@rule("E09")
def e09(ctx: Ctx) -> Outcome:
    hall, bunker, posts = ctx.region("hall"), ctx.region("bunker"), ctx.region("posts")
    barrel_ids = frozenset(i.id for i in ctx.items_in(ctx.region("barrel"), "barrel_gunpowder"))
    guards = frozenset(c.id for c in ctx.creatures_in(bunker, "shotgunner"))
    upto = ctx.run.events.between(0, ctx.end)
    burst = _first(
        [
            e
            for e in upto
            if e["type"] == "barrel_break"
            and (
                e.get("id") in barrel_ids or ctx.region("barrel").grow(6).has_point(e["x"], e["y"])
            )
        ]
    )
    wood = _first(
        [
            e
            for e in upto
            if e["type"] == "ignite"
            and e.get("material") == "wood"
            and (
                bunker.grow(1).has_point(e["x"], e["y"]) or posts.grow(1).has_point(e["x"], e["y"])
            )
        ]
    )
    death = _first(
        [e for e in ctx.run.events.between(0, ctx.run.last_frame, "death") if e.get("id") in guards]
    )
    shots = [
        e
        for e in upto
        if e["type"] == "hit"
        and e.get("id") in guards
        and e.get("projectile") in spell_projectiles()
    ]
    rewards = frozenset(i.id for i in ctx.items_in(ctx.region("reward"), "wand"))
    took = any(e.get("id") in rewards for e in ctx.run.events.between(0, ctx.end, "pickup"))
    in_hall = ctx.reached(hall, ctx.enter, ctx.end)
    if not (in_hall or burst or wood or (death is not None and death["frame"] <= ctx.end)):
        return Outcome.unscored("not scored: only the doorway was touched (the guard never saw it)")
    by_guard = burst is not None and _set_off_by_enemy(upto, burst, barrel_ids)
    guard_fire = by_guard and wood is not None and wood["frame"] >= burst["frame"]
    mine = bool((burst and not by_guard) or (wood and not guard_fire))
    luck = guard_fire and death is not None and death.get("source") == "fire"
    engaged = mine or bool(shots or took or (death and not luck))
    engaged = engaged or ctx.reached(posts, ctx.enter, ctx.end)
    burned_first = wood is not None and (death is None or wood["frame"] <= death["frame"])
    by_fire = death is not None and death.get("source") == "fire"
    r = Rubric()
    if guard_fire and (burned_first or by_fire):
        r.add("fire", 0.45, 0.0, "the guard's own shot set the barrel off: not the player's fire")
    elif burned_first or by_fire:
        why = "the bunker burned" + (" and the guard died in the fire" if by_fire else "")
        r.add("fire", 0.45, 1.0, why)
    elif death is not None:
        r.add("fire", 0.45, 0.0, f"the guard was shot down ({death.get('source')}): a duel")
    else:
        r.add("fire", 0.45, 0.0, "nothing of the bunker burned")
    won = took or (death is not None and not luck)
    if won:
        won_why = "the guard is dead or the wand taken"
    else:
        won_why = "the guard died in its own fire, the wand not taken" if luck else "no result"
    r.add("won", 0.20, won, won_why)
    blast = _clear_part(ctx, r, burst, by_guard)
    box = hall.grow(8)
    hurt = {
        id(e): e
        for e in ctx.run.events.player_damage(0, ctx.end)
        if box.has_point(float(e.get("x", -1)), float(e.get("y", -1)))
    }
    hurt.update({id(e): e for e in blast})
    lost = sum(float(e.get("amount", 0.0)) for e in hurt.values())
    r.add(
        "unhurt",
        0.20,
        linear(lost, 0, 50) if engaged else 0.0,
        f"lost {lost:.0f} HP in the hall" if engaged else "did nothing to the bunker or the barrel",
    )
    return Outcome.of(
        r,
        barrel_blew=burst is not None,
        barrel_by=None if burst is None else "guard" if by_guard else "player",
        wood_burned=wood is not None,
        guard_death=None if death is None else death.get("source"),
        guard_shots=len(shots),
        won=won,
    )


def _trapped(
    path: list[tuple[int, float, float, float]], pool: Rect, surface_y: int, upto: int
) -> bool:
    """True if the creature was, at some sample up to `upto`, over the pit with its feet more than
    `TRAPPED_DEPTH` cells below the surface (it fell in; it cannot climb out)."""
    return any(
        f <= upto and pool.x - 2 <= cx <= pool.right + 2 and feet > surface_y + TRAPPED_DEPTH
        for f, cx, feet, _hp in path
    )


@rule("E10")
def e10(ctx: Ctx) -> Outcome:
    near, pool, far = ctx.region("near"), ctx.region("pool"), ctx.region("far")
    surface = ctx.region("surface")
    t_near, t_pool, t_far = (ctx.first_reach(x, ctx.enter, ctx.end) for x in (near, pool, far))
    if t_near is None and t_pool is None and t_far is None:
        return Outcome.unscored("not scored: only the doorway was touched (the pack never saw it)")
    rewards = frozenset(i.id for i in ctx.items_in(ctx.region("reward"), "wand"))
    took = any(e.get("id") in rewards for e in ctx.run.events.between(0, ctx.end, "pickup"))
    crossed = took or ctx.reached(far, ctx.enter, ctx.run.last_frame)
    pack = ctx.creatures_in(ctx.region("pack"), "longleg", margin=12)
    trapped = [c for c in pack if _trapped(c.path, pool, surface.y, ctx.end)]
    lost = ctx.hp_lost()
    melee = ctx.hp_lost("melee")
    died = ctx.died()
    engaged = crossed or t_pool is not None
    r = Rubric()
    r.add("crossed", 0.40, crossed, "reached the far ledge" if crossed else "never got across")
    r.add(
        "water",
        0.20,
        None if not pack else 0.0 if died else len(trapped) / len(pack),
        "no pack in the scene"
        if not pack
        else f"{len(trapped)} of {len(pack)} Hämis ended in the pit"
        + (", but the player died" if died else ""),
    )
    if died:
        r.add("unhurt", 0.40, 0.0, f"died in the scene ({melee:.0f} HP to bites)")
    elif engaged:
        r.add(
            "unhurt",
            0.40,
            linear(lost, SWIM_TOLL, SWIM_BAD),
            f"lost {lost:.0f} HP, {melee:.0f} of them to bites",
        )
    else:
        r.add("unhurt", 0.40, 0.0, "neither went into the pit nor got across")
    return Outcome.of(
        r,
        crossed=crossed,
        pack=len(pack),
        trapped=len(trapped),
        melee_hp=round(melee, 1),
        swam=t_pool is not None,
    )
