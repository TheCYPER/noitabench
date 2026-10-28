"""The pilot: turns the player's state and a `NavField` into the controls of one frame.

Per frame it finds the player's node, picks a target a few nodes down the cheapest way (the
farthest one that can be reached in a straight line through free space), and presses the keys
that go there: walk left or right, levitate when the target is above (after a hop if it is
low), and fire the digging wand when the box ahead is blocked by something a bolt can remove.
Nothing here edits the game: it only returns the same control dict a person's keyboard would.

If the player stops making progress the pilot runs a recovery in turn: back off and hop, dig
toward the goal, rebuild the field from the current grid.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np

from noitabench.game import Controls, aim_at

from .navfield import NO_NODE, NavField
from .terrain import POWDER, STATIC, Materials, Terrain
from .wands import DIGGER, SPARK, wand_with

FPS = 60.0


@dataclass(frozen=True)
class PilotConfig:
    look_hops: int = 28  # nodes along the way that the target is picked from
    fly_gap: int = 2  # levitate when the target is this many cells above
    hop_max_gap: int = 10  # a target up to this far above is first tried with a jump
    stuck_frames: int = 120  # no progress for this long: recover
    progress_eps: float = 2.0  # cost units that count as progress
    recover_frames: int = 45
    dig_reach: float = 11.0  # farthest a blocking cell may be from the hand for a dig shot
    grid_refresh: int = 8  # frames between copies of the grid while digging
    rest_meter: float = 0.97  # wait on the ground for this meter before a long climb
    hazard_depth: int = 60  # cells under the box that a fall can reach before it can be stopped
    air_meter_per_node: float = 1.3  # meter frames a level or rising node without ground costs
    meter_hops: int = 160  # nodes ahead that the meter plan looks at
    meter_frames: float = 180.0  # a full meter, in frames of levitation (entities.json)
    fall_follow_gap: int = 8  # a fall to a target this far below follows the way's own column
    fall_column_depth: int = 6  # ... as it is this far further down
    dead_band: float = 0.5  # cells of error in the coasting position that are good enough
    air_px_per_frame: float = 0.9  # sideways speed in the air (entities.json: 52 and 57 px/s)
    climb_speed_cap: float = -70.0  # px/s: fastest climb the tracking asks for (thrust gives 95)
    fall_speed_cap: float = 350.0  # px/s: terminal fall speed
    thrust_start_band: float = 35.0  # px/s faster than wanted before thrust starts
    thrust_hold_band: float = -35.0  # px/s slower than wanted before thrust stops
    hover_speed: float = 8.0  # px/s: thrust that keeps both speeds under this is a hover in place
    hover_limit: int = 20  # frames of such a hover (pressed against something) before a release
    hover_release: int = 10  # frames the thrust is held back after that, to drop past the edge


@dataclass
class _Recovery:
    mode: str = ""  # "", "wiggle", "dig", "replan"
    until: int = 0
    count: int = 0
    side: int = 1


@dataclass
class Pilot:
    mats: Materials
    terrain: Terrain
    field: NavField
    grid: np.ndarray  # the world as last seen (refreshed by the driver)
    rebuild: Callable[[], tuple[Terrain, NavField]]
    hazard_ids: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.uint8))
    config: PilotConfig = field(default_factory=PilotConfig)
    # --- state
    frame: int = 0
    flying: bool = False
    hover: int = 0  # consecutive frames of thrust that went nowhere
    release_until: int = 0  # no thrust before this frame (after a hover)
    prev_jump: bool = False
    best_cost: float = math.inf
    best_frame: int = 0
    recovery: _Recovery = field(default_factory=_Recovery)
    digging: bool = False
    gun_wand: int = 0  # indices of the wands that hold the spark and the digging bolt
    dig_wand: int = 1
    target: tuple[int, int] = (0, 0)
    dig_target: tuple[int, int] | None = None
    log: list[tuple[int, int, int, str]] = field(default_factory=list)  # (frame, x, y, what)
    stats: dict[str, int] = field(
        default_factory=lambda: {
            "recoveries": 0,
            "replans": 0,
            "dig_frames": 0,
            "hops": 0,
            "fly_frames": 0,
        }
    )

    # -- queries --------------------------------------------------------------------------------

    def blocking_cells(self, x: int, y: int) -> np.ndarray:
        """`(n, 2)` array of the `(cx, cy)` cells in the box at `(x, y)` that block the player."""
        w, h = self.terrain.body.w, self.terrain.body.h
        sub = self.grid[y : y + h, x : x + w]
        kind = self.mats.kind[sub]
        ys, xs = np.nonzero((kind == STATIC) | (kind == POWDER))
        return np.stack([xs + x, ys + y], axis=1) if len(xs) else np.empty((0, 2), dtype=int)

    def _clear_line(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        n = max(abs(b[0] - a[0]), abs(b[1] - a[1])) + 1
        xs = np.rint(np.linspace(a[0], b[0], n)).astype(int)
        ys = np.rint(np.linspace(a[1], b[1], n)).astype(int)
        # where we stand is not in question; a line that grazes lava (the hit box touches it) is no
        # shortcut: it cuts a corner the way itself keeps clear of
        return bool(
            self.terrain.free[ys[1:], xs[1:]].all()
            and not self.terrain.contact[ys[1:], xs[1:]].any()
        )

    # -- the frame ------------------------------------------------------------------------------

    def decide(self, p: dict[str, Any], frame: int) -> Controls:
        """The controls for this frame given the player dict."""
        controls = self._decide(p, frame)
        self.stats["fly_frames"] += bool(controls.get("fly"))
        return controls

    def _decide(self, p: dict[str, Any], frame: int) -> Controls:
        self.frame = frame
        self.gun_wand, self.dig_wand = wand_with(p, SPARK, 0), wand_with(p, DIGGER, 1)
        x, y = int(p["x"]), int(p["y"])
        node = self.field.nearest_node(x, y)
        if node == NO_NODE:
            return self._flail(p)
        cost = float(self.field.dist[node])
        if cost < self.best_cost - self.config.progress_eps:
            self.best_cost, self.best_frame = cost, frame
        rec = self._recovery(p, node, cost)
        if rec is not None:
            return rec
        return self._follow(p, node)

    def _follow(self, p: dict[str, Any], node: int) -> Controls:
        cfg = self.config
        x, y = int(p["x"]), int(p["y"])
        ahead = self._path(node, cfg.look_hops)
        blocked_at = next(
            (i for i, (px, py) in enumerate(ahead[:6]) if i and len(self.blocking_cells(px, py))),
            None,
        )
        controls: Controls = {"select_wand": self.gun_wand}
        if blocked_at is not None:
            return self._dig_ahead(p, ahead[blocked_at], controls)
        self.digging = False
        tx, ty = self._lookahead(ahead, (x, y))
        if not p["on_ground"] and ty - y > cfg.fall_follow_gap:
            tx = self._column_below(
                ahead, y
            )  # falling: stay in the path's column, not the target's
        self.target = (tx, ty)
        # wait on the ground for the meter before a stretch that needs it
        need = self._meter_needed(node)
        if (
            p["on_ground"]
            and need > 0.2
            and p["fly"] < min(need, cfg.rest_meter)
            and not self._hazard_near(p)
        ):
            controls["aim"] = 0.0
            self.flying = False
            return controls
        self._steer(p, (tx, ty), controls)
        return controls

    def _meter_needed(self, node: int) -> float:
        """Share of the meter the next stretch of the way is going to use: the climbs, and the
        level or rising moves with nothing underfoot (hovering and flying across)."""
        way = self._path(node, self.config.meter_hops)
        climb = air = 0
        grounded = self.terrain.grounded
        for (px, py), (qx, qy) in pairwise(way):
            climb += max(0, py - qy)
            if qy <= py and not grounded[qy, qx]:
                air += 1
        frames = climb / 1.5 + air * self.config.air_meter_per_node + 15
        return min(1.0, frames / self.config.meter_frames)

    def _path(self, node: int, hops: int) -> list[tuple[int, int]]:
        out = [(int(self.field.xs[node]), int(self.field.ys[node]))]
        for _ in range(hops):
            nxt = int(self.field.succ[node])
            if nxt == NO_NODE:
                break
            node = nxt
            out.append((int(self.field.xs[node]), int(self.field.ys[node])))
        return out

    def _column_below(self, ahead: list[tuple[int, int]], y: int) -> int:
        """The x of the way a few cells further down than `y` (the last node if it ends sooner)."""
        want = y + self.config.fall_column_depth
        return next((nx for nx, ny in ahead if ny >= want), ahead[-1][0])

    def _lookahead(self, ahead: list[tuple[int, int]], here: tuple[int, int]) -> tuple[int, int]:
        """The farthest node of the way that a straight line from `here` reaches through free
        space; the next node if none does."""
        best = ahead[min(3, len(ahead) - 1)]  # never aim at a spot too near to steer by
        misses = 0
        for cand in ahead[4:]:
            if not self.terrain.free[cand[1], cand[0]]:
                break
            if self._clear_line(here, cand):
                best, misses = cand, 0
            else:
                misses += 1
                if misses >= 3:
                    break
        return best

    def _steer(self, p: dict[str, Any], target: tuple[int, int], controls: Controls) -> None:
        cfg = self.config
        x, y = int(p["x"]), int(p["y"])
        dy = target[1] - y
        # the box coasts on after the key is released: steer by where it will stop
        body = self.terrain.body
        ax = body.accel_ground if p["on_ground"] else body.accel_air
        dx_stop = target[0] - (x + p["vx"] / FPS / ax)
        move = 0 if abs(dx_stop) < cfg.dead_band else (1 if dx_stop > 0 else -1)
        controls["move"] = move
        controls["aim"] = 0.0 if move >= 0 else 180.0
        meter = float(p["fly"])
        jump = False
        fly = False
        if meter > 0.0:
            if p["on_ground"]:
                if dy <= -cfg.fly_gap:
                    if -dy <= cfg.hop_max_gap and not self.prev_jump:
                        jump = True  # a hop costs nothing; the meter is for what a hop cannot do
                        self.stats["hops"] += 1
                    elif -dy > cfg.hop_max_gap:
                        fly = True
            else:
                fly = self._airborne_fly(p, target)
        self.flying = fly
        self.prev_jump = jump
        if jump:
            controls["jump"] = True
        if fly:
            controls["fly"] = True

    def _airborne_fly(self, p: dict[str, Any], target: tuple[int, int]) -> bool:
        """Thrust or not while in the air: track the vertical speed that reaches the target's
        height just as the sideways travel reaches the target.

        A shallow slope down over a pit is then flown as a glide (thrust whenever the fall is
        faster than the slope), a climb as a climb, and a level crossing as a hover. The press
        of the levitation key costs meter, so thrust starts and stops with a band between.
        """
        cfg = self.config
        x, y, vy = int(p["x"]), int(p["y"]), float(p["vy"])
        frames_to_go = max(abs(target[0] - x), 1.0) / cfg.air_px_per_frame
        want = max(
            cfg.climb_speed_cap, min(cfg.fall_speed_cap, FPS * (target[1] - y) / frames_to_go)
        )
        if want > 0 and not self._hazard_below(x, y):
            self.hover = 0
            return False  # a fall with nothing to fear below is not worth the meter
        if self.frame < self.release_until:
            return False
        thrust = vy > want + (cfg.thrust_hold_band if self.flying else cfg.thrust_start_band)
        # Thrust that holds the box in one place (a tooth of brick on the left, nothing to rise
        # to) would drain the meter and end in a fall from higher up than the drop it avoids:
        # let go for a moment, so that the box drops past the edge.
        if thrust and abs(vy) < cfg.hover_speed and abs(float(p["vx"])) < cfg.hover_speed:
            self.hover += 1
            if self.hover > cfg.hover_limit:
                self.hover, self.release_until = 0, self.frame + cfg.hover_release
                self.stats["hover_releases"] = self.stats.get("hover_releases", 0) + 1
                return False
        else:
            self.hover = 0
        return thrust

    def _hazard_near(self, p: dict[str, Any]) -> bool:
        """Lava, acid or fire around the hit box: no place to stand and wait."""
        dx, dy, w, h = self.terrain.body.hit
        x0, y0 = max(0, int(p["x"]) + dx - 2), max(0, int(p["y"]) + dy - 2)
        sub = self.grid[y0 : y0 + h + 4, x0 : x0 + w + 4]
        return bool(np.isin(sub, self.hazard_ids).any()) or bool(p["statuses"].get("on_fire"))

    def _hazard_below(self, x: int, y: int) -> bool:
        """Lava, acid or fire that a fall from here could reach: in the columns under the box
        (with a margin), within `hazard_depth` cells and above the first thing that stops a fall
        (a hazard under a floor is not one)."""
        cfg, body = self.config, self.terrain.body
        y0 = y + body.h
        sub = self.grid[y0 : y0 + cfg.hazard_depth, max(0, x - 2) : x + body.w + 2]
        if sub.size == 0:
            return False
        kind = self.mats.kind[sub]
        stopped = np.cumsum((kind == STATIC) | (kind == POWDER), axis=0) > 0  # at or below a floor
        return bool((np.isin(sub, self.hazard_ids) & ~stopped).any())

    def _flail(self, p: dict[str, Any]) -> Controls:
        """No way on from here (the player is somewhere the field does not know): hop about."""
        self.prev_jump = not self.prev_jump
        return {
            "fly": True,
            "move": 1 if (self.frame // 30) % 2 == 0 else -1,
            "jump": self.prev_jump,
        }

    # -- digging --------------------------------------------------------------------------------

    def _dig_ahead(
        self, p: dict[str, Any], blocked_pos: tuple[int, int], controls: Controls
    ) -> Controls:
        cells = self.blocking_cells(*blocked_pos)
        hand = self._hand(p)
        d = np.hypot(cells[:, 0] + 0.5 - hand[0], cells[:, 1] + 0.5 - hand[1])
        target = cells[int(np.argmin(d))]
        self.dig_target = (int(target[0]), int(target[1]))
        self.digging = True
        return self._aim_dig(p, hand, self.dig_target, controls)

    def _aim_dig(
        self,
        p: dict[str, Any],
        hand: tuple[float, float],
        target: tuple[int, int],
        controls: Controls,
    ) -> Controls:
        tx, ty = target[0] + 0.5, target[1] + 0.5
        dist = math.hypot(tx - hand[0], ty - hand[1])
        controls["select_wand"] = self.dig_wand
        controls["aim"] = aim_at(hand, (tx, ty))
        if dist <= self.config.dig_reach:
            controls["fire"] = True
            self.stats["dig_frames"] += 1
            controls["move"] = 0
        else:  # not close enough for a bolt to reach: walk up to it
            controls["move"] = 1 if tx > hand[0] else -1
            if p["on_ground"] and ty < hand[1] - 6 and not self.prev_jump:
                controls["jump"] = True
        self.prev_jump = bool(controls.get("jump"))
        return controls

    def _hand(self, p: dict[str, Any]) -> tuple[float, float]:
        """Where bolts leave: the hand's cell centre."""
        body = self.terrain.body
        return p["x"] + body.hand_dx + 0.5, p["y"] + body.hand_dy + 0.5

    # -- recovery -------------------------------------------------------------------------------

    def _recovery(self, p: dict[str, Any], node: int, cost: float) -> Controls | None:
        cfg, rec = self.config, self.recovery
        if rec.mode and self.frame < rec.until:
            return self._recover(p, node, rec)
        if rec.mode:  # finished: look for progress anew
            rec.mode = ""
            self.best_cost, self.best_frame = cost, self.frame
            return None
        if self.frame - self.best_frame < cfg.stuck_frames or self.digging:
            if self.digging:
                self.best_frame = max(self.best_frame, self.frame - cfg.stuck_frames // 2)
            return None
        self.stats["recoveries"] += 1
        rec.count += 1
        rec.mode = ("wiggle", "dig", "replan")[(rec.count - 1) % 3]
        self.log.append((self.frame, int(p["x"]), int(p["y"]), rec.mode))
        rec.until = self.frame + cfg.recover_frames
        rec.side = -rec.side
        if rec.mode == "replan":
            self.terrain, self.field = self.rebuild()
            self.stats["replans"] += 1
            rec.until = self.frame + 1
        return self._recover(p, node, rec)

    def _recover(self, p: dict[str, Any], node: int, rec: _Recovery) -> Controls:
        controls: Controls = {"select_wand": self.gun_wand}
        if rec.mode == "wiggle":
            phase = rec.until - self.frame
            controls.update(move=rec.side if phase > 25 else -rec.side, fly=phase % 10 < 6)
            controls["aim"] = 0.0
            return controls
        if rec.mode == "dig":
            target = self.field.ahead(node, 3) if node != NO_NODE else (int(p["x"]), int(p["y"]))
            hand = self._hand(p)
            cell = (target[0] + self.terrain.body.w // 2, target[1] + self.terrain.body.h // 2)
            self.digging = True
            return self._aim_dig(p, hand, cell, controls)
        return controls
