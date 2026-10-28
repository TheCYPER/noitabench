"""The Python surface of the rules crate (``noitabench_core.rules()``) and the ``Rules`` wrapper
the generator and the solvability checks use (table.py).

The reaction table is the original one for every rule seed (CP2 decision, 2026-10-27); the rule
seed only draws the secret recipes. Rule-seed text (reactions_json, recipes) is internal tooling:
the generator and the tests read it, an agent never does (contracts section 10). Nothing in the
generator calls the removed ``perturb`` / ``Perturbed`` compatibility layer any more.
"""

from __future__ import annotations

import json
from pathlib import Path

import noitabench_core
import pytest
from noitabench.worldgen import table
from noitabench.worldgen.table import PLAIN_LIQUIDS, ROLES, get_rules

WORLDGEN = Path(table.__file__).parent


def test_the_table_is_the_original_for_every_rule_seed():
    a, b = get_rules(1), get_rules(2)
    assert a.reactions_json == b.reactions_json
    assert a.content_hash == b.content_hash
    assert json.loads(a.reactions_json)["format"] == "cogbench-reactions/0"
    assert a.table.lava_solidifiers() and "liquid" in a.table.lava_solidifiers()[0]
    assert a.table.extinguishers() and "material" in a.table.extinguishers()[0]


def test_the_transforms_query_names_what_two_materials_make():
    p = get_rules(3)
    out_a, out_b, probability = p.transforms("water", "lava")
    assert {out_a, out_b} == {"steam", "rock"} and 0.0 < probability <= 1.0
    assert p.transforms("rock", "rock") is None
    assert p.reacts("water", "lava") and not p.reacts("rock", "rock")


def test_the_wrapper_answers_the_questions_of_the_scenes():
    for rule_seed in range(12):
        rules = get_rules(rule_seed)
        assert rules.solidifiers() == sorted(rules.solidifiers())
        assert rules.solidifiers() and rules.extinguishers()
        assert set(rules.extinguishers()) <= set(PLAIN_LIQUIDS)
        for role in ROLES:  # every role of the scene format is answered
            assert isinstance(rules.candidates(role), list)
        assert not set(rules.candidates("not_lava_solidifier")) & set(rules.solidifiers())


def test_the_wrapper_is_cached_per_rule_seed_and_shares_one_table():
    assert get_rules(4) is get_rules(4) and get_rules(4) is not get_rules(5)
    assert get_rules(4).rule_seed == 4 and not hasattr(get_rules(4), "strength")
    assert get_rules(4).table is get_rules(5).table


def test_the_wrapper_names_the_recipes_of_its_rule_seed():
    for rule_seed in (0, 7, 2026):
        recipes = get_rules(rule_seed).recipes()
        assert len(recipes) == 8 and len({tuple(sorted(r[1])) for r in recipes}) == 8
        assert all(len(set(r[1])) == 3 for r in recipes)
        assert recipes == [
            (r["potion"], tuple(r["inputs"])) for r in noitabench_core.recipes(rule_seed)
        ]
    assert get_rules(1).recipes() != get_rules(2).recipes()


def test_an_unknown_role_names_the_choices():
    with pytest.raises(ValueError, match="lava_solidifier"):
        get_rules(0).candidates("nonsense")


def test_the_generator_does_not_use_the_compatibility_layer():
    """``perturb`` and ``Perturbed`` are deleted later: nothing under worldgen may call them."""
    offenders = [
        p.name
        for p in sorted(WORLDGEN.glob("*.py"))
        if any(
            word in line and not line.lstrip().startswith(("#", '"""'))
            for line in p.read_text(encoding="utf-8").splitlines()
            for word in ("noitabench_core.perturb(", "noitabench_core.Perturbed", ".Perturbed(")
        )
    ]
    assert not offenders, f"still calling the compatibility layer: {offenders}"
