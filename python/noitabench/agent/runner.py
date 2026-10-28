"""Running one command in game time (time model B).

The world advances frame by frame under the plan's controls. On every tick boundary (every 10
frames) the runner collects the events of the tick, asks the plan whether its own `ticks` or
`event` condition is met, then asks the interrupts whether something happened that the agent
must hear about. A command also stops when the budget of the decision (300 frames) is used up.

Between the end of a command and the next command nothing advances: the world waits for the
agent. The run never ends inside a tick: when a plan is done early, the rest of its tick passes
with no keys held.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .aim import Aim
from .engine import Engine, box_center, hit_center
from .events import EventCollector
from .interrupts import Interrupts
from .plans import Ctx, Plan
from .vocab import COMPLETED, DEAD, INTERRUPTED, TICK_FRAMES, TIME_LIMIT


@dataclass(frozen=True)
class RunResult:
    reason: str
    detail: str = ""
    message: str = ""
    ticks: int = 0
    frames: int = 0
    also: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"reason": self.reason, "ticks": self.ticks, "frames": self.frames}
        if self.detail:
            out["detail"] = self.detail
        if self.message:
            out["message"] = self.message
        if self.also:
            out["also"] = list(self.also)
        return out


class Runner:
    def __init__(
        self,
        engine: Engine,
        aim: Aim,
        interrupts: Interrupts,
        collector: EventCollector,
        decision_frame: int,
    ) -> None:
        self.engine = engine
        self.aim = aim
        self.interrupts = interrupts
        self.collector = collector
        self.decision_frame = decision_frame
        self.ctx = Ctx(engine, engine.content, aim)

    # -- the aim, every frame -----------------------------------------------------------------------

    def _target(self) -> dict[str, Any] | None:
        """The creature or item the aim follows, if it is still in the game; sets
        `ctx.target_present`."""
        self.ctx.target_present = True
        if self.aim.mode != "entity" or self.aim.entity is None:
            return None
        target = self.engine.entity(self.aim.entity)
        self.ctx.target_present = target is not None
        return target

    def refresh_target(self) -> None:
        """Before a command starts: is the creature that is aimed at still there?"""
        self._target()

    def _aim_angle(self, p: dict[str, Any]) -> float:
        """The aim of this frame. The aim follows a creature only while the player can see it;
        out of sight the last angle holds (a followed creature must not give away where it is)."""
        target = self._target()
        in_sight = target is not None and self.engine.sees(p, target)
        hx, hy = self.engine.content.hand
        hand = (p["x"] + hx + 0.5, p["y"] + hy + 0.5)
        return self.aim.resolve(hand, box_center(target) if in_sight and target else None)

    # -- running a plan -----------------------------------------------------------------------------

    def run(self, plan: Plan, budget_frames: int) -> RunResult:
        """Run `plan` until it ends, is interrupted or has used `budget_frames` frames (a
        multiple of the tick)."""
        engine = self.engine
        p = engine.player()
        met = plan.precheck(p)
        if met is not None:  # already met (`until=edge` at a ledge): no time passes
            return RunResult(COMPLETED, met, plan.message)
        done: str | None = None
        frames = ticks = 0
        while True:
            for _ in range(TICK_FRAMES):
                angle = self._aim_angle(p)
                controls = plan.controls(p) if done is None else {}
                engine.step({**controls, "aim": angle})
                p = engine.player()
                frames += 1
                if done is None:
                    done = plan.after_frame(p)
                    if done is None and self._halted(plan):
                        done = "blocked"
                    if done is not None:
                        plan.finish(engine)  # the keys are let go from the next frame on
            ticks += 1
            result = self._boundary(plan, p, ticks, frames, done, budget_frames)
            if result is not None:
                plan.finish(engine)
                return result

    def _halted(self, plan: Plan) -> bool:
        """Does the plan stop on its own because it is pushing against a wall? Only when the
        `blocked` interrupt is off: with it on, the interrupt does the stopping."""
        return (
            plan.halts_when_blocked
            and plan.blocked is not None
            and "blocked" not in self.interrupts.enabled
        )

    def _boundary(
        self,
        plan: Plan,
        p: dict[str, Any],
        ticks: int,
        frames: int,
        done: str | None,
        budget: int,
    ) -> RunResult | None:
        engine = self.engine
        raw = engine.drain_events()
        entities = engine.entities()
        visible = engine.visible(p, entities)
        tick_no = (engine.frame - self.decision_frame) // TICK_FRAMES
        events = self.collector.add_tick(
            tick_no, raw, p, {v["id"] for v in visible}, lambda x, y: engine.sees_point(p, x, y)
        )
        hostile = {v["id"] for v in visible if engine.hostile(v)}
        fired = self.interrupts.observe(
            p,
            visible,
            hostile,
            raw,
            self._materials_in_view(p),
            engine.submerged(p),
            plan.end_of_tick(),
            engine.content.material_keys,
        )
        if p["dead"]:
            return RunResult(DEAD, "", "You died.", ticks, frames)
        # An interrupt on the tick a command completes does not win, but it is not swallowed.
        also = tuple(t.name for t in fired)
        if done is not None:
            return RunResult(COMPLETED, done, plan.message, ticks, frames, also)
        met = plan.at_tick(ticks, events)
        if met is not None:
            return RunResult(COMPLETED, met, plan.message, ticks, frames, also)
        if fired:
            first = fired[0]
            also = tuple(t.name for t in fired[1:])
            return RunResult(INTERRUPTED, first.name, first.message, ticks, frames, also)
        if frames >= budget:
            return RunResult(
                TIME_LIMIT,
                "",
                "That is as long as one decision can last (5 seconds).",
                ticks,
                frames,
            )
        return None

    def _materials_in_view(self, p: dict[str, Any]) -> set[int]:
        if "new_material" not in self.interrupts.enabled:
            return set()
        cx, cy = (int(v) for v in hit_center(p))
        half_x, half_y = self.engine.view_half
        window = self.engine.window(cx - half_x, cy - half_y, 2 * half_x, 2 * half_y)
        seen = {int(m) for m in np.unique(window)}
        seen.discard(255)
        seen.discard(0)
        return seen
