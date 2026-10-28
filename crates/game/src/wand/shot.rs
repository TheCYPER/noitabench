//! Shot states and the result of one cast.
//!
//! A *shot state* collects what the modifiers did (WAND-R30); every projectile of the state gets
//! the full set, whatever the order of the cards. A trigger's payload is a separate shot state that
//! starts from defaults (WAND-R31).

use crate::spell::{Effect, Spell, SpellId, TrailSpec, TriggerKind};

use super::WandStats;

/// Upper bound of the running speed multiplier (WAND-R33, SPELL-R09).
const SPEED_MUL_MAX: f32 = 20.0;

/// The accumulators of a shot state, frozen at the end of the click.
#[derive(Clone, Debug, PartialEq)]
pub struct ShotParams {
    /// Cast delay in frames: for the root shot the wand's base plus every card played in it; the
    /// raw sum, which can be below 1 (the wand clamps it, WAND-R53).
    pub cast_delay: i32,
    /// Spread in degrees added to the projectile's own (wand spread only in the root shot).
    pub spread: f32,
    pub speed_mul: f32,
    /// Added to the direct-hit damage of every projectile (internal units).
    pub damage: f32,
    pub explosion_damage: f32,
    pub explosion_radius: f32,
    /// Bonus to the max durability of the explosion of every projectile of this shot state: the
    /// largest `explosion_durability` among the modifiers played in it (copies do not stack).
    pub explosion_durability: u32,
    /// Critical hit chance in percentage points.
    pub crit_chance: f32,
    pub bounces: i32,
    pub trail: Vec<TrailSpec>,
    pub effects: Vec<Effect>,
    /// Modifier cards played in this shot state, in play order.
    pub modifiers: Vec<SpellId>,
}

impl ShotParams {
    /// The root shot of a click: the wand's own cast delay, spread and speed (WAND-R12, R31).
    pub(super) fn root(stats: &WandStats) -> Self {
        ShotParams {
            cast_delay: stats.cast_delay,
            spread: stats.spread,
            speed_mul: stats.speed_multiplier,
            ..ShotParams::payload()
        }
    }

    /// A trigger payload: all defaults, nothing of the wand leaks in (WAND-R31).
    pub(super) fn payload() -> Self {
        ShotParams {
            cast_delay: 0,
            spread: 0.0,
            speed_mul: 1.0,
            damage: 0.0,
            explosion_damage: 0.0,
            explosion_radius: 0.0,
            explosion_durability: 0,
            crit_chance: 0.0,
            bounces: 0,
            trail: Vec::new(),
            effects: Vec::new(),
            modifiers: Vec::new(),
        }
    }

    /// Apply the shot-state part of a played card.
    pub(super) fn apply(&mut self, id: SpellId, spell: &Spell) {
        let d = &spell.shot;
        self.cast_delay += spell.cast_delay;
        self.spread += d.spread;
        if d.speed_mul != 1.0 {
            self.speed_mul = (self.speed_mul * d.speed_mul).clamp(0.0, SPEED_MUL_MAX);
        }
        self.damage += d.damage;
        self.explosion_damage += d.explosion_damage;
        self.explosion_radius += d.explosion_radius;
        self.explosion_durability = self.explosion_durability.max(d.explosion_durability);
        self.crit_chance += d.crit_chance;
        self.bounces += d.bounces;
        for trail in &d.trail {
            match self.trail.iter_mut().find(|t| t.material == trail.material) {
                Some(existing) => existing.amount += trail.amount,
                None => self.trail.push(trail.clone()),
            }
        }
        for effect in &d.effects {
            if !self.effects.contains(effect) {
                self.effects.push(*effect);
            }
        }
        if spell.kind == crate::spell::SpellType::Modifier {
            self.modifiers.push(id);
        }
    }
}

/// A projectile (or material blob, or static effect) the cast asks the world to create.
#[derive(Clone, Debug, PartialEq)]
pub struct ProjectileSpawn {
    pub spell: SpellId,
    /// The final accumulators of the shot state this projectile belongs to.
    pub shot: ShotParams,
    /// Total spread in degrees: the shot's plus the projectile's own, never below 0.
    pub spread_degrees: f32,
    /// This projectile's deviation from the aim, uniform in `-spread_degrees..=spread_degrees`;
    /// 0 when there is no spread.
    pub angle_offset_degrees: f32,
    pub trigger: Option<Trigger>,
}

/// A payload carried by a trigger/timer projectile; the cards were drawn and paid at cast time.
#[derive(Clone, Debug, PartialEq)]
pub struct Trigger {
    pub kind: TriggerKind,
    pub timer_frames: Option<u32>,
    /// Empty when no card could be drawn for it (WAND-R44).
    pub payload: Vec<ProjectileSpawn>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SkipReason {
    NotEnoughMana,
    NoUsesLeft,
}

/// A card that was drawn but not played (WAND-R20); it cost nothing.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Skipped {
    pub spell: SpellId,
    pub reason: SkipReason,
}

/// Everything one click produced.
#[derive(Clone, Debug, PartialEq)]
pub struct CastResult {
    /// Projectiles of the root shot, in spawn order.
    pub projectiles: Vec<ProjectileSpawn>,
    /// The root shot state after all draws (also when it holds no projectile).
    pub root: ShotParams,
    /// Cards played this click, in play order (always-casts first).
    pub played: Vec<SpellId>,
    pub skipped: Vec<Skipped>,
    /// Wand mana at click start (after the cap) and at the end; `mana_spent` is the difference
    /// and is negative when the click gained mana.
    pub mana_before: f32,
    pub mana_after: f32,
    pub mana_spent: f32,
    /// Effective cast delay in frames: at least 1; exactly 1 when the root shot has no projectile.
    pub cast_delay: u32,
    /// Frames of recharge if one started at the end of this click.
    pub recharge: Option<u32>,
    /// Frames until the wand can be cast again: the longer of cast delay and recharge.
    pub ready_in: u32,
    /// A spell's draw met an empty deck and wrapped it: the discard pile was dealt back in (it may
    /// have been empty too) and a recharge will start (WAND-R23).
    pub wrapped: bool,
    /// Sum of the recoil of all cards played.
    pub recoil: f32,
}

/// A shot state while the cards are still being dealt.
pub(super) struct ShotState {
    pub params: ShotParams,
    pub nodes: Vec<Node>,
}

impl ShotState {
    pub fn new(params: ShotParams) -> Self {
        ShotState {
            params,
            nodes: Vec::new(),
        }
    }
}

pub(super) struct Node {
    pub spell: SpellId,
    pub payload: Option<PendingPayload>,
}

pub(super) struct PendingPayload {
    pub kind: TriggerKind,
    pub timer_frames: Option<u32>,
    pub shot: ShotState,
}
