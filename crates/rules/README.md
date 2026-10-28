# cogbench-rules

The reaction table every world runs, the questions world generation asks of it, and the **secret recipes** of a rule seed
(task `design.md` section 4, `prd.md` section 2.6; CP2 decision of 2026-10-27).

Since CP2 the reaction table is **the original one for every rule seed** (water on lava always makes rock, as in Noita).
There is no perturbation, no strength, no odd one out. What the rule seed changes is how the eight secret potions are made.

```rust
let rules = cogbench_rules::Rules::embedded()?;     // or Rules::new(materials_json, reactions_json)
rules.reactions_json()      // exactly content/reactions.json
rules.content()             // the compiled cogbench_sim::Content (materials + table, no recipes)
rules.recipes(rule_seed)?   // Vec<RecipeDef>: one { potion, inputs: [a, b, c] } per secret potion
cogbench_rules::recipes_embedded(rule_seed)?   // the same for the shipped content, parsed once
```

The recipes go to the simulation with `Content::with_recipes(&recipes)`; `cogbench-game` does it for every world it loads.

## Questions about the table

`transforms(a, b)`, `reactions_for(a, a_burning, b, b_burning)`, `lava_solidifiers()`, `extinguishers()`,
`water_family_extinguishes()`, `acid_dissolves(target)`, `ignites(source, target)` and `check_invariants()` answer on the
table the simulation actually runs (tags, positional outputs and file order are the engine's).
`check_invariants()` is a guard for edits of `reactions.json`; the encounters rely on it:

* at least 2 liquids turn lava into rock or ground at >= 40% (`lava_solidifiers`; E02 lava river, E07, E14),
* some liquid puts burning cells out at >= 30%,
* acid makes rock disappear at >= 20%,
* fire ignites flammable gas at >= 15%,
* no reaction produces a potion (potions come from recipes only).

## The recipes

A material tagged `secret_potion` in `materials.json` gets one recipe; the ingredient pool is every material tagged
`ingredient`. Today: 8 potions (`potion_lively`, `potion_invulnerable`, `potion_mana_regen`, `potion_crit`,
`potion_berserk`, `potion_levitation`, `potion_invisible`, `potion_fireproof`) and 12 ingredients (`water`, `blood`,
`oil`, `whiskey`, `toxic_sludge`, `sand`, `coal`, `gunpowder`, `gold_dust`, `bone_dust`, `fungus_powder`, `slime`).

The recipes of a seed satisfy (tested over thousands of seeds):

* each recipe has **three distinct ingredients**; the 8 recipes are 8 different sets;
* **no two ingredients of one recipe react** with each other in the table when two plain cells touch (oil on water stays
  oil on water), so a recipe is never also a table reaction;
* **spread**: no ingredient is in more than 3 recipes (24 slots over 12 ingredients, 2 each on average);
* **deterministic**: one SplitMix64 stream `rules/recipes` of the rule seed (`DET-R04`), no `HashMap` iteration; the rule
  seed is the only input. The same seed gives the same recipes in every process.

The draw shuffles the 210 quiet triples with the stream and takes them in order while the usage cap allows (starting
over with the same stream if a shuffle cannot be completed); the k-th chosen triple belongs to the k-th secret potion.

**Recipes are not reactions.** They are never rows of `reactions.json` and never appear in a recording, an observation or
a tool output. The simulation's mixing rule (`crates/sim/src/rules/recipe_mix.rs`) reads them:

1. an ingredient cell only mixes where it touches (4-neighbour) an ingredient of another material that shares a recipe
   with it, so lakes and piles cost nothing;
2. there it looks along the four axes **through its own material** (up to 6 cells) and notes the first cell of another
   material in each direction, so a layer of liquid up to 6 cells thick between the other two ingredients still mixes;
3. if the other two ingredients of a recipe are both among those four cells, then with chance 64/256 per visit the three
   cells (the visited one and the two it sees) all become the potion.

Try it: `cargo run -p cogbench-rules --example show_recipes -- 1 2 3` prints the recipe book of each seed.

## Tests

* `tests/base_table.rs`: the table is the file byte for byte, the invariants hold, no row names a recipe, the question API.
* `tests/recipes.rs`: constraints over 3000 seeds, determinism, variety, ingredient balance, errors for bad materials.
* `tests/sim_effect.rs`: the predicates are true in the simulation; every recipe of 40 seeds makes its potion from its
  three ingredients in a `World`, two ingredients and a stranger make nothing, and without recipes nothing is made.

## Gates

```
cargo fmt -p cogbench-rules --check
cargo clippy -p cogbench-rules --all-targets -- -D warnings
cargo test -p cogbench-rules
```

## Lead decisions that still hold (2026-10-26)

* `lava_solidifiers` counts only rock or ground as a solid product.
* Text in notes and row `source` fields of a reaction table must not be shown to an agent; observations carry the content
  hash only.
