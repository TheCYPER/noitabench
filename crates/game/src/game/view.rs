//! Read-only views of the game for the Python layer, recordings and tests. Hit points are in
//! displayed units (internal times 25, like the HUD); positions are cells.

use cogbench_sim::Aabb;

use crate::entity::{Bottle, Enemy, Item, ItemKind, Player};
use crate::wand::WandStats;

use super::vitals::shown;
use super::Game;

/// Something with a box in the world: for the viewer and for observations.
#[derive(Clone, Debug, PartialEq)]
pub struct EntityView {
    pub id: u32,
    /// `player`, an enemy key, an item label (`wand`, `spell`, `bottle`, `potion_*` for a bottle
    /// of a potion, `barrel_*`, `bomb`) or `projectile`.
    pub kind: String,
    /// Top-left corner and size of the visible box (the hit boxes of a creature).
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
    pub hp: f64,
    pub hp_max: f64,
    pub vx: f32,
    pub vy: f32,
    /// What it is: a spell key for projectiles and spells, the material with the largest share
    /// in a bottle, the spells of a wand (`-` for an empty slot) joined with commas.
    pub detail: String,
    /// Active statuses with the frames left.
    pub statuses: Vec<(String, u32)>,
    /// For a bottle (carried by nobody): material key and cells of each part, by material
    /// index. `None` for everything else.
    pub contents: Option<Vec<(String, u32)>>,
    /// For a wand lying on the ground: its stats and spells. `None` for everything else.
    pub wand: Option<WandView>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct WandView {
    pub id: u32,
    pub stats: WandStats,
    /// Spell key and uses left per slot.
    pub slots: Vec<Option<(String, Option<u32>)>>,
    pub always_cast: Vec<String>,
    pub mana: f32,
    pub cooldown: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PlayerView {
    pub id: u32,
    /// Collision box.
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
    /// Union of the hit boxes.
    pub hit: (i32, i32, i32, i32),
    pub vx: f32,
    pub vy: f32,
    pub hp: f64,
    pub hp_max: f64,
    pub dead: bool,
    pub facing: i8,
    pub on_ground: bool,
    /// Levitation left, 0 to 1.
    pub fly: f32,
    /// Breath left, 0 to 1.
    pub breath: f32,
    pub invincible: u32,
    pub aim: f32,
    pub active_wand: usize,
    pub active_bottle: usize,
    pub wands: Vec<WandView>,
    /// Spells carried outside wands: key and uses left.
    pub spells: Vec<(String, Option<u32>)>,
    /// Per bottle: the material with the largest share (`""` when empty) and the cells in all.
    pub bottles: Vec<(String, u32)>,
    /// Per bottle: material key and cells of each part, by material index.
    pub bottle_contents: Vec<Vec<(String, u32)>>,
    pub statuses: Vec<(String, u32)>,
}

fn union(boxes: impl Iterator<Item = Aabb>) -> Aabb {
    let (mut x0, mut y0, mut x1, mut y1) = (i32::MAX, i32::MAX, i32::MIN, i32::MIN);
    for b in boxes {
        x0 = x0.min(b.x);
        y0 = y0.min(b.y);
        x1 = x1.max(b.x + b.w);
        y1 = y1.max(b.y + b.h);
    }
    if x0 > x1 {
        return Aabb::new(0, 0, 0, 0);
    }
    Aabb::new(x0, y0, x1 - x0, y1 - y0)
}

fn statuses(v: &crate::entity::Vitals) -> Vec<(String, u32)> {
    v.statuses
        .active()
        .into_iter()
        .map(|(s, f)| (s.key().to_string(), f))
        .collect()
}

impl Game {
    /// The material with the largest share of a bottle (`""` when it is empty).
    fn bottle_key(&self, b: &Bottle) -> String {
        b.largest().map_or(String::new(), |m| {
            self.world.content().mats.key_of(m).to_string()
        })
    }

    fn bottle_parts(&self, b: &Bottle) -> Vec<(String, u32)> {
        b.parts
            .iter()
            .map(|p| {
                (
                    self.world.content().mats.key_of(p.material).to_string(),
                    p.amount,
                )
            })
            .collect()
    }

    fn enemy_view(&self, e: &Enemy) -> Option<EntityView> {
        let def = self.defs.enemies.get(&e.kind)?;
        let (cx, cy) = e.body.cell();
        let b = union(
            def.hitboxes
                .iter()
                .map(|h| Aabb::new(cx + h.dx, cy + h.dy, h.w, h.h)),
        );
        Some(EntityView {
            id: e.id,
            kind: e.kind.clone(),
            x: b.x,
            y: b.y,
            w: b.w,
            h: b.h,
            hp: shown(e.vitals.hp),
            hp_max: shown(e.vitals.hp_max),
            vx: e.body.vx,
            vy: e.body.vy,
            detail: String::new(),
            statuses: statuses(&e.vitals),
            contents: None,
            wand: None,
        })
    }

    fn item_view(&self, it: &Item) -> EntityView {
        let b = it.body.aabb();
        let wand = match &it.kind {
            ItemKind::Wand(held) => Some(self.wand_view(held)),
            _ => None,
        };
        let detail = match &it.kind {
            ItemKind::Bottle(bottle) | ItemKind::Thrown(bottle) => self.bottle_key(bottle),
            ItemKind::Spell(slot) => self.book.key(slot.spell).to_string(),
            ItemKind::Wand(_) => wand.as_ref().map_or(String::new(), |w| {
                w.slots
                    .iter()
                    .map(|s| s.as_ref().map_or("-", |(spell, _)| spell.as_str()))
                    .collect::<Vec<_>>()
                    .join(",")
            }),
            _ => String::new(),
        };
        let contents = match &it.kind {
            ItemKind::Bottle(bottle) | ItemKind::Thrown(bottle) => Some(self.bottle_parts(bottle)),
            _ => None,
        };
        // A bottle of a potion is listed under the potion's key, like the world markers do (a
        // mixture is just a bottle).
        let kind = match &it.kind {
            ItemKind::Bottle(b) if b.parts.len() == 1 && detail.starts_with("potion_") => {
                detail.clone()
            }
            other => other.label(),
        };
        EntityView {
            id: it.id,
            kind,
            x: b.x,
            y: b.y,
            w: b.w,
            h: b.h,
            hp: shown(it.hp.max(0.0)),
            hp_max: shown(it.hp_max),
            vx: it.body.vx,
            vy: it.body.vy,
            detail,
            statuses: Vec::new(),
            contents,
            wand,
        }
    }

    fn player_box(&self, p: &Player) -> Aabb {
        let (cx, cy) = p.body.cell();
        union(
            self.defs
                .player
                .hitboxes
                .iter()
                .map(|h| Aabb::new(cx + h.dx, cy + h.dy, h.w, h.h)),
        )
    }

    /// The player, enemies, items and projectiles, in that order (each in creation order).
    pub fn entities(&self) -> Vec<EntityView> {
        let mut out = Vec::new();
        if let Some(p) = &self.state.player {
            let b = self.player_box(p);
            out.push(EntityView {
                id: p.id,
                kind: "player".into(),
                x: b.x,
                y: b.y,
                w: b.w,
                h: b.h,
                hp: shown(p.vitals.hp),
                hp_max: shown(p.vitals.hp_max),
                vx: p.body.vx,
                vy: p.body.vy,
                detail: String::new(),
                statuses: statuses(&p.vitals),
                contents: None,
                wand: None,
            });
        }
        out.extend(self.state.enemies.iter().filter_map(|e| self.enemy_view(e)));
        out.extend(self.state.items.iter().map(|i| self.item_view(i)));
        for pr in &self.state.projectiles {
            let (x, y) = (pr.x.floor() as i32, pr.y.floor() as i32);
            out.push(EntityView {
                id: pr.id,
                kind: "projectile".into(),
                x,
                y,
                w: 1,
                h: 1,
                hp: 0.0,
                hp_max: 0.0,
                vx: pr.vx,
                vy: pr.vy,
                detail: pr.def.name.clone(),
                statuses: Vec::new(),
                contents: None,
                wand: None,
            });
        }
        out
    }

    pub fn wand_view(&self, held: &crate::entity::HeldWand) -> WandView {
        let wand = &held.wand;
        WandView {
            id: held.id,
            stats: wand.stats().clone(),
            slots: wand
                .slots()
                .iter()
                .map(|s| s.map(|s| (self.book.key(s.spell).to_string(), s.uses)))
                .collect(),
            always_cast: wand
                .always_cast()
                .iter()
                .map(|s| self.book.key(*s).to_string())
                .collect(),
            mana: wand.mana(),
            cooldown: wand.cooldown(),
        }
    }

    /// Which cells of the rectangle `[x, x + w) x [y, y + h)` are burning: one byte per cell,
    /// row-major, 1 for a burning cell and 0 for any other (and for cells outside the world,
    /// also those past the end of the `i32` range). Always `w * h` bytes. Read-only; the page
    /// that shows the world to a human draws fire from it. A negative size is an empty
    /// rectangle.
    pub fn burning_rect(&self, x: i32, y: i32, w: i32, h: i32) -> Vec<u8> {
        let (w, h) = (w.max(0), h.max(0));
        let grid = self.world.grid();
        let mut out = Vec::with_capacity(w as usize * h as usize);
        for dy in 0..h {
            for dx in 0..w {
                let lit = match (x.checked_add(dx), y.checked_add(dy)) {
                    (Some(cx), Some(cy)) => grid.get(cx, cy).burning(),
                    _ => false,
                };
                out.push(u8::from(lit));
            }
        }
        out
    }

    pub fn player(&self) -> Option<PlayerView> {
        let p = self.state.player.as_ref()?;
        let fly = &self.defs.player.fly;
        let hit = self.player_box(p);
        let (x, y) = p.body.cell();
        Some(PlayerView {
            id: p.id,
            x,
            y,
            w: p.body.w,
            h: p.body.h,
            hit: (hit.x, hit.y, hit.w, hit.h),
            vx: p.body.vx,
            vy: p.body.vy,
            hp: shown(p.vitals.hp),
            hp_max: shown(p.vitals.hp_max),
            dead: p.vitals.dead,
            facing: p.facing,
            // Read from the grid as it is now (the end of the last frame), not as it was when the
            // player moved.
            on_ground: p.body.grounded(&self.world),
            fly: p.fly_meter / fly.meter_frames,
            breath: p.breath as f32 / self.defs.player.air_frames as f32,
            invincible: p.vitals.invincible,
            aim: p.aim,
            active_wand: p.active_wand,
            active_bottle: p.active_bottle,
            wands: p.wands.iter().map(|w| self.wand_view(w)).collect(),
            spells: p
                .spells
                .iter()
                .map(|s| (self.book.key(s.spell).to_string(), s.uses))
                .collect(),
            bottles: p
                .bottles
                .iter()
                .map(|b| (self.bottle_key(b), b.total()))
                .collect(),
            bottle_contents: p.bottles.iter().map(|b| self.bottle_parts(b)).collect(),
            statuses: statuses(&p.vitals),
        })
    }
}
