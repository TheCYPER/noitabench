//! Projectiles in flight (tick-design step 5, `spells.md` SPELL-R23..R30): gravity and air
//! friction, a 4-connected path through the cells each frame (so nothing slips between two
//! cells that touch at a corner, v1-scope section 5a), hits on terrain and creatures, bounces,
//! blasts, trails and trigger payloads.

use cogbench_sim::{Kind, KindMask, QueryMask, Value};

use crate::entity::{DamageSource, Owner, Target};
use crate::physics::{contains, supercover, unit, FPS};
use crate::projectile::{Projectile, CRIT_MULTIPLIER, TERMINAL_SPEED};

use super::blast::Victim;
use super::Game;

/// Per-frame factor of air friction: `v -= 0.016666567 * v * friction` (SPELL-R24).
const FRICTION_PER_FRAME: f32 = 0.016_666_567;
/// Longest path of one frame, in cells.
const MAX_PATH: usize = 96;

/// What happened where a projectile met terrain.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Terrain {
    Dead,
    Bounced,
    Passed,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum End {
    Hit,
    Lifetime,
}

/// Can a projectile of this owner hurt this target?
fn may_hit(owner: Owner, target: Target) -> bool {
    !matches!(
        (owner, target),
        (Owner::Player, Target::Player) | (Owner::Enemy(_), Target::Enemy(_))
    )
}

impl Game {
    /// Move every projectile one frame. New projectiles made on the way (payloads) start flying
    /// next frame.
    pub(crate) fn update_projectiles(&mut self) {
        if self.state.projectiles.is_empty() {
            return;
        }
        let flying = std::mem::take(&mut self.state.projectiles);
        self.flying = flying.len();
        let victims = self.victims();
        let mut alive = Vec::with_capacity(flying.len());
        for mut p in flying {
            if self.step_projectile(&mut p, &victims) {
                alive.push(p);
            }
        }
        self.flying = 0;
        alive.append(&mut self.state.projectiles);
        self.state.projectiles = alive;
    }

    /// One frame of one projectile; `false` when it is gone.
    fn step_projectile(&mut self, p: &mut Projectile, victims: &[Victim]) -> bool {
        p.age += 1;
        p.life -= 1;
        if let Some(t) = p.timer_left.as_mut() {
            *t = t.saturating_sub(1);
            if *t == 0 {
                p.timer_left = None;
                self.release(p, (p.x, p.y));
            }
        }
        p.vy += p.def.gravity / FPS;
        let keep = 1.0 - FRICTION_PER_FRAME * p.def.air_friction;
        p.vx *= keep;
        p.vy *= keep;
        let speed = p.speed();
        if speed > TERMINAL_SPEED {
            p.vx *= TERMINAL_SPEED / speed;
            p.vy *= TERMINAL_SPEED / speed;
        }
        if p.def
            .die_on_low_velocity
            .is_some_and(|v| p.age > 1 && p.speed() < v)
        {
            return self.expire(p);
        }
        if self.fly(p, victims) {
            return false;
        }
        self.leave_trail(p);
        if p.life <= 0 {
            return self.expire(p);
        }
        true
    }

    /// Lifetime ran out (or the projectile slowed to a stop): timers still go off, then it dies.
    fn expire(&mut self, p: &mut Projectile) -> bool {
        let timer = p
            .trigger
            .as_ref()
            .is_some_and(|t| t.kind == crate::spell::TriggerKind::Timer);
        if timer {
            self.release(p, (p.x, p.y));
        }
        self.finish(p, (p.x, p.y), End::Lifetime);
        false
    }

    /// Walk the path of this frame. Returns `true` when the projectile died on it.
    fn fly(&mut self, p: &mut Projectile, victims: &[Victim]) -> bool {
        let (x0, y0) = (p.x, p.y);
        let (x1, y1) = (x0 + p.vx / FPS, y0 + p.vy / FPS);
        let path = supercover(x0, y0, x1, y1, MAX_PATH);
        let skip = usize::from(p.age > 1);
        let mut kinds = KindMask::SURFACES;
        if p.def.die_on_liquid {
            kinds = kinds.union(KindMask::of(Kind::Liquid));
        }
        let mask = QueryMask::new(kinds);
        let mut last_free = (skip == 1).then(|| path[0]);
        for &(cx, cy) in &path[skip..] {
            if self.world.blocked_at(cx, cy, mask) {
                match self.hit_terrain(p, (cx, cy), last_free, (x0, y0)) {
                    Terrain::Dead => return true,
                    Terrain::Bounced => return false,
                    Terrain::Passed => {}
                }
            }
            let found = victims.iter().find_map(|v| {
                let box_hit = v.boxes.iter().find(|(b, _)| contains(*b, cx, cy))?;
                (may_hit(p.owner, v.target) && self.target_exists(v.target))
                    .then_some((v.target, box_hit.1, v.mass))
            });
            if let Some((target, mult, mass)) = found {
                if self.hit_creature(p, target, mult, mass, (cx, cy)) {
                    return true;
                }
            }
            last_free = Some((cx, cy));
        }
        p.x = x1;
        p.y = y1;
        false
    }

    fn hit_terrain(
        &mut self,
        p: &mut Projectile,
        cell: (i32, i32),
        last_free: Option<(i32, i32)>,
        from: (f32, f32),
    ) -> Terrain {
        let at = last_free.map_or(from, |(x, y)| (x as f32 + 0.5, y as f32 + 0.5));
        if p.bounces_left > 0 {
            let near = last_free.unwrap_or(cell);
            let n = self
                .world
                .surface_normal(near.0, near.1, KindMask::SURFACES);
            let (nx, ny) = unit((n.0 as f32, n.1 as f32), (0.0, 0.0));
            if (nx, ny) != (0.0, 0.0) {
                let dot = p.vx * nx + p.vy * ny;
                p.vx -= 2.0 * dot * nx;
                p.vy -= 2.0 * dot * ny;
            } else if p.def.bounce_always {
                p.vx = -p.vx;
                p.vy = -p.vy;
            } else {
                self.release(p, at);
                self.finish(p, at, End::Hit);
                return Terrain::Dead;
            }
            p.vx *= p.def.bounce_energy;
            p.vy *= p.def.bounce_energy;
            p.bounces_left -= 1;
            (p.x, p.y) = at;
            self.release(p, at);
            return Terrain::Bounced;
        }
        if !p.def.on_collision_die {
            return Terrain::Passed;
        }
        self.release(p, at);
        self.finish(p, at, End::Hit);
        Terrain::Dead
    }

    /// A projectile reached a creature or breakable thing. Returns `true` if it ends there.
    fn hit_creature(
        &mut self,
        p: &mut Projectile,
        target: Target,
        mult: f32,
        mass: f32,
        cell: (i32, i32),
    ) -> bool {
        let frame = self.world.frame();
        let def = &p.def;
        let scale = if def.damage_scaled_by_speed && p.speed0 > 0.0 {
            p.speed() / p.speed0
        } else {
            1.0
        };
        // Secret potions: the player's own hits crit more often (crit_boost) and hurt more
        // (berserk) while the potion lasts.
        let (crit_bonus, berserk) = if p.owner == Owner::Player {
            self.player_boosts()
        } else {
            (0.0, 1.0)
        };
        let crit = target != Target::Player
            && self.ai.unit(frame, u64::from(p.id), 9) * 100.0 < def.crit_chance + crit_bonus;
        let amount =
            def.hit_damage * scale * mult * berserk * if crit { CRIT_MULTIPLIER } else { 1.0 };
        let dealt = self.hurt(target, amount, DamageSource::Hit);
        let defs = self.defs.clone();
        for status in p.def.effects.clone() {
            self.apply_status(target, status, defs.statuses.frames(status));
        }
        let (ux, uy) = unit((p.vx, p.vy), p.heading);
        let kick = p.def.knockback * self.defs.sim.hit_knockback / mass.max(0.05);
        self.push(target, ux * kick, uy * kick);
        let (label, id) = self.target_label(target);
        self.world.log_event(
            "hit",
            vec![
                ("projectile", Value::Str(p.def.name.clone())),
                ("target", Value::Str(label)),
                ("id", Value::Int(i64::from(id))),
                ("damage", Value::Float(super::vitals::shown(dealt))),
                ("crit", Value::Int(i64::from(crit))),
                ("x", Value::Int(i64::from(cell.0))),
                ("y", Value::Int(i64::from(cell.1))),
            ],
        );
        if !p.def.on_collision_die {
            return false;
        }
        let at = (cell.0 as f32 + 0.5, cell.1 as f32 + 0.5);
        self.release(p, at);
        self.finish(p, at, End::Hit);
        true
    }

    /// Set a trigger's payload loose at `pos`, along the way the carrier flies.
    fn release(&mut self, p: &mut Projectile, pos: (f32, f32)) {
        let Some(trigger) = p.trigger.take() else {
            return;
        };
        let dir = unit((p.vx, p.vy), p.heading);
        for shot in &trigger.payload {
            self.launch_shot(shot, p.owner, pos, dir);
        }
    }

    /// The projectile ends at `pos`: its blast, and where a particle lands its material.
    fn finish(&mut self, p: &Projectile, pos: (f32, f32), end: End) {
        let (x, y) = (pos.0.floor() as i32, pos.1.floor() as i32);
        if let Some(e) = p.def.explosion {
            let goes_off = match end {
                End::Hit => e.on_death,
                End::Lifetime => e.on_lifetime_out,
            };
            if goes_off {
                self.blast_from_def(&e, x, y, p.owner);
            }
        }
        if let Some((material, count)) = p.def.emit {
            self.spill(x, y, material, count, 3, false);
        }
    }

    /// Trails of fire or water behind the projectile, and the heat of a flying fireball.
    fn leave_trail(&mut self, p: &Projectile) {
        let frame = self.world.frame();
        let id = u64::from(p.id);
        let sim = self.defs.sim;
        let (cx, cy) = (p.x.floor() as i32, p.y.floor() as i32);
        for (k, &(material, amount)) in p.def.trail.iter().enumerate() {
            let cells = (amount / sim.trail_divisor.max(1)).max(1);
            for j in 0..cells {
                let salt = 20 + (k as u64) * 64 + u64::from(j);
                let dx = self.ai.below(3, frame, id, salt) as i32 - 1;
                let dy = self.ai.below(3, frame, id, salt + 32) as i32 - 1;
                if self.is_free(cx + dx, cy + dy) {
                    self.world.set_cell(cx + dx, cy + dy, material, false);
                }
            }
        }
        let r = p.def.ignite_radius as i32;
        if r > 0 {
            for j in 0..sim.ignite_samples_per_frame {
                let dx = self
                    .ai
                    .below(2 * r as u32 + 1, frame, id, 400 + u64::from(j))
                    as i32
                    - r;
                let dy = self
                    .ai
                    .below(2 * r as u32 + 1, frame, id, 500 + u64::from(j))
                    as i32
                    - r;
                if dx * dx + dy * dy <= r * r {
                    self.world.ignite(cx + dx, cy + dy);
                }
            }
        }
    }
}
