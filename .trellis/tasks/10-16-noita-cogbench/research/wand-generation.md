# Noita procedural wand generation (stat ranges for a faithful generator)

Source of truth: `data/scripts/gun/procedural/gun_procedural.lua` (`get_gun_data`, `apply_random_variable`, `wand_add_random_cards`, `make_wand_from_gun_data`) read from the `NathanSnail/noitadata` mirror, cross-checked against the wiki "Wand Generation" page. Values are VERIFIED(lua) unless noted. Time stats are in **frames** (60 fps).

## 1. Budget ("cost") by wand tier

| Tier (`level`) | Cost | Notes |
|---|---|---|
| 1 | 30, +5 with 50 % chance | Mines |
| 2 | 40 | |
| 3 | 60 | |
| 4 | 80 | |
| 5 | 100 | |
| 6 | 120 | |
| 10 (generated as 11) | 180 (Limatoukka) / 200 (Nightmare Hell) | wiki |

Then `cost += Random(-3, 3)`. "Rare" wand: 5 % → `cost += 65`, purple light, and a free always cast. Independent of rarity, 4 % of wands get an always cast anyway.

## 2. Mana (independent of cost)

```
mana_charge_speed = 50*level + Random(-5, 5*level)
mana_max          = 50 + 150*level + Random(-5, 5)*10
if Random(0,100) < 20:  charge /= 5 ; max *= 3        # "slow" archetype
if Random(0,100) < 15:  charge  = (50*level + R)*5 ; max = (50+150*level + R)/3   # "fast" archetype (overrides slow)
mana_max = max(mana_max, 50) ; mana_charge_speed = max(mana_charge_speed, 10)
```
Effective archetype odds: fast 15 %, slow 17 %, normal 68 % (wiki agrees). Example tier 3 normal: mana_max 460±50, charge 150±15/s. "Better" wands (certain biomes) have no fast archetype and 20 % slow (wiki, UNVERIFIED in lua read).

## 3. Random order of stat purchases

`variables_01 = {reload_time, fire_rate_wait, spread_degrees, speed_multiplier}` (shuffled), then `deck_capacity`, then `variables_03 = {shuffle_deck_when_empty, actions_per_round}` (shuffled unless `force_unshuffle`). `force_unshuffle` is rolled with probability `(15 + 6*level) %`; the `prob_unshuffle`/`prob_draw_many` fields are initialised (0.1 / 0.15) and bumped by some distribution branches but are not otherwise consumed in the read code.

Each purchase draws a value from a weighted mixture of `RandomDistribution(min, max, mean, sharpness)` branches (engine function; the wiki gives `pow(sin(pi*((x-mean)/(max-min)+0.5)), sharpness)` as the density, sharpness 0 = uniform — density formula UNVERIFIED), clamps it to what the remaining cost allows, and subtracts the price.

| Stat | Clamp from cost | Price formula | Mixture branches (weight; min..max, mean, sharpness) |
|---|---|---|---|
| `reload_time` (frames) | `[clamp(60 − 5·cost, 1, 240), 1024]` | `(60 − value)/5` | 1; 5..60, 30, 2 · 0.5; 1..100, 40, 2 · 0.02; 1..100, 40, 0 · 0.35; 1..240, 40, 0 (→ 53 %, 27 %, 1 %, 19 %) |
| `fire_rate_wait` (frames) | `[clamp(16 − cost, −50, 50), 50]` | `16 − value` | 1; 1..30, 5, 2 · 0.1; 1..50, 15, 3 · 0.1; −15..15, 0, 3 · 0.45; 0..35, 12, 0 (→ 61 %, 6 %, 6 %, 27 %) |
| `spread_degrees` | `[clamp(cost/−1.5, −35, 35), 35]` | `16 − value` | 1; −5..10, 0, 3 · 0.1; −35..35, 0, 0 (→ 91 %, 9 %) |
| `speed_multiplier` | none | 0 | 1; 0.8..1.2, 1, 6 · 0.05; 1..2, 1.1, 3 · 0.05; 0.5..1, 0.9, 3 · 1; 0.8..1.2, 1, 0 · 0.001; 1..10, 5, 2 |
| `deck_capacity` | `[1, clamp(cost/5 + 6, 1, 20)]`; if `force_unshuffle`: max `(cost−15)/5`, and if that > 6 then `6 + (cost−45)/10` | `(value − 6)·5` | 1; 3..10, 6, 2 · 0.1; 2..7, 4, 4 · 0.05; 1..5, 3, 4 · 0.15; 5..11, 8, 2 · 0.12; 2..20, 8, 4 · 0.15; 3..12, 6, 6 · 1; 1..20, 6, 0 (→ 39 %, 3.9 %, 1.9 %, 5.8 %, 4.7 %, 5.8 %, 39 %) |
| `shuffle_deck_when_empty` | — | `15 + 5·capacity` if bought | 50 % coin (forced if `force_unshuffle`); becomes non-shuffle only if coin **and** `cost ≥ 15+5·capacity` **and** `capacity ≤ 9` |
| `actions_per_round` | `[1, max i with price_i ≤ cost]`, ≤ capacity | `{1:0, 2:5+2c, 3:15+3.5c, 4:35+5c, 5:45+c²}` (c = capacity) | 1; 1..3, 1, 3 · 0.2; 2..4, 2, 8 · 0.05; 1..5, 2, 2 · 1; 1..5, 2, 0 (→ 44 %, 8.9 %, 2.2 %, 44 %) |

## 4. Post-processing

1. Leftover cost (99.5 % of the time, if `cost > 5`): shuffle wands `capacity += cost/5`; non-shuffle `capacity += cost/10`; cost → 0.
2. `No More Shuffle` perk or `force_unshuffle` argument ⇒ non-shuffle.
3. `capacity = clamp(capacity, 2, 26)` unless `Random(0,10000) == 10000` (1/10001); `capacity ≤ 1 ⇒ 2`.
4. If `reload_time ≥ 60`: `actions_per_round += 1`, repeat with 70 % probability each time; then with 50 % probability set `actions_per_round = min over 6 draws of Random(actions_per_round, capacity)`.
5. `actions_per_round = clamp(actions_per_round, 1, capacity)`.
6. Written to the entity: `gun_config.{actions_per_round, reload_time, deck_capacity, shuffle_deck_when_empty}`, `gunaction_config.{fire_rate_wait, spread_degrees, speed_multiplier}`, `mana_charge_speed`, `mana_max`, `mana = mana_max`, `gun_level = level`, `item_recoil_recovery_speed = 15`. Sprite chosen by `GetWand(gun)` from 900 wand graphics by stat similarity (wiki).

## 5. Spell placement (`wand_add_random_cards`)

- Spells come from tier `level − 1`; the main projectile has a 10 %-repeating chance to come from one tier higher each repeat.
- `card_count = Random(0.51·capacity, capacity)` clamped to `[1, capacity − 1]` (so a generated wand always has ≥ 1 empty slot).
- 50 % "structured" layout: optional Multicast (40 %), optional second Multicast if > 3 cards (40 %), Modifier (80 %), then the projectile repeated; for < 3 cards: optional modifier (20 %) + projectiles.
- 50 % "random" layout: for each slot, with probability `good_cards` (Random 5–45 %) and > 2 cards, place a Multicast (first good card on a 1/cast wand is always a multicast) or Modifier (83 %) / Multicast (17 %); else the projectile (optionally re-rolled per slot with probability `(10·level − 5) %`).
- Always cast (4 % or rare): 77 % modifier, 8 % modifier, 8 % static projectile, 7 % projectile, from tier `level` (one above the cards).
- Random wands only contain Projectile / Multicast / Modifier types (wiki): utility/other/material only via chests, shops, premade wands.

## Sources
- https://noita.wiki.gg/wiki/Wand_Generation?action=raw
- https://noita.wiki.gg/wiki/Wands?action=raw
- https://noita.wiki.gg/wiki/Wand_and_Spell_Tiers?action=raw
- https://github.com/NathanSnail/noitadata (data/scripts/gun/procedural/gun_procedural.lua)
