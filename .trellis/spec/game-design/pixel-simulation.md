# Pixel Simulation: Grid, Chunks, Scheduling, Motion Rules, Particles, Explosions, Grid Queries

**Purpose / when to read this.** Normative reference for `noita_core::sim` (this is the `sim-rules.md` that `materials-reactions.md` MAT-R09 plans): the cell grid and cell record, 64x64 chunks and dirty rectangles, the 4-pass parallel scheduler, per-kind motion (powder, liquid, gas, fire, static), density swaps, free-flight particles, explosion carving, the grid queries projectiles and entities use, the determinism contract, performance budgets, and the deferred rigid-body hooks. Read it before touching `World`, `Cell`, `sim::{chunk,rules,explode,query}`, the cell RNG, or any test of frame-by-frame grid behaviour. Cite `SIM-Rnn` from code and tests; test vectors are `SIM-Tnn`.
**Division of labour.** Material fields, tags, reaction semantics, burning numbers, durability and ray-energy numbers: `materials-reactions.md` (`MAT-`, `RXN-`, `FIRE-`, `DUR-`, `MVP-`, decisions `D1-D13`). Entity damage: `entities-damage.md`. Projectile and spell data: `spells.md`. Protocol, hashing algorithm, seeds: `benchmark.md` (`DET-`, `PROTO-`, `VER-`). This page fixes *when and how* those inputs run on the grid. Frames are 1/60 s, lengths are cell pixels, y grows down.
**Tags on every rule.** `[N]` stated by Nolla (GDC 2019 talk as relayed by 80.lv / macuyiko; these pages were web-fetched, only the 554-byte braindump stub is mirrored locally, see Pitfall 1). `[W]` noita.wiki.gg. `[G]` read from the parsed game data. `[R]` observed in a permissively licensed clone (an idea, not a Noita fact). `[DES]` our decision, normative for the clone. `[CAL]` tunable calibration: the Noita mapping is UNVERIFIED and the number lives in the material table or `sim::consts`, never inline. **UNVERIFIED** = no primary source. **DECISION-NEEDED** = user choice, default stated (ids `SD1-SD13`, see Simplifications). Source shorthand: `PST` research/pixel-sim-tech.md, `RPA` rust-prior-art.md, `PSR` pixel-sim-repos.json, `EC` noita-engine-constants.json, `MJ` materials.json, `RJ` reactions.json, `TI` tags_index.json, `SJ` spells.json, `MR` spec/game-design/materials-reactions.md, `BEN` benchmark.md, `ED` entities-damage.md, `SP` spells.md, `DSN`/`PRD` task design.md / prd.md, `W:Page` = noita.wiki.gg/wiki/Page (local raw/Page.wikitext).

## Normative rules

### A. Space, time, cell record

- **SIM-R01 Coordinates and time** [N][W][DES]. x grows right, y grows down, "below" = +y; 1 cell = 1 px. One tick = one frame = 1/60 s; every duration and timer in the sim is an integer number of frames. World width and height are multiples of 64. Reads outside the world return the `boundary` material (indestructible, blocks everything, never written); out-of-world writes are ignored. Source: PST §0, §13.3; W:Cursed_Rock (2.5 damage/frame = 150/s); BEN PROTO-R04.
- **SIM-R02 Geometry** [N][W][DES]. Simulation chunk = 64x64 cells, the scheduling and dirty-rect unit [N]. Storage tile = 32x32 cells [DES]. Noita's streaming/save "broad chunk" is 512x512 = 8x8 sim chunks [W]; informational only, the clone has a fixed-size world without streaming. Source: PST §2.1, §13.1; EC `world.*`.
- **SIM-R03 Cell record** [DES]. Exactly 6 bytes, no padding: `mat:u16, life:u8, burn:u8, var:u8, flags:u8` (layout in Key numbers). `flags`: bit0 `UPDATED` (transient, SIM-R15), bit1 `BURNING`, bit2 `DIR` (lateral preference, 0 = left), bit3 `OBJECT` (reserved, SIM-R86), bits 4-7 reserved. No velocity, temperature or wetness in the cell. `u16` is mandatory (466 materials in the data, engine cap 1,024). Proposal: expose only BURNING in the RL `flags` channel (BEN OBS-R07 leaves the set open). Source: PST §13.2; W:Modding:_Magic_Numbers (`CELLFACTORY_CELLDATA_MAX_COUNT`); W:Technical:_File_Formats (saves hold only material id + optional colour).
- **SIM-R04 Kinds** [W][G]. Derived once at load (MR MAT-R03; use the `kind` field of `MJ`, produced by `scripts/build_materials_json.py kind_of`):

| Kind | Derivation | Count in `MJ` | Motion |
|---|---|---|---|
| Air | material id `air` (index 0); `MJ` lists it with kind `liquid` | 1 (inside the 100 "liquid") | none, never visited |
| Static | `liquid_static=1` (terrain: cell_type liquid + sand + static) | 103 | never moves, never displaced |
| Powder | cell_type liquid, `liquid_sand=1`, not static | 87 | down, diagonal-down |
| Liquid | cell_type liquid, `liquid_sand=0` | 99 (+ air) | down, diagonal-down, lateral hop |
| Gas | cell_type gas | 26 | up, lateral |
| Fire | cell_type fire (3 real fire materials + 15 `spark*`) | 18 | like gas, into Air only |
| Solid | cell_type solid (Box2D body material) | 132 | MVP: treated as Static (SIM-R85) |

- **SIM-R05 Integer ingestion** [DES]. Every float a cell rule consumes is converted once at load: `x100 = round_half_away(v * 100)` (gravity, flow, damping, viscosity have at most 2 decimals; checked over all 466), densities have at most 4 decimals and are stored `density_x10000: u32` (exact; SD6). Derived parameters (fall steps, lateral range, probabilities as `u8/256`) are computed from these integers with integer arithmetic and round-half-up. No float is read inside a per-cell rule. Float ties are real: in f64, `0.1/(1-0.8)` = 0.5000000000000001. Source: PST §12.2, §13.7; `MJ`.
- **SIM-R06 Material table** [DES]. Immutable during a run, part of `content_hash` (BEN VER-R03). Index = rank by `xml_order`, `air` = 0 (MR MAT-R01, D12). The sim binds `air`, `fire`, `smoke`, `water` by name and aborts if absent (MR MAT-R02). Fields that do not apply to a kind carry defaults or noise (statics show `liquid_gravity` 1.2, gases 0.5): a kind only reads its own fields (Pitfall 4).

### B. Chunks and dirty rectangles

- **SIM-R10 Dirty rect** [N]. Each chunk keeps one dirty rectangle (chunk-local min/max x,y in 0..63, packed 4 x u8) of the cells that need simulating this frame; cells outside it are not visited. A settled region costs nothing. Noita states no other sleeping mechanism (no per-cell sleep counter). Source: 80.lv via PST §3.1.
- **SIM-R11 No-op condition and wake margin** [DES]. A skipped cell must be an exact no-op. If a cell at `p` is written in frame `f`, every cell within `r` of `p` (`r` = largest read distance of any rule: lateral hop 10, fall 6, diagonal/reaction/ignition 1) may behave differently in `f+1`, so `dirty(f+1)` must contain `[p-WAKE, p+WAKE]` with `WAKE = 12`. A 1-2 px margin (DSN draft, noprobelm) is wrong for liquids. Source: PST §3.3, §3.5.
- **SIM-R12 Keep-awake** [DES]. A visit calls `keep_awake()` (adds its own position to `next` without writing) when the cell is unchanged but could change later: (a) it has a running timer (`life` or `burn`) or is BURNING; (b) a probabilistic action was physically possible and its roll failed (move, slide, hop, sink, mix, ignite, react); (c) a reaction partner is adjacent. A cell blocked for every random outcome, without timer or reactive neighbour, is settled; the cost of (c) is proportional to the number of cells next to reactive partners (e.g. water next to soil, xml_183), so measure it (SIM-R82). Reason: SIM-R72. Extension of PST §3.4 and §12.2 (the source covers timers only). Consequence: the 54 `RJ` rows with `air` as input (rock+air->moss 1 %, ...) would keep every exposed surface awake in the full 466-material set; MVP-40 has only 6 such rows (MR xml_005/021/053/111/168/179), so it is accepted (SD9).
- **SIM-R13 Write bookkeeping** [DES]. A chunk task never mutates another chunk's metadata. It records the bounding box of its writes per touched chunk (at most 9 boxes; one box per window is allowed but coarser) in its task-local output. After each pass a serial merge, in ascending chunk index, dilates each box by `WAKE`, clips it to every chunk it overlaps and unions it into that chunk's `next`. End of frame: `dirty = next; next = None`. Own-chunk writes extend `next` immediately. Source: PST §3.5.
- **SIM-R14 Active rectangle** [DES]. Only chunks intersecting the chunk-aligned `active` rect are scheduled (the game world 2048x1536 may be larger than the active rect; benchmark worlds 512x512 and 1024x1024 are fully active). Frozen chunks keep their cells, remain readable by queries, and re-activate fully dirty. Rule writes into frozen chunks: they are treated as `boundary` (SD4). UNVERIFIED which chunks Noita steps each frame; it keeps 12 broad chunks loaded [W]. Source: PST §2.2.
- **SIM-R15 UPDATED flag** [DES]. `set` and `swap` raise `UPDATED` on every written cell. `UPDATED` gates **visits only**: a cell with it is skipped as a mover for the rest of the frame, whichever pass it lands in; it may still be displaced as a swap target. It is cleared at the end of the frame by a per-chunk sweep over the `next` rect (every written cell lies inside it), never serialised, never hashed. Parity bits and generation stamps are forbidden: with dirty rects a stamped cell is not refreshed and is wrongly skipped 2 frames (u8 stamp: 256 frames) later (DSN draft §2.3 has this bug). Source: PST §4.2; the target-displacement clause is this page's reading.

### C. Scheduling and parallelism

- **SIM-R20 Scan order** [N][DES]. Single buffer, updated in place [N]. Inside a chunk: rows bottom-up through the dirty rect [N]; columns in direction `(frame + cx + cy) & 1` (0 = left to right) [DES; Noita's column order UNVERIFIED]. A cell is skipped if it is Air, `UPDATED`, or Static/Solid that is neither BURNING nor reactive. Bottom-up lets falling columns move as a train; upward movers (gas, buoyant liquid, displaced cells) land in rows visited later and rely on `UPDATED`. Source: PST §4.1.
- **SIM-R21 Four-pass checkerboard** [N][DES]. Chunk `(cx,cy)` has class `(cx&1, cy&1)`. A frame runs 4 passes, one per class, the chunks of a class in parallel, a barrier after each pass [N]. Pass order for frame `f` = `rotate([(0,0),(1,0),(0,1),(1,1)], f mod 4)` (left rotation by `f`) [DES], a pure function of the frame. All 8 neighbours of a chunk have a different class. Rotating the order averages out the bias of a fixed order (the first class sees the pre-frame state); DSN §2.3 had it fixed. Rejected: FallingSandSurvival's 6 iterations x 4 passes per tick (we use multi-step movement inside one visit, SIM-R31, so each cell is still visited once per frame) and column stripes (FallingSandJava: 2 barriers but coarse load balance). Source: PST §5.1, §5.3, §12.2, §13.4.
- **SIM-R22 Reach theorem** [N][DES]. A task may read and write cells within `MAX_REACH = 32 = CHUNK/2` of its chunk: its window is 128x128 centred on the chunk. Windows of same-class chunks are disjoint iff `R <= C/2` (cell x=63 touches <= 95, the next same-class chunk's cell x=128 touches >= 96), so a pass result does not depend on task order or thread timing. 32 px is also Nolla's stated bound on pixel travel per frame [N]. Compile-time assert `2*MAX_REACH <= CHUNK`. Source: PST §5.2.
- **SIM-R23 Reach policy** [DES]. Rule authors stay within `RULE_REACH = 16` of their own cell. Debug builds assert every `get/set` offset `<= MAX_REACH` and every read offset `<= WAKE` (SIM-R11). Current maxima: lateral hop 10, fall 6, diagonal 1, reaction 1, ignition 1, flame emission 1. Source: PST §13.1.
- **SIM-R24 Storage and window split** [DES]. World = `Vec<Tile>` of 32x32 tiles (6 KiB). For class `(ox,oy)`, window `(k,m)` owns tiles `tx in [4k+2ox-1, 4k+2ox+3)` and `ty in [4m+2oy-1, 4m+2oy+3)` (4x4 tiles = 128x128 px = 96 KiB); each tile belongs to exactly one window per pass. Build the window list with one `iter_mut()` over the tiles, then `par_iter_mut()` over windows: safe Rust, no `UnsafeCell` (the Rust clone FallingSandEngine flags its own aliasing as probable UB). A missing slot (outside the world) reads as `boundary`. Fallback only if profiling shows the indirection costs more than 10 %: flat `y*W+x` array behind one documented `unsafe` wrapper with the same invariant. Source: PST §13.3.
- **SIM-R25 Rule API is the only access path** [DES]. `get(dx,dy)`, `set(dx,dy,cell)`, `swap(dx,dy)`, `mat(id)`, `rand()`, `keep_awake()`, `emit_particle(..)`, `request_explosion(..)`, `frame()`, `pos()`. Rules never see the world; `pos()` is for hashing only. `swap` moves `flags`, `life`, `burn`, `var` with the cell and raises `UPDATED` on both. Every rule is a pure function of its neighbourhood, so it is unit-testable on a 5x5 patch. Source: PST §13.5 (idea from sandspiel's `SandApi`, MIT).
- **SIM-R26 Task outputs** [DES]. Particles, queued explosions and write boxes are returned task-locally and merged serially in ascending chunk index (SIM-R13, SIM-R74).

### D. Motion and per-cell visit

- **SIM-R30 Visit order and swap semantics** [DES][W][G]. A visit runs: (1) timers (SIM-R35; expiry deletes the cell and ends the visit); (2) burning step (SIM-R37); (3) reaction step (SIM-R38); (4) motion (Powder, Liquid, Gas, Fire), skipped if the cell was rewritten or moved in 1-3. Motion that enters a target **swaps** the two cells (matter conserved, both `UPDATED`):

| Mover | Target | Result |
|---|---|---|
| any | Air | move |
| Powder, Liquid | Gas, Fire | swap (the gas/fire cell is pushed into the vacated cell) |
| Powder, Liquid | Liquid | swap iff `density(M) > density(T)` (strict; equal = blocked), with probability `SINK_CHANCE` (liquid mover 3/4, powder mover 1) [CAL] |
| Powder, Liquid | Powder, Static, Solid | blocked (a powder may still slide diagonally, SIM-R31) |
| Liquid | equal-density different liquid | vertical blocked; lateral swap with probability `MIX_CHANCE` 1/16 [CAL] (W:Density: equal densities "mix") |
| Gas | Air | move |
| Gas | Gas | swap iff `density(T) > density(M)` (the lighter gas rises through the heavier) |
| Fire | Air | move; Fire into anything else: blocked |
| Gas, Fire | Liquid, Powder, Static, Solid | blocked (gas never bubbles up through liquid; it is lifted only when a liquid sinks past it) |

**SIM-R30 (cont.)** Only Air, Gas, Fire and Liquid cells are ever displaced. Kind gates, density orders: statics have densities 4 to 11 and are still never entered (Pitfall 5). A lighter liquid below a heavier one rises because the heavier one sinks; there is no separate rising rule. Source: PST §6.1-6.2; MR MAT-R08; W:Density; MJ.
- **SIM-R31 Powder** [DES][CAL]. Fall: `steps = fall_int + Bernoulli(fall_frac_q8/256)` per visit with `2g` in hundredths (`g` = `liquid_gravity`): `fall_int = floor(2g)`, `fall_frac_q8 = round_half_up(frac(2g)*256)`, capped at `MAX_STEPS_PER_VISIT = 6`; `g = 0` gives Bernoulli(1/8) (W: "with 0 it still falls, but slow and weird"). Each step tries `(0,+1)` under SIM-R30; stop at the first failed step. If no step succeeded, try `(-1,+1)` and `(+1,+1)` in the order `DIR xor 1 random bit`, powders only with probability `slide_p = clamp(1 - viscosity/200, 1/4, 1)` as `u8` (default viscosity 50: 0.75; soil 75: 0.625). `liquid_sticks_to_ceiling` and `stickyness` are not modelled. The visit counts as one move for `UPDATED`. Mapping UNVERIFIED; calibrate the angle of repose against footage. Source: PST §6.3, §13.7; W:Making_a_custom_material.
- **SIM-R32 Liquid** [DES][CAL]. Fall exactly like a powder (down, then both diagonals, always attempted: viscosity is ignored for liquids, W says "no noticeable difference?"; lava is slow because `liquid_gravity` is 0.2). If the cell did not move vertically: lateral hop. `L = round_half_up(flow / (1 - damping))` in integers, `L = (2*f100 + (100-d100)) / (2*(100-d100))` (default flow 0.9, damping 0.8 gives 5; damping 0.9 gives 9; flow 0.1 gives 1; flow 0.3 gives 2), `liquid_slime` halves `L` (floor, minimum 1), cap 10 (`WAKE` derives from it). Direction from `DIR`; flip `DIR` with probability 1/8 and whenever the first lateral cell is blocked. Scan outward up to `L` cells through enterable cells (Air, Gas, Fire), stop at the first non-enterable cell, then hop to the end of the free run in one move. Source: PST §6.4; W:Making_a_custom_material; `MJ` (liquid kind: flow 0.9 x94, 0.1 x4, 0.3 x2; damping 0.8 x96, 0.9 x4; slime x6).
- **SIM-R33 Mixing and layering** [DES][CAL]. `SINK_CHANCE` slows layering so mixtures settle visibly; `MIX_CHANCE` lets equal-density liquids interpenetrate. Data checks: sand 6 > water 4 > oil 1; lava 6 equals sand 6 (sand does not sink in lava); gunpowder 7 and snow 8 sink in lava; blood 4.1 sinks below water 4; water 4 > acid 2.9 > oil 1 (MR MV-11).
- **SIM-R34 Gas** [N][DES][CAL]. Noita checks up, then sideways [N]. Per visit: with probability `gas_speed/100` (50 %) the gas acts; it tries `(0,-1)` under SIM-R30, else `(+-1,0)` in `DIR` order (one cell), never moves down by choice. `DIR` flips when the first lateral cell is blocked. All 26 gases carry the same four numbers (50/100/100/90), so they carry no per-material information. The literal 4-weight reading (P(up) = 100/390 = 26 %, P(down) = 23 %) gives a net drift of about 0.013 px/frame (about 1 px/s), i.e. gas would not visibly rise, and contradicts the [N] check order and the wiki ("flowing upward and forming lakes in cave-ceiling pits"): rejected (SD3). Source: PST §6.5; W:Materials; MJ.
- **SIM-R35 Timers** [DES]. `life` = remaining lifetime in units of `life_unit` frames, `burn` = remaining fuel in units of `burn_unit` frames; both are per-material constants. `life_unit` = smallest integer `u >= 1` with `ceil(lifetime/u) <= 255`; a timer decrements on frames where `frame % unit == 0`; a cell never stores `life = 0` while alive; reaching 0 removes the cell (to Air; W: "material disappears when lifetime runs out"). All 15 distinct lifetimes in the data (4, 5, 10, 50, 150, 200, 240, 250, 300, 350, 410, 450, 900, 1000, 1350) are exact with `u` in {1, 2, 4, 6}. `burn_unit = max(1, ceil(fire_hp/250))`, `burn0 = ceil(fire_hp/unit)` (<= 250); `fire_hp` of -1 or >= 90,000 stores 255 (endless); `fire_hp = 0` converts on the first burning step. Initial `life` gets +-12 % jitter from the cell RNG [CAL]. Cells with a timer call `keep_awake()` (SIM-R12). Amends MR D5/D8 (global 8-frame quantum, which rounds `flame` 5 frames up to 8 and `rat_powder` 4 frames up to 8): SD2. Source: `MJ` (`lifetime_frames`, `fire_hp`); PST §13.2.
- **SIM-R36 Fire cells** [W][DES]. Fire-kind cells (`fire`, `fire_blue`, `flame`, 15 `spark*` that have `on_fire=0` and `temperature_of_fire` 0: MR FIRE-R07) move like gas into Air only and expire by life. `MJ` gives lifetime 0 for all of them except `flame` = 5, so the engine's expiry is UNVERIFIED: use MR D6 (uniform 12-30 frames, from the cosmetic `RENDER_FIRE_LIFETIME_MIN/MAX`) for `fire`, `fire_blue` and sparks. Fire is the only material the engine requires [W:Fire].
- **SIM-R37 Burning hook** [N][DES]. A BURNING cell (flammable material ignited, or an `on_fire` material at creation) and every Fire-kind cell run the burning step: keep awake; if `requires_oxygen` and no 4-neighbour is Air/Gas/Fire, neither progress nor emit (reading per MR FIRE-R05); decrement `burn`; at 0 become `on_fire_convert_to_material` if set else Air (no ash: MR FIRE-R04); emit flame/smoke into a random free 4-neighbour; pick **one random neighbour per frame** and try to ignite it [N: a burning pixel picks a random direction and tries to ignite that pixel]. Fire-kind cells skip the fuel steps (they have no `burn` counter): they only emit and ignite, and expire by `life` (SIM-R36). Numbers (strict `temperature_of_fire(source) > autoignition(target)`, chance `(100-autoignition)%`, 4-neighbour, flame chance `generates_flames/100`, fuel table) are MR FIRE-R03..R06 and D4/D5; PST §6.6 used `>=`, 8 neighbours and `/255`, superseded by MR (Pitfall 9). Water does not clear BURNING (MR FIRE-R08); lava ignites through reaction rows (MR FIRE-R09). Source: 80.lv via PST §6.6; MR.
- **SIM-R38 Reaction hook** [DES]. A visited non-Air cell whose material is flagged `reactive` examines one random 4-neighbour (MR RXN-R04, D2), looks the pair up in the dense table `reactions[a*n + b]` (compiled per MR RXN-R02..R08) and rolls `cell_rand.below(10000) < round(p*100)` (MR MV-08; this uses SIM-R70, not a chunk stream: SD1). A rewritten cell gets `UPDATED`. A failed roll on an existing pair calls `keep_awake()` (SIM-R12b). `direction`, blobs, `req_lifetime`, 3-input rows are MR's (RXN-R09..R14, MVP-R03). A reaction may only touch cells within `RULE_REACH`: blob radius <= 6 in MVP-40; the radius-15 and radius-40 blobs of `RJ` (MR RXN-R10) are out of MVP, and radius 40 would exceed `MAX_REACH` (SIM-R22).
- **SIM-R39 Static** [W][DES]. Static (and MVP-mapped Solid) cells never move and are never displaced; they can be removed (explosion, acid reaction), burned (12 flammable statics, e.g. `wood_static`) or converted (reactions). They participate as reaction partners and as BURNING cells.

### E. Free-flight particles

- **SIM-R45 Particles** [N][W][DES]. Cells have no velocity. Fast motion is a `Particle {mat:u16, x,y: Q16.16 px, vx,vy: Q16.16 px/frame, life:u16, id:u32}`; fixed point so it is bit-identical on every platform. Noita puts pixels thrown by splashes and explosions into a particle simulation with velocity and gravity [N: macuyiko quote of the talk; W: ConfigExplosion `hole_destroy_liquid`, ParticleEmitterComponent `create_real_particles`]. Creators: explosions throwing liquid cells, splashes of fast entities/projectiles entering liquid, material-spawning spells, optional powder promotion. Cap `MAX_PARTICLES = 100,000` (Noita's emitter cap [W]); overflow drops the newest. Emitter modes in Noita [W]: `create_real_particles` places cells directly (velocity and lifetime ignored), `emit_real_particles` keeps working off-screen, `emit_cosmetic_particles` collide with the grid but are culled outside the camera and never interact otherwise. Reference [R] FallingSandEngine: a falling grain becomes a particle when the cell below and the 4 beyond are empty, start velocity `(+-0.25, 1..2)`. Source: PST §7.
- **SIM-R46 Particle step** [DES][CAL]. Once per frame after the cell passes, serially in ascending `id`: `vy += GRAV` with `GRAV = 200 px/s^2 = 3641/65536 px/frame^2` (the ParticleEmitterComponent default `gravity (0,200)`; the Lua cosmetic default is 100; FallingSandEngine uses 0.1 px/tick^2); clamp so the displacement per frame is <= 32 px; sweep old to new cell with an integer DDA; Air is passed, Gas/Fire are passed unless the particle is `collide_with_gas_and_fire`; at the first non-passable cell: if it is a lighter Liquid the particle swaps through (the liquid cell is pushed up one cell), else deposit at the last free cell; if none is free search an outward spiral to radius 6, else destroy. Lifetime cap 600 frames (emitter `lifetime_max` 10 s [W]): on expiry deposit if the cell is free. Reference [R]: FallingSandEngine (BSD-3) steps `vy += 0.1` per tick with `floor(sqrt(|vx|+|vy|)) + 1` sub-steps, deposits at the start cell if free else displaces, last resort `upwarp` (`vy = -1`, `y -= 16`); 100-TomatoJuice walks a Bresenham line toward `pos + velocity` with integer velocity, +1 gravity per frame, retrying rotated 45 and 90 degrees (3 candidates for powder, 5 for liquid/gas). Source: PST §7.2-7.3; W:Documentation:_ParticleEmitterComponent.
- **SIM-R47 Particle determinism** [DES]. Spawn velocity and jitter come from the stateless hash of `(seed, frame, source id, k)`; ids are a monotone counter; cost estimate 20,000 particles x <= 32 reads = 0.64 M reads, about 1-3 ms (UNVERIFIED). If it matters, step particles inside the pass tasks (reach <= 32) and merge hand-overs in chunk order.

### F. Explosions (numbers: MR DUR-R01..R05, MVP table)

- **SIM-R50 Ray model** [W][G]. An explosion traces rays from its centre; each ray carries `ray_energy` (default 20,000), every non-Air cell it crosses costs the cell's `hp`; a cell is removed only if `durability <= max_durability_to_destroy` (default 10; durability 0 = unset, never blocks); the ray ends when energy is used up or at `explosion_radius` (default 20). Wiki example: hp 20, energy 100 gives 5 cells. Cells removed per ray in a uniform material = `min(R, ceil(E/hp))` (a cell is removed if energy > 0 on arrival: MR DUR-R02; it reproduces "Unstable Crystal removes 2-3 px of rock" with its two configs 170,000 / 280,000: 2 and 3 cells). Hard cells (durability > cap) stop the ray (UNVERIFIED stop vs skip; MR D6). `RANDOMIZE_LARGE_EXPLOSION_RAYS = 1` [W][G]. Source: W:Documentation:_ConfigExplosion, W:Materials; MR DUR-R01/R02.
- **SIM-R51 Our carve** [DES]. Rays `N = max(16, ceil(2*pi*R))` (MR D6; one ray per boundary cell, no cap: PST's clamp to 512 skipped cells beyond R = 81). Ray `k` angle `2*pi*(k + j_k)/N`, `j_k in [0,1)` from the stateless hash of `(seed, frame, explosion id, k)`; use an integer direction table or `libm`, never `std` `sin/cos`. Walk each ray with a grid DDA from the centre to `R`; a per-explosion scratch bitmap marks decided cells so overlapping rays near the centre do not pay twice; a cell destroyed by an earlier ray counts as Air. Work is `O(2*pi*R^2)`: nuke (R 250) 0.39 M cell visits, giga nuke (R 400) 1.0 M (PST §8.2 quoted 1.2 M for R 250: arithmetic error, Pitfall 10).
- **SIM-R52 Cell outcomes** [W][DES]. Air costs 0. A destroyed Liquid with `hole_destroy_liquid = false` (default) becomes a **particle** thrown outward (SIM-R45), otherwise it is removed. Any other destroyed cell is removed and, with probability `create_cell_probability` (default 5 %), replaced by `create_cell_material` (default `fire`; fireball and meteor 100 %). Powder/solid debris particles (`material_sparks_*`) are off. Big explosions in Noita also load `loose_ground` side entities that turn the terrain around the crater into falling powder (Bomb, Holy Bombs, Nuke, Giga Nuke, Meteor): mechanism UNVERIFIED (SP SPELL-R35), not simulated.
- **SIM-R53 Outputs** [DES]. The carve returns the changed-cells bounding box (to wake chunks; dilated by `WAKE` in the next merge), a histogram of destroyed materials (`collect_materials_to_shooter`) and the entities within `R` for the damage system (ED). Entity knockback is `explosion_radius * knockback_force * inv_normalized_distance / target.mass` [W: ConfigExplosion], applied entity-side.
- **SIM-R54 Phase and caps** [DES][CAL]. Explosions are queued by projectiles, reaction rows with an `ExplosionConfig` (3 in `RJ`) and explosive cells, and run in a dedicated serial phase at a fixed point of the frame (SIM-R80 pipeline) in queue order. Chain reactions defer to the next frame (bounded recursion). Per-frame caps: 32 explosions and `sum(R^2) <= 400,000`; the rest carries over in queue order (SD12). Material-triggered explosions (15 materials with an `explosion_config`, MR FIRE-R10) are MR's decision.

### G. Grid queries for projectiles and entities

- **SIM-R60 Four ray masks** [W]. Noita exposes four tests: `Raytrace` stops on any (non-Air) cell; `RaytraceSurfaces` stops on any cell that is not liquid, gas or fire (reading: powders and statics are surfaces; UNVERIFIED); `RaytraceSurfacesAndLiquiform` stops on any cell that is not gas or fire; `RaytracePlatforms` stops on any cell a character can stand on. `GetSurfaceNormal(x, y, ray_length, ray_count)` estimates a normal with several short rays. The clone exposes `blocked(mask)` over the kind bitmask {Static, Powder, Solid, Liquid, Gas, Fire} with these four presets. Source: W:Modding:_Lua_API; PST §9.1.
- **SIM-R61 Phase** [DES]. Entities and projectiles are not cells. They run in a serial phase in entity-id order, reading the grid between the cell passes (frame pipeline SIM-R80). The 32 px reach bound does not apply to them (projectile terminal velocity 1000 px/s = 16.7 px/frame, SPELL-R23; `LONG_DISTANCE_CAST` 1,800 px/s = 30 px/frame; Lightning is higher; the player's own fall speed is 350 px/s, ED), because a serial sweep touches no task window.
- **SIM-R62 Projectile sweep** [DES]. Per frame `p1 = p0 + v/60`; integer DDA (Bresenham) from the cell of `p0` to the cell of `p1`; the first cell matching the projectile's collision mask is a hit `Hit {cell, material, last_free_cell, t}`. Default mask for `collide_with_world`: Static, Powder, Solid (MR MVP-R05: liquids are non-blocking; `die_on_liquid_collision`, default false, adds Liquid; `go_through_this_material` removes one material from the mask). Noita's own sweep is UNVERIFIED. Source: PST §9.2; W:Documentation:_ProjectileComponent.
- **SIM-R63 Normal, bounce, penetration** [DES]. Normal = negated, normalised sum of vectors to blocked cells in the 7x7 neighbourhood of the hit (integer or Q16.16). Bounce: `v' = reflect(v, n) * bounce_energy` (default 0.5), `bounces_left` decrements. `penetrate_world`: continue through cells at `penetrate_world_velocity_coeff` 0.6. Ground penetration (drill): spend a budget from `ground_penetration_coeff` while `durability <= ground_penetration_max_durability_to_destroy` (Luminous Drill: coeff 4, max 14, 1,400 px/s); the slow-down formula is UNVERIFIED (MR DUR-R05). Source: PST §9; W:Documentation:_ProjectileComponent.
- **SIM-R64 Entity collision class** [DES]. By kind (MR MVP-R05): Static, Powder, Solid block; Liquid is buoyant and non-blocking; Gas and Fire pass. `platform_type` is not used in the MVP: 29 plant/fungus powders have `platform_type 0` ("fall through", `grass`, `moss`, mushrooms) and `cloud`/`cloud_lighter` gases have 1; none is in MVP-40. If plants are added, `platform_type 0` must stop blocking. Source: MR MAT-R13; `MJ`.
- **SIM-R65 AABB sweeps** [DES]. Player/enemy boxes sweep column/row-wise against `blocked(mask)`, with auto step-up of ledges up to `climb_over_y` = 4 px (collision box x -2..2, y -4.5..2.1). Details belong to ED §1; unit conversion 1 px/frame = 60 px/s.

### H. Determinism contract

- **SIM-R70 Stateless cell RNG** [DES]. No shared mutable RNG. A visit derives `h = mix64(cell_seed ^ frame*K1 ^ pass*K2 ^ index*K3)` lazily on the first draw (`pass` = 0..3, the position in that frame's pass order; redundant with `frame` and `index` but harmless) (SplitMix64 finaliser; `K1..K3` fixed odd 64-bit constants), `index = y*W + x` of the visited cell in **world** coordinates (independent of tile layout), and takes one byte of `h` per draw, re-hashing with a counter after 8 draws. `cell_seed = blake3(seed || "cells")` truncated to 64 bits, as BEN DET-R04 derives subsystem seeds. Draws: `chance(p_u8)` = `byte < p`, `below(n)`, `bit()`, `dir()`. Changing any constant changes the state hash (BEN VER-R02 minor bump). Fallback if SD1 is rejected: per-chunk xoshiro256** seeded from `(seed, frame, chunk, pass)` consumed in scan order (then SIM-R72 cannot hold). Source: PST §12.2.
- **SIM-R71 Integer and fixed point** [DES]. Cell rules are integer-only; particles and explosion kinematics are Q16.16. Entity/projectile kinematics: BEN DET-R06 allows `f32` with `+ - * / sqrt` only (IEEE-deterministic across x86-64 and arm64 without fused multiply-add) and transcendental functions via `libm` or tables; PST §10.3 prefers fixed point so that a later `f32` rapier sits behind a boundary conversion (SD13, default: BEN). No wall clock anywhere in `step`. Entity ids from a counter.
- **SIM-R72 Dirty-rect transparency** [DES]. State after any number of frames is identical with dirty rects on, off (all-dirty), and after a snapshot restore into all-dirty. Needs SIM-R12 and SIM-R70 and forbids per-cell counters that write on mere visits. Source: PST §12.2-12.3.
- **SIM-R73 Order functions** [DES]. Pass order (SIM-R21) and column direction (SIM-R20) are pure functions of `(frame, cx, cy)`, never of a thread RNG.
- **SIM-R74 Merges and containers** [DES]. No `HashMap`/`HashSet` iteration in `step` (BEN DET-R05); dense `Vec` by id. Task outputs merge serially in ascending chunk index, then sort by explicit unique keys (`id`); merge operations are commutative (rect union) or ordered. Do not rely on rayon preserving the order of an unindexed `par_extend` (UNVERIFIED). BEN DET-R05's "deterministic commit phase" is satisfied by SIM-R22 disjoint windows plus this serial merge.
- **SIM-R75 Hashed bytes** [DES]. The state hash covers: frame, `cell_seed`, all cells serialised as 6 B in chunk-index then row-major order **with `UPDATED` cleared**, particles sorted by id, entities, wands. The algorithm and Merkle structure are BEN DET-R02/R03 (blake3, per-chunk leaves rehashed only for chunks written since the last hash); `var` is hashed (it is part of the cell). Hashing is read-only on the sim (SD8).
- **SIM-R76 Cosmetic randomness** [DES]. `var` comes from a stateless hash of `(seed, creation frame, position, material)` and never consumes physics draws, so palette or renderer changes cannot alter physics.
- **SIM-R77 Reach monitor** [DES]. Debug builds track the maximum `|dx|,|dy|` of every `get/set` and assert `<= MAX_REACH`; the observed maximum must stay `<= 16` (log it).
- **SIM-R78 Snapshot** [DES]. A snapshot is `cells + frame + seed (+ particles, entities)`; dirty rects are rebuilt as all-dirty on load (SIM-R72 guarantees equal results).

### I. Frame pipeline and performance

- **SIM-R80 Frame pipeline** [DES]. (1) inputs, entity logic, wands cast (spawn projectiles, material emitters); (2) `bodies_stamp` hook (empty in MVP); (3) projectile/entity sweeps, serial, id order; (4) explosion phase, serial, queue order; (5) four cell passes (pass order SIM-R21), serial merge after each; (6) particle phase, serial, id order; (7) `bodies_unstamp` hook; (8) `UPDATED` clear, `dirty = next`, events, optional hash. Compatible with DSN §3 `Game::step` (projectiles, then `world.step()`). Source: PST §13.6.
- **SIM-R81 Budgets** [DES][PRD]. Release build on an M-series Mac: 1024x1024 with an active rect around the player at >= 60 Hz (<= 16.67 ms/frame); 512x512 headless at >= 5x realtime (<= 3.33 ms/frame, >= 300 frames/s). Per-cell budget = `frame_budget * threads / cells` (all-active worst case, Key numbers). Dirty rects are the first-order optimisation, threads the second. SD7.
- **SIM-R82 Benchmarks first** [DES]. criterion benches on the core record ns per active cell and per frame for: empty world; sand rain 5 % fill; water pour into a basin; lava + water; burning oil lake; 10 explosions of R 30 and one of R 250; fully active random soup; 1/2/4/8 threads; dirty rects on versus all-dirty. No official Nolla numbers exist (HN user "sydd" reports lag on large explosions on an i7-7700), so all performance targets are ours. Reference points [R], author claims not measured here: FallingSandEngine's author reports about 90 % less update time from testing `dynamic()` before cloning a cell and about 35 % from `#[inline(always)]` on the per-pixel function; sandspiel renders 300x300 in under 1 ms; falling-rust benches a 64x64 world (empty, water flow, burning oil). Source: PST §11.

### J. Rigid bodies (deferred)

- **SIM-R85 Deferred** [DES][PRD]. No Box2D/rapier in the MVP (PRD non-goal): the 132 Solid materials map to Static, with `box2d: bool` and the `solid_*` parameters kept in the table (`MJ.solid`; 119 have gravity scale 1, 6 have 1.3, 2 have 0.5, 1 has 0.8, 4 have 0). Entity numeric type: SD13. `SP` S3 proposes kinematic "rolling" bodies for Bomb/Dynamite/boxes instead of Box2D (DECISION-NEEDED there).
- **SIM-R86 Hooks to keep now** [DES]. (1) `box2d` flag and solid parameters in the material table. (2) Reserved cell flag `OBJECT` = "occupied by a body: not simulated, not displaceable, owned by body N". (3) Named pipeline hooks `bodies_stamp` / `bodies_unstamp` (SIM-R80). (4) All entity/projectile queries go through `Grid::blocked(mask)` so body pixels count automatically later.
- **SIM-R87 Plan when added** [N][W][R]. Noita: marching squares -> simplification -> triangulation -> Box2D shape, rebuilt when a body pixel is destroyed; every body pixel knows its body and local position [N: 80.lv]; Box2D steps on its own thread with a 12 ms wait budget and freezes stuck bodies (`BOX2D_THREAD_MAX_WAIT_IN_MS`, `BOX2D_FREEZE_STUCK_BODIES` [W]). Reference pipeline (FallingSandEngine, BSD-3): per-body pixel bitmap, `contour` -> `ramer_douglas_peucker` (eps 1.0) -> `earcutr` -> rapier compound of triangles (crates, 2026-10-07: rapier2d 0.36, contour 0.13, ramer_douglas_peucker 0.2, earcutr 0.5; licences of the geometry crates UNVERIFIED); body pixels are stamped into the grid as `Object` cells during the cell tick and removed after. Terrain colliders (not needed while bodies are absent): Noita lets a body declare update areas (`force_add_update_areas`), implying terrain colliders exist only near dynamic bodies [W]; clones regenerate per-chunk meshes on change (FallingSandEngine), edge-march -> RDP (eps 1 solid, 2 other) -> polyline scaled x8 (100-TomatoJuice), or connected components -> perimeter -> RDP 0.5 -> earcutr throttled to 0.1 s per dirty chunk (noprobelm). Sand/body coupling in FallingSandEngine: a counter impulse proportional to the contact point velocity, grains ejected as particles above relative speed 1, and an "impediment" that lowers the body's gravity scale so it can rest in sand. Pin the exact rapier version and keep its `parallel` feature off; cross-platform determinism UNVERIFIED (check `enhanced-determinism`). Source: PST §10; RPA §2, §4.

## Key numbers

| Constant | Value | Unit | Tag / source |
|---|---|---|---|
| Frame rate | 60 | Hz | [W] Cursed_Rock; 1 px/frame = 60 px/s |
| Simulation chunk / storage tile | 64 / 32 | px | [N] / [DES] |
| Broad (streaming) chunk | 512 = 8x8 sim chunks | px | [W] |
| Chunks Noita keeps loaded | 12 broad = 3,145,728 cells = 768 sim chunks | count | [W] Expert_Guide:_Waypoints, `STREAMING_CHUNK_TARGET` 12 |
| Virtual screen | 427 x 242 = 103,334 cells (3.3 % of the loaded set) | px | [W] Magic Numbers |
| Normal world width | 35,840 = 70 broad chunks | px | [W] Biomes |
| Game world (default) / benchmark worlds | 2048x1536 (4x3 broad, 768 chunks) / 512x512 (64 chunks), 1024x1024 (256) | px | [DES] / BEN, PRD |
| Passes per frame | 4 | count | [N] |
| `MAX_REACH` / `RULE_REACH` / `WAKE` | 32 / 16 / 12 | px | [N] bound / [DES] |
| Max pixel travel per frame | 32 = 1,920 px/s | px | [N] |
| Liquid lateral cap / fall cap | 10 / 6 | cells | [DES] |
| `MAX_PARTICLES` | 100,000 | count | [W] `PARTICLE_EMITTER_MAX_PARTICLES` (Mar 2023) |
| Max materials / in data | 1,024 / 466 | count | [W] / [G] |
| Cell / chunk / tile / window | 6 B / 24 KiB / 6 KiB / 96 KiB (4x4 tiles) | bytes | [DES] |
| World memory | 512x512 1.5 MiB; 1024x1024 6 MiB; 2048x1536 18 MiB | MiB | derived |
| Box2D thread wait | 12 | ms | [W] `BOX2D_THREAD_MAX_WAIT_IN_MS` |
| `GRID_MAX/MIN_UPDATES_PER_FRAME`, `GRID_FLEXIBLE_MAX_UPDATES` | 128 / 40 / 0 | - | [W]; meaning UNVERIFIED, do not use (40 = 8x5 chunks is numerology) |
| `GRID_RENDER_TILE_SIZE` / `GRID_RENDER_BORDER` | 32 / 2 | px | [W]; render only |
| Engine defaults (material) | density 1, durability 0, hp 100, `liquid_gravity` 0.5, flow 0.9, damping 0.8, viscosity 50, gas 50/100/100/90, autoignition 100, tof 10, flames 30, `requires_oxygen` 1, platform_type -1 | - | [W] Making_a_custom_material |
| Counts by kind | Static 103, Powder 87, Liquid 99 (+air), Gas 26, Fire 18, Solid 132 | count | [G] `MJ` |
| Density | 42 distinct values 1 to 50; liquids 1-14.5 (oil 1, acid 2.9, water 4, blood 4.1, lava 6, void 14.5); powders 2-10 (54 of 87 are 6); statics 4-11 (81 of 103 are 10); gases 1 or 2 (cloud 4.17) | - | [G] |
| `hp` / durability | hp 5 to 1,000,000 (40 distinct); durability 0 for 329 of 466, else 2-16 | - | [G]; cell `hp` is a ray cost, not entity HP (no x25) |
| Lifetimes | 38 materials: 23 gases (50-1,000), 10 liquids, 4 powders (4 frames), `flame` 5; max 1,350 | frames | [G] |
| `liquid_gravity` (liquid kind) | 0 x3, 0.1 x5, 0.2 x4, 0.3, 0.5 x14, 0.6 x2, 0.7 x3, 0.8 x22, 0.9 x2, 1.0 x6, 1.2 x6, 1.5 x28, 3 x4 | - | [G] |
| Fall steps (`2g`) | water 1.5 -> 3; oil 0.5 -> 1; sand 0.9 -> 1 + 205/256; lava 0.2 -> 0.4 (102/256); gold 3 -> 6 (cap) | cells/visit | derived SIM-R31 |
| Lateral range `L` | default 5; damping 0.9 -> 9; flow 0.1 -> 1; 0.3 -> 2; slime halves | cells | derived SIM-R32 |
| Probabilities as `u8/256` | `SINK_CHANCE` 192, `MIX_CHANCE` 16, DIR flip 32, g=0 fall 32, gas act 128 | /256 | [CAL] |
| Particle gravity | 200 px/s^2 = 3641 (Q16.16) px/frame^2 | | [CAL]; v after 60 frames = 3.33 px/frame |
| Explosion defaults | radius 20, `ray_energy` 20,000, `max_durability_to_destroy` 10, fire 5 %, `hole_destroy_liquid` false | | [W] ConfigExplosion |
| Explosion sources | `DIGGER` R6 / 100k / 10; `GRENADE` R7 / 350k / 10; `ROCKET` R15 / 4M / 10; `BOMB` R60 / 6M / 11; `NUKE` R250 / 6.7M / 12; `NUKE_GIGA` R400 / 9.7M / 14 | px / energy / dur | [G] MR "Explosion/digger sources" is the table of record |
| Projectile defaults | speed 60, `bounce_energy` 0.5, `penetrate_world_velocity_coeff` 0.6, gravity_y 400 px/s^2, terminal 1000 px/s | | [W] Documentation:_ProjectileComponent, _VelocityComponent |
| Perf budgets (all-active, single thread) | 512x512 at 5x: 12.7 ns/cell; 1024x1024 at 60 Hz: 15.9 ns/cell; with `t` threads multiply by `t` (4 threads: 63.6 ns/cell) | ns | derived SIM-R81 |
| Entity HP display | internal x 25 (player 4.0 = 100); material contact damage (acid 0.125, lava 0.075 display/px/frame) is entity-side | | `ED`, MR HAZ-R02 |

**Cell layout (SIM-R03).**

| Offset | Field | Type | Meaning |
|---|---|---|---|
| 0 | `mat` | u16 | material index (air = 0) |
| 2 | `life` | u8 | remaining lifetime in `life_unit` frames; 0 = no timer |
| 3 | `burn` | u8 | remaining fuel in `burn_unit` frames; 255 = endless; used with BURNING |
| 4 | `var` | u8 | colour variant, cosmetic, stateless hash |
| 5 | `flags` | u8 | bit0 UPDATED, bit1 BURNING, bit2 DIR, bit3 OBJECT (reserved), 4-7 reserved |

## Data files

Paths are under `.trellis/tasks/10-16-noita-cogbench/research/`; the shipped copies go to `assets/` (DSN §1). Field-level detail of the material and reaction tables is `MR` (Data files, MAT-R01..R16); this table lists what the **sim** consumes.

| File | Records | Fields the sim reads | Canonical vs derived |
|---|---|---|---|
| `materials.json` | 466 (array in `xml_order`) | `id`, `kind`, `density`, `durability`, `hp`, `gravity.liquid_gravity`, `gravity.gas_*`, `dispersion.{liquid_flow_speed,liquid_damping,liquid_viscosity,liquid_slime,liquid_sticks_to_ceiling}`, `stickyness`, `lifetime_frames`, `platform_type`, `flammable`, `fire_hp`, `autoignition`, `temperature_of_fire`, `requires_oxygen`, `generates_smoke/flames`, `on_fire_flame_material`, `on_fire_smoke_material`, `on_fire_convert_to_material_raw`, `starts_on_fire`, `explosion_config` (15 materials), `solid.*` (132), `tags`, `xml_order` | Canonical = values resolved from `materials.xml` (snapshot NathanSnail/noitadata `e469a926`, file dated 2024-04-23, may lag the current game build). Derived = `kind`, `burns_into` (an annotated **string**: "air (engine default...)" x141, "never consumed (fire_hp=-1)" x2, a real id x1, null x322: never parse it as an id), `danger`, `notes` (free text with interpretations), `palette*`, `biomes`. |
| `reactions.json` | 339 (330 `xml_*` + 9 `engine_*` docs) | `input_a/b/c`, `output_a/b/c`, `probability` (329 int, 1 float 0.3, 7 null, 2 formula strings for freeze/melt rows), `direction`, `fast_reaction`, `req_lifetime`, `blob_radius_a/b`, `explosion` (3), `entity` (5), `is_tag_rule` | Canonical = XML; load `xml_*` only (MR RXN-R01). Order is priority. |
| `tags_index.json` | 79 tag keys | tag -> member ids (expands `[tag]` inputs; `[burnable]` 63, `[static]` 113) | derived from resolved XML tags |
| `spells.json` | 422 | `projectile_xml.projectile` (speed, bounces, `penetrate_world`; `ground_penetration_coeff` is dropped by the extractor, SP), `projectile_xml.explosion` (132 configs, 17 without radius = default 20, 105 without `max_durability_to_destroy` = default 10) | Explosion configs are **incomplete**: `<Base>`-inherited fields are not merged (24 configs lack `ray_energy`, DYNAMITE inherits 6,000,000 from `base_projectile_physics.xml`; SP DF/TV-D5). Use MR's "Explosion/digger sources" table. |
| `noita-engine-constants.json` | n/a | cross-check of Key numbers (each entry has `status` and `sources`) | not loaded at runtime; runtime constants live in `sim::consts` |
| `pixel-sim-repos.json` | 17 repos | licences, chunk sizes, dirty-rect and threading summaries | provenance only |
| `raw/noitadata/data/{materials,magic_numbers}.xml`, `raw/game/**` | n/a | numbers only | Nolla's copyrighted data: facts and numbers are fine, never paste code or markup |
| `materials_from_data_xml.json` (469, 3 duplicate names), `materials_from_wiki.json` (212) | | | intermediate/cross-check, **do not load** |

**Loader contract.** Parse `materials.json`; assert 466 materials and the kind counts of SIM-R04; map `air` to kind Air; convert numbers per SIM-R05; compute per-material `MotionParams {kind, density_x10000, fall_int, fall_frac_q8, slide_p, lateral_L, gas_act, life_unit, life0, burn_unit, burn0, tof, aut, reactive}`; compile reactions per MR; hash everything into `content_hash`. Nothing is derived at runtime from floats.

**Idea sources (licences).** Adapt with attribution: FallingSandEngine (BSD-3 code; its art is CC BY-NC, never vendor it; its `Cargo.toml` says `ARR` but LICENSE and README govern), FallingSandSurvival (BSD-3), sandspiel (MIT), falling-rust (MIT), noprobelm/bevy_falling_sand (MIT or Apache-2.0), mintage (MIT), EP01_SandSim (BSD-3). 100-TomatoJuice: Apache-2.0 per the GitHub API (`PSR`), but the mirrored `raw/repos/TomatoJuice_bevy_falling_sand/LICENSE` is a 14-byte "404: Not Found" stub and `Cargo.toml` has no licence field: treat as idea-only until verified. Read-only, never copy: astratomic (PolyForm Noncommercial), FallingSandJava (no licence), The Powder Toy (GPL-3), JMS55/sandbox (AGPL-3), transistorfet/fallingrust and PowderRS (GPL-3). Source: RPA §3, `PSR`.

## Worked examples / test vectors

No sim test-case JSON exists (`wand-cast-test-cases.json` is wands only). Propose `noita_core/tests/data/sim_vectors.json`. **Patch notation:** rows listed top to bottom, y grows down, outside the patch is `boundary`; `.` Air, `#` rock_static, `S` sand, `W` water, `O` oil, `L` lava, `G` steam. **Test config T** (forces determinism): fall steps 1, `SINK_CHANCE` = `slide_p` = 1, `MIX_CHANCE` = 0, gas acts always, `L` as derived, frame 0, chunk (0,0) (scan left to right), `DIR` = 0 only where a wall makes the direction irrelevant. Reuse MR MV-05..MV-10 and MV-22/23 (reactions), MV-11 (density), MV-12 (gas life), MV-13..MV-17 (explosion depth), MV-19..MV-21 (ignition, burn-out, oxygen) rather than duplicating them; probabilistic vectors are seeded frequency tests (10,000 trials, 4 sigma).

| ID | Input (config T) | Expected |
|---|---|---|
| SIM-T01 free fall | column `S . .` | after 1 frame `. S .` |
| SIM-T02 train | column `S S S . . .` | after 1 frame `. S S S . .` (bottom-up: each moves once) |
| SIM-T03 rest | column `. S` | unchanged (boundary blocks) |
| SIM-T04 sink | column `S W` | `W S`; frame 2 unchanged |
| SIM-T05 float | column `W O` | `O W`; frame 2 unchanged (1 < 4 blocks) |
| SIM-T06 equal density | column `S L` (6 = 6) | unchanged |
| SIM-T07 diagonal | rows `S .` / `# .` / `# #` | `. .` / `# S` / `# #` (left diagonal is boundary) |
| SIM-T08 hop | row `W . . . . . . .` on boundary floor | `. . . . . W . .` (L = 5) |
| SIM-T09 hop blocked | row `W . . # . . . .` | `. . W # . . . .` |
| SIM-T10 gas rise | column `. . . G` | `. . G .`, then `. G . .`, `G . . .` after frames 2, 3; frame 4 unchanged |
| SIM-T11 gas ceiling | row `G . .` (ceiling above) | `. G .` (left blocked, DIR flips) |
| SIM-T12 gas column | column `. G G G` | `G . G G`, then `G G . G`, then `G G G .`: upward movers do not move as a train |
| SIM-T13 displacement | column `W W O #` | after 1 frame `O W W #` (each W moves once; the oil is displaced twice, allowed: SIM-R15) |
| SIM-T14 UPDATED | a cell swapped into a row visited later in the same frame | it is not visited again that frame; after the frame-end sweep no `UPDATED` bit survives anywhere |
| SIM-T15 stale-stamp regression | a settled cell stamped in frame f, chunk goes clean, wakes in f+2 | it moves in f+2 (a parity bit would skip it) |
| SIM-T16 pass order | frames 0,1,2,3,4 | `(0,0),(1,0),(0,1),(1,1)` / `(1,0),(0,1),(1,1),(0,0)` / `(0,1),(1,1),(0,0),(1,0)` / `(1,1),(0,0),(1,0),(0,1)` / same as frame 0 |
| SIM-T17 scan direction | `(frame+cx+cy)&1` | frame 0 chunk (0,0): 0 (left to right); chunk (1,0): 1; frame 1 chunk (0,0): 1 |
| SIM-T18 reach | chunk A cols 0-63, next same-class chunk cols 128-191 | `R=32`: A reaches 95, B reaches 96: disjoint. `R=33`: A reaches 96 = B's reach: must fail the compile-time assert |
| SIM-T19 window tiles | class (0,0) window (0,0); class (1,0) window (0,0) | tiles `tx in [-1,3)` (tile -1 missing = boundary), x -32..95; tiles `tx in [1,5)`, x 32..159 centred on chunk x=1 |
| SIM-T20 wake | single cell written at chunk-local (63, 10), `WAKE` 12 | dilated box x 51..75, y -2..22: own chunk gets x 51..63, y 0..22; the right neighbour x 0..11, y 0..22; the chunks above get y 62..63 for the same x ranges |
| SIM-T21 timer awake | `smoke` (lifetime 350) alone in a clean world, jitter off | removed at frame `created + 350` (within one `life_unit` = 2); its chunk is dirty every frame until then and clean the frame after |
| SIM-T22 derived params | fall (`sand`, `water`, `lava`, `gold`, `slime_green`) | `1 + 205/256`; `3`; `0 + 102/256`; `6` (cap); `0 + 51/256` (0.1 gives 0.2). Lateral `L` (liquids only): water 5, lava 5, `slime_green` 1 (flow 0.1 gives 1, slime halving floors to 0, minimum 1). `slide_p` (powders only): sand 192/256 (viscosity 50), soil 160/256 (75 gives 0.625), `spore` 64/256 (150 clamps to 0.25), viscosity 0 gives "always" |
| SIM-T23 `L` ties | flow 0.9 / damping 0.8; 0.1 / 0.8; 0.3 / 0.8; 0.9 / 0.9 | 5, 1, 2, 9 (integer formula; the f64 value of 0.1/0.2 is 0.5000000000000001) |
| SIM-T24 timers | `life_unit`: lifetime 5, 350, 1000, 1350; `burn`: `fire_hp` 600, 500, 1000, 0, 90000 | units 1, 2, 4, 6 (life0 5, 175, 250, 225); burn `(unit, burn0)` = (3, 200), (2, 250), (4, 250), converts on first step, 255 endless |
| SIM-T25 loader | load `materials.json` | 466 materials; Air 1, Static 103, Powder 87, Liquid 99, Gas 26, Fire 18, Solid 132; 42 distinct densities (all exact in x10,000); `air` index 0 |
| SIM-T26 carve depth | uniform column, `E` per ray, `R`, `D_max` | hp 20 x10, E 100: 5 cells; 3 Air then hp 20 x10, E 100: 5 solid cells (Air costs 0); `[dur 4 hp 20, dur 11 hp 20, dur 4 hp 20]`, `D_max` 10, E 1000: first removed, ray stops, third untouched; R 3 with huge E: exactly 3 cells |
| SIM-T27 depth table | `min(R, ceil(E/hp))`, "X" = blocked by durability | default (R20, 20k, dur 10): sand 20, soil 10, coal 20, rock 1, steel_static X, wood_static 10. `DIGGER` (6, 100k, 10): sand 6, rock 1, ice_static 4, coal_static 4, steel X. `GRENADE` (7, 350k, 10): rock 4. `MINE` (Unstable Crystal; 30, 170k, 10): rock 2, ice_static 6. `ROCKET` (15, 4M, 10): rock 15. `BOMB` (60, 6M, 11): rock 60, steel X (12 > 11). `NUKE` (250, 6.7M, 12): rock 67, steel_static 52, ice_static 224, templebrick X (14). `LIGHT_BULLET` (2, 400k, 8): sand 2, coal 2, soil X |
| SIM-T28 rays | `N = max(16, ceil(2*pi*R))` | R 2: 16; R 6: 38; R 20: 126; R 60: 377; R 250: 1,571; R 400: 2,514 |
| SIM-T29 particle clamp | speed far above 32 px/frame; separately 60 frames of `GRAV` from rest | displacement per frame clamped to 32 px; after 60 frames `vy` = 3.33 px/frame (200 px/s) |
| SIM-T30 ray masks | column top to bottom: Air, `steam`, `water`, `grass`, `sand`, `rock_static` | `Raytrace` hits steam (index 1); `Surfaces` hits grass (3); `SurfacesAndLiquiform` hits water (2); `Platforms` hits grass (3) in the MVP (kind-based, SIM-R64), sand (4) once `platform_type 0` is honoured |
| SIM-T31 thread independence | golden hash after 3,000 frames | identical for 1, 2, 3, 8, 16 threads (PRD, BEN DET-R08) |
| SIM-T32 pass-order independence | run each pass with its tasks in a random permutation, and sequentially | state hash equals the normal run (tests the disjoint-window invariant) |
| SIM-T33 transparency | all-dirty versus normal dirty rects | equal state hash after every frame (SIM-R72) |
| SIM-T34 snapshot | save at frame k, restore into all-dirty, run to N | hash equals the uninterrupted run |
| SIM-T35 soup fuzz | random material soup, several fixed seeds | no panic, stable hash, observed reach <= 16 |
| SIM-T36 burning awake | one BURNING `wood_static` cell (fuel 600) in a clean world, always air-exposed | its chunk is dirty every frame for 600 frames (burn0 200 x unit 3), then the cell is Air and the chunk goes clean |

## Pitfalls and common misreadings

1. **The [N] engine facts are not mirrored locally.** 64x64 chunks and the dirty rect are in the local braindump stub; bottom-up order, single buffer, 4-pass checkerboard with 32 px, the 32 px travel bound, "gases check up then sideways" and "burning pixels pick a random direction" come from web-fetched 80.lv / macuyiko summaries (`EC` status verified, cross-checked by the research author, not re-fetched here). `RJ`'s "GDC 2019 random direction" note is the same relayed claim (MR Sources: not in local sources).
2. **"Ground is solid."** No. Terrain is `Static` (cell_type liquid + sand + static); cell_type `solid` means Box2D bodies (MR MAT-R03).
3. **`air` is a material** with kind `liquid` in `MJ`: the "100 liquids" include it; real liquids are 99.
4. **Irrelevant fields are noise.** Statics carry `liquid_gravity` (66 at 1.2), gases 0.5, fire `flame` 5.0; read only the fields of the cell's kind. `MJ` is fully resolved: do not re-apply defaults.
5. **Density does not govern statics.** Statics have densities 4, 5, 6, 8, 10, 11 yet are never swap targets; kind gates first (SIM-R30).
6. **Upward movers are not trains.** A column of gas rises by gaps propagating down (SIM-T12); only downward movers move as a train (SIM-T02).
7. **Parity or generation stamps break with dirty rects** (SIM-R15, SIM-T15).
8. **Wake margins of 1-2 px are wrong** for liquids that scan 10 cells (SIM-R11).
9. **The ignition compare is strict.** MR FIRE-R03 uses `tof > autoignition` and a 4-neighbour; PST §6.6 used `>=` and 8 neighbours. The wiki documents `autoignition_temperature` as range 0-99, so the default 100 (17 flammable materials carry it) means "never"; `>=` would let `fire` (tof 100) ignite them. Trust MR.
10. **Cost arithmetic in PST §8.2/§13.10 is off.** Rays `2*pi*R` x `R` steps = `2*pi*R^2` = 0.39 M for R 250 (not 1.2 M); PST's `clamp(.., 32, 512)` rays would leave gaps beyond R 81.
11. **Probability scale.** `RJ` probabilities are percent floats stored by Noita as `int(p*100)`; 100 = certain; `rng % 10000 < round(p*100)` (MR MV-08). A per-frame per-cell application at face value would cover exposed rock with moss in seconds (`rock_static + air -> moss` 1 %): the engine cadence is UNVERIFIED (MR D2).
12. **`requires_oxygen` is documented backwards on the modding wiki** (MR FIRE-R05); gunpowder and gases with 0 burn through their volume.
13. **`liquid_sticks_to_ceiling`:** wiki says only 0 and 1 work "even though the game uses 50"; 34 materials set it (10 liquids, 24 powders; soil 50). Not modelled.
14. **Unloaded projectiles.** PST §2.2 says "an unloaded projectile does not move". W:Expert_Guide:_Waypoints says: entities inside a chunk that unloads are saved and deleted, but a projectile that flies into unloaded chunks keeps working normally. Not relevant for a fixed world; relevant for any future streaming.
15. **Equal-density liquids mix, they do not sort** (W:Density); equal never swaps vertically (strict `>`), mixing is lateral and rare (`MIX_CHANCE`).
16. **Durability 0 is not "indestructible"** (MR Pitfall 11); cell `hp` is a ray cost, not damage.
17. **Units do not mix.** Cell `hp` is a ray cost (never x25); entity HP is internal x 25 for display (player 4.0 = 100); reaction `probability` is a percent; contact damage from lava/acid lives on the entity (MR HAZ-R01..R03, ED).
18. **Seeds and hashes:** `UPDATED` is never hashed; `var` is.
19. **Fast things are not cells.** Projectiles (up to 1,800 px/s, Lightning faster) and particles (<= 32 px/frame) never run inside cell tasks.
20. **Do not copy the clones' scheduling.** FallingSandEngine seeds an entropy `fastrand` per chunk tick, builds phase lists from `AHashMap` iteration and uses `par_extend`; noprobelm uses a global `WyRand`, a random group order and a shared `HashSet` (its README admits undefined parallel order). Both are non-deterministic. sandspiel is deterministic but single-threaded. mintage's intent/resolver (modules emit intents in parallel, a serial resolver applies them first-writer-wins per cell with per-module seeds) is the deterministic fallback if cross-window conflicts ever appear.
21. **Clone scan orders differ and none is evidence about Noita:** FallingSandEngine bottom-up with a random column direction per chunk, falling-rust bottom-up alternating per step, FallingSandSurvival bottom-up left to right, sandspiel top-down alternating with a clock stamp. Only "bottom-up" is stated by Nolla.
22. **Noita's save format is not our storage.** It stores a material index per cell with the top bit marking a custom colour, which caps a chunk file at 128 materials (a format quirk), and it saves 512 px chunks as `world_x_y.png_petri` plus `entities_[2000*y+x].bin`. Our ids are `u16` and the world is not chunk-saved.

### Source disagreements and rulings

| Topic | Source A | Source B | Ruling and why |
|---|---|---|---|
| Updated mark | DSN §2.1/2.3: parity bit refreshed by visiting | PST §4.2: `UPDATED` + end-of-frame clear | B: parity breaks with dirty rects |
| Wake margin | DSN §2.2: 1 cell border + 1 halo | PST §3.5: `WAKE` 12 | B: liquids read 10 cells |
| Reach | DSN §2.3: `MAX_REACH` 16 | PST §5: bound 32 = CHUNK/2 [N] | both: 32 hard (assert), 16 policy |
| RNG | DSN §2.3 / BEN DET-R04 / MR RXN-R17: per-chunk streams | PST §12.2: stateless per-cell hash | B (SD1): only B allows dirty-rect transparency; DET-R04 and RXN-R17 amended accordingly |
| State hash | DSN §2.6: FNV-1a over `to_bytes` | BEN DET-R02: blake3 + per-chunk Merkle; PST §12.2: word-wise mixer | BEN owns the algorithm, this page owns the bytes (SD8) |
| Material table shape | BEN Data files: ~100 materials, `state/flammability/temperature` | `MJ`: 466, `kind`, resolved fields | `MJ` (derived from the game files); BEN table stale |
| World size | BEN: 512x512 v1 | DSN/PST: game 2048x1536 | both: benchmark worlds 512x512, game world 2048x1536 |
| Pass order | DSN §2.3: fixed | PST §5.3/§13.9: rotate by `frame mod 4` | B: removes a fixed-order flow bias (SIM-R21) |
| Storage | DSN §7: flat world `Vec` + one `unsafe` wrapper | PST §13.3: 32 px tiles, safe window split | B by default, A is the documented fallback (SIM-R24) |
| Timer storage | MR D5/D8: global 8-frame quantum | data: lifetimes 4, 5, 10 frames; PST §13.2 `ceil(lifetime/8)` | per-material unit (SD2): exact for all 15 lifetimes |
| Density storage | PST §13.7: `density_q8` "exact" | data: 42 values, up to 4 decimals | x10,000 `u32`: q8 is order-preserving here but not exact (SD6) |
| Gas movement | PST §6.5: 4 direction weights | PST §6.5/[N]: check order up then sideways; wiki: gas forms lakes in ceiling pits | check order (SD3): weights give ~1 px/s drift |
| Explosion depth | PST §8.1: `floor(E/hp)` | MR DUR-R02: `ceil(E/hp)` | MR: reproduces the wiki's "2-3 px" for Unstable Crystal (170k/280k) |
| Explosion rays | PST §8.2: `clamp(ceil(2*pi*R), 32, 512)` | MR D6: `max(16, ceil(2*pi*R))` | MR: no gaps; PST clamp skips rim cells |
| Fire cell expiry | PST §6.6: expire by life | `MJ`: lifetime 0 for fire, blue fire, sparks | MR D6 (12-30 frames) as tunable default |
| `autoignition`/tof | `research/materials.md`: cosmetic/unused | W:Making_a_custom_material; MR | wiki/MR: documented as ignition inputs; formula UNVERIFIED |
| Lava ignition | PST §6.6: temperature compare | MR FIRE-R09: reaction rows xml_093/094 | MR: avoids double counting |
| Visit order | PST §13.4: dispatch by kind, then reaction step; Air and Static skipped | MR FIRE-R03/D2: BURNING statics (`wood_static`) and reactive statics act as sources | this page (SIM-R20/R30): timers, burning, reaction, motion; burning or reactive Static/Solid cells are visited (order UNVERIFIED) |
| Entity numeric type | PST §10.3/§12.2: fixed point | BEN DET-R06: `f32` allowed, no `std` transcendentals | BEN by default (SD13) |
| TNT ray energy | PST register #4: absent, "at least 2.8 M" | SP SPELL-R05/TV-D5: 6,000,000 from `base_projectile_physics.xml` | SP: 6.0 M is 35x the crystal's 170k, matching "more than 30x" |
| Unloaded projectiles | PST §2.2 | W:Expert_Guide:_Waypoints | wiki (Pitfall 14) |
| Per-cell budget | PST §11.2: "about 48 ns with 4 effective threads" | arithmetic: 16.67 ms x 4 / 1,048,576 = 63.6 ns | recomputed (48 ns = 3 threads) |
| Platform/collision | PST §9.1 / `MJ`: `platform_type` classes | MR MVP-R05: by kind | MR for MVP |
| TomatoJuice licence | PST/RPA: Apache-2.0 | mirrored LICENSE = "404: Not Found" | unverified: idea-only |
| Duplicate material ids | `build_materials_json.py`: first definition used by the engine | W:Modding: later overwrites | UNVERIFIED; irrelevant to MVP (`rock_box2d`, `meat_pumpkin`, `steelmoss_static`: MR MAT-R01) |

## Our simplifications (MVP)

| # | Simplification | Noita | Why | Decision |
|---|---|---|---|---|
| S1 | Solid (Box2D) materials are Static; no rigid bodies, no marching squares, no `loose_ground` debris | Box2D bodies from pixels; big explosions turn terrain into falling powder | PRD non-goal; hooks kept (SIM-R86) | MR D13; SP S3 offers rolling bodies |
| S2 | Fixed-size world, no streaming, active rect | 12 broad chunks streamed, saved on unload | determinism, benchmark worlds | SD4 (frozen-chunk writes) |
| S3 | No per-cell velocity, temperature or wetness; fast motion = particles | runtime layout unknown | 6 B cell, cheap hashing | |
| S4 | Heat only through reactions/burning (`freezes_to` 26, `melts_to` 72, `break_into` 75 are reaction-driven or out of MVP) | same (no temperature grid per MR MAT-R14) | | |
| S5 | One random 4-neighbour per reactive cell per visit; ignition one random neighbour per burning cell | cadence unknown | MR D2/D4 | **SD9** (air-input rows) |
| S6 | Gas: act probability + up-first; liquids ignore viscosity; powders map viscosity to slide chance | speeds and viscosity formulas unknown | all 26 gases share 50/100/100/90 | **SD3**, SD11 |
| S7 | Explosions: DDA rays, liquids thrown as particles, no cracks/sparks/light/shake/stains | richer | | SD12 |
| S8 | Entities are not stamped into the grid (no `Object` pixels); entity vs cell through queries | | simpler, no per-frame stamping | |
| S9 | Threads optional (`parallel` feature), single-thread path is the same code | custom thread pool | | |
| S10 | Material-triggered explosions of the 15 `explosion_config` materials | yes | MR FIRE-R10 decides | |

| ID | DECISION-NEEDED | Default stated in this page | Alternative |
|---|---|---|---|
| SD1 | Cell RNG scheme | stateless per-cell hash (SIM-R70); BEN DET-R04 and MR RXN-R17 were amended to this wording | per-chunk xoshiro stream: simpler, loses dirty-rect transparency tests |
| SD2 | Timer storage | per-material tick unit, `u8` stays (SIM-R35) | global 8-frame quantum (MR D5/D8); or widen to `u16` (+1 B per cell) |
| SD3 | Gas model | act probability 50 % + up-first (SIM-R34) | 4-weight random walk (rejected: no visible rise) |
| SD4 | Writes into frozen chunks | treated as `boundary` | allow and wake: matter crosses the active edge; costs a merge rule |
| SD5 | Cell layout | 6 B with separate `burn` byte (SIM-R03) | DSN draft: 5 B + parity (rejected: stalls with dirty rects) |
| SD6 | Density storage | `density_x10000: u32` | `density_q8: u16` (order-preserving, 42 distinct, not exact) |
| SD7 | Perf acceptance scenario | "active radius" for 1024x1024 = 512x512 around the player, all-active soup reported separately | all-active 1024x1024 at 60 Hz (15.9 ns/cell single thread: not realistic) |
| SD8 | Who owns the hash | BEN owns algorithm/Merkle, this page owns the byte layout | blake3 over `to_bytes` per frame |
| SD9 | `air`-input reaction rows with the full 466 table | accepted always-awake in MVP-40 (6 rows) | random-tick sampler (a few stateless samples per chunk per frame, independent of dirty rects) before adding grass/moss/vine rows |
| SD10 | Particle constants | `GRAV` 200 px/s^2, lifetime cap 600 frames, cap 100,000, drop newest | gravity 100 (Lua cosmetic default) or FallingSandEngine's 360 px/s^2 |
| SD11 | Lateral range mapping | `L = round_half_up(flow/(1-damping))`, slime halves | table of per-material hand values |
| SD12 | Explosion caps | 32 explosions and sum(R^2) <= 400,000 per frame, carry-over | uncapped (a nuke storm stalls a frame) |
| SD13 | Entity/projectile numeric type | `f32` restricted per BEN DET-R06 | fixed point (PST §10.3: keeps a later rapier `f32` behind a boundary conversion) |

## Open questions

1. Does Noita alternate or randomise the column order, and does it keep a per-frame or per-pass "visited" mark (PST register #1)?
2. Which loaded chunks are stepped each frame; what do `GRID_MAX/MIN_UPDATES_PER_FRAME` (128/40) mean?
3. How does Noita re-deposit flying pixels, and are they stepped inside the checkerboard?
4. Exact explosion ray count and jitter; stop vs skip at hard cells; `>=` vs `>` energy test; liquid cost; can partial damage persist across rays (MR Open 7)?
5. Meaning of `liquid_viscosity`, `liquid_damping`, `liquid_sticks_to_ceiling`; unit of the `fire_hp` decrement; direction of `requires_oxygen` (MR FIRE-R05).
6. Real reaction cadence (neighbours examined per cell per frame) and how the engine avoids per-frame moss growth on exposed rock (MR D2).
7. How do `fire`, `fire_blue` and sparks expire (lifetime 0 in the data)?
8. Units of projectile `speed` (px/s assumed: terminal velocity 1000 px/s is stated in px/s [W]).
9. Does Noita store velocity or burn counters per cell at runtime (the save format stores material and colour only)?
10. Rapier cross-platform determinism options; licences of `contour`, `ramer_douglas_peucker`, `earcutr`.
11. Real performance of Noita's sim (no published numbers) and our cell-visit cost (5-30 ns per active cell is an unmeasured expectation).
12. Which duplicate definition wins in `materials.xml` (first or last)? It only matters for `rock_box2d`, `meat_pumpkin` (Box2D) and `steelmoss_static` (a static).
13. Risks to watch (PST §13.10): parameter mappings that look wrong against footage (keep them in the table, calibrate by frame counts); one rect per chunk wasting scans on scattered activity (add an 8x8-tile occupancy bitmap only if profiling shows mostly-empty scans, benefit UNVERIFIED); tile-indirection cost (fallback in SIM-R24); serial explosion and particle phases spiking on a nuke or 100,000 particles (move into the pass tasks if profiled); rapier determinism once bodies arrive; new rules silently exceeding the reach (SIM-R77).

## Sources

Research files (`./.trellis/tasks/10-16-noita-cogbench/research/`):
- `pixel-sim-tech.md` (all sections), `noita-engine-constants.json`, `pixel-sim-repos.json`, `rust-prior-art.md`
- `materials.json`, `materials.md` (cross-checked, errors listed in MR), `reactions.json`, `tags_index.json`, `materials_from_data_xml.json`, `spells.json`, `entities-damage.md`, `player-stats.json`
- `scripts/build_materials_json.py` (`kind_of`, duplicate handling)
- `raw/braindump_jethro_dev_posts_gdc_vault_exploring_the_tech_and_.txt` (GDC 2019 stub: simple algorithm, 64x64 chunks, dirty rect, marching squares)
- `raw/noitadata/data/magic_numbers.xml`, `raw/noitadata/data/materials.xml` (numbers only; Nolla's copyrighted data)
- `raw/Density.wikitext`, `raw/Materials.wikitext`, `raw/Fire.wikitext`, `raw/Falling_Sand_Game.wikitext`, `raw/Expert_Guide__Waypoints.wikitext`, `raw/Cursed_Rock.wikitext`, `raw/Biomes.wikitext`, `raw/Technical__File_Formats.wikitext`, `raw/Modding__Magic_Numbers.wikitext`, `raw/Modding__Making_a_custom_material.wikitext`, `raw/Modding:_Lua_API.wikitext`, `raw/Documentation__ConfigExplosion.wikitext`, `raw/Documentation__Reaction.wikitext`, `raw/Documentation__ProjectileComponent.wikitext`, `raw/Documentation:_VelocityComponent.wikitext`, `raw/Documentation:_ParticleEmitterComponent.wikitext`, `raw/Documentation__PhysicsBodyComponent.wikitext`
- Mirrored permissive-licence sources `raw/repos/{FallingSandEngine,FallingSandSurvival,sandspiel,falling-rust,noprobelm_bevy_falling_sand,TomatoJuice_bevy_falling_sand,mintage,EP01_SandSim}/` (read for ideas; licences per Data files)
- Sibling KB pages: `.trellis/spec/game-design/{materials-reactions,wand-casting,spells,entities-damage,benchmark}.md`; task docs `../prd.md`, `../design.md`

Web pages and URLs (relayed claims, see Pitfall 1):
- https://80.lv/articles/noita-a-game-based-on-falling-sand-simulation/ (64x64 chunks, dirty rect, 4-pass checkerboard, +32 px, pixel ownership by rigid bodies, burning-pixel ignition)
- https://blog.macuyiko.com/post/2020/an-exploration-of-cellular-automata-and-graph-based-game-systems-part-4.html (single buffer, 32 px guarantee, pixels into a particle simulation)
- https://braindump.jethro.dev/posts/gdc_vault_exploring_the_tech_and_design_of_noita/
- https://noita.wiki.gg/wiki/Modding:_Making_a_custom_material, /Modding:_Magic_Numbers, /Modding:_Lua_API, /Technical:_File_Formats, /Expert_Guide:_Waypoints, /Cursed_Rock, /Biomes, /Density, /Materials, /Fire, /Falling_Sand_Game, /Documentation:_ConfigExplosion, /Documentation:_Reaction, /Documentation:_ProjectileComponent, /Documentation:_VelocityComponent, /Documentation:_ParticleEmitterComponent, /Documentation:_PhysicsBodyComponent
- https://github.com/PieKing1215/FallingSandEngine, /FallingSandSurvival, https://github.com/MaxBittker/sandspiel, https://github.com/grunnt/falling-rust, https://github.com/noprobelm/bevy_falling_sand, https://github.com/100-TomatoJuice/bevy_falling_sand, https://github.com/astradamus/mintage, https://github.com/GameEngineering/EP01_SandSim
- https://news.ycombinator.com/item?id=24397769 (lag on large explosions)
