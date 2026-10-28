//! Invariants that must hold for any wand: a seeded random walk over wands, spells, mana and
//! clicks. The checks are structural (no card is lost or duplicated, numbers stay sane), so they
//! catch bookkeeping slips that a hand-made vector would not reach.

mod common;

use cogbench_game::wand::{Wand, WandStats};
use cogbench_game::{SpellBook, SpellId, SpellRandom, SpellRng};
use common::*;

/// A tiny deterministic generator for the test itself (independent of the code under test).
struct Lcg(u64);

impl Lcg {
    fn next(&mut self, n: u32) -> u32 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        ((self.0 >> 33) % u64::from(n)) as u32
    }
}

fn random_wand(book: &SpellBook, lcg: &mut Lcg) -> Wand {
    let capacity = 2 + lcg.next(10);
    let stats = WandStats {
        shuffle: lcg.next(2) == 0,
        spells_per_cast: 1 + lcg.next(capacity.min(4)),
        cast_delay: lcg.next(30) as i32 - 10,
        recharge: lcg.next(60) as i32 - 20,
        mana_max: 20.0 + lcg.next(300) as f32,
        mana_charge_speed: 5.0 + lcg.next(200) as f32,
        capacity,
        spread: lcg.next(20) as f32 - 5.0,
        speed_multiplier: 1.0,
    };
    let spells: Vec<Option<SpellId>> = (0..capacity)
        .map(|_| (lcg.next(5) != 0).then(|| SpellId(lcg.next(book.len() as u32) as u16)))
        .collect();
    let always: Vec<SpellId> = (0..lcg.next(3))
        .map(|_| SpellId(lcg.next(book.len() as u32) as u16))
        .collect();
    Wand::new(book, stats, &spells, &always).expect("a valid random wand")
}

fn live_cards(wand: &Wand) -> usize {
    wand.slots()
        .iter()
        .flatten()
        .filter(|slot| slot.uses != Some(0))
        .count()
}

#[test]
fn no_card_is_lost_or_duplicated_over_random_clicks() {
    let book = book();
    let mut lcg = Lcg(12345);
    for seed in 0..300u64 {
        let mut wand = random_wand(&book, &mut lcg);
        let mut rng = SpellRng::new(seed);
        for click in 0..60 {
            if lcg.next(7) == 0 {
                wand.set_mana(lcg.next(120) as f32);
            }
            let result = wand
                .cast(&book, &mut rng)
                .unwrap_or_else(|e| panic!("wand {seed} click {click}: {e}"));
            // The hand is empty again: every card with uses left is in the deck or the discard
            // pile, exactly once; cards that ran out of uses left the cycle.
            let in_piles = wand.deck_spells().len() + wand.discarded_spells().len();
            assert_eq!(
                in_piles,
                live_cards(&wand),
                "wand {seed} click {click}: cards in the piles"
            );
            assert!(result.cast_delay >= 1 && result.ready_in >= result.cast_delay);
            assert!(
                result.mana_after >= 0.0,
                "wand {seed} click {click}: negative mana"
            );
            let bookkeeping = result.mana_before - result.mana_after - result.mana_spent;
            assert!(bookkeeping.abs() < 1e-3, "wand {seed} click {click}: mana");
            assert_eq!(wand.mana(), result.mana_after);
            wand.advance(result.ready_in);
            assert!(wand.is_ready());
        }
    }
}

#[test]
fn every_slot_card_is_in_exactly_one_pile_after_a_recharge() {
    // After a click that started a recharge nothing is in the discard pile, and the deck holds
    // every card that still has uses (no duplicates, no losses).
    let book = book();
    let mut lcg = Lcg(777);
    let mut checked = 0;
    for seed in 0..300u64 {
        let mut wand = random_wand(&book, &mut lcg);
        let mut rng = SpellRng::new(seed);
        for _ in 0..40 {
            let result = cast_and_wait(&mut wand, &book, &mut rng);
            if result.recharge.is_none() {
                continue;
            }
            checked += 1;
            assert!(wand.discarded_spells().is_empty());
            let mut deck: Vec<u16> = wand.deck_spells().iter().map(|s| s.0).collect();
            let mut expected: Vec<u16> = wand
                .slots()
                .iter()
                .flatten()
                .filter(|slot| slot.uses != Some(0))
                .map(|slot| slot.spell.0)
                .collect();
            deck.sort_unstable();
            expected.sort_unstable();
            assert_eq!(deck, expected, "wand {seed}: deck after a recharge");
            assert_eq!(deck.len(), live_cards(&wand));
        }
    }
    assert!(
        checked > 500,
        "the walk should recharge often, saw {checked}"
    );
}

#[test]
fn the_random_source_is_only_consulted_for_shuffles_and_spreads() {
    // A non-shuffle wand whose cards have no spread never touches the random source at all.
    struct Forbidden;
    impl SpellRandom for Forbidden {
        fn shuffle_index(&mut self, _n: u32) -> u32 {
            panic!("a non-shuffle wand must not shuffle");
        }
        fn spread_unit(&mut self) -> f32 {
            panic!("a wand without spread must not roll an angle");
        }
    }
    let book = book();
    let mut wand = wand(&book, &["DIGGER", "BOMB", "EXPLOSION"]);
    for _ in 0..9 {
        let result = wand.cast(&book, &mut Forbidden).unwrap();
        wand.advance(result.ready_in);
    }
}
