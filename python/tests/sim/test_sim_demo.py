"""`python -m noitabench demo materials`: five recordings that show the material rules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from noitabench.demo.materials import SCENES, run_all
from sim_recording_reader import read_events, read_frames, read_meta


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("runs")
    summaries = run_all(out, seed=1)
    assert [Path(s["dir"]).name for s in summaries] == [f"demo-{n}" for n in SCENES]
    return out


def test_there_are_five_scenes() -> None:
    assert sorted(SCENES) == [
        "acid-rock", "gunpowder-crater", "lava-water", "oil-fire", "water-extinguish",
    ]  # fmt: skip


def test_every_recording_parses_and_ends_on_the_last_frame(runs: Path) -> None:
    for name, scene in SCENES.items():
        run = runs / f"demo-{name}"
        meta = read_meta(run)
        frames = read_frames(run)
        assert meta["run_id"] == f"demo-{name}" and meta["world"] == {"width": 256, "height": 192}
        assert frames[0].frame == 0 and frames[-1].frame == scene.frames
        assert (frames[0].w, frames[0].h) == (256, 192)
        assert meta["frame_count"] == len(frames)


def reaction_ids(run: Path) -> set[str]:
    return {e["id"] for e in read_events(run) if e["type"] == "reaction"}


def test_lava_meets_water_makes_rock_and_steam(runs: Path) -> None:
    run = runs / "demo-lava-water"
    assert "r01" in reaction_ids(run)
    keys = _keys()
    first, last = read_frames(run)[0].pixels, read_frames(run)[-1].pixels
    for material in ("rock", "steam"):
        i = keys.index(material)
        assert last.count(i) > first.count(i), material
    assert last.count(keys.index("lava")) < first.count(keys.index("lava")) + 1


def test_oil_floats_up_and_burns(runs: Path) -> None:
    run = runs / "demo-oil-fire"
    keys = _keys()
    frames = {f.frame: f.pixels for f in read_frames(run)}

    def oil_below_water(pixels: bytes) -> tuple[int, int]:
        """(oil cells, oil cells that have water above them in their column) in the pool."""
        oil = inverted = 0
        for x in range(48, 208):
            column = [keys[pixels[y * 256 + x]] for y in range(100, 150)]
            water_top = column.index("water") if "water" in column else len(column)
            oil += column.count("oil")
            inverted += sum(1 for i, k in enumerate(column) if k == "oil" and i > water_top)
        return oil, inverted

    oil, inverted = oil_below_water(frames[0])
    assert oil > 0 and inverted == oil, "the oil starts under the water"
    oil, inverted = oil_below_water(frames[140])
    assert oil > 0 and inverted == 0, "and has risen to float on top before it is lit"
    ignites = [e for e in read_events(run) if e["type"] == "ignite"]
    assert len(ignites) > 100 and all(e["material"] == "oil" for e in ignites)
    assert min(e["frame"] for e in ignites) >= 150


def test_acid_dissolves_one_cell_per_cell_of_acid_and_leaves_brick(runs: Path) -> None:
    run = runs / "demo-acid-rock"
    assert "r04" in reaction_ids(run)
    keys = _keys()
    frames = read_frames(run)
    first, last = frames[0].pixels, frames[-1].pixels

    def count(pixels: bytes, key: str) -> int:
        return pixels.count(keys.index(key))

    acid = count(first, "acid")
    assert acid == 48 * 12
    assert count(last, "acid") == 0, "the acid is used up"
    ground = count(first, "ground") - count(last, "ground")
    rock = count(first, "rock") - count(last, "rock")
    assert ground + rock == acid, "one dissolved cell for every cell of acid"
    assert rock > 100, "the pit got through the ground into the rock"
    assert count(last, "brick") == count(first, "brick")


def test_gunpowder_explodes_and_digs(runs: Path) -> None:
    run = runs / "demo-gunpowder-crater"
    explosions = [e for e in read_events(run) if e["type"] == "explosion"]
    assert len(explosions) >= 3
    keys = _keys()
    frames = {f.frame: f.pixels for f in read_frames(run)}
    ground = keys.index("ground")
    assert frames[190].count(ground) < frames[0].count(ground) - 300
    assert frames[190].count(keys.index("gunpowder")) == 0
    assert frames[420].count(keys.index("sand")) > 0
    assert frames[420].count(keys.index("brick")) == frames[0].count(keys.index("brick"))


def test_water_puts_out_burning_wood(runs: Path) -> None:
    run = runs / "demo-water-extinguish"
    events = read_events(run)
    out = [e for e in events if e["type"] == "extinguish"]
    assert len(out) > 100 and all(e["material"] == "wood" for e in out)
    assert min(e["frame"] for e in out) >= 160
    keys = _keys()
    last = read_frames(run)[-1].pixels
    wood = keys.index("wood")
    left = sum(1 for y in range(192) for x in range(124) if last[y * 256 + x] == wood)
    right = sum(1 for y in range(192) for x in range(132, 256) if last[y * 256 + x] == wood)
    assert left > 3 * right, "the frame with water survives, the other burns down"


def test_cli_writes_runs_demo_directories(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "noitabench", "demo", "materials", "--out", str(tmp_path),
         "--only", "acid-rock"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert "demo-acid-rock" in proc.stdout
    assert (tmp_path / "demo-acid-rock" / "frames.bin").stat().st_size > 1000


def test_cli_rejects_unknown_commands() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "noitabench", "frobnicate"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2 and "unknown command" in proc.stderr


def _keys() -> list[str]:
    import noitabench_core

    return noitabench_core.Env(1, 1, 0).material_keys()
