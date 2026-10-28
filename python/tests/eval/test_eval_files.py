"""Reading a run folder: the track, the frame records, the world file lookup, the CLI."""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import numpy as np
import pytest
from eval_runs import box, lab_marker, walk, write_run
from noitabench.eval import PROFILE_FORMAT, evaluate_run
from noitabench.eval.cli import main as eval_main
from noitabench.eval.frames import HEADER, FrameReader
from noitabench.eval.geometry import Rect, Sample, Track
from noitabench.eval.recording import load_run
from noitabench.eval.worldinfo import WorldFilesNotFound, find_world_files, load_world

PYTHON = Path(__file__).resolve().parents[2] / "noitabench"


# ------------------------------------------------------------------------------------- track
def sample(frame: int, x: float, y: float) -> Sample:
    return Sample(frame, x, y, 6, 16, 100.0, 100.0)


def test_track_interpolates_between_samples():
    t = Track([sample(0, 0, 0), sample(12, 12, 24)])
    mid = t.at(6)
    assert (mid.x, mid.y) == (6.0, 12.0)
    assert t.at(100).frame == 12 or t.at(100).x == 12


def test_a_fast_fall_through_a_region_is_a_stay():
    t = Track([sample(0, 10, 0), sample(12, 10, 100)])  # 100 cells in 12 frames
    spans = t.stays(Rect(0, 40, 30, 10))
    assert len(spans) == 1 and 0 < spans[0][0] <= spans[0][1] < 12


def test_nearby_stays_are_merged_and_far_ones_are_not():
    t = Track(
        [
            sample(0, 0, 0),
            sample(60, 0, 0),
            sample(100, 50, 0),
            sample(200, 50, 0),
            sample(500, 0, 0),
            sample(600, 0, 0),
        ]
    )
    region = Rect(-5, -5, 14, 30)
    assert len(t.stays(region, gap=60)) == 2
    assert len(t.stays(region, gap=1000)) == 1


def test_track_between_and_deepest():
    t = Track([sample(f, 0, f) for f in range(0, 100, 10)])
    assert [s.frame for s in t.between(20, 50)] == [20, 30, 40, 50]
    assert t.deepest_feet() == 90 + 16


# --------------------------------------------------------------------------------- frames.bin
def record(frame: int, x0: int, y0: int, grid: np.ndarray, codec: int = 1) -> bytes:
    raw = grid.astype(np.uint8).tobytes()
    payload = zlib.compress(raw) if codec else raw
    h, w = grid.shape
    return HEADER.pack(frame, x0, y0, w, h, codec, len(payload)) + payload


def test_frame_reader_applies_partial_rectangles_after_the_last_full_frame(tmp_path):
    base = np.zeros((6, 8), dtype=np.uint8)
    full = np.full((6, 8), 2, dtype=np.uint8)
    patch = np.full((2, 3), 9, dtype=np.uint8)
    blob = record(0, 0, 0, full) + record(10, 1, 1, patch, codec=0) + record(20, 0, 0, full * 0 + 4)
    path = tmp_path / "frames.bin"
    path.write_bytes(blob)
    reader = FrameReader(path, base)
    assert reader.grid_at(5)[0, 0] == 2
    g = reader.grid_at(15)
    assert g[1, 1] == 9 and g[2, 3] == 9 and g[0, 0] == 2 and g[3, 3] == 2
    assert (reader.grid_at(25) == 4).all()
    assert reader.grid_at(15)[1, 1] == 9  # earlier frames are still right after a later read


def test_frame_reader_falls_back_to_the_first_grid(tmp_path):
    base = np.full((4, 4), 7, dtype=np.uint8)
    assert (FrameReader(tmp_path / "missing.bin", base).grid_at(50) == 7).all()
    assert FrameReader(tmp_path / "missing.bin", None).grid_at(50) is None


def test_frame_reader_starts_from_the_png_when_there_is_no_full_frame(tmp_path):
    base = np.full((6, 8), 3, dtype=np.uint8)
    path = tmp_path / "frames.bin"
    path.write_bytes(record(4, 2, 2, np.full((2, 2), 8, dtype=np.uint8)))
    g = FrameReader(path, base).grid_at(10)
    assert g[2, 2] == 8 and g[0, 0] == 3


# ------------------------------------------------------------------------------ world lookup
def test_world_files_are_found_in_the_run_folder(tmp_path):
    run = write_run(tmp_path / "r", track=walk([(0, 1, 1), (12, 1, 1)]))
    png, js = find_world_files(run)
    assert js.name == "world.json" and png is None
    world = load_world(png, js)
    assert world.width == 768 and world.layer_at(300) == 1 and world.layer_at(600) == 0


def test_world_files_next_to_the_run_folder_and_by_seed(tmp_path):
    run = tmp_path / "play-3"
    run.mkdir()
    side = tmp_path / "play-3-world"
    side.mkdir()
    for name, seed in (("a.json", 5), ("b.json", 1)):
        doc = {"format": "cogbench-world/0", "seed": seed, "width": 4, "height": 4}
        (side / name).write_text(json.dumps(doc))
    assert find_world_files(run, seed=1)[1].name == "b.json"
    assert find_world_files(run)[1].name == "a.json"


def test_missing_world_files_say_so(tmp_path):
    (tmp_path / "r").mkdir()
    with pytest.raises(WorldFilesNotFound, match="no world file"):
        find_world_files(tmp_path / "r")
    explicit = (tmp_path / "x.png", tmp_path / "x.json")
    with pytest.raises(WorldFilesNotFound):
        find_world_files(tmp_path / "r", explicit)


def test_layers_come_from_the_biome_map(tmp_path):
    run = write_run(tmp_path / "r", track=walk([(0, 1, 1), (12, 1, 1)]))
    world = load_run(run).world
    assert [(s.layer, s.y0, s.y1) for s in world.layers()] == [
        (1, 128, 512),
        (2, 640, 1024),
        (3, 1152, 1536),
    ]
    assert world.layer_at(50) == 0 and world.layer_at(520) == 0 and world.layer_at(700) == 2


def test_a_folder_without_a_recording_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="meta.json"):
        load_run(tmp_path)


# ------------------------------------------------------------------------------- source / profile
def run_folder(tmp_path: Path, **kw) -> Path:
    m = lab_marker("E16")
    trough = box(m, "trough")
    track = walk([(0, trough.x - 10, trough.y - 14), (200, trough.right + 6, trough.y - 14)])
    return write_run(tmp_path / "run", markers=[m], track=track, **kw)


def test_the_source_is_read_from_the_folder(tmp_path):
    assert (
        load_run(run_folder(tmp_path / "a", notes="human play (noitabench.play)")).source == "human"
    )
    assert load_run(run_folder(tmp_path / "b", summary={"model": {}})).source == "agent"
    assert load_run(run_folder(tmp_path / "c", notes="scripted descent")).source == "bot"


def test_the_profile_has_the_documented_shape(tmp_path):
    summary = {
        "model": {"provider": "anthropic", "model": "claude-test"},
        "result": {
            "over": "decision_limit",
            "cost_usd": 0.5,
            "model_calls": 7,
            "usage": {"input_tokens": 9},
        },
        "cost_known": True,
    }
    transcript = [{"kind": "assistant", "text": "I think this is a test", "thinking": ""}]
    p = evaluate_run(run_folder(tmp_path, summary=summary, transcript=transcript, decisions=[]))
    assert p["format"] == PROFILE_FORMAT
    for key in ("run_id", "source", "model", "world", "composite", "ability_mean",
                "ability_raw_mean", "composite_note", "covered", "left_out", "depth", "outcome",
                "capabilities", "encounters", "metrics", "attribution", "cost", "steps",
                "test_awareness", "evaluator"):  # fmt: skip
        assert key in p, key
    assert 0 <= p["ability_mean"] <= 100
    assert p["composite"] == pytest.approx(0.8 * p["ability_mean"] + 0.2 * p["depth"]["score"],
                                           abs=0.01)  # fmt: skip
    for name, cap in p["capabilities"].items():
        n = cap["opportunities"]
        assert cap["discount"] == pytest.approx(n / (n + 2), abs=1e-4), name
        assert cap["discounted_score"] == pytest.approx(
            0.0 if cap["score"] is None else cap["score"] * n / (n + 2), abs=0.01
        ), name
    assert set(p["capabilities"]) == {f"N{i}" for i in range(1, 11)} | {"C"}
    assert set(p["capabilities"]["C"]["parts"]) == {"C1", "C2", "C3", "C4"}
    assert [e["id"] for e in p["encounters"]] == [
        "E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09", "E10", "E12", "E14", "E16",
        "E18", "E21", "E22", "E23", "E24",
    ]  # fmt: skip
    e16 = next(e for e in p["encounters"] if e["id"] == "E16")
    visit = e16["visits"][0]
    assert visit["scored"] and 0 <= visit["score"] <= 1 and visit["reasons"]
    assert p["model"] == {"provider": "anthropic", "model": "claude-test"}
    assert p["cost"]["usd"] == 0.5 and p["outcome"]["over"] == "decision_limit"
    assert p["test_awareness"]["hits"] == 1
    json.dumps(p)  # plain JSON all through


def test_the_profile_is_deterministic(tmp_path):
    folder = run_folder(tmp_path)
    assert json.dumps(evaluate_run(folder)) == json.dumps(evaluate_run(folder))


def test_the_cli_writes_profile_json(tmp_path, capsys):
    folder = run_folder(tmp_path)
    assert eval_main([str(folder)]) == 0
    written = json.loads((folder / "profile.json").read_text())
    assert written["format"] == PROFILE_FORMAT
    out = capsys.readouterr().out
    assert "composite" in out and "E16@" in out
    target = tmp_path / "elsewhere" / "p.json"
    assert eval_main([str(folder), "--out", str(target), "--quiet"]) == 0 and target.exists()


def test_the_cli_takes_the_world_files_and_reports_errors(tmp_path, capsys):
    folder = run_folder(tmp_path)
    moved = tmp_path / "moved"
    (folder / "world").rename(moved)
    assert eval_main([str(folder), "--quiet"]) == 2
    assert "no world file" in capsys.readouterr().err
    pair = [str(moved / "world.png"), str(moved / "world.json")]
    assert eval_main([str(folder), "--world-files", *pair, "--quiet"]) == 0
    assert eval_main([str(tmp_path / "nothing"), "--quiet"]) == 2


def test_python_m_noitabench_dispatches_eval(tmp_path, capsys):
    from noitabench.__main__ import main

    assert main(["eval", str(run_folder(tmp_path)), "--quiet"]) == 0


# --------------------------------------------------------------------------- secrecy of scores
def guarded_files() -> list[Path]:
    """Every module of the package but the evaluation itself and the command dispatcher, which
    names `noitabench.eval.cli` as a string to load it on demand."""
    skip = {PYTHON / "__main__.py"}
    return [
        p
        for p in sorted(PYTHON.rglob("*.py"))
        if (PYTHON / "eval") not in p.parents and p not in skip
    ]


def evaluation_mentions(path: Path) -> list[int]:
    """Line numbers at which a module imports or names the evaluation."""
    import ast

    source = path.read_text(encoding="utf-8")
    hits = []
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names = [base] + [f"{base}.{a.name}" for a in node.names]
            if node.level and base == "":
                names += [a.name for a in node.names]
        if any(n == "eval" or n.endswith(".eval") or ".eval." in n or n.startswith(("eval.", "noitabench.eval")) for n in names):  # fmt: skip
            hits.append(node.lineno)
    if "noitabench.eval" in source:
        hits.append(0)
    return hits


def test_nothing_the_agent_or_the_harness_runs_imports_the_evaluation():
    files = guarded_files()
    folders = {p.relative_to(PYTHON).parts[0] for p in files}
    # the packages an agent, a harness, a human player or a world touches, and the loose modules
    assert {"agent", "harness", "play", "bots", "worldgen", "demo", "content_tools"} <= folders
    assert {"game.py", "env.py"} <= folders
    offenders = [f"{p.relative_to(PYTHON)}:{n}" for p in files for n in evaluation_mentions(p)]
    assert offenders == []


def test_the_guard_sees_an_import_added_to_any_module(tmp_path):
    """The guard is not a rubber stamp: it finds the import in each shape and in each place."""
    shapes = [
        "import noitabench.eval",
        "from noitabench.eval import profile",
        "from .. import eval as e",
        "from ..eval import profile",
        "import importlib; importlib.import_module('noitabench.eval.cli')",
        "__import__('noitabench.eval.profile')",
    ]
    for i, line in enumerate(shapes):
        path = tmp_path / f"m{i}.py"
        path.write_text(f"x = 1\n{line}\n", encoding="utf-8")
        assert evaluation_mentions(path), line
    clean = tmp_path / "clean.py"
    clean.write_text("from noitabench.agent import tools\nevaluate = 1\n", encoding="utf-8")
    assert evaluation_mentions(clean) == []


def test_loading_the_game_side_packages_does_not_load_the_evaluation():
    """Whatever the modules import by indirect ways, the evaluation is not in memory after the
    packages an agent run uses are imported."""
    import subprocess
    import sys

    code = (
        "import sys, importlib\n"
        "for name in ('noitabench.agent', 'noitabench.harness', 'noitabench.play',"
        " 'noitabench.bots', 'noitabench.game', 'noitabench.env', 'noitabench.worldgen'):\n"
        "    importlib.import_module(name)\n"
        "loaded = sorted(m for m in sys.modules if m.startswith('noitabench.eval'))\n"
        "print('LOADED', loaded)\n"
    )
    env = {"PYTHONPATH": str(PYTHON.parent), "PATH": "/usr/bin:/bin"}
    done = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-1500:]
    assert "LOADED []" in done.stdout


def test_events_out_of_order_and_a_torn_last_line_are_read(tmp_path):
    folder = run_folder(tmp_path)
    lines = [
        json.dumps(
            {"frame": 300, "type": "damage", "target": "player", "amount": 9, "source": "contact"}
        ),
        json.dumps(
            {"frame": 100, "type": "damage", "target": "player", "amount": 4, "source": "contact"}
        ),
        '{"frame": 400, "type": "dam',  # cut off mid-write
    ]
    (folder / "events.jsonl").write_text("\n".join(lines))
    run = load_run(folder)
    assert [e["frame"] for e in run.events.rows] == [100, 300]
    assert [e["amount"] for e in run.events.player_damage(0, 200)] == [4]
