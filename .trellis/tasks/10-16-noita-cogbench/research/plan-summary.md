# Plan summary for the project owner (2026-10-07)

Status: research, knowledge base (KB) and planning documents are done and consistent. **No code exists and none will be written until you have answered
section (c).** What I need from you: accept or change the defaults in (c); everything else already has a default in the KB.

## (a) Final architecture

- **Three Rust crates.** `noita_core` is the whole game without a window (pixel world, spells and wands, entities, world generator, observation encoders, benchmark tasks).
  `noita_bench` is a headless program that speaks JSON lines to Python or any agent. `noita_game` is a thin macroquad window. No game rules live outside the core, so the game and the benchmark cannot disagree.
- **The world** is a grid of 1-pixel cells, 6 bytes each, cut into 64x64 chunks that sleep when nothing changes. Chunks update in four checkerboard passes so they run in parallel with identical results;
  randomness is a hash of (seed, frame, position), so results never depend on thread count or on which chunks were asleep.
- **Chemistry** is data: all 466 Noita materials load, 40 are enabled with 39 reactions. Burning is a state of a cell (water boils but does not put it out). Explosions are rays that spend energy on each cell's hardness,
  so digging depth depends on material.
- **Spells and wands**: a pure casting engine follows Noita's deck, hand and discard algorithm and builds the whole shot, trigger payloads included, at cast time. A spell that is not implemented cannot appear in a task.
  Health is stored in Noita's internal units and shown x25.
- **The benchmark** is bit-deterministic for a seed and action log, hashes every step, verifies replays, enforces limits inside the engine, and offers a text view and an RL array view. Suite v1 has eight tasks.
- **The game** is a fixed 2048x1536 generated world with a 512x512 area simulated around the player.

## (b) Milestones

| Milestone | Built | Testable then | Playable then |
|---|---|---|---|
| M0 Foundations | Your decisions; corrected casting fixtures; Rust coding-convention spec | Documents | No |
| M1 Falling sand | Grid, sleeping chunks, sand, water, oil, gas, parallel passes, hashing | Motion rules; same result on 1-16 threads; first speed numbers | Picture dumps |
| M2 Chemistry | Reactions, fire, lava + water, acid, explosions with material-dependent craters | Reaction, fire, crater tests; speed scenarios | Sandbox window with brush |
| M3 Wand core | Casting rules; all 422 spells load; first 50 as data | Casting vectors, no world needed | No |
| M4 Spells in the world | Projectiles, entities, damage, 3 enemies, ballistic Bomb | Scripted integration tests | Headless duels |
| M5 Benchmark v1 | Protocol, Python client, 8 tasks, baselines, replay verifier | `run_scripted.py` runs every task; tampering is caught | By agents |
| M6 Playable game | World generator, controller, HUD, wand editor | Frame time, determinism | Yes: dig, swim, levitate, burn, edit wands, restart |
| M7 Integration | Review and hardening | Everything together | Final smoke test |

M5 and M6 run in parallel; M3 can start during M1.

## (c) Mechanics decisions (faithful to Noita vs simpler for the benchmark)

Each default is what the plan already assumes. "Bench" = consequence for the benchmark.

1. **Bomb, Dynamite, crates (DN-SPELL-03).** Options: simple rolling projectile with fuse; drop them; real rigid-body physics later. Default: simple projectile.
   Bench: Bomb matters for dig and chain tasks; deterministic and cheap, but throws and rolls differ from Noita and nothing can be pushed.
2. **Putting out fire (FIRE-R08).** Options: faithful (water boils but does not douse burning materials; fires end by fuel, lack of air or removal) or simple (water clears fire). Default: faithful.
   Bench: `extinguish_fire` and `chain_reaction` are built around flooding, smothering or removing fuel and must be proven solvable; harder, more interesting.
3. **Explosions and digging (DN-SPELL-04, DN-MAT-07, DN-SIM-12).** Options: rays that spend energy on hardness, or a simple disc with a cut-off. Default: rays, at most 32 explosions per frame.
   Bench: dig depth depends on material (about 6 px of soil but 1 px of rock per ray); the biggest nuke costs about a million cell visits.
4. **Matter thrown by craters and splashes (DN-SIM-10; the question has no id yet).** Options: full particle system; push to the nearest free cells; delete. Default: nearest-free-cell shortcut first, particles later if needed.
   Bench: no score effect unless splashes matter; deleting would make water vanish.
5. **How much chemistry (DN-MAT-01, DN-MAT-02, DN-SIM-09).** Options: 40 materials and 39 reactions, or all 330 reactions. Default: 40 and 39, data-driven.
   Bench: fewer surprises; every addition changes the content hash (old runs stop being comparable), and growth rows (grass, moss) keep chunks awake and slow the sim.
6. **How liquids, gas and reactions feel (DN-SIM-03, DN-SIM-11, DN-MAT-03).** No source gives Noita's formulas. Options: our calibrated guesses or alternatives. Default: calibrated guesses.
   Bench: Noita-like, not Noita-exact; tasks such as lava crossing are tuned against scripted baselines and frozen per version.
7. **Spell catalogue scope (DN-SPELL-01, DN-SPELL-05).** Only 237 of 422 spells work without per-spell code. Options: a ladder (first 50, all 127 data-only, feature-based, then about 60 deck and trajectory spells) or all 422.
   Default: the ladder, all unlocked, pools hold implemented spells only. Bench: wand tasks draw from about 300 spells; no spell silently does nothing.
8. **Wand rules the sources leave open (DN-WAND-01..04).** Empty deck at end of a click recharges; no Unlimited Spells perk; one global IF_HALF toggle; hand-made task wands of 3 to 8 slots. Default: as stated.
   Bench: `wand_dps_optimization` has a reproducible reference answer; wands are smaller than Noita's (up to 26).
9. **Piercing projectiles (DN-ENT-02).** Options: hit once and die, or a once-per-entity hit list. Default: hit list (the first 50 spells include Lightning and Piercing Shot). Bench: some kill tasks reward piercing wands.
10. **Damage and statuses (DN-SPELL-02, DN-ENT-01, DN-ENT-04, DN-ENT-05, DN-SPELL-09, DN-SPELL-10).** Internal units shown x25, one damage type per hit, 60 invulnerability frames, statuses only from spells, flat explosion damage, negative damage clamps to zero.
    Bench: agents see the wand-editor numbers; standing in water does not make you wet, a deliberate loss of depth.
11. **Movement, numeric type, aiming (DN-SIM-13, DN-BEN-01).** Default: vanilla numbers (levitation 3.0 s), 32-bit floats with a fixed math library, integer-degree aim in text mode. Alternative: fixed point, shorter levitation.
    Bench: task geometry follows these numbers (a 1.0 s meter gives only 52 px of flight); Mac-versus-Linux bit-exactness is unverified until Linux CI exists.
12. **World size and generator (DN-WORLD-02, DN-WORLD-04, DN-BEN-08).** Default: fixed 2048x1536 game world with integer-noise caves; benchmark worlds 512 wide with a height per task and verified-solvable arenas.
    Bench: every task provably solvable; `dig_to_depth` at 1,024 needs a world about 1,152 px tall.
13. **Roster and scope cuts (DN-ENT-07, DN-BEN-09).** Default: 8 core enemies (3 first), no mutation, fixed waves, no perks or karma. Bench: fewer random events; procedural spawns can wait for suite v2.

## (d) Top risks

1. **Speed is unmeasured.** All performance figures are estimates; a fully active 512x512 world under 3.33 ms on one thread is not safe. Mitigation: two-tier gates, benchmarks first in M1.
2. **Sleeping chunks may stop sleeping.** Reactions with air, timers and fire keep chunks awake (DN-SIM-09). Mitigation: measure early, keep the 40 materials.
3. **"Feel" cannot be checked against Noita.** Liquid, gas, reaction and fire formulas are guesses. Mitigation: keep them in data, tune by footage, freeze per task version.
4. **Spell breadth.** 185 spells need custom code, 16 lack side-entity data. Mitigation: the ladder and implemented-only pools.
5. **Task validity.** Dig rate, levitation range and fire-fighting solutions are unvalidated. Mitigation: scripted baselines must prove solvability before a task is frozen.
6. **Cross-platform determinism.** Mac versus Linux floating point is unverified. Mitigation: libm only, no fast-math, Linux CI later.
7. **Stale sources.** Some research files and three casting fixtures hold known errors. Mitigation: the KB pages win over research files; fix the fixtures in M0.
8. **Late mechanics changes are costly.** A changed rule alters golden and content hashes and forces version bumps. Mitigation: settle (c) before M1.
