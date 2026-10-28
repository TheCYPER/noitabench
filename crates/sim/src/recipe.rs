//! Secret recipes: three ingredients that meet turn into a potion.
//!
//! A recipe is *data handed to the simulation*, never part of `reactions.json`: the reaction table
//! is the original one for every rule seed, only the recipes vary (CP2 decision, 2026-10-27).
//! `cogbench-rules` draws them from the rule seed; [`Content::with_recipes`](crate::Content)
//! compiles them into a bitmask per material (`MatRt::ingredient_of`) that the mixing rule of the
//! cell step reads (`rules/recipe_mix.rs`).

use crate::error::{Error, Result};
use crate::material::{Kind, MaterialSet};
use serde::{Deserialize, Serialize};

/// Most recipes a content set can hold: one bit each in `MatRt::ingredient_of`.
pub const MAX_RECIPES: usize = 16;

/// One recipe as data: the key of the potion and the keys of its three distinct ingredients.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct RecipeDef {
    pub potion: String,
    pub inputs: [String; 3],
}

/// A compiled recipe: material indices.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Recipe {
    pub inputs: [u8; 3],
    pub potion: u8,
}

fn mixable(kind: Kind) -> bool {
    matches!(kind, Kind::Liquid | Kind::Powder)
}

/// Resolve and validate `defs` against `mats`. Problems name `file` and the field path.
pub(crate) fn compile(file: &str, mats: &MaterialSet, defs: &[RecipeDef]) -> Result<Vec<Recipe>> {
    if defs.len() > MAX_RECIPES {
        return Err(Error::Content {
            file: file.to_string(),
            field: "recipes".to_string(),
            msg: format!("at most {MAX_RECIPES} recipes, found {}", defs.len()),
        });
    }
    let mut out: Vec<Recipe> = Vec::with_capacity(defs.len());
    for (i, def) in defs.iter().enumerate() {
        let bad = |field: &str, msg: String| Error::Content {
            file: file.to_string(),
            field: format!("recipes[{i}].{field}"),
            msg,
        };
        let find = |field: &str, key: &str| -> Result<u8> {
            let index = mats
                .index_of(key)
                .ok_or_else(|| bad(field, format!("unknown material `{key}`")))?;
            if !mixable(mats.rt(index).kind) {
                return Err(bad(
                    field,
                    format!("`{key}` must be a liquid or a powder to be mixed"),
                ));
            }
            Ok(index)
        };
        let mut inputs = [0u8; 3];
        for (slot, key) in inputs.iter_mut().zip(&def.inputs) {
            *slot = find("inputs", key)?;
        }
        let potion = find("potion", &def.potion)?;
        let mut sorted = inputs;
        sorted.sort_unstable();
        if sorted[0] == sorted[1] || sorted[1] == sorted[2] {
            return Err(bad("inputs", "the three ingredients must differ".into()));
        }
        if inputs.contains(&potion) {
            return Err(bad(
                "potion",
                "the potion cannot be one of its own ingredients".into(),
            ));
        }
        let duplicate = out.iter().any(|r| {
            let mut s = r.inputs;
            s.sort_unstable();
            s == sorted
        });
        if duplicate {
            return Err(bad(
                "inputs",
                "another recipe has the same three ingredients".into(),
            ));
        }
        out.push(Recipe { inputs, potion });
    }
    Ok(out)
}

/// The bit mask of recipes each material is an ingredient of (index = material).
pub(crate) fn masks(recipes: &[Recipe]) -> [u16; 256] {
    let mut masks = [0u16; 256];
    for (bit, r) in recipes.iter().enumerate() {
        for &m in &r.inputs {
            masks[usize::from(m)] |= 1 << bit;
        }
    }
    masks
}
