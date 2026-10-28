//! Wands and spells found in the world (marker `wand` and `spell`): generated from the tier tables
//! of `entities.json` with the `spawn` random stream, so the same world seed always lays out the
//! same loot (Q17). The tables follow `wand-casting.md` R90..R95 in spirit: a wand holds only
//! projectile, modifier and multicast spells and always keeps at least one slot empty.

use crate::error::Error;
use crate::rng::HashRng;
use crate::spell::{SpellId, SpellType};
use crate::wand::WandStats;

use super::Game;

/// Weights of the spell kinds a generated wand draws its extra cards from.
const WAND_KINDS: [SpellType; 3] = [
    SpellType::Projectile,
    SpellType::Modifier,
    SpellType::Multicast,
];

impl Game {
    fn spawn_rng(&self) -> HashRng {
        HashRng::stream(self.world.seed(), "spawn")
    }

    /// Spells of a type in catalogue order that random loot may contain: the ones listed in
    /// `entities.json` `spell_pickup_exclude` are left out (the seal key is placed by hand).
    fn spells_of(&self, kind: SpellType) -> Vec<SpellId> {
        let excluded = &self.defs.spell_pickup_exclude;
        self.book
            .iter()
            .filter(|(_, s)| s.kind == kind && !excluded.contains(&s.key))
            .map(|(id, _)| id)
            .collect()
    }

    fn weight_of(&self, kind: SpellType) -> u32 {
        let key = match kind {
            SpellType::Projectile => "projectile",
            SpellType::StaticProjectile => "static_projectile",
            SpellType::Modifier => "modifier",
            SpellType::Multicast => "multicast",
            SpellType::Material => "material",
        };
        self.defs
            .spell_pickup_weights
            .get(key)
            .copied()
            .unwrap_or(0)
    }

    /// A random spell for a spell pickup, weighted by `spell_pickup_weights`.
    pub(crate) fn random_spell(&self, salt: u64) -> Result<SpellId, Error> {
        let kinds = [
            SpellType::Projectile,
            SpellType::StaticProjectile,
            SpellType::Modifier,
            SpellType::Multicast,
            SpellType::Material,
        ];
        self.pick_spell(&kinds, salt, 0)
    }

    fn pick_spell(&self, kinds: &[SpellType], salt: u64, draw: u64) -> Result<SpellId, Error> {
        let rng = self.spawn_rng();
        let total: u32 = kinds.iter().map(|k| self.weight_of(*k)).sum();
        if total == 0 {
            return Err(Error::content(
                "content/entities.json",
                "spell_pickup_weights",
                "no weight for any spell kind",
            ));
        }
        let mut roll = rng.below(total, salt, 100 + draw, 0);
        for kind in kinds {
            let w = self.weight_of(*kind);
            if roll < w {
                let pool = self.spells_of(*kind);
                if pool.is_empty() {
                    break;
                }
                let i = rng.below(pool.len() as u32, salt, 200 + draw, 1) as usize;
                return Ok(pool[i]);
            }
            roll -= w;
        }
        Err(Error::arg(
            "the spell book has no spell of the weighted kinds",
        ))
    }

    /// Stats and spells of a wand of `tier` (1 to 3; higher tiers are clamped to the last).
    pub(crate) fn generate_wand(
        &self,
        tier: u32,
        salt: u64,
    ) -> Result<(WandStats, Vec<Option<SpellId>>), Error> {
        let tiers = &self.defs.wand_tiers;
        let def = tiers
            .get(&tier.to_string())
            .or_else(|| tiers.values().next_back())
            .ok_or_else(|| Error::content("content/entities.json", "wand_tiers", "no tiers"))?;
        let rng = self.spawn_rng();
        let pick = |range: [i64; 2], k: u64| rng.range(range[0], range[1], salt, 300 + k, 2);
        let capacity = pick([def.capacity[0].into(), def.capacity[1].into()], 0) as u32;
        let spells_per_cast = (pick(
            [def.spells_per_cast[0].into(), def.spells_per_cast[1].into()],
            1,
        ) as u32)
            .min(capacity);
        let stats = WandStats {
            shuffle: rng.percent(def.shuffle_percent, salt, 302, 2),
            spells_per_cast,
            cast_delay: pick([def.cast_delay[0].into(), def.cast_delay[1].into()], 3) as i32,
            recharge: pick([def.recharge[0].into(), def.recharge[1].into()], 4) as i32,
            mana_max: pick([def.mana_max[0].into(), def.mana_max[1].into()], 5) as f32,
            mana_charge_speed: pick(
                [
                    def.mana_charge_speed[0].into(),
                    def.mana_charge_speed[1].into(),
                ],
                6,
            ) as f32,
            capacity,
            spread: pick([def.spread[0].into(), def.spread[1].into()], 7) as f32,
            speed_multiplier: 1.0,
        };
        // At least one slot stays empty (WAND-R95), at least one spell goes in.
        let most = capacity.saturating_sub(1).max(1);
        let count =
            (pick([def.spell_count[0].into(), def.spell_count[1].into()], 8) as u32).clamp(1, most);
        let mut spells = Vec::new();
        for i in 0..count {
            let kinds: &[SpellType] = if i == 0 {
                &WAND_KINDS[..1]
            } else {
                &WAND_KINDS
            };
            spells.push(Some(self.pick_spell(kinds, salt, u64::from(i))?));
        }
        Ok((stats, spells))
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::*;

    #[test]
    fn generated_wands_and_random_spells_never_hold_an_excluded_spell() {
        let mut seen = BTreeSet::new();
        for world_seed in 0..40u64 {
            let g = Game::empty(10, 10, world_seed).expect("game");
            let excluded = g.defs.spell_pickup_exclude.clone();
            assert!(excluded.iter().any(|k| k == "EXPLOSIVE_PROJECTILE"));
            for tier in 1..=3 {
                for salt in 0..300u64 {
                    let (_, spells) = g.generate_wand(tier, salt).expect("wand");
                    for id in spells.into_iter().flatten() {
                        let key = g.book.key(id).to_string();
                        assert!(!excluded.contains(&key), "tier {tier} salt {salt}: {key}");
                        seen.insert(key);
                    }
                }
            }
            for salt in 0..300u64 {
                let id = g.random_spell(salt).expect("spell");
                let key = g.book.key(id).to_string();
                assert!(!excluded.contains(&key), "salt {salt}: {key}");
                seen.insert(key);
            }
        }
        // the rest of the book is still handed out, bombs and the other modifiers included
        for key in ["BOMB", "DAMAGE", "BURST_2", "BOUNCE", "SPEED"] {
            assert!(seen.contains(key), "{key} never came up");
        }
    }
}
