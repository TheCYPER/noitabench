# Pixel simulation technology: how Noita's "Falling Everything" engine works, and a concrete design for our Rust core

Research date: 2026-10-07. Companion files: `noita-engine-constants.json` (numbers with provenance), `pixel-sim-repos.json` and `rust-prior-art.md` (repo survey), `design.md` (parent architecture draft), `materials.json` / `reactions.json` / `spells.json` (parsed game data).

Scope: the physical simulation only (cells, chunks, threads, fluids, fire, particles, explosions, projectile-vs-cell, rigid bodies, performance, determinism) and a recommendation for `noita_core`. No code is written here; step lists are pseudo-structure, not source.

## 0. How to read this document

Every claim carries one of these tags.

| Tag | Meaning |
|---|---|
| **[N]** | Stated by Nolla or reported from Nolla's GDC 2019 talk (80.lv article, macuyiko blog quoting the talk, braindump notes). Strongest evidence. |
| **[W]** | Stated on noita.wiki.gg (modding docs, material pages, file-format page). Reliable for names, defaults and ranges, weak on engine internals. |
| **[G]** | Number read from the parsed game data files (`materials.json`, `reactions.json`, `spells.json`, `noitadata/data/magic_numbers.xml`). Facts and numbers only; no game code is reproduced. |
| **[R:repo]** | Read in the mirrored source of a permissively licensed open-source clone (`research/raw/repos/<repo>/`). Describes the clone, not Noita. |
| **[REF]** | Idea taken from a repo we may only read, not copy (astratomic is PolyForm Noncommercial; FallingSandJava has no license). |
| **[DES]** | Our own design decision or derivation. Reasoning is shown; it is a proposal, not a fact about Noita. |
| **UNVERIFIED** | Plausible but no source found. Never treat as a Noita fact. |

Conventions: x grows right, y grows **down** (as in Noita and every clone read); "below" is `+y`. A "cell" is one pixel of the grid. "Frame" is one fixed 60 Hz simulation tick [W: Cursed Rock page, 2.5 damage per frame = 150 per second].

## 1. Summary (the ten things that matter)

1. Noita's world is streamed in 512 px chunks, each split into an 8x8 grid of **64x64 simulation chunks** [N][W]. The game tries to keep **12** streaming chunks loaded around the player [W: Expert Guide: Waypoints; G: `STREAMING_CHUNK_TARGET` = 12], i.e. 12 x 512^2 = **3,145,728 cells** or 768 simulation chunks. Whether all loaded chunks are stepped every frame is UNVERIFIED.
2. Each 64x64 chunk keeps a **dirty rectangle** of cells that need simulating [N]. Settled regions cost nothing.
3. The grid is **single-buffered** (no double buffer) and updated **bottom-up** [N]. The alternating-x trick used by most clones is not stated for Noita (UNVERIFIED).
4. Multithreading is a **4-pass checkerboard** over chunks: in each pass every other chunk (in both axes) runs in parallel, and its cells may move within the chunk plus **32 px in each cardinal direction** [N]. 32 = half a chunk is exactly the largest reach for which same-class chunks cannot overlap (section 5).
5. Powder, liquid and static ground are **one engine cell type** (`cell_type=liquid` with `liquid_sand` / `liquid_static` flags) [W]. Of 466 materials in the game data, 290 take this path, 26 are gas, 18 are fire and 132 are Box2D solids [G].
6. Liquids check down, then sideways; gases check up, then sideways; burning cells pick a random direction and try to ignite that pixel [N]. Sinking order is decided by `density` [W]; the data has 42 distinct density values from 1 to 50 [G].
7. Pixels thrown by splashes and explosions become **particles with velocity and gravity** [N: macuyiko quote of the talk; W: ConfigExplosion `hole_destroy_liquid`, ParticleEmitterComponent `create_real_particles`]. The re-deposit algorithm is not documented for Noita; FallingSandEngine shows a working one [R:FSE particle.rs].
8. Explosions are **multi-ray carving**: each ray has `ray_energy`, each cell subtracts its material `hp`, cells with `durability > max_durability_to_destroy` are never removed [W: ConfigExplosion, Materials]. Defaults: radius 20, energy 20,000, max durability 10.
9. Rigid bodies: pixel bitmap -> marching squares -> simplification -> triangulation -> Box2D, rebuilt when a body pixel is destroyed; every body pixel knows its body and local position [N: 80.lv; talk pipeline cited by FallingSandJava README]. **Defer** for MVP (PRD non-goal) but reserve hooks (section 10).
10. For bit-identical results at any thread count we need: disjoint windows per pass (a theorem, section 5), a **stateless per-cell random function** instead of a shared RNG stream, integer-only rules, no hash-map iteration, and explicit sorting after every parallel merge (section 12). Section 13 gives the concrete design (6-byte cell, 64x64 chunks, 32x32 storage tiles, 4 passes, `get`/`set` rule API).

## 2. Noita's world, chunk and region layout

### 2.1 Numbers

| Quantity | Value | Tag | Source |
|---|---|---|---|
| Simulation chunk | 64 x 64 px | [N] | 80.lv; braindump GDC notes |
| Streaming / save chunk ("broad chunk") | 512 x 512 px = 8 x 8 simulation chunks | [W] | Technical: File Formats (`world_tree.bin` holds an 8x8 grid of 64 px sub-cells per 512 px chunk) |
| Chunks the game tries to keep loaded | 12 (loads when fewer, unloads old/far ones when more) | [W][G] | Expert Guide: Waypoints; magic number `STREAMING_CHUNK_TARGET` |
| Loaded cells | 12 x 512^2 = 3,145,728 (= 768 simulation chunks) | derived | |
| Normal world width | 35,840 px = 70 broad chunks | [W] | Biomes page ("The normal world is 35,840 pixels wide"); height not published |
| Chunk coverage of saved density map | +/-128 broad chunks (+/-65,536 px) | [W] | File Formats |
| Per-chunk save | `world_[x]_[y].png_petri` (materials + Box2D objects) and `entities_[index].bin`, `index = 2000*y + x` | [W] | File Formats |
| Stored per cell on disk | material index into a lookup table; highest bit = "has custom colour"; at most 128 materials per chunk file (format quirk) | [W] | File Formats |
| Maximum materials | 1024 (`CELLFACTORY_CELLDATA_MAX_COUNT`) | [W][G] | Magic Numbers; so a **u16 material id** is required, u8 is not enough |
| Virtual screen | 427 x 242 | [W][G] | Magic Numbers (`VIRTUAL_RESOLUTION_X/Y`); about 3.3 % of the 3.1 M loaded cells |
| Frame rate | 60 Hz | [W] | Cursed Rock page |
| Custom thread pool | on (`USE_CUSTOM_THREADPOOL` = 1) | [W][G] | Magic Numbers |
| Box2D thread wait | 12 ms (`BOX2D_THREAD_MAX_WAIT_IN_MS`); stuck bodies are frozen (`BOX2D_FREEZE_STUCK_BODIES` = 1) | [W][G] | Magic Numbers; implies Box2D runs on its own thread with a bounded wait |
| `GRID_MAX_UPDATES_PER_FRAME` 128, `GRID_MIN_UPDATES_PER_FRAME` 40, `GRID_FLEXIBLE_MAX_UPDATES` 0 | values known, meaning UNVERIFIED | [W] | Magic Numbers. Pure numerology: 40 = 8 x 5 chunks of 64 px, about the screen plus a one-chunk border. Do not rely on it. |
| `GRID_RENDER_TILE_SIZE` 32, `GRID_RENDER_BORDER` 2 | render tiling only | [W][G] | Magic Numbers |
| `PARTICLE_EMITTER_MAX_PARTICLES` | 100,000 | [W] | Magic Numbers (added Mar 2023) |

### 2.2 Which region is simulated

- Verified: chunks outside the loaded set are not part of the live world. When a chunk unloads, the entities in it (projectiles included) are saved and deleted, and an expiration trigger fires in the process [W: Expert Guide: Waypoints]. So an unloaded liquid does not flow and an unloaded projectile does not move.
- Verified: Box2D "update areas": a physics body can mark its predicted AABB as an update area (`force_add_update_areas`) [W: PhysicsBody2Component]. This implies terrain colliders exist only near dynamic bodies, not world-wide.
- UNVERIFIED: whether Noita steps all 12 loaded chunks each frame or only a window around the camera/player. There is no published number. Treat "12 loaded chunks, active window <= loaded set" as the upper bound.
- [DES] For us: the **active rectangle** is configurable. Benchmark worlds (512 x 512, 1024 x 1024) are fully active. The game world defaults to 2048 x 1536 = 4 x 3 broad chunks = 12 broad chunks, the same size as Noita's loaded set. Chunks outside the active rectangle are frozen (no stepping), keep their cells, and start fully dirty when re-activated (FallingSandEngine does the same: `force_update_chunk` sets a full-chunk dirty rect [R:FSE chunk_handler.rs]).

### 2.3 Material model facts that shape the simulator

From `Modding: Making a custom material` [W] and the parsed game data [G]:

- `cell_type` is one of four values: `solid`, `liquid`, `fire`, `gas`. "Solid" means a Box2D body material. **Sand is `liquid` + `liquid_sand=1`; ground is `liquid` + `liquid_sand=1` + `liquid_static=1`** (static sand that floats and can be stood on).
- Counts over the 466 parsed materials [G]: 100 liquids, 87 powders, 103 static ground, 26 gases, 18 fire, 132 Box2D solids. So one movement code path (the liquid one) covers 290 materials (62 %).
- Engine defaults [W]: `density` 1, `durability` 0, `hp` 100, `liquid_gravity` 0.5, `liquid_flow_speed` 0.9, `liquid_damping` 0.8, `liquid_viscosity` 50, `gas_speed` 50, `gas_upwards_speed` 100, `gas_horizontal_speed` 100, `gas_downwards_speed` 90, `autoignition_temperature` 100, `temperature_of_fire` 10, `generates_flames` 30, `requires_oxygen` 1.
- Density ranges [G]: liquids 1 to 14.5 (oil 1, acid 2.9, water 4, blood 4.1, slime 5, lava 6, void liquid 14.5); powders mostly 6 (54 of 87), then 7 (12), 8 (8), 10 (5); static ground mostly 10 (81 of 103); gases 1 or 2 (cloud 4.17); fire 1; Box2D solids 6 or 8. 42 distinct densities overall.
- Durability [G]: 329 of 466 materials have durability 0 ("not defined, hardness only" [W]); the rest span 2 to 16 (wiki lists 0 to 14; four gem Box2D materials carry 15/16). `hp` ranges 5 to 1,000,000 with 40 distinct values: sand 800, soil 2,000, coal powder 1,000, wood_static 2,000, ice_static 30,000, rock_static 100,000, steel_static 130,000.
- Lifetimes [G]: only 38 materials have a lifetime: 23 gases (50 to 1,000 frames; steam 1,000, smoke 350, most toxic gases 450), 10 liquids, 4 powders, 1 fire (`flame` = 5 frames). Maximum 1,350 frames.
- Reactions [G]: 339 `<Reaction>` rows; `direction` is `none` in 312, `top` 8, `bottom` 6, `left` 2, `right` 2; `fast_reaction` in 13; `convert_all` in 0; `entity` spawn in 5. File order is engine priority.

## 3. Chunks, dirty rectangles and how they propagate

### 3.1 What Noita says

Each 64x64 chunk keeps a dirty rectangle listing the pixels that need updating [N]. The rectangle is the only sleeping mechanism Noita states; there is no per-cell sleep counter in any source we have. Everything else below is read from clones.

### 3.2 What the clones do

| Repo | Chunk | Rectangle bookkeeping | Propagation to neighbours | Notes |
|---|---|---|---|---|
| FallingSandEngine [R:FSE simulator.rs, chunk_handler.rs] | 100 x 100 | `Option<Rect>` per chunk, min/max over all cells written during the chunk's tick (including writes into the 8 neighbours). Cleared at frame start, rebuilt by writes. | If the centre chunk wrote anything, the **half of each neighbour that faces it** (50 px band) is unioned into the neighbour's rect. Results are applied serially after the parallel phase. | Very conservative; any activity wakes up to 8 half-chunks. |
| noprobelm bevy_falling_sand [R:dirty.rs] | configurable (README example 64) | `ChunkDirtyState { current, next, positions, dirty_borders }`. `next` accumulates writes; `advance_frame()` makes it current and **inflates it by 2 px**. | If the inflated rect pokes outside the chunk, the matching neighbour gets a border flag; the neighbour then scans a 2 px strip along that edge. 8 flags (4 edges + 4 corners). | Cleanest model; the 2 px margin only works because its rules reach 1 to 2 cells. |
| 100-TomatoJuice [R:chunk.rs, simulation.rs] | any | two countdown counters per chunk (`strong_ticked`, `weak_ticked`, start value 2) decremented each frame; `set()` refreshes the chunk and its 8 neighbours. Chunk skipped when both are 0. | whole-chunk granularity | Used for collider regeneration too (only `strong_ticked` chunks). |
| FallingSandSurvival [R:Chunk.hpp, world excerpt] | 128 x 128 | no rects; a `tickVisited` bool array per pass; TODO in source: "only check tiles dirty last tick" | none | Shows Noita-like tick ordering without dirty tracking. |
| astratomic [REF] | 64 x 64 | update rect + render rect per chunk, `f_idle` sleep per atom (`FRAMES_SLEEP` = 1) | via async channels | Design reference only. |

### 3.3 The correctness condition (our requirement)

A cell skipped this frame must be an exact no-op. Formally: let `r` be the largest distance at which any rule *reads* a neighbour (liquid lateral scan, gas move, reaction, ignition). If a cell at `p` is written in frame `f`, every cell within `r` of `p` may change behaviour in frame `f+1`, so the dirty set for `f+1` must contain `[p-r, p+r]`. Rectangle dilation by `r` (clipped per chunk, spilling into neighbours) satisfies this.

Consequences for the clones: noprobelm's 2 px margin is correct only for rules with reach <= 2; FallingSandEngine's 50 px band is correct for any reach <= 50 but wastes work; design.md's draft ("within 1 of a chunk border plus 1-cell halo") is too small for liquids that scan sideways up to 10 cells.

### 3.4 Timers keep chunks awake

A cell whose state changes without moving (gas lifetime countdown, burning counter) would never be re-visited once its chunk goes clean. Rule: any cell with a running timer calls `keep_awake()`, which adds its own position to the chunk's next dirty rect without writing the cell. A burning tree therefore keeps exactly its bounding box awake. [DES]

### 3.5 Recommended dirty bookkeeping [DES]

- Per chunk: `dirty` (current, scanned this frame) and `next` (accumulating), each `Option<Rect>` packed as four u8 (x0, y0, x1, y1 in 0..63).
- Every write at world position `p` expands `next` of the owning chunk. Each worker task additionally records the bounding box of its writes (per window); after the pass a serial merge dilates it by `WAKE = 12` (liquid lateral range 10 + 2) and unions the clipped boxes into the chunks it overlaps.
- End of frame: `dirty = next; next = None`.
- Because a rect is one bounding box, two distant active spots in a chunk cost a full-chunk scan. Accept this (it is Noita's own design [N]); consider an 8x8-tile occupancy bitmap only if profiling shows chunks scanned mostly empty (UNVERIFIED benefit).

## 4. Update order and the "already updated" mark

### 4.1 Row and column order

| Source | Row order | Column order |
|---|---|---|
| Noita | **bottom-up** [N] | not stated (UNVERIFIED) |
| FallingSandEngine | bottom-up (`range_tb().rev()`) | one random direction per chunk per tick (`rng.bool()`) [R] |
| FallingSandSurvival | bottom-up | fixed left-to-right (alternation compiled out) [R] |
| falling-rust | bottom-up | alternates every step, tied to the visited toggle [R] |
| sandspiel | **top-down** | alternates every generation [R] (relies on the clock mark instead) |
| TomatoJuice | full scan, x outer and y inner ascending, skipping sleeping chunks | fixed [R] |

Why bottom-up: a column of falling cells moves as a train in one frame without gaps (the cell at `y+1` has already moved when `y` is visited) and downward movers never need a mark. Upward movers (gas, buoyant liquids, anything displaced upward by a heavier cell sinking) land in rows that are visited later, so they **do** need the mark. Top-down order reverses this. Alternating column direction removes the sideways drift and pile-leaning that a fixed direction produces.

### 4.2 The per-cell "already updated" mechanism

| Implementation | Mechanism | Staleness risk |
|---|---|---|
| sandspiel [R:lib.rs] | `clock: u8`; `set()` stamps `generation+1`; a cell is skipped if `clock - generation == 1`; generation increments twice per tick | none, the whole grid is scanned every tick; wraps every 256 stamps |
| falling-rust [R:mod.rs, simulation.rs] | `visited: bool` compared with a global `visited_state` that toggles each step; `set`, `swap` and the end of `update_cell` write the current state | none, every cell is refreshed every step |
| FallingSandSurvival [R:world excerpt] | `tickVisited` bool array, double-buffered, `memset` on a side thread **before every pass** | none |
| TomatoJuice [R:chunk.rs] | `updated: bool` per particle, cleared by a sweep each frame | none |
| FallingSandEngine [R:simulator.rs] | no mark in the code read (sand rule only moves downward, bottom-up) | a grain can fall again in a later pass if it crossed into a chunk of a later class (UNVERIFIED whether intended) |
| Noita | UNVERIFIED | |

**Pitfall for dirty-rect engines**: a 1-bit parity flag or a u8 generation stamp is only safe if every cell is refreshed every frame. With dirty rects a cell stamped in frame `f` and not touched again keeps its stamp; in frame `f+2` the parity matches again and the cell is wrongly skipped (a one-frame stall; with a u8 stamp the same happens every 256 frames). design.md's draft uses exactly that parity bit.

**Recommended [DES]**: a plain `UPDATED` bit in the cell. Every `set`/`swap` raises it on all written cells. It is **cleared at the end of the frame** by a pass over each chunk's `next` rect (all written cells lie inside `next` by construction), parallel per chunk. Cost is one linear sweep of the dirty area and the semantics are exact: "a cell moves at most once per frame, whatever the pass it lands in". The mark is transient; it is never saved or hashed.

## 5. The 4-pass checkerboard and why it is thread-safe

### 5.1 The scheme

Noita: "update the world in a checker pattern, 4 times; in each round every other 64x64 chunk is picked, and pixels in those chunks may move inside the 64x64 area plus 32 px in each cardinal direction" [N: 80.lv]. The talk also states the guarantee that no pixel moves more than 32 px [N: macuyiko quoting the talk].

Chunk class of chunk `(cx, cy)` is `(cx mod 2, cy mod 2)`; pass `k` runs all chunks of class `k` in parallel and ends with a barrier. Clone details:

| Repo | Class formula | Pass order | Reach |
|---|---|---|---|
| FallingSandEngine [R:chunk.rs] | `((-cy) mod 2) * 2 + (cx mod 2)`; a unit test asserts all 8 neighbours have a different class | fixed 0..3 | CHUNK/2 = 50 (comment, unchecked) |
| FallingSandSurvival [R:world excerpt] | `chOfsX = tk%2`, `chOfsY = 1-((tk%4)/2)`, 6 iterations of 4 passes per tick | fixed | none stated |
| noprobelm [R:coord.rs, systems.rs] | `(cy&1)<<1 \| (cx&1)` | **random** per tick (non-deterministic) | movement `Speed` |
| astratomic [REF] | `(x_toff, y_toff)` in {0,1}^2 | random | 4 half-chunk sides and 4 quarter-chunk corners handed to each task |
| FallingSandJava [REF] | column stripes, even then odd | alternating | n/a |

### 5.2 Safety argument

Let the chunk size be `C` (64) and the maximum distance `R` between a cell and any cell it reads or writes during its update be the **reach**.

1. A task owns the cells of one chunk (it scans only its own dirty rect) and may touch cells in `[chunk - R, chunk + C + R)` on each axis: its **window**, `C + 2R` wide.
2. Two chunks of the same class in one axis are `2C` apart (origins), so the gap between their edges is `C`. Windows are disjoint iff `R + R <= C`, i.e. **`R <= C/2`**. For `C = 64`, `R <= 32`: exactly Noita's number.
3. Checking the extreme case: cell at x = 63 of chunk A touches up to x = 95; cell at x = 128 of the next same-class chunk touches down to x = 96. No overlap.
4. Chunks of the same class that are diagonal neighbours in the class lattice are also `2C` apart in both axes, so the 2-D argument is the product of the 1-D one. With only 2 stripes classes (x only) vertical neighbours would collide, which is why the scheme needs 4 passes, not 2.
5. With `R = C/2` the windows of one pass **tile the plane exactly**: for class `(ox, oy)` the windows are 128 x 128 squares starting at `128k + 64*ox - 32` and `128m + 64*oy - 32`. Each of the four passes is a different shifted tiling of the world into 128 x 128 squares. This is the property the safe-Rust storage in section 13.3 exploits.
6. Tasks of one pass touch disjoint memory and read nothing outside their window, so the pass result does not depend on the order or timing of its tasks. Passes are separated by barriers. Therefore the whole frame is a deterministic function of the pre-frame state (given deterministic per-task randomness, section 12).

What can go wrong: any rule that reaches farther than `R` (a liquid scanning 40 cells, a particle moving 50 px per frame) silently breaks the argument. We enforce it with a compile-time constant and debug assertions inside `get`/`set` (section 13.5). FallingSandEngine's particle code states the same invariant ("no particle may move more than CHUNK_SIZE/2 per tick") and notes it is not enforced [R:particle.rs].

### 5.3 Costs and alternatives

- Parallelism per pass is `chunks/4`. A 512 x 512 benchmark world has 64 chunks, 16 per pass: little work per barrier on 8+ threads. A 2048 x 1536 world has 768 chunks, 192 per pass.
- Pass order matters for physics: chunks of the first class see the pre-frame state, later classes see its writes. A fixed order biases flows across boundaries slightly; rotating the class order by frame (deterministically) averages it out. [DES]
- Alternative: column stripes (FallingSandJava [REF]) need 2 barriers but give coarse load balance (rain in one column keeps one thread busy) and no dirty rect granularity.
- FallingSandSurvival runs 6 iterations x 4 passes per tick so that liquids get more sub-steps than sand [R]. We use per-material multi-step movement inside one visit instead (section 6.3), which keeps "one visit per cell per frame".

## 6. Material rules

All of this is the clone-level mechanism plus Noita's parameter set. Noita's actual per-material formulae are not public; where a mapping from Noita parameters to our integer rules is a guess it is marked UNVERIFIED.

### 6.1 Kinds [DES from W and G]

`Kind = Air | Static | Powder | Liquid | Gas | Fire | Solid`, derived once at load:

| Kind | Noita definition | Moves | Count in game data |
|---|---|---|---|
| Static | liquid + `liquid_sand` + `liquid_static` | never; can be removed, burnt, converted | 103 |
| Powder | liquid + `liquid_sand` | down, diagonal down | 87 |
| Liquid | liquid, `liquid_sand` = 0 | down, diagonal down, sideways | 100 |
| Gas | `cell_type=gas` | random walk, slight upward bias | 26 |
| Fire | `cell_type=fire` | rises, short life | 18 |
| Solid | `cell_type=solid` (Box2D body) | rigid body | 132 |

MVP maps `Solid` to `Static` (keep a `box2d` flag in the table for later, section 10).

### 6.2 Swap semantics and density comparison

Mover `M` wants to enter target `T`. If allowed, the two cells **exchange positions** (matter is conserved by the move; both cells are marked updated).

| Mover | Target | Rule |
|---|---|---|
| any | Air | move |
| Powder, Liquid | Gas, Fire | swap (the gas is pushed into the vacated cell, i.e. up or sideways) |
| Powder, Liquid | Liquid | swap iff `density(M) > density(T)` (strict); equal density = blocked |
| Powder | Powder, Static, Solid | blocked (diagonal slide may still apply) |
| Liquid | Liquid, equal density, different material | blocked for vertical moves; lateral swap with small probability (the wiki says liquids of the same density "mix") [W: Density] |
| Gas | Air | move |
| Gas | Gas | swap iff `density(T) > density(M)` (the lighter gas rises through the heavier) |
| Gas, Fire | Liquid, Powder, Static | blocked (gas never bubbles through liquid; it is lifted only when a liquid sinks past it) |

Data checks [G]: sand 6 > water 4 > oil 1 (sand sinks in water, oil floats); lava 6 equals sand 6 (sand does not sink in lava); gunpowder 7 and snow 8 are denser than sand; water 4 > acid 2.9 > oil 1; blood 4.1 sinks below water 4. Static ground (density 10 or 11) is never a legal target.

Only "heavier moves into lighter" swaps exist. A lighter liquid below a heavier one rises because the heavier one sinks past it; no separate rising rule is needed. Clones differ: sandspiel hard-codes lists (sand into water/gas/oil/acid) [R:species.rs]; falling-rust lets powders swap with any liquid/gas and gives liquids a 1-in-3 chance to swap down into a lighter liquid [R:simulation.rs] (slows layering down, looks natural); TomatoJuice swaps iff `density > density` [R:movement.rs]; noprobelm swaps iff `density > neighbour density`, equal = skip, lighter = obstructed [R:systems.rs]. Our probability: `SINK_CHANCE` default 3/4 for liquid-into-liquid, 1 for powder-into-fluid. [DES, tunable]

### 6.3 Powders

Noita parameters on powders [G]: `liquid_gravity` (sand 0.9, soil 0.5, coal/gunpowder 2.0), `liquid_viscosity` (soil 75, sand 50, a few 101 to 150), `liquid_sticks_to_ceiling` (soil 50), `stickyness`, `hp`, `durability`.

Rule (pseudo-structure) [DES]:
1. Compute `steps` for this frame (see below). Repeat up to `steps` times: try `(0,+1)`; if blocked try `(-1,+1)` and `(+1,+1)` in an order chosen by the cell's DIR bit XOR a random bit; stop at the first failed attempt.
2. A powder that cannot fall may slide diagonally only with probability `slide(viscosity)`. UNVERIFIED mapping: `slide = clamp(1 - viscosity/200, 1/4, 1)`, giving 0.75 for the default viscosity 50 and 0.625 for soil. This controls the angle of repose; calibrate against footage.
3. Multi-step falling (UNVERIFIED mapping): expected fall speed `2 * liquid_gravity` cells per frame, using the integer part as certain steps and the fractional part as a probability for one more (water 1.5 -> 3 steps; sand 0.9 -> 1.8; lava 0.2 -> 0.4, i.e. a slow 40 % chance; slime 0.1). Rationale: Noita says `liquid_gravity` "no max, with 0 it still falls, but slow and weird" [W], and the 32 px/frame travel guarantee [N] implies cells can move many pixels per frame. Cap at 6 steps.
4. `liquid_sticks_to_ceiling`, `stickyness` and static `liquid_static` handled outside the MVP (stickyness is an entity slow-down; sticks-to-ceiling semantics are UNVERIFIED).

FallingSandEngine's sand rule (BSD-3) is the nearest Noita-like reference: down preferred (9 in 10 when diagonals are also open), diagonals only if the cell above is air or a coin flip says so ("covered pixels slide less"), a 1-in-2 chance to hop 2 cells, and promotion to a free-flight particle when 4 cells below are empty [R:simulator.rs].

### 6.4 Liquids and dispersion

Noita parameters [G][W]: `liquid_gravity`, `liquid_flow_speed` (default 0.9; 94 of 100 liquids; four at 0.1, two at 0.3), `liquid_damping` (0.8; 4 at 0.9; wiki: other values "glitchy"), `liquid_viscosity` (default 50 for 73 liquids, 75 for 16, lava 10; wiki: "no noticeable difference?"), `liquid_slime` (6 liquids; "flows slower"), `liquid_sticks_to_ceiling`.

Observation: viscosity is almost constant across the data and lava (the slowest-looking liquid) has *lower* viscosity than water; lava's slowness comes from `liquid_gravity` 0.2. So `liquid_gravity` and `liquid_flow_speed` carry the visible behaviour; `liquid_viscosity` can be treated as a minor lateral-skip probability.

Dispersion model [DES, UNVERIFIED mapping]: damping implies a geometric decay of lateral motion: total travel `L = round(flow_speed / (1 - damping))`, giving 5 for the default (0.9 / 0.2 = 4.5), 9 with damping 0.9, 1 for flow speed 0.1, 2 for 0.3. Cap `L <= 10` (this is the `r` used for the wake margin). `liquid_slime` halves `L`.

Rule (pseudo-structure) [DES, modelled on falling-rust and sandspiel]:
1. Fall like a powder (down, then both diagonals), `steps` as above, with the density rules of 6.2.
2. If the cell did not move vertically: choose lateral direction from the DIR bit (flip it with chance 1/8, and whenever the first lateral cell is blocked). Scan outward up to `L` cells; remember the farthest cell reachable through enterable cells (air, gas, fire) and stop at the first non-enterable cell. If a free run exists, hop to its end in one move (sandspiel's "scoot double" and falling-rust's walk are the same idea; one hop avoids `L` separate swaps).
3. Equal-density neighbour of a different liquid: swap sideways with probability 1/16 (mixing).
4. Never recompute from floats per frame: `steps` fractions and `L` are integers or 8-bit probabilities fixed at load time.

falling-rust reference numbers: water `strength` 12 (scan up to 11 cells) and weight 128, acid strength 10 and weight 32; lateral direction is 50/50 each frame; gases move 3 in 5 upward [R:element.rs, simulation.rs]. sandspiel water keeps its flow direction in the parity of a per-cell byte (`ra`) and flips it when blocked, plus a "bump" counter (`rb`) that makes a bumped drop less certain for 3 to 6 frames, and neighbouring water copies each other's direction ("spread opinion") [R:species.rs]. We store one direction bit.

### 6.5 Gases

Noita [G][W]: all 26 gases use `gas_speed` 50, `gas_upwards_speed` 100, `gas_horizontal_speed` 100, `gas_downwards_speed` 90; densities 1 or 2 (cloud 4.17); lifetimes 50 to 1,000 frames. Gases are "non-collision pixels that obey gravity inversely, flowing upward and forming lakes in cave-ceiling pits" [W: Materials]. Noita's check order: up, then left/right [N].

Rule [DES, UNVERIFIED mapping of the four speeds]:
1. Lifetime: count down in 8-frame units; at 0 the cell becomes air (or its `decays_into`).
2. With probability `gas_speed/100` (50 %) pick a direction with integer weights up 100, left 100, right 100, down 90 (a slight upward drift; weights are per direction, alternative reading is horizontal 100 shared by both sides, UNVERIFIED).
3. Target air: move. Target gas with higher density: swap. Otherwise stay.

sandspiel's gas is a random walk with a "molecule merge" counter; falling-rust's gas moves up with probability 3/5 and left/right 1/5 each; TomatoJuice treats gas as a liquid with inverted gravity [R].

### 6.6 Fire and burning

Noita facts:
- Burning cell looks in a **random direction** and tries to ignite that pixel [N: 80.lv].
- Material fire properties [W]: `burnable`, `fire_hp` ("fire takes away fire_hp; when it runs out the material disappears; -1 burns forever"), `on_fire` (starts burning), `on_fire_convert_to_material`, `requires_oxygen`, `generates_flames` (default 30), `generates_smoke` (0 to 20), `temperature_of_fire` (0 to 200, default 10; higher = easier for neighbours to ignite), `autoignition_temperature` (0 to 99, default 100), `on_fire_flame_material` (default `fire`), `on_fire_smoke_material` (default `smoke`), `always_ignites_damagemodel` (ignites entities).
- Distribution among the 137 flammable materials [G]: fire_hp 600 (37), 0 (25), 90,000 (21, effectively endless: 25 minutes), 100 (12), 1,000 (7), 300 and 9,000 (5 each); autoignition 85 (43), 99 (34), 100 (17), 1 (7: gunpowder, gases), 10 (7, oil among them); `temperature_of_fire` 50 (49), 30 (27), 100 (16), 90 (15); 26 materials have `requires_oxygen` = 0; `generates_flames` 30 in 135 of 137.
- Fire cells: `fire` (density 1, tof 100), `flame` (lifetime 5, tof 60), `fire_blue`; steam and smoke are separate gas materials [G]. "Fire is the only material the engine requires" [W: Fire page].
- Fire page [W]: burning rate differs per material (Whiskey and flammable gas almost instantly, coal slowest, oil between) which matches fire_hp (coal powder 1,000, oil 500); water puts fire out and boiling produces steam; fire needs air: removing air supply or flooding extinguishes it; `requires_oxygen` is described confusingly by the wiki (UNVERIFIED direction; data suggests 0 = burns even when buried, e.g. gunpowder and flammable gases have 0).

Our rule [DES, UNVERIFIED parameter mapping]:
1. A flammable cell has a `BURNING` flag and a `burn` counter initialised to `fire_hp` in material-specific units (`burn_unit = ceil(fire_hp / 250)` frames, so it fits u8; `fire_hp` of -1 or >= 90,000 is a sentinel 255 meaning endless).
2. Each frame a burning cell: (a) keeps its chunk awake; (b) if `requires_oxygen` and none of its four neighbours is air/gas/fire, it neither progresses nor emits; (c) decrements `burn` per unit; at 0 it becomes `burns_into` (air by default); (d) with probability `generates_flames/255` spawns `on_fire_flame_material` into a random free 4-neighbour (up preferred); smoke likewise from `generates_smoke`; (e) picks **one random neighbour of the 8** and ignites it if it is flammable, not burning, oxygen condition passes, and `temperature_of_fire(source) >= autoignition_temperature(target)`.
3. Fire/flame cells run the same ignition step, rise like gas into air only, and expire by life. Water-tagged neighbours extinguish via the reaction table (fire + water -> steam).
4. Liquids burn in place (the flag travels with the cell on swaps); gases burn out almost at once.

Check against data: lava (tof 90) ignites wood (85) and oil (10) but not coal (94); fire (tof 100) ignites everything with autoignition <= 99. The Fire page also lists lava + `[burnable]` reactions at rate 8 and `[burnable_fast]` at 80, so Noita handles lava ignition partly through reactions; our temperature compare is a simplification. Burn durations from `fire_hp` at one unit per frame: wood_static 600 frames (10 s), oil 500 (8.3 s), coal powder 1,000 (16.7 s). Whether Noita decrements `fire_hp` once per frame is UNVERIFIED.

falling-rust's flags (`FLAG_BURNS`, `FLAG_TURNS_INTO_ASH`, fire strength via `dissolve_to`) and sandspiel's wood (`rb` = 90-frame burn counter that spawns fire every 4th frame into an empty random neighbour) are the clone-level equivalents [R].

### 6.7 Contact reactions

Noita reactions are material-pair rules with `probability` (stored as `int(float*100)`), optional `direction`, `fast_reaction`, `req_lifetime`, blob radii, tags (`[burnable]`, `[water]`, `[lava]`) and an optional `ExplosionConfig` or `entity` [W: Reaction docs]. For the MVP: a dense `reactions[a*n + b] -> u16` table (466^2 x 2 B = 434 KB), expanded from tags at load; a cell checks **one random 4-neighbour per visit** and rolls `probability/100`. How Noita samples neighbours and how often is UNVERIFIED; calibrate the per-visit rate so reactions land at the documented per-update percentages. A reaction that rewrites a cell stamps `UPDATED`. Details belong to the reactions child task.

## 7. Free-flight particles ("cells thrown into flight")

### 7.1 What is known about Noita

- A jump into blood takes the surrounding pixels and puts them into a **particle simulation with velocity and gravity** [N: macuyiko blog quoting the talk]. Explosion rays that meet liquid cells either destroy them or "throw them into the air", selected by `hole_destroy_liquid` (default false) [W: ConfigExplosion].
- ParticleEmitterComponent distinguishes [W]: `create_real_particles` (cells placed directly into the grid; velocity and lifetime ignored), `emit_real_particles` (particles that behave like particles and keep working off-screen), `emit_cosmetic_particles` (collide with the grid but have no other physical interaction; culled outside the camera). `collide_with_gas_and_fire` decides whether real particles are blocked by gas and fire. Lua `GameCreateParticle(material, x, y, how_many, xvel, yvel, just_visual, draw_as_long, randomize_velocity)` spawns them; weather uses particles that become cells on contact ("the particle material remains in the world once it has contacted a surface") [W: GameEmitRainParticles].
- Not published: how a particle is stepped and when it re-enters the grid.

### 7.2 A working re-deposit algorithm (FallingSandEngine, BSD-3) [R:particle.rs, simulator.rs]

- Particle = `{material cell, position f64 x2, velocity f64 x2}`; spawned when a falling sand grain has the cell below and the four cells beyond it all empty, with velocity `(+-0.25, 1..2)`.
- Per tick: `vy += 0.1`; `steps = floor(sqrt(|vx| + |vy|)) + 1`; for each sub-step the position advances proportionally along the displacement and the cell under it is read.
- On the first non-air cell: if the cell the particle started the tick in is free, deposit there; otherwise "displace" the particle into the world at the new position; if that fails, "upwarp" (`vy = -1`, `y -= 16`) and continue next tick. Particles inside a rigid body ignore that body's pixels until they have left it once.
- Scheduling: particles are grouped by 64 px chunk class and processed in 4 parallel phases; invariant "no particle moves more than CHUNK/2 per tick" (not enforced). Particles in unloaded chunks are parked (swapped between an active and a sleeping list every 29 ticks).
- EP01_SandSim (BSD-3) gives every cell a velocity vector instead; TomatoJuice (Apache-2.0) gives every cell integer velocity, adds 1 gravity per frame, walks a Bresenham line towards `pos + velocity`, and on a block retries with the velocity rotated 45 and 90 degrees (3 candidates for powder, 5 for liquid and gas) [R].

### 7.3 Our design [DES]

- Cells have **no velocity**. Fast motion exists only as **Particle** records; ordinary falling and flowing stay in the cell rules.
- Particle: `{mat: u16, x, y: Q16.16 fixed point, vx, vy: Q16.16, life: u16, id: u32}`. Fixed-point so it is bit-identical on every platform (section 12).
- Creation: explosions (section 8), splashes when a fast entity or projectile enters liquid, material-spawning spells (Water, Oil... in `spells.json`), powder promotion (optional).
- Step (once per frame, after the cell passes): `vy += GRAV`; clamp `|v|` so the per-frame displacement is <= 32 px (the Noita travel guarantee, keeps deposits inside reach); sweep from the old cell to the new cell with a DDA/Bresenham walk (TomatoJuice `line()` idea). Free cells (air, and gas/fire unless the particle is `collide_with_gas_and_fire`) are passed through.
- Contact: on a liquid of lower density a heavier particle swaps through (pushing the liquid up one cell); otherwise deposit at the last free cell. If no free cell exists within radius 3 of the contact, convert to the cheapest legal result: spawn into the nearest free cell by outward spiral up to radius 6, else destroy.
- Lifetime: expire to a deposit at the current cell if it is free.
- Cap at 100,000 live particles (Noita's emitter cap [W]); overflow drops the newest.
- MVP schedule: one global list, processed single-threaded in `id` order. Cost estimate: 20,000 particles x up to 32 cell reads = 640,000 reads, about 1 to 3 ms (UNVERIFIED, to be measured). If it matters, move particle stepping inside the pass tasks (each task steps the particles of its chunk, reach <= 32) and merge hand-overs in chunk order.

## 8. Explosions: carving by durability and hardness

### 8.1 Noita's model [W: ConfigExplosion, Materials, Explosion interactions; G]

- An explosion traces **multiple rays** around its centre. Each ray carries `ray_energy` (default 20,000), subtracts the `hp` of every cell it passes, and stops when its energy is used up or the explosion radius is reached. Example from the docs: cells with hp 20 and a ray of 100 energy: 5 cells penetrated.
- `max_durability_to_destroy` (default 10): cells with durability above it are never affected. Durability 0 means "no durability defined, hardness only" and is never blocked.
- `explosion_radius` default 20; `hole_enabled`; `hole_destroy_liquid` (default false: liquid cells are thrown, not deleted); `hole_destroy_physics_dynamic` (default true); `destroy_non_platform_solid_enabled`; `create_cell_material` (default `fire`) with `create_cell_probability` (default 5 %) turns destroyed cells into that material; sparks (`sparks_*`, `material_sparks_*`), stains, `shake_vegetation`, `knockback_force`, `physics_explosion_power`, `damage`; solid-cell explosions use `cell_explosion_*` (radius 5 to 150, damage required 100).
- Magic number `RANDOMIZE_LARGE_EXPLOSION_RAYS` = 1: ray directions of large explosions are randomised [W][G].
- Hardness examples [W]: an Energy Orb explosion (ray_energy 350,000) is shown in coal (hp 25,000, derived depth 14 cells) versus rock (hp 100,000, derived depth 3.5 cells); TNT (max durability 11, radius 28) outclasses Unstable Crystal (max durability 10): more than 30x the ray energy, so in rock the crystal removes 2 to 3 px and TNT reaches its full 28 px.
- Knockback on entities: `explosion_radius * knockback_force * inv_normalized_distance / target.mass` [W].
- Damage scaling by radius and `damage_mortals` etc. belong to the entity/damage design [W: Explosion interactions].

Spell explosion configs [G, 132 projectile configs, 115 of which set a radius, range 0 to 400, the rest use the default 20]: radius 250 for nuke, 60 bomb, 45 meteor, 30 mine and pipe bomb, 15 fireball and rocket, 7 grenade and powerdigger, 6 digger; `ray_energy` values: 100,000 digger, 200,000 powerdigger, 350,000 grenade, 280,000 mine, 120,000 pipe bomb, 50,000 fireball and death cross, 4,000,000 rocket, 6,000,000 bomb, 6,700,000 nuke, 7,500,000 meteor; `max_durability_to_destroy` is absent (default 10) in 105 of 132 configs, 8 in 10, 11 in 6 (bomb among them), 12 in 2 (nuke among them), 14 in 2; `create_cell_material` fire with probability 100 on fireball and meteor.

Derived penetration depth in cells per ray, `E / hp` [DES, from the documented rule; whether Noita uses `>=` or `>` and how it treats the first cell is UNVERIFIED]:

| Explosion | E | sand 800 | soil 2,000 | coal powder 1,000 | rock 100,000 (dur 10) | steel_static 130,000 (dur 12) |
|---|---|---|---|---|---|---|
| default | 20,000 | 25 | 10 | 20 | 0 | blocked |
| digger (R 6) | 100,000 | 125 | 50 | 100 | 1 | blocked |
| grenade (R 7) | 350,000 | 437 | 175 | 350 | 3 | blocked |
| rocket (R 15) | 4,000,000 | all | all | all | 40 | blocked |
| bomb (R 60, dur 11) | 6,000,000 | all | all | all | 60 (capped by R) | blocked (12 > 11) |
| nuke (R 250, dur 12) | 6,700,000 | all | all | all | 67 | 51 |

So a nuke carves the full 250 px only through soft material and about 67 px through rock; plausible but unchecked against play.

### 8.2 Our carve algorithm [DES]

Inputs: centre, radius `R`, energy `E`, `D_max`, flags `{destroy_liquid, create_cell: (material, probability), throw}`, explosion id.

1. Rays: `N = clamp(ceil(2*pi*R), 32, 512)` (about one ray per boundary cell, so no boundary cell is skipped). Angle of ray `k`: `2*pi*(k + j_k)/N` with `j_k` a deterministic jitter from the stateless hash of `(seed, frame, explosion id, k)`. Use an integer direction table or the `libm` crate, never platform `sin`/`cos` (section 12). Total work `O(N*R) = O(2*pi*R^2)`: nuke 1.2 M cell visits, ordinary spells 5 to 50 k.
2. For each ray in index order, walk cells outward with a grid DDA up to `R`. Keep a per-explosion scratch bitmap ("already decided") so overlapping rays near the centre do not pay twice; a cell destroyed by an earlier ray counts as air.
3. At each cell: air costs 0. If `durability > D_max`: the ray stops (a hard cell absorbs it; whether Noita stops or skips is UNVERIFIED). Otherwise if the remaining energy is `>= hp` it is destroyed and the energy drops by `hp`; else the ray stops.
4. Destroyed cell: liquid and `!destroy_liquid` -> becomes a **particle** with outward velocity (speed from `physics_explosion_power`-like constant plus hash jitter); otherwise it is removed and, with probability `create_cell_probability`, replaced by `create_cell_material` (fire by default); powders and solids optionally spawn a "debris" particle (`material_sparks_*`, default off).
5. Output: list of changed cells' bounding box (to wake chunks), histogram of destroyed materials (`collect_materials_to_shooter`), entities within `R` for the damage system.
6. Explosions are queued by projectiles, reactions (`ExplosionConfig`), explosive cells; they run in a dedicated serial phase at a fixed point of the frame in queue order. Chain reactions defer to the next frame (bounded recursion). Per-frame caps: 32 explosions, `sum(R^2) <= 400,000`.

## 9. Projectile-versus-cell collision

### 9.1 What is known [W]

- Noita exposes four ray tests in Lua: stop on **any cell**; stop on any cell that is not liquid, gas or fire (**surfaces**); stop on any cell that is not gas or fire (**surfaces and liquid-like**); stop on any cell a character can **stand on** (platforms). A `GetSurfaceNormal(x, y, ray_length, ray_count)` call estimates a normal with several short rays. Collision classes therefore come from the material kind plus `platform_type` (-1 = default, 234 materials; 0 = fall-through, 90; 1 = standable, 141; 2, 1 material [G]).
- ProjectileComponent [W]: `collide_with_world` (true), `penetrate_world` (false) with `penetrate_world_velocity_coeff` 0.6, `ground_penetration_coeff` (mass-dependent penetration) and `ground_penetration_max_durability_to_destroy`, `go_through_this_material`, `die_on_liquid_collision`, `on_collision_die` (true), `bounces_left` with `bounce_energy` 0.5, `bounce_always`, `bounce_at_any_angle`, `speed_min/max` 60 by default, `physics_impulse_coeff` 300.
- Fastest projectile in the data [G]: `long_distance_cast` speed 1,800, `luminous_drill` 1,400 with ground penetration up to durability 14, `ball_lightning` 1,000. Units are not stated; if px/s then at most 30 px/frame, which is inside the 32 px travel bound (UNVERIFIED).
- Noita's actual sweep algorithm is not documented (UNVERIFIED). Clones use Bresenham: TomatoJuice `line()` stops at the first occupied cell and records the previous cell; FallingSandEngine's `raycast` is a stepping line walk from point to point [R:world.rs].

### 9.2 Our design [DES]

- Entities (projectiles, player) are not cells; they are updated in a serial phase in entity-id order, reading the grid between cell passes.
- Per frame: `p1 = p0 + v/60`; integer DDA from the cell of `p0` to the cell of `p1`; test each cell against the projectile's **collision mask** over kinds {Static, Powder, Solid, Liquid, Gas, Fire} (default: Static|Powder|Solid, plus Liquid if `die_on_liquid_collision`). Result: `Hit { cell, material, last_free_cell, t }`.
- Normal: from occupancy in a 7 x 7 neighbourhood of the hit (sum of vectors to blocked cells, negated and normalised in integer or fixed point); this mirrors `GetSurfaceNormal` and is deterministic.
- Bounce: `v' = reflect(v, n) * bounce_energy`; `bounces_left` decrements. `penetrate_world`: continue through cells, speed scaled by 0.6 inside the world.
- Ground penetration (drill): after a hit with `durability <= ground_penetration_max_durability_to_destroy`, remove the cell and spend a penetration budget proportional to `mass * speed * coeff` (mapping UNVERIFIED).
- Entity AABB versus cells (player, enemies): sweep the box by columns/rows, use `platform_type` to decide standability, support a 1 to 3 px step-up. Not detailed here.

## 10. Rigid bodies from pixels

### 10.1 What is known about Noita

- Engine Box2D [W: PhysicsBodyComponent]. Pipeline per the talk (cited by the FallingSandJava README and the earlier research): marching squares -> simplification (Douglas-Peucker) -> triangulation -> Box2D shape; **recomputed when a body pixel is destroyed**; a body pixel knows its body and its local position inside it [N: 80.lv].
- Body components [W]: `PhysicsImageShapeComponent` builds a body from a PNG and a material (`is_circle`, `centered`, offsets); `PhysicsBodyComponent` defaults: `buoyancy` 0.7, damping 0, `allow_sleep` true, `gridworld_box2d` true (touches the grid), `go_through_sand` false, `hax_fix_going_through_ground` (lifts a body out of the ground), `auto_clean` (the simulation may delete a body hidden under sand), `kills_entity`, private `mPixelCount`. `PhysicsBody2Component` adds joints, `force_add_update_areas`, `mPixelCountOrig`.
- Material fields for solids [W]: `solid_friction` 0.3, `solid_restitution` 0.2, `solid_gravity_scale` 1, `solid_static_type` 0 to 5, `solid_collide_with_self`, `crackability`, `solid_on_break_explode`, `solid_break_to_type`, `convert_to_box2d_material`; liquids/powders may set `liquid_sand_never_box2d`. Of the 132 solid materials 119 have gravity scale 1, 6 have 1.3, 4 have 0 [G].
- Threading: separate Box2D thread with a 12 ms wait budget [W][G].

### 10.2 What the clones do (FallingSandEngine, BSD-3) [R:rigidbody.rs, mesh.rs, physics.rs, simulator.rs, world.rs]

1. Body pixels live in a **per-body bitmap** (w x h of cells) with a rapier transform.
2. Mesh: `contour` marching squares on the solid mask (smoothing on, seams along bitmap edges snapped), `ramer_douglas_peucker::rdp` with epsilon 1.0, `earcutr` triangulation (holes supported), one triangle collider per triangle in a compound shape, `PHYSICS_SCALE` = 10 px per physics unit. Disconnected loops become separate bodies (each pixel assigned to the nearest triangle loop).
3. Coupling each tick: body pixels are stamped into the grid as `Object` cells where the grid is empty so that sand and water collide with the body; where sand already sits under the body the code applies a counter impulse proportional to the point velocity, ejects the grain as a particle if relative speed > 1, and lowers the body's gravity scale by an "impediment" so a body can come to rest in sand; the stamps are removed after the sand tick.
4. When any body pixel is destroyed or turns non-solid, the body is removed and rebuilt from its pixels, keeping position, rotation and velocities.
5. Terrain static colliders: per-chunk meshes regenerated when a chunk loads or changes (FallingSandEngine), per-chunk edge marching -> RDP (epsilon 1 solid, 2 others) -> polyline colliders scaled x8 (TomatoJuice, Apache-2.0), connected components -> perimeter -> RDP 0.5 -> earcutr with a 0.1 s throttle per dirty chunk (noprobelm). noprobelm's `utils/geometry.rs` is engine-agnostic.
6. Crates (versions of 2026-10-07 from `rust-prior-art.md`): rapier2d 0.36, contour 0.13, ramer_douglas_peucker 0.2, earcutr 0.5. Licences of the geometry crates were not checked here (UNVERIFIED).

### 10.3 Plan: defer, with hooks [DES]

Defer for the MVP (PRD non-goal): rapier integration, mesh pipeline, body pixel stamping, sand-body impulses, body splitting, joints and ragdolls, terrain collider meshes. Rapier determinism across platforms and threads is UNVERIFIED (check its `enhanced-determinism` option and keep its `parallel` feature off before adopting).

Cheap hooks to keep now:
1. Material table keeps `box2d: bool` and the solid parameters; the 132 solid materials map to `Static` in the MVP.
2. A reserved cell flag/kind meaning "occupied by a body: not simulated, not displaceable, owned by body N". Stamping later then needs no rule changes.
3. The frame pipeline (section 13.6) has named hook points `bodies_stamp` before the cell passes and `bodies_unstamp` after.
4. All entity/projectile queries go through `Grid::blocked(mask)` so body pixels count automatically later.
5. Entity physics is fixed-point inside the core; a later f32 rapier lives behind a boundary conversion.
6. Intermediate, rotation-free option if falling debris is wanted earlier: connected-component check after destruction; detached components become "clusters" that translate with integer gravity and re-deposit when they rest (a mini rigid body without rotation). Not in the MVP.

## 11. Performance numbers

### 11.1 What exists

| Item | Number | Tag |
|---|---|---|
| Nolla frame time / throughput | none published | UNVERIFIED. HN user "sydd" reports lag on big explosions on an i7-7700 (comment 24397769). |
| Loaded cells | 3,145,728 (12 x 512^2) | derived |
| FallingSandEngine author comments | testing `dynamic()` before cloning a cell "reduces update time by like 90 %"; `#[inline(always)]` on the per-pixel function "speeds up `simulate_chunk` by about 35 %" | [R:simulator.rs], author claims, not measured by us |
| sandspiel | 300 x 300 = 90,000 cells, renders in under 1 ms, 66 KB wasm | prior-art survey, secondary |
| falling-rust | criterion benches on a 64 x 64 world (empty, water flow, burning oil); figures not captured | [R:simulation_benchmark.rs] |
| Cell visit cost | 5 to 30 ns per **active** cell on one core is the usual range for this kind of rule code | UNVERIFIED expectation; to be measured by our own benchmark |

### 11.2 Budgets derived from the PRD [DES]

| World | Cells | Chunks | 6 B/cell | Budget |
|---|---|---|---|---|
| 512 x 512 bench (>= 5x realtime) | 262,144 | 64 | 1.5 MiB | 16.67 ms / 5 = 3.33 ms per frame = 12.7 ns per cell if **all** cells were active on one thread |
| 1024 x 1024 (>= 60 Hz) | 1,048,576 | 256 | 6.0 MiB | 16.67 ms per frame = 15.9 ns per cell all-active single thread; about 48 ns per cell with 4 effective threads |
| 2048 x 1536 game world | 3,145,728 | 768 | 18.0 MiB | same as Noita's loaded set; only the active rectangle and dirty rects are paid for |

Dirty rectangles are the first-order optimisation (a settled world costs about zero); threads are second. Memory per window of 4 x 4 tiles is 96 KiB, the centre chunk alone 24 KiB.

### 11.3 Benchmarks to run on our core (benchmark-first)

Empty world; sand rain 5 % fill; water pour into a basin; lava and water; burning oil lake; 10 explosions of radius 30 and one of 250; fully active random soup (worst case); 1/2/4/8 thread scaling; dirty rect on versus all-dirty. Record ns per active cell and per frame in the criterion results.

## 12. Determinism: keeping the sim bit-identical across thread counts

### 12.1 How the clones fail or succeed

| Repo | Source of nondeterminism or determinism |
|---|---|
| FallingSandEngine [R] | `fastrand::Rng::new()` per chunk tick (entropy-seeded); `AHashMap` iteration to build phase lists; `par_extend` of particles; scan direction random per chunk |
| noprobelm [R] | global `WyRand`, groups processed in **random order**, positions shuffled, shared `HashSet` of visited entities; README admits undefined parallel movement order |
| sandspiel [R] | one global `SplitMix64` seeded with a constant, sequential: deterministic but single-threaded |
| mintage [R:engine.rs, sim.rs] | modules emit **intents** in parallel, a serial resolver applies them in module order with first-writer-wins per cell (a `changed` bitmap) and per-module seeds (`base_seed ^ constant`): deterministic regardless of threads |
| FallingSandSurvival [R] | one thread-pool job per selected chunk (`ctpl`, 6 threads); determinism is not a stated goal and its RNG use was not inspected |
| Noita | runs are seeded (`WORLD_SEED` magic number [W]); whether the threaded cell simulation is deterministic is UNVERIFIED |

### 12.2 Our rules [DES]

| Concern | Rule |
|---|---|
| Parallel schedule | Tasks of one pass own disjoint windows (section 5): the result is independent of which thread runs which task and when. Barrier between passes. |
| RNG | **No shared mutable RNG.** Preferred: stateless per-cell random function. A cell visit derives `h = mix64(seed ^ frame*K1 ^ pass*K2 ^ cell_index*K3)` lazily on the first draw (SplitMix64 finaliser) and takes bytes from `h`, rehashing with a counter after 8 draws. Fallback: per-chunk xoshiro256** seeded from `splitmix64(seed ^ frame ^ (chunk << 32) ^ (pass << 48))` and consumed in scan order; this satisfies thread independence but not the next property. |
| Dirty-rect transparency | With the stateless generator, visiting extra cells (an all-dirty rect) cannot change the result because skipped cells are exact no-ops that consume no shared random stream. This gives the strongest tests: state after N frames is identical with dirty rects on or off, and a snapshot needs only cells + frame + seed (+ particles/entities); dirty rects are rebuilt as "all dirty" on load. It requires: no per-cell counters that write when a cell is merely visited, and `keep_awake` instead of writes for timers. |
| Floating point | Cell rules are integer-only. Material parameters (fall steps, lateral range, probabilities) are converted to integers or 8-bit probabilities at load by one fixed rounding rule. Entity, particle and explosion kinematics use fixed point. Rust `f32` `+ - * /` and `sqrt` are IEEE-deterministic across x86-64 and arm64 if no fused multiply-add is introduced; transcendental functions are not (use `libm`-style software functions or tables). |
| Containers | No `HashMap`/`HashSet` iteration anywhere in `step`. Dense `Vec` by id. If a hash map is needed for lookup, never iterate it. |
| Parallel merges | Each task returns its outputs (spawned particles, queued explosions, write bounding boxes) in a local `Vec`; the merge runs serially in ascending chunk index order, then sorts by explicit unique keys (`id`) before use. Do not rely on rayon preserving order of an unindexed `par_extend` (UNVERIFIED). Merge operations must be commutative (rect union) or ordered. |
| Pass order | A pure function of `(seed, frame)`, e.g. rotate the four classes by `frame % 4`. Never random from a thread RNG. |
| Chunk scan direction | `(frame + cx + cy) & 1`; balanced in time and in space. |
| Time and IDs | No wall clock; entity ids from a counter; sort ties by id. |
| Cosmetic randomness | Colour variants come from a stateless hash of `(seed, creation frame, position, material)` and never consume physics randomness, so renderers or palette changes cannot alter physics. Variants are still part of the cell and therefore of the state hash. |
| Hashing | State hash over cells with `UPDATED` cleared, in fixed chunk order, plus particles (sorted by id), entities and wands. Use a 64-bit word-wise mixer (not byte-wise FNV: 18 MB per hash). Optionally cache per-chunk hashes and rehash only chunks written since the last hash. |
| Physics engines | rapier/Box2D deferred; pin the exact version when added. |

### 12.3 Tests that prove it

1. **Thread counts**: golden hash after 3,000 frames for 1, 2, 3, 8, 16 threads (PRD criterion).
2. **Pass-order independence**: run each pass with its tasks in a random permutation (and sequentially): hash must match. This tests the disjoint-window invariant directly.
3. **Dirty-rect transparency**: all-dirty versus normal: hash must match each frame.
4. **Snapshot/restore**: save at frame k, restore with all-dirty, run to N: hash equals the uninterrupted run.
5. **Reach monitor** (debug builds): track the maximum `|dx|, |dy|` of every `get`/`set`; assert <= 32; log the observed maximum (should stay <= 16 under the policy of 13.1).
6. **Soup fuzz**: random material soup with a fixed seed for several seeds; no panic, hash stable.

## 13. Recommended concrete design for `noita_core`

### 13.1 Constants

| Constant | Value | Reason |
|---|---|---|
| `CHUNK` | 64 | Noita [N]; chunk is the scheduling and dirty-rect unit |
| `TILE` | 32 | storage block, makes the safe-Rust window split possible (13.3) |
| `MAX_REACH` | 32 (= CHUNK/2) | theorem in section 5; compile-time assert |
| `RULE_REACH` | 16 (policy; liquid lateral <= 10) | margin so rule authors cannot hit the bound by accident |
| `WAKE` | 12 | dirty-rect dilation: liquid lateral range 10 + 2 |
| `PASSES` | 4 | checkerboard |
| `MAX_STEPS_PER_VISIT` | 6 | multi-step falling |
| `MAX_PARTICLES` | 100,000 | Noita emitter cap [W] |

### 13.2 Cell layout (6 bytes, no padding) [DES]

| Offset | Field | Type | Meaning |
|---|---|---|---|
| 0 | `mat` | u16 | material id (Noita allows 1,024 [W]; our table has 466 [G]) |
| 2 | `life` | u8 | remaining lifetime in 8-frame units (max lifetime 1,350 frames = 169 units [G]); 0 = no timer |
| 3 | `burn` | u8 | remaining burn in material-specific units (`ceil(fire_hp/250)` frames); 255 = endless |
| 4 | `var` | u8 | colour variant, cosmetic, from a stateless hash |
| 5 | `flags` | u8 | bit0 `UPDATED` (transient), bit1 `BURNING`, bit2 `DIR` (lateral flow preference), bits 3-7 reserved (e.g. `OBJECT` for future body pixels) |

Why not more: Noita itself stores only a material id plus an optional custom colour per cell in its save files [W: File Formats], there is no per-cell temperature or velocity in any source, and a smaller cell keeps a 64x64 chunk at 24 KiB (cache friendly) and the whole 2048 x 1536 world at 18 MiB. Why not fewer: `life` and `burn` are needed by 38 and 137 materials respectively [G], and merging them would force a write for every timer. sandspiel's cell is 4 bytes (`species`, `ra`, `rb`, `clock`), falling-rust's `Cell { element, variant, strength, visited }`, astratomic's about 11 to 12 bytes [R][REF]; ours sits between.

### 13.3 World storage and window split

- World dimensions are multiples of 64. Storage is a `Vec<Tile>` where `Tile = [Cell; 32*32]` (6 KiB), indexed `ty*TW + tx`; chunk metadata is a separate `Vec<ChunkMeta>` indexed `cy*CW + cx`.
- Why tiles: a window (128 x 128 centred on a chunk, section 5) is exactly **4 x 4 tiles**. For class `(ox, oy)` window `(k, m)` owns tiles `tx in [4k + 2ox - 1, 4k + 2ox + 3)` and `ty` likewise, and a tile belongs to exactly one window per pass. Each pass builds the window list with **one `iter_mut()` over the tile vector**, pushing each `&mut Tile` into its window's 16 slots, then runs `par_iter_mut()` over the windows. No `unsafe`, no `UnsafeCell`; this replaces the aliasing trick that FallingSandEngine's author flags as probable undefined behaviour [R:chunk_handler.rs], and the "centre + half sides + quarter corners" borrow of astratomic [REF] falls out of the same geometry.
- Window-local access: `(wx, wy)` in `0..128`, slot `(wy>>5)*4 + (wx>>5)`, cell `((wy&31)<<5) | (wx&31)`. A missing slot (outside the world) reads as the indestructible `boundary` material and ignores writes (sandspiel's wall semantics [R]).
- Fallback if profiling shows the indirection costs more than 10 %: flat `y*W + x` array behind one documented `unsafe` pointer wrapper with the same window invariant (the draft in `design.md`).

### 13.4 Scheduler

Per frame:
1. `order = rotate([(0,0),(1,0),(0,1),(1,1)], frame % 4)`.
2. For each class in `order`: build windows; for each window with a dirty chunk (and inside the active rect) run the chunk task in parallel; barrier; serial merge of task outputs in ascending chunk index (particles, queued explosions, write boxes with `WAKE` dilation).
3. Chunk task: scan rows from the bottom of the chunk's dirty rect to the top; columns in the direction `(frame + cx + cy) & 1`; for each cell: skip if `UPDATED`, or `Air`/`Static`; else dispatch by `Kind` (6.3 to 6.6) then the reaction step (6.7).
4. End of frame: clear `UPDATED` over each chunk's `next` rect (parallel per chunk); `dirty = next; next = None`.

### 13.5 Rule API (sandspiel `get`/`set` style) [DES; idea from sandspiel `SandApi`, MIT]

Rules never see the world, only a per-visit context bound to one window and one cell (relative coordinates, `+y` is down):

| Call | Semantics |
|---|---|
| `get(dx, dy) -> Cell` | read; boundary material outside the world; debug-asserts `abs(dx) <= MAX_REACH` and `abs(dy) <= MAX_REACH` |
| `set(dx, dy, cell)` | write, stamps `UPDATED`, extends the chunk's write box and wake set |
| `swap(dx, dy)` | exchange with the target, stamps `UPDATED` on both, moves flags (`BURNING`, `burn`, `life`) with the cell |
| `mat(id) -> &Material` | read-only material table (density, kind, integer parameters) |
| `rand()` | lazily initialised stateless generator for this cell visit: `chance(p_u8)`, `below(n)`, `bit()`, `dir()` |
| `keep_awake()` | add own position to `next` without writing (timers, burning) |
| `emit_particle(...)`, `request_explosion(...)` | queued in the task-local output, merged deterministically |
| `frame()`, `pos()` | frame number; absolute position (for hashing only, rules must not branch on position except through `rand`) |

This keeps every rule a pure function of its neighbourhood, makes rules unit-testable on a 5 x 5 patch (sandspiel's strength), and makes cross-window access impossible by construction.

### 13.6 Frame pipeline

1. Inputs applied; entity logic; wands cast (spawn projectiles, material emitters).
2. `bodies_stamp` (hook, empty in MVP).
3. Projectile/entity sweeps (serial, id order): hits, bounces, queued explosions.
4. Explosion phase (serial, queue order): carve, throw particles, wake boxes.
5. Four cell passes (parallel inside each).
6. Particle phase (serial, id order): move, deposit.
7. `bodies_unstamp` (hook).
8. End-of-frame cleanup, dirty rotation, event list, optional state hash.

### 13.7 Parameter derivation table (Noita field -> our integer parameter)

| Noita field | Our parameter | Mapping | Status |
|---|---|---|---|
| `density` | `density_q8` (u16, density x 256) | exact (42 distinct values) | direct |
| `liquid_gravity` g | `fall_q8` | steps per frame `2*g`, integer part certain, fraction as probability, cap 6 | UNVERIFIED |
| `liquid_flow_speed` f, `liquid_damping` d | `lateral` L | `round(f/(1-d))`, cap 10, halved by `liquid_slime` | UNVERIFIED |
| `liquid_viscosity` v (powder) | `slide_p` | `clamp(1 - v/200, 1/4, 1)` as u8 | UNVERIFIED |
| `gas_*_speed` | direction weights and act probability | up 100, side 100 each, down 90, act 50 % | UNVERIFIED reading |
| `lifetime` (frames) | `life0` | `ceil(lifetime/8)` units, start jitter +-12 % from stateless hash | direct + design |
| `fire_hp`, `autoignition_temperature`, `temperature_of_fire`, `requires_oxygen` | `burn0`, `ignite_threshold`, `source_heat`, `needs_air` | section 6.6 | UNVERIFIED |
| `hp`, `durability` | `hp: u32`, `dur: u8` | exact; durability 0 never blocks | direct |
| `platform_type` | `stand: i8` | exact | direct |
| reaction `probability` | `p_u16` per-visit | `probability/100` of a roll on a random 4-neighbour | UNVERIFIED rate |

### 13.8 Provenance of each idea (licence status)

| Design element | Taken from | Licence |
|---|---|---|
| 64x64 chunks, dirty rect per chunk, 4-pass checkerboard, bottom-up scan, 32 px reach | Noita statements (facts) | n/a |
| Class formula, `par_iter` per phase, dirty propagation, particle promotion and deposit, per-body bitmap and mesh pipeline, "Object" stamp pixels, impediment | FallingSandEngine, FallingSandSurvival | BSD-3-Clause |
| `get`/`set(dx,dy)` rule API with a +-2 guard, species-as-functions, clock skip | sandspiel | MIT |
| form + flags classification, `dissolve_to` strength countdown, bench layout (empty, water, burning oil) | falling-rust | MIT |
| Dirty advance with inflation and border flags (idea); geometry helpers for later | noprobelm bevy_falling_sand | MIT OR Apache-2.0 |
| Bresenham `line()` sweep for fast movers and projectiles; countdown chunk sleep (not adopted); edge-marching colliders | 100-TomatoJuice | Apache-2.0 |
| Intent/resolver pattern (reserved for reactions/temperature if cross-chunk conflicts appear), per-module seeds | mintage | MIT |
| Rule ideas for velocity-driven cells | EP01_SandSim | BSD-3-Clause |
| Window = centre + half sides + quarter corners (we derived the same geometry from the 80.lv statement; no code used) | astratomic | PolyForm Noncommercial: read-only, **do not copy** |
| Stripe threading contrast | FallingSandJava | no licence: read-only |
| GPL/AGPL repos (Powder Toy, JMS55/sandbox, fallingrust, PowderRS) | not consulted for code | do not copy |

### 13.9 Differences from the draft in `design.md` (for the planners to reconcile)

1. **Updated mark**: draft uses a parity bit refreshed by visiting; with dirty rects that stalls cells (section 4.2). Use `UPDATED` + end-of-frame clear.
2. **Wake margin**: draft wakes "within 1 of a border plus a 1-cell halo"; liquids read up to 10 cells away. Use `WAKE = 12`.
3. **Reach**: draft `MAX_REACH = 16` is a fine policy but the hard bound is 32 = CHUNK/2; keep both constants.
4. **RNG**: draft seeds a per-chunk xoshiro; we prefer a stateless per-cell hash (dirty-rect transparency, snapshot simplicity) and keep xoshiro as the fallback.
5. **Storage**: draft flat array plus `unsafe` wrapper; we propose 32 px tiles with a safe window split and keep the flat array as fallback.
6. **Cell**: draft 5 B padded to 6 with `variant, life, flags`; we add a separate `burn` byte and drop the parity bit (same 6 B).
7. **Pass order**: draft fixed; we rotate it deterministically by frame.
8. **Particles**: draft mentions a particle list; we specify fixed point, a 32 px per frame cap, id-ordered serial stepping for the MVP.

### 13.10 Risks and open questions

| Item | Risk | Mitigation |
|---|---|---|
| Parameter mappings in 13.7 | rules look wrong versus Noita | calibrate by footage frame counts; keep them in the material table, not in code |
| One rect per chunk | wasted scans with scattered activity | measure; add tile bitmap only if needed |
| Tile indirection cost | slower `get` than a flat array | benchmark; fallback documented |
| Serial explosion and particle phases | spikes on nukes (1.2 M ray steps; 100 k particles) | per-frame caps; move to parallel if profiled |
| Rapier determinism | breaks bit-identity when bodies arrive | defer; pin versions; hash tests per version |
| Reach violations by new rules | silent data race in the fallback unsafe layout | debug monitor (12.3), compile-time constants, code review rule: "no `get` farther than `RULE_REACH`" |
| Noita internals unknown | we match behaviour, not code | acceptable: the benchmark needs clear rules, not pixel-exact replication |

## Unverified claims register

1. Row/column alternation in Noita; whether Noita keeps a per-frame or per-pass visited mark.
2. Which loaded chunks Noita steps each frame; meaning of `GRID_MAX/MIN_UPDATES_PER_FRAME`.
3. How Noita re-deposits flying pixels; whether particles are processed inside the checkerboard.
4. The exact ray count, jitter, hard-cell behaviour (stop vs skip), `>=` vs `>` energy test and liquid cost in Noita's explosion carving; TNT's `ray_energy` (absent from the parsed config; the wiki implies at least about 2.8 M).
5. Meaning of `liquid_viscosity`, `liquid_damping`, `liquid_sticks_to_ceiling`, and the unit of `fire_hp` decrement; direction of `requires_oxygen`.
6. Units of projectile `speed` (px/s assumed).
7. Whether Noita's cells store velocity or burn counters at runtime (the save format stores material and colour only).
8. Rapier cross-platform determinism options.
9. Cell visit cost and every performance expectation in 11.1 and 11.2 beyond the arithmetic.
10. Licences of the geometry crates (`contour`, `ramer_douglas_peucker`, `earcutr`).

## Sources

Local research files (under `./.trellis/tasks/10-16-noita-cogbench/research/`):
- `noita-engine-constants.json`, `pixel-sim-repos.json`, `rust-prior-art.md`, `materials.json`, `reactions.json`, `spells.json`, `benchmark-design.md`
- `../design.md`, `../prd.md` (task design draft and PRD)
- `raw/braindump_jethro_dev_posts_gdc_vault_exploring_the_tech_and_.txt` (GDC 2019 notes)
- `raw/Falling_Sand_Game.wikitext`, `raw/Density.wikitext`, `raw/Durability.wikitext` (redirect to `Materials#Durability`), `raw/Materials.wikitext`, `raw/Explosion.wikitext`, `raw/Explosion_interactions.wikitext`, `raw/Fire.wikitext`, `raw/Rigid_Body.wikitext` (redirect to Props)
- `raw/Documentation__ConfigExplosion.wikitext`, `raw/Documentation__ProjectileComponent.wikitext`, `raw/Documentation__PhysicsBodyComponent.wikitext`, `raw/Documentation__PhysicsBody2Component.wikitext`, `raw/Documentation__PhysicsImageShapeComponent.wikitext`, `raw/Documentation__Reaction.wikitext`, `raw/Documentation:_ParticleEmitterComponent.wikitext`
- `raw/Modding__Making_a_custom_material.wikitext`, `raw/Modding__Magic_Numbers.wikitext`, `raw/Modding:_Lua_API.wikitext`, `raw/Technical__File_Formats.wikitext`, `raw/Expert_Guide__Waypoints.wikitext`, `raw/Cursed_Rock.wikitext`, `raw/Biomes.wikitext`, `raw/Digging.wikitext`
- `raw/noitadata/data/magic_numbers.xml` and `raw/noitadata/data/materials.xml` (numbers only, via `materials.json`)
- Mirrored permissive-licence repo sources: `raw/repos/FallingSandEngine/{simulator,chunk,chunk_handler,particle,rigidbody,mesh,physics,world}.rs`, `raw/repos/FallingSandSurvival/{Chunk.hpp,world_cpp_tick_excerpt_L1091-1140.cpp}`, `raw/repos/sandspiel/{lib,species}.rs`, `raw/repos/falling-rust/{cell,element,mod,simulation,simulation_benchmark}.rs`, `raw/repos/noprobelm_bevy_falling_sand/{coord,dirty,systems,static_mesh,geometry}.rs`, `raw/repos/TomatoJuice_bevy_falling_sand/{chunk,movement,simulation,sandbox,gen_colliders}.rs`, `raw/repos/mintage/{engine,intent,sim,util}.rs`, `raw/repos/EP01_SandSim/main_c_excerpt_L1-330.c`, `raw/repos/README.md`

Web pages (read-only fetch on 2026-10-07 because the talk summaries were not mirrored locally; summaries were produced by a fetch tool and cross-checked against `noita-engine-constants.json`):
- https://80.lv/articles/noita-a-game-based-on-falling-sand-simulation/ (64x64 chunks, dirty rect, 4-pass checkerboard with +32 px, pixel ownership of rigid bodies, fire ignition direction)
- https://blog.macuyiko.com/post/2020/an-exploration-of-cellular-automata-and-graph-based-game-systems-part-4.html (quotes of the GDC talk: single buffer, 32 px guarantee, pixels into a particle simulation)
- https://braindump.jethro.dev/posts/gdc_vault_exploring_the_tech_and_design_of_noita/

Wiki and repository URLs:
- https://noita.wiki.gg/wiki/Modding:_Making_a_custom_material, /Modding:_Magic_Numbers, /Modding:_Lua_API, /Technical:_File_Formats, /Expert_Guide:_Waypoints, /Cursed_Rock, /Biomes, /Density, /Materials, /Documentation:_ConfigExplosion, /Documentation:_ProjectileComponent, /Documentation:_PhysicsBodyComponent, /Documentation:_PhysicsBody2Component, /Documentation:_PhysicsImageShapeComponent, /Documentation:_ParticleEmitterComponent, /Documentation:_Reaction, /Explosion_interactions, /Fire, /Falling_Sand_Game, /Digging
- https://github.com/MaxBittker/sandspiel, https://github.com/PieKing1215/FallingSandEngine, https://github.com/PieKing1215/FallingSandSurvival, https://github.com/grunnt/falling-rust, https://github.com/noprobelm/bevy_falling_sand, https://github.com/100-TomatoJuice/bevy_falling_sand, https://github.com/astradamus/mintage, https://github.com/GameEngineering/EP01_SandSim, https://github.com/spicylobstergames/astratomic (read-only), https://github.com/DavidMcLaughlin208/FallingSandJava (read-only)
- https://news.ycombinator.com/item?id=24397769 (HN comment on explosion lag)
