"""Notes metrics: N2 notes kept and notes recalled (capability graph section 4, "工作区笔记被检索
并用上的次数").

What the run folder shows of the notebook (contracts section 17):

- `transcript.jsonl`: the `opening` lists the notebook at the start ("Your notebook holds:
  notes/a.md (120 characters), ..." or "Your notebook is empty."); the `assistant` records hold the
  tool calls (`workspace_read`, `workspace_search`, `workspace_write`, `workspace_edit`, of the
  player and of its helpers) and the `results` records whether each failed;
- `decisions.jsonl`: the `memory_*` commands of the text mode;
- `workspace/`: the notebook as the game left it.

Programs (`code_run`: Code Mode, hook scripts, plugins) can read and write the notebook unseen;
the transcript records only that they ran. Only the `notes/` and `skills/` areas count as notes;
agent paths are filed as the workspace files them (a name without a known folder goes to
`notes/`, and so do `plugins/` and `scripts/` paths when those folders are closed).

N2 notes_recall: the game began with notes (a kept family notebook). One opportunity. 1.0 if a note
    that was there at the start was read (or the notebook searched) before the player met its
    first encounter, 0.5 if only later, 0 if never (without decisions.jsonl the time of a read is
    not known and a read counts 1.0). The frame of a call is that of the decision asked next
    (nothing advances between decisions). Not measured if the notebook began empty, if
    the start is not in the run folder (no transcript opening), or if nothing was read in sight
    but a program ran (it may have read the notes unseen).
N2 notes_kept: one opportunity per game. 1.0 if the player left something in the notes. With the
    notebook known at both ends (the opening and `workspace/`): a note file at the end that is new
    or of another size than at the start, and that the player wrote or edited in sight (or any
    such file, if a program ran: programs write unseen). The harness changes sizes by itself (it
    re-cleans notes that held a secret, and the run folder gets a cleaned copy), so a change
    nobody wrote is not credited. Without one of the ends: a write or edit of a note that
    succeeded. Else 0. Not measured without a transcript (the play server does not log its notes
    panel, the scripted bot keeps none), or when nothing shows a write but a program ran and the
    end of the notebook is not in the folder.

Whether what a note says was right, was acted on, or was corrected later needs the meaning of the
notes: `knowledge.py` (right, and learned) and `notes_use.py` (followed, and mended) read them as
claims extracted by `python -m noitabench notes-claims`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..encounters import Result
from ..recording import RunData, as_int
from . import Metric, metric_group

NOTE_AREAS = ("notes", "skills")  # the folders of the notebook (harness/workspace.py)
CODE_AREAS = ("plugins", "scripts")  # open only with Code Mode, hooks or plugins (L2, L3, L5)
CODE_LAYERS = ("L2", "L3", "L5")
READS = {"workspace_read": "read", "workspace_search": "search"}
WRITES = ("workspace_write", "workspace_edit")
MEMORY_READS = {"memory_read": "read", "memory_search": "search"}
MEMORY_WRITES = ("memory_write", "memory_edit")
RECALL_LATE = 0.5
# `harness.prompt.opening_message`: "Your notebook holds: <path> (<n> characters), ... . <n>
# characters of room are left." or "Your notebook is empty. ..."; names hold no comma or bracket
HOLDS, EMPTY, ROOM = (
    "Your notebook holds:",
    "Your notebook is empty.",
    " characters of room are left.",
)
_LISTED = re.compile(r"\s*([^,()]+?) \((\d+) characters\)")


@dataclass(frozen=True)
class NoteCall:
    """One use of the notebook: `kind` is read, search or write; `path` normalised (None for a
    search); `frame` the game frame while it happened."""

    kind: str
    path: str | None
    frame: int


def code_area_open(run: RunData) -> bool:
    """Were `plugins/` and `scripts/` open (L2, L3 or L5 on, `summary.json` `layers`)? Without
    a summary they are taken as open: a path in them is then not a note."""
    layers = (run.summary or {}).get("layers")
    return not isinstance(layers, list) or any(x in layers for x in CODE_LAYERS)


def note_path(path: Any, code_area: bool = True) -> str | None:
    """A notebook path as the workspace files it (`harness.workspace.normalize`): a first part
    that is not one of its folders is a folder inside `notes/`, and so are `plugins/` and
    `scripts/` while the code areas are closed."""
    if not isinstance(path, str) or not path.strip():
        return None
    parts = path.strip().split("/")
    areas = NOTE_AREAS + (CODE_AREAS if code_area else ())
    return "/".join(parts if parts[0] in areas else ["notes", *parts])


def is_note(path: str | None) -> bool:
    return bool(path) and str(path).split("/")[0] in NOTE_AREAS


def opening_notebook(transcript: list[dict[str, Any]]) -> dict[str, int] | None:
    """The notebook at the start (path -> characters) from the player's first `opening` record;
    None if the transcript has none."""
    for row in transcript:
        if row.get("kind") == "opening" and not row.get("agent"):
            text = str(row.get("text", ""))
            if EMPTY in text:
                return {}
            head = text.rfind(HOLDS)
            if head < 0:
                return None
            listing = text[head + len(HOLDS) :].split(ROOM)[0]
            return {path: int(chars) for path, chars in _LISTED.findall(listing)}
    return None


def notebook_calls(run: RunData) -> list[NoteCall]:
    """The notebook calls that succeeded, in order: tool calls in the transcript (player and
    helpers) and `memory_*` commands in decisions.jsonl."""
    failed = {  # a turn's results share the `agent` and `call` of its assistant record
        (row.get("agent"), row.get("call"), r.get("id"))
        for row in run.transcript
        if row.get("kind") == "results"
        for r in row.get("results") or []
        if isinstance(r, dict) and r.get("is_error")
    }
    last, code_area = run.last_frame, code_area_open(run)
    out: list[NoteCall] = []
    for row in run.transcript:
        if row.get("kind") != "assistant":
            continue
        frame = run.decisions.frame_at(as_int(row.get("decision")))
        turn = (row.get("agent"), row.get("call"))
        for call in row.get("tool_calls") or []:
            if not isinstance(call, dict) or (*turn, call.get("id")) in failed:
                continue
            name, args = call.get("name"), call.get("arguments") or {}
            kind = READS.get(name) or ("write" if name in WRITES else None)
            if kind:
                path = None if kind == "search" else note_path(args.get("path"), code_area)
                out.append(NoteCall(kind, path, last if frame is None else frame))
    for row in run.decisions.rows:
        if row.get("ok") is False:
            continue
        for c in row.get("command") if isinstance(row.get("command"), list) else []:
            if not isinstance(c, dict):
                continue
            name, args = c.get("name"), c.get("args") or {}
            kind = MEMORY_READS.get(name) or ("write" if name in MEMORY_WRITES else None)
            if kind:
                path = None if kind == "search" else note_path(args.get("path"), code_area)
                out.append(NoteCall(kind, path, as_int(row.get("frame"))))
    return sorted(out, key=lambda c: c.frame)


def _programs_ran(run: RunData) -> bool:
    return any(row.get("kind") == "code_run" for row in run.transcript)


@metric_group
def notes_recall(run: RunData, results: list[Result]) -> list[Metric]:
    names = ("notes_recall", ("N2",))
    start = opening_notebook(run.transcript)
    if start is None:
        reason = "no transcript opening: the notebook at the start is not in the run folder"
        return [Metric(*names, None, 0, reason)]
    kept = sorted(p for p in start if is_note(p))
    if not kept:
        return [Metric(*names, None, 0, "the game began with no notes: nothing to recall")]
    reads = [
        c
        for c in notebook_calls(run)
        if c.kind == "search" or (c.kind == "read" and c.path in kept)
    ]
    first_scene = min((r.visit.enter for r in results), default=None)
    detail = {"kept_at_start": kept, "reads": len(reads)}
    if not reads:
        if _programs_ran(run):
            reason = "no note was read in sight, but programs ran (they can read notes unseen)"
            return [Metric(*names, None, 0, reason, detail)]
        return [
            Metric(*names, 0.0, 1, f"never read the {len(kept)} notes kept from before", detail)
        ]
    t = reads[0].frame
    if not run.decisions.present:
        why = "read the kept notes (when is not known: no decisions.jsonl)"
        return [Metric(*names, 1.0, 1, why, detail)]
    if first_scene is None or t <= first_scene:
        value, why = 1.0, "read the kept notes before meeting the first scene"
    else:
        value, why = RECALL_LATE, f"read the kept notes only at frame {t}, after the first scene"
    return [Metric(*names, value, 1, why, {**detail, "first_read_frame": t})]


@metric_group
def notes_kept(run: RunData, _results: list[Result]) -> list[Metric]:
    names = ("notes_kept", ("N2",))
    if not run.transcript:
        reason = (
            "no transcript: the play server does not log its notes panel and the scripted bot "
            "keeps no notes"
        )
        return [Metric(*names, None, 0, reason)]
    written = sorted({c.path or "" for c in notebook_calls(run) if c.kind == "write"})
    written = [p for p in written if is_note(p)]
    programs = _programs_ran(run)
    start, end = opening_notebook(run.transcript), run.workspace
    if start is not None and end is not None:
        # a note left at the end, new or of another size, that the player wrote (or a program
        # may have): the harness itself re-cleans notes and copies them cleaned, which also
        # changes sizes
        changed = sorted(p for p, n in end.items() if is_note(p) and start.get(p) != n)
        kept = changed if programs else [p for p in changed if p in written]
        if kept:
            return [Metric(*names, 1.0, 1, f"left notes for later: {', '.join(kept)}",
                           {"files": kept})]  # fmt: skip
        why = "wrote notes but none was left at the end" if written else "kept no notes"
        return [Metric(*names, 0.0, 1, why)]
    if written:
        return [Metric(*names, 1.0, 1, f"wrote notes: {', '.join(written)}", {"files": written})]
    if programs:
        reason = "no write in sight, but programs ran and the final notebook is not in the folder"
        return [Metric(*names, None, 0, reason)]
    return [Metric(*names, 0.0, 1, "wrote no notes in the whole game")]
