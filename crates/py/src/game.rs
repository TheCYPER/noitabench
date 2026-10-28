//! `noitabench_core.Game`: the pixel world with the player, enemies, items and projectiles on
//! top of it (`cogbench-game`), stepped under per-frame controls.

use cogbench_game::{BlastSpec, Controls, Game as Inner, WandEdit, WorldOptions};
use cogbench_sim::{ExplosionSpec, RecordConfig};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};
use std::path::PathBuf;
use std::sync::Arc;

use crate::common::{
    bounded, content_for, event_to_dict, game_err, recipes_arg, to_py_err, with_recipes,
};
use crate::convert::{
    contents_arg, controls_from, entity_dict, get, item_spec, json_to_py, player_dict, wand_stats,
};
use crate::queries;

/// A game: world, player, enemies, items. See `.trellis/spec/backend/contracts.md` sections 6
/// and 11.
#[pyclass(module = "noitabench_core")]
pub(crate) struct Game {
    inner: Inner,
}

#[pymethods]
impl Game {
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
    ) -> PyResult<Game> {
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
        let mut world =
            cogbench_sim::World::new(width, height, seed, content).map_err(to_py_err)?;
        world.set_rule_seed(rule_seed.unwrap_or(0));
        Ok(Game {
            inner: Inner::new(world).map_err(game_err)?,
        })
    }

    /// Load a world file pair of the generator and place its player, enemies and items.
    /// The world runs the original reaction table; `reactions_json` (the text of a table) is
    /// only for tests of other tables. The secret recipes are those of the rule seed (the
    /// argument, or the one in the world file); `recipes` replaces them (a list of `{"potion",
    /// "inputs"}` dicts; `[]` for none).
    #[staticmethod]
    #[pyo3(signature = (png_path, json_path, seed=None, rule_seed=None, reactions_json=None, recipes=None))]
    fn from_world(
        png_path: PathBuf,
        json_path: PathBuf,
        seed: Option<u64>,
        rule_seed: Option<u64>,
        reactions_json: Option<String>,
        recipes: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Game> {
        let options = WorldOptions {
            seed,
            rule_seed,
            reactions_json,
            recipes: recipes_arg(recipes)?,
        };
        let inner = Inner::from_world_files(&png_path, &json_path, &options).map_err(game_err)?;
        Ok(Game { inner })
    }

    // ----- running -----------------------------------------------------------------------

    /// Advance `frames` frames. `controls` is a dict held for all of them, or a list with one
    /// dict per frame; `None` holds nothing.
    #[pyo3(signature = (frames=1, controls=None))]
    fn step(&mut self, frames: u32, controls: Option<&Bound<'_, PyAny>>) -> PyResult<()> {
        let per_frame: Vec<Controls> = match controls {
            None => Vec::new(),
            Some(c) => {
                if let Ok(d) = c.cast::<PyDict>() {
                    vec![controls_from(d)?]
                } else if let Ok(list) = c.cast::<PyList>() {
                    list.iter()
                        .map(|item| {
                            let d = item
                                .cast::<PyDict>()
                                .map_err(|_| PyValueError::new_err("controls lists hold dicts"))?;
                            controls_from(d)
                        })
                        .collect::<PyResult<_>>()?
                } else {
                    return Err(PyValueError::new_err(
                        "controls must be a dict or a list of dicts",
                    ));
                }
            }
        };
        if per_frame.len() > 1 && per_frame.len() != frames as usize {
            return Err(PyValueError::new_err(format!(
                "{} control dicts for {frames} frames: give one dict or one per frame",
                per_frame.len()
            )));
        }
        let idle = Controls::default();
        for i in 0..frames as usize {
            let c = match per_frame.len() {
                0 => &idle,
                1 => &per_frame[0],
                _ => &per_frame[i],
            };
            self.inner.step(c).map_err(game_err)?;
        }
        Ok(())
    }

    // ----- looking -----------------------------------------------------------------------

    /// The player as a dict (position, health, statuses, wands, bottles, spells), or `None`.
    fn player<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
        self.inner.player().map(|p| player_dict(py, &p)).transpose()
    }

    /// The player, enemies, items and projectiles as dicts `{id, kind, x, y, w, h, hp, hp_max,
    /// vx, vy, detail, statuses}`; `hp` is in displayed units.
    fn entities<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let items = self
            .inner
            .entities()
            .iter()
            .map(|e| entity_dict(py, e))
            .collect::<PyResult<Vec<_>>>()?;
        PyList::new(py, items)
    }

    /// Events since the last call, oldest first.
    fn events<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let content = Arc::clone(self.inner.world().content());
        let dicts = self
            .inner
            .world_mut()
            .drain_events()
            .iter()
            .map(|e| event_to_dict(py, &content, e))
            .collect::<PyResult<Vec<_>>>()?;
        PyList::new(py, dicts)
    }

    /// The markers of the loaded world that are not spawns (encounters, rest areas, the seal).
    fn markers<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let list = PyList::empty(py);
        for m in self.inner.markers() {
            list.append(json_to_py(py, m)?)?;
        }
        Ok(list.into_any())
    }

    fn spell_keys(&self) -> Vec<String> {
        self.inner
            .book()
            .iter()
            .map(|(_, s)| s.key.clone())
            .collect()
    }

    fn enemy_kinds(&self) -> Vec<String> {
        self.inner.defs().enemies.keys().cloned().collect()
    }

    // ----- state -------------------------------------------------------------------------

    /// The whole game as bytes; `restore` brings it back bit-exactly.
    fn snapshot<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let blob = self.inner.snapshot().map_err(game_err)?;
        Ok(PyBytes::new(py, &blob))
    }

    fn restore(&mut self, blob: &[u8]) -> PyResult<()> {
        self.inner.restore(blob).map_err(game_err)
    }

    /// Hash of the whole state (cells, entities, wands).
    fn state_hash(&self) -> u64 {
        self.inner.state_hash()
    }

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
        self.inner.start_recording(cfg).map_err(game_err)
    }

    /// Finish the recording; returns `{dir, frames, first_frame, last_frame}`.
    fn stop_recording<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let s = self.inner.stop_recording().map_err(game_err)?;
        let d = PyDict::new(py);
        d.set_item("dir", s.dir.display().to_string())?;
        d.set_item("frames", s.frames)?;
        d.set_item("first_frame", s.first_frame)?;
        d.set_item("last_frame", s.last_frame)?;
        Ok(d)
    }

    // ----- building scenes ---------------------------------------------------------------

    /// Put the player (with the starter wands) at the cell `(x, y)` it stands in.
    fn spawn_player(&mut self, x: i32, y: i32) -> PyResult<u32> {
        self.inner.spawn_player(x, y).map_err(game_err)
    }

    fn spawn_enemy(&mut self, kind: &str, x: i32, y: i32) -> PyResult<u32> {
        self.inner.spawn_enemy(kind, x, y).map_err(game_err)
    }

    /// Put an item into the world: `bottle` (with `material`, `amount`, or a mixture as
    /// `contents`, a list of `{"material", "amount"}`), `potion_heal` and the other potions,
    /// `wand` (a generated one of `tier`, or `stats` and `spells` for your own), `spell`
    /// (optionally `spell` = key) or a `barrel_*`.
    #[pyo3(signature = (kind, x, y, *, material=None, amount=None, tier=None, spell=None, stats=None, spells=None, contents=None))]
    #[allow(clippy::too_many_arguments)]
    fn spawn_item(
        &mut self,
        kind: &str,
        x: i32,
        y: i32,
        material: Option<String>,
        amount: Option<u32>,
        tier: Option<u32>,
        spell: Option<String>,
        stats: Option<&Bound<'_, PyDict>>,
        spells: Option<Vec<Option<String>>>,
        contents: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<u32> {
        let contents = contents.map(contents_arg).transpose()?;
        let spec = item_spec(kind, material, amount, tier, spell, stats, spells, contents)?;
        self.inner.spawn_item(&spec, x, y).map_err(game_err)
    }

    /// Give the player a wand: `stats` (dict) and the spell keys of its slots (`None` = empty).
    #[pyo3(signature = (stats, spells, always_cast=None))]
    fn give_wand(
        &mut self,
        stats: &Bound<'_, PyDict>,
        spells: Vec<Option<String>>,
        always_cast: Option<Vec<String>>,
    ) -> PyResult<u32> {
        let st = wand_stats(stats)?;
        self.inner
            .give_wand(st, &spells, &always_cast.unwrap_or_default())
            .map_err(game_err)
    }

    fn give_spell(&mut self, key: &str) -> PyResult<()> {
        self.inner.give_spell(key).map_err(game_err)
    }

    /// Give the player a bottle: one `material` with `amount` cells (empty without a material),
    /// or a mixture as `contents`, a list of `{"material", "amount"}`.
    #[pyo3(signature = (material=None, amount=None, contents=None))]
    fn give_bottle(
        &mut self,
        material: Option<&str>,
        amount: Option<u32>,
        contents: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<()> {
        match contents {
            Some(c) => self
                .inner
                .give_mixed_bottle(&contents_arg(c)?)
                .map_err(game_err),
            None => self.inner.give_bottle(material, amount).map_err(game_err),
        }
    }

    /// End the drink, pour or fill in progress now and write its summary events on this frame
    /// (they are otherwise written when the key is next let go).
    fn end_bottle_action(&mut self) {
        self.inner.end_bottle_action();
    }

    /// One wand-editor action: `{"op": "place", "wand": 0, "slot": 1, "from": 0}`,
    /// `{"op": "take", "wand": 0, "slot": 1}` or `{"op": "swap", "wand": 0, "a": 0, "b": 1}`.
    fn edit_wand(&mut self, action: &Bound<'_, PyDict>) -> PyResult<()> {
        let n = |key: &str| -> PyResult<usize> {
            get::<usize>(action, key)?
                .ok_or_else(|| PyValueError::new_err(format!("wand edit needs `{key}`")))
        };
        let op: String =
            get(action, "op")?.ok_or_else(|| PyValueError::new_err("wand edit needs `op`"))?;
        let edit = match op.as_str() {
            "place" => WandEdit::Place {
                wand: n("wand")?,
                slot: n("slot")?,
                from: n("from")?,
            },
            "take" => WandEdit::Take {
                wand: n("wand")?,
                slot: n("slot")?,
            },
            "swap" => WandEdit::Swap {
                wand: n("wand")?,
                a: n("a")?,
                b: n("b")?,
            },
            other => {
                return Err(PyValueError::new_err(format!(
                    "unknown wand edit {other:?}; use place, take or swap"
                )))
            }
        };
        self.inner.edit_wand(edit).map_err(game_err)
    }

    /// An explosion that carves the grid and hurts what it reaches (owner: the world).
    #[pyo3(signature = (x, y, radius, damage=0.0, ray_energy=20000, max_durability=10, fire_percent=5))]
    #[allow(clippy::too_many_arguments)]
    fn blast(
        &mut self,
        x: i32,
        y: i32,
        radius: i64,
        damage: f32,
        ray_energy: i64,
        max_durability: i64,
        fire_percent: i64,
    ) -> PyResult<()> {
        self.inner.blast(BlastSpec {
            x,
            y,
            radius: bounded("radius", radius, u32::MAX)?,
            damage,
            ray_energy: bounded("ray_energy", ray_energy, u32::MAX)?,
            max_durability: bounded("max_durability", max_durability, 255)?,
            fire_percent: bounded("fire_percent", fire_percent, 100)?,
            owner: cogbench_game::entity::Owner::World,
            spare_owner: false,
        });
        Ok(())
    }

    // ----- the pixel world ---------------------------------------------------------------

    fn paint(&mut self, x: i32, y: i32, radius: i32, material_key: &str) -> PyResult<()> {
        self.inner
            .world_mut()
            .paint(x, y, radius, material_key)
            .map_err(to_py_err)
    }

    fn fill_rect(&mut self, x: i32, y: i32, w: i32, h: i32, material_key: &str) -> PyResult<()> {
        self.inner
            .world_mut()
            .fill_rect(x, y, w, h, material_key)
            .map_err(to_py_err)
    }

    fn ignite(&mut self, x: i32, y: i32) -> bool {
        self.inner.world_mut().ignite(x, y)
    }

    /// Carve the grid with a ray explosion without hurting anything; returns cells destroyed.
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
        self.inner.world_mut().explode(spec).map_err(to_py_err)
    }

    fn overlap<'py>(
        &self,
        py: Python<'py>,
        x: i128,
        y: i128,
        w: i128,
        h: i128,
    ) -> PyResult<Bound<'py, PyDict>> {
        queries::overlap(py, self.inner.world(), (x, y, w, h))
    }

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
        queries::raycast(
            py,
            self.inner.world(),
            (x0, y0),
            (x1, y1),
            mask.as_ref(),
            ignore,
        )
    }

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
            self.inner.world(),
            (x, y, w, h),
            (dx, dy),
            mask.as_ref(),
            step_up,
            ignore,
        )
    }

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
        queries::contact_damage(py, self.inner.world(), (x, y, w, h), (min_cells, max_cells))
    }

    fn grid<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        queries::grid(py, self.inner.world())
    }

    fn cell<'py>(&self, py: Python<'py>, x: i32, y: i32) -> PyResult<Bound<'py, PyDict>> {
        queries::cell(py, self.inner.world(), x, y)
    }

    /// Which cells of the rectangle `[x, x+w) x [y, y+h)` are burning: `w * h` bytes, row-major,
    /// 1 for a burning cell, 0 for any other and for cells outside the world. Read-only.
    fn burning_rect<'py>(
        &self,
        py: Python<'py>,
        x: i32,
        y: i32,
        w: i32,
        h: i32,
    ) -> PyResult<Bound<'py, PyBytes>> {
        const MAX_CELLS: i64 = 1 << 22;
        if w < 0 || h < 0 || i64::from(w) * i64::from(h) > MAX_CELLS {
            return Err(PyValueError::new_err(format!(
                "burning_rect: the rectangle must have w, h >= 0 and at most {MAX_CELLS} cells"
            )));
        }
        Ok(PyBytes::new(py, &self.inner.burning_rect(x, y, w, h)))
    }

    fn material_keys(&self) -> Vec<String> {
        queries::material_keys(self.inner.world())
    }

    #[getter]
    fn content_hash(&self) -> u64 {
        self.inner.world().content().hash
    }

    #[getter]
    fn width(&self) -> i32 {
        self.inner.world().width()
    }

    #[getter]
    fn height(&self) -> i32 {
        self.inner.world().height()
    }

    #[getter]
    fn frame(&self) -> u64 {
        self.inner.frame()
    }

    #[getter]
    fn seed(&self) -> u64 {
        self.inner.world().seed()
    }

    #[getter]
    fn rule_seed(&self) -> u64 {
        self.inner.world().rule_seed()
    }
}
