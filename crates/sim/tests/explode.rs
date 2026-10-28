//! Ray explosions: `SIM-R50..R52`, `DUR-R01..R03`, vectors `SIM-T26..T28`, `MV-13`, `MV-17`.

mod common;
use cogbench_sim::{ray_count, ExplosionSpec, Tuning, World};
use common::*;

/// A big world of one material with an air pocket in the middle; returns the farthest destroyed
/// distance from the centre.
fn reach(key: &str, radius: u32, energy: u32, max_dur: u8) -> f64 {
    let mut w = World::new(81, 81, 1, forced()).unwrap();
    w.fill_rect(0, 0, 81, 81, key).unwrap();
    w.paint(40, 40, 0, "air").unwrap();
    let n = w
        .explode(ExplosionSpec {
            fire_percent: 0,
            ..ExplosionSpec::new(40, 40, radius, energy, max_dur)
        })
        .unwrap();
    let _ = n;
    let mut far = 0.0f64;
    for y in 0..81 {
        for x in 0..81 {
            if (x, y) != (40, 40) && w.grid().get(x, y).mat == 0 {
                let d = (f64::from(x - 40).powi(2) + f64::from(y - 40).powi(2)).sqrt();
                far = far.max(d);
            }
        }
    }
    far
}

#[test]
fn sim_t28_ray_counts() {
    for (r, n) in [
        (2, 16),
        (6, 38),
        (20, 126),
        (60, 377),
        (250, 1571),
        (400, 2514),
    ] {
        assert_eq!(ray_count(r), n, "radius {r}");
    }
}

#[test]
fn sim_t27_depth_is_min_of_radius_and_energy_over_hp() {
    // Default explosion (R20, 20k, durability 10): sand (hp 800) -> full radius, ground
    // (hp 19000) -> 2 cells, rock (hp 100000) -> 1 cell, wood (hp 2000) -> 10 cells.
    let cases = [
        ("sand", 20.0),
        ("ground", 2.0),
        ("rock", 1.0),
        ("wood", 10.0),
    ];
    for (key, depth) in cases {
        let far = reach(key, 20, 20_000, 10);
        assert!(
            (far - depth).abs() <= 1.0,
            "{key}: carved to {far}, expected about {depth}"
        );
    }
    // Digging bolt: R6, 100k, durability 10.
    assert!((reach("rock", 6, 100_000, 10) - 1.0).abs() <= 1.0);
    // Spark bolt style: R2, 400k, durability 8: sand (4) is dug, ground (10) is not.
    assert!(reach("sand", 2, 400_000, 8) >= 1.0);
    assert_eq!(reach("ground", 2, 400_000, 8), 0.0);
}

#[test]
fn mv_13_durability_gate_by_material() {
    // max durability 8: sand (4) and coal (8) fall, ground and rock (10) stay.
    for (key, dug) in [
        ("sand", true),
        ("coal", true),
        ("ground", false),
        ("rock", false),
        ("brick", false),
    ] {
        let far = reach(key, 5, 400_000, 8);
        assert_eq!(far > 0.0, dug, "{key}");
    }
}

#[test]
fn dur_r01_a_hard_cell_ends_the_ray() {
    // One-cell-wide column: air, ground, brick, ground, ground, ... Centre at the top.
    let mut w = World::new(1, 10, 1, forced()).unwrap();
    w.fill_rect(0, 1, 1, 9, "ground").unwrap();
    w.fill_rect(0, 3, 1, 1, "brick").unwrap();
    w.explode(ExplosionSpec {
        fire_percent: 0,
        ..ExplosionSpec::new(0, 0, 8, 10_000_000, 10)
    })
    .unwrap();
    let col: String = (0..10)
        .map(|y| char_of(w.content().mats.key_of(w.grid().get(0, y).mat)))
        .collect();
    assert_eq!(
        col, "...BDDDDDD",
        "two ground cells dug, the brick stops the ray"
    );
}

#[test]
fn dur_r02_air_costs_nothing_and_radius_caps_the_reach() {
    // Three air cells in front of the wall: the ray still digs 5 solid cells with energy for 5.
    let mut w = World::new(1, 12, 1, forced()).unwrap();
    w.fill_rect(0, 4, 1, 8, "ground").unwrap();
    // centre at y=0; 4 air cells (y 0..3); energy 5 * 19000 = 95000 -> 5 ground cells dug.
    w.explode(ExplosionSpec {
        fire_percent: 0,
        ..ExplosionSpec::new(0, 0, 11, 95_000, 10)
    })
    .unwrap();
    let dug = (4..12).filter(|&y| w.grid().get(0, y).mat == 0).count();
    assert_eq!(dug, 5);
    // A radius of 3 reaches y = 3 at most: nothing of the wall is touched.
    let mut w = World::new(1, 12, 1, forced()).unwrap();
    w.fill_rect(0, 4, 1, 8, "ground").unwrap();
    w.explode(ExplosionSpec {
        fire_percent: 0,
        ..ExplosionSpec::new(0, 0, 3, 100_000_000, 10)
    })
    .unwrap();
    assert_eq!(count(&w, "ground"), 8);
}

#[test]
fn dur_r03_destroyed_cells_may_turn_into_fire() {
    let mut w = World::new(41, 41, 7, forced()).unwrap();
    w.fill_rect(0, 0, 41, 41, "sand").unwrap();
    w.explode(ExplosionSpec {
        fire_percent: 100,
        ..ExplosionSpec::new(20, 20, 10, 20_000, 10)
    })
    .unwrap();
    assert!(
        count(&w, "fire") > 150,
        "every destroyed cell becomes fire at 100 %"
    );
    let mut w = World::new(41, 41, 7, forced()).unwrap();
    w.fill_rect(0, 0, 41, 41, "sand").unwrap();
    w.explode(ExplosionSpec {
        fire_percent: 0,
        ..ExplosionSpec::new(20, 20, 10, 20_000, 10)
    })
    .unwrap();
    assert_eq!(count(&w, "fire"), 0);
}

#[test]
fn dur_r03_explosion_emits_an_event_and_wakes_the_neighbourhood() {
    let mut w = World::new(64, 64, 1, content(Tuning::default())).unwrap();
    w.fill_rect(0, 0, 64, 64, "sand").unwrap();
    w.step_frames(5).unwrap();
    w.drain_events();
    let n = w
        .explode(ExplosionSpec::new(32, 32, 10, 20_000, 10))
        .unwrap();
    let c = w.content().clone();
    let evs = of_type(&w.drain_events(), &c, "explosion");
    assert_eq!(evs.len(), 1);
    assert_eq!(int(&evs[0], "destroyed"), i64::from(n));
    assert!(
        !w.grid().dirty_rect(0, 0).is_empty(),
        "the crater must wake the sand around it"
    );
}

#[test]
fn explosion_arguments_are_validated() {
    let mut w = World::new(8, 8, 1, forced()).unwrap();
    assert!(w.explode(ExplosionSpec::new(4, 4, 0, 1000, 10)).is_err());
    assert!(w
        .explode(ExplosionSpec::new(4, 4, 100_000, 1000, 10))
        .is_err());
}

#[test]
fn sim_r51_a_crater_in_soft_ground_has_no_holes() {
    // Every cell well inside the radius must be carved; only the rim may be ragged.
    for (r, energy) in [
        (8u32, 400_000u32),
        (15, 4_000_000),
        (20, 20_000),
        (60, 6_000_000),
    ] {
        let n = 2 * r as i32 + 3;
        let c = r as i32 + 1;
        let mut w = World::new(n, n, 1, forced()).unwrap();
        w.fill_rect(0, 0, n, n, "sand").unwrap();
        w.explode(ExplosionSpec {
            fire_percent: 0,
            ..ExplosionSpec::new(c, c, r, energy, 10)
        })
        .unwrap();
        let inner = r as i32 - 2;
        let holes = (0..n)
            .flat_map(|y| (0..n).map(move |x| (x, y)))
            .filter(|&(x, y)| (x - c).pow(2) + (y - c).pow(2) <= inner * inner)
            .filter(|&(x, y)| w.grid().get(x, y).mat != 0)
            .count();
        assert_eq!(holes, 0, "radius {r}: uncarved cells inside the crater");
    }
}

#[test]
fn sim_r52_destroyed_liquid_is_removed_in_week_one() {
    // No particles yet: a liquid inside the blast radius is deleted, not thrown.
    let mut w = World::new(31, 31, 1, forced()).unwrap();
    w.fill_rect(0, 0, 31, 31, "water").unwrap();
    w.explode(ExplosionSpec {
        fire_percent: 0,
        ..ExplosionSpec::new(15, 15, 6, 20_000, 10)
    })
    .unwrap();
    assert_eq!(w.grid().get(15, 15).mat, 0);
    assert!(count(&w, "water") < 31 * 31 - 80);
}

#[test]
fn explosion_centre_outside_the_world_is_harmless() {
    let mut w = World::new(8, 8, 1, forced()).unwrap();
    w.fill_rect(0, 0, 8, 8, "sand").unwrap();
    assert_eq!(
        w.explode(ExplosionSpec::new(i32::MIN, i32::MAX, 20, 1_000_000, 10))
            .unwrap(),
        0
    );
    assert_eq!(
        w.explode(ExplosionSpec::new(-3, -3, 5, 1_000_000, 10))
            .unwrap(),
        0
    );
    assert_eq!(count(&w, "sand"), 64);
}
