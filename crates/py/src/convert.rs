//! Conversions between Python values (dicts, lists) and the types of `cogbench-game`: controls,
//! wand stats, item descriptions, and the dicts that views are returned as.

use cogbench_game::wand::WandStats;
use cogbench_game::{Controls, DropItem, EntityView, ItemSpec, PlayerView, WandView};
use pyo3::conversion::FromPyObjectOwned;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

const CONTROL_KEYS: &str = "move, jump, fly, aim, fire, kick, interact, drink, pour, fill, throw, \
                            select_wand, select_bottle, drop";

pub(crate) fn flag(key: &str, v: &Bound<'_, PyAny>) -> PyResult<bool> {
    v.extract::<bool>()
        .map_err(|_| PyValueError::new_err(format!("control `{key}` must be true or false")))
}

pub(crate) fn slot(key: &str, v: &Bound<'_, PyAny>) -> PyResult<Option<u8>> {
    if v.is_none() {
        return Ok(None);
    }
    v.extract::<u8>()
        .map(Some)
        .map_err(|_| PyValueError::new_err(format!("control `{key}` must be 0..=255 or None")))
}

/// The `drop` control: `{"wand": 1}`, `{"spell": 3}` or `{"bottle": 0}`; `None` drops nothing.
fn drop_from(v: &Bound<'_, PyAny>) -> PyResult<Option<DropItem>> {
    const SHAPE: &str =
        "control `drop` must be {\"wand\": i}, {\"spell\": i} or {\"bottle\": i} (0..=255), or None";
    if v.is_none() {
        return Ok(None);
    }
    let d = v
        .cast::<PyDict>()
        .map_err(|_| PyValueError::new_err(SHAPE))?;
    if d.len() != 1 {
        return Err(PyValueError::new_err(SHAPE));
    }
    let (k, val) = d
        .iter()
        .next()
        .ok_or_else(|| PyValueError::new_err(SHAPE))?;
    let key: String = k.extract().map_err(|_| PyValueError::new_err(SHAPE))?;
    let index: u8 = val.extract().map_err(|_| PyValueError::new_err(SHAPE))?;
    match key.as_str() {
        "wand" => Ok(Some(DropItem::Wand(index))),
        "spell" => Ok(Some(DropItem::Spell(index))),
        "bottle" => Ok(Some(DropItem::Bottle(index))),
        _ => Err(PyValueError::new_err(SHAPE)),
    }
}

/// Controls from a dict such as `{"move": 1, "jump": True, "aim": 30.0}`; absent keys are off.
pub(crate) fn controls_from(d: &Bound<'_, PyDict>) -> PyResult<Controls> {
    let mut c = Controls::default();
    for (k, v) in d.iter() {
        let key: String = k.extract()?;
        match key.as_str() {
            "move" => {
                let m: i64 = v
                    .extract()
                    .map_err(|_| PyValueError::new_err("control `move` must be -1, 0 or 1"))?;
                if !(-1..=1).contains(&m) {
                    return Err(PyValueError::new_err(format!(
                        "control `move` must be -1, 0 or 1, got {m}"
                    )));
                }
                c.move_x = m as i8;
            }
            "aim" => {
                c.aim = v
                    .extract()
                    .map_err(|_| PyValueError::new_err("control `aim` must be a number"))?;
                if !c.aim.is_finite() {
                    return Err(PyValueError::new_err("control `aim` must be finite"));
                }
            }
            "jump" => c.jump = flag(&key, &v)?,
            "fly" => c.fly = flag(&key, &v)?,
            "fire" => c.fire = flag(&key, &v)?,
            "kick" => c.kick = flag(&key, &v)?,
            "interact" => c.interact = flag(&key, &v)?,
            "drink" => c.drink = flag(&key, &v)?,
            "pour" => c.pour = flag(&key, &v)?,
            "fill" => c.fill = flag(&key, &v)?,
            "throw" => c.throw = flag(&key, &v)?,
            "select_wand" => c.select_wand = slot(&key, &v)?,
            "select_bottle" => c.select_bottle = slot(&key, &v)?,
            "drop" => c.drop = drop_from(&v)?,
            other => {
                return Err(PyValueError::new_err(format!(
                    "unknown control `{other}`; use {CONTROL_KEYS}"
                )))
            }
        }
    }
    Ok(c)
}

pub(crate) fn get<'py, T: FromPyObjectOwned<'py>>(
    d: &Bound<'py, PyDict>,
    key: &str,
) -> PyResult<Option<T>> {
    match d.get_item(key)? {
        Some(v) if !v.is_none() => v.extract::<T>().map(Some).map_err(Into::into),
        _ => Ok(None),
    }
}

pub(crate) fn need<'py, T: FromPyObjectOwned<'py>>(
    d: &Bound<'py, PyDict>,
    key: &str,
) -> PyResult<T> {
    get(d, key)?.ok_or_else(|| PyValueError::new_err(format!("wand stats need `{key}`")))
}

/// Wand stats from a dict. `shuffle`, `spells_per_cast`, `spread` and `speed_multiplier` may be
/// left out (false, 1, 0, 1); the rest are required.
pub(crate) fn wand_stats(d: &Bound<'_, PyDict>) -> PyResult<WandStats> {
    Ok(WandStats {
        shuffle: get(d, "shuffle")?.unwrap_or(false),
        spells_per_cast: get(d, "spells_per_cast")?.unwrap_or(1),
        cast_delay: need(d, "cast_delay")?,
        recharge: need(d, "recharge")?,
        mana_max: need(d, "mana_max")?,
        mana_charge_speed: need(d, "mana_charge_speed")?,
        capacity: need(d, "capacity")?,
        spread: get(d, "spread")?.unwrap_or(0.0),
        speed_multiplier: get(d, "speed_multiplier")?.unwrap_or(1.0),
    })
}

pub(crate) fn stats_to_dict<'py>(py: Python<'py>, s: &WandStats) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("shuffle", s.shuffle)?;
    d.set_item("spells_per_cast", s.spells_per_cast)?;
    d.set_item("cast_delay", s.cast_delay)?;
    d.set_item("recharge", s.recharge)?;
    d.set_item("mana_max", s.mana_max)?;
    d.set_item("mana_charge_speed", s.mana_charge_speed)?;
    d.set_item("capacity", s.capacity)?;
    d.set_item("spread", s.spread)?;
    d.set_item("speed_multiplier", s.speed_multiplier)?;
    Ok(d)
}

pub(crate) fn statuses_dict<'py>(
    py: Python<'py>,
    s: &[(String, u32)],
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    for (k, v) in s {
        d.set_item(k, v)?;
    }
    Ok(d)
}

pub(crate) fn entity_dict<'py>(py: Python<'py>, e: &EntityView) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("id", e.id)?;
    d.set_item("kind", &e.kind)?;
    d.set_item("x", e.x)?;
    d.set_item("y", e.y)?;
    d.set_item("w", e.w)?;
    d.set_item("h", e.h)?;
    d.set_item("hp", e.hp)?;
    d.set_item("hp_max", e.hp_max)?;
    d.set_item("vx", e.vx)?;
    d.set_item("vy", e.vy)?;
    d.set_item("detail", &e.detail)?;
    d.set_item("statuses", statuses_dict(py, &e.statuses)?)?;
    if let Some(parts) = &e.contents {
        d.set_item("contents", contents_list(py, parts)?)?;
    }
    if let Some(w) = &e.wand {
        d.set_item("wand", wand_dict(py, w)?)?;
    }
    Ok(d)
}

/// `[{"material": key, "amount": cells}, ...]`.
pub(crate) fn contents_list<'py>(
    py: Python<'py>,
    parts: &[(String, u32)],
) -> PyResult<Bound<'py, PyList>> {
    let list = PyList::empty(py);
    for (material, amount) in parts {
        let part = PyDict::new(py);
        part.set_item("material", material)?;
        part.set_item("amount", amount)?;
        list.append(part)?;
    }
    Ok(list)
}

/// A mixture from Python: a list of `{"material": key, "amount": cells}`.
pub(crate) fn contents_arg(value: &Bound<'_, PyAny>) -> PyResult<Vec<(String, u32)>> {
    let bad = || {
        PyValueError::new_err("`contents` must be a list of {\"material\": key, \"amount\": cells}")
    };
    let list = value.cast::<PyList>().map_err(|_| bad())?;
    list.iter()
        .map(|item| {
            let d = item.cast::<PyDict>().map_err(|_| bad())?;
            // A wrong type or a number out of range is the caller's mistake: `ValueError`.
            let material: String = get(d, "material").map_err(|_| bad())?.ok_or_else(bad)?;
            let amount: u32 = get(d, "amount").map_err(|_| bad())?.ok_or_else(bad)?;
            Ok((material, amount))
        })
        .collect()
}

pub(crate) fn wand_dict<'py>(py: Python<'py>, w: &WandView) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("id", w.id)?;
    d.set_item("stats", stats_to_dict(py, &w.stats)?)?;
    let slots = PyList::empty(py);
    for s in &w.slots {
        match s {
            None => slots.append(py.None())?,
            Some((spell, uses)) => {
                let item = PyDict::new(py);
                item.set_item("spell", spell)?;
                item.set_item("uses", uses)?;
                slots.append(item)?;
            }
        }
    }
    d.set_item("slots", slots)?;
    d.set_item("always_cast", &w.always_cast)?;
    d.set_item("mana", w.mana)?;
    d.set_item("mana_max", w.stats.mana_max)?;
    d.set_item("cooldown", w.cooldown)?;
    Ok(d)
}

pub(crate) fn player_dict<'py>(py: Python<'py>, p: &PlayerView) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("id", p.id)?;
    d.set_item("x", p.x)?;
    d.set_item("y", p.y)?;
    d.set_item("w", p.w)?;
    d.set_item("h", p.h)?;
    d.set_item("hit", p.hit)?;
    d.set_item("vx", p.vx)?;
    d.set_item("vy", p.vy)?;
    d.set_item("hp", p.hp)?;
    d.set_item("hp_max", p.hp_max)?;
    d.set_item("dead", p.dead)?;
    d.set_item("facing", p.facing)?;
    d.set_item("on_ground", p.on_ground)?;
    d.set_item("fly", p.fly)?;
    d.set_item("breath", p.breath)?;
    d.set_item("invincible", p.invincible)?;
    d.set_item("aim", p.aim)?;
    d.set_item("active_wand", p.active_wand)?;
    d.set_item("active_bottle", p.active_bottle)?;
    let wands = PyList::empty(py);
    for w in &p.wands {
        wands.append(wand_dict(py, w)?)?;
    }
    d.set_item("wands", wands)?;
    let spells = PyList::empty(py);
    for (spell, uses) in &p.spells {
        let s = PyDict::new(py);
        s.set_item("spell", spell)?;
        s.set_item("uses", uses)?;
        spells.append(s)?;
    }
    d.set_item("spells", spells)?;
    let bottles = PyList::empty(py);
    for ((material, amount), parts) in p.bottles.iter().zip(&p.bottle_contents) {
        let b = PyDict::new(py);
        // The largest share, or None when empty; the amount counts all materials.
        b.set_item("material", (!material.is_empty()).then_some(material))?;
        b.set_item("amount", amount)?;
        b.set_item("contents", contents_list(py, parts)?)?;
        bottles.append(b)?;
    }
    d.set_item("bottles", bottles)?;
    d.set_item("statuses", statuses_dict(py, &p.statuses)?)?;
    Ok(d)
}

pub(crate) fn json_to_py<'py>(
    py: Python<'py>,
    v: &serde_json::Value,
) -> PyResult<Bound<'py, PyAny>> {
    use serde_json::Value as J;
    Ok(match v {
        J::Null => py.None().into_bound(py),
        J::Bool(b) => (*b).into_pyobject(py)?.to_owned().into_any(),
        J::Number(n) => match (n.as_i64(), n.as_u64()) {
            (Some(i), _) => i.into_pyobject(py)?.into_any(),
            (None, Some(u)) => u.into_pyobject(py)?.into_any(),
            _ => n.as_f64().unwrap_or(0.0).into_pyobject(py)?.into_any(),
        },
        J::String(s) => s.into_pyobject(py)?.into_any(),
        J::Array(a) => {
            let list = PyList::empty(py);
            for item in a {
                list.append(json_to_py(py, item)?)?;
            }
            list.into_any()
        }
        J::Object(o) => {
            let d = PyDict::new(py);
            for (k, item) in o {
                d.set_item(k, json_to_py(py, item)?)?;
            }
            d.into_any()
        }
    })
}

/// The item a Python call describes.
#[allow(clippy::too_many_arguments)]
pub(crate) fn item_spec(
    kind: &str,
    material: Option<String>,
    amount: Option<u32>,
    tier: Option<u32>,
    spell: Option<String>,
    stats: Option<&Bound<'_, PyDict>>,
    spells: Option<Vec<Option<String>>>,
    contents: Option<Vec<(String, u32)>>,
) -> PyResult<ItemSpec> {
    Ok(match kind {
        "bottle" => match contents {
            Some(contents) => ItemSpec::MixedBottle { contents },
            None => ItemSpec::Bottle { material, amount },
        },
        k if k.starts_with("potion_") => ItemSpec::Bottle {
            material: Some(k.to_string()),
            amount,
        },
        "wand" => match stats {
            Some(s) => ItemSpec::CustomWand {
                stats: wand_stats(s)?,
                spells: spells.unwrap_or_default(),
            },
            None => ItemSpec::Wand {
                tier: tier.unwrap_or(1),
            },
        },
        "spell" => ItemSpec::Spell { key: spell },
        k if k.starts_with("barrel_") => ItemSpec::Barrel {
            kind: k.to_string(),
        },
        other => {
            return Err(PyValueError::new_err(format!(
                "unknown item {other:?}; use bottle, potion_*, wand, spell or barrel_*"
            )))
        }
    })
}
