//! The player's turn (tick-design step 1): selecting things, moving, picking up, kicking and
//! throwing. Bottles (drink, pour, fill) are in `bottles.rs`, casting in `cast.rs`.

use cogbench_sim::{Aabb, Value};

use crate::control::Controls;
use crate::entity::{DamageSource, ItemKind, Target};
use crate::physics::overlaps;

use super::player_motion::move_player;
use super::Game;

impl Game {
    pub(crate) fn update_player(&mut self, controls: &Controls) {
        let defs = self.defs.clone();
        let alive = self.player_alive();
        let ctl = if alive {
            controls.clone()
        } else {
            controls.idle()
        };
        let pressed = ctl.pressed(&self.state.prev);
        {
            let Some(p) = self.state.player.as_mut() else {
                return;
            };
            if let Some(w) = ctl
                .select_wand
                .map(usize::from)
                .filter(|w| *w < p.wands.len())
            {
                p.active_wand = w;
            }
            if let Some(b) = ctl
                .select_bottle
                .map(usize::from)
                .filter(|b| *b < p.bottles.len())
            {
                p.active_bottle = b;
            }
            p.aim = ctl.aim;
            p.kick_cooldown = p.kick_cooldown.saturating_sub(1);
            p.revealed = p.revealed.saturating_sub(1);
            move_player(&self.world, p, &defs.player, &defs.statuses, &ctl, pressed);
        }
        if !alive {
            return;
        }
        if pressed.interact {
            self.pick_up();
        }
        if pressed.kick {
            self.kick();
        }
        if let Some(what) = pressed.drop {
            self.drop_item(what);
        }
        self.use_bottle(&ctl, pressed);
    }

    /// Pick up the nearest wand, spell or bottle within reach.
    fn pick_up(&mut self) {
        let defs = self.defs.clone();
        let Some(p) = self.state.player.as_ref() else {
            return;
        };
        let (px, py) = p.body.center();
        let reach = defs.player.pickup_radius;
        let mut best: Option<(f32, usize)> = None;
        for (i, it) in self.state.items.iter().enumerate() {
            if !matches!(
                it.kind,
                ItemKind::Wand(_) | ItemKind::Spell(_) | ItemKind::Bottle(_)
            ) {
                continue;
            }
            let (ix, iy) = it.body.center();
            let (dx, dy) = (ix - px, iy - py);
            let d = (dx * dx + dy * dy).sqrt();
            if d <= reach && best.is_none_or(|(bd, _)| d < bd) {
                best = Some((d, i));
            }
        }
        let Some((_, i)) = best else {
            return;
        };
        let (what, full) = {
            let p = self.state.player.as_ref();
            let held = |n: usize, max: usize| n >= max;
            match (&self.state.items[i].kind, p) {
                (ItemKind::Wand(_), Some(p)) => {
                    ("wand", held(p.wands.len(), defs.items.wand.max_held))
                }
                (ItemKind::Spell(_), Some(p)) => {
                    ("spell", held(p.spells.len(), defs.items.spell.max_held))
                }
                (ItemKind::Bottle(_), Some(p)) => {
                    ("bottle", held(p.bottles.len(), defs.items.bottle.max_held))
                }
                _ => return,
            }
        };
        if full {
            self.world
                .log_event("pickup_failed", vec![("item", Value::Str(what.into()))]);
            return;
        }
        let item = self.state.items.remove(i);
        let mut detail = String::new();
        let label = match &item.kind {
            ItemKind::Bottle(b) => self.contents_label(b),
            _ => String::new(),
        };
        if let Some(p) = self.state.player.as_mut() {
            match item.kind {
                ItemKind::Wand(w) => p.wands.push(*w),
                ItemKind::Spell(slot) => {
                    detail = self.book.key(slot.spell).to_string();
                    p.spells.push(slot);
                }
                ItemKind::Bottle(b) => {
                    if !b.is_empty() {
                        detail = label;
                    }
                    p.bottles.push(b);
                }
                _ => {}
            }
        }
        self.world.log_event(
            "pickup",
            vec![
                ("item", Value::Str(what.into())),
                ("detail", Value::Str(detail)),
                ("id", Value::Int(i64::from(item.id))),
            ],
        );
    }

    /// Kick whatever stands in front of the player: items fly, creatures and barrels are hurt.
    fn kick(&mut self) {
        let defs = self.defs.clone();
        let kd = defs.player.kick;
        let Some(p) = self.state.player.as_mut() else {
            return;
        };
        if p.kick_cooldown > 0 {
            return;
        }
        p.kick_cooldown = kd.cooldown;
        self.reveal_player();
        let Some(p) = self.state.player.as_mut() else {
            return;
        };
        let (cx, cy) = p.body.cell();
        let facing = f32::from(p.facing);
        let x0 = if p.facing > 0 {
            cx + p.body.w
        } else {
            cx - kd.reach
        };
        let area = Aabb::new(x0, cy + p.body.h - kd.height, kd.reach, kd.height);
        let mut hits = 0;
        let item_ids: Vec<u32> = self
            .state
            .items
            .iter()
            .filter(|it| overlaps(area, it.body.aabb()))
            .map(|it| it.id)
            .collect();
        for id in item_ids {
            self.kick_item(id, facing * kd.item_speed, -kd.item_lift, kd.damage);
            hits += 1;
        }
        let enemy_ids: Vec<(u32, f32)> = self
            .state
            .enemies
            .iter()
            .filter(|e| !e.vitals.dead)
            .filter(|e| {
                let Some(def) = defs.enemies.get(&e.kind) else {
                    return false;
                };
                let (ex, ey) = e.body.cell();
                def.hitboxes
                    .iter()
                    .any(|h| overlaps(area, Aabb::new(ex + h.dx, ey + h.dy, h.w, h.h)))
            })
            .map(|e| (e.id, defs.enemies.get(&e.kind).map_or(1.0, |d| d.mass)))
            .collect();
        for (id, mass) in enemy_ids {
            self.hurt(Target::Enemy(id), kd.damage, DamageSource::Melee);
            self.push(
                Target::Enemy(id),
                facing * kd.enemy_speed / mass.max(0.05),
                0.0,
            );
            hits += 1;
        }
        self.world.log_event(
            "kick",
            vec![
                ("x", Value::Int(i64::from(x0))),
                ("y", Value::Int(i64::from(cy))),
                ("hits", Value::Int(hits)),
            ],
        );
    }
}
