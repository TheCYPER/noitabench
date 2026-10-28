//! Print the recipes of a rule seed for review:
//! `cargo run -p cogbench-rules --example show_recipes -- <rule_seed> [<rule_seed> ...]`

use cogbench_rules::Rules;

fn main() -> Result<(), cogbench_rules::Error> {
    let rules = Rules::embedded()?;
    let mut seeds: Vec<u64> = std::env::args()
        .skip(1)
        .filter_map(|s| s.parse().ok())
        .collect();
    if seeds.is_empty() {
        seeds.push(42);
    }
    for seed in seeds {
        println!("rule seed {seed}");
        for r in rules.recipes(seed)? {
            println!(
                "  {:<22} = {} + {} + {}",
                r.potion, r.inputs[0], r.inputs[1], r.inputs[2]
            );
        }
    }
    Ok(())
}
