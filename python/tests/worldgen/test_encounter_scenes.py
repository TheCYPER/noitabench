"""The encounter scenes: loading and validation, variants, placement and the solvability checks
(content/encounters/, encounter_defs.py, encounter_place.py, encounter_checks.py).

The reaction table is the original one for every rule seed (CP2 decision, 2026-10-27), so the
scenes are built for one table; the rule seeds below only prove that they do not matter."""

from __future__ import annotations

import copy
import dataclasses
import json

import numpy as np
import pytest
from noitabench.worldgen import breaker, generate_world
from noitabench.worldgen.checks import run_checks
from noitabench.worldgen.config import load_materials
from noitabench.worldgen.encounter_checks import (
    acid_allowed_mask,
    placed_encounters,
    predicate_holds,
)
from noitabench.worldgen.encounter_defs import (
    breaker_spells,
    instantiate,
    load_encounters,
    single_ids,
)
from noitabench.worldgen.rest import mobile_cells
from noitabench.worldgen.scene_world import scene_world
from noitabench.worldgen.table import Rules, get_rules

EXPECTED = {
    "E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09", "E10", "E12", "E14", "E16", "E18",
    "E21", "E22", "E23", "E24",
}  # fmt: skip
MUST_PASS = {"E02", "E06", "E07", "E08", "E12", "E16", "E22", "E23"}
RULE_SEEDS = [0, 1, 3, 7, 12]


@pytest.fixture(scope="module")
def defs():
    return load_encounters()


def _mutated(world, **changes):
    return dataclasses.replace(
        world, grid=world.grid.copy(), markers=copy.deepcopy(world.markers), **changes
    )


# ------------------------------------------------------------------------------ the content


def test_the_seventeen_scenes_are_defined(defs):
    assert set(defs) == EXPECTED
    assert {i for i, d in defs.items() if d.must_pass} == MUST_PASS


def test_every_scene_names_its_trap_and_the_cue_it_leaves(defs):
    for eid, d in defs.items():
        assert len(d.trap) > 40 and len(d.cue) > 40, eid
        assert d.nodes and d.variants % 2 == 0 and d.biomes, eid


def test_must_pass_scenes_have_a_top_and_a_bottom_door(defs):
    for eid in MUST_PASS - {"E06"}:  # E06 is the sealed deep: only a top door
        assert {"top", "bottom"} <= set(defs[eid].doors()), eid
    assert defs["E06"].fixed and set(defs["E06"].doors()) == {"top"}


def test_acid_is_only_allowed_in_the_brick_vat_scenes(defs):
    for eid, d in defs.items():
        has_acid = any("X" in row for row in d.rows)
        assert d.allow_acid == has_acid, eid
    assert {i for i, d in defs.items() if d.allow_acid} == {"E07", "E16"}


@pytest.mark.parametrize("rule_seed", RULE_SEEDS)
def test_instances_are_deterministic_and_the_odd_variant_is_the_mirror(defs, rule_seed):
    mats_rules = get_rules(rule_seed)
    from noitabench.worldgen.config import load_materials

    mats = load_materials()
    for eid, d in defs.items():
        for v in range(0, d.variants, 2):
            a = instantiate(d, mats_rules, v, mats)
            again = instantiate(d, mats_rules, v, mats)
            b = instantiate(d, mats_rules, v + 1, mats)
            assert np.array_equal(a.grid, again.grid) and a.markers == again.markers, eid
            assert not a.mirror and b.mirror and a.params == b.params, eid
            assert np.array_equal(a.grid[:, ::-1], b.grid), eid
            assert sorted(a.doors) == sorted(
                {"left": "right", "right": "left"}.get(s, s) for s in b.doors
            ), eid


def test_liquid_slots_follow_the_rules_of_the_world(defs):
    from noitabench.worldgen.config import load_materials

    mats = load_materials()
    for rule_seed in RULE_SEEDS:
        rules = get_rules(rule_seed)
        for eid in ("E02", "E04", "E14"):
            inst = instantiate(defs[eid], rules, 0, mats)
            for slot in defs[eid].slots.values():
                if slot.role == "lava_solidifier":
                    assert inst.params[slot.name] in rules.solidifiers(), (eid, rule_seed)
                if slot.role == "not_lava_solidifier":
                    assert inst.params[slot.name] not in rules.solidifiers(), (eid, rule_seed)
    # the table is the original for every rule seed: the same answer everywhere
    assert {tuple(get_rules(s).solidifiers()) for s in range(20)} == {
        tuple(get_rules(0).solidifiers())
    }


@pytest.mark.parametrize("rule_seed", RULE_SEEDS)
def test_no_pair_of_neighbouring_cells_reacts_at_frame_zero(defs, rule_seed):
    """Nothing in a scene starts to happen before the player arrives (any rule seed)."""
    from noitabench.worldgen.config import load_materials

    mats = load_materials()
    rules = get_rules(rule_seed)
    for eid, d in defs.items():
        for v in range(d.variants):
            g = instantiate(d, rules, v, mats).grid
            pairs = set()
            for a, b in ((g[:, :-1], g[:, 1:]), (g[:-1, :], g[1:, :])):
                diff = a != b
                pairs |= set(zip(a[diff].tolist(), b[diff].tolist(), strict=True))
            for x, y in pairs:
                ka, kb = mats.keys[x], mats.keys[y]
                assert not (rules.reacts(ka, kb) or rules.reacts(kb, ka)), (eid, v, ka, kb)
                assert not ((rules.ignites(ka, kb) or 0) > 0 or (rules.ignites(kb, ka) or 0) > 0), (
                    eid,
                    v,
                    ka,
                    kb,
                )


@pytest.mark.parametrize("rule_seed", [0, 7])
def test_every_scene_is_at_rest_in_its_lab_world(defs, rule_seed):
    from noitabench.worldgen.config import load_materials

    mats = load_materials()
    for eid, d in defs.items():
        for v in range(d.variants):
            w = scene_world(eid, v, rule_seed, 1, mats)
            for kind in ("powder", "liquid"):
                ys, xs = mobile_cells(w.grid, mats, kind)
                assert len(ys) == 0, (eid, v, kind, list(zip(xs[:3], ys[:3], strict=False)))


# ---------------------------------------------------------------------------- bad scenes

GOOD_ART = ["######", "#....#", "<....#", "#....#", "######"]
GOOD_DEF = {
    "format": "cogbench-encounter/0",
    "id": "E99",
    "name_zh": "x",
    "name_en": "x",
    "nodes": ["N1"],
    "must_pass": False,
    "biomes": ["mine"],
    "art": "E99.scene",
    "variants": 2,
    "markers": {},
    "trap": "t",
    "cue": "c",
}


def _load(tmp_path, art, **changes):
    from noitabench.worldgen.encounter_defs import load_encounters as load

    (tmp_path / "E99.scene").write_text("\n".join(art) + "\n", encoding="utf-8")
    (tmp_path / "E99.json").write_text(json.dumps({**GOOD_DEF, **changes}), encoding="utf-8")
    return load.__wrapped__(tmp_path)  # not the cached one


def test_a_minimal_scene_loads(tmp_path):
    assert set(_load(tmp_path, GOOD_ART)) == {"E99"}


def test_a_marker_given_as_a_list_changes_with_the_variant_pair(tmp_path, mats):
    water = {"type": "item", "item": "bottle", "contents": "water"}
    potion = {"type": "item", "item": "potion_heal"}
    art = ["######", "#....#", "<.1..#", "#gggg#", "######"]
    d = _load(tmp_path, art, variants=6, markers={"1": [water, potion]})["E99"]
    items = [instantiate(d, get_rules(0), v, mats).markers[0]["item"] for v in range(6)]
    assert items == ["bottle", "bottle", "potion_heal", "potion_heal", "bottle", "bottle"]
    assert d.markers["1"] == water  # the first template, for readers of a single one


BAD_SCENES = [
    ("unknown character", ["######", "#.Z..#", "<....#", "#....#", "######"], {}, "legend"),
    ("rows of different length", ["######", "#....#", "<...#", "######"], {}, "different lengths"),
    (
        "a marker without a definition",
        ["######", "#.1..#", "<....#", "#....#", "######"],
        {},
        "marker 1",
    ),
    (
        "acid without allow_acid",
        ["######", "#.XX.#", "<....#", "#....#", "######"],
        {},
        "allow_acid",
    ),
    ("a door off its edge", ["######", "#.^..#", "<....#", "#....#", "######"], {}, "edge"),
    ("no door at all", ["######", "#....#", "#....#", "#....#", "######"], {}, "door"),
    ("odd variant count", GOOD_ART, {"variants": 3}, "even"),
    ("id and file differ", GOOD_ART, {"id": "E98"}, "file name"),
    ("a missing field", GOOD_ART, {"trap": None}, "trap"),
    (
        "an enemy without room for its box",
        ["######", "#....#", "<.1..#", "#gggg#", "######"],
        {"markers": {"1": {"type": "spawn_enemy", "enemy": "longleg"}}},
        "free cells above",
    ),
    (
        "a barrel without room above it",
        ["######", "#....#", "<.1..#", "#gggg#", "######"],
        {"markers": {"1": {"type": "item", "item": "barrel_gunpowder"}}},
        "barrel needs",
    ),
    (
        "a breaker without a spell",
        ["######", "#....#", "<.1..#", "#gggg#", "######"],
        {"markers": {"1": {"type": "item", "item": "spell", "role": "breaker"}}},
        "breaker is a spell",
    ),
    (
        "a breaker of a spell the catalogue does not have",
        ["######", "#....#", "<.1..#", "#gggg#", "######"],
        {"markers": {"1": {"type": "item", "item": "spell", "spell": "NUKE", "role": "breaker"}}},
        "breaker is a spell",
    ),
    (
        "a breaker that is not a spell",
        ["######", "#....#", "<.1..#", "#gggg#", "######"],
        {"markers": {"1": {"type": "item", "item": "wand", "spell": "BOMB", "role": "breaker"}}},
        "breaker is a spell",
    ),
    (
        "a marker in mid-air",
        ["######", "#.1..#", "<....#", "#....#", "######"],
        {"markers": {"1": {"type": "item", "item": "potion_heal"}}},
        "no floor",
    ),
    (
        "more templates than variant pairs",
        ["######", "#....#", "<.1..#", "#gggg#", "######"],
        {"markers": {"1": [{"type": "item", "item": "bottle"}] * 2}},
        "variant pairs",
    ),
    (
        "an empty list of templates",
        ["######", "#....#", "<.1..#", "#gggg#", "######"],
        {"markers": {"1": []}},
        "non-empty list",
    ),
    (
        "a breaker that changes with the variant",
        ["######", "#....#", "<.1..#", "#gggg#", "######"],
        {
            "variants": 4,
            "markers": {
                "1": [
                    {"type": "item", "item": "spell", "spell": "BOMB", "role": "breaker"},
                    {"type": "item", "item": "bottle"},
                ]
            },
        },
        "cannot change with the variant",
    ),
    (
        "a barrel in one variant's template without room above it",
        ["######", "#....#", "<.1..#", "#gggg#", "######"],
        {
            "variants": 4,
            "markers": {
                "1": [{"type": "item", "item": "bottle"}, {"type": "item", "item": "barrel_oil"}]
            },
        },
        "barrel needs",
    ),
]


@pytest.mark.parametrize("name,art,changes,message", BAD_SCENES, ids=[b[0] for b in BAD_SCENES])
def test_bad_scenes_are_rejected_with_a_clear_message(tmp_path, name, art, changes, message):
    if name == "a missing field":
        changes = {}
        (tmp_path / "E99.scene").write_text("\n".join(art) + "\n", encoding="utf-8")
        bad = {k: v for k, v in GOOD_DEF.items() if k != "trap"}
        (tmp_path / "E99.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_encounters.__wrapped__(tmp_path)
        return
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, art, **changes)


# ------------------------------------------------------------------------ the rules bindings


def test_the_reaction_table_is_the_original_for_every_rule_seed():
    a, b = get_rules(5), get_rules(6)
    assert a.reactions_json == b.reactions_json and a.content_hash == b.content_hash
    assert get_rules(5) is get_rules(5)  # cached per rule seed


def test_the_table_has_a_liquid_that_solidifies_lava():
    for rule_seed in range(10):
        rules = get_rules(rule_seed)
        assert rules.solidifiers(), rule_seed
        assert predicate_holds("lava_solidifier", rules)[0]


KEY = ["EXPLOSIVE_PROJECTILE", "BOMB"]


def test_the_scenes_hand_out_the_two_parts_of_the_key_of_the_seal(defs):
    assert breaker_spells() == {"BOMB", "EXPLOSIVE_PROJECTILE"}
    assert {i for i, d in defs.items() if d.hands_out_breaker} == {"E02", "E12"}
    assert {"E02", "E12"} <= single_ids()  # a world holds each of them at most once
    # the first corridor of E12 holds the modifier, on a floor cell
    d = defs["E12"]
    item = next(m for m in d.markers.values() if m.get("role") == "breaker")
    assert item == {
        "type": "item",
        "item": "spell",
        "spell": "EXPLOSIVE_PROJECTILE",
        "role": "breaker",
    }


def test_the_key_assembled_in_the_starter_wand_reaches_brick_and_no_part_alone_does():
    brick = breaker.plug_durability()
    assert brick == 14
    combo = breaker.best_combo(["BOMB", "EXPLOSIVE_PROJECTILE"])
    assert combo is not None
    assert combo.spells == tuple(KEY)  # the modifier first, the projectile after it
    assert (combo.durability, combo.mana) == (14, 55.0)
    assert breaker.best_combo(["BOMB"]).durability == 11
    assert breaker.best_combo(["EXPLOSIVE_PROJECTILE"]) is None  # a modifier alone casts nothing
    assert predicate_holds("seal_breakable", get_rules(0))[0]  # the scenes' own set
    ok, why = predicate_holds("seal_breakable", get_rules(0), ["BOMB"])
    assert not ok and "brick" in why and "11" in why


def test_no_other_pair_of_the_catalogue_reaches_brick():
    keys = list(breaker.spell_table())
    brick = breaker.plug_durability()
    for projectile in keys:
        for modifier in [None, "EXPLOSIVE_PROJECTILE"]:
            held = [projectile] + ([modifier] if modifier else [])
            combo = breaker.best_combo(held)
            if combo is not None and combo.durability >= brick:
                assert set(combo.spells) == set(KEY), held


def test_copies_of_the_modifier_do_not_stack():
    # 10 (the dig bolt) + 3, not 10 + 3 + 3: the largest bonus counts
    assert breaker.best_combo(["DIGGER", "EXPLOSIVE_PROJECTILE"]).durability == 13
    assert breaker.best_combo(["FIREBALL", "SLOW_BULLET", "EXPLOSIVE_PROJECTILE"]).durability == 13


def test_the_key_has_to_fit_the_starter_wand(monkeypatch):
    monkeypatch.setattr(breaker, "starter_spark_wand", lambda: (1, 100.0))
    assert breaker.best_combo(KEY).durability == 11  # one slot: only the bomb
    assert not predicate_holds("seal_breakable", get_rules(0))[0]
    monkeypatch.setattr(breaker, "starter_spark_wand", lambda: (3, 50.0))
    assert breaker.best_combo(KEY).durability == 11  # 30 + 25 mana do not fit in 50
    assert not predicate_holds("seal_breakable", get_rules(0))[0]


# ----------------------------------------------------------------------------- in the world


def test_the_world_json_records_the_scene_and_the_rules(world_a):
    scenes = placed_encounters(world_a)
    assert len(scenes) >= 18
    for m in scenes:
        assert m["placeholder"] is False
        assert set(m) >= {"encounter_id", "variant", "mirror", "params", "footprint", "regions"}
        assert m["variant"] % 2 == int(m["mirror"])
    doc = json.loads(world_a.json_text())
    assert (
        "strength" not in doc and doc["rule_seed"] == world_a.rule_seed
    )  # the rule seed is stored, there is no strength


def test_the_slots_in_the_bands_are_the_must_pass_scenes(world_a):
    bands = [m for m in placed_encounters(world_a) if m["must_pass"]]
    assert {m["encounter_id"] for m in bands} <= MUST_PASS
    assert sum(1 for m in bands if m["biome"] != "seal") >= 6


def test_the_rule_seed_does_not_change_the_terrain():
    """Same seed, other rule seed: the same world (the table is fixed), only the stored seed differs."""
    a = generate_world(5, rule_seed=0)
    b = generate_world(5, rule_seed=7)
    assert (a.grid == b.grid).all() and a.markers == b.markers
    assert json.loads(a.json_text())["rule_seed"] == 0
    assert json.loads(b.json_text())["rule_seed"] == 7
    sol = {m["contents"] for m in b.markers if m.get("role") == "solvent"}
    assert sol <= set(get_rules(7).solidifiers())


def test_generate_world_takes_no_strength():
    """The old third positional argument (the strength) must fail loudly, not become max_attempts."""
    with pytest.raises(TypeError):
        generate_world(5, 0, 2)
    with pytest.raises(TypeError):
        generate_world(5, rule_seed=0, strength=0)


def test_generation_is_deterministic_for_one_rule_seed():
    a = generate_world(5, rule_seed=7)
    b = generate_world(5, rule_seed=7)
    assert a.json_text() == b.json_text() and (a.grid == b.grid).all()


def test_acid_stays_in_the_vats(world_a, mats):
    acid = world_a.grid == mats["acid"]
    assert acid.any() and not (acid & ~acid_allowed_mask(world_a)).any()


def test_the_key_of_the_seal_lies_where_the_player_walks(world_a, bm, mats):
    rep = run_checks(world_a, bm, mats)
    assert rep.ok, rep.failures
    spells = sorted(m["spell"] for m in world_a.markers if m.get("role") == "breaker")
    assert spells == sorted(KEY)
    assert rep.stats["breakers"] == {"BOMB": 1, "EXPLOSIVE_PROJECTILE": 1}


def test_a_scene_that_was_cut_is_noticed(world_a, bm, mats):
    w = _mutated(world_a)
    m = next(s for s in placed_encounters(w) if s["encounter_id"] == "E07")
    fp = m["footprint"]
    w.grid[fp["y"] + 8 : fp["y"] + 12, fp["x"] + 30 : fp["x"] + 40] = mats["rock"]
    w.markers = [
        s for s in w.markers if not (s["type"] in ("item", "spawn_enemy") and _inside(s, fp))
    ]
    assert any("differ from its scene" in f for f in run_checks(w, bm, mats).failures)


def test_a_solvent_that_does_not_solidify_lava_is_noticed(world_a, bm, mats):
    w = _mutated(world_a)
    rules = get_rules(w.rule_seed)
    wrong = next(k for k in ("oil", "whiskey") if k not in rules.solidifiers())
    for m in w.markers:
        if m["type"] == "item" and m.get("role") == "solvent" and m["encounter_id"] == "E02":
            m["contents"] = wrong
    fails = run_checks(w, bm, mats).failures
    assert any("E02 needs" in f and "solvent" in f for f in fails)


def test_each_copy_of_a_scene_carries_its_own_supplies(world_a, bm, mats):
    """E14 is placed twice: a copy without a working solvent fails even if the other has one."""
    w = _mutated(world_a)
    first, second = (m for m in placed_encounters(w) if m["encounter_id"] == "E14")
    assert run_checks(w, bm, mats).ok
    for m in w.markers:
        if m["type"] == "item" and m.get("role") == "solvent" and _inside(m, first["footprint"]):
            m["contents"] = "oil"
    assert any("E14 needs" in f and "solvent" in f for f in run_checks(w, bm, mats).failures), (
        second["footprint"]
    )


def test_a_world_holds_one_of_each_part_of_the_key(bm, mats):
    """Seed 66 used to draw E02 (which hands out the BOMB spell) a second time as an optional
    scene; the picker now keeps each part unique, and a second copy is a failure."""
    w = generate_world(66, rule_seed=66)
    keys = [m for m in w.markers if m.get("role") == "breaker"]
    assert sorted(m["spell"] for m in keys) == sorted(KEY)
    for key in keys:
        two = _mutated(w)
        two.markers.append({**key, "x": key["x"] + 2})
        fails = run_checks(two, bm, mats).failures
        assert any(f"2 breaker items of {key['spell']}" in f for f in fails), (key["spell"], fails)


@pytest.mark.parametrize("gone", KEY)
def test_a_missing_part_of_the_key_is_noticed(world_a, bm, mats, gone):
    w = _mutated(world_a)
    w.markers = [m for m in w.markers if not (m.get("role") == "breaker" and m["spell"] == gone)]
    fails = run_checks(w, bm, mats).failures
    assert any(f"0 breaker items of {gone}" in f for f in fails), fails
    assert any("E06" in f and "unsolvable" in f for f in fails), fails  # the seal cannot open
    assert any("E06 needs 2 breaker items" in f for f in fails), fails


def test_a_breaker_item_no_scene_hands_out_is_noticed(world_a, bm, mats):
    """A third part of the key (or a stand-in for a missing one) is no part of the design."""
    assert run_checks(world_a, bm, mats).ok
    w = _mutated(world_a)
    key = next(m for m in w.markers if m.get("role") == "breaker")
    w.markers.append({**key, "spell": "FIREBALL", "x": key["x"] + 3})
    fails = run_checks(w, bm, mats).failures
    assert any("FIREBALL" in f and "no scene definition" in f for f in fails), fails


def test_the_seal_check_fails_alone_when_the_modifier_loses_its_bonus(
    world_a, bm, mats, monkeypatch
):
    """Both parts of the key are in the world and reachable, but the catalogue's modifier no
    longer raises the explosion: the hard predicate is the only thing that notices."""
    assert run_checks(world_a, bm, mats).ok
    table = copy.deepcopy(breaker.spell_table())
    table["EXPLOSIVE_PROJECTILE"]["shot"]["explosion_durability"] = 0
    monkeypatch.setattr(breaker, "spell_table", lambda: table)
    fails = run_checks(world_a, bm, mats).failures
    assert len(fails) == 1 and "E06" in fails[0] and "unsolvable" in fails[0], fails
    assert "durability 11" in fails[0] and "brick has 14" in fails[0], fails


def test_a_key_that_cannot_open_the_seal_is_noticed(world_a, bm, mats):
    """The modifier swapped for a spell that does not raise the explosion: the missing part, the
    stray one and the seal that stays closed are all noticed."""
    w = _mutated(world_a)
    for m in w.markers:
        if m.get("role") == "breaker" and m["spell"] == "EXPLOSIVE_PROJECTILE":
            m["spell"] = "SPEED"
    fails = run_checks(w, bm, mats).failures
    assert any("E06" in f and "unsolvable" in f and "durability 11" in f for f in fails), fails


def test_a_part_of_the_key_behind_the_dig_zone_of_its_own_scene_is_noticed(world_a, bm, mats):
    """The modifier moved into the last corridor of E12, behind two plugs that must be dug: it
    lies in the strata's walking area (the zone counts as walkable for the way down) but it is
    no longer reachable without digging that scene's own zone."""
    assert run_checks(world_a, bm, mats).ok
    w = _mutated(world_a)
    fp = next(m for m in placed_encounters(w) if m["encounter_id"] == "E12")["footprint"]
    guard = next(
        m for m in w.markers if m["type"] == "spawn_enemy" and m.get("encounter_id") == "E12"
    )
    assert _inside(guard, fp)  # the guard stands in the third corridor
    key = next(m for m in w.markers if m.get("spell") == "EXPLOSIVE_PROJECTILE")
    key["x"], key["y"] = guard["x"], guard["y"]
    fails = run_checks(w, bm, mats).failures
    assert any("E12" in f and "cannot be reached on foot" in f for f in fails), fails


class _OtherTable:
    """The real table, except that only whiskey turns lava to rock (a stand-in for a table the
    world was not built for)."""

    def __init__(self, real):
        self._real = real

    def lava_solidifiers(self):
        return [{"liquid": "whiskey"}]

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_a_scene_built_for_another_table_is_noticed(bm, mats):
    """The world was built for one table; judged against another it fails."""
    w = generate_world(5, rule_seed=7)
    other = Rules(7, _OtherTable(get_rules(7).table))
    assert other.solidifiers() != get_rules(7).solidifiers()
    fails = run_checks(w, bm, mats, other).failures
    assert any("liquids do not match" in f or "solvent" in f for f in fails)


def _inside(m: dict, fp: dict) -> bool:
    return fp["x"] <= m["x"] < fp["x"] + fp["w"] and fp["y"] <= m["y"] < fp["y"] + fp["h"]


def test_the_scenes_of_a_generated_world_hold_still_in_the_game(tmp_path, mats):
    """Load a generated world into the game: no scene changes by itself."""
    from noitabench.game import Game

    world = generate_world(3, rule_seed=7)
    png, js = world.write(tmp_path, "w", mats)
    game = Game.from_world(png, js, 3, rule_seed=7, reactions_json=get_rules(7).reactions_json)
    game.step(90)
    for m in placed_encounters(world):
        fp = m["footprint"]
        box = world.grid[fp["y"] : fp["y"] + fp["h"], fp["x"] : fp["x"] + fp["w"]]
        want = {
            mats.keys[k]: int(n) for k, n in zip(*np.unique(box, return_counts=True), strict=True)
        }
        got = game.overlap(fp["x"], fp["y"], fp["w"], fp["h"])["materials"]
        for key, n in want.items():
            if mats.kinds[mats.index[key]] in ("liquid", "powder"):
                assert got.get(key, 0) == n, (m["encounter_id"], key)


# ----------------------------------------------------------- batch G1: five optional rooms

G1 = ("E05", "E09", "E10", "E21", "E24")


def test_the_new_rooms_are_optional_and_measure_the_thin_nodes(defs):
    nodes = {eid: defs[eid].nodes[0] for eid in G1}
    assert nodes == {"E05": "N2", "E09": "N4", "E10": "N4", "E21": "N9", "E24": "N10"}
    for eid in G1:
        assert not defs[eid].must_pass and not defs[eid].dig_zone and not defs[eid].gates, eid
        assert defs[eid].layer is None and "left" in defs[eid].doors(), eid


def test_a_scene_can_ask_to_be_placed_once(defs):
    assert {"E09", "E10"} <= single_ids()
    assert not ({"E05", "E21", "E24"} & single_ids())  # node coverage needs two of these
    assert {i for i, d in defs.items() if d.once} == {"E09", "E10"}


def test_the_new_rooms_have_the_regions_a_scorer_needs(defs):
    need = {
        "E05": {"key", "decoy", "shaft", "drop", "landing", "river", "river_gate", "vault"},
        "E09": {"bunker", "interior", "posts", "gutter", "barrel", "crater", "reward"},
        "E10": {"near", "pool", "surface", "bottom", "far", "pack", "reward"},
        "E21": {"nook", "bench", "bottles"},
        "E24": {"room_a", "pool_a", "vial_a", "partition", "room_b", "pool_b", "vial_b", "far"},
    }
    for eid, names in need.items():
        assert names <= set(defs[eid].regions), (eid, names - set(defs[eid].regions))


def test_the_solvent_of_e05_is_water_or_blood_never_a_gas_maker(defs):
    mats = load_materials()
    for rule_seed in RULE_SEEDS:
        rules = get_rules(rule_seed)
        for v in range(defs["E05"].variants):
            inst = instantiate(defs["E05"], rules, v, mats)
            assert inst.params["A"] in ("water", "blood")
            assert inst.params["B"] not in rules.solidifiers()


def test_e21_holds_one_remedy_and_never_a_lethal_liquid(defs):
    mats = load_materials()
    for v in range(defs["E21"].variants):
        inst = instantiate(defs["E21"], get_rules(0), v, mats)
        contents = sorted(m.get("contents", m["item"]) for m in inst.markers)
        assert contents.count("potion_heal") == 1
        assert "toxic_sludge" in contents
        assert not {"acid", "lava"} & set(contents)


_SEEDS = (0, 1, 2, 3, 4, 5)


@pytest.fixture(scope="module")
def worlds():
    return {seed: generate_world(seed, rule_seed=seed) for seed in _SEEDS}


def test_the_new_rooms_are_placed_in_the_right_layers(worlds):
    for seed, world in worlds.items():
        by_id: dict[str, list[dict]] = {}
        for m in placed_encounters(world):
            by_id.setdefault(m["encounter_id"], []).append(m)
        assert len(by_id["E09"]) == 1 and by_id["E09"][0]["layer"] == 1, seed
        assert len(by_id["E10"]) == 1 and by_id["E10"][0]["layer"] == 2, seed
        assert {m["layer"] for m in by_id["E21"]} <= {1, 2} and len(by_id["E21"]) == 2, seed
        assert {m["layer"] for m in by_id["E24"]} <= {1, 3} and len(by_id["E24"]) in (1, 2), seed
        assert {m["layer"] for m in by_id["E05"]} <= {2, 3} and len(by_id["E05"]) == 2, seed
        for eid in G1:
            assert all(not m["must_pass"] for m in by_id[eid]), (seed, eid)


def test_a_biome_holds_one_optional_copy_of_a_scene(worlds):
    for seed, world in worlds.items():
        seen = set()
        for m in world.markers:
            if m["type"] == "encounter" and not m["must_pass"]:
                key = (m["biome"], m["layer"], m["encounter_id"])
                assert key not in seen, (seed, key)
                seen.add(key)


def test_every_new_room_is_walkable_to_and_intact_in_the_worlds(worlds, bm, mats):
    for seed, world in worlds.items():
        rep = run_checks(world, bm, mats)
        assert rep.ok, (seed, rep.failures)
        assert rep.stats["broken_scenes"] == 0


def test_the_new_rooms_hold_the_items_they_promise(worlds):
    """E05 carries its solvent and its decoy, E10 and E09 their wands; a barrel stands in E09."""
    for seed, world in worlds.items():
        items = [m for m in world.markers if m["type"] == "item"]
        by_scene: dict[str, list[dict]] = {}
        for m in items:
            by_scene.setdefault(m.get("encounter_id", ""), []).append(m)
        solvents = [m for m in by_scene["E05"] if m.get("role") == "solvent"]
        assert len(solvents) == 2, seed  # one per copy of the scene
        assert all(m["contents"] in ("water", "blood") for m in solvents)
        decoys = [m for m in by_scene["E05"] if m.get("role") == "decoy"]
        assert len(decoys) == 2 and all(m["contents"] in ("oil", "whiskey") for m in decoys), seed
        for eid in ("E09", "E10"):
            assert sum(m["item"] == "wand" for m in by_scene[eid]) == 1, (seed, eid)
        assert sum(m["item"] == "barrel_gunpowder" for m in by_scene["E09"]) == 1
        assert sum(m["item"] == "potion_heal" for m in by_scene["E21"]) == 2  # one per copy
