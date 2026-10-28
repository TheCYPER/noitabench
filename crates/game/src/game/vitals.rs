//! Damage, statuses from contact, healing and death (`entities-damage.md` DAMAGE-R01..R19,
//! HAZ-R01..R03).
//!
//! Direct hits, blasts and melee strikes call [`Game::hurt`]. The slow sources (a material the
//! entity stands in, burning, poison, drowning) are worked out once per frame by
//! [`environment`] for every living thing and applied through the same `hurt`, so multipliers,
//! invincibility and death are handled in one place.

use cogbench_sim::{Aabb, Value};

use crate::entity::{DamageSource, Target, Vitals};
use crate::status::Status;

use super::environment::{environment, EnvSpec, EnvTick};
use super::{player_motion, Game};

const DISPLAY: f32 = 25.0;

/// Display value of an internal damage or health number.
pub(crate) fn shown(internal: f32) -> f64 {
    f64::from(internal * DISPLAY)
}

/// What one hit did to a creature's vitals.
struct Outcome {
    dealt: f32,
    hp_after: f32,
    died: bool,
    /// Damage to put in a `damage` event now (`None` while slow damage is still being summed).
    log_amount: Option<f32>,
}

/// Subtract `amount * mult` from a creature unless it is dead or invincible. Slow sources (fire,
/// contact) are summed into one event per `interval` frames, or at death.
fn take_damage(
    vit: &mut Vitals,
    mult: f32,
    amount: f32,
    source: DamageSource,
    frame: u64,
    interval: u64,
) -> Option<Outcome> {
    let dealt = amount * mult;
    if vit.dead || vit.invincible > 0 || dealt <= 0.0 {
        return None;
    }
    // Secret potions: nothing hurts an invulnerable creature, fire does not hurt a fireproof one.
    let protected = vit.statuses.has(Status::Invulnerable)
        || (source == DamageSource::Fire && vit.statuses.has(Status::Fireproof));
    if protected {
        return None;
    }
    vit.hp -= dealt;
    let died = vit.hp <= 0.0;
    if died {
        vit.hp = 0.0;
        vit.dead = true;
    }
    let slow = matches!(source, DamageSource::Fire | DamageSource::Contact);
    let mut log_amount = Some(dealt);
    if slow {
        vit.logged_damage += dealt;
        let flush = died || frame.saturating_sub(vit.logged_since) >= interval;
        log_amount = flush.then_some(vit.logged_damage);
        if flush {
            vit.logged_damage = 0.0;
            vit.logged_since = frame;
        }
    }
    Some(Outcome {
        dealt,
        hp_after: vit.hp,
        died,
        log_amount,
    })
}

impl Game {
    /// Center cell of a target, for event positions.
    pub(crate) fn target_center(&self, t: Target) -> (i32, i32) {
        let body = match t {
            Target::Player => self.state.player.as_ref().map(|p| &p.body),
            Target::Enemy(id) => self.enemy_index(id).map(|i| &self.state.enemies[i].body),
            Target::Item(id) => self.item_index(id).map(|i| &self.state.items[i].body),
        };
        body.map_or((0, 0), |b| {
            let (cx, cy) = b.center();
            (cx.floor() as i32, cy.floor() as i32)
        })
    }

    pub(crate) fn target_label(&self, t: Target) -> (String, u32) {
        match t {
            Target::Player => (
                "player".into(),
                self.state.player.as_ref().map_or(0, |p| p.id),
            ),
            Target::Enemy(id) => (
                self.enemy_index(id)
                    .map_or_else(String::new, |i| self.state.enemies[i].kind.clone()),
                id,
            ),
            Target::Item(id) => (
                self.item_index(id)
                    .map_or_else(String::new, |i| self.state.items[i].kind.label()),
                id,
            ),
        }
    }

    /// Hurt something. The source decides the multiplier of the target (explosions against the
    /// player, fire against Stendari). Returns the damage that went through.
    pub(crate) fn hurt(&mut self, target: Target, amount: f32, source: DamageSource) -> f32 {
        if amount <= 0.0 || !amount.is_finite() {
            return 0.0;
        }
        match target {
            Target::Item(id) => self.hurt_item(id, amount),
            Target::Player | Target::Enemy(_) => self.hurt_creature(target, amount, source),
        }
    }

    /// Wear down a barrel or bomb; a broken one is removed by `process_breaks`.
    fn hurt_item(&mut self, id: u32, amount: f32) -> f32 {
        let Some(item) = self.state.items.iter_mut().find(|x| x.id == id) else {
            return 0.0;
        };
        if item.hp_max <= 0.0 || item.dead {
            return 0.0;
        }
        item.hp -= amount;
        if item.hp <= 0.0 {
            item.dead = true;
        }
        amount
    }

    fn hurt_creature(&mut self, target: Target, amount: f32, source: DamageSource) -> f32 {
        let defs = self.defs.clone();
        let (frame, interval) = (self.world.frame(), defs.sim.event_damage_interval);
        let (label, id) = self.target_label(target);
        let (cx, cy) = self.target_center(target);
        let outcome = match target {
            Target::Player => self.state.player.as_mut().and_then(|p| {
                let mult = defs.player.damage_mult.get(source.key()).copied();
                take_damage(
                    &mut p.vitals,
                    mult.unwrap_or(1.0),
                    amount,
                    source,
                    frame,
                    interval,
                )
            }),
            Target::Enemy(eid) => self
                .state
                .enemies
                .iter_mut()
                .find(|e| e.id == eid)
                .and_then(|e| {
                    let mult = defs
                        .enemies
                        .get(&e.kind)
                        .and_then(|d| d.damage_mult.get(source.key()).copied());
                    take_damage(
                        &mut e.vitals,
                        mult.unwrap_or(1.0),
                        amount,
                        source,
                        frame,
                        interval,
                    )
                }),
            Target::Item(_) => None,
        };
        let Some(o) = outcome else {
            return 0.0;
        };
        if let Some(logged) = o.log_amount {
            self.world.log_event(
                "damage",
                vec![
                    ("target", Value::Str(label.clone())),
                    ("id", Value::Int(i64::from(id))),
                    ("amount", Value::Float(shown(logged))),
                    ("source", Value::Str(source.key().into())),
                    ("hp", Value::Float(shown(o.hp_after))),
                    ("x", Value::Int(i64::from(cx))),
                    ("y", Value::Int(i64::from(cy))),
                ],
            );
        }
        if o.died {
            self.world.log_event(
                "death",
                vec![
                    ("target", Value::Str(label)),
                    ("id", Value::Int(i64::from(id))),
                    ("source", Value::Str(source.key().into())),
                    ("x", Value::Int(i64::from(cx))),
                    ("y", Value::Int(i64::from(cy))),
                ],
            );
        }
        o.dealt
    }

    pub(crate) fn log_status(&mut self, target: Target, status: Status, active: bool) {
        let (label, id) = self.target_label(target);
        self.world.log_event(
            "status",
            vec![
                ("target", Value::Str(label)),
                ("id", Value::Int(i64::from(id))),
                ("status", Value::Str(status.key().into())),
                ("active", Value::Int(i64::from(active))),
            ],
        );
    }

    /// Put a status on a target (a spell hit, a splash). Wet puts fire out.
    pub(crate) fn apply_status(&mut self, target: Target, status: Status, frames: u32) {
        let (started, cleared_fire) = {
            let vit = match target {
                Target::Player => self.state.player.as_mut().map(|p| &mut p.vitals),
                Target::Enemy(id) => self
                    .state
                    .enemies
                    .iter_mut()
                    .find(|e| e.id == id)
                    .map(|e| &mut e.vitals),
                Target::Item(_) => None,
            };
            let Some(vit) = vit else {
                return;
            };
            if vit.dead || (status == Status::OnFire && vit.statuses.has(Status::Fireproof)) {
                return;
            }
            let cleared = status == Status::Wet && vit.statuses.clear(Status::OnFire);
            (vit.statuses.apply(status, frames), cleared)
        };
        if started {
            self.log_status(target, status, true);
        }
        if cleared_fire {
            self.log_status(target, Status::OnFire, false);
        }
    }

    /// End of frame: the environment's effect on the player and every enemy, then wand mana and
    /// the removal of the dead.
    pub(crate) fn settle(&mut self) {
        self.settle_player();
        self.settle_enemies();
        let sd = self.defs.statuses;
        if let Some(p) = self.state.player.as_mut() {
            let regen = p.vitals.statuses.has(Status::ManaRegen);
            let mana_mul = if regen { sd.mana_regen.mana_mul } else { 1.0 };
            for w in &mut p.wands {
                w.wand.advance_scaled(1, mana_mul);
            }
        }
        self.state.enemies.retain(|e| !e.vitals.dead);
    }

    fn settle_player(&mut self) {
        let defs = self.defs.clone();
        let frame = self.world.frame();
        let Some(p) = self.state.player.as_mut() else {
            return;
        };
        if p.vitals.dead {
            return;
        }
        p.vitals.invincible = p.vitals.invincible.saturating_sub(1);
        let (cx, cy) = p.body.cell();
        let hb = &defs.player.hitboxes[0];
        let bbox = Aabb::new(cx + hb.dx, cy + hb.dy, hb.w, hb.h);
        let empty = Default::default();
        let id = u64::from(p.id);
        let spec = EnvSpec {
            bbox,
            ignite_percent: 100,
            contact_table: &empty,
            wet_damage_per_s: 0.0,
            ignite_roll: self.ai.below(100, frame, id, 10),
            flame_roll: self.ai.below(100, frame, id, 11),
            flame_pos: self.ai.below(1000, frame, id, 12),
        };
        let tick = environment(&self.world, &defs, &mut p.vitals, &spec);
        let underwater = player_motion::head_underwater(&self.world, p, &defs.player);
        let mut drown = 0.0;
        if underwater {
            if p.breath > 0 {
                p.breath -= 1;
            } else {
                drown = defs.player.drown_damage_per_frame;
            }
        } else {
            p.breath = (p.breath + 3).min(defs.player.air_frames);
        }
        self.apply_tick(Target::Player, tick);
        self.hurt(Target::Player, drown, DamageSource::Contact);
    }

    fn settle_enemies(&mut self) {
        let defs = self.defs.clone();
        let frame = self.world.frame();
        let range = defs.sim.active_range;
        let anchor = self.state.player.as_ref().map(|p| p.body.cell());
        for i in 0..self.state.enemies.len() {
            let e = &mut self.state.enemies[i];
            let (ex, ey) = e.body.cell();
            if e.vitals.dead
                || anchor.is_some_and(|(px, py)| (ex - px).abs() > range || (ey - py).abs() > range)
            {
                continue;
            }
            let Some(def) = defs.enemies.get(&e.kind) else {
                continue;
            };
            let (x0, y0, x1, y1) = def.hitboxes.iter().fold(
                (i32::MAX, i32::MAX, i32::MIN, i32::MIN),
                |(a, b, c, d), h| {
                    (
                        a.min(h.dx),
                        b.min(h.dy),
                        c.max(h.dx + h.w),
                        d.max(h.dy + h.h),
                    )
                },
            );
            let bbox = Aabb::new(ex + x0, ey + y0, x1 - x0, y1 - y0);
            let id = u64::from(e.id);
            let spec = EnvSpec {
                bbox,
                ignite_percent: def.ignite_percent,
                contact_table: &def.contact_damage,
                wet_damage_per_s: def.wet_damage_per_s,
                ignite_roll: self.ai.below(100, frame, id, 10),
                flame_roll: self.ai.below(100, frame, id, 11),
                flame_pos: self.ai.below(1000, frame, id, 12),
            };
            let eid = e.id;
            let tick = environment(&self.world, &defs, &mut e.vitals, &spec);
            self.apply_tick(Target::Enemy(eid), tick);
        }
    }

    fn apply_tick(&mut self, target: Target, tick: EnvTick) {
        for s in tick.started {
            self.log_status(target, s, true);
        }
        for s in tick.ended {
            self.log_status(target, s, false);
        }
        for (amount, source) in tick.damage {
            self.hurt(target, amount, source);
        }
        if let Some((x, y)) = tick.flame {
            if self.world.grid().get(x, y).mat == 0 {
                let fire = self.world.content().fire;
                self.world.set_cell(x, y, fire, false);
            }
        }
    }
}
