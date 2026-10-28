"""The knowledge base: every fact the game's data files state, as the answer key for notes.

    build_knowledge(rule_seed) -> Knowledge

is a pure function of `content/{materials,reactions,entities,spells}.json`,
`content/encounters/E*.json` and `noitabench_core.recipes(rule_seed)` (contracts section 21).

A **fact** is `{id, kind, tier, told, fields, encounters, note}`:

- `recipe`  the potion and its three ingredients (a `seed` fact: it differs for every rule seed);
- `reaction` one per row of `reactions.json`, tags expanded to the materials that carry them
  (`@burning` is "a cell on fire"; `@extinguish` is no product);
- `drink`    what drinking a liquid does (`drink_effect`);
- `property` a key of `vocab.PROPERTIES` for a material, from the material rows alone, plus the
  harm of a contact status of `entities.json` (toxic sludge poisons) which counts as harm;
- `creature` and `spell`  traits read from `entities.json` and `spells.json`;
- `scene`    a statement an encounter lesson makes that no generic kind can say.

`tier` is `seed` (recipes), `game` (ours: lessons, materials with no `noita_id`, reaction rows
that the data marks as ours or changed) or `common` (Noita knowledge: the rest). The tier of a fact
that the data files state comes from the data alone: an encounter lesson that names it only links
it to the scene (Noita knowledge stays `common` however much a scene leans on it). A lesson sets
the tier of the facts it makes itself (`scene` and lesson-only traits, see `lessons.py`). `told`
marks what the agent is shown
(a potion's drink effect, the data of a spell card); told facts count for a note's accuracy and
never for what a game taught.

`told`: the system prompt (`harness/prompt.py`) and the command descriptions (`agent/spec.py`) state
no fact of these kinds (they say that liquids flow and materials change when they touch, not how);
what the agent is shown is a potion's name, which states its drink effect, and the numbers of a
spell card (`agent/inspecting.py`: type, uses, effects, trail, bounces, emitted material, blast
radius, trigger, mana, speed), which `Trait.told` and `_spell_keys` mirror. The blast durability a
modifier adds and the lighting power of a fireball are not on the card.

What is not a fact: places in a world (true in one cave only) and numbers (HP, damage, timings).
Where the spec is silent: a disagreement of density is a fact only for unequal densities (a
powder resting on a liquid of its own density neither floats nor sinks); `harms_on_contact`
covers a poisoning contact; `digs_terrain` is a blast of radius 5 or more, `blasts` one of 10 or
more; `looks_like` is the CIE76 colour distance below `LOOKS_ALIKE_DELTA_E` between two natural
liquids.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from functools import cache, cached_property
from typing import Any

from .. import worldinfo
from . import data, text
from .vocab import (
    BLAST_RADIUS,
    CREATURE_TRAITS,
    DIG_RADIUS,
    LOOKS_ALIKE_DELTA_E,
    SPELL_TRAITS,
    TIER_RANK,
    family_of,
    property_trait,
    vocabulary,
)

BURNING_TOKEN, EXTINGUISH_TOKEN = "@burning", "@extinguish"
HARMFUL_CONTACT_STATUSES = frozenset({"poisoned"})
BURNABLE_TAGS = frozenset({"burnable", "burnable_fast"})
SUBJECT_FIELD = {"property": "material", "creature": "creature", "spell": "spell"}
ClosedSets = dict[tuple[str, str], frozenset[str]]


@dataclass(frozen=True)
class Fact:
    id: str
    kind: str
    tier: str
    told: bool
    fields: dict[str, Any]
    encounters: tuple[str, ...] = ()
    note: str = ""

    @property
    def family(self) -> str | None:
        return self.fields.get("family")

    @property
    def subject(self) -> str | None:
        field_name = SUBJECT_FIELD.get(self.kind)
        return None if field_name is None else self.fields[field_name]

    def linked(self, encounter: str, tier: str | None = None) -> Fact:
        """The fact with a lesson of `encounter` attached. The tier stays the fact's own; only a
        fact that lessons make themselves (`tier` given) takes the harder of its two tiers."""
        scenes = tuple(sorted({*self.encounters, encounter}))
        if tier is None:
            return replace(self, encounters=scenes)
        return replace(self, encounters=scenes, tier=_lower_rank(self.tier, tier))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "tier": self.tier,
            "told": self.told,
            "fields": self.fields,
            "encounters": list(self.encounters),
            "note": self.note,
        }


def _lower_rank(a: str, b: str) -> str:
    """Of two tiers the one that is harder to know in advance (`seed` before `game`)."""
    return a if TIER_RANK[a] <= TIER_RANK[b] else b


@dataclass(frozen=True)
class Knowledge:
    rule_seed: int
    facts: tuple[Fact, ...]
    closed: ClosedSets = field(default_factory=dict)

    @cached_property
    def by_id(self) -> dict[str, Fact]:
        return {f.id: f for f in self.facts}

    @cached_property
    def _by_subject(self) -> dict[tuple[str, str, str], list[Fact]]:
        out: dict[tuple[str, str, str], list[Fact]] = {}
        for f in self.facts:
            if f.kind in SUBJECT_FIELD and f.family is not None:
                out.setdefault((f.kind, f.subject or "", f.family), []).append(f)
        return out

    def of_kind(self, kind: str) -> list[Fact]:
        return [f for f in self.facts if f.kind == kind]

    def about(self, kind: str, subject: str, family: str) -> list[Fact]:
        """The facts of a property, creature or spell family for one subject."""
        return self._by_subject.get((kind, subject, family), [])

    def is_closed(self, kind: str, family: str, subject: str) -> bool:
        return subject in self.closed.get((kind, family), frozenset())

    def recipe(self, potion: str) -> Fact | None:
        return self.by_id.get(f"recipe:{potion}")

    def potion_with_effect(self, effect: str) -> str | None:
        """The one secret potion whose drink effect is `effect`, else None."""
        found = [
            d.fields["material"]
            for d in self.of_kind("drink")
            if d.fields["effect"] == effect and self.recipe(d.fields["material"]) is not None
        ]
        return found[0] if len(found) == 1 else None

    def as_dict(self) -> dict[str, Any]:
        return {"rule_seed": self.rule_seed, "facts": [f.as_dict() for f in self.facts]}


class _Builder:
    def __init__(self) -> None:
        self.facts: list[Fact] = []
        self.closed: dict[tuple[str, str], set[str]] = {}

    def add(self, fact: Fact) -> None:
        self.facts.append(fact)

    def universe(self, kind: str, family: str, subjects: Any) -> None:
        self.closed.setdefault((kind, family), set()).update(subjects)


def _ours(*keys: str) -> bool:
    """True if any of the materials has no Noita original (`noita_id` null)."""
    table = data.material_table()
    return any(table[k].get("noita_id") is None for k in keys)


def _tier_of(*keys: str) -> str:
    return "game" if _ours(*keys) else "common"


# -------------------------------------------------------------------------------------- recipes
def _recipes(rule_seed: int, out: _Builder) -> None:
    import noitabench_core

    for row in noitabench_core.recipes(rule_seed):
        potion, inputs = str(row["potion"]), sorted(row["inputs"])
        out.add(
            Fact(
                f"recipe:{potion}",
                "recipe",
                "seed",
                False,
                {"potion": potion, "inputs": inputs},
                note=text.recipe_sentence(potion, inputs),
            )
        )


# ------------------------------------------------------------------------------------ reactions
def _members(token: str) -> tuple[str, ...]:
    if token == BURNING_TOKEN:
        return ("burning",)
    if token == EXTINGUISH_TOKEN:
        return ()
    if token.startswith("["):
        members = data.tag_members().get(token.strip("[]"), ())
        if not members:
            raise ValueError(f"reactions.json: tag {token} has no members")
        return members
    return (token,)


def _reactions(out: _Builder) -> None:
    for row in data.reactions():
        tokens = [row["a"], row["b"], row["out_a"], row["out_b"]]
        members = {t: _members(t) for t in tokens}
        products = sorted({m for t in tokens[2:] for m in members[t]})
        source = str(row.get("source", ""))
        mats = [m for t in tokens for m in members[t] if m != "burning"]
        tier = "game" if ("ours" in source or "changed" in source) else _tier_of(*mats)
        out.add(
            Fact(
                f"reaction:{row['id']}",
                "reaction",
                tier,
                False,
                {
                    "row": row["id"],
                    "a": row["a"],
                    "b": row["b"],
                    "a_members": list(members[row["a"]]),
                    "b_members": list(members[row["b"]]),
                    "out": products,
                },
                note=text.reaction_sentence(*tokens, members),
            )
        )


# ---------------------------------------------------------------------------------------- drinks
def _drinks(out: _Builder) -> None:
    for m in data.materials():
        if m["kind"] != "liquid" or m["key"] == "air":
            continue
        effect = str(m.get("drink_effect") or "none")
        out.add(
            Fact(
                f"drink:{m['key']}",
                "drink",
                _tier_of(m["key"]),
                m["family"] == "potion",  # the display name states what a potion does
                {"material": m["key"], "effect": effect},
                note=text.drink_sentence(m["key"], effect),
            )
        )


# ------------------------------------------------------------------------------------ properties
def _lab(color: str) -> tuple[float, float, float]:
    """CIE L*a*b* (D65) of a `#rrggbb` colour."""
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(u: float) -> float:
        return ((u + 0.055) / 1.055) ** 2.4 if u > 0.04045 else u / 12.92

    r, g, b = lin(r), lin(g), lin(b)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _burns(m: dict[str, Any]) -> bool:
    return bool(m.get("burnable")) or bool(BURNABLE_TAGS & set(m.get("tags", ())))


def _harms(m: dict[str, Any], contact: dict[str, Any]) -> bool:
    status = (contact.get("status") or {}).get(m["key"])
    return (
        float(m.get("contact_damage_per_px_frame") or 0) > 0
        or status in HARMFUL_CONTACT_STATUSES
        or m["key"] in contact.get("ignite", ())
    )


def _prop(out: _Builder, material: str, key: str, tier: str | None = None) -> None:
    trait = property_trait(key)
    assert trait is not None, key
    family = family_of(trait, key)
    sentence = text.trait_sentence(trait, key, text.material_name(material))
    out.add(
        Fact(
            f"property:{material}:{key}",
            "property",
            tier or _tier_of(material),
            False,
            {"material": material, "property": key, "family": family},
            note=sentence,
        )
    )


def _properties(out: _Builder) -> None:
    mats = [m for m in data.materials() if m["key"] != "air"]
    matter = [
        m
        for m in mats
        if m["kind"] in ("liquid", "powder", "static", "gas") and m["family"] != "potion"
    ]
    contact = data.entities()["contact"]
    keys = worldinfo.material_keys()
    hard = {keys[i] for i in worldinfo.undiggable_indices()}
    solid = [m for m in matter if m["kind"] in ("liquid", "powder", "static")]
    for m in matter:
        _prop(out, m["key"], "burns" if _burns(m) else "does_not_burn")
    for m in solid:
        if m["key"] != "acid":
            corroded = "corrodible" in m["tags"]
            _prop(out, m["key"], "corroded_by_acid" if corroded else "resists_acid")
    for m in matter:
        if m["kind"] in ("powder", "static") and m["key"] in hard:
            _prop(out, m["key"], "undiggable")
        if m["kind"] in ("liquid", "powder", "static") and _harms(m, contact):
            _prop(out, m["key"], "harms_on_contact")
        if m.get("explosion"):
            _prop(out, m["key"], "explodes_when_lit")
    out.universe("property", "dig", [m["key"] for m in matter if m["kind"] in ("powder", "static")])
    out.universe("property", "contact", [m["key"] for m in solid])
    out.universe("property", "explode", [m["key"] for m in matter])
    _density_facts(out, matter)
    _look_facts(out, vocabulary().liquids)


def _density_facts(out: _Builder, matter: list[dict[str, Any]]) -> None:
    table = data.material_table()
    movers = [m for m in matter if m["kind"] in ("liquid", "powder")]
    for liquid in vocabulary().liquids:
        for m in movers:
            if m["key"] == liquid or m["density"] == table[liquid]["density"]:
                continue
            key = (
                "floats_on" if m["density"] < table[liquid]["density"] else "sinks_in"
            ) + f":{liquid}"
            _prop(out, m["key"], key, _tier_of(m["key"], liquid))


def _look_facts(out: _Builder, liquids: tuple[str, ...]) -> None:
    table = data.material_table()
    for a in liquids:
        for b in liquids:
            if a != b:
                gap = math.dist(_lab(table[a]["color"]), _lab(table[b]["color"]))
                if gap < LOOKS_ALIKE_DELTA_E:
                    _prop(out, a, f"looks_like:{b}", _tier_of(a, b))


# -------------------------------------------------------------------------------------- creatures
def _creature_keys(spec: dict[str, Any]) -> list[str]:
    mult = spec.get("damage_mult") or {}
    keys = ["shoots" if spec.get("ranged") else "melee_only"]
    if spec.get("ai") == "leaper":
        keys.append("leaps_at_you")
    if mult.get("fire", 1.0) == 0:
        keys.append("immune_to_fire")
    if float(spec.get("ignite_percent", 0)) >= 50:
        keys.append("catches_fire_easily")
    if float(spec.get("wet_damage_per_s", 0)) > 0 or (spec.get("contact_damage") or {}).get(
        "water"
    ):
        keys.append("hurt_by_water")
    if any(float(h.get("mult", 1.0)) > 1.0 for h in spec.get("hitboxes", ())):
        keys.append("headshot_bonus")
    if mult.get("explosion", 1.0) < 1.0:
        keys.append("resists_explosions")
    return keys


def _creatures(out: _Builder) -> None:
    vocab = vocabulary()
    traits = {t.key: t for t in CREATURE_TRAITS}
    for creature, spec in data.entities()["enemies"].items():
        for key in _creature_keys(spec):
            trait = traits[key]
            out.add(
                Fact(
                    f"creature:{creature}:{key}",
                    "creature",
                    "common",
                    False,
                    {"creature": creature, "trait": key, "family": trait.family},
                    note=text.trait_sentence(trait, key, text.creature_name(creature)),
                )
            )
    for trait in CREATURE_TRAITS:
        if trait.closed:
            out.universe("creature", trait.family, vocab.creatures)


# ---------------------------------------------------------------------------------------- spells
def _spell_keys(row: dict[str, Any]) -> list[tuple[str, bool | None]]:
    """The traits of a spell card as `(key, told)`; `told` None means the trait's own default."""
    shot, proj = row["shot"], row.get("projectile") or {}
    blast = proj.get("explosion") or {}
    radius = blast.get("radius", 0)
    keys: list[tuple[str, bool | None]] = [(f"type:{row['type']}", None)]
    keys.append(("limited_uses" if row["max_uses"] else "unlimited_uses", None))
    if radius >= DIG_RADIUS:
        keys.append(("digs_terrain", None))
    if radius >= BLAST_RADIUS:
        keys.append(("blasts", None))
    shown_fire = "on_fire" in shot["effects"] or any(t["material"] == "fire" for t in shot["trail"])
    if shown_fire or proj.get("ignite_radius", 0) > 0:
        keys.append(("ignites", shown_fire))
    keys += [(f"makes_{e}", None) for e in ("wet", "oiled") if e in shot["effects"]]
    keys += [(f"leaves_trail:{t['material']}", None) for t in shot["trail"]]
    if proj.get("emit"):
        keys.append((f"sprays:{proj['emit']['material']}", None))
    if shot["bounces"] > 0 or proj.get("bounces", 0) > 0:
        keys.append(("bounces", None))
    if row["mana"] < 0:
        keys.append(("adds_mana", None))
    if shot["speed_mul"] > 1:
        keys.append(("speeds_up", None))
    elif shot["speed_mul"] < 1:
        keys.append(("slows_shot", None))
    trigger = (row.get("trigger") or {}).get("kind")
    if trigger:
        keys.append(("triggers_on_hit" if trigger == "collision" else "triggers_on_timer", None))
    if shot["explosion_radius"] > 0:
        keys.append(("enlarges_blast", None))
    if shot["explosion_durability"] > 0:
        keys.append(("raises_blast_durability", None))
    return keys


def _spells(out: _Builder) -> None:
    vocab = vocabulary()
    traits = {t.key: t for t in SPELL_TRAITS}
    families: set[str] = set()
    for row in data.spells():
        for key, told in _spell_keys(row):
            trait = traits[key.split(":")[0]]
            family = family_of(trait, key)
            families.add(family)
            out.add(
                Fact(
                    f"spell:{row['key']}:{key}",
                    "spell",
                    "common",
                    trait.told if told is None else told,
                    {"spell": row["key"], "trait": key, "family": family},
                    note=text.trait_sentence(trait, key, text.spell_name(row["key"])),
                )
            )
    for family in sorted(families):
        out.universe("spell", family, vocab.spells)


# ------------------------------------------------------------------------------------ the whole
@cache
def build_knowledge(rule_seed: int) -> Knowledge:
    """The knowledge base of a rule seed (cached)."""
    from . import lessons

    out = _Builder()
    _recipes(rule_seed, out)
    _reactions(out)
    _drinks(out)
    _properties(out)
    _creatures(out)
    _spells(out)
    closed = {k: frozenset(v) for k, v in out.closed.items()}
    base = Knowledge(rule_seed, tuple(out.facts), closed)
    return lessons.apply_lessons(base)


__all__ = ["Fact", "Knowledge", "build_knowledge"]
