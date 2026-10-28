"""Five short scenes that show the material rules, recorded for the web viewer.

    python -m noitabench demo materials

writes `runs/demo-<scene>/` (format `cogbench-rec/0`, contract section 5). Every scene is a
256 x 192 world, a few seconds long, and fully determined by its seed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from noitabench.env import Env

WIDTH, HEIGHT = 256, 192
FRAME_STRIDE = 2
# Keeps two recordings of the same scene byte-identical (meta.json is the only place a clock
# would otherwise leak in).
CREATED = "2026-10-26T00:00:00Z"

Action = Callable[[Env], None]


@dataclass(frozen=True)
class Scene:
    name: str
    title: str
    frames: int
    setup: Callable[[Env], None]
    # (frame, action) pairs: the action runs just before that frame is simulated.
    script: tuple[tuple[int, Action], ...] = ()


def _border(env: Env, thickness: int = 6) -> None:
    env.fill_rect(0, 0, WIDTH, thickness, "rock")
    env.fill_rect(0, HEIGHT - thickness, WIDTH, thickness, "rock")
    env.fill_rect(0, 0, thickness, HEIGHT, "rock")
    env.fill_rect(WIDTH - thickness, 0, thickness, HEIGHT, "rock")


# -- 1. lava meets water ------------------------------------------------------------------------


def _lava_water(env: Env) -> None:
    _border(env)
    env.fill_rect(6, 150, 244, 36, "rock")  # floor
    env.fill_rect(6, 112, 34, 38, "rock")  # basin walls
    env.fill_rect(216, 112, 34, 38, "rock")
    env.fill_rect(40, 122, 176, 28, "water")
    # A shelf with a gap in the middle; lava piled on it runs to the gap and pours into the water.
    env.fill_rect(6, 62, 100, 7, "rock")
    env.fill_rect(146, 62, 104, 7, "rock")
    env.fill_rect(10, 44, 90, 18, "lava")
    env.fill_rect(152, 44, 94, 18, "lava")


# -- 2. oil floats up through water, then burns ------------------------------------------------------


def _oil_fire(env: Env) -> None:
    _border(env)
    env.fill_rect(6, 150, 244, 36, "rock")
    env.fill_rect(40, 70, 8, 80, "rock")
    env.fill_rect(208, 70, 8, 80, "rock")
    env.fill_rect(48, 100, 160, 40, "water")
    env.fill_rect(48, 140, 160, 10, "oil")  # starts under the water and bubbles up


def _light_the_slick(env: Env) -> None:
    for x in (70, 128, 186):
        env.paint(x, 99, 2, "fire")


# -- 3. acid eats ground and rock until it is used up, but not brick -------------------------------


def _acid_rock(env: Env) -> None:
    _border(env)
    env.fill_rect(6, 90, 244, 18, "ground")
    env.fill_rect(6, 108, 244, 40, "rock")
    env.fill_rect(6, 148, 244, 38, "brick")
    # A notch in the top, full of acid. Every cell of acid dissolves one cell of ground or rock
    # and turns into gas, so the pit ends up exactly as big as the pool was.
    env.fill_rect(104, 90, 48, 12, "acid")


# -- 4. gunpowder digs a crater ---------------------------------------------------------------------


def _gunpowder_crater(env: Env) -> None:
    env.fill_rect(0, 90, WIDTH, HEIGHT - 90, "ground")
    env.fill_rect(0, 144, WIDTH, 10, "rock")
    env.fill_rect(0, 164, WIDTH, HEIGHT - 164, "brick")
    env.fill_rect(124, 90, 8, 54, "air")  # a shaft in the ground ...
    env.fill_rect(124, 104, 8, 40, "gunpowder")  # ... packed with gunpowder


def _spark(env: Env) -> None:
    env.ignite(128, 104)


def _drop_sand(env: Env) -> None:
    env.paint(128, 60, 14, "sand")


# -- 5. water puts out burning wood ---------------------------------------------------------------


def _scaffold(env: Env, x: int) -> None:
    """A thin wooden frame (every cell touches air, so it all burns), lit all over."""
    parts = [(x, 100, 2, 70), (x + 62, 100, 2, 70)]
    parts += [(x + 2, y, 60, 2) for y in (100, 134, 168)]
    for px, py, w, h in parts:
        env.fill_rect(px, py, w, h, "wood")
    for px, py, w, h in parts:
        for yy in range(py, py + h):
            for xx in range(px, px + w):
                env.ignite(xx, yy)


def _water_extinguish(env: Env) -> None:
    env.fill_rect(0, 170, WIDTH, HEIGHT - 170, "ground")
    env.fill_rect(124, 80, 8, 90, "rock")  # a wall between the two frames
    _scaffold(env, 30)  # this one gets water
    _scaffold(env, 160)  # this one burns down


def _flood(env: Env) -> None:
    """Water appears inside the left frame: its planks hold it, and it touches burning wood."""
    for y in (102, 136):
        env.fill_rect(32, y, 60, 32, "water")


SCENES: dict[str, Scene] = {
    s.name: s
    for s in (
        Scene("lava-water", "Lava pouring into water makes rock and steam", 480, _lava_water),
        Scene(
            "oil-fire",
            "Oil floats up through water and burns",
            600,
            _oil_fire,
            ((150, _light_the_slick),),
        ),
        Scene(
            "acid-rock",
            "Acid corrodes ground and rock until it is used up, but never brick",
            480,
            _acid_rock,
        ),
        Scene(
            "gunpowder-crater",
            "Gunpowder explodes and digs a crater",
            420,
            _gunpowder_crater,
            ((30, _spark), (200, _drop_sand)),
        ),
        Scene(
            "water-extinguish",
            "Water puts out burning wood; the frame without water burns down",
            640,
            _water_extinguish,
            ((160, _flood),),
        ),
    )
}


def run_scene(scene: Scene, out_dir: str | Path, seed: int = 1) -> dict[str, Any]:
    """Simulate one scene and write `<out_dir>/demo-<name>/`; returns a summary dict."""
    run_dir = Path(out_dir) / f"demo-{scene.name}"
    env = Env(WIDTH, HEIGHT, seed)
    scene.setup(env)
    env.start_recording(
        run_dir,
        FRAME_STRIDE,
        run_id=f"demo-{scene.name}",
        notes=scene.title,
        created=CREATED,
    )
    pending = sorted(scene.script, key=lambda item: item[0])
    events = 0
    for frame in range(scene.frames):
        while pending and pending[0][0] == frame:
            pending.pop(0)[1](env)
        env.step_frames(1)
        events += len(env.events())
    summary = env.stop_recording()
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
