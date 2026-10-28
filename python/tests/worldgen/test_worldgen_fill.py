"""Material filling of the solid cells of a biome region (fill.py)."""

from __future__ import annotations

import dataclasses

import numpy as np
from noitabench.worldgen.config import FillEntry
from noitabench.worldgen.fill import fill_solid
from scipy.ndimage import distance_transform_edt, label


def _cave(shape=(160, 160)) -> np.ndarray:
    cave = np.zeros(shape, dtype=bool)
    cave[:, 70:90] = True  # one vertical shaft, the rest is solid
    return cave


def test_material_shares_follow_the_weights(bm, mats):
    plain = dataclasses.replace(
        bm.biomes["mine"].fill,
        materials=(FillEntry("ground", 0.7), FillEntry("rock", 0.3)),
        edge_depth=0,
        speckle=0.0,
        veins=(),
    )
    grid = fill_solid(_cave(), plain, mats, np.random.default_rng(1))
    solid = ~_cave()
    assert (grid[~solid] == mats.air).all()
    share = float((grid[solid] == mats["ground"]).mean())
    assert abs(share - 0.7) < 0.02
    assert set(np.unique(grid[solid])) == {mats["ground"], mats["rock"]}


def test_buried_materials_stay_away_from_caves(bm, mats):
    style = dataclasses.replace(
        bm.biomes["mine"].fill,
        materials=(FillEntry("ground", 0.5), FillEntry("coal", 0.5, buried=6)),
        edge_depth=0,
        veins=(),
    )
    cave = _cave()
    grid = fill_solid(cave, style, mats, np.random.default_rng(2))
    dist = distance_transform_edt(~cave)
    coal = grid == mats["coal"]
    assert coal.sum() > 500
    assert dist[coal].min() >= 6


def test_edge_material_lines_the_caves(bm, mats):
    style = dataclasses.replace(
        bm.biomes["mine"].fill,
        materials=(FillEntry("rock", 1.0),),
        edge_material="ground",
        edge_depth=2,
        edge_prob=1.0,
        veins=(),
    )
    cave = _cave()
    grid = fill_solid(cave, style, mats, np.random.default_rng(3))
    dist = distance_transform_edt(~cave)
    assert (grid[(dist > 0) & (dist <= 2)] == mats["ground"]).all()
    assert (grid[dist > 3] == mats["rock"]).all()


def test_the_same_stream_gives_the_same_fill(bm, mats):
    style = bm.biomes["swamp"].fill
    a = fill_solid(_cave(), style, mats, np.random.default_rng(9))
    b = fill_solid(_cave(), style, mats, np.random.default_rng(9))
    assert np.array_equal(a, b)


def _runs(mask: np.ndarray, axis: int) -> float:
    """Mean length of the runs of True cells along ``axis``."""
    m = mask if axis == 1 else mask.T
    padded = np.pad(m, ((0, 0), (1, 1))).astype(np.int8)
    d = np.diff(padded, axis=1)
    starts, ends = np.count_nonzero(d == 1), np.count_nonzero(d == -1)
    assert starts == ends and starts > 0
    return float(m.sum() / starts)


def test_strata_are_wide_layers_not_speckle(bm, mats):
    """Cp1 feedback row 1: each material forms wide layers (long runs along x, shorter along y)."""
    style = dataclasses.replace(bm.biomes["mine"].fill, veins=(), edge_depth=0, speckle=0.0)
    grid = fill_solid(np.zeros((200, 256), dtype=bool), style, mats, np.random.default_rng(4))
    for key in ("ground", "rock"):
        mask = grid == mats[key]
        assert _runs(mask, 1) > 1.5 * _runs(mask, 0), key  # layers: wider than tall
        assert _runs(mask, 1) > 40, key  # and not made of single cells


def test_strata_transitions_are_not_salt_and_pepper(bm, mats):
    style = dataclasses.replace(bm.biomes["mine"].fill, veins=(), edge_depth=0)
    grid = fill_solid(np.zeros((200, 256), dtype=bool), style, mats, np.random.default_rng(5))
    boundary = (grid[:, 1:] != grid[:, :-1]).mean() + (grid[1:] != grid[:-1]).mean()
    assert boundary < 0.12, f"{boundary:.2f} boundary cells per cell: looks like speckle"


def test_veins_are_thin_elongated_and_buried(bm, mats):
    style = bm.biomes["mine"].fill
    assert style.veins and style.veins[0].material == "coal"
    cave = _cave((200, 256))
    plain = dataclasses.replace(style, veins=(), edge_depth=0)
    base = fill_solid(cave, plain, mats, np.random.default_rng(6))
    grid = fill_solid(
        cave, dataclasses.replace(style, edge_depth=0), mats, np.random.default_rng(6)
    )
    coal = (grid == mats["coal"]) & (base != mats["coal"])
    assert coal.sum() > 150
    dist = distance_transform_edt(~cave)
    assert dist[coal].min() >= style.veins[0].buried
    assert distance_transform_edt(coal).max() <= 4.5  # thin: no blob thicker than ~9 cells
    lab, n = label(coal, structure=np.ones((3, 3)))
    longest = max(int(np.ptp(np.nonzero(lab == k)[1]) + 1) for k in range(1, n + 1))
    assert longest >= 24  # and long
    assert coal.mean() < 0.2  # a mineral, not a stratum


def test_without_veins_there_is_no_mineral(bm, mats):
    style = dataclasses.replace(bm.biomes["swamp"].fill, veins=())
    grid = fill_solid(_cave(), style, mats, np.random.default_rng(7))
    assert not (grid == mats["coal"]).any()
