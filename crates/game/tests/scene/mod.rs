//! Helpers shared by the integration tests of the game layer: small worlds and a few readers.
#![allow(dead_code)]

use cogbench_game::{Controls, Game};
use cogbench_sim::Value;

/// A `w` by `h` world with a rock floor `thickness` cells thick at the bottom.
pub fn world(w: i32, h: i32, thickness: i32, seed: u64) -> Game {
    let mut g = Game::empty(w, h, seed).expect("game");
    g.world_mut()
        .fill_rect(0, h - thickness, w, thickness, "rock")
        .expect("floor");
    g
}

/// The `y` of the cell a standing creature occupies in a world made by [`world`].
pub fn ground_y(h: i32, thickness: i32) -> i32 {
    h - thickness - 1
}

/// A game with a player standing at `x` on the floor, past the opening invincibility.
pub fn with_player(w: i32, h: i32, thickness: i32, x: i32) -> Game {
    let mut g = world(w, h, thickness, 1);
    g.spawn_player(x, ground_y(h, thickness)).expect("player");
    g.step_frames(61, &Controls::default()).expect("settle");
    g.world_mut().drain_events();
    g
}

pub fn hold(f: impl FnOnce(&mut Controls)) -> Controls {
    let mut c = Controls::default();
    f(&mut c);
    c
}

pub fn run(g: &mut Game, frames: u32, c: &Controls) {
    g.step_frames(frames, c).expect("step");
}

pub fn px(g: &Game) -> i32 {
    g.player().expect("player").x
}

pub fn py(g: &Game) -> i32 {
    g.player().expect("player").y
}

pub fn cell(g: &Game, x: i32, y: i32) -> String {
    g.world().cell_info(x, y).expect("in world").key
}

/// All events so far (drained), as `(type, fields)` pairs.
pub fn events(g: &mut Game) -> Vec<(String, Vec<(String, Value)>)> {
    let content = g.world().content().clone();
    g.world_mut()
        .drain_events()
        .iter()
        .map(|e| {
            let mut fields = e.fields(&content);
            let kind = match fields.remove(1).1 {
                Value::Str(s) => s,
                other => panic!("type is not a string: {other:?}"),
            };
            (
                kind,
                fields
                    .into_iter()
                    .map(|(k, v)| (k.to_string(), v))
                    .collect(),
            )
        })
        .collect()
}

pub fn count(events: &[(String, Vec<(String, Value)>)], kind: &str) -> usize {
    events.iter().filter(|(k, _)| k == kind).count()
}

pub fn int(fields: &[(String, Value)], name: &str) -> i64 {
    match fields.iter().find(|(k, _)| k == name) {
        Some((_, Value::Int(v))) => *v,
        other => panic!("no int field {name}: {other:?}"),
    }
}

pub fn text(fields: &[(String, Value)], name: &str) -> String {
    match fields.iter().find(|(k, _)| k == name) {
        Some((_, Value::Str(v))) => v.clone(),
        other => panic!("no string field {name}: {other:?}"),
    }
}

/// How many cells of a material lie in a rectangle.
pub fn count_cells(g: &Game, x: i32, y: i32, w: i32, h: i32, key: &str) -> usize {
    let mut n = 0;
    for yy in y..y + h {
        for xx in x..x + w {
            if g.world().cell_info(xx, yy).is_some_and(|c| c.key == key) {
                n += 1;
            }
        }
    }
    n
}

/// Wand stats for tests: nothing but the cards limits a cast.
pub fn stats() -> cogbench_game::wand::WandStats {
    cogbench_game::wand::WandStats {
        shuffle: false,
        spells_per_cast: 1,
        cast_delay: 0,
        recharge: 0,
        mana_max: 100_000.0,
        mana_charge_speed: 100_000.0,
        capacity: 26,
        spread: 0.0,
        speed_multiplier: 1.0,
    }
}

/// Give the player a wand with these spells and return its index among the held wands.
pub fn give(g: &mut Game, keys: &[&str]) -> u8 {
    let spells: Vec<Option<String>> = keys.iter().map(|k| Some((*k).to_string())).collect();
    g.give_wand(stats(), &spells, &[]).expect("wand");
    (g.player().expect("player").wands.len() - 1) as u8
}

/// Controls that fire wand `wand` along `aim` degrees.
pub fn fire(wand: u8, aim: f32) -> Controls {
    hold(|c| {
        c.select_wand = Some(wand);
        c.fire = true;
        c.aim = aim;
    })
}

/// The explosion events so far as `(x, y, radius)`.
pub fn explosions(events: &[(String, Vec<(String, Value)>)]) -> Vec<(i64, i64, i64)> {
    events
        .iter()
        .filter(|(k, _)| k == "explosion")
        .map(|(_, f)| (int(f, "x"), int(f, "y"), int(f, "radius")))
        .collect()
}
