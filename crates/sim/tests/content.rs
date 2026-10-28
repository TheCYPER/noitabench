//! Content loading and validation: `MAT-R01..R04`, `RXN-R18`, `SIM-T22..T25`.

mod common;
use cogbench_sim::{Content, Kind, Tuning};

const MATERIALS: &str = include_str!("../../../content/materials.json");
const REACTIONS: &str = include_str!("../../../content/reactions.json");

fn load(materials: &str, reactions: &str) -> Result<Content, String> {
    Content::from_texts(
        ("materials.json", materials),
        ("reactions.json", reactions),
        Tuning::default(),
    )
    .map_err(|e| e.to_string())
}

fn patched(from: &str, to: &str) -> String {
    assert!(
        MATERIALS.contains(from),
        "test needs `{from}` in materials.json"
    );
    MATERIALS.replacen(from, to, 1)
}

#[test]
fn sim_t25_loader_reads_the_shipped_content() {
    let c = Content::embedded().unwrap();
    assert_eq!(c.mats.len(), 34);
    assert_eq!(c.mats.index_of("air"), Some(0));
    assert_eq!(c.mats.index_of("fire"), Some(3));
    assert_eq!(c.table.ids().len(), 14);
    let count = |k: Kind| c.mats.iter().filter(|m| m.kind == k).count();
    assert_eq!(
        (
            count(Kind::Air),
            count(Kind::Gas),
            count(Kind::Fire),
            count(Kind::Liquid),
            count(Kind::Powder),
            count(Kind::Static)
        ),
        (1, 2, 1, 19, 6, 5)
    );
    // The index in the file is the u8 cell value.
    for (i, m) in c.mats.iter().enumerate() {
        assert_eq!(usize::from(m.index), i);
    }
}

#[test]
fn embedded_content_equals_the_files_on_disk() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../content");
    let on_disk = Content::from_dir(&dir, Tuning::default()).unwrap();
    assert_eq!(on_disk.hash, Content::embedded().unwrap().hash);
}

#[test]
fn mat_r04_bad_files_fail_with_file_and_field() {
    assert!(load(
        &patched("\"cogbench-materials/0\"", "\"nope/9\""),
        REACTIONS
    )
    .unwrap_err()
    .contains("materials.json: field `format`"));
    assert!(load(&patched("\"index\": 3,", "\"index\": 9,"), REACTIONS)
        .unwrap_err()
        .contains("materials[3].index"));
    assert!(load(&patched("\"#f2a23a\"", "\"orange\""), REACTIONS)
        .unwrap_err()
        .contains("materials[3].color"));
    assert!(load(
        &patched("\"kind\": \"fire\"", "\"kind\": \"plasma\""),
        REACTIONS
    )
    .unwrap_err()
    .contains("materials[3].kind"));
    assert!(load(
        &patched("\"key\": \"water\"", "\"key\": \"steam\""),
        REACTIONS
    )
    .unwrap_err()
    .contains("duplicate key `steam`"));
    assert!(load(
        &patched("\"key\": \"water\"", "\"key\": \"Water\""),
        REACTIONS
    )
    .unwrap_err()
    .contains("snake_case"));
    assert!(
        load(&patched("\"density\": 4,", "\"density\": 0,"), REACTIONS)
            .unwrap_err()
            .contains("materials[4].density")
    );
    assert!(load(
        &patched("\"density\": 4.1,", "\"density\": 4.12345,"),
        REACTIONS
    )
    .unwrap_err()
    .contains("at most 4 decimals"));
    assert!(load(
        &patched("\"liquid_gravity\": 1.5,", "\"liquid_gravity\": null,"),
        REACTIONS
    )
    .unwrap_err()
    .contains("liquid_gravity"));
    assert!(load("{ not json", REACTIONS)
        .unwrap_err()
        .starts_with("materials.json: field `(json)`"));
}

#[test]
fn mat_r02_the_engine_needs_a_fire_material() {
    let err = load(
        &patched("\"key\": \"fire\"", "\"key\": \"blaze\""),
        REACTIONS,
    )
    .unwrap_err();
    assert!(err.contains("blaze") || err.contains("fire"), "{err}");
}

#[test]
fn rxn_r18_reactions_file_errors_name_the_file() {
    let bad = REACTIONS.replacen("\"b\": \"water\"", "\"b\": \"moonwater\"", 1);
    let err = load(MATERIALS, &bad).unwrap_err();
    assert!(
        err.starts_with("reactions.json: field `reactions[0].b (r01)`"),
        "{err}"
    );
    let bad = REACTIONS.replacen("cogbench-reactions/0", "cogbench-reactions/7", 1);
    assert!(load(MATERIALS, &bad)
        .unwrap_err()
        .contains("expected `cogbench-reactions/0`"));
}

#[test]
fn sim_t22_derived_parameters_are_integers_from_the_file() {
    let c = Content::embedded().unwrap();
    let rt = |k: &str| *c.mats.rt(c.mats.index_of(k).unwrap());
    // fall = 2g in hundredths -> whole steps + q8 chance
    assert_eq!((rt("sand").fall_int, rt("sand").fall_frac_q8), (1, 205));
    assert_eq!((rt("water").fall_int, rt("water").fall_frac_q8), (3, 0));
    assert_eq!((rt("lava").fall_int, rt("lava").fall_frac_q8), (0, 102));
    // powders: slide chance falls with viscosity; liquids always slide
    assert_eq!(rt("sand").slide_q8, 192);
    assert_eq!(rt("water").slide_q8, 256);
    // densities are exact in x10,000
    assert_eq!(rt("blood").density_x10000, 41_000);
    assert_eq!(rt("acid").density_x10000, 29_000);
    // gunpowder is the explosive one, and its numbers come from the file
    assert!(rt("gunpowder").explosion.is_some() && rt("coal").explosion.is_none());
}

const GUNPOWDER_EXPLOSION: &str = "\"explosion\": {
    \"radius\": 8,
    \"ray_energy\": 400000,
    \"max_durability\": 10,
    \"fire_percent\": 25
   }";

#[test]
fn fire_r10_explosion_block_is_read_from_materials_json() {
    let c = Content::embedded().unwrap();
    let e = c.mats.rt(c.mats.index_of("gunpowder").unwrap()).explosion;
    assert_eq!(
        e,
        Some(cogbench_sim::material::ExplosionParams {
            radius: 8,
            ray_energy: 400_000,
            max_durability: 10,
            fire_percent: 25,
        })
    );
    // Exactly one shipped material explodes.
    let n = c.mats.iter().filter(|m| m.explosion.is_some()).count();
    assert_eq!(n, 1);
}

#[test]
fn fire_r10_bad_explosion_blocks_fail_with_file_and_field() {
    // radius out of range or fractional, percent over 100, energy zero, durability over 255
    for (from, to, field) in [
        ("\"radius\": 8", "\"radius\": 0", "radius"),
        ("\"radius\": 8", "\"radius\": 8.5", "radius"),
        ("\"radius\": 8", "\"radius\": 5000", "radius"),
        (
            "\"fire_percent\": 25",
            "\"fire_percent\": 101",
            "fire_percent",
        ),
        ("\"ray_energy\": 400000", "\"ray_energy\": 0", "ray_energy"),
        (
            "\"max_durability\": 10,\n    \"fire",
            "\"max_durability\": 256,\n    \"fire",
            "max_durability",
        ),
    ] {
        let err = load(&patched(from, to), REACTIONS).unwrap_err();
        assert!(
            err.contains(&format!(
                "materials.json: field `materials[13].explosion.{field}`"
            )),
            "{err}"
        );
    }
    // a missing number is a parse error that names the file
    let err = load(
        &patched("\"max_durability\": 10,\n    \"fire", "\"fire"),
        REACTIONS,
    )
    .unwrap_err();
    assert!(
        err.starts_with("materials.json: field `(json)`") && err.contains("max_durability"),
        "{err}"
    );
}

#[test]
fn fire_r10_only_burnable_materials_may_carry_an_explosion_block() {
    // Sand cannot burn, so a block on it would never fire: refuse it at load time.
    let sand = "\"key\": \"sand\",";
    assert!(MATERIALS.contains(sand));
    let tags = "\"tags\": [\n    \"corrodible\",\n    \"ingredient\"\n   ],\n   \"drink_effect\": \"none\"";
    let text = MATERIALS.replacen(tags, &format!("{tags},\n   {GUNPOWDER_EXPLOSION}"), 1);
    assert_ne!(
        text, MATERIALS,
        "test needs a material with only the corrodible and ingredient tags"
    );
    let err = load(&text, REACTIONS).unwrap_err();
    assert!(
        err.contains(".explosion") && err.contains("burnable"),
        "{err}"
    );
}

#[test]
fn sim_t24_timers() {
    let c = Content::embedded().unwrap();
    let rt = |k: &str| *c.mats.rt(c.mats.index_of(k).unwrap());
    assert_eq!((rt("steam").life_unit, rt("steam").life0), (4, 250));
    // flammable gas has no lifetime (lead decision 2026-10-26: placed gas pockets must persist)
    assert_eq!(rt("flammable_gas").life_unit, 0);
    assert_eq!((rt("fire").life_unit, rt("fire").life0), (1, 12));
    assert_eq!((rt("coal").burn_unit, rt("coal").burn0), (4, 250));
    assert_eq!((rt("oil").burn_unit, rt("oil").burn0), (2, 250));
    assert_eq!((rt("wood").burn_unit, rt("wood").burn0), (3, 200));
    assert_eq!(rt("sand").life_unit, 0);
}

#[test]
fn tuning_is_validated() {
    let bad = Tuning {
        liquid_hop: 0,
        ..Tuning::default()
    };
    assert!(Content::embedded_with(bad).is_err());
    let bad = Tuning {
        liquid_hop: 99,
        ..Tuning::default()
    };
    assert!(Content::embedded_with(bad).is_err());
}
