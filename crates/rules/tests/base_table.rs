//! The reaction table is the original one for every world; the question API on it.

mod common;
use cogbench_rules::{Outcome, Rules};
use cogbench_sim::Content;
use common::*;

#[test]
fn the_table_is_the_file_byte_for_byte() {
    let r = rules();
    assert_eq!(r.reactions_json(), REACTIONS);
    let embedded = Content::embedded().unwrap();
    assert_eq!(r.content().hash, embedded.hash);
    assert_eq!(r.content().table.ids(), embedded.table.ids());
    assert_eq!(r.content().table.ids().len(), 14);
    assert!(Rules::embedded().unwrap().reactions_json() == REACTIONS);
}

#[test]
fn the_original_table_satisfies_every_invariant() {
    assert_eq!(rules().check_invariants(), vec![]);
}

#[test]
fn no_reaction_row_makes_a_potion_or_names_a_recipe() {
    // potions come from recipes only; the file must not give them away either
    let r = rules();
    let value: serde_json::Value = serde_json::from_str(REACTIONS).unwrap();
    for row in value["reactions"].as_array().unwrap() {
        for field in ["a", "b", "out_a", "out_b"] {
            let key = row[field].as_str().unwrap();
            assert!(!key.starts_with("potion_"), "{} {field}: {key}", row["id"]);
        }
    }
    // the rows themselves name no recipe: the only mention is the note that they are elsewhere
    let rows = value["reactions"].to_string().to_lowercase();
    for word in ["recipe", "ingredient", "secret", "mix"] {
        assert!(!rows.contains(word), "a reaction row mentions {word}");
    }
    assert!(r
        .reactions_for("water", false, "potion_lively", false)
        .is_empty());
}

#[test]
fn transforms_reads_the_expanded_table_in_both_orientations() {
    let r = rules();
    assert_eq!(
        r.transforms("lava", "water"),
        Some(("rock".into(), "steam".into(), 0.8))
    );
    assert_eq!(
        r.transforms("water", "lava"),
        Some(("steam".into(), "rock".into(), 0.8))
    );
    // tag inputs expand: `lava + [burnable]` covers coal; the output keeps lava
    assert_eq!(
        r.transforms("coal", "lava"),
        Some(("fire".into(), "lava".into(), 0.08))
    );
    // water does not touch sand; unknown keys give None
    assert_eq!(r.transforms("water", "sand"), None);
    assert_eq!(r.transforms("nope", "water"), None);
}

#[test]
fn burning_cells_have_their_own_reactions() {
    let r = rules();
    assert!(r.reactions_for("water", false, "wood", false).is_empty());
    let t = r.reactions_for("water", false, "wood", true);
    assert_eq!(t.len(), 1);
    assert_eq!(t[0].out_a, Outcome::Becomes("steam".into()));
    assert_eq!(t[0].out_b, Outcome::Extinguished);
    assert_eq!(t[0].probability, 0.5);
    assert!(t[0].b_burning && !t[0].a_burning);
}

#[test]
fn named_predicates_on_the_original_table() {
    let r = rules();
    let names: Vec<_> = r.lava_solidifiers().into_iter().map(|s| s.liquid).collect();
    assert_eq!(names, ["water", "blood", "toxic_sludge"]);
    assert!(r.water_family_extinguishes());
    let ext = r.extinguishers();
    let water = ext.iter().find(|e| e.material == "water").unwrap();
    assert!(water.targets.contains(&"wood".to_string()));
    assert!(water.targets.contains(&"oil".to_string()));
    assert_eq!(r.acid_dissolves("rock"), Some(0.5));
    assert_eq!(r.acid_dissolves("brick"), None, "brick is not corrodible");
    assert_eq!(
        r.acid_dissolves("metal"),
        None,
        "the alchemy bowl is not corrodible"
    );
    assert_eq!(r.ignites("lava", "oil"), Some(0.08));
    assert_eq!(r.ignites("fire", "flammable_gas"), Some(0.4));
    assert_eq!(r.ignites("water", "oil"), None);
}

#[test]
fn the_new_ingredients_react_with_nothing_in_the_table() {
    let r = rules();
    for new in ["gold_dust", "bone_dust", "fungus_powder", "slime", "metal"] {
        for other in [
            "water",
            "blood",
            "oil",
            "whiskey",
            "toxic_sludge",
            "sand",
            "coal",
            "gunpowder",
        ] {
            assert!(
                r.reactions_for(new, false, other, false).is_empty(),
                "{new} + {other}"
            );
        }
    }
}

#[test]
fn a_missing_core_material_is_reported() {
    let renamed = MATERIALS.replacen("\"key\": \"flammable_gas\"", "\"key\": \"marsh_gas\"", 1);
    // the reactions name flammable_gas too, so the table does not even load
    assert!(Rules::new(&renamed, REACTIONS).is_err());
    assert!(Rules::new(MATERIALS, "{").is_err());
}
