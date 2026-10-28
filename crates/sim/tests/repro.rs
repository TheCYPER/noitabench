//! Reproducibility (contract section 7, DET-R01, SIM-R70, SIM-R78, SIM-T34, SIM-T35).

mod common;
use cogbench_sim::{DirtyMode, Tuning, World};
use common::*;

fn run(seed: u64, soup_seed: u64, frames: u32) -> (u64, Vec<String>) {
    let mut w = soup(96, 80, seed, soup_seed, content(Tuning::default()));
    w.step_frames(frames).unwrap();
    fingerprint(&mut w)
}

#[test]
fn det_r01_same_seed_same_calls_same_everything() {
    for soup_seed in 0..4 {
        let a = run(7, soup_seed, 250);
        let b = run(7, soup_seed, 250);
        assert_eq!(a, b, "soup {soup_seed}");
        assert!(!a.1.is_empty(), "the soup should produce events");
    }
}

#[test]
fn det_r04_a_different_seed_changes_the_run() {
    assert_ne!(run(7, 1, 250).0, run(8, 1, 250).0);
}

#[test]
fn sim_t35_soup_fuzz_never_panics_and_is_stable() {
    for soup_seed in 10..16 {
        let mut w = soup(130, 70, 3, soup_seed, content(Tuning::default()));
        for _ in 0..8 {
            w.step_frames(40).unwrap();
            w.drain_events();
        }
        let h1 = w.state_hash();
        let mut w2 = soup(130, 70, 3, soup_seed, content(Tuning::default()));
        w2.step_frames(320).unwrap();
        assert_eq!(h1, w2.state_hash(), "soup {soup_seed}");
    }
}

#[test]
fn sim_t34_snapshot_restore_continue_equals_uninterrupted() {
    for cut in [0u32, 1, 57, 140] {
        let mut a = soup(96, 80, 5, 2, content(Tuning::default()));
        a.step_frames(cut).unwrap();
        a.drain_events();
        let blob = a.snapshot().unwrap();
        a.step_frames(160).unwrap();
        let reference = fingerprint(&mut a);

        // Into the same world ...
        a.restore(&blob).unwrap();
        a.step_frames(160).unwrap();
        assert_eq!(
            fingerprint(&mut a),
            reference,
            "restore in place, cut {cut}"
        );

        // ... and into a brand-new one of another size and seed.
        let mut b = World::new(8, 8, 999, content(Tuning::default())).unwrap();
        b.restore(&blob).unwrap();
        assert_eq!(b.frame(), u64::from(cut));
        b.step_frames(160).unwrap();
        assert_eq!(
            fingerprint(&mut b),
            reference,
            "restore into a new world, cut {cut}"
        );
    }
}

#[test]
fn sim_r78_snapshot_is_bit_exact_right_after_restore() {
    let mut a = soup(70, 70, 5, 3, content(Tuning::default()));
    a.step_frames(90).unwrap();
    let blob = a.snapshot().unwrap();
    let mut b = World::new(70, 70, 1, content(Tuning::default())).unwrap();
    b.restore(&blob).unwrap();
    assert_eq!(a.state_hash(), b.state_hash());
    assert_eq!(a.snapshot().unwrap(), b.snapshot().unwrap());
    assert_eq!(a.grid_bytes(), b.grid_bytes());
}

#[test]
fn snapshot_keeps_pending_explosions() {
    let mut a = World::new(60, 40, 1, forced_reactive()).unwrap();
    a.fill_rect(0, 30, 60, 10, "ground").unwrap();
    a.paint(30, 29, 0, "gunpowder").unwrap();
    assert!(a.ignite(30, 29));
    a.step().unwrap(); // burns out, explosion queued for next frame
    assert_eq!(a.pending_explosions().len(), 1);
    let blob = a.snapshot().unwrap();
    let mut b = World::new(60, 40, 1, forced_reactive()).unwrap();
    b.restore(&blob).unwrap();
    assert_eq!(b.pending_explosions().len(), 1);
    a.step_frames(5).unwrap();
    b.step_frames(5).unwrap();
    assert_eq!(a.state_hash(), b.state_hash());
}

#[test]
fn snapshot_errors_are_reported_not_panics() {
    let mut w = World::new(16, 16, 1, content(Tuning::default())).unwrap();
    w.paint(8, 8, 3, "sand").unwrap();
    let blob = w.snapshot().unwrap();
    let before = w.state_hash();
    assert!(w
        .restore(&blob[..10])
        .unwrap_err()
        .to_string()
        .contains("truncated"));
    assert!(w
        .restore(b"not a snapshot at all")
        .unwrap_err()
        .to_string()
        .contains("magic"));
    let mut corrupt = blob.clone();
    let n = corrupt.len();
    corrupt[n - 3] ^= 0xFF;
    assert!(w.restore(&corrupt).is_err());
    // Content mismatch: a world with another tuning refuses the snapshot.
    let mut other = World::new(16, 16, 1, forced()).unwrap();
    assert!(other
        .restore(&blob)
        .unwrap_err()
        .to_string()
        .contains("different"));
    // The failed restores left the world intact.
    assert_eq!(w.state_hash(), before);
}

#[test]
fn from_indices_matches_painting() {
    let c = content(Tuning::default());
    let mut painted = World::new(20, 20, 4, c.clone()).unwrap();
    painted.fill_rect(0, 15, 20, 5, "rock").unwrap();
    painted.paint(10, 5, 3, "sand").unwrap();
    let bytes = painted.grid_bytes();
    let mut loaded = World::from_indices(20, 20, 4, &bytes, c).unwrap();
    painted.step_frames(100).unwrap();
    loaded.step_frames(100).unwrap();
    assert_eq!(painted.grid_bytes(), loaded.grid_bytes());
}

#[test]
fn all_dirty_mode_is_deterministic_too() {
    let go = || {
        let mut w = soup(70, 70, 5, 3, content(Tuning::default()));
        w.set_dirty_mode(DirtyMode::AllDirty);
        w.step_frames(120).unwrap();
        w.state_hash()
    };
    assert_eq!(go(), go());
}

#[test]
fn snapshot_with_a_dirty_rectangle_outside_its_chunk_is_rejected() {
    let mut w = World::new(70, 70, 1, content(Tuning::default())).unwrap();
    w.paint(10, 10, 2, "sand").unwrap();
    let blob = w.snapshot().unwrap();
    // Header: magic 8, hash 8, seed 8, rule seed 8, w 4, h 4, frame 8, next id 8, queue len 4.
    let first_rect = 8 + 8 + 8 + 8 + 4 + 4 + 8 + 8 + 4;
    let mut bad = blob.clone();
    bad[first_rect + 12..first_rect + 16].copy_from_slice(&5000i32.to_le_bytes()); // y1
    let err = w.restore(&bad).unwrap_err().to_string();
    assert!(err.contains("outside the chunk"), "{err}");
    w.restore(&blob).unwrap();
}

#[test]
fn snapshot_with_an_absurd_queued_explosion_is_rejected() {
    let mut w = World::new(32, 32, 1, forced_reactive()).unwrap();
    w.fill_rect(0, 20, 32, 12, "ground").unwrap();
    w.paint(16, 19, 0, "gunpowder").unwrap();
    assert!(w.ignite(16, 19));
    w.step().unwrap();
    let blob = w.snapshot().unwrap();
    // queue entry: id 8, x 4, y 4, radius 4, ...
    let entry = 8 + 8 + 8 + 8 + 4 + 4 + 8 + 8 + 4;
    let mut bad = blob.clone();
    bad[entry + 16..entry + 20].copy_from_slice(&u32::MAX.to_le_bytes());
    let err = w.restore(&bad).unwrap_err().to_string();
    assert!(err.contains("queued explosion"), "{err}");
}
