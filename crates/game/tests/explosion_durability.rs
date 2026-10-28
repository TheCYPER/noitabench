//! `EXPLOSIVE_PROJECTILE` raises the max durability of the explosion of the projectile it modifies
//! by 3 (`v1-scope.md` section 5, lead decision 2026-10-27): the bomb's 11 plus 3 reaches
//! brickwork (14), nothing else in the content does, and bonuses of several cards do not add up.

mod common;
mod scene;

use cogbench_game::projectile::{shot_from_spawn, ExplosionDef};
use cogbench_game::wand::ProjectileSpawn;
use cogbench_game::{Controls, EntityDefs, Game, SpellBook, SpellRng};
use cogbench_sim::Content;
use scene::{count_cells, events, explosions, fire, give, ground_y, run, with_player};
use serde_json::Value;

const W: i32 = 500;
const H: i32 = 200;
const FLOOR: i32 = 30;
const BRICK: i32 = 14;

/// The shot state's bonus and the explosion of one projectile request, as the world builds it.
fn fold(book: &SpellBook, spawn: &ProjectileSpawn) -> (u32, Option<ExplosionDef>) {
    let defs = EntityDefs::embedded().unwrap();
    let content = Content::embedded().unwrap();
    let shot = shot_from_spawn(book, &content.mats, &defs, spawn).unwrap();
    (spawn.shot.explosion_durability, shot.def.explosion)
}

/// The explosion (and the shot state's bonus) of the first projectile a wand with `keys` casts.
fn cast_explosion(keys: &[&str]) -> (u32, Option<ExplosionDef>) {
    let book = SpellBook::embedded().unwrap();
    let mut wand = common::wand(&book, keys);
    let cast = wand.cast(&book, &mut SpellRng::new(1)).unwrap();
    fold(&book, &cast.projectiles[0])
}

fn durability(keys: &[&str]) -> u8 {
    cast_explosion(keys).1.expect("an explosion").max_durability
}

#[test]
fn only_explosive_projectile_carries_a_bonus() {
    let book = SpellBook::embedded().unwrap();
    let bonus: Vec<(&str, u32)> = book
        .iter()
        .map(|(_, s)| (s.key.as_str(), s.shot.explosion_durability))
        .filter(|(_, b)| *b > 0)
        .collect();
    assert_eq!(bonus, [("EXPLOSIVE_PROJECTILE", 3)]);
}

#[test]
fn the_bomb_with_the_modifier_reaches_brick_and_nothing_else_does() {
    assert_eq!(durability(&["BOMB"]), 11);
    assert_eq!(durability(&["EXPLOSIVE_PROJECTILE", "BOMB"]), 14);
    assert!(i32::from(durability(&["EXPLOSIVE_PROJECTILE", "BOMB"])) >= BRICK);
    // every other pair of the catalogue stays below brick
    for projectile in [
        "LIGHT_BULLET",
        "BULLET",
        "SLOW_BULLET",
        "FIREBALL",
        "DIGGER",
        "EXPLOSION",
    ] {
        let d = i32::from(durability(&["EXPLOSIVE_PROJECTILE", projectile]));
        assert!(d < BRICK, "{projectile} + EXPLOSIVE_PROJECTILE reaches {d}");
    }
    assert_eq!(durability(&["EXPLOSIVE_PROJECTILE", "FIREBALL"]), 13);
    assert_eq!(durability(&["EXPLOSIVE_PROJECTILE", "SLOW_BULLET"]), 13);
    assert_eq!(durability(&["EXPLOSIVE_PROJECTILE", "EXPLOSION"]), 13);
    assert_eq!(durability(&["EXPLOSIVE_PROJECTILE", "LIGHT_BULLET"]), 11);
}

#[test]
fn copies_do_not_stack_the_largest_bonus_counts() {
    let (bonus, _) = cast_explosion(&["EXPLOSIVE_PROJECTILE", "EXPLOSIVE_PROJECTILE", "DIGGER"]);
    assert_eq!(bonus, 3, "the shot state keeps the largest bonus");
    assert_eq!(
        durability(&["EXPLOSIVE_PROJECTILE", "EXPLOSIVE_PROJECTILE", "DIGGER"]),
        13
    );
    assert_eq!(
        durability(&[
            "EXPLOSIVE_PROJECTILE",
            "EXPLOSIVE_PROJECTILE",
            "EXPLOSIVE_PROJECTILE",
            "DIGGER"
        ]),
        13
    );
    // two of them in front of the bomb are the same 14 as one
    assert_eq!(
        durability(&["EXPLOSIVE_PROJECTILE", "EXPLOSIVE_PROJECTILE", "BOMB"]),
        14
    );
    // while the radius bonus does add up
    let single = cast_explosion(&["EXPLOSIVE_PROJECTILE", "BOMB"]).1.unwrap();
    let double = cast_explosion(&["EXPLOSIVE_PROJECTILE", "EXPLOSIVE_PROJECTILE", "BOMB"])
        .1
        .unwrap();
    assert_eq!((single.radius, double.radius), (75, 90));
}

#[test]
fn a_modifier_behind_the_projectile_gives_no_bonus_to_that_cast() {
    // spells per cast 1: the bomb is dealt alone, the modifier waits for the next cast
    assert_eq!(durability(&["BOMB", "EXPLOSIVE_PROJECTILE"]), 11);
    assert_eq!(cast_explosion(&["BOMB", "EXPLOSIVE_PROJECTILE"]).0, 0);
    // the cards come round again: the modifier's draw wraps the deck and finds the bomb in the
    // discard pile (WAND-R23), so the second cast is the key after all
    let book = SpellBook::embedded().unwrap();
    let mut wand = common::wand(&book, &["BOMB", "EXPLOSIVE_PROJECTILE"]);
    let mut rng = SpellRng::new(1);
    let first = common::cast_and_wait(&mut wand, &book, &mut rng);
    let second = common::cast_and_wait(&mut wand, &book, &mut rng);
    assert_eq!(
        fold(&book, &first.projectiles[0]).1.unwrap().max_durability,
        11
    );
    assert_eq!(book.key(second.projectiles[0].spell), "BOMB");
    assert_eq!(
        fold(&book, &second.projectiles[0])
            .1
            .unwrap()
            .max_durability,
        14
    );
}

#[test]
fn every_projectile_of_a_shot_state_gets_the_largest_bonus_whatever_the_order() {
    // a multicast deals its cards into one shot state (WAND-R30): the modifier dealt after the
    // bomb still counts for it, and for the spark bolt next to it; two modifiers do not add up
    let book = SpellBook::embedded().unwrap();
    for keys in [
        &["BURST_2", "BOMB", "EXPLOSIVE_PROJECTILE", "LIGHT_BULLET"][..],
        &[
            "BURST_3",
            "BOMB",
            "EXPLOSIVE_PROJECTILE",
            "EXPLOSIVE_PROJECTILE",
            "LIGHT_BULLET",
        ][..],
    ] {
        let mut wand = common::wand(&book, keys);
        let cast = wand.cast(&book, &mut SpellRng::new(1)).unwrap();
        let by_key = |key: &str| {
            let spawn = cast
                .projectiles
                .iter()
                .find(|s| book.key(s.spell) == key)
                .unwrap_or_else(|| panic!("{keys:?}: no {key} in the cast"));
            fold(&book, spawn)
        };
        let (bonus, bomb) = by_key("BOMB");
        assert_eq!((bonus, bomb.unwrap().max_durability), (3, 14), "{keys:?}");
        let (bonus, spark) = by_key("LIGHT_BULLET");
        assert_eq!((bonus, spark.unwrap().max_durability), (3, 11), "{keys:?}");
    }
}

#[test]
fn an_always_cast_modifier_counts_for_the_root_shot_and_the_bonus_stays_with_its_cast() {
    let book = SpellBook::embedded().unwrap();
    let mut wand = common::wand_with(
        &book,
        common::stats(),
        &["BOMB", "BOMB"],
        &["EXPLOSIVE_PROJECTILE"],
    );
    let mut rng = SpellRng::new(1);
    for _ in 0..2 {
        let cast = common::cast_and_wait(&mut wand, &book, &mut rng);
        assert_eq!(
            fold(&book, &cast.projectiles[0]).1.unwrap().max_durability,
            14
        );
    }
    // a plain wand cast afterwards starts from nothing, and so does another wand
    assert_eq!(durability(&["BOMB"]), 11);
    let mut other = common::wand(&book, &["BOMB"]);
    let cast = other.cast(&book, &mut SpellRng::new(1)).unwrap();
    assert_eq!(cast.root.explosion_durability, 0);
}

#[test]
fn the_bonus_applies_to_the_modified_projectiles_only() {
    // A modifier in a trigger's payload is a separate shot state: it must not reach the carrier.
    let book = SpellBook::embedded().unwrap();
    let mut wand = common::wand(
        &book,
        &["LIGHT_BULLET_TRIGGER", "EXPLOSIVE_PROJECTILE", "BOMB"],
    );
    let cast = wand.cast(&book, &mut SpellRng::new(1)).unwrap();
    let carrier = &cast.projectiles[0];
    assert_eq!(carrier.shot.explosion_durability, 0);
    let payload = &carrier.trigger.as_ref().unwrap().payload[0];
    assert_eq!(payload.shot.explosion_durability, 3);
    // and a bonus before a spell without a blast of its own gives it the default one, plus 3
    assert_eq!(durability(&["EXPLOSIVE_PROJECTILE", "RUBBER_BALL"]), 13);
}

#[test]
fn a_catalogue_without_the_field_loads_with_a_zero_bonus() {
    let mut doc: Value =
        serde_json::from_str(include_str!("../../../content/spells.json")).expect("json");
    for spell in doc["spells"].as_array_mut().unwrap() {
        spell["shot"]
            .as_object_mut()
            .unwrap()
            .remove("explosion_durability");
    }
    let book = SpellBook::from_json(&doc.to_string(), "old/spells.json").expect("old file loads");
    let ep = book.get(book.id("EXPLOSIVE_PROJECTILE").unwrap());
    assert_eq!(ep.shot.explosion_durability, 0);
    // and the embedded file writes it for every spell
    let embedded: Value =
        serde_json::from_str(include_str!("../../../content/spells.json")).unwrap();
    assert!(embedded["spells"]
        .as_array()
        .unwrap()
        .iter()
        .all(|s| s["shot"]["explosion_durability"].is_u64()));
}

#[test]
fn the_folded_durability_survives_a_serde_round_trip() {
    let e = cast_explosion(&["EXPLOSIVE_PROJECTILE", "BOMB"]).1.unwrap();
    let text = serde_json::to_string(&e).unwrap();
    let back: ExplosionDef = serde_json::from_str(&text).unwrap();
    assert_eq!(back, e);
    assert_eq!(back.max_durability, 14);
}

/// A brick wall `x0..x0 + 20` over the full height, in front of the player at x = 100.
fn brick_wall_world() -> Game {
    let mut g = with_player(W, H, FLOOR, 100);
    g.world_mut()
        .fill_rect(150, 0, 20, H - FLOOR, "brick")
        .unwrap();
    g
}

fn bricks(g: &Game) -> usize {
    count_cells(g, 150, 0, 20, H - FLOOR, "brick")
}

/// Throw the bomb wand at the wall and let the fuse burn down.
fn throw_and_wait(g: &mut Game, keys: &[&str]) {
    let w = give(g, keys);
    run(g, 1, &fire(w, 20.0));
    run(g, 230, &Controls::default());
}

#[test]
fn a_bomb_alone_leaves_the_brick_wall_standing() {
    let mut g = brick_wall_world();
    let before = bricks(&g);
    throw_and_wait(&mut g, &["BOMB"]);
    let radii: Vec<i64> = explosions(&events(&mut g)).iter().map(|e| e.2).collect();
    assert_eq!(radii, [60], "the bomb did go off");
    assert_eq!(bricks(&g), before, "durability 11 < 14");
}

#[test]
fn a_bomb_with_the_modifier_breaks_brick() {
    for keys in [
        &["EXPLOSIVE_PROJECTILE", "BOMB"][..],
        &["EXPLOSIVE_PROJECTILE", "EXPLOSIVE_PROJECTILE", "BOMB"][..],
    ] {
        let mut g = brick_wall_world();
        let before = bricks(&g);
        throw_and_wait(&mut g, keys);
        let radii: Vec<i64> = explosions(&events(&mut g)).iter().map(|e| e.2).collect();
        assert_eq!(radii.len(), 1, "{keys:?}: {radii:?}");
        let removed = before - bricks(&g);
        assert!(removed > 50, "{keys:?} removed only {removed} brick cells");
    }
}

/// A floor of `material` under the player, a dig bolt fired straight down: how many of its cells
/// go.
fn dug(material: &str, keys: &[&str]) -> usize {
    let mut g = scene::world(W, H, FLOOR, 1);
    g.world_mut()
        .fill_rect(0, H - FLOOR, W, FLOOR, material)
        .unwrap();
    g.spawn_player(100, ground_y(H, FLOOR)).unwrap();
    run(&mut g, 61, &Controls::default());
    let area = (80, H - FLOOR, 40, 20);
    let before = count_cells(&g, area.0, area.1, area.2, area.3, material);
    let w = give(&mut g, keys);
    run(&mut g, 60, &fire(w, -90.0));
    run(&mut g, 30, &Controls::default());
    before - count_cells(&g, area.0, area.1, area.2, area.3, material)
}

fn dug_brick(keys: &[&str]) -> usize {
    dug("brick", keys)
}

#[test]
fn a_dig_bolt_never_gets_through_brick_however_many_modifiers_it_has() {
    // control: the same wands do dig ground (durability 10), so the zeros below are not a dud
    assert!(dug("ground", &["DIGGER"]) > 50);
    assert!(
        dug(
            "ground",
            &["EXPLOSIVE_PROJECTILE", "EXPLOSIVE_PROJECTILE", "DIGGER"]
        ) > 50
    );
    assert_eq!(dug_brick(&["DIGGER"]), 0);
    assert_eq!(
        dug_brick(&["EXPLOSIVE_PROJECTILE", "DIGGER"]),
        0,
        "10 + 3 = 13"
    );
    assert_eq!(
        dug_brick(&["EXPLOSIVE_PROJECTILE", "EXPLOSIVE_PROJECTILE", "DIGGER"]),
        0,
        "copies do not stack: still 13, not 16"
    );
    assert_eq!(
        dug_brick(&[
            "EXPLOSIVE_PROJECTILE",
            "EXPLOSIVE_PROJECTILE",
            "EXPLOSIVE_PROJECTILE",
            "DIGGER"
        ]),
        0
    );
}

#[test]
fn a_snapshot_taken_with_the_bomb_in_the_air_breaks_the_same_brick() {
    let mut g = brick_wall_world();
    let before = bricks(&g);
    let w = give(&mut g, &["EXPLOSIVE_PROJECTILE", "BOMB"]);
    run(&mut g, 1, &fire(w, 20.0));
    run(&mut g, 20, &Controls::default());
    let blob = g.snapshot().unwrap();
    run(&mut g, 210, &Controls::default());
    let (left, hash) = (bricks(&g), g.state_hash());
    assert!(left < before, "the wall was breached");

    g.restore(&blob).unwrap();
    assert_eq!(bricks(&g), before, "restored to before the blast");
    run(&mut g, 210, &Controls::default());
    assert_eq!((bricks(&g), g.state_hash()), (left, hash));
}
