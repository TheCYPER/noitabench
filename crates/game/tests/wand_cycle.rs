//! Casting rules about the cycle around a click (`wand-casting.md` WAND-R50..R72): discard,
//! recharge, cast delay, mana, limited uses, always-casts; plus wand validation, editing,
//! determinism and snapshots. One test per rule, named after the rule id.

mod common;

use cogbench_game::wand::{SkipReason, Slot, Wand};
use cogbench_game::{Error, SpellId, SpellRng};
use common::*;

fn no_rng() -> Scripted {
    Scripted::new()
}

#[test]
fn wand_r50_the_hand_is_discarded_in_play_order() {
    let book = book();
    let mut wand = wand(&book, &["DAMAGE", "LIGHT_BULLET", "BULLET"]);
    wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(
        keys_of(&book, &wand.discarded_spells()),
        ["DAMAGE", "LIGHT_BULLET"]
    );
    assert_eq!(keys_of(&book, &wand.deck_spells()), ["BULLET"]);
}

#[test]
fn wand_r51_a_recharge_starts_only_when_the_deck_is_empty_or_wrapped() {
    let book = book();
    let mut wand = wand(&book, &["LIGHT_BULLET", "BULLET"]);
    assert!(wand.cast(&book, &mut no_rng()).unwrap().recharge.is_none());
    wand.advance(100);
    assert!(wand.cast(&book, &mut no_rng()).unwrap().recharge.is_some());
}

#[test]
fn wand_r52_r55_recharge_is_the_clamped_sum_over_the_whole_cycle() {
    let book = book();
    let mut s = stats();
    s.recharge = 30;
    let mut wand = wand_with(&book, s.clone(), &["RECHARGE", "LIGHT_BULLET"], &[]);
    assert_eq!(wand.cast(&book, &mut no_rng()).unwrap().recharge, Some(10));
    // Below zero the recharge is zero, not negative.
    s.recharge = 5;
    let mut wand = wand_with(&book, s, &["RECHARGE", "LIGHT_BULLET"], &[]);
    assert_eq!(wand.cast(&book, &mut no_rng()).unwrap().recharge, Some(0));
}

#[test]
fn wand_r53_a_click_without_projectile_waits_one_frame() {
    let book = book();
    let mut s = stats();
    s.cast_delay = 30;
    let mut wand = wand_with(&book, s, &["MANA_REDUCE"], &[]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert!(result.projectiles.is_empty());
    assert_eq!((result.root.cast_delay, result.cast_delay), (40, 1));
}

#[test]
fn wand_r54_the_wand_is_busy_for_the_longer_of_cast_delay_and_recharge() {
    let book = book();
    let mut s = stats();
    s.cast_delay = 10;
    s.recharge = 30;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET"], &[]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(
        (result.cast_delay, result.recharge, result.ready_in),
        (13, Some(30), 30)
    );
    let err = wand.cast(&book, &mut no_rng()).unwrap_err();
    assert!(matches!(err, Error::NotReady { remaining: 30 }), "{err}");
    wand.advance(29);
    assert!(!wand.is_ready() && wand.cooldown() == 1);
    wand.advance(1);
    assert!(wand.is_ready());
    assert!(wand.cast(&book, &mut no_rng()).is_ok());
}

#[test]
fn wand_r56_equipping_again_rebuilds_the_deck_but_keeps_the_cooldown() {
    let book = book();
    let mut s = stats();
    s.cast_delay = 20;
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET", "BULLET"], &[]);
    wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(keys_of(&book, &wand.deck_spells()), ["BULLET"]);
    wand.equip();
    assert_eq!(
        keys_of(&book, &wand.deck_spells()),
        ["LIGHT_BULLET", "BULLET"]
    );
    assert!(wand.discarded_spells().is_empty());
    assert_eq!(wand.cooldown(), 23, "a running delay is not cancelled");
}

#[test]
fn wand_r57_mana_regenerates_every_frame_up_to_the_maximum() {
    let book = book();
    let mut s = stats();
    s.mana_max = 100.0;
    s.mana_charge_speed = 60.0; // one mana per frame
    let mut wand = wand_with(&book, s, &["LIGHT_BULLET"], &[]);
    wand.set_mana(10.0);
    wand.advance(30);
    assert_eq!(wand.mana(), 40.0);
    wand.advance(100);
    assert_eq!(wand.mana(), 100.0);
}

#[test]
fn wand_r57_regeneration_is_the_same_in_one_step_or_many() {
    let book = book();
    let mut s = stats();
    s.mana_max = 1000.0;
    s.mana_charge_speed = 33.3;
    let mut a = wand_with(&book, s.clone(), &["LIGHT_BULLET"], &[]);
    let mut b = a.clone();
    a.set_mana(0.0);
    b.set_mana(0.0);
    a.advance(200);
    for _ in 0..200 {
        b.advance(1);
    }
    assert_eq!(a.mana().to_bits(), b.mana().to_bits());
}

#[test]
fn wand_r62_mana_gained_inside_a_click_may_exceed_the_maximum_until_the_next_click() {
    let book = book();
    let mut s = stats();
    s.mana_max = 100.0;
    s.mana_charge_speed = 0.0;
    let mut wand = wand_with(
        &book,
        s,
        &["MANA_REDUCE", "LIGHT_BULLET", "LIGHT_BULLET"],
        &[],
    );
    let first = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(first.mana_after, 125.0); // 100 + 30 - 5
    assert_eq!(wand.mana(), 125.0);
    wand.advance(first.ready_in);
    let second = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(
        second.mana_before, 100.0,
        "capped at the start of the next click"
    );
}

#[test]
fn wand_r62_gained_mana_only_helps_later_cards() {
    // Add Mana before the Fireball: 50 + 30 is enough for 70. Without it the Fireball is skipped.
    let book = book();
    let mut with = wand(&book, &["MANA_REDUCE", "FIREBALL"]);
    with.set_mana(50.0);
    let result = with.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(spawn_keys(&book, &result.projectiles), ["FIREBALL"]);
    assert_eq!(result.mana_after, 10.0);
    let mut without = wand(&book, &["FIREBALL"]);
    without.set_mana(50.0);
    let result = without.cast(&book, &mut no_rng()).unwrap();
    assert!(result.projectiles.is_empty());
    assert_eq!(result.skipped[0].reason, SkipReason::NotEnoughMana);
}

#[test]
fn wand_r63_a_card_with_uses_leaves_the_cycle_at_zero() {
    let book = book();
    let mut wand = wand(&book, &["BOMB"]);
    for expected in [Some(2), Some(1), Some(0)] {
        let result = cast_and_wait(&mut wand, &book, &mut no_rng());
        assert_eq!(spawn_keys(&book, &result.projectiles), ["BOMB"]);
        assert_eq!(wand.slots()[0].unwrap().uses, expected);
    }
    // Spent: not in the discard pile, so the recharge leaves the deck empty.
    assert!(wand.deck_spells().is_empty() && wand.discarded_spells().is_empty());
    let result = cast_and_wait(&mut wand, &book, &mut no_rng());
    assert!(result.projectiles.is_empty());
}

#[test]
fn wand_r63_an_exhausted_card_met_in_the_deck_is_skipped_and_stays_on_the_wand() {
    let book = book();
    let mut wand = wand(&book, &["BOMB", "LIGHT_BULLET"]);
    wand.set_uses(0, Some(0));
    wand.equip();
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(spawn_keys(&book, &result.projectiles), ["LIGHT_BULLET"]);
    assert_eq!(result.skipped[0].reason, SkipReason::NoUsesLeft);
    assert!(wand.slots()[0].is_some());
}

#[test]
fn wand_r63_limited_modifiers_pay_only_when_the_click_produced_a_projectile() {
    let book = book();
    let mut wand = wand(&book, &["DAMAGE"]);
    wand.set_uses(0, Some(2));
    wand.cast(&book, &mut no_rng()).unwrap(); // a modifier alone: no projectile, free
    assert_eq!(wand.slots()[0].unwrap().uses, Some(2));
}

#[test]
fn wand_r70_r71_an_always_cast_modifier_is_free_and_draws_nothing() {
    let book = book();
    let mut wand = wand_with(&book, stats(), &["LIGHT_BULLET"], &["DAMAGE"]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(keys_of(&book, &result.played), ["DAMAGE", "LIGHT_BULLET"]);
    assert_eq!(result.mana_spent, 5.0);
    assert!(approx(result.projectiles[0].shot.damage, 0.4));
    // The copy is dropped, not discarded: after the recharge only the slot card is in the deck.
    assert_eq!(keys_of(&book, &wand.deck_spells()), ["LIGHT_BULLET"]);
    assert!(wand.discarded_spells().is_empty());
}

#[test]
fn wand_r71_an_always_cast_trigger_has_an_empty_payload() {
    let book = book();
    let mut wand = wand_with(&book, stats(), &["RUBBER_BALL"], &["LIGHT_BULLET_TRIGGER"]);
    let result = wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(
        spawn_keys(&book, &result.projectiles),
        ["LIGHT_BULLET_TRIGGER", "RUBBER_BALL"]
    );
    assert!(result.projectiles[0]
        .trigger
        .as_ref()
        .unwrap()
        .payload
        .is_empty());
}

#[test]
fn wand_r72_an_always_cast_projectile_makes_limited_modifiers_pay() {
    let book = book();
    let mut wand = wand_with(&book, stats(), &["DAMAGE"], &["LIGHT_BULLET"]);
    wand.set_uses(0, Some(2));
    wand.cast(&book, &mut no_rng()).unwrap();
    assert_eq!(wand.slots()[0].unwrap().uses, Some(1));
}

#[test]
fn wand_validation_rejects_impossible_wands() {
    let book = book();
    let spark = Some(id(&book, "LIGHT_BULLET"));
    let try_wand =
        |s: cogbench_game::wand::WandStats, spells: &[Option<SpellId>], always: &[SpellId]| {
            Wand::new(&book, s, spells, always).unwrap_err().to_string()
        };
    let mut s = stats();
    s.capacity = 0;
    assert!(try_wand(s, &[], &[]).contains("capacity"));
    let mut s = stats();
    s.spells_per_cast = 27;
    assert!(try_wand(s, &[], &[]).contains("spells_per_cast"));
    let mut s = stats();
    s.mana_max = -1.0;
    assert!(try_wand(s, &[], &[]).contains("mana_max"));
    let mut s = stats();
    s.capacity = 2;
    assert!(try_wand(s, &[spark, spark, spark], &[]).contains("3 slots"));
    let five = [id(&book, "DAMAGE"); 5];
    assert!(try_wand(stats(), &[], &five).contains("at most 4"));
    assert!(try_wand(stats(), &[Some(SpellId(999))], &[]).contains("not in the spell book"));
}

#[test]
fn wand_editing_swaps_slots_and_rebuilds_the_deck() {
    let book = book();
    let mut wand = wand(&book, &["LIGHT_BULLET", "BULLET"]);
    wand.swap_slots(0, 1).unwrap();
    assert_eq!(
        keys_of(&book, &wand.deck_spells()),
        ["BULLET", "LIGHT_BULLET"]
    );
    wand.set_slot(
        3,
        Some(Slot {
            spell: id(&book, "BOMB"),
            uses: Some(3),
        }),
    )
    .unwrap();
    assert_eq!(wand.deck_spells().len(), 3);
    assert!(wand.set_slot(99, None).is_err() && wand.swap_slots(0, 99).is_err());
}

#[test]
fn wand_with_the_same_seed_casts_the_same_way() {
    let book = book();
    let run = || {
        let mut s = stats();
        s.shuffle = true;
        s.spread = 6.0;
        s.spells_per_cast = 2;
        let keys = [
            "LIGHT_BULLET",
            "BULLET",
            "SLOW_BULLET",
            "BURST_2",
            "DAMAGE",
            "RUBBER_BALL",
        ];
        let mut wand = wand_with(&book, s, &keys, &[]);
        let mut rng = SpellRng::new(2024);
        (0..40)
            .map(|_| cast_and_wait(&mut wand, &book, &mut rng))
            .collect::<Vec<_>>()
    };
    assert_eq!(run(), run());
}

#[test]
fn wand_state_survives_a_serde_round_trip() {
    let book = book();
    let mut s = stats();
    s.shuffle = true;
    s.spells_per_cast = 2;
    let keys = [
        "LIGHT_BULLET",
        "BULLET",
        "SLOW_BULLET",
        "BURST_2",
        "DAMAGE",
        "BOMB",
    ];
    let mut wand = wand_with(&book, s, &keys, &[]);
    let mut rng = SpellRng::new(11);
    for _ in 0..7 {
        cast_and_wait(&mut wand, &book, &mut rng);
    }
    let mut copy: Wand = serde_json::from_str(&serde_json::to_string(&wand).unwrap()).unwrap();
    let mut copy_rng: SpellRng =
        serde_json::from_str(&serde_json::to_string(&rng).unwrap()).unwrap();
    assert_eq!(copy, wand);
    for _ in 0..30 {
        let a = cast_and_wait(&mut wand, &book, &mut rng);
        let b = cast_and_wait(&mut copy, &book, &mut copy_rng);
        assert_eq!(a, b);
    }
}
