"""Bottles that hold mixtures, the `drop` control, ground wands, eager bottle events and
`on_ground`, through the Python `Game`."""

from __future__ import annotations

from typing import Any

import pytest
from noitabench.game import Game

W, H, FLOOR = 300, 160, 30
GROUND = H - FLOOR - 1
RECIPE = {"potion": "potion_crit", "inputs": ["water", "blood", "oil"]}


def make(**kwargs: Any) -> Game:
    game = Game(W, H, 1, **kwargs)
    game.fill_rect(0, H - FLOOR, W, FLOOR, "rock")
    game.spawn_player(60, GROUND)
    game.step(61)
    game.events()
    return game


def parts(*pairs: tuple[str, int]) -> list[dict[str, Any]]:
    return [{"material": m, "amount": n} for m, n in pairs]


def kinds(game: Game) -> list[str]:
    return [e["kind"] for e in game.entities()]


# -- the view of a bottle ----------------------------------------------------------------------------


def test_a_bottle_shows_its_largest_share_its_total_and_its_contents() -> None:
    game = make()
    game.give_bottle("oil", 50)
    game.give_bottle()
    game.give_bottle(contents=parts(("oil", 30), ("water", 70), ("blood", 5)))
    one, empty, mixed = game.player()["bottles"]
    assert one == {"material": "oil", "amount": 50, "contents": parts(("oil", 50))}
    assert empty == {"material": None, "amount": 0, "contents": []}
    assert mixed["material"] == "water" and mixed["amount"] == 105
    assert mixed["contents"] == parts(("water", 70), ("blood", 5), ("oil", 30))  # material order


def test_a_mixture_is_checked() -> None:
    game = make()
    with pytest.raises(ValueError, match="holds 400"):
        game.give_bottle(contents=parts(("water", 300), ("oil", 101)))
    with pytest.raises(ValueError, match="mercury"):
        game.give_bottle(contents=parts(("mercury", 1)))
    with pytest.raises(ValueError, match="contents"):
        game.give_bottle(contents=[("water", 5)])  # type: ignore[list-item]


@pytest.mark.parametrize(
    "bad",
    [
        parts(("water", -1)),
        parts(("water", 2**40)),
        [{"material": "water", "amount": 2.5}],
        [{"material": 7, "amount": 5}],
        [{"material": "water"}],
    ],
)
def test_amounts_that_are_not_a_cell_count_are_a_value_error(bad: Any) -> None:
    game = make()
    with pytest.raises(ValueError, match="contents"):
        game.give_bottle(contents=bad)
    assert game.player()["bottles"] == []


def test_amounts_that_would_wrap_around_are_refused() -> None:
    game = make()
    # 2**32 - 1 and 6 add up to 5 in 32 bits, which would fit in a bottle
    with pytest.raises(ValueError, match="holds 400"):
        game.give_bottle(contents=parts(("water", 2**32 - 1), ("oil", 6)))
    with pytest.raises(ValueError, match="holds 400"):
        game.spawn_item("bottle", 90, GROUND, contents=parts(("water", 2**32 - 1), ("oil", 6)))
    assert game.player()["bottles"] == []


def test_a_bottle_on_the_ground_lists_its_contents_and_a_wand_its_stats() -> None:
    game = make()
    bottle = game.spawn_item("bottle", 90, GROUND, contents=parts(("oil", 10), ("water", 20)))
    wand = game.spawn_item("wand", 110, GROUND, tier=2)
    plain = game.spawn_item("bottle", 130, GROUND, material="water", amount=7)
    by_id = {e["id"]: e for e in game.entities()}
    assert by_id[bottle]["kind"] == "bottle" and by_id[bottle]["detail"] == "water"
    assert by_id[bottle]["contents"] == parts(("water", 20), ("oil", 10))
    assert by_id[plain]["contents"] == parts(("water", 7))
    shown = by_id[wand]["wand"]
    mine = game.player()["wands"][0]
    assert set(shown) == set(mine) and shown["stats"]["capacity"] >= 1
    assert "contents" not in by_id[wand] and "wand" not in by_id[bottle]
    # a pile of potion is listed under the potion's key
    potion = game.spawn_item("bottle", 150, GROUND, contents=parts(("potion_heal", 10)))
    assert {e["id"]: e for e in game.entities()}[potion]["kind"] == "potion_heal"


# -- recipes inside a bottle -------------------------------------------------------------------------


def test_a_bottle_with_a_recipes_three_ingredients_makes_the_potion() -> None:
    game = make(recipes=[RECIPE])
    game.give_bottle(contents=parts(("water", 20), ("blood", 20), ("oil", 20)))
    game.step(10)
    bottle = game.player()["bottles"][0]
    assert bottle["contents"] == parts(("potion_crit", 60))
    assert bottle["material"] == "potion_crit" and bottle["amount"] == 60
    assert sum(e["cells"] for e in game.events() if e["type"] == "mix") == 60


def test_two_ingredients_do_not_and_a_world_without_recipes_never_does() -> None:
    game = make(recipes=[RECIPE])
    game.give_bottle(contents=parts(("water", 20), ("blood", 20)))
    game.step(30)
    assert game.player()["bottles"][0]["contents"] == parts(("water", 20), ("blood", 20))
    bare = make()
    bare.give_bottle(contents=parts(("water", 20), ("blood", 20), ("oil", 20)))
    bare.step(30)
    assert len(bare.player()["bottles"][0]["contents"]) == 3


# -- the drop control --------------------------------------------------------------------------------


def test_drop_puts_each_kind_of_thing_on_the_ground() -> None:
    game = make()
    game.give_spell("BOMB")
    game.give_bottle(contents=parts(("water", 30), ("oil", 20)))
    game.step(1, {"drop": {"wand": 0}})
    game.step(1)
    game.step(1, {"drop": {"spell": 0}})
    game.step(1)
    game.step(1, {"drop": {"bottle": 0}})
    game.step(1)
    p = game.player()
    assert (len(p["wands"]), p["spells"], p["bottles"]) == (1, [], [])
    on_ground = [e for e in game.entities() if e["kind"] in ("wand", "spell", "bottle")]
    assert sorted(e["kind"] for e in on_ground) == ["bottle", "spell", "wand"]
    bottle = next(e for e in on_ground if e["kind"] == "bottle")
    assert bottle["contents"] == parts(("water", 30), ("oil", 20))
    drops = [e for e in game.events() if e["type"] == "drop"]
    assert [(e["item"], e["detail"]) for e in drops] == [
        ("wand", ""),
        ("spell", "BOMB"),
        ("bottle", "water+oil"),
    ]
    # next to the player, on the floor
    p = game.player()
    for e in on_ground:
        assert abs(e["x"] + e["w"] / 2 - (p["x"] + p["w"] / 2)) <= 9
        assert e["y"] + e["h"] == GROUND + 1


def test_a_held_drop_drops_once_and_none_drops_nothing() -> None:
    game = make()
    game.give_spell("BOMB")
    game.give_spell("DAMAGE")
    game.give_spell("SPEED")
    game.step(8, {"drop": {"spell": 0}})
    assert len(game.player()["spells"]) == 2
    game.step(3, {"drop": None})
    game.step(3, {})
    assert len(game.player()["spells"]) == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"wand": 1, "spell": 2},
        {},
        {"hat": 1},
        {"wand": 300},
        {"wand": -1},
        {"wand": "first"},
        "wand",
        3,
    ],
)
def test_a_malformed_drop_is_refused(bad: Any) -> None:
    game = make()
    with pytest.raises(ValueError, match="drop"):
        game.step(1, {"drop": bad})


def test_an_index_that_is_not_there_drops_nothing() -> None:
    game = make()
    game.step(1, {"drop": {"wand": 9}})
    game.step(1, {})
    game.step(1, {"drop": {"spell": 0}})
    assert len(game.player()["wands"]) == 2
    assert [e for e in game.events() if e["type"] == "drop"] == []


def test_dropping_replays_and_snapshots_exactly() -> None:
    def play() -> Game:
        game = make()
        game.give_bottle(contents=parts(("water", 30), ("oil", 20)))
        game.step(1, {"drop": {"bottle": 0}})
        game.step(40)
        game.step(1, {"interact": True})
        game.step(20)
        return game

    a, b = play(), play()
    assert a.state_hash() == b.state_hash()
    assert a.player()["bottles"][0]["contents"] == parts(("water", 30), ("oil", 20))
    blob = a.snapshot()
    a.step(30, {"move": 1})
    after = a.state_hash()
    b.restore(blob)
    b.step(30, {"move": 1})
    assert b.state_hash() == after


# -- the summary events are written when the action ends -----------------------------------------------


def test_the_summary_event_comes_when_the_bottle_runs_dry_or_the_harness_ends_the_action() -> None:
    game = make()
    game.give_bottle("potion_heal", 30)
    game.step(3, {"drink": True})
    assert [e["cells"] for e in game.events() if e["type"] == "drink"] == [30]
    game.give_bottle("potion_heal", 400)
    game.step(2, {"drink": True, "select_bottle": 1})
    assert [e for e in game.events() if e["type"] == "drink"] == []
    game.end_bottle_action()
    assert [e["cells"] for e in game.events() if e["type"] == "drink"] == [20]
    game.step(1)
    assert [e for e in game.events() if e["type"] == "drink"] == []  # and not again


def test_one_event_per_material_of_a_mixture() -> None:
    game = make()
    game.give_bottle(contents=parts(("water", 40), ("oil", 40)))
    for _ in range(30):  # 8 cells a frame, a few frames more where the stream is crowded
        game.step(1, {"pour": True, "aim": 0})
        if game.player()["bottles"][0]["amount"] == 0:
            break
    assert game.player()["bottles"][0]["amount"] == 0
    events = [(e["material"], e["cells"]) for e in game.events() if e["type"] == "pour"]
    assert [m for m, _ in events] == ["water", "oil"]
    assert sum(n for _, n in events) == 80


# -- on_ground is the state at the end of the frame ----------------------------------------------------


def test_on_ground_is_current_after_every_frame() -> None:
    game = make()
    game.step(1, {"jump": True})
    flips = 0
    last = game.player()["on_ground"]
    for _ in range(60):
        game.step(1)
        p = game.player()
        under = game.overlap(p["x"], p["y"] + p["h"], p["w"], 1)["kinds"].get("static", 0) > 0
        assert p["on_ground"] == under
        flips += p["on_ground"] != last
        last = p["on_ground"]
    assert flips == 1 and last
