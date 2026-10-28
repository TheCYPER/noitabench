# Macroquad Frontend Rendering, Input, and UI

**Purpose:** Normative reference for `noita_game` (the playable Noita-like game with macroquad 0.4 rendering). Developers implementing the UI, render loop, input handling, and debug tools read this page (not the research files) to understand frame pacing, texture upload, camera control, input mapping, HUD display, and performance constraints. Every rule has a stable ID (`FE-Rnn`) that code and tests cite.

**Golden constraint:** No game logic in `noita_game`. The frontend is a pure observation reader and input device; all physics, damage, wand casting, and entity AI live in `noita_core`. The frontend links `noita_core` directly and reads the `World` struct each frame (not via the benchmark protocol).

---

## Normative Rules

### Render Loop and Timestep

**FE-R01: Fixed 60 Hz Timestep, Decoupled Rendering**
- The game loop runs at exactly 60 Hz (dt = 1/60 s ≈ 16.67 ms per frame).
- Simulation advances only when `step()` is called; rendering is separate and never blocks the simulation.
- Input events are buffered in a `VecDeque<ControlState>`; dropped video frames do not de-sync the engine.
- A fixed-timestep accumulator (SIM-R01, pixel-simulation.md) prevents spiral-of-death: `while accumulator >= dt && steps < max_frame_skip: { step(); accumulator -= dt; }` with `max_frame_skip = 3`.
- **Source:** frontend-tech.md §1; benchmark-design.md lessons §1.2.

**FE-R02: Frame Pipeline Order**
1. Consume enqueued input actions (held or one-shot).
2. Call `noita_core::step(actions)` → returns observation.
3. Update internal game state (map, HUD, camera position).
4. Mark grid texture dirty.
5. Render (decoupled: happens at display refresh or capped max FPS).
6. Return to step 1.
- **Source:** frontend-tech.md §1, §8.

**FE-R03: Pixel-Perfect Rendering with FilterMode::Nearest**
- All GPU textures use `FilterMode::Nearest` (no linear interpolation).
- Camera zoom is an integer factor (e.g., 2×, 4×), never fractional.
- Destination render size is `grid_width_px × zoom_factor` (e.g., 128 × 2 = 256 px).
- **Source:** frontend-tech.md §2.2.

### Texture and Grid Updates

**FE-R04: Grid Observation Contract**
- The observation arrives as a direct read of `noita_core::World` (not a base64-encoded protocol message).
- Grid format: `width × height` cells, each cell a `u16` material ID (0 = air).
- Visible region is a viewport-sized window (e.g., 128×128 cells for a 1280×720 screen with 2× zoom).
- Texture is updated per-frame if the grid changed; mark dirty only when new observation received.
- **Source:** frontend-tech.md §2.1; pixel-simulation.md SIM-R01.

**FE-R05: Texture Upload Performance Budget**
- Grid upload cost is <1 ms for 128×128 cells on modern GPUs (macBook Air M-series or better).
- macroquad 0.4 does not expose partial texture updates; always upload the full visible region.
- If performance becomes a bottleneck (target: 60 FPS on laptop), compress or split the grid and implement async upload.
- **Source:** frontend-tech.md §6.1.

### Camera and Coordinate Systems

**FE-R06: Camera2D with Integer Zoom and Player Follow**
- Use `Camera2D { zoom: Vec2(zoom_factor, zoom_factor), target: world_pos, ... }`.
- `target` follows the player: `camera.target = player_pos - viewport_size / 2`.
- Zoom factor must be integer to preserve pixel-perfect rendering (FE-R03).
- Viewport size in world pixels = screen size / zoom (e.g., 1280 / 2 = 640 world px width).
- **Source:** frontend-tech.md §2.2.

**FE-R07: Screen-to-World Coordinate Conversion**
- Mouse position is always screen-space (0..screen_width, 0..screen_height).
- Convert to world coordinates: `world_pos = camera.target + (screen_pos - screen_center) / zoom`.
- This value is passed to the input handler as the aim target (in world pixels).
- **Source:** frontend-tech.md §3.1.

### Input Mapping

**FE-R08: Input Mapping to Core ControlState**
- Keyboard input: WASD or arrows for movement (x-direction -1/0/1), Space for jump, E for interact, Q to swap wand, 1-6 for spell slot selection.
- Mouse: Position → aim target (world coordinates via FE-R07), left-click to fire.
- Each frame collects input into a `ControlState` struct: `{ move: i8, jump: bool, fly: bool, aim: Option<(f32, f32)>, fire: bool, kick: bool, interact: bool }`.
- Apply continuously (held) inputs every frame; one-shot inputs (jump, fire, kick) apply on edge trigger (transition to true).
- **Source:** benchmark.md ACT-R02; frontend-tech.md §3.1.

**FE-R09: One-Shot Actions**
- Wand swap, wand edit, drop spell, pickup, wait: applied at `step()` start, consume 0 frames.
- These are not held; they fire once per input event (e.g., one `SwapWand` per Q press).
- **Source:** benchmark.md ACT-R03.

### HUD and Debug Display

**FE-R10: HUD Rendering in Screen-Space**
- HUD elements (HP bar, mana, position, depth) are drawn in screen-space, not affected by camera.
- Use `push_camera_state()` / `set_default_camera()` to switch rendering contexts.
- Text rendering: macroquad built-in font (no custom font loading in 0.4 easy API).
- Cache static strings; each new `draw_text()` allocates a temporary glyph cache (~1-2 ms per unique string).
- **Source:** frontend-tech.md §4.

**FE-R11: Debug Tools (Optional for MVP)**
- Brush tool: paint cells by clicking and dragging (world-space).
- Pause/step: freeze simulation and advance one frame at a time (requires `--dev` flag, does not invalidate runs per benchmark.md ANTI-R03).
- Dirty-rect overlay: visualize chunk dirty rectangles (draw outlines on screen-space chunks).
- Entity hitbox overlay: draw collision AABBs (world-space, per entities-damage.md SIM-R65).
- **Source:** frontend-tech.md §9.

### Wand Editor UI

**FE-R12: Wand Editor UI Approach**
- **DECISION-NEEDED (FE-D1)**: Use macroquad::ui (built-in immediate-mode, simple but limited) or hand-rolled (full control, no dependency)?
  - **Recommended default**: Hand-rolled for MVP (buttons for slot selection, spell name display, no drag-and-drop yet).
  - **Alternative**: Test egui-macroquad 0.22.1 + macroquad 0.4 compatibility; if viable, use egui for full widget library (drag-to-reorder, themed UI, ~5-10 ms per frame for complex layouts).
- **Scope**: Display active wand, spell slots (6 typical, task-dependent up to 8), mana/recharge state.
- **Future**: Spell search, filtering, reordering (deferred to post-MVP).
- **Source:** frontend-tech.md §5.

### Performance and Crate Versions

**FE-R13: Performance Budget (60 Hz Target)**
- Release build on MacBook Air M-series or equivalent laptop GPU: maintain ≥60 FPS.
- Texture upload: <1 ms (FE-R05).
- Camera projection: negligible CPU (<0.5 ms).
- Text rendering: cache static strings; new strings ~1-2 ms each.
- Total render-to-display: <16.67 ms (1/60 s).
- **Source:** frontend-tech.md §6.2.

**FE-R14: Workspace Crate Versions (Pinned, Verified 2026-10-07)**
| Crate | Version | Notes |
|---|---|---|
| macroquad | 0.4.16 | Latest 0.4 series; not 0.5 dev |
| serde | 1.0.229 | Stable; breaking changes rare at 1.x |
| serde_json | 1.0.151 | Paired with serde |
| bincode | 2.0.1 | Stable; **do NOT use 3.0.0** (non-compiling placeholder) |
| rayon | 1.12.0 | Chunk parallelism (if needed) |
| rand, rand_xoshiro, noise, criterion, proptest | 0.10.3, 0.8.1, 0.9.0, 0.8.2, 1.11.0 | See pixel-simulation.md, benchmark.md for full workspace |

- **Source:** frontend-tech.md §7.

---

## Key Numbers

| Constant | Value | Unit | Notes |
|---|---|---|---|
| **Frame Rate & Timestep** | | | |
| Frame rate | 60 | Hz | SIM-R01 |
| Timestep | 1/60 | s | ≈16.67 ms/frame |
| Max frame skip (accumulator) | 3 | frames | Prevents spiral-of-death on low FPS |
| **Texture & Rendering** | | | |
| Grid observation size | 128×128 (typical) | cells | Viewport-dependent; up to 256×256 for larger worlds |
| Texture channels (MVP) | 1 (material ID) | uint8 | Future: 3-channel RGB (material, flags, entity class) |
| Pixel-perfect zoom | 2, 4, 8 | integer | Examples; must be integer (FE-R03) |
| Texture upload cost | <1 | ms | 128×128 on modern GPU (FE-R05) |
| Camera projection cost | <0.5 | ms | CPU-side matrix calculation (FE-R06) |
| **Input & UI** | | | |
| Visible wand slots | 3–8 | slots | Task-dependent capacity (benchmark.md Key numbers) |
| Text cache miss | 1–2 | ms | Per unique draw_text() string (FE-R10) |
| Spell editor UI build time | 0–10 | ms | Hand-rolled: <1 ms; egui: 5–10 ms with complex layout |
| **Memory** | | | |
| Grid texture (128×128, u16) | 32 KiB | bytes | Plus GPU VRAM (~32 KiB on GPU) |
| HUD cache (pre-rendered strings) | ~10 | KiB | Depends on static string count |
| Particles, entities, per-frame alloc | <1 | MiB | Dependent on simulation state |

---

## Data Files and Observation Contract

| Source | Format | Records/Size | Meaning |
|---|---|---|---|
| `noita_core::World` (direct link) | Struct in memory (not serialized) | Grid `width × height`, entity list, HUD state | Grid cells read each frame; material IDs are indices into materials.json |
| `materials.json` | JSON array, 466 records | Palette: material ID → name, colour, properties | Loaded by noita_core; frontend indexes grid values into this table for rendering |
| `spells.json` | JSON array, 422 records | Spell ID → display name, mana cost, icon | Used by wand editor UI (FE-R12) |
| `player-stats.json` | JSON object | Player HP, movement, levitation, damage model | HUD display: HP (internal × 25 = displayed per entities-damage.md), mana, position |
| Colour palette (material) | Derived from materials.json, implicit | Per-material RGBA or per-cell `var` cosmetic | Material palette + per-cell `var` (6-bit cosmetic randomness) for visual variety |

**Observation struct (read each frame from noita_core):**
- `grid: [[u16; W]; H]` — material IDs.
- `hud: { hp, hp_max, mana, mana_max, pos: (i32, i32), depth, state_flags }` — player HUD.
- `wands: [{ name, spells: [Option<spell_id>; 8] }]` — active wand and other wands in inventory.
- `entities: Vec<{ id, x, y, kind, hp }>` — visible entities (enemies, items, projectiles, capped ~16).

---

## Worked Examples and Test Vectors

### Example 1: Screen-to-World Coordinate Conversion (FE-R07)
**Input:** Screen resolution 1280×720, zoom factor 2, camera target (world pos) = (64, 48), mouse screen pos = (640, 360).
- Viewport size in world px = (1280/2, 720/2) = (640, 360).
- Screen center = (640, 360).
- Mouse screen offset = (640 - 640, 360 - 360) = (0, 0).
- World pos = (64, 48) + (0, 0) / 2 = (64, 48).
**Output:** Aim at world (64, 48) (camera center). ✓

### Example 2: Input Mapping (FE-R08)
**Input:** Player presses D (move right), mouse at (800, 300) screen coords.
- Move direction = 1 (right).
- Mouse world pos = screen_to_world((800, 300), camera) → (e.g., 180, 100).
- `ControlState { move: 1, jump: false, ..., aim: Some((180, 100)), fire: false, ... }`.
**Output:** ControlState enqueued; step() advances with movement and aim target. ✓

### Example 3: Texture Dirty Flag (FE-R04)
**Input:** Frame N: observation received, grid changed at position (50, 50).
- Mark `grid_texture_dirty = true`.
- On render: `if grid_texture_dirty: texture.update(&grid_image); grid_texture_dirty = false;`.
**Output:** GPU texture updated once; next frame's observation does not re-upload unless grid changed. ✓

### Example 4: HUD Rendering Order (FE-R10)
**Input:** Render phase, game state has `hp = 75`, `hp_max = 100`.
- `push_camera_state()` (save world camera).
- `set_default_camera()` (switch to screen-space 0,0 -> screen_w, screen_h).
- `draw_text("HP: 75/100", 10, 30, 20, RED)`.
- `pop_camera_state()` (restore camera for world rendering).
**Output:** HUD text appears in screen-space, unaffected by camera zoom/pan. ✓

### Example 5: Wand Editor Slot Selection (FE-R12)
**Input:** Hand-rolled UI, 6 spell slots, player presses "1" to select slot 0.
- Check if slot 0 is empty or contains a spell.
- Display slot 0 highlighted, show spell name (if any).
- If user clicks "swap", enqueue `OneShot::SwapWand(slot_idx)`.
**Output:** Wand editor shows active slot; next step() processes the swap. ✓

---

## Pitfalls and Common Misreadings

1. **Screen-Space vs World-Space Rendering:** HUD is screen-space (never zooms); world entities are world-space (zoom applies). Forgetting to `push_camera_state()` causes HUD to scale with the camera.

2. **Camera Target vs Zoom:** `Camera2D.target` is the world position to center on screen; `zoom` is the magnification. Both are independent. Setting zoom but forgetting `target` leaves the camera at (0, 0).

3. **Integer Zoom Requirement:** Fractional zoom (e.g., 2.3×) causes texture pixel bleeding and breaks pixel-perfect rendering. Always use integer zoom (FE-R03).

4. **Input Buffering Prevents De-Sync:** Dropped frames do NOT re-sync the simulation because inputs are buffered. The accumulator holds frames for the next `step()` call, so no input is lost.

5. **Observation is Direct, Not Serialized:** Unlike the benchmark protocol, the frontend reads `noita_core::World` directly in memory (no base64 encoding, no JSON). The grid is a 2D array of `u16` material IDs.

6. **No Game Logic in Frontend:** Do NOT calculate damage, physics, or wand state in `noita_game`. All logic runs in `noita_core::step()`. The frontend only renders and collects input.

7. **Text Rendering Cost:** Each unique `draw_text()` string allocates a glyph cache entry (~1-2 ms). Pre-render static strings and cache them, or concatenate dynamic values into a pre-rendered template.

8. **Macro Compatibility:** egui-macroquad's claim of macroquad 0.4 support is UNVERIFIED. Test a minimal example before committing to egui for the UI.

9. **Dirty Texture Flag:** Mark the grid dirty only when a new observation is received. Rendering the same texture every frame (without a change) is wasteful; check if the grid actually changed first.

10. **Frame Pipeline Order:** Inputs are consumed before `step()`, not after. Input events from frame N affect the result of `step()` in frame N; they do not carry over to frame N+1.

---

## Our Simplifications (MVP)

| Feature | Status | Rationale | DECISION-NEEDED |
|---|---|---|---|
| Single-channel grid | MVP | Simpler rendering; RGB/RGBA layers added later (benchmark.md OBS-R07 supports multi-channel). | If agents need multi-layer observations, extend to 3-channel in v2. |
| Hand-rolled wand UI | MVP (default) | Full control, no egui dependency, sufficient for 6–8 slots. | FE-D1: Test egui-macroquad 0.22.1 compatibility; if viable, use for post-MVP. |
| Built-in fonts only | MVP | Custom font loading is manual in 0.4; revisit when v1 is stable or 0.5 is released. | Add custom fonts post-MVP if UI polish is needed. |
| Fixed 1280×720 window | MVP | Simplifies camera math (no fullscreen, no resolution scaling). | Fullscreen / responsive layout deferred; fixed size adequate for demo. |
| No entity debug rendering | MVP | HUD + grid only; entity overlays (hitboxes, heatmaps) added if debug mode needed. | Debug tools (FE-R11) are optional; can be toggled with `--dev` flag. |
| No mobile input | MVP | Touch events out of scope; macroquad supports iOS/Android but not prioritized. | Mobile support deferred; feasible in v2 (macroquad capability exists). |

---

## Open Questions

1. **egui-macroquad on 0.4 Viability (FE-D1):** Does egui-macroquad 0.22.1 actually compile with macroquad 0.4.16? Recommendation: build a minimal test before committing.

2. **Custom Font Loading:** When are custom fonts needed? Current built-in font is sufficient for MVP. Recommendation: defer to post-MVP.

3. **Fullscreen and Resolution Scaling:** Required for demo, or fixed 1280×720 acceptable? Recommendation: locked resolution for v1; add scaling post-MVP if needed.

4. **Entity Debug Overlays:** Should the frontend render entity names, hitboxes, or AI state? Recommendation: out of scope for v1; implement if `--debug` flag is added.

5. **Multi-Channel Grid Rendering:** When does the benchmark protocol require RGB/RGBA observations in the frontend? Recommendation: v1 uses single-channel; extend if agents need multi-layer feature extraction.

6. **Async Texture Upload:** Is 128×128 upload cost (<1 ms) ever a bottleneck? Recommendation: profile before optimizing; async upload is complex and likely unnecessary for MVP.

---

## Sources

- Research: `./.trellis/tasks/10-16-noita-cogbench/research/frontend-tech.md` (comprehensive macroquad 0.4 reference, 2026-10-07).
- Benchmark protocol and input schema: `benchmark.md` (ACT-R02, ACT-R03, ACT-R05).
- Pixel-simulation constants: `pixel-simulation.md` (SIM-R01, SIM-R02, SIM-R06).
- Damage and player numbers: `entities-damage.md` (Key numbers for HUD display, movement).
- Materials and spells: `materials.json`, `spells.json` (shipped data files).
- macroquad 0.4 documentation: https://docs.rs/macroquad/0.4/macroquad/
- macroquad texture module: https://docs.rs/macroquad/0.4/macroquad/texture/
- macroquad immediate-mode UI: https://docs.rs/macroquad/0.4/macroquad/ui/
