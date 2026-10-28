//! Shared helpers: ASCII scenes in the notation of `pixel-simulation.md` (rows top to bottom,
//! y grows down, outside the scene is boundary).
#![allow(dead_code)]

use cogbench_sim::{Content, Tuning, World};
use std::sync::Arc;

/// Legend: `.` air, `#` rock, `S` sand, `W` water, `O` oil, `L` lava, `G` steam, `F` fire,
/// `w` wood, `g` gunpowder, `A` acid, `c` coal, `D` ground, `B` brick, `f` flammable gas,
/// `b` blood, `T` toxic sludge, `H` whiskey.
pub fn key_of(ch: char) -> &'static str {
    match ch {
        '.' => "air",
        '#' => "rock",
        'S' => "sand",
        'W' => "water",
        'O' => "oil",
        'L' => "lava",
        'G' => "steam",
        'F' => "fire",
        'w' => "wood",
        'g' => "gunpowder",
        'A' => "acid",
        'c' => "coal",
        'D' => "ground",
        'B' => "brick",
        'f' => "flammable_gas",
        'b' => "blood",
        'T' => "toxic_sludge",
        'H' => "whiskey",
        other => panic!("unknown scene character {other:?}"),
    }
}

pub fn char_of(key: &str) -> char {
    for ch in ".#SWOLGFwgAcDBfbTH".chars() {
        if key_of(ch) == key {
            return ch;
        }
    }
    '?'
}

pub fn content(tuning: Tuning) -> Arc<Content> {
    Arc::new(Content::embedded_with(tuning).expect("embedded content is valid"))
}

/// Test configuration T of the KB vectors, with the reaction table switched off so motion rules
/// can be checked on their own.
pub fn forced() -> Arc<Content> {
    Arc::new(
        Content::embedded_with(Tuning::forced())
            .and_then(|c| c.with_table(&[]))
            .expect("embedded content is valid"),
    )
}

/// Forced motion plus the real reaction table.
pub fn forced_reactive() -> Arc<Content> {
    content(Tuning::forced())
}

pub fn scene(rows: &[&str], c: Arc<Content>, seed: u64) -> World {
    let h = rows.len() as i32;
    let w = rows[0].chars().count() as i32;
    let mut world = World::new(w, h, seed, c).expect("size");
    for (y, row) in rows.iter().enumerate() {
        assert_eq!(row.chars().count() as i32, w, "ragged scene");
        for (x, ch) in row.chars().enumerate() {
            if ch != '.' {
                world
                    .fill_rect(x as i32, y as i32, 1, 1, key_of(ch))
                    .expect("paint");
            }
        }
    }
    world
}

/// Rows of the world with spaces removed from the comparison on purpose: one char per cell.
pub fn rows(world: &World) -> Vec<String> {
    let c = world.content().clone();
    let (w, h) = (world.width(), world.height());
    (0..h)
        .map(|y| {
            (0..w)
                .map(|x| char_of(c.mats.key_of(world.grid().get(x, y).mat)))
                .collect()
        })
        .collect()
}

/// Compare a scene to rows written with optional spaces between cells (`"S . ."`).
pub fn assert_rows(world: &World, expected: &[&str]) {
    let want: Vec<String> = expected.iter().map(|r| r.replace(' ', "")).collect();
    assert_eq!(rows(world), want, "frame {}", world.frame());
}

/// Same as `scene` but accepts the spaced notation of the KB.
pub fn spaced(rows: &[&str], c: Arc<Content>, seed: u64) -> World {
    let compact: Vec<String> = rows.iter().map(|r| r.replace(' ', "")).collect();
    let refs: Vec<&str> = compact.iter().map(String::as_str).collect();
    scene(&refs, c, seed)
}

/// Step until an event of the given type shows up (or `max` frames pass); returns all events seen.
pub fn step_until(world: &mut World, ty: &str, max: u32) -> Vec<cogbench_sim::Event> {
    let c = world.content().clone();
    let mut seen = Vec::new();
    for _ in 0..max {
        world.step().expect("step");
        let evs = world.drain_events();
        let hit = evs.iter().any(|e| {
            e.fields(&c)
                .iter()
                .any(|(k, v)| *k == "type" && *v == cogbench_sim::Value::Str(ty.into()))
        });
        seen.extend(evs);
        if hit {
            break;
        }
    }
    seen
}

/// Events of one type as `(field, value)` lists.
pub fn of_type(
    events: &[cogbench_sim::Event],
    c: &Content,
    ty: &str,
) -> Vec<Vec<(&'static str, cogbench_sim::Value)>> {
    events
        .iter()
        .map(|e| e.fields(c))
        .filter(|f| {
            f.iter()
                .any(|(k, v)| *k == "type" && *v == cogbench_sim::Value::Str(ty.into()))
        })
        .collect()
}

pub fn int(fields: &[(&'static str, cogbench_sim::Value)], name: &str) -> i64 {
    match fields.iter().find(|(k, _)| *k == name) {
        Some((_, cogbench_sim::Value::Int(n))) => *n,
        other => panic!("field {name}: {other:?}"),
    }
}

pub fn text(fields: &[(&'static str, cogbench_sim::Value)], name: &str) -> String {
    match fields.iter().find(|(k, _)| *k == name) {
        Some((_, cogbench_sim::Value::Str(s))) => s.clone(),
        other => panic!("field {name}: {other:?}"),
    }
}

/// The embedded content with its reaction table replaced by `rows` (id, a, b, out_a, out_b, p).
pub fn custom_table(tuning: Tuning, rows: &[(&str, &str, &str, &str, &str, f64)]) -> Arc<Content> {
    let defs: Vec<cogbench_sim::ReactionDef> = rows
        .iter()
        .map(
            |&(id, a, b, out_a, out_b, probability)| cogbench_sim::ReactionDef {
                id: id.into(),
                a: a.into(),
                b: b.into(),
                out_a: out_a.into(),
                out_b: out_b.into(),
                probability,
                source: String::new(),
            },
        )
        .collect();
    Arc::new(
        Content::embedded_with(tuning)
            .unwrap()
            .with_table(&defs)
            .expect("rows compile"),
    )
}

pub fn count(world: &World, key: &str) -> usize {
    let m = world.content().mats.index_of(key).unwrap();
    world.grid().cells().iter().filter(|c| c.mat == m).count()
}

/// A random material soup (SIM-T35): ground floor, walls, a scatter of every material.
pub fn soup(w: i32, h: i32, world_seed: u64, soup_seed: u64, c: Arc<Content>) -> World {
    use cogbench_sim::rng::Stream;
    let mut world = World::new(w, h, world_seed, c).unwrap();
    let keys: Vec<String> = world
        .content()
        .mats
        .iter()
        .skip(1)
        .map(|m| m.key.clone())
        .collect();
    let mut rng = Stream::new(soup_seed, "soup");
    world.fill_rect(0, h - 4, w, 4, "rock").unwrap();
    for _ in 0..(w * h / 90) {
        let key = &keys[rng.below(keys.len() as u32) as usize];
        let (x, y, r) = (
            rng.below(w as u32) as i32,
            rng.below((h - 4) as u32) as i32,
            rng.below(4) as i32,
        );
        world.paint(x, y, r, key).unwrap();
    }
    world
}

/// Everything observable about a run: state hash and the event log as JSON lines.
pub fn fingerprint(world: &mut World) -> (u64, Vec<String>) {
    let c = world.content().clone();
    let lines = world
        .drain_events()
        .iter()
        .map(|e| e.to_json_line(&c))
        .collect();
    (world.state_hash(), lines)
}
