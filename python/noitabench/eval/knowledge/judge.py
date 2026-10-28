"""Judging a claim against the knowledge base: all code, no model (contracts section 21).

    judge(claim, knowledge) -> Verdict {verdict, fact_id, tier, told, weight, subject}

`correct` weighs 1, `partial` 0.5, `wrong` 0; `unknown` (no fact covers the claim), `local` and
`other` are not counted. A hedged claim is judged like any other but never counted (`counts`).

- **recipe**: the named potion's ingredients exactly are correct; the right three under another
  potion's name, or two of three, are partial; else wrong. A potion described by its effect is
  found through its drink effect (`Knowledge.potion_with_effect`); one that no recipe makes
  (the healing potion) or an effect that fits no single potion is unknown.
- **no_recipe**: wrong if the three are a recipe, else correct. It never teaches (220 triples could
  be farmed): the verdict has no fact. A pair is not judged (a recipe needs all three).
- **reaction**: correct if a row joins the pair and every product claimed is among the row's
  products (a claim with no product named is correct); wrong if rows join the pair but none
  makes those products; unknown if no row joins them (burning and the like are not rows).
- **no_reaction**: wrong if a row joins the pair, or if one side is fire, lava or a burning cell
  and the other burns (ignition is not a row); else correct.
- **drink, property, creature, spell, scene**: the same value is correct; another value of the
  same family on the same subject is wrong; with no fact on the subject the claim is wrong where
  the data answers for every subject of the family (`Knowledge.closed`: a spell that is not a
  modifier is not a modifier) and unknown otherwise.

`subject_of` is the key two notebooks' claims are compared by (the subject of a recipe claim is the
potion; of a reaction claim the unordered pair).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .claims import Claim
from .facts import Fact, Knowledge
from .vocab import BURNING, creature_trait, family_of, property_trait, spell_trait

WEIGHTS = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}
COUNTED = tuple(WEIGHTS)
FIRE_SOURCES = ("fire", "lava", BURNING)
Subject = tuple[Any, ...]


@dataclass(frozen=True)
class Verdict:
    verdict: str  # correct, partial, wrong, unknown, local or other
    fact_id: str | None = None
    tier: str | None = None
    told: bool = False
    subject: Subject | None = None
    detail: str = ""

    @property
    def weight(self) -> float | None:
        return WEIGHTS.get(self.verdict)


def counts(claim: Claim, verdict: Verdict) -> bool:
    """True if the claim enters accuracy: judged right, partly right or wrong, and not hedged."""
    return verdict.verdict in COUNTED and not claim.hedged


def _from(fact: Fact | None, verdict: str, subject: Subject | None, detail: str = "") -> Verdict:
    if fact is None:
        return Verdict(verdict, None, None, False, subject, detail)
    return Verdict(verdict, fact.id, fact.tier, fact.told, subject, detail)


# ------------------------------------------------------------------------------------ subjects
def subject_of(claim: Claim, k: Knowledge | None = None) -> Subject | None:
    f, kind = claim.fields, claim.kind
    if kind == "recipe":
        potion = f.get("potion") or (k.potion_with_effect(f["effect"]) if k else None)
        return ("recipe", potion or f"effect:{f.get('effect')}")
    if kind == "no_recipe":
        return ("no_recipe", tuple(sorted(f["inputs"])))
    if kind in ("reaction", "no_reaction"):
        return ("reaction", *sorted((f["a"], f["b"])))
    if kind == "drink":
        return ("drink", f["material"])
    if kind == "property":
        return ("property", f["material"], _family(property_trait(f["property"]), f["property"]))
    if kind == "creature":
        return ("creature", f["creature"], _family(creature_trait(f["trait"]), f["trait"]))
    if kind == "spell":
        return ("spell", f["spell"], _family(spell_trait(f["trait"]), f["trait"]))
    if kind == "scene":
        return ("scene", f["encounter"], f["topic"])
    return None


def _family(trait: Any, key: str) -> str:
    return key if trait is None else family_of(trait, key)


# --------------------------------------------------------------------------------------- judge
def judge(claim: Claim, k: Knowledge) -> Verdict:
    subject = subject_of(claim, k)
    kind = claim.kind
    if kind in ("local", "other"):
        return Verdict(kind)
    if kind == "recipe":
        return _recipe(claim, k, subject)
    if kind == "no_recipe":
        return _no_recipe(claim, k, subject)
    if kind in ("reaction", "no_reaction"):
        return _reaction(claim, k, subject)
    if kind == "drink":
        fact = k.by_id.get(f"drink:{claim.fields['material']}")
        if fact is None:
            return Verdict("unknown", subject=subject)
        right = fact.fields["effect"] == claim.fields["effect"]
        return _from(fact, "correct" if right else "wrong", subject)
    if kind == "scene":
        f = claim.fields
        fact = k.by_id.get(f"scene:{f['encounter']}:{f['topic']}")
        if fact is None:
            return Verdict("unknown", subject=subject)
        return _from(fact, "correct" if fact.fields["value"] == f["value"] else "wrong", subject)
    return _trait(claim, k, subject)


def _recipe(claim: Claim, k: Knowledge, subject: Subject | None) -> Verdict:
    potion = claim.fields.get("potion") or k.potion_with_effect(claim.fields.get("effect", ""))
    fact = k.recipe(potion) if potion else None
    if fact is None:
        return Verdict("unknown", subject=subject, detail="no recipe makes that potion")
    claimed, real = set(claim.fields["inputs"]), set(fact.fields["inputs"])
    if claimed == real:
        return _from(fact, "correct", subject)
    elsewhere = [
        f for f in k.of_kind("recipe") if set(f.fields["inputs"]) == claimed and f is not fact
    ]
    if elsewhere:
        return _from(elsewhere[0], "partial", subject, "the right three, under another potion")
    if len(claimed & real) >= 2:
        return _from(fact, "partial", subject, "two of the three")
    return _from(fact, "wrong", subject)


def _no_recipe(claim: Claim, k: Knowledge, subject: Subject | None) -> Verdict:
    claimed = set(claim.fields["inputs"])
    if len(claimed) < 3:
        return Verdict("unknown", subject=subject, detail="a pair is not judged")
    for fact in k.of_kind("recipe"):
        if set(fact.fields["inputs"]) == claimed:
            return _from(fact, "wrong", subject, "these three do make a potion")
    return Verdict("correct", subject=subject, detail="these three make nothing")


def _joins(fact: Fact, a: str, b: str) -> bool:
    ma, mb = fact.fields["a_members"], fact.fields["b_members"]
    return (a in ma and b in mb) or (b in ma and a in mb)


def _reaction(claim: Claim, k: Knowledge, subject: Subject | None) -> Verdict:
    a, b = claim.fields["a"], claim.fields["b"]
    rows = [f for f in k.of_kind("reaction") if _joins(f, a, b)]
    if claim.kind == "no_reaction":
        if rows:
            return _from(rows[0], "wrong", subject, "a row joins them")
        burning = _ignition(a, b, k) or _ignition(b, a, k)
        if burning is not None:
            return _from(burning, "wrong", subject, "fire lights what burns")
        return Verdict("correct", subject=subject, detail="no row joins them")
    claimed = set(claim.fields.get("out", ()))
    for row in rows:
        if claimed <= set(row.fields["out"]):
            return _from(row, "correct", subject)
    if rows:
        return _from(rows[0], "wrong", subject, "they react, but not into that")
    return Verdict("unknown", subject=subject, detail="no row joins them")


def _ignition(source: str, target: str, k: Knowledge) -> Fact | None:
    """The `burns` fact of `target` if `source` is a flame (fire, lava, a burning cell)."""
    if source not in FIRE_SOURCES:
        return None
    return k.by_id.get(f"property:{target}:burns")


_TRAIT_LOOKUP = {
    "property": ("material", "property", property_trait),
    "creature": ("creature", "trait", creature_trait),
    "spell": ("spell", "trait", spell_trait),
}


def _trait(claim: Claim, k: Knowledge, subject: Subject | None) -> Verdict:
    who, which, finder = _TRAIT_LOOKUP[claim.kind]
    name, key = claim.fields[who], claim.fields[which]
    family = _family(finder(key), key)
    facts = k.about(claim.kind, name, family)
    for fact in facts:
        if fact.fields[which] == key:
            return _from(fact, "correct", subject)
    if facts:
        return _from(facts[0], "wrong", subject, "another value of the same family")
    if k.is_closed(claim.kind, family, name):
        return Verdict("wrong", subject=subject, detail="the data answers: it does not have it")
    return Verdict("unknown", subject=subject)


# ----------------------------------------------------------------------------- whole notebooks
@dataclass(frozen=True)
class Judged:
    """A claim with its verdict and the file it was found in."""

    path: str
    claim: Claim
    verdict: Verdict

    @property
    def counted(self) -> bool:
        return counts(self.claim, self.verdict)


def claim_key(claim: Claim) -> str:
    """The same statement written twice has one key (lists in a canonical order, the two sides of
    a reaction unordered), so that a note repeated across files is counted once."""
    fields = {k: sorted(v) if isinstance(v, list) else v for k, v in claim.fields.items()}
    if claim.kind in ("reaction", "no_reaction"):  # "lava + water" and "water + lava" are one
        fields["a"], fields["b"] = sorted((fields["a"], fields["b"]))
    return json.dumps([claim.kind, fields], sort_keys=True, ensure_ascii=False)


def judge_section(
    pairs: list[tuple[str, Claim]], k: Knowledge, *, distinct: bool = True
) -> list[Judged]:
    """Every `(path, claim)` judged; with `distinct`, a statement made in several files is judged
    once (the first file in path order, the hedged one kept only if no unhedged copy exists)."""
    out: list[Judged] = []
    seen: dict[str, int] = {}
    for path, claim in pairs:
        item = Judged(path, claim, judge(claim, k))
        if not distinct:
            out.append(item)
            continue
        key = claim_key(claim)
        if key not in seen:
            seen[key] = len(out)
            out.append(item)
        elif out[seen[key]].claim.hedged and not claim.hedged:
            out[seen[key]] = item
    return out
