"""`AgentSession`: one episode seen as a conversation (tick-design section 4).

    session = AgentSession(game)
    answer = session.observe()                      # decision 1: stop reason "start"
    answer = session.decide("walk_to(x=180)")       # or a list of commands, or dicts
    ...

A *decision* is one call to `decide`: up to four commands, run in order. Commands that take time
(`walk_to`, `fire`, ...) run in game time, tick by tick, until they are done, interrupted or the
decision has used 300 frames. Commands that take none (`aim`, `inspect`, `edit_wand`, notes) are
answered at once. Between decisions the world is frozen. The answer says why the world stopped,
what happened meanwhile, and shows the observation channels that are switched on.

What a decision costs against `max_decisions`: 1 for its commands other than `inspect` (if it
has any), plus 1 for every `inspect` in it, and at least 1 in all. So `kick; aim(angle=3)` costs
1, a lone `inspect` costs 1, two `inspect`s cost 2 and `kick; inspect; inspect` costs 3. A
command that was skipped because an earlier one stopped the decision costs nothing. A request
that cannot be read, or has more than four commands, costs 1 and takes no time.

The session owns the game: nothing it returns refers to the game object, the rule seed, the
reaction log or the world markers.
"""

from __future__ import annotations

import base64
import copy
import json
import reprlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from noitabench.game import Game

from .aim import Aim
from .content import Content
from .engine import Engine, public_kind
from .errors import CommandError
from .events import EventCollector
from .inspecting import inspect
from .interrupts import Interrupts
from .memory import MemoryBackend, NoMemory
from .observe import Observer, ViewConfig
from .plans import make_plan
from .recorder import DecisionLog, digest
from .runner import Runner, RunResult
from .spec import COMMANDS, FREE, MEMORY_COMMANDS, Command
from .tools import coerce_request, request_name
from .visibility import check_clean
from .vocab import (
    COMPLETED,
    DEAD,
    DEFAULT_MAX_DECISIONS,
    FPS,
    INVALID,
    MAX_COMMAND_FRAMES,
    MAX_COMMANDS,
    OVER,
    PROTOCOL,
    START,
    TICK_FRAMES,
    TIME_LIMIT,
)

_S = TypeVar("_S", bound="AgentSession")


@dataclass(frozen=True)
class SessionConfig:
    max_decisions: int = DEFAULT_MAX_DECISIONS
    view: ViewConfig = field(default_factory=ViewConfig)
    content_dir: Path | None = None
    frame_stride: int = 12  # recording: one full frame per this many frames
    paranoid: bool = True  # raise if an answer holds a hidden field

    def __post_init__(self) -> None:
        if self.max_decisions < 1:
            raise ValueError("max_decisions must be at least 1")


class AgentSession:
    """The conversation of one episode."""

    def __init__(
        self,
        game: Game,
        *,
        config: SessionConfig | None = None,
        memory: MemoryBackend | None = None,
        recording_dir: Path | str | None = None,
        notes: str = "agent session",
    ) -> None:
        self.config = config or SessionConfig()
        self.content = Content.load(self.config.content_dir)
        self.engine = Engine(game, self.content, self.config.view.view_half)
        self.engine.drain_events()  # whatever happened before the session is not a decision's
        self.observer = Observer(self.engine, self.content, self.config.view)
        self.memory: MemoryBackend = memory if memory is not None else NoMemory()
        self.aim = Aim()
        self.interrupts = Interrupts()  # the hook interface: enable / disable
        self.decisions = 0  # decisions answered so far
        self.over_reason: str | None = None
        self._envelope: dict[str, Any] = _start_envelope()
        self._last_digest = ""
        self._log: DecisionLog | None = None
        self._recording = recording_dir is not None
        if recording_dir is not None:
            Path(recording_dir).mkdir(parents=True, exist_ok=True)
            self.engine.start_recording(str(recording_dir), self.config.frame_stride, notes)
            self._log = DecisionLog(recording_dir)
        self._sync_seen()
        self._last_digest = digest(self.observe())

    # -- context manager --------------------------------------------------------------------------

    def __enter__(self: _S) -> _S:  # noqa: PYI019 - `Self` needs Python 3.11
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> dict[str, Any]:
        """Stop the recording and close the decision log. Safe to call twice."""
        summary: dict[str, Any] = {"decisions": self.decisions, "frames": self.engine.frame}
        if self._recording:
            summary["recording"] = self.engine.stop_recording()
            self._recording = False
        if self._log is not None:
            self._log.close()
            self._log = None
        return summary

    # -- looking ------------------------------------------------------------------------------------

    @property
    def frame(self) -> int:
        return self.engine.frame

    @property
    def over(self) -> bool:
        return self.over_reason is not None

    def state_hash(self) -> int:
        """Hash of the whole game state (for reproducibility checks; not for agents)."""
        return self.engine.state_hash()

    def observe(self) -> dict[str, Any]:
        """The current answer again: same stop reason and events, channels drawn afresh. Takes no
        time and is not a decision."""
        return self._answer(self._envelope)

    def carried(self) -> dict[str, Any]:
        """What the player carries, as the state channel tells it (whether or not that channel
        is on): `wands` (`index`, `stats` - without the hidden speed multiplier -, `slots` as
        `{spell, uses}` or `None`, `always_cast`, `mana`), `spells`, the loose cards
        (`{spell, uses}`), and `active_wand`, the index of the wand in hand. A copy; takes no time and is not a decision."""
        p = self.engine.player()
        wands = [
            {
                "index": i,
                "stats": {k: v for k, v in w["stats"].items() if k != "speed_multiplier"},
                "slots": [None if s is None else dict(s) for s in w["slots"]],
                "always_cast": list(w["always_cast"]),
                "mana": w["mana"],
            }
            for i, w in enumerate(p["wands"])
        ]
        return {
            "wands": wands,
            "spells": [dict(s) for s in p["spells"]],
            "active_wand": p["active_wand"],
        }

    def _answer(self, envelope: dict[str, Any]) -> dict[str, Any]:
        p = self.engine.player()
        visible = self.engine.visible(p, self.engine.entities())
        can_edit = self.engine.edit_zone_at(p) is not None
        answer = {
            "protocol": PROTOCOL,
            "decision": self.decisions + 1,
            "frame": self.engine.frame,
            "seconds": round(self.engine.frame / FPS, 2),
            "decisions_left": max(self.config.max_decisions - self.decisions, 0),
            "over": self.over_reason,
            **copy.deepcopy(envelope),
            "observation": self.observer.channels(p, visible, self.aim, can_edit),
        }
        if self.config.paranoid:
            check_clean(answer)
        return answer

    def _sync_seen(self) -> None:
        """What is in view now has been shown to the agent: it is not new any more."""
        p = self.engine.player()
        visible = self.engine.visible(p, self.engine.entities())
        ids = {v["id"] for v in visible if self.engine.hostile(v)}
        self.interrupts.seen_hostiles |= ids
        self.interrupts.statuses = set(p["statuses"])
        self.interrupts.hp = float(p["hp"])
        self.interrupts.submerged = self.engine.submerged(p)

    # -- deciding -----------------------------------------------------------------------------------

    def decide(self, request: Any) -> dict[str, Any]:
        """Run one decision: `request` is text (`aim(target=4); fire(until=target_dead)`), a
        command dict, a list of them, or checked `Command`s."""
        if self.over:
            return self._refuse_over()
        try:
            commands = coerce_request(request)
            _check_size(commands)
        except CommandError as err:
            return self.decide_invalid(err, _echo(request))
        return self._run(commands, [c.as_dict() for c in commands])

    def decide_invalid(self, err: CommandError, echo: Any) -> dict[str, Any]:
        """An invalid decision still counts as one, and no time passes (ACT-R05)."""
        if self.over:
            return self._refuse_over()
        envelope = {
            "stop": {
                "reason": INVALID,
                "code": err.code,
                "message": err.message,
                "ticks": 0,
                "frames": 0,
            },
            "results": [{"command": err.command or request_name(echo), "ok": False, **_fail(err)}],
            "events": [],
            "events_omitted": 0,
        }
        return self._finish(envelope, echo, 0, 1)

    def _refuse_over(self) -> dict[str, Any]:
        envelope = {
            "stop": {
                "reason": OVER,
                "message": f"The game is over ({self.over_reason}).",
                "ticks": 0,
                "frames": 0,
            },
            "results": [],
            "events": [],
            "events_omitted": 0,
        }
        return self._answer(envelope)

    def _run(self, commands: list[Command], echo: Any) -> dict[str, Any]:
        frame0 = self.engine.frame
        collector = EventCollector(self.engine.view_half)
        runner = Runner(self.engine, self.aim, self.interrupts, collector, frame0)
        results: list[dict[str, Any]] = []
        stop: RunResult | None = None
        invalid: dict[str, Any] | None = None
        budget = MAX_COMMAND_FRAMES
        for i, cmd in enumerate(commands):
            try:
                record, run = self._execute(cmd, runner, budget)
            except CommandError as err:
                results.append({"command": cmd.name, "ok": False, **_fail(err)})
                spent = self.engine.frame - frame0  # earlier commands of the decision ran
                invalid = {
                    "reason": INVALID,
                    "code": err.code,
                    "message": err.message,
                    "ticks": spent // TICK_FRAMES,
                    "frames": spent,
                }
                results += _skipped(commands[i + 1 :], "an earlier command was not valid")
                break
            results.append(record)
            if run is None:
                continue
            stop = run
            budget -= run.frames
            if run.reason != COMPLETED:
                results += _skipped(commands[i + 1 :], f"the decision ended: {run.reason}")
                break
        events, omitted = collector.summary(self.config.view.event_cap)
        envelope = {
            "stop": invalid or (stop.as_dict() if stop else _done_stop()),
            "results": results,
            "events": events,
            "events_omitted": omitted,
        }
        cost = _cost(commands, results)
        return self._finish(envelope, echo, self.engine.frame - frame0, cost)

    def _finish(
        self, envelope: dict[str, Any], echo: Any, frames: int, cost: int
    ) -> dict[str, Any]:
        shown_digest, frame_asked = self._last_digest, self.engine.frame - frames
        shown_reason = self._envelope["stop"]["reason"]
        self.decisions += cost
        if self.engine.player()["dead"]:
            self.over_reason = DEAD
        elif self.decisions >= self.config.max_decisions:
            self.over_reason = "decision_limit"
        self._envelope = envelope
        self._sync_seen()
        answer = self._answer(envelope)
        self._last_digest = digest(answer)
        if self._log is not None:
            self._log.write(
                {
                    "frame": frame_asked,
                    "index": self.decisions,
                    "stop_reason": shown_reason,
                    "command": echo,
                    "observation_digest": shown_digest,
                    "result": envelope["stop"],
                    "frames": frames,
                    "ok": all(r["ok"] for r in envelope["results"]),
                    "cost": cost,
                }
            )
        return answer

    # -- one command ------------------------------------------------------------------------------

    def _execute(
        self, cmd: Command, runner: Runner, budget: int
    ) -> tuple[dict[str, Any], RunResult | None]:
        p = self.engine.player()
        if COMMANDS[cmd.name].timing == FREE:
            return {"command": cmd.name, "ok": True, "result": self._free(cmd, p)}, None
        if budget < TICK_FRAMES:
            run = RunResult(TIME_LIMIT, "", "No time is left in this decision.", 0, 0)
            record = {
                "command": cmd.name,
                "ok": False,
                "code": "no_time_left",
                "message": run.message,
            }
            return record, run
        runner.refresh_target()
        plan = make_plan(cmd, runner.ctx, p)  # raises if the command cannot run
        if cmd.name in ("pour", "throw") and "angle" in cmd.args:
            self.aim.set_angle(float(cmd.args["angle"]))
        run = runner.run(plan, budget)
        record: dict[str, Any] = {"command": cmd.name, "ok": True, "stop": run.as_dict()}
        outcome = plan.outcome(self.engine.player())
        if outcome is not None:
            record["result"] = outcome
        return record, run

    def _free(self, cmd: Command, p: dict[str, Any]) -> dict[str, Any]:
        name, args = cmd.name, cmd.args
        if name == "aim":
            return self._do_aim(args, p)
        if name == "edit_wand":
            return self._do_edit(args, p)
        if name == "inspect":
            visible = self.engine.visible(p, self.engine.entities())
            return inspect(args, self.engine, self.content, p, visible)
        return self._do_memory(name, args)

    def _do_aim(self, args: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
        if "angle" in args:
            self.aim.set_angle(float(args["angle"]))
        elif "x" in args:
            x, y = float(args["x"]), float(args["y"])
            if not (0 <= x < self.engine.width and 0 <= y < self.engine.height):
                raise CommandError("out_of_world", f"aim: ({x:g}, {y:g}) is outside the world.")
            self.aim.set_point(x, y)
        else:
            self.aim.set_entity(self._aim_target(args.get("entity", args.get("target")), p))
        return {"aim_degrees": round(self.aim.angle, 1), "follows": self.aim.entity}

    def _aim_target(self, what: Any, p: dict[str, Any]) -> int:
        visible = self.engine.visible(p, self.engine.entities())
        if isinstance(what, int):
            if all(v["id"] != what for v in visible):
                raise CommandError("not_in_view", f"aim: nothing with id {what} is in view.")
            return what
        # by the kind an agent is told: a bottle of a potion is just a bottle
        match = next((v for v in visible if public_kind(v["kind"]) == what), None)
        if match is None:
            raise CommandError("not_in_view", f"aim: no {what} is in view.")
        return int(match["id"])

    def _do_edit(self, args: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
        if self.engine.edit_zone_at(p) is None:
            raise CommandError(
                "not_here",
                "You can only rearrange your wands in a rest area or at an edit station.",
            )
        op = args["op"]
        action: dict[str, Any] = {"op": op, "wand": args["wand"]}
        if op == "place":
            action.update(slot=args["slot"], **{"from": args["spell"]})
        elif op == "take":
            action["slot"] = args["slot"]
        else:
            action.update(a=args["a"], b=args["b"])
        try:
            self.engine.edit_wand(action)
        except ValueError as err:
            raise CommandError("edit_failed", str(err)) from err
        self.engine.drain_events()  # the `edit_wand` event is told by the result
        wand = self.engine.player()["wands"][args["wand"]]
        return {
            "wand": args["wand"],
            "slots": [s["spell"] if s else None for s in wand["slots"]],
            "carried": [s["spell"] for s in self.engine.player()["spells"]],
        }

    def _do_memory(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        m = self.memory
        if name == "memory_write":
            return m.write(args["path"], args["text"], bool(args.get("append", False)))
        if name == "memory_read":
            return m.read(args["path"])
        if name == "memory_search":
            return m.search(args["query"])
        if name == "memory_edit":
            return m.edit(args["path"], args["old"], args["new"])
        return m.list()

    # -- snapshots ----------------------------------------------------------------------------------

    def snapshot(self) -> bytes:
        """The game and the conversation state (aim, interrupts, the last answer's envelope,
        notes if the backend supports `snapshot`). Not available while recording."""
        notes = self.memory.snapshot() if hasattr(self.memory, "snapshot") else None
        state = {
            "format": "cogbench-agent-session/0",
            "game": base64.b64encode(self.engine.snapshot()).decode("ascii"),
            "decisions": self.decisions,
            "over": self.over_reason,
            "aim": self.aim.to_dict(),
            "interrupts": self.interrupts.to_dict(),
            "envelope": self._envelope,
            "digest": self._last_digest,
            "notes": notes,
        }
        return json.dumps(state, sort_keys=True).encode("utf-8")

    def restore(self, blob: bytes) -> None:
        state = json.loads(blob.decode("utf-8"))
        if state.get("format") != "cogbench-agent-session/0":
            raise ValueError("not a session snapshot")
        self.engine.restore(base64.b64decode(state["game"]))
        self.engine.drain_events()
        self.decisions = int(state["decisions"])
        self.over_reason = state["over"]
        self.aim = Aim.from_dict(state["aim"])
        self.interrupts = Interrupts.from_dict(state["interrupts"])
        self._envelope = state["envelope"]
        self._last_digest = state["digest"]
        if state["notes"] is not None and hasattr(self.memory, "restore"):
            self.memory.restore(state["notes"])


def _check_size(commands: list[Command]) -> None:
    """A decision holds at most `MAX_COMMANDS` commands; a longer one is refused before any
    command of it runs, like any other request that cannot be read."""
    if len(commands) > MAX_COMMANDS:
        raise CommandError(
            "too_many_commands",
            f"A decision holds at most {MAX_COMMANDS} commands; this one has {len(commands)}.",
            commands[0].name,
        )


def _cost(commands: list[Command], results: list[dict[str, Any]]) -> int:
    """Decisions a run costs: one for its commands, one more for each `inspect` in it unless
    nothing else was in it (then the first `inspect` is the decision itself). Notes commands are
    free, as the harness's workspace tools and the play page's notes panel are, so a run of only
    notes costs nothing. Commands that were skipped because an earlier one stopped the decision
    do not count."""
    ran = [c for c, r in zip(commands, results, strict=False) if r.get("code") != "skipped"]
    notes = sum(1 for c in ran if c.name in MEMORY_COMMANDS)
    looks = sum(1 for c in ran if c.name == "inspect")
    acts = len(ran) - looks - notes
    cost = looks + (1 if acts else 0)
    return cost if cost or notes else 1


def _start_envelope() -> dict[str, Any]:
    return {
        "stop": {"reason": START, "ticks": 0, "frames": 0},
        "results": [],
        "events": [],
        "events_omitted": 0,
    }


def _done_stop() -> dict[str, Any]:
    return {"reason": COMPLETED, "ticks": 0, "frames": 0}


def _fail(err: CommandError) -> dict[str, Any]:
    return {"code": err.code, "message": err.message}


def _skipped(commands: list[Command], why: str) -> list[dict[str, Any]]:
    return [
        {"command": c.name, "ok": False, "code": "skipped", "message": f"Not run: {why}."}
        for c in commands
    ]


def _echo(request: Any) -> Any:
    """What the agent sent, in a form that can be written to the log."""
    try:
        json.dumps(request)
    except (TypeError, ValueError, RecursionError):
        return reprlib.repr(request)
    return request


__all__ = ["AgentSession", "SessionConfig"]
