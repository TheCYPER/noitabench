//! Shared helpers for the integration tests.
#![allow(dead_code)]

use cogbench_rules::Rules;
use cogbench_sim::Content;
use std::sync::Arc;

pub const MATERIALS: &str = include_str!("../../../../content/materials.json");
pub const REACTIONS: &str = include_str!("../../../../content/reactions.json");

pub fn rules() -> Rules {
    Rules::new(MATERIALS, REACTIONS).expect("shipped content loads")
}

/// The shipped content with the recipes of `rule_seed` attached.
pub fn content_with_recipes(rules: &Rules, rule_seed: u64) -> Arc<Content> {
    let recipes = rules.recipes(rule_seed).expect("recipes");
    Arc::new(
        rules
            .content()
            .with_recipes(&recipes)
            .expect("valid recipes"),
    )
}
