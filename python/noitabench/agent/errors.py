"""Errors that are answers to the agent, not crashes.

A command that cannot be run (a mistyped argument, a wand that is not there, an edit outside a
rest area) raises `CommandError`. The session turns it into `{ok: false, code, message}` data
in the observation and no game time passes (error-handling guideline).
"""

from __future__ import annotations


class CommandError(ValueError):
    """An invalid command. `code` is a short machine word, `message` is addressed to the agent."""

    def __init__(self, code: str, message: str, command: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.command = command  # the name of the command at fault, when it is known

    def as_dict(self) -> dict[str, object]:
        return {"ok": False, "code": self.code, "message": self.message}
