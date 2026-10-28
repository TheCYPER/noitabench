//! Fire and burning: `FIRE-R03..R06`, `FIRE-R10`, `SIM-R37`, vectors `MV-19..MV-21`.

mod common;
use cogbench_sim::{Tuning, World};
use common::*;

#[test]
fn mv_19_ignition_chance_is_100_minus_autoignition() {
    // Fire in the middle, wood (autoignition 85) on all four sides, one step: the roll picks one
    // neighbour and succeeds with 15 %.
    let mut hits = 0;
    let trials = 6000;
    for seed in 0..trials {
        let mut w = scene(&["#w#", "wFw", "#w#"], forced(), seed);
        w.step().unwrap();
        hits += of_type(&w.drain_events(), &w.content().clone(), "ignite").len();
    }
    let p = hits as f64 / f64::from(trials as u32);
    assert!((p - 0.15).abs() < 0.02, "ignition rate {p}");
}

#[test]
fn fire_r03_source_must_be_hotter_than_the_ignition_temperature() {
    // Burning wood (temperature 90) never lights coal (ignition 94); it does light more wood.
    let run = |neighbour: char| {
        let mut w = scene(&["#.##", &format!("#w{neighbour}#"), "####"], forced(), 3);
        assert!(w.ignite(1, 1));
        w.step_frames(500).unwrap();
        w.drain_events()
    };
    let c = forced().clone();
    assert!(
        of_type(&run('c'), &c, "ignite").is_empty(),
        "coal must stay cold"
    );
    let lit = of_type(&run('w'), &c, "ignite");
    assert_eq!(lit.len(), 1, "the second wood block ignites");
    assert_eq!(text(&lit[0], "by"), "wood");
}

#[test]
fn mv_20_wood_burns_to_nothing_no_ash() {
    let mut w = scene(&[".", "w", "#"], forced(), 1);
    assert!(w.ignite(0, 1));
    w.step_frames(650).unwrap();
    assert_eq!(count(&w, "wood"), 0);
    assert_eq!(count(&w, "rock"), 1);
}

#[test]
fn mv_21_oxygen_wood_inside_does_not_burn_gunpowder_does() {
    // A wood cell with no air around it makes no progress.
    let mut w = scene(&["###", "#w#", "###"], forced(), 1);
    assert!(w.ignite(1, 1));
    w.step_frames(900).unwrap();
    assert_eq!(count(&w, "wood"), 1, "smothered fuel does not burn");

    // Gunpowder needs no oxygen: it burns (detonates) even enclosed.
    let mut w = scene(&["###", "#g#", "###"], forced(), 1);
    assert!(w.ignite(1, 1));
    w.step_frames(3).unwrap();
    assert_eq!(count(&w, "gunpowder"), 0);
}

#[test]
fn fire_r04_burning_cells_throw_flames() {
    let mut w = scene(&["...", ".w.", "###"], forced(), 4);
    assert!(w.ignite(1, 1));
    let mut saw_fire = false;
    for _ in 0..60 {
        w.step().unwrap();
        saw_fire |= count(&w, "fire") > 0;
    }
    assert!(saw_fire, "a burning cell with free neighbours emits fire");
}

#[test]
fn fire_r10_burning_gunpowder_detonates_and_digs() {
    let mut w = cogbench_sim::World::new(40, 30, 2, forced()).unwrap();
    w.fill_rect(0, 20, 40, 10, "ground").unwrap();
    w.fill_rect(18, 18, 4, 2, "gunpowder").unwrap();
    let before = count(&w, "ground");
    assert!(w.ignite(18, 18));
    let evs = step_until(&mut w, "explosion", 60);
    let c = w.content().clone();
    assert!(
        !of_type(&evs, &c, "explosion").is_empty(),
        "no explosion happened"
    );
    w.step_frames(60).unwrap();
    assert_eq!(count(&w, "gunpowder"), 0, "the pile is consumed");
    assert!(
        count(&w, "ground") < before - 30,
        "the blast must dig a crater"
    );
}

#[test]
fn fire_r07_fire_cells_are_short_lived() {
    let c = content(Tuning::default());
    let mut w = World::new(8, 8, 1, c).unwrap();
    w.paint(4, 4, 0, "fire").unwrap();
    w.step_frames(31).unwrap();
    assert_eq!(count(&w, "fire"), 0, "fire cells live 12-30 frames");
}

#[test]
fn sim_r54_explosion_queue_is_capped_per_frame() {
    // 100 isolated gunpowder cells all burn out in the same frame; at most 32 explosions run per
    // frame afterwards.
    let mut w = World::new(220, 220, 5, forced()).unwrap();
    for i in 0..10 {
        for j in 0..10 {
            w.paint(10 + i * 20, 10 + j * 20, 0, "gunpowder").unwrap();
            assert!(w.ignite(10 + i * 20, 10 + j * 20));
        }
    }
    let c = w.content().clone();
    w.step().unwrap(); // every cell burns out, 100 explosions queued
    assert_eq!(w.pending_explosions().len(), 100);
    let mut per_frame = Vec::new();
    for _ in 0..5 {
        w.step().unwrap();
        per_frame.push(of_type(&w.drain_events(), &c, "explosion").len());
    }
    assert_eq!(per_frame, vec![32, 32, 32, 4, 0]);
}

#[test]
fn fire_r10_a_blast_sets_off_packed_powder_beyond_its_radius() {
    // A shaft of gunpowder 8 wide and 40 deep in solid ground: lighting the top makes the whole
    // column go up, blast after blast, although each blast only reaches radius 8.
    let mut w = cogbench_sim::World::new(60, 80, 3, forced()).unwrap();
    w.fill_rect(0, 20, 60, 60, "ground").unwrap();
    w.fill_rect(26, 20, 8, 40, "gunpowder").unwrap();
    assert!(w.ignite(30, 20));
    w.step_frames(60).unwrap();
    assert_eq!(
        count(&w, "gunpowder"),
        0,
        "the whole column must have exploded"
    );
    let c = w.content().clone();
    assert!(of_type(&w.drain_events(), &c, "explosion").len() >= 3);
}

const MATERIALS: &str = include_str!("../../../content/materials.json");
const REACTIONS: &str = include_str!("../../../content/reactions.json");

fn world_with_materials(text: &str, seed: u64) -> World {
    let c = cogbench_sim::Content::from_texts(
        ("materials.json", text),
        ("reactions.json", REACTIONS),
        Tuning::forced(),
    )
    .expect("patched materials load");
    let mut w = World::new(40, 30, seed, std::sync::Arc::new(c)).unwrap();
    w.fill_rect(0, 20, 40, 10, "ground").unwrap();
    w.fill_rect(18, 18, 4, 2, "gunpowder").unwrap();
    w
}

#[test]
fn fire_r10_detonation_uses_the_explosion_block_of_the_material() {
    // The shipped block: radius 8. Patch it to radius 3, then to 12: the event follows the file.
    for radius in [3u32, 12] {
        let text = MATERIALS.replacen("\"radius\": 8", &format!("\"radius\": {radius}"), 1);
        let mut w = world_with_materials(&text, 2);
        // one lone cell, so there is exactly one blast
        w.fill_rect(18, 18, 4, 2, "air").unwrap();
        w.paint(20, 19, 0, "gunpowder").unwrap();
        assert!(w.ignite(20, 19));
        let c = w.content().clone();
        let evs = of_type(&step_until(&mut w, "explosion", 30), &c, "explosion");
        assert_eq!(evs.len(), 1);
        assert_eq!(int(&evs[0], "radius"), i64::from(radius));
    }
}

#[test]
fn fire_r10_a_burnable_material_without_an_explosion_block_just_burns_out() {
    let block = "\"drink_effect\": \"none\",
   \"explosion\": {
    \"radius\": 8,
    \"ray_energy\": 400000,
    \"max_durability\": 10,
    \"fire_percent\": 25
   }";
    assert!(
        MATERIALS.contains(block),
        "test needs the gunpowder explosion block"
    );
    let text = MATERIALS.replacen(block, "\"drink_effect\": \"none\"", 1);
    let mut w = world_with_materials(&text, 2);
    let before = count(&w, "ground");
    assert!(w.ignite(18, 18));
    w.step_frames(120).unwrap();
    let c = w.content().clone();
    assert!(of_type(&w.drain_events(), &c, "explosion").is_empty());
    assert_eq!(count(&w, "ground"), before, "no blast, no crater");
}
