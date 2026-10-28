"""The eight secret potions through the Python `Game`: drinking, the statuses an agent sees, and
the seal key staying out of random loot."""

from __future__ import annotations

import pytest
from noitabench.game import Game

W, H, FLOOR = 300, 160, 30
GROUND = H - FLOOR - 1

SECRET = {
    "potion_lively": "regeneration",
    "potion_invulnerable": "invulnerable",
    "potion_mana_regen": "mana_regen",
    "potion_crit": "crit_boost",
    "potion_berserk": "berserk",
    "potion_levitation": "levitation",
    "potion_invisible": "invisible",
    "potion_fireproof": "fireproof",
}


def make() -> Game:
    game = Game(W, H, 1)
    game.fill_rect(0, H - FLOOR, W, FLOOR, "rock")
    game.spawn_player(60, GROUND)
    game.step(61)
    game.events()
    return game


@pytest.mark.parametrize(("potion", "status"), SECRET.items())
def test_drinking_a_secret_potion_gives_its_status(potion: str, status: str) -> None:
    game = make()
    assert game.player()["statuses"] == {}
    game.give_bottle(potion, 100)
    game.step(12, {"drink": True, "select_bottle": 0})
    statuses = game.player()["statuses"]
    assert status in statuses and statuses[status] > 60, statuses
    assert game.player()["bottles"][0]["amount"] == 0
    assert any(e["type"] == "status" and e["status"] == status for e in game.events())


FULL_BOTTLE_FRAMES = {
    "potion_lively": 400,
    "potion_invulnerable": 600,
    "potion_mana_regen": 1200,
    "potion_crit": 900,
    "potion_berserk": 900,
    "potion_levitation": 600,
    "potion_invisible": 600,
    "potion_fireproof": 900,
}


@pytest.mark.parametrize(("potion", "frames"), FULL_BOTTLE_FRAMES.items())
def test_a_full_bottle_lasts_exactly_the_designed_time(potion: str, frames: int) -> None:
    game = make()
    status = SECRET[potion]
    game.give_bottle(potion, 400)
    elapsed = 0
    while game.player()["bottles"][0]["amount"] > 0:
        game.step(1, {"drink": True, "select_bottle": 0})
        elapsed += 1
    while status in game.player()["statuses"]:
        game.step(1)
        elapsed += 1
    assert elapsed == frames


def test_a_secret_potion_can_be_spawned_for_a_scene() -> None:
    game = make()
    game.spawn_item("potion_crit", 66, GROUND)
    kinds = [e["kind"] for e in game.entities()]
    assert "potion_crit" in kinds
    game.step(5)
    game.step(1, {"interact": True})
    game.step(1)
    game.step(1, {"interact": True})
    bottles = game.player()["bottles"]
    assert bottles and bottles[0]["material"] == "potion_crit"


def test_random_spell_pickups_never_hold_the_seal_key() -> None:
    game = Game(1200, 60, 3)
    game.fill_rect(0, 50, 1200, 10, "rock")
    seen = set()
    for i in range(1500):
        game.spawn_item("spell", 5 + i % 1100, 49)
    seen = {e["detail"] for e in game.entities() if e["kind"] == "spell"}
    assert "EXPLOSIVE_PROJECTILE" not in seen
    assert {"BOMB", "DAMAGE"} <= seen
    # placed by hand it is still there
    game.spawn_item("spell", 10, 49, spell="EXPLOSIVE_PROJECTILE")
    assert any(e["detail"] == "EXPLOSIVE_PROJECTILE" for e in game.entities())
