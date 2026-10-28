//! The predicates and the recipes are true in the simulation: run the original table, and the
//! recipes of many rule seeds, in a `World`.

mod common;
use cogbench_rules::Rules;
use cogbench_sim::{Content, Event, Tuning, Value, World};
use common::*;
use std::sync::Arc;

fn count(w: &World, key: &str) -> usize {
    let m = w.content().mats.index_of(key).expect("material");
    let g = w.grid();
    let mut n = 0;
    for y in 0..w.height() {
        for x in 0..w.width() {
            if g.get(x, y).mat == m {
                n += 1;
            }
        }
    }
    n
}

fn arc(r: &Rules) -> Arc<Content> {
    Arc::new(r.content().clone())
}

#[test]
fn every_lava_solidifier_really_solidifies_lava_in_the_sim() {
    let r = rules();
    for s in r.lava_solidifiers() {
        let mut w = World::new(40, 40, 1, arc(&r)).unwrap();
        w.fill_rect(0, 30, 40, 10, "rock").unwrap();
        w.fill_rect(10, 26, 20, 4, "lava").unwrap();
        w.fill_rect(10, 10, 20, 4, &s.liquid).unwrap();
        let before = count(&w, &s.product);
        w.step_frames(400).unwrap();
        let gained = count(&w, &s.product).saturating_sub(before);
        assert!(
            gained >= 10,
            "{} on lava made only {gained} {} (table said {}%)",
            s.liquid,
            s.product,
            s.probability * 100.0
        );
    }
}

#[test]
fn every_extinguisher_puts_out_a_burning_wood_cell_in_the_sim() {
    let r = rules();
    for e in r.extinguishers() {
        if !e.targets.contains(&"wood".to_string()) {
            continue;
        }
        // a sealed chamber: a burning wood cell at (2, 3) with the extinguisher in the cell over it
        let mut w = World::new(5, 5, 3, arc(&r)).unwrap();
        for (x, y, wd, h) in [
            (0, 1, 1, 4),
            (4, 1, 1, 4),
            (1, 4, 3, 1),
            (1, 3, 1, 1),
            (3, 3, 1, 1),
            (1, 2, 1, 1),
            (3, 2, 1, 1),
        ] {
            w.fill_rect(x, y, wd, h, "rock").unwrap();
        }
        w.fill_rect(2, 3, 1, 1, "wood").unwrap();
        w.fill_rect(2, 2, 1, 1, &e.material).unwrap();
        assert!(w.ignite(2, 3));
        w.step_frames(600).unwrap();
        let doused = w
            .drain_events()
            .iter()
            .any(|ev| matches!(ev, Event::Extinguish { .. }));
        assert!(doused, "{} did not put wood out", e.material);
    }
}

#[test]
fn acid_really_eats_rock_and_is_used_up_in_the_sim() {
    let r = rules();
    let mut w = World::new(20, 12, 1, arc(&r)).unwrap();
    w.fill_rect(0, 8, 20, 4, "rock").unwrap();
    w.fill_rect(5, 6, 10, 2, "acid").unwrap();
    let (rock, acid) = (count(&w, "rock"), count(&w, "acid"));
    w.step_frames(300).unwrap();
    assert!(count(&w, "rock") < rock, "no rock eaten");
    assert!(count(&w, "acid") < acid, "acid not used up");
}

// ----- recipes -----------------------------------------------------------------------------

/// A one-cell-wide shaft with `cells` poured into it: they settle in a column by density, so the
/// middle one touches both others.
fn column_of(content: Arc<Content>, seed: u64, cells: &[&str]) -> World {
    let h = cells.len() as i32 + 3;
    let mut w = World::new(3, h, seed, content).unwrap();
    w.fill_rect(0, 0, 3, h, "rock").unwrap();
    w.fill_rect(1, 0, 1, h - 1, "air").unwrap();
    for (i, key) in cells.iter().enumerate() {
        w.fill_rect(1, 1 + i as i32, 1, 1, key).unwrap();
    }
    w
}

fn mixes(w: &mut World) -> Vec<String> {
    let c = w.content().clone();
    w.drain_events()
        .iter()
        .filter_map(|e| {
            let f = e.fields(&c);
            let is_mix = f
                .iter()
                .any(|(k, v)| *k == "type" && *v == Value::Str("mix".into()));
            is_mix
                .then(|| {
                    f.iter().find_map(|(k, v)| match (*k, v) {
                        ("potion", Value::Str(s)) => Some(s.clone()),
                        _ => None,
                    })
                })
                .flatten()
        })
        .collect()
}

#[test]
fn each_recipe_of_each_seed_makes_its_potion_from_its_three_ingredients() {
    let r = rules();
    for seed in 0..40u64 {
        let content = content_with_recipes(&r, seed);
        for rec in r.recipes(seed).unwrap() {
            let inputs: Vec<&str> = rec.inputs.iter().map(String::as_str).collect();
            let mut w = column_of(content.clone(), seed, &inputs);
            w.step_frames(240).unwrap();
            assert_eq!(
                mixes(&mut w),
                std::slice::from_ref(&rec.potion),
                "seed {seed}: {inputs:?} should make {}",
                rec.potion
            );
            assert_eq!(count(&w, &rec.potion), 3, "seed {seed}: {inputs:?}");
            for k in inputs {
                assert_eq!(count(&w, k), 0, "seed {seed}: {k} left over");
            }
        }
    }
}

#[test]
fn two_ingredients_and_a_stranger_make_nothing() {
    let r = rules();
    let mut tried = 0;
    for seed in 0..40u64 {
        let content = content_with_recipes(&r, seed);
        let recipes = r.recipes(seed).unwrap();
        for rec in &recipes {
            // replace the last ingredient with one that is in no recipe together with the first two
            let strangers: Vec<&str> = [
                "water",
                "blood",
                "oil",
                "whiskey",
                "sand",
                "coal",
                "gold_dust",
            ]
            .into_iter()
            .filter(|k| !rec.inputs.iter().any(|i| i == k))
            .filter(|k| {
                !recipes.iter().any(|o| {
                    [&rec.inputs[0], &rec.inputs[1]]
                        .iter()
                        .all(|i| o.inputs.contains(i))
                        && o.inputs.iter().any(|x| x == k)
                })
            })
            .filter(|k| r.reactions_for(k, false, &rec.inputs[0], false).is_empty())
            .filter(|k| r.reactions_for(k, false, &rec.inputs[1], false).is_empty())
            .collect();
            let Some(stranger) = strangers.first() else {
                continue;
            };
            let mut w = column_of(
                content.clone(),
                seed,
                &[&rec.inputs[0], &rec.inputs[1], stranger],
            );
            w.step_frames(240).unwrap();
            assert!(
                mixes(&mut w).is_empty(),
                "seed {seed}: {:?} + {stranger}",
                &rec.inputs[..2]
            );
            tried += 1;
        }
    }
    assert!(tried >= 200, "only {tried} cases ran");
}

#[test]
fn without_recipes_the_same_column_stays_a_column() {
    // the table alone never makes a potion: the recipes are the only way
    let r = rules();
    let plain = Arc::new(r.content().clone());
    for seed in 0..20u64 {
        for rec in r.recipes(seed).unwrap() {
            let inputs: Vec<&str> = rec.inputs.iter().map(String::as_str).collect();
            let mut w = column_of(plain.clone(), seed, &inputs);
            w.step_frames(240).unwrap();
            assert!(mixes(&mut w).is_empty());
            assert_eq!(count(&w, &rec.potion), 0, "seed {seed}");
        }
    }
}

#[test]
fn recipes_of_other_seeds_do_not_fire() {
    // the recipe book of one seed does not mix the triples of another seed's book
    let r = rules();
    let (a, b) = (r.recipes(1).unwrap(), r.recipes(2).unwrap());
    let book_a: Vec<_> = a.iter().map(|x| x.inputs.clone()).collect();
    let content = Arc::new(r.content().with_recipes(&a).unwrap());
    let mut tried = 0;
    for rec in &b {
        if book_a.contains(&rec.inputs) {
            continue;
        }
        let inputs: Vec<&str> = rec.inputs.iter().map(String::as_str).collect();
        // a triple that also is a recipe of seed 1 might mix; skip those, they are the same triple
        let mut w = column_of(content.clone(), 1, &inputs);
        w.step_frames(240).unwrap();
        assert!(mixes(&mut w).is_empty(), "{inputs:?}");
        tried += 1;
    }
    assert!(tried >= 4, "only {tried} triples differ between the books");
}

#[test]
fn recipes_are_in_the_hash_so_a_snapshot_stays_with_its_book() {
    let r = rules();
    let (h1, h2) = (
        content_with_recipes(&r, 1).hash,
        content_with_recipes(&r, 2).hash,
    );
    assert_ne!(h1, h2);
    assert_ne!(h1, r.content().hash);
    assert_eq!(h1, content_with_recipes(&r, 1).hash);
}

#[test]
fn the_default_tuning_mixes_within_a_second() {
    let r = rules();
    let content = content_with_recipes(&r, 9);
    let rec = &r.recipes(9).unwrap()[0];
    let inputs: Vec<&str> = rec.inputs.iter().map(String::as_str).collect();
    assert_eq!(Tuning::default().recipe_mix_q8, 64);
    for seed in 0..50u64 {
        let mut w = column_of(content.clone(), seed, &inputs);
        w.step_frames(60).unwrap();
        assert_eq!(
            count(&w, &rec.potion),
            3,
            "seed {seed}: not mixed within 60 frames"
        );
    }
}
