//! Reactions: `RXN-R02..R08`, `RXN-R17`, `RXN-R18`, vectors `MV-05`, `MV-07`, `MV-08`, `MV-23`,
//! plus the extinguishing row of this project.

mod common;
use cogbench_sim::{Content, ReactionDef, ReactionTable, Tuning, Value, World};
use common::*;

fn fired(world: &mut World, ty: &str, max: u32) -> Vec<Vec<(&'static str, Value)>> {
    let c = world.content().clone();
    of_type(&step_until(world, ty, max), &c, ty)
}

fn def(id: &str, a: &str, b: &str, out_a: &str, out_b: &str, probability: f64) -> ReactionDef {
    ReactionDef {
        id: id.into(),
        a: a.into(),
        b: b.into(),
        out_a: out_a.into(),
        out_b: out_b.into(),
        probability,
        source: String::new(),
    }
}

#[test]
fn mv_05_outputs_are_positional_the_fire_stays_the_water_boils() {
    // [fire] + water -> [fire] + steam, with the real table. Fire above water in a 1-wide shaft.
    let mut found = 0;
    for seed in 0..60 {
        let mut w = scene(&["F", "W", "#"], forced_reactive(), seed);
        let evs = fired(&mut w, "reaction", 5);
        if let Some(e) = evs.first() {
            assert_eq!(text(e, "id"), "r03");
            assert_eq!(
                (int(e, "x"), int(e, "y")),
                (0, 0),
                "role a is the fire cell"
            );
            assert_eq!((int(e, "bx"), int(e, "by")), (0, 1));
            assert_eq!(rows(&w)[0], "F");
            assert_eq!(rows(&w)[1], "G");
            found += 1;
        }
    }
    assert!(found > 3, "the reaction must fire in some runs ({found})");
}

#[test]
fn rxn_r07_tag_output_keeps_the_matched_material() {
    // steam + [static] -> water + [static]; with wood as the static the wood must stay wood.
    let c = custom_table(
        Tuning::forced(),
        &[("t", "steam", "[static]", "water", "[static]", 1.0)],
    );
    let mut w = scene(&["w", "G", "."], c, 1);
    let evs = fired(&mut w, "reaction", 50);
    assert_eq!(evs.len(), 1);
    assert_eq!(rows(&w)[0], "w");
    assert!(rows(&w).iter().any(|r| r == "W"));
}

#[test]
fn rxn_r07_tag_output_may_name_the_other_slot() {
    // r10 is literal: whiskey + [fire] -> [fire] + flammable gas. The whiskey cell becomes the
    // fire material, the fire cell becomes gas.
    let c = custom_table(
        Tuning::forced(),
        &[("t", "whiskey", "[fire]", "[fire]", "flammable_gas", 1.0)],
    );
    let mut w = scene(&["F", "H", "#"], c, 1);
    let evs = fired(&mut w, "reaction", 50);
    assert_eq!(evs.len(), 1);
    assert_eq!(
        &rows(&w)[..2],
        &["f".to_string(), "F".to_string()],
        "top was the fire cell"
    );
}

#[test]
fn rxn_r09_burning_matches_any_burning_cell_and_extinguish_clears_it() {
    // r14: [water_family] + @burning -> steam + @extinguish
    let mut w = scene(&["W", "w", "#"], forced_reactive(), 11);
    assert!(w.ignite(0, 1));
    let evs = fired(&mut w, "extinguish", 400);
    assert_eq!(evs.len(), 1, "the burning wood must be put out");
    assert_eq!(text(&evs[0], "material"), "wood");
    assert!(!w.grid().get(0, 1).burning());
    assert_eq!(
        w.grid().get(0, 1).mat,
        w.content().mats.index_of("wood").unwrap()
    );
    assert_eq!(
        w.grid().get(0, 0).mat,
        w.content().mats.index_of("steam").unwrap()
    );
}

#[test]
fn rxn_r09_unlit_wood_does_not_react_with_water() {
    let mut w = scene(&["W", "w", "#"], forced_reactive(), 11);
    w.step_frames(300).unwrap();
    assert_eq!(&rows(&w)[..2], &["W".to_string(), "w".to_string()]);
}

#[test]
fn mv_23_water_on_lava_makes_rock_and_steam() {
    let c = content(Tuning::default());
    let mut w = World::new(40, 40, 3, c).unwrap();
    w.fill_rect(0, 30, 40, 10, "rock").unwrap();
    w.fill_rect(10, 26, 20, 4, "lava").unwrap();
    w.fill_rect(10, 10, 20, 4, "water").unwrap();
    let (lava, water) = (count(&w, "lava"), count(&w, "water"));
    w.step_frames(300).unwrap();
    assert!(count(&w, "rock") > 400 + 10, "lava must cool into rock");
    assert!(count(&w, "lava") < lava && count(&w, "water") < water);
}

#[test]
fn mv_07_candidates_are_tried_in_file_order_first_success_wins() {
    // Two rows for the same pair, 20 % then 80 %: given that something fires, the first row is
    // chosen with 0.2 / (0.2 + 0.8 * 0.8).
    let c = custom_table(
        Tuning::forced(),
        &[
            ("first", "sand", "coal", "sand", "water", 0.2),
            ("second", "sand", "coal", "sand", "blood", 0.8),
        ],
    );
    let (mut first, mut second) = (0u32, 0u32);
    for seed in 0..30_000u64 {
        let mut w = scene(&["S", "c", "#"], c.clone(), seed);
        w.step().unwrap();
        for e in of_type(&w.drain_events(), &c, "reaction") {
            if text(&e, "id") == "first" {
                first += 1;
            } else {
                second += 1;
            }
        }
    }
    let share = f64::from(first) / f64::from(first + second);
    assert!(
        (share - 0.2 / 0.84).abs() < 0.02,
        "first row share {share} ({first}/{second})"
    );
}

#[test]
fn mv_08_probability_thresholds_are_hundredths_of_a_percent() {
    let c = custom_table(
        Tuning::forced(),
        &[
            ("p03", "sand", "coal", "sand", "coal", 0.003),
            ("p70", "sand", "water", "sand", "water", 0.7),
            ("p100", "sand", "blood", "sand", "blood", 1.0),
            ("p0", "sand", "oil", "sand", "oil", 0.0),
        ],
    );
    let id = |k: &str| c.mats.index_of(k).unwrap();
    let t = |a: &str, b: &str| c.table.candidates(id(a), id(b))[0].threshold;
    assert_eq!(
        (
            t("sand", "coal"),
            t("sand", "water"),
            t("sand", "blood"),
            t("sand", "oil")
        ),
        (30, 7000, 10000, 0)
    );
}

#[test]
fn rxn_r02_pairs_are_matched_in_both_directions() {
    let c = content(Tuning::default());
    let id = |k: &str| c.mats.index_of(k).unwrap();
    let forward = c.table.candidates(id("lava"), id("water"));
    let backward = c.table.candidates(id("water"), id("lava"));
    assert!(forward[0].visited_is_a && !backward[0].visited_is_a);
    assert_eq!(c.table.ids()[usize::from(forward[0].row)], "r01");
}

#[test]
fn rxn_r06_tag_inputs_expand_over_all_members() {
    let c = content(Tuning::default());
    let id = |k: &str| c.mats.index_of(k).unwrap();
    let has_row = |a: &str, b: &str, row: &str| {
        c.table
            .candidates(id(a), id(b))
            .iter()
            .any(|cand| c.table.ids()[usize::from(cand.row)] == row)
    };
    // r05: lava + [burnable] covers oil, whiskey, coal, wood but not sand.
    for k in ["oil", "whiskey", "coal", "wood"] {
        assert!(has_row("lava", k, "r05"), "{k}");
    }
    assert!(!has_row("lava", "sand", "r05"));
    assert!(
        c.table.is_reactive(id("rock")),
        "rock is a partner of acid and steam"
    );
    // `@burning` matches every material, so every material but air is a (conditional) partner.
    assert!(c.table.is_reactive(id("brick")) && !c.table.is_reactive(0));
}

#[test]
fn rxn_r18_bad_tables_fail_loudly_with_file_and_field() {
    let content = Content::embedded().unwrap();
    let bad = |a: &str, b: &str, oa: &str, ob: &str, p: f64| {
        ReactionTable::compile(
            "reactions.json",
            &content.mats,
            &[def("x", a, b, oa, ob, p)],
        )
        .unwrap_err()
        .to_string()
    };
    assert!(bad("nonsense", "water", "water", "water", 0.5).contains("unknown material `nonsense`"));
    assert!(bad("[nope]", "water", "water", "water", 0.5).contains("unknown tag `[nope]`"));
    assert!(bad("air", "water", "water", "water", 0.5).contains("air cannot be a reaction input"));
    assert!(bad("sand", "water", "sand", "water", 1.5).contains("probability"));
    assert!(bad("sand", "water", "[static]", "water", 0.5).contains("no matching"));
    assert!(bad("sand", "water", "@extinguish", "water", 0.5).contains("@burning"));
    let msg = bad("sand", "water", "sand", "mud", 0.5);
    assert!(
        msg.starts_with("reactions.json: field `reactions[0].out_b (x)`"),
        "{msg}"
    );
}

#[test]
fn rxn_r18_duplicate_row_ids_are_rejected() {
    let content = Content::embedded().unwrap();
    let d = def("dup", "sand", "water", "sand", "water", 0.5);
    let err = ReactionTable::compile("r.json", &content.mats, &[d.clone(), d])
        .unwrap_err()
        .to_string();
    assert!(err.contains("duplicate id `dup`"), "{err}");
}

#[test]
fn rxn_r09_same_material_on_both_sides_keeps_both_roles_when_only_one_must_burn() {
    // oil + @burning -> oil + @extinguish: burning oil beside plain oil, and the other way round,
    // are different situations, so the table must hold a candidate for each role.
    let c = custom_table(
        Tuning::forced(),
        &[("t", "oil", "@burning", "oil", "@extinguish", 1.0)],
    );
    let oil = c.mats.index_of("oil").unwrap();
    let cands = c.table.candidates(oil, oil);
    assert_eq!(cands.len(), 2);
    assert!(cands[0].visited_is_a && !cands[0].visited_must_burn && cands[0].other_must_burn);
    assert!(!cands[1].visited_is_a && cands[1].visited_must_burn && !cands[1].other_must_burn);
    // And both fire: a burning oil cell on top is put out whichever of the two is visited.
    let mut w = scene(&["O", "O", "#"], c, 1);
    assert!(w.ignite(0, 0));
    let evs = fired(&mut w, "extinguish", 5);
    assert_eq!(evs.len(), 1);
    assert!(!w.grid().get(0, 0).burning());
}

#[test]
fn r04_one_acid_cell_dissolves_exactly_one_cell_and_is_used_up() {
    // Acid between brick (not corrodible) and ground: it corrodes the ground cell, turns into
    // flammable gas itself, and the ground cell becomes air.
    let mut w = scene(&["BBB", "BAB", "BDB", "BBB"], forced_reactive(), 5);
    let c = w.content().clone();
    w.step_frames(300).unwrap();
    assert_eq!(count(&w, "acid"), 0, "the acid is consumed");
    assert_eq!(count(&w, "ground"), 0, "and so is the cell it ate");
    assert_eq!(count(&w, "flammable_gas"), 1);
    assert_eq!(count(&w, "brick"), 10, "brick is not corrodible");
    let rows = of_type(&w.drain_events(), &c, "reaction");
    assert_eq!(rows.len(), 1);
    assert_eq!(text(&rows[0], "id"), "r04");
}

#[test]
fn r04_a_fixed_amount_of_acid_dissolves_a_bounded_amount_of_ground_and_then_stops() {
    // 30 acid cells on a thick bed of ground inside a brick vessel with an open top. Each
    // reaction uses up one acid cell and one ground cell, so exactly 30 ground cells go, however
    // long we wait.
    for seed in [1, 2, 3] {
        let mut w = World::new(24, 40, seed, content(Tuning::default())).unwrap();
        w.fill_rect(0, 20, 24, 20, "brick").unwrap();
        w.fill_rect(0, 0, 1, 20, "brick").unwrap();
        w.fill_rect(23, 0, 1, 20, "brick").unwrap();
        w.fill_rect(1, 24, 22, 15, "ground").unwrap();
        w.fill_rect(1, 20, 22, 4, "air").unwrap();
        w.fill_rect(6, 21, 10, 3, "acid").unwrap();
        let (acid0, ground0, brick0) = (count(&w, "acid"), count(&w, "ground"), count(&w, "brick"));
        assert_eq!(acid0, 30);
        w.step_frames(4000).unwrap();
        assert_eq!(count(&w, "acid"), 0, "seed {seed}: all the acid is used up");
        assert_eq!(count(&w, "ground"), ground0 - acid0, "seed {seed}");
        assert_eq!(
            count(&w, "brick"),
            brick0,
            "seed {seed}: brick is not corrodible"
        );
    }
}
