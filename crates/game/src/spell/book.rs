//! Loading and validating the spell catalogue.

use std::collections::BTreeMap;
use std::path::Path;

use serde::Deserialize;

use super::{BodyKind, Spell, SpellId, SpellType, TriggerKind};
use crate::error::Error;

pub const FORMAT: &str = "cogbench-spells/0";
const EMBEDDED: &str = include_str!("../../../../content/spells.json");
const EMBEDDED_NAME: &str = "content/spells.json";
const MAX_MANA: i32 = 1000;

#[derive(Deserialize)]
struct SpellFile {
    format: String,
    spells: Vec<Spell>,
}

/// All spells, indexed by [`SpellId`] (file order).
#[derive(Clone, Debug)]
pub struct SpellBook {
    /// Where the catalogue came from, for error messages.
    file: String,
    spells: Vec<Spell>,
    by_key: BTreeMap<String, SpellId>,
}

impl SpellBook {
    /// The catalogue compiled into this crate (`content/spells.json` at build time).
    pub fn embedded() -> Result<SpellBook, Error> {
        SpellBook::from_json(EMBEDDED, EMBEDDED_NAME)
    }

    /// Load and validate a catalogue file.
    pub fn load(path: &Path) -> Result<SpellBook, Error> {
        let text = std::fs::read_to_string(path).map_err(|source| Error::Io {
            path: path.to_path_buf(),
            source,
        })?;
        SpellBook::from_json(&text, &path.display().to_string())
    }

    /// Parse and validate `text`; `file` names the source in error messages.
    pub fn from_json(text: &str, file: &str) -> Result<SpellBook, Error> {
        let parsed: SpellFile =
            serde_json::from_str(text).map_err(|e| Error::content(file, "", e.to_string()))?;
        if parsed.format != FORMAT {
            let found = &parsed.format;
            return Err(Error::content(
                file,
                "format",
                format!("expected {FORMAT:?}, found {found:?}"),
            ));
        }
        validate(file, &parsed.spells)?;
        let by_key = parsed
            .spells
            .iter()
            .enumerate()
            .map(|(i, s)| (s.key.clone(), SpellId(i as u16)))
            .collect();
        Ok(SpellBook {
            file: file.to_string(),
            spells: parsed.spells,
            by_key,
        })
    }

    pub fn len(&self) -> usize {
        self.spells.len()
    }

    pub fn is_empty(&self) -> bool {
        self.spells.is_empty()
    }

    /// The spell with this id. Ids come from this book; one from another book may be out of range
    /// (then this panics): use [`SpellBook::contains`] on untrusted ids.
    pub fn get(&self, id: SpellId) -> &Spell {
        &self.spells[usize::from(id.0)]
    }

    pub fn contains(&self, id: SpellId) -> bool {
        usize::from(id.0) < self.spells.len()
    }

    pub fn id(&self, key: &str) -> Option<SpellId> {
        self.by_key.get(key).copied()
    }

    pub fn key(&self, id: SpellId) -> &str {
        &self.get(id).key
    }

    /// Spells in id order.
    pub fn iter(&self) -> impl Iterator<Item = (SpellId, &Spell)> {
        self.spells
            .iter()
            .enumerate()
            .map(|(i, s)| (SpellId(i as u16), s))
    }

    /// Check that every material a spell names (trails, emitted particles, explosion debris) is a
    /// material of the world (`is_material` answers for the world's material table).
    pub fn check_materials(&self, is_material: &dyn Fn(&str) -> bool) -> Result<(), Error> {
        for (i, spell) in self.spells.iter().enumerate() {
            let at = |field: &str| format!("spells[{i}] ({}).{field}", spell.key);
            for (t, trail) in spell.shot.trail.iter().enumerate() {
                if !is_material(&trail.material) {
                    let msg = format!("unknown material {:?}", trail.material);
                    let field = at(&format!("shot.trail[{t}].material"));
                    return Err(Error::content(&self.file, field, msg));
                }
            }
            let Some(p) = &spell.projectile else { continue };
            let emitted = p
                .emit
                .as_ref()
                .map(|e| ("projectile.emit.material", &e.material));
            let debris = p.explosion.as_ref().and_then(|e| e.cell_material.as_ref());
            let debris = debris.map(|m| ("projectile.explosion.cell_material", m));
            for (field, material) in emitted.into_iter().chain(debris) {
                if !is_material(material) {
                    let msg = format!("unknown material {material:?}");
                    return Err(Error::content(&self.file, at(field), msg));
                }
            }
        }
        Ok(())
    }
}

/// Reports the first problem, naming the file and the field.
struct Checker<'a> {
    file: &'a str,
}

impl Checker<'_> {
    fn fail(&self, field: String, message: impl Into<String>) -> Error {
        Error::content(self.file, field, message)
    }

    fn finite(&self, field: &str, value: f32) -> Result<(), Error> {
        if value.is_finite() {
            Ok(())
        } else {
            Err(self.fail(
                field.to_string(),
                format!("must be a finite number, found {value}"),
            ))
        }
    }
}

fn validate(file: &str, spells: &[Spell]) -> Result<(), Error> {
    let check = Checker { file };
    if spells.is_empty() {
        return Err(check.fail("spells".into(), "the catalogue is empty"));
    }
    if spells.len() > usize::from(u16::MAX) {
        return Err(check.fail("spells".into(), "too many spells for a 16-bit id"));
    }
    let mut seen = BTreeMap::new();
    for (i, spell) in spells.iter().enumerate() {
        let at = |field: &str| format!("spells[{i}] ({}).{field}", spell.key);
        validate_identity(&check, i, spell, &mut seen)?;
        validate_cost(&check, spell, &at)?;
        validate_structure(&check, spell, &at)?;
        validate_numbers(&check, spell, &at)?;
        if let Some(projectile) = &spell.projectile {
            validate_projectile(&check, spell, projectile, &at)?;
        }
    }
    Ok(())
}

fn validate_identity(
    check: &Checker,
    index: usize,
    spell: &Spell,
    seen: &mut BTreeMap<String, usize>,
) -> Result<(), Error> {
    let key = &spell.key;
    let valid = !key.is_empty()
        && key
            .chars()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_');
    if !valid {
        let message = format!("must be upper snake case (A-Z, 0-9, _), found {key:?}");
        return Err(check.fail(format!("spells[{index}].key"), message));
    }
    if let Some(first) = seen.insert(key.clone(), index) {
        let message = format!("duplicate key {key:?} (first at spells[{first}])");
        return Err(check.fail(format!("spells[{index}].key"), message));
    }
    let label = format!("spells[{index}] ({key})");
    if spell.name_en.is_empty() || spell.name_zh.is_empty() {
        return Err(check.fail(
            format!("{label}.name_en/name_zh"),
            "names must not be empty",
        ));
    }
    Ok(())
}

fn validate_cost(check: &Checker, spell: &Spell, at: &dyn Fn(&str) -> String) -> Result<(), Error> {
    if !(-MAX_MANA..=MAX_MANA).contains(&spell.mana) {
        let message = format!(
            "must be within -{MAX_MANA}..={MAX_MANA}, found {}",
            spell.mana
        );
        return Err(check.fail(at("mana"), message));
    }
    if spell.max_uses == Some(0) {
        return Err(check.fail(at("max_uses"), "must be at least 1 (null means unlimited)"));
    }
    Ok(())
}

/// The shape each spell type must have: what it draws, whether it carries a projectile.
fn validate_structure(
    check: &Checker,
    spell: &Spell,
    at: &dyn Fn(&str) -> String,
) -> Result<(), Error> {
    let draw_ok = match spell.kind {
        SpellType::Modifier => spell.draw >= 1,
        SpellType::Multicast => spell.draw >= 2,
        _ => spell.draw == 0,
    };
    if !draw_ok {
        let message = format!("{:?} spells cannot draw {} cards", spell.kind, spell.draw);
        return Err(check.fail(at("draw"), message));
    }
    if spell.kind.adds_projectile() != spell.projectile.is_some() {
        let message = format!(
            "a {:?} spell {} a projectile block",
            spell.kind,
            if spell.kind.adds_projectile() {
                "needs"
            } else {
                "must not have"
            }
        );
        return Err(check.fail(at("projectile"), message));
    }
    let Some(trigger) = &spell.trigger else {
        return Ok(());
    };
    if !matches!(
        spell.kind,
        SpellType::Projectile | SpellType::StaticProjectile
    ) {
        return Err(check.fail(at("trigger"), "only projectile spells can carry a trigger"));
    }
    if trigger.payload_draws == 0 {
        return Err(check.fail(at("trigger.payload_draws"), "must be at least 1"));
    }
    match (trigger.kind, trigger.timer_frames) {
        (TriggerKind::Timer, Some(frames)) if frames >= 1 => Ok(()),
        (TriggerKind::Timer, _) => Err(check.fail(
            at("trigger.timer_frames"),
            "a timer trigger needs timer_frames >= 1",
        )),
        (TriggerKind::Collision, None) => Ok(()),
        (TriggerKind::Collision, Some(_)) => Err(check.fail(
            at("trigger.timer_frames"),
            "a collision trigger has no timer",
        )),
    }
}

fn validate_numbers(
    check: &Checker,
    spell: &Spell,
    at: &dyn Fn(&str) -> String,
) -> Result<(), Error> {
    let shot = &spell.shot;
    let numbers = [
        ("recoil", spell.recoil),
        ("shot.spread", shot.spread),
        ("shot.speed_mul", shot.speed_mul),
        ("shot.damage", shot.damage),
        ("shot.explosion_damage", shot.explosion_damage),
        ("shot.explosion_radius", shot.explosion_radius),
        ("shot.crit_chance", shot.crit_chance),
    ];
    for (field, value) in numbers {
        check.finite(&at(field), value)?;
    }
    if shot.speed_mul < 0.0 {
        let message = format!("must not be negative, found {}", shot.speed_mul);
        return Err(check.fail(at("shot.speed_mul"), message));
    }
    for (t, trail) in shot.trail.iter().enumerate() {
        if trail.material.is_empty() || trail.amount == 0 {
            let message = "needs a material and an amount of at least 1";
            return Err(check.fail(at(&format!("shot.trail[{t}]")), message));
        }
    }
    Ok(())
}

fn validate_projectile(
    check: &Checker,
    spell: &Spell,
    p: &super::ProjectileSpec,
    at: &dyn Fn(&str) -> String,
) -> Result<(), Error> {
    let floats = [
        ("speed_min", p.speed_min),
        ("speed_max", p.speed_max),
        ("gravity", p.gravity),
        ("air_friction", p.air_friction),
        ("mass", p.mass),
        ("innate_spread", p.innate_spread),
        ("bounce_energy", p.bounce_energy),
        ("hit_damage", p.hit_damage),
        ("knockback", p.knockback),
    ];
    for (field, value) in floats {
        check.finite(&at(&format!("projectile.{field}")), value)?;
    }
    if p.speed_min < 0.0 || p.speed_min > p.speed_max {
        let message = format!(
            "need 0 <= speed_min <= speed_max, found {}..{}",
            p.speed_min, p.speed_max
        );
        return Err(check.fail(at("projectile.speed_min"), message));
    }
    if !(0.0..=1.0).contains(&p.bounce_energy) {
        return Err(check.fail(at("projectile.bounce_energy"), "must be within 0..=1"));
    }
    let body_ok = match spell.kind {
        SpellType::StaticProjectile => p.body == BodyKind::Static,
        SpellType::Material => p.body == BodyKind::MaterialParticle,
        _ => matches!(p.body, BodyKind::Projectile | BodyKind::ThrownBody),
    };
    if !body_ok {
        let message = format!("body {:?} does not fit a {:?} spell", p.body, spell.kind);
        return Err(check.fail(at("projectile.body"), message));
    }
    match &p.explosion {
        Some(explosion) => validate_explosion(check, explosion, at),
        None => Ok(()),
    }
}

fn validate_explosion(
    check: &Checker,
    e: &super::ExplosionSpec,
    at: &dyn Fn(&str) -> String,
) -> Result<(), Error> {
    if e.cell_percent > 100 {
        return Err(check.fail(
            at("projectile.explosion.cell_percent"),
            "must be at most 100",
        ));
    }
    if e.cell_percent > 0 && e.cell_material.is_none() {
        return Err(check.fail(
            at("projectile.explosion.cell_material"),
            "needed when cell_percent > 0",
        ));
    }
    check.finite(&at("projectile.explosion.damage"), e.damage)
}
