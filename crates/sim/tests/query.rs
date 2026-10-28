//! Grid queries for entities and projectiles: `SIM-R60..R65`, `MVP-R05`, `HAZ-R01`, vectors
//! `SIM-T30` and `MV-18`.

mod common;
use cogbench_sim::{unit_q16, Aabb, ContactRules, Kind, KindMask, QueryMask, World};
use common::*;

fn idx(w: &World, key: &str) -> u8 {
    w.content().mats.index_of(key).unwrap()
}

// ----- rays ---------------------------------------------------------------------------------

#[test]
fn sim_t30_four_ray_masks_stop_on_different_cells() {
    // Column top to bottom: air, steam, water, sand, rock.
    let w = scene(&[".", "G", "W", "S", "#", "#"], forced(), 1);
    let first = |mask: KindMask| w.raycast((0, 0), (0, 5), mask).map(|h| h.y);
    assert_eq!(
        first(KindMask::RAYTRACE),
        Some(1),
        "any cell that is not air"
    );
    assert_eq!(
        first(KindMask::SURFACES),
        Some(3),
        "not liquid, gas or fire"
    );
    assert_eq!(
        first(KindMask::SURFACES_AND_LIQUIDS),
        Some(2),
        "not gas or fire"
    );
    assert_eq!(first(KindMask::PLATFORMS), Some(3), "kind based in v1");
    assert_eq!(first(KindMask::BLOCKING), Some(3));
}

#[test]
fn sim_r60_fire_and_gas_are_passed_by_surface_masks() {
    let w = scene(&[".", "F", "f", "W", "#"], forced(), 1);
    let hit = w
        .raycast((0, 0), (0, 4), KindMask::SURFACES_AND_LIQUIDS)
        .unwrap();
    assert_eq!((hit.y, hit.kind), (3, Kind::Liquid));
    let hit = w.raycast((0, 0), (0, 4), KindMask::RAYTRACE).unwrap();
    assert_eq!((hit.y, hit.kind), (1, Kind::Fire));
}

#[test]
fn sim_r62_hit_reports_cell_material_last_free_cell_and_t() {
    let w = scene(&["....#...", "........"], forced(), 1);
    let hit = w.raycast((0, 0), (7, 0), KindMask::BLOCKING).unwrap();
    assert_eq!((hit.x, hit.y), (4, 0));
    assert_eq!(hit.material, idx(&w, "rock"));
    assert_eq!(hit.last_free, Some((3, 0)));
    assert_eq!((hit.step, hit.steps), (4, 7));
    assert_eq!(hit.t_q16(), 4 * 65_536 / 7);
    // Nothing on the lower row.
    assert_eq!(w.raycast((0, 1), (7, 1), KindMask::BLOCKING), None);
    assert!(!w.line_blocked((0, 1), (7, 1), KindMask::BLOCKING));
    assert!(w.line_blocked((0, 0), (7, 0), KindMask::BLOCKING));
}

#[test]
fn sim_r62_the_line_is_a_connected_dda_with_exact_ends() {
    // (0,0) -> (5,2) visits (0,0) (1,0) (2,1) (3,1) (4,2) (5,2): a rock on (4,2) is hit at
    // step 4 with (3,1) free before it; a rock on (2,0), which is off the line, is not.
    let w = scene(&["..#...", "......", "....#.", "......"], forced(), 1);
    let hit = w.raycast((0, 0), (5, 2), KindMask::BLOCKING).unwrap();
    assert_eq!(
        (hit.x, hit.y, hit.step, hit.last_free),
        (4, 2, 4, Some((3, 1)))
    );
    // The same line walked backwards finds the same obstacle cell.
    let back = w.raycast((5, 2), (0, 0), KindMask::BLOCKING).unwrap();
    assert_eq!((back.x, back.y), (4, 2));
    // Every step of a long shallow line changes x by one and y by at most one.
    let mut open = scene(&["................"; 12], forced(), 1);
    open.fill_rect(15, 11, 1, 1, "rock").unwrap();
    let hit = open.raycast((0, 0), (15, 11), KindMask::BLOCKING).unwrap();
    assert_eq!((hit.x, hit.y, hit.step, hit.steps), (15, 11, 15, 15));
}

#[test]
fn sim_r62_a_line_starting_inside_an_obstacle_hits_at_step_zero() {
    let w = scene(&["##..", "...."], forced(), 1);
    let hit = w.raycast((0, 0), (3, 0), KindMask::BLOCKING).unwrap();
    assert_eq!((hit.x, hit.y, hit.step, hit.last_free), (0, 0, 0, None));
    assert_eq!(hit.t_q16(), 0);
    // A zero-length line tests its single cell.
    assert!(w.raycast((1, 0), (1, 0), KindMask::BLOCKING).is_some());
    assert!(w.raycast((3, 0), (3, 0), KindMask::BLOCKING).is_none());
}

#[test]
fn sim_r62_go_through_this_material_removes_one_material_from_the_mask() {
    let w = scene(&["S#."], forced(), 1);
    let sand = idx(&w, "sand");
    let plain = w.raycast((0, 0), (2, 0), KindMask::BLOCKING).unwrap();
    assert_eq!(plain.x, 0);
    let through = w
        .raycast(
            (0, 0),
            (2, 0),
            QueryMask::new(KindMask::BLOCKING).passing(sand),
        )
        .unwrap();
    assert_eq!((through.x, through.material), (1, idx(&w, "rock")));
}

#[test]
fn sim_r01_the_world_edge_blocks_every_mask() {
    let w = scene(&["....", "...."], forced(), 1);
    // Leaving the world to the right: a hit on the boundary material one cell past the edge.
    let hit = w.raycast((1, 0), (10, 0), KindMask::BLOCKING).unwrap();
    assert_eq!(
        (hit.x, hit.y, hit.material, hit.kind),
        (4, 0, 255, Kind::Static)
    );
    assert_eq!(hit.last_free, Some((3, 0)));
    // Even a mask that matches nothing is stopped by the edge.
    assert!(w.raycast((0, 0), (0, 9), KindMask::NONE).is_some());
    // A line that starts outside hits at step 0.
    let hit = w.raycast((-5, 0), (3, 0), KindMask::BLOCKING).unwrap();
    assert_eq!((hit.step, hit.material), (0, 255));
    // Extreme coordinates terminate and agree.
    let far = w
        .raycast((0, 0), (i32::MAX, i32::MAX), KindMask::NONE)
        .unwrap();
    assert_eq!(far.material, 255);
    assert!(w
        .raycast((i32::MIN, i32::MIN), (i32::MAX, i32::MAX), KindMask::NONE)
        .is_some());
    assert!(w.blocked_at(-1, 0, KindMask::NONE));
    assert!(!w.blocked_at(0, 0, KindMask::BLOCKING));
}

#[test]
fn sim_r63_normal_points_away_from_the_floor_and_the_wall() {
    let mut w = World::new(40, 30, 1, forced()).unwrap();
    w.fill_rect(0, 20, 40, 10, "rock").unwrap();
    // Standing on flat ground: straight up.
    let n = w.surface_normal(20, 19, KindMask::BLOCKING);
    assert_eq!(n.0, 0);
    assert!(n.1 < 0);
    assert_eq!(unit_q16(n), (0, -65_536));
    // Next to a wall on the right: pushes left.
    w.fill_rect(30, 0, 10, 20, "rock").unwrap();
    let n = w.surface_normal(29, 5, KindMask::BLOCKING);
    assert!(n.0 < 0 && n.1 == 0);
    // In an inner corner (wall right, floor below) it points up and left.
    let n = w.surface_normal(29, 19, KindMask::BLOCKING);
    assert!(n.0 < 0 && n.1 < 0);
    // Open air: nothing blocks, no normal.
    assert_eq!(w.surface_normal(10, 5, KindMask::BLOCKING), (0, 0));
}

#[test]
fn sim_r63_unit_vectors_are_integer_q16() {
    assert_eq!(unit_q16((3, 4)), (39_321, 52_428)); // 0.6 and 0.8, rounded toward zero
    assert_eq!(unit_q16((-3, 4)), (-39_321, 52_428));
    assert_eq!(unit_q16((0, 0)), (0, 0));
    assert_eq!(unit_q16((7, 0)), (65_536, 0));
    // Largest inputs neither overflow nor panic.
    let (x, y) = unit_q16((i32::MIN, i32::MIN));
    assert!(
        (x + 46_341).abs() <= 1 && (y + 46_341).abs() <= 1,
        "{x} {y}"
    );
}

// ----- box sweeps ---------------------------------------------------------------------------

fn arena() -> World {
    // 60 x 40, floor from y = 30, walls at x = 0 and x = 59 are the world edge.
    let mut w = World::new(60, 40, 1, forced()).unwrap();
    w.fill_rect(0, 30, 60, 10, "rock").unwrap();
    w
}

#[test]
fn sim_r65_a_falling_box_lands_on_the_floor() {
    let w = arena();
    let b = Aabb::new(10, 0, 4, 6);
    let s = w.sweep_box(b, 0, 100, KindMask::BLOCKING, 0);
    assert_eq!(
        (s.x, s.y),
        (10, 24),
        "bottom row 29 sits on the floor at 30"
    );
    assert_eq!(s.blocked_y, Some(idx(&w, "rock")));
    assert_eq!(s.blocked_x, None);
    // A shorter fall is not blocked.
    let s = w.sweep_box(b, 0, 10, KindMask::BLOCKING, 0);
    assert_eq!((s.y, s.blocked_y), (10, None));
}

#[test]
fn sim_r65_a_box_stops_at_a_wall_and_reports_what_stopped_it() {
    let mut w = arena();
    w.fill_rect(30, 20, 3, 10, "brick").unwrap();
    let b = Aabb::new(10, 24, 4, 6);
    let s = w.sweep_box(b, 40, 0, KindMask::BLOCKING, 0);
    assert_eq!((s.x, s.y), (26, 24), "right edge touches the wall at 30");
    assert_eq!(s.blocked_x, Some(idx(&w, "brick")));
    let s = w.sweep_box(Aabb::new(40, 24, 4, 6), -40, 0, KindMask::BLOCKING, 0);
    assert_eq!(s.x, 33);
}

#[test]
fn mvp_r05_liquid_gas_and_fire_do_not_block_but_powder_does() {
    let mut w = arena();
    w.fill_rect(20, 24, 4, 6, "water").unwrap();
    w.fill_rect(24, 24, 4, 6, "steam").unwrap();
    w.fill_rect(28, 24, 4, 6, "fire").unwrap();
    let b = Aabb::new(10, 24, 4, 6);
    let s = w.sweep_box(b, 40, 0, KindMask::BLOCKING, 0);
    assert_eq!(
        (s.x, s.blocked_x),
        (50, None),
        "swims, drifts and burns through"
    );
    w.fill_rect(34, 24, 2, 6, "sand").unwrap();
    let s = w.sweep_box(b, 40, 0, KindMask::BLOCKING, 0);
    assert_eq!((s.x, s.blocked_x), (30, Some(idx(&w, "sand"))));
    // Asking for liquids as obstacles stops the box at the water.
    let wet = KindMask::BLOCKING.union(KindMask::LIQUID);
    assert_eq!(w.sweep_box(b, 40, 0, wet, 0).x, 16);
}

#[test]
fn sim_r65_ledges_up_to_step_up_are_climbed() {
    let mut w = arena();
    w.fill_rect(30, 27, 20, 3, "rock").unwrap(); // a ledge 3 cells high
    let b = Aabb::new(20, 24, 4, 6);
    let s = w.sweep_box(b, 20, 0, KindMask::BLOCKING, 4);
    assert_eq!((s.x, s.y, s.climbed, s.blocked_x), (40, 21, 3, None));
    // The same ledge stops a box that cannot climb, or one that climbs only 2.
    assert_eq!(w.sweep_box(b, 20, 0, KindMask::BLOCKING, 0).x, 26);
    assert_eq!(w.sweep_box(b, 20, 0, KindMask::BLOCKING, 2).x, 26);
    // A ledge of 5 is too high for 4.
    let mut w = arena();
    w.fill_rect(30, 25, 20, 5, "rock").unwrap();
    let s = w.sweep_box(b, 20, 0, KindMask::BLOCKING, 4);
    assert_eq!((s.x, s.climbed, s.blocked_x.is_some()), (26, 0, true));
}

#[test]
fn sim_r65_a_large_step_up_finds_the_exact_ledge_height_or_gives_up() {
    // The strip above the box is tested one row at a time: a step_up of 100 climbs a ledge of 12
    // by exactly 12, and gives up at a wall that reaches the top of the world.
    let b = Aabb::new(20, 24, 4, 6);
    let mut w = arena();
    w.fill_rect(30, 18, 20, 12, "rock").unwrap();
    let s = w.sweep_box(b, 20, 0, KindMask::BLOCKING, 100);
    assert_eq!((s.x, s.y, s.climbed, s.blocked_x), (40, 12, 12, None));
    let mut w = arena();
    w.fill_rect(30, 0, 20, 30, "rock").unwrap();
    let s = w.sweep_box(b, 20, 0, KindMask::BLOCKING, 100);
    assert_eq!((s.x, s.y, s.climbed), (26, 24, 0));
    assert_eq!(s.blocked_x, Some(idx(&w, "rock")));
    // A solid beam above the box ends the search at once, whatever the wall in front looks like.
    let mut w = arena();
    w.fill_rect(30, 10, 20, 20, "rock").unwrap();
    w.fill_rect(10, 20, 30, 2, "brick").unwrap();
    assert_eq!(w.sweep_box(b, 20, 0, KindMask::BLOCKING, 100).x, 26);
}

#[test]
fn sim_r65_a_low_ceiling_prevents_the_climb() {
    let mut w = arena();
    w.fill_rect(30, 27, 20, 3, "rock").unwrap(); // a ledge 3 cells high
    w.fill_rect(10, 20, 50, 3, "rock").unwrap(); // a ceiling right above the box (rows 20..22)
    let b = Aabb::new(20, 23, 4, 7);
    // Lifting needs the rows above the box free, and they are rock.
    let s = w.sweep_box(b, 20, 0, KindMask::BLOCKING, 4);
    assert_eq!((s.x, s.climbed), (26, 0));
    assert!(s.blocked_x.is_some());
}

#[test]
fn sim_r65_a_box_embedded_in_rock_can_leave_but_not_go_deeper() {
    let w = arena();
    let b = Aabb::new(10, 28, 4, 6); // rows 28..33: rows 30.. are inside the floor
    assert!(w.box_blocked(b, KindMask::BLOCKING));
    let up = w.sweep_box(b, 0, -5, KindMask::BLOCKING, 0);
    assert_eq!((up.y, up.blocked_y), (23, None), "free to move out");
    let down = w.sweep_box(b, 0, 5, KindMask::BLOCKING, 0);
    assert_eq!((down.y, down.blocked_y.is_some()), (28, true), "not deeper");
    assert!(!w.box_blocked(up_box(up), KindMask::BLOCKING));
}

fn up_box(s: cogbench_sim::Sweep) -> Aabb {
    Aabb::new(s.x, s.y, 4, 6)
}

#[test]
fn sim_r01_boxes_cannot_leave_the_world_and_extreme_moves_terminate() {
    let w = arena();
    let b = Aabb::new(2, 10, 4, 6);
    let s = w.sweep_box(b, -100, 0, KindMask::NONE, 0);
    assert_eq!((s.x, s.blocked_x), (0, Some(255)));
    let s = w.sweep_box(b, i32::MAX, i32::MIN, KindMask::BLOCKING, 0);
    assert_eq!((s.x, s.y), (56, 0));
    assert_eq!((s.blocked_x, s.blocked_y), (Some(255), Some(255)));
    // A box outside the world cannot move in.
    let out = w.sweep_box(Aabb::new(-50, 10, 4, 6), 100, 0, KindMask::BLOCKING, 0);
    assert_eq!(out.x, -50);
    // Boxes at the extremes of i32 do not overflow.
    let far = w.sweep_box(
        Aabb::new(i32::MAX - 1, i32::MAX - 1, 5, 5),
        3,
        3,
        KindMask::BLOCKING,
        4,
    );
    assert_eq!((far.x, far.y), (i32::MAX - 1, i32::MAX - 1));
}

#[test]
fn sim_r65_empty_boxes_do_not_move_or_block() {
    let w = arena();
    let s = w.sweep_box(Aabb::new(5, 5, 0, 6), 10, 10, KindMask::BLOCKING, 4);
    assert_eq!((s.x, s.y, s.blocked_x, s.blocked_y), (5, 5, None, None));
    assert!(!w.box_blocked(Aabb::new(0, 30, 0, 5), KindMask::BLOCKING));
    assert_eq!(w.overlap(Aabb::new(0, 30, 5, -1)).inside, 0);
}

#[test]
fn sim_r65_sideways_first_then_vertical() {
    // A diagonal move is resolved on x first: the box slides along the wall while it falls.
    let mut w = arena();
    w.fill_rect(30, 0, 3, 30, "brick").unwrap();
    let s = w.sweep_box(Aabb::new(20, 0, 4, 6), 20, 50, KindMask::BLOCKING, 0);
    assert_eq!((s.x, s.y), (26, 24));
    assert!(s.blocked_x.is_some() && s.blocked_y.is_some());
}

// ----- overlap census and contact damage -------------------------------------------------------

#[test]
fn sim_r64_overlap_counts_materials_and_kinds_in_ascending_order() {
    let mut w = arena();
    w.fill_rect(10, 20, 6, 4, "water").unwrap();
    w.fill_rect(10, 24, 6, 2, "sand").unwrap();
    let o = w.overlap(Aabb::new(8, 18, 10, 10)); // 100 cells: rows 18..28, cols 8..18
    let (water, sand, air) = (idx(&w, "water"), idx(&w, "sand"), 0u8);
    assert_eq!(o.inside, 100);
    assert_eq!(o.outside, 0);
    assert_eq!(o.count(water), 24);
    assert_eq!(o.count(sand), 12);
    assert_eq!(o.count(air), 64);
    assert_eq!(o.count(idx(&w, "lava")), 0);
    assert_eq!(o.kind_count(Kind::Liquid), 24);
    assert_eq!(o.kind_count(Kind::Powder), 12);
    assert_eq!(o.kind_count(Kind::Air), 64);
    assert_eq!(o.materials(), &[(air, 64), (water, 24), (sand, 12)]);
    assert_eq!(o.burning(), 0);
}

#[test]
fn sim_r64_overlap_counts_the_part_outside_the_world() {
    let w = arena();
    let o = w.overlap(Aabb::new(-2, -3, 6, 8)); // 48 cells, 4 columns x 5 rows inside
    assert_eq!((o.inside, o.outside), (4 * 5, 48 - 20));
    let huge = w.overlap(Aabb::new(i32::MIN, i32::MIN, i32::MAX, i32::MAX));
    assert_eq!(
        u64::from(huge.inside) + huge.outside,
        (i32::MAX as u64).pow(2)
    );
}

#[test]
fn sim_r64_overlap_counts_burning_cells() {
    let mut w = arena();
    w.fill_rect(10, 26, 4, 4, "wood").unwrap();
    for x in 10..13 {
        assert!(w.ignite(x, 26));
    }
    let o = w.overlap(Aabb::new(8, 24, 8, 6));
    assert_eq!(o.burning(), 3);
    assert_eq!(o.count(idx(&w, "wood")), 16);
}

#[test]
fn mv_18_contact_damage_follows_the_formula_with_four_cell_floor_and_85_cell_cap() {
    let mut w = arena();
    let rules = ContactRules::default();
    // Fully submerged player area of 85 cells in acid: 85 x 0.005 = 0.425 raw (10.625 shown).
    w.fill_rect(10, 10, 5, 17, "acid").unwrap();
    let d = w.contact_damage(Aabb::new(10, 10, 5, 17), rules);
    assert!((d.raw - 0.425).abs() < 1e-12, "{}", d.raw);
    assert_eq!(d.parts.len(), 1);
    assert_eq!(
        (d.parts[0].material, d.parts[0].cells, d.parts[0].counted),
        (idx(&w, "acid"), 85, 85)
    );
    // 20 cells of lava: 20 x 0.003 = 0.06 raw (1.5 shown).
    w.fill_rect(30, 10, 4, 5, "lava").unwrap();
    let d = w.contact_damage(Aabb::new(30, 10, 4, 5), rules);
    assert!((d.raw - 0.06).abs() < 1e-12, "{}", d.raw);
    // 3 cells of acid are below the floor of 4: no damage.
    w.fill_rect(45, 10, 3, 1, "acid").unwrap();
    let d = w.contact_damage(Aabb::new(44, 9, 6, 3), rules);
    assert_eq!((d.raw, d.parts.len()), (0.0, 0));
    // 4 cells hurt.
    w.fill_rect(45, 11, 1, 1, "acid").unwrap();
    let d = w.contact_damage(Aabb::new(44, 9, 6, 3), rules);
    assert!((d.raw - 0.02).abs() < 1e-12, "{}", d.raw);
}

#[test]
fn haz_r01_the_cap_counts_at_most_85_cells_and_harmless_materials_do_nothing() {
    let mut w = arena();
    w.fill_rect(10, 5, 20, 20, "acid").unwrap(); // 400 cells
    w.fill_rect(30, 5, 10, 10, "water").unwrap();
    let d = w.contact_damage(Aabb::new(10, 5, 30, 20), ContactRules::default());
    assert!(
        (d.raw - 0.425).abs() < 1e-12,
        "capped at 85 cells: {}",
        d.raw
    );
    assert_eq!((d.parts[0].cells, d.parts[0].counted), (400, 85));
}

#[test]
fn haz_r01_materials_add_up_in_a_fixed_order() {
    let mut w = arena();
    w.fill_rect(10, 10, 5, 5, "lava").unwrap(); // 25 x 0.003
    w.fill_rect(15, 10, 5, 5, "acid").unwrap(); // 25 x 0.005
    let d = w.contact_damage(Aabb::new(10, 10, 10, 5), ContactRules::default());
    assert!((d.raw - (25.0 * 0.003 + 25.0 * 0.005)).abs() < 1e-12);
    let order: Vec<u8> = d.parts.iter().map(|p| p.material).collect();
    assert_eq!(
        order,
        vec![idx(&w, "acid"), idx(&w, "lava")],
        "ascending material index"
    );
}

#[test]
fn haz_r03_an_entity_may_bring_its_own_damage_table_and_rules() {
    let mut w = arena();
    w.fill_rect(10, 10, 3, 3, "water").unwrap();
    let water = idx(&w, "water");
    let o = w.overlap(Aabb::new(10, 10, 3, 3));
    // Water hurts this made-up creature, 0.01 per cell, from 2 cells, at most 5 counted.
    let rules = ContactRules {
        min_cells: 2,
        max_cells: 5,
    };
    let d = o.contact_damage(|m| if m == water { 0.01 } else { 0.0 }, rules);
    assert!((d.raw - 0.05).abs() < 1e-12);
    // The default table says water is harmless.
    assert_eq!(w.contact_damage(Aabb::new(10, 10, 3, 3), rules).raw, 0.0);
}
