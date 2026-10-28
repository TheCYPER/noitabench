"""Eight short scenes that show the game layer, recorded for the web viewer.

    python -m noitabench demo game

writes `runs/demo-game-<scene>/` (format `cogbench-rec/0` plus `entities.jsonl`, contract
section 5). Every scene is a 320 x 192 world, a few seconds long, and fully determined by its
seed: the player is driven by a small script that reads the game state like an agent would.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from noitabench.game import Controls, Game, aim_at

WIDTH, HEIGHT = 320, 192
FLOOR_Y = 150  # first row of the floor; creatures stand on row FLOOR_Y - 1
FRAME_STRIDE = 2
SETTLE = 61  # the player is invincible for the first 60 frames; scenes start after that
CREATED = "2026-10-26T00:00:00Z"

Controller = Callable[[Game, int], Controls]
Action = Callable[[Game], None]


@dataclass(frozen=True)
class Scene:
    name: str
    title: str
    frames: int
    setup: Callable[[Game], None]
    controller: Controller
    # (frame, action) pairs: the action runs just before that frame is simulated.
    actions: tuple[tuple[int, Action], ...] = ()
    # Rule seed whose secret recipes the world has (None: no recipes).
    rule_seed: int | None = None


def stats(**overrides: Any) -> dict[str, Any]:
    """Wand stats for demo wands: plenty of mana, no spread, quick."""
    base: dict[str, Any] = {
        "cast_delay": 10,
        "recharge": 20,
        "mana_max": 500.0,
        "mana_charge_speed": 80.0,
        "capacity": 8,
    }
    base.update(overrides)
    return base


def arena(game: Game, floor: str = "rock") -> None:
    """Walls, ceiling and a floor, with the player standing at the left."""
    game.fill_rect(0, 0, WIDTH, 4, "rock")
    game.fill_rect(0, 0, 4, HEIGHT, "rock")
    game.fill_rect(WIDTH - 4, 0, 4, HEIGHT, "rock")
    game.fill_rect(0, FLOOR_Y, WIDTH, HEIGHT - FLOOR_Y, floor)


def center(entity: dict[str, Any]) -> tuple[float, float]:
    return entity["x"] + entity["w"] / 2, entity["y"] + entity["h"] / 2


def first(game: Game, kind: str) -> dict[str, Any] | None:
    return next((e for e in game.entities() if e["kind"] == kind), None)


def aim_for(game: Game, kind: str, lift: float = 0.0) -> float:
    """Aim at the first creature of a kind (straight ahead if there is none)."""
    player, target = game.player(), first(game, kind)
    if player is None or target is None:
        return 0.0
    return aim_at(center(player), center(target)) + lift


def hold(**keys: Any) -> Controls:
    return dict(keys)


# -- 1. walk, jump, levitate over a pillar, dig down ---------------------------------------------


def _move_setup(game: Game) -> None:
    arena(game, "ground")
    game.fill_rect(4, FLOOR_Y + 30, WIDTH - 8, 6, "rock")
    game.fill_rect(120, FLOOR_Y - 34, 8, 34, "rock")  # a pillar too high to jump
    game.spawn_player(30, FLOOR_Y - 1)


def _move_controller(game: Game, frame: int) -> Controls:
    p = game.player()
    assert p is not None
    if frame < 60:
        return hold(move=1)
    if frame == 60:
        return hold(move=1, jump=True)
    if frame < 110:
        return hold(move=1)
    if frame < 230 and p["x"] < 140:  # up and over the pillar
        return hold(move=1, fly=True)
    if frame < 290:
        return hold(move=1 if p["x"] < 200 else 0)
    # dig down with the digger wand (wand 1), aiming at the floor
    return hold(select_wand=1, fire=True, aim=-90.0, move=0)


# -- 2. Hämis comes in threes --------------------------------------------------------------------


def _hamis_setup(game: Game) -> None:
    arena(game)
    game.spawn_player(40, FLOOR_Y - 1)
    for x in (190, 215, 240):
        game.spawn_enemy("longleg", x, FLOOR_Y - 1)


def _shoot_controller(kind: str, wand: int) -> Controller:
    """Hold fire on wand `wand`, aimed at the first creature of `kind`."""

    def controller(game: Game, frame: int) -> Controls:
        return hold(select_wand=wand, fire=True, aim=aim_for(game, kind))

    return controller


# -- 3. the shotgunner ------------------------------------------------------------------------------


def _shotgunner_setup(game: Game) -> None:
    arena(game)
    game.spawn_player(60, FLOOR_Y - 1)
    game.spawn_enemy("shotgunner", 250, FLOOR_Y - 1)
    # Magic Arrow: 10 damage a hit, so a few hits drop the shotgunner
    game.give_wand(stats(cast_delay=12, recharge=10), ["BULLET", "BULLET"])


# -- 4. Stendari and water ---------------------------------------------------------------------------


def _stendari_setup(game: Game) -> None:
    arena(game)
    game.spawn_player(60, FLOOR_Y - 1)
    game.spawn_enemy("firemage_weak", 250, FLOOR_Y - 1)
    game.give_bottle("water")


def _stendari_controller(game: Game, frame: int) -> Controls:
    if frame == 20:  # throw the water over the mage's head
        return hold(throw=True, aim=aim_for(game, "firemage_weak", lift=12.0))
    return hold()


# -- 5. a chain of barrels -----------------------------------------------------------------------------


def _barrels_setup(game: Game) -> None:
    arena(game)
    # a ledge of ground carrying a heap of sand, held up by two pillars; the barrels stand under it
    game.fill_rect(120, FLOOR_Y - 60, 130, 10, "ground")
    game.fill_rect(120, FLOOR_Y - 50, 10, 30, "rock")  # left pillar, opening below
    game.fill_rect(240, FLOOR_Y - 50, 10, 50, "rock")  # right pillar
    game.fill_rect(120, FLOOR_Y - 90, 3, 30, "rock")  # rims keep the sand on the ledge
    game.fill_rect(247, FLOOR_Y - 90, 3, 30, "rock")
    game.fill_rect(123, FLOOR_Y - 90, 124, 30, "sand")
    game.spawn_player(50, FLOOR_Y - 1)
    game.spawn_item("barrel_oil", 150, FLOOR_Y - 1)
    game.spawn_item("barrel_gunpowder", 175, FLOOR_Y - 1)
    game.spawn_item("barrel_gunpowder", 200, FLOOR_Y - 1)
    game.spawn_item("barrel_acid", 225, FLOOR_Y - 1)
    game.give_wand(stats(cast_delay=60, recharge=60), ["FIREBALL"])


def _barrels_controller(game: Game, frame: int) -> Controls:
    # a little upward: the Fireball drops while it flies
    if frame < 15:
        return hold(select_wand=2, aim=8.0)
    return hold(select_wand=2, aim=8.0, fire=frame < 17)


# -- 6. potions -------------------------------------------------------------------------------------------


def _potions_setup(game: Game) -> None:
    arena(game)
    game.spawn_player(40, FLOOR_Y - 1)
    game.give_bottle("potion_heal")
    game.give_bottle("potion_haste")
    game.give_bottle("whiskey", 200)
    game.spawn_enemy("longleg", 280, FLOOR_Y - 1)


def _hurt(game: Game) -> None:
    game.blast(40, FLOOR_Y - 4, 6, damage=3.0, ray_energy=1000, max_durability=4, fire_percent=0)
    game.blast(40, FLOOR_Y - 4, 6, damage=3.0, ray_energy=1000, max_durability=4, fire_percent=0)


def _potions_controller(game: Game, frame: int) -> Controls:
    if frame < 40:
        return hold()
    if frame < 100:  # the healing potion
        return hold(select_bottle=0, drink=True)
    if frame < 120:  # the haste potion, then run
        return hold(select_bottle=1, drink=True)
    if frame < 220:
        return hold(move=1)
    if frame < 250:  # whiskey: the aim wobbles
        return hold(select_bottle=2, drink=True, move=0)
    return hold(select_wand=0, fire=True, aim=aim_for(game, "longleg"))


# -- 8. alchemy --------------------------------------------------------------------------------------


def _alchemy_setup(game: Game) -> None:
    arena(game)
    # a metal bowl, 20 cells wide inside, on the floor
    game.fill_rect(148, FLOOR_Y - 12, 2, 12, "metal")
    game.fill_rect(170, FLOOR_Y - 12, 2, 12, "metal")
    game.spawn_player(130, FLOOR_Y - 1)
    # rule seed 2 makes the critical potion from water, blood and oil
    for liquid in ("blood", "water", "oil"):
        game.give_bottle(liquid, 100)


def _alchemy_controller(game: Game, frame: int) -> Controls:
    # three pours of 13 frames, a pause between them for the liquids to settle
    for bottle, start in enumerate((20, 100, 180)):
        if start <= frame < start + 13:
            return hold(select_bottle=bottle, pour=True, aim=35.0)
    return hold()


# -- 7. trigger and multicast --------------------------------------------------------------------------------


def _combo_setup(game: Game) -> None:
    arena(game)
    game.fill_rect(230, FLOOR_Y - 50, 12, 50, "wood")  # a wooden gate: the Fireball sets it alight
    game.fill_rect(260, FLOOR_Y - 50, 40, 50, "ground")
    game.spawn_player(50, FLOOR_Y - 1)
    game.spawn_enemy("longleg", 275, FLOOR_Y - 51)
    # Double Spell deals the next two cards: the trigger bolt (whose payload is the Fireball
    # that follows it) and a plain Spark Bolt
    game.give_wand(
        stats(cast_delay=20, recharge=40, mana_max=600.0),
        ["BURST_2", "LIGHT_BULLET_TRIGGER", "FIREBALL", "LIGHT_BULLET"],
    )


def _combo_controller(game: Game, frame: int) -> Controls:
    return hold(select_wand=2, fire=frame % 100 < 4, aim=8.0)


SCENES: dict[str, Scene] = {
    s.name: s
    for s in (
        Scene(
            "move-dig",
            "Walk, jump, levitate over a pillar and dig down",
            420,
            _move_setup,
            _move_controller,
        ),
        Scene(
            "fight-hamis",
            "Three Hämis against a Spark Bolt wand",
            300,
            _hamis_setup,
            _shoot_controller("longleg", 0),
        ),
        Scene(
            "fight-shotgunner",
            "A shotgunner fires buckshot; Magic Arrows answer",
            420,
            _shotgunner_setup,
            _shoot_controller("shotgunner", 2),
        ),
        Scene(
            "fight-stendari",
            "A thrown flask of water hurts Stendari, who is immune to fire",
            420,
            _stendari_setup,
            _stendari_controller,
        ),
        Scene(
            "barrel-chain",
            "A fireball sets off an oil barrel, then gunpowder; the ledge and sand collapse",
            420,
            _barrels_setup,
            _barrels_controller,
        ),
        Scene(
            "potions",
            "Hurt by a blast, heal, speed up, get drunk",
            420,
            _potions_setup,
            _potions_controller,
            ((10, _hurt),),
        ),
        Scene(
            "trigger-combo",
            "Double Spell, a trigger bolt carrying a Fireball, and a Spark Bolt",
            300,
            _combo_setup,
            _combo_controller,
        ),
        Scene(
            "alchemy",
            "Pour blood, water and oil into a metal bowl: where all three meet they become a potion",
            420,
            _alchemy_setup,
            _alchemy_controller,
            rule_seed=2,
        ),
    )
}


def run_scene(scene: Scene, out_dir: str | Path, seed: int = 1) -> dict[str, Any]:
    """Simulate one scene and write `<out_dir>/demo-game-<name>/`; returns a summary dict."""
    run_dir = Path(out_dir) / f"demo-game-{scene.name}"
    game = Game(WIDTH, HEIGHT, seed, rule_seed=scene.rule_seed)
    scene.setup(game)
    game.step(SETTLE)  # the player lands and loses the opening invincibility
    game.events()
    game.start_recording(
        run_dir,
        FRAME_STRIDE,
        run_id=f"demo-game-{scene.name}",
        notes=scene.title,
        created=CREATED,
    )
    pending = sorted(scene.actions, key=lambda item: item[0])
    events = 0
    for frame in range(scene.frames):
        while pending and pending[0][0] + SETTLE <= game.frame:
            pending.pop(0)[1](game)
        controls = scene.controller(game, frame) if game.player() else {}
        game.step(1, controls)
        events += len(game.events())
    summary = game.stop_recording()
    summary["events"] = events
    return summary


def run_all(
    out_dir: str | Path = "runs", seed: int = 1, only: list[str] | None = None
) -> list[dict[str, Any]]:
    """Record every scene (or those named in `only`)."""
    names = only or list(SCENES)
    unknown = [n for n in names if n not in SCENES]
    if unknown:
        raise ValueError(f"unknown scene(s) {unknown}; choose from {sorted(SCENES)}")
    return [run_scene(SCENES[n], out_dir, seed) for n in names]
