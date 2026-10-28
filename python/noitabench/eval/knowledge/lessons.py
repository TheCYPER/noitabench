"""Encounter lessons: what a scene teaches, as facts (contracts section 21).

An encounter definition (`content/encounters/EXX.json`) may carry

    "lessons": [{"claim": {...}, "note": "..."}, {"claim": {...}, "tier": "game", ...}, ...]
    "lesson_topics": {"<topic>": {"values": [...], "about": "..."}}

A lesson is true whatever the variant, and states something the scene's question depends on. Its
`claim` is written in the claim schema (`claims.py`: the subject fields of a fact kind, no
`hedged`, no `text`), preferring the generic kinds:

- a `reaction`, `drink`, `property`, `creature` or `spell` claim must be *judged correct by the
  data files* (the same judge that judges notes); the lesson then only **links** the fact it names
  to the scene (`Fact.encounters`). The fact keeps the tier the data gives it: Noita knowledge
  that a scene leans on stays `common` (correct when written, never "learned something new").
  Such a lesson carries no `tier` (the loader refuses one: it would be ignored). A lesson that
  contradicts the data is an error: the build stops;
- a `creature` claim of a trait that no data file states (`vocab.Trait.closed` is false:
  `cannot_cross_deep_water`) and every `scene` claim make a fact of their own, with the lesson's
  `note` as its sentence and its `tier` (required of these lessons only). A `scene` claim names
  its own encounter, a topic of its `lesson_topics` and one of that topic's closed `values`; the
  list of values is vocabulary (it holds the true one among the others).

`note` is required of every lesson (it documents why the scene teaches it) but is shown only for
a fact the lesson makes itself; a linked fact keeps the sentence built from the data.
A fact several lessons make takes the tier that is harder to know in advance (`seed` over `game`
over `common`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import data
from .claims import Claim, check_fields
from .facts import Fact, Knowledge
from .judge import judge
from .vocab import (
    FACT_KINDS,
    TIERS,
    creature_trait,
    family_of,
    spell_trait,
    vocabulary,
)

LESSON_KINDS = tuple(k for k in FACT_KINDS if k != "recipe")


@dataclass(frozen=True)
class Lesson:
    encounter: str
    index: int
    claim: dict[str, Any]
    tier: str | None  # only a lesson that makes its own fact has one
    note: str

    @property
    def where(self) -> str:
        return f"{self.encounter}.json lessons[{self.index}]"


def load_lessons() -> list[Lesson]:
    """Every lesson of every encounter definition, checked for shape (not yet for truth)."""
    out: list[Lesson] = []
    for eid, doc in data.encounters().items():
        raw = doc.get("lessons") or []
        if not isinstance(raw, list):
            raise TypeError(f"{eid}.json: lessons must be a list")
        for i, entry in enumerate(raw):
            out.append(_parse(eid, i, entry))
    return out


def _parse(eid: str, index: int, entry: Any) -> Lesson:
    where = f"{eid}.json lessons[{index}]"
    if not isinstance(entry, dict) or not isinstance(entry.get("claim"), dict):
        raise TypeError(f"{where}: needs a claim object")
    claim, tier, note = dict(entry["claim"]), entry.get("tier"), entry.get("note")
    if set(entry) - {"claim", "tier", "note"}:
        raise ValueError(f"{where}: unknown key {sorted(set(entry) - {'claim', 'tier', 'note'})}")
    if not isinstance(note, str) or not note.strip():
        raise ValueError(f"{where}: note is required")
    kind = str(claim.get("kind"))
    if kind not in LESSON_KINDS:
        raise ValueError(f"{where}: kind must be one of {LESSON_KINDS}")
    if "hedged" in claim or "text" in claim:
        raise ValueError(f"{where}: a lesson claim has no hedged or text")
    if reason := check_fields(kind, claim):
        raise ValueError(f"{where}: {reason}")
    if kind == "scene" and claim["encounter"] != eid:
        raise ValueError(f"{where}: a scene lesson names its own encounter")
    fields = {k: v for k, v in claim.items() if k != "kind"}
    if _makes_own_fact(kind, fields):
        if tier not in TIERS:
            raise ValueError(
                f"{where}: this lesson makes its own fact: tier must be one of {TIERS}"
            )
    elif tier is not None:
        raise ValueError(
            f"{where}: no tier here: the fact is stated by the data files, which give it its tier"
        )
    return Lesson(eid, index, {"kind": kind, **fields}, tier, note.strip())


def _open_trait(kind: str, fields: dict[str, Any]) -> Any:
    """The trait of a creature or spell claim that no data file states, else None."""
    finder = {"creature": creature_trait, "spell": spell_trait}.get(kind)
    trait = finder(fields["trait"]) if finder else None
    return trait if trait is not None and not trait.closed else None


def _makes_own_fact(kind: str, fields: dict[str, Any]) -> bool:
    return kind == "scene" or _open_trait(kind, fields) is not None


def _own_fact(lesson: Lesson) -> Fact | None:
    """The fact a lesson makes by itself, or None when it names a fact of the data files."""
    kind, f = lesson.claim["kind"], {k: v for k, v in lesson.claim.items() if k != "kind"}
    trait = _open_trait(kind, f)
    if kind != "scene" and trait is None:
        return None
    tier = lesson.tier
    if tier is None:  # `_parse` demands one of these lessons
        raise ValueError(f"{lesson.where}: this lesson makes its own fact and needs a tier")
    if kind == "scene":
        return Fact(
            f"scene:{f['encounter']}:{f['topic']}",
            "scene",
            tier,
            False,
            f,
            (lesson.encounter,),
            lesson.note,
        )
    family = family_of(trait, f["trait"])
    return Fact(
        f"{kind}:{f[kind]}:{f['trait']}",
        kind,
        tier,
        False,
        {**f, "family": family},
        (lesson.encounter,),
        lesson.note,
    )


def apply_lessons(base: Knowledge) -> Knowledge:
    """`base` with the lessons applied: facts linked to their scenes, lesson facts added."""
    facts = list(base.facts)
    index = {f.id: i for i, f in enumerate(facts)}
    for lesson in load_lessons():
        own = _own_fact(lesson)
        if own is not None:
            _add_own(facts, index, own, lesson)
        else:
            _link(facts, index, base, lesson)
    return Knowledge(base.rule_seed, tuple(facts), base.closed)


def _add_own(facts: list[Fact], index: dict[str, int], own: Fact, lesson: Lesson) -> None:
    if own.id in index:
        old = facts[index[own.id]]
        if old.fields != own.fields:
            raise ValueError(f"{lesson.where}: contradicts another lesson on {own.id}")
        facts[index[own.id]] = old.linked(lesson.encounter, own.tier)
        return
    index[own.id] = len(facts)
    facts.append(own)


def _link(facts: list[Fact], index: dict[str, int], base: Knowledge, lesson: Lesson) -> None:
    claim = Claim(lesson.claim["kind"], {k: v for k, v in lesson.claim.items() if k != "kind"})
    verdict = judge(claim, base)
    if verdict.verdict != "correct" or verdict.fact_id is None:
        raise ValueError(
            f"{lesson.where}: the data files do not say this ({verdict.verdict}"
            f"{': ' + verdict.detail if verdict.detail else ''}): {lesson.claim}"
        )
    i = index[verdict.fact_id]
    facts[i] = facts[i].linked(lesson.encounter)


def topics_without_lesson() -> list[tuple[str, str]]:
    """`(encounter, topic)` pairs of the vocabulary that no lesson states a value for."""
    stated = {(l.encounter, l.claim["topic"]) for l in load_lessons() if l.claim["kind"] == "scene"}
    return sorted(set(vocabulary().scene_about) - stated)
