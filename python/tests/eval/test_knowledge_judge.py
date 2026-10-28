"""The judge: right, partly right, wrong or not judged, all by code."""

from __future__ import annotations

import pytest
from noitabench.eval.knowledge.claims import Claim
from noitabench.eval.knowledge.facts import build_knowledge
from noitabench.eval.knowledge.judge import (
    claim_key,
    counts,
    judge,
    judge_section,
    subject_of,
)

K = build_knowledge(3)
RECIPES = {f.fields["potion"]: f.fields["inputs"] for f in K.of_kind("recipe")}
POTION = "potion_crit"
INPUTS = RECIPES[POTION]
OTHER = next(p for p in RECIPES if p != POTION)
EFFECT = {f.fields["material"]: f.fields["effect"] for f in K.of_kind("drink")}


def claim(kind: str, hedged: bool = False, **fields) -> Claim:
    return Claim(kind, fields, hedged, "quote")


def verdict(kind: str, **fields):
    return judge(claim(kind, **fields), K)


# ------------------------------------------------------------------------------------- recipes
def test_a_recipe_named_and_exact_is_correct():
    v = verdict("recipe", potion=POTION, inputs=list(reversed(INPUTS)))
    assert (v.verdict, v.weight, v.fact_id, v.tier, v.told) == (
        "correct",
        1.0,
        f"recipe:{POTION}",
        "seed",
        False,
    )


def test_two_of_three_is_partial_and_a_stranger_is_wrong():
    wrong_one = [
        INPUTS[0],
        INPUTS[1],
        next(m for m in ("water", "coal", "slime", "gold_dust") if m not in INPUTS),
    ]
    assert verdict("recipe", potion=POTION, inputs=wrong_one).verdict == "partial"
    assert verdict("recipe", potion=POTION, inputs=INPUTS[:2]).verdict == "partial"
    far = [
        m
        for m in ("water", "blood", "coal", "slime", "gold_dust", "toxic_sludge")
        if m not in INPUTS
    ][:3]
    assert verdict("recipe", potion=POTION, inputs=far).verdict == "wrong"
    assert verdict("recipe", potion=POTION, inputs=[INPUTS[0], far[0]]).verdict == "wrong"


def test_the_right_three_under_another_potions_name_is_partial_and_points_at_that_recipe():
    v = verdict("recipe", potion=OTHER, inputs=INPUTS)
    assert v.verdict == "partial" and v.fact_id == f"recipe:{POTION}"


def test_a_potion_described_by_its_effect_is_found_through_the_drink_effect():
    effect = EFFECT[POTION]
    v = verdict("recipe", effect=effect, inputs=INPUTS)
    assert (v.verdict, v.fact_id) == ("correct", f"recipe:{POTION}")
    assert verdict("recipe", effect=EFFECT[OTHER], inputs=INPUTS).verdict == "partial"


def test_a_potion_no_recipe_makes_is_not_judged():
    assert verdict("recipe", potion="potion_heal", inputs=INPUTS).verdict == "unknown"
    assert verdict("recipe", effect="heal", inputs=INPUTS).verdict == "unknown"
    assert verdict("recipe", effect="wet", inputs=INPUTS).verdict == "unknown"


def test_no_recipe_is_wrong_for_a_real_recipe_and_never_teaches():
    assert verdict("no_recipe", inputs=INPUTS).verdict == "wrong"
    far = ["water", "blood", "coal"]
    assert set(far) not in [set(i) for i in RECIPES.values()]
    v = verdict("no_recipe", inputs=far)
    assert (v.verdict, v.fact_id, v.tier) == ("correct", None, None)
    assert verdict("no_recipe", inputs=INPUTS[:2]).verdict == "unknown"


# ----------------------------------------------------------------------------------- reactions
@pytest.mark.parametrize(
    "a, b, out, expected",
    [
        ("lava", "water", ["rock", "steam"], "correct"),
        ("water", "lava", ["rock"], "correct"),  # the pair is unordered
        ("lava", "water", [], "correct"),  # no product named
        ("lava", "water", ["fire"], "wrong"),
        ("lava", "water", ["rock", "fire"], "wrong"),
        ("acid", "sand", ["air"], "correct"),  # sand carries the tag `corrodible`
        ("acid", "water", ["flammable_gas", "air"], "correct"),
        ("acid", "oil", ["air"], "unknown"),  # no row joins them
        ("sand", "water", ["ground"], "unknown"),
        ("water", "burning", ["steam"], "correct"),  # r14
        ("fire", "water", ["fire", "steam"], "correct"),
        ("steam", "rock", ["water"], "correct"),  # the tag `static` stays
    ],
)
def test_reaction_claims(a, b, out, expected):
    assert verdict("reaction", a=a, b=b, out=out).verdict == expected


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("sand", "water", "correct"),
        ("lava", "water", "wrong"),
        ("water", "toxic_sludge", "wrong"),
        ("fire", "oil", "wrong"),  # lighting is not a row, and the statement is still false
        ("lava", "whiskey", "wrong"),
        ("burning", "coal", "wrong"),
        ("fire", "water", "wrong"),
        ("fire", "sand", "correct"),
    ],
)
def test_no_reaction_claims(a, b, expected):
    assert verdict("no_reaction", a=a, b=b).verdict == expected


# ---------------------------------------------------------------------------------- the others
def test_drink_claims():
    assert verdict("drink", material="potion_heal", effect="heal").verdict == "correct"
    assert verdict("drink", material="potion_heal", effect="heal").told
    assert verdict("drink", material="water", effect="oiled").verdict == "wrong"
    assert verdict("drink", material="sand", effect="none").verdict == "unknown"  # not a liquid


@pytest.mark.parametrize(
    "material, prop, expected",
    [
        ("oil", "burns", "correct"),
        ("oil", "does_not_burn", "wrong"),
        ("water", "burns", "wrong"),
        ("brick", "undiggable", "correct"),
        ("sand", "undiggable", "wrong"),  # a powder is in the universe and is not hard
        ("water", "undiggable", "unknown"),  # nobody digs a liquid
        ("water", "harms_on_contact", "wrong"),
        ("lava", "harms_on_contact", "correct"),
        ("toxic_sludge", "harms_on_contact", "correct"),
        ("gunpowder", "explodes_when_lit", "correct"),
        ("coal", "explodes_when_lit", "wrong"),
        ("oil", "floats_on:water", "correct"),
        ("oil", "sinks_in:water", "wrong"),
        ("sand", "floats_on:lava", "unknown"),  # equal densities
        ("toxic_sludge", "looks_like:slime", "correct"),
        ("water", "looks_like:blood", "unknown"),  # `looks_like` is open
        ("potion_heal", "burns", "unknown"),
        ("water", "corroded_by_acid", "correct"),
        ("oil", "resists_acid", "correct"),
    ],
)
def test_property_claims(material, prop, expected):
    assert verdict("property", material=material, property=prop).verdict == expected


def test_creature_and_spell_claims():
    assert verdict("creature", creature="longleg", trait="melee_only").verdict == "correct"
    assert verdict("creature", creature="longleg", trait="shoots").verdict == "wrong"
    assert verdict("creature", creature="shotgunner", trait="immune_to_fire").verdict == "wrong"
    assert (
        verdict("creature", creature="longleg", trait="cannot_cross_deep_water").verdict
        == "correct"
    )
    assert (
        verdict("creature", creature="shotgunner", trait="cannot_cross_deep_water").verdict
        == "unknown"
    )
    assert verdict("spell", spell="BOMB", trait="blasts").verdict == "correct"
    assert verdict("spell", spell="DIGGER", trait="blasts").verdict == "wrong"
    assert verdict("spell", spell="MANA_REDUCE", trait="type:modifier").verdict == "correct"
    assert verdict("spell", spell="MANA_REDUCE", trait="type:projectile").verdict == "wrong"
    assert verdict("spell", spell="FIREBALL", trait="ignites").told is False


def test_scene_claims():
    scene = {"encounter": "E21", "topic": "nearest_bottle_to_door"}
    assert verdict("scene", value="toxic_sludge", **scene).verdict == "correct"
    assert verdict("scene", value="heal_potion", **scene).verdict == "wrong"
    key = verdict("scene", encounter="E06", topic="seal_key", value="digger")
    assert (key.verdict, key.tier) == ("wrong", "game")


def test_local_and_other_are_not_judged_and_hedged_is_not_counted():
    for kind, extra in (("local", {}), ("other", {"paraphrase": "x"})):
        v = verdict(kind, **extra)
        assert v.verdict == kind and v.weight is None and not counts(claim(kind, **extra), v)
    wrong = claim("drink", hedged=True, material="water", effect="oiled")
    v = judge(wrong, K)
    assert v.verdict == "wrong" and not counts(wrong, v)
    assert counts(claim("drink", material="water", effect="oiled"), v)
    unknown = verdict("drink", material="sand", effect="none")
    assert not counts(claim("drink", material="sand", effect="none"), unknown)


# ------------------------------------------------------------------------------------ subjects
def test_subjects_compare_a_statement_across_notebooks():
    a = subject_of(claim("reaction", a="lava", b="water", out=["rock"]), K)
    assert a == subject_of(claim("no_reaction", a="water", b="lava"), K)
    assert subject_of(claim("recipe", effect=EFFECT[POTION], inputs=INPUTS), K) == (
        "recipe",
        POTION,
    )
    assert subject_of(claim("recipe", potion=POTION, inputs=INPUTS), K) == ("recipe", POTION)
    assert subject_of(claim("recipe", effect="wet", inputs=INPUTS), K) == ("recipe", "effect:wet")
    assert subject_of(claim("property", material="oil", property="burns"), K) == subject_of(
        claim("property", material="oil", property="does_not_burn"), K
    )
    assert subject_of(
        claim("property", material="oil", property="floats_on:water"), K
    ) != subject_of(claim("property", material="oil", property="floats_on:blood"), K)
    assert subject_of(claim("local")) is None


def test_a_statement_written_twice_is_judged_once():
    a = Claim("recipe", {"potion": POTION, "inputs": INPUTS}, True, "maybe")
    b = Claim("recipe", {"potion": POTION, "inputs": list(reversed(INPUTS))}, False, "sure")
    assert claim_key(a) == claim_key(b)
    out = judge_section([("notes/a.md", a), ("notes/b.md", b)], K)
    assert len(out) == 1 and not out[0].claim.hedged and out[0].path == "notes/b.md"
    assert len(judge_section([("a", a), ("b", b)], K, distinct=False)) == 2


def test_the_two_sides_of_a_reaction_are_one_statement_in_either_order():
    a = claim("reaction", a="lava", b="water", out=["steam", "rock"])
    b = claim("reaction", a="water", b="lava", out=["rock", "steam"])
    assert claim_key(a) == claim_key(b)
    assert claim_key(claim("no_reaction", a="sand", b="oil")) == claim_key(
        claim("no_reaction", a="oil", b="sand")
    )
    assert claim_key(a) != claim_key(claim("reaction", a="lava", b="water", out=["rock"]))
    assert len(judge_section([("notes/a.md", a), ("notes/b.md", b)], K)) == 1
