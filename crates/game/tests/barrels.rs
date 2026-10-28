//! Barrels (cp1-feedback section 1): gunpowder, acid and oil; chain reactions; kicks.

mod scene;

use scene::*;

use cogbench_game::entity::Owner;
use cogbench_game::{BlastSpec, Controls, Game, ItemSpec};

const W: i32 = 500;
const H: i32 = 200;
const FLOOR: i32 = 30;

fn arena() -> Game {
    with_player(W, H, FLOOR, 60)
}

fn barrel(g: &mut Game, kind: &str, x: i32) -> u32 {
    g.spawn_item(
        &ItemSpec::Barrel { kind: kind.into() },
        x,
        ground_y(H, FLOOR),
    )
    .unwrap()
}

fn shoot_until_broken(g: &mut Game, spell: &str, aim: f32, frames: u32) {
    let w = give(g, &[spell]);
    run(g, frames, &fire(w, aim));
}

fn kinds(g: &Game) -> Vec<String> {
    g.entities().into_iter().map(|e| e.kind).collect()
}

#[test]
fn an_acid_barrel_bursts_into_200_acid_cells() {
    let mut g = arena();
    barrel(&mut g, "barrel_acid", 140);
    shoot_until_broken(&mut g, "LIGHT_BULLET", 0.0, 12);
    let ev = events(&mut g);
    assert_eq!(count(&ev, "barrel_break"), 1, "{ev:?}");
    assert!(!kinds(&g).contains(&"barrel_acid".to_string()));
    // 200 cells placed; a few already corroded rock or fell through reactions in the frames since
    let acid = count_cells(&g, 0, 0, W, H, "acid");
    let gone = count_cells(&g, 0, 0, W, H, "flammable_gas");
    assert!(acid + gone >= 150, "acid {acid}, gas {gone}");
}

#[test]
fn acid_from_a_barrel_eats_the_rock_but_only_so_much() {
    let mut g = arena();
    barrel(&mut g, "barrel_acid", 140);
    let rock0 = count_cells(&g, 0, 0, W, H, "rock");
    shoot_until_broken(&mut g, "LIGHT_BULLET", 0.0, 12);
    run(&mut g, 600, &Controls::default());
    let eaten = rock0 - count_cells(&g, 0, 0, W, H, "rock");
    // r04: every cell of acid dissolves at most one cell, so 200 acid eat at most 200 rock
    assert!((20..=200).contains(&eaten), "ate {eaten} rock cells");
    assert_eq!(count_cells(&g, 0, 0, W, H, "acid"), 0, "all of it used up");
}

#[test]
fn a_gunpowder_barrel_explodes_when_fire_touches_it() {
    let mut g = arena();
    barrel(&mut g, "barrel_gunpowder", 200);
    let y = ground_y(H, FLOOR);
    g.world_mut().fill_rect(194, y - 6, 3, 6, "fire").unwrap();
    run(&mut g, 40, &Controls::default());
    let ev = events(&mut g);
    assert_eq!(count(&ev, "barrel_break"), 1);
    let boom = explosions(&ev);
    assert!(boom.iter().any(|b| b.2 == 30), "{boom:?}");
    // the blast digs a crater into the floor
    assert!(count_cells(&g, 170, y, 60, 30, "rock") < 60 * 30);
}

#[test]
fn a_gunpowder_barrel_explodes_when_a_blast_reaches_it() {
    let mut g = arena();
    barrel(&mut g, "barrel_gunpowder", 200);
    g.blast(cogbench_game::BlastSpec {
        x: 190,
        y: ground_y(H, FLOOR) - 3,
        radius: 15,
        damage: 2.0,
        ray_energy: 50_000,
        max_durability: 10,
        fire_percent: 0,
        owner: cogbench_game::entity::Owner::World,
        spare_owner: false,
    });
    run(&mut g, 2, &Controls::default());
    let ev = events(&mut g);
    assert_eq!(count(&ev, "barrel_break"), 1, "{ev:?}");
    assert!(explosions(&ev).iter().any(|b| b.2 == 30));
}

#[test]
fn a_chain_of_gunpowder_barrels_goes_off_one_after_the_other() {
    let mut g = arena();
    for x in [200, 214, 228, 242] {
        barrel(&mut g, "barrel_gunpowder", x);
    }
    let y = ground_y(H, FLOOR);
    g.world_mut().fill_rect(194, y - 6, 3, 6, "fire").unwrap();
    run(&mut g, 60, &Controls::default());
    let ev = events(&mut g);
    assert_eq!(count(&ev, "barrel_break"), 4, "all four barrels");
    assert_eq!(explosions(&ev).iter().filter(|b| b.2 == 30).count(), 4);
}

#[test]
fn a_blast_does_not_pass_through_brick() {
    // line of sight is checked after the carve; brick (durability 14) survives a barrel blast
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    barrel(&mut g, "barrel_gunpowder", 200);
    g.world_mut()
        .fill_rect(215, y - 40, 12, 41, "brick")
        .unwrap();
    barrel(&mut g, "barrel_gunpowder", 240);
    g.world_mut().fill_rect(194, y - 6, 3, 6, "fire").unwrap();
    run(&mut g, 60, &Controls::default());
    let ev = events(&mut g);
    assert_eq!(
        count(&ev, "barrel_break"),
        1,
        "the barrel behind the brick survives"
    );
    assert!(kinds(&g).contains(&"barrel_gunpowder".to_string()));
}

/// Blast the player from 8 cells away along the diagonal; `wall` puts two brick cells that touch
/// the diagonal path only at a corner in the way. Returns the player's hit points afterwards.
fn diagonal_blast(wall: bool) -> f64 {
    let mut g = arena();
    let (px, gy) = (60, ground_y(H, FLOOR));
    if wall {
        let w = g.world_mut();
        w.fill_rect(px - 3, gy - 9, 1, 1, "brick").unwrap();
        w.fill_rect(px - 4, gy - 8, 1, 1, "brick").unwrap();
    }
    g.blast(BlastSpec {
        x: px - 8,
        y: gy - 13,
        radius: 20,
        damage: 3.0,
        ray_energy: 1000,
        max_durability: 10,
        fire_percent: 0,
        owner: Owner::World,
        spare_owner: false,
    });
    g.player().unwrap().hp
}

#[test]
fn a_wall_of_diagonally_touching_cells_shields_from_a_blast() {
    assert!(diagonal_blast(false) < 90.0, "in the open the blast hurts");
    assert_eq!(diagonal_blast(true), 100.0, "the corner is no way through");
}

#[test]
fn an_oil_barrel_spills_oil_and_burns_when_lit() {
    let mut g = arena();
    barrel(&mut g, "barrel_oil", 200);
    let y = ground_y(H, FLOOR);
    g.world_mut().fill_rect(194, y - 6, 3, 6, "fire").unwrap();
    run(&mut g, 200, &Controls::default());
    let ev = events(&mut g);
    assert_eq!(count(&ev, "barrel_break"), 1);
    let brk = ev.iter().find(|(k, _)| k == "barrel_break").unwrap();
    assert_eq!(int(&brk.1, "burning"), 1);
    assert!(
        count_cells(&g, 0, 0, W, H, "oil") + count_cells(&g, 0, 0, W, H, "fire") > 30,
        "burning oil all over"
    );
}

#[test]
fn an_unlit_oil_barrel_just_leaks_oil_when_shot() {
    let mut g = arena();
    barrel(&mut g, "barrel_oil", 140);
    shoot_until_broken(&mut g, "LIGHT_BULLET", 0.0, 12);
    let ev = events(&mut g);
    let brk = ev
        .iter()
        .find(|(k, _)| k == "barrel_break")
        .expect("broken");
    assert_eq!(int(&brk.1, "burning"), 0);
    assert!(count_cells(&g, 0, 0, W, H, "oil") >= 250);
    assert_eq!(count_cells(&g, 0, 0, W, H, "fire"), 0);
}

#[test]
fn kicking_pushes_a_barrel_and_hurts_it_a_little() {
    let mut g = arena();
    let id = barrel(&mut g, "barrel_acid", 70);
    run(&mut g, 5, &Controls::default());
    let before = g.entities().into_iter().find(|e| e.id == id).unwrap();
    run(&mut g, 1, &hold(|c| c.kick = true));
    run(&mut g, 30, &Controls::default());
    let after = g.entities().into_iter().find(|e| e.id == id).unwrap();
    assert!(
        after.x > before.x + 3,
        "pushed from {} to {}",
        before.x,
        after.x
    );
    assert!(after.hp < before.hp, "kicks damage barrels");
}

#[test]
fn a_barrel_dropped_from_height_lands_and_sleeps() {
    let mut g = arena();
    let id = g
        .spawn_item(
            &ItemSpec::Barrel {
                kind: "barrel_oil".into(),
            },
            300,
            20,
        )
        .unwrap();
    run(&mut g, 120, &Controls::default());
    let b = g.entities().into_iter().find(|e| e.id == id).unwrap();
    assert_eq!(b.y + b.h, ground_y(H, FLOOR) + 1);
    assert_eq!((b.vx, b.vy), (0.0, 0.0));
}
