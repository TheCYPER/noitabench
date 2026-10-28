//! Helpers shared by the integration tests of the wand engine.
#![allow(dead_code)]

use std::collections::VecDeque;

use cogbench_game::wand::{CastResult, ProjectileSpawn, Wand, WandStats};
use cogbench_game::{SpellBook, SpellId, SpellRandom};

pub fn book() -> SpellBook {
    SpellBook::embedded().expect("content/spells.json loads")
}

/// The `default_wand` of the fixtures: nothing limits the cast but the cards themselves.
pub fn stats() -> WandStats {
    WandStats {
        shuffle: false,
        spells_per_cast: 1,
        cast_delay: 0,
        recharge: 0,
        mana_max: 100_000.0,
        mana_charge_speed: 100_000.0,
        capacity: 26,
        spread: 0.0,
        speed_multiplier: 1.0,
    }
}

pub fn id(book: &SpellBook, key: &str) -> SpellId {
    book.id(key).unwrap_or_else(|| panic!("no spell {key}"))
}

pub fn ids(book: &SpellBook, keys: &[&str]) -> Vec<SpellId> {
    keys.iter().map(|k| id(book, k)).collect()
}

/// A wand with `keys` in its first slots and the given always-casts.
pub fn wand_with(book: &SpellBook, stats: WandStats, keys: &[&str], always: &[&str]) -> Wand {
    let spells: Vec<Option<SpellId>> = keys.iter().map(|k| Some(id(book, k))).collect();
    Wand::new(book, stats, &spells, &ids(book, always)).expect("valid wand")
}

pub fn wand(book: &SpellBook, keys: &[&str]) -> Wand {
    wand_with(book, stats(), keys, &[])
}

pub fn spawn_keys(book: &SpellBook, spawns: &[ProjectileSpawn]) -> Vec<String> {
    spawns
        .iter()
        .map(|s| book.key(s.spell).to_string())
        .collect()
}

pub fn keys_of(book: &SpellBook, spells: &[SpellId]) -> Vec<String> {
    spells.iter().map(|s| book.key(*s).to_string()).collect()
}

/// Cast and let the whole cooldown pass, as a player waiting for the wand would.
pub fn cast_and_wait(wand: &mut Wand, book: &SpellBook, rng: &mut dyn SpellRandom) -> CastResult {
    let result = wand.cast(book, rng).expect("wand is ready");
    wand.advance(result.ready_in);
    result
}

/// A random source with a script: deck shuffles take the scripted indices (then index 0, which
/// keeps the order), the spread roll is a constant (0.5 means "straight ahead").
pub struct Scripted {
    pub indices: VecDeque<u32>,
    pub unit: f32,
}

impl Scripted {
    pub fn new() -> Self {
        Scripted {
            indices: VecDeque::new(),
            unit: 0.5,
        }
    }

    pub fn with_indices(indices: &[u32]) -> Self {
        Scripted {
            indices: indices.iter().copied().collect(),
            unit: 0.5,
        }
    }
}

impl SpellRandom for Scripted {
    fn shuffle_index(&mut self, n: u32) -> u32 {
        self.indices.pop_front().unwrap_or(0).min(n - 1)
    }

    fn spread_unit(&mut self) -> f32 {
        self.unit
    }
}

pub fn approx(a: f32, b: f32) -> bool {
    (a - b).abs() <= 1e-4 * a.abs().max(b.abs()).max(1.0)
}
