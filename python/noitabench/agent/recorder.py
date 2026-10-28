"""`decisions.jsonl`: one line per decision point, next to the recording of the game.

    {frame, index, stop_reason, command, observation_digest, ...}

`frame` is the frame at which the agent was asked, `index` the 1-based decision number,
`stop_reason` why the world had stopped (the reason shown in the observation), `command` what the
agent answered and `observation_digest` a hash of the observation it was shown. Extra fields
say what the answer did (`result`, `frames`, `ok`). Everything in a line is a fact about the
game, not a wall-clock time, so two runs of the same commands write the same file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TextIO


def digest(answer: dict[str, Any]) -> str:
    """A short stable hash of an answer (what the agent was shown)."""
    text = json.dumps(answer, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class DecisionLog:
    """Appends decision records to `decisions.jsonl` (flushed per line)."""

    def __init__(self, directory: Path | str) -> None:
        self.path = Path(directory) / "decisions.jsonl"
        self._file: TextIO | None = self.path.open("w", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        if self._file is None:
            raise ValueError("the decision log is closed")
        self._file.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
