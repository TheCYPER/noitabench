# v1 Scope (noita-cogbench)

**Purpose:** The rest of this knowledge base was written for a faithful, full-size Noita clone. The project was re-scoped on 2026-10-16..26 into an LLM-agent capability benchmark (task `.trellis/tasks/10-16-noita-cogbench/`). This page says which parts of the KB the first version uses, which parts it deliberately changes, and which pages are superseded. Read it before any other KB page.

**Precedence:** the task documents (`prd.md`, `design.md`, `tick-design.md`, `world-design.md`, `capability-graph.md`, all in Chinese) decide *what* is in scope; inside that scope the KB pages below stay normative for *how* a mechanic works, except where section 5 lists a deliberate deviation.

---

## 1. Superseded pages and decisions

| Page or item | Status | Replaced by |
|---|---|---|
| `benchmark.md` | Partly superseded. Still valid: JSON Lines framing (`PROTO-R01`, `R03`, `R05`), seeded RNG streams (`DET-R04`), no HashMap iteration (`DET-R05`), monotone scores (`SCORE-R01..R03`). Obsolete: RL observations (`OBS-R07..R09`), state hashing and anti-cheat (`DET-R02`, `DET-R03`, `ANTI-*`), thread-count equality (`DET-R08`), the 8-task suite | task `design.md` §5, §10–12; `tick-design.md`; `capability-graph.md` |
| `frontend.md` (macroquad human frontend) | Superseded | task `design.md` §8 and §13 (web client and replay) |
| `worldgen.md` fBm strategy (`WORLD-R07`) and `DN-WORLD-02` | Superseded: generation follows Noita (fixed biome map, herringbone Wang tiles, pixel scenes) | task `world-design.md` |
| Multithreaded stepping (`SIM-R21`, `SIM-R22`, `SIM-R74`) | Deferred: v1 is single-threaded | task `design.md` §1, §11 |
| State hash layout (`SIM-R75`) | Obsolete | none |
| MVP-40 material set (`MVP-R01`), 39 reactions (`MVP-R02`), MVP-50 spells | Replaced by the smaller sets in sections 2–4 | this page |

## 2. Materials (about 22)

| Our name | Noita id or reference | Family | Notes |
|---|---|---|---|
| 空气 air | `air` | empty | |
| 蒸汽 steam | `steam` | gas | |
| 可燃气 flammable gas | `acid_gas` ("Flammable Gas") | gas | also the merged output of whiskey burning |
| 火 fire | `fire` | fire | |
| 水 water | `water` | water family | extinguishes burning cells (section 5) |
| 血 blood | `blood` | water family | |
| 油 oil | `oil` | fuel liquid | |
| 威士忌 whiskey | `alcohol` | fuel liquid | |
| 酸 acid | `acid` | corrosive | |
| 岩浆 lava | `lava` | molten | |
| 毒泥 toxic sludge | `radioactive_liquid` | toxic | |
| 沙 sand | `sand` | powder | |
| 煤 coal | `coal` | powder | |
| 火药 gunpowder | `gunpowder_explosive` | powder | |
| 泥土地 ground | `sand_static` ("Ground") | terrain | soft, diggable |
| 岩石 rock | `rock_static` | terrain | |
| 木头 wood | `wood_static` | terrain | burnable; also used for fungus stalks |
| 神殿砖 brickwork | `templebrick_static` | terrain | durability 14, effectively undiggable early |
| 治疗药水 heal potion | ours (cf. Healthium) | potion | found in the world |
| 法力药水 mana potion | ours (cf. Concentrated Mana) | potion | found in the world |
| 加速药水 haste potion | ours (cf. Hastium) | potion | found in the world |
| 活力药剂 lively concoction | ours (cf. Lively Concoction) | potion | only from the seeded hidden recipe |

Physical numbers (density, hp, durability, fuel, ignition) come from the `MVP-40` table in `materials-reactions.md` for the Noita ids above. The repository file `content/materials.json` is the runtime source of truth.

## 3. Reactions (base table, perturbation strength 0)

See task `design.md` §2.2 for the 15 rows. Noita sources: `xml_065`, `xml_079`, `xml_009`, `xml_052`, `xml_093`, `xml_094`, `xml_095`, `xml_097`, `xml_150`, `xml_166`, `xml_035`, `xml_007`, `xml_086`, plus two rows of our own (extinguishing, the hidden recipe). Semantics of each row follow `RXN-R*` in `materials-reactions.md`.

## 4. Spells, enemies, statuses

- **Spells (25):** `LIGHT_BULLET`, `BULLET`, `RUBBER_BALL`, `SLOW_BULLET`, `BOMB`, `FIREBALL`, `DIGGER`, `EXPLOSION`, `MATERIAL_WATER`, `MATERIAL_OIL`, `MATERIAL_ACID`, `LIGHT_BULLET_TRIGGER`, `LIGHT_BULLET_TIMER`, `BURST_2`, `BURST_3`, `SPEED`, `DAMAGE`, `HEAVY_SHOT`, `SPREAD_REDUCE`, `BOUNCE`, `EXPLOSIVE_PROJECTILE`, `FIRE_TRAIL`, `WATER_TRAIL`, `RECHARGE`, `MANA_REDUCE`. Numbers from `spells.md` and `spells.json`; casting follows `WAND-R01..R64` (stage 1 only).
- **Enemies (3):** `longleg` (Hämis), `shotgunner` (Haulikkohiisi), `firemage_weak` (Stendari, fire multiplier 0). Numbers from `enemies.json`; speeds and attack intervals are re-tuned to the 10-frame tick.
- **Statuses:** wet, oiled, on fire, poisoned, haste, drunk, regeneration. Applied by contact and by drinking. Single damage type.
- **Player:** movement and levitation numbers from `entities-damage.md` Key numbers (walk 57 px/s, jump -95 px/s, levitation 3.0 s, no fall damage).

## 5. Deliberate deviations from Noita

| Deviation | Noita rule it overrides | Why |
|---|---|---|
| Water-family cells extinguish burning cells, as a reaction row that perturbation may change | `FIRE-R08` (water does not douse burning materials) | user decision (round-2 Q13): match common sense and the design PDF's examples |
| Reaction outputs merged into the smaller material set (`lavarock_static`, `rock_static_radioactive` → `rock_static`; `alcohol_gas`, `poison_gas`/`radioactive_gas` → `acid_gas`; smoke dropped) | `MVP-R02` outputs | keep the table closed over about 22 materials |
| Bombs, flasks and wands are simple ballistic bodies (gravity, bounce, no rotation) | `DN-SPELL-03` rolling bodies, Box2D | round-2 Q16 |
| Stains come from contact as well as spells | `DN-ENT-05` default (spell-only statuses) | round-2 Q15 |
| Acid is consumed when it corrodes (r04: `acid + [corrodible] -> flammable_gas + air`), and free acid is never placed in the world (only barrels, the `MATERIAL_ACID` spell, brick vats) | `xml_052` (acid persists) | user review of CP1, 2026-10-26: free acid dissolved whole biomes |
| On-fire damage is 0.2 internal HP per second (about 5 HP/s for the player), from `fire_damage_amount` read per second | `DAMAGE-R14` (2 % of max HP per second) | so burning kills Hämis as the KB describes and matters for the player (lead decision 2026-10-26) |
| Flammable gas never expires (no lifetime); it disappears only by burning or reacting | `acid_gas` lifetime 450 frames | gas hazard pockets placed by world generation must persist (lead decision 2026-10-26) |
| Being buried by powder traps but does not hurt | none | matches Noita; the digger wand frees the player |
| `EXPLOSIVE_PROJECTILE` also raises the max durability of the modified projectile's explosion by 3 (copies do not stack: the largest bonus applies), so `BOMB` (11) + `EXPLOSIVE_PROJECTILE` = 14 breaks brick and nothing else in the content does | Noita's modifier adds radius and damage only; brick (templebrick) is unbreakable in v1's content otherwise | the seal must open with an item found in the world, assembled into a wand (capability-graph C3, N3); plain bombs still leave brick vats and troughs intact (lead decision 2026-10-27) |
| Reaction table and recipes are perturbed per rule seed | all `xml_*` probabilities and outputs | contamination control (round-1 F1–F3) |

## 5a. Implementation amendments (2026-10-26)

- `SIM-R11` / `SIM-R72`: a chunk visits its dirty rectangle plus the `WAKE` area around writes already made this frame by itself and its 8 neighbours, so in-frame cascades never escape the scan and dirty-rect mode equals all-awake mode.
- `SIM-R31` / `SIM-R32`: slow liquids (lava) use one fall gate per frame for every column and end a sideways hop at the first unsupported cell, so a falling column stays together.
- `SIM-R60..R65`: implemented in `crates/sim/src/query/`; the origin cell of a ray is tested too; `PLATFORMS` equals `SURFACES` (collision is kind-based).
- `FIRE-R10`: explosion numbers come from the material's `explosion` block in `content/materials.json`.
- `HAZ-R01`: the 4-cell minimum and the 85-cell cap apply per material.
- `SIM-R78`: snapshots keep the per-chunk dirty rectangles instead of restoring all-dirty; restore is still exact (tested).
- Explosion line of sight in `crates/game` uses the same 4-connected (supercover) path as projectiles, so diagonally touching cells shield.
- `SIM-R62` rays are 8-connected (Bresenham) and can pass between two diagonally touching blocking cells. Projectile code in `crates/game` must not let projectiles slip through such corners: it tests the 4-connected (supercover) path (decided 2026-10-26).

## 6. Rule ranges still in force

`SIM-R01..R37`, `SIM-R50..R52`, `SIM-R70`; `MAT-*`, `RXN-*`, `FIRE-R01..R07`, `FIRE-R09`, `FIRE-R10`, `FIRE-R12`, `DUR-R01..R04`, `HAZ-R01..R03`; `WAND-R01..R64`; the damage, status and player sections of `entities-damage.md` restricted to section 4 above. Test vectors that only use in-scope materials, spells and rules remain valid.
