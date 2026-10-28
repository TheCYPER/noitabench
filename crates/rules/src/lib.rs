//! `cogbench-rules`: the reaction table every world runs, the questions world generation asks of
//! it, and the secret recipes of a rule seed (design.md section 4, prd.md section 2.6).
//!
//! Since the CP2 decision of 2026-10-27 the reaction table is the original one for every rule
//! seed (water on lava always makes rock, as in Noita). What the rule seed changes are the
//! *recipes*: each of the secret potions is made by mixing three ingredients drawn from the seed.
//!
//! ```
//! # fn main() -> Result<(), cogbench_rules::Error> {
//! let rules = cogbench_rules::Rules::embedded()?;
//! assert!(rules.check_invariants().is_empty());
//! assert!(!rules.lava_solidifiers().is_empty());
//! let recipes = rules.recipes(42)?;
//! assert_eq!(recipes.len(), 8);
//! # Ok(()) }
//! ```
//!
//! * [`Rules`] holds the original table compiled with the materials. Its question API
//!   ([`Rules::transforms`], [`Rules::lava_solidifiers`], [`Rules::extinguishers`], ...) lets
//!   world generation and the encounters check solvability on exactly the table the simulation
//!   runs.
//! * [`Rules::recipes`] draws the recipes of a rule seed (`recipes.rs` lists the constraints).
//!   All randomness is one named SplitMix64 stream of the rule seed (`DET-R04`); there is no
//!   `HashMap` iteration, so the same seed always gives the same recipes.
//!
//! `crates/rules/README.md` explains the recipes and how to look at them.

mod error;
mod invariants;
mod query;
mod recipes;
mod rules;

pub use cogbench_sim::{Recipe, RecipeDef};
pub use error::{Error, Result};
pub use invariants::{
    InvariantFailure, MIN_DISSOLVE_PROBABILITY, MIN_EXTINGUISH_PROBABILITY, MIN_LAVA_SOLIDIFIERS,
    MIN_QUENCH_PROBABILITY, MIN_SPREAD_PROBABILITY,
};
pub use query::{Extinguisher, Outcome, Solidifier, Transform};
pub use recipes::{INGREDIENT_TAG, MAX_USES_PER_INGREDIENT, SECRET_POTION_TAG};
pub use rules::{recipes_embedded, Rules};
