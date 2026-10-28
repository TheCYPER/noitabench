//! Solvability invariants: what the reaction table must allow for the encounters to be solvable.
//!
//! These are the conditions the encounters of `capability-graph.md` section 3 rely on. The table
//! is the original one for every rule seed, so this is a guard for edits of `reactions.json`
//! ([`crate::Rules::check_invariants`]), not a filter on a draw.

use crate::query::{dissolves, extinguishers, ignites, lava_solidifiers, reactions_for};
use cogbench_sim::Content;
use serde::Serialize;

/// Distinct liquids that must turn lava into a solid (E02 lava river, E07, E14): the table
/// ships three (water, blood, toxic sludge); two keep every encounter solvable.
pub const MIN_LAVA_SOLIDIFIERS: usize = 2;
/// A solidifier, an extinguisher and the like only count if they work at least this often.
pub const MIN_QUENCH_PROBABILITY: f64 = 0.4;
pub const MIN_EXTINGUISH_PROBABILITY: f64 = 0.3;
pub const MIN_DISSOLVE_PROBABILITY: f64 = 0.2;
pub const MIN_SPREAD_PROBABILITY: f64 = 0.15;

/// A violated invariant.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct InvariantFailure {
    pub name: &'static str,
    pub detail: String,
}

fn fail(name: &'static str, detail: impl Into<String>) -> InvariantFailure {
    InvariantFailure {
        name,
        detail: detail.into(),
    }
}

/// Check a compiled table against every invariant; empty means solvable.
pub fn check(content: &Content) -> Vec<InvariantFailure> {
    let mut failures = Vec::new();

    let solidifiers = lava_solidifiers(content, MIN_QUENCH_PROBABILITY);
    if solidifiers.len() < MIN_LAVA_SOLIDIFIERS {
        failures.push(fail(
            "lava_solidifier",
            format!(
                "{} liquid(s) turn lava into a solid at >= {}%, need {MIN_LAVA_SOLIDIFIERS}",
                solidifiers.len(),
                MIN_QUENCH_PROBABILITY * 100.0
            ),
        ));
    }

    let liquid_douses = extinguishers(content, MIN_EXTINGUISH_PROBABILITY)
        .into_iter()
        .any(|e| {
            content
                .mats
                .index_of(&e.material)
                .is_some_and(|i| content.mats.rt(i).kind == cogbench_sim::Kind::Liquid)
        });
    if !liquid_douses {
        failures.push(fail(
            "extinguisher",
            format!(
                "no liquid puts out burning cells at >= {}%",
                MIN_EXTINGUISH_PROBABILITY * 100.0
            ),
        ));
    }

    if dissolves(content, "acid", "rock").unwrap_or(0.0) < MIN_DISSOLVE_PROBABILITY {
        failures.push(fail(
            "acid_dissolves_rock",
            "acid no longer makes rock disappear",
        ));
    }

    if ignites(content, "fire", "flammable_gas").unwrap_or(0.0) < MIN_SPREAD_PROBABILITY {
        failures.push(fail(
            "fire_spreads_through_gas",
            "fire no longer ignites flammable gas",
        ));
    }

    failures.extend(potion_leaks(content));
    failures
}

/// Closure beyond "every output exists": no reaction may produce a potion (potions come only from
/// the hidden recipe), so a potion can never appear by accident.
fn potion_leaks(content: &Content) -> Vec<InvariantFailure> {
    let n = content.mats.len() as u8;
    let mut leaks = Vec::new();
    for a in 1..n {
        for b in a..n {
            for t in reactions_for(content, a, true, b, true) {
                for out in [&t.out_a, &t.out_b] {
                    if let crate::query::Outcome::Becomes(k) = out {
                        let is_potion = content
                            .mats
                            .index_of(k)
                            .and_then(|i| content.mats.get(i))
                            .is_some_and(|m| m.family == "potion");
                        if is_potion {
                            leaks.push(fail(
                                "no_potion_from_reactions",
                                format!("row {} produces {k}: {}", t.row, t.text()),
                            ));
                        }
                    }
                }
            }
        }
    }
    leaks
}
