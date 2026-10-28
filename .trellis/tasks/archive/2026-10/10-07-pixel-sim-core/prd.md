# Pixel physics simulation core

Parent: `.trellis/tasks/10-07-noita-clone` (read its `prd.md`, `design.md` sections 1-2 and 6 first).
Revised 2026-10-07 against `research/design-review.md`; where this PRD and the KB disagree, the KB page wins.

**Read first (KB index §4):** `index.md` (conventions, golden rules G01-G15); `pixel-simulation.md` in full (rules, Key numbers,
vectors `SIM-T01..T36`); `materials-reactions.md` (MAT-R01..R16, RXN-R01..R18, FIRE-R01..R12, DUR-R01..R09, MVP-R01..R05, the
MVP-40 and reaction tables, vectors `MV-01..MV-23`); `benchmark.md` (DET-R01..R08, VER-R02, VER-R03); `spells.md` SPELL-R05 and
SPELL-R31..R35 (explosion configs this API consumes); `entities-damage.md` DAMAGE-R11 and DAMAGE-R21 (hand-off points);
`decisions-needed.md` sections 1-2 and 8.

## Goal

Create the `noita_core` crate's simulation layer: a chunked, deterministic, data-driven falling-sand world with materials,
reactions, fire, explosions and projectile-vs-cell queries. This child also bootstraps the cargo workspace and the generated runtime
data. Milestones M1 (falling sand) and M2 (chemistry, fire, explosions) of `implement.md`.

## Requirements

### Workspace and data
- Cargo workspace at repo root with `crates/noita_core` (lib); no rendering or windowing dependency in `noita_core`; pinned
  toolchain; fixed `target-cpu` baseline; clippy `disallowed_methods` for `f32::sin/cos/exp/powf` (DET-R06).
- `scripts/build_runtime_data.py` generates trimmed `crates/noita_core/data/{materials,reactions,tags_index}.json` from the research
  JSON (no prose, no palettes beyond what the renderer needs). The loader asserts 466 materials, the kind counts of SIM-R04, 330 `xml_`
  reactions and 79 tag keys, binds `air, fire, smoke, water` by name, and fails with a clear error on any unknown id or tag (RXN-R18,
  MAT-R02). `content_hash` covers the generated files (VER-R03). The loader never re-applies defaults (MAT-R04).
- Material set: all 466 materials load (stable `u16` ids by `xml_order`, `air` = 0); the 40 materials of MVP-40 are the enabled
  content and 39 reactions are compiled (MVP-R01, MVP-R02; default pending user decisions DN-MAT-01, DN-MAT-02). Name mapping from the first
  draft of this PRD: rock = `rock_static`, dirt = `soil`, brick = `templebrick_static`, toxic sludge = `radioactive_liquid`, whiskey = `alcohol`,
  steel = `steel_static` (durability 12, **not** indestructible: a Bomb leaves it, a Nuke removes it); gravel, obsidian, honey and fungus
  are not in MVP-40 (no `obsidian` id exists; lava + water gives `rock_static` + steam).

### World, cell, scheduling
- `World` of W x H cells (multiples of 64): 64x64 simulation chunks, 32x32 storage tiles, one dirty rectangle per chunk, an `active` rect.
  `Cell` is exactly 6 bytes: `mat:u16, life:u8, burn:u8, var:u8, flags:u8` (UPDATED, BURNING, DIR, OBJECT reserved). No parity bit, no
  velocity, no temperature (SIM-R03, SIM-R15).
- Dirty rects with `WAKE = 12`, `keep_awake()`, task-local write boxes merged serially in ascending chunk index (SIM-R10..R13); frozen chunks
  outside the active rect drop writes (SIM-R14).
- Four-pass checkerboard by chunk class with the pass order rotated by `frame mod 4` and column direction `(frame+cx+cy)&1`;
  `MAX_REACH = 32` with a compile-time assert and `RULE_REACH = 16` with a debug reach monitor (SIM-R20..R23, R77). Tile windows split
  safely for rayon behind a `parallel` feature (SIM-R24); the flat-array fallback is used only if profiling shows tile indirection costs > 10%.
- Rule API as the only access path (SIM-R25). All cell randomness is the stateless hash of SIM-R70 (default pending user decision DN-SIM-01);
  integer-only cell rules and a load-time `MotionParams` table (SIM-R05); per-material timer units (SIM-R35; default pending DN-SIM-02).

### Rules (per KB, not per the first-draft wording)
- Powder and liquid: multi-step fall derived from `liquid_gravity` (cap 6), diagonals, liquid lateral hop up to `L <= 10`, density swap with
  strict `>`, equal density never swaps vertically, viscosity only for powder slide (SIM-R30..R33). Gas: act probability, up first (SIM-R34).
  Kind gates motion before density; static cells are never entered or displaced (G04).
- Burning is a cell state with fuel, flames and smoke (SIM-R36, SIM-R37, FIRE-R01..R09). **Water boils but does not clear BURNING**; burning
  ends by fuel, loss of air or deletion (FIRE-R08). Powders do **not** "settle after N idle frames": there is no per-cell sleep counter.
- Reactions: compiled per-pair candidate lists in file order, positional outputs, tag inputs, probability `below(10000) < round(p*100)`,
  blobs <= radius 6 (SIM-R38, RXN-R02..R10, RXN-R17; cadence default pending DN-MAT-03).
- Explosions: `request_explosion(&ExplosionConfig{radius, ray_energy, max_durability, create_cell, hole_destroy_liquid, ...}, x, y, source)`
  resolved in a serial phase with the caps of SIM-R54: rays spend `ray_energy` on each cell's `hp`, removal needs `durability <=
  max_durability_to_destroy`, destroyed liquid is thrown out (a deterministic spiral displacement now, particles per SIM-R45..R47 if kept by
  the plan review; DN-SIM-10), fire with `create_cell_probability`; returns the changed bbox, a histogram and entities in radius (SIM-R50..R53,
  DUR-R01..R03). The first-draft `explode(x, y, radius, power)` disc model is superseded.
- Queries: `blocked(mask)` with the four ray presets, `raycast`, projectile sweep with normal, `material_at`, `set_cell`, `paint_disc`,
  `fill_rect`, AABB sweep with `climb_over_y = 4` (SIM-R60..R65).
- State hash per SIM-R75 (algorithm in benchmark.md DET-R02: blake3, per-chunk leaves) and snapshot/restore (SIM-R78); `serialize` for
  replay. Frame pipeline hooks `bodies_stamp`/`bodies_unstamp` exist and are empty (SIM-R80, SIM-R86).

### Benchmarks (criterion, written before any optimisation; SIM-R82)
Named scenarios, each recording ns per active cell and per frame: empty world; sand rain at 5% fill; water pour into a basin; lava + water;
burning oil lake; 10 explosions of R30 and one of R250; fully active random soup; 1/2/4/8 threads; dirty rects on vs all-dirty.

## Acceptance Criteria

- [ ] `cargo test -p noita_core` passes with unit tests that cite rule IDs and implement the KB vectors: `SIM-T01..T36` and `MV-01..MV-23`
      (powder fall/slide, liquid hop, density swap, gas rise, burning and burn-out, oxygen, reactions incl. sequential candidates and
      probability, blob, explosion depth by material, ray masks, loader counts), plus a property test that inert swaps conserve matter.
- [ ] Determinism (`SIM-T31..T35`): identical `hash_state()` after 3,000 frames for 1, 2, 3, 8 and 16 threads; random pass-task order;
      dirty rects on vs all-dirty after every frame; snapshot at frame k restored into all-dirty; random-soup fuzz with observed reach <= 16.
- [ ] Regression tests for the two former blockers: a settled cell is not stalled by a stale mark when its chunk wakes later (`SIM-T15`);
      a cell 4 cells from a freshly dug gap wakes and flows (`SIM-T20`).
- [ ] Performance, two tiers on an M-series Mac in release mode, numbers recorded in the task notes: **gate** = sand-rain (5%) and water-pour
      scenes on 512x512 average <= 3.33 ms per `World::step` (>= 5x realtime) and a 1024x1024 world with a 512x512 active rect holds
      <= 16.67 ms; **report-only** = all-active soup, burning oil lake, explosions R250, thread scaling. A "settled" world (no gas, no fire or
      BURNING cells, no exposed ice/alcohol/cement, no water next to soil, no timers) steps < 0.1 ms (`SIM-T36`).
- [ ] `materials.json` and `reactions.json` validate on load with clear errors for unknown ids, unknown tags, missing bound ids and wrong
      counts; `content_hash` is stable across prose-only edits of the research files.
- [ ] Explosion acceptance: Digging Bolt removes 6 cells of `soil` but 1 of `rock_static` per ray (`MV-14`); a Bomb (max durability 11) leaves
      `steel_static` (durability 12) intact (`MV-16`) while a Nuke (max durability 12) removes it (DUR-R04); an explosion never removes a cell
      whose `durability` is above its limit (DUR-R01).
- [ ] A headless example (`cargo run -p noita_core --example sandbox --release`) dumps a PPM of a sand-and-water scene after 300 frames, and
      of lava meeting water (a `rock_static` crust and steam), for eyeballing.
