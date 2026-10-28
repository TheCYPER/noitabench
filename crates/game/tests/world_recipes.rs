//! A world loaded from a file gets the secret recipes of its rule seed, and runs the original
//! reaction table whatever is injected.

use std::path::{Path, PathBuf};

use cogbench_game::{Controls, Game, WorldOptions};
use cogbench_sim::{Content, RecipeDef};

const W: u32 = 160;
const H: u32 = 80;

fn write_world(dir: &Path, rule_seed: u64) -> (PathBuf, PathBuf) {
    let png_path = dir.join("w.png");
    let json_path = dir.join("w.json");
    let content = Content::embedded().unwrap();
    let rock = content.mats.index_of("rock").unwrap();
    let mut pixels = vec![0u8; (W * H) as usize];
    for y in 60..H {
        for x in 0..W {
            pixels[(y * W + x) as usize] = rock;
        }
    }
    let file = std::fs::File::create(&png_path).unwrap();
    let mut enc = png::Encoder::new(std::io::BufWriter::new(file), W, H);
    enc.set_color(png::ColorType::Indexed);
    enc.set_depth(png::BitDepth::Eight);
    enc.set_palette(
        (0..256u32)
            .flat_map(|i| [i as u8, i as u8, i as u8])
            .collect::<Vec<u8>>(),
    );
    enc.write_header()
        .unwrap()
        .write_image_data(&pixels)
        .unwrap();
    let json = format!(
        r#"{{"format":"cogbench-world/0","seed":9,"rule_seed":{rule_seed},"width":{W},"height":{H},
        "biome_cell_size":128,"biome_map":[["start"]],
        "markers":[{{"type":"spawn_player","x":20,"y":59}}]}}"#
    );
    std::fs::write(&json_path, json).unwrap();
    (png_path, json_path)
}

fn load(rule_seed: u64, options: &WorldOptions) -> Game {
    let dir = tempfile::tempdir().unwrap();
    let (png, json) = write_world(dir.path(), rule_seed);
    Game::from_world_files(&png, &json, options).unwrap()
}

fn recipes_of(g: &Game) -> Vec<RecipeDef> {
    g.world().content().recipe_defs().to_vec()
}

#[test]
fn the_recipes_come_from_the_rule_seed_of_the_file() {
    let g = load(4, &WorldOptions::default());
    assert_eq!(recipes_of(&g), cogbench_rules::recipes_embedded(4).unwrap());
    assert_eq!(recipes_of(&g).len(), 8);
    let other = load(5, &WorldOptions::default());
    assert_ne!(recipes_of(&g), recipes_of(&other));
    assert_ne!(g.world().content().hash, other.world().content().hash);
    // the world file's seed is the default; the option overrides it
    let over = load(
        4,
        &WorldOptions {
            rule_seed: Some(5),
            ..WorldOptions::default()
        },
    );
    assert_eq!(recipes_of(&over), recipes_of(&other));
    assert_eq!(over.world().rule_seed(), 5);
}

#[test]
fn explicit_recipes_replace_the_drawn_ones_and_an_empty_list_means_none() {
    let none = load(
        4,
        &WorldOptions {
            recipes: Some(Vec::new()),
            ..WorldOptions::default()
        },
    );
    assert!(none.world().content().recipes.is_empty());
    // without recipes the content is exactly the embedded content, hash included
    assert_eq!(
        none.world().content().hash,
        Content::embedded().unwrap().hash
    );
    let own = vec![RecipeDef {
        potion: "potion_crit".into(),
        inputs: ["water", "sand", "coal"].map(String::from),
    }];
    let g = load(
        4,
        &WorldOptions {
            recipes: Some(own.clone()),
            ..WorldOptions::default()
        },
    );
    assert_eq!(recipes_of(&g), own);
}

#[test]
fn a_bad_recipe_is_refused_with_the_field() {
    let dir = tempfile::tempdir().unwrap();
    let (png, json) = write_world(dir.path(), 4);
    let bad = vec![RecipeDef {
        potion: "potion_crit".into(),
        inputs: ["water", "sand", "mercury"].map(String::from),
    }];
    let err = Game::from_world_files(
        &png,
        &json,
        &WorldOptions {
            recipes: Some(bad),
            ..WorldOptions::default()
        },
    )
    .map(|_| ())
    .unwrap_err();
    assert!(err.to_string().contains("recipes[0].inputs"), "{err}");
}

#[test]
fn injecting_the_original_table_changes_nothing_but_another_table_does() {
    let original = include_str!("../../../content/reactions.json");
    let plain = load(4, &WorldOptions::default());
    let injected = load(
        4,
        &WorldOptions {
            reactions_json: Some(original.to_string()),
            ..WorldOptions::default()
        },
    );
    assert_eq!(
        plain.world().content().hash,
        injected.world().content().hash
    );
    // a table without the lava rows is a different table
    let mut value: serde_json::Value = serde_json::from_str(original).unwrap();
    value["reactions"].as_array_mut().unwrap().remove(0);
    let other = load(
        4,
        &WorldOptions {
            reactions_json: Some(value.to_string()),
            ..WorldOptions::default()
        },
    );
    assert_ne!(plain.world().content().hash, other.world().content().hash);
    // and the recipes survive the swap
    assert_eq!(recipes_of(&other), recipes_of(&plain));
}

#[test]
fn a_loaded_world_mixes_its_own_recipes_and_only_those() {
    let book = cogbench_rules::recipes_embedded(4).unwrap();
    let lively = &book[0];
    let other_book = cogbench_rules::recipes_embedded(5).unwrap();
    let foreign = other_book
        .iter()
        .find(|r| !book.iter().any(|b| b.inputs == r.inputs))
        .expect("the books differ");
    let pour = |g: &mut Game, recipe: &RecipeDef| {
        // a shaft on the floor with the three ingredients stacked in it
        let w = g.world_mut();
        w.fill_rect(100, 40, 3, 20, "rock").unwrap();
        w.fill_rect(104, 40, 3, 20, "rock").unwrap();
        w.fill_rect(103, 40, 1, 20, "air").unwrap();
        for (i, key) in recipe.inputs.iter().enumerate() {
            w.fill_rect(103, 50 + i as i32, 1, 1, key).unwrap();
        }
    };
    let mut g = load(4, &WorldOptions::default());
    pour(&mut g, lively);
    g.step_frames(240, &Controls::default()).unwrap();
    let made = (0..H as i32)
        .filter(|&y| g.world().cell_info(103, y).unwrap().key == lively.potion)
        .count();
    assert_eq!(made, 3, "the lively concoction of this seed");
    let mut g = load(4, &WorldOptions::default());
    pour(&mut g, foreign);
    g.step_frames(240, &Controls::default()).unwrap();
    let potions = (0..H as i32)
        .filter(|&y| {
            g.world()
                .cell_info(103, y)
                .unwrap()
                .key
                .starts_with("potion_")
        })
        .count();
    assert_eq!(potions, 0, "a triple of another seed's book does nothing");
}

#[test]
fn snapshots_keep_the_recipes_apart() {
    let mut a = load(4, &WorldOptions::default());
    a.step_frames(5, &Controls::default()).unwrap();
    let blob = a.snapshot().unwrap();
    let mut same = load(4, &WorldOptions::default());
    same.restore(&blob).unwrap();
    assert_eq!(same.state_hash(), a.state_hash());
    let mut other = load(5, &WorldOptions::default());
    assert!(other.restore(&blob).is_err(), "another recipe book");
}
