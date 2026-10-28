//! Putting entities into the world: the player with the starter loadout, enemies and items.
//!
//! A position `(x, y)` is the cell the entity stands in: the free cell directly above the floor
//! (the convention of the world file markers, contract section 4). The collision box is placed
//! with its bottom row on `y` and centred on `x`.

use crate::entity::{Bottle, Enemy, EntityId, HeldWand, Item, ItemKind, Player, Vitals};
use crate::error::Error;
use crate::physics::Body;
use crate::rng::{mix64, SpellRng};
use crate::wand::{Slot, Wand, WandStats};

use super::Game;

/// What to put into the world as an item.
#[derive(Clone, Debug, PartialEq)]
pub enum ItemSpec {
    /// A bottle; `material` is the key of the liquid inside (`None` = empty), `amount` defaults
    /// to a full bottle.
    Bottle {
        material: Option<String>,
        amount: Option<u32>,
    },
    /// A bottle holding a mixture: material keys with cells (at most a bottle's capacity in all).
    MixedBottle { contents: Vec<(String, u32)> },
    /// A wand generated for a tier (1 to 3).
    Wand { tier: u32 },
    /// A wand with explicit stats and spells (keys, `None` leaves a slot empty).
    CustomWand {
        stats: WandStats,
        spells: Vec<Option<String>>,
    },
    /// A spell card; `None` picks a random one.
    Spell { key: Option<String> },
    /// A barrel: `barrel_gunpowder`, `barrel_acid` or `barrel_oil`.
    Barrel { kind: String },
}

impl Game {
    /// The seed of a wand's own card-dealing streams (contract section 9).
    pub(crate) fn wand_rng(&self, id: EntityId) -> SpellRng {
        SpellRng::new(mix64(
            self.world.seed() ^ (u64::from(id) + 1).wrapping_mul(0x9E37_79B9_7F4A_7C15),
        ))
    }

    /// A new wand with a fresh id and its own random stream.
    pub fn make_wand(
        &mut self,
        stats: WandStats,
        spells: &[Option<String>],
        always_cast: &[String],
    ) -> Result<HeldWand, Error> {
        let lookup = |key: &String| {
            self.book
                .id(key)
                .ok_or_else(|| Error::arg(format!("unknown spell {key:?}")))
        };
        let ids = spells
            .iter()
            .map(|s| s.as_ref().map(lookup).transpose())
            .collect::<Result<Vec<_>, _>>()?;
        let always = always_cast
            .iter()
            .map(lookup)
            .collect::<Result<Vec<_>, _>>()?;
        let wand = Wand::new(&self.book, stats, &ids, &always)?;
        let id = self.state.fresh_id();
        Ok(HeldWand {
            id,
            rng: self.wand_rng(id),
            wand,
        })
    }

    /// A bottle of one material (`None` = empty); `amount` defaults to a full bottle and is cut
    /// to the capacity.
    pub(crate) fn single_bottle(
        &self,
        material: Option<&str>,
        amount: Option<u32>,
    ) -> Result<Bottle, Error> {
        let capacity = self.defs.items.bottle.capacity;
        match material {
            None => Ok(Bottle::default()),
            Some(key) => {
                let m = self
                    .mat_index(key)
                    .ok_or_else(|| Error::arg(format!("unknown material {key:?}")))?;
                Ok(Bottle::single(m, amount.unwrap_or(capacity).min(capacity)))
            }
        }
    }

    /// A bottle holding a mixture. Unknown materials and more cells than the capacity are errors.
    pub(crate) fn mixed_bottle(&self, contents: &[(String, u32)]) -> Result<Bottle, Error> {
        let capacity = self.defs.items.bottle.capacity;
        // Add the cells up in 64 bits before anything is put in a bottle: huge amounts from a
        // caller must be refused, not wrap around to a small number.
        let total: u64 = contents.iter().map(|(_, cells)| u64::from(*cells)).sum();
        if total > u64::from(capacity) {
            return Err(Error::arg(format!(
                "the contents add up to {total} cells; a bottle holds {capacity}"
            )));
        }
        let mut bottle = Bottle::default();
        for (key, cells) in contents {
            let m = self
                .mat_index(key)
                .ok_or_else(|| Error::arg(format!("unknown material {key:?}")))?;
            bottle.add(m, *cells);
        }
        Ok(bottle)
    }

    fn body_at(&self, x: i32, y: i32, w: i32, h: i32) -> Result<Body, Error> {
        if !self.world.grid().in_bounds(x, y) {
            let (ww, wh) = (self.world.width(), self.world.height());
            return Err(Error::arg(format!(
                "position ({x}, {y}) is outside the {ww}x{wh} world"
            )));
        }
        Ok(Body::new(x - w / 2, y - h + 1, w, h))
    }

    /// Put the player into the world with the starter wands (a spark wand and a digger).
    pub fn spawn_player(&mut self, x: i32, y: i32) -> Result<EntityId, Error> {
        if self.state.player.is_some() {
            return Err(Error::arg("there is already a player"));
        }
        let defs = self.defs.clone();
        let pd = &defs.player;
        let body = self.body_at(x, y, pd.collision.w, pd.collision.h)?;
        let id = self.state.fresh_id();
        let mut wands = Vec::new();
        for w in &defs.starter.wands {
            let spells: Vec<Option<String>> = w.spells.iter().cloned().map(Some).collect();
            wands.push(self.make_wand(w.stats.clone(), &spells, &[])?);
        }
        self.state.player = Some(Player {
            id,
            body,
            vitals: Vitals::new(pd.hp, pd.invincible_frames),
            facing: 1,
            fly_meter: pd.fly.meter_frames,
            air_wait: 0,
            breath: pd.air_frames,
            kick_cooldown: 0,
            aim: 0.0,
            wands,
            active_wand: 0,
            spells: Vec::new(),
            bottles: Vec::new(),
            active_bottle: 0,
            action: None,
            revealed: 0,
        });
        Ok(id)
    }

    pub fn spawn_enemy(&mut self, kind: &str, x: i32, y: i32) -> Result<EntityId, Error> {
        let defs = self.defs.clone();
        let def = defs.enemies.get(kind).ok_or_else(|| {
            let known: Vec<&str> = defs.enemies.keys().map(String::as_str).collect();
            Error::arg(format!(
                "unknown enemy {kind:?}; known: {}",
                known.join(", ")
            ))
        })?;
        let body = self.body_at(x, y, def.collision.w, def.collision.h)?;
        let id = self.state.fresh_id();
        let facing = if id.is_multiple_of(2) { 1 } else { -1 };
        self.state.enemies.push(Enemy {
            id,
            kind: kind.to_string(),
            body,
            vitals: Vitals::new(def.hp, 0),
            facing,
            alert: 0,
            flee: 0,
            patrol_dir: facing,
            patrol_left: 0,
            melee_cooldown: 0,
            ranged_cooldown: 0,
            lunge_cooldown: 0,
            windup: None,
            lunging: 0,
            last_hp: def.hp,
        });
        Ok(id)
    }

    /// Put an item into the world. Random choices (a random spell, a generated wand) are drawn
    /// from the `spawn` stream with the id the item gets, so they depend only on the world seed
    /// and the order of spawning.
    pub fn spawn_item(&mut self, spec: &ItemSpec, x: i32, y: i32) -> Result<EntityId, Error> {
        let salt = u64::from(self.state.next_id);
        self.spawn_item_salted(spec, x, y, salt)
    }

    /// As [`Game::spawn_item`], with the salt that keys the random choices (the world loader
    /// passes the marker index, so the loot does not depend on how many entities came before).
    pub(crate) fn spawn_item_salted(
        &mut self,
        spec: &ItemSpec,
        x: i32,
        y: i32,
        salt: u64,
    ) -> Result<EntityId, Error> {
        let defs = self.defs.clone();
        let items = &defs.items;
        let (kind, w, h, hp) = match spec {
            ItemSpec::Bottle { material, amount } => {
                let bottle = self.single_bottle(material.as_deref(), *amount)?;
                let b = &items.bottle;
                (ItemKind::Bottle(bottle), b.w, b.h, 0.0)
            }
            ItemSpec::MixedBottle { contents } => {
                let bottle = self.mixed_bottle(contents)?;
                let b = &items.bottle;
                (ItemKind::Bottle(bottle), b.w, b.h, 0.0)
            }
            ItemSpec::Wand { tier } => {
                let (stats, spells) = self.generate_wand(*tier, salt)?;
                let keys: Vec<Option<String>> = spells
                    .iter()
                    .map(|s| s.map(|id| self.book.key(id).to_string()))
                    .collect();
                let held = self.make_wand(stats, &keys, &[])?;
                let d = &items.wand;
                (ItemKind::Wand(Box::new(held)), d.w, d.h, 0.0)
            }
            ItemSpec::CustomWand { stats, spells } => {
                let held = self.make_wand(stats.clone(), spells, &[])?;
                let d = &items.wand;
                (ItemKind::Wand(Box::new(held)), d.w, d.h, 0.0)
            }
            ItemSpec::Spell { key } => {
                let id = match key {
                    Some(k) => self
                        .book
                        .id(k)
                        .ok_or_else(|| Error::arg(format!("unknown spell {k:?}")))?,
                    None => self.random_spell(salt)?,
                };
                let slot = Slot {
                    spell: id,
                    uses: self.book.get(id).max_uses,
                };
                let d = &items.spell;
                (ItemKind::Spell(slot), d.w, d.h, 0.0)
            }
            ItemSpec::Barrel { kind } => {
                let b = items.barrels.get(kind).ok_or_else(|| {
                    let known: Vec<&str> = items.barrels.keys().map(String::as_str).collect();
                    Error::arg(format!(
                        "unknown barrel {kind:?}; known: {}",
                        known.join(", ")
                    ))
                })?;
                (ItemKind::Barrel(kind.clone()), b.w, b.h, b.hp)
            }
        };
        let body = self.body_at(x, y, w, h)?;
        let id = self.state.fresh_id();
        self.state.items.push(Item {
            id,
            body,
            kind,
            hp,
            hp_max: hp,
            asleep: false,
            lit: 0,
            dead: false,
            logged_damage: 0.0,
        });
        Ok(id)
    }
}
