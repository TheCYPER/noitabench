"""The Python `Game` wrapper: stepping, controls, views, scene building, snapshots."""

from __future__ import annotations

import pytest
from noitabench.game import Game, aim_at

W, H, FLOOR = 300, 160, 30
GROUND = H - FLOOR - 1  # the row a creature stands in


def make(seed: int = 1, x: int = 60) -> Game:
    game = Game(W, H, seed)
    game.fill_rect(0, H - FLOOR, W, FLOOR, "rock")
    game.spawn_player(x, GROUND)
    game.step(61)  # lands, and the opening invincibility ends
    game.events()
    return game


def test_the_player_view_has_the_documented_fields() -> None:
    p = make().player()
    assert p is not None
    keys = [
        "id", "x", "y", "w", "h", "hit", "vx", "vy", "hp", "hp_max", "dead", "facing",
        "on_ground", "fly", "breath", "invincible", "aim", "active_wand", "active_bottle",
        "wands", "spells", "bottles", "statuses",
    ]  # fmt: skip
    for key in keys:
        assert key in p, key
    assert (p["w"], p["h"]) == (4, 7) and p["hit"][2:] == (6, 16)
    assert p["hp"] == p["hp_max"] == 100.0
    assert p["on_ground"] and p["fly"] == 1.0 and p["breath"] == 1.0
    spark, digger = p["wands"]
    assert [s["spell"] for s in spark["slots"] if s] == ["LIGHT_BULLET"]
    assert [s["spell"] for s in digger["slots"] if s] == ["DIGGER"]
    assert spark["stats"]["capacity"] == 3 and spark["mana"] == spark["mana_max"]


def test_no_player_before_spawning() -> None:
    game = Game(40, 40, 1)
    assert game.player() is None and game.entities() == []
    game.step(5)  # nothing to simulate but the world


def test_controls_move_the_player_and_unknown_controls_are_refused() -> None:
    game = make()
    x0 = game.player()["x"]
    game.step(30, {"move": 1})
    assert game.player()["x"] > x0 + 20
    with pytest.raises(ValueError, match="unknown control `walk`"):
        game.step(1, {"walk": 1})
    with pytest.raises(ValueError, match="move"):
        game.step(1, {"move": 2})
    with pytest.raises(ValueError, match="jump"):
        game.step(1, {"jump": "yes"})
    with pytest.raises(ValueError, match="dict"):
        game.step(1, 5)  # type: ignore[arg-type]


def test_a_list_of_controls_has_one_dict_per_frame() -> None:
    game = make()
    x0 = game.player()["x"]
    game.step(4, [{"move": 1}, {"move": 1}, {}, {"move": -1}])
    assert game.player()["x"] >= x0
    with pytest.raises(ValueError, match="3 control dicts for 4 frames"):
        game.step(4, [{}, {}, {}])


def test_jump_is_edge_triggered_and_fly_drains_the_meter() -> None:
    game = make()
    y0 = game.player()["y"]
    game.step(1, {"jump": True})
    game.step(6, {"jump": True})
    assert game.player()["y"] < y0
    game.step(80)
    assert game.player()["y"] == y0 and game.player()["on_ground"]
    game.step(30, {"fly": True})
    assert game.player()["fly"] < 0.9


def test_aim_at_points_from_one_cell_to_another() -> None:
    assert aim_at((0, 0), (10, 0)) == pytest.approx(0)
    assert aim_at((0, 0), (0, -10)) == pytest.approx(90)  # up
    assert aim_at((0, 0), (0, 10)) == pytest.approx(-90)  # down
    assert aim_at((5, 5), (-5, 5)) == pytest.approx(180)


def test_spawn_items_of_every_kind() -> None:
    game = make()
    y = GROUND
    ids = [
        game.spawn_item("bottle", 100, y, material="oil"),
        game.spawn_item("potion_heal", 110, y),
        game.spawn_item("wand", 120, y, tier=3),
        game.spawn_item("spell", 130, y),
        game.spawn_item("spell", 140, y, spell="BOMB"),
        game.spawn_item("barrel_acid", 150, y),
        game.spawn_item(
            "wand",
            160,
            y,
            stats={
                "cast_delay": 5,
                "recharge": 5,
                "mana_max": 50.0,
                "mana_charge_speed": 10.0,
                "capacity": 2,
            },
            spells=["BOMB", None],
        ),
    ]
    assert len(set(ids)) == len(ids)
    by_id = {e["id"]: e for e in game.entities()}
    assert by_id[ids[0]]["kind"] == "bottle" and by_id[ids[0]]["detail"] == "oil"
    assert by_id[ids[1]]["detail"] == "potion_heal"
    assert by_id[ids[4]]["detail"] == "BOMB"
    assert by_id[ids[5]]["kind"] == "barrel_acid" and by_id[ids[5]]["hp"] == pytest.approx(5.0)
    assert by_id[ids[6]]["kind"] == "wand"


def test_bad_spawns_raise_value_errors_that_say_what_is_allowed() -> None:
    game = make()
    with pytest.raises(ValueError, match="dragon"):
        game.spawn_enemy("dragon", 100, GROUND)
    with pytest.raises(ValueError, match="unknown item"):
        game.spawn_item("sword", 100, GROUND)
    with pytest.raises(ValueError, match="outside"):
        game.spawn_enemy("longleg", 9999, GROUND)
    with pytest.raises(ValueError, match="already a player"):
        game.spawn_player(10, GROUND)
    with pytest.raises(ValueError, match="need `cast_delay`"):
        game.give_wand({"capacity": 1}, ["BOMB"])
    with pytest.raises(ValueError, match="NOPE"):
        game.give_spell("NOPE")


def test_wand_editor_actions() -> None:
    game = make()
    game.give_spell("DAMAGE")
    game.edit_wand({"op": "place", "wand": 0, "slot": 1, "from": 0})
    slots = game.player()["wands"][0]["slots"]
    assert slots[1]["spell"] == "DAMAGE" and game.player()["spells"] == []
    game.edit_wand({"op": "swap", "wand": 0, "a": 0, "b": 1})
    assert game.player()["wands"][0]["slots"][0]["spell"] == "DAMAGE"
    game.edit_wand({"op": "take", "wand": 0, "slot": 0})
    assert [s["spell"] for s in game.player()["spells"]] == ["DAMAGE"]
    with pytest.raises(ValueError, match="unknown wand edit"):
        game.edit_wand({"op": "melt", "wand": 0})
    with pytest.raises(ValueError, match="needs `slot`"):
        game.edit_wand({"op": "take", "wand": 0})


def script(game: Game, frames: int) -> None:
    for f in range(frames):
        game.step(
            1,
            {
                "move": (1, 1, 0, -1)[(f // 20) % 4],
                "jump": f % 50 == 0,
                "fire": f % 30 < 10,
                "aim": float(f % 60) - 10,
                "select_wand": (f // 100) % 2,
                "kick": f % 70 == 35,
            },
        )


def scene(seed: int) -> Game:
    game = make(seed)
    game.spawn_enemy("longleg", 150, GROUND)
    game.spawn_enemy("shotgunner", 220, GROUND)
    game.spawn_item("barrel_gunpowder", 100, GROUND)
    game.spawn_item("barrel_oil", 120, GROUND)
    return game


def test_same_seed_and_controls_give_the_same_game() -> None:
    a, b = scene(5), scene(5)
    script(a, 300)
    script(b, 300)
    assert a.state_hash() == b.state_hash()
    assert a.events() == b.events()
    c = scene(6)
    script(c, 300)
    assert c.state_hash() != a.state_hash()


def test_snapshots_restore_the_game_exactly() -> None:
    game = scene(5)
    script(game, 100)
    game.events()
    blob = game.snapshot()
    h = game.state_hash()
    script(game, 200)
    end, events = game.state_hash(), game.events()
    game.restore(blob)
    assert game.state_hash() == h
    game.events()
    script(game, 200)
    assert (game.state_hash(), game.events()) == (end, events)
    with pytest.raises(ValueError, match="snapshot"):
        game.restore(b"garbage")


def test_events_carry_floats_and_ints_in_display_units() -> None:
    game = make()
    game.blast(60, GROUND - 3, 6, damage=3.0, ray_energy=1000, max_durability=4, fire_percent=0)
    events = game.events()
    damage = next(e for e in events if e["type"] == "damage")
    assert damage["target"] == "player" and damage["source"] == "explosion"
    assert damage["amount"] == pytest.approx(3.0 * 0.35 * 25)  # the explosion multiplier of 0.35
    assert damage["hp"] == pytest.approx(100 - damage["amount"])
    assert isinstance(damage["id"], int)


def test_world_helpers_work_on_a_game() -> None:
    game = make()
    assert game.cell(5, H - 2)["material"] == "rock"
    assert game.overlap(0, H - FLOOR, W, FLOOR)["materials"] == {"rock": W * FLOOR}
    hit = game.raycast(60, GROUND, 60, H + 5)
    assert hit is not None and hit["y"] == H - FLOOR
    sweep = game.sweep_box(10, GROUND - 6, 4, 7, 0, 5)
    assert sweep["blocked_y"] == "rock"
    assert game.contact_damage(0, 0, 10, 10)["raw"] == 0
    assert len(game.grid()) == W * H and game.grid_array().shape == (H, W)
    assert game.width == W and game.height == H and game.frame == 61
    assert "rock" in game.material_keys() and len(game.spell_keys()) == 25
    assert game.enemy_kinds() == ["firemage_weak", "longleg", "shotgunner"]
    with pytest.raises(ValueError):
        game.cell(-1, 0)
