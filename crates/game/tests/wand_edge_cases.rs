//! Hand-checked vectors for the corners of the casting algorithm that the KB vectors do not reach:
//! a wrap inside a payload, a multicast inside a payload, an always-cast multicast, a wand whose
//! only spell ran out of uses. Each expectation was worked out on paper from the reference
//! pseudocode of `wand-casting.md` before it was written down.

mod common;

use cogbench_game::spell::TriggerKind;
use common::*;

fn rng() -> Scripted {
    Scripted::new()
}

#[test]
fn a_multicast_draw_that_ends_in_a_wrap_still_applies_the_modifier_to_the_root_shot() {
    // [BURST_2, LB_TRIGGER, LB, DAMAGE]: BURST_2 draws the trigger (whose payload takes LB) and
    // DAMAGE; DAMAGE then draws on an empty deck, wraps an empty discard pile and is done.
    let book = book();
    let mut wand = wand(
        &book,
        &["BURST_2", "LIGHT_BULLET_TRIGGER", "LIGHT_BULLET", "DAMAGE"],
    );
    let result = wand.cast(&book, &mut rng()).unwrap();
    assert_eq!(
        spawn_keys(&book, &result.projectiles),
        ["LIGHT_BULLET_TRIGGER"]
    );
    let carrier = &result.projectiles[0];
    assert!(approx(carrier.shot.damage, 0.4), "DAMAGE is a root card");
    let payload = &carrier.trigger.as_ref().unwrap().payload;
    assert_eq!(spawn_keys(&book, payload), ["LIGHT_BULLET"]);
    assert_eq!(
        payload[0].shot.damage, 0.0,
        "DAMAGE does not reach the payload"
    );
    assert_eq!(result.mana_spent, 20.0, "BURST_2 free, 10 + 5 + 5");
    assert_eq!(result.root.cast_delay, 8, "3 for the trigger, 5 for DAMAGE");
    assert!(result.wrapped, "the empty-deck draw of DAMAGE wrapped");
    assert_eq!(result.recharge, Some(0));
    assert_eq!(result.ready_in, 8);
}

#[test]
fn a_payload_that_meets_an_empty_deck_wraps_the_discard_pile() {
    // [LB, LB_TRIGGER]: click 2 draws the trigger after the deck ran dry; the payload wraps the
    // discard pile (holding the Spark Bolt of click 1) and takes that card.
    let book = book();
    let mut wand = wand(&book, &["LIGHT_BULLET", "LIGHT_BULLET_TRIGGER"]);
    let first = cast_and_wait(&mut wand, &book, &mut rng());
    assert!(first.recharge.is_none());
    let second = cast_and_wait(&mut wand, &book, &mut rng());
    let carrier = &second.projectiles[0];
    assert_eq!(book.key(carrier.spell), "LIGHT_BULLET_TRIGGER");
    let trigger = carrier.trigger.as_ref().unwrap();
    assert_eq!(trigger.kind, TriggerKind::Collision);
    assert_eq!(spawn_keys(&book, &trigger.payload), ["LIGHT_BULLET"]);
    assert!(second.wrapped && second.recharge.is_some());
    assert_eq!(second.mana_spent, 15.0);
    // The recharge dealt everything back in slot order.
    assert_eq!(
        keys_of(&book, &wand.deck_spells()),
        ["LIGHT_BULLET", "LIGHT_BULLET_TRIGGER"]
    );
    assert!(wand.discarded_spells().is_empty());
}

#[test]
fn a_multicast_inside_a_payload_fills_the_payload() {
    let book = book();
    let mut wand = wand(
        &book,
        &["LIGHT_BULLET_TRIGGER", "BURST_2", "LIGHT_BULLET", "BULLET"],
    );
    let result = wand.cast(&book, &mut rng()).unwrap();
    assert_eq!(result.projectiles.len(), 1);
    let payload = &result.projectiles[0].trigger.as_ref().unwrap().payload;
    assert_eq!(spawn_keys(&book, payload), ["LIGHT_BULLET", "BULLET"]);
    assert_eq!(result.mana_spent, 10.0 + 5.0 + 20.0);
    assert_eq!(
        result.root.cast_delay, 3,
        "payload cards' delays stay in the payload"
    );
}

#[test]
fn an_always_cast_multicast_draws_from_the_deck_and_the_wands_own_draw_finds_it_empty() {
    // WAND-R71: only a draw of exactly one is cancelled for an always-cast; BURST_2 draws two.
    let book = book();
    let mut wand = wand_with(&book, stats(), &["LIGHT_BULLET", "BULLET"], &["BURST_2"]);
    let result = wand.cast(&book, &mut rng()).unwrap();
    assert_eq!(
        spawn_keys(&book, &result.projectiles),
        ["LIGHT_BULLET", "BULLET"]
    );
    assert_eq!(
        result.mana_spent, 25.0,
        "the always-cast is free, the cards are not"
    );
    assert_eq!(
        keys_of(&book, &result.played),
        ["BURST_2", "LIGHT_BULLET", "BULLET"]
    );
    assert!(!result.wrapped, "the wand's own draw never wraps");
    assert!(
        result.recharge.is_some(),
        "the deck is empty at the end of the click"
    );
}

#[test]
fn a_wand_whose_only_spell_ran_out_of_uses_does_nothing_but_keeps_recharging() {
    let book = book();
    let mut wand = wand(&book, &["BOMB"]);
    for click in 0..3 {
        let result = cast_and_wait(&mut wand, &book, &mut rng());
        assert_eq!(result.projectiles.len(), 1, "click {click}");
    }
    assert_eq!(wand.slots()[0].unwrap().uses, Some(0));
    assert!(wand.deck_spells().is_empty() && wand.discarded_spells().is_empty());
    let dead = cast_and_wait(&mut wand, &book, &mut rng());
    assert!(dead.projectiles.is_empty() && dead.played.is_empty());
    assert!(
        dead.skipped.is_empty(),
        "nothing was drawn, so nothing was skipped"
    );
    assert_eq!(dead.cast_delay, 1);
    assert!(dead.recharge.is_some());
}

#[test]
fn equipping_again_gives_an_exhausted_spell_a_place_in_the_deck_where_it_is_skipped() {
    let book = book();
    let mut wand = wand(&book, &["BOMB", "LIGHT_BULLET"]);
    wand.set_uses(0, Some(0));
    wand.equip();
    let result = wand.cast(&book, &mut rng()).unwrap();
    assert_eq!(spawn_keys(&book, &result.projectiles), ["LIGHT_BULLET"]);
    assert_eq!(result.skipped.len(), 1);
    assert_eq!(result.mana_spent, 5.0);
}
