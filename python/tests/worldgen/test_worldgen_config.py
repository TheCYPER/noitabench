"""Content files: biome map and biome definitions (config.py)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from noitabench.worldgen.config import CONTENT_DIR, load_biome_map, load_materials


def test_biome_map_is_6_by_13_cells_of_128_pixels(bm):
    assert (bm.cols, bm.rows, bm.cell_size) == (6, 13, 128)
    assert (bm.width, bm.height) == (768, 1664)
    assert len(bm.cells) == 13 and all(len(r) == 6 for r in bm.cells)


def test_nine_biomes_three_per_layer_and_global_scenes(bm):
    assert len(bm.biomes) == 9
    assert [(l.layer, l.left, l.mid, l.right) for l in bm.layers] == [
        (1, "coal_pit", "mine", "sand_cave"),
        (2, "fungal", "swamp", "oil_cave"),
        (3, "workshop", "lava_deeps", "brick_ruins"),
    ]
    assert bm.region("start") == (0, 0, 768, 128)
    assert bm.region("rest_1") == (0, 512, 768, 640)
    assert bm.region("rest_2") == (0, 1024, 768, 1152)
    assert bm.region("seal") == (0, 1536, 768, 1664)
    for key in bm.biomes:
        x0, y0, x1, y1 = bm.region(key)
        assert (x1 - x0, y1 - y0) == (256, 384)


def test_every_biome_references_known_materials_and_encounters(bm, mats):
    ids = {f"E{i:02d}" for i in range(1, 25)}
    for b in bm.biomes.values():
        for e in b.fill.materials:
            assert e.material in mats.index
        assert set(b.encounters.pool) <= ids
        if b.layout == "tiles":
            assert b.tile.tunnel_min >= 8  # the player (4 x 7) must fit
        else:
            assert b.rooms.door_w >= 8 and b.rooms.door_h >= 8
    for lay in bm.layers:
        assert set(lay.must_pass) <= ids and len(lay.must_pass) >= 2


def test_materials_match_the_contract(mats):
    assert mats.keys[0] == "air" and len(mats) >= 22  # materials are only ever appended
    assert len(mats.palette()) == 768
    assert mats.kind_code.shape == (len(mats),)


def _copy_content(tmp_path: Path) -> Path:
    dst = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, dst)
    return dst


def test_unknown_material_in_a_biome_is_rejected_with_a_clear_message(tmp_path):
    dst = _copy_content(tmp_path)
    path = dst / "biomes" / "mine.json"
    data = json.loads(path.read_text())
    data["fill"]["materials"][0]["material"] = "unobtainium"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unobtainium"):
        load_biome_map(dst)


def test_tunnels_narrower_than_the_player_are_rejected(tmp_path):
    dst = _copy_content(tmp_path)
    path = dst / "biomes" / "mine.json"
    data = json.loads(path.read_text())
    data["tile"]["tunnel_width"] = [4, 12]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="tunnel_width"):
        load_biome_map(dst)


def test_a_broken_biome_map_is_rejected(tmp_path):
    dst = _copy_content(tmp_path)
    path = dst / "biome_map.json"
    data = json.loads(path.read_text())
    data["cells"][2][2] = "swamp"  # a hole in the mine rectangle
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="rectangle|match"):
        load_biome_map(dst)


def test_missing_file_names_the_file(tmp_path):
    with pytest.raises(ValueError, match="biome_map.json"):
        load_biome_map(tmp_path)


def test_materials_loader_rejects_a_bad_index(tmp_path):
    bad = tmp_path / "materials.json"
    bad.write_text(
        json.dumps({"materials": [{"index": 1, "key": "air", "kind": "air", "color": "#000000"}]})
    )
    with pytest.raises(ValueError, match="index"):
        load_materials(bad)


def _edit_biome(tmp_path: Path, name: str, edit) -> Path:
    dst = _copy_content(tmp_path)
    path = dst / "biomes" / f"{name}.json"
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))
    return dst


def test_a_missing_field_names_the_file_and_the_field(tmp_path):
    dst = _edit_biome(tmp_path, "mine", lambda d: d["tile"].pop("short_side"))
    with pytest.raises(ValueError, match=r"mine\.json.*short_side"):
        load_biome_map(dst)


def test_enemy_and_item_keys_must_be_in_the_contract(tmp_path):
    dst = _edit_biome(tmp_path, "mine", lambda d: d["markers"]["enemies"][0].update(enemy="boss"))
    with pytest.raises(ValueError, match=r"mine\.json.*markers\.enemies.*boss"):
        load_biome_map(dst)
    dst = _edit_biome(
        tmp_path / "b", "mine", lambda d: d["markers"]["items"][0].update(item="sword")
    )
    with pytest.raises(ValueError, match=r"markers\.items.*sword"):
        load_biome_map(dst)


def test_a_bottle_needs_contents_and_contents_must_be_a_material(tmp_path):
    def no_contents(d):
        bottle = next(i for i in d["markers"]["items"] if i["item"] == "bottle")
        del bottle["contents"]

    with pytest.raises(ValueError, match=r"'bottle' needs 'contents'"):
        load_biome_map(_edit_biome(tmp_path / "a", "mine", no_contents))

    def bad_contents(d):
        bottle = next(i for i in d["markers"]["items"] if i["item"] == "bottle")
        bottle["contents"] = "mercury"

    with pytest.raises(ValueError, match="mercury"):
        load_biome_map(_edit_biome(tmp_path / "b", "mine", bad_contents))


def test_unknown_encounter_ids_are_rejected(tmp_path):
    dst = _edit_biome(tmp_path, "mine", lambda d: d["encounters"]["pool"].append("E99"))
    with pytest.raises(ValueError, match=r"encounters\.pool.*E99"):
        load_biome_map(dst)


def test_a_biome_file_must_match_its_name_and_its_place_in_the_map(tmp_path):
    dst = _edit_biome(tmp_path, "mine", lambda d: d.update(key="cellar"))
    with pytest.raises(ValueError, match=r"'key'"):
        load_biome_map(dst)
    dst = _edit_biome(tmp_path / "b", "mine", lambda d: d.update(slot="left"))
    with pytest.raises(ValueError, match="slot=left"):
        load_biome_map(dst)


def test_scene_rows_must_match_the_cells(tmp_path):
    dst = _copy_content(tmp_path)
    path = dst / "biome_map.json"
    data = json.loads(path.read_text())
    data["scenes"]["seal"]["row"] = 11
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=r"scenes\.seal\.row"):
        load_biome_map(dst)
    data["scenes"]["seal"]["row"] = 12
    del data["scenes"]["bands"]["wave"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=r"scenes\.bands\.wave"):
        load_biome_map(dst)


def test_the_seam_thickness_is_a_small_integer(tmp_path, bm):
    """Brick seams and shells need 2 cells at least and fit the ring of a region (``ring`` 6)."""
    assert 2 <= bm.scenes["bands"]["seam"] <= bm.ring
    dst = _copy_content(tmp_path)
    path = dst / "biome_map.json"
    data = json.loads(path.read_text())
    for bad in (1, bm.ring + 1, "4", 2.5):
        data["scenes"]["bands"]["seam"] = bad
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match=r"scenes\.bands\.seam"):
            load_biome_map(dst)
    del data["scenes"]["bands"]["seam"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=r"scenes\.bands\.seam"):
        load_biome_map(dst)


def test_a_layer_needs_two_known_must_pass_ids(tmp_path):
    dst = _copy_content(tmp_path)
    path = dst / "biome_map.json"
    data = json.loads(path.read_text())
    data["layers"][0]["must_pass"] = ["E16"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="must_pass"):
        load_biome_map(dst)


def test_materials_loader_rejects_bad_colours_and_duplicates(tmp_path):
    def rows(*extra):
        base = [{"index": 0, "key": "air", "kind": "air", "color": "#000000"}]
        return {"materials": base + list(extra)}

    bad = tmp_path / "color.json"
    bad.write_text(json.dumps(rows({"index": 1, "key": "x", "kind": "static", "color": "#12345g"})))
    with pytest.raises(ValueError, match="color"):
        load_materials(bad)
    dup = tmp_path / "dup.json"
    dup.write_text(
        json.dumps(rows({"index": 1, "key": "air", "kind": "static", "color": "#111111"}))
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_materials(dup)


def test_acid_cannot_lie_around_in_pools_or_bottles(tmp_path):
    def acid_pool(d):
        d["features"]["pools"]["liquids"].append({"material": "acid", "weight": 1})

    with pytest.raises(ValueError, match=r"features\.pools\.liquids.*acid"):
        load_biome_map(_edit_biome(tmp_path / "a", "mine", acid_pool))

    def acid_bottle(d):
        bottle = next(i for i in d["markers"]["items"] if i["item"] == "bottle")
        bottle["contents"] = "acid"

    with pytest.raises(ValueError, match=r"markers\.items.*acid"):
        load_biome_map(_edit_biome(tmp_path / "b", "mine", acid_bottle))


def test_barrels_are_item_keys_without_contents(bm):
    listed = {it.key for b in bm.biomes.values() for it in b.markers.items}
    assert {"barrel_gunpowder", "barrel_acid", "barrel_oil"} <= listed
    workshop = bm.biomes["workshop"]
    assert workshop.layout == "rooms" and workshop.tile is None and workshop.rooms is not None
    assert set(workshop.decor["barrel_rows"]["weights"]) == {
        "barrel_gunpowder",
        "barrel_acid",
        "barrel_oil",
    }
    assert all(it.extra == "" for it in workshop.markers.items if it.key.startswith("barrel_"))


def test_room_structures_need_the_rooms_layout(tmp_path):
    dst = _edit_biome(
        tmp_path, "mine", lambda d: d.setdefault("decor", {}).update(pillars={"per_room": [1, 2]})
    )
    with pytest.raises(ValueError, match=r"decor\.pillars.*rooms"):
        load_biome_map(dst)


def test_unknown_decor_hazard_and_barrel_keys_are_rejected(tmp_path):
    dst = _edit_biome(tmp_path / "a", "mine", lambda d: d["decor"].update(fountains={"per_10k": 1}))
    with pytest.raises(ValueError, match=r"decor\.fountains"):
        load_biome_map(dst)
    dst = _edit_biome(
        tmp_path / "b", "mine", lambda d: d["hazards"].update(quicksand={"per_10k": 1})
    )
    with pytest.raises(ValueError, match=r"hazards\.quicksand"):
        load_biome_map(dst)

    def bad_barrel(d):
        d["decor"]["barrel_rows"]["weights"]["barrel_water"] = 1.0

    with pytest.raises(ValueError, match="barrel_water"):
        load_biome_map(_edit_biome(tmp_path / "c", "workshop", bad_barrel))


def test_layout_and_tile_must_agree(tmp_path):
    dst = _edit_biome(tmp_path / "a", "workshop", lambda d: d.pop("rooms"))
    with pytest.raises(ValueError, match="rooms"):
        load_biome_map(dst)
    dst = _edit_biome(tmp_path / "b", "workshop", lambda d: d.update(layout="blobs"))
    with pytest.raises(ValueError, match="layout"):
        load_biome_map(dst)


def test_doors_must_fit_the_player(tmp_path):
    dst = _edit_biome(tmp_path, "workshop", lambda d: d["rooms"].update(door_h=5))
    with pytest.raises(ValueError, match="rooms.door_w"):
        load_biome_map(dst)


def test_the_rest_hall_must_hold_the_slots_and_fit_its_band(tmp_path):
    dst = _copy_content(tmp_path)
    path = dst / "biome_map.json"
    data = json.loads(path.read_text())
    data["scenes"]["rest"]["hall"]["x"] = [300, 420]  # too narrow for two 84-wide slots
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=r"scenes\.rest\.hall"):
        load_biome_map(dst)
    data["scenes"]["rest"]["hall"]["x"] = [252, 516]
    data["scenes"]["rest"]["hall"]["top"] = 80  # runs out of the 128-cell band
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=r"scenes\.rest\.hall\.top"):
        load_biome_map(dst)
