//! Projectiles: what a cast or an enemy attack puts into the world, as plain serialisable data.
//!
//! A [`ProjectileDef`] is a spell's projectile (or an enemy attack) with the modifiers of its
//! shot state already folded in: speed multiplier, damage, bounces, explosion radius and damage,
//! trails and statuses. Triggers and timers carry their payload as ready-made [`Shot`]s, drawn
//! and paid when the wand was cast (WAND-R40).

use cogbench_sim::MaterialSet;
use serde::{Deserialize, Serialize};

use crate::defs::{EntityDefs, ProjDef};
use crate::entity::{EntityId, Owner};
use crate::error::Error;
use crate::rng::HashRng;
use crate::spell::{BodyKind, Effect, SpellBook, TriggerKind};
use crate::status::Status;
use crate::wand::{ProjectileSpawn, ShotParams};

/// Projectiles never exceed this speed (SPELL-R23).
pub const TERMINAL_SPEED: f32 = 1000.0;
/// Critical hits deal this many times the damage (DAMAGE-R03).
pub const CRIT_MULTIPLIER: f32 = 5.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum BodyType {
    /// Flies along a path and dies on contact.
    Flying,
    /// A ballistic object with a fuse and hit points (bomb): gravity, bounce, no rotation.
    Thrown,
    /// Acts at once where it is cast (explosion spell).
    Static,
    /// A blob of material that turns into cells where it lands.
    Particle,
}

impl From<BodyKind> for BodyType {
    fn from(k: BodyKind) -> BodyType {
        match k {
            BodyKind::Projectile => BodyType::Flying,
            BodyKind::ThrownBody => BodyType::Thrown,
            BodyKind::Static => BodyType::Static,
            BodyKind::MaterialParticle => BodyType::Particle,
        }
    }
}

/// The blast of a projectile (`ConfigExplosion`).
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExplosionDef {
    pub radius: u32,
    pub damage: f32,
    pub ray_energy: u32,
    pub max_durability: u8,
    pub fire_percent: u8,
    pub on_death: bool,
    pub on_lifetime_out: bool,
    pub dont_damage_shooter: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ProjectileDef {
    /// Spell key (`LIGHT_BULLET`) or enemy attack key (`buckshot`), for events.
    pub name: String,
    pub body: BodyType,
    pub speed_min: f32,
    pub speed_max: f32,
    pub lifetime: u32,
    pub lifetime_jitter: u32,
    pub gravity: f32,
    pub air_friction: f32,
    pub bounces: i32,
    pub bounce_energy: f32,
    pub bounce_always: bool,
    pub on_collision_die: bool,
    pub die_on_low_velocity: Option<f32>,
    pub die_on_liquid: bool,
    pub hit_damage: f32,
    pub damage_scaled_by_speed: bool,
    pub knockback: f32,
    pub hp: Option<f32>,
    pub ignite_radius: u32,
    /// Material index and cells released where a particle lands.
    pub emit: Option<(u8, u32)>,
    pub explosion: Option<ExplosionDef>,
    /// Critical hit chance in percentage points.
    pub crit_chance: f32,
    /// Material index and amount of the trail left along the path.
    pub trail: Vec<(u8, u32)>,
    /// Statuses put on whatever the projectile hits.
    pub effects: Vec<Status>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TriggerDef {
    pub kind: TriggerKind,
    pub timer_frames: Option<u32>,
    pub payload: Vec<Shot>,
}

/// One projectile to create: its definition, its own deviation from the aim and its payload.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Shot {
    pub def: ProjectileDef,
    pub angle_offset: f32,
    pub trigger: Option<Box<TriggerDef>>,
}

fn effect_status(e: Effect) -> Status {
    match e {
        Effect::Wet => Status::Wet,
        Effect::Oiled => Status::Oiled,
        Effect::OnFire => Status::OnFire,
    }
}

fn material_index(mats: &MaterialSet, key: &str, what: &str) -> Result<u8, Error> {
    mats.index_of(key)
        .ok_or_else(|| Error::arg(format!("{what}: unknown material {key:?}")))
}

fn explosion_for(
    defs: &EntityDefs,
    spec: Option<&crate::spell::ExplosionSpec>,
    shot: &ShotParams,
) -> Option<ExplosionDef> {
    let extra = shot.explosion_radius.max(0.0).round() as u32;
    // Modifiers raise the durability the blast removes by the largest bonus among them.
    let max_durability = |base: u32| base.saturating_add(shot.explosion_durability).min(255) as u8;
    let mut e = match spec {
        Some(s) => ExplosionDef {
            radius: s.radius + extra,
            damage: s.damage + shot.explosion_damage,
            ray_energy: s.ray_energy,
            max_durability: max_durability(s.max_durability),
            fire_percent: if s.cell_material.as_deref() == Some("fire") {
                s.cell_percent.min(100) as u8
            } else {
                0
            },
            on_death: s.on_death,
            on_lifetime_out: s.on_lifetime_out,
            dont_damage_shooter: s.dont_damage_shooter,
        },
        None if extra > 0 => {
            // A radius modifier on a projectile without a blast gives it the default blast.
            let d = &defs.explosion.default;
            ExplosionDef {
                radius: extra,
                damage: d.damage + shot.explosion_damage,
                ray_energy: d.ray_energy,
                max_durability: max_durability(d.max_durability),
                fire_percent: d.fire_percent.min(100) as u8,
                on_death: true,
                on_lifetime_out: true,
                dont_damage_shooter: false,
            }
        }
        None => return None,
    };
    if extra > 0 {
        // SPELL-R32/R33: a positive radius modifier forces the blast on death and sets a floor.
        e.on_death = true;
        e.damage = e.damage.max(defs.damage_floor(e.radius));
    }
    Some(e)
}

/// The shot a wand projectile spawn stands for, payload included.
pub fn shot_from_spawn(
    book: &SpellBook,
    mats: &MaterialSet,
    defs: &EntityDefs,
    spawn: &ProjectileSpawn,
) -> Result<Shot, Error> {
    let spell = book.get(spawn.spell);
    let spec = spell
        .projectile
        .as_ref()
        .ok_or_else(|| Error::arg(format!("spell {} has no projectile", spell.key)))?;
    let shot = &spawn.shot;
    let mut trail = Vec::new();
    for t in &shot.trail {
        trail.push((material_index(mats, &t.material, &spell.key)?, t.amount));
    }
    let emit = match &spec.emit {
        Some(e) => Some((material_index(mats, &e.material, &spell.key)?, e.count)),
        None => None,
    };
    let def = ProjectileDef {
        name: spell.key.clone(),
        body: spec.body.into(),
        speed_min: spec.speed_min * shot.speed_mul,
        speed_max: spec.speed_max * shot.speed_mul,
        lifetime: spec.lifetime,
        lifetime_jitter: spec.lifetime_jitter,
        gravity: spec.gravity,
        air_friction: spec.air_friction,
        bounces: (spec.bounces as i32 + shot.bounces).max(0),
        bounce_energy: spec.bounce_energy,
        bounce_always: spec.bounce_always,
        on_collision_die: spec.on_collision_die,
        die_on_low_velocity: spec.die_on_low_velocity,
        die_on_liquid: spec.die_on_liquid,
        hit_damage: spec.hit_damage + shot.damage,
        damage_scaled_by_speed: spec.damage_scaled_by_speed,
        knockback: spec.knockback,
        hp: spec.hp,
        ignite_radius: spec.ignite_radius,
        emit,
        explosion: explosion_for(defs, spec.explosion.as_ref(), shot),
        crit_chance: shot.crit_chance,
        trail,
        effects: shot.effects.iter().map(|e| effect_status(*e)).collect(),
    };
    let trigger = match &spawn.trigger {
        Some(t) => {
            let payload = t
                .payload
                .iter()
                .map(|p| shot_from_spawn(book, mats, defs, p))
                .collect::<Result<Vec<_>, _>>()?;
            Some(Box::new(TriggerDef {
                kind: t.kind,
                timer_frames: t.timer_frames,
                payload,
            }))
        }
        None => None,
    };
    Ok(Shot {
        def,
        angle_offset: spawn.angle_offset_degrees,
        trigger,
    })
}

/// An enemy attack as a shot (no modifiers).
pub fn shot_from_enemy(name: &str, p: &ProjDef) -> Shot {
    let explosion = p.explosion.map(|e| ExplosionDef {
        radius: e.radius,
        damage: e.damage,
        ray_energy: e.ray_energy,
        max_durability: e.max_durability.min(255) as u8,
        fire_percent: e.fire_percent.min(100) as u8,
        on_death: true,
        on_lifetime_out: true,
        dont_damage_shooter: true,
    });
    Shot {
        def: ProjectileDef {
            name: name.to_string(),
            body: BodyType::Flying,
            speed_min: p.speed_min,
            speed_max: p.speed_max,
            lifetime: p.lifetime,
            lifetime_jitter: p.lifetime_jitter,
            gravity: p.gravity,
            air_friction: p.air_friction,
            bounces: p.bounces as i32,
            bounce_energy: p.bounce_energy,
            bounce_always: false,
            on_collision_die: true,
            die_on_low_velocity: None,
            die_on_liquid: p.die_on_liquid,
            hit_damage: p.hit_damage,
            damage_scaled_by_speed: false,
            knockback: p.knockback,
            hp: None,
            ignite_radius: p.ignite_radius,
            emit: None,
            explosion,
            crit_chance: 0.0,
            trail: Vec::new(),
            effects: Vec::new(),
        },
        angle_offset: 0.0,
        trigger: None,
    }
}

/// A projectile in flight.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Projectile {
    pub id: EntityId,
    pub owner: Owner,
    pub def: ProjectileDef,
    /// Centre of the projectile in cell coordinates (continuous).
    pub x: f32,
    pub y: f32,
    /// Velocity in px/s.
    pub vx: f32,
    pub vy: f32,
    pub speed0: f32,
    pub age: u32,
    pub life: i32,
    pub bounces_left: i32,
    pub trigger: Option<TriggerDef>,
    pub timer_left: Option<u32>,
    /// Unit vector the carrier was fired along (payloads leave along it when it has stopped).
    pub heading: (f32, f32),
}

impl Projectile {
    /// Create the projectile of `shot` at `origin` flying along the unit vector `dir`, turned by
    /// the shot's own spread offset. Speed and lifetime are rolled from the `ai` stream with the
    /// projectile id, so a replay with the same seed and controls rolls the same numbers.
    pub fn launch(
        id: EntityId,
        owner: Owner,
        shot: &Shot,
        origin: (f32, f32),
        dir: (f32, f32),
        rng: &HashRng,
        frame: u64,
    ) -> Projectile {
        let def = shot.def.clone();
        let u = rng.unit(frame, u64::from(id), 1);
        let speed = (def.speed_min + (def.speed_max - def.speed_min) * u).min(TERMINAL_SPEED);
        let heading = crate::physics::rotate(dir, shot.angle_offset);
        let (dx, dy) = heading;
        let jitter = if def.lifetime_jitter == 0 {
            0
        } else {
            let span = 2 * def.lifetime_jitter + 1;
            rng.below(span, frame, u64::from(id), 2) as i32 - def.lifetime_jitter as i32
        };
        let timer_left = shot.trigger.as_ref().and_then(|t| match t.kind {
            TriggerKind::Timer => t.timer_frames,
            TriggerKind::Collision => None,
        });
        Projectile {
            id,
            owner,
            x: origin.0,
            y: origin.1,
            vx: dx * speed,
            vy: dy * speed,
            speed0: speed,
            age: 0,
            life: (def.lifetime as i32 + jitter).max(1),
            bounces_left: def.bounces,
            trigger: shot.trigger.as_deref().cloned(),
            timer_left,
            heading,
            def,
        }
    }

    pub fn speed(&self) -> f32 {
        (self.vx * self.vx + self.vy * self.vy).sqrt()
    }
}
