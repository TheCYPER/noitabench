//! Loading a generated world (contract section 4): the grid and the markers become a game.

use std::path::Path;

use cogbench_game::{Controls, Game, WorldOptions};
use cogbench_sim::Content;

const W: u32 = 160;
const H: u32 = 80;

fn index_of(key: &str) -> u8 {
    Content::embedded().unwrap().mats.index_of(key).unwrap()
}

/// A flat world: ground from row 60 down, plus a wall of rock. Returns (png, json) paths.
fn write_world(dir: &Path, markers: &str) -> (std::path::PathBuf, std::path::PathBuf) {
    let png_path = dir.join("w.png");
    let json_path = dir.join("w.json");
    let mut pixels = vec![0u8; (W * H) as usize];
    let ground = index_of("ground");
    for y in 60..H {
        for x in 0..W {
            pixels[(y * W + x) as usize] = ground;
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
        r#"{{"format":"cogbench-world/0","seed":9,"rule_seed":4,"width":{W},"height":{H},
        "biome_cell_size":128,"biome_map":[["start"]],"markers":[{markers}]}}"#
    );
    std::fs::write(&json_path, json).unwrap();
    (png_path, json_path)
}

const MARKERS: &str = r#"
 {"type":"spawn_player","x":20,"y":59},
 {"type":"spawn_enemy","x":80,"y":59,"enemy":"longleg"},
 {"type":"spawn_enemy","x":100,"y":59,"enemy":"shotgunner"},
 {"type":"item","x":30,"y":59,"item":"potion_heal"},
 {"type":"item","x":34,"y":59,"item":"bottle","contents":"oil"},
 {"type":"item","x":38,"y":59,"item":"spell"},
 {"type":"item","x":42,"y":59,"item":"wand","tier":2},
 {"type":"item","x":120,"y":59,"item":"barrel_acid"},
 {"type":"item","x":130,"y":59,"item":"barrel_gunpowder"},
 {"type":"encounter","x":50,"y":50,"encounter_id":"E01","variant":0,
  "trigger":{"x":40,"y":40,"w":20,"h":20},"must_pass":true},
 {"type":"rest_area","x":5,"y":5,"w":10,"h":10,"index":1},
 {"type":"item","x":50,"y":59,"item":"no_such_thing"}
"#;

#[test]
fn markers_become_entities() {
    let dir = tempfile::tempdir().unwrap();
    let (png, json) = write_world(dir.path(), MARKERS);
    let g = Game::from_world_files(&png, &json, &WorldOptions::default()).unwrap();
    assert_eq!(g.world().seed(), 9);
    assert_eq!(g.world().rule_seed(), 4);
    let kinds: Vec<String> = g.entities().into_iter().map(|e| e.kind).collect();
    assert_eq!(
        kinds,
        [
            "player",
            "longleg",
            "shotgunner",
            "potion_heal",
            "bottle",
            "spell",
            "wand",
            "barrel_acid",
            "barrel_gunpowder"
        ]
    );
    let p = g.player().unwrap();
    assert_eq!(p.y + p.h, 60, "feet on the ground");
    assert_eq!(p.wands.len(), 2, "the starter loadout");
    let bottles: Vec<_> = g
        .entities()
        .into_iter()
        .filter(|e| e.kind == "bottle" || e.kind.starts_with("potion_"))
        .collect();
    assert_eq!(bottles[0].detail, "potion_heal");
    assert_eq!(bottles[1].detail, "oil");
    // the encounter and the rest area are kept for later, the unknown item too
    let kept: Vec<&str> = g
        .markers()
        .iter()
        .map(|m| m["type"].as_str().unwrap())
        .collect();
    assert_eq!(kept, ["encounter", "rest_area", "item"]);
}

#[test]
fn loot_depends_only_on_the_world_seed() {
    let dir = tempfile::tempdir().unwrap();
    let (png, json) = write_world(dir.path(), MARKERS);
    let load = |seed: Option<u64>| {
        let o = WorldOptions {
            seed,
            ..WorldOptions::default()
        };
        let g = Game::from_world_files(&png, &json, &o).unwrap();
        let wand = g
            .entities()
            .into_iter()
            .find(|e| e.kind == "wand")
            .unwrap()
            .id;
        let spell = g
            .entities()
            .into_iter()
            .find(|e| e.kind == "spell")
            .unwrap()
            .detail;
        (wand, spell, g.state_hash())
    };
    assert_eq!(load(None), load(None));
    assert_eq!(load(None), load(Some(9)));
    assert_ne!(load(None).2, load(Some(10)).2);
}

#[test]
fn a_bad_marker_position_is_an_error() {
    let dir = tempfile::tempdir().unwrap();
    let (png, json) = write_world(
        dir.path(),
        r#"{"type":"spawn_enemy","x":9999,"y":5,"enemy":"longleg"}"#,
    );
    let err = Game::from_world_files(&png, &json, &WorldOptions::default())
        .err()
        .unwrap();
    assert!(err.to_string().contains("outside"), "{err}");
    let (png, json) = write_world(
        dir.path(),
        r#"{"type":"spawn_enemy","x":9,"y":5,"enemy":"dragon"}"#,
    );
    let err = Game::from_world_files(&png, &json, &WorldOptions::default())
        .err()
        .unwrap();
    assert!(err.to_string().contains("dragon"), "{err}");
}

#[test]
fn injected_reactions_replace_the_original_table() {
    let dir = tempfile::tempdir().unwrap();
    let (png, json) = write_world(dir.path(), r#"{"type":"spawn_player","x":20,"y":59}"#);
    let table = r#"{"format":"cogbench-reactions/0","reactions":[
        {"id":"x1","a":"water","b":"oil","out_a":"steam","out_b":"steam","probability":1.0,"source":"test"}]}"#;
    let o = WorldOptions {
        reactions_json: Some(table.to_string()),
        ..WorldOptions::default()
    };
    let mut g = Game::from_world_files(&png, &json, &o).unwrap();
    let plain = Game::from_world_files(&png, &json, &WorldOptions::default()).unwrap();
    assert_ne!(g.world().content().hash, plain.world().content().hash);
    g.world_mut().fill_rect(60, 55, 3, 3, "water").unwrap();
    g.world_mut().fill_rect(63, 55, 3, 3, "oil").unwrap();
    g.step_frames(60, &Controls::default()).unwrap();
    assert!(
        g.world().cell_info(61, 59).is_some(),
        "the world runs with the injected table"
    );
    let steam_or_gone = (50..80)
        .flat_map(|x| (40..60).map(move |y| (x, y)))
        .filter(|&(x, y)| g.world().cell_info(x, y).unwrap().key == "steam")
        .count();
    assert!(
        steam_or_gone > 0,
        "water + oil made steam under the injected row"
    );
    let bad = WorldOptions {
        reactions_json: Some("{}".into()),
        ..WorldOptions::default()
    };
    assert!(Game::from_world_files(&png, &json, &bad).is_err());
}
