# Falling-sand / Noita-like prior art for a Rust engine

Research date: 2026-10-07. Companion to `pixel-sim-tech.md` (engine mechanics) and
`pixel-sim-repos.json` (machine-readable version of the table below).
Star counts and last-push dates come from the GitHub API (`gh api repos/<owner>/<repo>`) on the research date.

Legend for the **Adapt?** column:

- **YES** — permissive license (MIT / Apache-2.0 / BSD-3-Clause); code may be ported or copied with attribution.
- **REF** — read for ideas only; **do not copy code** (GPL/AGPL, PolyForm Noncommercial, or no license file at all).
- **n/a** — not relevant to the engine.

"Inspected" means the core update-loop source was read for this research (excerpts mirrored under `raw/repos/`).
Repos marked UNVERIFIED were found by search but their internals were not read.

## 1. Repositories

### 1.1 Rust engines (inspected)

| Repo | License | Stars | Lang / stack | Last push | What it does well | What we can adapt | Adapt? |
|---|---|---|---|---|---|---|---|
| [MaxBittker/sandspiel](https://github.com/MaxBittker/sandspiel) | MIT | 3,182 | Rust (wasm) + JS/WebGL | 2026-09-10 | The canonical small falling-sand core: 32-bit `Cell {species, ra, rb, clock}`; one-line-per-rule species functions; relative-coordinate `SandApi::get/set(dx,dy)` with a +/-2 neighborhood guard; `clock = generation+1` to skip cells already moved this tick; GPU wind field coupled back into the CA. 300x300 grid, renders in <1 ms, 66 KB wasm. | Cell packing that maps 1:1 to an RGBA texture; the `SandApi` style of writing rules (every rule is `get` + `set`, trivially testable); the clock/generation skip; concrete water (direction memory in `ra` parity, "scoot double"), fire (ra lifetime, random-direction ignition), wood (rb burn counter), acid, lava, gas-molecule merging rules. | YES |
| [PieKing1215/FallingSandEngine](https://github.com/PieKing1215/FallingSandEngine) | BSD-3-Clause (code); CC BY-NC 4.0 (art, do not copy). `fs_common/Cargo.toml` says `license = "ARR"` but LICENSE + README govern: BSD-3. | 75 | Rust; rapier2d 0.17, rayon, specs ECS, glium | 2026-04-20 (dev stopped) | The most complete Noita-style architecture in Rust: 100x100 chunks, `Option<Rect>` dirty rect per chunk, 4-phase checkerboard (`chunk_update_order`) + `rayon::par_iter` per phase, 3x3 chunk context through `UnsafeCell`, dirty-rect propagation to neighbours (CHUNK_SIZE/2 band), sand->particle promotion, rigid bodies from pixels (`contour` marching squares -> `ramer_douglas_peucker` -> `earcutr` -> rapier compound triangle collider), per-body pixel buffers with `simulate_pixel -> Option<MaterialInstance>`, dummy "Object" pixels for bodies/entities during the sand tick, impulses + gravity-scale "impediment" when bodies sink into sand, Minecraft-style worldgen, chunk streaming with loader zones. | Almost everything structural: chunk/phase scheduler, dirty-rect bookkeeping, the mesh pipeline and the crate choices behind it, the rigid-body pixel-ownership approach (documented in the author's issue thread), the tick ordering pseudocode. **Port, don't copy verbatim**: the parallel section casts `&mut` arrays to `&[UnsafeCell<T>]` and the author flags probable UB. | YES |
| [noprobelm/bevy_falling_sand](https://github.com/noprobelm/bevy_falling_sand) | MIT OR Apache-2.0 | 19 | Rust; Bevy 0.19, avian2d 0.7, earcutr 0.5; on crates.io (0.8.x) | 2026-07-28 (active) | Cleanest dirty-tracking design found: `ChunkDirtyState {current, next, current_positions, next_positions, dirty_borders}` with `advance_frame()` inflating the rect by 2 px and 8 border flags that request 2-px edge strips when a neighbour was active; `ChunkCoord::group() = (y&1)<<1 \| (x&1)` checkerboard groups run on `ComputeTaskPool`; data-driven particle types (`Movement` candidate tiers, `Density`, `Speed`, `Momentum`, `AirResistance`, `ParticleResistor`); fire/corrosion/contact reactions; per-chunk static trimesh colliders throttled to 0.1 s; dynamic rigid-body proxies for single particles; chunk persistence and toroidal chunk index. | The dirty-state + border-strip model; the movement-tier data model (ordered candidate groups with per-tier air resistance); `utils/geometry.rs` (connected components -> perimeter loop -> DP simplify -> earcut) which is engine-agnostic. **Not** the entity-per-particle ECS layout (slow, and the README warns movement order in parallel systems is undefined, i.e. non-deterministic). | YES |
| [100-TomatoJuice/bevy_falling_sand](https://github.com/100-TomatoJuice/bevy_falling_sand) | Apache-2.0 | 25 | Rust; Bevy 0.14, bevy_rapier2d 0.27 | 2024-07-07 | Velocity-based movement: gravity adds 1/frame, a Bresenham `line()` walks toward `pos+velocity` and stops at the first occupied cell; blocked powders retry with 45-degree rotations (3 candidates), liquids/gases also 90-degree (5 candidates); density swap when heavier than the blocker. Chunk sleep via `strong_ticked`/`weak_ticked` countdowns (2 frames) that `set()` refreshes on the chunk and its 8 neighbours. Per-chunk edge marching (4-neighbour case table) -> DP (eps 1 solid / 2 others) -> rapier `Collider::polyline`. | The `line()` sweep for fast particles/projectiles; the rotation-fallback idea for velocity-driven cells; the countdown-based chunk sleep; the 16-case edge-marching table for static colliders. | YES |
| [grunnt/falling-rust](https://github.com/grunnt/falling-rust) | MIT | 30 | Rust; Bevy + egui | 2024-10-31 | Small, readable, tested: `Cell {element, variant, strength, visited}`; bottom-up scan with alternating x direction; element flags (`FLAG_BURNS`, `FLAG_ACIDIC`, ...) + form (`Solid/Powder/Liquid/Gas`); weight-based liquid swapping (1/3 chance), sideways dispersion up to `strength` cells, gas 3/5 up bias; `strength` doubles as burn/dissolve HP; criterion benchmark harness. | Rule organisation (generic flag handlers + form handler + element-specific handler), the `dissolve_to` HP pattern, the bench layout (empty / water flow / burning oil at 64x64). | YES |
| [astradamus/mintage](https://github.com/astradamus/mintage) | MIT | 1 | Rust; macroquad, rayon, arc-swap, ron | 2026-01-21 | Determinism-first design: double-buffered SoA (`Vec<MaterialId>` u16 + `Vec<f32>` temperature); physics modules run in parallel with rayon and emit `CellIntent {Transform, Reaction, MoveSwap}`; a serial resolver applies them in module order, first-writer-wins per cell via a changed bitmap; seeded Xoshiro per module; thermal diffusion / phase change; snapshot handed to a render thread through `ArcSwap`. | The intent/resolver pattern for parts of the sim that must be reproducible across thread counts (reactions, temperature); RON-driven material and reaction tables; the render-thread snapshot handoff. Too small (no chunks) to be a base. | YES |
| [spicylobstergames/astratomic](https://github.com/spicylobstergames/astratomic) | **PolyForm Noncommercial 1.0** (not OSI) | 136 | Rust; Bevy | 2025-03-07 | The closest literal implementation of the Noita scheme: 64x64 chunks; 4 update steps over `(x_toff, y_toff) in {0,1}^2` in random order; each task gets a `ChunkGroup` = `&mut` centre chunk + 4 half-chunk sides + 4 quarter-chunk corners, i.e. exactly the "64x64 plus 32 px in each direction" write region; `Atom {color, state, id, moving, speed:(i8,i8), f_idle, updated_at}` with sleep after `FRAMES_SLEEP = 1`; separate update and render dirty rects sent over async channels; GPU texture upload of dirty rects; save/load. | Design reference for the chunk-group margin layout and the atom sleep counter. **Do not copy code.** | REF |
| [cgsdev0/termsand](https://github.com/cgsdev0/termsand) | MIT | 316 | Rust | 2026-07-21 | tmux toy, single `main.rs`. | Nothing engine-relevant. | n/a |

### 1.2 Non-Rust engines worth knowing (inspected)

| Repo | License | Stars | Lang | Last push | What it does well | What we can adapt | Adapt? |
|---|---|---|---|---|---|---|---|
| [PieKing1215/FallingSandSurvival](https://github.com/PieKing1215/FallingSandSurvival) | BSD-3-Clause | 222 | C++ (SDL, Box2D) | 2022-09-24 (archived) | Predecessor of FallingSandEngine: `CHUNK_W/H = 128`; per tick 6 iterations x 4 checker passes (`chOfsX = tk%2`, `chOfsY = 1-((tk%4)/2)`), one `ctpl` thread-pool job (6 threads) per selected chunk, bottom-up rows; `tickVisited` bool arrays double-buffered and memset on a side thread; per-material `iterations` count so liquids get more sub-steps than sand; explosions, Box2D bodies via `cpp-marching-squares` + Douglas-Peucker. Issue #4 is the best public write-up of the rigid-body pixel-ownership problem. | The multi-iteration-per-tick idea for liquids; the issue-thread algorithm (now in the Rust rewrite). | YES |
| [DavidMcLaughlin208/FallingSandJava](https://github.com/DavidMcLaughlin208/FallingSandJava) | **none** (no license file => all rights reserved) | 217 | Java (libGDX, Box2D) | 2021-07-04 | Well-known tutorial implementation (YouTube series): 32 px chunks with `shouldStep/shouldStepNextFrame`; 12 threads over column stripes with shuffled x indices and a random per-frame offset, even stripes then odd stripes; velocity + gravity with sub-pixel accumulators and a Bresenham sweep; `isFreeFalling` / `inertialResistance` wake neighbours; liquids use `dispersionRate`; README spells out the Noita Box2D pipeline (marching squares -> Douglas-Peucker -> triangulation -> Box2D, re-run when pixels are destroyed) and the repo contains Moore-neighbour tracing, Visvalingam and DP implementations. | Ideas only (velocity model, inertial resistance, column-stripe threading as a contrast to the chunk checkerboard). **Do not copy code.** | REF |
| [GameEngineering/EP01_SandSim](https://github.com/GameEngineering/EP01_SandSim) | BSD-3-Clause | 595 | C (gunslinger) | 2024-02-25 | Companion to John Jackson's "Recreating Noita's Falling Sand Simulation" video (HN 32871938). Single 106 KB `main.c`; `particle_t` carries a `velocity` and `has_been_updated_this_frame`; sand/water/salt/fire/smoke/ember/steam/gunpowder/oil/lava/acid rules; `is_in_liquid`, `completely_surrounded` helpers; bloom post-processing. | Rule ideas for velocity-driven cells; nothing structural (no chunks or threads). | YES |
| [The-Powder-Toy/The-Powder-Toy](https://github.com/The-Powder-Toy/The-Powder-Toy) | GPL-3.0 | 5,351 | C++ | — | The falling-sand game Wikipedia names as Noita's inspiration; hundreds of elements, pressure/heat/electricity fields, particle list rather than a pure grid. | Element behaviour ideas only. **Do not copy code.** | REF |
| [JMS55/sandbox](https://github.com/JMS55/sandbox) | AGPL-3.0 | 342 | Rust (wgpu) | 2023-03-06 | Popular Rust sand sim with post-processing. Not inspected. | Nothing (AGPL). | REF |

### 1.3 Found by search but not inspected (UNVERIFIED internals)

| Repo | License | Stars | Lang | Note |
|---|---|---|---|---|
| [kiwijuice56/sand-slide](https://github.com/kiwijuice56/sand-slide) | MIT | 142 | C++ / Godot GDExtension | "Fast falling sand game"; Godot-specific. |
| [2606360985/PixelAlchemy](https://github.com/2606360985/PixelAlchemy) | MIT | 59 | C# / Unity | Noita-inspired roguelike prototype. |
| [tombh/wrach](https://github.com/tombh/wrach) | none | 18 | Rust (GPU) | GPU fluid sim "inspired by Noita"; no license file. |
| [transistorfet/fallingrust](https://github.com/transistorfet/fallingrust) | GPL-3.0 | 19 | Rust (wasm) | GPL: do not copy. |
| [Maticzpl/PowderRS](https://github.com/Maticzpl/PowderRS) | GPL-3.0 | 7 | Rust | GPL: do not copy. |
| [api-haus/bevy_pixel_world](https://github.com/api-haus/bevy_pixel_world) | MIT | 1 | Rust / Bevy / WASM | Self-described infinite persistent Noita clone with physics; brand new, unreviewed. |
| [Boxxfish/bevy_falling_sand](https://github.com/Boxxfish/bevy_falling_sand) | MIT | 1 | Rust / Bevy | "Noita-like falling sand plugin for Bevy". |
| [ryanpeach/OrbitingSandRust](https://github.com/ryanpeach/OrbitingSandRust) | GPL-3.0 | 4 | Rust | Factorio x Noita in space; GPL. |
| [IntQuant/noita_entangled_worlds](https://github.com/IntQuant/noita_entangled_worlds) | Apache-2.0 | 1,311 | Rust | Not an engine: a co-op mod that synchronises Noita's world between clients. Potentially useful later as a reference for how Noita exposes chunk/pixel data to Lua, but not read for this research. |
| [vitaminmoo/noita-tools](https://github.com/vitaminmoo/noita-tools) | MIT | 1 | Rust | Claims a game-exact port of Noita's world RNG (`noita-rng`). Not verified; could matter if we ever want seed-compatible worldgen. |

## 2. Crates for the building blocks (crates.io, 2026-10-07)

| Concern | Crate | Latest | Downloads | Notes |
|---|---|---|---|---|
| Rigid bodies (Box2D role) | [rapier2d](https://crates.io/crates/rapier2d) | 0.36.0 | 1.0 M | Used by FallingSandEngine (0.17) and 100-TomatoJuice (via bevy_rapier2d). Pure Rust, no engine dependency: right fit for a headless core. Check its determinism feature flags before relying on cross-machine reproducibility (UNVERIFIED here). |
| Rigid bodies (Bevy-native alternative) | [avian2d](https://crates.io/crates/avian2d) | 0.7.0 | 245 k | Used by noprobelm/bevy_falling_sand. Bevy ECS only; not for a headless core. |
| Bevy binding for rapier | [bevy_rapier2d](https://crates.io/crates/bevy_rapier2d) | 0.36.0 | 516 k | Only if the frontend were Bevy (ours is macroquad). |
| Box2D itself | [box2d-rs](https://crates.io/crates/box2d-rs) 0.0.4 (2023), [wrapped2d](https://crates.io/crates/wrapped2d) 0.4.2 (2024) | — | 11 k / 33 k | Stale ports/bindings; prefer rapier2d. |
| Marching squares / contours | [contour](https://crates.io/crates/contour) | 0.13.1 | 132 k | Used by FallingSandEngine (0.7) to turn a 0/1 value map into polygons with holes (`ContourBuilder::new(w, h, smooth).contours(&values, &[1.0])`). [marching-squares](https://crates.io/crates/marching-squares) 0.1.1 (2020) and [contour_tracing](https://crates.io/crates/contour_tracing) 1.0.12 (2022) exist but are stale. noprobelm hand-rolls perimeter tracing in ~400 lines, which is also fine. |
| Polyline simplification | [ramer_douglas_peucker](https://crates.io/crates/ramer_douglas_peucker) | 0.2.4 | 10 k | `rdp(&points, epsilon) -> Vec<usize>` of indices to keep (FallingSandEngine uses eps = 1.0). [geo](https://crates.io/crates/geo) 0.33.1 also has `Simplify`/`SimplifyVw` but is a heavy dependency. |
| Triangulation | [earcutr](https://crates.io/crates/earcutr) | 0.5.0 | 13.0 M | Ear-clipping with holes; used by FallingSandEngine (0.4) and noprobelm (0.5). [spade](https://crates.io/crates/spade) 2.15.1 / [delaunator](https://crates.io/crates/delaunator) 1.1.0 are Delaunay alternatives (constrained Delaunay in spade). |
| Parallel chunk phases | [rayon](https://crates.io/crates/rayon) | 1.12.0 | 583 M | `par_iter` over the chunks of one checkerboard phase (FallingSandEngine, mintage). |
| Fast RNG | [fastrand](https://crates.io/crates/fastrand) | 2.5.0 | 972 M | FallingSandEngine seeds one `Rng` per chunk tick; for determinism seed it from `(world_seed, tick, chunk_xy)` instead of `Rng::new()`. [rand_xoshiro](https://crates.io/crates/rand_xoshiro) (sandspiel SplitMix64, mintage Xoshiro256++) if a `rand`-compatible generator is preferred. |
| Line sweep / raymarch | [line_drawing](https://crates.io/crates/line_drawing) | 1.0.1 | 3.2 M | Bresenham, Walk-grid, XiaolinWu iterators for projectile/particle sweeps. |
| Math | [glam](https://crates.io/crates/glam) | 0.34.1 | 156 M | IVec2/Vec2; what Bevy and noprobelm use. |
| Frontend | [macroquad](https://crates.io/crates/macroquad) | 0.4.16 | 1.8 M | Our frontend choice; mintage renders a falling-sand snapshot with it. |
| Data files | [ron](https://crates.io/crates/ron) | 0.12.2 | 118 M | Material/reaction tables (mintage, noprobelm, FallingSandEngine). |
| Flags | [bitflags](https://crates.io/crates/bitflags) | 2.13.2 | 1.97 B | Material/cell flags. |
| Snapshot handoff | [arc-swap](https://crates.io/crates/arc-swap) | 1.9.2 | 350 M | Sim thread -> render thread world snapshot (mintage). |
| Noise for worldgen | [bracket-noise](https://crates.io/crates/bracket-noise) 0.8.7 (2022), [noise](https://crates.io/crates/noise) 0.9.0 (2024) | — | 381 k / 2.7 M | FallingSandEngine uses bracket-noise + simdnoise. |
| Fluids (optional) | [salva2d](https://crates.io/crates/salva2d) | 0.10.0 | 23 k | SPH fluids coupled to rapier; FallingSandEngine experimented with it and commented it out. Not needed for a cellular liquid model. |

## 3. What not to copy, and why

- **GPL / AGPL** (The-Powder-Toy, JMS55/sandbox, transistorfet/fallingrust, Maticzpl/PowderRS, OrbitingSandRust): copying any code would force our whole project under the same license. Reading for ideas is fine.
- **PolyForm Noncommercial** (astratomic): forbids commercial use; incompatible with an MIT/Apache release. Independent third-party contributions are dual-licensed Apache-2.0 per its README, but the core by Isaac Turci is not; treat the whole repo as read-only.
- **No license file** (FallingSandJava, tombh/wrach): default copyright, no permission to copy.
- **CC BY-NC assets** in FallingSandEngine's `gamedir/assets/texture/`: code is BSD-3 but art is non-commercial; never vendor the assets.

## 4. Recommended starting stack (synthesis)

1. **Core layout** from FallingSandEngine: fixed-size chunks (64x64 to match Noita and astratomic; FallingSandEngine's 100 and FallingSandSurvival's 128 also work), `Option<Rect>` dirty rect per chunk, 4-phase checkerboard with `rayon`, 3x3 chunk context per task, propagate a `CHUNK/2` (= 32 px) band into neighbours' dirty rects after a chunk moves anything. Replace the `UnsafeCell` aliasing trick with a chunk-group borrow (astratomic's centre + 4 half sides + 4 quarter corners, or a `split_at_mut`-based accessor) so the parallel section is sound.
2. **Cell rules** written in sandspiel's `get/set(dx,dy)` style over falling-rust's `form + flags` classification; cell struct of 4-8 bytes with a u16 material id (Noita allows 1024 materials, so u8 is too small), a per-cell `updated_at: u8` clock, and 1-2 bytes of per-cell state (`ra/rb` style).
3. **Liquids**: falling-rust / Noita sideways dispersion with a per-material spread distance and density swapping; **gases**: inverse rule with weighted up/side/down speeds (Noita exposes `gas_upwards_speed` etc.).
4. **Fast movers**: a separate particle list (FallingSandEngine `Particle`) stepped with a Bresenham/DDA sweep (`line_drawing`), used for sand thrown by explosions, splashes and projectiles.
5. **Rigid bodies**: `contour` -> `ramer_douglas_peucker` -> `earcutr` -> `rapier2d` compound collider, bodies own their pixel buffer, `simulate_pixel` returns `Option<Material>` (FallingSandEngine / PieKing issue #4).
6. **Determinism for the benchmark**: fixed phase order, per-chunk RNG seeded from `(seed, tick, chunk)`, no `HashMap`/`HashSet` iteration inside the simulation, intent-style resolution (mintage) only where cross-chunk conflicts cannot be avoided, and a frozen `rapier2d` version. noprobelm's README is a warning: shuffled scan order plus shared visited sets gives "undefined particle movement behavior in parallel systems".

## Sources

- https://github.com/MaxBittker/sandspiel (README, `crate/src/lib.rs`, `crate/src/species.rs`, LICENSE)
- https://maxbittker.com/making-sandspiel
- https://github.com/PieKing1215/FallingSandEngine (README, `fs_common/src/game/common/world/{simulator.rs,chunk_handler.rs,chunk.rs,rigidbody.rs,mesh.rs,physics.rs,world.rs,material/mod.rs}`, `fs_common/Cargo.toml`, LICENSE)
- https://github.com/PieKing1215/FallingSandSurvival (`FallingSandSurvival/Chunk.hpp`, `FallingSandSurvival/world.cpp`, LICENSE)
- https://github.com/PieKing1215/FallingSandSurvival/issues/4
- https://github.com/noprobelm/bevy_falling_sand (README, `Cargo.toml`, `src/core/chunk/{mod.rs,dirty.rs,coord.rs,index.rs}`, `src/movement/processing/systems.rs`, `src/physics/{static_mesh.rs,dynamic.rs}`, `src/utils/geometry.rs`, LICENSE-MIT, LICENSE-APACHE)
- https://github.com/100-TomatoJuice/bevy_falling_sand (`Cargo.toml`, `src/sandbox/{chunk.rs,sandbox.rs,simulation.rs,effects/movement.rs,collider/gen_colliders.rs}`)
- https://github.com/grunnt/falling-rust (README, `src/simulation.rs`, `src/sandbox/{mod.rs,cell.rs,element.rs}`, `benches/simulation_benchmark.rs`, `src/main.rs`, LICENSE.md)
- https://github.com/astradamus/mintage (README, `Cargo.toml`, `src/physics/{engine.rs,intent.rs}`, `src/sim.rs`, LICENSE)
- https://github.com/spicylobstergames/astratomic (README, LICENSE.md, `src/{consts.rs,chunk_manager.rs,chunk_group.rs,atom.rs}`)
- https://github.com/DavidMcLaughlin208/FallingSandJava (README, `core/src/com/gdx/cellular/{CellularMatrix.java,CellularAutomaton.java,util/Chunk.java,elements/Element.java,elements/solid/movable/MovableSolid.java,elements/liquid/Liquid.java}`)
- https://github.com/GameEngineering/EP01_SandSim (README, `source/main.c`)
- https://github.com/cgsdev0/termsand
- https://github.com/JMS55/sandbox
- https://github.com/The-Powder-Toy/The-Powder-Toy
- https://github.com/kiwijuice56/sand-slide
- https://github.com/2606360985/PixelAlchemy
- https://github.com/tombh/wrach
- https://github.com/transistorfet/fallingrust
- https://github.com/Maticzpl/PowderRS
- https://github.com/api-haus/bevy_pixel_world
- https://github.com/Boxxfish/bevy_falling_sand
- https://github.com/ryanpeach/OrbitingSandRust
- https://github.com/IntQuant/noita_entangled_worlds
- https://github.com/vitaminmoo/noita-tools
- GitHub search: `gh search repos "falling sand" --language rust`, `gh search repos noita --language rust`, `gh search repos noita --language cpp`, `gh search repos "falling sand"`, `gh search repos sandspiel`, `gh search repos "sand simulation" --language rust`
- crates.io API: https://crates.io/api/v1/crates/{rapier2d,avian2d,bevy_rapier2d,box2d-rs,wrapped2d,contour,marching-squares,contour_tracing,ramer_douglas_peucker,geo,earcutr,spade,delaunator,rayon,fastrand,line_drawing,glam,macroquad,ron,bitflags,arc-swap,bracket-noise,noise,salva2d,bevy,wgpu,imageproc}
- https://news.ycombinator.com/item?id=32871938 (via https://hn.algolia.com/api/v1/search?query=noita&tags=story)
- https://en.wikipedia.org/wiki/Noita_(video_game)
