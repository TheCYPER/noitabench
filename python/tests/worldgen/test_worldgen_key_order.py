"""The seal key completes last: E12 is the deepest must-pass scene of layer 3 (key_order.py)."""

from __future__ import annotations

import copy
import dataclasses
import itertools
import json
import shutil
from collections import Counter

import numpy as np
import pytest
from noitabench.worldgen.checks import CheckReport, run_checks
from noitabench.worldgen.config import CONTENT_DIR, load_biome_map
from noitabench.worldgen.key_order import check_key_order
from noitabench.worldgen.layers import band_order


def _mutated(world):
    return dataclasses.replace(
        world, grid=world.grid.copy(), markers=copy.deepcopy(world.markers), meta=dict(world.meta)
    )


def _layer3_bands(world) -> list[dict]:
    """The layer-3 must-pass band scenes from the top down."""
    bands = [
        m
        for m in world.markers
        if m["type"] == "encounter" and m["must_pass"] and m["layer"] == 3 and m["biome"] != "seal"
    ]
    return sorted(bands, key=lambda m: m["footprint"]["y"])


def _breaker(world, spell: str) -> dict:
    return next(
        m for m in world.markers if m["type"] == "item" and m.get("role") == "breaker"
        and m["spell"] == spell
    )  # fmt: skip


def _failures(world, bm) -> list[str]:
    rep = CheckReport()
    check_key_order(world, bm, rep)
    return rep.failures


# ------------------------------------------------------------------ the order draw


def test_biome_map_names_e12_as_the_last_scene_of_layer_3_only(bm):
    assert [(lay.layer, lay.last) for lay in bm.layers] == [(1, None), (2, None), (3, "E12")]


def test_layer_3_always_ends_with_e12_and_keeps_the_other_two_in_random_order(bm):
    lay = bm.layers[2]
    orders = Counter(tuple(band_order(lay, np.random.default_rng(seed))) for seed in range(200))
    assert set(orders) == {("E02", "E23", "E12"), ("E23", "E02", "E12")}
    assert min(orders.values()) > 50  # both orders are common, not a rarity


@pytest.mark.parametrize("index", [0, 1])
def test_layers_without_a_last_scene_draw_every_order_as_before(bm, index):
    lay = bm.layers[index]
    assert lay.last is None
    seen = set()
    for seed in range(300):
        got = band_order(lay, np.random.default_rng(seed))
        plain = list(lay.must_pass)
        np.random.default_rng(seed).shuffle(plain)
        assert got == plain  # the same shuffle, untouched
        seen.add(tuple(got))
    assert seen == set(itertools.permutations(lay.must_pass))


def test_the_last_scene_costs_the_shuffle_nothing_extra(bm):
    """The draw consumes the same random numbers for every layer, so later draws do not move."""
    lay = bm.layers[2]
    a, b = np.random.default_rng(7), np.random.default_rng(7)
    band_order(lay, a)
    b.shuffle(list(lay.must_pass))
    assert a.integers(0, 1 << 30) == b.integers(0, 1 << 30)


# ------------------------------------------------------------ generated worlds


def test_generated_worlds_put_e12_below_the_other_layer_3_bands(world_a, world_b, bm):
    for world in (world_a, world_b):
        ids = [m["encounter_id"] for m in _layer3_bands(world)]
        assert ids[-1] == "E12" and sorted(ids) == ["E02", "E12", "E23"]
        assert _failures(world, bm) == []
        rep = CheckReport()
        check_key_order(world, bm, rep)
        assert rep.stats["key_last"] == {"3": "E12"}


def test_the_spell_that_completes_the_key_lies_in_e12_and_the_bomb_above_it(world_a, bm):
    e12 = _layer3_bands(world_a)[-1]["footprint"]
    mod, bomb = _breaker(world_a, "EXPLOSIVE_PROJECTILE"), _breaker(world_a, "BOMB")
    assert e12["y"] <= mod["y"] < e12["y"] + e12["h"]
    assert e12["x"] <= mod["x"] < e12["x"] + e12["w"]
    assert bomb["y"] < e12["y"]


def test_the_full_checks_run_the_key_order_check(world_a):
    rep = run_checks(world_a)
    assert rep.ok, rep.failures
    assert rep.stats["key_last"] == {"3": "E12"}


# ------------------------------------------------------------ negative controls


def test_a_world_with_e12_above_another_band_fails(world_a, bm):
    w = _mutated(world_a)
    bands = {m["encounter_id"]: m for m in _layer3_bands(w)}
    # swap the two scenes' places: the marker called E12 now sits in the shallowest band
    bands["E12"]["encounter_id"], bands["E02"]["encounter_id"] = "E02", "E12"
    text = " ".join(_failures(w, bm))
    assert "is not above E12" in text
    assert "EXPLOSIVE_PROJECTILE" in text  # and its item is no longer inside that scene


def test_every_misplaced_order_of_the_layer_3_bands_fails(world_a, bm):
    for order in itertools.permutations(["E02", "E23", "E12"]):
        w = _mutated(world_a)
        bands = _layer3_bands(w)
        for m, eid in zip(bands, order):
            m["encounter_id"] = eid
        failed = bool(_failures(w, bm))
        assert failed == (order[-1] != "E12"), order


def test_the_full_checks_ask_the_biome_map_for_the_last_scene(world_a, bm):
    """Wiring: ``run_checks`` runs the check with the map it is given."""
    other = [
        dataclasses.replace(lay, last="E23" if lay.layer == 3 else lay.last) for lay in bm.layers
    ]
    rep = run_checks(world_a, dataclasses.replace(bm, layers=tuple(other)))
    assert any("E12" in f and "is not above E23" in f for f in rep.failures), rep.failures
    assert rep.stats["key_last"] == {"3": "E23"}


def test_the_modifier_outside_e12_fails(world_a, bm):
    w = _mutated(world_a)
    _breaker(w, "EXPLOSIVE_PROJECTILE")["y"] -= 120  # up in the band above
    assert any("not inside E12" in f for f in _failures(w, bm))


def test_the_bomb_below_the_top_of_e12_fails(world_a, bm):
    w = _mutated(world_a)
    e12 = _layer3_bands(w)[-1]["footprint"]
    _breaker(w, "BOMB")["y"] = e12["y"] + 5  # the key would be complete on entering E12
    assert any("the key would be complete earlier" in f for f in _failures(w, bm))


def test_a_missing_or_doubled_last_scene_fails(world_a, bm):
    w = _mutated(world_a)
    _layer3_bands(w)[-1]["must_pass"] = False  # E12 is no longer a must-pass band
    assert any("exactly one is needed" in f for f in _failures(w, bm))
    w = _mutated(world_a)
    _layer3_bands(w)[0]["encounter_id"] = "E12"
    assert any("exactly one is needed" in f for f in _failures(w, bm))


# ------------------------------------------------------------------ content file


def _content_copy(tmp_path):
    dst = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, dst)
    return dst


def test_a_last_scene_must_be_a_must_pass_id_of_its_layer(tmp_path):
    dst = _content_copy(tmp_path)
    path = dst / "biome_map.json"
    data = json.loads(path.read_text())
    data["layers"][2]["last"] = "E16"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=r"layers\.last"):
        load_biome_map(dst)
    del data["layers"][2]["last"]  # a layer may also name none
    path.write_text(json.dumps(data))
    assert load_biome_map(dst).layers[2].last is None
