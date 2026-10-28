//! `noitabench_core.wand_trial(...)`: the wand practice range (`cogbench_game::trial`).
//!
//! A read-only function: it takes a wand's stats and its slots as plain Python values, holds the
//! fire key down for a while outside any world, and returns what each click played, what it cost
//! and what it would do to a dummy that every shot hits. Damage is returned in *displayed*
//! units (internal x 25), like everything an agent reads. Nothing here touches a `Game`.

use std::sync::OnceLock;

use cogbench_game::trial::{
    run_trial, SkipTally, TrialCast, TrialReport, TrialSlot, TrialSpec, MAX_TRIAL_FRAMES,
};
use cogbench_game::wand::{SkipReason, Skipped};
use cogbench_game::{EntityDefs, SpellBook};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::common::{bounded, embedded_content, game_err};
use crate::convert::{get, wand_stats};

/// Displayed damage is internal damage times this (`GUI_HP_MULTIPLIER`).
const DISPLAY: f32 = 25.0;
/// Most clicks a report keeps in its list; the totals count all of them.
const MAX_KEPT_CASTS: i64 = 2_000;

struct Tables {
    book: SpellBook,
    defs: EntityDefs,
}

/// The spell catalogue and entity numbers compiled into the module, parsed once per process.
fn tables() -> PyResult<&'static Tables> {
    static TABLES: OnceLock<Result<Tables, String>> = OnceLock::new();
    TABLES
        .get_or_init(|| {
            let book = SpellBook::embedded().map_err(|e| e.to_string())?;
            let defs = EntityDefs::embedded().map_err(|e| e.to_string())?;
            Ok(Tables { book, defs })
        })
        .as_ref()
        .map_err(|m| PyRuntimeError::new_err(m.clone()))
}

fn spell_id(book: &SpellBook, key: &str) -> PyResult<cogbench_game::SpellId> {
    book.id(key)
        .ok_or_else(|| PyValueError::new_err(format!("unknown spell {key:?}")))
}

/// One slot: `None` (empty), a spell key, or `{"spell": key, "uses": n}`.
fn slot_from(book: &SpellBook, item: &Bound<'_, PyAny>) -> PyResult<Option<TrialSlot>> {
    if item.is_none() {
        return Ok(None);
    }
    if let Ok(key) = item.extract::<String>() {
        return Ok(Some(TrialSlot {
            spell: spell_id(book, &key)?,
            uses: None,
        }));
    }
    let bad =
        || PyValueError::new_err("a slot is None, a spell key or {\"spell\": key, \"uses\": n}");
    let d = item.cast::<PyDict>().map_err(|_| bad())?;
    let key: String = get(d, "spell").map_err(|_| bad())?.ok_or_else(bad)?;
    let uses: Option<u32> = get(d, "uses").map_err(|_| bad())?;
    Ok(Some(TrialSlot {
        spell: spell_id(book, &key)?,
        uses,
    }))
}

fn reason_text(r: SkipReason) -> &'static str {
    match r {
        SkipReason::NotEnoughMana => "not_enough_mana",
        SkipReason::NoUsesLeft => "no_uses_left",
    }
}

fn skipped_list<'py>(
    py: Python<'py>,
    book: &SpellBook,
    skipped: &[Skipped],
) -> PyResult<Bound<'py, PyList>> {
    let list = PyList::empty(py);
    for s in skipped {
        let d = PyDict::new(py);
        d.set_item("spell", book.key(s.spell))?;
        d.set_item("reason", reason_text(s.reason))?;
        list.append(d)?;
    }
    Ok(list)
}

fn cast_dict<'py>(
    py: Python<'py>,
    book: &SpellBook,
    c: &TrialCast,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("frame", c.frame)?;
    let played: Vec<&str> = c.played.iter().map(|s| book.key(*s)).collect();
    d.set_item("spells", played)?;
    d.set_item("skipped", skipped_list(py, book, &c.skipped)?)?;
    d.set_item("projectiles", c.projectiles)?;
    d.set_item("payload_projectiles", c.payload_projectiles)?;
    d.set_item("mana_before", c.mana_before)?;
    d.set_item("mana_after", c.mana_after)?;
    d.set_item("cast_delay", c.cast_delay)?;
    d.set_item("recharge", c.recharge)?;
    d.set_item("ready_in", c.ready_in)?;
    d.set_item("wrapped", c.wrapped)?;
    d.set_item("damage", c.damage * DISPLAY)?;
    Ok(d)
}

fn skip_tally_dict<'py>(
    py: Python<'py>,
    book: &SpellBook,
    t: &SkipTally,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("spell", book.key(t.spell))?;
    d.set_item("reason", reason_text(t.reason))?;
    d.set_item("times", t.times)?;
    Ok(d)
}

fn report_dict<'py>(
    py: Python<'py>,
    book: &SpellBook,
    r: &TrialReport,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("frames", r.frames)?;
    d.set_item("total_casts", r.total_casts)?;
    d.set_item("shooting_casts", r.shooting_casts)?;
    d.set_item("projectiles", r.projectiles)?;
    d.set_item("payload_projectiles", r.payload_projectiles)?;
    d.set_item("damage", r.damage * DISPLAY)?;
    d.set_item("recharges", r.recharges)?;
    d.set_item("mana_start", r.mana_start)?;
    d.set_item("mana_end", r.mana_end)?;
    d.set_item("mana_min", r.mana_min)?;
    d.set_item("mana_spent", r.mana_spent)?;
    d.set_item("used_up", &r.used_up)?;
    let skips = PyList::empty(py);
    for t in &r.skips {
        skips.append(skip_tally_dict(py, book, t)?)?;
    }
    d.set_item("skips", skips)?;
    let casts = PyList::empty(py);
    for c in &r.casts {
        casts.append(cast_dict(py, book, c)?)?;
    }
    d.set_item("casts", casts)?;
    Ok(d)
}

/// Hold the fire key on a wand outside the world for `frames` frames (at most 7,200).
///
/// `stats` is a wand-stats dict (as in `Game.give_wand`), `slots` a list with one entry per
/// slot: `None`, a spell key, or `{"spell": key, "uses": n}` (uses left; the spell's own limit
/// when left out). `seed` only matters for a shuffle wand. The first `keep_casts` clicks are
/// listed in `casts`; the totals count all of them. Damage is displayed HP against a dummy that
/// every projectile hits and every blast reaches.
#[pyfunction]
#[pyo3(signature = (stats, slots, *, frames=600, seed=0, always_cast=None, keep_casts=64))]
pub(crate) fn wand_trial<'py>(
    py: Python<'py>,
    stats: &Bound<'py, PyDict>,
    slots: &Bound<'py, PyAny>,
    frames: i64,
    seed: i128,
    always_cast: Option<Vec<String>>,
    keep_casts: i64,
) -> PyResult<Bound<'py, PyDict>> {
    let t = tables()?;
    let list = slots
        .cast::<PyList>()
        .map_err(|_| PyValueError::new_err("`slots` must be a list"))?;
    let slots = list
        .iter()
        .map(|item| slot_from(&t.book, &item))
        .collect::<PyResult<Vec<_>>>()?;
    let always_cast = always_cast
        .unwrap_or_default()
        .iter()
        .map(|key| spell_id(&t.book, key))
        .collect::<PyResult<Vec<_>>>()?;
    let seed = u64::try_from(seed)
        .map_err(|_| PyValueError::new_err(format!("seed must be in [0, 2**64), got {seed}")))?;
    let spec = TrialSpec {
        stats: wand_stats(stats)?,
        slots,
        always_cast,
        frames: bounded("frames", frames, MAX_TRIAL_FRAMES)?,
        seed,
        keep_casts: bounded("keep_casts", keep_casts, MAX_KEPT_CASTS)?,
    };
    let content = embedded_content()?;
    let report = run_trial(&t.book, &content.mats, &t.defs, &spec).map_err(game_err)?;
    report_dict(py, &t.book, &report)
}
