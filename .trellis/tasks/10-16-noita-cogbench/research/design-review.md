# Design review: parent design.md and the four child PRDs against the research and the game-design KB

Date: 2026-10-07. Reviewer: sub-agent (no code written, no git, no web fetches; everything below was read from local files).

**Reviewed:** `../design.md`, `../prd.md`, `../../10-07-{pixel-sim-core,wand-spell-system,agent-benchmark,playable-frontend}/prd.md`.
**Against:** KB pages `.trellis/spec/game-design/{pixel-simulation,materials-reactions,wand-casting,spells,entities-damage,benchmark}.md` and the research files. The task asked for KB pages `worldgen.md` and `frontend.md`; they do not exist yet (only 6 pages, see F5), so `research/worldgen.md` and `research/frontend-tech.md` were used instead.
**Numbers re-derived from data** (not only quoted): `materials.json` (466 rows), `spell_taxonomy.json`, `mvp50.json`, `player-stats.json`, `wand-cast-test-cases.json`, `enemies.json`, and the game's `player_base` data under `raw/noitadata` (numbers only).

**Severity.** `blocker` = implementing the text as written gives wrong or non-deterministic behaviour, or an acceptance criterion cannot be met; fix before the child starts. `important` = significant rework, fidelity loss, benchmark-validity or performance risk; fix in design/PRD before that child starts. `minor` = wording, tuning, documentation.

**Abbreviations.** KB page shorthands used below: MR = materials-reactions.md, SP = spells.md, ED = entities-damage.md, BEN = benchmark.md, WAND = wand-casting.md; PST = research/pixel-sim-tech.md; EC = research/noita-engine-constants.json; PS = research/player-stats.json; SD1-SD13 are the DECISION-NEEDED ids of pixel-simulation.md.

**Tags.** KB rule ids (`SIM-R15`, `WAND-R40`, ...) are in `spec/game-design/`. UNVERIFIED = no primary source or not measured; every performance estimate in this file is UNVERIFIED because no code exists to measure.

## Headline

42 findings: 4 blocker, 25 important, 13 minor, plus 10 faithful-vs-simple decisions for the user.

- 4 blockers, all in the simulation core or the casting algorithm: the parity "already updated" flag (S1), the dirty-rect wake margin and parallel metadata race (S2), the 5-byte Cell layout (S3), and trigger payloads drawn when the trigger fires instead of at cast time (W1).
- The chunk size (64), the 4-pass checkerboard and the `u16` material id are correct. The reach argument is correct (same-class chunks are 64 cells apart, so any reach up to 32 is safe; 16 is a sound policy). The problems are around it: wake margin, metadata writes, and cell state.
- "Particles in flight" are not needed for ordinary cell motion; they are needed only for explosion-thrown liquids and splashes, and design.md mentions them in one clause without a spec (S9).
- The PRD sentence "spells.json >= 300 spells loadable" is trivially true (422 load) and hides the real cost: only 237 of 422 spells (D0 + D1) work without per-spell code, and the MVP-50 contains rigid-body spells that the PRD declares out of scope (W5, W6).
- Several PRD acceptance sentences contradict vanilla data: "take fall damage" (player `falling_damages` = 0), "obsidian" (no such material), "steel (indestructible)" (steel_static durability 12; a Nuke removes it), "extinguished by water" for burning materials (wiki: ineffective), and a 4 ms budget that disagrees with the 3.33 ms of "5x realtime" and "300 frames/s".

## Index

| ID | Sev | Area | One line |
|---|---|---|---|
| S1 | blocker | sim | Parity "updated" flag stalls cells once dirty rects exist |
| S2 | blocker | sim | Wake margin 1 cell vs reads up to 10; unsynchronised neighbour-chunk metadata writes |
| S3 | blocker | sim | Cell `life: u8` cannot hold lifetimes or fuel; gases need two timers |
| S4 | important | sim | Fall/flow ignore `liquid_gravity`, flow and damping; floats inside rules |
| S5 | important | sim | Per-chunk RNG stream, fixed pass order, global column direction |
| S6 | important | sim | One reaction per pair; no tags, candidate order, blobs, cadence |
| S7 | important | sim | Fire modelled as a consuming cell; water "extinguishes" |
| S8 | important | sim | Explosion disc `power*(1-d/r)`; no ray energy/hp; fire only on flammables; damage falloff |
| S9 | important | sim | "Particles in flight" mentioned, not specified; need is narrow |
| S10 | minor | sim | Writes into frozen (inactive) chunks undefined |
| S11 | minor | sim | Flat grid plus raw-pointer `unsafe` vs safe tile windows |
| S12 | minor | sim | Query API and entity collision box numbers |
| S13 | minor | sim | FNV-1a over the whole grid vs blake3 Merkle; hash cost |
| D1 | important | determinism | One RNG vs per-subsystem streams; "no external hash dep" vs blake3 |
| D2 | important | determinism | No f32/libm/FMA/target rules; golden hashes only on one platform |
| D3 | minor | determinism | Determinism test list too short |
| W1 | blocker | casting | Trigger payload drawn at fire time with a depth limit (should be at cast time) |
| W2 | important | casting | Cast purity needs a context; outputs incomplete; enables world-free DPS search |
| W3 | important | casting | ShotState and timing rules incomplete in the PRD |
| W4 | important | spells | `Behaviour` enum per spell id vs 7 primitives, feature library, handler registry |
| W5 | important | spells | ">= 300 loadable" hides 185 spells that need custom code; unimplemented no-op in pools |
| W6 | important | spells | MVP-50 has BOMB/DYNAMITE (physics bodies) while rigid bodies are a non-goal |
| W7 | important | spells | Worked-example acceptance uses a flawed doc and flawed fixtures, mixes stage 2 |
| W8 | important | projectiles | Projectile motion and collision under-specified (speeds, masks, normal, swept hit) |
| W9 | minor | casting | `Game::step` order and `Input` shape |
| E1 | important | entities | No damage-unit decision (x25); mixed units in spells.json |
| E2 | important | player | No levitation or movement numbers; BEN says 1.0 s, vanilla 3.0 s |
| E3 | minor | player | Acceptance "take fall damage" is not vanilla |
| E4 | minor | entities | Status/contact-damage model details |
| E5 | minor | entities | Enemy set and HP scale |
| B1 | important | benchmark | Protocol surface much smaller than benchmark.md; `wait` uncapped |
| B2 | important | benchmark | Replay/hash/seed/version model |
| B3 | important | benchmark | Action schema differences |
| B4 | important | benchmark | Observation modes: base64 rule, u8 material ids vs 466 materials, 4 px/char |
| B5 | important | benchmark | Task parameters vs world size and kinematics; monotone score needs task state |
| B6 | minor | benchmark | Python client / run header |
| P1 | important | performance | Acceptance numbers inconsistent and unscoped |
| F1 | important | frontend | Frontend via bench observations vs direct core access |
| F2 | minor | frontend | `macroquad::ui` cannot drag and drop |
| F3 | important | worldgen | Per-chunk-seeded noise gives seams; f32 noise; HashMap streaming; no KB page |
| F4 | minor | content | gravel/obsidian/indestructible steel; digging wording |
| F5 | minor | process | Child designs, manifests, KB pages, trimmed runtime assets missing |

## What holds up (verified, no change needed)

- Chunk = 64x64 (Nolla-stated), dirty rect per chunk, bottom-up scan, single buffer, 4 passes over `(cx&1, cy&1)`. Same-class chunks are 64 cells apart (design 2.3 says so correctly), so windows `[chunk +- R]` are disjoint iff `R <= 32`; design's `MAX_REACH = 16` is a valid policy with margin (SIM-R22).
- `u16` material id: 466 materials in the data, engine cap 1,024 (a `u8` would not fit).
- Fixed 60 Hz, all durations in integer frames, y grows down, out-of-bounds reads give an indestructible boundary material.
- `noita_core` / `noita_bench` / `noita_game` split with "no game rules in the front ends"; JSON lines on stdio; Python client with stdlib only; deterministic seeds; headless core.
- No rigid bodies in the MVP is a consistent PRD decision for the cell simulation (see W6 for the spells that conflict with it).
- Projectile sweep by ray-marching the grid from old to new position (the DDA idea is right; details in W8).

---

## S. Pixel simulation (design.md section 2, pixel-sim-core PRD)

### S1. Updated-parity flag (blocker)
- **Design/PRD:** design 2.1: `flags` bit0 = updated-parity (`frame & 1`); 2.3: a visited cell is skipped if its parity flag already equals the current frame's parity. PRD: "last-updated parity bit".
- **Research:** SIM-R15 / SIM-T15 and PST 4.2. With dirty rects a stamp written in frame f is never refreshed while the chunk sleeps. When the chunk wakes at f+2, f+4, ... the stale stamp equals the current parity and the cell is skipped (a u8 generation stamp fails 256 frames later). Failure: a grain moves at frame 10 (stamp 0); chunk clean from frame 12; its support is removed at frame 20 (even): the grain is skipped, nothing is written, the chunk goes clean again and the grain floats until something wakes the chunk on an odd frame. The bug is deterministic, so the 1-vs-8-thread determinism test will not catch it.
- **Change:** transient `UPDATED` flag raised by `set`/`swap`, gating visits only (a target may still be displaced), cleared by an end-of-frame sweep over the `next` rect, never serialised or hashed. Tests SIM-T14, SIM-T15.

### S2. Wake margin and parallel metadata writes (blocker)
- **Design/PRD:** design 2.2: a write expands `next_dirty` of the chunk and of neighbours "when the cell is within 1 of a chunk border (plus a 1-cell halo)"; "a chunk with no writes for one frame becomes clean". 2.3: chunk tasks run in parallel behind `SyncGridPtr`. PRD: "dirty-rect sleep".
- **Research:** SIM-R11/R12/R13. A rule at `p` can read up to its largest reach: lateral hop <= 10 (cap), fall <= 6, diagonal/reaction/ignition 1, reaction blob <= 6 in MVP-40 (blob radii 15 and 40 exist in the full table, 40 > MAX_REACH 32). Hence `dirty(f+1)` must contain `[p +- WAKE]`, `WAKE = 12`. Keep-awake is also required when a cell is unchanged but could change (timer running; a probabilistic move/slide/hop/react roll failed; a reactive neighbour). Task writes to another chunk's metadata are forbidden; boxes are returned task-locally and merged serially in ascending chunk index.
  - Liveness failure A: a water cell 4 cells from a freshly dug gap is outside the 1-cell halo, so it stays asleep. Flow then creeps at 1 cell/frame (wake propagates one cell per write) instead of hopping L = 5, or hangs if nothing else writes nearby.
  - Liveness failure B: with `viscosity` as a probability to skip the lateral move, a skipped move writes nothing; if every mover in a chunk skips in the same frame, "no writes for one frame" puts the chunk to sleep and the flow stops at random.
  - Race: chunks (0,0) and (2,0) have the same class and run in the same pass; both neighbour chunk (1,0), and both would write `next_dirty` of (1,0). That is an unsynchronised write to a shared `Option<IRect>`: UB with raw pointers or a lost update. The dirty set then depends on thread timing, and because design draws RNG per visited cell the whole state diverges per thread count.
- **Change:** SIM-R10..R13 with `WAKE = 12`, `RULE_REACH = 16`, `MAX_REACH = 32` and a compile-time `2*MAX_REACH <= CHUNK`; task-local write boxes, serial merge, `keep_awake()` rules (a)-(c). Accept SD9 (6 air-input rows keep exposed surfaces awake, see P1).

### S3. Cell layout (blocker)
- **Design/PRD:** design 2.1: `Cell { mat:u16, variant:u8, life:u8, flags:u8 }` (5 B, 6 padded); `life` = "gas/fire lifetime, burn counter, liquid settle counter"; flags = parity, burning, wet, sleeping, direction. PRD pixel-sim-core: "id u16, colour variant u8, flags/lifetime (u8), parity bit" (flags and lifetime in one byte; smaller still).
- **Research (checked on `materials.json`):**
  - Lifetimes: 15 distinct values from 4 to 1,350 frames (steam 1,000, smoke 350, acid/poison/fungal gas 450, alcohol gas 50, flame 5). `u8` stores 255. Needs a per-material `life_unit` in {1,2,4,6} (SIM-R35, exact for all 15).
  - Fuel (`fire_hp`): coal 1,000, wood_static 600, oil 500, molten metals 90,000, liquid_fire 1,000,000. Needs `burn_unit = max(1, ceil(fire_hp/250))`.
  - `acid_gas`, `poison_gas`, `fungal_gas` carry both lifetime (450) and fuel (1,000): two counters, so one overloaded byte is impossible.
  - No temperature grid exists (MAT-R14), no wetness, no per-cell velocity (fast matter is a particle, SIM-R45), no per-cell sleep counter (SIM-R10: Nolla states none; counters that write on mere visits break dirty-rect transparency SIM-R72). `req_lifetime` (5 cement reactions) is dropped (MR D8).
- **Answers to the questions asked:** parity -> replaced by the transient UPDATED flag (S1); lifetime -> `life` + per-material unit; velocity of flying particles -> not in the cell; temperature -> not needed.
- **Change:** 6 B, no padding: `mat u16, life u8, burn u8, var u8, flags u8` with flags UPDATED, BURNING, DIR, OBJECT (reserved), 4 bits spare. Drop `wet`, `sleeping`, "settle counter". Hash `var`, not UPDATED (SIM-R75).

### S4. Fall and flow rules ignore the material data (important)
- **Design/PRD:** design 2.4: powder tries down, then diagonals (one step); liquid slides "up to `dispersion` cells", `viscosity` = probability of skipping lateral motion; PRD lists a `dispersion` material field.
- **Research (derived from `materials.json`):** there is no `dispersion` field; the data has `liquid_gravity`, `liquid_flow_speed`, `liquid_damping`, `liquid_viscosity`. Of the 186 liquid and powder materials, 138 have `2g > 1` (93 have `2g >= 2`, 64 have `2g >= 3`, 9 reach the cap of 6: gold, wax, plastics), only 48 are `<= 1`. A 1-cell fall makes lava (g 0.2) and water (g 1.5) equally fast and ignores the column. Lateral range from the SIM-R32 mapping `L = round(flow/(1-damping))`: 5 for 91 of 99 liquids, 2 for 4, 1 for 4, cap 10 (all mappings are [CAL], UNVERIFIED). Viscosity is ignored for liquids (wiki: "no noticeable difference?") and drives the powder slide probability `clamp(1 - visc/200, 1/4, 1)`. Floats must not enter per-cell rules (SIM-R05): density `x10000` as `u32` (42 distinct values, up to 4 decimals), fall `2g` as integer plus `u8/256` fraction, `0.1/(1-0.8)` is 0.5000000000000001 in f64.
- **Change:** SIM-R31/R32/R05; compute a `MotionParams` table at load (`fall_int`, `fall_frac_q8`, `slide_p`, `lateral_L`, ...); tests SIM-T22, SIM-T23.

### S5. RNG scheme, pass order, scan direction (important)
- **Design/PRD:** design 2.3: per-chunk Xoshiro256** seeded from `(seed, frame, chunk, pass)` consumed in scan order; fixed pass order; column direction `frame & 1`, rows alternate with `(frame>>1)&1`.
- **Research:** SD1 / SIM-R70: stateless per-cell hash `mix64(cell_seed ^ frame*K1 ^ pass*K2 ^ index*K3)`. A stream consumed in scan order makes each draw depend on which cells the dirty rect visits, so (a) dirty-rect transparency and snapshot restore into all-dirty (SIM-R72, T33, T34) cannot hold, (b) every dirty-rect optimisation changes golden hashes (engine minor bump, VER-R02). A fixed pass order leaves a systematic flow bias (the first class sees the pre-frame state): rotate by `frame mod 4` (SIM-R21, T16). Column direction `(frame + cx + cy) & 1` (SIM-R20, T17).
- **Change:** adopt SIM-R70/R20/R21; amend BEN DET-R04 and MR RXN-R17 wording to "cell RNG"; keep per-chunk xoshiro only as the documented fallback.

### S6. Reactions (important)
- **Design/PRD:** design 2.4: dense `reactions[a*n + b] -> Option<ReactionIdx>` with `{out_a, out_b, prob}`, checked "for moving cells and periodically for stationary dirty cells".
- **Research:** RXN-R02..R08, R10, R14: a pair can have several candidates tried in file order (`[fire]+snow`: xml_010 20% steam then xml_015 80% water, giving steam 0.20, water 0.64, none 0.16); 162 of 330 reactions use a tag input (`[corrodible]` expands to 279 members; sorted at load); outputs are positional and tag outputs mean the matched member; suffix forms (`[meltable]_molten`); probability is a float percent stored as `int(p*100)`; 54 reactions have blobs (MVP radii <= 6); 32 have a third input (dropped in MVP); cadence UNVERIFIED (MR D2: one random 4-neighbour per reactive cell per visit, effective ~0.44 p per frame).
- **Change:** compile to per-pair candidate slices plus a `reactive` flag per material; load-time assertions 466 / 330 / 79 (RXN-R18); MVP-R02 list of 39 reactions.

### S7. Fire and burning (important)
- **Design/PRD:** design 2.4: fire is a cell kind with `life`; each frame it checks 4-8 neighbours, reduces neighbour `fire_hp`, ignites, converts exhausted cells via `burns_into` ("often air + smoke"); "water/wet neighbours extinguish -> steam". PRD R1: "extinguished by water (steam)".
- **Research:** FIRE-R01..R08, SIM-R37: burning is a per-cell state (BURNING flag + `burn` counter initialised from `fire_hp`) of a `burnable` material; Fire-kind cells (3 real, 15 sparks) are ignition sources and emissions. Ignition test `temperature_of_fire(source) > autoignition(target)`, chance `(100 - autoignition)%` (MR D4, UNVERIFIED), 4 neighbours, one random neighbour per frame (PST's `>=`, 8 neighbours superseded). Burnt cells become Air, no ash (the `burns_into` field is prose, never an id). `requires_oxygen=1` burns only while a 4-neighbour is air or gas. No reaction clears BURNING: `[fire]+water -> [fire]+steam` (20%) boils the water; wiki Fire: spraying water is ineffective against burning materials; fires end by fuel exhaustion, air starvation or deletion. (benchmark.md Pitfall 5 states the opposite, see K1.)
- **Change:** adopt SIM-R37 + FIRE-R03..R06; remove "water extinguishes" for materials from design and PRD (keep: an entity that is On Fire is extinguished by liquid immersion, DAMAGE-R14); decide the `extinguish_fire` task semantics (decision 2).

### S8. Explosion model (important)
- **Design/PRD:** design 2.4: `explode(cx, cy, radius, power)`: per cell in the disc `power*(1-d/r)` vs `durability`; "spawn fire on flammables with probability"; liquids pushed out. PRD: destroys cells whose `durability < power*falloff`. Wand PRD: "explosion damage with falloff".
- **Research:** DUR-R01..R03, SIM-R50..R54: rays from the centre with `ray_energy` (default 20,000), each crossed cell costs its `hp` (5 to 1,000,000, a ray cost, not entity HP); a cell is removed only if `durability <= max_durability_to_destroy` (default 10; 329 of 466 materials have durability 0 = unset); cells removed per ray = `min(R, ceil(E/hp))`. Examples: digger (R6, E 100k): soil (hp 2,000) 6 deep, rock_static (hp 100,000) 1 deep; bomb (R60, 6M, dur 11): rock 60 deep, steel_static (dur 12) untouched; nuke (R250, 6.7M, dur 12): rock 67 deep, steel 52 deep. Fire cells appear with `create_cell_probability` for every destroyed cell (default 5%, fireball 100%, bomb 40%, spark bolt 0), not only flammables. Destroyed liquids are thrown (`hole_destroy_liquid` false). Entity damage in the radius is flat (ConfigExplosion documents no falloff; UNVERIFIED), knockback falls off as `radius*force/(distance*mass)`; when the final shot `c.explosion_radius > 0` a damage floor applies: 325 / 375 / 500 (display) for radius 32-63 / 64-127 / >= 128. Cost: rays `N = max(16, ceil(2*pi*R))`: R250 1,571 rays about 0.39 M cell visits, R400 2,514 rays about 1.0 M.
- **Change:** `explode(&ExplosionConfig{radius, ray_energy, max_durability, create_cell{material,prob}, hole_destroy_liquid, damage, knockback}, x, y, source_id)`; serial explosion phase with a queue and caps (SIM-R54: 32 per frame, sum R^2 <= 400,000, chain reactions deferred a frame); flat damage unless the user chooses falloff (decision 3). The disc/durability-only model cannot reproduce "digging bolt: 6 px of soil but 1 px of rock".

### S9. Particles in flight (important)
- **Design/PRD:** design 2.4 (one clause): explosions convert liquids to "moving 'particles' list handled by the sim as free-falling cells with velocity". The Cell has no velocity; no struct, id order, cap, re-deposit rule or determinism rule exists.
- **Research:** needed? Not for ordinary motion: cells move <= 6 cells per visit (S4) and carry no velocity. Needed only for matter thrown by explosions and splashes (Nolla: such pixels go into a particle simulation; travel bound 32 px/frame, EC). Sprays and trails need none: a `MATERIAL_PARTICLE` projectile deposits one cell on death and trails (fire 10, water 20 cells) can write cells directly along the swept path (`create_real_particles` semantics). Spec exists in SIM-R45..R47 (Q16.16 position/velocity, gravity 200 px/s^2 = 3,641/65,536 px/frame^2, <= 32 px/frame, cap 100,000 drop-newest, serial id-ordered phase after the cell passes; 20,000 particles about 1-3 ms, UNVERIFIED).
- **Change:** remove the clause until chosen; decision 4: (a) full SIM-R45..R47, (b) MVP shortcut: matter in the crater is displaced to the nearest free cells outside it by a deterministic spiral (conserves matter, no flight, no new subsystem), (c) delete it (violates conservation; equals `hole_destroy_liquid = true`).

### S10. Frozen chunks (minor)
- **Design/PRD:** `step()` visits only chunks intersecting `active`; writes into non-visited chunks undefined.
- **Research:** SIM-R14, SD4: frozen chunks stay readable, writes into them are treated as boundary, they re-activate fully dirty.
- **Change:** adopt; state the active-rect size for the 2048x1536 game world (SD7 default 512x512 around the player).

### S11. Storage and `unsafe` (minor)
- **Design/PRD:** one flat `Vec<Cell>` plus `SyncGridPtr` (`unsafe impl Sync`).
- **Research:** SIM-R24: `Vec<Tile>` of 32x32 tiles and a safe window split (`iter_mut` then `par_iter_mut` over 128x128 windows) with the flat array as documented fallback if indirection costs >10%. The Rust clone FallingSandEngine flags its own aliasing as probable UB.
- **Change:** default to the safe tile layout; keep the flat version as a measured fallback.

### S12. Queries and collision numbers (minor)
- **Design/PRD:** 2.5 `raycast(from, to, predicate)`, `aabb_collide` with step-up of 1-3 px, `is_solid`.
- **Research:** SIM-R60..R65: four ray masks over a kind bitmask (Raytrace, RaytraceSurfaces, SurfacesAndLiquiform, Platforms) as `blocked(mask)`; entity collision by kind (static, powder, solid block; liquid buoyant; gas, fire pass). Player collision box x -2..2, y -4.5..2.1 (4 x 6.6 px, non-integer), hitbox 6 x 16, `climb_over_y` = 4 (not 1-3).
- **Change:** adopt `blocked(mask)`; sub-pixel entity positions (f32 or fixed point, D2); step-up 4.

### S13. State hash (minor)
- **Design/PRD:** 2.6: 64-bit FNV-1a over `to_bytes()` plus entity/wand state; "implemented in-crate; no external hash dep".
- **Research:** BEN DET-R02/R03: blake3 with per-chunk Merkle leaves, a hash returned on every `step`, full-grid every 600 frames. Cost estimate (UNVERIFIED): grid 512x512x6 B = 1.57 MB; byte-wise FNV-1a about 0.8-1.25 GB/s gives 1.3-2.0 ms, against a 3.33 ms frame budget; a `step` with `frames = 1` (per-frame control) would be dominated by hashing. Bytes to hash (SIM-R75): frame, cell seed, cells with UPDATED cleared in chunk-then-row order, particles sorted by id, entities (f32 via `to_bits`), wands.
- **Change:** SD8: BEN owns the algorithm, the sim page owns the bytes; use per-chunk leaves recomputed only for chunks written since the last hash; use the `blake3` crate for `content_hash`, `episode_seed` and `episode_hash` (see D1).

---

## D. Determinism (design.md section 6)

### D1. RNG streams and hash dependency (important)
- **Design/PRD:** `Game` owns "RNG"; casting takes `&mut Rng`; "`rand` only through rng.rs"; no external hash dep.
- **Research:** BEN DET-R04 / SEED-R01: separate streams `worldgen | cells | spells | ai | spawn` derived from the seed, so that adding an RNG call in `spells` cannot change `worldgen` (a stated unit test). PROTO-R02/SEED-R01 use blake3 for `content_hash` and `episode_seed = blake3(task_id || task_version || seed_index)`.
- **Change:** `Rngs { worldgen, cells(stateless), spells, ai, spawn }` in `rng.rs`; allow the `blake3` dependency for content and seed hashes (licence not checked here, UNVERIFIED); test "extra draw in spells leaves worldgen identical".

### D2. Floating point, trigonometry, platforms (important)
- **Design/PRD:** bans wall-clock, `HashMap` iteration and thread RNG; silent on floats. PRD AC compares 1 vs 8 threads on one machine.
- **Research:** DET-R06/R07, SIM-R71: cell rules integer-only; entities and projectiles may use f32 with `+ - * / sqrt` only; `sin/cos/exp/powf` only through `libm` or tables (std versions are platform-dependent); no fast-math, no non-deterministic SIMD; fixed `target-cpu`; golden hashes on macOS arm64 and Linux x86_64. Needed here: aim in degrees, spread, Formation patterns, Black Hole pull and ping-pong all want trigonometry. No Linux runner is known in this environment, so the cross-platform check is a later CI item (UNVERIFIED that f32 results match across the two).
- **Change:** add these rules to design 6; add a clippy `disallowed_methods` list for `f32::sin/cos/exp/powf`; decision 9 covers f32 vs Q16.16 for entities (SD13).

### D3. Determinism tests (minor)
- **Design/PRD:** 1 vs 8 threads, same seed twice after 3,000 frames, replay.
- **Research:** SIM-T31..T35: also threads 2, 3, 16, random pass-order permutation (disjoint windows), dirty-on vs all-dirty, snapshot at frame k, random-soup fuzz.
- **Change:** add them to the pixel-sim-core AC.

---

## W. Wand, spell and projectile system (design.md section 3, wand-spell-system PRD)

### W1. Trigger payload timing (blocker)
- **Design/PRD:** design 3: a projectile carries `payload: Option<Vec<SpellInstance>>` and `trigger: Collision | Timer(frames) | Death`; "when it fires, the payload is cast as a new shot at the projectile's position (recursive `cast_payload`, depth-limited)".
- **Research:** WAND-R40/R41, SPELL-R18/R19, vectors KV-07, TV-S12. Payload cards are drawn at cast time from the same deck (wraps allowed), their mana is paid at cast, they enter the same hand, then the parent shot resumes its remaining draws. The payload is a fresh ShotState (cast delay 0, spread 0, speed 1; wand stats do not leak). Its recharge deltas count at cast time, its cast delay does not. If the trigger never fires nothing is refunded. Timer fires at the first of N frames, collision or death, once; death trigger releases in a random direction if the carrier is stationary or killed by terrain. Payload draw counts: 1, except `LIGHT_BULLET_TRIGGER_2` 2 and `DELAYED_SPELL` 3. There is no trigger depth limit; the recursion limit 2 belongs to copy spells (WAND-R80). Mana vector KV-07: `[LIGHT_BULLET_TRIGGER, SPITTER]` at >= 15 mana gives trigger + payload, 10-14 trigger with an empty payload, 5-9 payload alone.
  - Failure of the lazy design: draws at hit time change mana, uses, deck and wrap state at the wrong moment; a trigger that never fires wrongly spends nothing; cast-delay and recharge accounting differ; fixtures draw_04 and timing_01 would not reproduce.
- **Change:** build a `ShotTree` entirely inside `cast`: `Projectile { spec, shot: ShotState, trigger: Option<Trigger{kind, timer_frames, payload: Box<ShotTree>}> }`; at runtime the projectile only releases its pre-built payload on collision, timer or death.

### W2. Purity and placement of the casting algorithm (important)
- **Design/PRD:** `spells/cast.rs` pure over `(&mut WandState, &SpellRegistry, &mut Rng)` returning `CastResult { spawns, cast_delay_frames, recharge_frames, mana_spent, events }`.
- **Research:** a pure core is right and valuable (unit-testable, no `World` import), and it enables a world-free evaluator for the `wand_dps` reference search (below). But the signature is insufficient:
  - World/entity reads: IF_ENEMY (>= 15 `homing_target` entities within 240 px), IF_PROJECTILE (>= 20 projectiles within 160 px), IF_HP (hp/max <= 0.25), IF_HALF (one global alternating flag; part of the hash, wand-casting S7).
  - Caster-state spells: BLOOD_MAGIC, BLOOD_TO_POWER (hp), MONEY_MAGIC (gold), DAMAGE_FOREVER (wand mana), DAMAGE_RANDOM (RNG); ZETA reads other wands; RANDOM_* and DRAW_RANDOM* need the `spells` stream (SPELL-R43).
  - Missing outputs: the ShotTree (W1), recoil accumulator, `current_reload_time`, `start_reload`/`reloading` flags, hand/discard and per-card uses bookkeeping (WAND-R63), always-cast copies, `got_projectiles`.
  - World-free search: the `wand_dps` reference needs a cast-only evaluator. Ordered subsets of a pool (empty slots do not matter): P=8 spells, capacity 6: 28,961 arrangements; P=12, capacity 8: 24,723,745. At about 2 us per cast evaluation (UNVERIFIED) the latter is about a minute; at 30-300 ms per 600-frame full-world trial (UNVERIFIED) it is infeasible.
- **Change:** `cast(&mut WandState, &SpellRegistry, &CastContext, &mut SpellRng) -> CastOutcome` with `CastContext` a plain read-only struct or trait built by game code (caster hp/max, gold, deterministic entity counts, global flags, other wands). Add an analytic damage evaluator in `tasks/` over `CastOutcome`.

### W3. ShotState and timing rules incomplete (important)
- **Design/PRD:** ShotState lists damage adds, speed multiplier, spread, bounces, "pierce", trail, radius add, homing, lifetime add, crit; PRD lists cast delay and recharge "accumulated from spell modifiers".
- **Research:** WAND-R12..R57, R70..R72, R80..R86; spells SPELL-R15/R16/R17. Set-mode cast delay (CHAINSAW 0, NUKE 20, NUKE_GIGA 50) discards earlier accumulation (TV-S4: order [BURST_2, LIGHT_BULLET, NUKE] gives 20 f, [BURST_2, NUKE, LIGHT_BULLET] gives 23 f); `speed_multiplier` clamp [0, 20]; radius clamps at 0; `pattern_degrees` is set, not added. Effective cast delay `max(1, total)` (clamp on the total, KV-14) and 1 frame for a click with no projectile; effective recharge `max(0, total)`; cast delay and recharge run concurrently (next click at `max`, WAND-R54); recharge deltas accumulate across clicks until a recharge starts (KV-09); mana regenerates every frame also when the wand is not held, the cap is applied at click start only (mana may exceed it inside a click, TV-S18); uses are charged at end of click only if a projectile/static/material card was played or the card is OTHER/UTILITY (R63); `dont_draw` is one global boolean (R25); recursion limit 2; Wand Refresh semantics (R86). "Pierce" is not a ShotState field (Piercing Shot is a D2 script setting `on_collision_die = 0`).
- **Change:** PRD R2 and design 3 reference WAND-R01..R86 and KV-01..KV-15, TV-S1..S18; record decision D1 (deck empty at end of click means recharge) and D2 (Unlimited Spells perk in tasks).

### W4. `Behaviour` enum keyed by spell id (important)
- **Design/PRD:** design 3: `Behaviour` is an enum resolved from `SpellDef.id` at load, unknown gives `Unimplemented`. PRD: an `enum Behaviour` implements MVP-50.
- **Research:** SPELL-R36..R41, DF-5: seven primitives (PROJ, TRIGGER, STATIC, MATERIAL, MODIFIER, MULTICAST, UTILITY) and three implementation classes: D0 127 (a data row interpreted by the core), D1 110 (data plus a named reusable feature: PROJ_HP 18, MATERIAL_CONVERT 19, HIT_EFFECT 19, PHYS_BODY 13, SIDE_ENTITY 12, HOMING 10, ...), D2 185 (42 engine-level deck logic, 143 entity scripts mostly 20-60 Lua lines). A per-spell enum would need up to 422 variants while 237 (56.2%) need no per-spell code.
- **Change:** `SpellDef { primitive, ProjectileSpec, CardDelta, Trigger, MaterialSpec, features, handler_id }` plus a handler registry for D2; an `implemented` bit per spell recorded in `content_hash`.

### W5. ">= 300 loadable" and the no-op fallback (important)
- **Design/PRD:** AC: "`spells.json` loads with >= 300 spells; a test asserts every MVP-50 spell has a non-no-op behaviour"; others "load but cast as unimplemented no-op, logged".
- **Research:** 422 spells load, so the load clause is trivial. Verified in `spell_taxonomy.json` and `mvp50.json`: MVP-50 = 35 D0 + 6 D1 (BOMB, DYNAMITE, FIREBALL, LIGHTNING, NUKE, HOMING) + 9 D2 (BLACK_HOLE, DECELERATING_SHOT, PIERCING_SHOT, PINGPONG_PATH, CHAIN_SHOT, ADD_TRIGGER, ADD_TIMER, DIVIDE_2, RESET). About 300 behaving spells means D0 127 + D1 110 = 237 plus about 63 of the 185 D2 (SP S1 suggests deck-ops 42 + trajectory 12 + holes 6). Out of reach for the MVP: 143 entity-script D2 spells (effort S/M/L), 15 summoned-creature and 13 easter-egg note spells (DEFER), 16 spells whose side-entity XML is not stored (UNVERIFIED), 5 MVP-50 spells behind 3 unlock flags (NUKE, ADD_TRIGGER, ADD_TIMER, RESET, DIVIDE_2; ignore flags, SP S5). A spell that silently does nothing inside a benchmark pool is a validity bug: the agent sees stats for a spell that has no effect.
- **Change:** AC: "all 422 parse and validate; per-spell `implemented` set hashed in `content_hash`; task pools and `edit_wand` accept implemented spells only (others give `INVALID_ACTION`); fuzz: cast every implemented spell once; milestones: MVP-50, then all D0 (127), then D1 by feature".

### W6. Rigid-body spells vs "no rigid bodies" (important)
- **Design/PRD:** parent PRD non-goal "rigid-body pixel objects"; wand PRD AC "bomb carves rock but not steel".
- **Research:** BOMB (#10) and DYNAMITE (#11) of the MVP-50 are PHYS_BODY + PROJ_HP (BOMB also SIDE_ENTITY loose_ground); 13 catalogue spells are PHYS_BODY; Noita's second starter wand is a Bomb (`player-stats.json`); Bomb: throw coefficient 0.75, fuse 180 f, hp 12.5 (display), radius 60, ray 6M, dur 11, fire 40%. Dynamite: throw coefficient 2.5, L50, radius 28.
- **Change:** decision 1 (SP S3). Default: ballistic projectile with bounces, friction, fuse and a shoot-to-detonate hit-point value; loose_ground collapse not simulated (UNVERIFIED mechanism).

### W7. Worked-example acceptance (important)
- **Design/PRD:** AC: "Unit tests reproduce the worked examples in `research/wand-mechanics.md`".
- **Research:** `wand-mechanics.md` has known errors (Scatter "+10 each" is +10/+20/+40; Mu draws only after a copy; Formation spacing off by 2; 179 vs 143 modifiers). `wand-cast-test-cases.json` (32 cases) has 3 wrong expected values: draw_01 mana 10 vs 15, greek_01 cast delay 105 vs 114, refresh_03 (second RESET never drawn; recharge flag false after click 1, replaced by KV-01). It also mixes stage 2: greek_01..03 (Tau, Gamma, Omega, Alpha) while wand-casting S4 puts Greek letters, Duplication, Requirement, Zeta and the random-draw spells in stage 2; draw_02 needs NUKE; refresh_01 and spc_01 depend on engine rule R51 (decision D1).
- **Change:** AC: "stage-1 vectors KV-01..KV-15, TV-S1..TV-S18 and the corrected fixtures (draw_01..06, tuple, spc, shuffle, mana, divide_01..05, addtrigger_01..04, refresh_01..02, always_cast, timing)"; stage 1 = WAND-R01..R64, R70..R72, R80, R81, R82, R86; separate stage-2 AC for Greek letters, Duplication, Requirement, Zeta.

### W8. Projectile motion and collision (important)
- **Design/PRD:** projectiles "integrate velocity (gravity factor), ray-march against the grid from old to new position, bounce/pierce/explode on hits, test against entity AABBs".
- **Research (the ray-march idea is right; these are missing):**
  - Units: speeds are px/s, divide by 60. Terminal velocity 1000 px/s = 16.7 px/frame (Spark Bolt 750-850 = 12.5-14.2 px/frame; `long_distance_cast` 1,800 = 30; Lightning 5,400 = 90, no cap); defaults gravity_y 400, air_friction 0.55, `v -= 0.016666567*v*friction` (integration order UNVERIFIED).
  - Collision mask by kind (SIM-R62/MVP-R05): static, powder, solid block; liquids do not unless `die_on_liquid_collision` (MATERIAL_PARTICLE sprays); `go_through_this_material`.
  - Normal: a DDA step gives only an axis-aligned side, so bounces on pixel terrain jag; SIM-R63 uses the negated sum of blocked-cell vectors in the 7x7 neighbourhood. `bounce_energy` 0.5 (Rubber Ball 0.9); `penetrate_world` coefficient 0.6; ground penetration (Luminous Drill coefficient 4, max durability 14; slow-down UNVERIFIED).
  - Entity hit: a swept segment against the hitbox (player 6 x 16 px) at up to 30 px/frame; a point-in-AABB test tunnels. One hit per entity unless `penetrate_entities` (tracked list); `on_collision_die = 0` re-hits every frame unless `damage_every_x_frames`; the shooter is skipped unless `collide_with_shooter_frames`; first hit by parameter `t`, ties by entity id.
- **Change:** add to design 3 with a `ProjectileSpec` per DF-5 (speed range, lifetime +- random, gravity, friction, mass, bounces, collide flags, damage by type, explosion config).

### W9. Frame order and Input shape (minor)
- **Design/PRD:** design 3 order input, AI, cast, projectiles, `world.step()`, statuses, cleanup; `Input` includes `edit wand`.
- **Research:** SIM-R80 adds a serial explosion phase (queue order), a particle phase, the UPDATED clear and `dirty = next`, events and optional hash; wand timers (mana regen, recharge and cast-delay countdown) tick every frame for every wand (WAND S10). BEN ACT-R02/R03 separate a held control state (jump edge-triggered) from one-shot actions.
- **Change:** align `Game::step` with SIM-R80; split `Input` into `ControlState` and `OneShot`.

---

## E. Entities, damage and player

### E1. Damage units (important)
- **Design/PRD:** no unit stated anywhere; "damage table", "explosion damage with falloff".
- **Research:** internal x 25 = display (player 4.0 = 100 HP; Spark Bolt XML 0.12 = 3; DAMAGE modifier +0.4 = +10; ConfigExplosion default 5 = 125). `spells.json` mixes units: `damage.*` and `damage_modifier.*` are display, while `projectile_xml.*.damage`, `damage_by_type_raw` and `action_effects_raw.c_add.damage_*_add` are internal (SPELL-R03, pitfall 1). Consequences: a dummy "hp 100" read as internal is 2,500 display, 833 Spark Bolt hits instead of 34. Contact damage per pixel per frame (internal): acid 0.005, lava 0.003, poison 0.001; minimum 4 overlapping cells; cap 85 px; acid fully submerged = 0.425 per frame = 10.6 display per frame, about 10 frames from 100 HP to 0; lava 4.5 HP/s per pixel (6 px at ankle depth about 27 HP/s, 20 px about 90 HP/s, 85 px 382.5 HP/s). entities-damage.md Example 4 states "dies in ~0.5 s" for the acid case; its own arithmetic gives 10 frames (K1).
- **Change:** decision S2: internal f32 in XML units everywhere in `noita_core` (newtype `Hp`), x25 only at the observation, UI and test boundary; suffix every data constant `_internal` or `_display`; loader tests TV-D1..TV-D7. Dummy HP defined as 4.0 internal (= 100 display).

### E2. Levitation and movement numbers (important)
- **Design/PRD:** none (PRD: "hold to levitate with a depleting meter that refills on the ground").
- **Research (`player-stats.json`, confirmed in `player_base` data):** gravity 350 px/s^2, max fall 350 px/s (5.8 px/frame), walk max 57 px/s (0.95 px/frame), jump velocity -95 px/s (apex 12.9 px), fly up 95, fly down 85, fly horizontal 52 px/s, `fly_time_max` 3.0 s (180 frames, drain 1 per second), ground refill 6 per second (full in 0.5 s), air refill 0.4 per second only after 38 airborne frames, -8 frames per fly press (anti-tap), jump input buffer 2 frames. benchmark.md Key numbers and benchmark-design loadouts say "levitation meter 1.0 s (~60 frames)", which contradicts 3.0 s. With 1.0 s the horizontal flight range is 52 px, so `cross_lava_pool` widths {48, 96, 160} px need 0.92, 1.85 and 3.08 s of flight: only 48 px works at 1.0 s, and 160 px (156 px of flight at 3.0 s) is marginal even at vanilla.
- **Change:** put the vanilla values in `player.rs` constants; make `fly_time_max` a task-config override recorded in the task version (decision 9); recompute task geometry from these speeds.

### E3. "Take fall damage" (minor)
- **Design/PRD:** playable-frontend AC: "take fall damage".
- **Research:** `falling_damages = 0` for the player (`player_base`, `player-stats.json`); entities-damage pitfall 9: only Eväkäs and props take fall damage.
- **Change:** drop it from the AC, or record it as a deliberate departure.

### E4. Status and contact-damage details (minor)
- **Design/PRD:** design 3: statuses interact with the cell under or around the entity (water gives wet, oil gives oiled, fire plus oiled gives burning).
- **Research:** ED MVP simplification: spell-applied fixed-duration statuses (720 f for wet, oiled, bloody, slimy; frozen 120; stun 40 per hit with 60 f resistance), no passive stain persistence; but immersion in a liquid extinguishes On Fire (DAMAGE-R14); contact damage is per overlapping cell per frame with a 4-cell floor and lives on the entity, not the material (HAZ-R03), so every enemy needs its own table; i-frames 60 without refresh; swim physics and air in lungs (7 s, 15 HP/s suffocation) exist in `player-stats.json` but are not in the design.
- **Change:** list the MVP status set and the swim/air rules in design 3.

### E5. Enemy set (minor)
- **Design/PRD:** "at least 3 simple enemies (walker, flyer, shooter)".
- **Research:** `enemies.json` has 8 MVP enemies (display HP: Hämis 2.75, Hurtta 12.5, Haulikkohiisi 22.5, Snipuhiisi 45, Stendari 80, Hämähäkki 162.5, Nelikoipi 20, Konna 7.5) and a 28 x 28 faction matrix; a Spark Bolt (3 damage) one-shots Hämis. No entry is a pure flyer (Stendari hovering is UNVERIFIED).
- **Change:** pick the 3 concrete enemies and their stats from `enemies.json`.

---

## B. Agent benchmark (design.md section 4, agent-benchmark PRD)

### B1. Protocol surface (important)
- **Design/PRD:** requests `info`, `reset{seed, task, config}`, `step{actions, frames}`, `observe{mode}`, `hash`, `replay{seed, task, actions[]}`; errors as responses; `wait: frames` as an action.
- **Research:** PROTO-R01..R05, ACT-R01..R05, ANTI-R03/R07: `hello` handshake (`protocol_version`, `engine_version`, `engine_git`, `content_hash`, `suite_version`), request `id` echoed, `list_tasks`, `info{what}`, `metrics`, `close`, `replay` returning `{verified, first_divergence, score}`; `step.frames` 1-600, `actions` length 1 or equal to `frames`; one-shots separate; `max_frames_per_decision` (120) and `decision_limit` enforced engine-side (the PRD's unbounded `wait` lets a client skip an episode); an invalid action gives `ok:false`, no frame advance, counts as a decision and is echoed in the next observation's events; `save_state`, `load_state`, `debug` only with `--dev`, recorded in the header; error codes `INVALID_ACTION`, `BAD_TASK`, `EPISODE_OVER`, `DEV_ONLY`, `PROTOCOL`, `LIMIT`.
- **Change:** adopt the benchmark-design 2.2 message set for v1; add `noita_bench verify run.jsonl`.

### B2. Replay, hash, seeds, versions (important)
- **Design/PRD:** `hash` request; `replay` returns the final hash; "task versioning"; `Task::setup(seed)`.
- **Research:** DET-R02/R03, SEED-R01..R03, VER-R01..R06: per-step `state_hash` and `episode_hash = blake3(concat(step hashes))` (localises the first divergence); `replay` must also take the config (obs, assists, `wand_edit` policy, frame skip) because they change the trajectory or the legal actions; seeds `episode_seed = blake3(task_id || version || index)`, public indices 0-19, hidden 20-39 via a maintainer salt, raw u64 marked non-leaderboard; `content_hash` over runtime files plus task generators; golden hashes per `task@N`; any change to a golden hash is an engine minor bump; frozen generator module per task version.
- **Change:** per-step hash and golden-hash files now; hidden-seed salt and leaderboard rules can wait (derive seeds the BEN way from the start so nothing is renamed later).

### B3. Action schema (important)
- **Design/PRD:** `{move, jump, fly, aim: [dx,dy] or angle, cast, kick, swap_wand, edit_wand:{wand, slot, spell|null}, wait}`.
- **Research:** ACT-R02/R03 and benchmark-design 2.3: control state (held): `move` -1/0/1, `jump` edge-triggered, `fly`, `aim` as `{deg}` or `{dx,dy}` or `{at}` with signed degrees (0 = right, counter-clockwise positive, integer degrees in text mode), `fire` (not `cast`), `kick`, `interact`, `down`; one-shots: `swap_wand`, `edit_wand{wand, spells[...]}` (whole wand), `drop_spell`, `pickup`, `wait`; `wand_edit` policy `anywhere | at_rest_zones | locked` and `max_wand_edits` (default 5), edit refused mid-cast; RL vector `MultiDiscrete([3,2,2,24,2,2,2,5])` with frame skip 4.
- **Change:** rename `cast` to `fire`; add the edit policy and budget; define integer-degree aim quantisation and its sin/cos via table/libm (D2); `interact`, `down`, `pickup`, `drop_spell` may follow later.

### B4. Observation modes (important)
- **Design/PRD:** LLM: ASCII map of R x C cells with downsampling, legend, entities, HUD, wands, spell pool, events, task progress. RL: "uint8 material grid (row-major, base64 or array), f32 vectors".
- **Research:** OBS-R01..R09, PROTO-R05: priority down-sampling (player > entity > fire > liquid > powder > gas > solid > air) then majority, default 4 px/char (48 x 32 chars = 192 x 128 px, about 1.5k tokens), `near` inset 1 px/char (24 x 16, about 400 tokens) on for digging and aiming tasks; legend fixed per `content_hash`; entities sorted by distance, cap 16, never hide the goal; spell numbers are the wand-editor display numbers; last 32 events; RL `grid` uint8 3 x 128 x 128 (material, flags, entity class), `vec` f32 >= 40, `spells` uint16 4 x 26, base64 with shape/dtype/codec, never JSON number lists (128 x 128 as numbers is about 60 KB vs 22 KB base64 vs about 3 KB zlib); spaces published by `info actions`.
  - Material ids: the table has 466 materials (u16), so a uint8 channel overflows past 254 (255 = unknown). MVP-40 fits, the full table does not.
  - Resolution: 4 px/char majority hides features below 4 px; benchmark-design task 4 puts dummies "behind 1-4 px thin rock", and a Digging Bolt crater (R6) is 1.5 chars wide.
- **Change:** remove "or array"; add a fixed `obs_class` LUT (<= 254 classes, versioned by `content_hash`) or a uint16 dtype; require `near` inset or feature size >= 8 px for aiming and digging tasks.

### B5. Task suite against world size, kinematics and rules (important)
- **Design/PRD:** >= 6 tasks (8 named), score in [0, 1], 512 x 512 benchmark world, `Task::score(&Game)`.
- **Research (benchmark-design task table plus numbers above):**
  - World size: `dig_to_depth` D in {256, 512, 1024} and `reach_portal` 300-600 px do not fit a 512 x 512 world (D = 1024 needs about 1,152 px of height: 512 x 1,152 = 589,824 cells, 2.25x the budget cell count, unless an active rect is used).
  - Digging rate: a Digging Bolt removes 1 cell of rock per ray (ceil(100,000/100,000)) but 6 in soil; rock progress is about 1-3 px per cast, so D = 1,024 in 3,600 frames needs at least 17 px/s (feasibility UNVERIFIED; validate with the scripted baseline).
  - Hazard numbers: benchmark-design says lava deals ">= 10 hp/s"; vanilla is 4.5 HP/s per overlapping pixel (E1).
  - `extinguish_fire`: success "zero burning cells for 120 frames" must be reachable under FIRE-R08 (water does not douse burning materials; starve, flood or delete) (S7, K1).
  - Monotone score: SCORE-R03 requires a running maximum, so `score(&Game)` as a pure function is insufficient; `Task` needs state (`on_step`), and `terminated` (death, goal) must be separate from `truncated` (frame or decision limit).
  - `wand_dps`: score needs a reference damage per seed computed offline (exhaustive for P <= 8 and capacity <= 6 = 28,961 ordered subsets, otherwise a fixed search budget), never exposed (ANTI-R04); needs the cast-only evaluator of W2. PRD defines score as "damage dealt" only, not normalised to [0, 1].
  - `cross_lava_pool`: see E2 (levitation).
- **Change:** per-task world dimensions (width 512, height per task, active window), tune parameters after kinematics, add `Task::on_step`, `Task::limits{frame, decision}`, `wand_edit` policy.

### B6. Client and run header (minor)
- **Design/PRD:** Python client stdlib only; `run_scripted.py`.
- **Research:** DET-R01: sticky actions and seed sampling live in the client with their own seed and are recorded in the header; header fields in benchmark-design section 6; a Gymnasium adapter is optional and outside the core.
- **Change:** write `run.jsonl` header and `metrics.json` from the first version.

---

## P. Performance acceptance

### P1. Numbers (important)
- **Design/PRD:** parent R1: "1024 x 1024 with an active radius at >= 60 Hz; headless 512 x 512 >= 5x realtime" (3.33 ms/frame). pixel-sim-core AC: "512 x 512 full of falling sand/water < 4 ms" (4.2x), "settled < 0.1 ms". Benchmark AC: ">= 300 frames/s on a 512 x 512 task world" (3.33 ms, end to end through the protocol). Frontend AC: "< 16 ms during heavy liquid flow" in 2048 x 1536.
- **Research / arithmetic:** all-active, single thread: 3.33 ms is 12.7 ns per cell, 4 ms is 15.3 ns per cell, 1024 x 1024 at 60 Hz is 15.9 ns per cell; with 4 effective threads 51-64 ns per cell. Prior art gives no hard evidence: Nolla publishes nothing; sandspiel 300 x 300 "renders in < 1 ms" (secondary, unclear whether it includes the tick; at most about 11 ns/cell); FallingSandEngine's author claims (-90% by testing before cloning, -35% from inlining) are unmeasured here; falling-rust benches (64 x 64) have no captured figures; "5-30 ns per active cell" is an unmeasured expectation (PST 11.1). The rules here are heavier than sandspiel's (multi-step fall with up to 6 reads, per-cell hash RNG, reaction candidate lookup, timers), so the upper half is likely (UNVERIFIED): all-active 512 x 512 under 4 ms single-threaded is not safe; with 4 or more threads (16 chunk tasks per pass) or at <= 25-30% active cells it is plausible. "Settled < 0.1 ms" holds only without always-awake sources (SIM-R12): MVP-40 has 6 air-input rows (xml_005 cement, 021 ice, 053 acid, 111 whiskey gas, 168 whiskey, 179 poison) and water+soil (xml_183), so exposed ice, whiskey, cement or soil-adjacent water never sleeps, and any gas with a timer keeps its chunk awake. The 300 frames/s gate also has to carry entities, projectiles, the state hash (S13) and observation encoding (a 128 x 128 x 3 uint8 grid is 49 KB, plus zlib and base64).
- **Change:** define named scenarios (SIM-R82: empty; sand rain 5%; water pour into a basin; lava plus water; burning oil lake; 10 explosions R30 and one R250; all-active soup; 1/2/4/8 threads; dirty on vs off) and record ns per active cell; make the AC two-tier: gate = typical task scene (<= 10% active) >= 300 frames/s end to end with frame skip 4; report-only = all-active worst case until measured. Fix 4 ms vs 3.33 ms. Set the active-rect size for the game world (SD7: 512 x 512 around the player).

---

## F. Frontend, worldgen, content

### F1. Frontend data path (important)
- **Design/PRD:** design 5: `noita_game` fills a view-sized RGBA buffer from `World` using the palette. `research/frontend-tech.md` section 1: the frontend requests observations from `noita_bench` and draws a 128 x 128 uint8 material grid.
- **Research:** the observation grid carries no colour variant and is 16,384 cells, 16% of Noita's virtual screen (427 x 242 = 103,334 cells); `Texture2D::update` is a full upload (partial update absent in 0.4, UNVERIFIED); 427 x 242 x 4 B = 404 KB per frame is fine; the timing table in frontend-tech is labelled "Measured (UNVERIFIED)".
- **Change:** follow design 5 (direct core access, rule "front ends contain no game rules"); correct the frontend-tech diagram; take view size from the camera, not from the bench window.

### F2. UI toolkit (minor)
- **Design/PRD:** design 5 "UI with `macroquad::ui`"; PRD "drag spells between inventory and wand slots".
- **Research:** frontend-tech 5.1: `macroquad::ui` has no drag and drop; `egui-macroquad` 0.22.1 compatibility UNVERIFIED; recommends a hand-rolled immediate-mode widget.
- **Change:** hand-rolled slot widgets; click-to-pick then click-to-place counts as the drag.

### F3. Worldgen (important)
- **Design/PRD:** frontend PRD: `noita_core::worldgen`, "seeded, chunk-local", fBm caves, pools, veins, rest rooms, portal, spawn points; design 7: fixed 2048 x 1536 world.
- **Research (`research/worldgen.md` section 7, 10, 11):** the pseudo-code seeds Perlin per chunk (`Seeded_Perlin(chunk_seed)`), so each chunk gets a different noise field and seams appear at chunk borders; it uses f32 Perlin via the `noise` crate (its own 11.1 says avoid floating point; cross-platform identity UNVERIFIED); it streams 512 x 512 chunks through a `HashMap<(i32,i32), Chunk>` (design 7 says fixed world; `HashMap` iteration is banned in the sim path, lookups are fine); text says "3D Perlin" for a 2D function; Noita itself uses herringbone Wang tiles plus pixel scenes (`worldgen.md` section 5, `noita-engine-constants.json`), not fBm. KB page `worldgen.md` does not exist (implement.md phase 0 unchecked).
- **Change:** one global seed; integer or fixed-point value-noise lattice keyed by world coordinates (`hash(seed, ix, iy)`), fBm summed in integers; chunk-local generation only as a scheduling unit; hand-authored or verified-solvable arenas for benchmark tasks (generator checks solvability by ray or BFS test); write the KB page before the frontend child starts.

### F4. Content statements in the PRDs (minor)
- **Design/PRD:** parent R1 material list: gravel, obsidian, honey, fungus, dirt, "steel (indestructible)"; AC "pour water on lava to make obsidian"; wand PRD "digging bolt removes soft material only".
- **Research (`materials.json`):** no `obsidian` or `gravel` id exists; `[lava]+water -> rock_static + steam` (xml_065, 80%, blob 6/3); `honey` is a powder of density 10; "dirt" is `soil`; `fungus_powder` spawns an entity (not MVP). `steel_static` durability 12: Bomb (max 11) cannot remove it, Nuke (12) can; only durability >= 15 (gems) and the world boundary are untouchable. Digging Bolt (ray 100,000, max durability 10) removes any cell with durability <= 10, including rock_static (1 cell per ray), so "soft only" is wrong (depth is `ceil(E/hp)`).
- **Change:** reword the ACs: "rock + steam", "removes durability <= 10, depth by hp", "Bomb leaves steel_static intact".

### F5. Process and assets (minor)
- **Design/PRD:** design.md intro: children refine their own `design.md`.
- **Research/state:** no child has a `design.md`; every `implement.jsonl` and `check.jsonl` still holds the template placeholder; KB pages `worldgen.md`, `frontend.md` and `.trellis/spec/rust-core/` do not exist; runtime assets are copies of `materials.json` (1.05 MB, with notes, palettes, wiki prose) and `spells.json` (1.67 MB), so a prose edit would change `content_hash` (VER-R03).
- **Change:** generate trimmed runtime JSON from the research files with a script; hash those; curate the manifests; write the missing pages.

---

## Top 10 faithful-vs-simple decisions for the user

Each lists what faithful costs, what the simple version costs, and the default I would take. "Default" is a recommendation, not a decision.

1. **Rigid-body objects (Bomb, Dynamite, crates; 13 PHYS_BODY spells; Noita's second starter wand is a Bomb).** Faithful: Box2D-style bodies (marching squares, simplification, triangulation, rapier; determinism across platforms UNVERIFIED). Middle: kinematic rolling bodies in the pixel sim (SP S3). Simple: a ballistic projectile with bounces, fuse (180 f) and hit points. Default: simple now, middle later; keep the `OBJECT` flag and `bodies_stamp/unstamp` hooks (SIM-R86).
2. **Fire and "extinguishing".** Faithful: burning is a cell state; water boils (20%) but does not douse burning materials; burn-out by fuel, air starvation or deletion; no ash. Simple: water clears the burning flag. It decides the `extinguish_fire` and `chain_reaction` tasks and contradicts benchmark.md Pitfall 5. Default: faithful sim; define `extinguish_fire` by burning-cell count with flooding or starvation as the intended solution, or switch the task to a vacuum/flood tool.
3. **Explosions.** Faithful: ray energy against cell `hp`, durability gate, fire on any destroyed cell, thrown liquid, flat entity damage, radius-based damage floor, loose-ground collapse (not simulated). Simple: disc with a durability cut-off and linear damage falloff. Faithful costs 0.39-1.0 M cell visits for a nuke and a queue with caps. Default: faithful ray model (it is what makes digging depth depend on material), flat damage, no collapse.
4. **Matter thrown by explosions and splashes.** Faithful: particle subsystem (Q16.16, cap 100,000, serial phase). Middle: displace to nearest free cells by a spiral. Simple: delete. Default: middle for the MVP, particles later if a task needs visible splashes.
5. **Material set and motion fidelity.** Faithful: 466 materials, gravity-derived multi-step fall, 330 reactions, Box2D materials, entity-spawning reactions. Simple: MVP-40 (+12 stretch), 39 reactions, 3-input and ReqReactions dropped. The full table adds 54 air-input rows that keep every exposed surface awake (SD9) and 132 Solid materials. Default: MVP-40 with data-driven loading so more materials are added without code.
6. **Spell catalogue scope.** Faithful: 422 spells (185 need custom code, 15 summoned creatures, 13 easter-egg notes, 16 UNVERIFIED side entities). Simple: MVP-50, then D0 (127), then D1 by feature, then about 60 D2. Related: all unlocked vs progression flags; identification system off. Default: the ladder in W5, and pools restricted to implemented spells.
7. **Wand engine scope and rules.** Faithful: shuffle, Always Cast, Unlimited Spells perk, Greek letters, Duplication, Requirement, Zeta, wand generation; capacity up to 26 (benchmark.md says 3-8, "Noita ~40" is inaccurate). Decisions D1 (deck empty at end of click recharges), D2 (Unlimited Spells in tasks changes Divide chains, KV-05), D3 (IF_HALF global or per wand). Default: stage 1 (WAND S4) first; hand-made wands for tasks; capacity 3-8 as a task knob.
8. **Damage and status model.** Faithful: internal x 25, player explosion x 0.35, crit x 5 with RNG, i-frames 60 without refresh, multi-type damage, stains. Simple: whole-number HP, single damage type, spell-applied fixed-duration statuses (ED MVP). Related: no fall damage; explosion damage flat vs falloff. Default: ED's MVP simplifications with internal units and display only at the boundary.
9. **Player and projectile kinematics, numeric type.** Faithful: vanilla gravity 350, walk 57, fly 95/85/52 px/s, `fly_time_max` 3.0 s, anti-tap rules, f32 with libm. Simple/benchmark-tuned: shorter meter, simplified controller, aim in whole degrees, Q16.16 fixed point everywhere (SD13). Cross-platform bit-exactness (macOS arm64 vs Linux x86_64 golden hashes) vs same-binary determinism is part of this choice. Default: vanilla numbers, f32 with `libm` and no FMA, integer-degree aim in text mode, meter as a task-config override.
10. **World and arenas.** Faithful: streaming, Wang-tile worldgen, 35,840 px wide world. Simple: fixed 2048 x 1536 game world with global-seed integer noise; benchmark arenas hand-authored or verified-solvable. World height per task (D = 1024 needs about 1,152 px). Default: fixed worlds, authored arenas for tasks, procedural only for the playable game.

## Acceptance-criteria rewrites (summary)

| Criterion (PRD) | Problem | Replace with |
|---|---|---|
| 512 x 512 full of sand/water < 4 ms | disagrees with 3.33 ms; scenario undefined; unmeasured | named scenarios, ns/active-cell recorded; gate on a typical task scene, report-only for all-active (P1) |
| Settled worlds < 0.1 ms | false with always-awake sources | define "settled" (no gas, fire, exposed ice/whiskey/cement) and test it (S2, P1) |
| >= 300 frames/s | which scene, which overhead | end to end through `noita_bench`, frame skip 4, typical scene (P1, S13) |
| 1 vs 8 threads identical hash | too narrow | add threads 2/3/16, pass-order permutation, dirty-on vs off, snapshot, soup fuzz (D3) |
| spells.json >= 300 loadable; MVP-50 non-no-op | trivial vs hidden cost; unimplemented spells reach agents | all 422 parse; `implemented` set hashed; pools and `edit_wand` implemented-only (W5) |
| Worked examples in wand-mechanics.md | source and fixtures contain errors; stage 2 mixed in | KB vectors KV/TV and corrected fixtures, stage-1 scope (W7) |
| Bomb carves rock, not steel | consistent (Bomb max durability 11 < 12) but needs a bomb body | keep; depends on decision 1 |
| Digging bolt removes soft material only | wrong: durability <= 10, depth by hp | reword (F4) |
| Water + lava makes obsidian | no such material | rock_static + steam (F4) |
| Player takes fall damage | vanilla has none | remove or mark deliberate (E3) |
| Extinguished by water (fire) | materials are not doused by water | entity rule only; materials by fuel/starvation (S7) |
| Headless replay returns the final hash | cannot localise divergence | per-step hash, `verify` with first divergence (B2) |

## Edit checklist by file

| File | Items |
|---|---|
| `design.md` 2.1 | S1, S3, S4 |
| `design.md` 2.2 / 2.3 | S2, S5, S10, S11, D1 |
| `design.md` 2.4 | S4, S6, S7, S8, S9 |
| `design.md` 2.5 / 2.6 | S12, S13, D2 |
| `design.md` 3 | W1, W2, W3, W4, W8, W9, E1, E2, E4 |
| `design.md` 4 | B1, B2, B3, B4, B5 |
| `design.md` 5 / 7 | F1, F2, F3, B5 (world size) |
| `design.md` 6 | D1, D2, D3 |
| pixel-sim-core PRD | S1..S13, D3, P1, F4 |
| wand-spell-system PRD | W1..W9, E1..E5, F4 |
| agent-benchmark PRD | B1..B6, P1, W5 (pool policy) |
| playable-frontend PRD | E2, E3, F1, F2, F3, F4 |
| parent `prd.md` | P1, F4, W5, W6, decisions 1-10 |
| process | F5 |

## K. KB-internal inconsistencies noticed while reviewing

- K1. `benchmark.md` Pitfall 5 says extinguishing fire with MATERIAL_WATER "removes the flag"; `materials-reactions.md` FIRE-R08 and the wiki say water does not clear BURNING. benchmark.md also lists levitation 1.0 s (vs 3.0 s in `player-stats.json`), materials "~100" (466 in data), uint8 material ids (466 materials), "Noita 2048 x 1024" (35,840 px wide) and "~40 slots" (capacity 2-26). `entities-damage.md` Example 4 says the acid player "dies in ~0.5 s" but its own numbers give 10 frames.
- K2. `materials-reactions.md` D5/D8 (8-frame quantum for timers) is superseded by SIM-R35 (per-material unit, SD2); keep both pages in sync before coding.
- K3. `research/worldgen.md` (per-chunk Perlin seed, f32, HashMap streaming) and `research/frontend-tech.md` (frontend via bench observations, `macroquad::ui` for the editor) disagree with design.md and the KB; treat both as superseded where noted above.

## Sources

KB pages (`./.trellis/spec/game-design/`): `pixel-simulation.md`, `materials-reactions.md`, `wand-casting.md`, `spells.md`, `entities-damage.md`, `benchmark.md`.

Task documents: `./.trellis/tasks/10-07-noita-clone/{design.md,prd.md,implement.md,task.json}`, `./.trellis/tasks/10-07-{pixel-sim-core,wand-spell-system,agent-benchmark,playable-frontend}/{prd.md,implement.jsonl,check.jsonl}`.

Research files (`./.trellis/tasks/10-16-noita-cogbench/research/`): `pixel-sim-tech.md` (4.2, 5, 11, 13.9), `rust-prior-art.md`, `benchmark-design.md` (2.2-2.5, 3, 4, 5, 6), `worldgen.md` (6-8, 10, 11), `frontend-tech.md` (1, 2, 5, 6), `wand-mechanics.md`, `wand-cast-test-cases.json`, `spell_taxonomy.json`, `mvp50.json`, `spells.json`, `materials.json`, `reactions.json`, `player-stats.json`, `enemies.json`, `noita-engine-constants.json`, `entities-damage.md`.

Local raw pages and data: `raw/Fire.wikitext`, `raw/Digging.wikitext`, `raw/Explosion_interactions.wikitext`, `raw/Documentation__ConfigExplosion.wikitext`, `raw/noitadata/data_entities_player_base.xml` (numbers only; Nolla data, no code reproduced).

Wiki URLs: https://noita.wiki.gg/wiki/Fire , https://noita.wiki.gg/wiki/Digging , https://noita.wiki.gg/wiki/Explosion_interactions , https://noita.wiki.gg/wiki/Documentation:_ConfigExplosion , https://noita.wiki.gg/wiki/Modding:_Making_a_custom_material , https://noita.wiki.gg/wiki/Modding:_Magic_Numbers , https://noita.wiki.gg/wiki/Documentation:_ProjectileComponent , https://noita.wiki.gg/wiki/Materials , https://noita.wiki.gg/wiki/Density

External references already recorded in the KB: https://80.lv/articles/noita-a-game-based-on-falling-sand-simulation/ , https://blog.macuyiko.com/post/2020/an-exploration-of-cellular-automata-and-graph-based-game-systems-part-4.html , https://braindump.jethro.dev/posts/gdc_vault_exploring_the_tech_and_design_of_noita/
