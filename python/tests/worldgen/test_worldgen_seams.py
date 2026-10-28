"""Brick seams and shells (layers.py) and the bypass check (checks.py): a must-pass scene is a true
chokepoint for a player who digs but cannot break brick (CP2 decision, 2026-10-27), and the hall
above the sealed deep is a wand-editing station."""

from __future__ import annotations

import copy
import dataclasses

import numpy as np
import pytest
from noitabench.worldgen import checks
from noitabench.worldgen.canvas import Canvas, GenerationFailure
from noitabench.worldgen.checks import EIGHT, passable_mask, run_checks
from noitabench.worldgen.encounter_defs import load_encounters
from noitabench.worldgen.layers import build_seam, build_shell
from noitabench.worldgen.scene_world import scene_world
from scipy.ndimage import label


def _mutated(world):
    return dataclasses.replace(
        world, grid=world.grid.copy(), markers=copy.deepcopy(world.markers), meta=dict(world.meta)
    )


def _bands(world) -> list[dict]:
    """The must-pass scenes with a seam: every must-pass slot except the one in front of the seal."""
    return [
        m
        for m in world.markers
        if m["type"] == "encounter" and m["must_pass"] and m["biome"] != "seal"
    ]


def _inside(m: dict, fp: dict) -> bool:
    return fp["x"] <= m["x"] < fp["x"] + fp["w"] and fp["y"] <= m["y"] < fp["y"] + fp["h"]


def _seam_of(world, band: dict) -> dict:
    fp = band["footprint"]
    return next(
        s
        for s in world.meta["seams"]
        if s["encounter_id"] == band["encounter_id"] and s["hole"] == [fp["x"], fp["x"] + fp["w"]]
    )


# ------------------------------------------------------------------------------ the seams


def test_every_must_pass_scene_has_a_seam_whose_hole_is_its_footprint(world_a, world_b, bm, mats):
    thick = bm.scenes["bands"]["seam"]
    brick = mats["brick"]
    for w in (world_a, world_b):
        bands = _bands(w)
        assert len(bands) == len(w.meta["seams"]) == 8  # 2 + 3 + 3 bands, E06 apart
        for band in bands:
            fp, seam = band["footprint"], _seam_of(w, band)
            assert seam["thick"] == thick and seam["layer"] == band["layer"]
            # the seam lies inside the rows of the scene, so the scene's rock meets it on both sides
            assert fp["y"] <= seam["y"] and seam["y"] + thick <= fp["y"] + fp["h"]
            mx0, _, mx1, _ = bm.region(bm.layers[band["layer"] - 1].mid)
            rows = w.grid[seam["y"] : seam["y"] + thick]
            assert (rows[:, mx0 : fp["x"]] == brick).all()
            assert (rows[:, fp["x"] + fp["w"] : mx1] == brick).all()
            assert not (rows[:, fp["x"] : fp["x"] + fp["w"]] == brick).all()  # the way through
        assert w.meta["seam_brick"] > 0 and w.meta["shell_brick"] > 0


def test_a_must_pass_flag_means_a_seam_and_only_that(world_a, world_b):
    """``must_pass`` is true only for a chokepoint: a band scene (with a seam) or the sealed deep."""
    for w in (world_a, world_b):
        flagged = [m for m in w.markers if m["type"] == "encounter" and m["must_pass"]]
        assert {m["biome"] for m in flagged if m["biome"] == "seal"} == {"seal"}
        assert len(flagged) == len(w.meta["seams"]) + 1
        optional = [m for m in w.markers if m["type"] == "encounter" and not m["must_pass"]]
        assert all(m["biome"] != "seal" for m in optional)


def test_seams_reach_the_shells_of_the_side_biomes(world_a, bm, mats):
    """No lane between the end of a seam and the brick shell of the pocket beside it."""
    brick = mats["brick"]
    t = bm.scenes["bands"]["seam"]
    for band in _bands(world_a):
        seam = _seam_of(world_a, band)
        lay = bm.layers[band["layer"] - 1]
        mx0, _, mx1, _ = bm.region(lay.mid)
        rows = slice(seam["y"], seam["y"] + t)
        assert (world_a.grid[rows, mx0 - t : mx0] == brick).all()  # the left pocket's shell
        assert (world_a.grid[rows, mx1 : mx1 + t] == brick).all()  # the right pocket's shell


def test_side_biomes_are_wrapped_in_brick_with_one_gate(world_a, world_b, bm, mats):
    brick, t = mats["brick"], bm.scenes["bands"]["seam"]
    for w in (world_a, world_b):
        for lay in bm.layers:
            for side, key in (("left", lay.left), ("right", lay.right)):
                x0, y0, x1, y1 = bm.region(key)
                ring = np.zeros((y1 - y0, x1 - x0), dtype=bool)
                ring[:t, :] = ring[-t:, :] = ring[:, :t] = ring[:, -t:] = True
                gap = ring & (w.grid[y0:y1, x0:x1] != brick)
                ys, xs = np.nonzero(gap)
                assert len(ys), f"{key}: no gate at all"
                facing = (x1 - x0 - t, x1 - x0) if side == "left" else (0, t)  # towards the middle
                assert xs.min() >= facing[0] and xs.max() < facing[1], (
                    key,
                    "gate off the mid side",
                )
                rows = np.unique(ys)
                assert rows.max() - rows.min() + 1 == len(rows) <= 14, (key, "one gate of 14 rows")


def test_the_seams_run_out_to_the_edge_of_the_world_through_the_shells(world_a, bm, mats):
    """The world's border is rock, but at the seams and along the pockets it is brick: border rock
    is diggable and would leave a lane past every scene."""
    brick, t = mats["brick"], bm.scenes["bands"]["seam"]
    for band in _bands(world_a):
        seam = _seam_of(world_a, band)
        rows = slice(seam["y"], seam["y"] + t)
        assert (world_a.grid[rows, : bm.border] == brick).all()
        assert (world_a.grid[rows, -bm.border :] == brick).all()
    _, y0, _, y1 = bm.region(bm.layers[1].left)
    assert (world_a.grid[y0:y1, : bm.border] == brick).all()  # left edge of the fungal caverns


# ----------------------------------------------------------------------- the bypass check


def test_no_must_pass_scene_can_be_bypassed(world_a, world_b, bm, mats):
    for w in (world_a, world_b):
        rep = run_checks(w, bm, mats)
        assert rep.ok, rep.failures
        assert rep.stats["bypass_checked"] == len(_bands(w))


@pytest.mark.parametrize("which", [0, 3, 7])
def test_a_missing_seam_is_noticed_for_its_scene_alone(world_a, bm, mats, which):
    w = _mutated(world_a)
    band = sorted(_bands(w), key=lambda m: m["trigger"]["y"])[which]
    seam, fp = _seam_of(w, band), band["footprint"]
    mx0, _, mx1, _ = bm.region(bm.layers[band["layer"] - 1].mid)
    rows = slice(seam["y"], seam["y"] + seam["thick"])
    w.grid[rows, mx0 : fp["x"]] = mats["rock"]  # the seam made of rock: the starter wand digs it
    w.grid[rows, fp["x"] + fp["w"] : mx1] = mats["rock"]
    bypassed = [f for f in run_checks(w, bm, mats).failures if "can be bypassed" in f]
    here = f"must-pass encounter {band['encounter_id']} at ({fp['x']}, {fp['y']}) can be bypassed"
    assert bypassed == [next(f for f in bypassed if here in f)], bypassed


def test_a_leaking_shell_lets_a_digger_round_the_scenes_of_the_layer(world_a, bm, mats):
    """The left pocket of layer 1 with its mid-facing wall made of rock: from the cave above the
    first band a digger goes down the pocket's rock and back into the cave below the second one."""
    w = _mutated(world_a)
    lay = bm.layers[0]
    t = bm.scenes["bands"]["seam"]
    _, y0, x1, y1 = bm.region(lay.left)
    w.grid[y0 + t : y1 - t, x1 - t : x1] = mats["rock"]
    layer_ids = {m["encounter_id"] for m in _bands(w) if m["layer"] == 1}
    assert len(layer_ids) == 2
    bypassed = " ".join(f for f in run_checks(w, bm, mats).failures if "can be bypassed" in f)
    assert all(eid in bypassed for eid in layer_ids), bypassed


def test_a_seam_that_stops_short_of_the_world_edge_is_noticed(world_a, bm, mats):
    w = _mutated(world_a)
    band = _bands(w)[0]
    seam = _seam_of(w, band)
    lay = bm.layers[band["layer"] - 1]
    x0, _, _, _ = bm.region(lay.left)
    rows = slice(seam["y"], seam["y"] + seam["thick"])
    w.grid[rows, x0 : bm.region(lay.mid)[0]] = mats["rock"]  # shell and pocket along the seam
    fails = run_checks(w, bm, mats).failures
    assert any("can be bypassed" in f for f in fails)


def _bypassed(world, bm, mats) -> list[str]:
    return [f for f in run_checks(world, bm, mats).failures if "can be bypassed" in f]


def _slit_cells(world, band: dict, mx0: int, mats, diagonal: bool) -> list[tuple[int, int]]:
    """The cells of a one-cell-wide slit through the brick part of the seam of ``band``, one per
    row, in a column where the cave above touches the start's side of the scene and the cave below
    the seal's side (with the scene shut, those are two areas), so that the slit joins them."""
    seam, fp = _seam_of(world, band), band["footprint"]
    ok = passable_mask(world.grid, mats)
    ok[fp["y"] : fp["y"] + fp["h"], fp["x"] : fp["x"] + fp["w"]] = False
    lab, _ = label(ok, structure=EIGHT)
    spawn = next(m for m in world.markers if m["type"] == "spawn_player")
    front = next(m for m in world.markers if m["type"] == "encounter" and m["biome"] == "seal")
    tr = front["trigger"]
    near, far = lab[spawn["y"], spawn["x"]], lab[tr["y"] + tr["h"] - 3, tr["x"] + tr["w"] // 2]
    assert near and far and near != far, "the scene is not a cut of the world"
    y, t = seam["y"], seam["thick"]
    step = 1 if diagonal else 0
    for x in range(mx0 + 8, seam["hole"][0] - 8):
        cells = [(y + i, x + step * i) for i in range(t)]
        (ya, xa), (yb, xb) = cells[0], cells[-1]
        if (lab[ya - 1, xa - 1 : xa + 2] == near).any() and (
            lab[yb + 1, xb - 1 : xb + 2] == far
        ).any():
            return cells
    raise AssertionError("no column of the seam joins the two sides of the scene")


@pytest.mark.parametrize("diagonal", [False, True])
@pytest.mark.parametrize("which", [0, 4, 7])
def test_a_slit_through_a_seam_is_a_bypass_only_when_it_goes_all_the_way(
    world_a, bm, mats, which, diagonal
):
    """One missing brick, or a column that stops one brick short, is no leak; a slit through all
    the rows is, whether it runs straight or on the diagonal (rays and 8-connected cells)."""
    band = sorted(_bands(world_a), key=lambda m: m["trigger"]["y"])[which]
    fp = band["footprint"]
    mx0 = bm.region(bm.layers[band["layer"] - 1].mid)[0]
    cells = _slit_cells(world_a, band, mx0, mats, diagonal)
    here = f"must-pass encounter {band['encounter_id']} at ({fp['x']}, {fp['y']}) can be bypassed"
    for cut in (cells[:1], cells[:-1]):
        w = _mutated(world_a)
        for y, x in cut:
            w.grid[y, x] = mats["rock"]
        assert _bypassed(w, bm, mats) == [], (len(cut), "rows of a seam of", len(cells))
    w = _mutated(world_a)
    for y, x in cells:
        w.grid[y, x] = mats["rock"]
    bypassed = _bypassed(w, bm, mats)
    assert len(bypassed) == 1 and here in bypassed[0], bypassed


def test_a_gap_in_a_shell_is_a_bypass_only_when_it_joins_two_caves_of_different_floors(
    world_a, bm, mats
):
    """A one-row gap in the mid-facing wall of layer 1's left pocket. The pocket is one cave
    with one gate; a gap beside the cave that holds the gate leaks nothing, a gap beside any
    other cave joins it to the gate's cave and so goes round the seams in between."""
    t = bm.scenes["bands"]["seam"]
    _, y0, x1, y1 = bm.region(bm.layers[0].left)
    seams = sorted((s for s in world_a.meta["seams"] if s["layer"] == 1), key=lambda s: s["y"])

    def floor(row: int) -> int:
        """0 above the first seam of the layer, 1 between the first and the second, and so on."""
        return sum(row >= s["y"] for s in seams)

    gate = np.nonzero((world_a.grid[y0:y1, x1 - t : x1] != mats["brick"]).any(axis=1))[0] + y0
    gate_floor = floor(int(gate.mean()))
    ok = passable_mask(world_a.grid, mats)
    bounds = [y0 + t, *(s["y"] for s in seams), y1 - t]
    for f in range(len(seams) + 1):  # a row in the stretch between two seams, clear of the gate
        row = next(
            r
            for r in (bounds[f] + (bounds[f + 1] - bounds[f]) * k // 4 for k in (2, 1, 3))
            if not gate.min() - 24 <= r <= gate.max() + 24
        )
        assert ok[row, x1 - t - 1] and ok[row, x1], "the gap must open onto free or diggable cells"
        w = _mutated(world_a)
        w.grid[row, x1 - t : x1] = mats["rock"]
        bypassed = " ".join(_bypassed(w, bm, mats))
        between = {s["encounter_id"] for s in seams[min(f, gate_floor) : max(f, gate_floor)]}
        assert {s["encounter_id"] for s in seams if s["encounter_id"] in bypassed} == between, (
            f,
            gate_floor,
            bypassed,
        )


def test_the_control_fails_when_the_way_through_a_scene_is_shut(world_a, bm, mats):
    """The positive control: with every scene open the start must reach the seal front, or the
    "cut" of the other half of the check would prove nothing."""
    w = _mutated(world_a)
    fp = _bands(w)[0]["footprint"]
    w.grid[fp["y"] : fp["y"] + fp["h"], fp["x"] : fp["x"] + fp["w"]] = mats["brick"]
    w.markers = [  # nothing may stand in the bricks, or the marker check stops the run first
        m for m in w.markers if not (m["type"] in ("item", "spawn_enemy") and _inside(m, fp))
    ]
    fails = run_checks(w, bm, mats).failures
    assert any("even with every scene open" in f for f in fails), fails
    assert not any("can be bypassed" in f for f in fails)  # no point in cutting what is cut


def test_passable_cells_are_what_the_starter_wand_can_dig(world_a, mats):
    """The bypass check digs everything but brick: rock and ground are passable, brick is not."""
    ok = passable_mask(world_a.grid, mats)
    assert not ok[world_a.grid == mats["brick"]].any()
    assert ok[world_a.grid == mats["rock"]].all() and ok[world_a.grid == mats.air].all()


def _bypass_failures(passable, start, target, footprint) -> list[str]:
    slot = {"must_pass": True, "encounter_id": "E99", "footprint": footprint, "trigger": footprint}
    rep = checks.CheckReport()
    checks._check_bypass(rep, passable, start, target, [slot])
    return rep.failures


def test_the_bypass_check_on_a_toy_grid():
    """True = a cell the digger can be in; the cut is the footprint cells."""
    hole = {"x": 3, "y": 4, "w": 2, "h": 1}
    wall = np.ones((8, 8), dtype=bool)
    wall[4, :] = False
    wall[4, 3:5] = True  # the only way through is the footprint: nothing to report
    assert _bypass_failures(wall, (0, 0), (7, 7), hole) == []
    wall[4, 6] = True  # a second way through, outside the footprint
    assert any("can be bypassed" in f for f in _bypass_failures(wall, (0, 0), (7, 7), hole))
    shut = np.ones((8, 8), dtype=bool)
    shut[4, :] = False  # the control: with the scene open there is no way either
    assert any(
        "even with every scene open" in f for f in _bypass_failures(shut, (0, 0), (7, 7), hole)
    )


def test_the_bypass_check_counts_a_diagonal_squeeze_as_a_leak():
    """Two bricks that touch only at a corner leave a way between them for 8-connected cells."""
    grid = np.ones((8, 8), dtype=bool)
    grid[3, 0:4] = False  # the left half of a wall on row 3 ...
    grid[4, 4:8] = False  # ... the right half one row lower: they meet at a corner
    far = {"x": 0, "y": 7, "w": 1, "h": 1}
    assert any("can be bypassed" in f for f in _bypass_failures(grid, (0, 0), (7, 7), far))


# ------------------------------------------------------------------------------- unit tests


def test_a_seam_must_lie_inside_the_rows_of_its_scene(bm, mats):
    canvas = Canvas(bm.width, bm.height, mats)
    slot = {"encounter_id": "E99", "rect": (300, 200, 380, 240)}
    with pytest.raises(GenerationFailure, match="seam rows"):
        build_seam(canvas, bm, bm.layers[0], slot, yc=199)  # the rows start above the scene
    with pytest.raises(GenerationFailure, match="seam rows"):
        build_seam(canvas, bm, bm.layers[0], slot, yc=240)
    seam = build_seam(canvas, bm, bm.layers[0], slot, yc=220)
    t = bm.scenes["bands"]["seam"]
    assert (seam.y, seam.thick, seam.hole) == (220 - t // 2, t, (300, 380))
    mx0, _, mx1, _ = bm.region(bm.layers[0].mid)
    assert seam.added == (300 - mx0 + mx1 - 380) * t
    rows = canvas.grid[seam.y : seam.y + t]
    assert (rows[:, mx0:300] == mats["brick"]).all() and (rows[:, 380:mx1] == mats["brick"]).all()
    assert (rows[:, 300:380] != mats["brick"]).all()  # the hole
    assert canvas.protected[seam.y : seam.y + t, mx0:300].all()  # later steps keep out
    assert not canvas.protected[seam.y : seam.y + t, 300:380].any()


def test_a_shell_wraps_the_whole_boundary_of_a_region(bm, mats):
    canvas = Canvas(bm.width, bm.height, mats)
    key = bm.layers[0].left
    added = build_shell(canvas, bm, key)
    x0, y0, x1, y1 = bm.region(key)
    t = bm.scenes["bands"]["seam"]
    brick = canvas.grid == mats["brick"]
    assert int(brick.sum()) == added == 2 * t * (x1 - x0) + 2 * t * (y1 - y0 - 2 * t)
    assert brick[y0 + t : y1 - t, x0 + t : x1 - t].sum() == 0
    assert build_shell(canvas, bm, key) == 0  # already brick: nothing new


# ------------------------------------------------------------------------- the edit station


def test_the_hall_above_the_seal_is_a_wand_editing_station(world_a, world_b):
    for w in (world_a, world_b):
        stations = [m for m in w.markers if m["type"] == "edit_station"]
        assert len(stations) == 1
        st = stations[0]
        assert set(st) == {"type", "x", "y", "w", "h"}
        seal = next(m for m in w.markers if m["type"] == "seal")
        front = next(m for m in w.markers if m["type"] == "encounter" and m["biome"] == "seal")
        assert st == {"type": "edit_station", **front["regions"]["edit_station"]}
        # the hall lies above the plug, inside the scene, and holds the way down to the plug
        fp = front["footprint"]
        assert fp["x"] <= st["x"] and st["x"] + st["w"] <= fp["x"] + fp["w"]
        assert st["y"] >= fp["y"] and st["y"] + st["h"] <= seal["y"]
        assert st["x"] <= seal["x"] and seal["x"] + seal["w"] <= st["x"] + st["w"]
        # nothing else is a station: the rest areas stay what they were
        assert sum(1 for m in w.markers if m["type"] == "rest_area") == 2


@pytest.mark.parametrize("variant", [0, 1])
def test_the_edit_station_moves_and_mirrors_with_the_scene(variant, mats):
    d = load_encounters()["E06"]
    ex, ey, ew, eh = d.regions["edit_station"]
    w = scene_world("E06", variant, 0, 1, mats)
    fp = w.meta["footprint"]
    st = next(m for m in w.markers if m["type"] == "edit_station")
    flipped = fp["w"] - ex - ew if variant & 1 else ex
    assert (st["x"], st["y"], st["w"], st["h"]) == (fp["x"] + flipped, fp["y"] + ey, ew, eh)
    # every other scene has no station
    other = scene_world("E08", 0, 0, 1, mats)
    assert not [m for m in other.markers if m["type"] == "edit_station"]
