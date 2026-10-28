"""The two log files a run writes next to the recording.

- `harness.jsonl`: one line per model call (and per failed attempt): provider, model, tokens
  with the cache split, cost, latency, stop reason. No prompts, no keys.
- `transcript.jsonl`: what the model said and did, for the replay page: its text and thinking
  summary, its tool calls, the results it was given, the briefings it wrote.
  Layers that run code add lines of their own: `code_run` (a program, hook script or plugin
  tool: ok, limit, commands, steps, no code), `lib_install` (what was installed, and how).

Both are diagnostics of the harness, not of the game: they carry wall-clock times and are not
part of the reproducibility contract (`decisions.jsonl` and the recording are).

Every record is passed through the `Redactor` (`redact.py`) before it is written, so that a
secret that got this far (in a program's output, an error, the model's own words) is not kept.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, TextIO

from .redact import Redactor, default_redactor


def _dump(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)


class RunLogs:
    def __init__(self, directory: Path | str, redactor: Redactor | None = None) -> None:
        self._redactor = redactor
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._harness: TextIO | None = (self.directory / "harness.jsonl").open(
            "w", encoding="utf-8"
        )
        self._transcript: TextIO | None = (self.directory / "transcript.jsonl").open(
            "w", encoding="utf-8"
        )
        self._seq = 0

    def call(self, record: dict[str, Any]) -> None:
        self._write(self._harness, {"ts": round(time.time(), 3), **record})

    def transcript(self, kind: str, **fields: Any) -> None:
        self._seq += 1
        self._write(self._transcript, {"seq": self._seq, "kind": kind, **fields})

    def _write(self, handle: TextIO | None, record: dict[str, Any]) -> None:
        if handle is None:
            raise ValueError("the log is closed")
        redactor = self._redactor if self._redactor is not None else default_redactor()
        handle.write(_dump(redactor.redact_value(record)) + "\n")
        handle.flush()

    def close(self) -> None:
        for name in ("_harness", "_transcript"):
            handle = getattr(self, name)
            if handle is not None:
                handle.close()
                setattr(self, name, None)
