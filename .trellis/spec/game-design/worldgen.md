# World Generation

**Purpose**: Reference for chunk-local deterministic world generation, seed derivation per subsystem, biome layout facts from Noita, spawn tables, and the benchmark 512×512 arena. Used by `noita_core::worldgen` module, task generators, and when initializing world state. Cite rule IDs (WORLD-R, WORLD-T) in code and tests. Normalizes Noita's known structure (Holy Mountain spacing, biome materials, Wang tiles) against our simplified generator (fBm caves, liquid pools, spawn markers).

**Frame rate**: 60 updates per second. All timers in frames (f). Lengths in cell pixels (1 px = 1 cell). Y grows down. **PROTO-R04** (benchmark.md) specifies frame counts as the only time unit; seeds are u32/u64 integers never frame-dependent.

---

## Normative Rules

### A. Noita World Reference (Facts)

**WORLD-R01: World dimensions.** The full Noita world is 35,840 px (70 chunks) wide × ~17,408 px (34 chunks) vertically playable. Grid: chunk (cx, cy) where −35 ≤ cx ≤ 34, −14 ≤ cy ≤ 33 (70×48 chunks). Each chunk = 512×512 px (8×8 grid of 64×64 sim sub-cells; pixel-simulation.md SIM-R02). World origin (x,y)=(0,0) is at chunk (0,0). Source: [W] Modding: Making a custom environment, research/biome_layout_from_noitamap.json.

**WORLD-R02: Vertical biome strata.** Progression biomes stacked by chunk y with Holy Mountains at y-intervals:
- y=−14 to −1: Solid walls (tower, no generation)
- y=0: Forest/Surface, trees, lakes
- y=1–6: Mines (Coal Pits branch), coal ore, weak enemies
- y=7–9: Holy Mountain 1 (Brickwork, portal, shop, altar)
- y=10–16: Snowy Depths, ice, cold enemies
- y=17–20: Holy Mountain 2
- y=21–26: Hiisi Base, steel, military enemies, laser grids
- y=27–29: Holy Mountain 3
- y=30–34: Underground Jungle, fungus, worms
- y=35+: The Vault, Temple, Laboratory (beyond MVP)

Each biome is 5–8 chunks tall; Holy Mountains occupy 3–4 chunks. Source: [G] biome_layout_from_noitamap.json, [W] Biomes.wikitext.

**WORLD-R03: Noita material composition.** Per-biome materials are listed in research/biome_material_components.json. Coalmine: coal 51–55%, soil 45–53%, sand 53–95%, water rare. Snowy Depths: snow, ice, rock, water. Hiisi Base: steel, brickwork, concrete. Underground Jungle: fungus, rock, soil, vegetation. Source: [G] biome_material_components.json.

**WORLD-R04: Holy Mountain structure.** Each mountain is a fixed procedural chamber: Brickwork (durability 14), Teleportatium basins (2–8 portals), shop (5–10 wands), health pool (256 px), spell refresher (128 px), perk altar (1 unit, 3 perks), training statues (2×30k HP), worm crystal room (256 px), exit tunnel (512 px) with collapse curse (1240 frames = 20.7 s, 2 curse/frame). Submerged variant (10%): basin filled with blood, water, toxic, oil, or lava. Source: [W] Holy Mountain, [G] research/worldgen.md §4.

**WORLD-R05: Wang tile terrain.** Noita uses herringbone Wang tiles (Sean Barrett method) from PNG templates (e.g., coalmine.png 348×448 px, 13 px tile short side). Pixel interiors encode materials via `wang_color` ARGB lookups (white = BIOME_FILL resolved by fBm, black = air). Edge colors (6–12 per biome) constrain tile compatibility. Placement: sample biome-scale noise, select tile variant, check 4-neighbor edge colors, render tile raster to chunk. Reused tiles cached by (biome, variant). Source: [G] wang_template_stats.json, [W] World Generation.

---

### B. Clone Generator Design

**WORLD-R06: Chunk-local determinism per DET-R04 (benchmark.md).** Each chunk's terrain, spawns, and hazards are fully determined by `(seed, chunk_x, chunk_y)` via `chunk_seed = blake3(episode_seed ‖ chunk_x ‖ chunk_y) & 0xFFFFFFFF`. No per-chunk RNG stream; cell randomness is stateless (SIM-R70). Chunk generation is single-threaded and frame-independent. Source: [DES] benchmark.md DET-R04, SEED-R01.

**WORLD-R07: Layered fBm caves (MVP simplification).** Instead of Wang tiles, generate terrain via stacked frequency-modulated Perlin noise:
- Layer 1 (base): freq=0.05, 4 octaves, lacunarity=2.0, persistence=0.5 → normalized ∈ [−1, 1]
- Threshold: 0.3 + 0.3×depth_factor (clamp depth ∈ [0,1] per y/10000) → denser deeper
- Cell = rock if noise > threshold, else air
- Layer 2 (ore): freq=0.02, rare veins if noise > 0.7 (coal y>5000), ore (copper y>8000, gold y>10000)
- Layer 3 (liquid): freq=0.01, water/lava/oil pools in air pockets, depth-gated
- Layer 4 (rest rooms): sparse safe chambers (64×64) every 8 chunks y, hashed placement

Source: [DES] our design choice over Wang tiling for determinism and simplicity.

**WORLD-R08: Spawn table determinism.** Entities spawn seeded per (chunk, biome): compute spawn_count from chunk_seed RNG (3–8 enemies/chunk), iterate spawn_pool (biome-specific list), roll entity type, find random air pixel in chunk, place entity. No cross-chunk entity moves at spawn time. Source: [G] spawn_tables_from_lua.json, [DES] seeded per-chunk placement.

**WORLD-R09: Holy Mountain placement (clone).** Place brickwork-filled mountain at designated y-coords (chunk y = 7, 15, 23, 31 in the progression). Fill with procedural portal, shop, altar markers as fBm patterns (high-noise → interior decoration). Collapse exit tunnel seeded per chunk. Source: [DES] simplified from Noita's per-mountain generator.

---

### C. Seed Derivation

**WORLD-R10: Multi-layer seed hierarchy (DET-R04, benchmark.md).** Per benchmark.md SEED-R01, `episode_seed = blake3(task_id ‖ task_version ‖ seed_index)`. From this, chunk seeds are derived:
```
chunk_seed   = blake3(episode_seed ‖ chunk_x ‖ chunk_y) & 0xFFFFFFFF
```
Then seed per subsystem within the chunk:
```
worldgen_rng = PCG32(chunk_seed)
spawn_rng    = PCG32(blake3(chunk_seed ‖ "spawn") & 0xFFFFFFFF)
cells_rng    = stateless hash per SIM-R70 (not consumed sequentially)
```
This ensures: (1) different seed_indices → different worlds, (2) same world replayed identically, (3) no RNG collision across subsystems or chunks. The 32-bit truncation supports PCG32 seeding. Source: [DES] SEED-R01/R02, benchmark.md; DET-R04.

---

### D. Benchmark Arena (512×512)

**WORLD-R11: Fixed arena for agent tasks.** Use single chunk (0, 0) at world origin (0, 0) px as the entire episode world:
- Zone A (y=0–64): air, rest platform, player spawn (256, 32)
- Zone B (y=64–256): fBm terrain, 4–6 weak enemies, ore deposits
- Zone C (y=256–384): deep cave, 8–12 medium enemies, lava pool (y=320–384, x=100–400)
- Zone D (y=384–512): abyss, hazard, 1–2 boss-class enemy, goal marker (256, 450)

Source: [DES] benchmark.md describes arenas; our instantiation.

**WORLD-R12: Arena generation.** Generate chunk (0,0) with episode_seed, override zones (carve top 64 px to air, inject lava), spawn player and goal deterministically. Task-specific variants adjust zone hazards and enemy counts per difficulty knobs. Source: [DES] design simplification.

---

## Key Numbers

| Constant | Value | Unit | Notes |
|---|---|---|---|
| **Dimensions** | | | |
| Chunk size | 512 × 512 | px | 8×8 grid of 64×64 sim sub-cells (SIM-R02) |
| World width (full) | 70 | chunks | −35 ≤ cx ≤ 34 |
| World height (playable) | 48 | chunks | −14 ≤ cy ≤ 33 |
| **Biome Spacing** | | | |
| Mines depth | y=1–6 | chunks | 6 chunks, materials: coal, soil, sand, water rare |
| Holy Mountain height | 3–4 | chunks | Brickwork (dur 14), ~2.5k frames to traverse |
| Snowy Depths depth | y=10–16 | chunks | 7 chunks, snow/ice/water |
| Hiisi Base depth | y=21–26 | chunks | 6 chunks, steel/brickwork/hazards |
| Jungle depth | y=30–34 | chunks | 5 chunks, fungus/vegetation/worms |
| **Terrain Generation** | | | |
| fBm base frequency | 0.05 | octaves^−1 | 4 octaves, lacunarity 2.0, persistence 0.5 |
| Ore frequency | 0.02 | octaves^−1 | Rare veins, depth-gated |
| Liquid frequency | 0.01 | octaves^−1 | Water, lava, oil pools |
| Depth threshold | 0.3–0.6 | noise | 0.3 + 0.3×(y/10000) |
| **Spawning** | | | |
| Enemies per chunk | 3–8 | count | Seeded per (cx, cy) |
| Rest room spacing | 8 | chunks (y) | 64×64 safe chambers |
| **Benchmark Arena** | | | |
| Zone A (rest) | y=0–64 | px | Air, player spawn (256, 32) |
| Zone B (main) | y=64–256 | px | 4–6 enemies, ore |
| Zone C (deep) | y=256–384 | px | 8–12 enemies, lava pool |
| Zone D (abyss) | y=384–512 | px | Hazard, boss, goal (256, 450) |
| **Collapse Curse** | 1240 | frames | Holy Mountain exit: 2 damage/frame × 1240 = 41 total |
| **Materials (MVP subset)** | | | |
| Terrain strata | rock_static, sand_static, coal_static | ids | Static materials per biome (see materials-reactions.md MVP-40) |
| Hazards | lava, water, acid, radioactive_liquid | ids | Depth-gated liquid pools |
| Ores | coal, gold | ids | Rare (coal y>5000, gold y>10000) |

---

## Data Files

| File | Role | Records |
|---|---|---|
| `materials.json` | Material IDs and properties (MVP-40 subset used) | 466 total; 40 in MVP |
| `biome_layout_from_noitamap.json` | Chunk→biome mapping, bounding boxes | 8+ biomes |
| `biome_material_components.json` | Per-biome fBm noise parameters for material strata | Coalmine, Snowy, Hiisi, Jungle |
| `spawn_tables_from_lua.json` | Entity pools per biome and spawn rates | g_small_enemies, g_big_enemies, etc. |
| `wang_template_stats.json` | Wang tile image dimensions, edge colors, tile counts (reference, not used in MVP) | 4+ biomes |
| `noita-engine-constants.json` | Engine hardcoded values (chunk size, frame rate, etc.) | ~50 constants |
| `seeds/public-v1.json` | Public seed indices for reproducible runs | 20 per task × 10 tasks |

Load order: materials.json first (defines IDs), then biome/spawn tables. At `reset`, derive `episode_seed` (WORLD-R10), cache generated chunks by `(cx, cy)`.

---

## Worked Examples / Test Vectors

| ID | Setup | Expected |
|---|---|---|
| WORLD-T01 | chunk_seed from episode_seed (0x12345678), cx=0, cy=0 | Identical terrain, spawn positions on replay with same seed; differ with different seed by >50% cell material change |
| WORLD-T02 | Benchmark arena (seed=0), zone B (y=64–256) | 4–6 enemies placed in air cells, no overlap, all inside zone bounds |
| WORLD-T03 | fBm threshold (depth y=256, noise=0.45) | Threshold = 0.3 + 0.3×(256/10000) = 0.3076; noise=0.45 > 0.3076 → rock |
| WORLD-T04 | Holy Mountain at cy=7 with seed=0 | Chunk filled with brickwork, portals at top, altar center, exit tunnel bottom |
| WORLD-T05 | Ore placement (coal y=1000, noise=0.72, freq=0.02) | Noise > 0.7 → place coal; noise < 0.7 → skip |
| WORLD-T06 | Lava pool (zone C, y=320–384, x=100–400) | Lava cells stable (not flowing off-world in first 600 frames) |
| WORLD-T07 | Spawn determinism | Same (cx, cy, seed) → identical spawn_count, enemy order, positions across threads (serial merge, SIM-R74) |

---

## Pitfalls & Common Misreadings

1. **"Chunk coordinates are world pixels."** Wrong: chunk (cx, cy) maps to world px via `(cx × 512, cy × 512)`. Chunk (0, 0) = world (0, 0) px top-left; chunk (−1, −1) = world (−512, −512) px.

2. **"Different seed → completely different world."** Partially true: episode_seed change flips terrain throughout, but biome *structure* (Holy Mountain y-coords, spawn pools) stays the same. Depth and progression are deterministic per task.

3. **"fBm threshold is global."** Wrong: depth-gated. Deeper chunks (higher y) use higher thresholds (denser terrain), creating natural stratification.

4. **"Spawn seeding leaks across chunks."** No: spawn_rng is per-chunk (blake3 deriv), and placement is within chunk bounds only. Cross-chunk entity moves are physics-driven (SIM-R74), not seeded.

5. **"Water always flows downward."** Correct: liquid motion is physics-driven per SIM-R31. Water entering boundaries wraps deterministically (boundary material is rock_static, no flow). Dams and pools are stable if enclosed.

6. **"Holy Mountains are rare."** Wrong: they are *guaranteed* at specific y-layers (y=7, 15, 23, 31 in progression). Every playthrough has the same mountain locations.

---

## MVP Simplifications

| Area | Noita | Our Clone | DECISION-NEEDED |
|---|---|---|---|
| Terrain algorithm | Wang herringbone tiles + pixel scenes | Layered fBm noise + procedural markers | WG-D1: Consider Wang tiles in v2 if fBm lacks biome flavor. **Default:** fBm (simpler, seeded per-chunk). |
| Biome variety | 8+ unique visual templates | Single fBm+material-swap per y-range | WG-D2: Per-biome noise scale tuning vs global params. **Default:** global params (less variance, easier repro). |
| Liquid stability | Complex flow physics + settling | Liquid falls via SIM-R31, boundaries are static | WG-D3: Inject "still" liquid pools seeded, or let physics settle. **Default:** pre-settled (faster load). |
| Ore distribution | Complex Perlin + Voronoi clusters | Simple freq-gated Perlin (51–55% coal, etc.) | WG-D4: Add Voronoi clustering for veins. **Default:** direct freq (OK for MVP). |
| Spawn persistence | Entities persist across saves | Chunk-based spawn on generation; re-spawn on re-enter | WG-D5: Cache spawned entities or regenerate? **Default:** regenerate (simpler, no serialization). |
| World size | 35,840 × 17,408 px (70×48 chunks) | 512×512 px (1 chunk) for benchmark | WG-D6: Expand to 2048×1536 (4×3 chunks) in v2 if agents plateau. **Default:** 512×512 (trainable). |

---

## Open Questions

1. **fBm parameter tuning:** Current freq/persistence chosen for simplicity; empirically verify cave aesthetics match Noita's feel. Reference: compare screenshots of generated Mines vs vanilla Coalmine.

2. **Ore clustering:** Perlin at freq 0.02 is too uniform; should we add Voronoi cells (blob clusters) to mimic natural veining? Low priority (ores are visual loot, not core mechanics).

3. **Liquid pool size distribution:** Should pool radius be seeded (variable size) or fixed? Current: freq-gated (variable), but distribution formula UNVERIFIED.

4. **Rest room accessibility:** Are rest rooms always reachable from main caves (no isolated pockets)? Recommend BFS validation at generation time.

5. **Spawn exclusion zones:** Should enemies spawn far from player spawn (256, 32) to avoid instant collisions? Current: purely random air pixel; recommend ≥100 px minimum distance for safety.

---

## Sources

**Noita facts (engine reference):**
- https://noita.wiki.gg/wiki/Modding:_Making_a_custom_environment
- https://noita.wiki.gg/wiki/World_Generation
- https://noita.wiki.gg/wiki/Holy_Mountain
- https://noita.wiki.gg/wiki/Biomes (Mines, Snowy Depths, Hiisi Base, Underground Jungle)
- https://nothings.org/gamedev/herringbone/ (Wang tile algorithm)

**Game data:**
- `./.trellis/tasks/10-16-noita-cogbench/research/noita-engine-constants.json`
- `./.trellis/tasks/10-16-noita-cogbench/research/biome_layout_from_noitamap.json`
- `./.trellis/tasks/10-16-noita-cogbench/research/biome_material_components.json`
- `./.trellis/tasks/10-16-noita-cogbench/research/spawn_tables_from_lua.json`
- `./.trellis/tasks/10-16-noita-cogbench/research/wang_template_stats.json`

**Related KB pages:**
- `pixel-simulation.md` (SIM-R02 chunk structure, SIM-R31 liquid motion, SIM-R70 cell RNG, SIM-R74 entity merges)
- `materials-reactions.md` (MVP-40 materials, durability gating DUR-R01)
- `benchmark.md` (DET-R04 seed streams, SEED-R01 seed derivation, PROTO-R04 frame units)
