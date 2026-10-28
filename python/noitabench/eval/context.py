"""The visits of a run and the questions an encounter rule asks about one.

A *visit* is one engagement with one placed encounter: the stays of the player's hit box in the
scene's trigger, from the first time it touched the trigger to the last (stays less than
`MERGE_GAP` frames apart are one stay). The rule of the encounter is run on the whole visit.

Health lost and the events a rule counts by default are those of the stays (each plus `TAIL`
frames): a player who left the scene for a long time and came back is not charged for what
happened in between, somewhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .geometry import Rect
from .recording import Command, Item, Life, RunData, as_float, as_int
from .worldinfo import Scene

TAIL = 60  # frames after the last touch that still belong to a visit (landing, last events)
LIQUID_KINDS = ("pour", "throw", "drink", "fill")
FILL_CELLS = 20  # cells of a `fill` that count as having the liquid in a bottle


@dataclass(frozen=True)
class Visit:
    scene: Scene
    segments: tuple[tuple[int, int], ...]

    @property
    def enter(self) -> int:
        return self.segments[0][0]

    @property
    def exit(self) -> int:
        return self.segments[-1][1]


@dataclass(frozen=True)
class Use:
    """A liquid put to use: poured, thrown, drunk or filled; where it was, if known."""

    frame: int
    kind: str
    material: str
    cells: int
    x: float
    y: float


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Overlapping or touching `(lo, hi)` spans joined, in order."""
    out: list[tuple[int, int]] = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def liquid_in_hand(run: RunData, liquid: str, before: int) -> int | None:
    """The frame at which a bottle of `liquid` came into the hand (a bottle of it picked up, or a
    `fill` of at least `FILL_CELLS` cells) if it was still there at `before`, else None.

    A throw of the liquid lets it go; pours and drinks that emptied the bottle, and drops (the
    `drop` event does not say which bottle), are not followed."""
    got = None
    for e in run.events.between(0, before - 1, "pickup", "fill", "throw"):
        kind = e["type"]
        if (e.get("detail") if kind == "pickup" else e.get("material")) != liquid:
            continue
        filled = kind == "fill" and as_int(e.get("cells")) >= FILL_CELLS
        if kind == "throw":
            got = None
        elif filled or (kind == "pickup" and e.get("item") == "bottle"):
            got = e["frame"]
    return got


def find_visits(run: RunData) -> list[Visit]:
    """Every placed encounter whose trigger the player touched, in order of first touch."""
    visits: list[Visit] = []
    for scene in run.world.scenes:
        stays = run.track.stays(scene.trigger)
        if stays:
            visits.append(Visit(scene, tuple(stays)))
    return sorted(visits, key=lambda v: (v.enter, v.scene.key))


class Ctx:
    """Questions about one visit; the encounter rules are written against this."""

    def __init__(self, run: RunData, visit: Visit) -> None:
        self.run = run
        self.visit = visit
        self.scene = visit.scene
        self.enter = visit.enter
        self.exit = visit.exit
        self.end = min(run.last_frame, visit.exit + TAIL)
        self.windows = _merge([(lo, min(run.last_frame, hi + TAIL)) for lo, hi in visit.segments])

    def in_visit(self, frame: int) -> bool:
        """True if `frame` falls in one of the stays (or the `TAIL` after it)."""
        return any(lo <= frame <= hi for lo, hi in self.windows)

    # -- geometry ----------------------------------------------------------------------------
    def region(self, name: str) -> Rect:
        return self.scene.region(name)

    def reached(self, region: Rect, f0: int | None = None, f1: int | None = None) -> bool:
        return self.first_reach(region, f0, f1) is not None

    def first_reach(self, region: Rect, f0: int | None = None, f1: int | None = None) -> int | None:
        """The first frame in the window at which the hit box touched `region`."""
        lo = self.enter if f0 is None else f0
        hi = self.end if f1 is None else f1
        return self.run.track.first_touch(region, lo, hi)

    def passed_below(self, margin: int = 24) -> bool:
        """True if the player got out through the bottom of the scene: its hit box was at the
        footprint's bottom edge or below it (within `margin` cells of the footprint's sides)
        while the visit lasted or just after it. Being there at some other time, deeper down in
        the same column, is not passing this scene."""
        fp = self.scene.footprint
        for s in self.run.track.between(self.enter, self.end):
            if s.y >= fp.bottom - 2 and fp.x - margin <= s.x <= fp.right + margin:
                return True
        return False

    # -- events ------------------------------------------------------------------------------
    def events(
        self, *types: str, f0: int | None = None, f1: int | None = None
    ) -> list[dict[str, Any]]:
        """Events of the given types in the window: by default those of the stays, else those
        between `f0` and `f1`."""
        lo = self.enter if f0 is None else f0
        hi = self.end if f1 is None else f1
        found = self.run.events.between(lo, hi, *types)
        if f0 is None and f1 is None:
            return [e for e in found if self.in_visit(e["frame"])]
        return found

    def hp_lost(self, *sources: str, f0: int | None = None, f1: int | None = None) -> float:
        """HP (displayed) the player lost, from `damage` events: during the stays by default,
        else between `f0` and `f1`."""
        lo = self.enter if f0 is None else f0
        hi = self.end if f1 is None else f1
        hurt = self.run.events.player_damage(lo, hi, *sources)
        if f0 is None and f1 is None:
            hurt = [e for e in hurt if self.in_visit(e["frame"])]
        return float(sum(as_float(e.get("amount")) for e in hurt))

    def died(self) -> bool:
        return any(e.get("target") == "player" for e in self.events("death"))

    def hp_max(self) -> float:
        sample = self.run.track.at(self.enter)
        return sample.hp_max if sample else 100.0

    def explosions_in(
        self, region: Rect, *, min_radius: int = 0, f0: int | None = None, f1: int | None = None
    ) -> list[dict[str, Any]]:
        """`explosion` events centred in `region` (digging bolts are explosions of radius 6)."""
        return [
            e
            for e in self.events("explosion", f0=f0, f1=f1)
            if region.has_point(e["x"], e["y"]) and e.get("radius", 0) >= min_radius
        ]

    def reactions_in(
        self, region: Rect, rows: frozenset[str], f0: int | None = None, f1: int | None = None
    ) -> int:
        """How many `reaction` events of the given rows touched `region` (cell A or B in it)."""
        box = region.grow(1)
        return sum(
            1
            for e in self.events("reaction", f0=f0, f1=f1)
            if e.get("id") in rows
            and (box.has_point(e["x"], e["y"]) or box.has_point(e.get("bx", -1), e.get("by", -1)))
        )

    def liquid_uses(self, f0: int | None = None, f1: int | None = None) -> list[Use]:
        """Pours, throws, drinks and fills in the window with the place they happened.

        A pour, drink or fill happens where the player stood; a throw lands where the matching
        `shatter` event says (the next one of the same material within two seconds)."""
        lo = self.enter if f0 is None else f0
        hi = self.end if f1 is None else f1
        events = self.run.events.between(lo, hi + 120, *LIQUID_KINDS, "shatter")
        out: list[Use] = []
        for i, e in enumerate(events):
            kind = e["type"]
            if kind not in LIQUID_KINDS or e["frame"] > hi:
                continue
            if f0 is None and f1 is None and not self.in_visit(e["frame"]):
                continue
            x = y = None
            if kind == "throw":
                for later in events[i + 1 :]:
                    if later["type"] == "shatter" and later["frame"] <= e["frame"] + 120:
                        x, y = later["x"], later["y"]
                        break
            if x is None:
                me = self.run.track.at(e["frame"])
                x, y = (me.x + me.w / 2, me.y + me.h / 2) if me else (0.0, 0.0)
            out.append(
                Use(e["frame"], kind, str(e.get("material", "")), as_int(e.get("cells")), x, y)
            )
        return out

    def near(self, use: Use, region: Rect, margin: int = 24) -> bool:
        return region.grow(margin).has_point(use.x, use.y)

    # -- decisions ---------------------------------------------------------------------------
    def commands(self, *names: str, f0: int | None = None, f1: int | None = None) -> list[Command]:
        lo = self.enter if f0 is None else f0
        hi = self.end if f1 is None else f1
        return self.run.decisions.commands(lo, hi, *names)

    def inspected_near(self, region: Rect, before: int, margin: int = 12) -> bool | None:
        """Did the player `inspect` a cell near `region` (or a creature in it) before `before`?

        None if the run has no `decisions.jsonl` (the scripted bot): then it cannot be known."""
        if not self.run.decisions.present:
            return None
        box = region.grow(margin)
        for c in self.run.decisions.commands(0, before, "inspect"):
            if c.frame > before:
                continue
            x, y = c.args.get("x"), c.args.get("y")
            if isinstance(x, int) and isinstance(y, int) and box.has_point(x, y):
                return True
        return False

    def looked_at(
        self,
        before: int,
        *,
        cells: Rect | None = None,
        entities: frozenset[int] = frozenset(),
        carried: frozenset[int] = frozenset(),
        margin: int = 2,
    ) -> bool | None:
        """Did the player `inspect` one of these things in a decision asked before `before`?

        `cells`: a cell in the region (grown by `margin`); `entities`: one of these entity ids;
        `carried`: a carried bottle (`inspect(bottle=..)`) after one of these items was picked
        up (which bottle of the hand it was is not recorded). None without `decisions.jsonl`."""
        if not self.run.decisions.present:
            return None
        box = cells.grow(margin) if cells is not None else None
        taken = [e["frame"] for e in self.run.events.of_type("pickup") if e.get("id") in carried]
        for c in self.run.decisions.commands(0, before, "inspect"):
            if c.frame >= before:
                continue
            x, y = c.args.get("x"), c.args.get("y")
            on_cell = isinstance(x, int) and isinstance(y, int)
            if box is not None and on_cell and box.has_point(x, y):
                return True
            if c.args.get("entity") in entities:
                return True
            if c.args.get("bottle") is not None and any(t <= c.frame for t in taken):
                return True
        return False

    # -- the scene's own things ----------------------------------------------------------------
    def items_in(self, region: Rect, *kinds: str, margin: int = 4) -> list[Item]:
        """Items first seen in `region` (grown by `margin`): the scene's own bottles, barrels and
        rewards, told apart from others of the same kind by where they started."""
        box = region.grow(margin)
        return [
            i
            for i in self.run.items.values()
            if box.has_point(i.x, i.y) and (not kinds or i.kind in kinds)
        ]

    def creatures_in(self, region: Rect, *kinds: str, margin: int = 8) -> list[Life]:
        """Creatures first seen in `region` (grown by `margin`): the scene's own guards."""
        box = region.grow(margin)
        return [
            life
            for life in self.run.lives.values()
            if box.has_point(life.first_x, life.first_y) and (not kinds or life.kind in kinds)
        ]

    def picked_up(
        self, item: str | None = None, detail: str | None = None, **window: int | None
    ) -> list[dict[str, Any]]:
        """`pickup` events in the window, filtered by item kind and detail."""
        return [
            e
            for e in self.events("pickup", **window)
            if (item is None or e.get("item") == item)
            and (detail is None or e.get("detail") == detail)
        ]
