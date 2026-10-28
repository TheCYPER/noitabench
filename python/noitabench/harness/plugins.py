"""L5, plugins: the player adds tools, hooks and instructions of its own.

A plugin is one Python file, `plugins/<name>.py` in the notebook. In it:

    @tool("what it does", {"type": "object", "properties": {...}})   # schema is optional
    def my_tool(args): ...                  # args: a dict; returns text or JSON
    @hook("new_material")                   # `@hook("hp_below", 30)` for hp_below
    def on_new_material(event): ...         # event: {"name", "message", "decision"}
    prompt_fragment = "a reminder for myself"      # at most 600 characters

Inside the functions `game` and `notes` work as in Code Mode (`codemode.py`); at the top of the
file they do not (the file is only read to see what it declares). A plugin cannot import
another plugin, the game or the harness.

The tool list of a run is fixed before the first model call (prompt caching), so plugin tools do
not become tools of their own. They are reached through two fixed ones: `plugin_list` (what the
plugins declare, and what is wrong with them) and `plugin_call(name, args)`. Plugin files are
read in the box whenever they have changed since last read: by `plugin_list`, by `plugin_call`,
and when a conversation is started. Plugin hooks join the hooks of layer L3 (`hooks.py`) when
the plugins are read; without L3 they are listed but do nothing.

*Prompt fragments* are added to the end of the system prompt at the start of a game and whenever
the loop starts a new conversation with a briefing (the `summary` strategy); the conversation
that is running keeps the prompt it has, as its cache depends on it.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from noitabench.agent import CommandError

from .codemode import COMMAND_CAP, CodeRuntime, runtime_of
from .errors import HarnessError
from .hooks import hooks_of
from .libs import Wheelhouse, register_libraries
from .model import ToolSpec
from .prompt import PLUGIN_CALL_DESCRIPTION, PLUGIN_LIST_DESCRIPTION
from .sandbox import Limits
from .toolbox import FREE, ToolDef, ToolOutput, object_schema

if TYPE_CHECKING:
    from .layers import LayerContext

MAX_DESCRIPTION = 400
MAX_SCHEMA_CHARS = 2_000
MAX_FRAGMENT = 600
MAX_FRAGMENTS_TOTAL = 2_000
MAX_ARGS_CHARS = 20_000
MAX_PROBLEM = 2_000  # characters of what is wrong with one plugin
MAX_ENTRIES = 200  # tools (and, apart, hooks) that are read from what the plugins declare
DESCRIBE_LIMITS = Limits(cpu_seconds=3, wall_seconds=5.0, total_seconds=20.0, memory_mb=256)
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


class PluginManager:
    """What the plugins of a game declare, kept up to date with the files."""

    def __init__(self, runtime: CodeRuntime, ctx: LayerContext) -> None:
        self.rt = runtime
        self.ctx = ctx
        self.tools: dict[str, dict[str, Any]] = {}
        self.hooks: list[dict[str, Any]] = []
        self.fragments: dict[str, str] = {}
        self.problems: dict[str, str] = {}
        self._seen: tuple[dict[str, str], dict[str, str]] | None = None  # sources, libraries

    # -- reading the files ---------------------------------------------------------------------

    def refresh(self) -> None:
        """Read the plugins again if any file changed since the last time."""
        sources = self.rt.workspace.plugin_sources()
        stamp = (
            sources,
            Wheelhouse.installed_in(self.rt.workspace.libs_dir),
        )  # imports may need libs
        if stamp == self._seen:
            return
        self._seen = stamp
        self.tools, self.hooks, self.fragments, self.problems = {}, [], {}, {}
        if sources:
            self._describe(sources)
        engine = hooks_of(self.ctx)
        if engine is not None:
            engine.set_plugin_hooks(self.hooks)

    def _describe(self, sources: dict[str, str]) -> None:
        saved = self.rt.limits
        self.rt.limits = DESCRIBE_LIMITS
        try:
            report = self.rt.run("describe", cap=0, label="plugin_list", plugins=sources)
        except HarnessError as err:
            self.problems["*"] = f"The plugins could not be read: {err}"
            return
        finally:
            self.rt.limits = saved
        if report.limit or report.described is None:
            why = report.detail or report.error or "unknown reason"
            self.problems["*"] = f"The plugins could not be read: {why}"
            return
        self._take(report.described)

    def _take(self, described: dict[str, Any]) -> None:
        """Take over what the box says the plugins declare. The box is not trusted: every part
        is checked for its shape and size, and what does not fit is left out."""
        errors = described.get("errors")
        if isinstance(errors, dict):
            self.problems.update({str(k)[:80]: str(v)[:MAX_PROBLEM] for k, v in errors.items()})
        for entry in _entries(described.get("tools")):
            name = str(entry.get("name", ""))
            plugin = str(entry.get("plugin", ""))[:80]
            if not _TOOL_NAME.match(name):
                self.problems[plugin] = (
                    f"{self.problems.get(plugin, '')}\nTool name `{name[:60]}` is not allowed: "
                    "use lowercase letters, digits and `_`, starting with a letter."
                ).strip()
            elif name in self.tools:
                self.problems[plugin] = (
                    f"{self.problems.get(plugin, '')}\nTool `{name}` is already declared by "
                    f"plugin {self.tools[name]['plugin']}."
                ).strip()
            else:
                self.tools[name] = {
                    "name": name,
                    "plugin": plugin,
                    "description": str(entry.get("description", ""))[:MAX_DESCRIPTION],
                    "schema": _clean_schema(entry.get("schema")),
                }
        for entry in _entries(described.get("hooks")):
            if isinstance(entry.get("plugin"), str) and isinstance(entry.get("function"), str):
                self.hooks.append(entry)
        prompts = described.get("prompts")
        total = 0
        for plugin, text in sorted(prompts.items()) if isinstance(prompts, dict) else []:
            clipped = str(text).strip()[:MAX_FRAGMENT]
            if clipped and total + len(clipped) <= MAX_FRAGMENTS_TOTAL:
                self.fragments[str(plugin)[:80]] = clipped
                total += len(clipped)

    # -- the tools --------------------------------------------------------------------------------

    def list_plugins(self, _args: dict[str, Any]) -> dict[str, Any]:
        self.refresh()
        by_plugin: dict[str, dict[str, Any]] = {}
        for name in sorted(self.rt.workspace.plugin_sources()):
            by_plugin[name] = {"tools": [], "hooks": []}
        for tool in self.tools.values():
            entry = by_plugin.setdefault(tool["plugin"], {"tools": [], "hooks": []})
            entry["tools"].append(
                {"name": tool["name"], "description": tool["description"], "schema": tool["schema"]}
            )
        for hook in self.hooks:
            entry = by_plugin.setdefault(hook["plugin"], {"tools": [], "hooks": []})
            entry["hooks"].append(
                {"event": hook["event"], "value": hook.get("value"), "function": hook["function"]}
            )
        out: dict[str, Any] = {"plugins": by_plugin}
        if self.fragments:
            out["prompt_fragments"] = self.fragments
            out["note"] = (
                "Prompt fragments are added to your instructions when your conversation is next "
                "started again with a briefing."
            )
        if self.problems:
            out["problems"] = self.problems
        if not by_plugin:
            out["note"] = "There are no plugins yet: write plugins/<name>.py."
        if self.hooks and hooks_of(self.ctx) is None:
            out["hooks_note"] = "Hooks in plugins do nothing without hook_set."
        return out

    def call(self, args: dict[str, Any]) -> ToolOutput:
        name = args["name"]
        if not isinstance(name, str):
            raise TypeError("`name` must be the name of a tool")
        given = args.get("args", {})
        if not isinstance(given, dict):
            raise TypeError("`args` must be an object")
        try:
            too_long = len(json.dumps(given, default=repr)) > MAX_ARGS_CHARS
        except (TypeError, ValueError, RecursionError):
            too_long = True  # nested too deeply to be arguments
        if too_long:
            raise ValueError("`args` is too long")
        self.refresh()
        if name not in self.tools:
            known = ", ".join(sorted(self.tools)) or "none"
            text = f"There is no plugin tool called `{name}`. Plugin tools: {known}."
            if self.problems:
                text += " Some plugins have problems; plugin_list shows them."
            return ToolOutput(text, is_error=True)
        try:
            report = self.rt.run(
                "plugin_call",
                cap=COMMAND_CAP,
                label=f"plugin {name}",
                plugins=self.rt.workspace.plugin_sources(),
                tool=name,
                args=given,
            )
        except HarnessError as err:
            return ToolOutput(f"The plugin tool could not be run: {err}", is_error=True)
        return self.rt.render(report, subject="The plugin tool")

    def system_suffix(self) -> str:
        """The prompt fragments of the plugins, for the end of a system prompt."""
        try:
            self.refresh()
        except (HarnessError, CommandError):  # pragma: no cover - never block a conversation
            return ""
        if not self.fragments:
            return ""
        lines = "".join(f"- {text}\n" for _, text in sorted(self.fragments.items()))
        return f"\nNOTES YOU LEFT IN YOUR PLUGINS\n{lines}"


def _entries(value: Any) -> list[dict[str, Any]]:
    """The dicts among the first `MAX_ENTRIES` items of a list the box reported."""
    if not isinstance(value, list):
        return []
    return [item for item in value[:MAX_ENTRIES] if isinstance(item, dict)]


def _clean_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return dict(_EMPTY_SCHEMA)
    try:
        if len(json.dumps(schema, default=repr)) > MAX_SCHEMA_CHARS:
            return dict(_EMPTY_SCHEMA)
    except (TypeError, ValueError, RecursionError):
        return dict(_EMPTY_SCHEMA)
    return schema


def register_l5(ctx: LayerContext) -> None:
    runtime = runtime_of(ctx)
    manager = PluginManager(runtime, ctx)
    ctx.extras["plugins"] = manager
    ctx.toolbox.add_system_suffix(manager.system_suffix)
    ctx.toolbox.register(
        ToolDef(
            ToolSpec("plugin_list", PLUGIN_LIST_DESCRIPTION, object_schema({})),
            FREE,
            manager.list_plugins,
        )
    )
    ctx.toolbox.register(
        ToolDef(
            ToolSpec(
                "plugin_call",
                PLUGIN_CALL_DESCRIPTION,
                object_schema(
                    {
                        "name": {"type": "string", "description": "The name of the tool."},
                        "args": {
                            "type": "object",
                            "description": "The arguments, as the tool's schema says.",
                        },
                    },
                    ["name"],
                ),
            ),
            FREE,
            manager.call,
            acts=True,
        )
    )
    register_libraries(ctx)
