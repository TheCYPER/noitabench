//! Bottles in the player's hands: scoop liquid from the ground (fill), tip it out (pour), swallow
//! it (drink) or throw the bottle, which shatters and spills where it lands (design.md section 3).
//!
//! A bottle is a flask of Noita: it holds a *mixture* of materials up to its capacity. Filling
//! adds whatever liquid is scooped, pouring and drinking take the same share of every material
//! (`Bottle::take`), a shattered bottle spills all of it. Inside a bottle the only reaction that
//! runs is the secret recipes (`mix_bottles`); the ordinary reaction table does not run there
//! (a deliberate simplification: the bottle is a container, not a bowl).
//!
//! Drinking works cell by cell: each swallowed cell applies the effect named by its material's
//! `drink_effect` in `materials.json`, with the numbers of `entities.json` `drink`. One event per
//! material sums up a drink, pour or fill when it stops: when the key is let go, when the bottle
//! is empty (drink, pour) or full (fill), when another action or bottle is chosen, when the
//! bottle is thrown or dropped, or when the harness calls [`Game::end_bottle_action`]. A fill that
//! finds nothing to scoop does not end by itself: the key decides.

use cogbench_sim::{Aabb, Kind, Value};

use crate::control::{Controls, Pressed};
use crate::entity::{Bottle, BottleAction, BottleOp, DamageSource, Item, ItemKind, Part, Target};
use crate::physics::Body;
use crate::status::Status;

use super::Game;

/// Width and height of the patch around the feet that a fill scoops from.
const SCOOP_W: i32 = 14;
const SCOOP_H: i32 = 12;
/// A drunk status never grows beyond this many frames.
const MAX_STATUS_FRAMES: u32 = 3600;
/// How far in front of the hand a pour lands, in cells.
const POUR_REACH: f32 = 8.0;
const POUR_RADIUS: i32 = 3;

/// Frames of status for swallowing `n` cells when `left` cells remain afterwards, at `per_cell`
/// frames per cell (may be fractional). The share is the difference of two whole-number totals,
/// `floor((left + n) * per_cell) - floor(left * per_cell)`, so the shares of a bottle drunk to the
/// last drop add up to `floor(cells * per_cell)` whatever the sip size: a full 400-cell bottle of
/// 2.25 frames per cell gives exactly 900 frames, not 10 sips rounded up to 23 each.
fn status_frames(left: u32, n: u32, per_cell: f32) -> u32 {
    let per_cell = f64::from(per_cell);
    let total = |cells: u32| (f64::from(cells) * per_cell).floor();
    (total(left + n) - total(left)) as u32
}

impl Game {
    pub(crate) fn use_bottle(&mut self, c: &Controls, pressed: Pressed) {
        let wanted = if c.drink {
            Some(BottleOp::Drink)
        } else if c.pour {
            Some(BottleOp::Pour)
        } else if c.fill {
            Some(BottleOp::Fill)
        } else {
            None
        };
        let running = self
            .state
            .player
            .as_ref()
            .and_then(|p| p.action.as_ref().map(|a| (a.op, a.bottle, p.active_bottle)));
        // Letting go, or switching to another action or another bottle, ends the action.
        if running.is_some_and(|(op, bottle, active)| Some(op) != wanted || bottle != active) {
            self.flush_bottle_action();
        }
        if pressed.throw {
            self.throw_bottle(c);
        }
        match wanted {
            Some(BottleOp::Drink) => self.drink_step(),
            Some(BottleOp::Pour) => self.pour_step(c),
            Some(BottleOp::Fill) => self.fill_step(),
            None => {}
        }
    }

    /// Add what moved this frame to the action in progress (or start one).
    fn note_action(&mut self, op: BottleOp, moved: &[Part]) {
        let Some(p) = self.state.player.as_mut() else {
            return;
        };
        let bottle = p.active_bottle;
        let action = p.action.get_or_insert_with(|| BottleAction {
            op,
            bottle,
            moved: Bottle::default(),
        });
        for part in moved {
            action.moved.add(part.material, part.amount);
        }
    }

    /// Write the summary events of a finished drink, pour or fill: one per material, in material
    /// order, `{material, cells}`. Does nothing when no action is running.
    pub(crate) fn flush_bottle_action(&mut self) {
        let Some(a) = self.state.player.as_mut().and_then(|p| p.action.take()) else {
            return;
        };
        let kind = match a.op {
            BottleOp::Drink => "drink",
            BottleOp::Pour => "pour",
            BottleOp::Fill => "fill",
        };
        for part in &a.moved.parts {
            let material = self.world.content().mats.key_of(part.material).to_string();
            self.world.log_event(
                kind,
                vec![
                    ("material", Value::Str(material)),
                    ("cells", Value::Int(i64::from(part.amount))),
                ],
            );
        }
    }

    /// End the drink, pour or fill in progress now, writing its summary events on this frame
    /// instead of when the key is next let go. For harnesses that stop pressing the key on the
    /// last frame of a tick, where no later frame of the decision would see the release.
    pub fn end_bottle_action(&mut self) {
        self.flush_bottle_action();
    }

    fn drink_step(&mut self) {
        let rate = self.defs.items.bottle.drink_cells_per_frame;
        let taken = {
            let Some(p) = self.state.player.as_mut() else {
                return;
            };
            let active = p.active_bottle;
            let Some(b) = p.bottles.get_mut(active).filter(|b| !b.is_empty()) else {
                self.flush_bottle_action();
                return;
            };
            // Each material with the cells of it that stay behind (for the status frames).
            let parts = b.take(rate);
            parts
                .into_iter()
                .map(|part| (part, b.amount_of(part.material)))
                .collect::<Vec<(Part, u32)>>()
        };
        let moved: Vec<Part> = taken.iter().map(|(part, _)| *part).collect();
        self.note_action(BottleOp::Drink, &moved);
        let (damage, started) = self.swallow(&taken);
        for s in started {
            self.log_status(Target::Player, s, true);
        }
        self.hurt(Target::Player, damage, DamageSource::Contact);
        if self.active_bottle_empty() {
            self.flush_bottle_action(); // nothing left to drink: the drink is over
        }
    }

    /// Apply what swallowing these cells does, each material by its `drink_effect`: healing,
    /// mana and statuses go to the player now. Returns the damage to deal and the statuses that
    /// began.
    fn swallow(&mut self, taken: &[(Part, u32)]) -> (f32, Vec<Status>) {
        let defs = self.defs.clone();
        let mut damage = 0.0;
        let mut started = Vec::new();
        for (part, left) in taken {
            let key = self
                .world
                .content()
                .mats
                .get(part.material)
                .map_or("none", |m| m.drink_effect.as_str())
                .to_string();
            let Some(effect) = defs.drink.get(&key) else {
                continue;
            };
            let Some(p) = self.state.player.as_mut() else {
                continue;
            };
            let cells = part.amount as f32;
            damage += cells * effect.damage_per_cell;
            p.vitals.hp = (p.vitals.hp + cells * effect.heal_per_cell).min(p.vitals.hp_max);
            if effect.mana_per_cell > 0.0 {
                for w in &mut p.wands {
                    let cap = w.wand.stats().mana_max;
                    w.wand
                        .set_mana((w.wand.mana() + cells * effect.mana_per_cell).min(cap));
                }
            }
            if let Some(status) = effect.status.as_deref().and_then(Status::parse) {
                let frames = status_frames(*left, part.amount, effect.frames_per_cell);
                if p.vitals.statuses.extend(status, frames) {
                    started.push(status);
                }
                p.vitals.statuses.cap(status, MAX_STATUS_FRAMES);
            }
        }
        (damage, started)
    }

    fn pour_step(&mut self, c: &Controls) {
        let rate = self.defs.items.bottle.pour_cells_per_frame;
        let dir = self.aim_dir(c, 5);
        let (x, y) = {
            let (hx, hy) = self.muzzle(dir);
            // The mouth is a little further out than the muzzle of a wand.
            (
                (hx + dir.0 * (POUR_REACH - self.defs.player.muzzle_distance)).floor() as i32,
                (hy + dir.1 * (POUR_REACH - self.defs.player.muzzle_distance)).floor() as i32,
            )
        };
        let taken = {
            let Some(p) = self.state.player.as_mut() else {
                return;
            };
            let active = p.active_bottle;
            let Some(b) = p.bottles.get_mut(active).filter(|b| !b.is_empty()) else {
                self.flush_bottle_action();
                return;
            };
            b.take(rate)
        };
        let fitted = self.spill_parts(x, y, &taken, POUR_RADIUS, false);
        let mut placed = Vec::new();
        let mut back = Vec::new();
        for (part, n) in taken.iter().zip(fitted) {
            placed.push(Part {
                material: part.material,
                amount: n,
            });
            back.push((part.material, part.amount - n));
        }
        if let Some(b) = self
            .state
            .player
            .as_mut()
            .and_then(|p| p.bottles.get_mut(p.active_bottle))
        {
            for (material, n) in back {
                b.add(material, n); // no room for it: it stays in the bottle
            }
        }
        self.note_action(BottleOp::Pour, &placed);
        if self.active_bottle_empty() {
            self.flush_bottle_action();
        }
    }

    fn fill_step(&mut self) {
        let defs = self.defs.clone();
        let rate = defs.items.bottle.fill_cells_per_frame;
        let capacity = defs.items.bottle.capacity;
        let (area, room) = {
            let Some(p) = self.state.player.as_ref() else {
                return;
            };
            let Some(b) = p.bottles.get(p.active_bottle) else {
                return;
            };
            let (cx, cy) = p.body.cell();
            let area = Aabb::new(
                cx + p.body.w / 2 - SCOOP_W / 2,
                cy + p.body.h - SCOOP_H / 2,
                SCOOP_W,
                SCOOP_H,
            );
            (area, capacity.saturating_sub(b.total()))
        };
        let want = rate.min(room);
        let mut found = Vec::new();
        if want > 0 {
            let mats = &self.world.content().mats;
            'scan: for y in area.y..area.y + area.h {
                for x in area.x..area.x + area.w {
                    let cell = self.world.grid().get(x, y);
                    if cell.mat == 0 || mats.rt(cell.mat).kind != Kind::Liquid {
                        continue;
                    }
                    found.push((x, y, cell.mat));
                    if found.len() as u32 >= want {
                        break 'scan;
                    }
                }
            }
        }
        if found.is_empty() {
            // Full, or the liquid has not flowed back into the scoop yet: the key decides.
            return;
        }
        let mut moved = Bottle::default();
        for &(x, y, material) in &found {
            self.world.set_cell(x, y, 0, false);
            moved.add(material, 1);
        }
        let full = {
            let Some(b) = self
                .state
                .player
                .as_mut()
                .and_then(|p| p.bottles.get_mut(p.active_bottle))
            else {
                return;
            };
            for part in &moved.parts {
                b.add(part.material, part.amount);
            }
            b.total() >= capacity
        };
        self.note_action(BottleOp::Fill, &moved.parts);
        if full {
            self.flush_bottle_action();
        }
    }

    fn active_bottle_empty(&self) -> bool {
        self.state
            .player
            .as_ref()
            .and_then(|p| p.bottles.get(p.active_bottle))
            .is_none_or(Bottle::is_empty)
    }

    /// Throw the active bottle along the aim; it shatters where it lands.
    fn throw_bottle(&mut self, c: &Controls) {
        let defs = self.defs.clone();
        let bd = &defs.items.bottle;
        let dir = self.aim_dir(c, 6);
        let origin = self.muzzle(dir);
        self.flush_bottle_action();
        let bottle = {
            let Some(p) = self.state.player.as_mut() else {
                return;
            };
            if p.active_bottle >= p.bottles.len() {
                return;
            }
            let b = p.bottles.remove(p.active_bottle);
            p.active_bottle = p.active_bottle.min(p.bottles.len().saturating_sub(1));
            b
        };
        let id = self.state.fresh_id();
        let mut body = Body::new(
            origin.0.floor() as i32 - bd.w / 2,
            origin.1.floor() as i32 - bd.h / 2,
            bd.w,
            bd.h,
        );
        body.vx = dir.0 * bd.throw_speed;
        body.vy = dir.1 * bd.throw_speed - bd.throw_lift;
        let (material, cells) = (self.contents_label(&bottle), bottle.total());
        self.state.items.push(Item {
            id,
            body,
            kind: ItemKind::Thrown(bottle),
            hp: 0.0,
            hp_max: 0.0,
            asleep: false,
            lit: 0,
            dead: false,
            logged_damage: 0.0,
        });
        self.world.log_event(
            "throw",
            vec![
                ("material", Value::Str(material)),
                ("cells", Value::Int(i64::from(cells))),
            ],
        );
    }

    /// A thrown bottle broke: everything in it spills where it was.
    pub(crate) fn shatter(&mut self, item: &Item) {
        let ItemKind::Thrown(bottle) = &item.kind else {
            return;
        };
        let (cx, cy) = item.body.center();
        let (x, y) = (cx.floor() as i32, cy.floor() as i32);
        let radius = self.defs.items.bottle.spill_radius;
        let placed: u32 = self
            .spill_parts(x, y, &bottle.parts, radius, false)
            .iter()
            .sum();
        let material = self.contents_label(bottle);
        self.world.log_event(
            "shatter",
            vec![
                ("material", Value::Str(material)),
                ("cells", Value::Int(i64::from(placed))),
                ("x", Value::Int(i64::from(x))),
                ("y", Value::Int(i64::from(y))),
            ],
        );
    }

    /// The keys of the materials in a bottle joined with `+` in material order (`water+oil`);
    /// `air` for an empty one.
    pub(crate) fn contents_label(&self, bottle: &Bottle) -> String {
        let mats = &self.world.content().mats;
        if bottle.is_empty() {
            return mats.key_of(0).to_string();
        }
        let keys: Vec<&str> = bottle
            .parts
            .iter()
            .map(|p| mats.key_of(p.material))
            .collect();
        keys.join("+")
    }

    /// Secret recipes inside bottles: where all three ingredients of a recipe are in one bottle
    /// (carried, or lying on the ground) they turn into the potion over time, at most
    /// `items.bottle.mix_cells_per_frame` cells of each ingredient per frame (about what the
    /// grid rule `recipe_mix` does along a contact line of that many cells). No random numbers:
    /// the same bottle always converts the same way. No other reaction runs in a bottle.
    pub(crate) fn mix_bottles(&mut self) {
        let content = self.world.content().clone();
        if content.recipes.is_empty() {
            return;
        }
        let most = self.defs.items.bottle.mix_cells_per_frame;
        let mut made: Vec<(i32, i32, u8, u32)> = Vec::new();
        if let Some(p) = self.state.player.as_mut() {
            let (cx, cy) = p.body.cell();
            let (x, y) = (cx + p.body.w / 2, cy + p.body.h / 2);
            for b in p.bottles.iter_mut().filter(|b| b.parts.len() >= 3) {
                for (potion, k) in b.mix(&content.recipes, most) {
                    made.push((x, y, potion, k));
                }
            }
        }
        for it in &mut self.state.items {
            let (cx, cy) = it.body.center();
            if let ItemKind::Bottle(b) = &mut it.kind {
                if b.parts.len() >= 3 {
                    for (potion, k) in b.mix(&content.recipes, most) {
                        made.push((cx.floor() as i32, cy.floor() as i32, potion, k));
                    }
                }
            }
        }
        for (x, y, potion, cells) in made {
            let key = content.mats.key_of(potion).to_string();
            self.world.log_event(
                "mix",
                vec![
                    ("x", Value::Int(i64::from(x))),
                    ("y", Value::Int(i64::from(y))),
                    ("potion", Value::Str(key)),
                    ("cells", Value::Int(i64::from(cells))),
                    ("bottle", Value::Int(1)),
                ],
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::status_frames;

    /// Drink `cells` cells in sips of `sip`, the way `drink_step` does, and add up the frames.
    fn drunk(cells: u32, sip: u32, per_cell: f32) -> u32 {
        let mut left = cells;
        let mut total = 0;
        while left > 0 {
            let n = sip.min(left);
            left -= n;
            total += status_frames(left, n, per_cell);
        }
        total
    }

    #[test]
    fn whole_numbers_of_frames_per_cell_are_just_cells_times_rate() {
        assert_eq!(status_frames(0, 10, 2.0), 20);
        assert_eq!(status_frames(300, 10, 3.0), 30);
        assert_eq!(drunk(400, 10, 1.0), 400);
        assert_eq!(drunk(400, 10, 3.0), 1200);
    }

    #[test]
    fn a_full_bottle_gives_exactly_the_designed_frames_whatever_the_sip() {
        for sip in [1, 3, 7, 10, 25] {
            assert_eq!(drunk(400, sip, 2.25), 900, "sip {sip}");
            assert_eq!(drunk(400, sip, 1.5), 600, "sip {sip}");
        }
    }

    #[test]
    fn a_part_bottle_gets_the_floor_of_its_share() {
        assert_eq!(drunk(25, 10, 2.25), 56); // 56.25
        assert_eq!(drunk(0, 10, 2.25), 0);
        assert_eq!(drunk(100, 10, 0.0), 0);
    }
}
