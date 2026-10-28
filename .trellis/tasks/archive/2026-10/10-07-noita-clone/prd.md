# Noita-like game: pixel physics sim, wand/spell system, agent benchmark

## Goal

Build a Noita-inspired 2D game in Rust whose two pillars are (1) a Noita-style
"falling everything" pixel-physics simulation and (2) a faithful wand/spell
casting system, and whose architecture makes the game usable as a **benchmark
for AI agents** (LLM agents and RL agents): headless, deterministic, scriptable,
with a task suite and scoring.

The game must also be playable by a human through a thin renderer.

## Decisions already taken (from the user's request)

- **Engine**: no Godot. Godot is not installed, a per-pixel simulation needs
  native code regardless, and a benchmark should run with a single
  `cargo run` and no editor binary. We use a **Rust workspace**:
  `noita_core` (engine-agnostic, headless), `noita_bench` (benchmark harness),
  `noita_game` (macroquad renderer). JS was considered and rejected for the core
  because the simulation must step ~10^5-10^6 cells per frame deterministically
  and headlessly; a WASM/JS or Godot front-end can be added later because the
  core has no rendering dependency.
- **Focus**: physical simulation and spells first. World generation, enemies
  and UI are built to the level needed to exercise those two systems and the
  benchmark.
- **Reference data**: the Noita wiki and game data files are the source of truth
  for spell, wand and material facts. Research is persisted under `research/`
  (provenance); the normative reference is the knowledge base (KB)
  `.trellis/spec/game-design/` (rule IDs such as `SIM-R22`, `WAND-R40`). Where a
  research file or this PRD disagrees with a KB page, the page wins.
- **No copying** of Noita's game code or assets. Numbers and names are
  facts; code and art are ours. Only MIT/Apache/BSD-licensed open-source code
  may be adapted (recorded per repo in `research/rust-prior-art.md`).
- **Process gate (supersedes the first-message "proceed autonomously")**: after
  research and design the plan is reported to the user, who reviews and may change
  game mechanics before any code is written. Implementation does not start until
  the user has reviewed `research/plan-summary.md` and settled or accepted the
  defaults of `.trellis/spec/game-design/decisions-needed.md`. After that gate,
  implementation proceeds autonomously per `implement.md`.

## Conventions every child follows

- Time is integer frames at 60 Hz; length is cell px (1 cell = 1 px, y grows down); speeds px/s in data;
  angles degrees. HP and damage are internal values in code and x25 only when displayed (player 4.0 = 100).
- Names: materials by lowercase `id` (e.g. `rock_static`, `soil`), spells by `game_id` (e.g. `LIGHT_BULLET`, `DIVIDE_2`).
- Every rule has a KB ID; tests cite it; KB vectors (`SIM-T`, `MV-`, `KV-`, `TV-`) are implemented as tests first.
- A new engine decision that is not yet in the KB goes into the KB page first (KB index §5), then into code.

## Requirements

### R1. Pixel physics simulation (child: `10-07-pixel-sim-core`)
- Chunked cell grid: 64x64 chunks, 32x32 storage tiles, one dirty rectangle per chunk (wake margin 12, keep-awake)
  so settled regions cost about nothing. A cell is 6 bytes: material id (u16), lifetime, fuel, colour variant, flags.
- Material kinds: static (terrain), powder, liquid, gas, fire, and air. Data-driven table loaded from generated runtime
  JSON: all 466 materials load, the 40 materials of MVP-40 are the enabled content (a superset of the original
  "at least 40 materials" requirement), 39 reactions are compiled.
- Rules: powders fall and slide; liquids fall, hop sideways and layer by density (oil floats on water, sand sinks);
  gases rise and dissipate by lifetime; burning is a per-cell state with fuel, flames and smoke; reactions are a pairwise
  table with probability (for example lava + water gives `rock_static` + steam; acid corrodes `[corrodible]` materials).
  **Water boils but does not put out burning materials**; fires end by fuel, loss of air or deletion.
- Explosions are rays that spend `ray_energy` on each cell's `hp`; a cell is removed only if its `durability` is within the
  source's limit; destroyed liquid is thrown out; fire appears with the source's probability. Digging depth therefore
  depends on material (a digger removes about 6 px of soil but 1 px of rock).
- Projectile and entity queries: ray masks, projectile sweep, AABB sweep.
- Deterministic: same seed and inputs give a bit-identical world after N frames, for any thread count, with dirty rects
  on or off and after a snapshot restore. Fixed 60 Hz timestep.
- Performance (two tiers, scenarios named in the pixel-sim-core PRD): a typical task scene (<= 10% active cells) on a
  512x512 world runs >= 5x faster than realtime (>= 300 frames/s, 3.33 ms per frame); a 1024x1024 world with a
  512x512 active rect around the player holds 60 Hz; the all-active worst case is measured and reported, not gated.

### R2. Wand and spell system (child: `10-07-wand-spell-system`)
- Wand stats as in Noita: shuffle, spells/cast, cast delay, recharge time, mana max, mana charge speed, capacity,
  spread, always-cast.
- Faithful deck/hand/discard casting engine (KB stage 1, `WAND-R01..R64, R70..R72, R80..R82, R86`): draw order, skip
  and wrap, multicast, modifiers on the current shot state, trigger/timer/expiration payloads **drawn and paid at cast
  time**, recharge and cast-delay accounting, mana per card, limited uses, shuffle, always-cast, Divide, Add-Trigger,
  Wand Refresh. Greek letters, Duplication, Requirement and Zeta are stage 2.
- Spell catalogue from the generated runtime `spells.json`: all 422 spells parse and validate; behaviour is implemented
  in a ladder (MVP-50, then all 127 data-only spells, then data+feature spells by feature, then about 60 spell-specific
  ones). A per-spell `implemented` set is part of `content_hash`; task pools and `edit_wand` accept implemented spells
  only.
- Projectile entities (speed, gravity, friction, lifetime, bounce, penetration, trails, explosion on hit, trigger
  payload release) acting on cells and entities. Bomb and Dynamite are ballistic projectiles with a fuse, not rigid bodies.
- Entity layer: player, target dummy (4.0 internal HP = 100 shown) and at least 3 simple enemies from `enemies.json`;
  damage pipeline and the minimal status set of the KB; material contact damage belongs to the entity.
- Events per frame (projectile spawned, hit, explosion, entity damaged or died, material converted) for the frontend and
  the benchmark. `Game` facade with `step(&Input)` where `Input` = held `ControlState` plus one-shot actions.

### R3. Agent benchmark harness (child: `10-07-agent-benchmark`)
- Headless `noita_bench` speaking JSON Lines: `hello`, `list_tasks`, `info`, `reset`, `step`, `observe`, `metrics`,
  `replay`, `close` (dev-only `save_state`, `load_state`, `debug`); a `verify` subcommand; thin stdlib Python client.
- Observation modes: LLM text (priority-down-sampled ASCII map with legend, entities, HUD, wands, spell pool with
  wand-editor numbers, last events, task progress) and RL (base64 arrays; `u8` observation-class grid, vector, spell ids).
- Action schema: held control state (`move, jump, fly, aim, fire, kick, ...`) plus one-shots (`swap_wand, edit_wand,
  wait, ...`), frame and decision limits enforced engine-side, wand-edit policy and budget, helpful validation errors.
- Task suite v1 (frozen list of 8, plus 2 stretch): `dig_to_depth`, `cross_lava_pool`, `extinguish_fire`, `kill_targets`,
  `survive_N_seconds`, `wand_dps_optimization`, `reach_portal`, `chain_reaction`. Each task declares world size,
  loadout, limits, a monotone score in [0, 1] that cannot rise by dying, and a plain-English objective; geometry is
  validated by a scripted baseline before a task version is frozen.
- Determinism, per-step state hashes, replay verification with first-divergence report, seeds derived from
  `blake3(task_id || version || index)`, versions for protocol, engine, content, task and suite.

### R4. Playable frontend (child: `10-07-playable-frontend`)
- macroquad window rendering the camera region directly from `World` with nearest filtering and integer zoom
  (2x-4x); the camera follows the player smoothly.
- Player: move, jump, levitate (3.0 s meter that refills on the ground), mouse aim, LMB cast, kick, take damage from
  projectiles, fire, acid and lava, die and restart. (Vanilla has no fall damage; none is required.)
- Seeded world generation in `noita_core::worldgen` (global seed, integer value-noise caves, strata, liquid pools,
  veins, rest rooms, portal, spawn points) from the approved material set; also provides benchmark arenas.
- HUD, wand inventory and a wand editor (click-pick and click-place spells, per-spell and per-wand stats).
- Debug tools: material brush, spawn dummy or enemy, pause and single-step, dirty-rect and chunk overlays, frame time.
- Starting kit: two wands (spark bolt, digging) and a small spell inventory.

## Cross-child acceptance criteria (parent owns)

- [ ] `cargo build --release --workspace` succeeds on macOS arm64; `cargo test --workspace` and
      `cargo clippy --workspace --all-targets -- -D warnings` pass.
- [ ] Determinism: two headless runs with the same seed and action log give identical state hashes after 3,000
      frames; thread counts 1, 2, 3, 8 and 16 give the same hash; dirty rects on versus all-dirty, a snapshot restored
      at frame k, and a random-soup fuzz all agree (`SIM-T31..T35`).
- [ ] Performance gates as in R1 (typical task scene >= 300 frames/s end to end through `noita_bench` with frame skip
      4); ns per active cell recorded for every named scenario in the criterion benches.
- [ ] `noita_bench` runs every suite task end to end from the Python client with scripted agents (random, no-op,
      heuristic) and emits a score; `noita_bench verify` accepts a recorded run and rejects a tampered one.
- [ ] `noita_game` launches; the player can dig with a digging-bolt wand (removes cells up to its durability limit,
      deep in soil and 1 px per ray in rock), pour water on lava to make `rock_static` and steam, set oil on fire
      (water boils but does not douse it), and build a multicast + trigger combo (for example `BURST_2`,
      `LIGHT_BULLET_TRIGGER`, `FIREBALL`) in the editor and see the payload released on hit.
- [ ] Integration review: the frontend and the benchmark use the same core API (no duplicated game logic).
- [ ] KB integrity: the consistency pass of KB index §5.7 passes; `worldgen.md` and `frontend.md` exist; Rust crate
      specs exist under `.trellis/spec/rust-core/`; no test cites a rule ID that does not exist.

## Child task map and ordering

| Order | Child | Depends on |
|---|---|---|
| 0 | Phase 0 (parent): KB pages `worldgen.md` and `frontend.md`, runtime data generator, curated context manifests, fixed casting fixtures | research, decisions of the plan review |
| 1 | `10-07-pixel-sim-core` | phase 0 (also creates the cargo workspace) |
| 2 | `10-07-wand-spell-system` | grid, queries and explosions from (1); the pure casting engine can start in parallel with (1) |
| 3 | `10-07-agent-benchmark` | (1), (2) |
| 3 | `10-07-playable-frontend` | slice A (viewer, brush, overlays) needs only (1); slice B (controller, editor, worldgen) needs (2); runs in parallel with the benchmark |

## Non-goals (MVP)

- Rigid-body pixel objects (Box2D-style marching squares): the 132 Solid materials map to Static; Bomb and Dynamite are ballistic;
  hooks are kept.
- Full Noita biome set, perks, shops, bosses, audio, save/load, modding, multiplayer, streaming worlds, stain physics,
  wand generation tables beyond what tasks need.
- Spells that need entity scripts (143 of the 422), summoned creatures (15) or the note easter egg (13) in the first releases.
- Pixel-exact replication of Noita's art; ours is procedural palettes.

## Open decisions (defaults assumed; the user settles them in the plan review)

Mechanics decisions with a recommended default are listed with options and benchmark consequences in
`research/plan-summary.md`; global ids are in `.trellis/spec/game-design/decisions-needed.md`. The ones that change what
a task or spell does: rigid bodies (`DN-SPELL-03`), fire extinguishing semantics (`FIRE-R08`), explosion model (`DN-SPELL-04`,
`DN-MAT-07`), thrown matter (`DN-SIM-10`), material and spell scope (`DN-MAT-01`, `DN-MAT-02`, `DN-SPELL-01`), wand rules
(`DN-WAND-01..04`), piercing (`DN-ENT-02`), damage units and statuses (`DN-SPELL-02`, `DN-ENT-01`, `DN-ENT-05`), numeric type
and aim (`DN-SIM-13`, `DN-BEN-01`), world size (`DN-WORLD-04`, `DN-BEN-08`).

## Notes

- Research lives in `research/` of this parent task; children reference it via their `implement.jsonl` manifests, which
  are curated in phase 0 (they still hold the template placeholder).
- Review of this plan against the research: `research/design-review.md`; changes applied: `design.md` revision log.
