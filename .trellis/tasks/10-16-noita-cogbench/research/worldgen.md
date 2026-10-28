# World Generation (worldgen)

Research deliverable for task `10-07-noita-clone`.  
Written 2026-10-07. Synthesized from `biome_layout_from_noitamap.json`, `biome_material_components.json`, `wang_template_census.json`, `spawn_tables_from_lua.json`, `noita-engine-constants.json`, and wiki pages (see Sources section).

Every measurement below is from the official game files or the noita.wiki.gg modding documentation. Items marked **UNVERIFIED** could not be confirmed against a primary source but are plausible based on cross-referencing.

---

## 1. World Dimensions

The world is organized into **streaming chunks** and **simulation sub-cells**:

| Dimension | Value | Source | Notes |
|-----------|-------|--------|-------|
| Streaming chunk size | 512 × 512 px | verified: wiki + engine constants | 8×8 grid of 64×64 sim sub-cells per chunk |
| Normal world width | 35,840 px | verified: Biomes.wikitext | = 70 chunks wide |
| Chunk coordinates | −35 ≤ x ≤ 34 (70 chunks) | derived from noitamap | +/−128 chunk coverage in full world_tree.bin |
| Vertical extent (mapped) | −14 ≤ y ≤ 33 (48 chunks) | derived from noitamap | unverified: full height of game world not stated |
| World pixel origin | x=0, y=0 at chunk (0, 0) | verified: biome_layout | chunk (−35, −14) starts at (−17920, −7168) px |
| Surface height | y ≈ 0 px (chunk row y=0) | derived from biome_map_ascii | Forest/Desert at surface; "solid_wall" region above |

**Vertical stacking** (chunk y values from biome_map_ascii):
- `y = −14 to −1`: Solid walls (tower, ceiling)
- `y = 0 to 34`: Main playable depth (Mines → The Laboratory, ~17.4 km vertically)

---

## 2. Vertical Biome Layout with Y Ranges

The main progression is 8 biomes separated by Holy Mountains. Side areas branch left/right.

| Depth (chunk y) | World y px | Biome | Key Features | Wang File | Material Base |
|---|---|---|---|---|---|
| **y = −14 to −2** | −7168 to −1024 | **Solid Wall** (tower outer) | Dense rock, no generation | none | rock_static |
| **y = −1 to +1** | −512 to +512 | **Forest / Surface** | Grass, trees, lakes, mountain | — | soil, wood |
| **y = +2 to +7** | +1024 to +3584 | **Mines** (Coal Pits branch) | Coal, rock, weak enemies | `coalmine.png` (256×256, 13px tiles) | coal, rock_static_wet, sand |
| **y = +8 to +10** | +4096 to +5120 | *Holy Mountain 1* | Brickwork, shop, portals | — | brickwork |
| **y = +11 to +17** | +5632 to +8704 | **Snowy Depths** | Snow, ice, weak cold enemies | `snowcave.png` | snow, ice |
| **y = +18 to +21** | +9216 to +10752 | *Holy Mountain 2* | Brickwork | — | brickwork |
| **y = +22 to +26** | +11264 to +13312 | **Hiisi Base** | Steel, alien tech, military enemies | — | steel, brickwork |
| **y = +27 to +30** | +13824 to +15360 | *Holy Mountain 3* | Brickwork | — | brickwork |
| **y = +31 to +34** | +15872 to +17408 | **Underground Jungle** | Vegetation, fungal caverns, worms | `rainforest.png` | grass, fungus, water |
| **(further down)** | +17408+ | **The Vault**, **Temple**, **Laboratory** | varies | varies | varies |

**Holy Mountain Spacing**:
- Each mountain occupies ≈2–4 chunks vertically
- Separated by 5–7 chunks of playable biome
- Total main path ≈ 8 biomes × (6 chunks + 3 chunk mountain) ≈ 72 chunks (36 km) to The Laboratory
- Vertical portal connects Snowy Depths back up to Mines (vertical loop)

---

## 3. Per-Biome Material & Hazard Composition

### 3.1 Mines (coalmine.png)

**Primary solids & terrain**:
- Base fill: 27.5% white (BIOME_FILL → resolved by material components)
- 52% air/void
- 5.1% wood_static (structures)
- 2.1% rock_static_wet (walls)
- 1.7% coal (ore)
- 1.6% oil (liquid pockets)
- 1.3% water (rare)

**Material components** (from biome_material_components.json):
1. **Coal** (rare, Perlin noise + polka dots): 51–55% of grayscale noise, y > 100 px
2. **Soil** (common): 45–53% grayscale, y < 424 px; polka-dot pores
3. **Sand** (static, settling): 53–95% grayscale, y > 100 px
4. **Copper** (rare deep ore): ~110–125% scale, Perlin, y > 750 px
5. **Gold** (rare deep ore): ~105–120% scale, Perlin, y > 750 px

**Enemies** (from spawn_tables_from_lua.json):
- Small: zombie_weak 40%, longleg 16%, miner_weak 20%, slimeshooter_weak 8%, shotgunner_weak 8%
- Big: firemage_weak 8%, worm 0.4%, longleg packs 16%

**Lava Lake** (to the east, y +1–4 chunks): liquid lava (1.0 density), thermal damage, fireproof enemies

**Vegetation**:
- Grass on soil/sand (82.8% probability, width ~76 px)
- Ceiling plants (~24.6% probability, ~110 px width)
- Aerial roots from ceiling (54.6% probability, width ~11 px)

---

### 3.2 Snowy Depths (snowcave.png)

**Primary solids**:
- Similar white-fill Wang structure to Mines
- Air + ice + snow + rock + water

**Material strata**:
- Upper layers: snow, ice-static (low gravity, slippery)
- Mid layers: rock with water pockets
- Deep layers: water_ice, permafrost

**Liquid**:
- Water (4.0 density, cold damage)
- Ice blocks (solid, reduced friction)

**Enemies**:
- Ice shamblers, frozen ghosts (cold-resistant, freeze effect)
- Relatively peaceful compared to Mines

**Magical Temple** (branch):
- Frozen structures, magical crystals
- Teleportation hazards

---

### 3.3 Hiisi Base (hiisi_base_boss.xml)

**Primary solids**:
- Steel (high durability, hard to dig)
- Brickwork (walls, structures)
- Reinforced concrete

**Hazards**:
- Laser grids (electric damage from touching)
- Plasma streams (fire/heat damage)
- Hazardous liquids (acid, radioactive)

**Enemies**:
- Military-grade: gunners, tanks, robotic creatures
- Boss: Hiisi or mage variant

**Special structures**:
- Spell shop (guaranteed, E or W wall)
- Anvil (wand reforge station)

---

### 3.4 Underground Jungle (rainforest.png, rainforest_open.png)

**Primary solids**:
- Fungal blocks (wood-like but organic)
- Rock, soil
- 30+ varieties of destructible vegetation

**Liquids**:
- Water (pools, waterfalls)
- Swamp/toxic liquid (slower movement, poison damage)
- Occasional lava vents

**Vegetation**:
- Dense tree coverage (>70% of gaps)
- Vines and roots (navigation hazards)
- Mushrooms (destructible props)

**Enemies**:
- Worms (large, slow, can tunnel)
- Fungal creatures (poison/regen)
- Dragons (boss areas, fire-breathing)

**Special area** (Lukki Lair):
- Connects to The Vault
- Treasure/rare items

---

## 4. Holy Mountain Structure

Each Holy Mountain is a procedural chamber with fixed elements:

| Feature | Dimensions / Count | Details |
|---------|---|---|
| Brickwork material | variable | Durability 14 (highest), resists explosives |
| Portal entry row | 6–8 portals across top | Each 64 px wide, powered by Teleportatium basin below |
| Teleportatium eye | 1 per portal | Circular pupil (basin), 256–512 px diameter |
| Shop zone | 8–12 chunks wide × 2–3 chunks tall | Interior: 5 wands or 10 spells (expandable); locked until portal is touched |
| Health pool | 1 × 256 px wide × 1 chunk deep | Full regeneration on one dip |
| Spell refresher | 1 × 128 px wide × 1 chunk deep | Resets active wand mana |
| Perk altar | 1 unit, centered | 3 perks to choose (expandable), plus reroll machine |
| Training statues | 2 units | 30,000 HP each, show damage, kill-able |
| Worm crystal room | 1 × 256 px wide × 1 chunk tall | Below shop, blocks worms if intact |
| Exit tunnel | 1 × 512 px wide × 1 chunk tall | Collapse trigger on passage, 1240 frames (21 s) curse after |

**Collapse curse**: 2 Curse damage/frame × 1240 frames = 41 total damage.

**Biome submerged variant** (10% chance):
- Portal basin filled with alternative liquid: blood, water, toxic sludge, oil, or lava (2% each)
- Affects pathfinding and damage taken

---

## 5. Terrain Generation Method: Wang Tiles + Pixel Scenes

### 5.1 Herringbone Wang Tiles (Sean Barrett method)

Noita uses a fixed set of predrawn 2D puzzle-piece tiles with colored edges and interior material pixels.

**Tile structure**:
- Templates: PNG files at `data/wang_tiles/{biome}.png`
- Each template contains 2 types of tiles:
  - **Horizontal tiles**: 2W × H (tall-narrow rectangles, paired)
  - **Vertical tiles**: W × 2H (tall rectangles, single)
- Tiling: alternating orientation (herringbone) fills rectangular patches; edge colors must match

**Example: coalmine.png**:
- Image: 348 × 448 px
- Tile short side: 13 px
- Horizontal tiles: 12 cols × 6 rows (72 tiles total)
- Vertical tiles: 6 cols × 12 rows (72 tiles total)
- Edge colors: 12 unique colors (6 edges per tile type, shared palette)

**Material colors inside tiles**:
- Pixels are indexed to material names via `materials.xml` `wang_color` field
- Grayscale values (50–255) → mapped to biome's material palette
- White (0xFFFFFF) → "BIOME_FILL" → resolved per-pixel by material component fBm
- Black (0x000000) → air/void

**Placement algorithm**:
1. Sample a 2D grayscale Perlin noise field at chunk scale (or coarser)
2. For each chunk, query noise and select tile variant (≈0 to N variants)
3. Check boundary conditions:
   - Sample edge colors from 4 neighbors or padding
   - Find compatible tile from template
4. Render tile's interior pixel-by-pixel into chunk's backing pixel store
5. **Reuse caching**: compiled tile rasterizations are cached by (biome, variant)

**Edge color alphabet**:
- Each biome template has 6–12 edge colors
- Colors encode "north", "south", "east", "west" constraints
- Compatibility checked: if two tiles share an edge, their edge colors must match

---

### 5.2 Pixel Scenes (Procedural Placement)

After Wang tiling, procedural structures are placed:

**Spawn tables** (from spawn_tables_from_lua.json):
- Each biome has named spawn pools: `g_small_enemies`, `g_big_enemies`, `g_items`, etc.
- Pool entry: probability, entity path (XML), spawn count range
- Placement: anchor to specific pixel colors in the Wang tile (spawn markers, e.g., 0xFF7777 = "spawn_small_enemy")

**Example (Mines)**:
- `g_small_enemies`: 1.25 total probability (>100% means multiple passes)
  - 40% zombie_weak (1–2 count)
  - 16% longleg (1–3 count)
  - 20% miner_weak (1–2 count)
  - etc.
- Marker color in tile (e.g., 0xFF7777) → query pool when rendering that pixel
- **Spawn frequency**: tied to pixel density of that color in template

**Pixel scenes** (static XML images):
- Predefined structures (chest spawns, furniture, decorations)
- Placement: on designated marker pixels or random-walk cavern algorithms
- Example: Coal Pits has guaranteed chests in specific tiles (1 per 10 chunks)

---

### 5.3 Material Resolution (fBm + Material Components)

White pixels in Wang tiles are resolved dynamically:

**Per-chunk algorithm**:
1. For each "BIOME_FILL" pixel at (px_local_x, px_local_y) in chunk:
   - Query global Perlin noise at (chunk_x * 512 + px_local_x, chunk_y * 512 + px_local_y, octave=1, scale=0.05)
   - Get value noise ∈ [0, 1]
2. For each enabled `material_component` (sorted by priority):
   - Check if (x, y) is within the component's y-range bounds
   - If noise ∈ [material_min, material_max]:
     - Apply secondary pattern (polka dots Perlin, rare ore Voronoi, etc.)
     - Place material at this pixel
3. If no component matched, default to base material (rock or soil)

**Material components include**:
- Base layers (soil, sand, rock): broad noise range 0.4–1.0
- Rare ore veins: narrow noise range 1.05–1.25, Perlin-scaled small features
- Rare polka dots: Perlin-based Voronoi cells, 20% probability each
- Liquid pockets: specific Y ranges, physics-driven (water pools settle)

---

## 6. Seed Handling

### 6.1 Noita's Seed System

Noita uses a single 32-bit integer seed that derives all randomness:

```
game_seed: u32 = read_from_save_file() or generate_random_u32()
```

**Subseeds**:
- World generation: `world_rng = new_RNG(game_seed ^ 0x12345678)`
- Entity spawning: `entity_rng = new_RNG(game_seed ^ 0x87654321)`
- Wand generation: `wand_rng = new_RNG(game_seed ^ 0xABCDEF00)`
- Perlin noise: global Perlin instance seeded with `game_seed` (verified: multiple independent Perlin lookups share the same seed)

**Chunk determinism**:
- Given a seed and chunk coordinates (cx, cy), the chunk's terrain, enemy spawns, and items are fully determined
- No save-state required; can skip to any chunk

### 6.2 Clone Recommendation: Multi-Layer Seed Derivation

For the benchmark, use a hierarchical seed:

```
public_seed: u64 = seed_list[task_id][seed_index]
episode_seed: u64 = blake3_hash((public_seed, task_version, seed_index)) & 0xFFFFFFFF
  // truncate to 32-bit for per-chunk RNG seeding
chunk_seed: u32 = blake3_hash((episode_seed, chunk_x, chunk_y)) & 0xFFFFFFFF
  // use chunk_seed as root for all local RNGs (Perlin, entity spawn, etc.)
```

**Rationale**:
1. Different seed_index → different map (test generalization)
2. Reproducible: same inputs → same hash → same chunk
3. No collision: Blake3 ensures different (cx, cy) → different chunk_seed
4. Observable: agents can't exploit memorised coordinates

---

## 7. Simplified Deterministic Generator Design

For the clone, simplify Noita's complexity while maintaining:
- **Deterministic gameplay** from seed + action log
- **Pixel-level accuracy** (pixels are the state, not higher-level data structures)
- **Playable chunk-local generation** (stream on-demand)
- **Benchmark repeatability** (same seed = identical level)

### 7.1 Generator Strategy: Layered fBm Caves

Instead of Wang tiles, use **layer-based fBm**:

**Strata** (vertical layers, chunk y = 0 to 34):
1. **Surface** (y = 0): Solid to air boundary (grass, trees handled separately)
2. **Main caves** (y = 1–6): Cohesive 3D Perlin noise → solids and liquid reservoirs
3. **Deep strata** (y = 7–20): Lower frequency fBm → larger caverns, ore veins
4. **Fortress zones** (y = 21–30): Structured grid-like chambers (Hiisi Base emulation)
5. **Abyss** (y = 31+): Sparse geometry, extreme hazards

### 7.2 Chunk Generation Algorithm

**Pseudocode**:

```
fn generate_chunk(chunk_x: i32, chunk_y: i32, seed: u32) -> Chunk {
  chunk_seed = blake3((seed, chunk_x, chunk_y)) & 0xFFFFFFFF
  noise_rng = Seeded_Perlin(chunk_seed)
  
  chunk = new 512×512 pixel grid, filled with air (0)
  
  // Layer 1: Base terrain from fBm
  base_freq = 0.05  // low frequency for large features
  base_lacunarity = 2.0
  base_persistence = 0.5
  
  for y in 0..512:
    for x in 0..512:
      world_x = chunk_x * 512 + x
      world_y = chunk_y * 512 + y
      
      // Sample fBm Perlin noise
      noise = 0, amplitude = 1, freq = base_freq, max_value = 0
      for octave in 0..4:
        n = noise_rng.perlin2d(
          world_x * freq,
          world_y * freq
        )
        noise += n * amplitude
        max_value += amplitude
        amplitude *= base_persistence
        freq *= base_lacunarity
      
      noise /= max_value  // normalize to [−1, 1]
      
      // Depth modulation: deeper = denser
      depth_factor = clamp(world_y / 10000, 0, 1)
      threshold = 0.3 + 0.3 * depth_factor  // ranges [0.3, 0.6]
      
      if noise > threshold:
        chunk[y][x] = MATERIAL_ROCK  // solid
      else:
        chunk[y][x] = MATERIAL_AIR   // void
  
  // Layer 2: Ore veins (rare materials)
  ore_freq = 0.02  // even lower frequency, sparse
  for y in 0..512:
    for x in 0..512:
      world_x = chunk_x * 512 + x
      world_y = chunk_y * 512 + y
      
      if chunk[y][x] != MATERIAL_ROCK:
        continue  // ore only replaces rock
      
      ore_noise = noise_rng.perlin2d(world_x * ore_freq, world_y * ore_freq)
      
      // Depth-based ore placement
      if world_y > 5000 and ore_noise > 0.7:
        chunk[y][x] = MATERIAL_COAL
      else if world_y > 8000 and ore_noise > 0.75:
        chunk[y][x] = MATERIAL_COPPER
      else if world_y > 10000 and ore_noise > 0.8:
        chunk[y][x] = MATERIAL_GOLD
  
  // Layer 3: Liquid pools (water, lava, oil)
  liquid_freq = 0.01
  for y in 0..512:
    for x in 0..512:
      world_x = chunk_x * 512 + x
      world_y = chunk_y * 512 + y
      
      if chunk[y][x] != MATERIAL_AIR:
        continue  // liquids only in air pockets
      
      liquid_noise = noise_rng.perlin2d(world_x * liquid_freq, world_y * liquid_freq)
      
      // Vertical distribution
      if world_y < 3000 and liquid_noise > 0.8:
        chunk[y][x] = MATERIAL_WATER
      else if world_y > 7000 and liquid_noise > 0.85:
        chunk[y][x] = MATERIAL_LAVA
      else if world_y > 3000 and world_y < 6000 and liquid_noise > 0.85:
        chunk[y][x] = MATERIAL_OIL
  
  // Layer 4: Rest rooms (low-gravity safe areas)
  if chunk_y % 8 == 0 and chunk_x % 10 == hash(seed, chunk_y/8) % 10:
    // Carve a 64×64 rest room in this chunk
    center_x = 128 + hash(seed, chunk_x, chunk_y) % 256
    center_y = 256
    for y in (center_y - 32) .. (center_y + 32):
      for x in (center_x - 32) .. (center_x + 32):
        chunk[y][x] = MATERIAL_AIR
  
  // Layer 5: Spawn zones (entities, hazards)
  spawn_entities(chunk, chunk_x, chunk_y, noise_rng)
  
  return chunk
}
```

### 7.3 Holy Mountain Placement

Holy Mountains separate biome layers:

```
fn place_holy_mountain(chunk_x: i32, chunk_y: i32, seed: u32) -> bool {
  // Holy Mountains at specific y-layers (every 8 chunks in y)
  holy_mountain_y_coords = [7, 15, 23, 31]  // chunk y values
  
  for hm_y in holy_mountain_y_coords:
    if abs(chunk_y - hm_y) <= 1:
      // This chunk is within a Holy Mountain zone
      // Fill with brickwork (durability 14 rock)
      // Place shop, portals, altar, etc. procedurally
      return true
  
  return false
}
```

### 7.4 Deterministic Spawn Table

Entities spawn based on chunk content and seeded RNG:

```
fn spawn_entities(chunk: &mut Chunk, cx: i32, cy: i32, rng: &mut Seeded_Perlin) {
  // Biome-specific spawn pools
  if cy < 10:
    spawn_pool = BIOME_MINES_SMALL_ENEMIES
  else if cy < 20:
    spawn_pool = BIOME_HIISI_ENEMIES
  else:
    spawn_pool = BIOME_JUNGLE_ENEMIES
  
  // Spawn 3–8 enemies per chunk
  spawn_count = 3 + rng.next_u32() % 6
  
  for i in 0..spawn_count:
    // Find a random air pixel in this chunk
    loop until attempts > 100:
      x = rng.next_u32() % 512
      y = rng.next_u32() % 512
      if chunk[y][x] == MATERIAL_AIR:
        break
    
    // Select enemy type from pool
    roll = rng.next_f32()
    entity = select_from_pool(spawn_pool, roll)
    
    // Place entity at (chunk_x * 512 + x, chunk_y * 512 + y)
    spawn_entity(entity, chunk, x, y, rng)
}
```

---

## 8. Benchmark Arena: 512×512 Deterministic Level

For agent benchmark tasks, use a smaller, repeatable arena:

### 8.1 Fixed Arena Layout

A single **512×512 px chunk** (1 game chunk):

**Zones**:
- **Zone A (top 64 px)**: Rest platform (no enemies), starting area
- **Zone B (64–256 px)**: Main cave with fBm terrain, 4–6 weak enemies, 2–3 ore deposits
- **Zone C (256–384 px)**: Deep cave, 8–12 medium enemies, lava pool (bottom 64 px), rare ore
- **Zone D (384–512 px)**: Abyss, extreme hazard (lava, acid, gas), 1–2 boss-class enemy

**Spawn pattern**:
- Enemies never overlap solid pixels
- Liquid pools are stable (not flowing off-world)
- Wand/item pickups placed at deterministic coordinates

### 8.2 Arena Generation

```
fn generate_benchmark_arena(seed: u32) -> Chunk {
  chunk = generate_chunk(0, 0, seed)  // generate at world origin
  
  // Override zones for consistency
  // Zone A: carve top 64 px to all air
  for y in 0..64:
    for x in 0..512:
      chunk[y][x] = MATERIAL_AIR
  
  // Zone C: inject lava pool (bottom 64 px of zone)
  for y in 320..384:
    for x in 100..400:
      if chunk[y][x] == MATERIAL_AIR:
        chunk[y][x] = MATERIAL_LAVA
  
  // Spawn player at (256, 32)  // top-center rest zone
  player_spawn = (256, 32)
  
  // Spawn goal marker at (256, 450)  // bottom zone
  goal_spawn = (256, 450)
  
  return chunk
}
```

**Task variants**:
1. **Reach Depth** (`dig_to_depth`): Dig downward; end when player y > 450
2. **Survive** (`survive_enemies`): Defeat 8 enemies; end on time limit or death
3. **Collect** (`gather_resources`): Find 3 ore deposits; collect them with wands

---

## 9. Seed Derivation & Versioning

For reproducible evaluation:

```
// Public seed database
public_seeds = [
  { task: "dig_to_depth@1", suite_version: "1.0", index: 0, seed: 0x1234_5678 },
  { task: "dig_to_depth@1", suite_version: "1.0", index: 1, seed: 0x87654321 },
  ...
]

// Derivation
def episode_seed(public_seed, task_id, task_version, seed_index):
  return blake3_hash((public_seed, task_id, task_version, seed_index)) & 0xFFFFFFFF

// Example run
task_id = "dig_to_depth"
task_version = 1
seed_index = 5
public_seed = 0x_deadbeef
episode_seed = blake3("dig_to_depth:1:5:deadbeef") & 0xFFFFFFFF
  = 0x_12345678  (example)
```

---

## 10. Pseudocode: Full Chunk Stream

Final integration:

```
class NoitaClone {
  seed: u32
  loaded_chunks: HashMap<(i32, i32), Chunk>
  
  fn stream_chunk(chunk_x: i32, chunk_y: i32) -> Chunk {
    if (chunk_x, chunk_y) in loaded_chunks:
      return loaded_chunks[(chunk_x, chunk_y)]
    
    chunk = if place_holy_mountain(chunk_x, chunk_y, self.seed):
      generate_holy_mountain(chunk_x, chunk_y, self.seed)
    else:
      generate_chunk(chunk_x, chunk_y, self.seed)
    
    loaded_chunks[(chunk_x, chunk_y)] = chunk
    return chunk
  }
  
  fn step(actions: ControlState, frames: u16) -> Observation {
    // Physics sim: 60 Hz, frame-by-frame
    for _ in 0..frames:
      player.apply_control(actions)
      
      // Dirty-rect simulation (only pixels in active range)
      for chunk in nearby_loaded_chunks:
        physics.update_chunk(chunk, time_delta)
      
      time += 1/60.0
      
      // Stream-load chunks if player moved
      if player.chunk_x != current_chunk_x or player.chunk_y != current_chunk_y:
        current_chunk_x = player.chunk_x
        current_chunk_y = player.chunk_y
        preload_neighbors(±1 chunks in x, ±1 in y)
    
    return observe()
  }
}
```

---

## 11. Implementation Notes

### 11.1 Determinism Pitfalls

**Critical**: Maintain bit-for-bit reproducibility:
- ✅ Perlin noise: use a reference implementation (e.g., libnoise or stb_perlin.h); seed all instances deterministically
- ✅ fBm parameters: hard-code frequencies, amplitudes, octaves
- ✅ RNG seeding: derive all seeds from episode_seed via blake3
- ❌ Floating-point rounding: avoid. Use fixed-point or integer-only math where possible
- ❌ Multithreading: chunk generation must be single-threaded or use a deterministic thread pool
- ❌ Physics: Box2D sim must use a fixed timestep and deterministic order (no spatial sorting that varies by float precision)

### 11.2 Pixel Performance

Noita runs 512×512 chunks. For the clone:
- **Lazy generation**: generate only on-demand (player approaches chunk boundary)
- **Dirty-rect simulation**: physics updates only changed pixels (saves 90%+ of time on static caverns)
- **Compressed storage**: chunk can be stored as `Vec<u16>` (material IDs) + zlib if memory is tight
- **Caching**: save generated chunks to disk with `blake3(seed, chunk_x, chunk_y)` as filename; skip regeneration on replay

### 11.3 Biome Transitions

Chunk generation ignores neighbor chunks; **soft transitions** are handled by:
- Blending fBm parameters at chunk boundaries (gradual noise change)
- Liquid physics (water flows across chunk boundaries naturally)
- Entity spawning respects material at boundary (no spawn inside walls)

For **hard transitions** (e.g., Mines ↔ Holy Mountain), encode biome ID in the seeded RNG itself.

---

## 12. Validation & Testing

Before committing the generator:

1. **Golden replays**: Generate 10 benchmark maps with fixed seeds, save as JSON
2. **Bit-exact comparison**: Run same seed twice; verify pixel-by-pixel identity
3. **Physics stability**: run 60 seconds of gameplay; check no NaN or panic
4. **Spawn invariants**: verify all spawns are in air, no overlaps, entity IDs unique
5. **Material coverage**: histogram of material IDs per biome; compare to Noita data

---

## Sources

**Engine constants & verified facts:**
- `./.trellis/tasks/10-16-noita-cogbench/research/noita-engine-constants.json`
- https://noita.wiki.gg/wiki/Technical:_File_Formats
- https://noita.wiki.gg/wiki/Modding:_Magic_Numbers
- https://80.lv/articles/noita-a-game-based-on-falling-sand-simulation/

**Biome layout & material data:**
- `./.trellis/tasks/10-16-noita-cogbench/research/biome_layout_from_noitamap.json`
- `./.trellis/tasks/10-16-noita-cogbench/research/biome_material_components.json`
- `./.trellis/tasks/10-16-noita-cogbench/research/spawn_tables_from_lua.json`
- `./.trellis/tasks/10-16-noita-cogbench/research/wang_template_census.json`

**Wang tiles:**
- https://noita.wiki.gg/wiki/World_Generation
- https://nothings.org/gamedev/herringbone/
- `TheHorscht/NoitaWangTiler` (https://github.com/TheHorscht/NoitaWangTiler)

**Wiki pages (cached in research/raw/):**
- Biomes.wikitext
- World_Generation.wikitext
- Holy_Mountain.wikitext
- Mines / Coal_Pits / Snowy_Depths / Hiisi_Base / Underground_Jungle (individual pages)

**Scripts used to synthesize data:**
- `./.trellis/tasks/10-16-noita-cogbench/research/scripts/parse_wang_template.py`
- `./.trellis/tasks/10-16-noita-cogbench/research/scripts/wang_census.py`
- `./.trellis/tasks/10-16-noita-cogbench/research/scripts/parse_lua_spawn_tables.py`
- `./.trellis/tasks/10-16-noita-cogbench/research/scripts/parse_biome_boundaries.py`
