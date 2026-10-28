//! Wands and the card-game casting engine (`WAND-R01..R64`, stage 1 of `wand-casting.md`).
//!
//! A [`Wand`] holds its stats, its spell slots and the state of the deck/hand/discard cycle. One
//! [`Wand::cast`] is one click: it deals cards, applies modifiers to shot states, pays mana, and
//! returns the projectiles to create, the cast delay and whether a recharge started. There is no
//! world here; the caller turns the result into entities and calls [`Wand::advance`] once per
//! frame (mana regeneration and the cast-delay / recharge countdown).
//!
//! Implemented: draw, skip and wrap, multicast, modifiers, trigger/timer payloads, mana per card,
//! limited uses, shuffle, always-cast, recharge and cast-delay accounting. Not implemented (none
//! of the 25 spells needs them): Divide, Add Trigger, Greek letters, Duplication, Requirement,
//! Wand Refresh, set-mode cast delay, Mana To Damage.

mod cast;
mod cycle;
mod shot;

use serde::{Deserialize, Serialize};

use crate::error::Error;
use crate::spell::{SpellBook, SpellId};

pub use cycle::Card;
pub use shot::{CastResult, ProjectileSpawn, ShotParams, SkipReason, Skipped, Trigger};

use cycle::Cycle;

/// Most always-cast spells a wand can carry (WAND-R72).
pub const MAX_ALWAYS_CAST: usize = 4;
/// Largest deck capacity the game allows (WAND-R93 absolute cap).
pub const MAX_CAPACITY: u32 = 66;
const FRAMES_PER_SECOND: f32 = 60.0;

/// Wand statistics (WAND-R03). Spells never change these; they only edit shot states.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct WandStats {
    pub shuffle: bool,
    /// Cards dealt per click ("Spells/Cast").
    pub spells_per_cast: u32,
    /// Base cast delay in frames; may be negative.
    pub cast_delay: i32,
    /// Base recharge time in frames; may be negative.
    pub recharge: i32,
    pub mana_max: f32,
    /// Mana regained per second.
    pub mana_charge_speed: f32,
    pub capacity: u32,
    /// Base spread in degrees; may be negative.
    pub spread: f32,
    /// Hidden multiplier on projectile speed.
    pub speed_multiplier: f32,
}

impl WandStats {
    pub fn validate(&self) -> Result<(), Error> {
        let bad = |message: String| Err(Error::Wand(message));
        if self.capacity == 0 || self.capacity > MAX_CAPACITY {
            return bad(format!(
                "capacity must be within 1..={MAX_CAPACITY}, found {}",
                self.capacity
            ));
        }
        if self.spells_per_cast == 0 || self.spells_per_cast > self.capacity {
            let (spc, cap) = (self.spells_per_cast, self.capacity);
            return bad(format!(
                "spells_per_cast must be within 1..=capacity ({cap}), found {spc}"
            ));
        }
        let non_negative = [
            ("mana_max", self.mana_max),
            ("mana_charge_speed", self.mana_charge_speed),
            ("speed_multiplier", self.speed_multiplier),
        ];
        for (name, value) in non_negative {
            if !value.is_finite() || value < 0.0 {
                return bad(format!(
                    "{name} must be a non-negative number, found {value}"
                ));
            }
        }
        if !self.spread.is_finite() {
            return bad(format!("spread must be a number, found {}", self.spread));
        }
        Ok(())
    }
}

/// A spell placed in a wand slot, with the uses it has left (`None` is unlimited).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Slot {
    pub spell: SpellId,
    pub uses: Option<u32>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Wand {
    stats: WandStats,
    slots: Vec<Option<Slot>>,
    always_cast: Vec<SpellId>,
    mana: f32,
    /// Frames until the next click is allowed.
    cooldown: u32,
    cycle: Cycle,
}

impl Wand {
    /// A wand holding `spells` (slot order; empty slots are `None`), full of mana, ready to cast.
    pub fn new(
        book: &SpellBook,
        stats: WandStats,
        spells: &[Option<SpellId>],
        always_cast: &[SpellId],
    ) -> Result<Wand, Error> {
        stats.validate()?;
        if spells.len() > stats.capacity as usize {
            let (n, cap) = (spells.len(), stats.capacity);
            return Err(Error::Wand(format!(
                "{n} slots given for a capacity of {cap}"
            )));
        }
        if always_cast.len() > MAX_ALWAYS_CAST {
            return Err(Error::Wand(format!(
                "at most {MAX_ALWAYS_CAST} always-cast spells"
            )));
        }
        for &id in spells.iter().flatten().chain(always_cast) {
            if !book.contains(id) {
                return Err(Error::Wand(format!(
                    "spell id {} is not in the spell book",
                    id.0
                )));
            }
        }
        let mut slots: Vec<Option<Slot>> = spells
            .iter()
            .map(|s| {
                s.map(|spell| Slot {
                    spell,
                    uses: book.get(spell).max_uses,
                })
            })
            .collect();
        slots.resize(stats.capacity as usize, None);
        let mut wand = Wand {
            mana: stats.mana_max,
            stats,
            slots,
            always_cast: always_cast.to_vec(),
            cooldown: 0,
            cycle: Cycle::default(),
        };
        wand.equip();
        Ok(wand)
    }

    pub fn stats(&self) -> &WandStats {
        &self.stats
    }

    pub fn slots(&self) -> &[Option<Slot>] {
        &self.slots
    }

    pub fn always_cast(&self) -> &[SpellId] {
        &self.always_cast
    }

    pub fn mana(&self) -> f32 {
        self.mana
    }

    pub fn set_mana(&mut self, mana: f32) {
        self.mana = mana.max(0.0);
    }

    /// Frames until the wand can be cast again (0 = ready).
    pub fn cooldown(&self) -> u32 {
        self.cooldown
    }

    pub fn is_ready(&self) -> bool {
        self.cooldown == 0
    }

    /// Spells still in the deck, top first.
    pub fn deck_spells(&self) -> Vec<SpellId> {
        self.cycle.deck.iter().map(|c| c.spell).collect()
    }

    /// Spells in the discard pile, oldest first.
    pub fn discarded_spells(&self) -> Vec<SpellId> {
        self.cycle.discarded.iter().map(|c| c.spell).collect()
    }

    /// Put the wand in hand again (WAND-R56): the deck is rebuilt from the slots, hand and discard
    /// are emptied, and the first click reorders the deck. A cooldown already running continues.
    pub fn equip(&mut self) {
        self.cycle.rebuild(&self.slots, self.stats.recharge);
    }

    /// Replace one slot (the wand editor); re-equips the wand.
    pub fn set_slot(&mut self, index: usize, slot: Option<Slot>) -> Result<(), Error> {
        let capacity = self.slots.len();
        let target = self.slots.get_mut(index).ok_or_else(|| {
            Error::Wand(format!("slot {index} does not exist (capacity {capacity})"))
        })?;
        *target = slot;
        self.equip();
        Ok(())
    }

    /// Swap two slots, uses travelling with their spells; re-equips the wand.
    pub fn swap_slots(&mut self, a: usize, b: usize) -> Result<(), Error> {
        let capacity = self.slots.len();
        if a >= capacity || b >= capacity {
            return Err(Error::Wand(format!(
                "slots {a} and {b} must be below {capacity}"
            )));
        }
        self.slots.swap(a, b);
        self.equip();
        Ok(())
    }

    /// Set the uses left of a slot (tests, world generation). Does nothing for an empty slot.
    pub fn set_uses(&mut self, index: usize, uses: Option<u32>) {
        if let Some(Some(slot)) = self.slots.get_mut(index) {
            slot.uses = uses;
        }
    }

    /// One click. Fails with [`Error::NotReady`] while a cast delay or recharge is running.
    pub fn cast(
        &mut self,
        book: &SpellBook,
        rng: &mut dyn crate::SpellRandom,
    ) -> Result<CastResult, Error> {
        if self.cooldown > 0 {
            return Err(Error::NotReady {
                remaining: self.cooldown,
            });
        }
        for &id in self
            .slots
            .iter()
            .flatten()
            .map(|s| &s.spell)
            .chain(&self.always_cast)
        {
            if !book.contains(id) {
                return Err(Error::Wand(format!(
                    "spell id {} is not in the spell book",
                    id.0
                )));
            }
        }
        let result = cast::click(self, book, rng);
        self.cooldown = result.ready_in;
        Ok(result)
    }

    /// Let `frames` frames pass: mana regenerates (WAND-R57) and the cooldown runs down. Call
    /// with 1 once per frame after the cast of that frame, so a click at frame `f` allows the next
    /// at `f + ready_in` (WAND-R54).
    pub fn advance(&mut self, frames: u32) {
        self.advance_scaled(frames, 1.0);
    }

    /// As [`Wand::advance`], with mana regenerating `mana_mul` times as fast (a potion of mana
    /// regeneration): the cooldown is not faster.
    pub fn advance_scaled(&mut self, frames: u32, mana_mul: f32) {
        let charge = self.stats.mana_charge_speed / FRAMES_PER_SECOND * mana_mul;
        for _ in 0..frames {
            self.cooldown = self.cooldown.saturating_sub(1);
            // Mana above the maximum (gained mid-click) is only capped at the next click.
            if self.mana < self.stats.mana_max {
                self.mana = (self.mana + charge).min(self.stats.mana_max);
            }
        }
    }
}
