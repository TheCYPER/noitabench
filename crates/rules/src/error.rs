//! Error type of the rules crate.

/// Everything that can go wrong while loading the rules or drawing recipes.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// A content file is malformed, or a recipe set does not load in the simulation.
    #[error(transparent)]
    Sim(#[from] cogbench_sim::Error),
    /// The materials file lacks a material the rules are built around.
    #[error("materials: the rules need a material `{0}`")]
    MissingMaterial(String),
    /// The materials cannot supply the recipes asked for (too few ingredients, too many potions,
    /// or every draw broke a constraint).
    #[error("recipes for rule seed {seed}: {why}")]
    Recipes { seed: u64, why: String },
}

pub type Result<T> = std::result::Result<T, Error>;
