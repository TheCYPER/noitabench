"""What each command does to the player, frame by frame.

A `Plan` is the running form of a command that takes game time. The runner (`runner.py`) asks it
for the controls of the next frame and, after the frame, whether the command is done. A plan
never sees the game, only the player dict and the `Engine` questions it is handed.

Conditions that can be met in the middle of a tick (reaching a column, landing, mana running
out, the aimed creature dying) end the plan at once: it stops pressing keys and the rest of the
tick passes quietly, so the decision point still falls on a tick boundary. `ticks` and `event`
are looked at only on tick boundaries (`at_tick`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, ClassVar

from .aim import Aim
from .content import Content
from .engine import Engine, position_of, public_kind
from .errors import CommandError
from .spec import Command
from .vocab import CLIFF_DEPTH, DROP_MESSAGE, STALL_FRAMES, TICK_FRAMES, WALL_MESSAGE

PICKUP_KINDS = ("wand", "spell", "bottle")


@dataclass
class Ctx:
    """What plans may use."""

    engine: Engine
    content: Content
    aim: Aim
    target_present: bool = True  # the creature the aim follows is still there (runner updates)


def _sign(v: float) -> int:
    return (v > 0) - (v < 0)


class Plan:
    """A command in progress."""

    takes_off = False  # does the command itself leave the ground (so `landed` means a landing)?
    # Does the command end by itself when it cannot go on (a wall in the way), even with the
    # `blocked` interrupt switched off? Walking does; the runner decides when it applies.
    halts_when_blocked = False

    def __init__(self, cmd: Command, ctx: Ctx, player: dict[str, Any]) -> None:
        self.cmd = cmd
        self.ctx = ctx
        self.until: dict[str, Any] = dict(cmd.args.get("until", {}))
        self.start = position_of(player)
        self.frames = 0
        self.blocked: str | None = None  # "wall": the command cannot go on
        self.blocked_in_tick: str | None = None
        self.left_ground = False
        self.message = ""
        if self.until.get("target_dead") and not (
            self.ctx.aim.mode == "entity" and self.ctx.target_present
        ):
            raise CommandError(
                "no_target",
                f"{cmd.name}: `target_dead` needs a creature to aim at; use aim(entity=...) first.",
            )

    # -- what the runner calls ------------------------------------------------------------------

    def precheck(self, player: dict[str, Any]) -> str | None:
        """The condition (a stop detail) that ends the command before it takes any time, or
        `None`. Only `until=edge` has one."""
        return None

    def controls(self, player: dict[str, Any]) -> dict[str, Any]:
        return {}

    def after_frame(self, player: dict[str, Any]) -> str | None:
        """The condition that ended the command in this frame, if any."""
        self.frames += 1
        if not player["on_ground"]:
            self.left_ground = True
        cx, _ = position_of(player)
        u = self.until
        if "x" in u and self._crossed(cx, u["x"]):
            return "x"
        if "distance" in u and self._distance(player) >= u["distance"]:
            return "distance"
        if u.get("landed") and player["on_ground"] and (self.left_ground or not self.takes_off):
            return "landed"
        if "hp_below" in u and player["hp"] < u["hp_below"]:
            return "hp_below"
        if u.get("target_dead") and not self.ctx.target_present:
            return "target_dead"
        if u.get("mana_empty") and self.mana_empty(player):
            return "mana_empty"
        if u.get("blocked") and self.blocked:
            return "blocked"
        return self.own_end(player)

    def own_end(self, player: dict[str, Any]) -> str | None:
        return None

    def at_tick(self, ticks: int, events: list[dict[str, Any]]) -> str | None:
        """Conditions looked at on a tick boundary: `ticks` and `event`."""
        if "ticks" in self.until and ticks >= self.until["ticks"]:
            return "ticks"
        wanted = self.until.get("event")
        if wanted and any(e["type"] in wanted for e in events):
            return "event"
        return None

    def outcome(self, player: dict[str, Any]) -> dict[str, Any] | None:
        """What the command achieved, for its result (`None`: nothing to add)."""
        return None

    def finish(self, engine: Engine) -> None:
        """The command has stopped pressing its keys (done, interrupted or out of time). Called
        more than once; must do nothing the second time."""

    def end_of_tick(self) -> str | None:
        """Why the command is stuck, for the `blocked` interrupt; resets for the next tick."""
        reason, self.blocked_in_tick = self.blocked_in_tick, None
        return reason

    # -- helpers --------------------------------------------------------------------------------

    def _distance(self, player: dict[str, Any]) -> float:
        x, y = position_of(player)
        return math.hypot(x - self.start[0], y - self.start[1])

    def _crossed(self, cx: int, x: int) -> bool:
        return abs(cx - x) <= 1 or _sign(self.start[0] - x) != _sign(cx - x) != 0

    def mana_empty(self, player: dict[str, Any]) -> bool:
        wand = player["wands"][player["active_wand"]] if player["wands"] else None
        if wand is None:
            return True
        costs = [self.ctx.content.spell_cost(s["spell"]) for s in wand["slots"] if s]
        return not costs or wand["mana"] < min(costs)

    def _flag_blocked(self, why: str | None) -> None:
        self.blocked = why
        if why is not None:
            self.blocked_in_tick = why


# -- walking ---------------------------------------------------------------------------------------


class WalkPlan(Plan):
    """`move` and `walk_to`: sideways along the ground, braking before a target column.

    A walk never stops for a drop: the player walks off a ledge and falls (there is no fall
    damage), holding the direction in the air (a `walk_to` brakes at its column up there too) and
    reaching its column only once it stands (or swims) again; the walk then goes on or ends as its
    other conditions say. `until=edge` is the way to stop before a ledge. A wall is not predicted
    but felt: the key has been held for `STALL_FRAMES` frames and the player has not moved a cell
    in either direction (a ledge of up to `STEP_UP` cells is climbed, which moves the player).
    """

    halts_when_blocked = True
    takes_off = True  # `landed` waits for a touch-down after the walk left the ground

    def __init__(self, cmd: Command, ctx: Ctx, player: dict[str, Any]) -> None:
        super().__init__(cmd, ctx, player)
        self.target: int | None = None
        self.direction = 0
        self.edge = bool(self.until.pop("edge", False))
        self.edge_ahead = False  # until=edge: a drop is in front, the walk has stopped for it
        self._pressing = False  # the key was held in the frame that just ran
        self._stalled = 0
        self._last = (player["x"], player["y"])
        if cmd.name == "walk_to":
            self.target = int(cmd.args["x"])
        elif cmd.args["direction"] == "left":
            self.direction = -1
        else:
            self.direction = 1
        if cmd.name == "move":
            self._aim_at_condition()
        if self.target is not None:
            if not 0 <= self.target < ctx.engine.width:
                raise CommandError(
                    "out_of_world", f"{cmd.name}: column {self.target} is outside the world."
                )
            self.direction = _sign(self.target - self.start[0])

    def _aim_at_condition(self) -> None:
        """`move(right, x=...)` and `move(right, distance=...)` brake at their column."""
        sx, d = self.start[0], self.direction
        if "x" in self.until:
            x = self.until["x"]
            if _sign(x - sx) not in (d, 0):
                side = "left" if x < sx else "right"
                raise CommandError(
                    "wrong_side", f"move: column {x} is to your {side}, not the way you walk."
                )
            self.target = x
            self.until.pop("x")
        elif "distance" in self.until:
            self.target = round(sx + d * self.until.pop("distance"))

    def _stop_distance(self, player: dict[str, Any]) -> float:
        a = self.ctx.content.accel_ground if player["on_ground"] else self.ctx.content.accel_air
        return abs(player["vx"]) / 60.0 * (1.0 - a) / a

    def _wanted(self, player: dict[str, Any]) -> int:
        """The key to hold this frame: toward the target, but not into a coast past it."""
        if self.target is None:
            return self.direction
        cx, _ = position_of(player)
        dist = self.target - cx
        if abs(dist) <= 1 and abs(player["vx"]) < 15:
            return 0
        want = _sign(dist)
        if want == 0:
            return 0
        moving_that_way = player["vx"] * want > 0
        if moving_that_way and abs(dist) <= self._stop_distance(player) + 0.5:
            return 0
        return want

    def _drop_ahead(self, player: dict[str, Any], want: int) -> bool:
        """`until=edge`: would the leading foot, after the coast that follows letting go of the
        key, leave the ground, with nothing to stand on within `CLIFF_DEPTH` cells below?"""
        if want == 0 or not player["on_ground"]:
            return False
        look = int(self._stop_distance(player)) + 1
        if self.target is not None:  # no need to look beyond where it is going to stop
            look = min(look, max(abs(self.target - position_of(player)[0]), 1))
        lead = player["x"] + (player["w"] - 1 if want > 0 else 0) + want * look
        # the world's edge is a wall, not a drop
        lead = max(0, min(lead, self.ctx.engine.width - 1))
        return not self.ctx.engine.has_ground(lead, player["y"], 1, player["h"], CLIFF_DEPTH)

    def precheck(self, player: dict[str, Any]) -> str | None:
        if self.edge and self._drop_ahead(player, self._wanted(player)):
            self.message = DROP_MESSAGE
            return "edge"
        return None

    def controls(self, player: dict[str, Any]) -> dict[str, Any]:
        want = self._wanted(player)
        if self.edge and self._drop_ahead(player, want):
            self.edge_ahead = True
            self.message = DROP_MESSAGE
        # let go at a drop (until=edge) and against a wall: no use pushing on
        self._pressing = want != 0 and not self.edge_ahead and self.blocked is None
        return {"move": want if self._pressing else 0}

    def after_frame(self, player: dict[str, Any]) -> str | None:
        here = (player["x"], player["y"])
        if self._pressing and here == self._last:
            self._stalled += 1
            if self._stalled >= STALL_FRAMES:
                self._flag_blocked("wall")
                self.message = WALL_MESSAGE
        else:
            self._stalled = 0
        self._last = here
        return super().after_frame(player)

    def own_end(self, player: dict[str, Any]) -> str | None:
        if self.edge_ahead:
            return "edge"
        if self.target is not None:
            cx, _ = position_of(player)
            slow_and_close = abs(self.target - cx) <= 1 and abs(player["vx"]) < 15
            if slow_and_close and (player["on_ground"] or self.ctx.engine.submerged(player)):
                return "reached"  # standing or swimming, not falling
        return None


# -- the air ---------------------------------------------------------------------------------------


class JumpPlan(Plan):
    takes_off = True

    def __init__(self, cmd: Command, ctx: Ctx, player: dict[str, Any]) -> None:
        super().__init__(cmd, ctx, player)
        self.direction = {"left": -1, "right": 1}.get(cmd.args.get("direction", "up"), 0)

    def controls(self, player: dict[str, Any]) -> dict[str, Any]:
        return {"jump": self.frames == 0, "move": self.direction}

    def own_end(self, player: dict[str, Any]) -> str | None:
        if self.left_ground and player["on_ground"]:
            return "landed"
        if self.frames >= 4 and not self.left_ground and abs(player["vy"]) < 1:
            self._flag_blocked("wall")  # it did not lift off: no room above
            return "landed"
        return None


class FlyPlan(Plan):
    takes_off = True

    def __init__(self, cmd: Command, ctx: Ctx, player: dict[str, Any]) -> None:
        super().__init__(cmd, ctx, player)
        self.direction = {"left": -1, "right": 1}.get(cmd.args.get("direction", "up"), 0)

    def controls(self, player: dict[str, Any]) -> dict[str, Any]:
        return {"fly": True, "move": self.direction}

    def own_end(self, player: dict[str, Any]) -> str | None:
        free_flight = "levitation" in player["statuses"]  # a potion: the meter does not drain
        return "levitation_empty" if player["fly"] <= 0.001 and not free_flight else None


# -- hands -----------------------------------------------------------------------------------------


class FirePlan(Plan):
    def __init__(self, cmd: Command, ctx: Ctx, player: dict[str, Any]) -> None:
        super().__init__(cmd, ctx, player)
        wand = player["wands"][player["active_wand"]] if player["wands"] else None
        if wand is None or not any(wand["slots"]):
            raise CommandError("empty_wand", "fire: the wand you hold has no spells.")
        if ctx.aim.mode == "entity" and not ctx.target_present:
            ctx.aim.set_angle(ctx.aim.angle)  # the creature is gone: keep the last direction

    def controls(self, player: dict[str, Any]) -> dict[str, Any]:
        return {"fire": True}

    def own_end(self, player: dict[str, Any]) -> str | None:
        if self.mana_empty(player):
            return "mana_empty"
        if self.ctx.aim.mode == "entity" and not self.ctx.target_present:
            return "target_dead"
        return None


class WaitPlan(Plan):
    def __init__(self, cmd: Command, ctx: Ctx, player: dict[str, Any]) -> None:
        super().__init__(cmd, ctx, player)
        if not self.until:
            self.until = {"ticks": 1}


class OneTickPlan(Plan):
    """`kick`, `swap_wand`, `pickup`, `throw`, `drop`: a key pressed on the first frame."""

    def __init__(self, cmd: Command, ctx: Ctx, player: dict[str, Any]) -> None:
        super().__init__(cmd, ctx, player)
        self.keys = self._keys(cmd, player)

    def _keys(self, cmd: Command, player: dict[str, Any]) -> dict[str, Any]:
        name = cmd.name
        if name == "kick":
            return {"kick": True}
        if name == "swap_wand":
            index = cmd.args["wand"]
            if index >= len(player["wands"]):
                raise CommandError(
                    "no_such_wand",
                    f"swap_wand: you have {len(player['wands'])} wand(s), no wand {index}.",
                )
            return {"select_wand": index}
        if name == "pickup":
            self._check_pickup(cmd, player)
            return {"interact": True}
        if name == "drop":
            return {"drop": self._drop(cmd, player)}
        return {"select_bottle": self._bottle(cmd, player), "throw": True}

    def _drop(self, cmd: Command, player: dict[str, Any]) -> dict[str, int]:
        """The `drop` control for a wand, a carried spell or a bottle that is there."""
        for what, held, code in (
            ("wand", player["wands"], "no_such_wand"),
            ("spell", player["spells"], "no_such_spell"),
            ("bottle", player["bottles"], "no_such_bottle"),
        ):
            if what in cmd.args:
                index = int(cmd.args[what])
                if index >= len(held):
                    raise CommandError(
                        code, f"drop: you have {len(held)} {what}(s), no {what} {index}."
                    )
                return {what: index}
        raise CommandError("bad_argument", "drop: give a wand, a spell or a bottle")  # unreachable

    def _bottle(self, cmd: Command, player: dict[str, Any]) -> int:
        bottles = player["bottles"]
        index = cmd.args.get("bottle", player["active_bottle"])
        if index >= len(bottles):
            raise CommandError(
                "no_such_bottle",
                f"{cmd.name}: you carry {len(bottles)} bottle(s), no bottle {index}.",
            )
        return int(index)

    def _check_pickup(self, cmd: Command, player: dict[str, Any]) -> None:
        engine = self.ctx.engine
        px, py = player["x"] + player["w"] / 2, player["y"] + player["h"] / 2
        reach = self.ctx.content.pickup_radius + 2
        best: tuple[float, dict[str, Any]] | None = None
        for e in engine.entities():
            if not _pickable(e["kind"]):
                continue
            d = math.hypot(e["x"] + e["w"] / 2 - px, e["y"] + e["h"] / 2 - py)
            if d <= reach and (best is None or d < best[0]):
                best = (d, e)
        if best is None:
            raise CommandError(
                "nothing_in_reach", "pickup: there is nothing you can pick up within reach."
            )
        wanted = cmd.args.get("item")
        if wanted is not None and best[1]["id"] != wanted:
            raise CommandError(
                "not_nearest",
                f"pickup: item {wanted} is not the nearest thing within reach "
                f"(that is {public_kind(best[1]['kind'])} #{best[1]['id']}).",
            )

    def controls(self, player: dict[str, Any]) -> dict[str, Any]:
        return dict(self.keys) if self.frames == 0 else {}

    def own_end(self, player: dict[str, Any]) -> str | None:
        return "done" if self.frames >= 1 else None


def _pickable(kind: str) -> bool:
    return kind in PICKUP_KINDS or kind.startswith("potion_")


class BottlePlan(Plan):
    """`drink`, `pour` and `fill`: hold the key until the amount has moved."""

    KEY: ClassVar[dict[str, str]] = {"drink": "drink", "pour": "pour", "fill": "fill"}

    def __init__(self, cmd: Command, ctx: Ctx, player: dict[str, Any]) -> None:
        super().__init__(cmd, ctx, player)
        bottles = player["bottles"]
        self.index = int(cmd.args.get("bottle", player["active_bottle"]))
        if self.index >= len(bottles):
            raise CommandError(
                "no_such_bottle",
                f"{cmd.name}: you carry {len(bottles)} bottle(s), no bottle {self.index}.",
            )
        self.start_contents = _contents(bottles[self.index])
        self.start_amount = bottles[self.index]["amount"]
        capacity = ctx.content.bottle_capacity
        if cmd.name == "fill":
            if self.start_amount >= capacity:
                raise CommandError("bottle_full", f"fill: bottle {self.index} is full.")
            full = capacity - self.start_amount
        else:
            if self.start_amount <= 0:
                raise CommandError("empty_bottle", f"{cmd.name}: bottle {self.index} is empty.")
            full = self.start_amount
        asked = cmd.args.get("amount", 100 if cmd.name == "drink" else "all")
        self.goal = full if asked == "all" else min(int(asked), full)
        self.last_amount, self.last_change = self.start_amount, 0

    def controls(self, player: dict[str, Any]) -> dict[str, Any]:
        return {"select_bottle": self.index, self.KEY[self.cmd.name]: True}

    def outcome(self, player: dict[str, Any]) -> dict[str, Any] | None:
        """What moved: `cells` in all and the `material` (`water+oil` when several moved, with
        `parts` giving each)."""
        now = _contents(player["bottles"][self.index])
        order = sorted(self.start_contents.keys() | now.keys(), key=self.ctx.content.material_index)
        moved = {m: abs(now.get(m, 0) - self.start_contents.get(m, 0)) for m in order}
        moved = {m: n for m, n in moved.items() if n > 0}
        out: dict[str, Any] = {
            "material": "+".join(moved) or (next(iter(self.start_contents), None)),
            "cells": sum(moved.values()),
        }
        if len(moved) > 1:
            out["parts"] = [{"material": m, "cells": n} for m, n in moved.items()]
        return out

    def finish(self, engine: Engine) -> None:
        engine.end_bottle_action()  # the summary event belongs to the frame the key was let go

    def own_end(self, player: dict[str, Any]) -> str | None:
        bottles = player["bottles"]
        amount = bottles[self.index]["amount"] if self.index < len(bottles) else 0
        if amount != self.last_amount:
            self.last_amount, self.last_change = amount, self.frames
        if abs(amount - self.start_amount) >= self.goal:
            return "done"
        if self.frames - self.last_change >= TICK_FRAMES:
            self.message = (
                "Nothing more could be scooped up."
                if self.cmd.name == "fill"
                else "Nothing came out."
            )
            return "no_progress"
        return None


def _contents(bottle: dict[str, Any]) -> dict[str, int]:
    """Cells of each material in a bottle dict, by material key."""
    return {part["material"]: int(part["amount"]) for part in bottle["contents"]}


def make_plan(cmd: Command, ctx: Ctx, player: dict[str, Any]) -> Plan:
    """The plan of a command that takes game time. Raises `CommandError` if it cannot run."""
    name = cmd.name
    if name in ("move", "walk_to"):
        return WalkPlan(cmd, ctx, player)
    if name == "jump":
        return JumpPlan(cmd, ctx, player)
    if name == "fly":
        return FlyPlan(cmd, ctx, player)
    if name == "fire":
        return FirePlan(cmd, ctx, player)
    if name == "wait":
        return WaitPlan(cmd, ctx, player)
    if name in ("drink", "pour", "fill"):
        return BottlePlan(cmd, ctx, player)
    if name in ("kick", "swap_wand", "pickup", "throw", "drop"):
        return OneTickPlan(cmd, ctx, player)
    raise CommandError("unknown_command", f"{name} is not a command that takes time")
