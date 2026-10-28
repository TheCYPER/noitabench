//! Loading a generated world (contract section 4) into a game: the grid, then the player, enemies
//! and items at their markers.

use std::path::Path;
use std::sync::Arc;

use cogbench_sim::reaction::parse_reactions_json;
use cogbench_sim::worldfile::load_world_files;
use cogbench_sim::{embedded_reaction_defs, Content, RecipeDef, World};

use crate::defs::EntityDefs;
use crate::error::Error;
use crate::spell::SpellBook;

use super::{Game, ItemSpec};

/// Options for [`Game::from_world_files`].
#[derive(Clone, Debug, Default)]
pub struct WorldOptions {
    /// Episode seed; defaults to the seed in the world file.
    pub seed: Option<u64>,
    /// Rule seed; defaults to the one in the world file.
    pub rule_seed: Option<u64>,
    /// A reaction table (`cogbench-reactions/0` JSON text) to use instead of the original one.
    /// The table is the same for every rule seed (CP2 decision, 2026-10-27), so there is
    /// nothing to inject: without it, or with text that equals the original table, the world
    /// runs the embedded content and keeps its hash.
    pub reactions_json: Option<String>,
    /// The secret recipes of the world. `None` (the default) draws them from the rule seed
    /// (`cogbench_rules`); `Some(vec![])` makes a world without recipes.
    pub recipes: Option<Vec<RecipeDef>>,
}

/// The item a marker stands for.
fn item_spec(marker: &serde_json::Value, capacity: u32) -> Option<ItemSpec> {
    let key = marker.get("item")?.as_str()?;
    let text = |name: &str| {
        marker
            .get(name)
            .and_then(|v| v.as_str())
            .map(str::to_string)
    };
    Some(match key {
        "potion_heal" | "potion_mana" | "potion_haste" => ItemSpec::Bottle {
            material: Some(key.to_string()),
            amount: Some(capacity),
        },
        "bottle" => ItemSpec::Bottle {
            material: text("contents"),
            amount: Some(capacity),
        },
        "spell" => ItemSpec::Spell { key: text("spell") },
        "wand" => ItemSpec::Wand {
            tier: marker
                .get("tier")
                .and_then(|v| v.as_u64())
                .map_or(1, |t| t.min(u64::from(u32::MAX)) as u32),
        },
        k if k.starts_with("barrel_") => ItemSpec::Barrel {
            kind: k.to_string(),
        },
        _ => return None,
    })
}

fn coord(marker: &serde_json::Value, name: &str) -> Option<i32> {
    marker
        .get(name)?
        .as_i64()
        .and_then(|v| i32::try_from(v).ok())
}

impl Game {
    /// Load `<name>.png` and `<name>.json` of the world generator and place everything the
    /// markers describe. Unknown marker kinds are kept in [`Game::markers`] and otherwise ignored.
    pub fn from_world_files(
        png_path: &Path,
        json_path: &Path,
        options: &WorldOptions,
    ) -> Result<Game, Error> {
        let file = load_world_files(png_path, json_path)?;
        let text = std::fs::read_to_string(json_path).map_err(|source| Error::Io {
            path: json_path.to_path_buf(),
            source,
        })?;
        let json: serde_json::Value = serde_json::from_str(&text)
            .map_err(|e| Error::content(&json_path.display().to_string(), "", e.to_string()))?;
        let mut content = Content::embedded()?;
        if let Some(reactions) = &options.reactions_json {
            let defs = parse_reactions_json("reactions (injected)", reactions)?;
            if defs != embedded_reaction_defs()? {
                content = content.with_table(&defs)?;
            }
        }
        let rule_seed = options.rule_seed.unwrap_or(file.meta.rule_seed);
        let recipes = match &options.recipes {
            Some(recipes) => recipes.clone(),
            None => cogbench_rules::recipes_embedded(rule_seed)?,
        };
        content = content.with_recipes(&recipes)?;
        let seed = options.seed.unwrap_or(file.meta.seed);
        let mut world = World::from_indices(
            file.meta.width,
            file.meta.height,
            seed,
            &file.indices,
            Arc::new(content),
        )?;
        world.set_rule_seed(rule_seed);
        let book = Arc::new(SpellBook::embedded()?);
        let defs = Arc::new(EntityDefs::embedded()?);
        let mut game = Game::with_content(world, book, defs)?;
        let markers = json
            .get("markers")
            .and_then(|m| m.as_array())
            .cloned()
            .unwrap_or_default();
        game.place_markers(&markers)?;
        Ok(game)
    }

    /// Place the spawns of a marker list; keep the other markers.
    pub fn place_markers(&mut self, markers: &[serde_json::Value]) -> Result<(), Error> {
        let capacity = self.defs.items.bottle.capacity;
        for (index, marker) in markers.iter().enumerate() {
            let kind = marker.get("type").and_then(|v| v.as_str()).unwrap_or("");
            let at = (coord(marker, "x"), coord(marker, "y"));
            let (Some(x), Some(y)) = at else {
                self.markers.push(marker.clone());
                continue;
            };
            match kind {
                "spawn_player" => {
                    self.spawn_player(x, y)?;
                }
                "spawn_enemy" => {
                    let enemy = marker.get("enemy").and_then(|v| v.as_str()).unwrap_or("");
                    self.spawn_enemy(enemy, x, y)?;
                }
                "item" => match item_spec(marker, capacity) {
                    Some(spec) => {
                        self.spawn_item_salted(&spec, x, y, index as u64)?;
                    }
                    None => self.markers.push(marker.clone()),
                },
                _ => self.markers.push(marker.clone()),
            }
        }
        Ok(())
    }
}
