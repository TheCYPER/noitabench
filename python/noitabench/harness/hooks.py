"""L3, hooks: the game reacts to something for the player.

    hook_set(event, action, ...)   hook_list()   hook_clear(id)

An *event* is something the agent layer's interrupts already watch for, so a hook never sees
more than the player is told:

    damage           the player took damage                      (interrupt `damage`, on at start)
    new_enemy        a hostile creature came into view           (`new_enemy`, on at start)
    status_change    the player has a new condition              (`status_change`, on at start)
    new_material     a material came into view for the first time (`new_material`, off at start)
    entered_liquid   the player is in a liquid                   (`fell_in_liquid`, off at start)
    hp_below(value)  HP fell below `value`                       (`hp_low`, off at start)

An *action* is `interrupt` (the event stops a running command, or stops doing so with `on=false`;
this switches the interrupt on `session.interrupts`) or `run` (the same, and then a script of the
player's runs). A script is `scripts/<name>.py`, read when the hook fires and run in the box
with `game`, `notes` and `event` in scope and at most `HOOK_COMMAND_CAP` game commands.

When a hook fires: after every decision made through the toolbox (a tool call, a step of a
program, a step of another hook's script is not one) the stop reasons of the answer are read: a
command that was interrupted names the interrupt (`stop.detail`), and every other interrupt of
that tick is in `stop.also`; a command that completed on the same tick lists them in `also`
too. Each event that appears fires the `run` hooks of that event once, in the order they were
set, right after that decision. What a script prints (and the view after its last command, if it
played) is put at the end of the result of the turn that is running. Scripts that run do not
start hooks themselves, and at most `MAX_HOOK_RUNS` scripts run in one game.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from noitabench.agent import CommandError
from noitabench.agent.vocab import DEFAULT_INTERRUPTS

from .codemode import runtime_of
from .errors import HarnessError
from .model import ToolSpec
from .prompt import HOOK_CLEAR_DESCRIPTION, HOOK_LIST_DESCRIPTION, HOOK_SET_DESCRIPTION
from .toolbox import FREE, ToolDef, object_schema

if TYPE_CHECKING:
    from .codemode import CodeRuntime
    from .layers import LayerContext

log = logging.getLogger(__name__)

EVENTS = (
    "damage",
    "new_enemy",
    "status_change",
    "new_material",
    "entered_liquid",
    "hp_below",
)
INTERRUPT_OF = {
    "damage": "damage",
    "new_enemy": "new_enemy",
    "status_change": "status_change",
    "new_material": "new_material",
    "entered_liquid": "fell_in_liquid",
    "hp_below": "hp_low",
}
EVENT_OF = {interrupt: event for event, interrupt in INTERRUPT_OF.items()}
MESSAGE_OF = {
    "damage": "You took damage.",
    "new_enemy": "A creature came into view.",
    "status_change": "You have a new condition.",
    "new_material": "A new material came into view.",
    "entered_liquid": "You are in a liquid.",
    "hp_below": "Your HP fell.",
}
ACTIONS = ("interrupt", "run")
HOOK_COMMAND_CAP = 20
MAX_HOOKS = 12
MAX_RUN_HOOKS_PER_EVENT = 3
MAX_HOOK_RUNS = 100
_SCRIPT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,60}$")


@dataclass
class Hook:
    id: str
    event: str
    action: str
    on: bool = True  # for `interrupt`
    script: str = ""  # scripts/<name>.py, for `run`
    value: float | None = None  # for hp_below
    plugin: str = ""  # a hook function of a plugin instead of a script
    function: str = ""
    runs: int = 0

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "event": self.event, "action": self.action}
        if self.action == "interrupt":
            out["on"] = self.on
        if self.script:
            out["script"] = self.script
        if self.plugin:
            out["plugin"] = f"{self.plugin}.{self.function}"
        if self.value is not None:
            out["value"] = self.value
        out["runs"] = self.runs
        return out


def fired_events(answer: dict[str, Any]) -> list[tuple[str, str]]:
    """The events that happened in a decision, from its answer: `(event, message)`, once each."""
    found: dict[str, str] = {}
    stops = [answer.get("stop") or {}]
    stops += [r.get("stop") or {} for r in answer.get("results", [])]
    for stop in stops:
        names: list[tuple[str, str]] = []
        if stop.get("reason") == "interrupted" and stop.get("detail"):
            names.append((stop["detail"], stop.get("message", "")))
        if stop.get("reason") in ("interrupted", "completed"):
            names += [(also, "") for also in stop.get("also", [])]
        for interrupt, message in names:
            event = EVENT_OF.get(interrupt)
            if event is not None and event not in found:
                found[event] = message or MESSAGE_OF[event]
    return list(found.items())


def script_path(name: str) -> str:
    """`scripts/<name>.py` for `name`, `name.py` or `scripts/name.py`."""
    text = str(name).strip()
    text = text.removeprefix("scripts/")
    text = text.removesuffix(".py")
    if not _SCRIPT.match(text):
        raise CommandError(
            "bad_script", "A script name is plain letters, digits, `_`, `-` and `.`, like check."
        )
    return f"scripts/{text}.py"


class HookEngine:
    """The hooks of one game."""

    def __init__(self, runtime: CodeRuntime) -> None:
        self.rt = runtime
        self.hooks: list[Hook] = []
        self._counter = 0
        self._running = False
        self._total_runs = 0
        self._said_limit = False

    # -- the tools ----------------------------------------------------------------------------------

    def set_hook(self, args: dict[str, Any]) -> dict[str, Any]:
        event, action = args["event"], args["action"]
        if event not in EVENTS:
            raise CommandError("bad_event", f"event must be one of: {', '.join(EVENTS)}")
        if action not in ACTIONS:
            raise CommandError("bad_action", "action must be `interrupt` or `run`")
        value = args.get("value")
        if event == "hp_below":
            if action == "run" and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise CommandError("bad_value", "hp_below needs `value`, the HP it falls below")
            if value is not None:
                value = float(value)
        elif value is not None:
            raise CommandError("bad_value", "only hp_below takes a `value`")
        hook = Hook(id="", event=event, action=action, value=value)
        notes: list[str] = []
        if action == "run":
            hook.script = script_path(str(args.get("script", "")))
            try:
                self.rt.workspace.read_text(hook.script)
            except CommandError:
                raise CommandError(
                    "no_such_script",
                    f"There is no file {hook.script}. Write the script first with workspace_write.",
                ) from None
        else:
            hook.on = bool(args.get("on", True))
            if "script" in args:
                raise CommandError("bad_action", "only `run` takes a script")
        notes += self._place(hook)
        self.apply()
        out: dict[str, Any] = {**hook.as_dict(), "stops_on": self.stops_on()}
        if notes:
            out["note"] = " ".join(notes)
        return out

    def list_hooks(self, _args: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "hooks": [h.as_dict() for h in self.hooks],
            "stops_on": self.stops_on(),
            "runs_left": max(MAX_HOOK_RUNS - self._total_runs, 0),
        }
        threshold = self.rt.session.interrupts.hp_threshold
        if "hp_below" in out["stops_on"]:
            out["hp_below_value"] = threshold
        return out

    def clear_hook(self, args: dict[str, Any]) -> dict[str, Any]:
        which = str(args["id"]).strip()
        if which == "all":
            gone = [h for h in self.hooks if not h.plugin]
        else:
            gone = [h for h in self.hooks if h.id == which]
            if not gone:
                raise CommandError("no_such_hook", f"There is no hook called `{which}`.")
            if gone[0].plugin:
                raise CommandError(
                    "plugin_hook",
                    "That hook comes from a plugin: change or delete the plugin file.",
                )
        self.hooks = [h for h in self.hooks if h not in gone]
        self.apply()
        return {"cleared": [h.id for h in gone], "stops_on": self.stops_on()}

    # -- bookkeeping ----------------------------------------------------------------------------------

    def _place(self, hook: Hook) -> list[str]:
        """Add a hook; says what it replaced."""
        notes: list[str] = []
        mine = [h for h in self.hooks if not h.plugin]
        if len(mine) >= MAX_HOOKS:
            raise CommandError("too_many_hooks", f"At most {MAX_HOOKS} hooks; clear one first.")
        replaced: list[Hook] = []
        if hook.event == "hp_below":  # the game keeps one threshold
            replaced = [h for h in mine if h.event == "hp_below"]
        elif hook.action == "interrupt":
            replaced = [h for h in mine if h.event == hook.event and h.action == "interrupt"]
        else:
            same = [h for h in mine if h.event == hook.event and h.action == "run"]
            if len(same) >= MAX_RUN_HOOKS_PER_EVENT:
                raise CommandError(
                    "too_many_hooks",
                    f"At most {MAX_RUN_HOOKS_PER_EVENT} scripts per event; clear one first.",
                )
        for old in replaced:
            self.hooks.remove(old)
            notes.append(f"It replaces hook {old.id}.")
        self._counter += 1
        hook.id = f"h{self._counter}"
        self.hooks.append(hook)
        keeps_on = any(h.event == hook.event and h.action == "run" for h in self.hooks)
        if hook.action == "interrupt" and not hook.on and keeps_on:
            notes.append("A script hook on this event keeps it switched on.")
        return notes

    def set_plugin_hooks(self, entries: list[dict[str, Any]]) -> None:
        """Replace the hooks that plugins declare (called when the plugins are read)."""
        self.hooks = [h for h in self.hooks if not h.plugin]
        for entry in entries:
            event = entry.get("event")
            value = entry.get("value")
            if event not in EVENTS or (event == "hp_below" and not isinstance(value, (int, float))):
                continue
            if event != "hp_below" and value is not None:
                continue
            hook = Hook(
                id=f"{entry['plugin']}.{entry['function']}",
                event=event,
                action="run",
                value=None if value is None else float(value),
                plugin=entry["plugin"],
                function=entry["function"],
            )
            self.hooks.append(hook)
        self.apply()

    def stops_on(self) -> list[str]:
        """Events that stop a running command now."""
        enabled = self.rt.session.interrupts.enabled
        return [e for e in EVENTS if INTERRUPT_OF[e] in enabled]

    def apply(self) -> None:
        """Set the game's interrupts to what the hooks say."""
        interrupts = self.rt.session.interrupts
        for event in EVENTS:
            name = INTERRUPT_OF[event]
            mine = [h for h in self.hooks if h.event == event]
            runs = [h for h in mine if h.action == "run"]
            switches = [h for h in mine if h.action == "interrupt"]
            if runs:
                want = True
            elif switches:
                want = switches[-1].on
            else:
                want = name in DEFAULT_INTERRUPTS
            if want and name not in interrupts.enabled:
                interrupts.enable(name)
            elif not want and name in interrupts.enabled:
                interrupts.disable(name)
            values = [h.value for h in mine if h.value is not None]
            if event == "hp_below" and values and want:
                interrupts.enable(name, hp_below=values[-1])

    # -- firing ---------------------------------------------------------------------------------------

    def after_decision(self, answer: dict[str, Any]) -> None:
        if self._running or not self.hooks or self.rt.session.over:
            return
        for event, message in fired_events(answer):
            for hook in [h for h in self.hooks if h.event == event and h.action == "run"]:
                if self.rt.session.over:
                    return
                self._run(hook, event, message, int(answer["decision"]))

    def _run(self, hook: Hook, event: str, message: str, decision: int) -> None:
        toolbox = self.rt.toolbox
        if self._total_runs >= MAX_HOOK_RUNS:
            if not self._said_limit:
                self._said_limit = True
                toolbox.add_notice(
                    f"Your hooks have run {MAX_HOOK_RUNS} times; they will not run again in this "
                    "game."
                )
            return
        self._total_runs += 1
        hook.runs += 1
        info: dict[str, Any] = {"name": event, "message": message, "decision": decision}
        if hook.value is not None:
            info["value"] = hook.value
        what = hook.script or f"{hook.plugin}.{hook.function}"
        head = f"Hook {hook.id} ({event}: {message}) ran {what} after Decision {decision}."
        self._running = True
        try:
            if hook.script:
                source = self.rt.workspace.read_text(hook.script)
                report = self.rt.run(
                    "code", cap=HOOK_COMMAND_CAP, label=f"hook {hook.id}", code=source, event=info
                )
            else:
                report = self.rt.run(
                    "plugin_hook",
                    cap=HOOK_COMMAND_CAP,
                    label=f"hook {hook.id}",
                    plugins=self.rt.workspace.plugin_sources(),
                    plugin=hook.plugin,
                    function=hook.function,
                    event=info,
                )
            toolbox.add_notice(f"{head}\n{self.rt.render(report, subject='The script').text}")
        except (CommandError, HarnessError) as err:
            toolbox.add_notice(f"Hook {hook.id} could not run {what}: {err}")
        finally:
            self._running = False


def hooks_of(ctx: LayerContext) -> HookEngine | None:
    """The hook engine of this game, if layer L3 is on."""
    engine = ctx.extras.get("hooks")
    return engine if isinstance(engine, HookEngine) else None


def register_l3(ctx: LayerContext) -> None:
    runtime = runtime_of(ctx)
    engine = HookEngine(runtime)
    ctx.extras["hooks"] = engine
    ctx.toolbox.on_decision(engine.after_decision)
    event_doc = f"One of: {', '.join(EVENTS)}."
    tools: list[tuple[ToolSpec, Any]] = [
        (
            ToolSpec(
                "hook_set",
                HOOK_SET_DESCRIPTION,
                object_schema(
                    {
                        "event": {"type": "string", "enum": list(EVENTS), "description": event_doc},
                        "action": {
                            "type": "string",
                            "enum": list(ACTIONS),
                            "description": "interrupt, or run (interrupt and then run a script).",
                        },
                        "value": {
                            "type": "number",
                            "description": "hp_below only: the HP it falls below.",
                        },
                        "on": {
                            "type": "boolean",
                            "description": "interrupt only: false stops the event from "
                            "interrupting (default true).",
                        },
                        "script": {
                            "type": "string",
                            "description": "run only: the script, like check for scripts/check.py.",
                        },
                    },
                    ["event", "action"],
                ),
            ),
            engine.set_hook,
        ),
        (ToolSpec("hook_list", HOOK_LIST_DESCRIPTION, object_schema({})), engine.list_hooks),
        (
            ToolSpec(
                "hook_clear",
                HOOK_CLEAR_DESCRIPTION,
                object_schema(
                    {"id": {"type": "string", "description": "The hook id, like h1, or all."}},
                    ["id"],
                ),
            ),
            engine.clear_hook,
        ),
    ]
    for spec, handler in tools:
        ctx.toolbox.register(ToolDef(spec, FREE, handler))
