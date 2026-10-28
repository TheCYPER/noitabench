"""The readable copy of the knowledge base: `docs/knowledge-base.md` (contracts section 21).

One English line per fact, grouped by tier and kind, without the recipes: they differ for every
rule seed and a human participant never sees one (a line says how a recipe looks, and how a
researcher prints one seed's). The text depends on the data files only, so it is the same for
every rule seed; a test compares the committed file with a fresh render.
"""

from __future__ import annotations

from . import data
from .facts import Fact, build_knowledge
from .text import join_names
from .vocab import FACT_KINDS, TIER_RANK, vocabulary

KIND_TITLES = {
    "reaction": "Reactions (what happens when two things touch)",
    "drink": "What drinking does",
    "property": "Properties of materials",
    "creature": "Creatures",
    "spell": "Spells",
    "scene": "What the encounters teach",
}
TIER_TITLES = {
    "seed": "1. Different for every rule seed: the secret recipes",
    "game": "2. Knowledge that belongs to this game",
    "common": "3. Noita common knowledge",
}
TIER_ABOUT = {
    "game": "This is the game's own content, or what an encounter is there to teach. A player has "
    "a chance to learn it only by meeting the matching encounter.",
    "common": "Knowledge from the original Noita. Someone who has played it (or a model from "
    "memory) may know it already; an encounter that leans on it changes nothing: a correct note "
    'is correct, but it is not "something new learned".',
}
HEADER = """\
# Knowledge base (the answer key for the notes)

Generated from `content/*.json` by `python -m noitabench knowledge --doc docs/knowledge-base.md`; \
please do not edit by hand.
When a run is scored, the agent's notes are turned into claims of a fixed form, and each claim is \
checked against the facts below: a match is one note that is right.

- [told]: the game already told the player this (a potion's name states its effect, a spell card \
shows its type and uses). Writing it down counts for the accuracy of the notes, not for \
"learned something new".
- (scenes: ...): this fact is what that encounter asks about.
- The code at the end of a line is the id of the fact.
"""
RECIPES = """\
In every rule seed, each of the {count} secret potions ({names}) has one recipe: 3 ingredients \
drawn from a pool of {pool} materials. Put together in one bottle, or poured together, they \
become the potion.
The recipes differ from seed to seed and are not listed in this document (a human participant \
must not see them). Researchers print one seed's recipes with \
`python -m noitabench knowledge --seed N`.
"""


def _scenes(fact: Fact) -> str:
    names = [f"{e} {data.encounters()[e]['name_en']}" for e in fact.encounters]
    return f" (scenes: {', '.join(names)})" if names else ""


def _line(fact: Fact) -> str:
    told = " [told]" if fact.told else ""
    return f"- {fact.note}{told}{_scenes(fact)} `{fact.id}`"


def _order(fact: Fact) -> tuple[int, str, str]:
    """Properties, creatures and spells sort by their subject, the rest in build order."""
    subject = fact.subject
    if subject is None:
        return (0, "", "")
    keys = list(vocabulary().materials) + list(vocabulary().creatures) + list(vocabulary().spells)
    return (keys.index(subject), subject, fact.id)


def render_document() -> str:
    """The Markdown text of `docs/knowledge-base.md`."""
    facts = [f for f in build_knowledge(0).facts if f.kind != "recipe"]
    out = [HEADER]
    v = vocabulary()
    recipes = RECIPES.format(
        count=len(v.secret),
        names=join_names([v.potions[p] for p in v.secret]),
        pool=len(data.tag_members()["ingredient"]),
    )
    out.append(f"## {TIER_TITLES['seed']}\n\n{recipes}")
    for tier in sorted(TIER_TITLES, key=TIER_RANK.get):  # type: ignore[arg-type]
        if tier == "seed":
            continue
        in_tier = [f for f in facts if f.tier == tier]
        out.append(f"## {TIER_TITLES[tier]}\n\n{TIER_ABOUT[tier]} ({len(in_tier)} facts)\n")
        for kind in FACT_KINDS:
            rows = [f for f in in_tier if f.kind == kind]
            if not rows:
                continue
            ordered = (
                sorted(rows, key=_order) if kind in ("property", "creature", "spell") else rows
            )
            out.append(f"### {KIND_TITLES[kind]} ({len(rows)})\n")
            out.append("\n".join(_line(f) for f in ordered) + "\n")
    return "\n".join(out).rstrip("\n") + "\n"


def recipe_lines(rule_seed: int) -> list[str]:
    """The recipes of one rule seed, one line each (researchers only)."""
    return [f.note for f in build_knowledge(rule_seed).of_kind("recipe")]


__all__ = ["recipe_lines", "render_document"]
