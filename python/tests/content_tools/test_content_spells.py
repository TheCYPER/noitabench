"""The spell catalogue and the casting fixtures are generated; they must match their generators."""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parents[2]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from noitabench.content_tools import build_spells, build_wand_fixtures
from noitabench.content_tools.noita_xml import (
    _dedupe_attributes,
    flag,
    load_entity,
    number,
)

# The spell table is built from the game's own XML files, which are research material that stays
# out of the repository (research/RAW-DATA.md). Without them these tests cannot run.
needs_raw_game_data = pytest.mark.skipif(
    not build_spells.GAME_FILES.is_dir(),
    reason="needs the raw game data in research/raw/game (not in the repository)",
)


@pytest.fixture(scope="module")
def built() -> dict:
    if not build_spells.GAME_FILES.is_dir():
        pytest.skip("needs the raw game data in research/raw/game (not in the repository)")
    return build_spells.build()


def by_key(document: dict) -> dict:
    return {spell["key"]: spell for spell in document["spells"]}


@needs_raw_game_data
def test_committed_spells_file_is_up_to_date():
    assert build_spells.main(["--check"]) == 0


def test_committed_fixture_file_is_up_to_date():
    assert build_wand_fixtures.main(["--check"]) == 0


def test_spells_are_the_25_of_the_scope_page_in_order(built):
    keys = [spell["key"] for spell in built["spells"]]
    assert keys == [key for key, _ in build_spells.SPELLS]
    assert len(keys) == 25 and len(set(keys)) == 25
    assert built["format"] == "cogbench-spells/0"


def test_types_and_draw_counts(built):
    spells = by_key(built)
    assert spells["BURST_2"]["type"] == "multicast" and spells["BURST_2"]["draw"] == 2
    assert spells["BURST_3"]["draw"] == 3
    assert spells["SPEED"]["type"] == "modifier" and spells["SPEED"]["draw"] == 1
    assert spells["LIGHT_BULLET"]["draw"] == 0
    assert spells["EXPLOSION"]["type"] == "static_projectile"
    assert spells["MATERIAL_ACID"]["type"] == "material"
    assert spells["LIGHT_BULLET_TIMER"]["trigger"] == {
        "kind": "timer",
        "timer_frames": 10,
        "payload_draws": 1,
    }
    assert spells["LIGHT_BULLET_TRIGGER"]["trigger"]["kind"] == "collision"


def test_damage_is_internal_units_from_the_xml(built):
    spells = by_key(built)
    assert spells["LIGHT_BULLET"]["projectile"]["hit_damage"] == 0.12
    assert spells["DAMAGE"]["shot"]["damage"] == 0.4
    assert spells["BOMB"]["projectile"]["explosion"]["damage"] == 5.0
    # The research extractor lost the Digging Bolt's 0.3 to a second damage_by_type element.
    assert spells["DIGGER"]["projectile"]["hit_damage"] == 0.3
    # Fireball: no direct damage of the projectile type, 0.25 of fire.
    assert spells["FIREBALL"]["projectile"]["hit_damage"] == 0.25


def test_engine_defaults_fill_absent_attributes(built):
    bomb = by_key(built)["BOMB"]["projectile"]
    assert (bomb["speed_min"], bomb["speed_max"]) == (60, 60)
    assert bomb["gravity"] == 400 and bomb["air_friction"] == 0.55
    assert bomb["body"] == "thrown_body" and bomb["hp"] == 0.5
    assert bomb["on_collision_die"] is False


def test_duplicate_attribute_takes_the_last_value(built):
    # bullet_slow.xml sets knockback_force twice (0.1, then 2.8); the KB and the wiki say 2.8.
    assert by_key(built)["SLOW_BULLET"]["projectile"]["knockback"] == 2.8


def test_explosion_only_when_the_projectile_explodes(built):
    spells = by_key(built)
    assert spells["RUBBER_BALL"]["projectile"]["explosion"] is None
    assert spells["MATERIAL_WATER"]["projectile"]["explosion"] is None
    spark = spells["LIGHT_BULLET"]["projectile"]["explosion"]
    assert (spark["radius"], spark["max_durability"], spark["cell_percent"]) == (2, 8, 0)
    assert spark["cell_material"] is None
    assert spells["FIREBALL"]["projectile"]["explosion"]["cell_material"] == "fire"


def test_only_explosive_projectile_raises_the_explosion_durability(built):
    spells = by_key(built)
    bonus = {key: spell["shot"]["explosion_durability"] for key, spell in spells.items()}
    assert bonus["EXPLOSIVE_PROJECTILE"] == 3
    assert {key for key, value in bonus.items() if value} == {"EXPLOSIVE_PROJECTILE"}
    assert all(isinstance(value, int) for value in bonus.values())
    # The seal is brick (durability 14): the bomb's 11 plus the modifier's 3 reaches it, and no
    # other pair of spells of the catalogue does.
    materials = json.loads((build_spells.REPO / "content" / "materials.json").read_text("utf-8"))
    brick = next(m for m in materials["materials"] if m["key"] == "brick")["durability"]
    own = {
        key: spell["projectile"]["explosion"]["max_durability"]
        for key, spell in spells.items()
        if spell["projectile"] and spell["projectile"]["explosion"]
    }
    reaching = {key for key, value in own.items() if value + bonus["EXPLOSIVE_PROJECTILE"] >= brick}
    assert reaching == {"BOMB"} and own["BOMB"] < brick


@needs_raw_game_data
def test_the_durability_bonus_is_for_modifiers_only(monkeypatch):
    monkeypatch.setitem(build_spells.EXPLOSION_DURABILITY, "BOMB", 3)
    with pytest.raises(build_spells.BuildError, match="BOMB.*only modifiers"):
        build_spells.build()


def test_a_bonus_for_a_spell_that_is_not_built_is_an_error(monkeypatch):
    monkeypatch.setitem(build_spells.EXPLOSION_DURABILITY, "NUKE", 3)
    with pytest.raises(build_spells.BuildError, match="NUKE"):
        build_spells.build()


def test_material_spells_name_their_particle_and_effect(built):
    spells = by_key(built)
    assert spells["MATERIAL_ACID"]["projectile"]["emit"] == {"material": "acid", "count": 6}
    assert spells["MATERIAL_WATER"]["shot"]["effects"] == ["wet"]
    assert spells["MATERIAL_OIL"]["shot"]["effects"] == ["oiled"]
    assert spells["FIRE_TRAIL"]["shot"]["trail"] == [{"material": "fire", "amount": 10}]
    assert spells["FIRE_TRAIL"]["shot"]["effects"] == ["on_fire"]


def test_materials_named_by_spells_exist_in_the_material_table(built):
    materials = json.loads((build_spells.REPO / "content" / "materials.json").read_text("utf-8"))
    known = {m["key"] for m in materials["materials"]}
    named = set()
    for spell in built["spells"]:
        named |= {t["material"] for t in spell["shot"]["trail"]}
        projectile = spell["projectile"] or {}
        if projectile.get("emit"):
            named.add(projectile["emit"]["material"])
        if projectile.get("explosion") and projectile["explosion"]["cell_material"]:
            named.add(projectile["explosion"]["cell_material"])
    assert named and named <= known, sorted(named - known)


def test_every_number_is_finite(built):
    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, float):
            assert math.isfinite(value)

    walk(built)


@needs_raw_game_data
def test_build_fails_when_the_research_data_disagrees(monkeypatch):
    research = build_spells._load_research()
    broken = copy.deepcopy(research)
    broken["SPEED"]["cast_delay_modifier"] = {"frames": 7, "seconds": 0.1, "mode": "add"}
    monkeypatch.setattr(build_spells, "_load_research", lambda: broken)
    with pytest.raises(build_spells.BuildError, match="SPEED.*cast_delay"):
        build_spells.build()


@needs_raw_game_data
def test_build_fails_on_a_shot_field_it_does_not_model(monkeypatch):
    research = build_spells._load_research()
    broken = copy.deepcopy(research)
    broken["SPEED"]["action_effects_raw"]["c_add"]["gravity"] = 5
    monkeypatch.setattr(build_spells, "_load_research", lambda: broken)
    with pytest.raises(build_spells.BuildError, match="unmodelled"):
        build_spells.build()


def test_fixture_filter_keeps_only_in_scope_cases_and_corrects_draw_01():
    document = build_wand_fixtures.build()
    cases = {case["id"]: case for case in document["cases"]}
    assert len(cases) == 9 and "shuffle_01_multicast_second_slot_wraps" in cases
    assert cases["draw_01_multicast_modifier"]["clicks"][0]["mana_spent"] == 15
    assert document["excluded"]["draw_02_nested_multicast_and_leftover"] == ["NUKE"]
    assert "(replaced by KV-01)" in document["excluded"]["refresh_03_spells_per_cast_forces_wrap"]
    # greek_01 is out of scope, so its correction (105 -> 114) is not applied anywhere.
    assert "greek_01_tau_recursion" in document["excluded"]


def test_dedupe_keeps_the_last_attribute_value():
    assert _dedupe_attributes('<A x="1" y="2" x="3"/>') == '<A x="3" y="2"/>'
    assert _dedupe_attributes('<B z="1"></B>') == '<B z="1"></B>'


def test_xml_helpers_use_defaults_and_trim_values():
    attrs = {"a": " 0.25 ", "on": "1", "off": "0"}
    assert number(attrs, "a", 9) == 0.25 and number(attrs, "missing", 9) == 9
    assert flag(attrs, "on", False) and not flag(attrs, "off", True) and flag(attrs, "x", True)


def test_base_overrides_merge_attribute_wise(tmp_path):
    root = tmp_path / "entities"
    root.mkdir()
    (root / "base.xml").write_text(
        '<Entity><VelocityComponent mass="0.05" gravity_y="400"/>'
        '<ProjectileComponent lifetime="60"><config_explosion damage="2" ray_energy="9"/>'
        "</ProjectileComponent></Entity>"
    )
    (root / "child.xml").write_text(
        '<Entity><Base file="data/entities/base.xml">'
        '<VelocityComponent gravity_y="100"/>'
        '<ProjectileComponent><config_explosion damage="5"/></ProjectileComponent>'
        "</Base></Entity>"
    )
    entity = load_entity(tmp_path, "data/entities/child.xml")
    assert entity["VelocityComponent"]["@"] == {"mass": "0.05", "gravity_y": "100"}
    assert entity["ProjectileComponent"]["@"] == {"lifetime": "60"}
    assert entity["ProjectileComponent"]["config_explosion"] == {"damage": "5", "ray_energy": "9"}


def test_a_repeated_child_element_counts_once_with_its_first_values(tmp_path):
    (tmp_path / "e.xml").write_text(
        '<Entity><ProjectileComponent><damage_by_type drill="0.3"/>'
        '<damage_by_type drill="0.01"/></ProjectileComponent></Entity>'
    )
    entity = load_entity(tmp_path, "data/e.xml")
    assert entity["ProjectileComponent"]["damage_by_type"] == {"drill": "0.3"}
