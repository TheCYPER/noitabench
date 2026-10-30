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
The one exception is the `id` of each tool call and of each result in a transcript line: it is
checked against known secrets only, not against key shapes (`Redactor.redact_id`), because the
ids some providers make look like keys and a recording needs them to tell which result answers
which call.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, TextIO

from .redact import Redactor, default_redactor

# The transcript fields that list tool calls or their results, each item with an `id`.
CALL_LISTS = ("tool_calls", "results")


def _dump(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)


def _clean_call(redactor: Redactor, item: Any) -> Any:
    """One tool call or result: the item redacted as usual, its `id` by `Redactor.redact_id`."""
    if not isinstance(item, dict) or "id" not in item:
        return redactor.redact_value(item)
    rest = {key: value for key, value in item.items() if key != "id"}
    return {"id": redactor.redact_id(item["id"]), **redactor.redact_value(rest)}


def _is_call_list(key: str, value: Any) -> bool:
    """Whether `value` is a list of tool calls or results. Anything else under those names (a list
    of characters that spells a secret, say) gets the usual redaction as a whole."""
    return key in CALL_LISTS and isinstance(value, list) and all(isinstance(v, dict) for v in value)


def _clean_transcript(redactor: Redactor, record: dict[str, Any]) -> dict[str, Any]:
    """A transcript record, redacted: the key order is kept, the ids are checked on their own."""
    out: dict[str, Any] = {}
    for key, value in record.items():
        if _is_call_list(key, value):
            out[key] = [_clean_call(redactor, item) for item in value]
        else:
            out[redactor.redact(key)] = redactor.redact_value(value)
    return out


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
        self._write(self._transcript, {"seq": self._seq, "kind": kind, **fields}, clean=True)

    def _write(self, handle: TextIO | None, record: dict[str, Any], *, clean: bool = False) -> None:
        if handle is None:
            raise ValueError("the log is closed")
        redactor = self._redactor if self._redactor is not None else default_redactor()
        done = _clean_transcript(redactor, record) if clean else redactor.redact_value(record)
        handle.write(_dump(done) + "\n")
        handle.flush()

    def close(self) -> None:
        for name in ("_harness", "_transcript"):
            handle = getattr(self, name)
            if handle is not None:
                handle.close()
                setattr(self, name, None)
