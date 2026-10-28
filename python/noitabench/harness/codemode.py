"""L2, Code Mode: the player writes a Python program that plays for it.

    run_code(code)      the program runs in the box (`sandbox.py`) with two modules in scope:
        game            one function per game command (`game.walk_to(x=180)`), `game.decide(text)`
                        for up to four commands as one step, `game.observe()` for the view
        notes           the notebook: read, write, edit, search, list, delete

Every request of the program is answered here, on the real session, by a `Bridge`: a game call is
one decision, charged exactly like the same tool call (inspect and the four-command rule
included), and the interrupts, hooks and recording see it like any other decision. A program may
run at most `COMMAND_CAP` game commands; when the game ends the next call stops it. The program
is given only what an agent is given: answers of the agent layer without screenshots, and the
notebook. It never gets the game, a seed or a marker, and an internal error reaches it as the
bare name of the exception.

The same machinery runs hook scripts (`hooks.py`) and plugin tools (`plugins.py`): `CodeRuntime`
runs a job and `render` turns the outcome into the text the player reads.
"""

from __future__ import annotations

import ast
import json
import logging
import reprlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from noitabench.agent import CommandError, coerce_request, render_text, tool_schemas
from noitabench.agent.grammar import MAX_TEXT, split_statements
from noitabench.agent.protocol import with_text
from noitabench.agent.spec import MEMORY_COMMANDS

from .errors import HarnessError
from .model import ToolSpec
from .prompt import RUN_CODE_DESCRIPTION
from .redact import Redactor
from .sandbox import JobResult, Limits, Sandbox
from .toolbox import FREE, ToolDef, ToolOutput, object_schema, screenshot_of

if TYPE_CHECKING:
    from .layers import LayerContext

log = logging.getLogger(__name__)

COMMAND_CAP = 200  # game commands in one program
MAX_CODE_CHARS = 20_000
MAX_VALUE_CHARS = 50_000  # what a plugin tool may return (the box cuts it there)
DEFAULT_LIMITS = Limits()


@dataclass
class ProgramReport:
    """How a program ended and what it did."""

    ok: bool
    error: str = ""
    limit: str | None = None
    detail: str = ""
    stdout: str = ""
    stdout_truncated: bool = False
    value: Any = None
    has_value: bool = False
    commands: int = 0
    steps: int = 0
    first_decision: int = 0
    ended: str | None = None  # why the game ended while the program ran
    last_stop: dict[str, Any] | None = None
    load_errors: dict[str, str] = field(default_factory=dict)
    described: dict[str, Any] | None = None
    wall_seconds: float = 0.0
    peak_mb: float = 0.0


class Bridge:
    """Answers the requests of one program."""

    def __init__(self, runtime: CodeRuntime, cap: int) -> None:
        self.rt = runtime
        self.cap = cap
        self.commands = 0
        self.last_stop: dict[str, Any] | None = None
        self.ended: str | None = None

    def __call__(self, message: dict[str, Any]) -> dict[str, Any]:
        target, name = message.get("target"), message.get("name")
        args = message.get("args")
        if not isinstance(name, str) or not isinstance(args, dict):
            return _failure("RuntimeError", "bad request")
        try:
            if target == "game":
                return self._game(name, args)
            if target == "notes":
                return self._notes(name, args)
        except CommandError as err:
            return _failure("NotesError", f"{err.code}: {err.message}")
        except (TypeError, KeyError, ValueError):
            return _failure("TypeError", f"bad arguments for {target}.{name}")
        except Exception:
            log.exception("request %s.%s failed", target, name)
            return _failure("RuntimeError", "the game could not do that")
        return _failure("RuntimeError", f"there is nothing called {target}")

    # -- the game ---------------------------------------------------------------------------------

    def _game(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        rt = self.rt
        if name == "observe":
            return {"ok": True, "value": wire(rt.session.observe())}
        if name == "decide":
            text = args.get("text")
            if not isinstance(text, str):
                return _failure("TypeError", "game.decide() needs a string of commands")
            used = _count_commands(text)
        elif name in rt.command_names:
            used = 1
        else:
            return _failure("AttributeError", f"game has no command called {name!r}")
        if self.commands + used > self.cap:
            return _failure(
                "LimitReached",
                f"At most {self.cap} game commands can run in one go; this one has used "
                f"{self.commands}.",
            )
        self.commands += used
        if name == "decide":
            answer = rt.toolbox.run_game_request(self._decoded_safely(args["text"]))
        else:
            answer = rt.toolbox.run_game_command(name, args)
        self.last_stop = answer["stop"]
        reply: dict[str, Any] = {"ok": True, "value": wire(answer)}
        if rt.session.over:
            self.ended = rt.session.over_reason
            reply["over"] = True
        return reply

    def _decoded_safely(self, text: str) -> Any:
        """`text` for the game to read. The box's requests are cleaned before they get here, but
        the game reads quotes and escapes (`'\\x73k-'`, `'sk-' 'ant-'`), so a secret may be
        in the commands only once they are read, and from there it would reach the notebook (the
        `memory_*` commands), the answer and the record of the decision. A command with a
        secret in it is written out again with the secret hidden."""
        redactor = self.rt.toolbox.redactor
        if not redactor.enabled or len(text) > MAX_TEXT:  # (too long: the game refuses it unread)
            return text
        try:
            statements = split_statements(text)
        except Exception:  # noqa: BLE001 - what cannot be read is the game's to refuse
            return text
        out: list[str] = []
        changed = False
        for statement in statements:
            rewritten = _hide_in_command(statement, redactor)
            changed = changed or rewritten is not None
            out.append(statement if rewritten is None else rewritten)
        return "; ".join(out) if changed else text

    # -- the notebook -----------------------------------------------------------------------------

    def _notes(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        ws = self.rt.workspace
        if name == "read":
            value = ws.read(str(args["path"]), int(args.get("offset", 0)))
        elif name == "write":
            append = bool(args.get("append", False))
            value = ws.write(str(args["path"]), args["text"], append)
            if append:
                value = self._recheck(value)
        elif name == "edit":
            value = self._recheck(ws.edit(str(args["path"]), args["old"], args["new"]))
        elif name == "search":
            value = ws.search(args["query"])
        elif name == "list":
            value = ws.list()
        elif name == "delete":
            value = ws.delete(str(args["path"]))
        else:
            return _failure("AttributeError", f"notes has no function called {name!r}")
        return {"ok": True, "value": value}

    def _recheck(self, stored: dict[str, Any]) -> dict[str, Any]:
        """A file that was added to or edited, hidden again if the pieces written so far (each too
        short to be recognised alone) add up to a secret."""
        ws = self.rt.workspace
        path = str(stored["path"])
        text = ws.read_text(path)
        cleaned = self.rt.toolbox.redactor.redact(text)
        if cleaned == text:
            return stored
        try:
            return ws.write(path, cleaned, False)
        except CommandError:  # no room for the hidden text: keep nothing
            ws.delete(path)
            raise CommandError(
                "bad_text", "That file would hold a secret and was removed."
            ) from None


class _HideLiterals(ast.NodeTransformer):
    """Replaces what a command holds that is a secret once Python has read it: strings, byte
    strings, whole numbers, words and argument names."""

    def __init__(self, redactor: Redactor) -> None:
        self.redactor = redactor
        self.changed = False

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        value = node.value
        if isinstance(value, bytes):
            text = value.decode("utf-8", errors="replace")
        elif isinstance(value, str):
            text = value
        elif isinstance(value, int) and not isinstance(value, bool):
            try:
                text = str(value)
            except ValueError:  # more digits than Python shows
                return node
        else:
            return node
        cleaned = self.redactor.redact(text)
        if cleaned == text:
            return node
        self.changed = True
        return ast.copy_location(ast.Constant(value=cleaned), node)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if self.redactor.redact(node.id) == node.id:
            return node
        self.changed = True
        return ast.copy_location(ast.Name(id="hidden", ctx=node.ctx), node)

    def visit_keyword(self, node: ast.keyword) -> ast.AST:
        if node.arg is not None and self.redactor.redact(node.arg) != node.arg:
            self.changed = True
            node = ast.copy_location(ast.keyword(arg="hidden", value=node.value), node)
        return self.generic_visit(node)


def _hide_in_command(statement: str, redactor: Redactor) -> str | None:
    """The statement written out again with its secrets hidden, or None when it holds none (or
    cannot be read: the game says so, quoting the text as it was written)."""
    try:
        tree = ast.parse(statement, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    try:
        hider = _HideLiterals(redactor)
        tree = hider.visit(tree)
        if not hider.changed:
            return None
        return ast.unparse(ast.fix_missing_locations(tree))
    except RecursionError:
        return "hidden"  # too deep to write out again, and it held a secret or too much


def _failure(kind: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"type": kind, "message": message}}


def _count_commands(text: str) -> int:
    try:
        return max(len(coerce_request(text)), 1)
    except CommandError:
        return 1  # a request that cannot be read is one wasted step


def wire(answer: dict[str, Any]) -> dict[str, Any]:
    """An answer as a program gets it: the answer plus `ok` and `text`, with the screenshot
    reduced to its size (a program cannot look at pictures)."""
    out = with_text(answer)
    observation = dict(out.get("observation", {}))
    shot = observation.get("screenshot")
    if shot:
        observation["screenshot"] = {k: v for k, v in shot.items() if k != "data_base64"}
    out["observation"] = observation
    return out


# -- running jobs --------------------------------------------------------------------------------


def sdk_commands() -> list[dict[str, Any]]:
    """The game commands as the box needs to know them (`game.<name>`), from the tool schemas."""
    out: list[dict[str, Any]] = []
    for schema in tool_schemas():
        if schema["name"] in MEMORY_COMMANDS:
            continue
        props = schema["inputSchema"]["properties"]
        required = set(schema["inputSchema"].get("required", []))
        out.append(
            {
                "name": schema["name"],
                "summary": schema["description"],
                "params": [
                    {"name": k, "doc": v.get("description", ""), "required": k in required}
                    for k, v in props.items()
                ],
            }
        )
    return out


class CodeRuntime:
    """Runs the player's code for the layers that need to (one per game)."""

    def __init__(self, ctx: LayerContext) -> None:
        self.ctx = ctx
        self.toolbox = ctx.toolbox
        self.workspace = ctx.workspace
        self.limits = DEFAULT_LIMITS
        self.sdk = sdk_commands()
        self.command_names = {c["name"] for c in self.sdk}

    @property
    def session(self) -> Any:
        return self.ctx.session

    def run(self, kind: str, *, cap: int, label: str, **fields: Any) -> ProgramReport:
        """Run one job in the box and collect what came of it."""
        session = self.session
        bridge = Bridge(self, cap)
        steps_before = session.decisions
        was_over = session.over
        job = {"kind": kind, "commands": self.sdk, **fields}
        sandbox = Sandbox(
            libs=self.workspace.libs_dir, limits=self.limits, redactor=self.toolbox.redactor
        )
        result = sandbox.run(job, bridge)
        if result.learned:  # what it wrote before the redactor knew of a secret is cleaned now
            self.workspace.scrub(self.toolbox.redactor.redact)
        report = self._report(result, bridge)
        report.steps = session.decisions - steps_before
        report.first_decision = steps_before + 1
        report.ended = None if was_over else (session.over_reason if session.over else None)
        if self.ctx.logs is not None:
            self.ctx.logs.transcript(
                "code_run",
                label=label,
                job=kind,
                ok=report.ok,
                limit=report.limit,
                commands=report.commands,
                steps=report.steps,
                first_decision=report.first_decision,
                ended=report.ended,
                seconds=report.wall_seconds,
                peak_mb=report.peak_mb,
                error=report.error[-400:] if report.error else "",
            )
        return report

    def _report(self, result: JobResult, bridge: Bridge) -> ProgramReport:
        """What the box says about the job. The box is not trusted: nothing it says is used
        before its type and size have been checked."""
        done = result.done or {}
        room = self.limits.output_chars
        stdout, stdout_cut = _bounded_text(done.get("stdout"), room)
        error, _ = _bounded_text(done.get("error"), room)
        report = ProgramReport(
            ok=done.get("ok") is True and result.limit is None,
            error=error,
            limit=result.limit,
            detail=result.detail,
            stdout=stdout,
            stdout_truncated=stdout_cut or done.get("stdout_truncated") is True,
            commands=bridge.commands,
            last_stop=bridge.last_stop,
            load_errors=_text_map(done.get("load_errors"), room),
            described=done.get("described") if isinstance(done.get("described"), dict) else None,
            wall_seconds=result.wall_seconds,
            peak_mb=result.peak_mb,
        )
        raw = done.get("value_json")
        if isinstance(raw, str):
            report.has_value = True
            report.value = _read_value(raw)
        return report

    def render(self, report: ProgramReport, *, subject: str = "The program") -> ToolOutput:
        """The report as the player reads it: what happened, what it printed, and (if it played)
        the view after its last command."""
        lines: list[str] = []
        if report.limit:
            lines.append(f"{subject} was stopped: {report.detail}.")
        elif not report.ok:
            lines.append(f"{subject} stopped with an error.")
        else:
            lines.append(f"{subject} finished.")
        if report.ended:
            lines.append(f"The game ended while it was running ({report.ended}).")
        if report.has_value and report.value is not None:
            shown = report.value if isinstance(report.value, str) else _compact(report.value)
            lines.append(f"It returned: {shown}")
        if report.stdout:
            cut = "\n... (cut: it printed too much)" if report.stdout_truncated else ""
            lines.append(f"It printed:\n{report.stdout.rstrip()}{cut}")
        if report.error:
            lines.append(report.error)
        for name, problem in report.load_errors.items():
            lines.append(f"Plugin {name} could not be loaded:\n{problem}")
        if report.commands:
            lines.append(_commands_line(report))
        images: tuple[bytes, ...] = ()
        if report.commands:
            view = self.session.observe()
            lines.append(render_text(view))
            images = screenshot_of(view)
        failed = bool(report.limit) or not report.ok
        return ToolOutput("\n".join(lines), images, is_error=failed)

    # -- the tool ---------------------------------------------------------------------------------

    def run_code_tool(self, args: dict[str, Any]) -> ToolOutput:
        code = args["code"]
        if not isinstance(code, str) or not code.strip():
            raise ValueError("`code` must be a non-empty string")
        if len(code) > MAX_CODE_CHARS:
            raise ValueError(f"the program is too long: at most {MAX_CODE_CHARS} characters")
        try:
            report = self.run("code", cap=COMMAND_CAP, label="run_code", code=code)
        except HarnessError as err:
            return ToolOutput(f"The program could not be run: {err}", is_error=True)
        return self.render(report)


def _commands_line(report: ProgramReport) -> str:
    text = f"Game commands run: {report.commands}. Steps used: {report.steps}."
    stop = report.last_stop
    if stop:
        detail = f" ({stop['detail']})" if stop.get("detail") else ""
        text += f" The last command stopped: {stop['reason']}{detail}."
    return text


def _compact(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError):  # a value that the box built to break this
        return reprlib.repr(value)


def _bounded_text(value: Any, cap: int) -> tuple[str, bool]:
    """`(text, was_cut)` for something the code reported: anything but text is ignored."""
    if not isinstance(value, str):
        return "", False
    return (value[:cap], True) if len(value) > cap else (value, False)


def _text_map(value: Any, cap: int) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k)[:80]: _bounded_text(v, cap)[0] for k, v in list(value.items())[:50]}


def _read_value(raw: str) -> Any:
    """The value a plugin tool returned. The box writes valid JSON, but the box is not trusted:
    anything that does not read, or nests too deeply, is shown as the text it is."""
    try:
        value = json.loads(raw)
        json.dumps(value)  # nested too deeply to show is as bad as nested too deeply to read
        return value
    except (ValueError, RecursionError):
        return raw[:MAX_VALUE_CHARS]


def runtime_of(ctx: LayerContext) -> CodeRuntime:
    """The one `CodeRuntime` of this game (made by whichever code layer registers first)."""
    runtime = ctx.extras.get("code_runtime")
    if runtime is None:
        runtime = ctx.extras["code_runtime"] = CodeRuntime(ctx)
    assert isinstance(runtime, CodeRuntime)
    return runtime


def register_l2(ctx: LayerContext) -> None:
    runtime = runtime_of(ctx)
    spec = ToolSpec(
        "run_code",
        RUN_CODE_DESCRIPTION,
        object_schema(
            {
                "code": {
                    "type": "string",
                    "description": f"The Python program (at most {MAX_CODE_CHARS} characters).",
                }
            },
            ["code"],
        ),
    )
    ctx.toolbox.register(ToolDef(spec, FREE, runtime.run_code_tool, acts=True))
