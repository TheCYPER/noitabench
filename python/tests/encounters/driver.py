"""A scripted player for the reference solutions of the encounters.

``Runner`` drives a ``Game`` loaded from a scene world (``worldgen.scene_world``) the way an
agent would: it reads the game state (positions, statuses) and answers with controls. It uses
no hidden state beyond what the scene's markers and ``meta`` say (where the exit is).
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any

from noitabench.game import Game, aim_at
from noitabench.worldgen.config import load_materials
from noitabench.worldgen.scene_world import scene_world
from noitabench.worldgen.table import get_rules

SETTLE = 62  # the player falls to the floor and the opening invincibility ends
ENEMY_KINDS = ("longleg", "shotgunner", "firemage_weak")


class Runner:
    """A ``Game`` plus the helpers a script needs to move, shoot and use bottles."""

    def __init__(self, game: Game, meta: dict[str, Any]):
        self.g = game
        self.meta = meta
        self.log: list[str] = []

    # -- state -------------------------------------------------------------------------------
    @property
    def p(self) -> dict[str, Any]:
        p = self.g.player()
        assert p is not None
        return p

    @property
    def x(self) -> float:
        return self.p["x"]

    @property
    def y(self) -> float:
        return self.p["y"]

    @property
    def hp(self) -> float:
        return self.p["hp"]

    @property
    def dead(self) -> bool:
        return bool(self.p["dead"])

    def center(self) -> tuple[float, float]:
        p = self.p
        return p["x"] + p["w"] / 2, p["y"] + p["h"] / 2

    def cell(self, x: int, y: int) -> str:
        return self.g.cell(x, y)["material"]

    def count(self, material: str, rect: tuple[int, int, int, int]) -> int:
        x, y, w, h = rect
        return int(self.g.overlap(x, y, w, h)["materials"].get(material, 0))

    def entities(self, kind: str | None = None) -> list[dict[str, Any]]:
        return [e for e in self.g.entities() if kind is None or e["kind"] == kind]

    # -- stepping ----------------------------------------------------------------------------
    def step(self, n: int = 1, **controls: Any) -> None:
        self.g.step(n, controls or None)

    def wait(self, n: int) -> None:
        self.g.step(n)

    # -- movement ----------------------------------------------------------------------------
    def walk_to(self, x: float, tol: float = 1.5, max_frames: int = 900, **keys: Any) -> bool:
        """Walk along the floor to column ``x``, hopping over small steps. True on arrival."""
        stuck = 0
        for _ in range(max_frames):
            dx = x - self.x
            if abs(dx) <= tol:
                return True
            before = self.x
            hop = stuck > 6 and self.p["on_ground"]
            self.step(move=1 if dx > 0 else -1, jump=hop, **keys)
            stuck = stuck + 1 if abs(self.x - before) < 0.05 else 0
            if hop:
                stuck = 0
        return False

    def hop_to(self, x: float, tol: float = 2.0, max_frames: int = 240) -> bool:
        """Walk toward ``x`` jumping repeatedly (over a gap or a short step)."""
        for _ in range(max_frames):
            dx = x - self.x
            if abs(dx) <= tol:
                return True
            self.step(move=1 if dx > 0 else -1, jump=self.p["on_ground"])
        return False

    def fly_to(self, x: float, y: float, tol: float = 2.0, max_frames: int = 400) -> bool:
        """Levitate to the cell ``(x, y)`` (top-left of the collision box)."""
        for _ in range(max_frames):
            dx, dy = x - self.x, y - self.y
            if abs(dx) <= tol and abs(dy) <= tol:
                return True
            up = dy < -1
            self.step(
                move=0 if abs(dx) <= tol else (1 if dx > 0 else -1),
                fly=up or not self.p["on_ground"] and dy < 3,
            )
        return False

    def fall(self, max_frames: int = 300) -> None:
        """Wait until the player stands on something."""
        for _ in range(max_frames):
            if self.p["on_ground"]:
                return
            self.step()

    # -- wands -------------------------------------------------------------------------------
    def aim_at_point(self, x: float, y: float) -> float:
        return aim_at(self.center(), (x, y))

    def shoot_at(self, x: float, y: float, frames: int = 20, wand: int = 0) -> None:
        for _ in range(frames):
            self.step(select_wand=wand, fire=True, aim=self.aim_at_point(x, y))

    def dig(self, angle: float, frames: int = 30) -> None:
        """Fire the digger wand (the second starter wand) at ``angle`` degrees."""
        self.step(frames, select_wand=1, fire=True, aim=angle)

    # -- fighting ----------------------------------------------------------------------------
    def foes(self, within: float = 400.0, in_sight: bool = True) -> list[dict[str, Any]]:
        """Living enemies within ``within`` cells, nearest first; with ``in_sight`` only those
        with no rock or ground between them and the player."""
        me = self.center()
        out = []
        for e in self.g.entities():
            if e["kind"] in ENEMY_KINDS and e["hp"] > 0:
                there = (e["x"] + e["w"] / 2, e["y"] + e["h"] / 2)
                d = distance(me, there)
                if d > within:
                    continue
                if in_sight and self.g.raycast(
                    int(me[0]), int(me[1]), int(there[0]), int(there[1]), "surfaces"
                ):
                    continue
                out.append((d, e))
        return [e for _, e in sorted(out, key=lambda t: t[0])]

    def fight(self, max_frames: int = 900, within: float = 400.0, reach: float = 12.0) -> bool:
        """Kill every enemy within ``within`` cells: kick the ones at arm's length (a bolt
        spawned beyond them would miss), shoot the others; True if all are dead."""
        for t in range(max_frames):
            foes = self.foes(within)
            if not foes or self.dead:
                return not foes
            e = foes[0]
            ex, ey = e["x"] + e["w"] / 2, e["y"] + e["h"] / 2
            px, py = self.center()
            if abs(ex - px) < reach and abs(ey - py) < 14:
                self.step(aim=0 if ex > px else 180, move=1 if ex > px else -1, kick=t % 2 == 0)
            else:
                self.step(select_wand=0, fire=True, aim=self.aim_at_point(ex, ey))
        return not self.foes(within)

    # -- bottles -----------------------------------------------------------------------------
    def pour(self, angle: float, frames: int, bottle: int = 0) -> int:
        """Tip the bottle out at ``angle``; returns how many cells left it."""
        before = self.bottle_amount(bottle)
        self.step(frames, select_bottle=bottle, pour=True, aim=angle)
        return before - self.bottle_amount(bottle)

    def bottle_amount(self, bottle: int = 0) -> int:
        bottles = self.p["bottles"]
        return int(bottles[bottle]["amount"]) if bottle < len(bottles) else 0

    def fill(self, frames: int = 30, bottle: int = 0) -> None:
        self.step(frames, select_bottle=bottle, fill=True)

    def throw(self, angle: float, bottle: int = 0) -> None:
        """Throw the bottle along ``angle`` degrees (it shatters where it lands)."""
        self.step(1, select_bottle=bottle, aim=angle, throw=False)
        self.step(1, select_bottle=bottle, aim=angle, throw=True)
        self.step(1, aim=angle, throw=False)

    def throw_angle(self, tx: float, ty: float, speed: float = 180.0, lift: float = 40.0) -> float:
        """The flattest angle that lands a thrown bottle on ``(tx, ty)`` from here (gravity 400)."""
        ox, oy = self.center()
        sign = 1 if tx >= ox else -1
        fits: list[tuple[float, int]] = []
        for deg in range(-80, 81):
            a = math.radians(deg)
            vx, vy = speed * math.cos(a) * sign, -(speed * math.sin(a) + lift)
            x, y = ox, oy
            err = 1e9
            for _ in range(240):
                x, y, vy = x + vx / 60.0, y + vy / 60.0, vy + 400.0 / 60.0
                err = min(err, math.hypot(x - tx, y - ty))
                if (x - tx) * sign > 0 and y > ty:
                    break
            fits.append((err, deg))
        best = min(e for e, _ in fits)
        deg = min((d for e, d in fits if e <= best + 1.5), key=abs)
        return float(deg) if sign > 0 else 180.0 - deg

    def pick_up(self) -> None:
        self.step(1, interact=False)
        self.step(2, interact=True)
        self.step(1, interact=False)


def start(
    eid: str,
    variant: int = 0,
    rule_seed: int = 0,
    seed: int = 1,
    settle: bool = True,
    tmp: Path | None = None,
) -> Runner:
    """A game of the lab world around encounter ``eid`` (the rule seed only seeds the recipes)."""
    mats = load_materials()
    world = scene_world(eid, variant, rule_seed, seed, mats)
    out = Path(tmp) if tmp is not None else Path(tempfile.mkdtemp(prefix="scene_"))
    png, js = world.write(out, f"{eid}_v{variant}", mats)
    rules = get_rules(rule_seed)
    game = Game.from_world(png, js, seed, rule_seed=rule_seed, reactions_json=rules.reactions_json)
    runner = Runner(game, world.meta)
    if settle:
        runner.wait(SETTLE)
    return runner


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ------------------------------------------------------------------------------------ helpers
def solvents(rules_seed: int) -> list[str]:
    return get_rules(rules_seed).solidifiers()
