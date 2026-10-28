//! The read-only grid questions of the Python API (contract section 6), shared by `Env` and
//! `Game`: both own a `World` and answer them the same way.

use cogbench_sim::{Aabb, ContactRules, Kind, World};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};

use crate::common::{cell_count, query_mask, to_i32};

fn aabb(x: i128, y: i128, w: i128, h: i128) -> PyResult<Aabb> {
    Ok(Aabb::new(
        to_i32("x", x)?,
        to_i32("y", y)?,
        to_i32("w", w)?,
        to_i32("h", h)?,
    ))
}

pub(crate) fn overlap<'py>(
    py: Python<'py>,
    world: &World,
    (x, y, w, h): (i128, i128, i128, i128),
) -> PyResult<Bound<'py, PyDict>> {
    let o = world.overlap(aabb(x, y, w, h)?);
    let d = PyDict::new(py);
    d.set_item("inside", o.inside)?;
    d.set_item("outside", o.outside)?;
    d.set_item("burning", o.burning())?;
    let kinds = PyDict::new(py);
    for kind in Kind::ALL {
        if o.kind_count(kind) > 0 {
            kinds.set_item(kind.name(), o.kind_count(kind))?;
        }
    }
    d.set_item("kinds", kinds)?;
    let mats = PyDict::new(py);
    for &(m, n) in o.materials() {
        mats.set_item(world.content().mats.key_of(m), n)?;
    }
    d.set_item("materials", mats)?;
    Ok(d)
}

pub(crate) fn raycast<'py>(
    py: Python<'py>,
    world: &World,
    from: (i128, i128),
    to: (i128, i128),
    mask: Option<&Bound<'py, PyAny>>,
    ignore: Option<&str>,
) -> PyResult<Option<Bound<'py, PyDict>>> {
    let q = query_mask(world, mask, ignore)?;
    let from = (to_i32("x0", from.0)?, to_i32("y0", from.1)?);
    let to = (to_i32("x1", to.0)?, to_i32("y1", to.1)?);
    let Some(hit) = world.raycast(from, to, q) else {
        return Ok(None);
    };
    let d = PyDict::new(py);
    d.set_item("x", hit.x)?;
    d.set_item("y", hit.y)?;
    d.set_item("material", world.content().mats.key_of(hit.material))?;
    d.set_item("kind", hit.kind.name())?;
    d.set_item("last_free", hit.last_free)?;
    d.set_item("step", hit.step)?;
    d.set_item("steps", hit.steps)?;
    Ok(Some(d))
}

pub(crate) fn sweep_box<'py>(
    py: Python<'py>,
    world: &World,
    b: (i128, i128, i128, i128),
    (dx, dy): (i128, i128),
    mask: Option<&Bound<'py, PyAny>>,
    step_up: i128,
    ignore: Option<&str>,
) -> PyResult<Bound<'py, PyDict>> {
    let q = query_mask(world, mask, ignore)?;
    let s = world.sweep_box(
        aabb(b.0, b.1, b.2, b.3)?,
        to_i32("dx", dx)?,
        to_i32("dy", dy)?,
        q,
        to_i32("step_up", step_up)?,
    );
    let key = |m: Option<u8>| m.map(|m| world.content().mats.key_of(m).to_string());
    let d = PyDict::new(py);
    d.set_item("x", s.x)?;
    d.set_item("y", s.y)?;
    d.set_item("blocked_x", key(s.blocked_x))?;
    d.set_item("blocked_y", key(s.blocked_y))?;
    d.set_item("climbed", s.climbed)?;
    Ok(d)
}

pub(crate) fn contact_damage<'py>(
    py: Python<'py>,
    world: &World,
    b: (i128, i128, i128, i128),
    (min_cells, max_cells): (i128, i128),
) -> PyResult<Bound<'py, PyDict>> {
    let c = world.contact_damage(
        aabb(b.0, b.1, b.2, b.3)?,
        ContactRules {
            min_cells: cell_count("min_cells", min_cells)?,
            max_cells: cell_count("max_cells", max_cells)?,
        },
    );
    let parts = PyList::empty(py);
    for part in &c.parts {
        let p = PyDict::new(py);
        p.set_item("material", world.content().mats.key_of(part.material))?;
        p.set_item("cells", part.cells)?;
        p.set_item("counted", part.counted)?;
        p.set_item("damage", part.damage)?;
        parts.append(p)?;
    }
    let d = PyDict::new(py);
    d.set_item("raw", c.raw)?;
    d.set_item("parts", parts)?;
    Ok(d)
}

pub(crate) fn grid<'py>(py: Python<'py>, world: &World) -> Bound<'py, PyBytes> {
    PyBytes::new(py, &world.grid_bytes())
}

pub(crate) fn cell<'py>(
    py: Python<'py>,
    world: &World,
    x: i32,
    y: i32,
) -> PyResult<Bound<'py, PyDict>> {
    let info = world.cell_info(x, y).ok_or_else(|| {
        PyValueError::new_err(format!(
            "cell ({x}, {y}) is outside the {}x{} world",
            world.width(),
            world.height()
        ))
    })?;
    let d = PyDict::new(py);
    d.set_item("material", info.key)?;
    d.set_item("index", info.material)?;
    d.set_item("burning", info.burning)?;
    d.set_item("lifetime", info.lifetime)?;
    Ok(d)
}

pub(crate) fn material_keys(world: &World) -> Vec<String> {
    world.content().mats.iter().map(|m| m.key.clone()).collect()
}
