"""Preview rendering and the command line (preview.py, cli.py)."""

from __future__ import annotations

import numpy as np
import pytest
from noitabench.worldgen.cli import main
from noitabench.worldgen.preview import render_preview, terrain_image
from PIL import Image


def test_plain_preview_is_the_upscaled_terrain(world_a, mats):
    img = render_preview(world_a, mats, scale=2, overlay=False)
    assert img.size == (768 * 2, 1664 * 2)
    assert np.array_equal(np.array(img), np.array(terrain_image(world_a, mats, 2, shade=False)))


def test_overlay_preview_adds_a_header_and_marks_the_markers(world_a, mats, bm):
    plain = render_preview(world_a, mats, bm, scale=2, overlay=False)
    img = render_preview(world_a, mats, bm, scale=2, overlay=True)
    assert img.width == plain.width and img.height > plain.height
    body = np.array(img)[img.height - plain.height :]
    assert (body != np.array(plain)).any(axis=2).mean() > 0.002  # overlay pixels exist


def test_preview_command_writes_images(tmp_path, capsys):
    rc = main(
        [
            "preview",
            "--seed",
            "3",
            "--out",
            str(tmp_path),
            "--scale",
            "1",
            "--plain",
            "--write-world",
        ]
    )
    assert rc == 0
    for name in ("world_seed3.png", "world_seed3_plain.png", "world_seed3.json"):
        assert (tmp_path / name).exists(), name
    assert Image.open(tmp_path / "world_seed3_plain.png").size == (768, 1664)
    assert "seed 3" in capsys.readouterr().out


def test_check_command_passes_and_reports_determinism(capsys):
    rc = main(["check", "--seeds", "3", "--start", "100", "--jobs", "1", "--determinism", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "passed 3  failed 0" in out and "1/1 seeds byte-identical in a fresh process" in out


def test_generate_command_writes_the_file_pair(tmp_path):
    assert main(["generate", "--seed", "5", "--out", str(tmp_path), "--name", "w5"]) == 0
    assert (tmp_path / "w5.png").exists() and (tmp_path / "w5.json").exists()


def test_tiles_command_writes_a_sheet(tmp_path):
    assert main(["tiles", "--biome", "coal_pit", "--out", str(tmp_path)]) == 0
    assert Image.open(tmp_path / "tiles_coal_pit.png").width > 500


def test_tiles_command_explains_that_room_biomes_have_no_tiles(tmp_path):
    with pytest.raises(SystemExit, match="rooms"):
        main(["tiles", "--biome", "workshop", "--out", str(tmp_path)])


def test_preview_crops_are_plain_close_ups(tmp_path, world_a, mats):
    rc = main(["preview", "--seed", "3", "--out", str(tmp_path), "--scale", "1",
               "--crop", "0,1152,256,1280", "--crop-scale", "2"])  # fmt: skip
    assert rc == 0
    img = Image.open(tmp_path / "world_seed3_crop1.png")
    assert img.size == (512, 256)
    expected = terrain_image(world_a, mats, 2, shade=False).crop((0, 2304, 512, 2560))
    assert np.array_equal(np.array(img), np.array(expected))
    with pytest.raises(SystemExit):
        main(["preview", "--seed", "3", "--crop", "10,10,5,5"])


def test_scene_command_renders_a_lab_world(tmp_path):
    rc = main(["scene", "E02", "--variant", "3", "--rule-seed", "7",
               "--out", str(tmp_path), "--scale", "1", "--write-world"])  # fmt: skip
    assert rc == 0
    assert Image.open(tmp_path / "scene_E02_v3_r7.png").width > 100
    assert (tmp_path / "scene_E02_v3.png").exists() and (tmp_path / "scene_E02_v3.json").exists()
    with pytest.raises(SystemExit, match="unknown encounter"):
        main(["scene", "E99", "--out", str(tmp_path)])


def test_check_command_takes_a_rule_seed_and_no_strength(capsys):
    rc = main(["check", "--seeds", "2", "--start", "5", "--jobs", "1", "--determinism", "0",
               "--rule-seed", "7"])  # fmt: skip
    out = capsys.readouterr().out
    assert rc == 0 and "rule seed 7" in out and "strength" not in out
    assert "passed 2  failed 0" in out
    for argv in (
        ["preview", "--seed", "1"],
        ["check"],
        ["generate", "--seed", "1"],
        ["scene", "E02"],
    ):
        with pytest.raises(SystemExit):  # argparse rejects the old option
            main([*argv, "--strength", "1"])
        assert "unrecognized arguments: --strength" in capsys.readouterr().err
