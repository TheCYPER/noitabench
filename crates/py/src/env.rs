//! `noitabench_core.Env`: the bare pixel world (contract section 6).

use cogbench_sim::worldfile::load_world_files;
use cogbench_sim::{DirtyMode, ExplosionSpec, RecordConfig, World};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};
use std::path::PathBuf;
use std::sync::Arc;

use crate::common::{bounded, content_for, event_to_dict, recipes_arg, to_py_err, with_recipes};
use crate::queries;

/// A simulated world. See `.trellis/spec/backend/contracts.md` section 6.
#[pyclass(module = "noitabench_core")]
pub(crate) struct Env {
    world: World,
}

#[pymethods]
impl Env {
    /// An empty (all air) world of `width` x `height` cells. Without `rule_seed` (or `recipes`)
    /// the world has no secret recipes; with one, it has those of that rule seed (the embedded
    /// content only).
    #[new]
    #[pyo3(signature = (width, height, seed, content_dir=None, rule_seed=None, recipes=None))]
    fn new(
        width: i32,
        height: i32,
        seed: u64,
        content_dir: Option<PathBuf>,
        rule_seed: Option<u64>,
        recipes: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Env> {
        let mut content = content_for(content_dir.clone())?;
        let explicit = recipes_arg(recipes)?;
        if rule_seed.is_some() || explicit.is_some() {
            if content_dir.is_some() && explicit.is_none() {
                return Err(PyValueError::new_err(
                    "rule_seed draws recipes for the embedded content; give `recipes` with a \
                     content_dir",
                ));
            }
            content = with_recipes(content, rule_seed.unwrap_or(0), explicit)?;
        }
        let mut world = World::new(width, height, seed, content).map_err(to_py_err)?;
        world.set_rule_seed(rule_seed.unwrap_or(0));
        Ok(Env { world })
    }

    /// Load a world file pair written by the world generator. The world has the secret recipes
    /// of its rule seed (from the file); `recipes` replaces them (`[]` for none).
    #[staticmethod]
    #[pyo3(signature = (png_path, json_path, seed=None, content_dir=None, recipes=None))]
    fn from_world(
        png_path: PathBuf,
        json_path: PathBuf,
        seed: Option<u64>,
        content_dir: Option<PathBuf>,
        recipes: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Env> {
        let file = load_world_files(&png_path, &json_path).map_err(to_py_err)?;
        let seed = seed.unwrap_or(file.meta.seed);
        let explicit = recipes_arg(recipes)?;
        let mut content = content_for(content_dir.clone())?;
        if content_dir.is_none() || explicit.is_some() {
            content = with_recipes(content, file.meta.rule_seed, explicit)?;
        }
        let mut world = World::from_indices(
            file.meta.width,
            file.meta.height,
            seed,
            &file.indices,
            content,
        )
        .map_err(to_py_err)?;
        world.set_rule_seed(file.meta.rule_seed);
        Ok(Env { world })
    }

    /// Advance `n` frames at 60 Hz.
    fn step_frames(&mut self, n: u32) -> PyResult<()> {
        self.world.step_frames(n).map_err(to_py_err)
    }

    /// Paint a filled disc of a material (for tests and demos).
    fn paint(&mut self, x: i32, y: i32, radius: i32, material_key: &str) -> PyResult<()> {
        self.world
            .paint(x, y, radius, material_key)
            .map_err(to_py_err)
    }

    /// Fill the rectangle `[x, x+w) x [y, y+h)` with a material.
    fn fill_rect(&mut self, x: i32, y: i32, w: i32, h: i32, material_key: &str) -> PyResult<()> {
        self.world
            .fill_rect(x, y, w, h, material_key)
            .map_err(to_py_err)
    }

    /// Set a burnable cell alight; returns whether it caught.
    fn ignite(&mut self, x: i32, y: i32) -> bool {
        self.world.ignite(x, y)
    }

    /// Run a ray explosion now; returns the number of cells destroyed.
    #[pyo3(signature = (x, y, radius, ray_energy, max_durability, fire_percent=5))]
    fn explode(
        &mut self,
        x: i32,
        y: i32,
        radius: i64,
        ray_energy: i64,
        max_durability: i64,
        fire_percent: i64,
    ) -> PyResult<u32> {
        let spec = ExplosionSpec {
            fire_percent: bounded("fire_percent", fire_percent, 100)?,
            ..ExplosionSpec::new(
                x,
                y,
                bounded("radius", radius, u32::MAX)?,
                bounded("ray_energy", ray_energy, u32::MAX)?,
                bounded("max_durability", max_durability, 255)?,
            )
        };
        self.world.explode(spec).map_err(to_py_err)
    }

    /// What lies under the box `[x, x+w) x [y, y+h)`: `{inside, outside, burning, kinds,
    /// materials}`; `kinds` and `materials` map names to cell counts (non-zero only).
    fn overlap<'py>(
        &self,
        py: Python<'py>,
        x: i128,
        y: i128,
        w: i128,
        h: i128,
    ) -> PyResult<Bound<'py, PyDict>> {
        queries::overlap(py, &self.world, (x, y, w, h))
    }

    /// Walk the cells from `(x0, y0)` to `(x1, y1)` and return the first one `mask` stops on, as
    /// `{x, y, material, kind, last_free, step, steps}`, or `None` when the line is free. Cells
    /// outside the world stop every mask (material `"boundary"`).
    #[pyo3(signature = (x0, y0, x1, y1, mask=None, ignore=None))]
    #[allow(clippy::too_many_arguments)]
    fn raycast<'py>(
        &self,
        py: Python<'py>,
        x0: i128,
        y0: i128,
        x1: i128,
        y1: i128,
        mask: Option<Bound<'py, PyAny>>,
        ignore: Option<&str>,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        queries::raycast(py, &self.world, (x0, y0), (x1, y1), mask.as_ref(), ignore)
    }

    /// Move the box `(x, y, w, h)` by `(dx, dy)` against `mask`, sideways first: `{x, y,
    /// blocked_x, blocked_y, climbed}` where `blocked_*` is the key of the material that cut the
    /// move short (or `None`) and `climbed` the cells lifted over ledges (`step_up` > 0).
    #[pyo3(signature = (x, y, w, h, dx, dy, mask=None, step_up=0, ignore=None))]
    #[allow(clippy::too_many_arguments)]
    fn sweep_box<'py>(
        &self,
        py: Python<'py>,
        x: i128,
        y: i128,
        w: i128,
        h: i128,
        dx: i128,
        dy: i128,
        mask: Option<Bound<'py, PyAny>>,
        step_up: i128,
        ignore: Option<&str>,
    ) -> PyResult<Bound<'py, PyDict>> {
        queries::sweep_box(
            py,
            &self.world,
            (x, y, w, h),
            (dx, dy),
            mask.as_ref(),
            step_up,
            ignore,
        )
    }

    /// Raw contact damage of one frame on the box (HAZ-R01) with the damage table of
    /// `materials.json`: `{raw, parts}`, `parts` a list of `{material, cells, counted, damage}`
    /// (`cells` overlap the box, `counted` of them are paid for). A material counts from
    /// `min_cells` cells and for at most `max_cells`.
    #[pyo3(signature = (x, y, w, h, min_cells=4, max_cells=85))]
    #[allow(clippy::too_many_arguments)]
    fn contact_damage<'py>(
        &self,
        py: Python<'py>,
        x: i128,
        y: i128,
        w: i128,
        h: i128,
        min_cells: i128,
        max_cells: i128,
    ) -> PyResult<Bound<'py, PyDict>> {
        queries::contact_damage(py, &self.world, (x, y, w, h), (min_cells, max_cells))
    }

    /// `width * height` bytes: the material index of every cell, row-major.
    fn grid<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        queries::grid(py, &self.world)
    }

    /// `{material, index, burning, lifetime}` of one cell.
    fn cell<'py>(&self, py: Python<'py>, x: i32, y: i32) -> PyResult<Bound<'py, PyDict>> {
        queries::cell(py, &self.world, x, y)
    }

    /// The whole state as bytes; `restore` brings it back bit-exactly.
    fn snapshot<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let blob = self.world.snapshot().map_err(to_py_err)?;
        Ok(PyBytes::new(py, &blob))
    }

    /// Replace the state with a snapshot (also clears the pending event list).
    fn restore(&mut self, blob: &[u8]) -> PyResult<()> {
        self.world.restore(blob).map_err(to_py_err)
    }

    /// Events since the last call, oldest first.
    fn events<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let content = Arc::clone(self.world.content());
        let dicts = self
            .world
            .drain_events()
            .iter()
            .map(|e| event_to_dict(py, &content, e))
            .collect::<PyResult<Vec<_>>>()?;
        PyList::new(py, dicts)
    }

    /// Start writing a recording (`cogbench-rec/0`) into `dir`.
    #[pyo3(signature = (dir, frame_stride, rect=None, run_id=None, notes=None, created=None))]
    fn start_recording(
        &mut self,
        dir: PathBuf,
        frame_stride: u32,
        rect: Option<(i32, i32, i32, i32)>,
        run_id: Option<String>,
        notes: Option<String>,
        created: Option<String>,
    ) -> PyResult<()> {
        let mut cfg = RecordConfig::new(dir, frame_stride);
        cfg.rect = rect;
        cfg.run_id = run_id;
        cfg.notes = notes.unwrap_or_default();
        cfg.created = created;
        self.world.start_recording(cfg).map_err(to_py_err)
    }

    /// Finish the recording; returns `{dir, frames, first_frame, last_frame}`.
    fn stop_recording<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let s = self.world.stop_recording().map_err(to_py_err)?;
        let d = PyDict::new(py);
        d.set_item("dir", s.dir.display().to_string())?;
        d.set_item("frames", s.frames)?;
        d.set_item("first_frame", s.first_frame)?;
        d.set_item("last_frame", s.last_frame)?;
        Ok(d)
    }

    /// Hash of the full simulation state (frame, seed, cells, pending explosions).
    fn state_hash(&self) -> u64 {
        self.world.state_hash()
    }

    /// Visit every cell every frame (`True`, slow, for tests) or only awake chunks (`False`).
    fn set_all_dirty(&mut self, enabled: bool) {
        self.world.set_dirty_mode(if enabled {
            DirtyMode::AllDirty
        } else {
            DirtyMode::Normal
        });
    }

    /// Number of chunks that will be visited next frame.
    fn awake_chunks(&self) -> usize {
        let (cw, ch) = self.world.grid().chunk_dims();
        (0..ch)
            .flat_map(|cy| (0..cw).map(move |cx| (cx, cy)))
            .filter(|&(cx, cy)| !self.world.grid().dirty_rect(cx, cy).is_empty())
            .count()
    }

    /// Explosions waiting for the next frame.
    fn pending_explosions(&self) -> usize {
        self.world.pending_explosions().len()
    }

    /// Material keys in index order (`keys[i]` is the material with cell value `i`).
    fn material_keys(&self) -> Vec<String> {
        queries::material_keys(&self.world)
    }

    /// Hash of the materials, reactions and tuning this world runs with.
    #[getter]
    fn content_hash(&self) -> u64 {
        self.world.content().hash
    }

    #[getter]
    fn width(&self) -> i32 {
        self.world.width()
    }

    #[getter]
    fn height(&self) -> i32 {
        self.world.height()
    }

    #[getter]
    fn frame(&self) -> u64 {
        self.world.frame()
    }

    #[getter]
    fn seed(&self) -> u64 {
        self.world.seed()
    }

    #[getter]
    fn rule_seed(&self) -> u64 {
        self.world.rule_seed()
    }
}
