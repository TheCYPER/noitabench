//! Questions about an expanded reaction table: "what happens when these two materials touch",
//! and the named predicates world generation and the encounters use to stay solvable.
//!
//! All questions are answered on the table the simulation actually runs (the compiled
//! [`cogbench_sim::ReactionTable`]), so tags, positional outputs and file order are exactly the
//! engine's.

use cogbench_sim::reaction::Out;
use cogbench_sim::{Content, Kind};
use serde::Serialize;

/// What happens to one of the two cells.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub enum Outcome {
    /// The cell becomes this material (its own material means: unchanged).
    Becomes(String),
    /// The cell keeps its material and stops burning.
    Extinguished,
}

impl Outcome {
    fn text(&self) -> &str {
        match self {
            Outcome::Becomes(key) => key,
            Outcome::Extinguished => "(doused)",
        }
    }
}

/// One way two cells can react.
#[derive(Clone, Debug, Serialize)]
pub struct Transform {
    /// Id of the reaction row.
    pub row: String,
    pub a: String,
    pub b: String,
    /// The reaction needs `a` / `b` to be in the burning state.
    pub a_burning: bool,
    pub b_burning: bool,
    pub out_a: Outcome,
    pub out_b: Outcome,
    /// Chance per examination, 0..=1 (a multiple of 0.0001).
    pub probability: f64,
}

impl Transform {
    /// `a + b -> out_a + out_b (p%)`; `*` marks a burning cell, `(doused)` an extinguished one.
    pub fn text(&self) -> String {
        let mark = |key: &str, burning: bool| format!("{key}{}", if burning { "*" } else { "" });
        format!(
            "{} + {} -> {} + {} ({}%)",
            mark(&self.a, self.a_burning),
            mark(&self.b, self.b_burning),
            self.out_a.text(),
            self.out_b.text(),
            percent(self.probability)
        )
    }
}

/// A probability as a percentage without trailing noise: `0.8` -> `80`, `0.003` -> `0.3`.
fn percent(p: f64) -> String {
    format!("{}", (p * 10_000.0).round() / 100.0)
}

fn outcome(content: &Content, out: Out) -> Outcome {
    match out {
        Out::Set(m) => Outcome::Becomes(content.mats.key_of(m).to_string()),
        Out::Extinguish => Outcome::Extinguished,
    }
}

/// Every reaction two cells of materials `a` and `b` can have, in file order, given which of them
/// are burning. Outcomes are positional: `out_a` is what `a` becomes.
pub(crate) fn reactions_for(
    content: &Content,
    a: u8,
    a_burning: bool,
    b: u8,
    b_burning: bool,
) -> Vec<Transform> {
    content
        .table
        .candidates(a, b)
        .iter()
        .filter(|c| c.threshold > 0)
        .filter(|c| (!c.visited_must_burn || a_burning) && (!c.other_must_burn || b_burning))
        .map(|c| Transform {
            row: content.table.ids()[usize::from(c.row)].clone(),
            a: content.mats.key_of(a).to_string(),
            b: content.mats.key_of(b).to_string(),
            a_burning: c.visited_must_burn,
            b_burning: c.other_must_burn,
            out_a: outcome(content, c.out_visited),
            out_b: outcome(content, c.out_other),
            probability: f64::from(c.threshold) / 10_000.0,
        })
        .collect()
}

/// A liquid that turns lava into a solid, and what it turns it into.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Solidifier {
    pub liquid: String,
    pub product: String,
    pub probability: f64,
}

/// A material that puts burning cells out.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Extinguisher {
    pub material: String,
    /// `family` of the material in `materials.json`.
    pub family: String,
    /// Best chance over the burnable materials it can douse.
    pub probability: f64,
    pub targets: Vec<String>,
}

fn is_potion(content: &Content, m: u8) -> bool {
    content.mats.get(m).is_some_and(|x| x.family == "potion")
}

pub(crate) fn lava_solidifiers(content: &Content, min_probability: f64) -> Vec<Solidifier> {
    let Some(lava) = content.mats.index_of("lava") else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for m in content.mats.iter() {
        if m.kind != Kind::Liquid || m.index == lava || is_potion(content, m.index) {
            continue;
        }
        let hit = reactions_for(content, lava, false, m.index, false)
            .into_iter()
            .filter(|t| t.probability >= min_probability)
            .find_map(|t| match &t.out_a {
                Outcome::Becomes(p) if is_solid(content, p) => Some((p.clone(), t.probability)),
                _ => None,
            });
        if let Some((product, probability)) = hit {
            out.push(Solidifier {
                liquid: m.key.clone(),
                product,
                probability,
            });
        }
    }
    out
}

/// Products that count as "lava turned solid" (contract §10: rock or ground).
const SOLID_PRODUCTS: [&str; 2] = ["rock", "ground"];

fn is_solid(content: &Content, key: &str) -> bool {
    SOLID_PRODUCTS.contains(&key)
        && content
            .mats
            .index_of(key)
            .is_some_and(|i| content.mats.rt(i).kind == Kind::Static)
}

pub(crate) fn extinguishers(content: &Content, min_probability: f64) -> Vec<Extinguisher> {
    let burnable: Vec<u8> = content
        .mats
        .iter()
        .filter(|m| m.burnable)
        .map(|m| m.index)
        .collect();
    let mut out = Vec::new();
    for x in content.mats.iter().skip(1) {
        let mut best = 0.0f64;
        let mut targets = Vec::new();
        for &y in &burnable {
            let douses = reactions_for(content, x.index, false, y, true)
                .into_iter()
                .filter(|t| t.out_b == Outcome::Extinguished)
                .map(|t| t.probability)
                .fold(0.0, f64::max);
            if douses >= min_probability {
                best = best.max(douses);
                targets.push(content.mats.key_of(y).to_string());
            }
        }
        if !targets.is_empty() {
            out.push(Extinguisher {
                material: x.key.clone(),
                family: x.family.clone(),
                probability: best,
                targets,
            });
        }
    }
    out
}

/// Chance that `agent` next to `target` makes `target` vanish (it becomes air), if it can.
pub(crate) fn dissolves(content: &Content, agent: &str, target: &str) -> Option<f64> {
    let (a, b) = (
        content.mats.index_of(agent)?,
        content.mats.index_of(target)?,
    );
    reactions_for(content, a, false, b, false)
        .into_iter()
        .find(|t| t.out_b == Outcome::Becomes("air".to_string()))
        .map(|t| t.probability)
}

/// Chance that a plain `source` cell next to a plain `target` cell turns the target into a
/// fire-kind material, if it can.
pub(crate) fn ignites(content: &Content, source: &str, target: &str) -> Option<f64> {
    let (a, b) = (
        content.mats.index_of(source)?,
        content.mats.index_of(target)?,
    );
    reactions_for(content, a, false, b, false)
        .into_iter()
        .find(|t| match &t.out_b {
            Outcome::Becomes(k) => content
                .mats
                .index_of(k)
                .is_some_and(|i| content.mats.rt(i).kind == Kind::Fire),
            Outcome::Extinguished => false,
        })
        .map(|t| t.probability)
}
