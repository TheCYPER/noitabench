//! Spells in the world: casting, flight, hits, blasts, bounces, triggers, material sprays and
//! trails (SPELL-R23..R35, WAND-R40, TV-S6, TV-S7).

mod scene;

use scene::*;

use cogbench_game::{Controls, EntityDefs, Game, SpellBook};
use cogbench_sim::Content;

const W: i32 = 500;
const H: i32 = 200;
const FLOOR: i32 = 30;

fn arena() -> Game {
    with_player(W, H, FLOOR, 100)
}

#[test]
fn a_spark_bolt_flies_to_the_wall_and_bursts_there() {
    let mut g = arena();
    g.world_mut().fill_rect(250, 0, 20, H, "sand").unwrap();
    let w = give(&mut g, &["LIGHT_BULLET"]);
    run(&mut g, 1, &fire(w, 0.0));
    run(&mut g, 40, &Controls::default());
    let ev = events(&mut g);
    assert_eq!(count(&ev, "cast"), 1);
    let boom = explosions(&ev);
    assert_eq!(boom.len(), 1, "{ev:?}");
    let (x, _, r) = boom[0];
    assert_eq!(r, 2);
    assert!((245..=250).contains(&x), "burst at x = {x}");
    // sand (durability 4) is no match for the blast; rock (10) would be, see MV-13
    assert!(count_cells(&g, 244, 0, 10, H - FLOOR, "sand") < 10 * (H - FLOOR) as usize);
}

#[test]
fn mv_13_a_spark_bolt_does_not_dig_rock() {
    let mut g = arena();
    g.world_mut().fill_rect(250, 0, 20, H, "rock").unwrap();
    let w = give(&mut g, &["LIGHT_BULLET"]);
    run(&mut g, 1, &fire(w, 0.0));
    run(&mut g, 40, &Controls::default());
    assert_eq!(
        count_cells(&g, 250, 0, 20, H - FLOOR, "rock"),
        20 * (H - FLOOR) as usize,
        "durability 10 is above the bolt's 8"
    );
}

#[test]
fn the_starter_digger_digs_ground_below_the_feet() {
    let mut g = world(W, H, FLOOR, 1);
    g.world_mut()
        .fill_rect(0, H - FLOOR, W, FLOOR, "ground")
        .unwrap();
    g.spawn_player(100, ground_y(H, FLOOR)).unwrap();
    run(&mut g, 61, &Controls::default());
    let before = count_cells(&g, 90, H - FLOOR, 20, 20, "ground");
    // digging down: aim -90, wand 1 is the digger
    run(&mut g, 60, &fire(1, -90.0));
    let after = count_cells(&g, 90, H - FLOOR, 20, 20, "ground");
    assert!(after + 100 < before, "dug {} cells", before - after);
    // and the player falls into the hole it dug
    run(&mut g, 30, &Controls::default());
    assert!(
        py(&g) > ground_y(H, FLOOR) - 6,
        "the player sank into the hole"
    );
}

#[test]
fn tv_s6_explosive_projectile_on_a_bomb_has_the_375_floor() {
    let book = SpellBook::embedded().unwrap();
    let defs = EntityDefs::embedded().unwrap();
    let content = Content::embedded().unwrap();
    let mut wand = cogbench_game::wand::Wand::new(
        &book,
        stats(),
        &[book.id("EXPLOSIVE_PROJECTILE"), book.id("BOMB")],
        &[],
    )
    .unwrap();
    let mut rng = cogbench_game::SpellRng::new(1);
    let cast = wand.cast(&book, &mut rng).unwrap();
    let shot = cogbench_game::projectile::shot_from_spawn(
        &book,
        &content.mats,
        &defs,
        &cast.projectiles[0],
    )
    .unwrap();
    let e = shot.def.explosion.unwrap();
    assert_eq!(e.radius, 75, "60 + 15");
    assert_eq!(
        e.damage * 25.0,
        375.0,
        "DUR-R08: radius 64-127 floors at 375"
    );
}

#[test]
fn tv_s7_explosive_projectile_on_a_spark_bolt_has_no_floor() {
    let book = SpellBook::embedded().unwrap();
    let defs = EntityDefs::embedded().unwrap();
    let content = Content::embedded().unwrap();
    let mut wand = cogbench_game::wand::Wand::new(
        &book,
        stats(),
        &[book.id("EXPLOSIVE_PROJECTILE"), book.id("LIGHT_BULLET")],
        &[],
    )
    .unwrap();
    let mut rng = cogbench_game::SpellRng::new(1);
    let cast = wand.cast(&book, &mut rng).unwrap();
    let shot = cogbench_game::projectile::shot_from_spawn(
        &book,
        &content.mats,
        &defs,
        &cast.projectiles[0],
    )
    .unwrap();
    let e = shot.def.explosion.unwrap();
    assert_eq!(e.radius, 17);
    assert!((e.damage * 25.0 - 5.0).abs() < 1e-3);
    assert!(e.on_death);
}

#[test]
fn a_rubber_ball_bounces_off_the_floor() {
    let mut g = arena();
    let w = give(&mut g, &["RUBBER_BALL"]);
    run(&mut g, 1, &fire(w, -60.0));
    let mut rose_again = false;
    let mut hit_floor = false;
    for _ in 0..60 {
        run(&mut g, 1, &Controls::default());
        let ball = g.entities().into_iter().find(|e| e.kind == "projectile");
        if let Some(b) = ball {
            if b.vy > 0.0 {
                hit_floor = true;
            } else if hit_floor && b.vy < 0.0 {
                rose_again = true;
            }
        }
    }
    assert!(
        rose_again,
        "the ball goes down, then up again after the floor"
    );
}

#[test]
fn a_collision_trigger_releases_its_payload_where_it_hits() {
    // WAND-R40: the payload (a fireball) was drawn at cast time and flies on from the impact.
    let mut g = arena();
    g.world_mut().fill_rect(250, 0, 20, H, "rock").unwrap();
    let w = give(&mut g, &["LIGHT_BULLET_TRIGGER", "FIREBALL"]);
    run(&mut g, 1, &fire(w, 0.0));
    run(&mut g, 80, &Controls::default());
    let ev = events(&mut g);
    let radii: Vec<i64> = explosions(&ev).iter().map(|e| e.2).collect();
    assert!(radii.contains(&2), "trigger bolt bursts: {radii:?}");
    assert!(radii.contains(&15), "fireball bursts: {radii:?}");
}

#[test]
fn a_timer_trigger_fires_after_10_frames_in_the_air() {
    let mut g = arena();
    let w = give(&mut g, &["LIGHT_BULLET_TIMER", "BOMB"]);
    run(&mut g, 1, &fire(w, 20.0));
    for _ in 0..8 {
        run(&mut g, 1, &Controls::default());
    }
    assert!(g.entities().iter().all(|e| e.kind != "bomb"));
    for _ in 0..6 {
        run(&mut g, 1, &Controls::default());
    }
    assert!(
        g.entities().iter().any(|e| e.kind == "bomb"),
        "bomb released"
    );
}

#[test]
fn a_bomb_goes_off_after_its_three_second_fuse() {
    let mut g = arena();
    let w = give(&mut g, &["BOMB"]);
    run(&mut g, 1, &fire(w, 30.0));
    run(&mut g, 170, &Controls::default());
    assert!(explosions(&events(&mut g)).is_empty(), "not yet");
    run(&mut g, 20, &Controls::default());
    let boom = explosions(&events(&mut g));
    assert_eq!(boom.len(), 1);
    assert_eq!(boom[0].2, 60);
}

#[test]
fn water_spray_wets_the_ground() {
    let mut g = arena();
    let w = give(&mut g, &["MATERIAL_WATER"]);
    run(&mut g, 20, &fire(w, -80.0));
    run(&mut g, 60, &Controls::default());
    let water = count_cells(&g, 0, 0, W, H, "water");
    assert!(water >= 15, "{water} water cells");
}

#[test]
fn fire_trail_leaves_fire_behind() {
    let mut g = arena();
    let w = give(&mut g, &["FIRE_TRAIL", "FIREBALL"]);
    run(&mut g, 1, &fire(w, 10.0));
    let mut seen = 0;
    for _ in 0..30 {
        run(&mut g, 1, &Controls::default());
        seen = seen.max(count_cells(&g, 0, 0, W, H, "fire"));
    }
    assert!(seen >= 10, "{seen} fire cells at most");
}

#[test]
fn a_cast_costs_mana_and_respects_the_cast_delay() {
    let mut g = arena();
    let before = g.player().unwrap().wands[0].mana;
    run(&mut g, 1, &fire(0, 0.0)); // the starter spark wand
    let after = g.player().unwrap().wands[0].mana;
    assert!(
        before - after > 4.0,
        "Spark Bolt costs 5 mana: {before} -> {after}"
    );
    let cd = g.player().unwrap().wands[0].cooldown;
    assert!(cd >= 20, "cast delay 10+3 and recharge 22 overlap: {cd}");
    run(&mut g, 2, &fire(0, 0.0));
    let ev = events(&mut g);
    assert_eq!(
        count(&ev, "cast"),
        1,
        "no second cast while the wand cools down"
    );
}

#[test]
fn projectiles_do_not_slip_through_diagonal_corners() {
    // v1-scope 5a: a staircase wall whose cells only touch at corners still stops a bolt (the
    // 8-connected line of the simulation could pass between two such cells).
    for aim in [30.0, 40.0, 45.0, 50.0, 60.0] {
        let mut g = arena();
        for i in 0..120 {
            g.world_mut()
                .fill_rect(150 + i, 20 + i, 1, 1, "rock")
                .unwrap();
        }
        g.world_mut().fill_rect(400, 0, 10, H, "rock").unwrap();
        let w = give(&mut g, &["LIGHT_BULLET"]);
        run(&mut g, 1, &fire(w, aim));
        run(&mut g, 60, &Controls::default());
        let boom = explosions(&events(&mut g));
        assert_eq!(boom.len(), 1, "aim {aim}");
        assert!(
            boom[0].0 < 280,
            "aim {aim}: burst at {:?}, past the wall",
            boom[0]
        );
    }
}

#[test]
fn the_starter_digger_digs_rock_but_never_brick() {
    // the world generator's connectivity check assumes the starter wand can dig durability <= 10
    for (floor, digs) in [("rock", true), ("brick", false)] {
        let mut g = world(W, H, FLOOR + 40, 1);
        g.world_mut()
            .fill_rect(0, H - FLOOR - 40, W, 40, floor)
            .unwrap();
        g.spawn_player(100, ground_y(H, FLOOR + 40)).unwrap();
        run(&mut g, 61, &Controls::default());
        let y0 = py(&g);
        run(&mut g, 240, &fire(1, -90.0));
        let sank = py(&g) - y0;
        assert_eq!(sank >= 20, digs, "{floor}: sank {sank} cells in 4 seconds");
    }
}
