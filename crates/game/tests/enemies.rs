//! The three enemies: Hämis (`longleg`), Haulikkohiisi (`shotgunner`) and Stendari
//! (`firemage_weak`): sight, attacks with a windup, deaths, fire and water.

mod scene;

use scene::*;

use cogbench_game::{Controls, Game};

const W: i32 = 600;
const H: i32 = 200;
const FLOOR: i32 = 30;

fn arena() -> Game {
    with_player(W, H, FLOOR, 100)
}

fn enemy(g: &Game, kind: &str) -> Option<cogbench_game::EntityView> {
    g.entities().into_iter().find(|e| e.kind == kind)
}

fn spawn(g: &mut Game, kind: &str, x: i32) -> u32 {
    g.spawn_enemy(kind, x, ground_y(H, FLOOR)).unwrap()
}

#[test]
fn a_spark_bolt_kills_hamis_in_one_hit_and_he_drops_dead() {
    let mut g = arena();
    spawn(&mut g, "longleg", 200);
    let w = give(&mut g, &["LIGHT_BULLET"]);
    run(&mut g, 1, &fire(w, 0.0));
    run(&mut g, 20, &Controls::default());
    assert!(
        enemy(&g, "longleg").is_none(),
        "Hämis has 2.75 HP, a bolt does 3"
    );
    let ev = events(&mut g);
    assert_eq!(count(&ev, "death"), 1);
    assert!(count(&ev, "hit") >= 1);
}

#[test]
fn hamis_comes_for_the_player_and_bites() {
    let mut g = arena();
    spawn(&mut g, "longleg", 170);
    run(&mut g, 400, &Controls::default());
    let p = g.player().unwrap();
    assert!(p.hp < 100.0, "bitten: {}", p.hp);
    let h = enemy(&g, "longleg").unwrap();
    assert!((h.x - p.x).abs() < 20, "he stays close");
}

#[test]
fn hamis_needs_a_free_line_of_sight_to_notice_the_player() {
    let mut g = arena();
    g.world_mut().fill_rect(140, 0, 6, H, "rock").unwrap();
    spawn(&mut g, "longleg", 170);
    run(&mut g, 300, &Controls::default());
    assert_eq!(
        g.player().unwrap().hp,
        100.0,
        "behind a wall he does not hunt"
    );
}

#[test]
fn far_away_enemies_sleep() {
    let mut g = world(2000, H, FLOOR, 1);
    g.spawn_player(100, ground_y(H, FLOOR)).unwrap();
    g.spawn_enemy("longleg", 1500, ground_y(H, FLOOR)).unwrap();
    let x0 = enemy(&g, "longleg").unwrap().x;
    run(&mut g, 300, &Controls::default());
    assert_eq!(enemy(&g, "longleg").unwrap().x, x0);
}

#[test]
fn every_enemy_attack_has_a_windup_of_at_least_ten_frames() {
    // The agent decides once per 10 frames: no hit may come out of nowhere.
    let defs = cogbench_game::EntityDefs::embedded().unwrap();
    for (key, e) in &defs.enemies {
        assert!(e.melee.windup >= 10, "{key}");
        if let Some(l) = e.lunge {
            assert!(l.windup >= 20, "{key}");
        }
        if let Some(r) = &e.ranged {
            assert!(r.windup >= 20, "{key}");
        }
    }
}

#[test]
fn the_shotgunner_fires_buckshot_from_a_distance() {
    let mut g = arena();
    spawn(&mut g, "shotgunner", 220);
    run(&mut g, 300, &Controls::default());
    let ev = events(&mut g);
    assert!(
        count(&ev, "enemy_attack") >= 2,
        "volleys: {}",
        count(&ev, "enemy_attack")
    );
    assert!(g.player().unwrap().hp < 100.0, "pellets hurt");
    let attack = ev.iter().find(|(k, _)| k == "enemy_attack").unwrap();
    let n = int(&attack.1, "projectiles");
    assert!((3..=4).contains(&n), "3 or 4 pellets, got {n}");
}

#[test]
fn the_shotgunner_does_not_fire_without_sight() {
    let mut g = arena();
    g.world_mut().fill_rect(160, 0, 6, H, "rock").unwrap();
    spawn(&mut g, "shotgunner", 220);
    run(&mut g, 300, &Controls::default());
    assert_eq!(count(&events(&mut g), "enemy_attack"), 0);
}

#[test]
fn stendari_throws_fireballs_and_burns_things() {
    let mut g = arena();
    spawn(&mut g, "firemage_weak", 240);
    run(&mut g, 300, &Controls::default());
    let ev = events(&mut g);
    assert!(count(&ev, "enemy_attack") >= 1);
    let p = g.player().unwrap();
    assert!(p.hp < 100.0, "a fireball burst: {}", p.hp);
}

#[test]
fn stendari_is_immune_to_fire() {
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    let id = spawn(&mut g, "firemage_weak", 300);
    g.world_mut()
        .fill_rect(285, y - 20, 30, 21, "fire")
        .unwrap();
    run(&mut g, 20, &Controls::default());
    let e = g.entities().into_iter().find(|e| e.id == id).unwrap();
    assert_eq!(e.hp, e.hp_max);
    assert!(e.statuses.iter().all(|s| s.0 != "on_fire"));
}

#[test]
fn fire_kills_hamis_quickly() {
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    spawn(&mut g, "longleg", 400);
    g.world_mut()
        .fill_rect(390, y - 20, 25, 21, "fire")
        .unwrap();
    run(&mut g, 120, &Controls::default());
    assert!(enemy(&g, "longleg").is_none());
}

#[test]
fn water_hurts_stendari() {
    // wet_damage_per_s 1.8 of 3.2 HP: a minute under the tap is not needed
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    let id = spawn(&mut g, "firemage_weak", 400);
    g.world_mut().fill_rect(380, y - 60, 3, 61, "rock").unwrap();
    g.world_mut().fill_rect(425, y - 60, 3, 61, "rock").unwrap();
    g.world_mut()
        .fill_rect(383, y - 30, 42, 31, "water")
        .unwrap();
    run(&mut g, 150, &Controls::default());
    let hp = g.entities().into_iter().find(|e| e.id == id).map(|e| e.hp);
    assert!(hp.is_none() || hp.unwrap() < 20.0, "{hp:?}");
}

/// Damage of the first hit of a spark bolt aimed `aim` degrees at a shotgunner 100 cells away.
fn first_hit(aim: f32) -> f64 {
    let mut g = arena();
    spawn(&mut g, "shotgunner", 200);
    let w = give(&mut g, &["LIGHT_BULLET"]);
    run(&mut g, 1, &fire(w, aim));
    run(&mut g, 20, &Controls::default());
    let ev = events(&mut g);
    let hit = ev.iter().find(|(k, _)| k == "hit").expect("a hit");
    match hit.1.iter().find(|(k, _)| k == "damage") {
        Some((_, cogbench_sim::Value::Float(d))) => *d,
        other => panic!("no damage: {other:?}"),
    }
}

#[test]
fn hits_to_the_head_count_two_and_a_half_times() {
    // the shotgunner's head box has mult 2.5; the bolt does 3 displayed damage
    let body = first_hit(0.0);
    let head = first_hit(4.0);
    assert!((body - 3.0).abs() < 1e-3, "{body}");
    assert!((head - 7.5).abs() < 1e-3, "{head}");
}

#[test]
fn a_kick_hurts_and_pushes_an_enemy() {
    let mut g = arena();
    let id = spawn(&mut g, "shotgunner", 106);
    run(&mut g, 3, &Controls::default());
    let before = g.entities().into_iter().find(|e| e.id == id).unwrap();
    run(&mut g, 1, &hold(|c| c.kick = true));
    run(&mut g, 5, &Controls::default());
    let after = g.entities().into_iter().find(|e| e.id == id).unwrap();
    assert!(after.hp < before.hp, "a kick does 1 HP");
    assert!(after.x > before.x, "and pushes");
}
