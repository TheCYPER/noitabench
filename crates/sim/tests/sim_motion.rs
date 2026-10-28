//! Motion rules: test vectors `SIM-T01..T13` of `pixel-simulation.md` (test configuration T).

mod common;
use common::*;

#[test]
fn sim_t01_free_fall() {
    let mut w = spaced(&["S", ".", "."], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &[".", "S", "."]);
}

#[test]
fn sim_t02_train_moves_once_each() {
    let mut w = spaced(&["S", "S", "S", ".", ".", "."], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &[".", "S", "S", "S", ".", "."]);
}

#[test]
fn sim_t03_rest_on_boundary() {
    let mut w = spaced(&[".", "S"], forced(), 1);
    w.step_frames(5).unwrap();
    assert_rows(&w, &[".", "S"]);
}

#[test]
fn sim_t04_sand_sinks_in_water() {
    let mut w = spaced(&["S", "W"], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &["W", "S"]);
    w.step().unwrap();
    assert_rows(&w, &["W", "S"]);
}

#[test]
fn sim_t05_water_sinks_in_oil_and_stays() {
    let mut w = spaced(&["W", "O"], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &["O", "W"]);
    w.step().unwrap();
    assert_rows(&w, &["O", "W"]);
}

#[test]
fn sim_t06_equal_density_never_swaps() {
    // sand and lava both have density 6.
    let mut w = spaced(&["S", "L"], forced(), 1);
    w.step_frames(3).unwrap();
    assert_rows(&w, &["S", "L"]);
}

#[test]
fn sim_t07_powder_slides_diagonally() {
    let mut w = spaced(&["S .", "# .", "# #"], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &[". .", "# S", "# #"]);
}

#[test]
fn sim_t08_liquid_hops_five_cells() {
    let mut w = spaced(&["W . . . . . . ."], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &[". . . . . W . ."]);
}

#[test]
fn sim_t09_hop_stops_at_a_wall() {
    let mut w = spaced(&["W . . # . . . ."], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &[". . W # . . . ."]);
}

#[test]
fn sim_t10_gas_rises_one_cell_per_frame() {
    let mut w = spaced(&[".", ".", ".", "G"], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &[".", ".", "G", "."]);
    w.step().unwrap();
    assert_rows(&w, &[".", "G", ".", "."]);
    w.step().unwrap();
    assert_rows(&w, &["G", ".", ".", "."]);
    w.step().unwrap();
    assert_rows(&w, &["G", ".", ".", "."]);
}

#[test]
fn sim_t11_gas_under_a_ceiling_goes_sideways() {
    let mut w = spaced(&["G . ."], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &[". G ."]);
}

#[test]
fn sim_t12_rising_gas_is_not_a_train() {
    let mut w = spaced(&[".", "G", "G", "G"], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &["G", ".", "G", "G"]);
    w.step().unwrap();
    assert_rows(&w, &["G", "G", ".", "G"]);
    w.step().unwrap();
    assert_rows(&w, &["G", "G", "G", "."]);
}

#[test]
fn sim_t13_displaced_liquid_may_be_displaced_again() {
    let mut w = spaced(&["W", "W", "O", "#"], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &["O", "W", "W", "#"]);
}

#[test]
fn sim_r30_liquid_displaces_gas_and_matter_is_conserved() {
    let mut w = spaced(&["W", "G", "#"], forced(), 1);
    w.step().unwrap();
    assert_rows(&w, &["G", "W", "#"]);
}

#[test]
fn sim_r30_static_is_never_entered() {
    // Wood has density 11, higher than anything that falls onto it.
    let mut w = spaced(&["S", "w"], forced(), 1);
    w.step_frames(4).unwrap();
    assert_rows(&w, &["S", "w"]);
}

#[test]
fn sim_r33_layering_by_density() {
    // oil (1) < acid (2.9) < water (4) < blood (4.1): whatever the start, they end up sorted.
    let mut w = spaced(&["O", "A", "W", "b", "#"], forced(), 3);
    w.step_frames(20).unwrap();
    assert_rows(&w, &["O", "A", "W", "b", "#"].map(|r| r));
    let mut w = spaced(&["b", "W", "A", "O", "#"], forced(), 3);
    w.step_frames(20).unwrap();
    assert_rows(&w, &["O", "A", "W", "b", "#"]);
}

#[test]
fn sim_r31_fall_steps_of_default_tuning() {
    // sand: 2g = 1.8 -> 1 step plus a 205/256 chance of a second; water: 3 steps (SIM-T22).
    let c = content(cogbench_sim::Tuning::default());
    let rt = |k: &str| *c.mats.rt(c.mats.index_of(k).unwrap());
    let sand = rt("sand");
    assert_eq!((sand.fall_int, sand.fall_frac_q8), (1, 205));
    let water = rt("water");
    assert_eq!((water.fall_int, water.fall_frac_q8), (3, 0));
    let lava = rt("lava");
    assert_eq!((lava.fall_int, lava.fall_frac_q8), (0, 102));
    let coal = rt("coal"); // gravity 2 -> 4 steps
    assert_eq!(coal.fall_int, 4);
}

#[test]
fn sim_r31_slide_chance_follows_viscosity() {
    let c = content(cogbench_sim::Tuning::default());
    let sand = c.mats.rt(c.mats.index_of("sand").unwrap());
    assert_eq!(sand.slide_q8, 192); // viscosity 50 -> 0.75
}

#[test]
fn sim_r35_timer_units_cover_the_lifetimes() {
    let c = content(cogbench_sim::Tuning::default());
    let steam = c.mats.rt(c.mats.index_of("steam").unwrap());
    assert_eq!((steam.life_unit, steam.life0), (4, 250)); // 1000 frames
    let gas = c.mats.rt(c.mats.index_of("flammable_gas").unwrap());
    assert_eq!(gas.life_unit, 0); // no lifetime: placed gas pockets persist (decision 2026-10-26)
    let wood = c.mats.rt(c.mats.index_of("wood").unwrap());
    assert_eq!((wood.burn_unit, wood.burn0), (3, 200)); // 600 frames of fuel
    let powder = c.mats.rt(c.mats.index_of("gunpowder").unwrap());
    assert_eq!(powder.burn0, 0); // fuel 0: converts on the first burning step
}

#[test]
fn sim_r31_slow_liquids_fall_on_the_same_frames_in_every_column() {
    // Lava falls less than one cell per frame. Six cells side by side, nothing in the way: they
    // must stay level with each other, frame after frame, and fall at the average rate 2g.
    let c = content(cogbench_sim::Tuning::default());
    let mut w = cogbench_sim::World::new(40, 400, 11, c).unwrap();
    for x in [2, 5, 9, 14, 20, 33] {
        w.paint(x, 0, 0, "lava").unwrap();
    }
    let row_of = |w: &cogbench_sim::World, x: i32| (0..400).find(|&y| w.grid().get(x, y).mat != 0);
    for f in 0..600 {
        w.step().unwrap();
        let rows: Vec<_> = [2, 5, 9, 14, 20, 33]
            .iter()
            .map(|&x| row_of(&w, x))
            .collect();
        assert!(rows.iter().all(|r| *r == rows[0]), "frame {f}: {rows:?}");
    }
    let fallen = f64::from(row_of(&w, 2).unwrap() as u32) / 600.0;
    assert!(
        (fallen - 0.4).abs() < 0.07,
        "lava falls {fallen} cells per frame"
    );
}

/// Of the lava cells below the shelf (in the air or on the way down), the share that has no lava
/// in its 8-neighbourhood, summed over frames 5, 10, ... 300.
fn stray_share(seed: u64) -> (u32, u32) {
    let mut w =
        cogbench_sim::World::new(256, 192, seed, content(cogbench_sim::Tuning::default())).unwrap();
    w.fill_rect(0, 170, 256, 22, "rock").unwrap();
    // A shelf with a 40-wide gap and lava piled on both halves: it pours through the gap.
    w.fill_rect(0, 62, 106, 7, "rock").unwrap();
    w.fill_rect(146, 62, 110, 7, "rock").unwrap();
    w.fill_rect(10, 44, 90, 18, "lava").unwrap();
    w.fill_rect(152, 44, 94, 18, "lava").unwrap();
    let lava = w.content().mats.index_of("lava").unwrap();
    let (mut total, mut strays) = (0, 0);
    for f in 1..=300 {
        w.step().unwrap();
        if f % 5 != 0 {
            continue;
        }
        for y in 70..160 {
            for x in 6..250 {
                if w.grid().get(x, y).mat != lava {
                    continue;
                }
                total += 1;
                let near = (-1..=1)
                    .flat_map(|dy| (-1..=1).map(move |dx| (dx, dy)))
                    .filter(|&d| d != (0, 0))
                    .any(|(dx, dy)| w.grid().get(x + dx, y + dy).mat == lava);
                strays += u32::from(!near);
            }
        }
    }
    (total, strays)
}

#[test]
fn sim_r32_a_pour_of_lava_stays_in_one_piece() {
    // Before the fix about one in ten falling lava cells was alone; now it is one in a few
    // hundred. The bound leaves room for the odd cell that slides off the side of a curtain.
    for seed in [1, 2, 3] {
        let (total, strays) = stray_share(seed);
        assert!(
            total > 10_000,
            "seed {seed}: the pour must actually reach the cells below"
        );
        assert!(
            u64::from(strays) * 50 < u64::from(total),
            "seed {seed}: {strays} of {total} lava cells fell alone"
        );
    }
}

#[test]
fn sim_r32_slow_liquid_steps_off_an_edge_instead_of_hopping_into_the_air() {
    // A lone lava cell on a shelf, walled in on the left, with the shelf ending three cells to
    // its right. The first hop it makes ends on the edge cell (x = 8), not five cells out.
    let c = content(cogbench_sim::Tuning::default());
    for seed in 0..8 {
        let mut w = cogbench_sim::World::new(24, 12, seed, c.clone()).unwrap();
        w.fill_rect(0, 6, 8, 3, "rock").unwrap(); // shelf: x 0..7
        w.fill_rect(3, 5, 1, 1, "rock").unwrap(); // wall left of the lava
        w.paint(4, 5, 0, "lava").unwrap();
        let lava = w.content().mats.index_of("lava").unwrap();
        let lava_x = |w: &cogbench_sim::World| (0..24).find(|&x| w.grid().get(x, 5).mat == lava);
        let mut landed = None;
        for _ in 0..40 {
            w.step().unwrap();
            let x = lava_x(&w);
            if x != Some(4) {
                landed = x;
                break;
            }
        }
        assert_eq!(landed, Some(8), "seed {seed}");
    }
}
