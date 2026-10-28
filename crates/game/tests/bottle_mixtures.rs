//! Bottles hold mixtures: fill, pour, drink and throw work on every material in proportion, and
//! inside a bottle the secret recipes of the world turn ingredients into the potion.

mod scene;

use std::sync::Arc;

use scene::*;

use cogbench_game::{Controls, EntityDefs, Game, ItemSpec, SpellBook};
use cogbench_sim::{Content, RecipeDef, World};

const W: i32 = 500;
const H: i32 = 200;
const FLOOR: i32 = 30;

fn arena() -> Game {
    with_player(W, H, FLOOR, 100)
}

/// An arena whose world has the given recipes (`potion`, three ingredients).
fn arena_with_recipes(recipes: &[(&str, [&str; 3])]) -> Game {
    let defs: Vec<RecipeDef> = recipes
        .iter()
        .map(|(potion, inputs)| RecipeDef {
            potion: (*potion).to_string(),
            inputs: inputs.map(str::to_string),
        })
        .collect();
    let content = Arc::new(Content::embedded().unwrap().with_recipes(&defs).unwrap());
    let mut world = World::new(W, H, 1, content).unwrap();
    world.fill_rect(0, H - FLOOR, W, FLOOR, "rock").unwrap();
    let mut g = Game::with_content(
        world,
        Arc::new(SpellBook::embedded().unwrap()),
        Arc::new(EntityDefs::embedded().unwrap()),
    )
    .unwrap();
    g.spawn_player(100, ground_y(H, FLOOR)).unwrap();
    g.step_frames(61, &Controls::default()).unwrap();
    g.world_mut().drain_events();
    g
}

fn mix(parts: &[(&str, u32)]) -> Vec<(String, u32)> {
    parts.iter().map(|(k, n)| ((*k).to_string(), *n)).collect()
}

fn contents(g: &Game, bottle: usize) -> Vec<(String, u32)> {
    g.player().unwrap().bottle_contents[bottle].clone()
}

/// Rock walls so that a liquid stays in a pit above the floor.
fn pit(g: &mut Game, x0: i32, width: i32) {
    let y = ground_y(H, FLOOR);
    g.world_mut()
        .fill_rect(x0 - 3, y - 60, 3, 61, "rock")
        .unwrap();
    g.world_mut()
        .fill_rect(x0 + width, y - 60, 3, 61, "rock")
        .unwrap();
}

fn press(f: impl FnOnce(&mut Controls)) -> Controls {
    hold(f)
}

// ----- the old single-material surface keeps working ----------------------------------------

#[test]
fn a_single_material_bottle_looks_like_it_always_did() {
    let mut g = arena();
    g.give_bottle(Some("water"), None).unwrap();
    g.give_bottle(None, None).unwrap();
    let p = g.player().unwrap();
    assert_eq!(
        p.bottles,
        vec![("water".to_string(), 400), (String::new(), 0)]
    );
    assert_eq!(p.bottle_contents[0], mix(&[("water", 400)]));
    assert!(p.bottle_contents[1].is_empty());
}

#[test]
fn a_mixed_bottle_shows_its_largest_share_and_all_its_cells() {
    let mut g = arena();
    g.give_mixed_bottle(&mix(&[("oil", 60), ("water", 100), ("blood", 40)]))
        .unwrap();
    let p = g.player().unwrap();
    assert_eq!(p.bottles, vec![("water".to_string(), 200)]);
    // by material index: water 4, blood 5, oil 6
    assert_eq!(
        p.bottle_contents[0],
        mix(&[("water", 100), ("blood", 40), ("oil", 60)])
    );
    // too much, and unknown materials, are refused
    assert!(g
        .give_mixed_bottle(&mix(&[("water", 300), ("oil", 101)]))
        .is_err());
    assert!(g.give_mixed_bottle(&mix(&[("mercury", 3)])).is_err());
}

// ----- fill --------------------------------------------------------------------------------

#[test]
fn filling_adds_whatever_liquid_is_scooped_to_what_the_bottle_holds() {
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    pit(&mut g, 80, 40);
    g.world_mut().fill_rect(80, y - 5, 40, 6, "water").unwrap();
    g.give_bottle(Some("oil"), Some(100)).unwrap();
    run(&mut g, 4, &press(|c| c.fill = true));
    let held = contents(&g, 0);
    assert_eq!(held[0], ("water".to_string(), 80), "4 frames x 20 cells");
    assert_eq!(held[1], ("oil".to_string(), 100));
    assert_eq!(g.player().unwrap().bottles, vec![("oil".to_string(), 180)]);
}

#[test]
fn filling_in_two_liquids_takes_both() {
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    pit(&mut g, 80, 40);
    g.world_mut().fill_rect(80, y - 3, 40, 4, "water").unwrap();
    g.world_mut().fill_rect(80, y - 5, 40, 2, "oil").unwrap();
    g.give_bottle(None, None).unwrap();
    run(&mut g, 30, &press(|c| c.fill = true));
    run(&mut g, 1, &Controls::default());
    let held = contents(&g, 0);
    let names: Vec<&str> = held.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(names, ["water", "oil"]);
    // the top layer (oil) is taken first, then the water below it
    assert!(held.iter().all(|(_, n)| *n > 0), "{held:?}");
    let ev = events(&mut g);
    assert_eq!(
        ev.iter().filter(|(k, _)| k == "fill").count(),
        2,
        "one summary per material"
    );
}

#[test]
fn a_full_bottle_stops_scooping() {
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    pit(&mut g, 80, 40);
    g.world_mut().fill_rect(80, y - 8, 40, 9, "water").unwrap();
    g.give_mixed_bottle(&mix(&[("oil", 390)])).unwrap();
    run(&mut g, 5, &press(|c| c.fill = true));
    assert_eq!(g.player().unwrap().bottles[0].1, 400);
    assert_eq!(contents(&g, 0), mix(&[("water", 10), ("oil", 390)]));
}

// ----- pour --------------------------------------------------------------------------------

#[test]
fn pouring_a_mixture_puts_every_material_in_proportion() {
    let mut g = arena();
    g.give_mixed_bottle(&mix(&[("water", 300), ("oil", 100)]))
        .unwrap();
    let pour = press(|c| {
        c.pour = true;
        c.aim = 0.0;
    });
    run(&mut g, 10, &pour); // up to 80 cells
    let water = count_cells(&g, 0, 0, W, H, "water") as i64;
    let oil = count_cells(&g, 0, 0, W, H, "oil") as i64;
    assert!(water + oil >= 70, "{water} + {oil}");
    // three parts water to one part oil; the last cells of a frame (the oil) are the ones that
    // may find no room at the crowded mouth
    assert!(
        oil >= 10 && water >= 2 * oil && water <= 4 * oil,
        "{water} {oil}"
    );
    // cells that found no room stay in the bottle: nothing is lost
    let left = contents(&g, 0);
    assert_eq!(left[0].1 as i64 + water, 300);
    assert_eq!(left[1].1 as i64 + oil, 100);
    run(&mut g, 1, &Controls::default());
    let ev = events(&mut g);
    let pours: Vec<(String, i64)> = ev
        .iter()
        .filter(|(k, _)| k == "pour")
        .map(|(_, f)| (text(f, "material"), int(f, "cells")))
        .collect();
    assert_eq!(
        pours,
        [("water".to_string(), water), ("oil".to_string(), oil)]
    );
}

#[test]
fn pouring_until_empty_empties_every_material() {
    let mut g = arena();
    g.give_mixed_bottle(&mix(&[("water", 25), ("oil", 10), ("blood", 5)]))
        .unwrap();
    run(
        &mut g,
        10,
        &press(|c| {
            c.pour = true;
            c.aim = 0.0;
        }),
    );
    assert_eq!(g.player().unwrap().bottles, vec![(String::new(), 0)]);
    assert_eq!(count_cells(&g, 0, 0, W, H, "water"), 25);
    assert_eq!(count_cells(&g, 0, 0, W, H, "oil"), 10);
    assert_eq!(count_cells(&g, 0, 0, W, H, "blood"), 5);
}

// ----- drink -------------------------------------------------------------------------------

#[test]
fn drinking_a_mixture_applies_each_materials_effect_in_proportion() {
    let mut g = arena();
    // hurt the player a little so that the healing shows
    for _ in 0..2 {
        g.blast(cogbench_game::BlastSpec {
            x: 100,
            y: ground_y(H, FLOOR) - 4,
            radius: 5,
            damage: 3.0,
            ray_energy: 1000,
            max_durability: 4,
            fire_percent: 0,
            owner: cogbench_game::entity::Owner::World,
            spare_owner: false,
        });
    }
    let hurt = g.player().unwrap().hp;
    g.give_mixed_bottle(&mix(&[("potion_heal", 100), ("potion_haste", 100)]))
        .unwrap();
    run(&mut g, 1, &press(|c| c.drink = true)); // 10 cells: 5 of each
    let p = g.player().unwrap();
    assert_eq!(
        p.bottle_contents[0],
        mix(&[("potion_heal", 95), ("potion_haste", 95)])
    );
    // haste: 2 frames a cell, 5 cells; the frame of the sip has already run one of them down
    let haste = p.statuses.iter().find(|(s, _)| s == "haste").unwrap().1;
    assert_eq!(haste, 9);
    // heal: 0.01 internal a cell = 0.25 shown; 5 cells
    assert!((p.hp - hurt - 1.25).abs() < 0.05, "{hurt} -> {}", p.hp);
}

#[test]
fn a_mixture_drunk_to_the_last_drop_gives_the_full_status_time_of_each_part() {
    let mut g = arena();
    g.give_mixed_bottle(&mix(&[("potion_haste", 40), ("potion_heal", 60)]))
        .unwrap();
    run(&mut g, 10, &press(|c| c.drink = true));
    let p = g.player().unwrap();
    assert_eq!(p.bottles, vec![(String::new(), 0)]);
    let haste = p.statuses.iter().find(|(s, _)| s == "haste").unwrap().1;
    // 40 cells x 2 frames, whatever the sip sizes, less the 10 frames that have run since
    assert_eq!(haste, 80 - 10);
}

// ----- throw -------------------------------------------------------------------------------

#[test]
fn a_thrown_mixture_spills_every_material_where_it_lands() {
    let mut g = arena();
    g.give_mixed_bottle(&mix(&[("water", 60), ("oil", 40)]))
        .unwrap();
    run(
        &mut g,
        1,
        &press(|c| {
            c.throw = true;
            c.aim = 20.0;
        }),
    );
    run(&mut g, 90, &Controls::default());
    assert!(g.player().unwrap().bottles.is_empty());
    assert_eq!(count_cells(&g, 0, 0, W, H, "water"), 60);
    assert_eq!(count_cells(&g, 0, 0, W, H, "oil"), 40);
    let ev = events(&mut g);
    let t = ev.iter().find(|(k, _)| k == "throw").unwrap();
    assert_eq!(text(&t.1, "material"), "water+oil");
    assert_eq!(int(&t.1, "cells"), 100);
    let s = ev.iter().find(|(k, _)| k == "shatter").unwrap();
    assert_eq!(text(&s.1, "material"), "water+oil");
    assert_eq!(int(&s.1, "cells"), 100);
}

// ----- recipes inside bottles --------------------------------------------------------------

const RECIPE: (&str, [&str; 3]) = ("potion_crit", ["water", "blood", "oil"]);

#[test]
fn a_bottle_with_all_three_ingredients_turns_them_into_the_potion_over_time() {
    let mut g = arena_with_recipes(&[RECIPE]);
    g.give_mixed_bottle(&mix(&[("water", 100), ("blood", 100), ("oil", 100)]))
        .unwrap();
    // 4 cells of each per frame
    run(&mut g, 10, &Controls::default());
    assert_eq!(
        contents(&g, 0),
        mix(&[
            ("water", 60),
            ("blood", 60),
            ("oil", 60),
            ("potion_crit", 120)
        ])
    );
    run(&mut g, 15, &Controls::default());
    assert_eq!(contents(&g, 0), mix(&[("potion_crit", 300)]));
    assert_eq!(
        g.player().unwrap().bottles,
        vec![("potion_crit".to_string(), 300)]
    );
    run(&mut g, 20, &Controls::default());
    assert_eq!(
        contents(&g, 0),
        mix(&[("potion_crit", 300)]),
        "nothing more to do"
    );
    let ev = events(&mut g);
    let made: i64 = ev
        .iter()
        .filter(|(k, _)| k == "mix")
        .map(|(_, f)| int(f, "cells"))
        .sum();
    assert_eq!(
        made, 300,
        "100 cells of each ingredient became 300 cells of potion"
    );
}

#[test]
fn two_ingredients_of_three_do_nothing() {
    let mut g = arena_with_recipes(&[RECIPE]);
    g.give_mixed_bottle(&mix(&[("water", 100), ("blood", 100), ("sand", 100)]))
        .unwrap();
    run(&mut g, 120, &Controls::default());
    assert_eq!(
        contents(&g, 0),
        mix(&[("water", 100), ("blood", 100), ("sand", 100)])
    );
    assert_eq!(count(&events(&mut g), "mix"), 0);
}

#[test]
fn the_third_ingredient_poured_in_later_starts_the_conversion() {
    let mut g = arena_with_recipes(&[RECIPE]);
    let y = ground_y(H, FLOOR);
    pit(&mut g, 80, 40);
    g.world_mut().fill_rect(80, y - 5, 40, 6, "oil").unwrap();
    g.give_mixed_bottle(&mix(&[("water", 50), ("blood", 50)]))
        .unwrap();
    run(&mut g, 30, &Controls::default());
    assert_eq!(contents(&g, 0), mix(&[("water", 50), ("blood", 50)]));
    run(&mut g, 2, &press(|c| c.fill = true));
    run(&mut g, 60, &Controls::default());
    let held = contents(&g, 0);
    assert!(
        held.iter().any(|(k, n)| k == "potion_crit" && *n > 0),
        "{held:?}"
    );
}

#[test]
fn only_the_recipes_of_the_world_count_and_other_reactions_do_not_run_in_a_bottle() {
    let mut g = arena_with_recipes(&[RECIPE]);
    // lava and water would make rock in the grid; in a bottle they just sit together
    g.give_mixed_bottle(&mix(&[("lava", 50), ("water", 50)]))
        .unwrap();
    run(&mut g, 60, &Controls::default());
    assert_eq!(contents(&g, 0), mix(&[("water", 50), ("lava", 50)]));
    // a world without recipes converts nothing
    let mut none = arena();
    none.give_mixed_bottle(&mix(&[("water", 10), ("blood", 10), ("oil", 10)]))
        .unwrap();
    run(&mut none, 60, &Controls::default());
    assert_eq!(
        contents(&none, 0),
        mix(&[("water", 10), ("blood", 10), ("oil", 10)])
    );
}

#[test]
fn a_bottle_lying_on_the_ground_converts_too() {
    let mut g = arena_with_recipes(&[RECIPE]);
    let id = g
        .spawn_item(
            &ItemSpec::MixedBottle {
                contents: mix(&[("water", 8), ("blood", 8), ("oil", 8)]),
            },
            300,
            ground_y(H, FLOOR),
        )
        .unwrap();
    run(&mut g, 5, &Controls::default());
    let view = g.entities().into_iter().find(|e| e.id == id).unwrap();
    assert_eq!(view.contents, Some(mix(&[("potion_crit", 24)])));
    assert_eq!(
        view.kind, "potion_crit",
        "a bottle of one potion is listed under its key"
    );
}

#[test]
fn mixing_is_deterministic() {
    let run_once = || {
        let mut g = arena_with_recipes(&[RECIPE]);
        g.give_mixed_bottle(&mix(&[("water", 77), ("blood", 31), ("oil", 90)]))
            .unwrap();
        run(&mut g, 40, &Controls::default());
        (contents(&g, 0), g.state_hash())
    };
    assert_eq!(run_once(), run_once());
}

// ----- the entity view -----------------------------------------------------------------------

#[test]
fn a_bottle_on_the_ground_lists_its_contents_and_its_largest_share() {
    let mut g = arena();
    let id = g
        .spawn_item(
            &ItemSpec::MixedBottle {
                contents: mix(&[("oil", 30), ("water", 70)]),
            },
            300,
            ground_y(H, FLOOR),
        )
        .unwrap();
    let e = g.entities().into_iter().find(|e| e.id == id).unwrap();
    assert_eq!(e.kind, "bottle");
    assert_eq!(e.detail, "water");
    assert_eq!(e.contents, Some(mix(&[("water", 70), ("oil", 30)])));
    let single = g
        .spawn_item(
            &ItemSpec::Bottle {
                material: Some("potion_heal".into()),
                amount: Some(10),
            },
            320,
            ground_y(H, FLOOR),
        )
        .unwrap();
    let e = g.entities().into_iter().find(|e| e.id == single).unwrap();
    assert_eq!(
        (e.kind.as_str(), e.detail.as_str()),
        ("potion_heal", "potion_heal")
    );
}

// ----- the summary events are written when the action ends ----------------------------------

#[test]
fn the_drink_event_is_written_on_the_frame_the_bottle_runs_dry() {
    let mut g = arena();
    g.give_bottle(Some("potion_heal"), Some(30)).unwrap();
    run(&mut g, 2, &press(|c| c.drink = true));
    assert_eq!(count(&events(&mut g), "drink"), 0, "still drinking");
    run(&mut g, 1, &press(|c| c.drink = true)); // the third frame empties the bottle
    let ev = events(&mut g);
    let d = ev.iter().find(|(k, _)| k == "drink").expect("written now");
    assert_eq!(int(&d.1, "cells"), 30);
}

#[test]
fn the_pour_event_is_written_on_the_frame_the_bottle_is_empty_and_a_fill_when_it_is_full() {
    let mut g = arena();
    g.give_bottle(Some("oil"), Some(16)).unwrap();
    let pour = press(|c| {
        c.pour = true;
        c.aim = 0.0;
    });
    run(&mut g, 1, &pour);
    assert_eq!(count(&events(&mut g), "pour"), 0);
    run(&mut g, 1, &pour);
    assert_eq!(count(&events(&mut g), "pour"), 1);
    let y = ground_y(H, FLOOR);
    pit(&mut g, 80, 40);
    g.world_mut().fill_rect(80, y - 8, 40, 9, "water").unwrap();
    g.give_bottle(Some("water"), Some(380)).unwrap();
    run(
        &mut g,
        1,
        &press(|c| {
            c.select_bottle = Some(1);
            c.fill = true;
        }),
    );
    let ev = events(&mut g);
    let f = ev
        .iter()
        .find(|(k, _)| k == "fill")
        .expect("full: written now");
    assert_eq!(int(&f.1, "cells"), 20);
}

#[test]
fn ending_the_action_by_hand_writes_the_event_at_once() {
    let mut g = arena();
    g.give_bottle(Some("potion_heal"), None).unwrap();
    run(&mut g, 3, &press(|c| c.drink = true));
    assert_eq!(count(&events(&mut g), "drink"), 0);
    g.end_bottle_action();
    let ev = events(&mut g);
    assert_eq!(
        int(&ev.iter().find(|(k, _)| k == "drink").unwrap().1, "cells"),
        30
    );
    g.end_bottle_action(); // nothing pending: nothing written
    assert_eq!(count(&events(&mut g), "drink"), 0);
    run(&mut g, 1, &Controls::default());
    assert_eq!(
        count(&events(&mut g), "drink"),
        0,
        "and not again when the key is let go"
    );
}

// ----- the cells of a bottle are never made or lost by handling ---------------------------------

/// A small deterministic generator for the handling test below.
struct Lcg(u64);

impl Lcg {
    fn next(&mut self, below: u64) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        (self.0 >> 33) % below
    }
}

const TRACKED: [&str; 4] = ["water", "oil", "blood", "potion_heal"];

/// Cells of the tracked materials in the grid, in carried bottles and in bottles that lie on the
/// ground or fly.
fn tracked_cells(g: &Game) -> u32 {
    let grid: usize = TRACKED.iter().map(|k| count_cells(g, 0, 0, W, H, k)).sum();
    let carried: u32 = g
        .player()
        .unwrap()
        .bottle_contents
        .iter()
        .flatten()
        .map(|(_, n)| n)
        .sum();
    let lying: u32 = g
        .entities()
        .iter()
        .filter_map(|e| e.contents.as_ref())
        .flatten()
        .map(|(_, n)| n)
        .sum();
    grid as u32 + carried + lying
}

fn handling_controls(rng: &mut Lcg) -> Controls {
    hold(|c| {
        c.aim = [0.0, 20.0, 60.0, 180.0, -30.0][rng.next(5) as usize];
        c.move_x = rng.next(3) as i8 - 1;
        match rng.next(9) {
            0 | 1 => c.fill = true,
            2 | 3 => c.pour = true,
            4 => c.drink = true,
            5 => c.throw = true,
            6 => c.interact = true,
            7 => {
                c.drop = Some(cogbench_game::DropItem::Bottle(rng.next(3) as u8));
            }
            _ => {}
        }
        c.select_bottle = Some(rng.next(3) as u8);
    })
}

#[test]
fn handling_bottles_at_random_never_makes_or_loses_a_cell() {
    let (mut all_drunk, mut all_thrown, mut all_dropped) = (0i64, 0i64, 0usize);
    for seed in 1..=6u64 {
        let mut g = arena();
        let y = ground_y(H, FLOOR);
        pit(&mut g, 60, 80);
        g.world_mut().fill_rect(60, y - 4, 80, 5, "water").unwrap();
        g.world_mut().fill_rect(60, y - 6, 80, 2, "oil").unwrap();
        g.world_mut().fill_rect(60, y - 7, 80, 1, "blood").unwrap();
        g.give_mixed_bottle(&mix(&[("water", 120), ("oil", 77), ("potion_heal", 33)]))
            .unwrap();
        g.give_bottle(Some("blood"), Some(250)).unwrap();
        g.give_bottle(None, None).unwrap();
        let start = tracked_cells(&g);
        let mut rng = Lcg(seed);
        let (mut drunk, mut thrown, mut shattered) = (0i64, 0i64, 0i64);
        for _ in 0..500 {
            let c = handling_controls(&mut rng);
            run(&mut g, 1 + rng.next(4) as u32, &c);
            assert!(
                g.player().unwrap().bottles.iter().all(|b| b.1 <= 400),
                "a bottle holds at most its capacity"
            );
        }
        run(&mut g, 1, &Controls::default());
        g.end_bottle_action();
        run(&mut g, 150, &Controls::default()); // everything thrown has landed
        for (kind, fields) in events(&mut g) {
            match kind.as_str() {
                "drink" => drunk += int(&fields, "cells"),
                "throw" => thrown += int(&fields, "cells"),
                "shatter" => shattered += int(&fields, "cells"),
                "drop" => all_dropped += 1,
                _ => {}
            }
        }
        all_drunk += drunk;
        all_thrown += thrown;
        let lost_in_spills = thrown - shattered; // a spill with no room for it
        let now = i64::from(tracked_cells(&g));
        assert_eq!(
            now + drunk + lost_in_spills,
            i64::from(start),
            "seed {seed}: {now} left, {drunk} drunk, {lost_in_spills} lost in spills"
        );
    }
    // the run is only worth something if it did the things it is meant to check
    assert!(all_drunk > 0 && all_thrown > 0 && all_dropped > 0);
}

#[test]
fn a_snapshot_in_the_middle_of_mixing_and_drinking_continues_the_same_way() {
    let mut a = arena_with_recipes(&[RECIPE]);
    a.give_mixed_bottle(&mix(&[("water", 90), ("blood", 70), ("oil", 80)]))
        .unwrap();
    a.give_mixed_bottle(&mix(&[("potion_heal", 200), ("water", 100)]))
        .unwrap();
    a.spawn_item(
        &ItemSpec::MixedBottle {
            contents: mix(&[("water", 50), ("blood", 50), ("oil", 50)]),
        },
        300,
        ground_y(H, FLOOR),
    )
    .unwrap();
    // 7 frames of mixing, a drink of the second bottle under way
    run(
        &mut a,
        7,
        &press(|c| {
            c.select_bottle = Some(1);
            c.drink = true;
        }),
    );
    let blob = a.snapshot().unwrap();
    let hash = a.state_hash();
    let go = |g: &mut Game| {
        run(
            g,
            9,
            &press(|c| {
                c.select_bottle = Some(1);
                c.drink = true;
            }),
        );
        run(g, 30, &Controls::default());
        (g.state_hash(), g.player().unwrap().bottle_contents.clone())
    };
    let first = go(&mut a);
    let mut b = arena_with_recipes(&[RECIPE]);
    b.restore(&blob).unwrap();
    assert_eq!(b.state_hash(), hash);
    assert_eq!(go(&mut b), first);
    // restored a second time into the same game: still the same
    b.restore(&blob).unwrap();
    assert_eq!(go(&mut b), first);
}

#[test]
fn amounts_that_would_wrap_around_are_refused_not_wrapped() {
    let mut g = arena();
    // u32::MAX + 6 wraps to 5 in 32 bits, which would fit a bottle
    assert!(g
        .give_mixed_bottle(&mix(&[("water", u32::MAX), ("oil", 6)]))
        .is_err());
    assert!(g
        .give_mixed_bottle(&mix(&[("water", u32::MAX), ("water", u32::MAX)]))
        .is_err());
    assert!(g.player().unwrap().bottles.is_empty());
    assert!(g
        .spawn_item(
            &ItemSpec::MixedBottle {
                contents: mix(&[("water", u32::MAX), ("oil", 6)]),
            },
            300,
            ground_y(H, FLOOR),
        )
        .is_err());
}
