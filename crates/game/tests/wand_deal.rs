//! Casting rules about dealing the cards (`wand-casting.md` WAND-R11..R41 and the spread of
//! SPELL-R09): deck order, draw and skip, wrap, multicast, modifiers, payloads. One test per rule,
//! named after the rule id.

mod common;

use cogbench_game::spell::TriggerKind;
use cogbench_game::wand::SkipReason;
use cogbench_game::{SpellRandom, SpellRng};
use common::*;

fn no_rng() -> Scripted {
    Scripted::new()
}

#[test]
fn wand_r12_mana_is_capped_at_click_start() {
    let book = book();
    let mut s = stats();
    s.mana_max = 100.0;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET"], &[]);
    wand.set_mana(150.0);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!((result.mana_before, result.mana_after), (100.0, 95.0));
    assert_eq!(wand.mana(), 95.0);
}

#[test]
fn wand_r12_first_click_deals_the_deck_in_slot_order() {
    let book = book();
    let mut s = stats();
    s.spells_per_cast = 2;
    let mut wand = wand_with(&book, s, &["BULLET", "LIGHT_BULLET"], &[]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(
        spawn_keys(&book, &result.projectiles),
        ["BULLET", "LIGHT_BULLET"]
    );
}

#[test]
fn wand_r11_shuffle_deals_the_permutation_the_stream_chooses() {
    let book = book();
    let mut s = stats();
    s.shuffle = true;
    s.spells_per_cast = 3;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET", "BULLET", "SLOW_BULLET"], &[]);
    // Indices into the remaining cards: take #2, then #0, then the last one.
    let result = wand
        .cast(&book, &mut Scripted::with_indices(&[2, 0, 0]))
        .unwrap();
    assert_eq!(
        spawn_keys(&book, &result.projectiles),
        ["SLOW_BULLET", "LIGHT_BULLET", "BULLET"]
    );
}

#[test]
fn wand_r11_a_shuffle_wand_keeps_one_permutation_until_the_next_recharge() {
    let book = book();
    let mut s = stats();
    s.shuffle = true;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET", "BULLET", "SLOW_BULLET"], &[]);
    let mut rng = Scripted::with_indices(&[1, 0, 0]); // deals BULLET, LIGHT_BULLET, SLOW_BULLET
    let mut dealt = Vec::new();
    for _ in 0..4 {
        let result = cast_and_wait(&mut wand, &book, &mut rng);
        dealt.push(spawn_keys(&book, &result.projectiles)[0].clone());
    }
    // Click 3 empties the deck; the recharge shuffles the discard pile (in the order it was
    // discarded) again. The script is spent, so index 0 keeps that order: BULLET comes first.
    assert_eq!(dealt, ["BULLET", "LIGHT_BULLET", "SLOW_BULLET", "BULLET"]);
}

#[test]
fn wand_r11_without_shuffle_a_recharge_restores_slot_order() {
    let book = book();
    let mut wand = wand(&book, &["LIGHT_BULLET", "BULLET"]);
    cast_and_wait(&mut wand, &book, &mut no_rng());
    let second = cast_and_wait(&mut wand, &book, &mut no_rng());
    assert!(second.recharge.is_some());
    assert_eq!(
        keys_of(&book, &wand.deck_spells()),
        ["LIGHT_BULLET", "BULLET"]
    );
    assert!(wand.discarded_spells().is_empty());
}

#[test]
fn wand_r20_a_card_that_costs_exactly_the_mana_left_is_played() {
    let book = book();
    let mut wand = wand(&book, &["LIGHT_BULLET"]);
    wand.set_mana(5.0);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(spawn_keys(&book, &result.projectiles), ["LIGHT_BULLET"]);
    assert_eq!(result.mana_after, 0.0);
}

#[test]
fn wand_r20_r21_unaffordable_cards_are_skipped_for_free_and_the_draw_retries() {
    // [EXPLOSIVE_PROJECTILE (30), LIGHT_BULLET (5)], one card per click, by mana at click start.
    let book = book();
    let cases: [(f32, &[&str], f32); 4] = [
        (35.0, &["LIGHT_BULLET"], 0.0), // EP plays, then its draw takes the Spark Bolt
        (31.0, &[], 1.0), // EP plays, the Spark Bolt (5) is skipped: last card eats the draw
        (29.0, &["LIGHT_BULLET"], 24.0), // EP skipped for free, the retry draws the Spark Bolt
        (4.0, &[], 4.0),  // nothing is affordable
    ];
    for (mana, expected, left) in cases {
        let mut wand = wand(&book, &["EXPLOSIVE_PROJECTILE", "LIGHT_BULLET"]);
        wand.set_mana(mana);
        let result = wand.cast(&book, &mut no_rng()).unwrap();
        assert_eq!(
            spawn_keys(&book, &result.projectiles),
            expected,
            "mana {mana}"
        );
        assert_eq!(result.mana_after, left, "mana {mana}");
    }
    let mut wand = wand(&book, &["EXPLOSIVE_PROJECTILE", "LIGHT_BULLET"]);
    wand.set_mana(29.0);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    let skipped: Vec<_> = result
        .skipped
        .iter()
        .map(|s| (book.key(s.spell), s.reason))
        .collect();
    assert_eq!(
        skipped,
        [("EXPLOSIVE_PROJECTILE", SkipReason::NotEnoughMana)]
    );
}

#[test]
fn wand_r22_the_wands_own_draws_never_wrap() {
    let book = book();
    let mut s = stats();
    s.spells_per_cast = 3;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET", "BULLET"], &[]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(
        spawn_keys(&book, &result.projectiles),
        ["LIGHT_BULLET", "BULLET"]
    );
    assert!(!result.wrapped);
    assert!(result.recharge.is_some(), "an emptied deck recharges (WD1)");
}

#[test]
fn wand_r23_r51_a_trailing_modifier_wraps_the_wand_and_forces_a_recharge() {
    // draw_05 of the fixtures with SPEED in place of LIGHT: [BURST_2, LB, LB, LB, SPEED].
    let book = book();
    let mut wand = wand(
        &book,
        &[
            "BURST_2",
            "LIGHT_BULLET",
            "LIGHT_BULLET",
            "LIGHT_BULLET",
            "SPEED",
        ],
    );
    let first = cast_and_wait(&mut wand, &book, &mut no_rng());
    assert_eq!(first.projectiles.len(), 2);
    assert!(first.recharge.is_none() && !first.wrapped);
    let second = cast_and_wait(&mut wand, &book, &mut no_rng());
    assert_eq!(second.projectiles.len(), 1);
    assert!(second.recharge.is_none());
    let third = cast_and_wait(&mut wand, &book, &mut no_rng());
    assert_eq!(
        spawn_keys(&book, &third.projectiles),
        ["LIGHT_BULLET", "LIGHT_BULLET"]
    );
    assert!(
        third.wrapped && third.recharge.is_some(),
        "a wrap recharges although the deck is refilled"
    );
    assert_eq!(keys_of(&book, &third.root.modifiers), ["SPEED"]);
}

#[test]
fn wand_r24_draw_budget_of_nested_multicasts_and_modifiers() {
    // draw_02 of the fixtures with BOMB in place of NUKE.
    let book = book();
    let slots = [
        "DAMAGE",
        "BURST_2",
        "BURST_3",
        "LIGHT_BULLET",
        "LIGHT_BULLET",
        "LIGHT_BULLET",
        "SPEED",
        "LIGHT_BULLET",
        "BOMB",
    ];
    let mut wand = wand(&book, &slots);
    let first = cast_and_wait(&mut wand, &book, &mut no_rng());
    assert_eq!(first.projectiles.len(), 4);
    assert_eq!(keys_of(&book, &first.root.modifiers), ["DAMAGE", "SPEED"]);
    assert!(first.recharge.is_none());
    let second = cast_and_wait(&mut wand, &book, &mut no_rng());
    assert_eq!(spawn_keys(&book, &second.projectiles), ["BOMB"]);
    assert!(second.recharge.is_some());
}

#[test]
fn wand_r30_modifiers_reach_every_projectile_of_their_shot_state() {
    let book = book();
    let mut wand = wand(&book, &["BURST_2", "LIGHT_BULLET", "DAMAGE", "BULLET"]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    // DAMAGE is played after the Spark Bolt but its +0.4 is on both projectiles.
    assert_eq!(result.projectiles.len(), 2);
    assert!(result
        .projectiles
        .iter()
        .all(|p| approx(p.shot.damage, 0.4)));
}

#[test]
fn wand_r31_a_payload_starts_from_defaults() {
    let book = book();
    let mut s = stats();
    s.cast_delay = 10;
    s.spread = 5.0;
    s.speed_multiplier = 2.0;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET_TRIGGER", "RUBBER_BALL"], &[]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    let carrier = &result.projectiles[0];
    assert!(approx(carrier.shot.speed_mul, 2.0) && approx(carrier.shot.spread, 5.0));
    assert_eq!(carrier.shot.cast_delay, 13);
    let payload = &carrier.trigger.as_ref().unwrap().payload[0];
    assert_eq!(book.key(payload.spell), "RUBBER_BALL");
    assert!(
        approx(payload.shot.speed_mul, 1.0),
        "wand speed does not leak into the payload"
    );
    assert!(
        approx(payload.shot.spread, -1.0),
        "wand spread does not leak into the payload"
    );
    assert_eq!(
        payload.shot.cast_delay, -2,
        "only the payload's own cards count"
    );
}

#[test]
fn wand_r32_r40_a_payload_is_drawn_and_paid_at_cast_time() {
    let book = book();
    let mut wand = wand(&book, &["LIGHT_BULLET_TRIGGER", "RUBBER_BALL"]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(result.mana_spent, 15.0);
    assert_eq!(
        keys_of(&book, &result.played),
        ["LIGHT_BULLET_TRIGGER", "RUBBER_BALL"]
    );
    let trigger = result.projectiles[0].trigger.as_ref().unwrap();
    assert_eq!(trigger.kind, TriggerKind::Collision);
    assert_eq!(spawn_keys(&book, &trigger.payload), ["RUBBER_BALL"]);
    // The payload card is in the hand like any other: it was discarded, and the recharge that
    // started (the deck ran dry) dealt both cards back into the deck.
    assert_eq!(
        keys_of(&book, &wand.deck_spells()),
        ["LIGHT_BULLET_TRIGGER", "RUBBER_BALL"]
    );
}

#[test]
fn wand_r40_payloads_nest() {
    let book = book();
    let mut wand = wand(
        &book,
        &["LIGHT_BULLET_TRIGGER", "LIGHT_BULLET_TIMER", "RUBBER_BALL"],
    );
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    let outer = result.projectiles[0].trigger.as_ref().unwrap();
    let inner = &outer.payload[0];
    assert_eq!(book.key(inner.spell), "LIGHT_BULLET_TIMER");
    let inner_trigger = inner.trigger.as_ref().unwrap();
    assert_eq!(
        (inner_trigger.kind, inner_trigger.timer_frames),
        (TriggerKind::Timer, Some(10))
    );
    assert_eq!(spawn_keys(&book, &inner_trigger.payload), ["RUBBER_BALL"]);
}

#[test]
fn wand_r41_the_payloads_cast_delay_does_not_count_for_the_wand() {
    let book = book();
    let mut wand = wand(&book, &["LIGHT_BULLET_TRIGGER", "DAMAGE", "BULLET"]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(
        result.root.cast_delay, 3,
        "only the Spark Bolt with Trigger"
    );
    assert_eq!(result.cast_delay, 3);
    assert_eq!(
        result.recoil, 33.0,
        "recoil is global: 10 from DAMAGE and 23 from the arrow"
    );
}

#[test]
fn spell_r09_spread_adds_up_and_the_angle_is_rolled_within_it() {
    let book = book();
    let mut s = stats();
    s.spread = 10.0;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET"], &[]);
    let mut rng = Scripted::new();
    rng.unit = 0.0;
    let result = wand.cast(&book, &mut rng).unwrap();
    let spawn = &result.projectiles[0];
    assert!(approx(spawn.spread_degrees, 9.0)); // wand 10, Spark Bolt -1
    assert!(approx(spawn.angle_offset_degrees, -9.0));
}

#[test]
fn spell_r09_negative_total_spread_is_zero_and_rolls_nothing() {
    let book = book();
    let mut wand = wand(&book, &["SPREAD_REDUCE", "BULLET"]);
    let mut rng = SpellRng::new(5);
    let before = rng.clone();
    let result = wand.cast(&book, &mut rng).unwrap();
    assert_eq!(result.projectiles[0].spread_degrees, 0.0);
    assert_eq!(result.projectiles[0].angle_offset_degrees, 0.0);
    assert_eq!(rng, before, "no spread, no random draw");
}

#[test]
fn spell_r33_modifiers_that_repeat_stack_and_trails_merge() {
    let book = book();
    let mut wand = wand(
        &book,
        &["FIRE_TRAIL", "FIRE_TRAIL", "WATER_TRAIL", "LIGHT_BULLET"],
    );
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    let trail: Vec<_> = result
        .root
        .trail
        .iter()
        .map(|t| (t.material.as_str(), t.amount))
        .collect();
    assert_eq!(trail, [("fire", 20), ("water", 20)]);
    assert_eq!(
        result.root.effects.len(),
        2,
        "an effect is applied once however often it is added"
    );
}

#[test]
fn wand_r11_shuffle_is_uniform_over_permutations() {
    // 10,000 fresh wands deal [A, B, C] in a random order: each of the 6 orders is expected
    // 1,667 times with a standard deviation of 37; allow 4 sigma.
    let book = book();
    let mut counts = std::collections::BTreeMap::new();
    for seed in 0..10_000u64 {
        let mut s = stats();
        s.shuffle = true;
        s.spells_per_cast = 3;
        let mut wand = wand_with(&book, s, &["LIGHT_BULLET", "BULLET", "SLOW_BULLET"], &[]);
        let result = wand.cast(&book, &mut SpellRng::new(seed)).unwrap();
        *counts
            .entry(spawn_keys(&book, &result.projectiles))
            .or_insert(0u32) += 1;
    }
    assert_eq!(counts.len(), 6);
    for (order, count) in counts {
        assert!((1518..=1816).contains(&count), "{order:?}: {count}");
    }
}

#[test]
fn spread_roll_uses_its_own_stream() {
    // The spread of a projectile must not change which cards a shuffle wand deals.
    let book = book();
    let deal = |spread: f32| {
        let mut s = stats();
        s.shuffle = true;
        s.spread = spread;
        s.spells_per_cast = 3;
        let mut wand = wand_with(&book, s, &["LIGHT_BULLET", "BULLET", "SLOW_BULLET"], &[]);
        let result = wand.cast(&book, &mut SpellRng::new(77)).unwrap();
        spawn_keys(&book, &result.projectiles)
    };
    assert_eq!(deal(0.0), deal(20.0));
    let mut rng = SpellRng::new(1);
    assert!(rng.spread_unit() < 1.0);
}
