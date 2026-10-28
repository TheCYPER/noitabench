"""Every word the player is told, in one place.

The player is told it is playing a game, and the goal is "get as deep as you can". Nothing here
says or hints that the game is a benchmark, a test or an evaluation; no score or ability is
named; there is no strategy advice. The texts are constants (no dates, ids or seeds), so that
they are byte-identical from call to call and stay in the prompt cache.
"""

from __future__ import annotations

from collections.abc import Iterable

from noitabench.agent.observe import ViewConfig
from noitabench.agent.spec import COMMANDS, CommandSpec
from noitabench.agent.vocab import GOAL, MAX_COMMANDS

TEXT_MODE_BUDGET_WORD = "budget"

_INTRO = """\
You are playing a cave-exploration game, one step at a time.

THE GAME
You control a lone explorer who carries wands. The world is a deep cave drawn in single cells \
of material: rock, sand, water, oil, fire and much more. Liquids flow, loose powders fall, gases \
rise, fire spreads, and materials change when they touch each other. There are creatures. The \
cave has three layers with resting places between them, and every new game has a different cave.

THE GOAL
{goal}

HOW IT WORKS
- Time only passes when you act. While you think, the world waits.
- You act with commands. A command that takes time (walking, jumping, flying, firing, waiting, \
drinking, pouring, filling) keeps running until it is finished, until something happens that you \
should know about (you are hurt, a creature comes into view, a condition starts, you are \
blocked), or until 5 seconds of game time have passed. Then the game tells you why it stopped, \
what happened meanwhile, and what you can see now.
- A step is one turn of yours with up to {max_commands} commands, run in order. Looking closely \
with `inspect` takes no game time but each look counts as a step. You have a limited number of \
steps; every reply says how many are left.
- If you die, the game is over.
"""

_ACT_TOOLS = """
HOW TO ACT
Call the tools. Several tool calls in one turn are run in order as one step.
"""

_ACT_TEXT = """
HOW TO ACT
Think if you like, then end your message with the commands of your next step on one line, \
separated by semicolons, for example:
walk_to(x=180); fire(until=target_dead)
Arguments are written name=value (the first one may be written without its name). A line with \
only `budget` shows what is left of your allowance. These are the commands:
{commands}
"""

_NOTES_KEPT = """
NOTEBOOK
You have a notebook of text files. What you write in it is kept when the game is over: if you \
play again you will find it as you left it. There is little room, so keep it short and useful.
"""

_NOTES_SCRATCH = """
NOTEBOOK
You have a notebook of text files to keep track of things during the game. There is little room, \
so keep it short and useful.
"""

_ALLOWANCE = """
ALLOWANCE
You have a limited allowance of money and steps for this game; `budget` shows what is left. \
When it is used up the game stops.
"""

_PROGRAMS_INTRO = """
PROGRAMS AND PLUGINS
Besides single commands you can do more with code. Programs and plugins are kept in your \
notebook (folders scripts/ and plugins/).
"""
_PROGRAMS_L2 = (
    "- `run_code` runs a small Python program that plays several steps for you, with loops and "
    "conditions of your own.\n"
)
_PROGRAMS_L3 = (
    "- `hook_set` makes a running command stop when something happens, and can run one of your "
    "scripts right after.\n"
)
_PROGRAMS_L5 = (
    "- `plugin_list` shows tools you added yourself in plugins; `lib_list` and `lib_install` "
    "add extra Python libraries (there is no internet).\n"
)

_NOTEBOOK_TOOLS = "Folders are notes/ and skills/ and hold 8,000 characters in all."
_NOTEBOOK_TOOLS_CODE = (
    "Folders are notes/ and skills/ (8,000 characters in all) and plugins/ and scripts/ "
    "(64,000 characters in all)."
)

RUN_CODE_DESCRIPTION = (
    "Run a Python program that plays for you. In it, `game` has one function for each game "
    "command, with the same arguments (for example `game.walk_to(x=180)`). Each call is one step "
    "and returns what the command would have returned, as a dict: `answer['text']` is the text "
    "you would have read, `answer['stop']` says why it stopped. `game.decide('aim(target=4); "
    "fire(until=target_dead)')` runs up to four commands as one step; `game.observe()` shows the "
    "view as it is and takes no game time. `notes` works on your notebook: notes.read(path), "
    "notes.write(path, text, append=False), notes.edit(path, old, new), notes.search(query), "
    "notes.list(), notes.delete(path). Loops and conditions are yours to write. The program "
    "stops after 200 game commands, or when the game is over (the call that ends the game "
    "raises game.GameOver). It has no internet and cannot read files; numpy and scipy can "
    "be imported, and libraries you have installed. It is stopped after 10 seconds of "
    "processor time, 30 seconds of its own running, or 512 MB of memory. You get what it "
    "printed, a short summary and the view after its last command. The commands cost steps as "
    "usual; the call itself takes no game time."
)
HOOK_SET_DESCRIPTION = (
    "Make the game react when something happens. `event`: damage; new_enemy (a creature comes "
    "into view); status_change (you get a new condition); new_material (a material comes into "
    "view that you have not seen before); entered_liquid; hp_below (also give `value`, the HP "
    "it falls below). `action`: 'interrupt' makes a running command stop at that event "
    "(`on`: false switches that off; damage, new_enemy and status_change are on from the "
    "start); 'run' does that and then runs scripts/<script>.py (write it first with "
    "workspace_write) right after the step in which it happened. A script has `game` and "
    "`notes` as in run_code, and `event`, a dict with name, message and decision (the number of the reply that told of it). It may run up to "
    "20 game commands; what it prints is added to your next result. A script does not start "
    "another script. Takes no game time."
)
HOOK_LIST_DESCRIPTION = (
    "List your hooks, and which events stop a running command now. Takes no game time."
)
HOOK_CLEAR_DESCRIPTION = (
    "Remove a hook by its id (like h1), or all of them with 'all'. The event goes back to how "
    "it was at the start. Takes no game time."
)
PLUGIN_LIST_DESCRIPTION = (
    "Show the tools your plugins add, and any problems in them. A plugin is a Python file "
    "plugins/<name>.py in your notebook. In it, `@tool(description, schema)` above a function "
    "makes a tool: the function gets the arguments as a dict and returns text or JSON; `schema` "
    "is a JSON schema for the arguments (optional). `@hook(event)` above a function makes it run "
    "after a step in which that event happened (events as in hook_set; `@hook('hp_below', 30)` "
    "for hp_below); it gets the event dict. A module-level string `prompt_fragment = '...'` "
    "(at most 600 characters) is added to your instructions the next time your conversation is "
    "started again with a briefing. Inside the functions (not at the top of the file) `game` and "
    "`notes` work as in run_code. Each plugin is one file and cannot import another. Call a tool "
    "with plugin_call. Takes no game time."
)
PLUGIN_CALL_DESCRIPTION = (
    "Run a tool from one of your plugins, by name, with its arguments. It runs like run_code "
    "(same limits; the game commands it runs cost steps) and returns what the tool returned, what "
    "it printed and the view after its last command."
)
LIB_LIST_DESCRIPTION = (
    "List the extra Python libraries you can install for programs and plugins (there is no "
    "internet: only these), and which are installed. numpy and scipy are always there. Takes no "
    "game time."
)
LIB_INSTALL_DESCRIPTION = (
    "Install one of the libraries from lib_list (with what it needs), so that programs and "
    "plugins can import it. Takes no game time."
)

SUMMARY_REQUEST = (
    "Time-out. Before you go on, write a briefing for yourself that will take the place of "
    "everything said so far. Say where you are and what is around you (exact coordinates); your "
    "health and mana; your wands (every slot and spell), carried spells and bottles with what is "
    "in them; what you have found out about materials, creatures, items and hazards, each as a "
    "plain fact; where you have been and what happened there; what you are trying to do next and "
    "any plan under way. Keep exact names, numbers and ids. Reply with the briefing only, as "
    "plain text of at most 500 words, and do not call a tool."
)
SERVER_COMPACTION_INSTRUCTIONS = (
    "Write a briefing that lets the player carry on the game from here. Say where the player is "
    "and what is around (exact coordinates); health and mana; every wand slot and spell, carried "
    "spells and bottles with what is in them; what has been found out about materials, "
    "creatures, items and hazards, each as a plain fact; where the player has been and what "
    "happened there; what it is trying to do next. Keep exact names, numbers and ids."
)
SUMMARY_INTRO = (
    "You are carrying on a game in progress. This is the briefing you wrote for yourself "
    "earlier:\n\n{summary}\n\nThis is where things stand now:\n\n{observation}"
)
NUDGE_NO_TOOL = "No command was given. Call one of the tools to act."
NUDGE_NO_COMMAND = (
    "No command was found in your message. End your message with one line of commands, for "
    "example: walk_to(x=180)"
)
NUDGE_CUT_OFF = (
    "Your last message was cut off before it was finished. Answer again, more briefly, with "
    "your next command."
)
SUMMARY_FALLBACK = "(The briefing could not be written. The notebook and the view below remain.)"

# Word stems that must never reach the player; a text is clean if no word *starts* with one
# (the tests scan every text the player sees).
FORBIDDEN_STEMS = (
    "benchmark",
    "test",
    "score",
    "capabilit",
    "evaluat",
    "assess",
    "grading",
    "metric",
    "episode",
    "harness",
    "cogbench",
    "noitabench",
    "experiment",
)


def command_reference(specs: Iterable[CommandSpec] | None = None) -> str:
    """The commands as text, for models that are not given tools."""
    lines: list[str] = []
    for spec in specs if specs is not None else COMMANDS.values():
        params = ", ".join(
            p.name if p.required else f"[{p.name}]" for p in spec.params if p.name != "until"
        )
        has_until = any(p.name == "until" for p in spec.params) or spec.until_direct
        if has_until:
            params = f"{params}, [until]" if params else "[until]"
        lines.append(f"- {spec.name}({params}): {spec.summary}")
        for p in spec.params:
            if p.name != "until":
                lines.append(f"    {p.name}: {p.doc}")
    return "\n".join(lines)


def what_you_see(view: ViewConfig) -> str:
    """The paragraph that says what each reply shows, for the channels that are switched on."""
    shown: list[str] = []
    if view.text:
        shown.append("your condition, what you carry, and the creatures and items in view")
    if view.ascii:
        shown.append(
            f"a map around you (each character stands for {view.ascii_cell} by "
            f"{view.ascii_cell} cells; the legend names the materials)"
        )
    if view.screenshot:
        shown.append("a picture of the cells around you")
    if not shown:
        return ""
    listed = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + ", and " + shown[-1]
    return (
        f"\nWHAT YOU SEE\nEvery reply shows {listed}. `inspect` tells you exactly what "
        "something is.\n"
    )


def programs_note(layers: Iterable[str]) -> str:
    """The paragraph about code, for the layers that give the player some (none for the minimal
    setting: its prompt does not change)."""
    names = set(layers)
    lines = [
        text
        for layer, text in (("L2", _PROGRAMS_L2), ("L3", _PROGRAMS_L3), ("L5", _PROGRAMS_L5))
        if layer in names
    ]
    note = _PROGRAMS_INTRO + "".join(lines) if lines else ""
    if "L4" in names:
        from .subagent_specs import PROMPT_L4  # imported here: subagent_specs imports adapters

        note += "\n" + PROMPT_L4
    return note


def system_prompt(
    *,
    mode: str,
    notes_kept: bool,
    view: ViewConfig | None = None,
    layers: Iterable[str] = (),
) -> str:
    """The system prompt. `mode` is `tools` or `text`; `notes_kept` says whether the notebook
    survives the game (it does not in the setting where each game starts from an empty one);
    `layers` are those of the run (code is only mentioned where it is offered)."""
    parts = [_INTRO.format(goal=GOAL, max_commands=MAX_COMMANDS)]
    parts.append(what_you_see(view or ViewConfig()))
    if mode == "text":
        parts.append(_ACT_TEXT.format(commands=command_reference()))
    else:
        parts.append(_ACT_TOOLS)
    parts.append(_NOTES_KEPT if notes_kept else _NOTES_SCRATCH)
    if mode != "text":
        parts.append(programs_note(layers))
    parts.append(_ALLOWANCE)
    return "".join(parts)


def notebook_tools_note(with_code_area: bool) -> str:
    return _NOTEBOOK_TOOLS_CODE if with_code_area else _NOTEBOOK_TOOLS


def opening_message(observation: str, files: list[tuple[str, int]], chars_left: int) -> str:
    """The first thing the player reads: the first view and what is in the notebook."""
    if files:
        listing = ", ".join(f"{path} ({chars} characters)" for path, chars in files)
        book = f"Your notebook holds: {listing}. {chars_left} characters of room are left."
    else:
        book = f"Your notebook is empty. {chars_left} characters of room are left."
    return f"{observation}\n\n{book}"
