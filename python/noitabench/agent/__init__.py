"""The agent interface: time model B, the command table, three observations, the protocol.

    from noitabench.agent import AgentSession
    session = AgentSession(game)                  # a `noitabench.game.Game` with a player
    answer = session.decide("walk_to(x=180)")     # run one decision, get the next observation

See `session.py` for how a decision runs, `spec.py` for the commands, `protocol.py` for the JSON
Lines form and `python -m noitabench agent play --help` for the command line. Contract text:
`.trellis/spec/backend/contracts.md`, "Agent interface".
"""

from .errors import CommandError
from .grammar import parse_decision
from .interrupts import Interrupts
from .memory import InMemoryNotes, MemoryBackend, NoMemory
from .observe import ViewConfig
from .render import render_text
from .session import AgentSession, SessionConfig
from .spec import COMMANDS, Command
from .tools import call_tool, coerce_request, tool_schemas
from .validate import validate_command

__all__ = [
    "COMMANDS",
    "AgentSession",
    "Command",
    "CommandError",
    "InMemoryNotes",
    "Interrupts",
    "MemoryBackend",
    "NoMemory",
    "SessionConfig",
    "ViewConfig",
    "call_tool",
    "coerce_request",
    "parse_decision",
    "render_text",
    "tool_schemas",
    "validate_command",
]
