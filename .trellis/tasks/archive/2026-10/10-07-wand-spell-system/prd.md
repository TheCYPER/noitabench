# Wand and spell system

Parent: `.trellis/tasks/10-07-noita-clone` (read its `prd.md`, `design.md` sections 3 and 6 first). Depends on `10-07-pixel-sim-core`
for the world-facing half (grid, queries, `explode`); the pure casting engine does not import `World` and may start earlier.
Revised 2026-10-07 against `research/design-review.md`; where this PRD and the KB disagree, the KB page wins.

**Read first (KB index §4):** `index.md` (golden rules G14-G23); `wand-casting.md` in full (rules, pseudocode, Key numbers, the fixture
verification table, vectors `KV-01..KV-15`); `spells.md` (SPELL-R01..R47, KN-1..KN-4, DF-1..DF-5, `TV-D`, `TV-S`, `TV-B`);
`entities-damage.md` (DAMAGE-R01..R21, status effects, enemy tables); `materials-reactions.md` DUR-R01..R09 and HAZ-R01..R05;
`pixel-simulation.md` SIM-R45..R65 and SIM-R80; `benchmark.md` DET-R04 and OBS-R05; `decisions-needed.md` sections 3-5.

## Goal

Implement Noita's wand mechanics and a data-driven spell catalogue inside `noita_core`, plus the projectile and entity layer needed to
make spells act on the pixel world and on entities. Milestones M3 (headless wand and spell core) and M4 (spells in the world) of `implement.md`.

## Requirements

### Units and data
- HP and damage are **internal** values everywhere in `noita_core` (newtype, XML units; player 4.0 = 100 displayed); x25 only in observations, UI
  and tests. `spells.json` stores `damage*` as display values and the loader converts once (SPELL-R03; default pending user decision
  DN-SPELL-02). Constants carry `_internal` or `_display` suffixes. Dummy HP = 4.0 internal.
- Time in frames, speeds px/s (divide by 60), angles degrees; absent XML attributes mean the engine default, never 0 (SPELL-R02, SPELL-R05).
- Spell catalogue from the generated runtime `spells.json` (422 rows keyed by `game_id`; never the 69 legacy rows; SPELL-R01, R04, R10). Each spell
  has a primitive (PROJ, TRIGGER, STATIC, MATERIAL, MODIFIER, MULTICAST, UTILITY), an implementation class (D0, D1, D2) and an `implemented` bit that
  is part of `content_hash` (SPELL-R36..R41, DF-5). No per-spell enum; D1 features are built once each, D2 spells use a handler registry.

### Wand and casting engine (pure, no `World`)
- `Wand` stats and runtime state per WAND-R03, WAND-R04 (shuffle, spells/cast, cast delay, recharge, mana max, mana charge speed, capacity, spread,
  always-cast; deck/hand/discard, timers, per-card uses); capacity 2-26 in the engine, 3-8 as a task knob.
- `cast(&mut WandState, &SpellRegistry, &CastContext, &mut SpellRng) -> CastOutcome`. `CastContext` is a read-only struct built by game code (caster
  hp and max, gold, entity counts in deterministic id order, the global `IF_HALF` flag, other wands for stage 2). `CastOutcome` holds the `ShotTree`, cast
  delay and recharge frames, mana spent, recoil and events.
- Stage 1 (this child): WAND-R01..R64, R70..R72, R80..R82, R86: draw with mana skip and wrap, shot-state accumulation (add and set modes),
  multicast, **trigger/timer/expiration payloads drawn and paid at cast time** into the `ShotTree`, end-of-click rules, recharge and cast-delay
  clamps on the total and concurrently, mana regeneration every frame, uses consumed at end of click, always-cast, Divide, Add-Trigger/Timer/Expiration,
  Wand Refresh. Open rule choices: `DN-WAND-01..04` (defaults: empty-deck recharge as the wiki, no Unlimited Spells, generation after the core).
- Stage 2 (later, separate acceptance): Greek letters, Spell Duplication, Requirement spells, Zeta, random-draw spells (WAND S4).
- Shuffle and every random spell draw from the seeded `spells` stream (SPELL-R43); never frame numbers, never the wall clock.

### Spells in the world
- Scope ladder (default pending user decision DN-SPELL-01): MVP-50 first (35 D0, 6 D1, 9 D2; SPELL-R45), then all 127 D0, then D1 features by spell count
  (PROJ_HP, MATERIAL_CONVERT, HIT_EFFECT, ...), then roughly 60 D2 (deck-ops, trajectory, black/white holes). A spell that is not `implemented` is
  rejected by task pools and `edit_wand` (`INVALID_ACTION`); it never silently does nothing. All spells unlocked (DN-SPELL-05).
- Projectiles from `ProjectileSpec` (SPELL-R05, R08, R23..R29; DF-5): speed in px/s, lifetime plus or minus random, gravity, air friction, terminal velocity
  1000 px/s, bounces, collision masks, damage by type, explosion config; sweep by DDA, bounce normal and penetration per SIM-R62, SIM-R63.
  Entity hits use a swept segment against the hitbox, first hit by parameter `t`, ties by entity id; one hit per entity unless `penetrate_entities`
  (implemented now: default pending DN-ENT-02); `on_collision_die = 0` re-hits per `damage_every_x_frames`; the shooter is skipped for
  `collide_with_shooter_frames` (DAMAGE-R20). Trails and material sprays write cells directly (SPELL-R30, SPELL-R46).
- Explosions: configs from the materials page table, ray model (DUR-R01..R03), flat entity damage in the radius (falloff UNVERIFIED, DN-SPELL-10), knockback
  with distance, damage floor by radius (SPELL-R33), player explosion multiplier 0.35, `explosion_dont_damage_shooter` (SPELL-R28, SPELL-R34, DAMAGE-R06).
  No loose-ground collapse.
- Bomb and Dynamite are ballistic projectiles with bounce, friction, a fuse (Bomb 180 frames) and hit points; no Box2D (default pending user decision
  DN-SPELL-03; `OBJECT` flag and body hooks kept).
- Entity layer: `Entity { id, kind, pos, vel, hitbox, hp, max_hp, statuses }` with the player (constants of `player-stats.json`: gravity 350 px/s^2, walk 57
  px/s, fly 95/85/52 px/s, levitation 180 frames, no fall damage), target dummy, and at least 3 enemies from `enemies.json` (initially Hämis, Hurtta,
  Haulikkohiisi; no variants, no mutation). Damage pipeline in the KB order (DAMAGE-R01..R09), single damage type in the MVP (default pending DN-ENT-01),
  i-frames 60 without refresh (DN-ENT-04), negative projectile damage clamps at 0 (DN-SPELL-09). Statuses: the minimal set of the KB (wet, oiled, bloody, on fire,
  frozen, poisoned/toxic, electrocution stun) with fixed spell-applied durations (default pending DN-ENT-05); entering liquid clears On Fire (DAMAGE-R14);
  material contact damage lives on the entity (HAZ-R01..R03).
- Events: a per-frame `Vec<Event>` (projectile spawned, hit, explosion, entity damaged or died, material converted, invalid action) for the frontend and the benchmark.
- `Game` facade in `noita_core`: owns World, entities, wands, `Rngs`, frame counter; `game.step(&Input)` in the SIM-R80 order. `Input` = held `ControlState`
  (`move, jump, fly, aim, fire, kick, interact, down`; jump edge-triggered inside the core) plus one-shot actions (`swap_wand`, `edit_wand` whole wand, ...).
  Aim and spread geometry use `libm` or tables, never `std` trigonometry (DET-R06).

## Acceptance Criteria

- [ ] Stage 1 casting tests pass without importing `World`: vectors `KV-01..KV-15`, `TV-S1..TV-S18`, loader vectors `TV-D1..TV-D7`, behaviour vectors `TV-B`, and the
      corrected fixtures of `wand-cast-test-cases.json` (draw_01 mana 15, greek_01 delay 114 moved to stage 2, refresh_03 replaced by `KV-01`; cases
      draw_01..06, tuple, spc, shuffle, mana, divide_01..05, addtrigger_01..04, refresh_01..02, always_cast, timing). Not the worked examples of
      `research/wand-mechanics.md`, which contain known errors.
- [ ] The spell loader parses and validates all 422 rows with display/internal conversion (`TV-D1..D7`); the `implemented` set is hashed into `content_hash`;
      every MVP-50 spell is `implemented` and has a behaviour test (no no-op); task pools and `edit_wand` reject unimplemented spells; fuzz: cast every
      implemented spell once with no panic.
- [ ] Integration tests through `Game`: a `LIGHT_BULLET` (3 displayed damage) kills a 100-HP dummy in 34 hits (unit check); `BOMB` carves `rock_static` but not
      `steel_static`; `DIGGER` removes cells with durability <= 10, deep in `soil` and 1 cell per ray in rock; a water spray onto lava makes `rock_static` and steam;
      a fire trail ignites oil; `BLACK_HOLE` removes every non-indestructible cell in its radius; a trigger spell with a payload releases the payload at the hit
      point; a player explosion hurts the caster at 0.35 of the displayed damage.
- [ ] Trigger timing: the payload's mana is spent at cast time, nothing is refunded when the trigger never fires, and the payload starts from default shot values (`KV-07`, `TV-S12`).
- [ ] Determinism: same seed and `Input` log give the same `Game::hash_state()`; an extra draw in the `spells` stream leaves the `worldgen` stream identical.
- [ ] Stage 2 is tracked separately: Greek letters, Duplication, Requirement and Zeta each have their own vectors before they enter any pool.
