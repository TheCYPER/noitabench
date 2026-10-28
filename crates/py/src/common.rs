//! Helpers shared by the Python classes: error mapping, argument checks, mask parsing.
//!
//! Errors follow `.trellis/spec/backend/error-handling.md`: `ValueError` for bad input,
//! `RuntimeError` for internal trouble, `FileNotFoundError` for a missing file.

use cogbench_sim::{
    Content, Error, Event, Kind, KindMask, QueryMask, RecipeDef, Tuning, Value, World,
};
use pyo3::exceptions::{PyFileNotFoundError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::PathBuf;
use std::sync::{Arc, OnceLock};

pub(crate) fn to_py_err(e: Error) -> PyErr {
    match &e {
        Error::Io { source, .. } if source.kind() == std::io::ErrorKind::NotFound => {
            PyFileNotFoundError::new_err(e.to_string())
        }
        Error::Io { .. } => PyRuntimeError::new_err(e.to_string()),
        _ => PyValueError::new_err(e.to_string()),
    }
}

/// The content compiled into the extension, parsed once per process.
pub(crate) fn embedded_content() -> PyResult<Arc<Content>> {
    static CONTENT: OnceLock<Result<Arc<Content>, String>> = OnceLock::new();
    CONTENT
        .get_or_init(|| Content::embedded().map(Arc::new).map_err(|e| e.to_string()))
        .clone()
        .map_err(PyRuntimeError::new_err)
}

pub(crate) fn content_for(content_dir: Option<PathBuf>) -> PyResult<Arc<Content>> {
    match content_dir {
        None => embedded_content(),
        Some(dir) => Content::from_dir(&dir, Tuning::default())
            .map(Arc::new)
            .map_err(to_py_err),
    }
}

/// The `recipes` argument of a constructor: `None` (draw them from the rule seed), a list of
/// `{"potion": key, "inputs": [a, b, c]}` dicts, or an empty list (no recipes).
pub(crate) fn recipes_arg(arg: Option<&Bound<'_, PyAny>>) -> PyResult<Option<Vec<RecipeDef>>> {
    let Some(list) = arg.filter(|a| !a.is_none()) else {
        return Ok(None);
    };
    let bad = |what: &str| PyValueError::new_err(format!("recipes: {what}"));
    let mut out = Vec::new();
    for item in list
        .try_iter()
        .map_err(|_| bad("expected a list of {\"potion\", \"inputs\"} dicts"))?
    {
        let item = item?;
        let d = item
            .cast::<PyDict>()
            .map_err(|_| bad("each recipe is a dict"))?;
        let potion: String = d
            .get_item("potion")?
            .ok_or_else(|| bad("a recipe needs `potion`"))?
            .extract()
            .map_err(|_| bad("`potion` is a material key"))?;
        let inputs: Vec<String> = d
            .get_item("inputs")?
            .ok_or_else(|| bad("a recipe needs `inputs`"))?
            .extract()
            .map_err(|_| bad("`inputs` is a list of three material keys"))?;
        let inputs: [String; 3] = inputs
            .try_into()
            .map_err(|_| bad("`inputs` needs exactly three material keys"))?;
        out.push(RecipeDef { potion, inputs });
    }
    Ok(Some(out))
}

/// `content` with the recipes of `rule_seed` (or the given ones) attached. An empty list leaves
/// the content as it is.
pub(crate) fn with_recipes(
    content: Arc<Content>,
    rule_seed: u64,
    recipes: Option<Vec<RecipeDef>>,
) -> PyResult<Arc<Content>> {
    let recipes = match recipes {
        Some(r) => r,
        None => cogbench_rules::recipes_embedded(rule_seed)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?,
    };
    if recipes.is_empty() {
        return Ok(content);
    }
    content
        .with_recipes(&recipes)
        .map(Arc::new)
        .map_err(to_py_err)
}

/// An integer argument that must lie in `0..=max` (a Python `int` outside the range of the Rust
/// type would otherwise surface as `OverflowError`; the contract says `ValueError`).
pub(crate) fn bounded<T: TryFrom<i64>>(name: &str, value: i64, max: impl Into<i64>) -> PyResult<T> {
    let max = max.into();
    if !(0..=max).contains(&value) {
        return Err(PyValueError::new_err(format!(
            "{name} must be 0..={max}, got {value}"
        )));
    }
    T::try_from(value).map_err(|_| PyValueError::new_err(format!("{name} out of range")))
}

/// An `i32` argument. The Python side is taken as `i128`, so every int up to 128 bits gives a
/// `ValueError` here rather than an `OverflowError` from the argument conversion.
pub(crate) fn to_i32(name: &str, value: i128) -> PyResult<i32> {
    i32::try_from(value)
        .map_err(|_| PyValueError::new_err(format!("{name} must fit in 32 bits, got {value}")))
}

/// A cell count argument: `0..=u32::MAX`.
pub(crate) fn cell_count(name: &str, value: i128) -> PyResult<u32> {
    u32::try_from(value)
        .map_err(|_| PyValueError::new_err(format!("{name} must be 0..={}, got {value}", u32::MAX)))
}

/// The kinds a Python `mask` argument names: a preset (`"any"`, `"surfaces"`,
/// `"surfaces_and_liquids"`, `"platforms"`, `"blocking"`) or a list of kind names
/// (`["static", "powder"]`).
pub(crate) fn parse_kinds(mask: &Bound<'_, PyAny>) -> PyResult<KindMask> {
    if let Ok(name) = mask.extract::<String>() {
        return KindMask::preset(&name).ok_or_else(|| {
            PyValueError::new_err(format!(
                "unknown mask `{name}`; use any, surfaces, surfaces_and_liquids, platforms, \
                 blocking or a list of kinds"
            ))
        });
    }
    let names: Vec<String> = mask
        .extract()
        .map_err(|_| PyValueError::new_err("mask must be a preset name or a list of kind names"))?;
    let mut kinds = KindMask::NONE;
    for name in &names {
        let kind = Kind::ALL.iter().find(|k| k.name() == name).ok_or_else(|| {
            PyValueError::new_err(format!(
                "unknown kind `{name}`; use air, gas, fire, liquid, powder, static"
            ))
        })?;
        kinds = kinds.union(KindMask::of(*kind));
    }
    Ok(kinds)
}

/// A query mask: the kinds of `mask` (default `"blocking"`), optionally minus the material
/// `ignore` (a material key).
pub(crate) fn query_mask(
    world: &World,
    mask: Option<&Bound<'_, PyAny>>,
    ignore: Option<&str>,
) -> PyResult<QueryMask> {
    let kinds = mask.map_or(Ok(KindMask::BLOCKING), parse_kinds)?;
    let mut q = QueryMask::new(kinds);
    if let Some(key) = ignore {
        let index =
            world.content().mats.index_of(key).ok_or_else(|| {
                PyValueError::new_err(format!("unknown material `{key}` in ignore"))
            })?;
        q = q.passing(index);
    }
    Ok(q)
}

pub(crate) fn event_to_dict<'py>(
    py: Python<'py>,
    content: &Content,
    ev: &Event,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    for (name, value) in ev.fields(content) {
        match value {
            Value::Int(n) => d.set_item(name, n)?,
            Value::Float(f) => d.set_item(name, f)?,
            Value::Str(s) => d.set_item(name, s)?,
        }
    }
    Ok(d)
}

/// Map an error of the game crate (`cogbench-game`) the same way.
pub(crate) fn game_err(e: cogbench_game::Error) -> PyErr {
    match e {
        cogbench_game::Error::Sim(inner) => to_py_err(inner),
        cogbench_game::Error::Io { source, path }
            if source.kind() == std::io::ErrorKind::NotFound =>
        {
            PyFileNotFoundError::new_err(format!("reading {}: {source}", path.display()))
        }
        cogbench_game::Error::Io { .. } => PyRuntimeError::new_err(e.to_string()),
        other => PyValueError::new_err(other.to_string()),
    }
}
