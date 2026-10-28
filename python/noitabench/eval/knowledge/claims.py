"""Claims: what a note says, in the fixed form a fact can be compared with (contracts section 21).

A claim is `{kind, ...subject fields, hedged, text}`. The subject fields of each kind are those of
the fact of the same kind (`recipe` `potion`/`effect` + `inputs`; `reaction` `a`, `b`, `out`;
`drink`; `property`; `creature`; `spell`; `scene`), plus four kinds that are not facts:

- `no_recipe {inputs}`   "these make nothing";
- `no_reaction {a, b}`   "these two do not react";
- `local`                a place or thing in one world (never judged);
- `other {paraphrase}`   anything outside the vocabulary, one line of English (never judged).

`text` is the stretch of the note the claim came from (at most `MAX_TEXT` characters) and must
occur in the note once white space is normalised, or the claim is dropped: a model cannot invent a
claim the note does not make. The quote must hold at least `MIN_QUOTE_CHARS` letters or digits
(`MIN_QUOTE_CJK` Chinese characters if it holds any): a quote of one letter or of punctuation
occurs in any note. It must begin and end on a word boundary where it begins or ends with an ASCII
letter or digit (`il bur` is not a stretch of `oil burns`). An unknown key or value drops the claim
too, with the reason. `parse_claim` is the only door; the extractor, `--claims-from` and the
loader of `notes_claims.json` all go through it.

`notes_claims.json` (`cogbench-note-claims/0`) holds the claims of the notebook the game began
with (`start`, absent if unknown) and of the one it ended with (`end`), per file, each file keyed by
its sha256 so that an unchanged file is extracted once (`extract.py`).
`subject_of` gives a claim the key under which two notebooks' claims are compared.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .vocab import CLAIM_KINDS, EFFECTS, MAX_TEXT, Vocabulary, vocabulary

FORMAT = "cogbench-note-claims/0"
FILE_NAME = "notes_claims.json"
MAX_INPUTS, MIN_INPUTS = 3, 2
MAX_PRODUCTS = 3
MIN_QUOTE_CHARS = 4  # letters or digits a quote must hold,
MIN_QUOTE_CJK = 3  # or Chinese characters when it holds any: a human may write notes in Chinese,
#                   and three characters can be a whole statement
_SPACE = re.compile(r"\s+")
_WORD = "A-Za-z0-9_"

# the subject fields of every kind (the keys a claim may carry besides hedged and text)
FIELDS: dict[str, tuple[str, ...]] = {
    "recipe": ("potion", "effect", "inputs"),
    "no_recipe": ("inputs",),
    "reaction": ("a", "b", "out"),
    "no_reaction": ("a", "b"),
    "drink": ("material", "effect"),
    "property": ("material", "property"),
    "creature": ("creature", "trait"),
    "spell": ("spell", "trait"),
    "scene": ("encounter", "topic", "value"),
    "local": (),
    "other": ("paraphrase",),
}
COMMON_KEYS = ("kind", "hedged", "text")
assert set(FIELDS) == set(CLAIM_KINDS)


def normalise(text: str) -> str:
    """White space collapsed and trimmed: how a quote is compared with its note."""
    return _SPACE.sub(" ", text).strip()


def quote_problem(quote: str, note: str) -> str | None:
    """Why `quote` is not a usable stretch of `note`, or None. Both are compared white-space
    normalised, case as written."""
    q, n = normalise(quote), normalise(note)
    need = MIN_QUOTE_CJK if any("\u4e00" <= ch <= "\u9fff" for ch in q) else MIN_QUOTE_CHARS
    if sum(1 for ch in q if ch.isalnum()) < need:
        return f"text holds fewer than {need} letters, digits or characters"
    start = rf"(?<![{_WORD}])" if re.match(rf"[{_WORD}]", q[0]) else ""
    end = rf"(?![{_WORD}])" if re.match(rf"[{_WORD}]", q[-1]) else ""
    if re.search(start + re.escape(q) + end, n) is None:
        return "text does not occur in the note"
    return None


@dataclass(frozen=True)
class Claim:
    kind: str
    fields: dict[str, Any]
    hedged: bool = False
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, **self.fields, "hedged": self.hedged, "text": self.text}


@dataclass(frozen=True)
class FileClaims:
    """The claims of one note file (`dropped` holds `{reason, raw}` of every claim refused)."""

    sha256: str
    chars: int
    claims: tuple[Claim, ...] = ()
    dropped: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "chars": self.chars,
            "claims": [c.as_dict() for c in self.claims],
            "dropped": list(self.dropped),
        }


@dataclass
class NoteClaims:
    """The content of a `notes_claims.json`."""

    extractor: dict[str, Any]
    cost_usd: float = 0.0
    calls: int = 0
    start: dict[str, FileClaims] | None = None  # None: the notebook the game began with is unknown
    end: dict[str, FileClaims] = field(default_factory=dict)
    skipped: list[dict[str, str]] = field(default_factory=list)  # files not extracted (cost cap)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "format": FORMAT,
            "extractor": self.extractor,
            "cost_usd": round(self.cost_usd, 6),
            "calls": self.calls,
        }
        if self.start is not None:
            out["start"] = _section(self.start)
        out["end"] = _section(self.end)
        if self.skipped:
            out["skipped"] = self.skipped
        return out

    def section(self, name: str) -> list[tuple[str, Claim]]:
        """`(path, claim)` of every claim of `start` or `end`, files in path order."""
        files = self.start if name == "start" else self.end
        return [(p, c) for p, fc in sorted((files or {}).items()) for c in fc.claims]


def _section(files: dict[str, FileClaims]) -> dict[str, Any]:
    return {"files": {p: fc.as_dict() for p, fc in sorted(files.items())}}


# ----------------------------------------------------------------------------------- parsing
def _one_of(value: Any, allowed: Any, name: str) -> str | None:
    if not isinstance(value, str) or value not in allowed:
        return f"{name} {str(value)[:40]!r} is not in the vocabulary"
    return None


def _list_of(value: Any, allowed: Any, name: str, low: int, high: int) -> str | None:
    if not isinstance(value, list) or not low <= len(value) <= high:
        return f"{name} must be a list of {low} to {high} values"
    for item in value:
        if (err := _one_of(item, allowed, name)) is not None:
            return err
    if len(set(value)) != len(value):
        return f"{name} repeats a value"
    return None


def _check_subject(kind: str, raw: dict[str, Any], v: Vocabulary) -> str | None:
    """The reason a claim's subject fields are unusable, or None."""
    checks: list[str | None] = []
    if kind in ("recipe", "no_recipe"):
        checks.append(_list_of(raw.get("inputs"), v.materials, "inputs", MIN_INPUTS, MAX_INPUTS))
    if kind == "recipe":
        potion, effect = raw.get("potion"), raw.get("effect")
        if potion is None and effect is None:
            return "a recipe names neither a potion nor an effect"
        if potion is not None:
            checks.append(_one_of(potion, v.potions, "potion"))
        if effect is not None:
            checks.append(_one_of(effect, EFFECTS, "effect"))
    elif kind in ("reaction", "no_reaction"):
        checks += [_one_of(raw.get(n), v.reaction_ends(), n) for n in ("a", "b")]
        if kind == "reaction":
            out = raw.get("out", [])
            checks.append(_list_of(out, v.products(), "out", 0, MAX_PRODUCTS))
    elif kind == "drink":
        checks += [_one_of(raw.get("material"), v.materials, "material")]
        checks += [_one_of(raw.get("effect"), EFFECTS, "effect")]
    elif kind == "property":
        checks += [_one_of(raw.get("material"), v.materials, "material")]
        checks += [_one_of(raw.get("property"), v.properties, "property")]
    elif kind == "creature":
        checks += [_one_of(raw.get("creature"), v.creatures, "creature")]
        checks += [_one_of(raw.get("trait"), v.creature_traits, "trait")]
    elif kind == "spell":
        checks += [_one_of(raw.get("spell"), v.spells, "spell")]
        checks += [_one_of(raw.get("trait"), v.spell_traits, "trait")]
    elif kind == "scene":
        checks.append(_check_scene(raw, v))
    elif kind == "other":
        para = raw.get("paraphrase")
        if not isinstance(para, str) or not para.strip() or len(para) > MAX_TEXT:
            checks.append("paraphrase must be a short text")
    return next((c for c in checks if c is not None), None)


def _check_scene(raw: dict[str, Any], v: Vocabulary) -> str | None:
    topics = v.scene_topics.get(str(raw.get("encounter")))
    if topics is None:
        return f"encounter {str(raw.get('encounter'))[:20]!r} has no topic"
    values = topics.get(str(raw.get("topic")))
    if values is None:
        return f"topic {str(raw.get('topic'))[:40]!r} is not a topic of {raw['encounter']}"
    return _one_of(raw.get("value"), values, "value")


def check_fields(kind: str, raw: dict[str, Any], v: Vocabulary | None = None) -> str | None:
    """The reason the subject fields of a claim or a lesson are unusable, or None. Unknown keys
    are refused."""
    if kind not in FIELDS:
        return f"unknown kind {str(kind)[:30]!r}"
    extra = sorted(set(raw) - set(FIELDS[kind]) - set(COMMON_KEYS))
    if extra:
        return f"unknown key {extra[0]!r}"
    return _check_subject(kind, raw, v or vocabulary())


def parse_claim(
    raw: Any, note: str | None = None, v: Vocabulary | None = None
) -> tuple[Claim | None, str | None]:
    """`(claim, None)` or `(None, reason)`. With `note`, the quote must occur in it."""
    if not isinstance(raw, dict):
        return None, "a claim must be an object"
    raw = {k: val for k, val in raw.items() if val is not None}  # a flat schema may send nulls
    kind = raw.get("kind")
    if err := check_fields(str(kind), raw, v):
        return None, err
    hedged = raw.get("hedged", False)
    if not isinstance(hedged, bool):
        return None, "hedged must be true or false"
    quote = raw.get("text")
    if not isinstance(quote, str) or not quote.strip():
        return None, "text is missing"
    if len(quote) > MAX_TEXT:
        return None, f"text is longer than {MAX_TEXT} characters"
    if note is not None and (why := quote_problem(quote, note)) is not None:
        return None, why
    fields = {k: raw[k] for k in FIELDS[str(kind)] if k in raw}
    if kind == "reaction":
        fields.setdefault("out", [])
    return Claim(str(kind), fields, hedged, normalise(quote)), None


# ---------------------------------------------------------------------------- the file
def load_note_claims(path: Path | str) -> NoteClaims | None:
    """`notes_claims.json` at `path` (a file, or the run folder that holds it); None if missing,
    unreadable or of another format. A damaged claim is dropped, the rest is read."""
    p = Path(path)
    p = p / FILE_NAME if p.is_dir() else p
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return None
    extractor = doc.get("extractor")
    skipped = [s for s in doc.get("skipped") or [] if isinstance(s, dict)]
    return NoteClaims(
        extractor=extractor if isinstance(extractor, dict) else {},
        cost_usd=_number(doc.get("cost_usd")),
        calls=int(_number(doc.get("calls"))),
        start=_files(doc["start"]) if isinstance(doc.get("start"), dict) else None,
        end=_files(doc.get("end")),
        skipped=skipped,
    )


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _files(section: Any) -> dict[str, FileClaims]:
    out: dict[str, FileClaims] = {}
    files = section.get("files") if isinstance(section, dict) else None
    for path, entry in (files if isinstance(files, dict) else {}).items():
        if not isinstance(entry, dict):
            continue
        claims = []
        for raw in entry.get("claims") or []:
            claim, _why = parse_claim(raw)
            if claim is not None:
                claims.append(claim)
        dropped = tuple(d for d in entry.get("dropped") or [] if isinstance(d, dict))
        out[str(path)] = FileClaims(
            str(entry.get("sha256", "")), int(_number(entry.get("chars"))), tuple(claims), dropped
        )
    return out


def save_note_claims(doc: NoteClaims, path: Path | str) -> Path:
    p = Path(path)
    p = p / FILE_NAME if p.is_dir() else p
    p.write_text(json.dumps(doc.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
