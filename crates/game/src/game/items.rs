//! Items in the world: wands, spells, bottles, barrels and bombs are simple ballistic bodies
//! (round-2 Q16): gravity, bounce and ground friction, no rotation and no rigid-body solver.
//! A resting item sleeps until the floor under it goes away; items far from the player sleep too.

use crate::entity::{DamageSource, Item, ItemKind, Owner, Target};
use crate::physics::{overlaps, Body, FPS};
use crate::projectile::Shot;

use super::Game;

/// Speeds under this (px/s) let a grounded item fall asleep.
const SLEEP_SPEED: f32 = 8.0;
/// Items never fall faster than this (px/s).
const TERMINAL_FALL: f32 = 350.0;

impl Game {
    /// How heavy an item is for kicks and blasts.
    pub(crate) fn item_mass(&self, item: &Item) -> f32 {
        let items = &self.defs.items;
        match &item.kind {
            ItemKind::Wand(_) => items.wand.mass,
            ItemKind::Spell(_) => items.spell.mass,
            ItemKind::Bottle(_) | ItemKind::Thrown(_) => items.bottle.mass,
            ItemKind::Barrel(k) => items.barrels.get(k).map_or(1.0, |b| b.mass),
            ItemKind::Bomb(_) => items.bomb.mass,
        }
    }

    fn near_player(&self, x: i32, y: i32) -> bool {
        let range = self.defs.sim.active_range;
        self.state.player.as_ref().is_none_or(|p| {
            let (px, py) = p.body.cell();
            (x - px).abs() <= range && (y - py).abs() <= range
        })
    }

    /// Fall, bounce, light fuses and shatter thrown bottles (tick-design step 3).
    pub(crate) fn update_items(&mut self) {
        let defs = self.defs.clone();
        let frame = self.world.frame();
        let interval = defs.sim.wake_check_interval.max(1);
        for i in 0..self.state.items.len() {
            let (x, y) = self.state.items[i].body.cell();
            if self.state.items[i].dead || !self.near_player(x, y) {
                continue;
            }
            self.tick_breakable(i);
            if self.tick_fuse(i) {
                continue;
            }
            let it = &mut self.state.items[i];
            if it.asleep {
                let check = frame % interval == u64::from(it.id) % interval;
                if !check || it.body.grounded(&self.world) {
                    continue;
                }
                it.asleep = false;
            }
            let grounded = it.body.grounded(&self.world);
            let bounce = match &it.kind {
                ItemKind::Bomb(b) => b.def.bounce_energy,
                ItemKind::Thrown(_) => 0.0,
                _ => defs.items.bounce,
            };
            // Gravity always acts: a resting item meets the floor again every few frames and the
            // sweep stops it, so a landing is never missed.
            it.body.vy = (it.body.vy + defs.items.gravity / FPS).min(TERMINAL_FALL);
            if grounded {
                it.body.vx *= defs.items.ground_friction;
            }
            let moved = it.body.integrate(&self.world, defs.items.step_up, bounce);
            if matches!(it.kind, ItemKind::Thrown(_)) {
                if moved.hit_x || moved.hit_y || grounded {
                    it.dead = true; // shatters in `break_item`
                }
            } else if grounded
                && it.body.vx.abs() < SLEEP_SPEED
                && !matches!(it.kind, ItemKind::Bomb(_))
            {
                it.body.vx = 0.0;
                it.body.vy = 0.0;
                it.asleep = true;
            }
            if matches!(self.state.items[i].kind, ItemKind::Thrown(_)) {
                self.thrown_hits_creature(i);
            }
        }
    }

    /// A bomb's fuse; returns whether the item went off (and needs no more simulation).
    fn tick_fuse(&mut self, index: usize) -> bool {
        let it = &mut self.state.items[index];
        let ItemKind::Bomb(bomb) = &mut it.kind else {
            return false;
        };
        bomb.fuse -= 1;
        if bomb.fuse <= 0 {
            it.dead = true;
            return true;
        }
        false
    }

    /// A thrown bottle that touches an enemy shatters on it.
    fn thrown_hits_creature(&mut self, index: usize) {
        let defs = self.defs.clone();
        let b = self.state.items[index].body.aabb();
        let hit = self.state.enemies.iter().any(|e| {
            let Some(def) = defs.enemies.get(&e.kind) else {
                return false;
            };
            let (cx, cy) = e.body.cell();
            !e.vitals.dead
                && def
                    .hitboxes
                    .iter()
                    .any(|h| overlaps(b, cogbench_sim::Aabb::new(cx + h.dx, cy + h.dy, h.w, h.h)))
        });
        if hit {
            self.state.items[index].dead = true;
        }
    }

    /// Create the world object of a shot: a bomb for thrown bodies, a flying projectile
    /// otherwise, an immediate blast for static spells.
    pub(crate) fn launch_shot(
        &mut self,
        shot: &Shot,
        owner: Owner,
        origin: (f32, f32),
        dir: (f32, f32),
    ) {
        use crate::projectile::{BodyType, Projectile};
        let frame = self.world.frame();
        match shot.def.body {
            BodyType::Static => {
                if let Some(e) = shot.def.explosion {
                    let (x, y) = (origin.0.floor() as i32, origin.1.floor() as i32);
                    self.blast_from_def(&e, x, y, owner);
                }
            }
            BodyType::Thrown => self.throw_bomb(shot, owner, origin, dir),
            BodyType::Flying | BodyType::Particle => {
                if self.state.projectiles.len() + self.flying >= self.defs.sim.max_projectiles {
                    return;
                }
                let id = self.state.fresh_id();
                let p = Projectile::launch(id, owner, shot, origin, dir, &self.ai, frame);
                self.state.projectiles.push(p);
            }
        }
    }

    fn throw_bomb(&mut self, shot: &Shot, owner: Owner, origin: (f32, f32), dir: (f32, f32)) {
        let frame = self.world.frame();
        let id = self.state.fresh_id();
        let d = &self.defs.items.bomb;
        let u = self.ai.unit(frame, u64::from(id), 1);
        let speed = shot.def.speed_min + (shot.def.speed_max - shot.def.speed_min) * u;
        let mut body = Body::new(
            origin.0.floor() as i32 - d.w / 2,
            origin.1.floor() as i32 - d.h / 2,
            d.w,
            d.h,
        );
        body.vx = dir.0 * speed;
        body.vy = dir.1 * speed;
        let hp = shot.def.hp.unwrap_or(0.0);
        self.state.items.push(Item {
            id,
            body,
            kind: ItemKind::Bomb(Box::new(crate::entity::Bomb {
                def: shot.def.clone(),
                fuse: shot.def.lifetime as i32,
                owner,
            })),
            hp,
            hp_max: hp,
            asleep: false,
            lit: 0,
            dead: false,
            logged_damage: 0.0,
        });
    }

    /// Wear down a kicked or struck item's neighbours: a kick hurts breakable things a little.
    pub(crate) fn kick_item(&mut self, id: u32, vx: f32, vy: f32, damage: f32) {
        let mass = self
            .item_index(id)
            .map_or(1.0, |i| self.item_mass(&self.state.items[i]));
        let m = mass.max(0.05);
        self.push(Target::Item(id), vx / m, vy / m);
        self.hurt(Target::Item(id), damage, DamageSource::Melee);
    }
}
