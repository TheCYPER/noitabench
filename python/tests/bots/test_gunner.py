"""Shooting at enemies on the way."""

from __future__ import annotations

import pytest
from noitabench.bots.gunner import Gunner, weak_points
from noitabench.bots.terrain import Body
from noitabench.game import Game

W, H, FLOOR = 320, 160, 30
GROUND = H - FLOOR - 1
BODY = Body.load()


def arena(enemy: str = "longleg", distance: int = 90, barrel_x: int | None = None) -> Game:
    game = Game(W, H, 3)
    game.fill_rect(0, H - FLOOR, W, FLOOR, "rock")
    game.spawn_player(60, GROUND)
    game.spawn_enemy(enemy, 60 + distance, GROUND)
    if barrel_x is not None:
        game.spawn_item("barrel_oil", barrel_x, GROUND)
    game.step(61)  # lands; the opening invincibility ends
    game.events()
    return game


def gunner(game: Game) -> Gunner:
    return Gunner(game, frozenset(game.enemy_kinds()), BODY.hand_dx, BODY.hand_dy)


def play(game: Game, frames: int) -> Gunner:
    g = gunner(game)
    for _ in range(frames):
        p = game.player()
        assert p is not None
        controls: dict = {}
        g.assist(controls, p, game.frame, digging=False)
        game.step(1, controls)
    return g


def alive(game: Game, kind: str) -> list[dict]:
    return [e for e in game.entities() if e["kind"] == kind and e["hp"] > 0]


def test_the_gunner_kills_a_hamis_in_front_of_it() -> None:
    game = arena("longleg", 90)
    g = play(game, 200)
    assert g.fire_frames > 0
    assert not alive(game, "longleg")
    assert any(e["type"] == "hit" and e["projectile"] == "LIGHT_BULLET" for e in game.events())


def test_it_aims_at_the_head_of_a_shotgunner() -> None:
    spots = weak_points()
    shotgunner, hamis = spots["shotgunner"], spots["longleg"]
    assert shotgunner[1] < 5.0  # the head, near the top of the box
    assert hamis[1] > 4.0  # no weak point: the middle of the body
    game = arena("shotgunner", 110)
    play(game, 150)
    hits = [e for e in game.events() if e["type"] == "hit" and e["target"] == "shotgunner"]
    assert hits and max(h["damage"] for h in hits) > 6.0  # headshots (3 x 2.5)


def test_it_holds_fire_when_a_barrel_stands_in_the_line_of_fire() -> None:
    game = arena("longleg", 100, barrel_x=95)
    p = game.player()
    assert p is not None
    controls: dict = {}
    g = gunner(game)
    assert g.assist(controls, p, game.frame, digging=False) is False
    assert "fire" not in controls
    clear = arena("longleg", 100)
    assert gunner(clear).assist({}, clear.player(), clear.frame, digging=False) is True


def test_it_does_not_shoot_while_digging_or_through_rock() -> None:
    game = arena("longleg", 90)
    p = game.player()
    assert p is not None
    assert gunner(game).assist({}, p, game.frame, digging=True) is False
    game.fill_rect(100, GROUND - 40, 4, 41, "rock")  # a wall between them
    assert gunner(game).assist({}, p, game.frame, digging=False) is False


@pytest.mark.parametrize("kind", ["longleg", "shotgunner", "firemage_weak"])
def test_every_enemy_kind_has_an_aim_point(kind: str) -> None:
    assert kind in weak_points()
