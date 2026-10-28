//! `content/entities.json`: the numbers of the game layer are validated up front.

use cogbench_game::{EntityDefs, Error};

fn edited(f: impl FnOnce(&mut serde_json::Value)) -> Result<EntityDefs, Error> {
    let text = include_str!("../../../content/entities.json");
    let mut v: serde_json::Value = serde_json::from_str(text).unwrap();
    f(&mut v);
    EntityDefs::from_json(&v.to_string(), "entities-test.json")
}

#[test]
fn the_embedded_file_loads() {
    let d = EntityDefs::embedded().unwrap();
    assert_eq!(d.enemies.len(), 3);
    assert_eq!(d.items.barrels.len(), 3);
    assert_eq!(d.player.hp, 4.0);
    assert_eq!(
        d.player.collision.w, 4,
        "the world generator assumes a 4 x 7 player"
    );
    assert_eq!(d.player.collision.h, 7);
}

#[test]
fn damage_floor_follows_dur_r08() {
    let d = EntityDefs::embedded().unwrap();
    // 325 / 375 / 500 displayed, in internal units
    assert_eq!(d.damage_floor(10), 0.0);
    assert_eq!(d.damage_floor(32) * 25.0, 325.0);
    assert_eq!(d.damage_floor(63) * 25.0, 325.0);
    assert_eq!(d.damage_floor(64) * 25.0, 375.0);
    assert_eq!(d.damage_floor(127) * 25.0, 375.0);
    assert_eq!(d.damage_floor(128) * 25.0, 500.0);
}

#[test]
fn errors_name_the_file_and_the_field() {
    let err = edited(|v| v["format"] = "cogbench-entities/9".into()).unwrap_err();
    assert!(
        err.to_string().contains("entities-test.json: format"),
        "{err}"
    );
    let err = edited(|v| v["enemies"]["longleg"]["hp"] = 0.0.into()).unwrap_err();
    assert!(err.to_string().contains("enemies.longleg"), "{err}");
    let err = edited(|v| v["enemies"]["shotgunner"]["ranged"]["projectile"] = "cannon".into())
        .unwrap_err();
    assert!(
        err.to_string()
            .contains("enemies.shotgunner.ranged.projectile"),
        "{err}"
    );
    let err = edited(|v| v["contact"]["status"]["water"] = "soggy".into()).unwrap_err();
    assert!(err.to_string().contains("unknown status"), "{err}");
    let err = edited(|v| v["player"]["hitboxes"] = serde_json::json!([])).unwrap_err();
    assert!(err.to_string().contains("player.hitboxes"), "{err}");
    let err = edited(|v| v["explosion"]["damage_floor"][0]["radius"] = 500.into()).unwrap_err();
    assert!(err.to_string().contains("ascend"), "{err}");
    let err = edited(|v| {
        v["items"]["barrels"]["crate"] = v["items"]["barrels"]["barrel_oil"].clone();
    })
    .unwrap_err();
    assert!(err.to_string().contains("barrel_"), "{err}");
    let err = edited(|v| {
        v["enemies"]["longleg"]["ai"] = "shooter".into();
    })
    .unwrap_err();
    assert!(err.to_string().contains("ranged attack"), "{err}");
}

#[test]
fn a_game_refuses_defs_that_name_missing_materials() {
    let defs = edited(|v| {
        v["items"]["barrels"]["barrel_acid"]["contents"]["material"] = "mercury".into();
    })
    .unwrap();
    let content = std::sync::Arc::new(cogbench_sim::Content::embedded().unwrap());
    let world = cogbench_sim::World::new(10, 10, 1, content).unwrap();
    let book = std::sync::Arc::new(cogbench_game::SpellBook::embedded().unwrap());
    let err = cogbench_game::Game::with_content(world, book, std::sync::Arc::new(defs))
        .err()
        .expect("must fail");
    assert!(err.to_string().contains("mercury"), "{err}");
}

#[test]
fn attacks_must_be_visible_for_a_decision_tick() {
    let err = edited(|v| v["enemies"]["longleg"]["melee"]["windup"] = 5.into()).unwrap_err();
    assert!(err.to_string().contains("enemies.longleg"), "{err}");
    let err = edited(|v| v["enemies"]["longleg"]["lunge"]["windup"] = 10.into()).unwrap_err();
    assert!(err.to_string().contains("windups"), "{err}");
    let err = edited(|v| v["enemies"]["shotgunner"]["ranged"]["windup"] = 12.into()).unwrap_err();
    assert!(
        err.to_string().contains("enemies.shotgunner.ranged.windup"),
        "{err}"
    );
}

#[test]
fn sizes_ranges_and_tiers_are_checked() {
    let err = edited(|v| v["player"]["collision"]["w"] = 0.into()).unwrap_err();
    assert!(err.to_string().contains("player.collision"), "{err}");
    let err =
        edited(|v| v["enemies"]["firemage_weak"]["hitboxes"][0]["h"] = (-3).into()).unwrap_err();
    assert!(err.to_string().contains("firemage_weak.hitboxes"), "{err}");
    let err = edited(|v| v["sim"]["active_range"] = 0.into()).unwrap_err();
    assert!(err.to_string().contains("sim.active_range"), "{err}");
    let err =
        edited(|v| v["wand_tiers"]["2"]["cast_delay"] = serde_json::json!([20, 4])).unwrap_err();
    assert!(err.to_string().contains("wand_tiers.2.cast_delay"), "{err}");
    let err = edited(|v| v["wand_tiers"]["3"]["capacity"] = serde_json::json!([0, 4])).unwrap_err();
    assert!(err.to_string().contains("wand_tiers.3"), "{err}");
    let err = edited(|v| {
        v["wand_tiers"]["four"] = v["wand_tiers"]["1"].clone();
    })
    .unwrap_err();
    assert!(err.to_string().contains("tier keys"), "{err}");
}

#[test]
fn a_game_refuses_defs_without_a_drink_effect_the_materials_name() {
    let defs = edited(|v| {
        v["drink"].as_object_mut().unwrap().remove("heal");
    })
    .unwrap();
    let content = std::sync::Arc::new(cogbench_sim::Content::embedded().unwrap());
    let world = cogbench_sim::World::new(10, 10, 1, content).unwrap();
    let book = std::sync::Arc::new(cogbench_game::SpellBook::embedded().unwrap());
    let err = cogbench_game::Game::with_content(world, book, std::sync::Arc::new(defs))
        .err()
        .expect("must fail");
    let text = err.to_string();
    assert!(
        text.contains("potion_heal") && text.contains("heal"),
        "{text}"
    );
}
