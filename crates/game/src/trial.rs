//! The wand practice range: casting a wand outside the world.
//!
//! [`run_trial`] holds the fire key down for a number of frames on a wand that stands nowhere,
//! exactly as the game does (a click whenever the wand is ready, [`Wand::advance`] once per
//! frame afterwards), and reports what each click played, what it cost and what it would do to
//! a *dummy*: a target that never moves, never dies, is hit by every projectile and stands in
//! the reach of every blast. Nothing is simulated beyond the casting engine, so the numbers are
//! the wand's own; spread, bounces, flight time, material sprays, trails and statuses are not
//! counted.
//!
//! Damage of a projectile = its direct hit (with the expected gain from its critical chance)
//! plus its blast if it has one that goes off; a trigger's payload counts too, as if released.
//! The result is read-only: no world, no player, nothing to snapshot.

use cogbench_sim::MaterialSet;

use crate::defs::EntityDefs;
use crate::error::Error;
use crate::projectile::{shot_from_spawn, Shot, CRIT_MULTIPLIER};
use crate::rng::SpellRng;
use crate::spell::{SpellBook, SpellId};
use crate::wand::{SkipReason, Skipped, Wand, WandStats};

/// Longest practice run, in frames (two minutes).
pub const MAX_TRIAL_FRAMES: u32 = 7_200;

/// Largest cast delay or recharge a practice wand may have, in either direction, in frames. The
/// numbers come from whoever asks (the agent may make a wand up), and the casting engine adds
/// the spells' own deltas to them with plain integer sums: this keeps those sums far from
/// `i32::MAX`, where a debug build would panic and a release build would wrap around.
pub const MAX_WAND_FRAMES: u32 = 1_000_000;

/// A spell card placed in a slot, with the uses it has left.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TrialSlot {
    pub spell: SpellId,
    /// `None` takes the spell's own limit. A number above the limit is cut to it; a spell without
    /// a limit stays unlimited.
    pub uses: Option<u32>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TrialSpec {
    pub stats: WandStats,
    /// One entry per slot, empty slots as `None`; at most `stats.capacity` entries.
    pub slots: Vec<Option<TrialSlot>>,
    pub always_cast: Vec<SpellId>,
    pub frames: u32,
    /// Seed of the shuffle and spread streams (only a shuffle wand's order depends on it).
    pub seed: u64,
    /// How many clicks to keep in [`TrialReport::casts`] (the first ones); totals count all.
    pub keep_casts: usize,
}

/// One click of the wand.
#[derive(Clone, Debug, PartialEq)]
pub struct TrialCast {
    pub frame: u32,
    /// Cards played, in play order (always-casts first).
    pub played: Vec<SpellId>,
    pub skipped: Vec<Skipped>,
    /// Projectiles of the click itself (not counting what triggers release).
    pub projectiles: u32,
    /// Projectiles that triggers and timers of this click carry.
    pub payload_projectiles: u32,
    pub mana_before: f32,
    pub mana_after: f32,
    pub cast_delay: u32,
    /// Frames of recharge if one started at the end of this click.
    pub recharge: Option<u32>,
    pub ready_in: u32,
    pub wrapped: bool,
    /// Damage to the dummy, internal units (the game shows internal x 25).
    pub damage: f32,
}

/// How often a card was drawn and passed over.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SkipTally {
    pub spell: SpellId,
    pub reason: SkipReason,
    pub times: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TrialReport {
    pub frames: u32,
    /// The first `keep_casts` clicks.
    pub casts: Vec<TrialCast>,
    pub total_casts: u32,
    /// Clicks that made at least one projectile.
    pub shooting_casts: u32,
    pub projectiles: u32,
    pub payload_projectiles: u32,
    /// Damage to the dummy over the whole run, internal units.
    pub damage: f32,
    /// Recharges that started.
    pub recharges: u32,
    pub skips: Vec<SkipTally>,
    pub mana_start: f32,
    pub mana_end: f32,
    /// The lowest mana at the end of any frame.
    pub mana_min: f32,
    /// Mana paid by all clicks together (negative when they gained more than they paid).
    pub mana_spent: f32,
    /// Slots whose spell ran out of uses.
    pub used_up: Vec<usize>,
}

/// What a shot and everything it releases would do to the dummy.
#[derive(Default)]
struct Tally {
    damage: f32,
    payload_shots: u32,
}

fn tally(shot: &Shot, into: &mut Tally) {
    let d = &shot.def;
    let crit = (d.crit_chance / 100.0).clamp(0.0, 1.0);
    into.damage += d.hit_damage * (1.0 + crit * (CRIT_MULTIPLIER - 1.0));
    if let Some(e) = &d.explosion {
        if e.on_death || e.on_lifetime_out {
            into.damage += e.damage;
        }
    }
    if let Some(trigger) = &shot.trigger {
        for payload in &trigger.payload {
            into.payload_shots += 1;
            tally(payload, into);
        }
    }
}

fn build_wand(book: &SpellBook, spec: &TrialSpec) -> Result<Wand, Error> {
    let spells: Vec<Option<SpellId>> = spec.slots.iter().map(|s| s.map(|s| s.spell)).collect();
    let mut wand = Wand::new(book, spec.stats.clone(), &spells, &spec.always_cast)?;
    for (i, slot) in spec.slots.iter().enumerate() {
        let Some(slot) = slot else { continue };
        let limit = book.get(slot.spell).max_uses;
        let uses = match (slot.uses, limit) {
            (Some(n), Some(max)) => Some(n.min(max)),
            (_, limit) => limit,
        };
        wand.set_uses(i, uses);
    }
    Ok(wand)
}

fn count_skips(skips: &mut Vec<SkipTally>, cast_skips: &[Skipped]) {
    for s in cast_skips {
        match skips
            .iter_mut()
            .find(|t| t.spell == s.spell && t.reason == s.reason)
        {
            Some(t) => t.times += 1,
            None => skips.push(SkipTally {
                spell: s.spell,
                reason: s.reason,
                times: 1,
            }),
        }
    }
}

/// Hold the fire key for `spec.frames` frames on the wand described by `spec`.
pub fn run_trial(
    book: &SpellBook,
    mats: &MaterialSet,
    defs: &EntityDefs,
    spec: &TrialSpec,
) -> Result<TrialReport, Error> {
    if spec.frames == 0 || spec.frames > MAX_TRIAL_FRAMES {
        return Err(Error::arg(format!(
            "frames must be within 1..={MAX_TRIAL_FRAMES}, found {}",
            spec.frames
        )));
    }
    for (name, value) in [
        ("cast_delay", spec.stats.cast_delay),
        ("recharge", spec.stats.recharge),
    ] {
        if value.unsigned_abs() > MAX_WAND_FRAMES {
            return Err(Error::arg(format!(
                "{name} must be within -{MAX_WAND_FRAMES}..={MAX_WAND_FRAMES} frames, found {value}"
            )));
        }
    }
    let mut wand = build_wand(book, spec)?;
    let mut rng = SpellRng::new(spec.seed);
    let mana_start = wand.mana();
    let mut report = TrialReport {
        frames: spec.frames,
        casts: Vec::new(),
        total_casts: 0,
        shooting_casts: 0,
        projectiles: 0,
        payload_projectiles: 0,
        damage: 0.0,
        recharges: 0,
        skips: Vec::new(),
        mana_start,
        mana_end: mana_start,
        mana_min: mana_start,
        mana_spent: 0.0,
        used_up: Vec::new(),
    };
    for frame in 0..spec.frames {
        if wand.is_ready() {
            let result = wand.cast(book, &mut rng)?;
            let mut hits = Tally::default();
            for spawn in &result.projectiles {
                tally(&shot_from_spawn(book, mats, defs, spawn)?, &mut hits);
            }
            let cast = TrialCast {
                frame,
                played: result.played.clone(),
                skipped: result.skipped.clone(),
                projectiles: result.projectiles.len() as u32,
                payload_projectiles: hits.payload_shots,
                mana_before: result.mana_before,
                mana_after: result.mana_after,
                cast_delay: result.cast_delay,
                recharge: result.recharge,
                ready_in: result.ready_in,
                wrapped: result.wrapped,
                damage: hits.damage,
            };
            report.total_casts += 1;
            report.shooting_casts += u32::from(cast.projectiles > 0);
            report.projectiles += cast.projectiles;
            report.payload_projectiles += cast.payload_projectiles;
            report.damage += cast.damage;
            report.recharges += u32::from(cast.recharge.is_some());
            report.mana_spent += result.mana_spent;
            count_skips(&mut report.skips, &cast.skipped);
            if report.casts.len() < spec.keep_casts {
                report.casts.push(cast);
            }
        }
        wand.advance(1);
        report.mana_min = report.mana_min.min(wand.mana());
    }
    report.mana_end = wand.mana();
    report.used_up = wand
        .slots()
        .iter()
        .enumerate()
        .filter(|(_, s)| s.is_some_and(|s| s.uses == Some(0)))
        .map(|(i, _)| i)
        .collect();
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frames_are_bounded() {
        let book = SpellBook::embedded().unwrap();
        let content = cogbench_sim::Content::embedded().unwrap();
        let defs = EntityDefs::embedded().unwrap();
        let spec = TrialSpec {
            stats: WandStats {
                shuffle: false,
                spells_per_cast: 1,
                cast_delay: 0,
                recharge: 0,
                mana_max: 100.0,
                mana_charge_speed: 10.0,
                capacity: 2,
                spread: 0.0,
                speed_multiplier: 1.0,
            },
            slots: Vec::new(),
            always_cast: Vec::new(),
            frames: 0,
            seed: 0,
            keep_casts: 4,
        };
        assert!(run_trial(&book, &content.mats, &defs, &spec).is_err());
        let spec = TrialSpec {
            frames: MAX_TRIAL_FRAMES + 1,
            ..spec
        };
        assert!(run_trial(&book, &content.mats, &defs, &spec).is_err());
    }
}
