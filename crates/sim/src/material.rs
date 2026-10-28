//! Materials: loading `content/materials.json` (contract section 2) and deriving the integer
//! runtime parameters the cell rules use (SIM-R05, SIM-R06).

use crate::consts::{Tuning, MAX_FALL_STEPS};
use crate::error::{Error, Result};
use crate::material_file::parse_materials;
use std::collections::BTreeMap;

pub const MATERIALS_FORMAT: &str = "cogbench-materials/0";

/// Cell kinds (SIM-R04). `Air` is the empty cell; `Static` is terrain.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Air,
    Gas,
    Fire,
    Liquid,
    Powder,
    Static,
}

impl Kind {
    /// Every kind, in index order (see [`Kind::index`]).
    pub const ALL: [Kind; 6] = [
        Kind::Air,
        Kind::Gas,
        Kind::Fire,
        Kind::Liquid,
        Kind::Powder,
        Kind::Static,
    ];

    /// Position in [`Kind::ALL`]: a dense index for per-kind arrays.
    pub const fn index(self) -> usize {
        match self {
            Kind::Air => 0,
            Kind::Gas => 1,
            Kind::Fire => 2,
            Kind::Liquid => 3,
            Kind::Powder => 4,
            Kind::Static => 5,
        }
    }

    /// Lower-case name as written in `materials.json`.
    pub const fn name(self) -> &'static str {
        match self {
            Kind::Air => "air",
            Kind::Gas => "gas",
            Kind::Fire => "fire",
            Kind::Liquid => "liquid",
            Kind::Powder => "powder",
            Kind::Static => "static",
        }
    }

    pub(crate) fn parse(s: &str) -> Option<Kind> {
        match s {
            "air" => Some(Kind::Air),
            "gas" => Some(Kind::Gas),
            "fire" => Some(Kind::Fire),
            "liquid" => Some(Kind::Liquid),
            "powder" => Some(Kind::Powder),
            "static" => Some(Kind::Static),
            _ => None,
        }
    }
}

/// What a burning cell of a material detonates with (`explosion` in `materials.json`, FIRE-R10).
/// The numbers are those of an `ExplosionConfig` (DUR-R03).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ExplosionParams {
    pub radius: u32,
    pub ray_energy: u32,
    pub max_durability: u8,
    /// Chance in percent that a destroyed cell becomes fire (`create_cell_probability`).
    pub fire_percent: u8,
}

/// One validated material as written in the content file.
#[derive(Clone, Debug)]
pub struct Material {
    pub index: u8,
    pub key: String,
    pub name_zh: String,
    pub name_en: String,
    pub noita_id: Option<String>,
    pub kind: Kind,
    pub family: String,
    pub color: [u8; 3],
    pub density: f64,
    pub hp: u32,
    pub durability: u8,
    pub burnable: bool,
    pub fuel_frames: Option<u32>,
    pub autoignition: Option<u8>,
    pub fire_temperature: u8,
    pub requires_oxygen: bool,
    pub lifetime_frames: Option<u32>,
    pub liquid_gravity: Option<f64>,
    pub viscosity: Option<f64>,
    pub contact_damage_per_px_frame: f64,
    pub tags: Vec<String>,
    pub drink_effect: String,
    /// Present on materials that explode when they burn (gunpowder).
    pub explosion: Option<ExplosionParams>,
}

/// Integer parameters derived once at load (SIM-R05); the cell rules read nothing else.
#[derive(Clone, Copy, Debug)]
pub struct MatRt {
    pub kind: Kind,
    pub density_x10000: u32,
    /// Whole fall steps per visit and the chance of one more (`/256`), SIM-R31.
    pub fall_int: u8,
    pub fall_frac_q8: u16,
    /// Chance that a powder slides diagonally when it cannot fall (`/256`).
    pub slide_q8: u16,
    /// Timer: `life_unit` frames per tick of `life`; 0 = no timer (SIM-R35).
    pub life_unit: u8,
    pub life0: u8,
    pub burnable: bool,
    pub burn_unit: u8,
    pub burn0: u8,
    pub requires_oxygen: bool,
    /// 100 means "never ignites".
    pub autoignition: u8,
    pub fire_temperature: u8,
    /// A burning cell of this material detonates with these numbers (FIRE-R10).
    pub explosion: Option<ExplosionParams>,
    pub hp: u32,
    pub durability: u8,
    /// Set by `Content` once the reaction table is known: the material is a reaction partner.
    pub reactive: bool,
    /// Bit `i` is set if the material is an ingredient of recipe `i` (set by `Content` when
    /// recipes are attached, `rules/recipe_mix.rs`); 0 for everything that takes part in no recipe.
    pub ingredient_of: u16,
}

impl MatRt {
    /// Runtime record of the out-of-world pseudo material: indestructible, blocks everything.
    fn boundary() -> MatRt {
        MatRt {
            kind: Kind::Static,
            density_x10000: u32::MAX,
            fall_int: 0,
            fall_frac_q8: 0,
            slide_q8: 0,
            life_unit: 0,
            life0: 0,
            burnable: false,
            burn_unit: 1,
            burn0: 0,
            requires_oxygen: false,
            autoignition: 100,
            fire_temperature: 0,
            explosion: None,
            hp: u32::MAX,
            durability: u8::MAX,
            reactive: false,
            ingredient_of: 0,
        }
    }
}

/// All materials of a content set, plus lookup tables.
#[derive(Clone, Debug)]
pub struct MaterialSet {
    materials: Vec<Material>,
    by_key: BTreeMap<String, u8>,
    tags: BTreeMap<String, Vec<u8>>,
    rt: Vec<MatRt>,
}

impl MaterialSet {
    /// Parse and validate `materials.json` text. `file` is only used in error messages.
    pub fn from_json(file: &str, text: &str, tuning: &Tuning) -> Result<MaterialSet> {
        MaterialSet::assemble(file, parse_materials(file, text)?, tuning)
    }

    fn assemble(file: &str, materials: Vec<Material>, tuning: &Tuning) -> Result<MaterialSet> {
        let mut by_key = BTreeMap::new();
        let mut tags: BTreeMap<String, Vec<u8>> = BTreeMap::new();
        for m in &materials {
            if by_key.insert(m.key.clone(), m.index).is_some() {
                return Err(Error::content(
                    file,
                    format!("materials[{}].key", m.index),
                    format!("duplicate key `{}`", m.key),
                ));
            }
            for t in &m.tags {
                tags.entry(t.clone()).or_default().push(m.index);
            }
        }
        let mut rt = vec![MatRt::boundary(); 256];
        for m in &materials {
            rt[usize::from(m.index)] = derive_rt(m, tuning);
        }
        Ok(MaterialSet {
            materials,
            by_key,
            tags,
            rt,
        })
    }

    pub fn len(&self) -> usize {
        self.materials.len()
    }

    pub fn is_empty(&self) -> bool {
        self.materials.is_empty()
    }

    pub fn get(&self, index: u8) -> Option<&Material> {
        self.materials.get(usize::from(index))
    }

    pub fn iter(&self) -> impl Iterator<Item = &Material> {
        self.materials.iter()
    }

    pub fn index_of(&self, key: &str) -> Option<u8> {
        self.by_key.get(key).copied()
    }

    /// Key of a material index; `"boundary"` for the out-of-world pseudo material.
    pub fn key_of(&self, index: u8) -> &str {
        self.get(index).map_or("boundary", |m| m.key.as_str())
    }

    /// Materials carrying `tag`, in index order. `None` if no material has the tag.
    pub fn with_tag(&self, tag: &str) -> Option<&[u8]> {
        self.tags.get(tag).map(Vec::as_slice)
    }

    #[inline]
    pub fn rt(&self, index: u8) -> &MatRt {
        &self.rt[usize::from(index)]
    }

    pub(crate) fn set_reactive(&mut self, index: u8, reactive: bool) {
        self.rt[usize::from(index)].reactive = reactive;
    }

    pub(crate) fn set_ingredient_of(&mut self, index: u8, mask: u16) {
        self.rt[usize::from(index)].ingredient_of = mask;
    }
}

/// Round half up of `num / den`.
fn div_round(num: u32, den: u32) -> u32 {
    (2 * num + den) / (2 * den)
}

fn derive_rt(m: &Material, tuning: &Tuning) -> MatRt {
    let g100 = m.liquid_gravity.map_or(0, |g| (g * 100.0).round() as u32);
    let two_g100 = 2 * g100;
    let (mut fall_int, mut fall_frac_q8) = match m.kind {
        Kind::Liquid | Kind::Powder if g100 == 0 => (0, 32), // gravity 0 still falls, slowly
        Kind::Liquid | Kind::Powder => (
            (two_g100 / 100).min(MAX_FALL_STEPS),
            div_round((two_g100 % 100) * 256, 100) as u16,
        ),
        _ => (0, 0),
    };
    if two_g100 / 100 >= MAX_FALL_STEPS {
        fall_frac_q8 = 0;
    }
    let visc = m.viscosity.map_or(50, |v| v.round() as u32);
    // Powders slide diagonally with a chance that falls with viscosity; liquids ignore viscosity.
    let mut slide_q8 = if m.kind == Kind::Powder {
        div_round((200u32.saturating_sub(visc)) * 256, 200).clamp(64, 256) as u16
    } else {
        256
    };
    if tuning.single_fall_step && matches!(m.kind, Kind::Liquid | Kind::Powder) {
        fall_int = 1;
        fall_frac_q8 = 0;
        slide_q8 = 256;
    }
    let (life_unit, life0) = match (m.kind, m.lifetime_frames) {
        (Kind::Fire, _) => (1, tuning.fire_life_min),
        (_, Some(l)) => {
            let unit = l.div_ceil(255).max(1);
            (unit as u8, l.div_ceil(unit) as u8)
        }
        _ => (0, 0),
    };
    let fuel = m.fuel_frames.unwrap_or(0);
    let burn_unit = fuel.div_ceil(250).max(1);
    let burn0 = if fuel == 0 {
        0
    } else {
        fuel.div_ceil(burn_unit)
    };
    MatRt {
        kind: m.kind,
        density_x10000: (m.density * 10_000.0).round() as u32,
        fall_int: fall_int as u8,
        fall_frac_q8,
        slide_q8,
        life_unit,
        life0,
        burnable: m.burnable,
        burn_unit: burn_unit as u8,
        burn0: burn0 as u8,
        requires_oxygen: m.requires_oxygen,
        autoignition: m.autoignition.unwrap_or(100),
        fire_temperature: m.fire_temperature,
        explosion: m.explosion,
        hp: m.hp,
        durability: m.durability,
        reactive: false,
        ingredient_of: 0,
    }
}
