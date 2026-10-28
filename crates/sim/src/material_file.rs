//! Parsing and validation of `content/materials.json` (contract section 2).
//!
//! Every problem is reported with the file name and the field path, so a bad content file
//! fails at load time with a message that says where to look.

use crate::consts::{BOUNDARY, MAX_EXPLOSION_RADIUS};
use crate::error::{Error, Result};
use crate::material::{ExplosionParams, Kind, Material, MATERIALS_FORMAT};
use serde::Deserialize;

#[derive(Deserialize)]
struct RawFile {
    format: String,
    materials: Vec<RawMaterial>,
}

/// The optional `explosion` object: what a burning cell of the material detonates with.
#[derive(Deserialize)]
struct RawExplosion {
    radius: f64,
    ray_energy: f64,
    max_durability: f64,
    fire_percent: f64,
}

#[derive(Deserialize)]
struct RawMaterial {
    index: u32,
    key: String,
    #[serde(default)]
    name_zh: String,
    #[serde(default)]
    name_en: String,
    #[serde(default)]
    noita_id: Option<String>,
    kind: String,
    #[serde(default)]
    family: String,
    color: String,
    density: f64,
    hp: f64,
    durability: f64,
    #[serde(default)]
    burnable: bool,
    #[serde(default)]
    fuel_frames: Option<f64>,
    #[serde(default)]
    autoignition: Option<f64>,
    fire_temperature: f64,
    requires_oxygen: bool,
    #[serde(default)]
    lifetime_frames: Option<f64>,
    #[serde(default)]
    liquid_gravity: Option<f64>,
    #[serde(default)]
    viscosity: Option<f64>,
    #[serde(default)]
    contact_damage_per_px_frame: f64,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    drink_effect: String,
    #[serde(default)]
    explosion: Option<RawExplosion>,
}

/// Parse the file text and validate every material.
pub(crate) fn parse_materials(file: &str, text: &str) -> Result<Vec<Material>> {
    let raw: RawFile =
        serde_json::from_str(text).map_err(|e| Error::content(file, "(json)", e.to_string()))?;
    if raw.format != MATERIALS_FORMAT {
        return Err(Error::content(
            file,
            "format",
            format!("expected `{MATERIALS_FORMAT}`, found `{}`", raw.format),
        ));
    }
    if raw.materials.is_empty() || raw.materials.len() >= usize::from(BOUNDARY) {
        return Err(Error::content(
            file,
            "materials",
            format!(
                "need 1..{} materials, found {}",
                BOUNDARY,
                raw.materials.len()
            ),
        ));
    }
    raw.materials
        .iter()
        .enumerate()
        .map(|(i, m)| validate(file, i, m))
        .collect()
}

fn int_field(file: &str, field: &str, v: f64, lo: f64, hi: f64) -> Result<u32> {
    if v.fract() != 0.0 || v < lo || v > hi {
        return Err(Error::content(
            file,
            field,
            format!("must be an integer in {lo}..={hi}, found {v}"),
        ));
    }
    Ok(v as u32)
}

fn parse_color(file: &str, field: &str, s: &str) -> Result<[u8; 3]> {
    let bad = || Error::content(file, field, format!("`{s}` is not a #RRGGBB colour"));
    let hex = s.strip_prefix('#').ok_or_else(bad)?;
    if hex.len() != 6 || !hex.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(bad());
    }
    let n = u32::from_str_radix(hex, 16).map_err(|_| bad())?;
    Ok([(n >> 16) as u8, (n >> 8) as u8, n as u8])
}

fn valid_name(s: &str) -> bool {
    !s.is_empty()
        && s.chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

/// Index, key, kind and colour: who the material is.
fn validate_identity(file: &str, pos: usize, m: &RawMaterial) -> Result<(Kind, [u8; 3])> {
    let f = |name: &str| format!("materials[{pos}].{name}");
    if m.index as usize != pos || m.index >= u32::from(BOUNDARY) {
        return Err(Error::content(
            file,
            f("index"),
            format!(
                "expected {pos} (indices are contiguous from 0), found {}",
                m.index
            ),
        ));
    }
    if !valid_name(&m.key) {
        return Err(Error::content(
            file,
            f("key"),
            format!("`{}` is not snake_case", m.key),
        ));
    }
    let kind = Kind::parse(&m.kind).ok_or_else(|| {
        Error::content(
            file,
            f("kind"),
            format!(
                "`{}` is not one of air|gas|fire|liquid|powder|static",
                m.kind
            ),
        )
    })?;
    if (pos == 0) != (kind == Kind::Air) || (pos == 0 && m.key != "air") {
        return Err(Error::content(
            file,
            f("kind"),
            "index 0 must be `air` with kind `air`, and no other material may be kind `air`",
        ));
    }
    Ok((kind, parse_color(file, &f("color"), &m.color)?))
}

fn validate_density(file: &str, field: &str, density: f64) -> Result<()> {
    let d10k = density * 10_000.0;
    if density.is_nan() || density <= 0.0 || (d10k - d10k.round()).abs() > 1e-6 {
        return Err(Error::content(
            file,
            field,
            format!("must be positive with at most 4 decimals, found {density}"),
        ));
    }
    Ok(())
}

fn validate(file: &str, pos: usize, m: &RawMaterial) -> Result<Material> {
    let f = |name: &str| format!("materials[{pos}].{name}");
    let (kind, color) = validate_identity(file, pos, m)?;
    validate_density(file, &f("density"), m.density)?;
    let hp = int_field(file, &f("hp"), m.hp, 1.0, 4_000_000_000.0)?;
    let durability = int_field(file, &f("durability"), m.durability, 0.0, 254.0)? as u8;
    let fire_temperature =
        int_field(file, &f("fire_temperature"), m.fire_temperature, 0.0, 255.0)? as u8;
    let fuel_frames = m
        .fuel_frames
        .map(|v| int_field(file, &f("fuel_frames"), v, 0.0, 63_750.0))
        .transpose()?;
    let autoignition = m
        .autoignition
        .map(|v| int_field(file, &f("autoignition"), v, 0.0, 100.0).map(|x| x as u8))
        .transpose()?;
    let lifetime_frames = m
        .lifetime_frames
        .map(|v| int_field(file, &f("lifetime_frames"), v, 1.0, 65_025.0))
        .transpose()?;
    if m.burnable && (fuel_frames.is_none() || autoignition.is_none()) {
        return Err(Error::content(
            file,
            f("burnable"),
            "a burnable material needs `fuel_frames` and `autoignition`",
        ));
    }
    if matches!(kind, Kind::Liquid | Kind::Powder) {
        check_motion_fields(file, &f(""), m)?;
    }
    check_tags(file, &f("tags"), &m.tags)?;
    let explosion = m
        .explosion
        .as_ref()
        .map(|e| validate_explosion(file, &f("explosion"), m.burnable, e))
        .transpose()?;
    Ok(Material {
        index: m.index as u8,
        key: m.key.clone(),
        name_zh: m.name_zh.clone(),
        name_en: m.name_en.clone(),
        noita_id: m.noita_id.clone(),
        kind,
        family: m.family.clone(),
        color,
        density: m.density,
        hp,
        durability,
        burnable: m.burnable,
        fuel_frames,
        autoignition,
        fire_temperature,
        requires_oxygen: m.requires_oxygen,
        lifetime_frames,
        liquid_gravity: m.liquid_gravity,
        viscosity: m.viscosity,
        contact_damage_per_px_frame: m.contact_damage_per_px_frame,
        tags: m.tags.clone(),
        drink_effect: m.drink_effect.clone(),
        explosion,
    })
}

/// An explosion block needs a burnable material (only burning cells detonate) and sane numbers.
fn validate_explosion(
    file: &str,
    field: &str,
    burnable: bool,
    e: &RawExplosion,
) -> Result<ExplosionParams> {
    if !burnable {
        return Err(Error::content(
            file,
            field,
            "only burnable materials can detonate; set `burnable` or drop the explosion block",
        ));
    }
    let f = |name: &str| format!("{field}.{name}");
    Ok(ExplosionParams {
        radius: int_field(
            file,
            &f("radius"),
            e.radius,
            1.0,
            f64::from(MAX_EXPLOSION_RADIUS),
        )?,
        ray_energy: int_field(
            file,
            &f("ray_energy"),
            e.ray_energy,
            1.0,
            f64::from(u32::MAX),
        )?,
        max_durability: int_field(file, &f("max_durability"), e.max_durability, 0.0, 255.0)? as u8,
        fire_percent: int_field(file, &f("fire_percent"), e.fire_percent, 0.0, 100.0)? as u8,
    })
}

fn check_motion_fields(file: &str, prefix: &str, m: &RawMaterial) -> Result<()> {
    let g = m.liquid_gravity.ok_or_else(|| {
        Error::content(
            file,
            format!("{prefix}liquid_gravity"),
            "liquids and powders need it",
        )
    })?;
    let v = m.viscosity.ok_or_else(|| {
        Error::content(
            file,
            format!("{prefix}viscosity"),
            "liquids and powders need it",
        )
    })?;
    if !(0.0..=5.0).contains(&g) || (g * 100.0 - (g * 100.0).round()).abs() > 1e-6 {
        return Err(Error::content(
            file,
            format!("{prefix}liquid_gravity"),
            format!("must be in 0..=5 with at most 2 decimals, found {g}"),
        ));
    }
    if !(0.0..=150.0).contains(&v) {
        return Err(Error::content(
            file,
            format!("{prefix}viscosity"),
            format!("must be in 0..=150, found {v}"),
        ));
    }
    Ok(())
}

fn check_tags(file: &str, field: &str, tags: &[String]) -> Result<()> {
    for (i, t) in tags.iter().enumerate() {
        if !valid_name(t) {
            return Err(Error::content(
                file,
                field,
                format!("tag `{t}` is not snake_case"),
            ));
        }
        if tags[..i].contains(t) {
            return Err(Error::content(file, field, format!("duplicate tag `{t}`")));
        }
    }
    Ok(())
}
