"""The fixed numbers and words of the agent interface (tick-design sections 4.1, 4.3, 4.4)."""

from __future__ import annotations

PROTOCOL = "cogbench-agent/0"

FPS = 60
TICK_FRAMES = 10  # the world is only looked at, and the agent only asked, on tick boundaries
MAX_COMMAND_FRAMES = 300  # one decision never spans more than this many frames (5 s)
MAX_TICKS = MAX_COMMAND_FRAMES // TICK_FRAMES
DEFAULT_MAX_DECISIONS = 1000
MAX_COMMANDS = 4  # commands in one decision; a longer list is invalid and takes no time

# What a player sees: one range for everything, the extent of the ASCII map around the player
# (half sizes in cells; `ViewConfig.view_half` works it out from the map size). Creatures and
# items inside it with a clear line of sight, cells for `inspect`, events, new materials.
VIEW_HALF = (128, 64)
# The screenshot is a bigger rectangle (256 x 192 cells); only the terrain in it goes beyond what
# can be seen of creatures and items.
SHOT_HALF = (128, 96)

# Event types an agent may be told about (events.py turns them into short facts). Anything else
# the engine logs (`reaction`, `mix` and the row ids above all) never leaves the session. The
# summary events of drinking, pouring and filling are left out: the command's own result says
# what moved.
EVENT_TYPES = (
    "cast",
    "hit",
    "damage",
    "death",
    "status",
    "pickup",
    "pickup_failed",
    "drop",
    "kick",
    "throw",
    "shatter",
    "barrel_break",
    "enemy_attack",
    "edit_wand",
    "explosion",
    "ignite",
    "extinguish",
    "error",
)

# Interrupts (tick-design 4.4). The first four are on by default.
DEFAULT_INTERRUPTS = ("damage", "new_enemy", "status_change", "blocked")
OPTIONAL_INTERRUPTS = ("fell_in_liquid", "hp_low", "new_material")
ALL_INTERRUPTS = DEFAULT_INTERRUPTS + OPTIONAL_INTERRUPTS

# Stop reasons of a decision.
START = "start"
COMPLETED = "completed"
INTERRUPTED = "interrupted"
TIME_LIMIT = "time_limit"
INVALID = "invalid"
DEAD = "dead"
OVER = "over"

# Conditions of `until` (tick-design 4.3). `ticks` and `event` are looked at on tick boundaries,
# the others every frame.
UNTIL_KEYS = (
    "ticks",
    "distance",
    "x",
    "blocked",
    "landed",
    "hp_below",
    "target_dead",
    "mana_empty",
    "event",
    "edge",
)

# Walking never stops for a drop: the player walks off a ledge and falls (there is no fall damage).
# Only `until=edge` looks for one: a drop deeper than this many cells ahead is a cliff.
CLIFF_DEPTH = 8
# A walk is stuck against a wall when the key has been held this long and the player has not moved
# a cell in either direction (a tick: the wall is reported at the end of the first tick).
STALL_FRAMES = 10
DROP_MESSAGE = "There is a drop ahead."
WALL_MESSAGE = "A wall is in the way."
# Ledges up to this many cells high are stepped over by the walking player (entities.json).
STEP_UP = 4

GOAL = "Get as deep as you can."
