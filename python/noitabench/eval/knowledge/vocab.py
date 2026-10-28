"""The closed vocabulary of facts and claims (contracts section 21).

A fact and a claim are both a *kind* plus *subject fields* whose values come from the lists here,
so a claim can be compared with a fact by plain equality. Nothing in this module is a truth about
a game: it names what can be said (a material, a drink effect, a property key...), with a
definition of each word, and both sides of every pair (`burns` and `does_not_burn`) are there, so
that the list reveals nothing to a model that is shown it (the extractor's prompt is built from
it). Names and sentences are English: the game, the harness and the agents are English, and the
extractor reads a note in any language.

Traits and properties come in *families*: the keys of one family say contrary things about the
same subject (`burns` / `does_not_burn`; `floats_on:water` / `sinks_in:water`; `type:modifier` /
`type:projectile`). A key that stands alone is its own family. A family is *closed* when the data
answers it for every subject of its universe: then a subject without the trait is known not to
have it (a claim that it has it is wrong), otherwise a claim the data does not mention is
`unknown` (`looks_like`, traits that only an encounter lesson states).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from . import data

BURNING = "burning"  # the claim token for "a cell that is on fire" (`@burning` of reactions.json)
AIR = "air"

FACT_KINDS = ("recipe", "reaction", "drink", "property", "creature", "spell", "scene")
CLAIM_KINDS = (*FACT_KINDS, "no_recipe", "no_reaction", "local", "other")
TIERS = ("seed", "game", "common")  # from the least to the most knowable in advance
TIER_RANK = {tier: i for i, tier in enumerate(TIERS)}
MAX_TEXT = 200  # characters of a note a claim may quote

# a liquid blast of at least this radius is a big explosion; at least the smaller one digs ground
BLAST_RADIUS, DIG_RADIUS = 10, 5
LOOKS_ALIKE_DELTA_E = 40.0  # CIE76 colour distance below which two liquids look alike

# ---------------------------------------------------------------------- drink effects
EFFECTS: dict[str, str] = {
    "none": "nothing happens",
    "wet": "makes you wet",
    "oiled": "covers you in oil, so that you catch fire easily",
    "drunk": "makes you drunk, your aim shakes",
    "damage": "hurts you",
    "burn": "burns you and sets you on fire",
    "poisoned": "poisons you, a slow loss of health",
    "heal": "heals you",
    "mana": "refills the mana of your wand",
    "haste": "makes you faster for a while",
    "regeneration": "heals you steadily for a while",
    "invulnerable": "no damage can hurt you for a while",
    "mana_regen": "your wands regain mana faster for a while",
    "crit_boost": "raises your chance of a critical hit for a while",
    "berserk": "doubles the damage of your shots for a while",
    "levitation": "flying costs no energy for a while",
    "invisible": "enemies cannot see you for a while; casting or kicking shows you for a moment",
    "fireproof": "you cannot catch fire for a while",
}


@dataclass(frozen=True)
class Trait:
    """One key of the property, creature or spell vocabulary.

    `sentence` is the line of the readable document (`{s}` the subject, `{p}` the parameter);
    `definition` is what the extractor reads. `param` is `liquid` (a natural liquid), `emitted`
    (a liquid or fire) or `spell_type` for a key written `key:<parameter>`. `told` says whether
    the game shows the agent the data this trait is read from (a spell card, for instance);
    `closed` see the module docstring."""

    key: str
    family: str
    sentence: str
    definition: str
    param: str | None = None
    closed: bool = True
    told: bool = False


PROPERTIES: tuple[Trait, ...] = (
    Trait("burns", "burn", "{s} burns", "the material catches fire and burns"),
    Trait("does_not_burn", "burn", "{s} does not burn", "the material does not burn"),
    Trait(
        "corroded_by_acid",
        "acid",
        "{s} is eaten away by acid",
        "acid eats the material away",
    ),
    Trait("resists_acid", "acid", "{s} resists acid", "acid does not eat the material"),
    Trait(
        "undiggable",
        "dig",
        "{s} cannot be broken by the starting digging spell",
        "the starting digging spell cannot break the material",
    ),
    Trait(
        "harms_on_contact",
        "contact",
        "Touching {s} hurts you (damage, poison or fire)",
        "touching or swimming in the material hurts, poisons or burns you",
    ),
    Trait(
        "explodes_when_lit",
        "explode",
        "{s} explodes when fire reaches it",
        "the material explodes when fire reaches it",
    ),
    Trait(
        "floats_on",
        "density:{p}",
        "{s} floats on {p}",
        "the material floats on top of {p}",
        "liquid",
    ),
    Trait(
        "sinks_in", "density:{p}", "{s} sinks below {p}", "the material sinks below {p}", "liquid"
    ),
    Trait(
        "looks_like",
        "look:{p}",
        "{s} looks like {p} (the colours are close, easy to confuse)",
        "the colour of the material is easy to confuse with {p}",
        "liquid",
        closed=False,
    ),
)

CREATURE_TRAITS: tuple[Trait, ...] = (
    Trait("shoots", "ranged", "{s} shoots from a distance", "it shoots at you from a distance"),
    Trait("melee_only", "ranged", "{s} only fights up close", "it only fights up close"),
    Trait("leaps_at_you", "leaps_at_you", "{s} leaps at you", "it leaps at you"),
    Trait("immune_to_fire", "immune_to_fire", "{s} is immune to fire", "fire does it no harm"),
    Trait(
        "catches_fire_easily",
        "catches_fire_easily",
        "{s} catches fire easily",
        "it catches fire easily",
    ),
    Trait("hurt_by_water", "hurt_by_water", "Water hurts {s}", "water hurts it"),
    Trait(
        "headshot_bonus",
        "headshot_bonus",
        "A hit on the head hurts {s} more",
        "a hit on its head does more",
    ),
    Trait(
        "resists_explosions",
        "resists_explosions",
        "Explosions hurt {s} less",
        "explosions hurt it less",
    ),
    Trait(
        "cannot_cross_deep_water",
        "cannot_cross_deep_water",
        "{s} cannot get out of a water pit deeper than it can jump",
        "it cannot get out of a water pit deeper than it can jump",
        closed=False,
    ),
)

SPELL_TYPE_NAMES: dict[str, str] = {
    "projectile": "a projectile spell",
    "static_projectile": "a spell that acts on the spot",
    "modifier": "a modifier that changes the spells after it",
    "multicast": "a multicast that casts several spells at once",
    "material": "a spell that sprays a material",
}
SPELL_TYPES = tuple(SPELL_TYPE_NAMES)
SPELL_TRAITS: tuple[Trait, ...] = (
    Trait("type", "type", "{s} is {p}", "its kind of spell is {p}", "spell_type", told=True),
    Trait("limited_uses", "uses", "{s} can be used only a few times", "it can be used only a few times", told=True),
    Trait("unlimited_uses", "uses", "{s} can be used without limit", "it can be used without limit", told=True),
    Trait("digs_terrain", "digs_terrain", "The blast of {s} digs out ground", "its blast digs out ground", told=True),
    Trait("blasts", "blasts", "{s} makes a large explosion", "it makes a large explosion", told=True),
    Trait("ignites", "ignites", "{s} sets things on fire", "it sets things on fire"),
    Trait("makes_wet", "makes_wet", "What {s} hits gets wet", "what it hits gets wet", told=True),
    Trait("makes_oiled", "makes_oiled", "What {s} hits gets covered in oil", "what it hits gets oiled", told=True),
    Trait("leaves_trail", "leaves_trail:{p}", "{s} leaves {p} along its path", "it leaves {p} along its path", "emitted", told=True),
    Trait("sprays", "sprays:{p}", "{s} sprays {p}", "it sprays {p}", "emitted", told=True),
    Trait("bounces", "bounces", "{s} makes the shot bounce", "the shot bounces off walls", told=True),
    Trait("adds_mana", "adds_mana", "Using {s} gives the wand mana", "using it gives the wand mana", told=True),
    Trait("speeds_up", "speed", "{s} makes the shot fly faster", "the shot flies faster", told=True),
    Trait("slows_shot", "speed", "{s} makes the shot fly slower", "the shot flies slower", told=True),
    Trait("triggers_on_hit", "triggers", "{s} fires the next spell when it hits something", "the next spell fires when it hits", told=True),
    Trait("triggers_on_timer", "triggers", "{s} fires the next spell after a short time", "the next spell fires after a short time", told=True),
    Trait("enlarges_blast", "enlarges_blast", "{s} makes the explosion bigger", "it makes the explosion of the shot larger", told=True),
    Trait("raises_blast_durability", "raises_blast_durability", "{s} lets the blast break harder materials", "the blast of the shot breaks harder materials"),
)  # fmt: skip

PARAM_KINDS = ("liquid", "emitted", "spell_type")


def _by_key(traits: tuple[Trait, ...]) -> dict[str, Trait]:
    return {t.key: t for t in traits}


@cache
def property_trait(key: str) -> Trait | None:
    return _by_key(PROPERTIES).get(key.split(":")[0])


@cache
def creature_trait(key: str) -> Trait | None:
    return _by_key(CREATURE_TRAITS).get(key)


@cache
def spell_trait(key: str) -> Trait | None:
    return _by_key(SPELL_TRAITS).get(key.split(":")[0])


def family_of(trait: Trait, key: str) -> str:
    """The family of a (possibly parameterised) key: `density:water` for `floats_on:water`."""
    parameter = key.split(":", 1)[1] if ":" in key else ""
    return trait.family.replace("{p}", parameter)


# ------------------------------------------------------------------ the whole vocabulary
@dataclass(frozen=True)
class Vocabulary:
    """Every value a fact or a claim may hold, with its names."""

    materials: dict[str, str]  # key -> English name; without air
    liquids: tuple[str, ...]  # natural liquids: the ones a property may compare against
    potions: dict[str, str]  # every potion; the secret ones (a recipe makes them) are `secret`
    secret: tuple[str, ...]
    effects: tuple[str, ...]
    properties: tuple[str, ...]
    creatures: dict[str, str]
    creature_traits: tuple[str, ...]
    spells: dict[str, str]
    spell_traits: tuple[str, ...]
    scene_topics: dict[str, dict[str, tuple[str, ...]]]  # encounter -> topic -> values
    scene_about: dict[tuple[str, str], str]  # (encounter, topic) -> what the topic asks

    def reaction_ends(self) -> tuple[str, ...]:
        """What one side of a reaction claim may be: a material or a burning cell."""
        return (*self.materials, BURNING)

    def products(self) -> tuple[str, ...]:
        return (*self.materials, AIR)


def _keyed(prefix: str, params: tuple[str, ...]) -> tuple[str, ...]:
    """`prefix:param` for each parameter, or the bare key when the trait has none."""
    return tuple(f"{prefix}:{p}" for p in params) if params else (prefix,)


@cache
def vocabulary() -> Vocabulary:
    mats = [m for m in data.materials() if m["key"] != AIR]
    materials = {m["key"]: m["name_en"] for m in mats}
    liquids = tuple(m["key"] for m in mats if m["kind"] == "liquid" and m["family"] != "potion")
    potions = {m["key"]: m["name_en"] for m in mats if m["family"] == "potion"}
    secret = tuple(m["key"] for m in mats if "secret_potion" in m["tags"])
    properties: list[str] = []
    for t in PROPERTIES:
        properties += _keyed(t.key, liquids if t.param == "liquid" else ())
    traits: list[str] = []
    for t in SPELL_TRAITS:
        emitted = (*liquids, "fire")
        params = {"emitted": emitted, "spell_type": SPELL_TYPES}.get(t.param or "", ())
        traits += _keyed(t.key, params)
    ent = data.entities()["enemies"]
    creatures = {k: v["name_en"] for k, v in ent.items()}
    topics: dict[str, dict[str, tuple[str, ...]]] = {}
    about: dict[tuple[str, str], str] = {}
    for eid, doc in data.encounters().items():
        for topic, spec in (doc.get("lesson_topics") or {}).items():
            topics.setdefault(eid, {})[topic] = tuple(sorted(spec["values"]))
            about[(eid, topic)] = spec.get("about", "")
    return Vocabulary(
        materials=materials,
        liquids=liquids,
        potions=potions,
        secret=secret,
        effects=tuple(EFFECTS),
        properties=tuple(properties),
        creatures=creatures,
        creature_traits=tuple(t.key for t in CREATURE_TRAITS),
        spells={s["key"]: s["name_en"] for s in data.spells()},
        spell_traits=tuple(traits),
        scene_topics=topics,
        scene_about=about,
    )
