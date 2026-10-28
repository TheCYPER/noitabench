"""The Python surface of the simulation (contract section 6)."""

from __future__ import annotations

import json
from pathlib import Path

import noitabench_core
import pytest
from noitabench.env import Env
from PIL import Image

REPO = Path(__file__).resolve().parents[3]


def make_world() -> noitabench_core.Env:
    env = noitabench_core.Env(64, 48, 3)
    env.fill_rect(0, 40, 64, 8, "rock")
    env.paint(32, 10, 4, "water")
    return env


def test_contract_methods_exist() -> None:
    env = noitabench_core.Env(8, 8, 1)
    for name in (
        "step_frames", "paint", "grid", "cell", "snapshot", "restore", "events",
        "start_recording", "stop_recording",
    ):  # fmt: skip
        assert callable(getattr(env, name)), name
    assert callable(noitabench_core.Env.from_world)


def test_empty_world_is_air() -> None:
    env = noitabench_core.Env(10, 6, 1)
    assert env.grid() == bytes(60)
    assert (env.width, env.height, env.frame, env.seed) == (10, 6, 0, 1)


def test_materials_match_the_content_file() -> None:
    """Catches a stale build: re-run maturin develop after editing content/."""
    file = json.loads((REPO / "content" / "materials.json").read_text())
    keys = [m["key"] for m in sorted(file["materials"], key=lambda m: m["index"])]
    assert noitabench_core.Env(1, 1, 0).material_keys() == keys


def test_paint_step_and_cell() -> None:
    env = make_world()
    keys = env.material_keys()
    assert keys[env.grid()[10 * 64 + 32]] == "water"
    env.step_frames(120)
    assert env.frame == 120
    below = env.cell(32, 39)
    assert below["material"] == "water" and below["burning"] is False
    assert below["index"] == keys.index("water")
    assert env.cell(32, 40)["material"] == "rock"


def test_paint_radius_zero_and_clipping() -> None:
    env = noitabench_core.Env(5, 5, 1)
    env.paint(0, 0, 0, "sand")
    env.paint(4, 4, 3, "rock")  # reaches past the world edge: clipped
    keys = env.material_keys()
    assert keys[env.grid()[0]] == "sand"
    assert keys[env.grid()[5 * 4 + 4]] == "rock"
    assert env.grid().count(keys.index("rock")) == 25 - 1 - sum(
        1
        for y in range(5)
        for x in range(5)
        if (x, y) != (0, 0) and (x - 4) ** 2 + (y - 4) ** 2 > 9
    )


def test_cell_reports_lifetime_and_burning() -> None:
    env = noitabench_core.Env(8, 8, 1)
    env.paint(4, 4, 0, "steam")
    assert 900 <= env.cell(4, 4)["lifetime"] <= 1130  # 1000 frames, +-12 % jitter
    env.paint(2, 7, 0, "wood")
    assert env.ignite(2, 7) is True and env.ignite(2, 7) is False
    assert env.cell(2, 7)["burning"] is True


def test_errors_are_value_errors_with_a_hint() -> None:
    env = noitabench_core.Env(8, 8, 1)
    with pytest.raises(ValueError, match="unknown material `unobtanium`; known: air"):
        env.paint(1, 1, 1, "unobtanium")
    with pytest.raises(ValueError, match="outside the 8x8 world"):
        env.cell(8, 0)
    with pytest.raises(ValueError, match="world size"):
        noitabench_core.Env(0, 5, 1)
    with pytest.raises(ValueError, match="radius must be"):
        env.paint(1, 1, -1, "sand")
    with pytest.raises(ValueError, match="no recording"):
        env.stop_recording()


def test_events_are_dicts_and_drain() -> None:
    env = noitabench_core.Env(40, 30, 2)
    env.fill_rect(0, 25, 40, 5, "rock")
    env.fill_rect(10, 20, 6, 5, "lava")
    env.fill_rect(10, 15, 6, 5, "water")
    env.step_frames(60)
    events = env.events()
    assert events and all("frame" in e and "type" in e for e in events)
    assert {e["type"] for e in events} >= {"reaction"}
    reaction = next(e for e in events if e["type"] == "reaction")
    assert reaction["id"] in {"r01", "r03", "r14"} and isinstance(reaction["x"], int)
    assert env.events() == []


def test_explode_digs_and_reports() -> None:
    env = noitabench_core.Env(40, 40, 1)
    env.fill_rect(0, 0, 40, 40, "ground")
    destroyed = env.explode(20, 20, 6, 400_000, 10, 0)
    assert destroyed > 80
    assert env.cell(20, 20)["material"] == "air"
    explosion = next(e for e in env.events() if e["type"] == "explosion")
    assert explosion["destroyed"] == destroyed
    with pytest.raises(ValueError, match="radius"):
        env.explode(1, 1, 0, 1, 1)
    with pytest.raises(ValueError, match="max_durability must be 0..=255"):
        env.explode(1, 1, 2, 1, 300)
    with pytest.raises(ValueError, match="fire_percent must be 0..=100"):
        env.explode(1, 1, 2, 1, 5, 101)
    with pytest.raises(ValueError, match="ray_energy"):
        env.explode(1, 1, 2, -5, 5)
    with pytest.raises(ValueError, match="centre"):
        env.paint(-(2**31), 0, 1, "sand")


def test_snapshot_restore_roundtrip() -> None:
    env = make_world()
    env.step_frames(5)  # the water is still falling
    blob = env.snapshot()
    reference = env.grid()
    env.step_frames(10)
    assert env.grid() != reference
    env.restore(blob)
    assert (env.frame, env.grid()) == (5, reference)
    with pytest.raises(ValueError, match="snapshot"):
        env.restore(b"garbage")


def test_wrapper_mirrors_the_core() -> None:
    env = Env(32, 24, 5)
    env.fill_rect(0, 20, 32, 4, "rock")
    env.paint(16, 5, 2, "sand")
    env.step_frames(40)
    arr = env.grid_array()
    assert arr.shape == (24, 32) and arr.dtype.name == "uint8"
    assert bytes(arr.flatten()) == env.grid()
    assert env.cell(16, 19)["material"] == "sand"
    assert env.width == 32 and env.height == 24 and env.frame == 40


def write_world(tmp: Path, indices: bytes, w: int, h: int, rule_seed: int = 9) -> tuple[Path, Path]:
    materials = json.loads((REPO / "content" / "materials.json").read_text())["materials"]
    img = Image.frombytes("P", (w, h), indices)
    palette: list[int] = []
    for m in materials:
        palette += [int(m["color"][i : i + 2], 16) for i in (1, 3, 5)]
    img.putpalette(palette + [0] * (768 - len(palette)))
    png, js = tmp / "w.png", tmp / "w.json"
    img.save(png)
    js.write_text(
        json.dumps(
            {
                "format": "cogbench-world/0", "seed": 5, "rule_seed": rule_seed, "width": w,
                "height": h, "biome_cell_size": 128, "biome_map": [], "markers": [],
            }
        )
    )  # fmt: skip
    return png, js


def test_from_world_loads_an_indexed_png(tmp_path: Path) -> None:
    keys = noitabench_core.Env(1, 1, 0).material_keys()
    w, h = 20, 12
    px = bytearray(w * h)
    px[(h - 1) * w :] = bytes([keys.index("rock")]) * w
    px[3 * w + 5] = keys.index("sand")
    png, js = write_world(tmp_path, bytes(px), w, h)
    env = noitabench_core.Env.from_world(str(png), str(js), 11)
    assert (env.width, env.height, env.seed, env.rule_seed) == (w, h, 11, 9)
    assert env.grid() == bytes(px)
    env.step_frames(30)
    assert env.cell(5, h - 2)["material"] == "sand"
    default_seed = noitabench_core.Env.from_world(str(png), str(js))
    assert default_seed.seed == 5


def test_from_world_errors(tmp_path: Path) -> None:
    png, js = write_world(tmp_path, bytes(16), 4, 4)
    with pytest.raises(FileNotFoundError):
        noitabench_core.Env.from_world(str(tmp_path / "nope.png"), str(js))
    rgb = tmp_path / "rgb.png"
    Image.new("RGB", (4, 4)).save(rgb)
    with pytest.raises(ValueError, match="8-bit indexed"):
        noitabench_core.Env.from_world(str(rgb), str(js))
    bad = tmp_path / "bad.json"
    bad.write_text(js.read_text().replace('"width": 4', '"width": 5'))
    with pytest.raises(ValueError, match="does not match"):
        noitabench_core.Env.from_world(str(png), str(bad))
