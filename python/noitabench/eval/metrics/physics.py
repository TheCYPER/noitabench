"""N4 first_contact_physics: the first meeting with each harmful material or physical situation
(capability graph section 4, "第一次遇到某种通用物理情况时的处理是否合理").

One opportunity per kind met, judged on that first meeting only (meeting it again is N1's
`repeat_harm`), and only where the meeting put a question: an opportunity that anyone passes
measures nothing, yet raises the capability through its discount (n / (n + 2)).

lava, acid, toxic  the first meeting of that kind (`meetings.py`: a cell of it within `REACH`
                   cells of the hit box, no brick or metal between), or the first contact if that
                   comes first. It was touched if, while it lasted, the hit box held the kind (at
                   least `contact.min_cells` cells at a sample), a contact episode of the kind
                   came (contact damage named by the hazard under the hit box as in
                   `harm.hazard_kind`, or by the poisoning in force; lava damage with no burning
                   at hand is poison taken beside lava), or it began a burning (lava ignites the
                   player) or a poisoning (toxic; one a drink began is not a contact). Never
                   touched is 1.0, and so is a graze (under `GRAZE_HP`, no status begun).
                   Touched is at most `TOUCH_BEST`: TOUCH_BEST x (1 - HP / `BAD`), the HP being
                   the slow damage from the touch (both labels: the engine sums contact and fire
                   damage into one event named after whichever came last) until the meeting and
                   the burning or poisoning it began are over; died in it is 0. Needs the
                   recorded grid; kinds not met before a cut scan (`MAX_MEET_CHECKS`) are not
                   known.
fire               the first burning that neither lava (in reach when it began, or a lava contact
                   then; judged with the lava) nor a drink started: put out before 80 % of its
                   natural length (only water, or the fireproof potion, ends burning early) is
                   1.0; died burning is 0; burned to the end is 0 if water was at hand (on the
                   recorded grid within `WATER_REACH` cells of the hit box when it caught fire, or
                   a bottle of water in hand) and no opportunity otherwise (waiting was all one
                   could do). Left out if the run ended while it burned.
deep water         the first dive that used at least half the breath (`player.air_frames` of
                   `content/entities.json`): the head cell (top centre of the hit box) under a
                   liquid that cannot be breathed (any liquid but the potions, lava and acid,
                   which are judged above), looked for on the recorded grid while the player was
                   wet, oiled or poisoned (the statuses of liquids; a dive into blood or slime,
                   which give none, is not found). Breath is reckoned from the samples: it drains
                   one a frame under and refills `BREATH_REFILL` a frame above. No drowning in
                   that dive is 1.0, `DROWN_BAD` HP lost to drowning or more is 0; 0 if the
                   player drowned. Shorter dips put no question and are not counted. Needs the
                   grid.

Not measured (`fire_and_buoyancy` in `unmeasured.py`): keeping out of the way of rising fire and
using what floats (frames.bin v0 holds no burning state and buoyancy is no harm); gases do no harm
of their own here (steam is harmless, flammable gas hurts only as fire).
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from ..context import liquid_in_hand
from ..encounters import Result
from ..recording import RunData, as_float, as_int
from ..rubric import linear
from ..worldinfo import CONTENT, breathless_liquids, drink_effects, material_keys
from . import Metric, metric_group
from .harm import EPISODE_GAP, hazard_kind
from .meetings import Meeting, Scan, kinds_at

KINDS = {"lava": "lava", "acid": "acid", "toxic_sludge": "toxic", "poison": "toxic"}
BAD = {"lava": 50.0, "acid": 50.0, "toxic": 40.0}  # HP of a first contact that scores 0
TOUCH_BEST = 0.5  # what a touched first meeting scores at best (an avoided one is 1.0)
GRAZE_HP = 2.0  # HP under which a touch that began no burning or poisoning is a graze
TOUCH_STATUS = {"lava": "on_fire", "toxic": "poisoned"}  # what a touch of the kind begins
PUT_OUT = 0.8  # burning that ends before this share of its natural length was put out
WATER_REACH = 64  # cells: water this close to the hit box when it caught fire was at hand
FIRE_LINK = 12  # frames: a burning that starts this close to lava damage is the lava's
DRINK_WINDOW = 300  # frames: a `drink` event (written when the drink ends) this soon after a
#                     status began means the drink began it (a decision lasts at most 300)
SLOW_FLUSH = 30  # frames: slow damage (fire, contact) is summed into one event per 30 frames
RISKY_BREATH = 0.5  # share of the breath a dive must use to put the question
BREATH_REFILL = 3  # breath regained per frame with the head out (crates/game game/vitals.rs)
DROWN_BAD = 30.0  # HP lost to drowning in the dive that scores 0
LIQUID_STATUSES = ("wet", "oiled", "poisoned")
STATUSES = (*LIQUID_STATUSES, "on_fire", "fireproof")
MAX_GRID_CHECKS = 1500  # recorded grids looked at for the dives; beyond it: not measured
JUDGED_ELSEWHERE = ("lava", "acid")  # liquids whose contact is judged as their own kind

Span = tuple[int, int]  # (start, end) frames of a status; end = the run's end if it never ended


@cache
def _entities() -> dict[str, Any]:
    return json.loads((CONTENT / "entities.json").read_text(encoding="utf-8"))


def _fire_frames() -> tuple[int, int]:
    """(frames of burning, multiplier when oiled) from `content/entities.json`."""
    fire = _entities()["statuses"]["on_fire"]
    return int(fire["frames"]), int(fire.get("oiled_frames_mul", 1))


def _wetting() -> list[str]:
    """The materials whose contact makes the player wet (and so puts fire out)."""
    return sorted(m for m, s in _entities()["contact"]["status"].items() if s == "wet")


class _Body:
    """The player's statuses over the run, as spans, and the drinks that began some of them."""

    def __init__(self, run: RunData) -> None:
        self.run = run
        self.spans: dict[str, list[Span]] = {n: [] for n in STATUSES}
        opened: dict[str, int] = {}
        for e in run.events.of_type("status"):
            name = str(e.get("status"))
            if e.get("target") != "player" or name not in self.spans:
                continue
            if e.get("active"):
                opened.setdefault(name, e["frame"])
            elif name in opened:
                self.spans[name].append((opened.pop(name), e["frame"]))
        for name, start in opened.items():
            self.spans[name].append((start, run.last_frame))
        self.unended = frozenset(opened.items())  # (name, start) of the spans still open
        for spans in self.spans.values():
            spans.sort()

    def has(self, name: str, frame: int) -> bool:
        return any(lo <= frame <= hi for lo, hi in self.spans[name])

    def began_by_drink(self, start: int, effect: str) -> bool:
        """True if a drink with this effect (`drink_effect` of materials.json) began at `start`."""
        effects = drink_effects()
        return any(
            effects.get(str(e.get("material")), "none") == effect
            for e in self.run.events.between(start, start + DRINK_WINDOW, "drink")
        )

    def poisoning_drunk(self, frame: int) -> bool:
        """True if the poisoning in force at `frame` was begun by a drink."""
        begun = [lo for lo, hi in self.spans["poisoned"] if lo <= frame <= hi]
        return bool(begun) and self.began_by_drink(begun[-1], "poisoned")

    def begun(self, name: str, lo: int, hi: int) -> Span | None:
        """The first span of status `name` that began in `[lo, hi]`, unless a drink began it."""
        effect = {"on_fire": "burn", "poisoned": "poisoned"}.get(name, "")
        for start, end in self.spans[name]:
            if lo <= start <= hi and not self.began_by_drink(start, effect):
                return start, end
        return None

    def lava_burning(self, frame: int) -> Span | None:
        """The burning in force or started around lava damage logged at `frame` (it is logged up
        to `SLOW_FLUSH` frames after the touch)."""
        for lo, hi in self.spans["on_fire"]:
            if lo - FIRE_LINK <= frame and frame - SLOW_FLUSH - FIRE_LINK <= hi:
                return lo, hi
        return None


def _contact_kind(body: _Body, event: dict[str, Any]) -> str | None:
    """The harmful material kind of a contact `damage` event, or None."""
    frame = event["frame"]
    named = hazard_kind(body.run, event)
    lava_alone = body.lava_burning(frame) is None and not body.has("fireproof", frame)
    if named == "lava" and lava_alone:  # lava beside the hit box, but it did not burn
        named = "poison" if body.has("poisoned", frame) else "contact"
    if named == "poison" and body.poisoning_drunk(frame):
        return None
    return KINDS.get(named)


def _contact_episodes(body: _Body) -> dict[str, dict[str, Any]]:
    """For each harmful material kind, its first contact episode: frames and HP."""
    found: dict[str, dict[str, Any]] = {}
    for e in body.run.events.of_type("damage"):
        if e.get("target") != "player" or e.get("source") != "contact":
            continue
        kind = _contact_kind(body, e)
        if kind is None:
            continue
        ep = found.get(kind)
        if ep is None:
            found[kind] = {"start": e["frame"], "end": e["frame"], "hp": as_float(e["amount"])}
        elif not ep.get("closed") and e["frame"] - ep["end"] <= EPISODE_GAP:
            ep["end"] = e["frame"]
            ep["hp"] += as_float(e["amount"])
        else:
            ep["closed"] = True
    return found


def _touch(body: _Body, kind: str, m: Meeting, c: dict[str, Any] | None) -> dict[str, Any] | None:
    """How the first meeting `m` of `kind` touched it: `{start, end, hp, began, died}` (`began`:
    the burning or poisoning the touch began), or None if it was never touched."""
    run = body.run
    status = TOUCH_STATUS.get(kind)
    began = body.begun(status, m.start - FIRE_LINK, m.end + FIRE_LINK) if status else None
    if c is not None and not m.start - SLOW_FLUSH <= c["start"] <= m.end + SLOW_FLUSH:
        c = None  # a contact of a later meeting
    seen = [t for t in (m.touch, began and began[0], c and c["start"]) if t is not None]
    if not seen:
        return None
    t0 = min(seen)
    t1 = max(m.end, c["end"] if c else m.end, began[1] if began else m.end)
    hurt = run.events.player_damage(t0, t1 + SLOW_FLUSH, "contact", "fire")
    died = run.died_at()
    return {
        "start": t0,
        "end": t1,
        "hp": sum(as_float(e.get("amount")) for e in hurt),
        "began": began,
        "died": died is not None and t0 <= died <= t1 + SLOW_FLUSH,
    }


def _judge_kind(body: _Body, kind: str, m: Meeting, c: dict[str, Any] | None) -> dict[str, Any]:
    """The first meeting judged: `{start, value, why}`, and `began`, the burning or poisoning
    the touch began (None if none)."""
    touch = _touch(body, kind, m, c)
    start = m.start if touch is None else min(m.start, touch["start"])
    if touch is None:
        return {"start": start, "value": 1.0, "why": "met it and never touched it"}
    hp = touch["hp"]
    began = touch["began"]
    if touch["died"]:
        return {"start": start, "value": 0.0, "why": "died at the first meeting", "began": began}
    if hp < GRAZE_HP and began is None:
        return {"start": start, "value": 1.0, "why": f"met it and only grazed it ({hp:.1f} HP)"}
    note = {"lava": " with the burning", "toxic": " with the poisoning"}.get(kind, "")
    why = f"touched it: {hp:.0f} HP{note if began else ''}"
    value = TOUCH_BEST * linear(hp, 0.0, BAD[kind])
    return {"start": start, "value": value, "why": why, "began": began}


def _judge_meetings(body: _Body) -> dict[str, dict[str, Any]]:
    """Each hazard kind met, judged on its first meeting."""
    contacts = _contact_episodes(body)
    scan = Scan(body.run)
    judged: dict[str, dict[str, Any]] = {}
    for kind in BAD:
        c, m = contacts.get(kind), scan.met.get(kind)
        if m is None and c is not None and scan.upto is not None and c["start"] <= scan.upto:
            m = Meeting(c["start"], c["end"], c["start"])  # touched between two samples
        if m is not None:
            judged[kind] = _judge_kind(body, kind, m, c)
        elif scan.cut:  # not met in what was seen; what came after is not known
            judged[kind] = {"start": None, "value": None, "why": f"not known: {scan.cut}"}
    return judged


def _lava_lit(body: _Body, start: int) -> bool:
    """Was the burning that began at `start` lit by lava: lava in reach at a sample within
    `FIRE_LINK` frames of it, or a lava contact event around it?"""
    run = body.run
    for sample in run.track.between(start - FIRE_LINK, start + FIRE_LINK):
        seen = kinds_at(run, sample)
        if seen is not None and "lava" in seen[0]:
            return True
    return any(
        _contact_kind(body, e) == "lava"
        for e in run.events.player_damage(start - FIRE_LINK, start + SLOW_FLUSH, "contact")
    )


def _water_at_hand(run: RunData, frame: int) -> bool | None:
    """Water within `WATER_REACH` cells of the hit box at `frame` (recorded grid), or a bottle
    of it in hand; None if neither is held and no grid was recorded then."""
    if any(liquid_in_hand(run, m, frame) is not None for m in _wetting()):
        return True
    me = run.track.at(frame)
    if me is None:
        return None
    x0, y0 = int(me.x) - WATER_REACH, int(me.y) - WATER_REACH
    x1, y1 = int(me.x + me.w) + WATER_REACH, int(me.y + me.h) + WATER_REACH
    patch = run.frames.window(frame, x0, y0, x1, y1)
    if patch is None:
        return None
    wetting = [i for i, k in enumerate(material_keys()) if k in _wetting()]
    return any(bool((patch == i).any()) for i in wetting)


def _fire(body: _Body, lava_fire: Span | None) -> dict[str, Any] | None:
    """The first burning that neither lava (`lava_fire`: the one the first lava meeting began)
    nor a drink started, judged."""
    burnings = [
        (lo, hi)
        for lo, hi in body.spans["on_fire"]
        if (lo, hi) != lava_fire and not body.began_by_drink(lo, "burn") and not _lava_lit(body, lo)
    ]
    if not burnings:
        return None
    run, (t0, te) = body.run, burnings[0]
    died = run.died_at()
    frames, oiled_mul = _fire_frames()
    natural = frames * (oiled_mul if body.has("oiled", t0) else 1)
    if died is not None and t0 <= died <= te:
        return {"start": t0, "value": 0.0, "why": "died burning"}
    if ("on_fire", t0) in body.unended:
        return {"start": t0, "value": None, "why": "still burning at the end"}
    if te - t0 < PUT_OUT * natural:
        return {"start": t0, "value": 1.0, "why": f"put out after {te - t0} frames"}
    at_hand = _water_at_hand(run, t0)
    if at_hand:
        return {"start": t0, "value": 0.0, "why": f"burned out ({te - t0}) with water at hand"}
    why = f"burned out ({te - t0}) with no water at hand: waiting was all one could do"
    if at_hand is None:
        why = f"burned out ({te - t0}); no recorded grid to tell whether water was at hand"
    return {"start": t0, "value": None, "why": why}


def _head_under(run: RunData, frame: int, liquids: frozenset[int]) -> bool:
    me = run.track.at(frame)
    if me is None:
        return False
    x, y = int(me.x + me.w / 2), int(me.y)
    cell = run.frames.window(frame, x, y, x + 1, y + 1) if x >= 0 and y >= 0 else None
    return cell is not None and cell.size == 1 and int(cell[0, 0]) in liquids


def _wet_frames(body: _Body) -> list[int]:
    """The sample frames at which the player had a liquid's status (in order, each once)."""
    spans = [s for name in LIQUID_STATUSES for s in body.spans[name]]
    return sorted({s.frame for lo, hi in spans for s in body.run.track.between(lo, hi)})


def _risky_dive(body: _Body) -> tuple[dict[str, Any] | None, bool]:
    """The first dive that used `RISKY_BREATH` of the breath as `{start, end, low}` (end: the
    first sample with the head out; low: the least breath left), and whether the grids ran out
    (`MAX_GRID_CHECKS`) before one was found."""
    run, keys = body.run, material_keys()
    liquids = frozenset(i for i in breathless_liquids() if keys[i] not in JUDGED_ELSEWHERE)
    air = int(_entities()["player"]["air_frames"])
    risky = air * (1 - RISKY_BREATH)
    stride = as_int(run.meta.get("frame_stride"), 12)
    breath, under, last, dive = air, False, None, None
    for k, frame in enumerate(_wet_frames(body)):
        if k >= MAX_GRID_CHECKS:
            return None, True
        gap = 0 if last is None else frame - last
        if under and gap <= stride:
            breath = max(0, breath - gap)
        else:
            breath = min(air, breath + BREATH_REFILL * gap)  # the head was out in between
        under, last = _head_under(run, frame, liquids), frame
        if under:
            dive = dive or {"start": frame, "low": breath}
            dive["end"], dive["low"] = frame, min(dive["low"], breath)
        elif dive is not None:
            if dive["low"] <= risky:
                return {**dive, "end": frame}, False
            dive = None
    return (dive if dive is not None and dive["low"] <= risky else None), False


def _deep_water(body: _Body) -> dict[str, Any] | None:
    """The first dive that used half the breath, judged by the drowning in it."""
    run = body.run
    if not run.frames.records:
        return {"start": None, "value": None, "why": "no recorded grid (frames.bin)"}
    dive, cut = _risky_dive(body)
    if cut:
        why = f"too long in liquids to look at every grid (over {MAX_GRID_CHECKS} samples)"
        return {"start": None, "value": None, "why": why}
    if dive is None:
        return None
    t0, up = dive["start"], dive["end"]
    drown = [
        e
        for e in run.events.player_damage(t0, up + SLOW_FLUSH, "contact")
        if hazard_kind(run, e) == "contact"
    ]
    lost = sum(as_float(e.get("amount")) for e in drown)
    died = run.died_at()
    if died is not None and t0 <= died <= up + SLOW_FLUSH:
        return {"start": t0, "value": 0.0, "why": "drowned"}
    why = f"head under for {up - t0} frames (breath down to {dive['low']}), {lost:.0f} HP lost"
    return {"start": t0, "value": linear(lost, 0.0, DROWN_BAD), "why": why}


@metric_group
def first_contact_physics(run: RunData, _results: list[Result]) -> list[Metric]:
    body = _Body(run)
    judged = _judge_meetings(body)
    lava_fire = judged.get("lava", {}).get("began")
    for kind, found in (("fire", _fire(body, lava_fire)), ("deep_water", _deep_water(body))):
        if found is not None:
            judged[kind] = found
    scored = {k: v for k, v in judged.items() if v.get("value") is not None}
    detail = {
        k: {"frame": v.get("start"), "value": v.get("value"), "why": v["why"]}
        for k, v in sorted(judged.items(), key=lambda kv: kv[1].get("start") or 0)
    }
    reason = "; ".join(f"{k}: {v['why']}" for k, v in detail.items())
    if not scored:
        reason = reason or "no harmful material, fire or deep water was met"
        return [Metric("first_contact_physics", ("N4",), None, 0, reason, detail)]
    value = sum(v["value"] for v in scored.values()) / len(scored)
    return [Metric("first_contact_physics", ("N4",), value, len(scored), reason, detail)]
