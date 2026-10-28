"""Which wand holds which bolt, and the swap that makes the quick wand shoot."""

from __future__ import annotations

from noitabench.bots.wands import SPARK, arm_for_combat, wand_with
from noitabench.game import Game


def start() -> Game:
    game = Game(100, 80, 1)
    game.fill_rect(0, 60, 100, 20, "rock")
    game.spawn_player(20, 59)
    game.step(3)
    return game


def test_wands_are_found_by_their_spell() -> None:
    p = start().player()
    assert p is not None
    assert wand_with(p, "LIGHT_BULLET") == 0 and wand_with(p, "DIGGER") == 1
    assert wand_with(p, "BOMB", default=7) == 7


def test_arming_gives_the_quick_wand_the_spark_bolt() -> None:
    game = start()
    before = game.player()
    assert before is not None
    assert arm_for_combat(game) is True
    p = game.player()
    assert p is not None
    assert wand_with(p, SPARK) == 1 and wand_with(p, "DIGGER") == 0
    assert p["spells"] == []  # nothing left in the inventory
    quick, slow = p["wands"][1]["stats"], p["wands"][0]["stats"]
    assert quick["cast_delay"] + quick["recharge"] < slow["cast_delay"] + slow["recharge"]
    assert arm_for_combat(game) is False  # already armed: nothing to swap


def test_the_swapped_wand_shoots_faster() -> None:
    def casts(arm: bool) -> int:
        game = start()
        if arm:
            arm_for_combat(game)
        p = game.player()
        assert p is not None
        game.step(120, {"fire": True, "aim": 0.0, "select_wand": wand_with(p, SPARK)})
        return sum(
            1 for e in game.events() if e["type"] == "cast" and "LIGHT_BULLET" in e["spells"]
        )

    assert casts(True) >= 2 * casts(False)
