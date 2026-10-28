//! The wand practice range (`trial.rs`): the same casting loop as the game, without a world.

mod scene;

use cogbench_game::trial::{
    run_trial, TrialReport, TrialSlot, TrialSpec, MAX_TRIAL_FRAMES, MAX_WAND_FRAMES,
};
use cogbench_game::wand::{SkipReason, WandStats};
use cogbench_game::{EntityDefs, SpellBook};
use cogbench_sim::Content;

fn stats() -> WandStats {
    scene::stats()
}

fn spec(book: &SpellBook, stats: WandStats, keys: &[&str], frames: u32) -> TrialSpec {
    TrialSpec {
        stats,
        slots: keys
            .iter()
            .map(|k| {
                Some(TrialSlot {
                    spell: book.id(k).unwrap_or_else(|| panic!("no spell {k}")),
                    uses: None,
                })
            })
            .collect(),
        always_cast: Vec::new(),
        frames,
        seed: 0,
        keep_casts: 1_000,
    }
}

fn run(spec: &TrialSpec) -> TrialReport {
    let book = SpellBook::embedded().unwrap();
    let content = Content::embedded().unwrap();
    let defs = EntityDefs::embedded().unwrap();
    run_trial(&book, &content.mats, &defs, spec).unwrap()
}

fn keys_of(book: &SpellBook, report: &TrialReport, cast: usize) -> Vec<String> {
    report.casts[cast]
        .played
        .iter()
        .map(|s| book.key(*s).to_string())
        .collect()
}

fn near(a: f32, b: f32) -> bool {
    (a - b).abs() < 1e-4
}

#[test]
fn a_spark_bolt_wand_clicks_once_per_cast_delay_and_hurts_the_dummy_each_time() {
    let book = SpellBook::embedded().unwrap();
    let report = run(&spec(&book, stats(), &["LIGHT_BULLET"], 60));
    // cast delay +3 and an instant recharge: a click at frames 0, 3, 6 ... 57
    assert_eq!(report.total_casts, 20);
    assert_eq!(report.shooting_casts, 20);
    assert_eq!(report.projectiles, 20);
    assert_eq!(report.casts[1].frame, 3);
    // a direct hit of 0.12 with the expected gain of the +5% critical chance, and a blast of 0
    let per_cast = 0.12 * (1.0 + 0.05 * 4.0);
    assert!(
        near(report.casts[0].damage, per_cast),
        "{:?}",
        report.casts[0]
    );
    assert!(near(report.damage, 20.0 * per_cast));
    assert_eq!(report.recharges, 20, "the one card is dealt every click");
    assert_eq!(report.mana_spent, 100.0);
}

#[test]
fn recharge_and_cast_delay_run_side_by_side() {
    let book = SpellBook::embedded().unwrap();
    let mut s = stats();
    s.cast_delay = 10;
    s.recharge = 30;
    let report = run(&spec(&book, s, &["LIGHT_BULLET"], 100));
    // the longer of 13 frames of cast delay and 30 frames of recharge: clicks at 0, 30, 60, 90
    let frames: Vec<u32> = report.casts.iter().map(|c| c.frame).collect();
    assert_eq!(frames, [0, 30, 60, 90]);
    assert_eq!(report.casts[0].cast_delay, 13);
    assert_eq!(report.casts[0].recharge, Some(30));
    assert_eq!(report.casts[0].ready_in, 30);
}

#[test]
fn a_wand_that_runs_out_of_mana_clicks_on_empty() {
    let book = SpellBook::embedded().unwrap();
    let mut s = stats();
    s.mana_max = 20.0;
    s.mana_charge_speed = 0.0;
    let report = run(&spec(&book, s, &["LIGHT_BULLET"], 60));
    assert_eq!(report.shooting_casts, 4, "5 mana each, 20 in all");
    assert_eq!(report.mana_end, 0.0);
    assert_eq!(report.mana_min, 0.0);
    let empty = report.casts.iter().find(|c| c.projectiles == 0).unwrap();
    assert_eq!(
        empty.cast_delay, 1,
        "a click without a shot waits one frame"
    );
    assert_eq!(empty.skipped.len(), 1);
    assert_eq!(empty.skipped[0].reason, SkipReason::NotEnoughMana);
    assert_eq!(report.skips.len(), 1);
    assert_eq!(report.skips[0].times, report.total_casts - 4);
}

#[test]
fn a_trigger_carries_its_payload_and_the_payload_counts() {
    let book = SpellBook::embedded().unwrap();
    let report = run(&spec(&book, stats(), &["LIGHT_BULLET_TRIGGER", "BOMB"], 20));
    let first = &report.casts[0];
    assert_eq!(first.projectiles, 1);
    assert_eq!(first.payload_projectiles, 1);
    assert_eq!(first.mana_before - first.mana_after, 35.0);
    // the bomb's blast (5.0 internal, 125 shown) is on top of the carrier's hit
    assert!(first.damage > 5.0 && first.damage < 5.5, "{}", first.damage);
}

#[test]
fn spells_with_uses_run_out() {
    let book = SpellBook::embedded().unwrap();
    let report = run(&spec(&book, stats(), &["BOMB"], 600));
    // three uses, cast delay 100: three bombs, then nothing is left to deal
    assert_eq!(report.shooting_casts, 3);
    assert_eq!(report.used_up, [0]);
    assert!(
        report.skips.is_empty(),
        "the empty card is not in the deck, so it is not skipped"
    );
    assert!(near(report.damage, 3.0 * 5.0));
}

#[test]
fn the_uses_a_card_has_left_are_honoured_and_never_exceed_its_limit() {
    let book = SpellBook::embedded().unwrap();
    let bomb = book.id("BOMB").unwrap();
    let mut s = spec(&book, stats(), &["BOMB"], 600);
    s.slots[0] = Some(TrialSlot {
        spell: bomb,
        uses: Some(1),
    });
    assert_eq!(run(&s).shooting_casts, 1);
    s.slots[0] = Some(TrialSlot {
        spell: bomb,
        uses: Some(99),
    });
    assert_eq!(
        run(&s).shooting_casts,
        3,
        "cut to the spell's own limit of 3"
    );
    let bolt = book.id("LIGHT_BULLET").unwrap();
    s.slots[0] = Some(TrialSlot {
        spell: bolt,
        uses: Some(2),
    });
    assert!(
        run(&s).shooting_casts > 20,
        "an unlimited spell stays unlimited"
    );
}

#[test]
fn the_same_seed_gives_the_same_run_and_a_shuffle_wand_depends_on_it() {
    let book = SpellBook::embedded().unwrap();
    let mut s = stats();
    s.shuffle = true;
    let keys = [
        "LIGHT_BULLET",
        "BULLET",
        "RUBBER_BALL",
        "SLOW_BULLET",
        "FIREBALL",
        "DIGGER",
    ];
    let mut sp = spec(&book, s, &keys, 300);
    sp.seed = 5;
    assert_eq!(run(&sp), run(&sp));
    let first_cards: std::collections::BTreeSet<_> = (0..16)
        .map(|seed| {
            sp.seed = seed;
            keys_of(&book, &run(&sp), 0)
        })
        .collect();
    assert!(
        first_cards.len() > 1,
        "the deal order changes with the seed"
    );
    // without shuffle the seed changes nothing
    let mut plain = spec(&book, stats(), &keys, 300);
    let a = run(&plain);
    plain.seed = 99;
    assert_eq!(a, run(&plain));
}

#[test]
fn always_cast_spells_are_played_first_and_free() {
    let book = SpellBook::embedded().unwrap();
    let mut s = spec(&book, stats(), &["LIGHT_BULLET"], 10);
    s.always_cast = vec![book.id("DAMAGE").unwrap()];
    let report = run(&s);
    assert_eq!(keys_of(&book, &report, 0), ["DAMAGE", "LIGHT_BULLET"]);
    assert_eq!(
        report.casts[0].mana_before - report.casts[0].mana_after,
        5.0
    );
    assert!(report.casts[0].damage > 0.12 * 1.2, "DAMAGE adds its 0.4");
}

#[test]
fn only_the_first_clicks_are_kept_but_the_totals_count_all() {
    let book = SpellBook::embedded().unwrap();
    let mut s = spec(&book, stats(), &["LIGHT_BULLET"], 60);
    s.keep_casts = 5;
    let report = run(&s);
    assert_eq!(report.casts.len(), 5);
    assert_eq!(report.total_casts, 20);
}

#[test]
fn bad_wands_and_bad_lengths_are_errors() {
    let book = SpellBook::embedded().unwrap();
    let content = Content::embedded().unwrap();
    let defs = EntityDefs::embedded().unwrap();
    let mut s = stats();
    s.capacity = 2;
    let too_many = spec(&book, s, &["LIGHT_BULLET", "BULLET", "DAMAGE"], 10);
    let err = run_trial(&book, &content.mats, &defs, &too_many).unwrap_err();
    assert!(err.to_string().contains("slots"), "{err}");
    for frames in [0, MAX_TRIAL_FRAMES + 1] {
        let bad = spec(&book, stats(), &["LIGHT_BULLET"], frames);
        assert!(run_trial(&book, &content.mats, &defs, &bad).is_err());
    }
}

#[test]
fn the_practice_range_casts_what_the_game_casts() {
    // The same wand, fire held for the same time, once in a world and once outside it.
    let book = SpellBook::embedded().unwrap();
    let keys = [
        "BURST_2",
        "LIGHT_BULLET",
        "BULLET",
        "DAMAGE",
        "RECHARGE",
        "LIGHT_BULLET_TIMER",
    ];
    let mut st = stats();
    st.mana_max = 60.0;
    st.mana_charge_speed = 30.0;
    st.cast_delay = 7;
    st.recharge = 25;
    st.spells_per_cast = 2;
    let frames = 240;
    let report = run(&spec(&book, st.clone(), &keys, frames));

    let mut g = scene::with_player(500, 200, 30, 100);
    let spells: Vec<Option<String>> = keys.iter().map(|k| Some((*k).to_string())).collect();
    g.give_wand(st, &spells, &[]).unwrap();
    let wand = (g.player().unwrap().wands.len() - 1) as u8;
    scene::run(&mut g, frames, &scene::fire(wand, 0.0));
    let ev = scene::events(&mut g);
    let casts: Vec<_> = ev.iter().filter(|(k, _)| k == "cast").collect();
    assert!(casts.len() >= 8, "mana-limited, recharging casts: {ev:?}");
    assert_eq!(casts.len() as u32, report.shooting_casts, "{ev:?}");
    for (cast, mine) in casts.iter().zip(&report.casts) {
        let played: Vec<String> = mine
            .played
            .iter()
            .map(|s| book.key(*s).to_string())
            .collect();
        assert_eq!(scene::text(&cast.1, "spells"), played.join("+"));
        assert_eq!(scene::int(&cast.1, "ready_in"), i64::from(mine.ready_in));
    }
}

#[test]
fn cast_delay_and_recharge_are_bounded_so_that_the_sums_cannot_overflow() {
    // The practice range takes made-up wands from the agent: a cast delay near `i32::MAX` would
    // overflow when a spell adds its own (a panic in a debug build).
    let book = SpellBook::embedded().unwrap();
    let content = Content::embedded().unwrap();
    let defs = EntityDefs::embedded().unwrap();
    for (delay, recharge) in [
        (i32::MAX, 0),
        (i32::MIN, 0),
        (0, i32::MAX),
        (0, i32::MIN),
        (MAX_WAND_FRAMES as i32 + 1, 0),
        (0, -(MAX_WAND_FRAMES as i32) - 1),
    ] {
        let mut s = stats();
        s.cast_delay = delay;
        s.recharge = recharge;
        let bad = spec(&book, s, &["LIGHT_BULLET"], 10);
        let err = run_trial(&book, &content.mats, &defs, &bad).unwrap_err();
        assert!(err.to_string().contains("frames"), "{err}");
    }
    // the largest allowed numbers, with the dearest spells in every slot, run to the end
    let all: Vec<&str> = book.iter().map(|(_, s)| s.key.as_str()).collect();
    for (delay, recharge) in [
        (MAX_WAND_FRAMES as i32, MAX_WAND_FRAMES as i32),
        (-(MAX_WAND_FRAMES as i32), -(MAX_WAND_FRAMES as i32)),
    ] {
        let mut s = stats();
        s.capacity = all.len() as u32;
        s.cast_delay = delay;
        s.recharge = recharge;
        s.spells_per_cast = 3;
        let ok = spec(&book, s, &all, MAX_TRIAL_FRAMES);
        assert!(run_trial(&book, &content.mats, &defs, &ok).is_ok());
    }
}

/// A tiny deterministic generator (xorshift64*): the tests need odd inputs, not good randomness.
struct Odd(u64);

impl Odd {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }

    fn pick<T: Copy>(&mut self, from: &[T]) -> T {
        from[self.below(from.len() as u64) as usize]
    }
}

#[test]
fn random_wands_and_decks_never_panic_and_keep_their_books() {
    // Odd wands: every spell in every order, extreme cast delays and recharges, empty and
    // limited slots, shuffles, always-casts. The tests run with overflow checks on, so an
    // overflowing sum is a failure here.
    let book = SpellBook::embedded().unwrap();
    let content = Content::embedded().unwrap();
    let defs = EntityDefs::embedded().unwrap();
    let ids: Vec<_> = book.iter().map(|(id, _)| id).collect();
    let frames_pool = [1, 2, 7, 60, 300, 1_000, MAX_TRIAL_FRAMES];
    let delay_pool = [
        0,
        1,
        -1,
        9,
        -35,
        600,
        -600,
        100_000,
        -100_000,
        MAX_WAND_FRAMES as i32,
        -(MAX_WAND_FRAMES as i32),
    ];
    let mut odd = Odd(0x9E37_79B9_7F4A_7C15);
    for round in 0..400 {
        let mut s = stats();
        s.capacity = 1 + odd.below(26) as u32;
        s.spells_per_cast = 1 + odd.below(u64::from(s.capacity)) as u32;
        s.cast_delay = odd.pick(&delay_pool);
        s.recharge = odd.pick(&delay_pool);
        s.shuffle = odd.below(2) == 0;
        s.mana_max = odd.pick(&[0.0, 1.0, 20.0, 100.0, 5_000.0, 1.0e9]);
        s.mana_charge_speed = odd.pick(&[0.0, 1.0, 30.0, 1_000.0, 1.0e9]);
        s.spread = odd.pick(&[0.0, -35.0, 35.0, 1.0e6]);
        let slots = (0..odd.below(u64::from(s.capacity) + 1))
            .map(|_| {
                (odd.below(5) != 0).then(|| TrialSlot {
                    spell: odd.pick(&ids),
                    uses: odd.pick(&[None, Some(0), Some(1), Some(3), Some(u32::MAX)]),
                })
            })
            .collect();
        let always_cast = (0..odd.below(5)).map(|_| odd.pick(&ids)).collect();
        let frames = odd.pick(&frames_pool);
        let spec = TrialSpec {
            stats: s,
            slots,
            always_cast,
            frames,
            seed: odd.next(),
            keep_casts: odd.below(40) as usize,
        };
        let report = run_trial(&book, &content.mats, &defs, &spec)
            .unwrap_or_else(|e| panic!("round {round}: {e}\n{spec:?}"));
        assert_eq!(report.frames, frames);
        assert!(
            report.total_casts <= frames,
            "round {round}: a click a frame at most"
        );
        assert!(report.shooting_casts <= report.total_casts);
        assert!(report.casts.len() <= spec.keep_casts.min(report.total_casts as usize));
        assert!(report.projectiles >= report.shooting_casts);
        assert!(
            report.damage >= 0.0 && report.damage.is_finite(),
            "round {round}"
        );
        assert!(report.mana_min <= report.mana_start.max(report.mana_end));
        assert_eq!(
            report,
            run_trial(&book, &content.mats, &defs, &spec).unwrap()
        );
    }
}
