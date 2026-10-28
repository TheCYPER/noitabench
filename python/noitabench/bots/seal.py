"""The sealed bottom: finding what breaks the seal, using it, and the fallback when there is none.

The deepest room is closed by a plug of brick that the starting wands cannot dig (brick
durability 14, the digging bolt breaks up to 10). The world is meant to hold something found
earlier that does break it. This module is the one place that knows about that:

* `find_seal_keys(markers, entities)` looks for the item markers that say they are keys of the
  seal: an `item` marker with `"role": "breaker"` (what the encounter content hands out: the
  BOMB spell of E02 and the EXPLOSIVE_PROJECTILE spell of E12, `E06.json` `requires.supply`),
  or `"role": "seal_key"`, `"key_for": "seal"` or `"seal_key": true`. There may be several; the
  item to fetch for each is the spawned entity of the marker's kind (and `spell` or `contents`)
  that lies nearest to it. Spells work together: the bomb's explosion removes durability 11 and
  the modifier adds 3 (`breaker.py` plans the wand and throws the bomb).
* `use_key(driver, key, geometry)` equips a wand or bottle key and fires or throws it at the
  plug; a spell key goes through `breaker.py` instead.
* The fallback, when there is no usable key item, has two steps. First `breaker_spell` looks in
  the content for a single spell whose explosion removes brick; if there is one,
  `hand_over_breaker` gives it to the player (`Game.give_spell`) and uses it on the plug through
  the controls. There is none today, so `blast_open` does what is left: it carves the plug with
  `Game.blast`, an explosion strong enough for brick. Both log `seal_fallback`.

All of it goes through a `Driver`, so frames are counted, recorded and logged in one place.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from noitabench.game import Controls, Game, aim_at

from .spellinfo import best_reach
from .terrain import CONTENT, POWDER, STATIC, Body, Materials
from .wands import wand_with

KEY_FLAGS: tuple[tuple[str, Any], ...] = (
    ("role", "breaker"),
    ("role", "seal_key"),
    ("key_for", "seal"),
    ("seal_key", True),
)
KEY_KINDS = ("spell", "wand", "bottle")
USE_FRAMES = 260  # how long a found key gets to open the plug before the fallback takes over
FIRE_EVERY = 100  # frames between casts: a bomb's fuse is long and its blast hurts the caster
BLAST_STEP = 8  # cells deeper for each further fallback blast
MAX_BLASTS = 8
EXTRA_CELLS = 10  # ray length beyond the plug's thickness


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def bottom(self) -> int:
        return self.y + self.h


@dataclass(frozen=True)
class SealGeometry:
    """Where the seal is: the brick plug between the front pocket and the sealed room."""

    plug: Rect
    room: Rect

    @classmethod
    def read(cls, grid: np.ndarray, mats: Materials, marker: dict[str, Any]) -> SealGeometry:
        """The plug is the brick inside the marker's columns, from just above the marker down to
        the room."""
        room = Rect(**{k: int(marker["room"][k]) for k in ("x", "y", "w", "h")})
        x0, x1 = int(marker["x"]), int(marker["x"]) + int(marker["w"])
        top = int(marker["y"]) - 4
        brick = mats.index("brick")
        band = grid[top : room.y, x0:x1] == brick
        rows = np.nonzero(band.any(axis=1))[0]
        if len(rows) == 0:
            raise ValueError("the seal marker has no brick under it")
        y0, y1 = top + int(rows[0]), top + int(rows[-1]) + 1
        return cls(plug=Rect(x0, y0, x1 - x0, y1 - y0), room=room)

    def is_open(self, grid: np.ndarray, mats: Materials, body_w: int) -> bool:
        """A channel as wide as the player runs through the whole plug."""
        p = self.plug
        cols = grid[p.y : p.bottom, p.x : p.x + p.w]
        kind = mats.kind[cols]
        free = ~((kind == STATIC) | (kind == POWDER)).any(axis=0)  # per column
        run = 0
        for ok in free:
            run = run + 1 if ok else 0
            if run >= body_w:
                return True
        return False


@dataclass(frozen=True)
class SealKey:
    """An item of the world that opens the seal."""

    marker: dict[str, Any]
    entity: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.entity["kind"])

    @property
    def detail(self) -> str:
        return str(self.entity.get("detail") or "")

    @property
    def center(self) -> tuple[float, float]:
        e = self.entity
        return e["x"] + e["w"] / 2, e["y"] + e["h"] / 2

    def can_open(
        self, mats: Materials, spells_path: Path | None = None, held: Iterable[str] = ()
    ) -> bool:
        """Whether this key reaches the brick, together with the spells in `held`: the explosion
        of a projectile, plus the largest bonus of a modifier among them, has to beat the
        brick's durability. Wands and bottles are tried: what they hold is not known from
        outside."""
        if self.kind != "spell":
            return True
        reach = best_reach([self.detail, *held], spells_path)
        return reach is not None and reach >= int(mats.durability[mats.index("brick")])


def explosion_durability(spell: str, path: Path | None = None) -> int | None:
    """The hardest durability the explosion of `spell` removes (`content/spells.json`)."""
    data = json.loads((path or CONTENT / "spells.json").read_text(encoding="utf-8"))
    for s in data["spells"]:
        if s["key"] == spell:
            explosion = (s.get("projectile") or {}).get("explosion")
            return None if explosion is None else int(explosion["max_durability"])
    return None


def is_key_marker(marker: dict[str, Any]) -> bool:
    return marker.get("type") == "item" and any(marker.get(k) == v for k, v in KEY_FLAGS)


def is_item_of_marker(marker: dict[str, Any], entity: dict[str, Any]) -> bool:
    """Whether a spawned entity is the item `marker` asked for: the same kind (spell, wand,
    bottle) and, where the marker names one, the same spell or bottle content."""
    wanted = marker.get("item")
    if entity["kind"] not in KEY_KINDS or (wanted is not None and entity["kind"] != wanted):
        return False
    named = {"spell": marker.get("spell"), "bottle": marker.get("contents")}.get(wanted)
    return named is None or entity.get("detail") == named


def find_seal_keys(markers: list[dict[str, Any]], entities: list[dict[str, Any]]) -> list[SealKey]:
    """Every key item of this world (none if the generator placed none), in marker order.

    The entity is the one of the marker's kind (and spell or content) nearest to the marker:
    items settle a few cells off their marker, and other items lie close by in an encounter.
    One entity serves one marker.
    """
    keys: list[SealKey] = []
    taken: set[int] = set()
    for m in markers:
        if not is_key_marker(m):
            continue
        entity = nearest_item(m, entities, taken)
        if entity is not None:
            taken.add(int(entity.get("id", -1)))
            keys.append(SealKey(marker=m, entity=entity))
    return keys


def find_seal_key(markers: list[dict[str, Any]], entities: list[dict[str, Any]]) -> SealKey | None:
    """The first key item of this world, or None (see `find_seal_keys`)."""
    keys = find_seal_keys(markers, entities)
    return keys[0] if keys else None


def nearest_item(
    marker: dict[str, Any], entities: list[dict[str, Any]], taken: set[int] | None = None
) -> dict[str, Any] | None:
    """The spawned entity of the kind (and spell or contents) of an item marker that lies
    nearest to it, within the distance items settle at; entities in `taken` are skipped."""
    near = [
        e
        for e in entities
        if is_item_of_marker(marker, e)
        and abs(e["x"] - marker["x"]) <= 40
        and abs(e["y"] - marker["y"]) <= 40
        and int(e.get("id", -1)) not in (taken or set())
    ]
    if not near:
        return None
    return min(near, key=lambda e: (e["x"] - marker["x"]) ** 2 + (e["y"] - marker["y"]) ** 2)


class Driver(Protocol):
    """What the seal code needs from the bot that runs it."""

    game: Game
    body: Body

    def step(self, controls: Controls) -> dict[str, Any]:
        """Advance one frame (recorded, counted) and return the player."""

    def seal_open(self) -> bool: ...

    def note(self, event: str, **fields: Any) -> None: ...


# -- using a key -------------------------------------------------------------------------------


def _player(game: Game) -> dict[str, Any]:
    p = game.player()
    if p is None:
        raise RuntimeError("the game has no player")
    return p


def _equip(game: Game, key: SealKey) -> tuple[int, bool]:
    """Make the picked-up item the thing the player holds; `(wand index, throw_it)`."""
    p = _player(game)
    if key.kind == "wand":
        return len(p["wands"]) - 1, False
    if key.kind == "spell":
        return equip_spell(game, key.detail), False
    return 0, True  # a bottle is thrown


def equip_spell(game: Game, spell: str) -> int:
    """Put a carried spell first in a wand that has a free slot, without taking anything out of
    the wands (the digging bolt stays where it is). Returns the wand's index: the one the spell
    sits in already if it is not carried, wand 0 if there is nowhere to put it."""
    p = _player(game)
    carried = [s["spell"] for s in p["spells"]]
    free = [
        (i, next(k for k, slot in enumerate(w["slots"]) if slot is None))
        for i, w in enumerate(p["wands"])
        if any(slot is None for slot in w["slots"])
    ]
    if spell not in carried:
        return wand_with(p, spell, 0)
    if not free:
        return 0
    wand, slot = max(free, key=lambda f: len(p["wands"][f[0]]["slots"]))
    game.edit_wand({"op": "place", "wand": wand, "slot": slot, "from": carried.index(spell)})
    if slot != 0:  # first in the deck, so that the next click casts it
        game.edit_wand({"op": "swap", "wand": wand, "a": 0, "b": slot})
    return wand


def fire_at_plug(driver: Driver, wand: int, geometry: SealGeometry, *, throw: bool = False) -> bool:
    """Cast the wand (or throw the bottle) at the plug for a while; True if the plug opened."""
    game, plug = driver.game, geometry.plug
    for frame in range(USE_FRAMES):
        p = game.player()
        if p is None or p["dead"]:
            return False
        hand = (p["x"] + driver.body.hand_dx + 0.5, p["y"] + driver.body.hand_dy + 0.5)
        controls: Controls = {"aim": aim_at(hand, (plug.cx, plug.y + 2)), "select_wand": wand}
        if throw:
            controls["select_bottle"] = max(0, len(p["bottles"]) - 1)
            controls["throw"] = frame % FIRE_EVERY == 0
        else:
            controls["fire"] = frame % FIRE_EVERY < 2
        driver.step(controls)
        if driver.seal_open():
            return True
    return False


def use_key(driver: Driver, key: SealKey, geometry: SealGeometry) -> bool:
    """Fire or throw what was found at the plug; True if the plug opened."""
    wand, throw = _equip(driver.game, key)
    holds = key.kind != "spell" or wand_with(_player(driver.game), key.detail, -1) == wand
    driver.note("seal_key_equipped", item=key.kind, detail=key.detail, wand=wand, holds=holds)
    return fire_at_plug(driver, wand, geometry, throw=throw)


def breaker_spell(mats: Materials, spells_path: Path | None = None) -> str | None:
    """The spell of the content with the weakest explosion that still removes brick, if any."""
    brick = int(mats.durability[mats.index("brick")])
    data = json.loads((spells_path or CONTENT / "spells.json").read_text(encoding="utf-8"))
    best: tuple[int, str] | None = None
    for s in data["spells"]:
        explosion = (s.get("projectile") or {}).get("explosion")
        if explosion and int(explosion["max_durability"]) >= brick:
            candidate = (int(explosion["max_durability"]), str(s["key"]))
            best = candidate if best is None else min(best, candidate)
    return None if best is None else best[1]


def hand_over_breaker(driver: Driver, spell: str, geometry: SealGeometry) -> bool:
    """The fallback of the plan: hand the player the spell the world should have provided
    (`Game.give_spell`) and use it on the plug through the controls. True if the plug opened."""
    driver.game.give_spell(spell)
    wand = equip_spell(driver.game, spell)
    driver.note(
        "seal_fallback", tool=f"Game.give_spell({spell})", reason="no seal-breaking item", wand=wand
    )
    return fire_at_plug(driver, wand, geometry)


# -- the fallback -------------------------------------------------------------------------------


def blast_open(
    driver: Driver, geometry: SealGeometry, mats: Materials, reason: str = "no seal-breaking item"
) -> int:
    """Carve the plug with explosions the sim's test API provides. Returns the blasts used.

    Each blast is a ray explosion that beats brick (`max_durability` = brick's durability) with
    enough energy for the plug's thickness, centred a few cells deeper than the last, until a
    channel runs through.
    """
    game, plug = driver.game, geometry.plug
    brick = mats.index("brick")
    durability = int(mats.durability[brick])
    energy = int(mats.hp[brick] * (plug.h + EXTRA_CELLS))
    radius = plug.w // 2 + 2
    driver.note(
        "seal_fallback",
        tool="Game.blast",
        reason=reason,
        max_durability=durability,
        ray_energy=energy,
        radius=radius,
    )
    for n in range(MAX_BLASTS):
        if driver.seal_open():
            return n
        game.blast(plug.cx, plug.y + 4 + n * BLAST_STEP, radius, 0.0, energy, durability, 0)
        for _ in range(4):
            driver.step({"aim": -90.0})
    return MAX_BLASTS
