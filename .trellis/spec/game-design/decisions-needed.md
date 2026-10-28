# Decisions Needed and Open Questions

Every `DECISION-NEEDED` and open question of the knowledge-base pages, deduplicated and grouped by system. Each item has one global id (`DN-<system>-<nn>`), the options, a recommended default, and the page-local ids it came from (cite those with the page: `SIM SD1`, `MR D2`, `WAND WD1`, `SP S3`, `ED ED-D2`). Nothing here is decided until the user says so; the stated default is what the pages already assume, so implementation can proceed on it. How to update this file: [index.md](index.md) section 5.

**Type tags.** `[User]` the page asks the user to choose; `[Default]` a default is adopted, revisit only if calibration or benchmarks disagree; `[Fact]` an engine or data fact that is UNVERIFIED (resolve by observation, calibration or a test, no user input); `[Conflict]` two pages or a page and a task document disagree (found in the consistency pass of this finalisation); `[Settled]` listed only so nobody reopens it.

**Sections.** 1 Pixel simulation, 2 Materials and reactions, 3 Wands and casting, 4 Spells, 5 Entities and damage, 6 Agent benchmark, 7 World generation and frontend (pages not yet written), 8 Task-document drift.

---

## 1. Pixel simulation ([pixel-simulation.md](pixel-simulation.md))

| ID | Question | Options | Recommended default | Origin |
|---|---|---|---|---|
| DN-SIM-01 | [User] Cell RNG scheme | (a) stateless per-cell hash of `(cell_seed, frame, pass, world index)`; (b) per-chunk xoshiro256** stream seeded `(seed, frame, chunk, pass)` consumed in scan order | (a). The only scheme that allows the dirty-rect transparency test (SIM-R72); benchmark.md DET-R04 and materials-reactions.md RXN-R17 already use this wording. (b) is simpler but cannot meet SIM-R72. | SIM SD1 |
| DN-SIM-02 | [User] Timer storage in the `u8` counters | (a) per-material tick unit (`life_unit`, `burn_unit`), exact for all 15 lifetimes; (b) global 8-frame quantum (earlier MR D5/D8; rounds `flame` 5 f and `rat_powder` 4 f up to 8); (c) widen to `u16` (+1 byte per cell) | (a) | SIM SD2, SIM-R35; MR D5, D8 |
| DN-SIM-03 | [User] Gas movement model | (a) act with probability `gas_speed/100` (50 %), try up first, then sideways; (b) the literal 4-weight random walk (about 1 px/s net drift, gas would not visibly rise) | (a) | SIM SD3, SIM-R34 |
| DN-SIM-04 | [User] Rule writes into frozen chunks (outside the active rect) | (a) treated as `boundary` (writes dropped); (b) allowed and wake the chunk (costs a merge rule) | (a). Only matters when the active rect is smaller than the world (game world 2048x1536). | SIM SD4 |
| DN-SIM-05 | [User] Cell layout | (a) 6 B with a separate `burn` byte; (b) 5 B plus a parity bit (rejected: stamps stall under dirty rects) | (a) | SIM SD5, SIM-R03, SIM-R15 |
| DN-SIM-06 | [User] Density storage | (a) `density_x10000: u32` (exact for all 42 values); (b) `density_q8: u16` (order-preserving, not exact) | (a) | SIM SD6 |
| DN-SIM-07 | [User] Performance acceptance scenario for the 1024x1024 world | (a) active radius = 512x512 around the player at 60 Hz, all-active soup reported separately; (b) all-active 1024x1024 at 60 Hz (15.9 ns per cell single-threaded, not realistic) | (a) | SIM SD7, SIM-R81 |
| DN-SIM-08 | [User] Who owns the state hash | (a) benchmark.md owns the algorithm and Merkle structure, this page owns the hashed byte layout; (b) blake3 over a `to_bytes` dump per frame | (a) | SIM SD8, SIM-R75; BEN DET-R02 |
| DN-SIM-09 | [User] `air`-input reaction rows with the full 466-material table | (a) accept the always-awake cost (MVP-40 has 6 such rows); (b) add a random-tick sampler (a few stateless samples per chunk per frame, independent of dirty rects) before adding grass, moss or vine rows | (a) for MVP-40; revisit when stretch or full tables are enabled (see DN-MAT-02) | SIM SD9, SIM-R12 |
| DN-SIM-10 | [User] Particle constants | (a) `GRAV` 200 px/s^2, lifetime cap 600 f, cap 100,000, drop newest; (b) gravity 100 (Lua cosmetic default) or 360 (FallingSandEngine) | (a) | SIM SD10, SIM-R45, SIM-R46 |
| DN-SIM-11 | [User] Liquid lateral range mapping | (a) `L = round_half_up(flow/(1-damping))`, slime halves, cap 10; (b) a hand-written table per material | (a) | SIM SD11, SIM-R32 |
| DN-SIM-12 | [User] Explosion caps per frame | (a) 32 explosions and sum(R^2) <= 400,000, rest carried over in queue order; (b) uncapped (a nuke storm stalls a frame) | (a) | SIM SD12, SIM-R54 |
| DN-SIM-13 | [User] Numeric type of entity and projectile kinematics | (a) `f32` restricted by DET-R06 (`+ - * / sqrt`, transcendentals via `libm` or tables); (b) fixed point (keeps a later `f32` rapier behind a boundary conversion) | (a) | SIM SD13, SIM-R71; BEN DET-R06 |
| DN-SIM-14 | [Fact] Engine behaviours not verifiable locally | Column order and visited marks (Q1); which chunks Noita steps and the meaning of `GRID_*_UPDATES` (Q2); how flying pixels are re-deposited (Q3); meaning of viscosity, damping, `liquid_sticks_to_ceiling`, the `fire_hp` decrement unit and the direction of `requires_oxygen` (Q5); expiry of `fire`, `fire_blue` and sparks (Q7); units of projectile `speed` (Q8); whether Noita stores per-cell velocity or burn counters (Q9); Noita's real performance (Q11); which duplicate material definition wins (Q12) | Keep the page defaults; keep every mapping in the material table or `sim::consts`; calibrate against footage and frame counts. None blocks implementation. Explosion ray details are DN-MAT-07, reaction cadence is DN-MAT-03. | SIM Open 1-3, 5, 7-9, 11-12 |
| DN-SIM-15 | [Fact] Rigid-body libraries | Rapier cross-platform determinism options (`enhanced-determinism`, `parallel` off) and licences of `contour`, `ramer_douglas_peucker`, `earcutr` | Not needed until rigid bodies exist (DN-SPELL-03); verify then | SIM Open 10, SIM-R87 |
| DN-SIM-16 | [Default] Risk watch list | Parameter mappings that look wrong against footage; one dirty rect per chunk wasting scans on scattered activity (add an 8x8-tile occupancy bitmap only if profiling shows it); tile-indirection cost (fallback in SIM-R24); serial explosion and particle phases spiking; rapier determinism; rules silently exceeding the reach (SIM-R77) | Monitor through the SIM-R82 benchmarks and the reach monitor | SIM Open 13 |

## 2. Materials, reactions, fire and durability ([materials-reactions.md](materials-reactions.md))

| ID | Question | Options | Recommended default | Origin |
|---|---|---|---|---|
| DN-MAT-01 | [User] Approve the material set | (a) MVP-40 plus the 12 stretch ids; (b) adjust (for example swap `poison` / `radioactive_liquid` for `slime`). The generator research (research/worldgen.md) also uses `copper`, `rock_static_wet`, `grass`, `fungus`, `water_ice`, which are outside MVP-40 (`grass` and `water_ice` are stretch ids) | (a); the world generator must stay inside the approved set, or the set grows (see DN-WORLD-03) | MR D1, MVP-R01 |
| DN-MAT-02 | [Conflict] Size of the runtime material table | (a) load all 466 materials (stable `u16` ids, rank by `xml_order`); MVP-40 is the enabled content for worldgen, legend and tests; only the 39 MVP reactions are compiled; (b) ship a 40-row table with renumbered ids; (c) load all 466 and compile all 330 `xml_` reactions (needs the SD9 sampler and the 3-input rules). MVP-R01 ("ships exactly 40") reads as (b), while SIM-R04, SIM-T25 and RXN-R18 assert 466 as in (a) | (a) | MR MVP-R01, MVP-R02, RXN-R18; SIM-R04, SIM-T25, SD9 |
| DN-MAT-03 | [User] Reaction cadence | (a) each non-air cell examines one random 4-neighbour per frame, pair matched symmetrically (effective rate about 0.44 p); (b) all 4 neighbours (4x faster); (c) 8 neighbours | (a); calibrate by feel (the water-on-lava crust should form in a few frames) | MR D2, Open 1; SIM-R38, Open 6 |
| DN-MAT-04 | [Default] `fast_reaction` and priority | Ignore `fast_reaction`; XML file order is the priority; alternatives unknown | As stated | MR D3, Open 2 |
| DN-MAT-05 | [Default] Ignition chance | `(100 - autoignition)` percent per attempt, strict `temperature_of_fire(source) > autoignition(target)`, one random 4-neighbour per burning cell per frame; alternative: a flat 50 % above the threshold | As stated | MR D4, Open 3; SIM-R37 |
| DN-MAT-06 | [Default] Fuel, flame and smoke units | 1 fuel per frame; flame chance `generates_flames/100` into a random free neighbour; smoke `min(100, generates_smoke)` percent; tune visually. Storage of the counters follows DN-SIM-02 | As stated | MR D5, Open 3 |
| DN-MAT-07 | [Default] Fire-cell life and explosion ray geometry | Fire cells live a uniform 12 to 30 frames and move like gas; explosions use `N = max(16, ceil(2*pi*R))` evenly spaced rays with seeded jitter; a cell blocked by durability stops its ray (alternative: skip it); the energy test is `E > 0` on arrival; liquids are pushed out, not deleted. Unknown: real ray count, stop versus skip, `>` versus `>=`, partial damage across rays | As stated; verify with the wiki's "2-3 px of rock" for `MINE` (vector MV-17) | MR D6, Open 7; SIM Open 4, 7 |
| DN-MAT-08 | [User, conditional] Durability of concrete | (a) use the game-data value 0 (concrete, ice and glass removable by any ray with enough energy, `hp` still protects); (b) the wiki table's 8 for concrete. Decide only if an MVP spell has `max_durability_to_destroy` < 8 (none does; `EXPLOSION_LIGHT` is 2 and is not MVP) | (a) | MR D7, Open 9 |
| DN-MAT-09 | [Default] `req_lifetime` and gas lifetime | Ignore `req_lifetime` (cement sets on first contact); gas and other lifetimes through the per-material unit of SIM-R35; alternative: widen counters to `u16` | As stated | MR D8, Open 6 |
| DN-MAT-10 | [Default] Blob geometry | Euclidean disc `dx^2 + dy^2 <= r^2` around the reacting cell, restricted to the matched material; alternative: Chebyshev square. MVP blobs have radius <= 6 | As stated | MR D9, Open 5; SIM-R38 |
| DN-MAT-11 | [Default] Three-input reactions and ReqReactions | Dropped from the MVP (32 and 5 rows); semantics UNVERIFIED | As stated | MR D10, Open 4 |
| DN-MAT-12 | [User, low impact] Reactions whose literal outputs look swapped (alcohol with lava, `coal` with `fire`, `[lava]` with `[meltable_to_lava]`) | (a) literal positional outputs, an output `[fire]` with no input tag becomes `fire`; (b) the "intent" reading (alcohol turns to gas, fire stays) | (a) | MR D11 |
| DN-MAT-13 | [Fact] Remaining data facts | Default of `_inherit_reactions` when unset (treated as 0); whether material contact damage ticks every frame (wiki) or more slowly; which materials count as "air" for `requires_oxygen` (gases, steam, smoke?) | Unset = 0; every frame; air, gas and fire neighbours (FIRE-R05) | MR Open 8, 10, 11 |
| DN-MAT-14 | [Settled] Numeric ids and Box2D | Numeric ids = rank by `xml_order`, `u16`, mapping hashed in `content_hash`; no Box2D materials (rigid bodies are DN-SPELL-03) | As stated | MR D12, D13 |

## 3. Wands and casting ([wand-casting.md](wand-casting.md))

| ID | Question | Options | Recommended default | Origin |
|---|---|---|---|---|
| DN-WAND-01 | [Settled 2026-10-26: option (a), implemented in `crates/game`] Recharge when the wand's own draw meets an empty deck | (a) a deck that is empty at the end of a click starts a recharge however it became empty (wiki behaviour); (b) pure `gun.lua` reading, which would leave the wand stuck. Related unknowns: what counts as a "projectile" for the 1-frame no-projectile cast delay, and whether the 1-frame clamp rounds | (a) | WAND WD1, R51, Open 1 |
| DN-WAND-02 | [User] Expose the Unlimited Spells perk in benchmark tasks | (a) not in suite v1 (finite-use Divide chains stay reproducible, KV-05 gives 50 not 100); (b) as a per-task flag later | (a) (the page states no default; this is the recommendation) | WAND WD2, S6 |
| DN-WAND-03 | [User, post-MVP] `IF_HALF` toggle | (a) one global flag shared by all wands, included in the state hash (as in Noita); (b) one flag per wand. Entity counting for `IF_ENEMY` and `IF_PROJECTILE` must use a deterministic order either way | (a) | WAND WD3, S7 |
| DN-WAND-04 | [User] Wand generation tables | (a) normal tables only; benchmark tasks use fixed hand-made wands; (b) "better wand" tables (no fast archetype, 20 % slow) for early biomes | (a) (the page states no default; wand generation comes after the casting core) | WAND WD4, S8 |
| DN-WAND-05 | [Fact] Always-cast order | Assumed: always-casts are played first, before the draws and the mana snapshot (engine order unknown) | As assumed (R12, R70) | WAND Open 2 |
| DN-WAND-06 | [Fact] Formation geometry | Spacing `2A/(n-1)` for A < 180 or `2A/n` for A >= 180, first projectile on top (UNVERIFIED); needed once formations are rendered | As stated; confirm with the hosted wand simulator | WAND Open 3, conflicts table |
| DN-WAND-07 | [Fact] Wand-generation provenance | `gun_procedural.lua` is not stored locally; R90 to R95 rest on earlier research and the wiki. Re-fetch it from NathanSnail/noitadata to verify the Spells/Cast bump, fast-archetype terms, tier-10 mana level and the `RandomDistribution` density | Use the page values; re-fetch before implementing wand generation | WAND Open 4 |
| DN-WAND-08 | [Fact] In-game confirmation | Finite-use Divide chains (KV-05) and the stale `start_reload` edge (a wrap followed by `reloading` in the same click) | Follow the Lua reading | WAND Open 5 |
| DN-WAND-09 | [Default] Fixtures and Lua-only actions | Three expected values of `wand-cast-test-cases.json` are wrong (draw_01 `mana_spent` 10 must be 15, greek_01 cast delay 105 must be 114, refresh_03 is replaced by KV-01): fix the fixture file before use. Ignore the 69 Lua-only actions; none is needed by the benchmark so far | As stated | WAND Verification table, Open 6, S9 |
| DN-WAND-10 | [Default] Reference simulator licence | The licence of `salinecitrine/noita-wand-simulator` is not recorded: reference only; the hosted simulator (tinker-with-wands-online.vercel.app) may serve as a black-box oracle for extra vectors | As stated | WAND Open 7 |
| DN-WAND-11 | [Settled] Casting scope and simplifications | All cards identified (no free first use); `order_deck` shuffle uses the `spells` RNG stream (DET-R04); stage 1 implements R01-R64, R70-R72, R80, R81, R82, R86 and stage 2 the Greek letters, Duplication, Requirement, Zeta and random-draw spells (scope list: DN-SPELL-01); engine-side timing follows the wiki; counters tick once per frame, one click per frame | As stated | WAND S1-S5, S10 |

## 4. Spells ([spells.md](spells.md))

| ID | Question | Options | Recommended default | Origin |
|---|---|---|---|---|
| DN-SPELL-01 | [User] Scope ladder and which D2 spells | MVP-50 (35 D0, 6 D1, 9 D2), then all 127 D0, then D1 features by spell count, then D2 families by value for wand building. benchmark.md plans about 300 spells and D0 + D1 = 237, so about 60 D2 spells are needed: suggested deck-ops 42 + trajectory 12 + black/white holes 6 | The suggestion; the wand stage-2 spells (Greek, Duplicate, Requirement, Random) belong to the 42 deck-ops | SP S1; WAND S4 |
| DN-SPELL-02 | [User] Damage storage unit | (a) internal floats in `noita_core` (bit-faithful to `damage_*_add`), display values in observations; (b) display values everywhere (agent-readable); note `spells.json` already stores display values for `damage` and `damage_modifier` | (a) | SP S2, SPELL-R03 |
| DN-SPELL-03 | [User] Physics-body projectiles and rigid bodies | (a) no Box2D and `solid` materials map to Static; `BOMB`, `DYNAMITE`, boxes and rocks become kinematic "rolling" bodies in the pixel sim (gravity, bounce, friction, fuse, hit points), keeping the hooks of SIM-R86; (b) no bodies at all (replace `BOMB` and `DYNAMITE` of the MVP-50); (c) real rigid bodies later through rapier (pipeline in SIM-R87) | (a). The MVP-50 needs `BOMB` and `DYNAMITE` (PHYS_BODY); accept the divergence in rolling and throw behaviour. | SP S3; MR D13; SIM S1, SIM-R85..R87 |
| DN-SPELL-04 | [User, resolved by the sim page] Terrain carving model for spells | (a) the ray model (DUR-R01, DUR-R02, SIM-R50..R52); (b) a simplified disc carve with a durability cut-off. Loose-ground collapse around big craters (SPELL-R35) is optional and not simulated | (a); the sim and materials pages already specify it, please confirm | SP S4; SIM-R50; MR DUR |
| DN-SPELL-05 | [User] Progress flags | (a) all 422 spells unlocked, `spawn_requires_flag` ignored but kept in the data; (b) gate by flag in a future "exploration" task variant | (a) | SP S5, SPELL-R44 |
| DN-SPELL-06 | [User] Runtime `spells.json` schema | Generated from `research/spells.json` plus `spell_taxonomy.json`, game file over wiki, version pinned (SPELL-R10). Open: which fields agents may see (`draw_count`, `trigger`?), and that field renames bump benchmark versions because `content_hash` covers the file | Keep `game_id` as key and display-unit damage; expose only wand-editor numbers (OBS-R05) | SP S10, Open 12 |
| DN-SPELL-07 | [Default] Deferred families and cosmetics | Easter-egg notes (13), summoned creatures (15), X-ray, portal, wand ghost, Zeta, Cessation and All-Spells deferred; colours, screenshake, gore, ragdoll, light parsed and ignored; recoil, knockback, status effects and material emission kept; minimal status set (wet, oiled, bloody, on fire, frozen, poisoned or toxic, electricity stun); perks and extra modifiers not modelled | As stated | SP S6-S9 |
| DN-SPELL-08 | [Default] Game versus wiki version skew | `PROJECTILE_THUNDER_FIELD` / `PROJECTILE_GRAVITY_FIELD` uses 6 (game) versus 3 (wiki); `VACUUM_POWDER` mana 40 versus 50; a few spawn probabilities | The game file wins; re-check against the current game build when it can be fetched | SPELL-R10, Open 8 |
| DN-SPELL-09 | [User] Negative projectile damage | When a modifier pushes damage below zero (`CHAIN_SHOT` -5 or `PIERCING_SHOT` -15 on `LIGHT_BULLET`, damage 3): (a) clamp at 0; (b) allow negative (heals) | (a) (recommendation; no source states the engine rule) | SP Open 6 |
| DN-SPELL-10 | [Fact] Projectile runtime details | Integrator order and the unit of `gravity_y`; `lifetime_randomness` as an inclusive integer draw, `lob_min/lob_max`, `ProjectileComponent.friction`; spread semantics (+-spread versus total arc); Luminous Drill travel (47 or 33 px) and where its 4-frame timer payload spawns; explosion damage falloff inside the radius and how the R33 floor interacts with a Divide-reduced radius; the Fly Up/Down clamp bypass; direct-hit damage of `CRUMBLING_EARTH` | Use the page assumptions; calibrate against footage or the black-box simulator | SP Open 1-5, 11, 13 |
| DN-SPELL-11 | [Fact] Classification inputs | 16 spells whose side-entity or extra-entity XML is not saved locally (SPELL-R42); whether the unconditional `c.*` lines of the 44 complex spells are complete in `action_effects_raw`; what damages `PROJ_HP` projectiles (Bomb hp 12.5); Explosive Detonator and Fizzle semantics | Do not implement a D2 spell from wiki text alone: read `spell_actions_lua.json` per spell (SPELL-R41) | SP Open 7, 9, 10 |

## 5. Entities and damage ([entities-damage.md](entities-damage.md))

| ID | Question | Options | Recommended default | Origin |
|---|---|---|---|---|
| DN-ENT-01 | [User] Multitype damage | (a) single-type damage in the MVP with a flag for later extension; (b) full bitflags (Melee-Bite, Melee-Ice, Fire-Explosion; immunity to any flagged type nullifies the hit, multipliers summed per type) | (a) | ED ED-D1, DAMAGE-R08, Open 5 |
| DN-ENT-02 | [Conflict, User] Projectile piercing | (a) projectiles hit once and die (the page's MVP simplification); (b) implement `penetrate_entities` (once-per-entity hit list) and `on_collision_die 0` with `damage_every_x_frames` now. The MVP-50 needs it: `LIGHTNING`, `LUMINOUS_DRILL`, `PIERCING_SHOT`, `DELAYED_SPELL` | (b) (small per-projectile list) | ED ED-D2, DAMAGE-R20; SP SPELL-R25, SPELL-R45 |
| DN-ENT-03 | [Fact] Toxic and Poisoned tick cadence | 1.5 s (Damage Types page) versus 1 s (Status Effects page) | 1 s (conservative, more lethal) | ED Open 1, DAMAGE-R18, R19 |
| DN-ENT-04 | [Default] i-frame refresh | Vanilla (no refresh on hit, player starts with 60 f) versus the mod behaviour (refresh to 60 on each hit) | Vanilla; document for AI tuning | ED Open 2, DAMAGE-R10 |
| DN-ENT-05 | [Default] Stains | Statuses come only from spells with fixed durations (Wet 720 f ...); no passive stain persistence or stain drop formula (`VERLET_STAIN_DROP_CHANCE_DIV` 200 and `GAMEEFFECT_STAINS_DROP_FASTER_DROP_CHANCE_MULTIPLIER` 10 stay unused). Consequence: standing in water does not apply Wet | As stated; defer stain physics | ED Open 3, MVP simplifications |
| DN-ENT-06 | [Default] Crit timing for explosions | A projectile and its explosion roll crit independently | As stated | ED Open 4 |
| DN-ENT-07 | [Default] Enemy set and factions | The 8 core enemies without variants (Hämis, Hurtta, Haulikkohiisi, Snipuhiisi, Hämähäkki, Stendari, Nelikoipi, Konna); fixed faction relations (no More Love or More Hatred perks); levitation anti-tap delays included | As stated | ED MVP simplifications |
| DN-ENT-08 | [Fact] Fire damage unit | Whether `fire_damage_amount` (0.2) applies per frame or per second; the wiki states the effect as 2 % of max HP per second with max HP clamped to >= 0.8 internal | Use the wiki statement | ED DAMAGE-R14; MR FIRE-R12 |

## 6. Agent benchmark ([benchmark.md](benchmark.md))

| ID | Question | Options | Recommended default | Origin |
|---|---|---|---|---|
| DN-BEN-01 | [User] Aim quantisation | (a) integer degrees in text mode, optional 24 bins (15 degree steps) or continuous `f32` in RL, both logged in the header; (b) continuous everywhere | (a) | BEN Open 1, ACT-R02 |
| DN-BEN-02 | [User] Hash cadence | (a) a state hash every step (per-chunk Merkle, under 1 % overhead); (b) every N frames | (a) | BEN Open 2, DET-R02 |
| DN-BEN-03 | [User] Default of the 1 px/char `near` inset | (a) on for digging and aiming tasks (1, 4, 6, 8), off for navigation (7); (b) always on (about 400 more tokens) | (a) | BEN Open 3, OBS-R02 |
| DN-BEN-04 | [User] Shaped rewards in RL mode | (a) allowed per task, documented per task version, never part of the primary score; (b) none | (a) | BEN Open 4 |
| DN-BEN-05 | [User] Observation modality | (a) lock modality, task-independent rendering, modality-specific assists only; (b) task-optimised subsets | (a) | BEN Open 5, ANTI-R05 |
| DN-BEN-06 | [User] Sticky actions | (a) client-side, recorded in the header; (b) engine-side | (a) | BEN Open 6, DET-R01 |
| DN-BEN-07 | [User] Task prompt style | (a) generic objective, hints as an assist track; (b) task-specific instructions | (a) | BEN Open 7, ANTI-R06 |
| DN-BEN-08 | [Default] World size | 512x512 in v1; revisit about 1024x1024 in v2 if agents plateau | As stated | BEN Simplifications; SIM-R14 |
| DN-BEN-09 | [Default] Scope cuts of v1 | Enemies neither mutate nor breed (fixed waves); no permadeath world corruption; no NPC factions or karma; wand capacity 3 to 8 slots per task (relax for `wand_dps_optimization` variants); spell pool given in `wand_dps_optimization`; no mod support | As stated | BEN Simplifications |
| DN-BEN-10 | [Conflict] Dtype of the RL `grid` material channel | (a) an observation material index from the fixed legend, `u8`, at most 255 entries (40 in the MVP) (applied in OBS-R07); (b) a `uint16` channel carrying the simulation id; (c) an extra remap channel | (a) | BEN OBS-R07, OBS-R03; SIM-R03; DN-MAT-02 |

## 7. World generation and frontend

| ID | Question | Options | Recommended default | Origin |
|---|---|---|---|---|
| DN-WORLD-01 | [Resolved] Seed derivation for world generation | research/worldgen.md sections 6.2 and 9 truncate `episode_seed` to 32 bits; benchmark.md defines `episode_seed = blake3(task_id, task_version, seed_index)` and the `worldgen` stream seed `blake3(seed, "worldgen")` per DET-R04 | benchmark.md wins; worldgen.md R10 derives chunk randomness statelessly from the `worldgen` stream seed and chunk coordinates via blake3 | WORLD-R10; BEN SEED-R01, DET-R04 |
| DN-WORLD-02 | [Superseded 2026-10-26] Generator strategy | Was: layered fBm caves instead of Wang tiling. Now: Noita-style fixed biome map + herringbone Wang tiles + pixel scenes | Follow task `world-design.md`; see [v1-scope.md](v1-scope.md) | WORLD-R07; user review 2026-10-21 |
| DN-WORLD-03 | [Conflict, resolved] Material palette of the generator | research/worldgen.md listed `copper`, `rock_static_wet`, `grass`, `fungus`, `water_ice` outside MVP-40 | Restrict generator to approved set (DN-MAT-01); page edited to remove out-of-scope materials | WORLD-R03; MR MVP-40 |
| DN-WORLD-04 | [Settled] World extent | Fixed-size game world 2048×1536, no streaming, active rect; Noita's 35,840 px width and depth not reproduced | As stated in WORLD-R01 (benchmark 512×512 arena per WORLD-R11) | WORLD-R01, WORLD-R11; SIM-R14 |
| DN-WORLD-05 | [User] Terrain aesthetics calibration | fBm parameters (freq 0.05, persistence 0.5, depth threshold 0.3–0.6) chosen for simplicity; empirically verify cave appearance vs vanilla Noita | Proceed with defaults; screenshot-compare against vanilla footage for tune feedback | WORLD-R07, Open 1 |
| DN-WORLD-06 | [User] Ore and liquid distribution | Perlin veins freq 0.02 too uniform (UNVERIFIED); should Voronoi clustering mimic real veining? | Defer Voronoi to v2; current direct freq acceptable for MVP | WORLD-R07, Open 2 |
| DN-WORLD-07 | [Fact] Rest-room accessibility | Are rest rooms (safe chambers every 8 chunks y) always reachable from main caves (no isolated pockets)? | Recommend BFS validation at generation time | WORLD-R07, Open 4 |
| DN-FE-01 | [User] Toolkit for the wand editor | (a) hand-rolled immediate-mode UI (recommended, full control, no dependency); (b) `egui-macroquad` (full widget library but macroquad 0.4 compatibility UNVERIFIED) | (a) for MVP; test egui-macroquad 0.22.1 before committing to egui post-MVP | FE-R12, FE-D1 |
| DN-FE-02 | [Default] Fonts, fullscreen, mobile, accessibility | Built-in font only (custom fonts post-MVP); windowed fixed-integer zoom; mobile touch and text-to-speech out of scope for v1 | As stated in FE-R10, FE-R12, our Simplifications | FE-R10, FE-R12 |
| DN-FE-03 | [Default] Multi-channel grid observations | RL observations single-channel material ID for v1; multi-layer (RGB/RGBA with flags, entity class) deferred if agents need feature extraction | As stated; extend per benchmark.md OBS-R07 if needed | FE-R04, FE Simplifications |
| DN-FE-04 | [Fact] Async texture upload necessity | Is 128×128 upload cost (<1 ms FE-R05) ever a bottleneck on MacBook Air M-series? | Profile before optimizing; async upload is complex, likely unnecessary for MVP | FE-R05, Open 6 |

## 8. Task-document drift (PRDs and design notes versus this KB)

The PRDs under `.trellis/tasks/` were written before the pages. Follow the page; correct the PRD when the child task starts.

| ID | Where | Task document says | KB says (wins) |
|---|---|---|---|
| DN-DRIFT-01 | pixel-sim-core PRD | `Cell` with a last-updated parity bit; RNG hashed per chunk and frame from `(world_seed, frame, chunk_index)` | `UPDATED` flag cleared at frame end, parity forbidden (SIM-R15); stateless per-cell hash (SIM-R70, DN-SIM-01, DN-SIM-05) |
| DN-DRIFT-02 | pixel-sim-core PRD | Material list `dirt`, `gravel`, `obsidian`, `honey`, `fungus`, `brick`, `whiskey`, `toxic sludge` | Ids are `soil`, no gravel, no obsidian (lava plus water gives `rock_static`, xml_065), `honey` and fungus are not in MVP-40, `templebrick_static`, `alcohol`, `radioactive_liquid` (MR MVP-40; DN-MAT-01) |
| DN-DRIFT-03 | pixel-sim-core PRD | Powders "settle after N idle frames" (dirty-rect sleep) | No per-cell sleep counter; dirty rects with wake margin 12 and keep-awake (SIM-R10..R12) |
| DN-DRIFT-04 | pixel-sim-core PRD | `explode(x, y, radius, power)` destroys cells whose durability is below `power * falloff` | Ray model with `ray_energy`, `hp` cost and a durability gate (MR DUR-R01..R03, SIM-R50..R52) |
| DN-DRIFT-05 | pixel-sim-core PRD | Fire is "extinguished by water (steam)" | Water boils but does not clear BURNING; burning ends by fuel or loss of air (MR FIRE-R08) |
| DN-DRIFT-06 | pixel-sim-core PRD | A 512x512 world of sand and water steps in under 4 ms per frame | At least 5x realtime, at most 3.33 ms per frame (SIM-R81; parent PRD) |
| DN-DRIFT-07 | wand-spell-system PRD | Explosion damage "with falloff" | Damage falloff inside the radius is UNVERIFIED (SPELL-R31, DN-SPELL-10); knockback falls off with distance (DAMAGE-R12) |
| DN-DRIFT-08 | playable-frontend PRD | Acceptance: the player can "take fall damage" | Only fish and props take fall damage; the player has `falling_damages = 0` (entities-damage.md Pitfall 9) |
| DN-DRIFT-09 | agent-benchmark PRD and research/worldgen.md | Task names `wand_dps`, `survive`, `chain_reaction` (PRD); `survive_enemies`, `gather_resources` (worldgen research) | benchmark.md and its research file name the tasks (for example `wand_dps_optimization`, `dig_to_depth`, `kill_targets`, `reach_portal`, `cross_lava_pool`); freeze one suite list before implementing tasks |

## Sources

KB pages: `./.trellis/spec/game-design/{pixel-simulation,materials-reactions,wand-casting,spells,entities-damage,benchmark,worldgen,frontend,index,glossary}.md` (the sections "Our simplifications", "MVP Simplifications", "DECISION-NEEDED" tables and "Open questions" of each page).

Task documents: `./.trellis/tasks/archive/2026-10/10-07-noita-clone/prd.md` and `design.md`; child PRDs `./.trellis/tasks/archive/2026-10/10-07-{pixel-sim-core,wand-spell-system,agent-benchmark,playable-frontend}/prd.md`.

Research files (`./.trellis/tasks/10-16-noita-cogbench/research/`): `worldgen.md`, `frontend-tech.md`, `benchmark-design.md`, `materials.json`, `spells.json`, `wand-cast-test-cases.json`, `player-stats.json`, `status-effects.json`, `entities-damage.md`, `rust-prior-art.md`.

Wiki: https://noita.wiki.gg/wiki/Documentation:_Reaction , /Documentation:_ConfigExplosion , /Materials , /Status_Effects , /Damage_Types .
