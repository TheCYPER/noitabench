"""Generated worlds: determinism, structure, markers, file pair (generate.py, world.py)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from noitabench.worldgen import generate, generate_world, load_world
from noitabench.worldgen.canvas import GenerationFailure
from noitabench.worldgen.encounter_checks import acid_allowed_mask
from noitabench.worldgen.encounters import BASE_NODES, node_of
from noitabench.worldgen.generate import MAX_ATTEMPTS
from PIL import Image

PYTHON_DIR = Path(__file__).resolve().parents[2]
ENEMY_HEIGHT = {"longleg": 9, "shotgunner": 11, "firemage_weak": 19}  # content/entities.json


def _digest(world, mats) -> str:
    return hashlib.sha256(world.png_bytes(mats) + world.json_text().encode()).hexdigest()


def test_same_seed_gives_byte_identical_files(world_a, mats):
    again = generate_world(3)
    assert world_a.png_bytes(mats) == again.png_bytes(mats)
    assert world_a.json_text() == again.json_text()


def test_same_seed_is_identical_across_processes_and_hash_seeds():
    code = (
        "import hashlib\n"
        "from noitabench.worldgen import generate_world\n"
        "from noitabench.worldgen.config import load_materials\n"
        "w = generate_world(11); m = load_materials()\n"
        "print(hashlib.sha256(w.png_bytes(m) + w.json_text().encode()).hexdigest())\n"
    )
    outs = []
    for hash_seed in ("0", "12345"):
        env = {**os.environ, "PYTHONPATH": str(PYTHON_DIR), "PYTHONHASHSEED": hash_seed}
        r = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
        )
        outs.append(r.stdout.strip())
    assert outs[0] == outs[1] and len(outs[0]) == 64


def test_different_seeds_give_different_terrain_but_the_same_biome_map(world_a, world_b):
    assert world_a.biome_map == world_b.biome_map
    differ = float((world_a.grid != world_b.grid).mean())
    assert differ > 0.2, f"only {differ:.0%} of the cells differ"
    cave_a, cave_b = world_a.grid == 0, world_b.grid == 0
    assert float((cave_a != cave_b).mean()) > 0.15


def test_world_is_generated_within_ten_seconds():
    t0 = time.perf_counter()
    generate_world(21)
    assert time.perf_counter() - t0 < 10.0


def test_file_pair_follows_the_contract(world_a, mats, tmp_path):
    png, js = world_a.write(tmp_path, "w", mats)
    img = Image.open(png)
    assert img.mode == "P" and img.size == (768, 1664)
    palette = img.getpalette()
    for i, color in enumerate(mats.colors):
        assert palette[3 * i : 3 * i + 3] == [
            int(color[1:3], 16),
            int(color[3:5], 16),
            int(color[5:7], 16),
        ]
    data = json.loads(js.read_text())
    assert data["format"] == "cogbench-world/0"
    for key in ("seed", "rule_seed", "width", "height", "biome_cell_size", "biome_map", "markers"):
        assert key in data
    assert (data["width"], data["height"], data["biome_cell_size"]) == (768, 1664, 128)
    assert len(data["biome_map"]) == 13 and len(data["biome_map"][0]) == 6
    back = load_world(png, js)
    assert np.array_equal(back.grid, world_a.grid) and back.markers == world_a.markers
    assert int(np.array(img).max()) < len(mats)


def test_cell_values_are_valid_material_indices(world_a, mats):
    assert world_a.grid.dtype == np.uint8
    assert int(world_a.grid.max()) < len(mats)
    assert (world_a.grid == mats["brick"]).any() and (world_a.grid == mats.air).any()


def test_marker_counts_and_fields(world_a, mats):
    by_type: dict[str, list[dict]] = {}
    for m in world_a.markers:
        by_type.setdefault(m["type"], []).append(m)
    assert len(by_type["spawn_player"]) == 1
    assert len(by_type["seal"]) == 1
    assert sorted(m["index"] for m in by_type["rest_area"]) == [1, 2]
    assert len(by_type["spawn_enemy"]) >= 25 and len(by_type["item"]) >= 12
    assert {m["enemy"] for m in by_type["spawn_enemy"]} <= {
        "longleg",
        "shotgunner",
        "firemage_weak",
    }
    items = {"potion_heal", "potion_mana", "potion_haste", "spell", "wand", "bottle"}
    barrels = {"barrel_gunpowder", "barrel_acid", "barrel_oil"}
    assert {m["item"] for m in by_type["item"]} <= items | barrels
    for m in by_type["item"]:
        if m["item"] == "bottle":  # an empty bottle (a scene's container) has no contents
            assert m.get("contents", "water") in mats.index and m.get("contents") != "acid"
        else:
            assert "contents" not in m
    for m in world_a.markers:
        assert 0 <= m["x"] < 768 and 0 <= m["y"] < 1664
    for m in by_type["spawn_enemy"] + by_type["item"] + by_type["spawn_player"]:
        assert mats.kinds[world_a.grid[m["y"], m["x"]]] in ("air", "gas")


def test_encounter_slots_are_valid_placeholders(world_a, bm):
    slots = [m for m in world_a.markers if m["type"] == "encounter"]
    ids: dict[str, int] = {}
    for m in slots:
        t = m["trigger"]
        assert t["w"] >= 20 and t["h"] >= 20
        assert 0 <= t["x"] and t["x"] + t["w"] <= 768 and 0 <= t["y"] and t["y"] + t["h"] <= 1664
        assert isinstance(m["must_pass"], bool) and isinstance(m["placeholder"], bool)
        if not m["placeholder"]:  # a scene: the footprint is the trigger and the marker says how
            assert m["footprint"]["w"] >= 20 and m["footprint"]["h"] >= 20
            assert set(m["params"]) <= set("ABCDEF") and isinstance(m["mirror"], bool)
        ids[m["encounter_id"]] = ids.get(m["encounter_id"], 0) + 1
    assert max(ids.values()) <= 2
    for layer in (1, 2, 3):
        assert sum(1 for m in slots if m["layer"] == layer and m["must_pass"]) >= 2
    assert sum(1 for m in slots if m["must_pass"]) >= 6
    nodes: dict[str, int] = {}
    for m in slots:
        nodes[node_of(m["encounter_id"])] = nodes.get(node_of(m["encounter_id"]), 0) + 1
    assert all(nodes.get(n, 0) >= 3 for n in BASE_NODES)
    for key, biome in bm.biomes.items():
        optional = [m for m in slots if m["biome"] == key and not m["must_pass"]]
        assert len(optional) == biome.encounters.slots, key


def test_trigger_rectangles_do_not_overlap(world_a):
    rects = [m["trigger"] for m in world_a.markers if m["type"] == "encounter"]
    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            apart = (
                a["x"] + a["w"] <= b["x"]
                or b["x"] + b["w"] <= a["x"]
                or a["y"] + a["h"] <= b["y"]
                or b["y"] + b["h"] <= a["y"]
            )
            assert apart, f"{a} overlaps {b}"


def test_every_biome_has_caves_and_enemies(world_a, bm, mats):
    for key in bm.biomes:
        x0, y0, x1, y1 = bm.region(key)
        cave = (world_a.grid[y0:y1, x0:x1] == mats.air).mean()
        assert 0.15 < cave < 0.65, f"{key}: {cave:.2f}"
        n = sum(
            1
            for m in world_a.markers
            if m["type"] == "spawn_enemy" and x0 <= m["x"] < x1 and y0 <= m["y"] < y1
        )
        assert n >= 2, key


def test_global_scenes_are_in_place(world_a, bm, mats):
    start = next(m for m in world_a.markers if m["type"] == "spawn_player")
    assert start["y"] < 128
    rests = [m for m in world_a.markers if m["type"] == "rest_area"]
    assert [(r["y"] // 128) for r in rests] == [4, 8]
    seal = next(m for m in world_a.markers if m["type"] == "seal")
    plug = world_a.grid[seal["y"] : seal["y"] + seal["h"], seal["x"] : seal["x"] + seal["w"]]
    assert (plug == mats["brick"]).all()
    room = seal["room"]
    assert (
        world_a.grid[room["y"] : room["y"] + room["h"], room["x"] : room["x"] + room["w"]]
        == mats.air
    ).mean() > 0.9
    assert room["y"] >= 1536


def test_meta_records_the_attempt_and_checks(world_a):
    assert world_a.meta["generator"] == "noitabench.worldgen"
    assert 0 <= world_a.meta["attempt"] < MAX_ATTEMPTS
    assert world_a.meta["checks"]["natural_connected"] in (True, False)
    assert len(world_a.meta["main_path"]) > 50


def test_failed_attempts_are_re_rolled_with_a_sub_seed_and_stay_deterministic(monkeypatch):
    real_build, real_checks = generate._build, generate.run_checks
    attempts: list[int] = []

    def flaky_build(*args):  # (seed, sub, rule_seed, attempt, bm, mats, ctx)
        attempt = args[3]
        attempts.append(attempt)
        if attempt == 0:
            raise GenerationFailure("synthetic structural failure")
        return real_build(*args)

    def picky_checks(world, bm=None, mats=None, rules=None):
        rep = real_checks(world, bm, mats, rules)
        if world.meta["attempt"] == 1:
            rep.failures.append("synthetic check failure")
        return rep

    monkeypatch.setattr(generate, "_build", flaky_build)
    monkeypatch.setattr(generate, "run_checks", picky_checks)
    # Seed 2: its attempt 2 passes the real checks. Seed 3's attempt 2 fails the mixing check
    # since the scenes of batch G1 moved the layouts, so it would need a fourth attempt.
    first = generate_world(2)
    second = generate_world(2)
    assert attempts == [0, 1, 2, 0, 1, 2]
    assert first.meta["attempt"] == 2 and first.json_text() == second.json_text()


def test_giving_up_reports_every_attempt(monkeypatch):
    def always_fails(*args):
        raise GenerationFailure("never works")

    monkeypatch.setattr(generate, "_build", always_fails)
    with pytest.raises(RuntimeError, match="no valid world in 3 attempts") as err:
        generate_world(3, max_attempts=3)
    assert err.value.args[0].count("never works") == 3


@pytest.mark.parametrize("seed, rule_seed", [(-1, 0), (0, -5), (1 << 64, 0), (0, 1 << 64)])
def test_seeds_outside_u64_are_rejected(seed, rule_seed):
    with pytest.raises(ValueError, match="seed"):
        generate_world(seed, rule_seed)


def test_liquids_and_gas_pockets_are_contained(world_a, mats):
    """Pools and gas pockets are placed in closed containers: nothing can run out."""
    g = world_a.grid
    air = g == mats.air
    free_below = np.zeros_like(air)
    free_below[:-1] = air[1:]
    free_above = np.zeros_like(air)
    free_above[1:] = air[:-1]
    free_left = np.zeros_like(air)
    free_left[:, 1:] = air[:, :-1]
    free_right = np.zeros_like(air)
    free_right[:, :-1] = air[:, 1:]
    liquid = np.zeros_like(air)
    for key, kind in zip(mats.keys, mats.kinds):
        if kind == "liquid":  # the healing pools of the rest halls included
            liquid |= g == mats[key]
    gas = g == mats["flammable_gas"]
    assert liquid.sum() > 1000 and gas.sum() > 300
    assert not (liquid & (free_below | free_left | free_right)).any()
    assert not (gas & (free_above | free_left | free_right)).any()


def test_spawns_and_items_stand_on_ground_with_room_above(world_a, mats):
    g = world_a.grid
    for m in world_a.markers:
        if m["type"] not in ("spawn_player", "spawn_enemy", "item"):
            continue
        x, y = m["x"], m["y"]
        assert mats.kind_at_least(g[y + 1, x], "powder"), (m, mats.keys[g[y + 1, x]])
        if m["type"] == "spawn_enemy":  # the enemy's collision box stands free on the floor
            h = min(
                ENEMY_HEIGHT[m["enemy"]], 14
            )  # (a scene's enemy has all its height: the loader checks)
            assert (g[y - h + 1 : y + 1, x] == mats.air).all(), m


def test_main_path_runs_from_the_start_to_the_seal_front(world_a):
    start = next(m for m in world_a.markers if m["type"] == "spawn_player")
    front = next(m for m in world_a.markers if m["type"] == "encounter" and m["biome"] == "seal")
    path = world_a.meta["main_path"]
    t = front["trigger"]
    assert abs(path[0][0] - start["x"]) <= 4 and abs(path[0][1] - start["y"]) <= 4
    assert t["x"] <= path[-1][0] < t["x"] + t["w"] and t["y"] <= path[-1][1] < t["y"] + t["h"]


def test_load_world_rejects_broken_files(world_a, mats, tmp_path):
    png, js = world_a.write(tmp_path, "w", mats)
    bad_format = tmp_path / "bad_format.json"
    bad_format.write_text(js.read_text().replace("cogbench-world/0", "cogbench-world/9"))
    with pytest.raises(ValueError, match="format"):
        load_world(png, bad_format)
    data = json.loads(js.read_text())
    del data["markers"]
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="markers"):
        load_world(png, missing)
    data = json.loads(js.read_text())
    data["width"] = 100
    wrong = tmp_path / "wrong_size.json"
    wrong.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="size"):
        load_world(png, wrong)
    rgb = tmp_path / "rgb.png"
    Image.new("RGB", (768, 1664)).save(rgb)
    with pytest.raises(ValueError, match="indexed"):
        load_world(rgb, js)
    with pytest.raises(ValueError, match="cannot read"):
        load_world(png, tmp_path / "nope.json")


def test_there_is_no_free_acid_and_the_barrels_hold_it(world_a, mats):
    """Acid only comes from barrels (cp1-feedback section 1) and from the brick vats of scenes."""
    acid = world_a.grid == mats["acid"]
    assert not (acid & ~acid_allowed_mask(world_a)).any()
    barrels = [
        m for m in world_a.markers if m["type"] == "item" and m["item"].startswith("barrel_")
    ]
    kinds = {m["item"] for m in barrels}
    assert kinds == {"barrel_acid", "barrel_oil", "barrel_gunpowder"}
    for m in barrels:
        assert mats.kinds[world_a.grid[m["y"], m["x"]]] in ("air", "gas")  # a free cell...
        assert mats.kind_at_least(world_a.grid[m["y"] + 1, m["x"]], "powder")  # ...on the floor


def test_the_workshop_is_the_barrel_biome(world_a, bm):
    x0, y0, x1, y1 = bm.region("workshop")
    inside = [
        m
        for m in world_a.markers
        if m["type"] == "item"
        and m["item"].startswith("barrel_")
        and x0 <= m["x"] < x1
        and y0 <= m["y"] < y1
    ]
    assert len(inside) >= 20
    assert {m["item"] for m in inside} == {"barrel_acid", "barrel_oil", "barrel_gunpowder"}
    elsewhere = [
        m for m in world_a.markers if m["type"] == "item" and m["item"].startswith("barrel_")
    ]
    assert 0 < len(elsewhere) - len(inside) < len(inside)  # a few elsewhere


def test_rest_areas_are_small_halls_in_solid_rock(world_a, bm, mats):
    for r in (m for m in world_a.markers if m["type"] == "rest_area"):
        # small halls, not the old 740 x 100 boxes (352 wide: 264 for the slots and the pool, and a
        # nook for the alchemy bowl at each end)
        assert r["w"] <= 360 and r["h"] <= 70
        band = world_a.grid[r["y"] // 128 * 128 : r["y"] // 128 * 128 + 128]
        open_cells = int((band == mats.air).sum())
        assert open_cells < 0.25 * band.size  # the rest of the band is rock (one way in, one out)
        hall = world_a.grid[r["y"] : r["y"] + r["h"], r["x"] : r["x"] + r["w"]]
        assert (hall == mats["brick"]).any()  # pillars
        assert (world_a.grid == mats["potion_heal"]).any()


def test_meta_counts_what_was_built(world_a):
    built = world_a.meta["built"]
    assert set(built) >= {"mine", "fungal", "oil_cave", "sand_cave", "lava_deeps", "workshop"}
    assert built["fungal"]["mushrooms"] > 0 and built["oil_cave"]["seams"] > 0
    assert built["workshop"]["barrels"] > 0 and built["sand_cave"]["sand_pocket"] > 0
    assert world_a.meta["checks"]["barrels"].keys() == {
        "barrel_gunpowder",
        "barrel_acid",
        "barrel_oil",
    }
