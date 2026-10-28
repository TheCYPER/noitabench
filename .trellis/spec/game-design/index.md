# Game-Design Knowledge Base: Index

**What this is.** The normative design reference for the Noita-like Rust game (`noita_core` headless deterministic simulation, wand and spell system, entities, world generation, observation encoders, benchmark tasks; `noita_bench` JSON-lines binary; `noita_game` macroquad renderer). Each page turns the research under `.trellis/tasks/10-16-noita-cogbench/research/` into numbered rules that code and tests cite (`SIM-R22`, `WAND-R53`, ...), with data-file contracts, test vectors, pitfalls and the places where the clone deliberately simplifies Noita. The research files are provenance; **where a page and a research file disagree, the page wins** (the known research errors are listed in each page's pitfalls and disagreement tables). Focus of the project: the physical simulation and the spells; the game is also an AI-agent benchmark, so determinism and clear rules come first.

**Status at the time of writing (2026-10-07).** Eight content pages exist: `pixel-simulation.md`, `materials-reactions.md`, `wand-casting.md`, `spells.md`, `entities-damage.md`, `benchmark.md`, `worldgen.md`, and `frontend.md`. All normative pages are now in place.

Companion files: [glossary.md](glossary.md) (terms and where each is defined), [decisions-needed.md](decisions-needed.md) (every DECISION-NEEDED and open question, deduplicated, with a recommended default).

---

## 1. Conventions shared by every page

**Units.** Time is **frames at 60 Hz** (store frames, never seconds; 1 frame = 1/60 s, the simulation tick). Lengths are cell pixels (1 cell = 1 px); y grows down. Speeds are px/s in data (px/frame = px/s / 60). Angles are degrees. **HP and damage: internal x 25 = displayed** (`GUI_HP_MULTIPLIER`; player 4.0 internal = 100 shown); in `spells.json` the fields `damage` and `damage_modifier` hold displayed values while `projectile_xml`, `damage_by_type_raw`, `action_effects_raw` and the Lua/XML sources hold internal ones; convert once at the boundary (SPELL-R03). A cell's `hp` (hardness) is a **ray cost** for explosions, never entity HP and never multiplied by 25 (MAT-R11). Reaction `probability` is a percent float stored by the engine as `int(p*100)` (RXN-R03). Where a table mixes frames and seconds, the unit column says so.

**Names.** Materials: the lowercase snake_case `id` of `materials.json` (466 materials, e.g. `rock_static`, `acid_gas`; `air` is index 0 and a real material). Spells: the `game_id` of `spells.json` in UPPER_SNAKE (422 live spells, e.g. `LIGHT_BULLET`, `DIVIDE_2`); the lowercase `id` field in the JSON is only `game_id` lowercased and is never a key (SPELL-R01). Wiki display names ("Spark Bolt") appear in prose next to the id, never alone as an identifier. Test fixtures and benchmark logs use `game_id` strings (benchmark.md Pitfall 2).

**Evidence tags** (each page defines its own subset): `[N]` stated by Nolla (GDC 2019, relayed), `[W]` noita.wiki.gg, `[G]` read from the game data, `[R]` observed in a permissively licensed clone, `[DES]` our decision (normative), `[CAL]` tunable calibration, `UNVERIFIED` no primary source, `DECISION-NEEDED` the user must choose (a default is always stated).

**Rule and vector IDs.** Rule IDs are unique per prefix and never renumbered; cite them from code and tests.

| Prefix | Page | Notes |
|---|---|---|
| `SIM-Rnn`, vectors `SIM-Tnn` | pixel-simulation.md | decisions `SD1..SD13`, simplifications `S1..S10` |
| `MAT-`, `RXN-`, `FIRE-`, `DUR-`, `HAZ-`, `MVP-` (+ `-Rnn`), vectors `MV-nn` | materials-reactions.md | decisions `D1..D13` |
| `WAND-Rnn`, vectors `KV-nn` | wand-casting.md | decisions `WD1..WD4`, simplifications `S1..S10` |
| `SPELL-Rnn`, tables `KN-n`, `DF-n`, vectors `TV-D/S/B` | spells.md | simplifications `S1..S10` |
| `DAMAGE-Rnn` | entities-damage.md | decisions `ED-D1..ED-D2` |
| `WORLD-Rnn`, vectors `WORLD-Tnn` | worldgen.md | decisions `WG-D1..WG-D6`, simplifications `S1..S2` |
| `FE-Rnn` | frontend.md | decisions `FE-D1..FE-D2` |
| `PROTO-`, `DET-`, `ACT-`, `OBS-`, `SCORE-`, `SEED-`, `VER-`, `ANTI-`, `REAL-` (+ `-Rnn`) | benchmark.md | |

Decision and simplification IDs are page-local: cite them with the page (`MR D2`, `SIM SD1`, `WAND WD1`, `SP S3`, `ED ED-D2`). `decisions-needed.md` gives each open item one global id (`DN-SIM-01`, ...). In source lines, `ED` means either the page `entities-damage.md` or the research file of the same name (which the pages cite by section number, `ED §2.4`); `SP`, `MR`, `BEN`, `SIM` mean the pages.

---

## 2. Golden rules (never violate)

The 24 most load-bearing normative rules across all pages. Each is a summary; the rule ID is authoritative.

| # | Rule | ID | Page |
|---|---|---|---|
| G01 | One tick is one frame (1/60 s); all durations and timers are integer frames; no wall clock inside `step`. x grows right, y down, 1 cell = 1 px; reads outside the world return the indestructible `boundary` material and writes there are ignored. | SIM-R01, PROTO-R04 | [pixel-simulation.md](pixel-simulation.md), [benchmark.md](benchmark.md) |
| G02 | A cell is exactly 6 bytes (`mat:u16, life:u8, burn:u8, var:u8, flags:u8`); no velocity, temperature or wetness in the cell; `UPDATED` is transient and never hashed, `var` is hashed. | SIM-R03, SIM-R75 | [pixel-simulation.md](pixel-simulation.md) |
| G03 | Cell rules are integer-only: every float is converted once at load (x100; densities x10,000). Particle kinematics are Q16.16; entity and projectile `f32` may use only `+ - * / sqrt`, transcendental functions only via `libm` or tables. | SIM-R05, SIM-R71, DET-R06 | [pixel-simulation.md](pixel-simulation.md), [benchmark.md](benchmark.md) |
| G04 | Kind gates motion before density: only Air, Gas, Fire and Liquid cells are ever displaced; Static and Solid cells are never entered; equal density never swaps vertically; every swap conserves matter. | SIM-R30, MAT-R08 | [pixel-simulation.md](pixel-simulation.md), [materials-reactions.md](materials-reactions.md) |
| G05 | Terrain is `static` (cell_type liquid + sand + static); cell_type `solid` means Box2D rigid bodies, which are out of scope and map to Static in the MVP. | MAT-R03, SIM-R85 | [materials-reactions.md](materials-reactions.md), [pixel-simulation.md](pixel-simulation.md) |
| G06 | A skipped cell must be an exact no-op: dirty rects are dilated by `WAKE` = 12, unchanged-but-could-change cells call `keep_awake`, and results are identical with dirty rects on, off, and after a snapshot restore. | SIM-R11, SIM-R12, SIM-R72 | [pixel-simulation.md](pixel-simulation.md) |
| G07 | `UPDATED` gates visits only and is cleared at frame end; parity bits and generation stamps are forbidden (they break with dirty rects). | SIM-R15 | [pixel-simulation.md](pixel-simulation.md) |
| G08 | Four-pass checkerboard by chunk class with a pass order that is a pure function of the frame; `MAX_REACH` = 32 = CHUNK/2 keeps same-class windows disjoint (compile-time assert); rule authors stay within 16. | SIM-R21, SIM-R22, SIM-R23 | [pixel-simulation.md](pixel-simulation.md) |
| G09 | Cell randomness is a stateless hash of `(cell_seed, frame, pass, world cell index)`; no shared mutable RNG; no `HashMap`/`HashSet` iteration in `step`; task outputs merge serially in ascending chunk index. | SIM-R70, SIM-R74, DET-R05 | [pixel-simulation.md](pixel-simulation.md), [benchmark.md](benchmark.md) |
| G10 | The engine is bit-deterministic given `(engine_version, content_hash, task@version, seed, action_log)`, independent of thread count (1 and 8 threads give identical hashes). A change that alters a golden hash is at least a minor version bump; runs are comparable only at equal `content_hash`. | DET-R01, DET-R08, VER-R02, VER-R03 | [benchmark.md](benchmark.md) |
| G11 | Material ids are `u16`, ranked by `xml_order` with `air` = 0; the sim binds `air`, `fire`, `smoke`, `water` by name and aborts if absent; `materials.json` is already fully resolved, so loaders never re-apply defaults or inheritance. | MAT-R01, MAT-R02, MAT-R04 | [materials-reactions.md](materials-reactions.md) |
| G12 | Reaction outputs are positional (`output_a` replaces the cell matched to `input_a`); candidates for a pair are tried in file order and the first success wins; the roll is `below(10000) < round(p*100)`; loading fails on unknown ids or tags. | RXN-R02, RXN-R03, RXN-R05, RXN-R18 | [materials-reactions.md](materials-reactions.md) |
| G13 | No generic fire-to-fuel reaction exists: burning is an engine state with a strict `temperature_of_fire(source) > autoignition(target)` test; water does not clear BURNING. | FIRE-R01, FIRE-R03, FIRE-R08 | [materials-reactions.md](materials-reactions.md) |
| G14 | Explosions are rays that spend `ray_energy` on each cell's `hp`; a cell is removed only if `durability <= max_durability_to_destroy` (default 10); liquids in the hole are thrown as particles unless `hole_destroy_liquid`; cells removed per ray in a uniform material = `min(R, ceil(E/hp))`. | DUR-R01, DUR-R02, SIM-R50, SIM-R51, SIM-R52 | [materials-reactions.md](materials-reactions.md), [pixel-simulation.md](pixel-simulation.md) |
| G15 | Material contact damage belongs to the entity, applies per pixel per frame with a 4-cell floor and no type multipliers, and is raw internal x 25 for display. | HAZ-R01, HAZ-R03, DAMAGE-R11 | [materials-reactions.md](materials-reactions.md), [entities-damage.md](entities-damage.md) |
| G16 | Damage pipeline order: immunity gate first (any matching protection nullifies the whole hit), then hitbox and per-type multipliers, crit, global multipliers, HP subtraction. The player's explosion multiplier 0.35 and holy 1.5 are implemented as-is. | DAMAGE-R01, DAMAGE-R02, DAMAGE-R03, DAMAGE-R04, DAMAGE-R06 | [entities-damage.md](entities-damage.md) |
| G17 | Mana is checked per card at draw time (`cost > mana` skips; skipped cards are free and the same draw retries); only a spell's own draw on an empty deck wraps; the wand's Spells/Cast never wraps. | WAND-R20, WAND-R21, WAND-R22, WAND-R23 | [wand-casting.md](wand-casting.md) |
| G18 | Spells edit only the current shot state; a trigger payload is drawn and paid at cast time and starts from default values (wand stats never leak in); recharge, mana and recoil are global across shot states. | WAND-R30, WAND-R31, WAND-R32, WAND-R40, WAND-R41 | [wand-casting.md](wand-casting.md) |
| G19 | Cast delay and recharge clamp on the total (cast delay >= 1 frame, recharge >= 0), accumulate recharge deltas over the whole cycle, run concurrently (next click at `click_frame + max(cast_delay, recharge)`), at most one click per frame. | WAND-R52, WAND-R53, WAND-R54, WAND-R55 | [wand-casting.md](wand-casting.md) |
| G20 | Uses are consumed at end of click, and only if a projectile, static or material card was played or the card is OTHER/UTILITY; always-cast copies are free (unless negative cost), carry unlimited uses and are dropped, not discarded. | WAND-R63, WAND-R70, SPELL-R14 | [wand-casting.md](wand-casting.md), [spells.md](spells.md) |
| G21 | There is one global `dont_draw` flag (not a stack, reset unconditionally by every copy wrapper) and a recursion limit of 2 for copy spells. | WAND-R25, WAND-R80 | [wand-casting.md](wand-casting.md) |
| G22 | The spell catalogue is the 422 live spells keyed by `game_id`; game files win over the wiki; an absent XML attribute means the engine default, never 0; store frames, px/s and degrees; never load the 69 legacy rows. | SPELL-R01, SPELL-R02, SPELL-R04, SPELL-R05 | [spells.md](spells.md) |
| G23 | All gameplay randomness (spells, shuffle, worldgen, AI, spawns) comes from the seeded per-subsystem streams of `DET-R04`; never frame-number seeds, never the wall clock. | DET-R04, SPELL-R43, WAND S2 | [benchmark.md](benchmark.md), [spells.md](spells.md), [wand-casting.md](wand-casting.md) |
| G24 | Benchmark integrity: the score is in [0, 1] and cannot increase by dying or ending early; frame and decision caps are enforced engine-side; observations carry no privileged information; dev commands exist only with `--dev` and invalidate a run. | SCORE-R01, ANTI-R07, ANTI-R04, ANTI-R03 | [benchmark.md](benchmark.md) |
| G25 | Each chunk's terrain, spawns and hazards are fully determined by `(seed, chunk_x, chunk_y)` via per-chunk derivation from the episode seed; chunk generation is single-threaded and frame-independent, ensuring identical results across thread counts. | WORLD-R06 | [worldgen.md](worldgen.md) |
| G26 | The game loop runs at exactly 60 Hz with a fixed-timestep accumulator; the simulation advances only when `step()` is called; rendering is separate and never blocks the simulation; dropped video frames do not de-sync the engine. | FE-R01, PROTO-R04 | [frontend.md](frontend.md), [benchmark.md](benchmark.md) |

---

## 3. Page table

Data files live under `.trellis/tasks/10-16-noita-cogbench/research/` (shipped copies go to `crates/noita_core/data/`, see each page's Data files section).

| Page | What it covers | Read it when | Key data files |
|---|---|---|---|
| [v1-scope.md](v1-scope.md) | **Read first.** What the re-scoped v1 (task `10-16-noita-cogbench`) uses from this KB, its deliberate deviations from Noita, and which pages are superseded (benchmark RL parts, macroquad frontend, fBm worldgen). | any work on the v1 benchmark | task docs under `.trellis/tasks/10-16-noita-cogbench/` |
| [pixel-simulation.md](pixel-simulation.md) | Grid and 6-byte cell, 64x64 chunks, dirty rects, 4-pass parallel scheduler, per-kind motion rules (powder, liquid, gas, fire, static), timers, free-flight particles, explosion carving, grid queries for projectiles and entities, determinism contract, frame pipeline, budgets, deferred rigid bodies. Test vectors `SIM-T01..T36`. | touching `World`, `Cell`, `sim::*`, the cell RNG, any frame-by-frame grid test or performance work | `materials.json`, `reactions.json`, `tags_index.json`, `noita-engine-constants.json`, `pixel-sim-repos.json`, `rust-prior-art.md` |
| [materials-reactions.md](materials-reactions.md) | Material model (466 materials, kinds, tags, inheritance), reaction table semantics (positional outputs, probability, blobs, direction), fire and burning, durability and explosion rays, material contact damage, the MVP-40 materials and 39 reactions. Vectors `MV-01..MV-23`. | touching `materials`, `sim::rules::{fire,reactions}`, `sim::explode`, any test that cites a material number | `materials.json`, `reactions.json`, `tags_index.json`, `materials_from_wiki.json` (cross-check), `raw/materials_xml_parsed.json` |
| [wand-casting.md](wand-casting.md) | Wand stats, deck/hand/discard, draw, skip and wrap, shot states, multicast, triggers/timers/expiration, recharge and cast delay, mana and uses, always-cast, Divide/Greek/Add-Trigger/Refresh/Requirement, wand generation, reference pseudocode, verification of the 32 fixtures, vectors `KV-01..KV-15`. | writing casting code, casting tests, wand-building benchmark tasks, reviewing any change to draw order, mana, recharge or cast delay | `spells.json`, `wand-stats.json`, `wand-cast-test-cases.json`, `mvp50.json`, `spell_behaviors_from_gun_actions.json` (cross-check) |
| [spells.md](spells.md) | The 422-spell catalogue: field meanings and units, engine facts spells rely on, projectile runtime, explosion modifiers, the 7 behaviour primitives and D0/D1/D2 classes, MVP-50 behaviour table, data derivation vectors `TV-D`, shot-state vectors `TV-S`. | touching the spell loader, shot-state code, projectile or explosion code, any spell test | `spells.json`, `spell_taxonomy.json`, `mvp50.json`, `spell_actions_lua.json` (read-only reference), `validation_report.json` |
| [entities-damage.md](entities-damage.md) | Damage pipeline, crit, multipliers, status effects (fire, frozen, electrocution, stains, toxic, poison), knockback, player movement/levitation/kick numbers, the 8 MVP enemies, faction relations. | touching entities, enemy AI, damage or status code, HUD/player numbers, test-vector generation | `player-stats.json`, `enemies.json`, `damage-types.json`, `status-effects.json`, `factions-relations.json` |
| [benchmark.md](benchmark.md) | JSON-lines protocol and versioning, determinism and hashing, action and observation schemas (LLM and RL), scoring, seeds, anti-cheat, task data files, examples. | touching `noita_bench`, observation encoders, tasks, scoring, replay or the Python client | `benchmark-design.md` (research); at runtime: task JSON, `seeds/public-v1.json`, golden hashes |
| [worldgen.md](worldgen.md) | Seeded chunk-local world generation, biome strata, fBm caves and noise layers, Holy Mountain structure, spawn tables, benchmark arena, seed derivation. Vectors `WORLD-T01..T07`. | writing `noita_core::worldgen` or benchmark world setup | `materials.json`, `biome_layout_from_noitamap.json`, `biome_material_components.json`, `spawn_tables_from_lua.json`, `noita-engine-constants.json` |
| [frontend.md](frontend.md) | macroquad rendering, texture upload and zoom, input mapping, fixed timestep, HUD, wand editor UI, debug tools, workspace layout. Crate versions pinned as of 2026-10-07. | writing `noita_game` | `materials.json`, `spells.json`, `player-stats.json` |

---

## 4. Reading order per child task

Read each page's rules and Key numbers before its test vectors; implement the vectors as tests. The child PRDs predate this KB: where a PRD differs (parity bit, per-chunk RNG, "settle after N idle frames", `explode(radius, power)`, material names such as `dirt`, `gravel`, `obsidian`, wand-spell counts), the page wins; the differences are listed in `decisions-needed.md` section 8.

**`10-07-pixel-sim-core`**
1. This index, golden rules G01 to G15.
2. `pixel-simulation.md` in full (rules A to J, Key numbers, vectors `SIM-T01..T36`).
3. `materials-reactions.md`: MAT-R01..R16, RXN-R01..R18, FIRE-R01..R12, DUR-R01..R09, MVP-R01..R05, the MVP-40 and reaction tables, vectors `MV-01..MV-23`.
4. `benchmark.md`: DET-R01..R08, VER-R02/R03 (what must hash identically).
5. `spells.md`: SPELL-R05 and SPELL-R31..R35 (explosion config consumed by the explosion API).
6. `entities-damage.md`: DAMAGE-R11, DAMAGE-R21 (hand-off points only).
7. `decisions-needed.md` sections 1 and 2; `glossary.md`.

**`10-07-wand-spell-system`**
1. This index, golden rules G14 to G23.
2. `wand-casting.md` in full (rules, pseudocode, Key numbers, the fixture verification table before using `wand-cast-test-cases.json`, vectors `KV-01..KV-15`).
3. `spells.md`: SPELL-R01..R47, KN-1..KN-4, DF-1..DF-5, `TV-D`, `TV-S`, `TV-B`.
4. `entities-damage.md`: DAMAGE-R01..R21, status effects, enemy tables, data files.
5. `materials-reactions.md`: DUR-R01..R09, the explosion source table, HAZ-R01..R05; `pixel-simulation.md`: SIM-R45..R65 (particles, explosions, grid queries) and SIM-R80 (frame pipeline).
6. `benchmark.md`: DET-R04 (RNG streams), OBS-R05 (spell numbers shown to agents).
7. `decisions-needed.md` sections 3 to 5; `glossary.md`.

**`10-07-agent-benchmark`**
1. This index, golden rules G09, G10, G23, G24.
2. `benchmark.md` in full.
3. `pixel-simulation.md`: SIM-R70..R78 (determinism, hashed bytes, snapshot), SIM-R03 (flags channel), SIM-R14, SIM-R81 (throughput budget).
4. `wand-casting.md`: the per-wand state to hash (pseudocode header), WAND-R03/R04 (stats and capacity for `edit_wand` validation), WAND-R90..R95 only for generation tasks.
5. `spells.md`: SPELL-R03 (display units for observations), SPELL-R43, DF-2 (fields), S10 (runtime schema decision).
6. `entities-damage.md` Key numbers (HUD and player fields, levitation).
7. `worldgen.md`: WORLD-R06 (chunk-local determinism), WORLD-R10 (seed derivation), WORLD-R11..R12 (benchmark arena).
8. `decisions-needed.md` section 6; `glossary.md`.

**`10-07-playable-frontend`**
1. This index.
2. `frontend.md` (rendering, input, timestep, HUD, wand editor) and `worldgen.md` (world setup).
3. `frontend.md`: FE-R01..R14 (render loop, textures, input mapping, HUD, wand editor, performance).
4. `worldgen.md`: WORLD-R01..R05 (Noita facts), WORLD-R06/R10 (chunk determinism and seeds), WORLD-R11/R12 (benchmark arena).
5. `entities-damage.md`: Key numbers for movement, levitation, kick, hitbox and collision AABB, enemies, status effects.
6. `wand-casting.md`: WAND-R03/R04 and Key numbers (editor stats), WAND-R90..R95 (wand generation); `spells.md`: SPELL-R02/R03 (units shown in the editor), KN-2, DF-2.
7. `pixel-simulation.md`: SIM-R03 and SIM-R76 (`var` is cosmetic), SIM-R14 (active rect), SIM-R81 (60 Hz budget), SIM-R86 (hooks); `materials-reactions.md`: MAT-R15 (render colour versus `wang_color`).
8. `decisions-needed.md` sections 7; `glossary.md`.
All game logic stays in `noita_core`; the frontend consumes the same core API as the benchmark (parent PRD).

---

## 5. How to keep this KB correct

1. **One owner per fact.** Material and reaction numbers: materials-reactions.md. Cell layout, scheduling, motion, RNG, hashed bytes, budgets: pixel-simulation.md. Hash algorithm, protocol, seeds, scoring, versions: benchmark.md. Wand algorithm and generation: wand-casting.md. Spell fields, projectile runtime, MVP-50: spells.md. Damage, statuses, player and enemy numbers: entities-damage.md. When two pages disagree, the owner wins and the other page is fixed in the same change; record the ruling in the owner's "Source disagreements" table.
2. **When code deliberately diverges, update the page first.** Edit the rule text, keep its ID (never renumber or reuse an ID; mark a replaced rule "superseded by `X`" and add the new one), add the divergence to the page's "Our simplifications" table, and add or adjust the test vector. If the change alters a golden hash, bump versions per VER-R02.
3. **Record every choice you cannot settle.** A new `DECISION-NEEDED` goes into the page where it arises (with a stated default) and into `decisions-needed.md` with a `DN-` id. When the user decides, write "DECIDED (date): ..." in both places and keep the ID. A new `UNVERIFIED` fact that blocks a rule gets an open-question entry.
4. **Verify, then retag.** When an `UNVERIFIED` number is confirmed (observation, source file, in-game test), replace the tag with its source, remove the open question, and add a disagreement row if the ruling flips.
5. **Tests cite rule IDs.** Every normative rule has a vector or test; probabilistic ones are seeded frequency tests (10,000 trials, 4 sigma).
6. **Licensing.** Numbers and facts from Nolla's data files are fine; never paste Lua, XML or markup. Adapt code ideas only from MIT/Apache/BSD repositories recorded in `research/rust-prior-art.md`; clones with other licences are read-only references.
7. **Consistency pass after any edit batch.** Check that rule IDs are unique per prefix and every cited ID exists; that counts agree across pages (466 materials, 330 `xml_` reactions of which 39 run in the MVP, 79 tag keys, 422 spells, 32 casting fixtures, MVP-40 and MVP-50); that units follow section 1; that materials and spells are named by id; and that every page ends with `## Sources`.
8. **Task documents are not normative.** PRDs and `design.md` under `.trellis/tasks/` predate these pages; fix them or follow the page, and list leftover drift in `decisions-needed.md` section 8.

---

## Sources

KB pages: `./.trellis/spec/game-design/{pixel-simulation,materials-reactions,wand-casting,spells,entities-damage,benchmark,worldgen,frontend,glossary,decisions-needed}.md`.

Task documents: `./.trellis/tasks/archive/2026-10/10-07-noita-clone/{prd.md,design.md}` and the four child task PRDs `.trellis/tasks/archive/2026-10/10-07-{pixel-sim-core,wand-spell-system,agent-benchmark,playable-frontend}/prd.md`.

Research files (`./.trellis/tasks/10-16-noita-cogbench/research/`): `pixel-sim-tech.md`, `materials.md`, `materials.json`, `reactions.json`, `tags_index.json`, `spells.md`, `spells.json`, `spell_taxonomy.json`, `mvp50.json`, `wand-mechanics.md`, `wand-generation.md`, `wand-stats.json`, `wand-cast-test-cases.json`, `entities-damage.md`, `player-stats.json`, `enemies.json`, `damage-types.json`, `status-effects.json`, `factions-relations.json`, `benchmark-design.md`, `worldgen.md`, `frontend-tech.md`, `noita-engine-constants.json`, `rust-prior-art.md`, `pixel-sim-repos.json`.

Wiki: https://noita.wiki.gg/wiki/Documentation:_Reaction , /Modding:_Making_a_custom_material , /Documentation:_ConfigExplosion , /Expert_Guide:_Draw , /Wands , /Spells , /Materials .
