# Agent Benchmark: Noita Clone Contract

**Purpose:** This page defines the normative contract between the game engine and agent harnesses for deterministic, replayable benchmarking of LLM and RL agents. Implementers read this (not the research files) to understand versioning, observation/action schemas, scoring rules, seed derivation, and anti-cheat measures. Every rule here has a stable ID (e.g., `PROTO-R01`) that code and tests reference.

---

## Normative rules

### Protocol and versioning

- **PROTO-R01**: The engine speaks JSON Lines on stdin/stdout (one UTF-8 JSON object per `\n`-terminated line; no pretty printing; stderr for logs only). Requests echo their `id` in responses so clients detect desync.
- **PROTO-R02**: Versioned handshake via `hello`: engine returns `protocol_version` (semver), `engine_version`, `engine_git`, `content_hash` (blake3 of `materials.json`, `spells.json`, task generators), `suite_version`. Client refuses protocol major mismatch.
- **PROTO-R03**: A complete run is one `reset`, N `step` calls, optionally `observe` (re-render), and `close`. No out-of-order or interleaved episodes.
- **PROTO-R04**: All timestamps are frame counts at 60 Hz (0.01667 s/frame), never wall-clock time; moon-phase and time-of-day effects derive from seed.
- **PROTO-R05**: Binary payloads (uint8 grids) are base64-encoded with explicit `shape`/`dtype`/`codec` (optional zlib); never sent as JSON number lists.

### Determinism and state hashing

- **DET-R01**: The engine is bit-deterministic given `(engine_version, content_hash, task@version, seed, action_log)`. Stochastic wrappers (sticky actions, seed sampling) live in the Python client, not the engine.
- **DET-R02**: State hash (blake3 over canonical serialisation of frame, RNG states, cells, entities, player state, task state) is computed and returned with every `step` response. Per-chunk Merkle leaves scale cost to dirty chunks only.
- **DET-R03**: Full-grid hash is recomputed every 600 frames and at episode end. `episode_hash = blake3(concat(all step_hashes))` validates the entire trajectory.
- **DET-R04**: RNG uses seeded PCG/xoshiro with separate streams per subsystem derived as `stream_seed = blake3(seed ‖ "worldgen"|"cells"|"spells"|"ai"|"spawn")`. The `cells` stream is not consumed sequentially: cell-automaton randomness is a stateless hash of `(cell_seed, frame, pass, world cell index)` (pixel-simulation.md SIM-R70, decision SD1), so there are no per-chunk streams and neither dirty rects nor thread count can change a result. Adding an RNG call in one subsystem does not change output of others.
- **DET-R05**: No iteration over `HashMap`/`HashSet` in simulation; use `Vec`, `BTreeMap`, or `IndexMap` with explicit sort. Entity IDs are monotonic. Cross-chunk cell moves resolve in a deterministic commit phase (checkerboard order; realised by pixel-simulation.md SIM-R21/R22 disjoint windows and the serial merge of SIM-R74).
- **DET-R06**: Floating-point: integer/fixed-point for the cell automaton; `f32` allowed for projectiles/entities, but transcendental functions only via vendored `libm` or lookup tables (never std library `f32::sin/cos/exp/powf`); no `fast-math` or non-deterministic SIMD.
- **DET-R07**: Build targets are fixed (`target-cpu=generic` or explicit baseline to avoid platform drift). Cross-platform golden hashes (macOS arm64 vs Linux x86_64) are checked in CI.
- **DET-R08**: Thread-count independence: 1 vs 8 worker threads give identical state hashes (tested in CI).

### Action schema and frame advancement

- **ACT-R01**: Each `step` receives `frames` (1–600 frames to advance) and `actions` (either length 1, held for all frames, or length == `frames` for per-frame control). Invalid actions set `ok:false`, do not advance frames, and are echoed in the next observation's `events`.
- **ACT-R02**: Control state (held each frame): `move` (-1/0/1), `jump` (edge-triggered first true frame), `fly`, `aim` (degrees or dx/dy relative), `fire`, `kick`, `interact`, `down`. Aim quantisation (integer vs continuous) is logged in the run header.
- **ACT-R03**: One-shot actions (applied at step start, 0 frames): `swap_wand`, `edit_wand`, `drop_spell`, `pickup`, `wait`. `edit_wand` is allowed only per task's `wand_edit` policy (`anywhere` | `at_rest_zones` | `locked`); each edit counts toward `max_wand_edits`.
- **ACT-R04**: LLM text grammar compiles to control states; each decision is one line (`;`-separated macros). Total frames per decision capped by `max_frames_per_decision` (default 120) so no single decision skips an episode. Frame limit and decision limit are both enforced engine-side.
- **ACT-R05**: Invalid one-shots (e.g., `edit_wand` mid-cast, exceeding capacity, wand locked when not allowed) return `error` object with `code` and `msg`; the agent continues and the error counts as an invalid action.

### Observations (LLM mode)

- **OBS-R01**: Text observation includes: frame/time, HUD (hp, mana, position, velocity, depth, state flags), ASCII map with legend, entity list (sorted by distance, capped 16), wand inventory (active slot, recharge state, spells), task state (objective, progress, frames left, decisions left).
- **OBS-R02**: Map is a downsampled ASCII grid; each character covers `cell×cell` pixels (default `cell=4`), chosen by priority (player > entity > fire > liquid > powder > gas > static/solid terrain > air; kinds per pixel-simulation.md SIM-R04) then material majority. The `near` inset (optional, default off for navigation tasks, on for digging/aiming) renders 1 px/char for precision.
- **OBS-R03**: Legend is fixed per `content_hash` and versioned. Unknown / out-of-world cells are `?`. Entity list never hides portal/dummy/goal by design; may hide enemy names depending on task.
- **OBS-R04**: All coordinates are world pixels; y grows downward. `rel` = `pos − player_pos`, so "rel [48, −18]" means 48 px right, 18 px up. Geodesic distances (BFS over passable cells) are used for progress metrics, not Euclidean.
- **OBS-R05**: Spell stats in wands and spell pool are the wand-editor numbers (type, mana, cast_delay, recharge, damage, spread, uses), not hidden oracle values. No privileged information (reference DPS, hidden cells, enemy internals) leaves the engine in non-dev mode.
- **OBS-R06**: History (prior states) is the client's job; engine returns one observation per step plus last N events (default 32 events).

### Observations (RL mode)

- **OBS-R07**: RL mode returns three arrays: `grid` (uint8, 3×128×128 or custom size, base64 zlib-encoded): channel 0 = observation material index from the fixed legend (OBS-R03; `u8` holds at most 255 entries, 40 in the MVP set, while the simulation's own material id is `u16`, pixel-simulation.md SIM-R03), 1 = flags bitfield (pixel-simulation.md SIM-R03 proposes exposing only BURNING), 2 = entity class; `vec` (float32, 40+ elements): hp/hp_max, mana/mana_max, levitation, velocity/256, state flags, active wand stats (11 fields), task vector (goal rel x/y / 1024, progress, frames_left/limit); `spells` (uint16, 4×26): spell id per wand slot (0 = empty).
- **OBS-R08**: Window size, downsample factor and channel set are `reset.config.obs` parameters and recorded in the run header. Spaces are published via `info actions` so clients build corresponding `gymnasium.spaces` objects.
- **OBS-R09**: RGB (optional, `obs.rgb=true`): uint8, 64×64×3, nearest-filtered downsample of the map around the player.

### Scoring and success criteria

- **SCORE-R01**: Episode score ∈ [0, 1]; `success` is a boolean. Partial credit is monotone in progress and **cannot increase by dying or ending early**.
- **SCORE-R02**: `terminated` (MDP terminal: player died, objective met) is distinct from `truncated` (hit frame or decision limit). Both return the score at that point.
- **SCORE-R03**: Partial-credit formulas are maxima over the episode of a monotone progress metric. Dying yields the progress at death; no time bonus in the primary score.
- **SCORE-R04**: Each task defines a success threshold (e.g., "player touches portal alive") and a bounded formula (e.g., "distance traveled / total distance"). Reference baselines (random, no-op, heuristic hand-written, optional LLM/RL) are run per task version.
- **SCORE-R05**: Report success rate (fraction of seeds reaching success), mean score, and geometric mean `exp(mean(ln(1+100·success_rate))) − 1` across seeds so hard tasks matter. Efficiency metrics (frames_to_success / frame_limit, decisions, tokens, wall-clock, USD) are reported separately, never folded into the primary score.

### Seeds and reproducibility

- **SEED-R01**: Public seed indices 0–19 per task version; hidden indices 20–39 map through a maintainer-held salt. Derivation: `episode_seed = blake3(task_id ‖ task_version ‖ seed_index)`.
- **SEED-R02**: Raw `u64` seeds are accepted (`reset.seed = {"raw": 12345}`) for research; such runs are marked `seed_kind: "raw"` and are not leaderboard-eligible.
- **SEED-R03**: Public seeds are listed in `seeds/public-v1.json` and are reproducible across releases. Hidden seeds rotate with each suite version so published results stay reproducible within a version.

### Versioning

- **VER-R01**: Protocol: `protocol_version` semver; major bump = incompatible message change, minor = new optional fields, patch = docs. Client checks major compatibility.
- **VER-R02**: Engine: `engine_version` semver + `engine_git` commit. Any change that alters golden `state_hash` → **minor** bump minimum; pure perf/refactor with identical hashes → patch.
- **VER-R03**: Content: `content_hash` = blake3(`materials.json` + `spells.json` + task generators). Runs are only comparable at equal content hash.
- **VER-R04**: Tasks: `task_id@N` (e.g., `dig_to_depth@1`). Generator, loadout, limits, scoring, or observation-rendering change → new `@N`. Old versions stay runnable (frozen generator module) for ≥1 suite release, then deprecated with notice.
- **VER-R05**: Suite: `suite-vX` = pinned list of `task@N` + public/hidden seed lists + engine/content/protocol hashes. Each release: add tasks, rotate hidden salt, re-run baselines. Results tables are per suite version.
- **VER-R06**: Known issues are documented in `KNOWN_ISSUES.md` per task version (e.g., Procgen's `jumper` ~7% early-termination bug) instead of silently fixed within a version.

### Anti-cheat and validation

- **ANTI-R01**: Submission = action log (`run.jsonl`: header + requests + state hashes) + `metrics.json`. Validator replays on the reference engine build, compares hashes, recomputes scores; divergence invalidates the run.
- **ANTI-R02**: Official evaluation uses hidden seeds; each suite adds ≥1 new task (generator published only after the next release).
- **ANTI-R03**: Dev-mode commands (`save_state`, `load_state`, `debug *`) exist only with `--dev` flag. The header records `dev_mode: true`; validator rejects such runs. Engine refuses these commands otherwise (returns `DEV_ONLY` error).
- **ANTI-R04**: No privileged information in observations (e.g., `wand_dps_optimization` reference damage, hidden-cell contents, enemy internals). Privileged data stays in the harness, not the protocol.
- **ANTI-R05**: Assists (`walk_to`, `admissible_actions`, hints) and observation config (`mode`, `radius`, `max_frames_per_decision`, `frame_skip`) are run attributes in the header. Leaderboards are partitioned by `(obs.mode, assists, realtime)` so unassisted runs are never ranked against assisted ones.
- **ANTI-R06**: Task objectives are declarative ("reach the portal"); hints are an assist. Generators are reviewed for solution leakage in the prompt (SWE-bench+ found 32.67% of passing patches had leaked solutions) and for weak success checks (31.08% passed only with weak tests). Negative tests: scripted degenerate agents (die immediately, stand still, spam actions) must score ≤ documented floor.
- **ANTI-R07**: Frame/decision caps are enforced engine-side, including `max_frames_per_decision`, so a client cannot fast-forward past hazards.
- **ANTI-R08**: Reference evaluations run in a pinned Docker container (exact Rust toolchain, engine git hash). Results cached by `(engine_git, content_hash, task@version, seed, log_hash)`, never by user-supplied `run_id` alone.
- **ANTI-R09**: Minimum 10 seeds per task for leaderboard entry. Mean ± standard error published; BALROG found prompt variance exceeded ±1 SD even among optimised prompts.

### Real-time track (optional, v2)

- **REAL-R01**: `reset.config.realtime = {budget_ms: 500, on_timeout: "repeat"|"noop"}` enables wall-clock auto-advance. Engine advances `frame_skip` frames every `budget_ms` and auto-fills missing decisions. Timeouts become explicit `repeat`/`noop` entries in the log.
- **REAL-R02**: The simulation stays deterministic given the resulting action log; replays verify identically. Only the wall-clock-to-actions mapping is non-reproducible.

---

## Key numbers

| Constant | Value | Unit | Notes |
|---|---|---|---|
| Frame rate | 60 | Hz | 0.01667 s/frame; all timings in frame counts |
| World size (v1) | 512×512 | cells | Pixels; player spawned at task-defined position; the playable game world is 2048×1536 (pixel-simulation.md Key numbers) |
| Typical observation | ~2.5 | k tokens | LLM text mode; map 48×32 @ 4 px/char ≈ 1.5 K tokens |
| Decision latency | ≤120 | frames | Default `max_frames_per_decision` (hard cap to prevent skipping episodes) |
| Step latency | ≤600 | frames | Default `max_frames_per_step` |
| Hash recompute cadence | every step (per-chunk Merkle), every 600 frames (full grid) | frames | Full-grid hash at episode end |
| Grid observation window | 128×128 | pixels | 48×48 default in text (4 px/char downsample); RL 128×128 @ 1 px/cell (zlib 3 KB) |
| Inset (near) window | 1 | px/char | Precision digging/aiming; default off navigation, on dig/aim tasks |
| Entity cap | 16 | entities | Observation sorted by distance; portal/dummy/goal never hidden |
| Event history | 32 | events | Last N events per step; full history client-side (BALROG keeps 16 text turns) |
| Public seeds | 20 | seeds | Per task version; hidden 20 indices rotate per suite |
| Wand capacity | 3–8 | spell slots | Task-dependent; `edit_wand` counts toward `max_wand_edits` (default 5) |
| Levitation meter | 3.0 | seconds | `fly_time_max` = 180 frames of held flight, drains 1/s, refills 6/s on the ground (entities-damage.md Key numbers); shown to agents as a 0..1 fraction (OBS-R07) |
| Default RL frame_skip | 4 | frames | One decision per 4 frames; RL agent sees ~240 decisions per 1000-frame episode |
| Colour variant bitmask | 8 | bits | Per cell; indexed into palette (cave darkness, burning phases, etc.) |

---

## Data files

The following files are canonical and immutable per `content_hash`. Load order matters for initialization. All are JSON or JSON Lines.

| File | Path | Record count | Key fields | Load signature |
|---|---|---|---|---|
| Materials (elements) | `noita_core/data/materials.json` (+ `reactions.json`, `tags_index.json`) | 466 materials, 330 `xml_` reactions (39 executed in the MVP, materials-reactions.md MVP-R02) | resolved fields of `materials.json` (`id`, `kind`, `density`, `durability`, `hp`, fire and dispersion fields; materials-reactions.md Data files); reactions live in `reactions.json`, not inside the material rows | `Vec` indexed by numeric id = rank by `xml_order`, air = 0 (MAT-R01); the earlier draft schema (`state`, `flammability`, `temperature`, `interactions[]`, ~100 materials) is superseded |
| Spells (projectiles, modifiers, multicasts, ...) | `noita_core/data/spells.json` (generated from `research/spells.json` + `spell_taxonomy.json`) | 422 | key `game_id` (UPPER_SNAKE string, e.g. `LIGHT_BULLET`), `type` (8 values; triggers are a payload on a projectile, not a type), `mana_drain`, `max_uses`, `cast_delay_modifier`, `recharge_time_modifier`, `damage_modifier` (display units), `trigger`, `draw_count` (full field list spells.md DF-2) | `Vec<SpellRecord>` keyed by `game_id`; the earlier draft schema (`mana_cost`, `requires_spells[]`, `inherits_velocity`, ~300 spells) is superseded; remaining schema choices are spells.md S10 |
| Wand templates | `noita_core/data/wand_templates.json` | ~30 | `id`, `name`, then the stat names of wand-casting.md WAND-R03: `deck_capacity`, `mana_max`, `mana_charge_speed` (mana/s), `fire_rate_wait` (cast delay, frames), `reload_time` (recharge, frames), `spread_degrees`, `shuffle`, `actions_per_round` (Spells/Cast), `always_casts` (spell `game_id`s) | `Vec<WandTemplate>` indexed by `template_id` |
| Tasks (generators + configs) | `noita_core/data/tasks/` (one JSON per task) | 10+ | `id`, `version`, `family`, `description`, `frame_limit`, `decision_limit`, `public_seeds` (array of seed indices or seed values), `difficulty_knobs` (parametric ranges), `loadout`, `success_criterion`, `partial_credit_formula` | Load at `reset` given task name; freeze generator module per version (`tasks/dig_to_depth/v1.rs`) |
| Seed lists (public) | `noita_core/data/seeds/public-v1.json` | 200 (20 per task × 10 tasks) | `task_id`, `version`, `seed_index`, optional `seed_raw` (u64), `difficulty` (easy/medium/hard) | Client generates episode seed as `blake3(task_id ‖ version ‖ index)` |
| Golden hashes | `golden_hashes/<task@N>.json` | 1 per task version | `task_id`, `version`, `seed_index`, `expected_hashes: [{frame, hash}]`, `expected_score`, `expected_success` | CI compares run hashes; mismatch = regression |

Observation legend (character → entity/material name) is fixed per `content_hash` and returned in `reset.info` and `info legend`. Do not hardcode it; query at startup.

---

## Worked examples / test vectors

### Example 1: Determinism check (DET-R02, D2)

**Input:** Task `dig_to_depth@1`, seed 5 (public), depth=256 (easy), actions = dig straight down.

**Expected output:** Two identical runs should produce identical `state_hash` at every frame. Frame 100 hash should match across runs and between macOS arm64 and Linux x86_64 CI.

**Test:** `pytest test_determinism.py::test_replay_identical[dig_to_depth_v1_seed5]`

### Example 2: Partial credit is monotone (SCORE-R01, R03)

**Input:** Task `kill_targets@1`, N=3, seed 0, agent kills 1/3 dummies, then dies.

**Expected output:** Score = 1/3 (killed/N). If agent gets respawned (hypothetically) and kills 1 more, score still 2/3. Score never decreases on subsequent steps.

**Test:** Verify `score` in observation is non-decreasing frame-by-frame.

### Example 3: Invalid action is observed (ACT-R05)

**Input:** Task `reach_portal@1`, agent sends `edit_wand` while mid-cast (invalid per task policy).

**Expected output:** `step` returns `ok:false` (no frame advance), next observation includes event `{"type": "invalid_action", "msg": "edit_wand: wand is mid-cast"}`.

**Test:** `pytest test_actions.py::test_invalid_action_feedback`

### Example 4: Observation mode split (ANTI-R05)

**Input:** Two runs of `cross_lava_pool@1`, seed 3, one with `obs.mode="text"`, one with `obs.mode="grid"`.

**Expected output:** Both return the same `state_hash` and `score` (same engine state). Observation content differs; leaderboard rows are keyed by `(task, seed, obs.mode)` independently.

**Test:** Run both configs, verify hashes match in `metrics.json`, check leaderboard rows separate.

### Example 5: Replay and validate (ANTI-R01)

**Input:** A `run.jsonl` from a submitted agent (header + requests + hashes), `metrics.json`.

**Expected output:** `noita_bench verify run.jsonl` re-executes every request, compares all `state_hash` fields, recomputes `score`, writes `verify.json {verified: true, score_claimed: X, score_computed: X}`. Any divergence sets `verified: false`, logs `first_divergence: {frame, expected, got}`.

**Test:** Write a golden run for each task version; run `verify` and check `verified: true`.

---

## Pitfalls and common misreadings

1. **"Aim degrees are unsigned."** No: aim is signed, 0° = right, positive = counter-clockwise (up). -35° is down-right. Quantise to integers in text mode for action log compactness; round-trip to degrees for replay.

2. **"Spell ids are numeric."** No: spells are identified by string (e.g., `"DIGGER"`, `"LIGHT_BULLET"`). The engine maps to internal numeric IDs internally; logs always use strings. `spells.json` is the canonical reference.

3. **"More gold = higher score."** Depends on task: `dig_to_depth` scores on depth, not gold found (gold is visual loot, not an objective). Always read the `success_criterion` and `partial_credit_formula` for each task.

4. **"My agent died late, so it should score higher than one that died early."** Wrong if death was avoidable: all agents share the same stochastic seed, so both saw identical world state at spawn. The late agent likely explored more (good) or wasted time (neutral), but partial credit only rewards progress. Time-taken is an *efficiency metric*, not part of the score.

5. **"The map shows burning cells as 'f'."** Yes, but burning is a state flag, not a material. The underlying material is still recorded; 'f' is rendering priority (fire > liquid > solid). Water does not clear the flag (materials-reactions.md FIRE-R08; `[fire]+water` boils the water); burning ends by fuel exhaustion or loss of air, and the material stays until then.

6. **"Edit wand anywhere; the engine won't stop me."** Depends on `reset.config.wand_edit` policy. In `locked` mode, `edit_wand` is forbidden mid-episode and returns an error (ACT-R05). Task spec declares the policy; respect it in the run header.

7. **"I'll aim at the enemy by targeting their y-position directly."** Aiming is in degrees relative to the player, centered on the camera. Pass `aim: {deg: -20}` or `aim: {dx: 40, dy: -30}` (pixel offset). The rendering of "enemy at rel [100, 50]" tells you the pixel offset, but aim degrees are independent.

8. **"Invalid actions don't cost frames, so I can spam actions until one works."** True: an invalid action (e.g., edit when locked) returns immediately with an error, consuming 0 frames and 1 decision count. However, `decision_limit` is finite (typically 20–60 per episode), and spamming will exhaust it.

9. **"State hashing is expensive; skip it."** No: per-chunk Merkle leaves (DET-R02) make hashing cheap (sub-millisecond for a 512×512 grid). Full-grid hash every 600 frames + episode end gives regression-test coverage without overhead. Blake3 SIMD is faster than JSON serialisation.

10. **"I seeded the Python PRNG in my harness; the game is now reproducible."** Wrong: the *engine* state is deterministic (DET-R01) given `(seed, action_log)`. Your harness's randomness (seed sampling, sticky actions) is orthogonal and must be recorded in the run header if you want reproducibility. The engine log alone replays identically.

---

## Our simplifications (MVP)

These are deliberate scope constraints from the Noita full game. Implementers should note them; revisit in later suite versions based on agent performance.

| Simplification | Rationale | DECISION-NEEDED |
|---|---|---|
| World size 512×512 cells (vs 35,840 px wide in Noita and 2048×1536 for the clone's game world) | Determinism per-chunk hashing is O(dirty chunks), not O(world). 512×512 is tractable; larger requires more infrastructure investment. | If agents plateau, revisit ~1024² in v2 |
| Enemies do not mutate or give birth | Procedural entity counts and AI complexity adds RNG surface. Fixed spawn waves (task-driven) are simpler to validate. | v2 may add procedural spawns |
| No permadeath world corruption | Noita's perma-consequences (items destroyed, biomes scarred) are fascinating but non-deterministic in a 10-task suite. Task variants (hard/easy) replace it. | Out of scope for v1 |
| No NPC factions or karma system | Adds multiple observation streams and side quests. v1 focuses on core physics, spells and wand building. | Future expansion |
| Wand capacity 3–8 slots, vs Noita's generated 2–26 (absolute cap 62/66, wand-casting.md WAND-R93) | Simplifies the wand search space. Cap is task-dependent (`difficulty_knobs`). | May relax for `wand_dps_optimization` variants |
| Spell pool in `wand_dps_optimization` task is given | Agents don't need to find spells in the world; they search loadout space (combinatorics). | v2: world-exploration + spell-finding variant |
| No mod support (Noita has 2500+ mods) | Out of scope; focus on vanilla game mechanics. | Orthogonal; not planned |

---

## Open questions

1. **Aim quantisation in text mode:** Should text-mode aim be quantised to integer degrees (e.g., `aim -35` vs `aim -35.3`) to keep logs compact and align RL/LLM action spaces? Recommendation: integer degrees in text, optional 24-bin (15° steps) or continuous float in RL, both logged as `f32` degrees.

2. **Hash cadence:** Compute full-grid hash every step (current) vs every N frames (cheaper)? Per-chunk Merkle leaves make every-step cheap (<1% overhead). Recommendation: keep every-step for precise divergence detection.

3. **`near` inset default:** Should the 1 px/char inset be on by default in text mode? Costs ~400 tokens. Recommendation: on for digging/aiming (tasks 1, 4, 6, 8), off for navigation (7) to save tokens in observation.

4. **Shaped rewards in RL mode:** Task-specific shaping terms (e.g., "−0.01 per frame" penalty) help RL agents but are non-standard. Document per task version because they change learning curves but not simulation hashes. Reference: BALROG's `penalty_step` modes, NLE time penalties.

5. **Generalist vs specialist observation:** Should agents receive the same observation regardless of modality (text + grid), or task-optimised subsets (e.g., `kill_targets` hides entity interiors to force RL agents to use visual recognition)? Current design: identical engine state, task-independent rendering rules, optional modality-specific assists. Recommendation: lock modality, keep rendering fixed.

6. **Sticky actions for RL:** Should sticky actions (repeat prior action with p=0.25) be in the engine or client? Current: client, recorded in header. This lets RL users opt in. Recommendation: keep client-side.

7. **Task-specific instruction tuning:** Should agent prompts be task-specific ("You are standing in a cave; dig downward") or generic ("Reach the goal")? Current: generic objective + task-specific hints (assist). Recommendation: lock generic; optional hints are an assist track for fairness.

---

## Sources

Research deliverable: `./.trellis/tasks/10-16-noita-cogbench/research/benchmark-design.md`

Structured files synthesised from that research:
- `benchmark-survey.json` — survey table of 17 prior benchmarks (not present in `research/`; the content is in `benchmark-design.md`)
- `benchmark-protocol.json` — JSON Schema for JSONL protocol (not present in `research/`; see `benchmark-design.md`)
- `benchmark-tasks.json` — task suite v1 with generators and scoring (not present in `research/`; see `benchmark-design.md`)

Prior benchmarks cited (alphabetically, with key lessons):
- **BALROG** (2025): Text agents on multi-env; invalid-action feedback; harness-aware leaderboards
- **Crafter** (2021): Geometric-mean scoring; privileged-info mistake noted
- **Factorio Learning Environment** (2025): Error-as-observation; code-as-action; degenerate failure modes
- **Gymnasium Env API**: Standard reset/step/spaces contract
- **MineRL** (v0.4, 2021): Data drift risk (mirrors went offline 2024)
- **NetHack Learning Environment** (2020): Anti-TAS reseeding; moon-phase derivation from seed; permutation of RNGs (core vs display)
- **NeurIPS 2021 NetHack Challenge**: Optimised-for-score pitfall; per-instance organiser-controlled validation
- **Procgen** (2019): Level bugs documented (jumper 7%); generalisation protocol
- **SWE-bench** (2023): Cache-by-run-id pitfall; Verified subset analysis
- **SWE-bench+** (2024): Solution leakage (32.67%) and weak-test inflation (31.08%)
- **TextArena** (2025): Invalid moves penalised but continue; TrueSkill leaderboard; relative ranking avoids saturation
- **TextWorld** (2018): Free-text actions; admissible-command feedback
- **VideoGameBench** (2025): Real-time (Lite paused mode); raw pixels only (pixels-only limitation); checkpoint-based progress scoring
- **Lux AI Challenge S3** (2024): JSONL protocol; replay verification; stderr for logs
- **SmartPlay** (2023): Generic objective + manual; 9-capability taxonomy per game
- **PokéAgent Challenge** (NeurIPS 2025): Limited structured RAM reads (no puzzle state); anti-cheat (memory_reader.py DO NOT MODIFY); latency as first-class cost
- **Orak** (2025): MCP servers for game/agent modules; image-only causes drop; image+text hurts narrative games (−31.8 on Ace Attorney, GPT-4o) but helps action games (+16.6 Claude on Street Fighter III)

Domain expert experience from livestreamed LLM agents (Claude Plays Pokémon, Gemini Plays Pokémon): harness differences dominate (note-taking, navigation tools); prompt variance exceeds ±1 SD; invalid reasoning persists in notes without re-grounding.

Determinism lessons:
- **Age of Empires** (1997 GDC talk): "1500 archers on a 28.8" — lockstep replication, OOS checksums (AE "sync logs")
- **Atari 2600** (ALE revisited, 2018): Sticky actions as fix for memorisation, not non-deterministic emulator
- **Craftax** (2024): Pure JAX functions + explicit PRNG keys; 250× speedup over Crafter

All URLs fetched 2026-10-07; raw copies in `research/raw/` where noted.
