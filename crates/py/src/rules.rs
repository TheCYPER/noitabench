//! `noitabench_core.rules()` and `noitabench_core.recipes()`: the reaction table every world runs
//! (the original one) and the secret recipes of a rule seed (`cogbench-rules`), for world
//! generation, the harness and the tests. (The table perturbation and its `perturb` /
//! `Perturbed` compatibility layer were removed after the CP2 decision of 2026-10-27.)
//!
//! **Recipes and the rule seed must never reach an agent** (contracts sections 10 and 11); use
//! `content_hash` where an observation needs an identity.

use std::sync::{Arc, OnceLock};

use cogbench_rules::{Outcome, RecipeDef, Rules as Inner, Transform};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

fn rules_err(e: cogbench_rules::Error) -> PyErr {
    match e {
        cogbench_rules::Error::Sim(inner) => crate::common::to_py_err(inner),
        other => PyRuntimeError::new_err(other.to_string()),
    }
}

fn seed_arg(rule_seed: i128) -> PyResult<u64> {
    u64::try_from(rule_seed).map_err(|_| {
        PyValueError::new_err(format!("rule_seed must be in [0, 2**64), got {rule_seed}"))
    })
}

/// The shipped rules, built once per process.
fn embedded_rules() -> PyResult<Arc<Inner>> {
    static RULES: OnceLock<Result<Arc<Inner>, String>> = OnceLock::new();
    RULES
        .get_or_init(|| Inner::embedded().map(Arc::new).map_err(|e| e.to_string()))
        .clone()
        .map_err(PyRuntimeError::new_err)
}

fn outcome_text(o: &Outcome) -> String {
    match o {
        Outcome::Becomes(key) => key.clone(),
        Outcome::Extinguished => "@extinguish".to_string(),
    }
}

fn transform_dict<'py>(py: Python<'py>, t: &Transform) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("row", &t.row)?;
    d.set_item("a", &t.a)?;
    d.set_item("b", &t.b)?;
    d.set_item("a_burning", t.a_burning)?;
    d.set_item("b_burning", t.b_burning)?;
    d.set_item("out_a", outcome_text(&t.out_a))?;
    d.set_item("out_b", outcome_text(&t.out_b))?;
    d.set_item("probability", t.probability)?;
    Ok(d)
}

fn dicts<'py, T>(
    py: Python<'py>,
    items: &[T],
    fill: impl Fn(&Bound<'py, PyDict>, &T) -> PyResult<()>,
) -> PyResult<Bound<'py, PyList>> {
    let list = PyList::empty(py);
    for item in items {
        let d = PyDict::new(py);
        fill(&d, item)?;
        list.append(d)?;
    }
    Ok(list)
}

fn recipe_dict<'py>(py: Python<'py>, r: &RecipeDef) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("potion", &r.potion)?;
    d.set_item("inputs", r.inputs.to_vec())?;
    Ok(d)
}

fn recipe_list<'py>(py: Python<'py>, recipes: &[RecipeDef]) -> PyResult<Bound<'py, PyList>> {
    let list = PyList::empty(py);
    for r in recipes {
        list.append(recipe_dict(py, r)?)?;
    }
    Ok(list)
}

// ----- the questions of the table ------------------------------------------------------------

fn lava_solidifiers<'py>(py: Python<'py>, r: &Inner) -> PyResult<Bound<'py, PyList>> {
    dicts(py, &r.lava_solidifiers(), |d, s| {
        d.set_item("liquid", &s.liquid)?;
        d.set_item("product", &s.product)?;
        d.set_item("probability", s.probability)
    })
}

fn extinguishers<'py>(py: Python<'py>, r: &Inner) -> PyResult<Bound<'py, PyList>> {
    dicts(py, &r.extinguishers(), |d, e| {
        d.set_item("material", &e.material)?;
        d.set_item("family", &e.family)?;
        d.set_item("probability", e.probability)?;
        d.set_item("targets", e.targets.clone())
    })
}

fn reactions_for<'py>(
    py: Python<'py>,
    r: &Inner,
    (a, b): (&str, &str),
    (a_burning, b_burning): (bool, bool),
) -> PyResult<Bound<'py, PyList>> {
    let list = PyList::empty(py);
    for t in r.reactions_for(a, a_burning, b, b_burning) {
        list.append(transform_dict(py, &t)?)?;
    }
    Ok(list)
}

fn invariants<'py>(py: Python<'py>, r: &Inner) -> PyResult<Bound<'py, PyList>> {
    dicts(py, &r.check_invariants(), |d, f| {
        d.set_item("name", f.name)?;
        d.set_item("detail", &f.detail)
    })
}

/// The reaction table every world runs, and the questions world generation and the encounters
/// ask of it. The table is the original one whatever the rule seed.
#[pyclass(module = "noitabench_core", name = "Rules", frozen)]
pub(crate) struct Rules {
    inner: Arc<Inner>,
}

#[pymethods]
impl Rules {
    #[new]
    fn new() -> PyResult<Rules> {
        Ok(Rules {
            inner: embedded_rules()?,
        })
    }

    /// Hash of the materials, reactions and tuning of the original table (no recipes).
    #[getter]
    fn content_hash(&self) -> u64 {
        self.inner.content().hash
    }

    /// The table as `cogbench-reactions/0` text: exactly `content/reactions.json`.
    #[getter]
    fn reactions_json(&self) -> String {
        self.inner.reactions_json().to_string()
    }

    /// The secret recipes of `rule_seed`: `[{"potion": key, "inputs": [a, b, c]}]`, one per
    /// secret potion, three distinct ingredients each.
    fn recipes<'py>(&self, py: Python<'py>, rule_seed: i128) -> PyResult<Bound<'py, PyList>> {
        let recipes = self
            .inner
            .recipes(seed_arg(rule_seed)?)
            .map_err(rules_err)?;
        recipe_list(py, &recipes)
    }

    /// Liquids that turn lava into rock or ground at 40 % or more: `[{liquid, product,
    /// probability}]`.
    fn lava_solidifiers<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        lava_solidifiers(py, &self.inner)
    }

    /// Materials that put burning cells out at 30 % or more: `[{material, family, probability,
    /// targets}]`.
    fn extinguishers<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        extinguishers(py, &self.inner)
    }

    /// Whether some water-family material puts burning cells out.
    fn water_family_extinguishes(&self) -> bool {
        self.inner.water_family_extinguishes()
    }

    /// What two plain cells of `a` and `b` do when their first listed reaction fires:
    /// `(what a becomes, what b becomes, chance per examination)`, or `None`.
    fn transforms(&self, a: &str, b: &str) -> Option<(String, String, f64)> {
        self.inner.transforms(a, b)
    }

    /// Every reaction of the pair in file order, given which of the cells burn: `[{row, a, b,
    /// a_burning, b_burning, out_a, out_b, probability}]` (`out_*` is `"@extinguish"` when the
    /// cell only stops burning).
    #[pyo3(signature = (a, b, a_burning=false, b_burning=false))]
    fn reactions_for<'py>(
        &self,
        py: Python<'py>,
        a: &str,
        b: &str,
        a_burning: bool,
        b_burning: bool,
    ) -> PyResult<Bound<'py, PyList>> {
        reactions_for(py, &self.inner, (a, b), (a_burning, b_burning))
    }

    /// Chance that acid next to a plain `target` cell makes it vanish, or `None`.
    fn acid_dissolves(&self, target: &str) -> Option<f64> {
        self.inner.acid_dissolves(target)
    }

    /// Chance that a plain `source` cell turns a plain `target` cell into fire, or `None`.
    fn ignites(&self, source: &str, target: &str) -> Option<f64> {
        self.inner.ignites(source, target)
    }

    /// The violated solvability invariants of the table (empty unless `reactions.json` was
    /// edited into something the encounters cannot use).
    fn check_invariants<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        invariants(py, &self.inner)
    }
}

/// The recipes of `rule_seed`: `[{"potion": key, "inputs": [a, b, c]}]` (see `Rules.recipes`).
#[pyfunction]
pub(crate) fn recipes<'py>(py: Python<'py>, rule_seed: i128) -> PyResult<Bound<'py, PyList>> {
    let recipes = embedded_rules()?
        .recipes(seed_arg(rule_seed)?)
        .map_err(rules_err)?;
    recipe_list(py, &recipes)
}

/// The shipped rules (`Rules`); the compiled table behind it is shared between calls.
#[pyfunction]
pub(crate) fn rules() -> PyResult<Rules> {
    Rules::new()
}
