"""`python -m noitabench demo game`: eight recordings of the game layer."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from game_recording_reader import frame_numbers, read_events, read_meta
from noitabench.demo.game import SCENES, run_all


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("game-runs")
    summaries = run_all(out, seed=1)
    assert [Path(s["dir"]).name for s in summaries] == [f"demo-game-{n}" for n in SCENES]
    return out


def counts(run: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in read_events(run):
        out[e["type"]] = out.get(e["type"], 0) + 1
    return out


def entity_lines(run: Path) -> list[dict]:
    return [json.loads(line) for line in (run / "entities.jsonl").read_text().splitlines()]


def last_of(run: Path, kind: str) -> dict | None:
    return next((e for e in entity_lines(run)[-1]["entities"] if e["kind"] == kind), None)


def player_track(run: Path, key: str) -> list[float]:
    return [
        next(e for e in line["entities"] if e["kind"] == "player")[key]
        for line in entity_lines(run)
    ]


def test_there_are_eight_scenes() -> None:
    assert sorted(SCENES) == [
        "alchemy", "barrel-chain", "fight-hamis", "fight-shotgunner", "fight-stendari",
        "move-dig", "potions", "trigger-combo",
    ]  # fmt: skip


def test_alchemy_pours_three_liquids_into_a_bowl_and_makes_a_potion(runs: Path) -> None:
    run = runs / "demo-game-alchemy"
    events = read_events(run)
    assert [e["material"] for e in events if e["type"] == "pour"] == ["blood", "water", "oil"]
    mixes = [e for e in events if e["type"] == "mix"]
    assert len(mixes) >= 8 and {e["potion"] for e in mixes} == {"potion_crit"}


def test_every_recording_parses_and_pairs_frames_with_entities(runs: Path) -> None:
    for name in SCENES:
        run = runs / f"demo-game-{name}"
        meta, frames, lines = read_meta(run), frame_numbers(run), entity_lines(run)
        assert meta["run_id"] == f"demo-game-{name}"
        assert meta["world"] == {"width": 320, "height": 192}
        assert frames == [line["frame"] for line in lines], name
        assert lines[0]["entities"][0]["kind"] == "player"
        for e in lines[-1]["entities"]:
            assert {"id", "kind", "x", "y", "w", "h", "hp", "hp_max"} <= set(e)


def test_walking_levitating_and_digging(runs: Path) -> None:
    run = runs / "demo-game-move-dig"
    ys, xs = player_track(run, "y"), player_track(run, "x")
    assert min(ys) < ys[0] - 20, "it rises over the pillar"
    assert xs[-1] > 150, "and gets past it"
    assert ys[-1] > ys[0] + 20, "then digs down into the ground"
    assert counts(run)["cast"] > 10


def test_hamis_fight(runs: Path) -> None:
    run = runs / "demo-game-fight-hamis"
    c = counts(run)
    assert c["death"] == 3 and c["hit"] >= 3
    assert last_of(run, "longleg") is None


def test_shotgunner_fight(runs: Path) -> None:
    run = runs / "demo-game-fight-shotgunner"
    c = counts(run)
    assert c["death"] == 1 and c["hit"] >= 3
    assert last_of(run, "shotgunner") is None


def test_stendari_dies_of_water(runs: Path) -> None:
    run = runs / "demo-game-fight-stendari"
    events = read_events(run)
    story = [e["type"] for e in events if e["type"] in ("throw", "shatter", "death")]
    assert story == ["throw", "shatter", "death"]
    wet = [e for e in events if e["type"] == "status" and e["target"] == "firemage_weak"]
    assert wet and wet[0]["status"] == "wet" and wet[0]["active"] == 1
    death = next(e for e in events if e["type"] == "death")
    assert death["target"] == "firemage_weak"


def test_barrel_chain(runs: Path) -> None:
    run = runs / "demo-game-barrel-chain"
    events = read_events(run)
    breaks = [e["kind"] for e in events if e["type"] == "barrel_break"]
    assert sorted(breaks) == [
        "barrel_acid", "barrel_gunpowder", "barrel_gunpowder", "barrel_oil",
    ]  # fmt: skip
    assert breaks[0] == "barrel_oil", "the oil barrel is the one the fireball hits"
    assert sum(1 for e in events if e["type"] == "explosion" and e["radius"] == 30) == 2
    kinds = {e["kind"] for e in entity_lines(run)[-1]["entities"]}
    assert not any(k.startswith("barrel") for k in kinds)


def test_potions(runs: Path) -> None:
    run = runs / "demo-game-potions"
    events = read_events(run)
    drinks = [e["material"] for e in events if e["type"] == "drink"]
    assert drinks[:2] == ["potion_heal", "potion_haste"]
    hp = player_track(run, "hp")
    assert min(hp) < 60 and hp[-1] == 100.0, "hurt by the blast, healed by the potion"
    statuses = {e["status"] for e in events if e["type"] == "status" and e["active"]}
    assert "haste" in statuses


def test_event_lines_keep_floats_as_floats(runs: Path) -> None:
    # `3.0`, not `3`: a reader gets the same type from the file as from `Game.events()`
    damage = [e for e in read_events(runs / "demo-game-potions") if e["type"] == "damage"]
    assert damage
    for e in damage:
        assert isinstance(e["amount"], float) and isinstance(e["hp"], float), e


def test_trigger_combo(runs: Path) -> None:
    run = runs / "demo-game-trigger-combo"
    events = read_events(run)
    casts = [e for e in events if e["type"] == "cast"]
    assert casts[0]["spells"] == "BURST_2+LIGHT_BULLET_TRIGGER+FIREBALL+LIGHT_BULLET"
    assert casts[0]["projectiles"] == 2
    radii = {e["radius"] for e in events if e["type"] == "explosion"}
    assert {2, 15} <= radii, "the trigger bolt's burst and the payload fireball's"


def test_recordings_are_reproducible(tmp_path: Path, runs: Path) -> None:
    run_all(tmp_path, seed=1, only=["barrel-chain"])
    for name in ("meta.json", "frames.bin", "events.jsonl", "entities.jsonl"):
        a = (runs / "demo-game-barrel-chain" / name).read_bytes()
        b = (tmp_path / "demo-game-barrel-chain" / name).read_bytes()
        assert a == b, name


def test_unknown_scene_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown scene"):
        run_all(tmp_path, only=["nope"])


def test_the_command_line_records_one_scene(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "noitabench", "demo", "game", "--out", str(tmp_path),
         "--only", "potions"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert "demo-game-potions" in done.stdout
    assert (tmp_path / "demo-game-potions" / "entities.jsonl").exists()
    bad = subprocess.run(
        [sys.executable, "-m", "noitabench", "demo", "game", "--only", "nope"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert bad.returncode == 2 and "unknown scene" in bad.stderr
