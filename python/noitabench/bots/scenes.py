"""The must-pass scenes of a world, and a log of the bot going through them.

The generator makes every must-pass scene a true chokepoint (contracts section 4): a brick seam
across the middle biome with a hole as wide as the scene, a brick shell around each side biome.
A digger cannot get round one, so the way down leads through each scene's footprint. The bot
reads the `encounter` markers of the world file for that (a test and recording tool may; an
agent never sees them): the scene's id, footprint and named regions.

`SceneTracker` says, frame by frame, whether the player is in a footprint, and so whether a
scene was entered from above and left downwards (passed). The tests use it to show that the bot
did not bypass any scene.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import numpy as np

from .seal import Rect
from .terrain import CONTENT, POWDER, STATIC, Materials, Terrain


@dataclasses.dataclass(frozen=True)
class Scene:
    """One placed encounter scene of the world file."""

    eid: str
    layer: int
    variant: int
    mirror: bool
    footprint: Rect
    regions: dict[str, Rect]
    must_pass: bool
    dig_zone: bool = False  # the scene is meant to be dug through (E08, E12): digging is its way

    def region(self, name: str) -> Rect:
        return self.regions[name]

    def contains(self, x: float, y: float) -> bool:
        f = self.footprint
        return f.x <= x < f.x + f.w and f.y <= y < f.bottom


def _rect(d: dict[str, Any]) -> Rect:
    return Rect(int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"]))


def dig_zones(path: Path | None = None) -> set[str]:
    """Ids of the scenes whose definition says `dig_zone` (`content/encounters/EXX.json`)."""
    found: set[str] = set()
    for f in sorted((path or CONTENT / "encounters").glob("E*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        if doc.get("dig_zone"):
            found.add(str(doc["id"]))
    return found


def read_scenes(
    markers: list[dict[str, Any]], *, must_pass: bool = True, digging: set[str] | None = None
) -> list[Scene]:
    """The scenes of the world that carry a scene (not placeholders), shallowest first; by
    default only the must-pass ones. `digging` is the set of ids that are dig zones (default:
    read from the scene definitions)."""
    digging = dig_zones() if digging is None else digging
    out = []
    for m in markers:
        if m.get("type") != "encounter" or m.get("placeholder", True) or "footprint" not in m:
            continue
        if must_pass and not m.get("must_pass"):
            continue
        out.append(
            Scene(
                eid=str(m["encounter_id"]),
                layer=int(m.get("layer") or 0),
                variant=int(m.get("variant", 0)),
                mirror=bool(m.get("mirror", False)),
                footprint=_rect(m["footprint"]),
                regions={k: _rect(v) for k, v in (m.get("regions") or {}).items()},
                must_pass=bool(m.get("must_pass")),
                dig_zone=str(m["encounter_id"]) in digging,
            )
        )
    return sorted(out, key=lambda s: (s.footprint.y, s.footprint.x))


@dataclasses.dataclass
class Visit:
    """The bot in one scene: when it came in, when it left downwards, what it cost."""

    eid: str
    layer: int
    entered: int | None = None  # frame the centre of the collision box first lay in the footprint
    from_above: bool = False  # ... and it came from above the footprint (not from the side)
    passed: int | None = None  # frame it was below the footprint after coming in from above
    hp_in: float = 0.0
    hp_min: float = 0.0
    hp_out: float = 0.0
    died: bool = False
    dig_frames: int = 0  # frames the digging wand was fired inside the footprint

    def asdict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class SceneTracker:
    """Follows the player through the footprints of `scenes`, one call per frame.

    A scene counts as passed only if the player came into the footprint from above (the frame
    before, the centre of the collision box was over its top edge) and later lay below it: a
    footprint that was skirted, entered from the side or from below does not count.
    """

    def __init__(self, scenes: list[Scene]) -> None:
        self.scenes = scenes
        self.visits = [Visit(s.eid, s.layer) for s in scenes]
        self._last_cy: float | None = None  # the centre's height at the previous update

    def update(self, frame: int, p: dict[str, Any]) -> None:
        cx, cy = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
        before, self._last_cy = self._last_cy, cy
        hp = float(p["hp"])
        for scene, v in zip(self.scenes, self.visits, strict=True):
            if v.passed is not None:
                continue
            if v.entered is None:
                if scene.contains(cx, cy):
                    v.entered, v.hp_in, v.hp_min = frame, hp, hp
                    v.from_above = before is not None and before < scene.footprint.y
                continue
            v.hp_min = min(v.hp_min, hp)
            v.hp_out = hp
            v.died = v.died or bool(p["dead"])
            if cy >= scene.footprint.bottom and v.from_above:
                v.passed = frame

    def note_dig(self, p: dict[str, Any]) -> None:
        """The digging wand is being fired with the player at `p` (the caller decides what counts
        as digging: any frame the active wand holds the digging bolt and the cast key is down)."""
        cx, cy = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
        for scene, v in zip(self.scenes, self.visits, strict=True):
            if v.entered is not None and v.passed is None and scene.contains(cx, cy):
                v.dig_frames += 1

    @property
    def passed(self) -> list[Visit]:
        return [v for v in self.visits if v.passed is not None]

    def missed(self) -> list[str]:
        """Ids of the scenes the player did not go through."""
        return [v.eid for v in self.visits if v.passed is None]


def no_dig_mask(shape: tuple[int, int], scenes: list[Scene], box: tuple[int, int]) -> np.ndarray:
    """Box positions `(y, x)` (top-left corner of a `box` = (w, h) collision box) whose box
    overlaps the footprint of a scene that is not a dig zone. There the bot may walk, hop and
    fly but not tunnel: a tunnel under a scene's trap is not the encounter (the generator makes
    the footprint the only way down, not the obstacle inside it the only way across)."""
    height, width = shape
    w, h = box
    mask = np.zeros(shape, dtype=bool)
    for scene in scenes:
        if scene.dig_zone:
            continue
        f = scene.footprint
        mask[
            max(0, f.y - h + 1) : min(height, f.bottom), max(0, f.x - w + 1) : min(width, f.x + f.w)
        ] = True
    return mask


def door_of(
    grid: np.ndarray, mats: Materials, scene: Scene, *, top: bool
) -> tuple[int, int] | None:
    """Columns `[x0, x1)` of the widest run of open cells in the top (or bottom) row of the
    footprint: the scene's door shaft."""
    f = scene.footprint
    row = grid[f.y if top else f.bottom - 1, f.x : f.x + f.w]
    kind = mats.kind[row]
    open_ = ~((kind == STATIC) | (kind == POWDER))
    best: tuple[int, int] | None = None
    start = None
    for i, ok in enumerate([*open_.tolist(), False]):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return None if best is None else (f.x + best[0], f.x + best[1])


def exit_spot(
    grid: np.ndarray, mats: Materials, terrain: Terrain, scene: Scene, reach: int = 80
) -> tuple[int, int] | None:
    """A box position standing on the floor under the bottom door of the scene (the first one
    below it, `reach` rows at most)."""
    door = door_of(grid, mats, scene, top=False)
    if door is None:
        return None
    w = terrain.body.w
    x = (door[0] + door[1] - w) // 2
    ok = terrain.free & terrain.grounded
    for y in range(scene.footprint.bottom, min(terrain.height, scene.footprint.bottom + reach)):
        for dx in (0, -1, 1, -2, 2):
            if 0 <= x + dx < terrain.width and ok[y, x + dx]:
                return x + dx, y
    return None
