# Playable frontend (macroquad)

Parent: `.trellis/tasks/10-07-noita-clone` (read its `prd.md`, `design.md` sections 5 and 6 first). Depends on `10-07-pixel-sim-core` (slice A) and
`10-07-wand-spell-system` (slice B). Revised 2026-10-07 against `research/design-review.md`; where this PRD and the KB disagree, the KB page wins.

**Read first (KB index §4):** `index.md`; `frontend.md` and `worldgen.md` (**not yet written**; they are phase M0 deliverables, write them before coding; until then
`research/frontend-tech.md` and `research/worldgen.md` are unvetted and superseded where `design.md` section 5 and the review (F1, F3) differ);
`entities-damage.md` Key numbers (movement, levitation, kick, hitbox, collision box, enemies, statuses); `wand-casting.md` WAND-R03/R04 and Key numbers (editor stats),
WAND-R90..R95 (generation); `spells.md` SPELL-R02/R03 (units shown in the editor), KN-2, DF-2; `pixel-simulation.md` SIM-R03 and SIM-R76 (`var` is cosmetic), SIM-R14,
SIM-R81, SIM-R86; `materials-reactions.md` MAT-R15 (render colour is not `wang_color`); `decisions-needed.md` section 7.

## Goal

A human-playable window for the game, exercising the simulation and the spell system: rendering, player controls, seeded world generation, wand editor and debug
tools. All game logic stays in `noita_core`; the frontend consumes the same core API as the benchmark. Milestone M6 of `implement.md`; slice A (viewer, brush,
overlays) needs only the simulation (after M2), slice B (controller, worldgen, HUD, editor) needs the wand and spell system (after M4).

## Requirements

- `crates/noita_game` binary using macroquad. It fills a camera-sized RGBA buffer (about 427 x 242 cells) **directly from `World`** with the material palette (colour from the
  palette and `var`, never from `wang_color`), uploads it to a texture with nearest filtering and integer zoom (2x-4x), and the camera follows the player smoothly. It does not
  read bench observations. A 60 Hz fixed-step accumulator decouples simulation from rendering; the view size comes from the camera.
- World generation in `noita_core::worldgen` (headless, seeded): **one global seed** and an integer value-noise lattice keyed by world coordinates (`hash(seed, ix, iy)`), so there
  are no seams at chunk borders and no floating point; chunk-local generation is only a scheduling unit. Surface, strata by depth, caves, liquid pools (water, oil, lava,
  acid, `radioactive_liquid`), `coal`/`wood_static`/`gold` veins, rest rooms between layers, portal, enemy and wand/chest spawn points, from the approved MVP-40 materials only
  (DN-MAT-01, DN-WORLD-03). Fixed 2048 x 1536 world, no streaming. Benchmark arenas are hand-authored or verified solvable by a ray or BFS test and are shared with the benchmark.
- The simulation runs inside an active rect of 512 x 512 cells around the player; frozen chunks keep their cells and re-activate fully dirty (SIM-R14; default pending user decisions
  DN-SIM-04, DN-SIM-07).
- Player controller with the vanilla numbers of `player-stats.json` (gravity 350 px/s^2, walk 57 px/s, jump -95 px/s, fly 95 up / 85 down / 52 horizontal px/s, `fly_time_max` 3.0 s
  = 180 frames, ground refill 6/s, air refill 0.4/s after 38 airborne frames, -8 frames per fly press, jump buffer 2 frames, `climb_over_y` 4 px). Controls: A/D move, W/space jump,
  hold space/W to levitate (the meter depletes and refills on the ground), mouse aim, LMB cast, F kick, 1-4 swap wands, Tab/E wand editor, R restart, Esc pause. The player takes damage
  from projectiles, fire, acid and lava (contact damage per overlapping pixel, 4-cell floor), is extinguished by entering liquid, drowns after 7 s, dies and restarts. **No fall damage**
  (vanilla `falling_damages = 0`).
- HUD: HP bar (display units), levitation bar, mana bar for the held wand, wand slot icons, depth, FPS and frame time.
- Wand inventory and editor built from a **hand-rolled immediate-mode widget set**: click a spell to pick it up, click a slot to place it (the "drag"); shows wand stats and per-spell
  stats (mana, damage, cast delay, recharge, uses) in the displayed units; edits go through the same core `edit_wand` path as the benchmark and accept implemented spells only
  (`egui-macroquad` and `macroquad::ui` are not used; default pending user decision DN-FE-01).
- Debug tools: material brush (pick material, radius), spawn target dummy or enemy, pause and single-step, show dirty rects, show chunk grid, frame-time overlay.
- Entities drawn as simple sprites or rectangles with HP bars; projectiles as coloured dots with trails; explosions as brief flashes. Enemies from `enemies.json` (initially Hämis, Hurtta,
  Haulikkohiisi).
- Starting kit: two wands (a `LIGHT_BULLET` wand and a `DIGGER` wand) and a small spell inventory of implemented spells.

## Acceptance Criteria

- [ ] `cargo run -p noita_game --release` opens a window at >= 60 FPS with a generated 2048 x 1536 world; the frame-time overlay stays under 16 ms during heavy liquid flow inside the
      active rect near the player (measured and recorded; the all-active worst case is not a gate).
- [ ] Slice A (after M2): a human can paint materials with the brush, watch sand, water, oil, lava, fire and steam behave, and toggle the dirty-rect and chunk overlays.
- [ ] Slice B (after M4): the player can dig (cells up to the digger's durability limit), swim, levitate with the 3.0 s meter, get burned by fire, acid and lava, be extinguished by entering
      water (entity rule; burning materials are not doused by water), die and restart.
- [ ] The wand editor can build a multicast + trigger combo (for example `BURST_2`, `LIGHT_BULLET_TRIGGER`, `FIREBALL`), shows its stats in displayed units, and casting it shows the
      trigger payload released on hit.
- [ ] World generation is deterministic per seed (hash test in core), has no seams at 64-cell chunk borders (noise continuity test), uses only approved materials, and every generated or
      authored arena used by a benchmark task passes the solvability check.
- [ ] No game logic lives in `noita_game` that the benchmark would need: a review of the crate finds only rendering, input mapping, UI and debug tooling; it calls only the public `noita_core` API.
