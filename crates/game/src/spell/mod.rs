//! The spell catalogue (`content/spells.json`, `cogbench-spells/0`).
//!
//! Plain data: what a spell costs, what it does to the shot state while the wand deals the cards
//! (`ShotDelta`), and what a projectile it spawns does in the world (`ProjectileSpec`, read by the
//! projectile code, not by the casting engine). Damage is in *internal* units (player max HP 4.0 is
//! shown as 100); time in frames, lengths in px, speeds in px/s, angles in degrees.

mod book;

use serde::{Deserialize, Serialize};

pub use book::SpellBook;

/// Index of a spell in the catalogue: its position in `content/spells.json` (append only).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(transparent)]
pub struct SpellId(pub u16);

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SpellType {
    Projectile,
    StaticProjectile,
    Modifier,
    Multicast,
    Material,
}

impl SpellType {
    /// Cards that put something into the world (they count for `got_projectiles`, WAND-R63).
    pub fn adds_projectile(self) -> bool {
        matches!(
            self,
            SpellType::Projectile | SpellType::StaticProjectile | SpellType::Material
        )
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TriggerKind {
    /// Payload is released when the projectile hits something.
    Collision,
    /// Payload is released after `timer_frames`, or on collision if that comes first.
    Timer,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct TriggerSpec {
    pub kind: TriggerKind,
    pub timer_frames: Option<u32>,
    /// Cards drawn for the payload at cast time (WAND-R42).
    pub payload_draws: u32,
}

/// Status a spell puts on whatever its projectile hits.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Effect {
    Wet,
    Oiled,
    OnFire,
}

/// A material the projectile leaves along its path.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TrailSpec {
    pub material: String,
    pub amount: u32,
}

/// What playing the card adds to the current shot state (WAND-R30..R33).
#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct ShotDelta {
    pub spread: f32,
    /// Multiplier on the projectile speed; the running product is clamped to 0..=20.
    pub speed_mul: f32,
    pub damage: f32,
    pub explosion_damage: f32,
    pub explosion_radius: f32,
    /// Raises the max durability the modified projectile's explosion can remove (cogbench
    /// extension, `v1-scope.md` section 5). Bonuses of several cards do not add up: the largest
    /// one counts. Absent in older files, which means 0.
    #[serde(default)]
    pub explosion_durability: u32,
    pub crit_chance: f32,
    pub bounces: i32,
    pub trail: Vec<TrailSpec>,
    pub effects: Vec<Effect>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BodyKind {
    /// Flies along a path (gravity and air friction), dies on contact.
    Projectile,
    /// A simple ballistic object with a fuse (bomb): gravity, bounce, no rotation.
    ThrownBody,
    /// Appears at the caster and acts at once (explosion).
    Static,
    /// A blob of material that lands and turns into cells.
    MaterialParticle,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct ExplosionSpec {
    pub radius: u32,
    pub damage: f32,
    pub ray_energy: u32,
    pub max_durability: u32,
    pub cell_material: Option<String>,
    /// Chance in percent that a destroyed cell is replaced by `cell_material`.
    pub cell_percent: u32,
    pub hole_destroy_liquid: bool,
    pub on_death: bool,
    pub on_lifetime_out: bool,
    pub dont_damage_shooter: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
pub struct EmitSpec {
    pub material: String,
    pub count: u32,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct ProjectileSpec {
    pub body: BodyKind,
    pub speed_min: f32,
    pub speed_max: f32,
    pub lifetime: u32,
    pub lifetime_jitter: u32,
    pub gravity: f32,
    pub air_friction: f32,
    pub mass: f32,
    /// Spread built into the projectile itself, added to the shot's spread.
    pub innate_spread: f32,
    pub bounces: u32,
    pub bounce_energy: f32,
    pub bounce_always: bool,
    pub on_collision_die: bool,
    pub die_on_low_velocity: Option<f32>,
    pub die_on_liquid: bool,
    /// Damage of a direct hit (all damage types of the original, summed: one damage type here).
    pub hit_damage: f32,
    pub damage_scaled_by_speed: bool,
    pub knockback: f32,
    /// Hit points of a projectile that can be shot (the bomb).
    pub hp: Option<f32>,
    /// Radius in which the flying projectile ignites materials (fireball).
    pub ignite_radius: u32,
    pub emit: Option<EmitSpec>,
    pub explosion: Option<ExplosionSpec>,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct Spell {
    /// Upper snake case id, e.g. `LIGHT_BULLET`. Never shown as a different name elsewhere.
    pub key: String,
    pub name_en: String,
    pub name_zh: String,
    #[serde(rename = "type")]
    pub kind: SpellType,
    /// Mana drained when the card is drawn; negative adds mana (WAND-R06).
    pub mana: i32,
    /// `None` is unlimited.
    pub max_uses: Option<u32>,
    /// Cards a *played* modifier (1) or multicast (N) draws from the same shot (WAND-R24).
    pub draw: u32,
    pub trigger: Option<TriggerSpec>,
    /// Frames added to the shot's cast delay (WAND-R53).
    pub cast_delay: i32,
    /// Frames added to the running recharge time, wherever the card is played (WAND-R52).
    pub recharge: i32,
    pub recoil: f32,
    pub shot: ShotDelta,
    pub projectile: Option<ProjectileSpec>,
}
