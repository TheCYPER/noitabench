"""The wand practice range: `wand_range`, a free tool that casts a wand outside the world.

The player gives a wand (one it carries, or the numbers of one it has looked at) and, if it likes,
another order of the spells it carries. The engine's own casting code is run for a few seconds
with the fire button held down (`noitabench.game.wand_trial`), and the tool tells what each click
played, how the mana lasts, how many shots there are per second and how much damage they would do
to a dummy that every shot hits. It takes no game time and costs no step; nothing in the world
changes.

**Which spells may be tried.** Only spells the player carries, each card once: in its wands
(including the wand being tried) and among its loose cards. A hypothetical spell is not allowed:
a spell the player has not found would tell it that the spell exists, what it does and what it
needs, which is information from the cave, not from practice; and it would make finding spells
pointless. Rearranging what one holds is what the practice range is for. Wand *numbers* may be
made up (`stats`): they are only numbers the player typed, and show nothing but how the casting
rules work.

**What the numbers mean.** The dummy never moves and never dies, every projectile hits it and
every blast reaches it, and nothing else is counted: spread, flight time, bounces, sprays,
trails and conditions are left out. Damage is displayed HP. A wand that shuffles is run with
several shuffles; its rates are averages and its timeline is one of them. The report never holds
anything the state channel or `inspect` does not already tell (no ray energy, no durability, no
seeds).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from noitabench.agent import AgentSession
from noitabench.agent.errors import CommandError
from noitabench.game import wand_trial

from .model import ToolSpec
from .toolbox import FREE, ToolDef

if TYPE_CHECKING:  # layers.py imports the layer modules: no import cycle at run time
    from .layers import LayerContext

FPS = 60
DEFAULT_SECONDS = 10.0
MAX_SECONDS = 60.0
SHUFFLE_RUNS = 5
TIMELINE_ROWS = 10
KEEP_CLICKS = 600  # clicks the engine hands back (the totals count all of them)
REQUIRED_STATS = ("mana_max", "mana_per_second", "cast_delay", "recharge", "capacity")
OPTIONAL_STATS = ("spells_per_cast", "spread", "shuffle")
REASONS = {"not_enough_mana": "not enough mana", "no_uses_left": "no uses left"}
# What is said when the engine refuses a made-up wand. The engine's own message names its limits
# (the most slots a wand can have, ...), which are not the player's to learn from a refusal.
BAD_WAND = (
    "wand_range: those numbers do not make a wand. capacity and spells_per_cast are whole numbers "
    "from 1 (spells_per_cast at most capacity), mana_max and mana_per_second are not negative, and "
    "cast_delay and recharge are whole numbers of a reasonable size."
)

PROMPT_WAND_RANGE = """\
PRACTICE RANGE
`wand_range` shows what a wand would do if you held the fire button for a while, without using \
game time or a step: which spells each click plays, how the mana lasts, how many shots there are \
per second, and the damage per second against a dummy that every shot hits. It works for a wand \
you carry, or for the numbers of a wand you have looked at; with `slots` you can try the spells \
you carry in another order. It cannot use spells you do not carry.
"""

Trial = Callable[..., dict[str, Any]]


# -- what is carried ------------------------------------------------------------------------------


def _whole(value: Any, name: str) -> int:
    """`value` as a whole number; anything else (text, infinity, 2.5) is a bad argument."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CommandError("bad_argument", f"wand_range: `{name}` is a whole number.")
    if isinstance(value, float) and not (math.isfinite(value) and value == int(value)):
        raise CommandError("bad_argument", f"wand_range: `{name}` is a whole number.")
    return int(value)


def _key(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        raise CommandError("bad_argument", "wand_range: a spell is named by its key, like BULLET.")
    return text.strip().upper().replace(" ", "_")


class _Cards:
    """The spell cards a player carries: for each key, the uses left of each card (`None`:
    unlimited), the most uses first."""

    def __init__(self, carried: Mapping[str, Any]) -> None:
        cards: dict[str, list[int | None]] = {}
        for wand in carried["wands"]:
            for slot in wand["slots"]:
                if slot is not None:
                    cards.setdefault(slot["spell"], []).append(slot["uses"])
        for card in carried["spells"]:
            cards.setdefault(card["spell"], []).append(card["uses"])
        self._cards = {k: sorted(v, key=_uses_order, reverse=True) for k, v in cards.items()}
        self.owned = Counter({k: len(v) for k, v in self._cards.items()})

    def take(self, key: str) -> int | None:
        """One card of `key`; raises `CommandError` when none is left."""
        cards = self._cards.get(key)
        if not cards:
            have = self.owned.get(key, 0)
            raise CommandError(
                "not_carried",
                (
                    f"wand_range: you carry only {have} {key} card(s)."
                    if have
                    else f"wand_range: you do not carry {key}."
                )
                + " Only spells you carry can be tried, each card once; "
                f"carried: {_carried_text(self.owned)}.",
            )
        return cards.pop(0)


def _uses_order(uses: int | None) -> float:
    return float("inf") if uses is None else float(uses)


def _carried_text(owned: Mapping[str, int]) -> str:
    return ", ".join(f"{k} x{n}" if n > 1 else k for k, n in sorted(owned.items())) or "nothing"


# -- the wand to try ------------------------------------------------------------------------------


def _real(value: Any, name: str) -> float:
    """`value` as a finite number."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CommandError("bad_argument", f"wand_range: `{name}` is a number.")
    return float(value)


def _stats_from_numbers(given: Mapping[str, Any]) -> dict[str, Any]:
    """Engine wand stats from the numbers `inspect` shows for a wand."""
    unknown = sorted(set(given) - set(REQUIRED_STATS) - set(OPTIONAL_STATS))
    if unknown:
        raise CommandError(
            "bad_argument",
            f"wand_range: unknown wand number(s) {', '.join(unknown)}; give "
            f"{', '.join(REQUIRED_STATS)} and, if you know them, {', '.join(OPTIONAL_STATS)}.",
        )
    missing = [k for k in REQUIRED_STATS if k not in given]
    if missing:
        raise CommandError(
            "bad_argument", f"wand_range: the wand numbers need {', '.join(missing)}."
        )
    if not isinstance(given.get("shuffle", False), bool):
        raise CommandError("bad_argument", "wand_range: `shuffle` is true or false.")
    return {
        "mana_max": _real(given["mana_max"], "mana_max"),
        "mana_charge_speed": _real(given["mana_per_second"], "mana_per_second"),
        "cast_delay": _whole(given["cast_delay"], "cast_delay"),
        "recharge": _whole(given["recharge"], "recharge"),
        "capacity": _whole(given["capacity"], "capacity"),
        "spells_per_cast": _whole(given.get("spells_per_cast", 1), "spells_per_cast"),
        "spread": _real(given.get("spread", 0.0), "spread"),
        "shuffle": given.get("shuffle", False),
    }


class _Setup:
    """What to run: stats, slots (spell and uses left), always-cast spells, and a label."""

    def __init__(
        self,
        stats: dict[str, Any],
        slots: list[dict[str, Any] | None],
        always_cast: list[str],
        label: str,
    ) -> None:
        self.stats = stats
        self.slots = slots
        self.always_cast = always_cast
        self.label = label


def _setup(carried: Mapping[str, Any], active: int, args: Mapping[str, Any]) -> _Setup:
    wands = carried["wands"]
    cards = _Cards(carried)
    if "stats" in args and "wand" in args:
        raise CommandError("bad_argument", "wand_range: give `wand` or `stats`, not both.")
    if "stats" in args:
        if not isinstance(args["stats"], Mapping):
            raise CommandError("bad_argument", "wand_range: `stats` is an object of wand numbers.")
        if "slots" not in args:
            raise CommandError("bad_argument", "wand_range: with `stats` give the `slots` to try.")
        stats, always, held, label = _stats_from_numbers(args["stats"]), [], None, "given numbers"
    else:
        index = _whole(args.get("wand", active), "wand")
        if not 0 <= index < len(wands):
            raise CommandError(
                "no_such_wand", f"wand_range: you carry {len(wands)} wand(s), no wand {index}."
            )
        held = wands[index]
        stats, always, label = dict(held["stats"]), list(held["always_cast"]), f"wand {index}"
    if "slots" not in args:
        assert held is not None
        return _Setup(stats, [None if s is None else dict(s) for s in held["slots"]], always, label)
    asked = args["slots"]
    if not isinstance(asked, Sequence) or isinstance(asked, str):
        raise CommandError("bad_argument", "wand_range: `slots` is a list of spell keys or null.")
    capacity = _whole(stats["capacity"], "capacity")
    if len(asked) > capacity:
        raise CommandError(
            "too_many_slots", f"wand_range: that wand has {capacity} slot(s), not {len(asked)}."
        )
    slots: list[dict[str, Any] | None] = []
    for item in asked:
        if item is None:
            slots.append(None)
            continue
        key = _key(item)
        slots.append({"spell": key, "uses": cards.take(key)})
    return _Setup(stats, slots, always, label)


# -- running and reporting ------------------------------------------------------------------------


def wand_range(
    session: AgentSession, args: Mapping[str, Any], *, trial: Trial = wand_trial
) -> dict[str, Any]:
    """Answer one `wand_range` call. Raises `CommandError` for what cannot be tried."""
    carried = session.carried()
    setup = _setup(carried, carried["active_wand"], args)
    seconds = _seconds(args.get("seconds", DEFAULT_SECONDS))
    target = _target_hp(args.get("target_hp"))
    frames = round(seconds * FPS)
    shuffles = bool(setup.stats.get("shuffle"))
    runs = []
    for seed in range(SHUFFLE_RUNS if shuffles else 1):
        try:
            runs.append(
                trial(
                    setup.stats,
                    setup.slots,
                    frames=frames,
                    seed=seed,
                    always_cast=setup.always_cast,
                    keep_casts=KEEP_CLICKS,
                )
            )
        except ValueError as err:  # the engine refuses this wand (a capacity of 0, ...)
            raise CommandError("bad_wand", BAD_WAND) from err
    return _report(setup, runs, seconds, target)


def _seconds(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise CommandError("bad_argument", "wand_range: `seconds` is a number.") from None
    if not 1.0 <= seconds <= MAX_SECONDS:
        raise CommandError(
            "bad_argument", f"wand_range: `seconds` must be from 1 to {MAX_SECONDS:g}."
        )
    return seconds


def _target_hp(value: Any) -> float | None:
    if value is None:
        return None
    try:
        hp = float(value)
    except (TypeError, ValueError):
        raise CommandError("bad_argument", "wand_range: `target_hp` is a number.") from None
    if hp <= 0:
        raise CommandError("bad_argument", "wand_range: `target_hp` must be above 0.")
    return hp


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _rate(runs: Sequence[dict[str, Any]], field: str, seconds: float) -> float:
    return round(_mean([r[field] for r in runs]) / seconds, 2)


def _report(
    setup: _Setup, runs: list[dict[str, Any]], seconds: float, target: float | None
) -> dict[str, Any]:
    first = runs[0]
    stats = setup.stats
    report: dict[str, Any] = {
        "wand": setup.label,
        "slots": [None if s is None else s["spell"] for s in setup.slots],
        "seconds": round(seconds, 2),
        "clicks_per_second": _rate(runs, "shooting_casts", seconds),
        "shots_per_second": _rate(runs, "projectiles", seconds),
        "damage_per_second": _rate(runs, "damage", seconds),
        "damage_total": round(_mean([r["damage"] for r in runs]), 1),
    }
    if first["payload_projectiles"]:
        report["payload_shots_per_second"] = _rate(runs, "payload_projectiles", seconds)
    report["mana"] = _mana(first, stats, seconds)
    if first["recharges"]:
        report["recharges"] = round(_mean([r["recharges"] for r in runs]), 1)
    if first["used_up"]:
        report["used_up"] = [setup.slots[i]["spell"] for i in first["used_up"] if setup.slots[i]]
    if target is not None:
        report["seconds_to_kill"] = _kill_time(first, target)
        if report["seconds_to_kill"] is None and _horizon_cut(first, target):
            last = first["casts"][-1]["frame"] / FPS
            report["seconds_to_kill_note"] = (
                f"later than {last:.1f} s (the clicks after that are not followed)"
            )
    report["timeline"] = _timeline(first)
    if first["total_casts"] > len(report["timeline"]):
        report["timeline_cut"] = first["total_casts"] - len(report["timeline"])
    skipped = _skipped(first)
    if skipped:
        report["passed_over"] = skipped
    notes = ["The dummy never moves and never dies; every shot and every blast reaches it."]
    if len(runs) > 1:
        notes.append(
            f"This wand shuffles: rates are averages of {len(runs)} shuffles; the timeline is one of them."
        )
    notes.append(
        "Damage includes the average gain from critical hits. Spread, flight time, bounces, "
        "sprays, trails and conditions are not counted."
    )
    report["notes"] = notes
    return report


def _mana(run: dict[str, Any], stats: Mapping[str, Any], seconds: float) -> dict[str, Any]:
    out: dict[str, Any] = {
        "start": round(run["mana_start"], 1),
        "end": round(run["mana_end"], 1),
        "lowest": round(run["mana_min"], 1),
        "max": round(float(stats["mana_max"]), 1),
        "regained_per_second": round(float(stats["mana_charge_speed"]), 1),
        "spent_per_second": round(run["mana_spent"] / seconds, 1),
    }
    dry = next(
        (c for c in run["casts"] if any(s["reason"] == "not_enough_mana" for s in c["skipped"])),
        None,
    )
    if dry is not None:
        out["first_short_of_mana_at"] = round(dry["frame"] / FPS, 2)
    return out


def _kill_time(run: dict[str, Any], target_hp: float) -> float | None:
    """When the dummy, given `target_hp`, would be dead; None if not within the clicks the report
    follows (see `_horizon_cut`)."""
    total = 0.0
    for c in run["casts"]:
        total += c["damage"]
        if total >= target_hp:
            return round(c["frame"] / FPS, 2)
    return None


def _horizon_cut(run: dict[str, Any], target_hp: float) -> bool:
    """True when the dummy dies, but after the last click the report follows (a wand that clicks
    more than `KEEP_CLICKS` times in the run)."""
    return len(run["casts"]) < run["total_casts"] and run["damage"] >= target_hp


def _timeline(run: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for c in run["casts"][:TIMELINE_ROWS]:
        row: dict[str, Any] = {
            "t": round(c["frame"] / FPS, 2),
            "plays": "+".join(c["spells"]) or "-",
        }
        shots = c["projectiles"]
        if shots:
            row["shots"] = shots
        if c["payload_projectiles"]:
            row["payload_shots"] = c["payload_projectiles"]
        if c["damage"]:
            row["damage"] = round(c["damage"], 1)
        row["mana_left"] = round(c["mana_after"], 1)
        row["next_click_after_s"] = round(c["ready_in"] / FPS, 2)
        if c["recharge"] is not None:
            row["recharge_s"] = round(c["recharge"] / FPS, 2)
        if c["skipped"]:
            row["passed_over"] = [f"{s['spell']} ({REASONS[s['reason']]})" for s in c["skipped"]]
        rows.append(row)
    return rows


def _skipped(run: dict[str, Any]) -> list[str]:
    return [
        f"{s['spell']}: {REASONS[s['reason']]}, {s['times']} time(s)"
        for s in sorted(run["skips"], key=lambda s: (-s["times"], s["spell"]))
    ]


# -- registration ---------------------------------------------------------------------------------


def wand_range_spec() -> ToolSpec:
    wand_numbers = {
        "type": "object",
        "description": (
            "The numbers of a wand you do not carry, as `inspect` shows them: mana_max, "
            "mana_per_second, cast_delay, recharge, capacity, and if known spells_per_cast, "
            "spread, shuffle. Needs `slots`."
        ),
        "properties": {
            "mana_max": {"type": "number"},
            "mana_per_second": {"type": "number"},
            "cast_delay": {"type": "integer"},
            "recharge": {"type": "integer"},
            "capacity": {"type": "integer"},
            "spells_per_cast": {"type": "integer"},
            "spread": {"type": "number"},
            "shuffle": {"type": "boolean"},
        },
        "additionalProperties": False,
    }
    return ToolSpec(
        "wand_range",
        "Try a wand on the practice range: hold the fire button for a few seconds outside the "
        "world and see which spells each click plays, how the mana lasts, the shots per second "
        "and the damage per second against a dummy that every shot hits. Takes no game time and "
        "costs no step. Only spells you carry can be tried, each card once.",
        {
            "type": "object",
            "properties": {
                "wand": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Index of a wand you carry (default: the one in your hand).",
                },
                "stats": wand_numbers,
                "slots": {
                    "type": "array",
                    "items": {"type": ["string", "null"]},
                    "description": "Spells to try, one entry per slot, in slot order; null leaves "
                    "a slot empty. Default: the wand as it is.",
                },
                "seconds": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": MAX_SECONDS,
                    "description": f"How long to fire (default {DEFAULT_SECONDS:g}).",
                },
                "target_hp": {
                    "type": "number",
                    "description": "Health of the dummy, to see how soon it would be dead.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    )


def register_wand_range(ctx: LayerContext) -> None:
    """Add `wand_range` to the toolbox (a free tool: no game time, no step)."""
    ctx.toolbox.register(
        ToolDef(wand_range_spec(), FREE, lambda args: wand_range(ctx.session, args))
    )
