//! Loading a world file pair (contract section 4).

mod common;
use cogbench_sim::worldfile::load_world_files;
use cogbench_sim::{Tuning, World};
use common::*;
use std::path::Path;

fn write_png(
    path: &Path,
    w: u32,
    h: u32,
    indices: &[u8],
    color: png::ColorType,
    depth: png::BitDepth,
) {
    let file = std::fs::File::create(path).unwrap();
    let mut enc = png::Encoder::new(std::io::BufWriter::new(file), w, h);
    enc.set_color(color);
    enc.set_depth(depth);
    if color == png::ColorType::Indexed {
        enc.set_palette((0..=255u8).flat_map(|i| [i, i, i]).collect::<Vec<_>>());
    }
    enc.write_header()
        .unwrap()
        .write_image_data(indices)
        .unwrap();
}

fn write_json(path: &Path, w: i32, h: i32) {
    std::fs::write(
        path,
        format!(r#"{{"format": "cogbench-world/0", "seed": 5, "rule_seed": 77, "width": {w}, "height": {h}, "biome_cell_size": 128, "biome_map": [], "markers": []}}"#),
    )
    .unwrap();
}

#[test]
fn world_file_pair_loads_into_a_world() {
    let dir = tempfile::tempdir().unwrap();
    let (png, json) = (dir.path().join("w.png"), dir.path().join("w.json"));
    let c = content(Tuning::default());
    let rock = c.mats.index_of("rock").unwrap();
    let water = c.mats.index_of("water").unwrap();
    let mut px = vec![0u8; 12 * 6];
    px[12 * 5..].fill(rock);
    px[12 * 4 + 3] = water;
    write_png(
        &png,
        12,
        6,
        &px,
        png::ColorType::Indexed,
        png::BitDepth::Eight,
    );
    write_json(&json, 12, 6);
    let f = load_world_files(&png, &json).unwrap();
    assert_eq!(
        (f.meta.width, f.meta.height, f.meta.seed, f.meta.rule_seed),
        (12, 6, 5, 77)
    );
    let w = World::from_indices(f.meta.width, f.meta.height, 1, &f.indices, c).unwrap();
    assert_eq!(w.grid_bytes(), px);
}

#[test]
fn world_file_errors_are_specific() {
    let dir = tempfile::tempdir().unwrap();
    let (png, json) = (dir.path().join("w.png"), dir.path().join("w.json"));
    write_json(&json, 4, 4);
    // wrong colour type
    write_png(
        &png,
        4,
        4,
        &[0; 16 * 3],
        png::ColorType::Rgb,
        png::BitDepth::Eight,
    );
    assert!(load_world_files(&png, &json)
        .unwrap_err()
        .to_string()
        .contains("8-bit indexed"));
    // size mismatch between PNG and JSON
    write_png(
        &png,
        4,
        4,
        &[0; 16],
        png::ColorType::Indexed,
        png::BitDepth::Eight,
    );
    write_json(&json, 5, 4);
    assert!(load_world_files(&png, &json)
        .unwrap_err()
        .to_string()
        .contains("does not match"));
    // wrong format string
    std::fs::write(&json, r#"{"format": "x", "width": 4, "height": 4}"#).unwrap();
    assert!(load_world_files(&png, &json)
        .unwrap_err()
        .to_string()
        .contains("cogbench-world/0"));
    // missing file
    assert!(load_world_files(&dir.path().join("nope.png"), &json).is_err());
    // material index outside the content set
    write_json(&json, 4, 4);
    let f = load_world_files(&png, &json).unwrap();
    let mut bad = f.indices.clone();
    bad[3] = 200;
    let err = World::from_indices(4, 4, 1, &bad, content(Tuning::default()))
        .err()
        .unwrap();
    assert!(err.to_string().contains("material index 200"), "{err}");
}
