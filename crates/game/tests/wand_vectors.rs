//! The KB vectors `KV-*` (wand-casting.md) and `TV-S*` (spells.md) that only use in-scope spells,
//! plus the two worked timing examples. Where the KB vector uses a spell outside the 25, the
//! stand-in is named in the test (SPITTER -> RUBBER_BALL, ROCKET -> FIREBALL, CHAINSAW -> DIGGER).
//! Damage is in internal units (the KB's displayed values divided by 25).

mod common;

use cogbench_game::spell::TriggerKind;
use cogbench_game::wand::Wand;
use common::*;

fn rng() -> Scripted {
    Scripted::new()
}

#[test]
fn kv_07_a_trigger_and_its_payload_are_paid_card_by_card() {
    // KV-07 with RUBBER_BALL (mana 5, like SPITTER) as the payload.
    let book = book();
    let cases: [(f32, &[&str], bool, f32); 4] = [
        (15.0, &["LIGHT_BULLET_TRIGGER"], true, 15.0), // trigger and payload
        (12.0, &["LIGHT_BULLET_TRIGGER"], false, 10.0), // trigger with an empty payload
        (7.0, &["RUBBER_BALL"], false, 5.0), // trigger skipped, the payload card is cast alone
        (4.0, &[], false, 0.0),
    ];
    for (mana, expected, has_payload, spent) in cases {
        let mut wand = wand(&book, &["LIGHT_BULLET_TRIGGER", "RUBBER_BALL"]);
        wand.set_mana(mana);
        let result = wand.cast(&book, &mut rng()).unwrap();
        assert_eq!(
            spawn_keys(&book, &result.projectiles),
            expected,
            "mana {mana}"
        );
        assert_eq!(result.mana_spent, spent, "mana {mana}");
        if let Some(trigger) = result.projectiles.first().and_then(|p| p.trigger.as_ref()) {
            assert_eq!(!trigger.payload.is_empty(), has_payload, "mana {mana}");
        }
    }
}

#[test]
fn kv_08_a_modifier_with_one_use_drops_out_of_the_cycle() {
    let book = book();
    let mut wand = wand(&book, &["DAMAGE", "LIGHT_BULLET"]);
    wand.set_uses(0, Some(1));
    let first = cast_and_wait(&mut wand, &book, &mut rng());
    assert!(approx(first.root.damage, 0.4));
    assert!(first.recharge.is_some());
    assert_eq!(wand.slots()[0].unwrap().uses, Some(0));
    for _ in 0..2 {
        let next = cast_and_wait(&mut wand, &book, &mut rng());
        assert_eq!(spawn_keys(&book, &next.projectiles), ["LIGHT_BULLET"]);
        assert_eq!(next.root.damage, 0.0);
        assert!(
            next.recharge.is_some(),
            "the deck is empty after every click"
        );
    }
}

#[test]
fn kv_09_recharge_deltas_pile_up_over_the_cycle() {
    // KV-09 with DIGGER (cast delay +1, recharge -10, mana 0) in place of CHAINSAW.
    let book = book();
    let mut s = stats();
    s.cast_delay = 10;
    s.recharge = 40;
    let mut wand = wand_with(&book, s, &["DIGGER"; 4], &[]);
    for click in 1..=4 {
        let result = cast_and_wait(&mut wand, &book, &mut rng());
        assert_eq!(result.cast_delay, 11);
        assert_eq!(result.mana_spent, 0.0);
        let expected = if click < 4 { None } else { Some(0) }; // 40 - 4 x 10
        assert_eq!(result.recharge, expected, "click {click}");
    }
    // The next cycle starts from the base recharge again.
    let mut s = stats();
    s.recharge = 100;
    let mut wand = wand_with(&book, s, &["DIGGER"; 4], &[]);
    let last = (0..4)
        .map(|_| cast_and_wait(&mut wand, &book, &mut rng()))
        .last()
        .unwrap();
    assert_eq!(last.recharge, Some(60));
}

#[test]
fn kv_10_a_payload_spells_recharge_delta_counts_at_cast_time() {
    let book = book();
    let mut s = stats();
    s.recharge = 30;
    let mut wand = wand_with(
        &book,
        s,
        &["LIGHT_BULLET_TRIGGER", "DIGGER", "LIGHT_BULLET"],
        &[],
    );
    let first = cast_and_wait(&mut wand, &book, &mut rng());
    assert_eq!(first.mana_spent, 10.0);
    assert_eq!(
        first.cast_delay, 3,
        "the payload's +1 cast delay is not the wand's"
    );
    assert!(first.recharge.is_none());
    let second = cast_and_wait(&mut wand, &book, &mut rng());
    assert_eq!(
        second.recharge,
        Some(20),
        "30 - 10 from the DIGGER inside the payload"
    );
}

#[test]
fn kv_13_an_always_cast_modifier_is_free_on_every_click() {
    let book = book();
    let mut s = stats();
    s.spells_per_cast = 2;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET"; 3], &["DAMAGE"]);
    let first = cast_and_wait(&mut wand, &book, &mut rng());
    assert_eq!(first.projectiles.len(), 2);
    assert!(first.projectiles.iter().all(|p| approx(p.shot.damage, 0.4)));
    assert_eq!(first.mana_spent, 10.0);
    let second = cast_and_wait(&mut wand, &book, &mut rng());
    assert_eq!(second.projectiles.len(), 1);
    assert!(approx(second.projectiles[0].shot.damage, 0.4));
    assert!(second.recharge.is_some());
}

#[test]
fn kv_14_a_negative_total_cast_delay_is_one_frame() {
    let book = book();
    let mut s = stats();
    s.cast_delay = -15;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET"], &[]);
    let result = wand.cast(&book, &mut rng()).unwrap();
    assert_eq!((result.root.cast_delay, result.cast_delay), (-12, 1));
}

#[test]
fn tv_s1_damage_and_spark_bolt() {
    let book = book();
    let result = wand(&book, &["DAMAGE", "LIGHT_BULLET"])
        .cast(&book, &mut rng())
        .unwrap();
    let spark = book
        .get(id(&book, "LIGHT_BULLET"))
        .projectile
        .clone()
        .unwrap();
    assert!(approx(spark.hit_damage + result.root.damage, 0.52)); // 3 + 10 shown
    assert_eq!(result.root.cast_delay, 8);
    assert!(approx(result.root.crit_chance, 5.0));
    assert_eq!((result.recoil, result.mana_spent), (10.0, 10.0));
}

#[test]
fn tv_s2_two_heavy_shots_multiply_the_speed() {
    let book = book();
    let result = wand(&book, &["HEAVY_SHOT", "HEAVY_SHOT", "LIGHT_BULLET"])
        .cast(&book, &mut rng())
        .unwrap();
    assert!(approx(result.root.damage, 3.5)); // 87.5 shown
    assert!(approx(result.root.speed_mul, 0.09));
    assert_eq!(result.root.cast_delay, 23);
}

#[test]
fn tv_s3_the_speed_multiplier_is_clamped_after_each_modifier() {
    let book = book();
    let speed = |n: usize| {
        let mut keys = vec!["SPEED"; n];
        keys.push("LIGHT_BULLET");
        wand(&book, &keys)
            .cast(&book, &mut rng())
            .unwrap()
            .root
            .speed_mul
    };
    assert!(approx(speed(1), 2.5) && approx(speed(2), 6.25) && approx(speed(3), 15.625));
    assert_eq!(speed(4), 20.0);
    assert_eq!(speed(9), 20.0);
}

#[test]
fn tv_s6_explosive_projectile_before_a_bomb() {
    let book = book();
    let result = wand(&book, &["EXPLOSIVE_PROJECTILE", "BOMB"])
        .cast(&book, &mut rng())
        .unwrap();
    assert_eq!(result.root.explosion_radius, 15.0); // the radius floor of R33 is projectile-side
    assert_eq!(result.root.explosion_durability, 3); // cogbench extension: bomb 11 + 3 = brick 14
    assert!(approx(result.root.explosion_damage, 0.2));
    assert!(approx(result.root.speed_mul, 0.75));
    assert_eq!((result.root.cast_delay, result.mana_spent), (140, 55.0));
}

#[test]
fn tv_s7_explosive_projectile_before_a_spark_bolt() {
    let book = book();
    let result = wand(&book, &["EXPLOSIVE_PROJECTILE", "LIGHT_BULLET"])
        .cast(&book, &mut rng())
        .unwrap();
    assert_eq!(result.root.explosion_radius, 15.0);
    assert_eq!(result.root.cast_delay, 43);
}

#[test]
fn tv_s12_a_timer_payload_has_its_own_modifiers() {
    // [LIGHT_BULLET_TIMER, DAMAGE, SPITTER] with RUBBER_BALL as the payload projectile.
    let book = book();
    let result = wand(&book, &["LIGHT_BULLET_TIMER", "DAMAGE", "RUBBER_BALL"])
        .cast(&book, &mut rng())
        .unwrap();
    let carrier = &result.projectiles[0];
    assert_eq!(carrier.shot.damage, 0.0);
    let trigger = carrier.trigger.as_ref().unwrap();
    assert_eq!(
        (trigger.kind, trigger.timer_frames),
        (TriggerKind::Timer, Some(10))
    );
    let payload = &trigger.payload[0];
    assert!(approx(payload.shot.damage, 0.4));
    assert_eq!(keys_of(&book, &payload.shot.modifiers), ["DAMAGE"]);
    assert_eq!(result.root.cast_delay, 3, "payload cast delay is ignored");
}

#[test]
fn tv_s13_bounce_adds_ten_bounces() {
    // [BOUNCE, SPITTER] with RUBBER_BALL: 10 of its own plus 10 from the modifier at spawn time.
    let book = book();
    let result = wand(&book, &["BOUNCE", "RUBBER_BALL"])
        .cast(&book, &mut rng())
        .unwrap();
    assert_eq!(result.root.bounces, 10);
    assert_eq!((result.root.cast_delay, result.cast_delay), (-2, 1));
    assert_eq!(result.mana_spent, 5.0);
    let ball = book
        .get(id(&book, "RUBBER_BALL"))
        .projectile
        .clone()
        .unwrap();
    assert_eq!(ball.bounces + result.root.bounces as u32, 20);
}

#[test]
fn tv_s15_fire_trail_leaves_fire_and_ignites_what_it_hits() {
    let book = book();
    let result = wand(&book, &["FIRE_TRAIL", "LIGHT_BULLET"])
        .cast(&book, &mut rng())
        .unwrap();
    assert_eq!(result.root.trail.len(), 1);
    assert_eq!(
        (
            result.root.trail[0].material.as_str(),
            result.root.trail[0].amount
        ),
        ("fire", 10)
    );
    assert_eq!(result.root.effects, [cogbench_game::spell::Effect::OnFire]);
    assert_eq!((result.mana_spent, result.root.cast_delay), (15.0, 3));
}

#[test]
fn tv_s16_reduce_spread_floors_the_spread_at_zero() {
    let book = book();
    let result = wand(&book, &["SPREAD_REDUCE", "BULLET"])
        .cast(&book, &mut rng())
        .unwrap();
    assert!(approx(result.root.spread, -58.0));
    assert_eq!(result.projectiles[0].spread_degrees, 0.0);
    assert_eq!((result.recoil, result.root.cast_delay), (23.0, 4));
}

#[test]
fn tv_s17_reduce_recharge_time() {
    let book = book();
    let mut s = stats();
    s.recharge = 30;
    let result = wand_with(&book, s, &["RECHARGE", "LIGHT_BULLET"], &[])
        .cast(&book, &mut rng())
        .unwrap();
    assert_eq!(result.recharge, Some(10));
    assert_eq!((result.cast_delay, result.mana_spent), (1, 17.0)); // 3 - 10 is below 1
    assert_eq!(result.ready_in, 10);
}

#[test]
fn tv_s18_add_mana_makes_the_next_card_affordable() {
    // [MANA_REDUCE, ROCKET] with FIREBALL (70) as the expensive card, wand mana 50.
    let book = book();
    let mut wand = wand(&book, &["MANA_REDUCE", "FIREBALL"]);
    wand.set_mana(50.0);
    let result = wand.cast(&book, &mut rng()).unwrap();
    assert_eq!(spawn_keys(&book, &result.projectiles), ["FIREBALL"]);
    assert_eq!((result.mana_after, result.root.cast_delay), (10.0, 60));
}

fn timing_stats(capacity: u32) -> cogbench_game::wand::WandStats {
    let mut s = stats();
    s.cast_delay = 10;
    s.recharge = 30;
    s.mana_max = 100.0;
    s.mana_charge_speed = 50.0;
    s.capacity = capacity;
    s
}

#[test]
fn timing_01_worked_example() {
    // wand-mechanics.md section 17 with RUBBER_BALL as the payload (cast delay -2 instead of -1).
    let book = book();
    let keys = [
        "BURST_2",
        "DAMAGE",
        "LIGHT_BULLET",
        "LIGHT_BULLET_TRIGGER",
        "RUBBER_BALL",
    ];
    let mut wand = wand_with(&book, timing_stats(5), &keys, &[]);
    let result = wand.cast(&book, &mut rng()).unwrap();
    assert_eq!(
        spawn_keys(&book, &result.projectiles),
        ["LIGHT_BULLET", "LIGHT_BULLET_TRIGGER"]
    );
    assert_eq!(result.root.cast_delay, 21);
    assert!(approx(result.root.spread, -1.0) && approx(result.root.crit_chance, 10.0));
    assert!(approx(result.root.damage, 0.4));
    assert_eq!(result.mana_after, 75.0);
    assert_eq!((result.recharge, result.ready_in), (Some(30), 30));
    wand.advance(result.ready_in);
    assert_eq!(wand.mana(), 100.0);
}

#[test]
fn timing_02_wrap_example() {
    let book = book();
    let mut wand = wand_with(
        &book,
        timing_stats(4),
        &["LIGHT_BULLET", "BURST_2", "RUBBER_BALL", "DAMAGE"],
        &[],
    );
    let first = wand.cast(&book, &mut rng()).unwrap();
    assert_eq!(
        (first.root.cast_delay, first.mana_after, first.recharge),
        (13, 95.0, None)
    );
    wand.advance(first.ready_in);
    assert_eq!(first.ready_in, 13);
    let second = wand.cast(&book, &mut rng()).unwrap();
    assert_eq!(
        spawn_keys(&book, &second.projectiles),
        ["RUBBER_BALL", "LIGHT_BULLET"]
    );
    assert!(second.wrapped);
    assert_eq!((second.root.cast_delay, second.mana_after), (16, 85.0));
    assert_eq!(
        second.ready_in, 30,
        "recharge is longer than the cast delay"
    );
    assert_eq!(keys_of(&book, &second.root.modifiers), ["DAMAGE"]);
}

#[test]
fn wands_do_not_depend_on_the_book_instance() {
    // Two loads of the catalogue give the same ids, so a saved wand works with a fresh book.
    let (a, b) = (book(), book());
    let mut wand: Wand = wand(&a, &["LIGHT_BULLET"]);
    assert!(wand.cast(&b, &mut rng()).is_ok());
}
