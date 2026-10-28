"""Herringbone Wang tiles: geometry, edge matching, tile content (tiles.py)."""

from __future__ import annotations

import numpy as np
import pytest
from noitabench.worldgen import tiles
from noitabench.worldgen.fill import tileset_for
from noitabench.worldgen.tiles import KIND_H, KIND_V, N_COLORS, SLOTS, TileSet

BIOMES = [
    "coal_pit",
    "mine",
    "sand_cave",
    "fungal",
    "swamp",
    "oil_cave",
    "lava_deeps",
]  # the two 'rooms' biomes (workshop, brick_ruins) have no tiles


def test_herringbone_layout_covers_every_unit_cell_exactly_once():
    u0, u1, v0, v1 = -3, 17, -2, 14
    cover = np.zeros((v1 - v0, u1 - u0), dtype=int)
    for kind, u, v in tiles.layout(u0, u1, v0, v1):
        tw, th = tiles.tile_size_units(kind)
        for du in range(tw):
            for dv in range(th):
                if u0 <= u + du < u1 and v0 <= v + dv < v1:
                    cover[v + dv - v0, u + du - u0] += 1
    assert cover.min() == 1 and cover.max() == 1


def test_every_interior_edge_segment_is_shared_by_exactly_two_tiles():
    owners: dict[tuple, int] = {}
    for kind, u, v in tiles.layout(-2, 24, -2, 24):
        for seg in tiles.segment_ids(kind, u, v):
            owners[seg] = owners.get(seg, 0) + 1
    assert max(owners.values()) == 2
    for (orient, x, y), n in owners.items():
        if 4 <= x < 18 and 4 <= y < 18:
            assert n == 2, f"segment {(orient, x, y)} is used by {n} tiles"


def test_neighbours_match_the_herringbone_pattern():
    # a horizontal tile is flanked by a vertical tile on each side (same unit row)
    left = [(k, u, v) for k, u, v in tiles.layout(0, 12, 0, 12) if k == KIND_V and (u, v) == (3, 0)]
    assert left, "vertical tile anchored at (3, 0) must exist when the horizontal one is at (0, 0)"
    assert (KIND_H, 0, 0) in set(tiles.layout(0, 12, 0, 12))


@pytest.mark.parametrize("key", BIOMES)
def test_tiled_region_has_matching_edges(key, bm):
    biome = bm.biomes[key]
    rect = bm.region(key)
    ts = tileset_for(biome)
    s = biome.tile.short_side
    region, placements = tiles.tile_region(ts, 12345, rect, (s // 3, s // 2))
    checked = [
        p
        for p in placements
        if p.x >= rect[0] and p.y >= rect[1] and p.x + p.w <= rect[2] and p.y + p.h <= rect[3]
    ]
    assert len(checked) >= 6
    assert tiles.seam_errors(region, rect, placements, biome.tile) == 0


def test_seam_check_detects_a_broken_seam(bm):
    biome = bm.biomes["mine"]
    rect = bm.region("mine")
    ts = tileset_for(biome)
    region, placements = tiles.tile_region(ts, 7, rect, (5, 9))
    assert tiles.seam_errors(region, rect, placements, biome.tile) == 0
    p = next(
        q
        for q in placements
        if q.x > rect[0] + 60
        and q.y > rect[1] + 60
        and q.x + q.w < rect[2] - 60
        and q.y + q.h < rect[3] - 60
    )
    broken = region.copy()
    broken[p.y - rect[1] : p.y - rect[1] + 6, p.x - rect[0] : p.x - rect[0] + p.w] ^= (
        True  # flip the top band
    )
    assert tiles.seam_errors(broken, rect, placements, biome.tile) > 0


@pytest.mark.parametrize("key", ["mine", "coal_pit", "lava_deeps"])
@pytest.mark.parametrize("kind", [KIND_H, KIND_V])
def test_tile_strips_equal_their_edge_colour_pattern(key, kind, bm):
    ts = tileset_for(bm.biomes[key])
    rng = np.random.default_rng(5)
    for _ in range(12):
        edges = tuple(int(c) for c in rng.integers(0, N_COLORS, 6))
        tile = ts.tile(kind, edges, int(rng.integers(0, 2)))
        for i, color in enumerate(edges):
            strip = ts.strip(tile, kind, i)
            assert strip.shape == (ts.style.band, ts.style.short_side)
            assert (strip == ts.patterns[color][None, :]).all(), (
                f"{key} kind {kind} slot {SLOTS[kind][i].name}"
            )


def test_tile_corners_are_closed_and_openings_wide_enough(bm):
    ts = tileset_for(bm.biomes["mine"])
    st = ts.style
    for color in range(1, N_COLORS):
        pat = ts.patterns[color]
        assert pat.sum() >= st.tunnel_min
        assert not pat[: st.margin].any() and not pat[-st.margin :].any()
    assert not ts.patterns[0].any()
    edges = (1, 2, 3, 4, 1, 2)
    tile = ts.tile(KIND_H, edges, 0)
    b = st.band
    for ys in (slice(0, b), slice(-b, None)):
        for xs in (slice(0, b), slice(-b, None)):
            assert not tile[ys, xs].any()


def test_tiles_are_deterministic_and_independent_of_the_cache(bm):
    biome = bm.biomes["swamp"]
    a = TileSet(biome.tile, 99)
    b = TileSet(biome.tile, 99)
    edges = (0, 1, 2, 3, 4, 1)
    first = a.tile(KIND_V, edges, 1)
    b.tile(KIND_H, (1, 1, 1, 1, 1, 1), 0)  # fill the other cache differently first
    assert np.array_equal(first, b.tile(KIND_V, edges, 1))
    assert not np.array_equal(first, TileSet(biome.tile, 100).tile(KIND_V, edges, 1))


def test_open_fraction_of_every_biome_is_cave_like(bm):
    for key in BIOMES:
        biome = bm.biomes[key]
        region, _ = tiles.tile_region(tileset_for(biome), 1, bm.region(key), (3, 4))
        assert 0.15 < region.mean() < 0.65, f"{key}: open fraction {region.mean():.2f}"
