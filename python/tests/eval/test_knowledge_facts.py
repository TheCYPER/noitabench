"""The knowledge base: facts from the data files, tiers, told, lessons (contracts section 21)."""

from __future__ import annotations

import json

import noitabench_core
import pytest
from noitabench.eval.knowledge import data, lessons
from noitabench.eval.knowledge.claims import check_fields
from noitabench.eval.knowledge.facts import Knowledge, build_knowledge
from noitabench.eval.knowledge.vocab import TIERS, vocabulary
from noitabench.worldgen.config import load_materials
from noitabench.worldgen.encounter_defs import instantiate, load_encounters
from noitabench.worldgen.table import get_rules

SEEDS = (0, 1, 7, 42)


def ids(k: Knowledge) -> set[str]:
    return {f.id for f in k.facts}


@pytest.mark.parametrize("seed", SEEDS)
def test_the_recipes_are_the_engines(seed):
    k = build_knowledge(seed)
    made = {f.fields["potion"]: f.fields["inputs"] for f in k.of_kind("recipe")}
    engine = {r["potion"]: sorted(r["inputs"]) for r in noitabench_core.recipes(seed)}
    assert made == engine and len(made) == 8
    for f in k.of_kind("recipe"):
        assert (f.tier, f.told, f.encounters) == ("seed", False, ())
        assert len(set(f.fields["inputs"])) == 3


def test_recipes_differ_between_seeds_and_nothing_else_does():
    a, b = build_knowledge(0), build_knowledge(5)
    assert [f.fields["inputs"] for f in a.of_kind("recipe")] != [
        f.fields["inputs"] for f in b.of_kind("recipe")
    ]
    rest = lambda k: [f.as_dict() for f in k.facts if f.kind != "recipe"]
    assert rest(a) == rest(b)


def test_every_fact_has_a_tier_a_sentence_and_a_unique_id():
    k = build_knowledge(0)
    assert len(ids(k)) == len(k.facts)
    for f in k.facts:
        assert f.tier in TIERS and f.note.strip(), f.id
        assert f.id.startswith(f.kind + ":")


def test_there_is_one_reaction_fact_per_row_and_one_drink_per_liquid():
    k = build_knowledge(0)
    assert len(k.of_kind("reaction")) == len(data.reactions())
    liquids = [m for m in data.materials() if m["kind"] == "liquid" and m["key"] != "air"]
    assert {f.fields["material"] for f in k.of_kind("drink")} == {m["key"] for m in liquids}


def test_tags_are_expanded_in_reaction_facts():
    k = build_knowledge(0)
    acid = k.by_id["reaction:r04"]
    assert "water" in acid.fields["b_members"] and "sand" in acid.fields["b_members"]
    assert "acid" not in acid.fields["b_members"]
    put_out = k.by_id["reaction:r14"]
    assert put_out.fields["b_members"] == ["burning"] and put_out.fields["out"] == ["steam"]
    assert k.by_id["reaction:r03"].fields["a_members"] == ["fire"]


def test_told_marks_what_the_game_shows():
    k = build_knowledge(0)
    for f in k.of_kind("drink"):
        family = data.material_table()[f.fields["material"]]["family"]
        assert f.told == (family == "potion"), f.id
    assert k.by_id["spell:BOMB:blasts"].told  # the card shows the blast radius
    assert k.by_id["spell:FIRE_TRAIL:ignites"].told  # its trail and effect are on the card
    assert not k.by_id["spell:FIREBALL:ignites"].told  # the card does not say it lights things
    assert not k.by_id["spell:EXPLOSIVE_PROJECTILE:raises_blast_durability"].told
    assert not any(f.told for f in k.facts if f.kind in ("reaction", "property", "creature"))


def test_the_properties_come_from_the_material_rows():
    k = build_knowledge(0)
    for good in (
        "property:oil:burns",
        "property:whiskey:burns",  # burnable by its tag
        "property:coal:burns",
        "property:water:does_not_burn",
        "property:brick:undiggable",
        "property:metal:undiggable",
        "property:gunpowder:explodes_when_lit",
        "property:acid:harms_on_contact",
        "property:toxic_sludge:harms_on_contact",  # its contact poisons
        "property:water:corroded_by_acid",
        "property:oil:resists_acid",
        "property:oil:floats_on:water",
        "property:water:sinks_in:oil",
        "property:toxic_sludge:looks_like:slime",
    ):
        assert good in ids(k), good
    for bad in (
        "property:ground:undiggable",
        "property:water:harms_on_contact",
        "property:sand:floats_on:lava",  # equal densities: neither
        "property:sand:sinks_in:lava",
        "property:oil:corroded_by_acid",
    ):
        assert bad not in ids(k), bad


def test_creature_and_spell_traits_come_from_their_files():
    k = build_knowledge(0)
    for good in (
        "creature:longleg:melee_only",
        "creature:longleg:leaps_at_you",
        "creature:longleg:catches_fire_easily",
        "creature:shotgunner:shoots",
        "creature:shotgunner:headshot_bonus",
        "creature:firemage_weak:immune_to_fire",
        "creature:firemage_weak:hurt_by_water",
        "creature:firemage_weak:resists_explosions",
        "spell:BOMB:blasts",
        "spell:DIGGER:digs_terrain",
        "spell:MATERIAL_WATER:sprays:water",
        "spell:MATERIAL_WATER:makes_wet",
        "spell:WATER_TRAIL:leaves_trail:water",
        "spell:BOUNCE:bounces",
        "spell:RUBBER_BALL:bounces",
        "spell:MANA_REDUCE:adds_mana",
        "spell:EXPLOSIVE_PROJECTILE:enlarges_blast",
        "spell:LIGHT_BULLET_TIMER:triggers_on_timer",
        "spell:BOMB:limited_uses",
        "spell:DIGGER:type:projectile",
    ):
        assert good in ids(k), good
    assert "spell:DIGGER:blasts" not in ids(k) and "creature:longleg:shoots" not in ids(k)


def test_the_facts_hold_no_places_and_no_numbers():
    k = build_knowledge(0)
    for f in k.facts:
        if f.kind != "scene":
            assert not any(isinstance(v, (int, float)) for v in f.fields.values()), f.id


# ------------------------------------------------------------------------------------- lessons
def test_every_lesson_is_in_the_claim_schema_and_the_data_agree():
    found = lessons.load_lessons()
    assert {l.encounter for l in found} >= {"E02", "E05", "E06", "E09", "E21", "E24"}
    for lesson in found:
        kind = lesson.claim["kind"]
        assert check_fields(kind, lesson.claim) is None, lesson.where
    assert lessons.topics_without_lesson() == []


def test_a_lesson_links_the_fact_it_names_to_its_scene():
    k = build_knowledge(0)
    lava = k.by_id["reaction:r01"]
    assert lava.encounters == ("E02", "E04", "E05", "E07", "E14")
    assert lava.tier == "common"  # a lesson links a fact, it does not make Noita knowledge ours
    assert k.by_id["reaction:r05"].tier == "common" and k.by_id["reaction:r05"].encounters == ()
    assert k.by_id["property:gunpowder:explodes_when_lit"].encounters == ("E09", "E22")
    assert k.by_id["scene:E21:nearest_bottle_to_door"].fields["value"] == "toxic_sludge"
    assert k.by_id["creature:longleg:cannot_cross_deep_water"].tier == "game"


def test_noita_knowledge_linked_by_a_lesson_stays_common():
    k = build_knowledge(0)
    r01 = k.by_id["reaction:r01"]  # lava + water, the Noita original
    assert (r01.tier, "E05" in r01.encounters) == ("common", True)
    for fid in (
        "creature:firemage_weak:immune_to_fire",
        "spell:FIREBALL:ignites",
        "drink:oil",
        "drink:whiskey",
        "drink:toxic_sludge",
        "property:oil:burns",
        "property:brick:undiggable",
    ):
        assert k.by_id[fid].tier == "common" and k.by_id[fid].encounters, fid
    # what the lessons make themselves keeps the lesson's tier
    assert k.by_id["scene:E06:seal_key"].tier == "game"
    assert k.by_id["creature:longleg:cannot_cross_deep_water"].tier == "game"
    # a fact is `game` because the data says it is ours, whether or not a lesson names it
    ours = [f for f in k.facts if f.tier == "game" and f.kind not in ("scene",)]
    assert ours and all(f.id != "reaction:r01" for f in ours)


def test_a_lesson_the_data_contradict_stops_the_build(monkeypatch):
    encounters = json.loads(json.dumps(data.encounters()))
    bad = {"kind": "reaction", "a": "lava", "b": "oil", "out": ["rock"]}
    encounters["E02"]["lessons"] = [{"claim": bad, "note": "wrong"}]
    monkeypatch.setattr(data, "encounters", lambda: encounters)
    with pytest.raises(ValueError, match="E02.json lessons.0.: the data files do not say this"):
        lessons.apply_lessons(build_knowledge(0))


@pytest.mark.parametrize(
    "lesson, why",
    [
        ({"claim": {"kind": "recipe", "potion": "potion_crit", "inputs": ["oil", "sand"]}, "note": "x"}, "kind must be"),
        ({"claim": {"kind": "creature", "creature": "longleg", "trait": "cannot_cross_deep_water"}, "tier": "gold", "note": "x"}, "tier must be"),
        ({"claim": {"kind": "drink", "material": "water", "effect": "wet"}, "tier": "game", "note": "x"}, "no tier here"),
        ({"claim": {"kind": "creature", "creature": "longleg", "trait": "cannot_cross_deep_water"}, "note": "x"}, "tier must be"),
        ({"claim": {"kind": "drink", "material": "water", "effect": "wet"}}, "note is required"),
        ({"claim": {"kind": "drink", "material": "water", "effect": "fly"}, "note": "x"}, "vocabulary"),
        ({"claim": {"kind": "scene", "encounter": "E21", "topic": "nearest_bottle_to_door", "value": "toxic_sludge"}, "tier": "game", "note": "x"}, "own encounter"),
        ({"claim": {"kind": "drink", "material": "water", "effect": "wet", "text": "t"}, "note": "x"}, "hedged or text"),
    ],
)  # fmt: skip
def test_a_malformed_lesson_is_refused(monkeypatch, lesson, why):
    encounters = json.loads(json.dumps(data.encounters()))
    encounters["E02"]["lessons"] = [lesson]
    monkeypatch.setattr(data, "encounters", lambda: encounters)
    with pytest.raises(ValueError, match=why):
        lessons.load_lessons()


def test_the_encounter_loader_ignores_lessons_and_topics():
    defs = load_encounters()
    assert "E21" in defs and "E06" in defs  # parsed although they carry both new fields
    assert data.encounters()["E21"]["lesson_topics"]


# ---- the lessons that state a value are checked against the scene's own definition
def test_the_nearest_bottle_of_e21_is_the_sludge_in_every_variant():
    d, mats = load_encounters()["E21"], load_materials()
    for variant in range(d.variants):
        inst = instantiate(d, get_rules(0), variant, mats)
        (door_x,) = {x for cells in inst.doors.values() for x, _ in cells}
        things = [m for m in inst.markers if m.get("item") in ("bottle", "potion_heal")]
        assert len(things) == 4
        nearest = min(things, key=lambda m: abs(m["x"] - door_x))
        assert nearest["item"] == "bottle" and nearest["contents"] == "toxic_sludge", variant


def test_only_the_bomb_with_the_explosive_projectile_first_breaks_the_seal():
    brick = data.material_table()["brick"]["durability"]
    spells = {s["key"]: s for s in data.spells()}
    boost = spells["EXPLOSIVE_PROJECTILE"]["shot"]["explosion_durability"]
    reach = {
        key: s["projectile"]["explosion"]["max_durability"]
        for key, s in spells.items()
        if (s.get("projectile") or {}).get("explosion")
    }
    assert all(v < brick for v in reach.values())  # no single spell breaks brick
    assert {key for key, v in reach.items() if v + boost >= brick} == {"BOMB"}
    fact = build_knowledge(0).by_id["scene:E06:seal_key"]
    assert fact.fields["value"] == "bomb_with_explosive_projectile_first"


def test_the_flooded_room_of_e08_has_only_a_door_above_and_one_below():
    d, mats = load_encounters()["E08"], load_materials()
    for variant in range(d.variants):
        assert set(instantiate(d, get_rules(0), variant, mats).doors) == {"top", "bottom"}


def test_the_vocabulary_names_every_topic_value_of_every_lesson():
    v = vocabulary()
    for f in build_knowledge(0).of_kind("scene"):
        values = v.scene_topics[f.fields["encounter"]][f.fields["topic"]]
        assert f.fields["value"] in values


def test_a_decoy_of_the_seal_key_topic_is_false_in_the_data():
    """The list of values is shown to the extractor: its other values must really be wrong
    (a plain bomb, a digger, the fireball with the booster and a bomb with a modifier that adds
    nothing to the blast's hardness all fall short of brick)."""
    spells = {s["key"]: s for s in data.spells()}
    brick = data.material_table()["brick"]["durability"]

    def blast(key: str) -> int:
        return spells[key]["projectile"]["explosion"]["max_durability"]

    def boost(key: str) -> int:
        return spells[key]["shot"]["explosion_durability"]

    assert blast("BOMB") < brick and blast("DIGGER") < brick
    assert blast("FIREBALL") + boost("EXPLOSIVE_PROJECTILE") < brick
    assert boost("DAMAGE") == 0 and blast("BOMB") + boost("DAMAGE") < brick
    values = vocabulary().scene_topics["E06"]["seal_key"]
    assert {
        "bomb_alone",
        "digger",
        "fireball_with_explosive_projectile",
        "bomb_with_damage_plus",
    } <= set(values)
