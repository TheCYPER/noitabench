//! [`Rules`]: the original reaction table with the questions world generation and the
//! encounters ask of it, and the recipe draw.

use crate::error::{Error, Result};
use crate::invariants::{self, InvariantFailure};
use crate::query::{self, Extinguisher, Outcome, Solidifier, Transform};
use crate::recipes;
use cogbench_sim::{Content, RecipeDef, Tuning};
use std::sync::OnceLock;

const MATERIALS_FILE: &str = "materials.json";
const REACTIONS_FILE: &str = "reactions.json";
const EMBEDDED_MATERIALS: &str = include_str!("../../../content/materials.json");
const EMBEDDED_REACTIONS: &str = include_str!("../../../content/reactions.json");

/// Materials the solvability predicates are built around.
const REQUIRED_MATERIALS: [&str; 6] = ["air", "lava", "acid", "rock", "fire", "flammable_gas"];

/// The reaction table every world runs (the original one: no rule seed changes it), compiled
/// together with the materials, plus the recipe draw.
#[derive(Clone, Debug)]
pub struct Rules {
    reactions_json: String,
    content: Content,
}

impl Rules {
    /// Load the given `materials.json` and `reactions.json` texts.
    pub fn new(materials_json: &str, reactions_json: &str) -> Result<Rules> {
        let content = Content::from_texts(
            (MATERIALS_FILE, materials_json),
            (REACTIONS_FILE, reactions_json),
            Tuning::default(),
        )?;
        if let Some(key) = REQUIRED_MATERIALS
            .iter()
            .find(|key| content.mats.index_of(key).is_none())
        {
            return Err(Error::MissingMaterial((*key).to_string()));
        }
        Ok(Rules {
            reactions_json: reactions_json.to_string(),
            content,
        })
    }

    /// The shipped content (`content/materials.json`, `content/reactions.json`).
    pub fn embedded() -> Result<Rules> {
        Rules::new(EMBEDDED_MATERIALS, EMBEDDED_REACTIONS)
    }

    /// The reaction table as `cogbench-reactions/0` text: exactly the file it was loaded from.
    pub fn reactions_json(&self) -> &str {
        &self.reactions_json
    }

    /// The compiled simulation content (materials, table, default tuning; no recipes).
    pub fn content(&self) -> &Content {
        &self.content
    }

    /// The secret recipes of `rule_seed`: one per secret potion, three distinct ingredients
    /// each (see `recipes.rs` for the constraints). Deterministic: the rule seed is the only
    /// input. Hand the result to `Content::with_recipes`; never write it into a reaction table
    /// and never show it to an agent.
    pub fn recipes(&self, rule_seed: u64) -> Result<Vec<RecipeDef>> {
        recipes::generate(&self.content, rule_seed)
    }

    /// What two plain (non-burning) cells of `a` and `b` do when the first-listed reaction fires:
    /// `(what a becomes, what b becomes, chance per examination)`. A material that becomes
    /// itself is unchanged. `None` if they do not react or a key is unknown. Use
    /// [`Rules::reactions_for`] for the whole chain, burning cells and douse outcomes.
    pub fn transforms(&self, a: &str, b: &str) -> Option<(String, String, f64)> {
        let (ia, ib) = (
            self.content.mats.index_of(a)?,
            self.content.mats.index_of(b)?,
        );
        query::reactions_for(&self.content, ia, false, ib, false)
            .into_iter()
            .find_map(|t| match (t.out_a, t.out_b) {
                (Outcome::Becomes(x), Outcome::Becomes(y)) => Some((x, y, t.probability)),
                _ => None,
            })
    }

    /// Every reaction of the pair in file order (the first whose roll succeeds executes), given
    /// which cells burn. Empty for unknown keys.
    pub fn reactions_for(
        &self,
        a: &str,
        a_burning: bool,
        b: &str,
        b_burning: bool,
    ) -> Vec<Transform> {
        match (self.content.mats.index_of(a), self.content.mats.index_of(b)) {
            (Some(ia), Some(ib)) => {
                query::reactions_for(&self.content, ia, a_burning, ib, b_burning)
            }
            _ => Vec::new(),
        }
    }

    /// Liquids that turn lava into a solid (terrain) at least 40% of the time.
    pub fn lava_solidifiers(&self) -> Vec<Solidifier> {
        query::lava_solidifiers(&self.content, invariants::MIN_QUENCH_PROBABILITY)
    }

    /// Materials that put burning cells out at least 30% of the time.
    pub fn extinguishers(&self) -> Vec<Extinguisher> {
        query::extinguishers(&self.content, invariants::MIN_EXTINGUISH_PROBABILITY)
    }

    /// Whether some water-family material puts burning cells out.
    pub fn water_family_extinguishes(&self) -> bool {
        self.extinguishers().iter().any(|e| e.family == "water")
    }

    /// Chance that `acid` makes a plain `target` cell disappear, if it does.
    pub fn acid_dissolves(&self, target: &str) -> Option<f64> {
        query::dissolves(&self.content, "acid", target)
    }

    /// Chance that a plain `source` cell turns a plain `target` cell into fire, if it does.
    pub fn ignites(&self, source: &str, target: &str) -> Option<f64> {
        query::ignites(&self.content, source, target)
    }

    /// The solvability invariants of the table (empty = all hold). A guard for edits of
    /// `reactions.json`: the encounters rely on them.
    pub fn check_invariants(&self) -> Vec<InvariantFailure> {
        invariants::check(&self.content)
    }
}

/// The recipes of `rule_seed` for the shipped content.
pub fn recipes_embedded(rule_seed: u64) -> Result<Vec<RecipeDef>> {
    static RULES: OnceLock<std::result::Result<Rules, String>> = OnceLock::new();
    let rules = RULES
        .get_or_init(|| Rules::embedded().map_err(|e| e.to_string()))
        .as_ref()
        .map_err(|msg| Error::Recipes {
            seed: rule_seed,
            why: msg.clone(),
        })?;
    rules.recipes(rule_seed)
}
