//! Barrels and other breakable things (cp1-feedback section 1): a gunpowder barrel explodes when
//! fire reaches it or a blast hits it, an acid barrel bursts and releases its acid, an oil barrel
//! spills oil and burns when lit. Barrels have hit points; projectiles, blasts, kicks, fire and
//! corrosive contact all wear them down.

use std::collections::VecDeque;

use cogbench_sim::{ContactRules, Kind, Value};

use crate::entity::{DamageSource, Item, ItemKind, Owner, Part, Target};
use crate::projectile::ExplosionDef;

use super::{BlastSpec, Game};

/// Neighbour order of the spill search: down first, so liquid settles low.
const SPILL_STEPS: [(i32, i32); 4] = [(0, 1), (-1, 0), (1, 0), (0, -1)];

impl Game {
    /// Break every item whose hit points ran out, one at a time: a break can set off a blast that
    /// kills the next barrel. At most `chain_limit_per_frame` per call; the rest waits.
    pub(crate) fn process_breaks(&mut self) {
        for _ in 0..self.defs.explosion.chain_limit_per_frame {
            let Some(i) = self.state.items.iter().position(|it| it.dead) else {
                return;
            };
            let item = self.state.items.remove(i);
            self.break_item(item);
        }
    }

    fn break_item(&mut self, item: Item) {
        let (cx, cy) = item.body.center();
        let (x, y) = (cx.floor() as i32, cy.floor() as i32);
        let defs = self.defs.clone();
        match &item.kind {
            ItemKind::Barrel(key) => {
                let Some(def) = defs.items.barrels.get(key) else {
                    return;
                };
                self.world.log_event(
                    "barrel_break",
                    vec![
                        ("kind", Value::Str(key.clone())),
                        ("id", Value::Int(i64::from(item.id))),
                        ("x", Value::Int(i64::from(x))),
                        ("y", Value::Int(i64::from(y))),
                        ("burning", Value::Int(i64::from(item.lit > 0))),
                    ],
                );
                if let Some(e) = def.explosion {
                    self.blast(BlastSpec {
                        x,
                        y,
                        radius: e.radius,
                        damage: e.damage,
                        ray_energy: e.ray_energy,
                        max_durability: e.max_durability.min(255) as u8,
                        fire_percent: e.fire_percent.min(100) as u8,
                        owner: Owner::World,
                        spare_owner: false,
                    });
                }
                if let Some(c) = &def.contents {
                    if let Some(m) = self.mat_index(&c.material) {
                        self.spill(x, y, m, c.cells, def.spill_radius, item.lit > 0);
                    }
                }
            }
            ItemKind::Bomb(bomb) => {
                if let Some(e) = bomb.def.explosion {
                    self.blast_from_def(&e, x, y, bomb.owner);
                }
            }
            ItemKind::Thrown(_) => self.shatter(&item),
            _ => {}
        }
    }

    /// The blast a projectile or bomb definition describes, at a cell.
    pub(crate) fn blast_from_def(&mut self, e: &ExplosionDef, x: i32, y: i32, owner: Owner) {
        // Secret potion: the player's explosions hurt more while berserk.
        let (_, berserk) = if owner == Owner::Player {
            self.player_boosts()
        } else {
            (0.0, 1.0)
        };
        self.blast(BlastSpec {
            x,
            y,
            radius: e.radius,
            damage: e.damage * berserk,
            ray_energy: e.ray_energy,
            max_durability: e.max_durability,
            fire_percent: e.fire_percent,
            owner,
            spare_owner: e.dont_damage_shooter,
        });
    }

    /// Put `cells` cells of `material` into the free cells (air and gas) around `(x, y)`, nearest
    /// first and low before high, within `radius` cells. Returns how many fitted; liquid cells
    /// then flow on their own. `burning` lights burnable material (burning oil).
    pub(crate) fn spill(
        &mut self,
        x: i32,
        y: i32,
        material: u8,
        cells: u32,
        radius: i32,
        burning: bool,
    ) -> u32 {
        let part = Part {
            material,
            amount: cells,
        };
        self.spill_parts(x, y, &[part], radius, burning)[0]
    }

    /// As [`Game::spill`] for a mixture: one search for free cells, the first material taking
    /// the nearest ones, then the next. Returns how many cells of each part fitted.
    pub(crate) fn spill_parts(
        &mut self,
        x: i32,
        y: i32,
        parts: &[Part],
        radius: i32,
        burning: bool,
    ) -> Vec<u32> {
        let radius = radius.max(1);
        let side = 2 * radius + 1;
        let slot = |cx: i32, cy: i32| ((cy - y + radius) * side + (cx - x + radius)) as usize;
        let mut seen = vec![false; (side * side) as usize];
        let mut queue = VecDeque::new();
        let start = (0..=radius)
            .map(|up| (x, y - up))
            .find(|&(cx, cy)| self.is_free(cx, cy));
        if let Some(s) = start {
            seen[slot(s.0, s.1)] = true;
            queue.push_back(s);
        }
        let mut placed = vec![0u32; parts.len()];
        let mut current = 0;
        while let Some((cx, cy)) = queue.pop_front() {
            while current < parts.len() && placed[current] >= parts[current].amount {
                current += 1;
            }
            if current >= parts.len() {
                break;
            }
            if self
                .world
                .set_cell(cx, cy, parts[current].material, burning)
            {
                placed[current] += 1;
            }
            for (dx, dy) in SPILL_STEPS {
                let (nx, ny) = (cx + dx, cy + dy);
                let inside = (nx - x).abs() <= radius && (ny - y).abs() <= radius;
                if inside && !seen[slot(nx, ny)] && self.is_free(nx, ny) {
                    seen[slot(nx, ny)] = true;
                    queue.push_back((nx, ny));
                }
            }
        }
        placed
    }

    /// A cell that liquid can be put into: inside the world, air or gas.
    pub(crate) fn is_free(&self, x: i32, y: i32) -> bool {
        let g = self.world.grid();
        g.in_bounds(x, y) && {
            let m = g.get(x, y).mat;
            m == 0 || self.world.content().mats.rt(m).kind == Kind::Gas
        }
    }

    /// Fire, fuses and corrosion for a barrel or bomb this frame.
    pub(crate) fn tick_breakable(&mut self, index: usize) {
        let defs = self.defs.clone();
        let frame = self.world.frame();
        let item = &self.state.items[index];
        if item.hp_max <= 0.0 || item.dead {
            return;
        }
        let b = item.body.aabb();
        let around = cogbench_sim::Aabb::new(b.x - 1, b.y - 1, b.w + 2, b.h + 2);
        let ov = self.world.overlap(around);
        let molten: u32 = defs
            .contact
            .ignite
            .iter()
            .filter_map(|k| self.mat_index(k))
            .map(|m| ov.count(m))
            .sum();
        let hot = ov.kind_count(Kind::Fire) + ov.burning() + molten > 0;
        let id = item.id;
        let key = match &item.kind {
            ItemKind::Barrel(k) => Some(k.clone()),
            _ => None,
        };
        let mut flame_at = None;
        if let Some(def) = key.as_ref().and_then(|k| defs.items.barrels.get(k)) {
            let it = &mut self.state.items[index];
            if def.explosion.is_some() || def.burn_frames > 0 {
                let span = def.fuse_frames.max(def.burn_frames);
                if it.lit == 0 && hot {
                    it.lit = span;
                } else if it.lit == 1 {
                    it.dead = true; // `lit` stays 1: the break knows the barrel was burning
                } else if it.lit > 1 {
                    it.lit -= 1;
                    if def.burn_frames > 0 && frame.is_multiple_of(5) {
                        flame_at = Some((b.x + b.w / 2, b.y - 1));
                    }
                }
            }
        }
        if let Some((x, y)) = flame_at {
            if self.is_free(x, y) {
                let fire = self.world.content().fire;
                self.world.set_cell(x, y, fire, false);
            }
        }
        let raw = self.world.contact_damage(b, ContactRules::default()).raw;
        self.hurt(Target::Item(id), raw as f32, DamageSource::Contact);
        if hot {
            // fire wears a barrel down like it does a creature
            let burn = defs.statuses.on_fire.damage_per_s / 60.0;
            self.hurt(Target::Item(id), burn, DamageSource::Fire);
        }
    }
}
