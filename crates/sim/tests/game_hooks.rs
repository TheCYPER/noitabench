//! The two small hooks the game layer uses: `World::set_cell` (spills, trails) and
//! `World::log_event` (damage, deaths, pickups).

mod common;

use cogbench_sim::{Event, Value, World};

fn empty() -> World {
    World::new(16, 16, 1, common::content(cogbench_sim::Tuning::default())).unwrap()
}

#[test]
fn set_cell_puts_a_material_and_wakes_the_area() {
    let mut w = empty();
    let water = w.content().mats.index_of("water").unwrap();
    assert!(w.set_cell(5, 3, water, false));
    assert_eq!(w.cell_info(5, 3).unwrap().key, "water");
    w.step_frames(40).unwrap();
    assert_eq!(
        w.cell_info(5, 3).unwrap().key,
        "air",
        "it fell: the area was awake"
    );
    let n = (0..16)
        .filter(|&y| w.cell_info(5, y).unwrap().key == "water")
        .count();
    assert_eq!(n, 1);
}

#[test]
fn set_cell_refuses_bad_positions_and_materials() {
    let mut w = empty();
    assert!(!w.set_cell(-1, 0, 1, false));
    assert!(!w.set_cell(0, 16, 1, false));
    assert!(!w.set_cell(0, 0, 200, false), "no such material");
}

#[test]
fn set_cell_can_light_a_burnable_material() {
    let mut w = empty();
    let oil = w.content().mats.index_of("oil").unwrap();
    let rock = w.content().mats.index_of("rock").unwrap();
    assert!(w.set_cell(4, 4, oil, true));
    assert!(w.cell_info(4, 4).unwrap().burning);
    assert!(w.set_cell(8, 8, rock, true));
    assert!(!w.cell_info(8, 8).unwrap().burning, "rock does not burn");
    assert!(w.set_cell(4, 4, 0, false), "clearing a cell");
    assert_eq!(w.cell_info(4, 4).unwrap().key, "air");
}

#[test]
fn game_events_carry_their_fields_into_json() {
    let mut w = empty();
    w.step_frames(3).unwrap();
    w.log_event(
        "damage",
        vec![
            ("target", Value::Str("player".into())),
            ("amount", Value::Float(12.5)),
            ("id", Value::Int(1)),
        ],
    );
    let events = w.drain_events();
    assert_eq!(events.len(), 1);
    assert!(matches!(
        &events[0],
        Event::Game {
            frame: 3,
            kind: "damage",
            ..
        }
    ));
    let line = events[0].to_json_line(w.content());
    assert_eq!(
        line,
        r#"{"frame":3,"type":"damage","target":"player","amount":12.5,"id":1}"#
    );
    let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();
    assert_eq!(parsed["amount"], 12.5);
}

#[test]
fn non_finite_floats_are_written_as_zero() {
    let mut w = empty();
    w.log_event("x", vec![("v", Value::Float(f64::NAN))]);
    let line = w.drain_events()[0].to_json_line(w.content());
    assert_eq!(line, r#"{"frame":0,"type":"x","v":0.0}"#);
}
