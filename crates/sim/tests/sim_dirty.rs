//! Chunks, dirty rectangles and scheduling: `SIM-R10..R15`, `SIM-R20`, `SIM-R21`, `SIM-R12`,
//! `SIM-R72`, vectors `SIM-T14..T17`, `SIM-T20`, `SIM-T21`, `SIM-T36`.

mod common;
use cogbench_sim::world::{pass_order, scan_left_to_right};
use cogbench_sim::{DirtyMode, Rect, Tuning};
use common::*;

fn all_clean(w: &cogbench_sim::World) -> bool {
    let (cw, ch) = w.grid().chunk_dims();
    (0..ch).all(|cy| (0..cw).all(|cx| w.grid().dirty_rect(cx, cy).is_empty()))
}

#[test]
fn sim_t14_updated_never_survives_a_frame() {
    let mut w = spaced(
        &["S", "S", "W", "W", ".", ".", "."],
        content(Tuning::default()),
        5,
    );
    for _ in 0..30 {
        w.step().unwrap();
        assert!(w
            .grid()
            .cells()
            .iter()
            .all(|c| c.flags & cogbench_sim::grid::UPDATED == 0));
    }
}

#[test]
fn sim_t15_cell_that_slept_wakes_when_its_floor_goes_away() {
    // A settled grain, a clean chunk, then the floor is removed some frames later.
    let mut w = spaced(&[".", "S", "D"], forced(), 1);
    w.step_frames(10).unwrap();
    assert!(all_clean(&w), "a resting grain must let its chunk sleep");
    w.fill_rect(0, 2, 1, 1, "air").unwrap();
    w.step().unwrap();
    assert_rows(&w, &[".", ".", "S"]);
}

#[test]
fn sim_r10_settled_world_costs_nothing() {
    let mut w = spaced(&[". . .", "S . S", "# # #"], forced(), 1);
    w.step_frames(3).unwrap();
    assert!(all_clean(&w));
}

#[test]
fn sim_t16_pass_order_rotates_with_the_frame() {
    assert_eq!(pass_order(0), [(0, 0), (1, 0), (0, 1), (1, 1)]);
    assert_eq!(pass_order(1), [(1, 0), (0, 1), (1, 1), (0, 0)]);
    assert_eq!(pass_order(2), [(0, 1), (1, 1), (0, 0), (1, 0)]);
    assert_eq!(pass_order(3), [(1, 1), (0, 0), (1, 0), (0, 1)]);
    assert_eq!(pass_order(4), pass_order(0));
}

#[test]
fn sim_t17_scan_direction_alternates() {
    assert!(scan_left_to_right(0, 0, 0));
    assert!(!scan_left_to_right(0, 1, 0));
    assert!(!scan_left_to_right(1, 0, 0));
    assert!(scan_left_to_right(1, 1, 0));
}

#[test]
fn sim_t20_wake_margin_is_dilated_and_clipped_to_chunks() {
    let mut w = cogbench_sim::World::new(128, 128, 1, forced()).unwrap();
    w.paint(63, 10, 0, "rock").unwrap();
    let r = |cx, cy| w.grid().dirty_rect(cx, cy);
    assert_eq!(
        r(0, 0),
        Rect {
            x0: 51,
            y0: 0,
            x1: 63,
            y1: 22
        }
    );
    assert_eq!(
        r(1, 0),
        Rect {
            x0: 64,
            y0: 0,
            x1: 75,
            y1: 22
        }
    );
    assert!(r(0, 1).is_empty() && r(1, 1).is_empty());
}

#[test]
fn sim_t20_wake_reaches_the_chunks_above() {
    let mut w = cogbench_sim::World::new(128, 128, 1, forced()).unwrap();
    w.paint(63, 70, 0, "rock").unwrap(); // chunk (0,1), local y 6
    assert_eq!(
        w.grid().dirty_rect(0, 0),
        Rect {
            x0: 51,
            y0: 58,
            x1: 63,
            y1: 63
        }
    );
    assert_eq!(
        w.grid().dirty_rect(0, 1),
        Rect {
            x0: 51,
            y0: 64,
            x1: 63,
            y1: 82
        }
    );
}

#[test]
fn sim_t21_timer_keeps_the_chunk_awake_until_the_cell_expires() {
    let mut w = cogbench_sim::World::new(8, 8, 1, forced()).unwrap();
    w.paint(4, 6, 0, "steam").unwrap();
    for f in 0..1000 {
        if w.grid().cells().iter().all(|c| c.mat == 0) {
            // expired within one life unit (4 frames) of 1000 frames
            assert!((996..1000).contains(&f), "expired at frame {f}");
            w.step().unwrap();
            assert!(all_clean(&w), "the chunk must sleep once nothing is left");
            return;
        }
        assert!(
            !all_clean(&w),
            "frame {f}: a timer must keep its chunk dirty"
        );
        w.step().unwrap();
    }
    panic!("steam never expired");
}

#[test]
fn sim_t36_burning_cell_keeps_awake_then_chunk_goes_clean() {
    let mut w = cogbench_sim::World::new(5, 5, 1, forced()).unwrap();
    w.paint(2, 2, 0, "wood").unwrap();
    assert!(w.ignite(2, 2));
    let mut gone_at = None;
    for f in 0..700 {
        if w.grid().get(2, 2).mat == 0 {
            gone_at = Some(f);
            break;
        }
        assert!(
            !all_clean(&w),
            "frame {f}: a burning cell must keep its chunk dirty"
        );
        w.step().unwrap();
    }
    let f = gone_at.expect("wood burns out");
    assert!(
        (594..=600).contains(&f),
        "600 frames of fuel, burned out at {f}"
    );
}

#[test]
fn sim_r12_sleeping_cells_have_nothing_to_do() {
    // Let a scene settle completely, then force every cell to be visited once: nothing may change
    // (a skipped cell must be an exact no-op, SIM-R11).
    let mut w = cogbench_sim::World::new(64, 40, 9, content(Tuning::default())).unwrap();
    w.fill_rect(0, 36, 64, 4, "ground").unwrap();
    // A basin exactly full of water with oil on top, so every liquid row is complete.
    w.fill_rect(30, 24, 2, 12, "rock").unwrap();
    w.fill_rect(44, 24, 2, 12, "rock").unwrap();
    w.fill_rect(32, 31, 12, 5, "water").unwrap();
    w.fill_rect(32, 29, 12, 2, "oil").unwrap();
    // Powder piles that must find their angle of repose.
    w.paint(8, 10, 4, "sand").unwrap();
    w.paint(20, 14, 3, "coal").unwrap();
    w.paint(52, 12, 4, "gunpowder").unwrap();
    for _ in 0..3000 {
        w.step().unwrap();
        if all_clean(&w) {
            break;
        }
    }
    assert!(all_clean(&w), "the scene should settle completely");
    let strip = |w: &cogbench_sim::World| {
        let mut v = w.grid().cells().to_vec();
        v.iter_mut().for_each(|c| c.flags = 0);
        v
    };
    let settled = strip(&w);
    w.set_dirty_mode(DirtyMode::AllDirty);
    w.step_frames(3).unwrap();
    assert_eq!(
        settled,
        strip(&w),
        "an all-dirty frame changed a world that was asleep"
    );
}

#[test]
fn sim_r21_matter_crosses_chunk_borders() {
    // A grain falls 130 cells through three chunk rows and lands on the floor.
    let mut w = cogbench_sim::World::new(200, 150, 4, content(Tuning::default())).unwrap();
    w.fill_rect(0, 140, 200, 10, "rock").unwrap();
    w.paint(30, 5, 0, "sand").unwrap();
    w.step_frames(120).unwrap();
    assert_eq!(
        w.grid().get(30, 139).mat,
        w.content().mats.index_of("sand").unwrap()
    );

    // A lone droplet on an open floor keeps hopping, and crosses the border at x = 64 both ways.
    let mut w = cogbench_sim::World::new(200, 150, 4, content(Tuning::default())).unwrap();
    w.fill_rect(0, 140, 200, 10, "rock").unwrap();
    w.paint(60, 139, 0, "water").unwrap();
    let water = w.content().mats.index_of("water").unwrap();
    let mut sides = std::collections::BTreeSet::new();
    for _ in 0..40 {
        w.step().unwrap();
        let x = (0..200)
            .find(|&x| w.grid().get(x, 139).mat == water)
            .unwrap();
        sides.insert(x >= 64);
    }
    assert_eq!(sides.len(), 2, "the droplet crosses the chunk border");
}

#[test]
fn sim_r12_a_cell_with_a_reaction_partner_beside_it_stays_awake() {
    let c = content(Tuning::default());
    // Acid on rock: corroding goes on, so the chunk never sleeps.
    let mut w = cogbench_sim::World::new(8, 4, 1, c.clone()).unwrap();
    w.fill_rect(0, 2, 8, 2, "rock").unwrap();
    w.fill_rect(0, 1, 8, 1, "acid").unwrap();
    w.step_frames(20).unwrap();
    assert!(!all_clean(&w));
    // Acid on brick (not corrodible): nothing to do, the chunk goes to sleep.
    let mut w = cogbench_sim::World::new(8, 4, 1, c).unwrap();
    w.fill_rect(0, 2, 8, 2, "brick").unwrap();
    w.fill_rect(0, 1, 8, 1, "acid").unwrap();
    w.step_frames(40).unwrap();
    assert!(all_clean(&w));
}

#[test]
fn editing_arguments_are_validated_not_overflowed() {
    let mut w = cogbench_sim::World::new(8, 8, 1, forced()).unwrap();
    assert!(w.paint(4, 4, 1 << 30, "sand").is_err());
    assert!(w.paint(i32::MAX, 0, 2, "sand").is_err());
    assert!(w.paint(i32::MIN, 0, 2, "sand").is_err());
    assert!(w.paint(0, i32::MIN, 2, "sand").is_err());
    assert!(w.fill_rect(i32::MIN, 0, 2, 2, "sand").is_err());
    assert!(w.fill_rect(i32::MAX - 1, 0, 10, 10, "sand").is_err());
    assert!(w.fill_rect(0, 0, -1, 5, "sand").is_err());
    // far outside the world is fine: clipped
    w.fill_rect(-1000, -1000, 5000, 5000, "rock").unwrap();
    assert!(w
        .grid_bytes()
        .iter()
        .all(|&m| m == w.content().mats.index_of("rock").unwrap()));
    w.paint(-5, -5, 3, "sand").unwrap();
}

#[test]
fn sim_r72_dirty_rectangles_are_transparent() {
    // The same soup with dirty rectangles on and with every cell visited every frame must end
    // in the same state after every frame: skipped cells really are exact no-ops. The worlds
    // span 2 to 4 chunk columns and rows, with the motion rules forced and as shipped.
    const SIZES: [(i32, i32); 4] = [(96, 80), (140, 150), (200, 70), (70, 200)];
    for soup_seed in 0..16u64 {
        let (w, h) = SIZES[soup_seed as usize % SIZES.len()];
        let tuning = if soup_seed.is_multiple_of(3) {
            Tuning::forced()
        } else {
            Tuning::default()
        };
        let mut sleepy = soup(w, h, 5, soup_seed, content(tuning));
        let mut eager = soup(w, h, 5, soup_seed, content(tuning));
        eager.set_dirty_mode(DirtyMode::AllDirty);
        for f in 0..250 {
            sleepy.step().unwrap();
            eager.step().unwrap();
            assert_eq!(
                sleepy.state_hash(),
                eager.state_hash(),
                "soup {soup_seed} ({w}x{h}), frame {f}"
            );
        }
        assert_eq!(fingerprint(&mut sleepy).1, fingerprint(&mut eager).1);
    }
}

/// Build the same scene twice, once with sleeping chunks and once with every cell awake, and
/// step both: the hashes must agree after every frame.
fn assert_modes_agree(build: impl Fn() -> cogbench_sim::World, frames: u32, what: &str) {
    let (mut sleepy, mut eager) = (build(), build());
    eager.set_dirty_mode(DirtyMode::AllDirty);
    for f in 0..frames {
        sleepy.step().unwrap();
        eager.step().unwrap();
        assert_eq!(sleepy.state_hash(), eager.state_hash(), "{what}: frame {f}");
    }
}

#[test]
fn sim_r72_a_gap_moving_along_a_liquid_row_is_followed_past_the_dirty_rectangle() {
    // A single-row lake 80 cells long, asleep, then one cell of it is removed. Every cell to the
    // right hops left in turn, so the gap travels the whole row in one frame, far beyond the
    // WAKE margin of the edit. The row crosses the chunk border at x = 64; the gap is placed at
    // several distances from it and the scan runs both ways over the frames.
    for gap in [4, 20, 50, 63, 64] {
        assert_modes_agree(
            || {
                let mut w = cogbench_sim::World::new(96, 8, 3, content(Tuning::forced())).unwrap();
                w.fill_rect(0, 7, 96, 1, "rock").unwrap();
                w.fill_rect(0, 6, 1, 1, "rock").unwrap();
                w.fill_rect(1, 6, 90, 1, "water").unwrap();
                w.fill_rect(91, 6, 1, 1, "rock").unwrap();
                w.step_frames(20).unwrap();
                w.fill_rect(gap, 6, 1, 1, "air").unwrap();
                w
            },
            6,
            &format!("gap at x={gap}"),
        );
    }
}

#[test]
fn sim_r72_a_falling_train_longer_than_the_wake_margin_moves_as_a_whole() {
    // Sand packed in a 1-wide shaft, 75 cells tall, asleep; the cell under it is removed. With
    // every cell awake the whole column steps down at once (SIM-T02), and so it must with
    // sleeping chunks although the edit only wakes the lowest 12 cells.
    let build = || {
        let mut w = cogbench_sim::World::new(8, 100, 1, content(Tuning::forced())).unwrap();
        w.fill_rect(0, 95, 8, 5, "rock").unwrap();
        w.fill_rect(2, 0, 1, 95, "rock").unwrap();
        w.fill_rect(4, 0, 1, 95, "rock").unwrap();
        w.fill_rect(3, 20, 1, 75, "sand").unwrap();
        w.step_frames(30).unwrap();
        w.fill_rect(3, 95, 1, 1, "air").unwrap();
        w
    };
    assert_modes_agree(build, 6, "75-cell column");
    let mut w = build();
    w.step().unwrap();
    let top = (0..100).find(|&y| w.grid().get(3, y).mat != 0).unwrap();
    assert_eq!(
        top, 21,
        "the top of the train moved down in the first frame"
    );
}

#[test]
fn sim_r72_a_write_in_the_top_row_of_the_rectangle_wakes_the_rows_above_it() {
    // C rests on X in a notch with rock on both sides of the pair, and X can slide out under
    // the overhang. After the first frame the dirty rectangle of the chunk is the single cell
    // of X (when its slide roll failed), so X sits in the top row of the rectangle. When X
    // slides away the cell above it falls into the hole in the same frame, as it does with
    // every cell awake: the scan must go on above the rectangle it started with.
    for seed in 0..40u64 {
        assert_modes_agree(
            || {
                let mut w =
                    cogbench_sim::World::new(16, 30, seed, content(Tuning::default())).unwrap();
                w.fill_rect(7, 8, 1, 4, "rock").unwrap();
                w.fill_rect(9, 8, 1, 4, "rock").unwrap();
                w.fill_rect(0, 12, 9, 18, "rock").unwrap();
                w.fill_rect(9, 13, 7, 17, "rock").unwrap();
                w.fill_rect(8, 10, 1, 2, "sand").unwrap(); // C on row 10, X on row 11
                w
            },
            12,
            &format!("seed {seed}"),
        );
    }
}

/// A world of loose matter between platforms and walls, `build` of the sparse-edit test below.
fn sparse_world(scenario: u64, eager: bool) -> cogbench_sim::World {
    use cogbench_sim::rng::Stream;
    let mut r = Stream::new(scenario, "sparse-size");
    let (w, h) = (100 + r.below(100) as i32, 100 + r.below(100) as i32);
    let tuning = if scenario.is_multiple_of(3) {
        Tuning::forced()
    } else {
        Tuning::default()
    };
    let mut world = cogbench_sim::World::new(w, h, scenario * 7 + 1, content(tuning)).unwrap();
    if eager {
        world.set_dirty_mode(DirtyMode::AllDirty);
    }
    let keys: Vec<String> = world
        .content()
        .mats
        .iter()
        .skip(1)
        .filter(|m| m.key != "fire")
        .map(|m| m.key.clone())
        .collect();
    let mut r = Stream::new(scenario, "sparse-build");
    world.fill_rect(0, h - 4, w, 4, "rock").unwrap();
    for _ in 0..(6 + r.below(10)) {
        let (x, y) = (r.below(w as u32) as i32, r.below(h as u32 - 10) as i32);
        let len = 5 + r.below(50) as i32;
        world
            .fill_rect(x, y, len, 1 + r.below(3) as i32, "rock")
            .unwrap();
    }
    for _ in 0..(3 + r.below(6)) {
        let (x, y) = (r.below(w as u32) as i32, r.below(h as u32 - 10) as i32);
        let len = 5 + r.below(40) as i32;
        world
            .fill_rect(x, y, 1 + r.below(2) as i32, len, "rock")
            .unwrap();
    }
    for _ in 0..(3 + r.below(5)) {
        let key = &keys[r.below(keys.len() as u32) as usize];
        let (x, y) = (r.below(w as u32) as i32, r.below(h as u32 - 10) as i32);
        world.paint(x, y, 1 + r.below(5) as i32, key).unwrap();
    }
    world
}

#[test]
fn sim_r72_edits_to_settled_sparse_worlds_wake_exactly_what_every_cell_awake_would_move() {
    // Mostly asleep worlds, poked every 25 frames by the same random edit in both modes: the
    // state and the event log must agree after every frame. The first six scenarios failed
    // while the scan kept the dirty rectangle it started with.
    use cogbench_sim::rng::Stream;
    for scenario in [1u64, 16, 166, 190, 205, 230, 0, 2, 3, 4, 5, 6, 7, 8] {
        let (mut sleepy, mut eager) = (sparse_world(scenario, false), sparse_world(scenario, true));
        let (w, h) = (sleepy.width(), sleepy.height());
        let keys: Vec<String> = sleepy
            .content()
            .mats
            .iter()
            .skip(1)
            .map(|m| m.key.clone())
            .collect();
        let mut edits = Stream::new(scenario, "sparse-edits");
        for f in 0..400 {
            if f % 25 == 24 {
                let key = keys[edits.below(keys.len() as u32) as usize].as_str();
                let key = if edits.below(3) == 0 { "air" } else { key };
                let (x, y) = (edits.below(w as u32) as i32, edits.below(h as u32) as i32);
                let (ew, eh) = (1 + edits.below(8) as i32, 1 + edits.below(30) as i32);
                sleepy.fill_rect(x, y, ew, eh, key).unwrap();
                eager.fill_rect(x, y, ew, eh, key).unwrap();
            }
            sleepy.step().unwrap();
            eager.step().unwrap();
            assert_eq!(
                fingerprint(&mut sleepy),
                fingerprint(&mut eager),
                "scenario {scenario}, frame {f}"
            );
        }
    }
}

#[test]
fn sim_r72_a_snapshot_taken_with_partly_asleep_chunks_continues_like_the_original() {
    // The scheduler state is the per-chunk dirty rectangles; the snapshot must carry exactly
    // that. Sparse worlds have most chunks asleep and the rest half awake at the cut.
    for scenario in [1u64, 5, 9, 16, 190] {
        let mut a = sparse_world(scenario, false);
        a.step_frames(120).unwrap();
        let blob = a.snapshot().unwrap();
        let mut b = cogbench_sim::World::new(8, 8, 0, a.content().clone()).unwrap();
        b.restore(&blob).unwrap();
        for f in 0..200 {
            a.step().unwrap();
            b.step().unwrap();
            assert_eq!(
                a.state_hash(),
                b.state_hash(),
                "scenario {scenario}, frame {f} after the cut"
            );
        }
        assert_eq!(a.snapshot().unwrap(), b.snapshot().unwrap());
    }
}
