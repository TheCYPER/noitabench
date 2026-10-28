//! Reproducibility (contract section 7): the same seed and the same controls give the same game,
//! bit for bit; a snapshot restores it exactly; recordings carry the entities.

mod scene;

use scene::*;

use cogbench_game::{Controls, Game, ItemSpec};
use cogbench_sim::RecordConfig;

const W: i32 = 600;
const H: i32 = 200;
const FLOOR: i32 = 30;

/// A busy little world: every enemy, barrels, bottles and a wall of sand.
fn busy(seed: u64) -> Game {
    let mut g = world(W, H, FLOOR, seed);
    let y = ground_y(H, FLOOR);
    g.world_mut()
        .fill_rect(380, y - 30, 40, 31, "sand")
        .unwrap();
    g.spawn_player(60, y).unwrap();
    g.spawn_enemy("longleg", 200, y).unwrap();
    g.spawn_enemy("shotgunner", 300, y).unwrap();
    g.spawn_enemy("firemage_weak", 500, y).unwrap();
    for (i, k) in ["barrel_oil", "barrel_gunpowder", "barrel_acid"]
        .iter()
        .enumerate()
    {
        g.spawn_item(
            &ItemSpec::Barrel { kind: (*k).into() },
            120 + 20 * i as i32,
            y,
        )
        .unwrap();
    }
    g.spawn_item(&ItemSpec::Wand { tier: 2 }, 90, y).unwrap();
    g.spawn_item(
        &ItemSpec::Bottle {
            material: Some("water".into()),
            amount: None,
        },
        80,
        y,
    )
    .unwrap();
    give(
        &mut g,
        &[
            "BURST_2",
            "LIGHT_BULLET_TRIGGER",
            "FIREBALL",
            "SPEED",
            "BOMB",
        ],
    );
    g
}

/// Controls for frame `f`: walk, jump, shoot, kick, pick up, throw, in a fixed pattern.
fn script(f: u32) -> Controls {
    let phase = f / 40;
    hold(|c| {
        c.move_x = match phase % 4 {
            0 | 1 => 1,
            2 => -1,
            _ => 0,
        };
        c.jump = f.is_multiple_of(70);
        c.fire = phase % 3 != 2;
        c.aim = ((f * 7) % 90) as f32 - 20.0;
        c.kick = f % 90 == 45;
        c.interact = f.is_multiple_of(55);
        c.throw = f % 200 == 150;
        c.drink = f % 130 > 100;
        c.select_wand = Some((phase % 3) as u8);
    })
}

fn play(g: &mut Game, from: u32, to: u32) {
    for f in from..to {
        g.step(&script(f)).unwrap();
    }
}

fn digest(g: &mut Game) -> (u64, Vec<String>) {
    let content = g.world().content().clone();
    let ev = g
        .world_mut()
        .drain_events()
        .iter()
        .map(|e| e.to_json_line(&content))
        .collect();
    (g.state_hash(), ev)
}

#[test]
fn same_seed_and_controls_give_the_same_game() {
    let mut a = busy(7);
    let mut b = busy(7);
    for chunk in 0..6 {
        play(&mut a, chunk * 100, chunk * 100 + 100);
        play(&mut b, chunk * 100, chunk * 100 + 100);
        assert_eq!(
            digest(&mut a),
            digest(&mut b),
            "after {} frames",
            chunk * 100 + 100
        );
    }
    assert_eq!(a.world().frame(), 600);
}

#[test]
fn the_busy_world_really_is_busy() {
    let mut g = busy(7);
    play(&mut g, 0, 600);
    let ev = events(&mut g);
    for kind in ["cast", "hit", "explosion", "damage", "kick", "pickup"] {
        assert!(count(&ev, kind) > 0, "no {kind} events in {}", ev.len());
    }
}

#[test]
fn another_seed_plays_differently() {
    let mut a = busy(7);
    let mut b = busy(8);
    play(&mut a, 0, 300);
    play(&mut b, 0, 300);
    assert_ne!(a.state_hash(), b.state_hash());
}

#[test]
fn a_snapshot_restores_the_game_exactly() {
    let mut g = busy(3);
    play(&mut g, 0, 150);
    g.world_mut().drain_events();
    let blob = g.snapshot().unwrap();
    let hash = g.state_hash();
    play(&mut g, 150, 450);
    let end = digest(&mut g);
    // back to frame 150 in the same game
    g.restore(&blob).unwrap();
    assert_eq!(g.state_hash(), hash);
    g.world_mut().drain_events();
    play(&mut g, 150, 450);
    assert_eq!(digest(&mut g), end, "replaying from the snapshot");
    // and into a fresh game of the same content
    let mut fresh = busy(3);
    fresh.restore(&blob).unwrap();
    assert_eq!(fresh.state_hash(), hash);
    play(&mut fresh, 150, 450);
    assert_eq!(digest(&mut fresh).0, end.0);
}

#[test]
fn a_corrupt_snapshot_is_refused_and_changes_nothing() {
    let mut g = busy(3);
    play(&mut g, 0, 50);
    let hash = g.state_hash();
    let blob = g.snapshot().unwrap();
    assert!(g.restore(&blob[..20]).is_err());
    assert!(g.restore(b"nonsense").is_err());
    let mut bad = blob.clone();
    bad[0] = b'X';
    assert!(g.restore(&bad).is_err());
    let mut bad_json = blob.clone();
    let n = bad_json.len();
    bad_json[n - 10] = b'#';
    bad_json.truncate(n - 5);
    assert!(g.restore(&bad_json).is_err());
    assert_eq!(g.state_hash(), hash);
}

#[test]
fn recordings_carry_the_entities_of_every_recorded_frame() {
    let dir = tempfile::tempdir().unwrap();
    let mut g = busy(5);
    let mut cfg = RecordConfig::new(dir.path().join("rec"), 4);
    cfg.created = Some("2026-10-26T00:00:00Z".into());
    g.start_recording(cfg).unwrap();
    assert!(g.is_recording());
    play(&mut g, 0, 123);
    let summary = g.stop_recording().unwrap();
    assert!(!g.is_recording());
    let text = std::fs::read_to_string(dir.path().join("rec/entities.jsonl")).unwrap();
    let lines: Vec<serde_json::Value> = text
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    // frames 0, 4, ..., 120 and the final frame 123
    assert_eq!(
        lines.len() as u64,
        summary.frames,
        "one line per pixel frame"
    );
    assert_eq!(lines.first().unwrap()["frame"], 0);
    assert_eq!(lines.last().unwrap()["frame"], 123);
    let first = lines[0]["entities"].as_array().unwrap();
    assert_eq!(first[0]["kind"], "player");
    for key in ["id", "kind", "x", "y", "w", "h", "hp", "hp_max"] {
        assert!(first[0].get(key).is_some(), "{key}");
    }
    let kinds: Vec<&str> = first.iter().map(|e| e["kind"].as_str().unwrap()).collect();
    for k in [
        "longleg",
        "shotgunner",
        "firemage_weak",
        "barrel_oil",
        "wand",
        "bottle",
    ] {
        assert!(kinds.contains(&k), "{k} in {kinds:?}");
    }
    let events = std::fs::read_to_string(dir.path().join("rec/events.jsonl")).unwrap();
    assert!(events.lines().any(|l| l.contains("\"type\":\"cast\"")));
}

#[test]
fn restoring_during_a_recording_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let mut g = busy(5);
    let blob = g.snapshot().unwrap();
    g.start_recording(RecordConfig::new(dir.path().join("rec"), 4))
        .unwrap();
    assert!(g.restore(&blob).is_err());
    g.stop_recording().unwrap();
}
