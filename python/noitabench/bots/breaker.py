"""The wand that breaks brick, and a bomb thrown at the seal without the thrower in the blast.

No single spell of the content breaks brick (durability 14): the bomb's explosion removes up to
11 and the modifier `EXPLOSIVE_PROJECTILE` adds 3 to the explosion of the spell it modifies
(`spells.json` `shot.explosion_durability`, the largest bonus counts, copies do not stack). So the
key is two spells found in two places of the world, and an order in a wand: modifiers first, the
projectile after them (a modifier draws the next card, so `[EXPLOSIVE_PROJECTILE, BOMB]` casts
as one).

* `plan_loadout` picks from the spells in hand the ones that reach the brick.
* `assemble` / `stow` put them at the front of a wand and take them out again, with the wand
  editor (`place`, `swap`, `take`), leaving the spells already in the wand where they are.
* `break_with_loadout` goes to the plug, throws the bomb onto it, runs from the blast (the
  explosion hurts everything within its radius that has a line to it, and carves too much for
  cover to help: the only shelter is distance) and looks at the plug again, up to the bomb's uses.

Every number about a spell is read from `content/spells.json`; a field the content does not have
(yet) counts as zero.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from noitabench.game import Game

from .seal import Driver, SealGeometry, fire_at_plug
from .spellinfo import explosion_options, load_spells

SAFETY = 16  # cells beyond the blast radius the thrower keeps (the hit box is 16 tall)
FUSE_SLACK = 20  # frames of the fuse that must be left over when the thrower has run
THROW_ANGLE = 45.0  # degrees below the horizontal: the bomb lands a few cells ahead
THROW_WAIT = 300  # frames to wait for the wand to be ready and have the mana
AFTER_BLAST = 70  # frames to stay away after a blast, at least
FIRE_WAIT = 420  # ... and at most, while fire is still burning around the crater
MAX_BLASTS = 5


@dataclass(frozen=True)
class Loadout:
    """Spells that together break brick, in the order they go into the wand."""

    spells: tuple[str, ...]  # the modifier (if any) first, the projectile last
    durability: int  # the hardest durability the blast removes
    radius: int  # the blast's radius
    mana: float  # what one cast costs
    fuse: int  # frames from the throw to the blast
    uses: int  # casts the spells have
    thrown: bool  # the projectile is a bomb to throw (else a bolt to fire at the plug)


def plan_loadout(
    held: Iterable[str],
    brick: int,
    *,
    slots: int | None = None,
    mana_max: float | None = None,
    path: Path | None = None,
) -> Loadout | None:
    """The cheapest arrangement of the spells in `held` whose explosion removes durability
    `brick`, if one fits in `slots` and costs no more than `mana_max`; None if there is none."""
    infos = load_spells(path)
    best: Loadout | None = None
    for spells, durability, radius in explosion_options(held, infos):
        if durability < brick or (slots is not None and len(spells) > slots):
            continue
        mana = sum(infos[k].mana for k in spells)
        if mana_max is not None and mana > mana_max:
            continue
        limits = [u for k in spells if (u := infos[k].max_uses) is not None]
        projectile = infos[spells[-1]]
        candidate = Loadout(
            spells,
            durability,
            radius,
            mana,
            projectile.fuse,
            min([*limits, MAX_BLASTS]),
            projectile.body == "thrown_body",
        )
        if best is None or (candidate.mana, candidate.spells) < (best.mana, best.spells):
            best = candidate
    return best


# -- the wand ---------------------------------------------------------------------------------


def _player(game: Game) -> dict[str, Any]:
    p = game.player()
    if p is None:
        raise RuntimeError("the game has no player")
    return p


def _slots(player: dict[str, Any], wand: int) -> list[str | None]:
    return [s["spell"] if s else None for s in player["wands"][wand]["slots"]]


def choose_wand(player: dict[str, Any], n: int) -> int | None:
    """The wand with room for `n` more spells: the one with the most free slots (the starter's
    spark wand, with two free, before the digger's), the first on a tie."""
    free = [(sum(s is None for s in _slots(player, i)), -i, i) for i in range(len(player["wands"]))]
    fits = [f for f in free if f[0] >= n]
    return max(fits)[2] if fits else None


@dataclass(frozen=True)
class Assembled:
    """A wand with the loadout at the front, and what its slots held before."""

    wand: int
    before: tuple[str | None, ...]


def assemble(game: Game, loadout: Loadout) -> Assembled | None:
    """Put the loadout at the front of a wand; None if no wand has room or a spell of the
    loadout is neither carried nor in that wand. The spells already in the wand follow it."""
    p = _player(game)
    wand = choose_wand(p, len(loadout.spells))
    if wand is None:
        return None
    before = tuple(_slots(p, wand))
    carried = [s["spell"] for s in p["spells"]]
    if any(k not in carried and k not in before for k in loadout.spells):
        return None
    for spell in loadout.spells:
        p = _player(game)
        if spell in _slots(p, wand):
            continue
        carried = [s["spell"] for s in p["spells"]]
        slot = _slots(p, wand).index(None)
        game.edit_wand({"op": "place", "wand": wand, "slot": slot, "from": carried.index(spell)})
    for i, spell in enumerate(loadout.spells):  # modifiers first, the projectile after them
        slots = _slots(_player(game), wand)
        j = slots.index(spell, i)
        if j != i:
            game.edit_wand({"op": "swap", "wand": wand, "a": i, "b": j})
    return Assembled(wand, before)


def stow(game: Game, loadout: Loadout, assembled: Assembled) -> None:
    """Take the loadout out of the wand again and put the spells that were there back in their
    places, so that the wand casts what it did before."""
    wand = assembled.wand
    for spell in loadout.spells:
        slots = _slots(_player(game), wand)
        if spell in slots and spell not in assembled.before:
            game.edit_wand({"op": "take", "wand": wand, "slot": slots.index(spell)})
    for i, spell in enumerate(assembled.before):
        slots = _slots(_player(game), wand)
        if spell is not None and slots[i] != spell:
            game.edit_wand({"op": "swap", "wand": wand, "a": i, "b": slots.index(spell)})


# -- the throw --------------------------------------------------------------------------------


class BlastDriver(Driver, Protocol):
    """What the bomb needs from the bot that throws it."""

    def front_goal(self) -> tuple[int, int]:
        """The box position standing on the plug."""

    def walk_to(
        self,
        label: str,
        goal: tuple[int, int],
        *,
        tolerance: int = 2,
        max_frames: int = ...,
        stop: Callable[[], bool] | None = None,
        arrive: bool = True,
    ) -> bool: ...

    def escape_goal(
        self, center: tuple[float, float], distance: float, budget: int
    ) -> tuple[int, int] | None:
        """A place at least `distance` cells from `center` that the bot reaches in `budget`
        frames, or None."""


def _bombs(game: Game) -> dict[int, dict[str, Any]]:
    return {e["id"]: e for e in game.entities() if e["kind"] == "bomb"}


def throw_bomb(driver: BlastDriver, wand: int, angle: float) -> int | None:
    """Hold the cast key until the wand fires; the id of the bomb that appeared, else None."""
    game = driver.game
    before = set(_bombs(game))
    for _ in range(THROW_WAIT):
        p = game.player()
        if p is None or p["dead"]:
            return None
        driver.step({"select_wand": wand, "aim": angle, "fire": True})
        fresh = set(_bombs(game)) - before
        if fresh:
            return min(fresh)
    return None


def _centre(e: dict[str, Any]) -> tuple[float, float]:
    return e["x"] + e["w"] / 2, e["y"] + e["h"] / 2


def throw_from_plug(
    driver: BlastDriver, loadout: Loadout, escape: tuple[int, int], plug_cx: int
) -> int | None:
    """Put the loadout in a wand, throw the bomb (away from the way out) and take the spells out
    again at once: the bomb flies on without the wand, and a digging bolt fired by the pilot
    from this wand later would cast the bomb again. The bomb's id, or None."""
    game = driver.game
    assembled = assemble(game, loadout)
    if assembled is None:
        driver.note("breaker_no_wand", spells=list(loadout.spells))
        return None
    driver.note(
        "breaker_assembled",
        spells=list(loadout.spells),
        wand=assembled.wand,
        durability=loadout.durability,
        radius=loadout.radius,
    )
    side = 1 if escape[0] >= plug_cx - 2 else -1
    angle = -(180.0 - THROW_ANGLE) if side > 0 else -THROW_ANGLE
    try:
        bomb = throw_bomb(driver, assembled.wand, angle)
    finally:
        if not _player(game)["dead"]:
            stow(game, loadout, assembled)
    if bomb is None:
        driver.note("blast_not_thrown", wand=assembled.wand)
    return bomb


def keep_clear(
    driver: BlastDriver, loadout: Loadout, bomb: int, escape: tuple[int, int], attempt: int
) -> bool:
    """Run to `escape` and hold it until the bomb has gone off (`walk_to` with `arrive` off keeps
    the pilot on the spot, and brings it back if it is pushed off or falls), note how far from
    the bomb that left the bot, and wait for the fires to die. False if the bot died."""
    game = driver.game
    thrown = game.frame
    last = {"at": (0.0, 0.0)}

    def gone() -> bool:
        found = _bombs(game).get(bomb)
        if found is not None:
            last["at"] = _centre(found)
        return found is None

    driver.walk_to(
        "flee", escape, tolerance=3, max_frames=loadout.fuse + 60, stop=gone, arrive=False
    )
    p = _player(game)
    cx, cy = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
    driver.note(
        "blast",
        attempt=attempt,
        frames=game.frame - thrown,
        distance=round(((cx - last["at"][0]) ** 2 + (cy - last["at"][1]) ** 2) ** 0.5, 1),
        hp=round(float(p["hp"]), 1),
    )
    waited = 0
    fire = game.material_keys().index("fire")
    cx0, cy0 = int(last["at"][0]), int(last["at"][1])
    window = (
        slice(max(0, cy0 - loadout.radius), cy0 + loadout.radius),
        slice(max(0, cx0 - loadout.radius), cx0 + loadout.radius),
    )

    def settled() -> bool:
        """The minimum wait is over and (looked at every ten frames) no fire burns in the crater."""
        nonlocal waited
        waited += 1
        if waited < AFTER_BLAST or waited % 10:
            return False
        return waited >= FIRE_WAIT or not np.count_nonzero(game.grid_array()[window] == fire)

    driver.walk_to(
        "after_blast", escape, tolerance=3, max_frames=FIRE_WAIT + 10, stop=settled, arrive=False
    )
    return not _player(game)["dead"]


def blast_once(driver: BlastDriver, loadout: Loadout, geometry: SealGeometry, attempt: int) -> bool:
    """Throw one bomb onto the plug and keep clear of it. False if it could not be done."""
    plug = geometry.plug
    if not driver.walk_to(f"blast_{attempt}", driver.front_goal()):
        return False
    away = loadout.radius + SAFETY
    escape = driver.escape_goal((float(plug.cx), float(plug.y)), away, loadout.fuse - FUSE_SLACK)
    if escape is None:
        driver.note("blast_no_safe_place", away=away, fuse=loadout.fuse)
        return False
    bomb = throw_from_plug(driver, loadout, escape, plug.cx)
    if bomb is None:
        return False
    driver.note(
        "blast_thrown",
        attempt=attempt,
        escape=escape,
        away=away,
        fuse=loadout.fuse,
        hp=round(float(_player(driver.game)["hp"]), 1),
    )
    return keep_clear(driver, loadout, bomb, escape, attempt)


def break_with_loadout(driver: BlastDriver, loadout: Loadout, geometry: SealGeometry) -> bool:
    """Blast the plug with the loadout until it is open or the casts run out; True if open.
    The spells are in a wand only for the moment of each throw."""
    if not loadout.thrown:  # a bolt: fired at the plug from where the bot stands
        assembled = assemble(driver.game, loadout)
        if assembled is None:
            driver.note("breaker_no_wand", spells=list(loadout.spells))
            return False
        try:
            return driver.walk_to("to_seal", driver.front_goal()) and fire_at_plug(
                driver, assembled.wand, geometry
            )
        finally:
            stow(driver.game, loadout, assembled)
    for attempt in range(loadout.uses):
        if driver.seal_open():
            break
        if not blast_once(driver, loadout, geometry, attempt):
            break
    return driver.seal_open()
