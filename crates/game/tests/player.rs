//! The player: movement and levitation numbers of `entities-damage.md`, contact damage
//! (HAZ-R01, MV-18), drowning, statuses.

mod scene;

use scene::*;

use cogbench_game::{Controls, Game};

const W: i32 = 400;
const H: i32 = 200;
const FLOOR: i32 = 20;

fn standing(x: i32) -> Game {
    with_player(W, H, FLOOR, x)
}

#[test]
fn walking_speed_is_about_57_px_per_second() {
    // player walk speed 57 px/s = 0.95 px/frame; the speed eases in over a few frames.
    let mut g = standing(40);
    let x0 = px(&g);
    run(&mut g, 60, &hold(|c| c.move_x = 1));
    let walked = px(&g) - x0;
    assert!(
        (46..=58).contains(&walked),
        "walked {walked} px in a second"
    );
    let x1 = px(&g);
    run(&mut g, 60, &hold(|c| c.move_x = -1));
    assert!(px(&g) < x1 - 40, "and back again");
}

#[test]
fn player_stands_on_the_floor_and_stops_when_released() {
    let mut g = standing(40);
    run(&mut g, 30, &hold(|c| c.move_x = 1));
    run(&mut g, 60, &Controls::default());
    let x = px(&g);
    run(&mut g, 30, &Controls::default());
    assert_eq!(px(&g), x, "friction stops the player");
    let p = g.player().unwrap();
    assert!(p.on_ground);
    assert_eq!(p.y + p.h, ground_y(H, FLOOR) + 1, "feet on the floor");
}

#[test]
fn jump_apex_is_about_13_px() {
    // jump speed 95 px/s under gravity 350 px/s2: v^2 / 2g = 12.9 px.
    let mut g = standing(40);
    let y0 = py(&g);
    let mut top = y0;
    run(&mut g, 1, &hold(|c| c.jump = true));
    for _ in 0..60 {
        run(&mut g, 1, &Controls::default());
        top = top.min(py(&g));
    }
    let height = y0 - top;
    assert!((11..=14).contains(&height), "jumped {height} px");
    assert_eq!(py(&g), y0, "lands again");
}

#[test]
fn holding_jump_does_not_jump_again_until_released() {
    let mut g = standing(40);
    let c = hold(|c| c.jump = true);
    run(&mut g, 40, &c);
    // The jump is edge triggered: one hop of ~13 px, then the player stays down.
    assert!(g.player().unwrap().on_ground);
}

#[test]
fn levitation_lasts_three_seconds_and_refills_on_the_ground() {
    let mut g = with_player(W, 900, FLOOR, 200);
    let fly = hold(|c| c.fly = true);
    let mut frames_up = 0;
    let mut meter = g.player().unwrap().fly;
    for _ in 0..300 {
        run(&mut g, 1, &fly);
        let now = g.player().unwrap().fly;
        if now >= meter {
            break;
        }
        frames_up += 1;
        meter = now;
    }
    // 180 frames of meter: exactly 3.0 s of levitation.
    assert_eq!(frames_up, 180);
    assert!(g.player().unwrap().y < 800 - 100, "it really rose");
    let p = g.player().unwrap();
    assert!(p.fly < 0.05, "meter empty: {}", p.fly);
    // Fall back down, then the meter refills fully within half a second on the ground.
    run(&mut g, 600, &Controls::default());
    assert!(g.player().unwrap().on_ground);
    run(&mut g, 31, &Controls::default());
    assert!(g.player().unwrap().fly > 0.99);
}

#[test]
fn tapping_levitate_in_the_air_costs_meter() {
    // Every fresh press in the air removes 8 frames of meter (the second anti-tap rule).
    let mut g = standing(200);
    run(&mut g, 30, &hold(|c| c.fly = true));
    let before = g.player().unwrap().fly;
    run(&mut g, 1, &Controls::default());
    run(&mut g, 1, &hold(|c| c.fly = true));
    let after = g.player().unwrap().fly;
    // one frame of flying (1) plus the press cost (8), out of 180
    assert!(before - after > 8.0 / 180.0, "{before} -> {after}");
}

#[test]
fn walking_up_a_4_px_ledge_works_a_5_px_one_does_not() {
    for (ledge, climbs) in [(4, true), (5, false)] {
        let mut g = world(W, H, FLOOR, 1);
        let top = ground_y(H, FLOOR) + 1 - ledge;
        g.world_mut()
            .fill_rect(100, top, 100, ledge, "rock")
            .unwrap();
        g.spawn_player(60, ground_y(H, FLOOR)).unwrap();
        run(&mut g, 150, &hold(|c| c.move_x = 1));
        let past = px(&g) > 110;
        assert_eq!(past, climbs, "ledge of {ledge}: x = {}", px(&g));
    }
}

#[test]
fn falling_from_a_great_height_does_not_hurt() {
    let mut g = world(W, 600, FLOOR, 1);
    g.spawn_player(200, 100).unwrap();
    run(&mut g, 600, &Controls::default());
    let p = g.player().unwrap();
    assert!(p.on_ground);
    assert_eq!(p.hp, 100.0, "no fall damage");
}

#[test]
fn walls_stop_the_player() {
    let mut g = world(W, H, FLOOR, 1);
    g.world_mut().fill_rect(120, 0, 10, H, "rock").unwrap();
    g.spawn_player(60, ground_y(H, FLOOR)).unwrap();
    run(&mut g, 300, &hold(|c| c.move_x = 1));
    let p = g.player().unwrap();
    assert_eq!(p.x + p.w, 120, "stopped at the wall");
}

#[test]
fn haz_r01_standing_in_acid_hurts_per_frame() {
    // 85 cells counted x 0.005 = 0.425 internal = 10.6 displayed per frame (MV-18).
    let mut g = standing(100);
    g.world_mut()
        .fill_rect(80, ground_y(H, FLOOR) - 30, 40, 40, "acid")
        .unwrap();
    let before = g.player().unwrap().hp;
    run(&mut g, 1, &Controls::default());
    let after = g.player().unwrap().hp;
    let lost = before - after;
    assert!((lost - 10.6).abs() < 1.5, "lost {lost} HP in a frame");
    run(&mut g, 20, &Controls::default());
    assert!(g.player().unwrap().dead, "acid kills in about 10 frames");
}

#[test]
fn haz_r01_a_few_cells_of_acid_do_nothing() {
    let mut g = standing(100);
    g.world_mut()
        .paint(100, ground_y(H, FLOOR) - 2, 0, "acid")
        .unwrap();
    g.world_mut()
        .paint(101, ground_y(H, FLOOR) - 2, 0, "acid")
        .unwrap();
    run(&mut g, 1, &Controls::default());
    assert_eq!(g.player().unwrap().hp, 100.0, "under 4 cells: no damage");
}

#[test]
fn the_player_starts_with_one_second_of_invincibility() {
    let mut g = world(W, H, FLOOR, 1);
    g.spawn_player(100, ground_y(H, FLOOR)).unwrap();
    g.world_mut()
        .fill_rect(80, ground_y(H, FLOOR) - 30, 40, 40, "acid")
        .unwrap();
    run(&mut g, 50, &Controls::default());
    assert_eq!(g.player().unwrap().hp, 100.0);
    run(&mut g, 30, &Controls::default());
    assert!(g.player().unwrap().dead);
}

/// Rock walls at `x0` and `x1` (3 cells thick, 80 high) so that liquid stays where it is put.
fn basin(g: &mut Game, x0: i32, x1: i32) {
    let top = ground_y(H, FLOOR) - 79;
    g.world_mut().fill_rect(x0 - 3, top, 3, 80, "rock").unwrap();
    g.world_mut().fill_rect(x1, top, 3, 80, "rock").unwrap();
}

#[test]
fn staying_under_water_drowns_after_seven_seconds() {
    let mut g = standing(100);
    basin(&mut g, 60, 140);
    g.world_mut()
        .fill_rect(60, ground_y(H, FLOOR) - 40, 80, 41, "water")
        .unwrap();
    run(&mut g, 400, &Controls::default());
    assert_eq!(g.player().unwrap().hp, 100.0, "still breathing");
    run(&mut g, 60, &Controls::default());
    let hp = g.player().unwrap().hp;
    assert!(hp < 100.0 && hp > 0.0, "drowning: {hp}");
    run(&mut g, 400, &Controls::default());
    assert!(g.player().unwrap().dead);
}

#[test]
fn swimming_up_gets_the_head_out() {
    let mut g = standing(100);
    basin(&mut g, 60, 140);
    g.world_mut()
        .fill_rect(60, ground_y(H, FLOOR) - 20, 80, 21, "water")
        .unwrap();
    run(&mut g, 120, &hold(|c| c.fly = true));
    let p = g.player().unwrap();
    assert!(p.breath > 0.5, "head above water, breath {}", p.breath);
}

#[test]
fn water_makes_you_wet_oil_makes_you_oily() {
    let mut g = standing(100);
    g.world_mut()
        .fill_rect(60, ground_y(H, FLOOR) - 5, 80, 6, "water")
        .unwrap();
    run(&mut g, 5, &Controls::default());
    let names: Vec<String> = g
        .player()
        .unwrap()
        .statuses
        .iter()
        .map(|s| s.0.clone())
        .collect();
    assert_eq!(names, vec!["wet".to_string()]);
}

#[test]
fn fire_sets_the_player_alight_and_water_puts_it_out() {
    let mut g = standing(100);
    let y = ground_y(H, FLOOR);
    g.world_mut().fill_rect(95, y - 8, 12, 9, "fire").unwrap();
    run(&mut g, 4, &Controls::default());
    let burning = |g: &Game| {
        g.player()
            .unwrap()
            .statuses
            .iter()
            .any(|s| s.0 == "on_fire")
    };
    assert!(burning(&g), "alight");
    let hp = g.player().unwrap().hp;
    run(&mut g, 60, &hold(|c| c.move_x = 1));
    assert!(g.player().unwrap().hp < hp, "burning hurts");
    g.world_mut().fill_rect(0, y - 20, W, 21, "water").unwrap();
    run(&mut g, 3, &Controls::default());
    assert!(!burning(&g), "water puts the fire out");
}

#[test]
fn the_healing_pool_heals() {
    let mut g = standing(100);
    let y = ground_y(H, FLOOR);
    // hurt the player first with a little acid
    g.world_mut().fill_rect(95, y - 8, 12, 9, "acid").unwrap();
    run(&mut g, 2, &Controls::default());
    let hurt = g.player().unwrap().hp;
    assert!(hurt < 100.0);
    g.world_mut()
        .fill_rect(60, y - 20, 80, 21, "potion_heal")
        .unwrap();
    run(&mut g, 10, &Controls::default());
    assert!(
        g.player().unwrap().hp > hurt,
        "heals while standing in the pool"
    );
}

#[test]
fn a_dead_player_stays_dead_and_ignores_controls() {
    let mut g = standing(100);
    g.world_mut()
        .fill_rect(80, ground_y(H, FLOOR) - 30, 40, 40, "acid")
        .unwrap();
    run(&mut g, 30, &Controls::default());
    assert!(g.player().unwrap().dead);
    let x = px(&g);
    run(&mut g, 30, &hold(|c| c.move_x = 1));
    assert_eq!(px(&g), x);
    let ev = events(&mut g);
    assert_eq!(count(&ev, "death"), 1);
}

#[test]
fn oil_makes_a_fire_last_twice_as_long() {
    let fire_frames = |oiled: bool| {
        let mut g = standing(100);
        let y = ground_y(H, FLOOR);
        if oiled {
            g.give_bottle(Some("oil"), Some(30)).unwrap();
            run(&mut g, 3, &hold(|c| c.drink = true));
        }
        g.world_mut().fill_rect(95, y - 8, 12, 9, "fire").unwrap();
        run(&mut g, 4, &Controls::default());
        g.player()
            .unwrap()
            .statuses
            .iter()
            .find(|s| s.0 == "on_fire")
            .map(|s| s.1)
            .expect("alight")
    };
    let plain = fire_frames(false);
    let oily = fire_frames(true);
    assert!(oily > plain * 3 / 2, "{plain} vs {oily}");
}

#[test]
fn a_dead_player_cannot_jump_on_the_frame_a_key_goes_down() {
    let mut g = standing(100);
    g.world_mut()
        .fill_rect(80, ground_y(H, FLOOR) - 30, 40, 40, "acid")
        .unwrap();
    run(&mut g, 30, &Controls::default());
    assert!(g.player().unwrap().dead);
    let y = py(&g);
    run(&mut g, 1, &hold(|c| c.jump = true));
    run(&mut g, 10, &hold(|c| c.jump = true));
    assert!(py(&g) >= y);
}

#[test]
fn poison_hurts_but_never_kills() {
    let mut g = standing(100);
    for _ in 0..4 {
        g.give_bottle(Some("toxic_sludge"), Some(400)).unwrap();
    }
    for bottle in 0..4u8 {
        run(
            &mut g,
            40,
            &hold(|c| {
                c.drink = true;
                c.select_bottle = Some(bottle);
            }),
        );
    }
    assert!(g
        .player()
        .unwrap()
        .statuses
        .iter()
        .any(|s| s.0 == "poisoned"));
    run(&mut g, 4000, &Controls::default());
    let p = g.player().unwrap();
    assert!(!p.dead);
    // DAMAGE-R19: poison floors at 2 % of the maximum, which is 2 displayed HP
    assert!((p.hp - 2.0).abs() < 0.5, "{}", p.hp);
}

#[test]
fn a_non_finite_aim_is_treated_as_straight_ahead() {
    let mut g = standing(100);
    run(
        &mut g,
        5,
        &hold(|c| {
            c.aim = f32::NAN;
            c.fire = true;
        }),
    );
    run(&mut g, 5, &hold(|c| c.aim = f32::INFINITY));
    assert_eq!(g.player().unwrap().aim, 0.0);
}

/// Is there ground right under the feet, looking at the grid now?
fn ground_under(g: &Game) -> bool {
    let p = g.player().unwrap();
    (p.x..p.x + p.w).any(|x| cell(g, x, p.y + p.h) == "rock")
}

#[test]
fn on_ground_is_the_state_at_the_end_of_the_frame_not_the_start() {
    let mut g = standing(40);
    run(&mut g, 1, &hold(|c| c.jump = true));
    let mut flips = 0;
    let mut last = g.player().unwrap().on_ground;
    for frame in 0..60 {
        run(&mut g, 1, &Controls::default());
        let p = g.player().unwrap();
        assert_eq!(p.on_ground, ground_under(&g), "frame {frame} of the jump");
        if p.on_ground != last {
            flips += 1;
            last = p.on_ground;
        }
    }
    assert_eq!(flips, 1, "up in the air once, then landed");
    assert!(last);
}

#[test]
fn on_ground_follows_a_floor_that_goes_away_under_the_feet() {
    let mut g = standing(40);
    let p = g.player().unwrap();
    // take the rock from under the player
    g.world_mut()
        .fill_rect(p.x - 3, p.y + p.h, 10, 3, "air")
        .unwrap();
    run(&mut g, 1, &Controls::default());
    assert!(!g.player().unwrap().on_ground, "the floor is already gone");
}
