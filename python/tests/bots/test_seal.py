"""The seal: its geometry, the key item convention, and what can open it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mini_world import ROOM, SEAL_THICK, SEAL_TOP, SEAL_W, SEAL_X, patched_spells, write_world
from noitabench.bots.seal import (
    SealGeometry,
    SealKey,
    breaker_spell,
    equip_spell,
    explosion_durability,
    find_seal_key,
    find_seal_keys,
    is_key_marker,
)
from noitabench.bots.terrain import CONTENT, Body, Materials
from noitabench.game import Game


def game_and_geometry(tmp_path: Path, mats: Materials) -> tuple[Game, SealGeometry, dict]:
    files = write_world(tmp_path, mats)
    game = Game.from_world(files.png, files.json)
    marker = next(m for m in game.markers() if m["type"] == "seal")
    return game, SealGeometry.read(game.grid_array(), mats, marker), marker


def test_the_plug_is_the_brick_between_the_hall_and_the_room(tmp_path: Path, mats) -> None:
    _, geometry, _ = game_and_geometry(tmp_path, mats)
    p = geometry.plug
    assert (p.x, p.y, p.w, p.h) == (SEAL_X, SEAL_TOP, SEAL_W, SEAL_THICK)
    assert (geometry.room.y, geometry.room.h) == (ROOM["y"], ROOM["h"])
    assert p.cx == SEAL_X + SEAL_W // 2 and p.bottom == SEAL_TOP + SEAL_THICK


def test_a_channel_as_wide_as_the_player_opens_the_seal(tmp_path: Path, mats) -> None:
    game, geometry, _ = game_and_geometry(tmp_path, mats)
    body = Body.load()
    assert not geometry.is_open(game.grid_array(), mats, body.w)
    game.fill_rect(SEAL_X + 2, SEAL_TOP, body.w - 1, SEAL_THICK, "air")  # one cell too narrow
    assert not geometry.is_open(game.grid_array(), mats, body.w)
    game.fill_rect(SEAL_X + 2, SEAL_TOP, body.w, SEAL_THICK, "air")
    assert geometry.is_open(game.grid_array(), mats, body.w)


def test_a_marker_with_no_brick_under_it_is_an_error(tmp_path: Path, mats) -> None:
    game, _, marker = game_and_geometry(tmp_path, mats)
    game.fill_rect(SEAL_X, SEAL_TOP - 5, SEAL_W, 40, "air")
    with pytest.raises(ValueError, match="no brick"):
        SealGeometry.read(game.grid_array(), mats, marker)


@pytest.mark.parametrize(
    "flags",
    [{"role": "breaker"}, {"role": "seal_key"}, {"key_for": "seal"}, {"seal_key": True}],
)
def test_the_key_item_conventions(flags: dict) -> None:
    marker = {"type": "item", "item": "spell", "spell": "BOMB", "x": 50, "y": 60, **flags}
    assert is_key_marker(marker)
    entities = [
        {"kind": "spell", "x": 49, "y": 55, "w": 6, "h": 6, "detail": "BOMB", "id": 7},
        {"kind": "spell", "x": 300, "y": 55, "w": 6, "h": 6, "detail": "DIGGER", "id": 8},
    ]
    key = find_seal_key([marker], entities)
    assert key is not None and key.kind == "spell" and key.detail == "BOMB"
    assert key.center == (52.0, 58.0)


def test_other_items_and_solvents_are_not_keys() -> None:
    plain = {"type": "item", "item": "spell", "x": 5, "y": 5}
    solvent = {"type": "item", "item": "bottle", "role": "solvent", "x": 5, "y": 5}
    assert not is_key_marker(plain) and not is_key_marker(solvent)
    assert find_seal_key([plain, solvent], []) is None
    key = {"type": "item", "item": "spell", "role": "breaker", "x": 5, "y": 5}
    assert find_seal_key([key], []) is None  # the item is gone from the world


def test_no_spell_of_the_content_breaks_brick(mats: Materials) -> None:
    """Today brick (durability 14) beats every explosion of the 25 spells; the bot's fallback
    exists for that. When this test fails the content changed: the key path is live."""
    brick = int(mats.durability[mats.index("brick")])
    assert brick == 14
    assert explosion_durability("BOMB") == 11
    assert explosion_durability("SPEED") is None  # a modifier has no explosion
    assert explosion_durability("NO_SUCH_SPELL") is None
    bomb = SealKey(
        marker={}, entity={"kind": "spell", "detail": "BOMB", "x": 0, "y": 0, "w": 1, "h": 1}
    )
    assert not bomb.can_open(mats)
    bottle = SealKey(
        marker={}, entity={"kind": "bottle", "detail": "x", "x": 0, "y": 0, "w": 1, "h": 1}
    )
    assert bottle.can_open(mats)  # what a bottle does to brick is not known from outside


def test_a_spell_that_breaks_brick_is_found_in_the_content(tmp_path: Path, mats) -> None:
    assert breaker_spell(mats) is None  # none of the 25 does today
    data = json.loads((CONTENT / "spells.json").read_text())
    for spell in data["spells"]:
        if spell["key"] == "BOMB":
            spell["projectile"]["explosion"]["max_durability"] = 14
    patched = tmp_path / "spells.json"
    patched.write_text(json.dumps(data))
    assert breaker_spell(mats, patched) == "BOMB"
    assert explosion_durability("BOMB", patched) == 14


def test_equipping_a_spell_keeps_the_digging_bolt_in_its_wand(tmp_path: Path, mats) -> None:
    game, _, _ = game_and_geometry(tmp_path, mats)
    game.give_spell("BOMB")
    wand = equip_spell(game, "BOMB")
    p = game.player()
    assert p is not None
    held = [[s["spell"] if s else None for s in w["slots"]] for w in p["wands"]]
    assert held[wand][0] == "BOMB"  # first in the deck: the next click casts it
    spells = {spell for wand_slots in held for spell in wand_slots}
    assert ["DIGGER"] in held and "LIGHT_BULLET" in spells  # nothing was taken out
    assert p["spells"] == []


def test_the_key_is_the_item_the_marker_names_not_just_the_nearest_one() -> None:
    marker = {"type": "item", "item": "spell", "spell": "BOMB", "role": "breaker", "x": 50, "y": 60}
    box = {"x": 49, "y": 59, "w": 6, "h": 6, "id": 1}
    decoys = [  # all nearer to the marker than the real thing
        {"kind": "bottle", "detail": "water", **box},
        {"kind": "wand", "detail": "", **box, "x": 48},
        {"kind": "spell", "detail": "DIGGER", **box, "x": 47},
    ]
    real = {"kind": "spell", "detail": "BOMB", **box, "x": 56, "y": 66}
    key = find_seal_key([marker], [*decoys, real])
    assert key is not None and key.entity is real
    assert find_seal_key([marker], decoys) is None  # without the real one there is no key
    bottle = {
        "type": "item",
        "item": "bottle",
        "contents": "blood",
        "key_for": "seal",
        "x": 5,
        "y": 5,
    }
    blood = {"kind": "bottle", "detail": "blood", "x": 8, "y": 8, "w": 4, "h": 6}
    water = {"kind": "bottle", "detail": "water", "x": 6, "y": 6, "w": 4, "h": 6}
    found = find_seal_key([bottle], [water, blood])
    assert found is not None and found.entity is blood


def test_a_spell_that_is_in_a_wand_already_is_not_equipped_again(tmp_path: Path, mats) -> None:
    game, _, _ = game_and_geometry(tmp_path, mats)
    game.give_spell("BOMB")
    wand = equip_spell(game, "BOMB")
    assert equip_spell(game, "BOMB") == wand  # nothing carried: the wand that holds it
    assert equip_spell(game, "NO_SUCH_SPELL") == 0  # unknown: the first wand


def test_a_world_can_have_several_breaker_items() -> None:
    """The bomb of one encounter and the modifier of another are both keys: all are found, each
    with its own entity, however close they lie to each other."""
    bomb = {"type": "item", "item": "spell", "spell": "BOMB", "role": "breaker", "x": 50, "y": 60}
    boost = {
        "type": "item",
        "item": "spell",
        "spell": "EXPLOSIVE_PROJECTILE",
        "role": "breaker",
        "x": 300,
        "y": 90,
    }
    box = {"w": 6, "h": 6, "kind": "spell"}
    entities = [
        {**box, "id": 1, "x": 296, "y": 88, "detail": "EXPLOSIVE_PROJECTILE"},
        {**box, "id": 2, "x": 52, "y": 58, "detail": "BOMB"},
        {**box, "id": 3, "x": 49, "y": 59, "detail": "DIGGER"},
    ]
    keys = find_seal_keys([bomb, boost], entities)
    assert [(k.detail, k.entity["id"]) for k in keys] == [("BOMB", 2), ("EXPLOSIVE_PROJECTILE", 1)]
    assert find_seal_key([bomb, boost], entities) == keys[0]  # the first one, as before


def test_one_entity_serves_one_marker() -> None:
    twin = {"type": "item", "item": "spell", "spell": "BOMB", "role": "breaker", "y": 60}
    markers = [{**twin, "x": 50}, {**twin, "x": 60}]
    only = {"kind": "spell", "x": 52, "y": 58, "w": 6, "h": 6, "detail": "BOMB", "id": 9}
    assert len(find_seal_keys(markers, [only])) == 1
    other = {**only, "id": 10, "x": 62}
    assert [k.entity["id"] for k in find_seal_keys(markers, [only, other])] == [9, 10]


def test_a_missing_item_leaves_the_other_key() -> None:
    bomb = {"type": "item", "item": "spell", "spell": "BOMB", "role": "breaker", "x": 50, "y": 60}
    boost = {**bomb, "spell": "EXPLOSIVE_PROJECTILE", "x": 300}
    real = {"kind": "spell", "x": 301, "y": 61, "w": 6, "h": 6, "detail": "EXPLOSIVE_PROJECTILE"}
    keys = find_seal_keys([bomb, boost], [{**real, "id": 4}])
    assert [k.detail for k in keys] == ["EXPLOSIVE_PROJECTILE"]


def test_a_spell_key_opens_brick_together_with_the_modifier_in_hand(
    tmp_path: Path, mats: Materials
) -> None:
    """The bomb's own explosion is 11, brick 14: with the modifier of the other key (+3) it is."""
    bomb = SealKey(
        marker={}, entity={"kind": "spell", "detail": "BOMB", "x": 0, "y": 0, "w": 1, "h": 1}
    )
    with_bonus = patched_spells(tmp_path, 3)
    without = patched_spells(tmp_path, None)
    assert not bomb.can_open(mats, with_bonus)
    assert bomb.can_open(mats, with_bonus, held=["EXPLOSIVE_PROJECTILE"])
    assert not bomb.can_open(mats, without, held=["EXPLOSIVE_PROJECTILE"])  # no bonus: counts 0
    assert not bomb.can_open(mats, with_bonus, held=["DIGGER"])
