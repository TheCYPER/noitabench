//! Explosions: carving the grid (the simulation's ray model, DUR-R01..R03) and then hurting and
//! pushing whatever stands in the crater's reach.
//!
//! Damage does not pass through rock: it needs a line from the blast to the target that no
//! static or powder cell crosses, checked after the carve (so a tunnel opened by the blast lets
//! it through). Blasts that go off inside a chain (a barrel set off by another) are queued by
//! the callers and run in order.

use cogbench_sim::{Aabb, ExplosionSpec, KindMask, QueryMask};
use serde::{Deserialize, Serialize};

use crate::entity::{DamageSource, Owner, Target};
use crate::physics::{contains, distance_to_box, supercover};

use super::Game;

/// The longest line of sight checked between a blast and a target, in cells (the largest blast
/// radius is 512, so a diagonal of a full blast stays inside this).
const MAX_LOS_CELLS: usize = 1536;

/// Parameters of one explosion (`ConfigExplosion`).
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct BlastSpec {
    pub x: i32,
    pub y: i32,
    pub radius: u32,
    /// Damage to everything in reach, internal units, before the target's multiplier.
    pub damage: f32,
    pub ray_energy: u32,
    pub max_durability: u8,
    pub fire_percent: u8,
    pub owner: Owner,
    /// The owner is not hurt (`explosion_dont_damage_shooter`).
    pub spare_owner: bool,
}

/// One thing a projectile or blast can hurt: its hit boxes (with the damage multiplier of a hit
/// inside each) and its mass.
pub(crate) struct Victim {
    pub target: Target,
    pub boxes: Vec<(Aabb, f32)>,
    pub mass: f32,
}

fn centre_of(boxes: &[(Aabb, f32)]) -> (f32, f32) {
    let (mut x0, mut y0, mut x1, mut y1) = (i32::MAX, i32::MAX, i32::MIN, i32::MIN);
    for (b, _) in boxes {
        x0 = x0.min(b.x);
        y0 = y0.min(b.y);
        x1 = x1.max(b.x + b.w);
        y1 = y1.max(b.y + b.h);
    }
    ((x0 + x1) as f32 / 2.0, (y0 + y1) as f32 / 2.0)
}

impl Game {
    /// Hit boxes of everything that can be hurt, in the order player, enemies, items.
    pub(crate) fn victims(&self) -> Vec<Victim> {
        let defs = &self.defs;
        let mut out = Vec::new();
        if let Some(p) = self.state.player.as_ref().filter(|p| !p.vitals.dead) {
            let (cx, cy) = p.body.cell();
            let boxes = defs
                .player
                .hitboxes
                .iter()
                .map(|h| (Aabb::new(cx + h.dx, cy + h.dy, h.w, h.h), h.mult))
                .collect();
            out.push(Victim {
                target: Target::Player,
                boxes,
                mass: defs.player.mass,
            });
        }
        for e in self.state.enemies.iter().filter(|e| !e.vitals.dead) {
            let Some(def) = defs.enemies.get(&e.kind) else {
                continue;
            };
            let (cx, cy) = e.body.cell();
            out.push(Victim {
                target: Target::Enemy(e.id),
                boxes: def
                    .hitboxes
                    .iter()
                    .map(|h| (Aabb::new(cx + h.dx, cy + h.dy, h.w, h.h), h.mult))
                    .collect(),
                mass: def.mass,
            });
        }
        for it in self
            .state
            .items
            .iter()
            .filter(|i| i.hp_max > 0.0 && !i.dead)
        {
            out.push(Victim {
                target: Target::Item(it.id),
                boxes: vec![(it.body.aabb(), 1.0)],
                mass: self.item_mass(it),
            });
        }
        out
    }

    /// Carve the grid and hurt what the blast reaches.
    pub fn blast(&mut self, spec: BlastSpec) {
        // Clamped to what the simulation accepts, so `explode` cannot fail.
        let radius = spec
            .radius
            .clamp(1, cogbench_sim::consts::MAX_EXPLOSION_RADIUS);
        let sim = ExplosionSpec {
            x: spec.x,
            y: spec.y,
            radius,
            ray_energy: spec.ray_energy,
            max_durability: spec.max_durability,
            fire_percent: spec.fire_percent.min(100),
        };
        let _destroyed = self.world.explode(sim).unwrap_or(0);
        if spec.damage <= 0.0 {
            return;
        }
        let from = (spec.x, spec.y);
        let knock = self.defs.explosion.knockback_speed;
        for v in self.victims() {
            if spec.spare_owner && owns(spec.owner, v.target) {
                continue;
            }
            let reach = v
                .boxes
                .iter()
                .map(|(b, _)| distance_to_box(spec.x as f32 + 0.5, spec.y as f32 + 0.5, *b))
                .fold(f32::INFINITY, f32::min);
            if reach > radius as f32 {
                continue;
            }
            let (tx, ty) = centre_of(&v.boxes);
            let to = (tx.floor() as i32, ty.floor() as i32);
            if self.line_cut(from, to, &v.boxes) {
                continue;
            }
            self.hurt(v.target, spec.damage, DamageSource::Explosion);
            let falloff = (1.0 - reach / radius as f32).max(0.0);
            let (dx, dy) = (tx - (spec.x as f32 + 0.5), ty - (spec.y as f32 + 0.5));
            let len = (dx * dx + dy * dy).sqrt();
            let (ux, uy) = if len < 0.5 {
                (0.0, -1.0)
            } else {
                (dx / len, dy / len)
            };
            let speed = knock * falloff / v.mass.max(0.05);
            self.push(v.target, ux * speed, uy * speed);
        }
    }

    /// Does rock or sand lie between the blast and the target? The line is the 4-connected path
    /// of cells (v1-scope section 5a), so a wall of diagonally touching cells shields too. A
    /// blocking cell inside one of the target's own boxes does not count.
    fn line_cut(&self, from: (i32, i32), to: (i32, i32), boxes: &[(Aabb, f32)]) -> bool {
        let mask = QueryMask::new(KindMask::SURFACES);
        let (x0, y0) = (from.0 as f32 + 0.5, from.1 as f32 + 0.5);
        let (x1, y1) = (to.0 as f32 + 0.5, to.1 as f32 + 0.5);
        let cells = supercover(x0, y0, x1, y1, MAX_LOS_CELLS);
        cells
            .into_iter()
            .find(|&(x, y)| self.world.blocked_at(x, y, mask))
            .is_some_and(|(x, y)| !boxes.iter().any(|(b, _)| contains(*b, x, y)))
    }

    /// Add to the velocity of a target (blasts, kicks, hits). Wakes sleeping items.
    pub(crate) fn push(&mut self, target: Target, dvx: f32, dvy: f32) {
        let body = match target {
            Target::Player => self.state.player.as_mut().map(|p| &mut p.body),
            Target::Enemy(id) => self
                .state
                .enemies
                .iter_mut()
                .find(|e| e.id == id)
                .map(|e| &mut e.body),
            Target::Item(id) => self.state.items.iter_mut().find(|i| i.id == id).map(|i| {
                i.asleep = false;
                &mut i.body
            }),
        };
        if let Some(b) = body {
            b.vx += dvx;
            b.vy += dvy;
        }
    }
}

fn owns(owner: Owner, target: Target) -> bool {
    match (owner, target) {
        (Owner::Player, Target::Player) => true,
        (Owner::Enemy(a), Target::Enemy(b)) => a == b,
        _ => false,
    }
}
