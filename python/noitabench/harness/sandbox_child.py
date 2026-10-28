"""The program that runs INSIDE the box (see `sandbox.py`). It is handed to the interpreter as
`python -I -B -c <this source>`, so it cannot import anything from this package and must stay
self-contained (standard library only).

It reads one `job` message from the pipe it was started with, runs the player's code and answers
with one `done` message. While the code runs, every use of the game or the notebook is a request
to the other side: `{"op": "call", "id", "target", "name", "args"}` out, `{"id", "ok", "value" |
"error"}` back. Nothing else leaves the box. All messages are single JSON lines.

Jobs (`job["kind"]`):

    code         run `job["code"]` with `game` and `notes` in scope (Code Mode and hook scripts);
                 `job["event"]`, when given, is in scope as `event`
    describe     load every plugin in `job["plugins"]` and report the tools, hooks and prompt
                 fragments they declare (nothing may touch the game while loading)
    plugin_call  load the plugins, then run the tool `job["tool"]` with `job["args"]`
    plugin_hook  load the plugins, then run the hook function `job["function"]` of plugin
                 `job["plugin"]` with `job["event"]`

The module-level code of a plugin may only declare things; `game` and `notes` work inside its
functions.
"""

from __future__ import annotations

import builtins
import inspect
import io
import json
import linecache
import os
import sys
import traceback
import types
from typing import Any

BLOCKED_MODULES = ("noitabench", "noitabench_core")
MAX_VALUE_CHARS = 50_000
LOAD_SECONDS = 1.0  # a plugin must be read in this time, so that one cannot hold up the others


class GameOver(Exception):
    """The game ended during a game command; `answer` is that command's answer."""

    def __init__(self, answer: dict[str, Any]) -> None:
        super().__init__(f"The game is over ({answer.get('over')}).")
        self.answer = answer


class LimitReached(Exception):
    """A limit of the program was reached (for example the number of game commands)."""


class NotesError(Exception):
    """The notebook refused an operation; the message starts with its code."""


class Unavailable(Exception):
    """A game or notebook call at a time when it is not allowed (while a plugin loads)."""


ERRORS: dict[str, type[Exception]] = {
    "LimitReached": LimitReached,
    "NotesError": NotesError,
    "Unavailable": Unavailable,
}


class Capture(io.TextIOBase):
    """What the program prints, up to a cap."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.parts: list[str] = []
        self.size = 0
        self.truncated = False

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:  # type: ignore[override]
        room = self.cap - self.size
        if len(text) <= room:
            self.parts.append(text)
            self.size += len(text)
        else:
            if room > 0:
                self.parts.append(text[:room])
                self.size += room
            self.truncated = True
        return len(text)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return "".join(self.parts)


class Channel:
    """The pipe to the other side."""

    def __init__(self, source: Any, sink: Any) -> None:
        self.source = source
        self.sink = sink
        self.next_id = 0

    def send(self, message: dict[str, Any]) -> None:
        self.sink.write(json.dumps(message, ensure_ascii=True, default=repr) + "\n")
        self.sink.flush()

    def receive(self) -> dict[str, Any]:
        line = self.source.readline()
        if not line:
            os._exit(3)  # the other side went away
        loaded: dict[str, Any] = json.loads(line)
        return loaded

    def call(self, target: str, name: str, args: dict[str, Any]) -> Any:
        self.next_id += 1
        self.send({"op": "call", "id": self.next_id, "target": target, "name": name, "args": args})
        reply = self.receive()
        if not reply.get("ok"):
            error = reply.get("error") or {}
            raise ERRORS.get(error.get("type", ""), RuntimeError)(error.get("message", "failed"))
        if reply.get("over"):
            raise GameOver(reply["value"])
        return reply["value"]


class State:
    """What the player's code is allowed to do right now."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel
        self.loading = False  # a plugin's module-level code is running

    def call(self, target: str, name: str, args: dict[str, Any]) -> Any:
        if self.loading:
            raise Unavailable(
                "The game and the notebook cannot be used while a plugin is loading: "
                "use them inside the functions of the plugin."
            )
        return self.channel.call(target, name, args)


# -- the `game` and `notes` modules ----------------------------------------------------------------


def make_game_module(commands: list[dict[str, Any]], state: State) -> types.ModuleType:
    module = types.ModuleType("game")
    module.__doc__ = (
        "One function per game command, with the arguments of the command. Each call is one step "
        "and returns a dict: `ok`, `stop`, `results`, `events`, `observation`, and `text` (what "
        "you would read). `game.decide('a; b')` runs up to four commands as one step; "
        "`game.observe()` shows the current view and takes no game time."
    )
    for spec in commands:
        setattr(module, spec["name"], make_command(spec, state))

    def decide(text: str) -> dict[str, Any]:
        """Run up to four commands, written like `aim(target=4); fire(until=target_dead)`, as
        one step."""
        result: dict[str, Any] = state.call("game", "decide", {"text": text})
        return result

    def observe() -> dict[str, Any]:
        """The current answer again, with the view as it is now. Takes no game time."""
        result: dict[str, Any] = state.call("game", "observe", {})
        return result

    module.decide = decide  # type: ignore[attr-defined]
    module.observe = observe  # type: ignore[attr-defined]
    module.GameOver = GameOver  # type: ignore[attr-defined]
    module.LimitReached = LimitReached  # type: ignore[attr-defined]
    return module


def make_command(spec: dict[str, Any], state: State) -> Any:
    names = [p["name"] for p in spec["params"]]
    name = spec["name"]

    def command(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if len(args) > len(names):
            raise TypeError(f"{name}() takes at most {len(names)} positional arguments")
        merged = dict(zip(names, args, strict=False))
        for key, value in kwargs.items():
            if key in merged:
                raise TypeError(f"{name}() got multiple values for argument {key!r}")
            merged[key] = value
        result: dict[str, Any] = state.call(
            "game", name, {k: v for k, v in merged.items() if v is not None}
        )
        return result

    command.__name__ = name
    command.__qualname__ = f"game.{name}"
    lines = [spec["summary"], ""]
    lines += [f"{p['name']}: {p['doc']}" for p in spec["params"] if p.get("doc")]
    command.__doc__ = "\n".join(lines)
    command.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [inspect.Parameter(n, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None) for n in names]
    )
    return command


def make_notes_module(state: State) -> types.ModuleType:
    module = types.ModuleType("notes")
    module.__doc__ = (
        "Your notebook: read(path), write(path, text, append=False), edit(path, old, new), "
        "search(query), list(), delete(path). Errors raise notes.NotesError."
    )

    def read(path: str, offset: int = 0) -> dict[str, Any]:
        """Read a file (long files are read in parts with `offset`)."""
        return _notes(state, "read", {"path": path, "offset": offset})

    def write(path: str, text: str, append: bool = False) -> dict[str, Any]:
        """Write a file, replacing it or adding to its end."""
        return _notes(state, "write", {"path": path, "text": text, "append": append})

    def edit(path: str, old: str, new: str) -> dict[str, Any]:
        """Replace one piece of text; `old` must occur exactly once."""
        return _notes(state, "edit", {"path": path, "old": old, "new": new})

    def search(query: str) -> dict[str, Any]:
        """Search all files for a word or phrase."""
        return _notes(state, "search", {"query": query})

    def list_files() -> dict[str, Any]:
        """The files with their sizes and the room that is left."""
        return _notes(state, "list", {})

    def delete(path: str) -> dict[str, Any]:
        """Delete a file."""
        return _notes(state, "delete", {"path": path})

    list_files.__name__ = "list"
    for fn in (read, write, edit, search, delete):
        setattr(module, fn.__name__, fn)
    module.list = list_files  # type: ignore[attr-defined]
    module.NotesError = NotesError  # type: ignore[attr-defined]
    return module


def _notes(state: State, name: str, args: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = state.call("notes", name, args)
    return result


# -- plugins ---------------------------------------------------------------------------------------


class Registry:
    """What the loaded plugins declared."""

    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}
        self.hooks: list[dict[str, Any]] = []
        self.prompts: dict[str, str] = {}
        self.errors: dict[str, str] = {}
        self.current = ""


def make_plugin_module(registry: Registry) -> types.ModuleType:
    module = types.ModuleType("plugin")
    module.__doc__ = "tool(description, schema=None) and hook(event, value=None) decorators."

    def tool(
        description: str, schema: dict[str, Any] | None = None, name: str | None = None
    ) -> Any:
        def register(fn: Any) -> Any:
            key = name or fn.__name__
            if key in registry.tools:
                first = registry.tools[key]["plugin"]
                note = f"Tool `{key}` is already declared by plugin {first}."
                registry.errors[registry.current] = "\n".join(
                    filter(None, [registry.errors.get(registry.current, ""), note])
                )
                return fn
            registry.tools[key] = {
                "name": key,
                "description": description,
                "schema": schema,
                "plugin": registry.current,
                "fn": fn,
            }
            return fn

        return register

    def hook(event: str, value: float | None = None) -> Any:
        def register(fn: Any) -> Any:
            registry.hooks.append(
                {
                    "event": event,
                    "value": value,
                    "plugin": registry.current,
                    "function": fn.__name__,
                    "fn": fn,
                }
            )
            return fn

        return register

    module.tool = tool  # type: ignore[attr-defined]
    module.hook = hook  # type: ignore[attr-defined]
    return module


def load_plugins(
    sources: dict[str, str], registry: Registry, scope: dict[str, Any], state: State
) -> None:
    """Run the module-level code of every plugin; a plugin that fails is recorded, not fatal."""
    import signal

    def too_slow(_signal: int, _frame: Any) -> None:
        raise TimeoutError(f"the plugin took longer than {LOAD_SECONDS:g} seconds to load")

    state.loading = True
    signal.signal(signal.SIGALRM, too_slow)
    try:
        for name in sorted(sources):
            registry.current = name
            namespace = dict(scope, __name__=f"plugin_{name}")
            filename = f"<plugin {name}>"
            register_source(filename, sources[name])
            try:
                signal.setitimer(signal.ITIMER_REAL, LOAD_SECONDS)
                exec(compile(sources[name], filename, "exec"), namespace)  # noqa: S102
            except BaseException as exc:  # noqa: BLE001 - a broken plugin is reported
                registry.errors[name] = format_error(exc)
                continue
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            fragment = namespace.get("prompt_fragment")
            if isinstance(fragment, str) and fragment.strip():
                registry.prompts[name] = fragment.strip()
    finally:
        state.loading = False
        registry.current = ""


def describe(registry: Registry) -> dict[str, Any]:
    return {
        "tools": [{k: v for k, v in t.items() if k != "fn"} for t in registry.tools.values()],
        "hooks": [{k: v for k, v in h.items() if k != "fn"} for h in registry.hooks],
        "prompts": registry.prompts,
        "errors": registry.errors,
    }


# -- running the code ------------------------------------------------------------------------------


def register_source(filename: str, source: str) -> None:
    """Make the lines of the player's code available to tracebacks."""
    lines = source.splitlines(keepends=True)
    linecache.cache[filename] = (len(source), None, lines, filename)


def format_error(exc: BaseException) -> str:
    """The error as the player should read it: its own lines only, never ours."""
    if isinstance(exc, SyntaxError):
        where = f"line {exc.lineno}" if exc.lineno else "the code"
        text = f"\n    {exc.text.strip()}" if exc.text else ""
        return f"SyntaxError: {exc.msg} ({where}){text}"
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename.startswith("<")]
    lines = ["Traceback (most recent call last):"] if frames else []
    for frame in frames:
        lines.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}')
        if frame.line:
            lines.append(f"    {frame.line.strip()}")
    message = str(exc)
    lines.append(f"{type(exc).__name__}: {message}" if message else type(exc).__name__)
    return "\n".join(lines)


def limit_resources(limits: dict[str, Any]) -> None:
    import resource

    cpu = int(limits["cpu_seconds"])
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    fsize = int(limits["file_bytes"])
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    nofile = int(limits["open_files"])
    resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))  # not to be raised again


class Blocker:
    """Keeps the program from importing the game itself (it could not read it anyway)."""

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> None:
        if name.split(".")[0] in BLOCKED_MODULES:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)


def run_code(job: dict[str, Any], scope: dict[str, Any]) -> Any:
    namespace = dict(scope, __name__="__main__")
    if "event" in job:
        namespace["event"] = job["event"]
    register_source("<run_code>", job["code"])
    exec(compile(job["code"], "<run_code>", "exec"), namespace)  # noqa: S102
    return None


def run_plugin_tool(job: dict[str, Any], registry: Registry) -> Any:
    entry = registry.tools.get(job["tool"])
    if entry is None:
        known = ", ".join(sorted(registry.tools)) or "none"
        raise LookupError(f"there is no plugin tool called {job['tool']!r} (tools: {known})")
    return entry["fn"](job.get("args") or {})


def run_plugin_hook(job: dict[str, Any], registry: Registry) -> Any:
    for entry in registry.hooks:
        if entry["plugin"] == job["plugin"] and entry["function"] == job["function"]:
            return entry["fn"](job.get("event") or {})
    raise LookupError(f"plugin {job['plugin']!r} has no hook function {job['function']!r}")


def execute(job: dict[str, Any], state: State, out: Capture) -> dict[str, Any]:
    game = make_game_module(job.get("commands", []), state)
    notes = make_notes_module(state)
    registry = Registry()
    plugin = make_plugin_module(registry)
    for name, module in (("game", game), ("notes", notes), ("plugin", plugin)):
        sys.modules[name] = module
    scope: dict[str, Any] = {
        "game": game,
        "notes": notes,
        "tool": plugin.tool,  # type: ignore[attr-defined]
        "hook": plugin.hook,  # type: ignore[attr-defined]
        "__builtins__": builtins,
    }
    result: dict[str, Any] = {"ok": True, "ended": False}
    try:
        kind = job["kind"]
        if kind == "code":
            run_code(job, scope)
        else:
            load_plugins(job.get("plugins", {}), registry, scope, state)
            if kind == "describe":
                result["described"] = describe(registry)
            elif kind == "plugin_call":
                result["value"] = run_plugin_tool(job, registry)
                failed = registry.errors
                if failed:
                    result["load_errors"] = failed
            elif kind == "plugin_hook":
                result["value"] = run_plugin_hook(job, registry)
            else:
                raise ValueError(f"unknown job kind {kind!r}")
    except GameOver:
        result["ended"] = True
    except SystemExit:
        pass
    except BaseException as exc:  # noqa: BLE001 - whatever the code did is reported
        result["ok"] = False
        result["error"] = format_error(exc)
        if job.get("kind") == "plugin_call" and registry.errors:
            result["load_errors"] = registry.errors
    return result


def finish(channel: Channel, result: dict[str, Any], out: Capture) -> None:
    value = result.pop("value", None)
    try:
        shown = json.dumps(value, ensure_ascii=False, default=repr)
    except (TypeError, ValueError, RecursionError):  # not JSON, or nested too deeply
        try:
            shown = json.dumps(repr(value), ensure_ascii=False)
        except RecursionError:
            shown = json.dumps(f"<a {type(value).__name__} that cannot be shown>")
    if len(shown) > MAX_VALUE_CHARS:  # what the other side reads is always valid JSON
        shown = json.dumps(shown[:MAX_VALUE_CHARS] + " ...", ensure_ascii=False)
        result["value_truncated"] = True
    result["value_json"] = shown if value is not None else None
    result["stdout"] = out.getvalue()
    result["stdout_truncated"] = out.truncated
    channel.send({"op": "done", **result})


def main() -> None:
    source = os.fdopen(os.dup(0), "r", encoding="utf-8", newline="\n")
    sink = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, 0)
    os.dup2(null, 1)
    channel = Channel(source, sink)
    job = channel.receive()
    out = Capture(int(job["limits"]["output_chars"]))
    sys.stdout = sys.stderr = out
    limit_resources(job["limits"])
    sys.meta_path.insert(0, Blocker())  # type: ignore[arg-type]
    libs = job.get("libs")
    if libs:
        sys.path.insert(0, libs)
    state = State(channel)
    try:
        result = execute(job, state, out)
    except BaseException as exc:  # noqa: BLE001 - never die without saying why
        result = {"ok": False, "ended": False, "error": f"internal error: {type(exc).__name__}"}
    finish(channel, result, out)
    sink.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
