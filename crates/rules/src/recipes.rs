//! The secret recipes of a rule seed.
//!
//! Every material tagged `secret_potion` (the potions that exist only as the product of a mix)
//! gets one recipe: three distinct materials tagged `ingredient`. The recipes of a seed satisfy:
//!
//! * each recipe has three different ingredients, and no two recipes have the same three;
//! * no two ingredients of one recipe react with each other in the reaction table when two
//!   plain cells touch (oil floating on water stays oil on water), so a recipe is never also a
//!   table reaction;
//! * no ingredient is in more than [`MAX_USES_PER_INGREDIENT`] recipes, so the recipes spread
//!   over the pool instead of piling onto a few materials.
//!
//! The draw is a pure function of `(materials, reaction table, rule seed)`: one SplitMix64
//! stream `rules/recipes` (`DET-R04`), no `HashMap` iteration. The recipes are handed to the
//! simulation (`Content::with_recipes`); they are never rows of `reactions.json`.

use crate::error::{Error, Result};
use crate::query::reactions_for;
use cogbench_sim::rng::Stream;
use cogbench_sim::{Content, RecipeDef, MAX_RECIPES};

/// Tag of the materials recipes are drawn from.
pub const INGREDIENT_TAG: &str = "ingredient";
/// Tag of the potions that have a recipe.
pub const SECRET_POTION_TAG: &str = "secret_potion";
/// Most recipes one ingredient may appear in.
pub const MAX_USES_PER_INGREDIENT: usize = 3;
/// Name of the random stream (the rule seed is the only input).
pub const STREAM: &str = "rules/recipes";
/// How many times the draw starts over when a shuffle cannot be completed under the usage cap.
const MAX_ATTEMPTS: u32 = 64;

fn fail(seed: u64, why: impl Into<String>) -> Error {
    Error::Recipes {
        seed,
        why: why.into(),
    }
}

/// All triples `a < b < c` of the pool in which no pair reacts when two plain cells touch.
fn quiet_triples(content: &Content, pool: &[u8]) -> Vec<[u8; 3]> {
    let quiet = |a: u8, b: u8| reactions_for(content, a, false, b, false).is_empty();
    let mut out = Vec::new();
    for (i, &a) in pool.iter().enumerate() {
        for (j, &b) in pool.iter().enumerate().skip(i + 1) {
            if !quiet(a, b) {
                continue;
            }
            for &c in pool.iter().skip(j + 1) {
                if quiet(a, c) && quiet(b, c) {
                    out.push([a, b, c]);
                }
            }
        }
    }
    out
}

/// Draw the recipes of `rule_seed`: one per secret potion, in the potions' index order.
pub(crate) fn generate(content: &Content, rule_seed: u64) -> Result<Vec<RecipeDef>> {
    let mats = &content.mats;
    let pool: Vec<u8> = mats.with_tag(INGREDIENT_TAG).unwrap_or(&[]).to_vec();
    let potions: Vec<u8> = mats.with_tag(SECRET_POTION_TAG).unwrap_or(&[]).to_vec();
    if potions.is_empty() {
        return Err(Error::MissingMaterial(format!("tag {SECRET_POTION_TAG}")));
    }
    if pool.len() < 3 {
        return Err(Error::MissingMaterial(format!(
            "three with tag {INGREDIENT_TAG}"
        )));
    }
    if potions.len() > MAX_RECIPES {
        return Err(fail(
            rule_seed,
            format!(
                "{} potions, the simulation holds {MAX_RECIPES}",
                potions.len()
            ),
        ));
    }
    if 3 * potions.len() > MAX_USES_PER_INGREDIENT * pool.len() {
        return Err(fail(
            rule_seed,
            format!(
                "{} potions need {} ingredient slots, {} ingredients offer {}",
                potions.len(),
                3 * potions.len(),
                pool.len(),
                MAX_USES_PER_INGREDIENT * pool.len()
            ),
        ));
    }
    let mut triples = quiet_triples(content, &pool);
    if triples.len() < potions.len() {
        return Err(fail(
            rule_seed,
            format!("only {} quiet triples of ingredients", triples.len()),
        ));
    }
    let mut stream = Stream::new(rule_seed, STREAM);
    for _ in 0..MAX_ATTEMPTS {
        for k in (1..triples.len()).rev() {
            triples.swap(k, stream.below(k as u32 + 1) as usize);
        }
        let mut uses = [0usize; 256];
        let mut chosen: Vec<[u8; 3]> = Vec::with_capacity(potions.len());
        for t in &triples {
            if chosen.len() == potions.len() {
                break;
            }
            if t.iter()
                .all(|&m| uses[usize::from(m)] < MAX_USES_PER_INGREDIENT)
            {
                t.iter().for_each(|&m| uses[usize::from(m)] += 1);
                chosen.push(*t);
            }
        }
        if chosen.len() == potions.len() {
            return Ok(potions
                .iter()
                .zip(chosen)
                .map(|(&potion, inputs)| RecipeDef {
                    potion: mats.key_of(potion).to_string(),
                    inputs: inputs.map(|m| mats.key_of(m).to_string()),
                })
                .collect());
        }
    }
    Err(fail(
        rule_seed,
        format!("no draw of {} recipes fits the usage cap", potions.len()),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Rules;

    #[test]
    fn only_water_and_toxic_sludge_cannot_share_a_recipe() {
        let rules = Rules::embedded().expect("shipped content");
        let content = rules.content();
        let pool = content.mats.with_tag(INGREDIENT_TAG).expect("pool");
        assert_eq!(pool.len(), 12);
        // C(12, 3) = 220 triples, 10 of which hold both water and toxic sludge
        assert_eq!(quiet_triples(content, pool).len(), 210);
    }
}
