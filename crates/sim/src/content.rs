//! A loaded, validated content set: materials, the reaction table and the tuning knobs.

use crate::consts::{Tuning, MAX_HOP};
use crate::error::{Error, Result};
use crate::material::{Kind, MaterialSet};
use crate::reaction::{parse_reactions_json, ReactionDef, ReactionTable};
use crate::recipe::{self, Recipe, RecipeDef};
use std::path::Path;

const EMBEDDED_MATERIALS: &str = include_str!("../../../content/materials.json");
const EMBEDDED_REACTIONS: &str = include_str!("../../../content/reactions.json");

/// Everything the cell rules read and never mutate during a run.
#[derive(Clone, Debug)]
pub struct Content {
    pub mats: MaterialSet,
    pub table: ReactionTable,
    pub tuning: Tuning,
    /// Index of the material `fire` (bound by name, MAT-R02).
    pub fire: u8,
    /// The secret recipes of this world (empty unless [`Content::with_recipes`] attached some).
    /// They are not reactions: see `recipe.rs` and `rules/recipe_mix.rs`.
    pub recipes: Vec<Recipe>,
    recipe_defs: Vec<RecipeDef>,
    /// The hash before any recipes were attached (recipes extend it, see [`Content::with_recipes`]).
    base_hash: u64,
    /// FNV-1a of the source texts and tuning: snapshots refuse to load into other content.
    pub hash: u64,
}

fn fnv_extend(mut h: u64, bytes: &[u8]) -> u64 {
    for b in bytes {
        h ^= u64::from(*b);
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}

fn tuning_bytes(t: &Tuning) -> Vec<u8> {
    format!("{t:?}").into_bytes()
}

/// The rows of the reaction table compiled into the binary, as data.
pub fn embedded_reaction_defs() -> Result<Vec<ReactionDef>> {
    parse_reactions_json("content/reactions.json", EMBEDDED_REACTIONS)
}

impl Content {
    /// The copy of `content/*.json` compiled into the binary, default tuning.
    pub fn embedded() -> Result<Content> {
        Content::embedded_with(Tuning::default())
    }

    pub fn embedded_with(tuning: Tuning) -> Result<Content> {
        Content::from_texts(
            ("content/materials.json", EMBEDDED_MATERIALS),
            ("content/reactions.json", EMBEDDED_REACTIONS),
            tuning,
        )
    }

    /// Load `materials.json` and `reactions.json` from a directory.
    pub fn from_dir(dir: &Path, tuning: Tuning) -> Result<Content> {
        let read = |name: &str| {
            let path = dir.join(name);
            std::fs::read_to_string(&path)
                .map(|t| (path.display().to_string(), t))
                .map_err(|e| Error::io(format!("reading {}", path.display()), e))
        };
        let (mf, mt) = read("materials.json")?;
        let (rf, rt) = read("reactions.json")?;
        Content::from_texts((&mf, &mt), (&rf, &rt), tuning)
    }

    /// Build from `(file name for messages, text)` pairs.
    pub fn from_texts(
        materials: (&str, &str),
        reactions: (&str, &str),
        tuning: Tuning,
    ) -> Result<Content> {
        let defs = parse_reactions_json(reactions.0, reactions.1)?;
        let mut content = Content::from_defs(materials, &defs, reactions.0, tuning)?;
        let mut h = fnv_extend(0xcbf2_9ce4_8422_2325, materials.1.as_bytes());
        h = fnv_extend(h, reactions.1.as_bytes());
        content.hash = fnv_extend(h, &tuning_bytes(&tuning));
        content.base_hash = content.hash;
        Ok(content)
    }

    /// Build from the materials text and an already parsed reaction list.
    pub fn from_defs(
        materials: (&str, &str),
        defs: &[ReactionDef],
        reactions_name: &str,
        tuning: Tuning,
    ) -> Result<Content> {
        if tuning.liquid_hop == 0 || tuning.liquid_hop > MAX_HOP {
            return Err(Error::arg(format!(
                "tuning.liquid_hop must be 1..={MAX_HOP}, found {}",
                tuning.liquid_hop
            )));
        }
        let mats = MaterialSet::from_json(materials.0, materials.1, &tuning)?;
        let table = ReactionTable::compile(reactions_name, &mats, defs)?;
        Content::assemble(mats, table, tuning, 0, materials.0)
    }

    fn assemble(
        mut mats: MaterialSet,
        table: ReactionTable,
        tuning: Tuning,
        hash: u64,
        file: &str,
    ) -> Result<Content> {
        let fire = mats
            .index_of("fire")
            .filter(|&i| mats.rt(i).kind == Kind::Fire)
            .ok_or_else(|| {
                Error::content(
                    file,
                    "materials",
                    "the engine needs a material `fire` of kind `fire`",
                )
            })?;
        for m in 0..mats.len() as u8 {
            mats.set_reactive(m, table.is_reactive(m));
        }
        Ok(Content {
            mats,
            table,
            tuning,
            fire,
            recipes: Vec::new(),
            recipe_defs: Vec::new(),
            base_hash: hash,
            hash,
        })
    }

    /// Replace the reaction table (tests of other tables: every world runs the original one); the
    /// hash follows the new rows and attached recipes stay.
    pub fn with_table(&self, defs: &[ReactionDef]) -> Result<Content> {
        let table = ReactionTable::compile("(replacement table)", &self.mats, defs)?;
        let hash = fnv_extend(self.base_hash, format!("{defs:?}").as_bytes());
        let swapped = Content::assemble(
            self.mats.clone(),
            table,
            self.tuning,
            hash,
            "(replacement table)",
        )?;
        // The recipes belong to the world, not to the table: they stay attached.
        swapped.with_recipes(&self.recipe_defs)
    }

    /// Attach secret recipes (three ingredients that meet become a potion). Replaces any recipes
    /// already attached; the hash follows the recipes, so snapshots only load into a world with
    /// the same ones.
    pub fn with_recipes(&self, defs: &[RecipeDef]) -> Result<Content> {
        let recipes = recipe::compile("(recipes)", &self.mats, defs)?;
        let masks = recipe::masks(&recipes);
        let mut mats = self.mats.clone();
        for m in 0..=u8::MAX {
            mats.set_ingredient_of(m, masks[usize::from(m)]);
        }
        // Attaching nothing leaves the hash of the recipe-free content untouched.
        let hash = if defs.is_empty() {
            self.base_hash
        } else {
            fnv_extend(self.base_hash, format!("{defs:?}").as_bytes())
        };
        Ok(Content {
            mats,
            table: self.table.clone(),
            tuning: self.tuning,
            fire: self.fire,
            recipes,
            recipe_defs: defs.to_vec(),
            base_hash: self.base_hash,
            hash,
        })
    }

    /// The recipes as they were attached (keys), for tools; never for an agent.
    pub fn recipe_defs(&self) -> &[RecipeDef] {
        &self.recipe_defs
    }
}
