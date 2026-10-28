"""The command table (tick-design 4.3): names, arguments, how long each takes.

`COMMANDS` is the one place that says what an agent may do. The text grammar (`grammar.py`), the
JSON tool schemas (`tools.py`) and the session all read it; `validate.py` checks raw arguments
against it.

Timing of a command:

- `free`: no game time passes (`aim`, `edit_wand`, `inspect`, the memory commands);
- `tick`: one tick (`kick`, `swap_wand`, `pickup`, `throw`, `drop`);
- `until`: runs for as many ticks as its `until` conditions and its own ends say, never more
  than 300 frames.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

FREE, TICK, UNTIL = "free", "tick", "until"

INT, NUMBER, BOOL, STR, ENUM, AMOUNT, TARGET = (
    "int",
    "number",
    "bool",
    "str",
    "enum",
    "amount",
    "target",
)
UNTIL_SPEC = "until"

DIRECTION_ALIASES = {
    "left": "left",
    "l": "left",
    "west": "left",
    "-1": "left",
    "right": "right",
    "r": "right",
    "east": "right",
    "1": "right",
    "up": "up",
    "u": "up",
    "none": "up",
    "stay": "up",
    "straight": "up",
}


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    doc: str
    required: bool = False
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class CommandSpec:
    name: str
    summary: str
    timing: str
    params: tuple[Param, ...] = ()
    positional: tuple[str, ...] = ()
    until_direct: bool = False  # `ticks=3`, `blocked` ... may be given beside the arguments

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)


@dataclass(frozen=True)
class Command:
    """A checked command: its name and normalised arguments (plain JSON values)."""

    name: str
    args: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "args": dict(self.args)}

    def __str__(self) -> str:
        shown = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"{self.name}({shown})"


# -- the table ------------------------------------------------------------------------------------

_UNTIL_DOC = (
    "Extra stop conditions, any of which ends the command: ticks (1-30), distance (cells), "
    "x (world column), blocked (a wall), landed (on the ground; for jump, fly, move and "
    "walk_to a touch-down after leaving it), hp_below (HP), target_dead, mana_empty, event (an "
    "event type), edge (move and walk_to only: stop before stepping off a ledge). Written as "
    "an object, or directly beside the other arguments."
)
_UNTIL = Param("until", UNTIL_SPEC, _UNTIL_DOC)
_BOTTLE = Param(
    "bottle", INT, "Which bottle (index in your bottle list); default the active one.", minimum=0
)
_ANGLE = Param("angle", NUMBER, "Aim in degrees first: 0 right, 90 up, -90 down.")
_LR = ("left", "right")
_LRU = ("left", "right", "up")


def _specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec(
            "move",
            "Walk sideways in a direction. Stops at a wall (stop reason 'blocked'). It walks off "
            "ledges and falls; add until=edge to stop before a drop instead.",
            UNTIL,
            (Param("direction", ENUM, "left or right.", True, _LR), _UNTIL),
            ("direction",),
            True,
        ),
        CommandSpec(
            "walk_to",
            "Walk sideways to the world column x and stop there. No path finding: it walks "
            "straight, stops at walls, and walks off ledges (until=edge stops before a drop).",
            UNTIL,
            (Param("x", INT, "World column to walk to.", True), _UNTIL),
            ("x",),
            True,
        ),
        CommandSpec(
            "jump",
            "Jump straight up, or to the left or right. Ends when you land.",
            UNTIL,
            (Param("direction", ENUM, "up (default), left or right.", False, _LRU), _UNTIL),
            ("direction",),
            True,
        ),
        CommandSpec(
            "fly",
            "Hold levitation (up, or sideways while rising) until the meter is empty or the "
            "conditions are met.",
            UNTIL,
            (Param("direction", ENUM, "up (default), left or right.", False, _LRU), _UNTIL),
            ("direction",),
            True,
        ),
        CommandSpec(
            "aim",
            "Choose where you aim; it stays until changed. Give exactly one of: angle (degrees), "
            "x and y (a point of the world), entity (the id of a creature or item you see) or "
            "target (an id, or the kind of the nearest creature you see). Takes no time.",
            FREE,
            (
                Param("angle", NUMBER, "Degrees: 0 right, 90 up, -90 down."),
                Param("x", NUMBER, "World column of a point to aim at."),
                Param("y", NUMBER, "World row of a point to aim at."),
                Param("entity", INT, "Id of a creature or item in view.", minimum=0),
                Param("target", TARGET, "An id, or a kind such as 'longleg'."),
            ),
            ("target",),
        ),
        CommandSpec(
            "fire",
            "Hold the cast key with the active wand, aiming as set. Ends when the wand cannot "
            "pay for a spell, when the creature you aim at is dead, or by the conditions.",
            UNTIL,
            (_UNTIL,),
            (),
            True,
        ),
        CommandSpec("kick", "Kick what is in front of you (one tick).", TICK),
        CommandSpec(
            "wait",
            "Stand still. Ends after the ticks (default 1) or when an event happens.",
            UNTIL,
            (_UNTIL,),
            (),
            True,
        ),
        CommandSpec(
            "drink",
            "Drink from a bottle. Amount in cells (default 100, about one tick; 'all'). A "
            "mixture is drunk in proportion: every material in it does its work.",
            UNTIL,
            (Param("amount", AMOUNT, "Cells to drink, or 'all'."), _BOTTLE, _UNTIL),
            ("amount",),
            True,
        ),
        CommandSpec(
            "pour",
            "Tip a bottle out in front of you along the aim. Amount in cells (default: all). A "
            "mixture comes out in proportion.",
            UNTIL,
            (Param("amount", AMOUNT, "Cells to pour, or 'all'."), _BOTTLE, _ANGLE, _UNTIL),
            ("amount",),
            True,
        ),
        CommandSpec(
            "fill",
            "Scoop the liquid around your feet into a bottle until it is full or nothing more "
            "can be scooped. Every liquid there goes in and mixes with what the bottle already "
            "holds.",
            UNTIL,
            (Param("amount", AMOUNT, "Cells to scoop, or 'all'."), _BOTTLE, _UNTIL),
            ("amount",),
            True,
        ),
        CommandSpec(
            "throw",
            "Throw a bottle along the aim; it breaks where it lands and spills all of what it "
            "holds (one tick).",
            TICK,
            (_BOTTLE, _ANGLE),
        ),
        CommandSpec(
            "pickup",
            "Pick up the nearest wand, spell or bottle within reach (one tick). Name its id to "
            "make sure it is the one you mean.",
            TICK,
            (Param("item", INT, "Id of the item you want.", minimum=0),),
            ("item",),
        ),
        CommandSpec(
            "drop",
            "Put something you carry on the ground beside you (one tick); pick it up again with "
            "pickup. Give exactly one of: wand, spell or bottle (its index).",
            TICK,
            (
                Param("wand", INT, "Index of a wand.", minimum=0),
                Param("spell", INT, "Index of a carried spell.", minimum=0),
                Param("bottle", INT, "Index of a bottle.", minimum=0),
            ),
        ),
        CommandSpec(
            "swap_wand",
            "Hold another of your wands (one tick).",
            TICK,
            (Param("wand", INT, "Index in your wand list.", True, minimum=0),),
            ("wand",),
        ),
        CommandSpec(
            "edit_wand",
            "Rearrange spells. Only in a rest area or at an edit station. op=place puts the "
            "carried spell `spell` into `slot` of `wand`; op=take takes the spell out of the "
            "slot; op=swap swaps slots a and b. Takes no time.",
            FREE,
            (
                Param("op", ENUM, "place, take or swap.", True, ("place", "take", "swap")),
                Param("wand", INT, "Index in your wand list.", True, minimum=0),
                Param("slot", INT, "Slot index (place, take).", minimum=0),
                Param("spell", INT, "Index in your carried spells (place).", minimum=0),
                Param("a", INT, "First slot (swap).", minimum=0),
                Param("b", INT, "Second slot (swap).", minimum=0),
            ),
            ("op",),
        ),
        CommandSpec(
            "inspect",
            "Look closely, without letting time pass (each inspect in a decision counts as one "
            "decision). Give one of: x and y (a cell in view), entity (an id in view: a bottle "
            "shows what is in it, a wand on the ground its stats and spells, a creature its "
            "health), wand (an index; with slot for one spell), spell (index of a carried spell) "
            "or bottle (an index).",
            FREE,
            (
                Param("x", INT, "World column of a cell in view."),
                Param("y", INT, "World row of a cell in view."),
                Param("entity", INT, "Id of a creature or item in view.", minimum=0),
                Param("wand", INT, "Index of one of your wands.", minimum=0),
                Param("slot", INT, "Slot of that wand.", minimum=0),
                Param("spell", INT, "Index of a carried spell.", minimum=0),
                Param("bottle", INT, "Index of one of your bottles.", minimum=0),
            ),
        ),
        CommandSpec(
            "memory_write",
            "Write (or append to) a file of your notes. Takes no time.",
            FREE,
            (
                Param("path", STR, "File name.", True),
                Param("text", STR, "What to write.", True),
                Param("append", BOOL, "Add to the end instead of replacing."),
            ),
            ("path", "text"),
        ),
        CommandSpec(
            "memory_read",
            "Read a file of your notes. Takes no time.",
            FREE,
            (Param("path", STR, "File name.", True),),
            ("path",),
        ),
        CommandSpec(
            "memory_search",
            "Search your notes for a word or phrase. Takes no time.",
            FREE,
            (Param("query", STR, "What to look for.", True),),
            ("query",),
        ),
        CommandSpec(
            "memory_edit",
            "Replace a piece of text in a note file. Takes no time.",
            FREE,
            (
                Param("path", STR, "File name.", True),
                Param("old", STR, "Text to replace (must occur once).", True),
                Param("new", STR, "New text.", True),
            ),
            ("path", "old", "new"),
        ),
        CommandSpec("memory_list", "List your note files. Takes no time.", FREE),
    )


COMMANDS: dict[str, CommandSpec] = {spec.name: spec for spec in _specs()}
MEMORY_COMMANDS = tuple(n for n in COMMANDS if n.startswith("memory_"))
