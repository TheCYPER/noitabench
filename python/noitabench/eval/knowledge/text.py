"""The English sentences of the readable document, one per fact.

Facts carry their sentence (`Fact.note`); it is built here from the vocabulary's English names
(`name_en` of the content files), so a fact never needs a hand-written line. Only lessons that make
a fact of their own (a `scene` fact, a trait no data file states) bring their own sentence in the
encounter definition. Style: short and plain, one sentence per fact. A material is written in lower
case (`oil`, `toxic sludge`), a potion or a spell in quotes (`"Heal Potion"`, `"Spark Bolt"`, so
that the spell Water is not the material water), a creature by its name.
"""

from __future__ import annotations

from collections.abc import Sequence

from .vocab import (
    BURNING,
    EFFECTS,
    SPELL_TYPE_NAMES,
    Trait,
    Vocabulary,
    vocabulary,
)

TAG_LABELS = {
    "water_family": "water-family liquids",
    "corrodible": "things acid corrodes",
    "burnable": "burnable things",
    "burnable_fast": "highly flammable gases",
    "static": "solid terrain",
}
EXTINGUISH = "@extinguish"


def join_names(names: Sequence[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    items = list(names)
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def capitalise(sentence: str) -> str:
    return sentence[:1].upper() + sentence[1:]


def material_name(key: str, vocab: Vocabulary | None = None) -> str:
    if key == BURNING:
        return "something burning"
    if key == "air":
        return "air"
    v = vocab or vocabulary()
    if key in v.potions:
        return f'"{v.potions[key]}"'
    return v.materials[key].lower() if key in v.materials else key


def creature_name(key: str) -> str:
    return vocabulary().creatures[key]


def spell_name(key: str) -> str:
    return f'"{vocabulary().spells[key]}"'


def parameter_name(trait: Trait, parameter: str) -> str:
    if trait.param == "spell_type":
        return SPELL_TYPE_NAMES[parameter]
    return material_name(parameter)


def trait_sentence(trait: Trait, key: str, subject: str) -> str:
    """The sentence of a (possibly parameterised) property, creature or spell trait."""
    parameter = key.split(":", 1)[1] if ":" in key else ""
    return capitalise(
        trait.sentence.format(s=subject, p=parameter_name(trait, parameter) if parameter else "")
    )


def effect_text(effect: str) -> str:
    return EFFECTS.get(effect, effect)


def _side(token: str, members: Sequence[str]) -> str:
    if token == BURNING or token == "@burning":
        return material_name(BURNING)
    if not token.startswith("["):
        return material_name(token)
    if len(members) == 1:
        return material_name(members[0])
    label = TAG_LABELS.get(token.strip("[]"), token.strip("[]"))
    return f"{label} ({', '.join(material_name(m) for m in members)})"


def _out(token: str, members: Sequence[str]) -> str:
    if token == EXTINGUISH:
        return "the fire goes out"
    if token.startswith("[") and len(members) > 1:
        return "the same " + TAG_LABELS.get(token.strip("[]"), token.strip("[]"))
    return _side(token, members)


def reaction_sentence(
    a: str,
    b: str,
    out_a: str,
    out_b: str,
    members: dict[str, Sequence[str]],
) -> str:
    """`lava + water -> rock + steam`: two cells that touch, and what they become."""
    left = f"{_side(a, members[a])} + {_side(b, members[b])}"
    right = f"{_out(out_a, members.get(out_a, ()))} + {_out(out_b, members.get(out_b, ()))}"
    return f"{left} -> {right}"


def recipe_sentence(potion: str, inputs: Sequence[str]) -> str:
    return f"{material_name(potion)} is mixed from {join_names([material_name(m) for m in inputs])}"


def drink_sentence(material: str, effect: str) -> str:
    return f"Drinking {material_name(material)}: {effect_text(effect)}"
