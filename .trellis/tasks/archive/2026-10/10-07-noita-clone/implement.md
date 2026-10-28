# Execution plan — NoitaClone (parent)

The parent owns ordering, integration review and the knowledge base (KB, `.trellis/spec/game-design/`). Each child writes
its own `design.md` and `implement.md` when it starts, against `design.md` here and the reading order of KB `index.md` §4.
Revised 2026-10-07 against `research/design-review.md`; the milestone names (M0-M7) are the ones used in
`research/plan-summary.md`.

## Working rules
- **Gate:** no implementation (`task.py start`, code) until the user has reviewed `research/plan-summary.md` and settled
  or accepted the defaults of `decisions-needed.md`. Record each answer as "DECIDED (date): ..." in the KB page and in
  `decisions-needed.md` (KB index §5.3). Everything below M0 assumes the stated defaults.
- **Test first, KB first:** the KB vectors are the tests (`SIM-T01..T36`, `MV-01..MV-23`, `KV-01..KV-15`, `TV-D/S/B`); write
  the test, see it fail, then implement. Every test cites a rule ID. If code must diverge from a rule, edit the KB page first
  (new rule ID, simplification row, vector) and bump versions per VER-R02 when a golden hash changes.
- **Measure before optimising:** criterion benches for the named scenarios (SIM-R82) exist before any optimisation; ns per
  active cell is recorded in the task notes. Every performance figure in the research is UNVERIFIED until then.
- **Cheapest adequate model** for every sub-agent (Haiku for extraction and summaries, Sonnet where core-system
  correctness needs it); parallel sub-agents for independent work.
- Licensing: facts and numbers from Nolla data are fine; never paste Lua, XML or markup; adapt code only from the permissive
  repositories in `research/rust-prior-art.md` (KB index §5.6).

## M0 — Foundations (parent; no gameplay code)
- [x] Research fan-out persisted in `research/`.
- [x] KB consolidated: six content pages, `glossary.md`, `decisions-needed.md`, `index.md` (2026-10-07).
- [x] Design review (`research/design-review.md`) and planning documents revised (`design.md` revision log).
- [ ] **User plan review** (gate above): answer or accept the mechanics decisions of `plan-summary.md`.
- [ ] Write KB pages `worldgen.md` and `frontend.md` (merge their decisions into `decisions-needed.md`, terms into `glossary.md`,
      rows into `index.md`; re-run the consistency pass of index §5.7).
- [ ] Write `.trellis/spec/rust-core/` (determinism rules, module layout, testing, data assets, clippy `disallowed_methods`).
- [ ] Curate `implement.jsonl` and `check.jsonl` for the parent and every child (spec and research files only; they still hold
      the template placeholder).
- [ ] Produce the corrected casting fixtures from `wand-cast-test-cases.json` (draw_01 mana 15, greek_01 delay 114, refresh_03
      replaced by KV-01; stage-2 cases split out) and the stage-1 vector list (WAND S4).
- [ ] Each child writes `design.md` (module layout, test list) before coding.

## M1 — Falling sand core (child `10-07-pixel-sim-core`, part A)
- [ ] Cargo workspace, pinned toolchain, release profile, clippy lints; `scripts/build_runtime_data.py` and the loader with the
      load-time asserts (466 materials / 330 reactions / 79 tags; kind counts); `content_hash`.
- [ ] `Cell` (6 B), `Tile`, `World`, rule API, `UPDATED`, dirty rects with `WAKE = 12`, keep-awake, task-local write boxes and
      serial merge, 4-pass rotated scheduler, stateless cell hash, `MAX_REACH` assert (SIM-R03, R10..R15, R20..R26, R70).
- [ ] `MotionParams` and the powder, liquid, gas rules (SIM-R31..R34); vectors `SIM-T01..T23` and the loader vector `SIM-T25`.
- [ ] State hash (blake3, per-chunk leaves), snapshot/restore; determinism suite `SIM-T31..T35` (threads 1/2/3/8/16, pass-order
      permutation, dirty on vs all-dirty, snapshot at frame k, random soup).
- [ ] Criterion benches: empty, sand rain, water pour; `examples/sandbox.rs` writing a PPM. Decide here whether the tile
      indirection costs > 10% (flat-array fallback, SIM-R24).
- Exit: determinism suite green on macOS arm64; ns per active cell recorded; a PPM of sand and water looks right.

## M2 — Chemistry, fire, explosions (child `10-07-pixel-sim-core`, part B)
- [ ] Timers with `life_unit`/`burn_unit` (SIM-R35; `SIM-T24`, `SIM-T36`); reaction compiler (tags, candidate slices, suffix forms) and the 39 MVP
      reactions (RXN-R02..R08, MVP-R02); vectors `MV-05..MV-12`, `MV-22`, `MV-23`.
- [ ] Burning state, Fire-kind cells, ignition, fuel, oxygen, lava (SIM-R36, R37; FIRE-R01..R09); vectors `MV-19..MV-21`.
- [ ] Explosion ray model, queue and caps, spiral stop-gap for thrown liquid, histogram and entity list (SIM-R50..R54; DUR-R01..R03;
      vectors `MV-13..MV-17`, `SIM-T26..T28`); particle phase only if decided (SIM-R45..R47, `SIM-T29`).
- [ ] Queries: `blocked(mask)`, four ray presets, projectile sweep, normal, AABB sweep (SIM-R60..R65; `SIM-T30`).
- [ ] Remaining benches (lava+water, burning oil lake, explosions R30 and R250, all-active soup, threads, dirty on/off); the
      "settled" definition test (no gas, fire, exposed ice/whiskey/cement; P1).
- Exit: pixel-sim-core acceptance criteria; frontend slice A may start.

## M3 — Wand and spell core, headless (child `10-07-wand-spell-system`, part A; may start during M1)
- [ ] Spell loader: 422 rows parse and validate, damage units converted once (SPELL-R03), `implemented` bits hashed.
- [ ] Pure casting engine, stage 1 (WAND-R01..R64, R70..R72, R80..R82, R86) with `CastContext`, `CastOutcome` and `ShotTree`;
      vectors `KV-01..KV-15`, `TV-S1..TV-S18`, `TV-D1..TV-D7`, `TV-B` and the corrected fixtures.
- [ ] MVP-50 spell rows and handlers (35 D0, 6 D1, 9 D2) at the data and cast level; fuzz: cast every implemented spell once.
- Exit: casting tests pass with no `World` import; stage-2 spells explicitly absent from pools.

## M4 — Spells in the world (child `10-07-wand-spell-system`, part B; needs M2)
- [ ] Entities and ids; damage pipeline, statuses (minimal set), contact damage, player controller constants, dummy, 3 enemies
      (DAMAGE-R01..R20, HAZ-R01..R03).
- [ ] Projectile runtime (`ProjectileSpec`, sweeps, swept entity hits, hit list, triggers/timers/death release, trails, material
      spells), ballistic Bomb and Dynamite, explosions with entity effects.
- [ ] `Game` facade: `step(&Input)` in the SIM-R80 order, events, snapshot, state hash incl. wands and entities.
- [ ] Integration tests of the child PRD (spark bolt damages a dummy, bomb carves rock but not `steel_static`, digging bolt depth by
      material, water + lava gives `rock_static` and steam, fire trail ignites oil, black hole, trigger payload at hit).
- Exit: wand-spell-system acceptance criteria; same seed and `Input` log give the same `Game` hash.

## M5 — Benchmark v1 (child `10-07-agent-benchmark`; needs M3 and M4; parallel with M6)
- [ ] `noita_bench`: handshake, `reset/step/observe/replay/close`, error codes, `--dev`, limits enforced engine-side, per-step hash;
      Python client, run header, `metrics.json`, `verify` with first divergence.
- [ ] Observation encoders (LLM text, RL arrays with `u8` obs class); stateful `Task` trait; world size per task.
- [ ] First three tasks end to end: `dig_to_depth`, `kill_targets`, `wand_dps_optimization` (with the world-free evaluator); golden hashes.
- [ ] Remaining five tasks; scripted baselines (random, no-op, heuristic) validate that each task is solvable and that dying early
      scores at most the documented floor; freeze `task@1` and `suite-v1`.
- Exit: `python3 bench/run_scripted.py` completes every task; `verify` accepts and rejects correctly; throughput gate met.

## M6 — Playable game (child `10-07-playable-frontend`; slice A after M2, slice B after M4)
- [ ] Slice A: macroquad viewer, texture upload, zoom, camera, material brush, pause/single-step, dirty-rect and chunk overlays.
- [ ] Slice B: world generation (integer noise, authored arenas), player controller, HUD, enemies, starting kit, hand-rolled wand
      editor, die and restart.
- Exit: human smoke test of the cross-child criteria; frame time < 16 ms with heavy liquid flow inside the active rect.

## M7 — Integration and hardening (parent)
- [ ] `cargo build --release --workspace && cargo test --workspace` clean; determinism across threads, dirty-rect modes and replay.
- [ ] Scripted agent runs all tasks; human smoke test of the game window.
- [ ] Adversarial review workflow over the whole codebase; fix findings.
- [ ] KB retro: retag every UNVERIFIED number that was measured, record ns per active cell, update simplification tables;
      spec update (Trellis step 3.3), git init and commits (3.4), journal entry.

## Validation commands
```bash
cargo build --release --workspace
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo bench -p noita_core --bench step -- --quick
python3 bench/run_scripted.py
cargo run -p noita_core --example sandbox --release
cargo run -p noita_game --release
```

## Rollback points
- Each milestone that closes a child task (M2, M4, M5, M6) is a tagged commit; `git revert` per child if needed.
- Golden hashes change only with a version bump (VER-R02); a failing golden hash is a regression until proven a deliberate change.
