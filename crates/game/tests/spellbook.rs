//! The spell catalogue: what `content/spells.json` contains and how bad files are rejected.

mod common;

use cogbench_game::spell::{BodyKind, SpellType, TriggerKind};
use cogbench_game::{Error, SpellBook};
use common::{approx, book};
use serde_json::{json, Value};

/// v1-scope.md section 4, in the order of the file (the order is the spell id).
const SCOPE: [&str; 25] = [
    "LIGHT_BULLET",
    "BULLET",
    "RUBBER_BALL",
    "SLOW_BULLET",
    "BOMB",
    "FIREBALL",
    "DIGGER",
    "EXPLOSION",
    "MATERIAL_WATER",
    "MATERIAL_OIL",
    "MATERIAL_ACID",
    "LIGHT_BULLET_TRIGGER",
    "LIGHT_BULLET_TIMER",
    "BURST_2",
    "BURST_3",
    "SPEED",
    "DAMAGE",
    "HEAVY_SHOT",
    "SPREAD_REDUCE",
    "BOUNCE",
    "EXPLOSIVE_PROJECTILE",
    "FIRE_TRAIL",
    "WATER_TRAIL",
    "RECHARGE",
    "MANA_REDUCE",
];

fn embedded_json() -> Value {
    let text = include_str!("../../../content/spells.json");
    serde_json::from_str(text).expect("valid json")
}

fn load(doc: &Value) -> Result<SpellBook, Error> {
    SpellBook::from_json(&doc.to_string(), "test/spells.json")
}

fn message(result: Result<SpellBook, Error>) -> String {
    result.expect_err("expected a validation error").to_string()
}

#[test]
fn spell_r01_the_embedded_catalogue_is_the_25_in_scope_spells_in_order() {
    let book = book();
    let keys: Vec<&str> = book.iter().map(|(_, s)| s.key.as_str()).collect();
    assert_eq!(keys, SCOPE);
    for (i, key) in SCOPE.iter().enumerate() {
        assert_eq!(book.id(key).map(|id| usize::from(id.0)), Some(i));
    }
    assert_eq!(book.id("NUKE"), None);
}

#[test]
fn spell_r01_load_reads_the_same_file_from_disk() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../content/spells.json");
    assert_eq!(SpellBook::load(&path).expect("loads").len(), 25);
}

#[test]
fn spell_r03_damage_is_internal_units() {
    let book = book();
    let spark = book.get(book.id("LIGHT_BULLET").unwrap());
    let projectile = spark.projectile.as_ref().unwrap();
    assert!(approx(projectile.hit_damage, 0.12)); // 3 shown
    let damage = book.get(book.id("DAMAGE").unwrap());
    assert!(approx(damage.shot.damage, 0.4)); // +10 shown
    let heavy = book.get(book.id("HEAVY_SHOT").unwrap());
    assert!(approx(heavy.shot.damage, 1.75)); // +43.75 shown
    let bomb = book
        .get(book.id("BOMB").unwrap())
        .projectile
        .clone()
        .unwrap();
    assert!(approx(bomb.explosion.unwrap().damage, 5.0)); // 125 shown
}

#[test]
fn spell_r05_absent_xml_attributes_take_the_engine_default() {
    let book = book();
    let bomb = book
        .get(book.id("BOMB").unwrap())
        .projectile
        .clone()
        .unwrap();
    assert_eq!((bomb.speed_min, bomb.speed_max), (60.0, 60.0));
    assert!(approx(bomb.air_friction, 0.55) && approx(bomb.gravity, 400.0));
    assert_eq!(bomb.body, BodyKind::ThrownBody);
    // DIGGER names no gravity either: the default 400 applies.
    let digger = book
        .get(book.id("DIGGER").unwrap())
        .projectile
        .clone()
        .unwrap();
    assert!(approx(digger.gravity, 400.0));
}

#[test]
fn spell_r06_mana_costs_and_the_negative_one() {
    let book = book();
    let mana = |k: &str| book.get(book.id(k).unwrap()).mana;
    assert_eq!(mana("LIGHT_BULLET"), 5);
    assert_eq!(mana("BURST_2"), 0);
    assert_eq!(mana("BURST_3"), 2);
    assert_eq!(mana("FIREBALL"), 70);
    assert_eq!(mana("MANA_REDUCE"), -30);
}

#[test]
fn spell_r07_limited_uses() {
    let book = book();
    let uses = |k: &str| book.get(book.id(k).unwrap()).max_uses;
    assert_eq!(
        (uses("BOMB"), uses("FIREBALL"), uses("LIGHT_BULLET")),
        (Some(3), Some(15), None)
    );
}

#[test]
fn spell_r12_draw_counts_per_type() {
    let book = book();
    for (_, spell) in book.iter() {
        match spell.kind {
            SpellType::Modifier => assert_eq!(spell.draw, 1, "{}", spell.key),
            SpellType::Multicast => assert!(spell.draw >= 2, "{}", spell.key),
            _ => assert_eq!(spell.draw, 0, "{}", spell.key),
        }
    }
    let draw = |k: &str| book.get(book.id(k).unwrap()).draw;
    assert_eq!((draw("BURST_2"), draw("BURST_3")), (2, 3));
}

#[test]
fn spell_r18_triggers() {
    let book = book();
    let trigger = |k: &str| book.get(book.id(k).unwrap()).trigger.clone();
    let collision = trigger("LIGHT_BULLET_TRIGGER").unwrap();
    assert_eq!(
        (
            collision.kind,
            collision.timer_frames,
            collision.payload_draws
        ),
        (TriggerKind::Collision, None, 1)
    );
    let timer = trigger("LIGHT_BULLET_TIMER").unwrap();
    assert_eq!(
        (timer.kind, timer.timer_frames, timer.payload_draws),
        (TriggerKind::Timer, Some(10), 1)
    );
    assert_eq!(book.iter().filter(|(_, s)| s.trigger.is_some()).count(), 2);
}

#[test]
fn spell_r30_material_spells_name_what_they_leave_behind() {
    let book = book();
    let emit = |k: &str| {
        book.get(book.id(k).unwrap())
            .projectile
            .clone()
            .unwrap()
            .emit
            .unwrap()
    };
    assert_eq!(emit("MATERIAL_ACID").count, 6);
    assert_eq!(emit("MATERIAL_WATER").material, "water");
    let fire = book.get(book.id("FIRE_TRAIL").unwrap());
    assert_eq!(
        (
            fire.shot.trail[0].material.as_str(),
            fire.shot.trail[0].amount
        ),
        ("fire", 10)
    );
    assert!(book
        .check_materials(&|m| ["water", "oil", "acid", "fire"].contains(&m))
        .is_ok());
    let err = book
        .check_materials(&|m| m != "fire")
        .unwrap_err()
        .to_string();
    assert!(
        err.contains("content/spells.json") && err.contains("unknown material \"fire\""),
        "{err}"
    );
}

#[test]
fn spell_r31_explosion_configs() {
    let book = book();
    let explosion = |k: &str| {
        book.get(book.id(k).unwrap())
            .projectile
            .clone()
            .unwrap()
            .explosion
    };
    let bomb = explosion("BOMB").unwrap();
    assert_eq!(
        (
            bomb.radius,
            bomb.ray_energy,
            bomb.max_durability,
            bomb.cell_percent
        ),
        (60, 6_000_000, 11, 40)
    );
    assert!(!bomb.dont_damage_shooter);
    let spark = explosion("LIGHT_BULLET").unwrap();
    assert_eq!(
        (spark.radius, spark.max_durability, spark.cell_percent),
        (2, 8, 0)
    );
    // The rubber ball's blast block exists in the XML but never goes off.
    assert!(explosion("RUBBER_BALL").is_none());
    assert!(explosion("MATERIAL_WATER").is_none());
}

#[test]
fn loader_rejects_a_wrong_format_string() {
    let mut doc = embedded_json();
    doc["format"] = json!("cogbench-spells/9");
    let msg = message(load(&doc));
    assert!(msg.starts_with("test/spells.json: format:"), "{msg}");
}

#[test]
fn loader_rejects_a_duplicate_key_naming_the_field() {
    let mut doc = embedded_json();
    doc["spells"][1]["key"] = json!("LIGHT_BULLET");
    let msg = message(load(&doc));
    assert!(
        msg.contains("spells[1].key") && msg.contains("duplicate"),
        "{msg}"
    );
}

#[test]
fn loader_rejects_a_lowercase_key() {
    let mut doc = embedded_json();
    doc["spells"][0]["key"] = json!("spark");
    assert!(message(load(&doc)).contains("spells[0].key"));
}

#[test]
fn loader_rejects_a_missing_field() {
    let mut doc = embedded_json();
    doc["spells"][2].as_object_mut().unwrap().remove("mana");
    let msg = message(load(&doc));
    assert!(
        msg.starts_with("test/spells.json:") && msg.contains("missing field `mana`"),
        "{msg}"
    );
}

#[test]
fn loader_rejects_a_modifier_that_draws_nothing() {
    let mut doc = embedded_json();
    doc["spells"][15]["draw"] = json!(0); // SPEED
    let msg = message(load(&doc));
    assert!(msg.contains("spells[15] (SPEED).draw"), "{msg}");
}

#[test]
fn loader_rejects_a_projectile_card_without_projectile_block() {
    let mut doc = embedded_json();
    doc["spells"][0]["projectile"] = Value::Null;
    assert!(message(load(&doc)).contains("spells[0] (LIGHT_BULLET).projectile"));
}

#[test]
fn loader_rejects_a_timer_trigger_without_frames() {
    let mut doc = embedded_json();
    doc["spells"][12]["trigger"]["timer_frames"] = Value::Null;
    assert!(message(load(&doc)).contains("spells[12] (LIGHT_BULLET_TIMER).trigger.timer_frames"));
}

#[test]
fn loader_rejects_zero_uses_and_silly_mana() {
    let mut doc = embedded_json();
    doc["spells"][4]["max_uses"] = json!(0);
    assert!(message(load(&doc)).contains("spells[4] (BOMB).max_uses"));
    let mut doc = embedded_json();
    doc["spells"][0]["mana"] = json!(5000);
    assert!(message(load(&doc)).contains("spells[0] (LIGHT_BULLET).mana"));
}

#[test]
fn loader_rejects_a_speed_range_that_is_backwards() {
    let mut doc = embedded_json();
    doc["spells"][0]["projectile"]["speed_min"] = json!(900);
    assert!(message(load(&doc)).contains("spells[0] (LIGHT_BULLET).projectile.speed_min"));
}

#[test]
fn loader_rejects_a_body_that_does_not_fit_the_spell_type() {
    let mut doc = embedded_json();
    doc["spells"][8]["projectile"]["body"] = json!("projectile"); // MATERIAL_WATER
    assert!(message(load(&doc)).contains("spells[8] (MATERIAL_WATER).projectile.body"));
}

#[test]
fn loader_names_the_file_for_unreadable_json_and_missing_files() {
    let msg = SpellBook::from_json("{ nope", "x/spells.json")
        .unwrap_err()
        .to_string();
    assert!(msg.starts_with("x/spells.json:"), "{msg}");
    let err = SpellBook::load(std::path::Path::new("/definitely/not/here.json")).unwrap_err();
    assert!(
        matches!(err, Error::Io { .. }) && err.to_string().contains("/definitely/not/here.json")
    );
}

#[test]
fn loader_ignores_unknown_fields() {
    let mut doc = embedded_json();
    doc["future"] = json!(true);
    doc["spells"][0]["something_new"] = json!([1, 2, 3]);
    assert_eq!(load(&doc).expect("unknown fields are fine").len(), 25);
}
