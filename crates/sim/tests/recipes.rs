//! Secret recipes: three ingredients that meet become a potion (`recipe.rs`,
//! `rules/recipe_mix.rs`), and the `metal` of the alchemy bowl.

mod common;
use cogbench_sim::{
    Content, DirtyMode, ExplosionSpec, RecipeDef, Tuning, Value, World, MAX_RECIPES,
};
use std::sync::Arc;

fn recipe(potion: &str, inputs: [&str; 3]) -> RecipeDef {
    RecipeDef {
        potion: potion.to_string(),
        inputs: inputs.map(str::to_string),
    }
}

/// Test configuration T (no randomness in motion, mixing certain), no reactions, these recipes.
fn forced_with(recipes: &[RecipeDef]) -> Arc<Content> {
    let base = Content::embedded_with(Tuning::forced())
        .and_then(|c| c.with_table(&[]))
        .expect("embedded content is valid");
    Arc::new(base.with_recipes(recipes).expect("recipes are valid"))
}

fn lively_of(inputs: [&str; 3]) -> RecipeDef {
    recipe("potion_lively", inputs)
}

fn mat(w: &World, x: i32, y: i32) -> String {
    w.content().mats.key_of(w.grid().get(x, y).mat).to_string()
}

/// A shaft `inside` cells wide and `height` tall with rock all around it.
fn shaft(content: Arc<Content>, inside: i32, height: i32) -> World {
    let mut w = World::new(inside + 2, height + 1, 7, content).unwrap();
    w.fill_rect(0, 0, inside + 2, height + 1, "rock").unwrap();
    w.fill_rect(1, 0, inside, height, "air").unwrap();
    w
}

fn mix_events(w: &mut World) -> Vec<String> {
    let c = w.content().clone();
    w.drain_events()
        .iter()
        .map(|e| e.fields(&c))
        .filter(|f| {
            f.iter()
                .any(|(k, v)| *k == "type" && *v == Value::Str("mix".into()))
        })
        .filter_map(|f| {
            f.iter().find_map(|(k, v)| match (*k, v) {
                ("potion", Value::Str(s)) => Some(s.clone()),
                _ => None,
            })
        })
        .collect()
}

// ----- compiling ----------------------------------------------------------------------------

#[test]
fn recipes_are_validated_with_the_field_that_is_wrong() {
    let base = Content::embedded().unwrap();
    let err = |defs: &[RecipeDef]| base.with_recipes(defs).unwrap_err().to_string();
    assert!(err(&[lively_of(["water", "sand", "mercury"])]).contains("recipes[0].inputs"));
    assert!(err(&[lively_of(["water", "sand", "rock"])]).contains("liquid or a powder"));
    assert!(err(&[lively_of(["water", "air", "sand"])]).contains("liquid or a powder"));
    assert!(err(&[lively_of(["water", "sand", "sand"])]).contains("must differ"));
    assert!(err(&[lively_of(["water", "sand", "potion_lively"])]).contains("own ingredients"));
    assert!(err(&[recipe("rock", ["water", "sand", "coal"])]).contains("recipes[0].potion"));
    assert!(err(&[
        lively_of(["water", "sand", "coal"]),
        recipe("potion_crit", ["coal", "water", "sand"]),
    ])
    .contains("recipes[1].inputs"));
    let keys = [
        "water",
        "blood",
        "oil",
        "whiskey",
        "sand",
        "coal",
        "gunpowder",
    ];
    let mut many = Vec::new();
    'all: for a in 0..keys.len() {
        for b in a + 1..keys.len() {
            for c in b + 1..keys.len() {
                many.push(lively_of([keys[a], keys[b], keys[c]]));
                if many.len() > MAX_RECIPES {
                    break 'all;
                }
            }
        }
    }
    assert!(err(&many).contains("at most"));
}

#[test]
fn recipes_do_not_touch_the_reaction_table_and_change_the_hash() {
    let base = Content::embedded().unwrap();
    let with = base
        .with_recipes(&[lively_of(["water", "sand", "coal"])])
        .unwrap();
    assert_eq!(with.table.ids(), base.table.ids());
    assert_ne!(with.hash, base.hash);
    let other = base
        .with_recipes(&[lively_of(["water", "sand", "oil"])])
        .unwrap();
    assert_ne!(with.hash, other.hash);
    // attaching nothing is the same as never attaching: the hash is the embedded content's
    assert_eq!(base.with_recipes(&[]).unwrap().hash, base.hash);
    // the recipes survive a swap of the reaction table
    let swapped = with.with_table(&[]).unwrap();
    assert_eq!(swapped.recipes.len(), 1);
    assert_ne!(swapped.hash, base.hash);
    assert_eq!(swapped.recipe_defs(), with.recipe_defs());
}

#[test]
fn only_ingredients_of_a_recipe_are_marked() {
    let c = Content::embedded()
        .unwrap()
        .with_recipes(&[
            lively_of(["water", "sand", "coal"]),
            recipe("potion_crit", ["sand", "oil", "slime"]),
        ])
        .unwrap();
    let mask = |k: &str| c.mats.rt(c.mats.index_of(k).unwrap()).ingredient_of;
    assert_eq!(mask("water"), 0b01);
    assert_eq!(mask("coal"), 0b01);
    assert_eq!(mask("sand"), 0b11);
    assert_eq!(mask("oil"), 0b10);
    assert_eq!(mask("slime"), 0b10);
    assert_eq!(mask("blood"), 0);
    assert_eq!(mask("potion_lively"), 0);
}

// ----- mixing -------------------------------------------------------------------------------

#[test]
fn three_touching_ingredients_turn_into_the_potion() {
    let c = forced_with(&[lively_of(["coal", "sand", "gold_dust"])]);
    // rock walls on both sides keep the piles from sliding
    let mut w = shaft(c, 3, 4);
    w.fill_rect(1, 3, 1, 1, "rock").unwrap(); // (1,3) is a ledge
    w.paint(2, 3, 0, "coal").unwrap();
    w.paint(3, 3, 0, "sand").unwrap();
    w.paint(2, 2, 0, "gold_dust").unwrap();
    w.step().unwrap();
    for (x, y) in [(2, 3), (3, 3), (2, 2)] {
        assert_eq!(mat(&w, x, y), "potion_lively", "cell ({x}, {y})");
    }
    assert_eq!(mix_events(&mut w), ["potion_lively"], "one event per mix");
}

#[test]
fn two_of_the_three_do_nothing_and_let_the_world_sleep() {
    let c = forced_with(&[lively_of(["coal", "sand", "gold_dust"])]);
    let mut w = shaft(c, 3, 4);
    w.fill_rect(1, 3, 1, 1, "rock").unwrap();
    w.paint(2, 3, 0, "coal").unwrap();
    w.paint(3, 3, 0, "sand").unwrap();
    w.step_frames(60).unwrap();
    assert_eq!(
        (mat(&w, 2, 3), mat(&w, 3, 3)),
        ("coal".into(), "sand".into())
    );
    assert!(mix_events(&mut w).is_empty());
    let (cw, ch) = w.grid().chunk_dims();
    assert!(
        (0..ch).all(|cy| (0..cw).all(|cx| w.grid().dirty_rect(cx, cy).is_empty())),
        "a partial recipe must not keep the chunk awake"
    );
    // the third ingredient arrives: it wakes the area and the mix happens
    w.paint(2, 2, 0, "gold_dust").unwrap();
    w.step().unwrap();
    assert_eq!(mat(&w, 2, 3), "potion_lively");
}

#[test]
fn the_wrong_third_ingredient_does_nothing() {
    let c = forced_with(&[lively_of(["coal", "sand", "gold_dust"])]);
    let mut w = shaft(c, 3, 4);
    w.fill_rect(1, 3, 1, 1, "rock").unwrap();
    w.paint(2, 3, 0, "coal").unwrap();
    w.paint(3, 3, 0, "sand").unwrap();
    w.paint(2, 2, 0, "bone_dust").unwrap();
    w.step_frames(30).unwrap();
    assert_eq!(mat(&w, 2, 2), "bone_dust");
    assert!(mix_events(&mut w).is_empty());
}

#[test]
fn layers_mix_across_a_thick_middle_up_to_the_reach() {
    // oil floats on water floats on blood: the water layer touches both, but only one at a time
    let c = forced_with(&[lively_of(["oil", "water", "blood"])]);
    for (thickness, mixes) in [(1, true), (4, true), (6, true), (7, false), (9, false)] {
        let mut w = shaft(c.clone(), 1, 12);
        let h = 12;
        w.fill_rect(1, h - 2, 1, 2, "blood").unwrap();
        w.fill_rect(1, h - 2 - thickness, 1, thickness, "water")
            .unwrap();
        w.fill_rect(1, h - 4 - thickness, 1, 2, "oil").unwrap();
        w.step_frames(40).unwrap();
        let made = (0..h).filter(|&y| mat(&w, 1, y) == "potion_lively").count();
        assert_eq!(
            made > 0,
            mixes,
            "water layer {thickness} cells thick: {made} potion cells"
        );
        assert_eq!(made % 3, 0, "potion cells come three at a time");
    }
}

#[test]
fn a_cell_in_the_middle_of_a_lake_does_not_look() {
    // the contact rule keeps lakes cheap: no contact, no scan, no change, and the chunk sleeps
    let c = forced_with(&[lively_of(["oil", "water", "blood"])]);
    let mut w = shaft(c, 6, 6);
    w.fill_rect(1, 2, 6, 4, "water").unwrap();
    w.step_frames(20).unwrap();
    assert!(mix_events(&mut w).is_empty());
    let (cw, ch) = w.grid().chunk_dims();
    assert!((0..ch).all(|cy| (0..cw).all(|cx| w.grid().dirty_rect(cx, cy).is_empty())));
}

#[test]
fn the_chance_per_visit_is_the_tuning_knob() {
    // default tuning: 64/256 per visit; only the coal cell sees both others in this L
    let tuning = Tuning::default();
    assert_eq!(tuning.recipe_mix_q8, 64);
    let base = Content::embedded_with(Tuning {
        // keep motion exact so the L stays an L
        single_fall_step: true,
        ..tuning
    })
    .and_then(|c| c.with_table(&[]))
    .unwrap();
    let c = Arc::new(
        base.with_recipes(&[lively_of(["coal", "sand", "gold_dust"])])
            .unwrap(),
    );
    let trials = 4000u64;
    let mut converted = 0;
    for seed in 0..trials {
        let mut w = World::new(5, 5, seed, c.clone()).unwrap();
        w.fill_rect(0, 0, 5, 5, "rock").unwrap();
        w.fill_rect(2, 1, 2, 3, "air").unwrap();
        w.paint(2, 3, 0, "coal").unwrap();
        w.paint(3, 3, 0, "sand").unwrap();
        w.paint(2, 2, 0, "gold_dust").unwrap();
        w.step().unwrap();
        if mat(&w, 2, 3) == "potion_lively" {
            converted += 1;
        }
    }
    let p = f64::from(converted) / trials as f64;
    assert!(
        (p - 0.25).abs() < 0.03,
        "converted {converted} of {trials}: {p}"
    );
}

#[test]
fn a_cell_that_sees_a_whole_recipe_stays_awake_until_it_mixes() {
    let tuning = Tuning {
        recipe_mix_q8: 8, // rare, so the cells wait a while
        ..Tuning::forced()
    };
    let base = Content::embedded_with(tuning)
        .and_then(|c| c.with_table(&[]))
        .unwrap();
    let c = Arc::new(
        base.with_recipes(&[lively_of(["coal", "sand", "gold_dust"])])
            .unwrap(),
    );
    let mut w = shaft(c, 3, 4);
    w.fill_rect(1, 3, 1, 1, "rock").unwrap();
    w.paint(2, 3, 0, "coal").unwrap();
    w.paint(3, 3, 0, "sand").unwrap();
    w.paint(2, 2, 0, "gold_dust").unwrap();
    for f in 0..2000 {
        if mat(&w, 2, 3) == "potion_lively" {
            assert!(f > 1, "with a 1 in 32 chance the first visit rarely wins");
            return;
        }
        w.step().unwrap();
    }
    panic!("the three ingredients never mixed");
}

#[test]
fn dirty_rectangles_do_not_change_what_mixes() {
    // a bowl with layered liquids and powders, run with the normal wake rules and with every
    // cell awake: the grids are equal after every frame (SIM-R72)
    let c = Arc::new(
        Content::embedded()
            .unwrap()
            .with_recipes(&[
                lively_of(["oil", "water", "blood"]),
                recipe("potion_crit", ["sand", "water", "slime"]),
                recipe("potion_berserk", ["coal", "oil", "bone_dust"]),
            ])
            .unwrap(),
    );
    let build = |mode| {
        let mut w = World::new(40, 40, 11, c.clone()).unwrap();
        w.fill_rect(0, 30, 40, 10, "rock").unwrap();
        w.fill_rect(8, 20, 24, 10, "air").unwrap();
        w.fill_rect(5, 18, 3, 12, "metal").unwrap();
        w.fill_rect(32, 18, 3, 12, "metal").unwrap();
        w.fill_rect(8, 26, 24, 4, "blood").unwrap();
        w.fill_rect(8, 23, 24, 3, "water").unwrap();
        w.fill_rect(8, 21, 24, 2, "oil").unwrap();
        w.fill_rect(12, 14, 8, 3, "sand").unwrap();
        w.fill_rect(22, 14, 6, 3, "slime").unwrap();
        w.set_dirty_mode(mode);
        w
    };
    let (mut a, mut b) = (build(DirtyMode::Normal), build(DirtyMode::AllDirty));
    let mut mixed = false;
    for f in 0..240 {
        a.step().unwrap();
        b.step().unwrap();
        assert_eq!(a.grid().cells(), b.grid().cells(), "frame {f}");
        mixed |= !mix_events(&mut a).is_empty();
    }
    assert!(mixed, "the scene should make some potion");
    assert_eq!(a.state_hash(), b.state_hash());
}

/// Twelve ingredients, eight recipes: what a real rule seed hands the simulation.
fn book() -> Vec<RecipeDef> {
    vec![
        recipe("potion_lively", ["gunpowder", "fungus_powder", "slime"]),
        recipe("potion_invulnerable", ["whiskey", "sand", "slime"]),
        recipe("potion_mana_regen", ["blood", "oil", "gold_dust"]),
        recipe("potion_crit", ["blood", "whiskey", "fungus_powder"]),
        recipe("potion_berserk", ["bone_dust", "fungus_powder", "slime"]),
        recipe("potion_levitation", ["blood", "gunpowder", "gold_dust"]),
        recipe("potion_invisible", ["oil", "whiskey", "toxic_sludge"]),
        recipe("potion_fireproof", ["oil", "sand", "bone_dust"]),
    ]
}

const POOL: [&str; 12] = [
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
    "slime",
];

/// A walled box with random walls and random blobs of the twelve ingredients (a tiny LCG keeps
/// the layout a function of `seed`).
fn random_box(content: &Arc<Content>, seed: u64, mode: DirtyMode) -> World {
    let (w, h) = (64, 56);
    let mut world = World::new(w, h, seed, content.clone()).unwrap();
    world.fill_rect(0, 0, w, h, "rock").unwrap();
    world.fill_rect(2, 2, w - 4, h - 4, "air").unwrap();
    let mut state = seed.wrapping_mul(7919).wrapping_add(13);
    let mut below = |n: u32| {
        state = state
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        ((state >> 33) as u32) % n
    };
    for _ in 0..6 {
        let (x, y) = (4 + below(50) as i32, 10 + below(40) as i32);
        let (bw, bh) = (2 + below(10) as i32, 1 + below(2) as i32);
        world.fill_rect(x, y, bw, bh, "rock").unwrap();
    }
    for _ in 0..14 {
        let key = POOL[below(12) as usize];
        let (x, y) = (3 + below(50) as i32, 3 + below(30) as i32);
        let (bw, bh) = (2 + below(9) as i32, 1 + below(5) as i32);
        world.fill_rect(x, y, bw, bh, key).unwrap();
    }
    world.set_dirty_mode(mode);
    world
}

#[test]
fn random_boxes_mix_the_same_whether_or_not_chunks_sleep() {
    // SIM-R72 on messy scenes: every ingredient, every recipe, default and forced tuning
    for tuning in [Tuning::default(), Tuning::forced()] {
        let base = Content::embedded_with(tuning).unwrap();
        let c = Arc::new(base.with_recipes(&book()).unwrap());
        let mut mixes = 0;
        for seed in 0..24u64 {
            let mut a = random_box(&c, seed, DirtyMode::Normal);
            let mut b = random_box(&c, seed, DirtyMode::AllDirty);
            for f in 0..150 {
                a.step().unwrap();
                b.step().unwrap();
                assert_eq!(a.grid().cells(), b.grid().cells(), "seed {seed} frame {f}");
                mixes += mix_events(&mut a).len();
                mix_events(&mut b);
            }
        }
        assert!(mixes > 20, "the boxes should make potions: {mixes}");
    }
}

#[test]
fn a_snapshot_taken_in_the_middle_of_mixing_continues_the_same() {
    let c = Arc::new(Content::embedded().unwrap().with_recipes(&book()).unwrap());
    let mut a = random_box(&c, 5, DirtyMode::Normal);
    a.step_frames(40).unwrap();
    let blob = a.snapshot().unwrap();
    a.step_frames(120).unwrap();
    let mut b = World::new(64, 56, 5, c.clone()).unwrap();
    b.restore(&blob).unwrap();
    b.step_frames(120).unwrap();
    assert_eq!(a.state_hash(), b.state_hash());
    assert_eq!(a.grid().cells(), b.grid().cells());
}

#[test]
fn ingredients_that_share_no_recipe_leave_the_world_asleep() {
    // water and sand are in one recipe, oil and blood in another: oil on water never looks
    let c = forced_with(&[
        lively_of(["water", "sand", "coal"]),
        recipe("potion_crit", ["oil", "blood", "gold_dust"]),
    ]);
    let mut w = shaft(c, 6, 6);
    w.fill_rect(1, 4, 6, 2, "water").unwrap();
    w.fill_rect(1, 2, 6, 2, "oil").unwrap();
    w.step_frames(60).unwrap();
    assert!(mix_events(&mut w).is_empty());
    let (cw, ch) = w.grid().chunk_dims();
    assert!(
        (0..ch).all(|cy| (0..cw).all(|cx| w.grid().dirty_rect(cx, cy).is_empty())),
        "no shared recipe, no scan, no reason to stay awake"
    );
}

#[test]
fn the_same_seed_gives_the_same_mixing() {
    let c = Arc::new(
        Content::embedded()
            .unwrap()
            .with_recipes(&[lively_of(["oil", "water", "blood"])])
            .unwrap(),
    );
    let run = || {
        let mut w = World::new(30, 30, 3, c.clone()).unwrap();
        w.fill_rect(0, 20, 30, 10, "rock").unwrap();
        w.fill_rect(5, 10, 20, 10, "air").unwrap();
        w.fill_rect(5, 17, 20, 3, "blood").unwrap();
        w.fill_rect(5, 14, 20, 3, "water").unwrap();
        w.fill_rect(5, 12, 20, 2, "oil").unwrap();
        w.step_frames(200).unwrap();
        (w.state_hash(), w.grid_bytes())
    };
    assert_eq!(run(), run());
}

#[test]
fn recipes_belong_to_the_content_and_snapshots_check_them() {
    let base = Content::embedded().unwrap();
    let with = |inputs| Arc::new(base.with_recipes(&[lively_of(inputs)]).unwrap());
    let mut a = World::new(10, 10, 1, with(["water", "sand", "coal"])).unwrap();
    a.fill_rect(0, 8, 10, 2, "rock").unwrap();
    a.step_frames(3).unwrap();
    let blob = a.snapshot().unwrap();
    let mut same = World::new(10, 10, 1, with(["water", "sand", "coal"])).unwrap();
    same.restore(&blob).unwrap();
    assert_eq!(same.state_hash(), a.state_hash());
    let mut other = World::new(10, 10, 1, with(["water", "sand", "oil"])).unwrap();
    assert!(
        other.restore(&blob).is_err(),
        "other recipes, other content"
    );
}

#[test]
fn the_potion_cells_of_a_mix_are_ordinary_potion_liquid() {
    // the output exists as a liquid that falls and can be scooped like any other
    let c = forced_with(&[lively_of(["coal", "sand", "gold_dust"])]);
    let mut w = shaft(c, 3, 6);
    w.fill_rect(1, 5, 3, 1, "rock").unwrap();
    w.paint(2, 4, 0, "coal").unwrap();
    w.paint(3, 4, 0, "sand").unwrap();
    w.paint(2, 3, 0, "gold_dust").unwrap();
    w.step_frames(30).unwrap();
    let potion: Vec<_> = (0..6)
        .flat_map(|y| (1..4).map(move |x| (x, y)))
        .filter(|&(x, y)| mat(&w, x, y) == "potion_lively")
        .collect();
    assert_eq!(potion.len(), 3);
    assert!(
        potion.iter().all(|&(_, y)| y == 4),
        "settled on the ledge row: {potion:?}"
    );
}

// ----- the metal of the alchemy bowl --------------------------------------------------------

#[test]
fn metal_resists_acid_fire_lava_and_every_blast_of_the_content() {
    let content = Arc::new(Content::embedded().unwrap());
    let metal = content.mats.index_of("metal").unwrap();
    let rt = content.mats.rt(metal);
    assert_eq!(rt.durability, 15);
    assert!(!rt.burnable);
    let mut w = World::new(60, 40, 5, content.clone()).unwrap();
    w.fill_rect(0, 0, 60, 40, "metal").unwrap();
    w.fill_rect(10, 10, 40, 20, "air").unwrap();
    w.paint(20, 20, 3, "acid").unwrap();
    w.paint(30, 20, 3, "lava").unwrap();
    w.paint(40, 20, 3, "oil").unwrap();
    w.ignite(40, 20);
    w.step_frames(300).unwrap();
    for (x, y) in [(9, 20), (50, 20), (30, 9), (30, 30), (0, 0)] {
        assert_eq!(mat(&w, x, y), "metal", "cell ({x}, {y})");
    }
    // the strongest blast: bomb 11 + explosive projectile 3 = 14, with all the energy there is
    let carved = w
        .explode(ExplosionSpec::new(30, 20, 25, u32::MAX, 14))
        .unwrap();
    assert!(
        carved < 40 * 20,
        "the blast has only air and a few liquids to carve"
    );
    for (x, y) in [(9, 20), (50, 20), (30, 9), (30, 30)] {
        assert_eq!(mat(&w, x, y), "metal", "cell ({x}, {y}) after the blast");
    }
    // while brick (durability 14) gives way to the same blast
    let mut b = World::new(60, 40, 5, content).unwrap();
    b.fill_rect(0, 0, 60, 40, "brick").unwrap();
    b.explode(ExplosionSpec::new(30, 20, 25, 50_000_000, 14))
        .unwrap();
    assert_eq!(mat(&b, 30, 20), "air");
}
