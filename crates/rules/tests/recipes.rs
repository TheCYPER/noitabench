//! The recipes of a rule seed: constraints, determinism and spread over many seeds.

mod common;
use cogbench_rules::{
    recipes_embedded, Error, Rules, INGREDIENT_TAG, MAX_USES_PER_INGREDIENT, SECRET_POTION_TAG,
};
use common::*;
use std::collections::{BTreeMap, BTreeSet};

fn keys_with_tag(r: &Rules, tag: &str) -> Vec<String> {
    let mats = &r.content().mats;
    mats.with_tag(tag)
        .unwrap()
        .iter()
        .map(|&i| mats.key_of(i).to_string())
        .collect()
}

#[test]
fn the_pool_and_the_potions_are_the_ones_of_the_design() {
    let r = rules();
    assert_eq!(
        keys_with_tag(&r, INGREDIENT_TAG),
        [
            "water",
            "blood",
            "oil",
            "whiskey",
            "toxic_sludge",
            "sand",
            "coal",
            "gunpowder",
            "gold_dust",
            "bone_dust",
            "fungus_powder",
            "slime"
        ]
    );
    assert_eq!(
        keys_with_tag(&r, SECRET_POTION_TAG),
        [
            "potion_lively",
            "potion_invulnerable",
            "potion_mana_regen",
            "potion_crit",
            "potion_berserk",
            "potion_levitation",
            "potion_invisible",
            "potion_fireproof"
        ]
    );
}

#[test]
fn every_seed_gives_eight_valid_recipes() {
    let r = rules();
    let pool = keys_with_tag(&r, INGREDIENT_TAG);
    let potions = keys_with_tag(&r, SECRET_POTION_TAG);
    for seed in 0..3000u64 {
        let recipes = r.recipes(seed).unwrap();
        assert_eq!(recipes.len(), 8, "seed {seed}");
        let named: Vec<_> = recipes.iter().map(|x| x.potion.clone()).collect();
        assert_eq!(
            named, potions,
            "seed {seed}: one recipe per potion, in order"
        );

        let mut sets = BTreeSet::new();
        let mut uses: BTreeMap<&str, usize> = BTreeMap::new();
        for rec in &recipes {
            let mut idx: Vec<u8> = Vec::new();
            for key in &rec.inputs {
                assert!(
                    pool.contains(key),
                    "seed {seed}: {key} is not an ingredient"
                );
                idx.push(r.content().mats.index_of(key).unwrap());
                *uses.entry(key).or_default() += 1;
            }
            assert!(
                idx.windows(2).all(|w| w[0] < w[1]),
                "ordered, distinct: {rec:?}"
            );
            for i in 0..3 {
                for j in i + 1..3 {
                    assert!(
                        r.reactions_for(&rec.inputs[i], false, &rec.inputs[j], false)
                            .is_empty(),
                        "seed {seed}: {} and {} react",
                        rec.inputs[i],
                        rec.inputs[j]
                    );
                }
            }
            assert!(
                sets.insert(rec.inputs.clone()),
                "seed {seed}: duplicate set"
            );
        }
        assert!(
            uses.values().all(|&n| n <= MAX_USES_PER_INGREDIENT),
            "seed {seed}: {uses:?}"
        );
    }
}

#[test]
fn the_recipes_are_a_pure_function_of_the_rule_seed() {
    let (a, b) = (rules(), rules());
    for seed in [0u64, 1, 42, 0xdead_beef, u64::MAX] {
        assert_eq!(a.recipes(seed).unwrap(), b.recipes(seed).unwrap());
        assert_eq!(a.recipes(seed).unwrap(), recipes_embedded(seed).unwrap());
    }
    // asking about other seeds in between changes nothing
    let first = a.recipes(5).unwrap();
    for s in 100..120 {
        let _ = a.recipes(s).unwrap();
    }
    assert_eq!(a.recipes(5).unwrap(), first);
}

#[test]
fn seeds_give_different_recipe_books_and_every_ingredient_gets_used() {
    let r = rules();
    let mut books = BTreeSet::new();
    let mut first_potion = BTreeSet::new();
    let mut used = BTreeSet::new();
    for seed in 0..500u64 {
        let recipes = r.recipes(seed).unwrap();
        first_potion.insert(recipes[0].inputs.clone());
        for rec in &recipes {
            used.extend(rec.inputs.iter().cloned());
        }
        books.insert(recipes);
    }
    assert_eq!(books.len(), 500, "two of 500 seeds drew the same book");
    assert!(
        first_potion.len() > 100,
        "{} lively recipes",
        first_potion.len()
    );
    assert_eq!(used.len(), 12);
}

#[test]
fn ingredient_frequencies_are_even_enough() {
    // 8 recipes x 3 slots over 12 ingredients: 2 each on average, never more than 3
    let r = rules();
    let mut count: BTreeMap<String, usize> = BTreeMap::new();
    let seeds = 2000u64;
    for seed in 0..seeds {
        for rec in r.recipes(seed).unwrap() {
            for k in rec.inputs {
                *count.entry(k).or_default() += 1;
            }
        }
    }
    let mean = (seeds * 24) as f64 / 12.0;
    for (k, n) in &count {
        let share = *n as f64 / mean;
        assert!(
            (0.8..1.2).contains(&share),
            "{k} appears {n} times (mean {mean})"
        );
    }
}

#[test]
fn the_recipes_load_in_the_simulation() {
    let r = rules();
    for seed in 0..300u64 {
        let c = content_with_recipes(&r, seed);
        assert_eq!(c.recipes.len(), 8);
        assert_eq!(c.table.ids().len(), 14, "the table is untouched");
    }
}

#[test]
fn bad_materials_say_what_is_missing() {
    // no ingredient tag at all
    let none = MATERIALS.replace("\"ingredient\"", "\"stuff\"");
    let r = Rules::new(&none, REACTIONS).unwrap();
    let err = r.recipes(1).unwrap_err();
    assert!(matches!(err, Error::MissingMaterial(_)), "{err}");
    // too many potions for the ingredients: 4 ingredients cannot carry 8 recipes
    let mut value: serde_json::Value = serde_json::from_str(MATERIALS).unwrap();
    for m in value["materials"].as_array_mut().unwrap() {
        let drop = matches!(
            m["key"].as_str(),
            Some(
                "gold_dust"
                    | "bone_dust"
                    | "fungus_powder"
                    | "slime"
                    | "coal"
                    | "sand"
                    | "gunpowder"
                    | "whiskey"
            )
        );
        if drop {
            m["tags"]
                .as_array_mut()
                .unwrap()
                .retain(|t| t != "ingredient");
        }
    }
    let r = Rules::new(&value.to_string(), REACTIONS).unwrap();
    let err = r.recipes(1).unwrap_err();
    assert!(matches!(err, Error::Recipes { .. }), "{err}");
    assert!(err.to_string().contains("ingredient slots"), "{err}");
}
