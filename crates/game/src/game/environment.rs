//! What the surroundings do to a living thing each frame: statuses from contact, ignition,
//! contact damage (HAZ-R01), healing pools, and the per-frame effect of the statuses.

use cogbench_sim::{Aabb, ContactRules, Kind, World};

use crate::defs::EntityDefs;
use crate::entity::{DamageSource, Vitals};
use crate::status::Status;

const FPS: f32 = 60.0;

/// What differs between the player and an enemy for the environment rules.
pub(crate) struct EnvSpec<'a> {
    pub bbox: Aabb,
    /// Chance in percent per frame that fire or burning cells set the entity alight.
    pub ignite_percent: u32,
    /// Per-cell contact damage by material key; empty means the table of `materials.json`.
    pub contact_table: &'a std::collections::BTreeMap<String, f32>,
    pub wet_damage_per_s: f32,
    /// Random numbers for this frame: the ignition roll and where a flame appears.
    pub ignite_roll: u32,
    pub flame_roll: u32,
    pub flame_pos: u32,
}

/// What the environment did to one entity this frame.
#[derive(Default)]
pub(crate) struct EnvTick {
    pub damage: Vec<(f32, DamageSource)>,
    pub started: Vec<Status>,
    pub ended: Vec<Status>,
    /// A flame to put into the world at this cell.
    pub flame: Option<(i32, i32)>,
}

fn cell_count_of(world: &World, ov: &cogbench_sim::Overlap, key: &str) -> u32 {
    world
        .content()
        .mats
        .index_of(key)
        .map_or(0, |m| ov.count(m))
}

/// Contact statuses, ignition, contact damage, healing and the per-frame effect of the statuses.
pub(crate) fn environment(
    world: &World,
    defs: &EntityDefs,
    vit: &mut Vitals,
    spec: &EnvSpec<'_>,
) -> EnvTick {
    let mut out = EnvTick::default();
    let ov = world.overlap(spec.bbox);
    contact_statuses(world, defs, vit, spec, &ov, &mut out);
    contact_damage_and_healing(world, defs, vit, spec, &ov, &mut out);
    status_effects(defs, vit, spec, &mut out);
    out.ended.extend(vit.statuses.tick());
    out
}

/// Stains from the materials around, ignition by fire and lava, and wet putting fire out.
fn contact_statuses(
    world: &World,
    defs: &EntityDefs,
    vit: &mut Vitals,
    spec: &EnvSpec<'_>,
    ov: &cogbench_sim::Overlap,
    out: &mut EnvTick,
) {
    let (c, sd) = (&defs.contact, &defs.statuses);
    for (material, status) in &c.status {
        let Some(status) = Status::parse(status) else {
            continue;
        };
        if cell_count_of(world, ov, material) >= c.min_cells
            && vit.statuses.apply(status, sd.frames(status))
        {
            out.started.push(status);
        }
    }
    let wet = vit.statuses.has(Status::Wet);
    let lava = c
        .ignite
        .iter()
        .map(|k| cell_count_of(world, ov, k))
        .sum::<u32>();
    let hot = ov.kind_count(Kind::Fire) + ov.burning();
    let fireproof = vit.statuses.has(Status::Fireproof);
    let ignites = !fireproof
        && spec.ignite_percent > 0
        && ((lava >= c.ignite_min_cells)
            || (hot >= c.ignite_min_cells && !wet && spec.ignite_roll < spec.ignite_percent));
    if ignites && !vit.statuses.has(Status::OnFire) {
        let mut frames = sd.on_fire.frames;
        if vit.statuses.has(Status::Oiled) {
            frames *= sd.on_fire.oiled_frames_mul.max(1);
        }
        if lava >= c.ignite_min_cells {
            vit.statuses.clear(Status::Wet);
        }
        vit.statuses.apply(Status::OnFire, frames);
        out.started.push(Status::OnFire);
    }
    if (vit.statuses.has(Status::Wet) || fireproof) && vit.statuses.clear(Status::OnFire) {
        out.ended.push(Status::OnFire);
    }
}

/// Damage from materials (HAZ-R01) and healing from pools.
fn contact_damage_and_healing(
    world: &World,
    defs: &EntityDefs,
    vit: &mut Vitals,
    spec: &EnvSpec<'_>,
    ov: &cogbench_sim::Overlap,
    out: &mut EnvTick,
) {
    let mats = &world.content().mats;
    let per_px = |m: u8| -> f64 {
        let Some(material) = mats.get(m) else {
            return 0.0;
        };
        if spec.contact_table.is_empty() {
            material.contact_damage_per_px_frame
        } else {
            spec.contact_table
                .get(&material.key)
                .map_or(0.0, |v| f64::from(*v))
        }
    };
    let contact = ov.contact_damage(per_px, ContactRules::default());
    if contact.raw > 0.0 {
        out.damage.push((contact.raw as f32, DamageSource::Contact));
    }
    for (material, rate) in &defs.contact.heal_per_px_frame {
        let cells = cell_count_of(world, ov, material).min(cogbench_sim::consts::CONTACT_MAX_CELLS);
        if cells >= defs.contact.min_cells {
            vit.hp = (vit.hp + cells as f32 * rate).min(vit.hp_max);
        }
    }
}

/// The per-frame effect of the statuses an entity has: burning, poison, regeneration, and water
/// hurting a creature that is wet (Stendari).
fn status_effects(defs: &EntityDefs, vit: &mut Vitals, spec: &EnvSpec<'_>, out: &mut EnvTick) {
    let sd = &defs.statuses;
    if vit.statuses.has(Status::OnFire) {
        out.damage
            .push((sd.on_fire.damage_per_s / FPS, DamageSource::Fire));
        if spec.flame_roll < sd.on_fire.emit_percent {
            let (w, h) = (spec.bbox.w + 2, spec.bbox.h + 2);
            let n = spec.flame_pos % (2 * (w + h) as u32);
            let (dx, dy) = ring_offset(n as i32, w, h);
            out.flame = Some((spec.bbox.x - 1 + dx, spec.bbox.y - 1 + dy));
        }
    }
    if vit.statuses.has(Status::Poisoned) {
        let want = vit.hp_max * sd.poisoned.damage_pct_per_s / 100.0 / FPS;
        let floor = vit.hp_max * sd.poisoned.floor_pct / 100.0;
        let allowed = (vit.hp - floor).max(0.0);
        out.damage.push((want.min(allowed), DamageSource::Contact));
    }
    if vit.statuses.has(Status::Regeneration) {
        vit.hp =
            (vit.hp + vit.hp_max * sd.regeneration.heal_pct_per_s / 100.0 / FPS).min(vit.hp_max);
    }
    if spec.wet_damage_per_s > 0.0 && vit.statuses.has(Status::Wet) {
        out.damage
            .push((spec.wet_damage_per_s / FPS, DamageSource::Contact));
    }
}

/// The `n`-th cell on the outline of a `w` by `h` rectangle, walking clockwise from the top left.
fn ring_offset(n: i32, w: i32, h: i32) -> (i32, i32) {
    if n < w {
        (n, 0)
    } else if n < w + h {
        (w - 1, n - w)
    } else if n < 2 * w + h {
        (w - 1 - (n - w - h), h - 1)
    } else {
        (0, h - 1 - (n - 2 * w - h))
    }
}
