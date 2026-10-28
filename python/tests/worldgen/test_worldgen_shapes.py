"""Cave shape variety (shapes.py): halls, shafts, passages, alcoves, ledges, cracks."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from noitabench.worldgen.canvas import PLAYER_H, PLAYER_W
from noitabench.worldgen.config import Rate, ShapeStyle
from noitabench.worldgen.fill import smooth_cave, tileset_for
from noitabench.worldgen.shapes import shape_cave, widen
from noitabench.worldgen.tiles import tile_region
from scipy.ndimage import binary_erosion, distance_transform_edt, label

PLAYER = np.ones((PLAYER_H, PLAYER_W), dtype=bool)


def _tiled(bm, key="mine", seed=11) -> np.ndarray:
    biome = bm.biomes[key]
    x0, y0, x1, y1 = bm.region(key)
    cave, _ = tile_region(tileset_for(biome), seed, (x0, y0, x1, y1), (3, 4))
    cave = smooth_cave(cave, biome.tile, np.random.default_rng(seed))
    cave[: bm.ring] = cave[-bm.ring :] = False
    cave[:, : bm.ring] = cave[:, -bm.ring :] = False
    return cave


def _fit_labels(cave: np.ndarray) -> tuple[np.ndarray, int]:
    return label(binary_erosion(cave, structure=PLAYER))


def test_shaping_only_adds_open_cells_apart_from_ledges(bm):
    cave = _tiled(bm)
    style = dataclasses.replace(bm.biomes["mine"].shape, ledges=Rate())
    out = shape_cave(cave, style, bm.ring, np.random.default_rng(1))
    assert (out | cave).sum() == out.sum()  # nothing that was open got closed
    assert out.sum() > cave.sum()


def test_shaping_never_cuts_a_passage(bm):
    """Everything is attached to an open cell and ledges keep room around them: the
    player-fit areas of the tiled cave stay connected, ledges included."""
    for key in ("mine", "sand_cave", "oil_cave"):
        cave = _tiled(bm, key)
        out = shape_cave(cave, bm.biomes[key].shape, bm.ring, np.random.default_rng(2))
        before, n0 = _fit_labels(cave)
        after, _ = _fit_labels(out)
        for k in range(1, n0 + 1):
            part = after[(before == k) & (after > 0)]
            if part.size < 40:
                continue
            counts = np.bincount(part)
            counts[0] = 0
            assert part.size - counts.max() <= 20, f"{key}: area {k} fell apart"


def test_added_shapes_stay_inside_the_ring(bm):
    cave = _tiled(bm)
    style = dataclasses.replace(bm.biomes["mine"].shape, widen_max=0)  # widening is clipped later
    out = shape_cave(cave, style, bm.ring, np.random.default_rng(3))
    added = out & ~cave
    r = bm.ring + 2
    assert added.sum() > 500
    assert not added[:r].any() and not added[-r:].any()
    assert not added[:, :r].any() and not added[:, -r:].any()


def test_halls_are_much_bigger_than_a_tile_chamber(bm):
    style = ShapeStyle(halls=Rate(2.0, (90, 100), (40, 44)))
    cave = np.zeros((384, 256), dtype=bool)
    cave[190:194, 20:230] = True  # one corridor to hang the halls on
    out = shape_cave(cave, style, 6, np.random.default_rng(4))
    free = distance_transform_edt(out)
    assert free.max() >= 15  # a hall holds a disc of radius 15 or more


def test_shafts_and_passages_have_the_wanted_orientation(bm):
    cave = np.zeros((384, 256), dtype=bool)
    cave[190:200, 100:110] = True
    shafts = shape_cave(
        cave, ShapeStyle(shafts=Rate(4.0, (9, 9), (90, 90))), 6, np.random.default_rng(5)
    )
    passages = shape_cave(
        cave, ShapeStyle(passages=Rate(4.0, (9, 9), (90, 90))), 6, np.random.default_rng(5)
    )
    for out, tall in ((shafts, True), (passages, False)):
        ys, xs = np.nonzero(out & ~cave)
        assert ys.size > 0
        extent_y, extent_x = np.ptp(ys), np.ptp(xs)
        assert (extent_y > extent_x) if tall else (extent_x > extent_y)


def test_cracks_are_too_narrow_for_the_player(bm):
    cave = np.zeros((384, 256), dtype=bool)
    cave[190:210, 100:140] = True
    far = distance_transform_edt(~cave) >= 3  # beyond the mouth of a crack
    total = 0
    for seed in range(6):
        out = shape_cave(
            cave, ShapeStyle(cracks=Rate(0.3, (0, 0), (30, 30))), 6, np.random.default_rng(seed)
        )
        added = out & ~cave
        total += int(added.sum())
        fit = binary_erosion(out, structure=PLAYER)
        assert not (fit & added & far).any()  # no crack cell is part of a player-fit area
    assert total > 100


def test_widening_swells_tunnels_by_at_most_the_maximum():
    cave = np.zeros((120, 200), dtype=bool)
    cave[58:66, 10:190] = True
    out = widen(cave, 3, 30.0, np.random.default_rng(7))
    widths = out.sum(axis=0)[10:190]
    assert widths.min() >= 8 and widths.max() <= 8 + 2 * 3
    assert widths.max() > widths.min()  # varying width
    assert widen(cave, 0, 30.0, np.random.default_rng(7)).sum() == cave.sum()


@pytest.mark.parametrize("key", ["mine", "coal_pit", "sand_cave", "swamp", "oil_cave"])
def test_every_tiled_biome_has_varied_cave_widths(bm, key):
    """Row 2 of cp1-feedback: wide and narrow passages in the same biome."""
    cave = _tiled(bm, key, seed=21)
    out = shape_cave(cave, bm.biomes[key].shape, bm.ring, np.random.default_rng(21))
    dist = distance_transform_edt(out)
    skeleton = dist[
        out & (dist >= np.maximum.reduce([np.roll(dist, s, a) for a in (0, 1) for s in (1, -1)]))
    ]
    assert np.percentile(skeleton, 95) >= 2.0 * np.percentile(skeleton, 10)
