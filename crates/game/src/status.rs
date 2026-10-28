//! The statuses (v1-scope section 4): wet, oiled, on fire, poisoned, haste, drunk and
//! regeneration, and the seven that only the secret potions give (invulnerable, mana regen,
//! critical boost, berserk, levitation, invisible, fireproof). They come from contact with
//! materials, from drinking and from spells.

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Wet,
    Oiled,
    OnFire,
    Poisoned,
    Haste,
    Drunk,
    Regeneration,
    /// Secret potion: no damage of any kind.
    Invulnerable,
    /// Secret potion: held wands regain mana several times faster.
    ManaRegen,
    /// Secret potion: the player's projectiles crit more often.
    CritBoost,
    /// Secret potion: the player's projectile and explosion damage is multiplied.
    Berserk,
    /// Secret potion: the levitation meter does not drain.
    Levitation,
    /// Secret potion: enemies neither notice nor target the player.
    Invisible,
    /// Secret potion: cannot be set on fire, fire and burning do no damage.
    Fireproof,
}

/// How many statuses there are.
pub const STATUS_COUNT: usize = 14;

impl Status {
    pub const ALL: [Status; STATUS_COUNT] = [
        Status::Wet,
        Status::Oiled,
        Status::OnFire,
        Status::Poisoned,
        Status::Haste,
        Status::Drunk,
        Status::Regeneration,
        Status::Invulnerable,
        Status::ManaRegen,
        Status::CritBoost,
        Status::Berserk,
        Status::Levitation,
        Status::Invisible,
        Status::Fireproof,
    ];

    pub const fn index(self) -> usize {
        match self {
            Status::Wet => 0,
            Status::Oiled => 1,
            Status::OnFire => 2,
            Status::Poisoned => 3,
            Status::Haste => 4,
            Status::Drunk => 5,
            Status::Regeneration => 6,
            Status::Invulnerable => 7,
            Status::ManaRegen => 8,
            Status::CritBoost => 9,
            Status::Berserk => 10,
            Status::Levitation => 11,
            Status::Invisible => 12,
            Status::Fireproof => 13,
        }
    }

    pub const fn key(self) -> &'static str {
        match self {
            Status::Wet => "wet",
            Status::Oiled => "oiled",
            Status::OnFire => "on_fire",
            Status::Poisoned => "poisoned",
            Status::Haste => "haste",
            Status::Drunk => "drunk",
            Status::Regeneration => "regeneration",
            Status::Invulnerable => "invulnerable",
            Status::ManaRegen => "mana_regen",
            Status::CritBoost => "crit_boost",
            Status::Berserk => "berserk",
            Status::Levitation => "levitation",
            Status::Invisible => "invisible",
            Status::Fireproof => "fireproof",
        }
    }

    pub fn parse(key: &str) -> Option<Status> {
        Status::ALL.into_iter().find(|s| s.key() == key)
    }
}

/// Frames left of every status (0 = not active).
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Statuses {
    frames: [u32; STATUS_COUNT],
}

impl Statuses {
    pub fn has(&self, status: Status) -> bool {
        self.frames[status.index()] > 0
    }

    pub fn frames_left(&self, status: Status) -> u32 {
        self.frames[status.index()]
    }

    /// Start or extend a status: it lasts at least `frames` more frames. Returns whether it was
    /// not active before.
    pub fn apply(&mut self, status: Status, frames: u32) -> bool {
        let slot = &mut self.frames[status.index()];
        let fresh = *slot == 0 && frames > 0;
        *slot = (*slot).max(frames);
        fresh
    }

    /// Add `frames` to the time left (drinking: every cell adds some).
    pub fn extend(&mut self, status: Status, frames: u32) -> bool {
        let slot = &mut self.frames[status.index()];
        let fresh = *slot == 0 && frames > 0;
        *slot = slot.saturating_add(frames);
        fresh
    }

    /// Never more than `max` frames left.
    pub fn cap(&mut self, status: Status, max: u32) {
        let slot = &mut self.frames[status.index()];
        *slot = (*slot).min(max);
    }

    /// Whether the status was active (it is gone now).
    pub fn clear(&mut self, status: Status) -> bool {
        std::mem::take(&mut self.frames[status.index()]) > 0
    }

    /// One frame passes; returns the statuses that ran out.
    pub fn tick(&mut self) -> Vec<Status> {
        let mut ended = Vec::new();
        for s in Status::ALL {
            let slot = &mut self.frames[s.index()];
            if *slot > 0 {
                *slot -= 1;
                if *slot == 0 {
                    ended.push(s);
                }
            }
        }
        ended
    }

    /// Active statuses with their frames left, in `Status::ALL` order.
    pub fn active(&self) -> Vec<(Status, u32)> {
        Status::ALL
            .into_iter()
            .filter(|s| self.has(*s))
            .map(|s| (s, self.frames_left(s)))
            .collect()
    }
}
