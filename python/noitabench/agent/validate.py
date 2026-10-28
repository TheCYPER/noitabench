"""Checking commands: raw arguments (from JSON or from the text grammar) become a `Command` with
normalised arguments, or `CommandError`, which the session returns to the agent as data."""

from __future__ import annotations

import math
import reprlib
from collections.abc import Callable, Mapping
from typing import Any

from .errors import CommandError
from .spec import (
    AMOUNT,
    BOOL,
    COMMANDS,
    DIRECTION_ALIASES,
    ENUM,
    INT,
    NUMBER,
    STR,
    TARGET,
    Command,
    CommandSpec,
    Param,
)
from .vocab import EVENT_TYPES, MAX_TICKS, UNTIL_KEYS

FLAGS = ("blocked", "landed", "target_dead", "mana_empty", "edge")
WALKING = ("move", "walk_to")  # the commands `until=edge` makes sense for
MAX_NAME = 40  # characters of a command name that are echoed back


def _fail(command: str, name: str, message: str) -> CommandError:
    return CommandError("bad_argument", f"{command}: `{name}` {message}")


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _out_of_range(v: float, lo: float | None, hi: float | None) -> bool:
    return (lo is not None and v < lo) or (hi is not None and v > hi)


def _bounds(lo: float | None, hi: float | None) -> str:
    if lo is not None and hi is not None:
        return f"between {lo:g} and {hi:g}"
    return f"at least {lo:g}" if lo is not None else f"at most {hi:g}"


def _coerce_int(command: str, name: str, v: Any, lo: float | None, hi: float | None) -> int:
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        v = int(v)
    if not isinstance(v, int) or isinstance(v, bool):
        raise _fail(command, name, f"must be a whole number, got {reprlib.repr(v)}")
    if _out_of_range(v, lo, hi):
        raise _fail(command, name, f"must be {_bounds(lo, hi)}, got {v}")
    return v


def _coerce_number(
    command: str, name: str, v: Any, lo: float | None, hi: float | None
) -> int | float:
    if not _is_number(v):
        raise _fail(command, name, f"must be a number, got {reprlib.repr(v)}")
    if _out_of_range(v, lo, hi):
        raise _fail(command, name, f"must be {_bounds(lo, hi)}, got {v}")
    return int(v) if float(v).is_integer() and abs(v) < 2**31 else float(v)


def _coerce_enum(command: str, name: str, v: Any, choices: tuple[str, ...]) -> str:
    if v is None:  # the bare word `none` of the text grammar (and JSON null) is the word "none"
        v = "none"
    key = str(v).strip().lower() if isinstance(v, (str, int)) and not isinstance(v, bool) else ""
    if set(choices) <= {"left", "right", "up"}:
        key = DIRECTION_ALIASES.get(key, key)
    if key not in choices:
        raise _fail(command, name, f"must be one of {', '.join(choices)}, got {reprlib.repr(v)}")
    return key


def _coerce(command: str, p: Param, v: Any) -> Any:
    if p.kind == INT:
        return _coerce_int(command, p.name, v, p.minimum, p.maximum)
    if p.kind == NUMBER:
        return _coerce_number(command, p.name, v, p.minimum, p.maximum)
    if p.kind == BOOL:
        if not isinstance(v, bool):
            raise _fail(command, p.name, f"must be true or false, got {reprlib.repr(v)}")
        return v
    if p.kind == STR:
        if not isinstance(v, str):
            raise _fail(command, p.name, f"must be text, got {reprlib.repr(v)}")
        return v
    if p.kind == ENUM:
        return _coerce_enum(command, p.name, v, p.choices)
    if p.kind == AMOUNT:
        if isinstance(v, str) and v.strip().lower() == "all":
            return "all"
        return _coerce_int(command, p.name, v, 1, 100_000)
    if p.kind == TARGET:
        if isinstance(v, str) and v.strip():
            return v.strip()
        return _coerce_int(command, p.name, v, 0, None)
    raise AssertionError(f"unhandled parameter kind {p.kind}")  # pragma: no cover


# -- `until` ---------------------------------------------------------------------------------------


def _until_value(command: str, key: str, v: Any) -> Any:
    name = f"until.{key}"
    if key == "ticks":
        return _coerce_int(command, name, v, 1, MAX_TICKS)
    if key == "distance":
        n = _coerce_number(command, name, v, 0.0, 100_000.0)
        if n <= 0:
            raise _fail(command, name, "must be more than 0")
        return n
    if key == "x":
        return _coerce_int(command, name, v, None, None)
    if key == "hp_below":
        return _coerce_number(command, name, v, 0.0, 1_000_000.0)
    if key == "event":
        names = [v] if isinstance(v, str) else v
        if not isinstance(names, (list, tuple)) or not names:
            raise _fail(command, name, "must be an event type or a list of them")
        bad = [n for n in names if n not in EVENT_TYPES]
        if bad:
            raise _fail(
                command,
                name,
                f"has no event type {reprlib.repr(bad[0])}; use one of {', '.join(EVENT_TYPES)}",
            )
        return list(dict.fromkeys(names))
    if not isinstance(v, bool):
        raise _fail(command, name, f"is a flag (true or false), got {reprlib.repr(v)}")
    return v


def _split_until_text(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for part in text.replace("|", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition("=")
        if not sep:
            out[key.strip()] = True
            continue
        out[key.strip()] = _number_or_text(value.strip())
    return out


def _number_or_text(text: str) -> int | float | str:
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            continue
    return text


def normalize_until(command: str, raw: Any) -> dict[str, Any]:
    """The `until` of a command as a plain dict (empty when there is none)."""
    if raw is None or raw is False:
        return {}
    if isinstance(raw, str):
        raw = _split_until_text(raw)
    if isinstance(raw, (list, tuple)):
        merged: dict[str, Any] = {}
        for item in raw:
            merged.update(normalize_until(command, item))
        return merged
    if not isinstance(raw, Mapping):
        raise _fail(
            command, "until", f"must be a condition, a list or an object, got {reprlib.repr(raw)}"
        )
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in UNTIL_KEYS:
            raise _fail(command, "until", f"has no condition `{key}`; use {', '.join(UNTIL_KEYS)}")
        if value is False and key in FLAGS:
            continue
        out[key] = _until_value(command, key, value)
    return out


# -- checks that need several arguments ------------------------------------------------------------


def _one_of(command: str, args: Mapping[str, Any], groups: list[tuple[str, ...]]) -> None:
    """Exactly one group of arguments is given, and all of its names."""
    given = [g for g in groups if any(k in args for k in g)]
    names = " | ".join("+".join(g) for g in groups)
    if len(given) != 1:
        raise CommandError("bad_argument", f"{command}: give exactly one of: {names}")
    missing = [k for k in given[0] if k not in args]
    if missing:
        raise CommandError(
            "bad_argument", f"{command}: `{missing[0]}` is missing (give {'+'.join(given[0])})"
        )


def _check_aim(args: Mapping[str, Any]) -> None:
    _one_of("aim", args, [("angle",), ("x", "y"), ("entity",), ("target",)])


def _check_inspect(args: Mapping[str, Any]) -> None:
    _one_of("inspect", args, [("x", "y"), ("entity",), ("wand",), ("spell",), ("bottle",)])
    if "slot" in args and "wand" not in args:
        raise CommandError("bad_argument", "inspect: `slot` goes with `wand`")


def _check_edit(args: Mapping[str, Any]) -> None:
    need = {"place": ("slot", "spell"), "take": ("slot",), "swap": ("a", "b")}[args["op"]]
    for name in need:
        if name not in args:
            raise CommandError("bad_argument", f"edit_wand: op={args['op']} needs `{name}`")
    extra = [k for k in ("slot", "spell", "a", "b") if k in args and k not in need]
    if extra:
        raise CommandError("bad_argument", f"edit_wand: op={args['op']} does not use `{extra[0]}`")


def _check_drop(args: Mapping[str, Any]) -> None:
    _one_of("drop", args, [("wand",), ("spell",), ("bottle",)])


_CHECKS: dict[str, Callable[[Mapping[str, Any]], None]] = {
    "aim": _check_aim,
    "inspect": _check_inspect,
    "edit_wand": _check_edit,
    "drop": _check_drop,
}


# -- entry point -----------------------------------------------------------------------------------


def _take_direct_until(spec: CommandSpec, args: dict[str, Any]) -> dict[str, Any]:
    """Pop the `until` conditions that were written beside the arguments."""
    out: dict[str, Any] = {}
    if not spec.until_direct:
        return out
    for key in UNTIL_KEYS:
        if key in args and spec.param(key) is None:
            out.update(normalize_until(spec.name, {key: args.pop(key)}))
    return out


def validate_command(name: Any, raw: Mapping[str, Any] | None = None) -> Command:
    """Check a command given by name and raw arguments. Raises `CommandError`, which names the
    command at fault."""
    try:
        return _validate(name, raw)
    except CommandError as err:
        if err.command is None and isinstance(name, str):
            err.command = name[:MAX_NAME]
        raise


def _validate(name: Any, raw: Mapping[str, Any] | None) -> Command:
    if not isinstance(name, str) or name not in COMMANDS:
        raise CommandError(
            "unknown_command",
            f"unknown command {reprlib.repr(name)}; the commands are: {', '.join(COMMANDS)}",
        )
    spec = COMMANDS[name]
    if raw is not None and not isinstance(raw, Mapping):
        raise CommandError("bad_argument", f"{name}: the arguments must be an object")
    args = dict(raw or {})
    until = normalize_until(name, args.pop("until", None))
    until.update(_take_direct_until(spec, args))
    known = {p.name for p in spec.params if p.name != "until"}
    unknown = [k for k in args if k not in known]
    if unknown:
        usable = sorted(known | (set(UNTIL_KEYS) if spec.until_direct else set()))
        hint = f"; use {', '.join(usable)}" if usable else "; it takes no arguments"
        raise CommandError("bad_argument", f"{name}: unknown argument `{unknown[0]}`{hint}")
    out: dict[str, Any] = {}
    for p in spec.params:
        if p.name == "until":
            continue
        if p.name in args:
            out[p.name] = _coerce(name, p, args[p.name])
        elif p.required:
            raise CommandError("bad_argument", f"{name}: `{p.name}` is required")
    if "edge" in until and name not in WALKING:
        raise _fail(name, "until.edge", "is for move and walk_to (it stops before a drop)")
    if until:
        out["until"] = until
    check = _CHECKS.get(name)
    if check is not None:
        check(out)
    return Command(name, out)
