# Agent benchmark harness

Parent: `.trellis/tasks/10-07-noita-clone` (read its `prd.md`, `design.md` sections 4 and 6 first). Depends on `10-07-pixel-sim-core` and
`10-07-wand-spell-system` (the `Game` facade). Revised 2026-10-07 against `research/design-review.md`; where this PRD and the KB disagree,
the KB page wins.

**Read first (KB index §4):** `index.md` (golden rules G09, G10, G23, G24); `benchmark.md` in full (PROTO, DET, ACT, OBS, SCORE, SEED, VER, ANTI,
Key numbers, examples); `pixel-simulation.md` SIM-R70..R78, SIM-R03, SIM-R14, SIM-R81; `wand-casting.md` WAND-R03/R04 (stats for `edit_wand`
validation); `spells.md` SPELL-R03, SPELL-R43, DF-2, S10; `entities-damage.md` Key numbers (HUD, player, levitation); `decisions-needed.md` section 6;
`research/benchmark-design.md` sections 2-6 as provenance. `worldgen.md` does not exist yet: write it (phase M0) before the task generators.

## Goal

Make the game a reproducible benchmark for AI agents: a headless binary with a JSON-lines protocol, a Python client, observation encoders for LLM
and RL agents, a versioned task suite with scoring, and replay verification. Milestone M5 of `implement.md`.

## Requirements

### Protocol (PROTO-R01..R05, ANTI-R03, ANTI-R07)
- `crates/noita_bench` reads one JSON request per line on stdin and writes one JSON response per line on stdout (stderr for logs); every response echoes the
  request `id`. Requests: `hello` (protocol_version, engine_version, engine_git, content_hash, suite_version, dev_mode, capabilities), `list_tasks`,
  `info{what: materials|spells|actions|legend|task}`, `reset{seed, task, config}`, `step{frames, actions, oneshot}`, `observe`, `metrics`, `replay`, `close`.
  `save_state`, `load_state` and `debug` exist only with `--dev`, otherwise `DEV_ONLY`; a dev run records `dev_mode: true` and is not valid.
- Errors are responses, never crashes: `{ok:false, error:{code, msg, hint}}` with codes `INVALID_ACTION, BAD_TASK, EPISODE_OVER, DEV_ONLY, PROTOCOL, LIMIT`.
- `noita_bench verify run.jsonl` re-executes a recorded run, compares every per-step `state_hash`, recomputes the score and reports `first_divergence`.
- Binary arrays are base64 with explicit `shape`, `dtype`, `codec`; never JSON number lists.

### Determinism, seeds, versions (DET-R01..R08, SEED-R01..R03, VER-R01..R06)
- The engine is bit-deterministic given `(engine_version, content_hash, task@version, seed, action_log)`; sticky actions and seed sampling live in the
  Python client and are recorded in the run header (default pending user decision DN-BEN-06).
- A `state_hash` (blake3, per-chunk Merkle leaves; default pending DN-BEN-02) is returned with every `step`; `episode_hash = blake3(concat(step hashes))`;
  a full-grid hash every 600 frames and at episode end. Golden hashes per `task@N` live in `golden_hashes/`; a changed golden hash needs an engine minor bump.
- `episode_seed = blake3(task_id || task_version || seed_index)`; public indices 0-19, hidden 20-39 through a maintainer salt (can wait), raw `u64` seeds marked
  `seed_kind: "raw"` and not leaderboard-eligible. `replay` and the run header also record obs mode, assists, `wand_edit` policy and frame skip.

### Actions (ACT-R01..R05)
- `step.frames` is 1-600; `actions` has length 1 (held) or `frames` (per frame). Held control state: `move` (-1/0/1), `jump` (edge-triggered), `fly`, `aim`
  (signed degrees, 0 = right, counter-clockwise positive; `{deg}`, `{dx,dy}`), `fire` (not `cast`), `kick`, `interact`, `down`. One-shots: `swap_wand`,
  `edit_wand{wand, spells[...]}` (whole wand), `drop_spell`, `pickup`, `wait`. Aim is integer degrees in text mode and the choice is logged in the header
  (default pending DN-BEN-01); sin/cos via `libm` or a table.
- `max_frames_per_decision` (default 120) and `decision_limit` are enforced engine-side; `wait` is capped by the same limit. An invalid action returns
  `ok:false`, advances no frame, counts as a decision and is echoed in the next observation's `events`. `edit_wand` follows the task's `wand_edit` policy
  (`anywhere | at_rest_zones | locked`) and `max_wand_edits` (default 5), is refused mid-cast, and accepts implemented spells only.

### Observations in `noita_core::obs` (reused by the frontend; OBS-R01..R09)
- `llm`: HUD (hp, mana, levitation fraction, position, velocity, depth, state flags), priority-down-sampled ASCII map (default 4 px/char; `near` 1 px/char inset on for
  digging and aiming tasks, default pending DN-BEN-03), fixed legend per `content_hash` (unknown = `?`), entities sorted by distance and capped at 16 (goal/portal/dummy never
  hidden), wands with editor numbers (display units), spell pool, last 32 events, task progress, frames and decisions left. About 1.5-2.5k tokens.
- `rl`: `grid` `uint8` (3 x 128 x 128: **observation class** from a fixed legend of at most 254 entries, flags with BURNING only, entity class), `vec` `float32` (40 or more),
  `spells` `uint16`; window, downsample and channels are `reset.config.obs` and published by `info actions` (default pending DN-BEN-10 for the `u8` class).
- No privileged information: no reference DPS, hidden cells or enemy internals outside `--dev` (OBS-R05, ANTI-R04). Features smaller than 8 px (thin rock, a Digging Bolt crater)
  are only reachable through the `near` inset in tasks that need them.

### Tasks and scoring (SCORE-R01..R05)
- `noita_core::tasks::Task` is **stateful**: `setup(seed) -> Game`, `limits() -> {frame, decision}`, `wand_edit_policy`, `on_step(&Game, &[Event])`, `score()`; the score is a running
  maximum of a monotone progress metric in [0, 1], cannot rise by dying or ending early, no time bonus; `terminated` (death, goal) is distinct from `truncated` (frame or decision limit).
- Suite v1, frozen list (DN-DRIFT-09): `dig_to_depth`, `cross_lava_pool`, `extinguish_fire`, `kill_targets`, `survive_N_seconds`, `wand_dps_optimization`, `reach_portal`,
  `chain_reaction`; stretch `lava_crust_bridge`, `collect_gold`. Generators are frozen per `task@N`.
- Each task declares its own world dimensions (width 512; height per task; `dig_to_depth` D = 1024 needs about 1,152 px or an active window), loadout, limits, success predicate,
  partial credit and a plain-English objective. Geometry is computed from vanilla kinematics (levitation 180 frames and 52 px/s horizontal give about 156 px of flight; `cross_lava_pool`
  widths are set accordingly; lava deals 4.5 HP/s per overlapping pixel) and validated by the scripted baselines before the version is frozen.
- `extinguish_fire`: success is zero burning cells for 120 consecutive frames with bounded wood loss. Water boils but does not douse burning materials (FIRE-R08), so the generator
  and baseline must show a solution (flooding, air starvation, removing fuel); the objective names the goal, not the method.
- `wand_dps_optimization`: the reference damage per seed comes from an offline cast-only evaluator (exhaustive for P <= 8 and capacity <= 6, else a fixed search budget), stored with
  the seed and never exposed; the score uses the best trial; pools contain implemented spells only.
- Scripted baselines per task: random, no-op, a heuristic that reaches success on the fixed tier; degenerate agents (die at once, stand still, spam) score at most the documented floor (ANTI-R06).

### Python client and files
- `bench/noita_bench.py` (stdlib only): spawn the binary, `hello` version check, `reset/step/observe`, context manager, `run.jsonl` header and `metrics.json` from the first version.
  `bench/run_scripted.py` runs every task with the scripted agents; `bench/README.md` documents protocol and schemas. A Gymnasium adapter is optional and outside the core.

## Acceptance Criteria

- [ ] `cargo run -p noita_bench --release` answers `hello` and `list_tasks` with versions and the task list; invalid JSON, an unknown request, a bad task and a dev command without
      `--dev` each yield an error response with the right code and the process keeps running.
- [ ] `python3 bench/run_scripted.py` completes every task of suite v1 and prints scores; exit code 0; the heuristic reaches success on each fixed tier and degenerate agents stay at or
      below their documented floor; the score is non-decreasing frame by frame in every run.
- [ ] Replay: a recorded `run.jsonl` verifies (`verified: true`, same score); a tampered trajectory reports `first_divergence`; golden hashes exist for every `task@1`.
- [ ] Limits: an invalid action advances no frame and appears in the next events; `max_frames_per_decision`, `decision_limit` and the frame limit are enforced engine-side
      (a client cannot skip an episode with `wait`).
- [ ] Throughput, gate: >= 300 frames per second end to end through `noita_bench` with frame skip 4 on a 512x512 typical task scene (<= 10% active cells), release mode; the
      all-active worst case is reported, not gated; `info` or a test reports the measured figure.
- [ ] Observation encoders have unit tests: legend consistency per `content_hash`, map size, priority down-sampling, entity cap and ordering, goal never hidden, base64 shape/dtype/codec,
      `u8` class table within 254, JSON schema stability, and no privileged field in non-dev mode.
- [ ] Task validity: every task's geometry passes a solvability check (ray or BFS test) in its generator; `wand_dps_optimization` reference values are stored and never appear in any response.
