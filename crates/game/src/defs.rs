//! Entity numbers: `content/entities.json` (`cogbench-entities/0`).
//!
//! Everything about the player, enemies, barrels, bottles, statuses and the world wand tiers lives
//! in that file; no code in this crate hard-codes such a number (see the quality guidelines).
//! Damage is in internal units (player max HP 4.0 is shown as 100), time in frames, lengths in
//! px, speeds in px/s. A box `{dx, dy, w, h}` is relative to the top-left corner of the entity's
//! collision box.

use std::collections::BTreeMap;
use std::path::Path;

use serde::Deserialize;

use crate::error::Error;
use crate::status::Status;
use crate::wand::WandStats;

pub const FORMAT: &str = "cogbench-entities/0";
/// Shortest windup of a melee attack and of a lunge or ranged attack: one and two decision
/// ticks of 10 frames (tick-design section 4), so an agent can see an attack coming.
const MIN_MELEE_WINDUP: u32 = 10;
const MIN_SLOW_WINDUP: u32 = 20;
const EMBEDDED: &str = include_str!("../../../content/entities.json");
const EMBEDDED_NAME: &str = "content/entities.json";

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct SizeDef {
    pub w: i32,
    pub h: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct BoxDef {
    pub dx: i32,
    pub dy: i32,
    pub w: i32,
    pub h: i32,
    /// Damage multiplier of a hit inside this box (a head counts more).
    pub mult: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct SimDef {
    /// Enemies, items and barrels further than this from the player (Chebyshev, px) sleep.
    pub active_range: i32,
    /// A resting item checks its floor every this many frames.
    pub wake_check_interval: u64,
    /// Contact, fire and poison damage is logged as one event per this many frames.
    pub event_damage_interval: u64,
    pub max_projectiles: usize,
    /// A trail of `amount` leaves `amount / trail_divisor` cells per frame (at least one).
    pub trail_divisor: u32,
    /// Knockback speed (px/s) a projectile gives per unit of its `knockback`.
    pub hit_knockback: f32,
    /// Cells a flying fireball tries to ignite per frame inside its ignite radius.
    pub ignite_samples_per_frame: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct FlyDef {
    pub meter_frames: f32,
    pub speed_up: f32,
    pub speed_down: f32,
    pub speed_x: f32,
    pub change: f32,
    pub recharge_ground: f32,
    pub recharge_air: f32,
    pub air_wait_frames: u32,
    pub press_cost_frames: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct SwimDef {
    pub gravity_mul: f32,
    pub drag: f32,
    pub up_speed: f32,
    pub speed_mul: f32,
    pub min_submerged_percent: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct HandDef {
    pub dx: i32,
    pub dy: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct KickDef {
    pub cooldown: u32,
    pub reach: i32,
    pub height: i32,
    pub damage: f32,
    pub item_speed: f32,
    pub item_lift: f32,
    pub enemy_speed: f32,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct PlayerDef {
    pub hp: f32,
    pub mass: f32,
    pub collision: SizeDef,
    pub hitboxes: Vec<BoxDef>,
    pub gravity: f32,
    pub walk_speed: f32,
    pub accel_ground: f32,
    pub accel_air: f32,
    pub jump_speed: f32,
    pub fall_speed_max: f32,
    pub step_up: i32,
    pub fly: FlyDef,
    pub swim: SwimDef,
    pub air_frames: u32,
    pub drown_damage_per_frame: f32,
    pub invincible_frames: u32,
    pub damage_mult: BTreeMap<String, f32>,
    pub hand: HandDef,
    pub muzzle_distance: f32,
    pub pickup_radius: f32,
    pub kick: KickDef,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct StatusFrames {
    pub frames: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct OnFireDef {
    pub frames: u32,
    pub damage_per_s: f32,
    pub oiled_frames_mul: u32,
    pub emit_percent: u32,
    pub speed_mul: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct PoisonDef {
    pub frames: u32,
    pub damage_pct_per_s: f32,
    pub floor_pct: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct HasteDef {
    pub frames: u32,
    pub speed_mul: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct DrunkDef {
    pub frames: u32,
    pub aim_jitter_degrees: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct RegenDef {
    pub frames: u32,
    pub heal_pct_per_s: f32,
}

/// Secret potion: held wands regain mana `mana_mul` times as fast.
#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct ManaRegenDef {
    pub frames: u32,
    pub mana_mul: f32,
}

/// Secret potion: `bonus_percent` percentage points of critical chance on the player's hits.
#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct CritBoostDef {
    pub frames: u32,
    pub bonus_percent: f32,
}

/// Secret potion: the player's projectile hits and explosions do `damage_mul` times the damage.
#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct BerserkDef {
    pub frames: u32,
    pub damage_mul: f32,
}

/// Secret potion: enemies do not notice the player; casting or kicking shows the player for
/// `reveal_frames` frames.
#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct InvisibleDef {
    pub frames: u32,
    pub reveal_frames: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct StatusDefs {
    pub wet: StatusFrames,
    pub oiled: StatusFrames,
    pub on_fire: OnFireDef,
    pub poisoned: PoisonDef,
    pub haste: HasteDef,
    pub drunk: DrunkDef,
    pub regeneration: RegenDef,
    pub invulnerable: StatusFrames,
    pub mana_regen: ManaRegenDef,
    pub crit_boost: CritBoostDef,
    pub berserk: BerserkDef,
    pub levitation: StatusFrames,
    pub invisible: InvisibleDef,
    pub fireproof: StatusFrames,
}

impl StatusDefs {
    /// Default duration of a status in frames.
    pub fn frames(&self, status: Status) -> u32 {
        match status {
            Status::Wet => self.wet.frames,
            Status::Oiled => self.oiled.frames,
            Status::OnFire => self.on_fire.frames,
            Status::Poisoned => self.poisoned.frames,
            Status::Haste => self.haste.frames,
            Status::Drunk => self.drunk.frames,
            Status::Regeneration => self.regeneration.frames,
            Status::Invulnerable => self.invulnerable.frames,
            Status::ManaRegen => self.mana_regen.frames,
            Status::CritBoost => self.crit_boost.frames,
            Status::Berserk => self.berserk.frames,
            Status::Levitation => self.levitation.frames,
            Status::Invisible => self.invisible.frames,
            Status::Fireproof => self.fireproof.frames,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct ContactDef {
    /// A material gives a status from this many cells of the hitbox.
    pub min_cells: u32,
    pub ignite_min_cells: u32,
    /// Material key to the status it gives.
    pub status: BTreeMap<String, String>,
    /// Materials that set an entity alight even when it is wet (lava). Fire cells and burning
    /// cells do too, unless the entity is wet.
    pub ignite: Vec<String>,
    /// Healing per cell and frame of a material (the healing pool).
    pub heal_per_px_frame: BTreeMap<String, f32>,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct FloorDef {
    pub radius: u32,
    pub damage: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct BlastDef {
    pub damage: f32,
    pub ray_energy: u32,
    pub max_durability: u32,
    pub fire_percent: u32,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct ExplosionDefs {
    pub knockback_speed: f32,
    pub chain_limit_per_frame: usize,
    /// Minimum explosion damage by the radius of the explosion (DUR-R08), ascending.
    pub damage_floor: Vec<FloorDef>,
    pub default: BlastDef,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct ExplosionBlock {
    pub radius: u32,
    pub damage: f32,
    pub ray_energy: u32,
    pub max_durability: u32,
    pub fire_percent: u32,
}

/// A projectile that is not a spell (enemy attacks).
#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct ProjDef {
    pub speed_min: f32,
    pub speed_max: f32,
    pub lifetime: u32,
    pub lifetime_jitter: u32,
    pub gravity: f32,
    pub air_friction: f32,
    pub bounces: u32,
    pub bounce_energy: f32,
    pub hit_damage: f32,
    pub knockback: f32,
    #[serde(default)]
    pub die_on_liquid: bool,
    #[serde(default)]
    pub ignite_radius: u32,
    pub explosion: Option<ExplosionBlock>,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct FleeDef {
    pub chance: u32,
    pub frames: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct MeleeDef {
    pub damage_min: f32,
    pub damage_max: f32,
    pub range: i32,
    pub interval: u32,
    pub windup: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct LungeDef {
    pub damage: f32,
    pub speed: f32,
    pub distance: i32,
    pub interval: u32,
    pub windup: u32,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct RangedDef {
    pub projectile: String,
    pub count_min: u32,
    pub count_max: u32,
    pub spread_degrees: f32,
    pub range: i32,
    pub interval: u32,
    pub windup: u32,
    pub keep_distance: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AiKind {
    Leaper,
    Shooter,
    Mage,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct EnemyDef {
    pub name_en: String,
    pub hp: f32,
    pub mass: f32,
    pub collision: SizeDef,
    pub hitboxes: Vec<BoxDef>,
    pub gravity: f32,
    pub run_speed: f32,
    pub jump_speed: f32,
    pub step_up: i32,
    pub ai: AiKind,
    pub detect: SizeDef,
    pub flee: FleeDef,
    pub melee: MeleeDef,
    pub lunge: Option<LungeDef>,
    pub ranged: Option<RangedDef>,
    pub ignite_percent: u32,
    #[serde(default)]
    pub wet_damage_per_s: f32,
    pub damage_mult: BTreeMap<String, f32>,
    /// Per-cell contact damage by material key; empty means the table of `materials.json`.
    pub contact_damage: BTreeMap<String, f32>,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct BottleDef {
    pub w: i32,
    pub h: i32,
    pub mass: f32,
    pub capacity: u32,
    pub max_held: usize,
    pub fill_cells_per_frame: u32,
    pub pour_cells_per_frame: u32,
    pub drink_cells_per_frame: u32,
    /// Cells of each ingredient that turn into a secret potion per frame inside a bottle.
    pub mix_cells_per_frame: u32,
    pub throw_speed: f32,
    pub throw_lift: f32,
    pub spill_radius: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct BombDef {
    pub w: i32,
    pub h: i32,
    pub mass: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
pub struct HeldDef {
    pub w: i32,
    pub h: i32,
    pub mass: f32,
    pub max_held: usize,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct ContentsDef {
    pub material: String,
    pub cells: u32,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct BarrelDef {
    pub w: i32,
    pub h: i32,
    pub hp: f32,
    pub mass: f32,
    #[serde(default)]
    pub fuse_frames: u32,
    #[serde(default)]
    pub burn_frames: u32,
    #[serde(default)]
    pub spill_radius: i32,
    pub contents: Option<ContentsDef>,
    pub explosion: Option<ExplosionBlock>,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct ItemDefs {
    pub gravity: f32,
    pub bounce: f32,
    pub ground_friction: f32,
    pub step_up: i32,
    pub bottle: BottleDef,
    pub wand: HeldDef,
    pub spell: HeldDef,
    pub bomb: BombDef,
    pub barrels: BTreeMap<String, BarrelDef>,
}

/// What drinking one cell of a material does.
#[derive(Clone, Debug, Default, PartialEq, Deserialize)]
pub struct DrinkDef {
    #[serde(default)]
    pub heal_per_cell: f32,
    #[serde(default)]
    pub mana_per_cell: f32,
    #[serde(default)]
    pub damage_per_cell: f32,
    pub status: Option<String>,
    /// Frames of the status per swallowed cell (may be fractional: 1.5 gives a full 400-cell
    /// bottle 10 seconds).
    #[serde(default)]
    pub frames_per_cell: f32,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct StarterWand {
    pub name: String,
    pub stats: WandStats,
    pub spells: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct StarterDef {
    pub wands: Vec<StarterWand>,
}

/// Inclusive ranges `[min, max]` a generated wand of one tier draws its numbers from.
#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct WandTierDef {
    pub capacity: [u32; 2],
    pub spells_per_cast: [u32; 2],
    pub cast_delay: [i32; 2],
    pub recharge: [i32; 2],
    pub mana_max: [u32; 2],
    pub mana_charge_speed: [u32; 2],
    pub spread: [i32; 2],
    pub shuffle_percent: u32,
    pub spell_count: [u32; 2],
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct EntityDefs {
    pub format: String,
    pub sim: SimDef,
    pub player: PlayerDef,
    pub statuses: StatusDefs,
    pub contact: ContactDef,
    pub explosion: ExplosionDefs,
    pub projectiles: BTreeMap<String, ProjDef>,
    pub enemies: BTreeMap<String, EnemyDef>,
    pub items: ItemDefs,
    pub drink: BTreeMap<String, DrinkDef>,
    pub starter: StarterDef,
    pub wand_tiers: BTreeMap<String, WandTierDef>,
    pub spell_pickup_weights: BTreeMap<String, u32>,
    /// Spells that random loot (spell pickups, generated wands) never contains: the world places
    /// them by hand. Keys of `spells.json`.
    #[serde(default)]
    pub spell_pickup_exclude: Vec<String>,
}

impl EntityDefs {
    /// The file compiled into this crate.
    pub fn embedded() -> Result<EntityDefs, Error> {
        EntityDefs::from_json(EMBEDDED, EMBEDDED_NAME)
    }

    pub fn load(path: &Path) -> Result<EntityDefs, Error> {
        let text = std::fs::read_to_string(path).map_err(|source| Error::Io {
            path: path.to_path_buf(),
            source,
        })?;
        EntityDefs::from_json(&text, &path.display().to_string())
    }

    pub fn from_json(text: &str, file: &str) -> Result<EntityDefs, Error> {
        let defs: EntityDefs =
            serde_json::from_str(text).map_err(|e| Error::content(file, "", e.to_string()))?;
        if defs.format != FORMAT {
            let found = &defs.format;
            return Err(Error::content(
                file,
                "format",
                format!("expected {FORMAT:?}, found {found:?}"),
            ));
        }
        defs.validate(file)?;
        Ok(defs)
    }

    fn validate(&self, file: &str) -> Result<(), Error> {
        let bad = |field: String, message: String| Err(Error::content(file, field, message));
        self.validate_enemies(file)?;
        self.validate_sizes(file)?;
        self.validate_tiers(file)?;
        for (field, status) in self.contact.status.iter().chain(
            self.drink
                .iter()
                .filter_map(|(k, d)| d.status.as_ref().map(|s| (k, s))),
        ) {
            if Status::parse(status).is_none() {
                return bad(field.clone(), format!("unknown status {status:?}"));
            }
        }
        if self
            .explosion
            .damage_floor
            .windows(2)
            .any(|w| w[0].radius >= w[1].radius)
        {
            return bad("explosion.damage_floor".into(), "radii must ascend".into());
        }
        for key in self.items.barrels.keys() {
            if !key.starts_with("barrel_") {
                return bad(
                    format!("items.barrels.{key}"),
                    "keys start with barrel_".into(),
                );
            }
        }
        Ok(())
    }

    fn validate_enemies(&self, file: &str) -> Result<(), Error> {
        let bad = |field: String, message: String| Err(Error::content(file, field, message));
        for (key, enemy) in &self.enemies {
            if let Some(r) = &enemy.ranged {
                if !self.projectiles.contains_key(&r.projectile) {
                    let message = format!("unknown projectile {:?}", r.projectile);
                    return bad(format!("enemies.{key}.ranged.projectile"), message);
                }
                if r.count_min == 0 || r.count_min > r.count_max {
                    return bad(
                        format!("enemies.{key}.ranged"),
                        "count_min must be 1..=count_max".into(),
                    );
                }
                if r.windup < MIN_SLOW_WINDUP {
                    let message = format!("windup must be at least {MIN_SLOW_WINDUP} frames");
                    return bad(format!("enemies.{key}.ranged.windup"), message);
                }
            }
            if enemy.ai != AiKind::Leaper && enemy.ranged.is_none() {
                return bad(
                    format!("enemies.{key}.ranged"),
                    "shooters and mages need a ranged attack".into(),
                );
            }
            if enemy.hitboxes.is_empty() || enemy.hp <= 0.0 {
                return bad(
                    format!("enemies.{key}"),
                    "needs hitboxes and positive hp".into(),
                );
            }
            // An attack must be visible for at least one decision tick (tick-design section 4).
            let lunge = enemy.lunge.map_or(MIN_SLOW_WINDUP, |l| l.windup);
            if enemy.melee.windup < MIN_MELEE_WINDUP || lunge < MIN_SLOW_WINDUP {
                let message = format!(
                    "windups must be at least {MIN_MELEE_WINDUP} frames (melee) and \
                     {MIN_SLOW_WINDUP} frames (lunge, ranged)"
                );
                return bad(format!("enemies.{key}"), message);
            }
        }
        Ok(())
    }

    fn validate_sizes(&self, file: &str) -> Result<(), Error> {
        let bad = |field: String, message: String| Err(Error::content(file, field, message));
        if self.player.hitboxes.is_empty() {
            return bad("player.hitboxes".into(), "needs at least one box".into());
        }
        let boxes = self
            .player
            .hitboxes
            .iter()
            .map(|b| ("player.hitboxes".to_string(), b))
            .chain(self.enemies.iter().flat_map(|(k, e)| {
                e.hitboxes
                    .iter()
                    .map(move |b| (format!("enemies.{k}.hitboxes"), b))
            }));
        for (field, b) in boxes {
            if b.w <= 0 || b.h <= 0 || b.mult < 0.0 {
                return bad(
                    field,
                    "boxes need positive w and h and a mult of 0 or more".into(),
                );
            }
        }
        let collisions = [("player".to_string(), self.player.collision)]
            .into_iter()
            .chain(
                self.enemies
                    .iter()
                    .map(|(k, e)| (format!("enemies.{k}"), e.collision)),
            );
        for (field, c) in collisions {
            if c.w <= 0 || c.h <= 0 {
                return bad(
                    format!("{field}.collision"),
                    "w and h must be positive".into(),
                );
            }
        }
        let sim = &self.sim;
        let positive = [
            ("sim.active_range", sim.active_range > 0),
            ("sim.wake_check_interval", sim.wake_check_interval > 0),
            ("sim.event_damage_interval", sim.event_damage_interval > 0),
            ("sim.max_projectiles", sim.max_projectiles > 0),
            ("items.bottle.capacity", self.items.bottle.capacity > 0),
            (
                "items.bottle.mix_cells_per_frame",
                self.items.bottle.mix_cells_per_frame > 0,
            ),
            (
                "player.fly.meter_frames",
                self.player.fly.meter_frames > 0.0,
            ),
            ("player.air_frames", self.player.air_frames > 0),
        ];
        match positive.iter().find(|(_, ok)| !ok) {
            Some((field, _)) => bad((*field).to_string(), "must be positive".into()),
            None => Ok(()),
        }
    }

    /// Wand tiers: keys are numbers and every `[min, max]` range runs upward.
    fn validate_tiers(&self, file: &str) -> Result<(), Error> {
        let bad = |field: String, message: String| Err(Error::content(file, field, message));
        for (key, t) in &self.wand_tiers {
            if key.parse::<u32>().is_err() {
                return bad(format!("wand_tiers.{key}"), "tier keys are numbers".into());
            }
            let ranges = [
                ("capacity", t.capacity.map(i64::from)),
                ("spells_per_cast", t.spells_per_cast.map(i64::from)),
                ("cast_delay", t.cast_delay.map(i64::from)),
                ("recharge", t.recharge.map(i64::from)),
                ("mana_max", t.mana_max.map(i64::from)),
                ("mana_charge_speed", t.mana_charge_speed.map(i64::from)),
                ("spread", t.spread.map(i64::from)),
                ("spell_count", t.spell_count.map(i64::from)),
            ];
            for (name, [lo, hi]) in ranges {
                if lo > hi {
                    let message = format!("range [{lo}, {hi}] must run from low to high");
                    return bad(format!("wand_tiers.{key}.{name}"), message);
                }
            }
            if t.capacity[0] == 0 || t.spells_per_cast[0] == 0 || t.spell_count[0] == 0 {
                let message = "capacity, spells_per_cast and spell_count start at 1".to_string();
                return bad(format!("wand_tiers.{key}"), message);
            }
        }
        Ok(())
    }

    /// The minimum explosion damage for an explosion of this radius (DUR-R08): the entry with
    /// the largest radius not above `radius`; 0 below the first.
    pub fn damage_floor(&self, radius: u32) -> f32 {
        self.explosion
            .damage_floor
            .iter()
            .rev()
            .find(|f| radius >= f.radius)
            .map_or(0.0, |f| f.damage)
    }
}
