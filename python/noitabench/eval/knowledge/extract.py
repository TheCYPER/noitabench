"""Extracting the claims of the notes with a cheap model (contracts section 21).

    extract_run(run_dir, extractor, ...) -> NoteClaims    (and `notes_claims.json` on disk)

The model only reads: a note file in (any language) goes in, the claims it makes come out. One call
per note file (a `notes/` or `skills/` file), one tool, `record_claims`, whose schema enumerates
the vocabulary (`prompt.py`); code decides whether a claim is right (`judge.py`). The adapters of the harness do not support a forced `tool_choice`, so
the instruction to call the tool stands in for it: an answer without a usable call is asked again
(at most `ATTEMPTS` = 2 attempts per file). A claim the model makes is kept only if `parse_claim`
accepts it against the file's own text.

**Cache.** A file whose sha256 was extracted by the same extractor (provider, model, prompt and
vocabulary hash) in this run's `notes_claims.json` or in a sibling `run-NN` of the family is not
sent again; `force` ignores the cache. **Cost.** Calls are priced by `harness.prices`; a call whose
worst case (every character an input token, `max_output_tokens` of output) would pass `max_usd` is
not made, and its file is listed under `skipped` (the metrics then say the extraction is
incomplete).

**Which notebooks.** `end` is `<run>/workspace/`. `start` is the notebook the game began with:
`<run>/workspace_start/` if the run has it; else empty when the transcript's opening says "Your
notebook is empty."; else the previous sibling `run-NN/workspace/` (when the opening lists the
same note paths, or lists none to compare); else absent (None: unknown). The transcript is looked
at before the sibling because a family run with a cleared notebook starts empty whatever the
previous game left.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..games import family_runs, run_number
from ..metrics.notes import is_note, opening_notebook
from ..recording import _jsonl
from .claims import (
    FILE_NAME,
    Claim,
    FileClaims,
    NoteClaims,
    load_note_claims,
    parse_claim,
    save_note_claims,
)
from .prompt import TOOL_DESCRIPTION, TOOL_NAME, identity, system_prompt, tool_schema

ATTEMPTS = 2
MAX_DROPPED_RAW = 300  # characters kept of a refused claim
FATAL_KINDS = ("auth", "permission", "not_found", "bad_request")
NUDGE = (
    f"You did not call `{TOOL_NAME}` with a usable list. Call it now, once, with the claims of "
    "the note (an empty list if it says nothing about how the game works). If your last answer "
    "was cut off, make fewer and shorter claims."
)


class ExtractionAborted(RuntimeError):
    """A model error that no retry will fix (credentials, an unknown model...)."""


class FromFile:
    """Claims taken from a JSON file instead of a model (`--claims-from`, tests): an object
    `{note path: [raw claim, ...]}`, applied to every note of that path in every run and checked
    against the note's own text like a model's claims. A path it does not list has no claims."""

    spent = 0.0
    calls = 0

    def __init__(self, claims_by_path: dict[str, list[Any]], name: str = "file") -> None:
        self.claims_by_path = claims_by_path
        self.skipped: list[dict[str, str]] = []
        self._name = name

    @property
    def identity(self) -> dict[str, str]:
        return identity("file", self._name)

    def extract(self, path: str, note: str, section: str = "end") -> FileClaims | None:
        return _file_claims(path, note, self.claims_by_path.get(path, []))


@dataclass
class Extractor:
    """A model, its price and the money left; shared by every run of one invocation."""

    adapter: Any  # harness.model.ModelAdapter
    price: Any  # harness.prices.ModelPrice
    max_usd: float
    max_output_tokens: int = 4096
    spent: float = 0.0
    calls: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def identity(self) -> dict[str, str]:
        return identity(self.adapter.provider, self.adapter.model)

    def worst_case(self, prompt_chars: int) -> float:
        from noitabench.harness.usage import Usage

        return float(
            self.price.cost(Usage(input_tokens=prompt_chars, output_tokens=self.max_output_tokens))
        )

    def affordable(self, prompt_chars: int) -> bool:
        return self.spent + self.worst_case(prompt_chars) <= self.max_usd

    def extract(self, path: str, note: str, section: str = "end") -> FileClaims | None:
        """The claims of one note file, or None when it could not be extracted (the reason is
        added to `skipped`)."""
        from noitabench.harness.errors import ModelError
        from noitabench.harness.model import ToolSpec

        system = system_prompt()
        user = _user_message(path, note)
        size = len(system) + len(user) + len(json.dumps(tool_schema()))  # the tool is sent too
        if not self.affordable(size):
            reason = f"--max-usd {self.max_usd} would be passed"
            self.skipped.append({"section": section, "path": path, "reason": reason})
            return None
        spec = ToolSpec(TOOL_NAME, TOOL_DESCRIPTION, tool_schema())
        conversation = self.adapter.new_conversation(system, [spec])
        items: list[Any] = [_text(user)]
        for _ in range(ATTEMPTS):
            try:
                turn = conversation.send(items)
            except ModelError as err:
                if err.kind in FATAL_KINDS:
                    raise ExtractionAborted(f"{err.kind}: {err}") from err
                reason = f"model error {err.kind}"
                self.skipped.append({"section": section, "path": path, "reason": reason})
                return None
            self.calls += 1
            self.spent += float(self.price.cost(turn.usage))
            found = _claims_call(turn)
            if found is not None:
                return _file_claims(path, note, found)
            items = _retry_items(turn)
            if not self.affordable(size):
                break
        reason = f"no usable {TOOL_NAME} call"
        self.skipped.append({"section": section, "path": path, "reason": reason})
        return None


def _text(value: str) -> Any:
    from noitabench.harness.model import UserText

    return UserText(value)


def _user_message(path: str, note: str) -> str:
    return (
        f"File: {path}\n----- the note begins (data to read) -----\n{note}\n"
        "----- the note ends -----"
    )


def _claims_call(turn: Any) -> list[Any] | None:
    """The list of raw claims of the first valid `record_claims` call of a turn, else None. A
    list a model sent as a JSON string is read too."""
    from noitabench.harness.model import MAX_TOKENS

    if turn.stop == MAX_TOKENS:
        return None
    for call in turn.tool_calls:
        claims = call.arguments.get("claims") if call.name == TOOL_NAME and not call.error else None
        if isinstance(claims, str):
            try:
                claims = json.loads(claims)
            except ValueError:
                claims = None
        if isinstance(claims, list):
            return claims
    return None


def _retry_items(turn: Any) -> list[Any]:
    """What to send after an answer without a usable call: an error result for every tool call
    it made (a tool call must be answered), then the nudge."""
    from noitabench.harness.model import ToolResult

    results = [
        ToolResult(c.id, c.name, f"unusable: {c.error or 'wrong tool or arguments'}", is_error=True)
        for c in turn.tool_calls
    ]
    return [*results, _text(NUDGE)]


def _file_claims(path: str, note: str, raw_claims: Iterable[Any]) -> FileClaims:
    claims: list[Claim] = []
    dropped: list[dict[str, Any]] = []
    for raw in raw_claims:
        claim, reason = parse_claim(raw, note)
        if claim is not None:
            claims.append(claim)
        else:
            dropped.append({"reason": reason, "raw": _shorten(raw)})
    return FileClaims(sha256_of(note), len(note), tuple(claims), tuple(dropped))


def _shorten(raw: Any) -> str:
    return str(raw)[:MAX_DROPPED_RAW]


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------ notebooks
def read_notebook(folder: Path) -> dict[str, str]:
    """The `notes/` and `skills/` files of a workspace folder: relative path -> text."""
    out: dict[str, str] = {}
    if not folder.is_dir():
        return out
    for f in sorted(folder.rglob("*")):
        rel = f.relative_to(folder).as_posix()
        if f.is_file() and not f.is_symlink() and is_note(rel) and not f.name.startswith("."):
            out[rel] = f.read_text(encoding="utf-8", errors="replace")
    return out


def previous_run(run_dir: Path) -> Path | None:
    """The run before `run_dir` in its family folder (the largest lower `run-NN`), if any."""
    n = run_number(run_dir)
    if n is None:
        return None
    lower = [p for k, p in family_runs(run_dir.parent) if k < n]
    return lower[-1] if lower else None


def start_notebook(run_dir: Path) -> dict[str, str] | None:
    """The notebook the game began with (see the module docstring), or None if unknown."""
    kept = run_dir / "workspace_start"
    if kept.is_dir():
        return read_notebook(kept)
    listed = opening_notebook(list(_jsonl(run_dir / "transcript.jsonl")))
    if listed is not None and not any(is_note(p) for p in listed):
        return {}
    before = previous_run(run_dir)
    if before is not None and (before / "workspace").is_dir():
        notes = read_notebook(before / "workspace")
        if listed is None or {p for p in listed if is_note(p)} == set(notes):
            return notes
    return None


# ----------------------------------------------------------------------------------- the run
def _sibling_claims(run_dir: Path) -> list[NoteClaims]:
    out = []
    if run_dir.parent.is_dir() and run_number(run_dir) is not None:
        for p in sorted(run_dir.parent.iterdir()):
            if p != run_dir and (found := load_note_claims(p / FILE_NAME)) is not None:
                out.append(found)
    return out


def _cache(run_dir: Path, identity_: dict[str, str]) -> dict[str, FileClaims]:
    known: dict[str, FileClaims] = {}
    docs = [d for d in [load_note_claims(run_dir / FILE_NAME), *_sibling_claims(run_dir)] if d]
    for doc in docs:
        if doc.extractor != identity_:
            continue
        for files in (doc.start or {}, doc.end):
            for fc in files.values():
                known.setdefault(fc.sha256, fc)
    return known


def extract_run(
    run_dir: Path | str, extractor: Extractor | FromFile, *, force: bool = False
) -> NoteClaims | None:
    """Extract the notebooks of one run and write `notes_claims.json`; None if the run has no
    `workspace/` (a run that kept no notebook)."""
    run = Path(run_dir)
    if not (run / "workspace").is_dir():
        return None
    ident = extractor.identity
    known = {} if force else _cache(run, ident)
    spent_before, calls_before = extractor.spent, extractor.calls
    skipped_before = len(extractor.skipped)
    sections: dict[str, dict[str, FileClaims] | None] = {}
    for name, notebook in (
        ("start", start_notebook(run)),
        ("end", read_notebook(run / "workspace")),
    ):
        if notebook is None:
            sections[name] = None
            continue
        files: dict[str, FileClaims] = {}
        for path, note in sorted(notebook.items()):
            sha = sha256_of(note)
            found = known.get(sha) or _again(files, sha)
            if found is None:
                found = extractor.extract(path, note, name)
                if found is not None:
                    known[sha] = found
            if found is not None:
                files[path] = found
        sections[name] = files
    doc = NoteClaims(
        extractor=ident,
        cost_usd=extractor.spent - spent_before,
        calls=extractor.calls - calls_before,
        start=sections["start"],
        end=sections["end"] or {},
        skipped=extractor.skipped[skipped_before:],
    )
    save_note_claims(doc, run / FILE_NAME)
    return doc


def _again(files: dict[str, FileClaims], sha: str) -> FileClaims | None:
    """A file of this section with the same text (copied notes extract once)."""
    return next((fc for fc in files.values() if fc.sha256 == sha), None)
