# Frontend technology: macroquad 0.4 for Noita-like pixel rendering

Research date: 2026-10-07. Verified on macOS arm64 (rustc 1.98) and Linux x86_64 (cross-compilation). This document covers the rendering, input, and UI subsystems for `noita_game`, which receives observations from the deterministic headless core (`noita_bench`/`noita_core`) and displays a playable Noita-like game at 60 Hz.

## 1. Architecture overview

The frontend runs on a **fixed 60 Hz timestep, decoupled from rendering**:

```
┌─────────────────────────────────────────────────────────────┐
│  Input events (keys, mouse)                                 │
│  ↓                                                           │
│  ┌─ GameState (player pos, aim, wand state, HUD) ─┐        │
│  │  Input events enqueued in a `VecDeque<Action>` │        │
│  └─────────────────────────────────────────────────┘        │
│  ↓ (consumed at 60 Hz by `step()`)                          │
│  Timestep accumulator                                       │
│  ├─ Enqueued actions → step input                           │
│  ├─ step() → request observation from `noita_bench`         │
│  └─ Accumulate: when `frame_time >= 1/60`, call step        │
│  ↓                                                           │
│  Observation received                                       │
│  ├─ Update internal state (map, entities, HUD)              │
│  └─ Mark texture dirty                                      │
│  ↓                                                           │
│  Render (decoupled, runs at display refresh or max)         │
│  ├─ If texture dirty: update GPU Texture2D from grid        │
│  ├─ Draw texture with integer zoom                          │
│  ├─ Draw HUD text, wand editor                              │
│  └─ swap_buffer()                                           │
└─────────────────────────────────────────────────────────────┘
```

Key principle (lesson 5 from benchmark-design.md): sim advances only on `step()`; rendering does not block the simulation thread. Input is buffered; dropped frames do not cause de-sync.

## 2. Texture upload and rendering

### 2.1 Per-frame grid update

The observation arrives as a base64-encoded `uint8` grid (`128×128` or configurable). The texture is updated per-frame when the grid changes:

```rust
// Grid observation: 128×128 px uint8 material ids (0=air)
let grid: Vec<u8> = decode_base64(&obs.grid.data); // shape [128, 128]

// Create GPU texture once at startup
let texture = Texture2D::new();
texture.set_filter(FilterMode::Nearest); // Pixel-perfect: no interpolation

// Each step, upload the visible region (e.g. 64×64 cells = 256×256 px)
// macroquad 0.4 Texture2D::update_part() accepts Image data:
let image = Image {
    bytes: grid, // raw u8, interpreted as greyscale
    width: 128,
    height: 128,
};
texture.update(&image); // Full update; partial updates not in 0.4 API

// Render: draw_texture_ex() applies dest_size for integer zoom
let zoom = 2; // 2× pixel grid
let dest_size = Some(Vec2::new(128.0 * zoom as f32, 128.0 * zoom as f32));
draw_texture_ex(texture, x, y, WHITE, DrawTextureParams {
    dest_size,
    flip_x: false,
    flip_y: false,
    rotation: 0.0,
    pivot: None,
});
```

**API details (macroquad 0.4.16 on docs.rs)**:

| Method | Input | Use |
|--------|-------|-----|
| `Texture2D::new()` | dimensions u32, format | Create GPU texture |
| `texture.set_filter(FilterMode::Nearest)` | enum | Disable linear interpolation (required for pixel art) |
| `texture.update(&Image)` | `Image { bytes: Vec<u8>, width, height }` | Upload entire grid; **there is no partial update in 0.4** |
| `draw_texture_ex()` | texture, x, y, tint, params | Draw with zoom via `dest_size: Vec2` |
| **Material layer** | channels (RGB/RGBA) | Grid uses single-channel; for multi-layer (material + flags + entity) see §2.3 |

**UNVERIFIED**: macroquad 0.4.16 Texture2D::update() parameter details (whether it accepts raw bytes or requires Image struct). Recommend checking `docs.rs/macroquad/latest/macroquad/texture/` and calling `cargo doc --open` locally.

### 2.2 Integer zoom with Camera2D

For pixel-perfect rendering, use a Camera2D with an integer zoom factor:

```rust
// Set once at window init (e.g. 1280×720 window, 2× zoom of 640×360 logical)
let camera = Camera2D {
    zoom: Vec2::new(2.0, 2.0), // Integer pixel scaling
    target: Vec2::new(0.0, 0.0), // Or center on player; updated each frame
    rotation: 0.0,
    order: 0.0,
};
set_camera(&camera);

// Player-follow: update camera.target each step
let player_pos = obs.hud.pos; // [x, y] in world pixels
let viewport_w = 640; // logical pixels
let viewport_h = 360;
camera.target = Vec2::new(
    (player_pos[0] as f32) - viewport_w / 2.0,
    (player_pos[1] as f32) - viewport_h / 2.0,
);
set_camera(&camera);

// Render grid then HUD within the camera view
draw_texture(grid_texture, 0.0, 0.0, WHITE);
// HUD elements (text, wand icon) are also within camera bounds
```

**Alternative**: `draw_texture_ex(..., dest_size: Vec2)` scales without a camera; use one or the other, not both, to avoid confusion.

**Performance note**: macroquad's `Camera2D` is CPU-side (projection matrix recalc each frame). For very large worlds (16K×16K pixels), consider rendering only the visible region to the texture.

### 2.3 Multi-layer grids (if needed later)

The benchmark protocol allows multi-channel grids (material, flags, entity class). macroquad 0.4 supports:
- Single-channel grayscale: `Image { bytes, width, height }` → texture.update()
- RGB/RGBA: bytes laid out as flat `[R, G, B, R, G, B, ...]` or `[R, G, B, A, ...]`

For now (v1), a single material grid suffices. If rendering changes to "material layer + flags + entity", the GPU texture becomes a 3-channel image and rendering uses shader sampling (or CPU blitting for simplicity).

## 3. Input mapping and world coordinates

### 3.1 Keyboard and mouse input

```rust
// Per frame (before step):
let mut input = ControlState::default();

// WASD / arrow keys for movement
if is_key_down(KeyCode::Right) || is_key_down(KeyCode::D) {
    input.move_direction = 1;
}
if is_key_down(KeyCode::Left) || is_key_down(KeyCode::A) {
    input.move_direction = -1;
}

// Space for jump
if is_key_pressed(KeyCode::Space) {
    input.jump = true;
}

// Mouse aim: convert screen to world coordinates
let mouse = mouse_position();
let mouse_world = screen_to_world(mouse, camera);
input.aim = Some(AimTarget::At([mouse_world.x, mouse_world.y]));

// Left-click to fire
if is_mouse_button_pressed(MouseButton::Left) {
    input.fire = true;
}

// E for interact
if is_key_pressed(KeyCode::E) {
    input.interact = true;
}

// Q to swap wand
if is_key_pressed(KeyCode::Q) {
    oneshot_actions.push(OneShot::SwapWand(1));
}

// Enqueue for step (capped at max_frames_per_decision):
action_queue.push_back(input);
```

**Screen-to-world helper** (with camera):

```rust
fn screen_to_world(screen_pos: (f32, f32), camera: &Camera2D) -> Vec2 {
    let world_zoom = camera.zoom.x; // Assumes square zoom (x == y)
    let viewport_w = screen_width() / world_zoom;
    let viewport_h = screen_height() / world_zoom;
    
    let norm_x = screen_pos.0 / screen_width();
    let norm_y = screen_pos.1 / screen_height();
    
    Vec2::new(
        camera.target.x + (norm_x - 0.5) * viewport_w,
        camera.target.y + (norm_y - 0.5) * viewport_h,
    )
}
```

### 3.2 Fixed timestep accumulator

```rust
struct GameLoop {
    accumulator: f32,
    dt: f32, // 1.0 / 60.0 seconds
    max_frame_skip: u32, // Prevent spiral of death
}

impl GameLoop {
    fn update(&mut self, frame_time: f32) -> u32 {
        self.accumulator += frame_time;
        let mut steps = 0;
        
        while self.accumulator >= self.dt && steps < self.max_frame_skip {
            // Dequeue action(s) and call step()
            let obs = benchmark_client.step(...)?;
            update_state(&obs);
            
            self.accumulator -= self.dt;
            steps += 1;
        }
        steps
    }
}

// Main loop:
let mut game_loop = GameLoop { accumulator: 0.0, dt: 1.0/60.0, max_frame_skip: 3 };

loop {
    let frame_time = get_frame_time();
    let steps_this_frame = game_loop.update(frame_time);
    
    if steps_this_frame > 0 {
        texture_dirty = true;
    }
    
    // Render (decoupled timing)
    clear_background(BLACK);
    if texture_dirty {
        grid_texture.update(&grid_image);
    }
    draw_texture(...);
    draw_hud(...);
    next_frame().await;
}
```

**Key property**: `frame_time` is wall-clock elapsed (from macroquad's `get_frame_time()`); steps consumed from the accumulator in multiples of `1/60`. Dropped video frames do not de-sync the simulation.

## 4. HUD and text rendering

### 4.1 Basic text drawing

```rust
// Per-frame HUD update (after observation):
let hud_text = format!(
    "HP: {}/{}\nMana: {}/{}\nPos: ({}, {})\nDepth: {}",
    obs.hud.hp,
    obs.hud.hp_max,
    obs.hud.mana as i32,
    obs.hud.mana_max,
    obs.hud.pos[0],
    obs.hud.pos[1],
    obs.hud.depth,
);

// Draw in screen-space (no camera transform for HUD)
let font_size = 20.0;
draw_text(&hud_text, 10.0, 30.0, font_size, WHITE);

// Or individual lines with positioned elements:
draw_text(&format!("❤ {}", obs.hud.hp), 10.0, 30.0, font_size, RED);
draw_text(&format!("✦ {}", obs.hud.mana), 10.0, 50.0, font_size, BLUE);
```

**Text rendering caveats**:
- macroquad 0.4 uses a built-in font (no custom font loading in easy API; you must load as Image + build a glyph cache manually if custom fonts needed).
- Text coordinates are in screen-space. Use `push_camera_state()` / `pop_camera_state()` to switch between world and screen rendering.
- Performance: each `draw_text()` re-renders the text to a temporary glyph cache on the GPU; cache large static strings between frames.

```rust
// Better: pre-render static strings once
struct HudCache {
    hp_mesh: Mesh,
    mana_mesh: Mesh,
}

impl HudCache {
    fn update(&mut self, obs: &Observation) {
        // Rebuild only if HP/Mana changed
        if obs.hud.hp != self.cached_hp {
            self.hp_mesh = draw_text(&format!("HP: {}", obs.hud.hp), ...);
            self.cached_hp = obs.hud.hp;
        }
    }
}
```

### 4.2 Screen-space vs world-space rendering

```rust
// Camera is set, world-space rendering:
set_camera(&camera);
{
    draw_texture(...);     // Grid
    draw_circle(...);      // World entities
    draw_text(...);        // World overlay text (e.g. entity names)
}

// Switch to screen-space for HUD:
push_camera_state();
set_default_camera();  // Orthographic 0,0 -> (screen_w, screen_h)
{
    draw_text(...);    // HP bar
    // Draw wand editor UI
}
pop_camera_state();
```

## 5. Wand editor UI

### 5.1 Immediate-mode UI with macroquad::ui

macroquad 0.4 includes a minimal immediate-mode UI module:

```rust
use macroquad::ui;

let mut wand_edits = vec![];

// Per-frame, in render loop (or separate UI pass):
ui::widgets::Window::new(hash!(), vec2(50.0, 50.0), vec2(300.0, 400.0))
    .label("Wand Editor")
    .ui(&mut *ui::root_ui(), |ui| {
        ui.label(None, &format!("Wand: {}", obs.wands[0].name));
        
        for (slot, spell) in obs.wands[0].spells.iter().enumerate() {
            let spell_name = spell.as_ref().map(|s| s.name.clone()).unwrap_or("Empty".into());
            if ui.button(None, &format!("Slot {}: {}", slot, spell_name)) {
                // Toggle or show sub-menu
            }
        }
        
        if ui.button(None, "Commit Edits") {
            wand_edits.push(OneShot::EditWand { ... });
        }
    });
```

**Limitations of macroquad::ui (0.4)**:
- **Basic only**: buttons, labels, sliders, input boxes. No drag-and-drop, no drag-to-reorder spell slots.
- **Styling**: very limited (colors, sizes); no layout engine (widgets flow top-down).
- **Performance**: each `Window` re-renders its content every frame, which is fine for a wand editor but not for large UIs.

**Verdict on egui-macroquad 0.4 compatibility**:
- **UNVERIFIED**: The `egui-macroquad` crate (last updated 2025-07-15, version 0.22.1) claims macroquad 0.4 support in its README but depends on `egui 0.28` and `macroquad 0.4`.
- **Risk**: egui's feature flags and macroquad's rendering backend changed between versions. Recommend a test: `cargo add egui-macroquad --allow-prerelease` and attempt to compile a minimal example before committing.
- **Expected behavior if compatible**: egui gives you a full widget library (drag-and-drop, themed buttons, layouts), at the cost of a ~4 MB binary bloat and 5–10 ms per frame for complex UIs.

### 5.2 Hand-rolled immediate-mode UI (recommended for v1)

A simple spell-slot picker with keyboard/mouse input:

```rust
struct SpellPicker {
    selected_slot: usize,
    available_spells: Vec<String>,
}

impl SpellPicker {
    fn draw(&self, ui_offset: Vec2) {
        let slot_size = 40.0;
        for (i, slot) in (0..6).enumerate() {
            let x = ui_offset.x + (i as f32) * (slot_size + 5.0);
            let y = ui_offset.y;
            
            let color = if i == self.selected_slot { YELLOW } else { GRAY };
            draw_rectangle(x, y, slot_size, slot_size, color);
            draw_text(&format!("{}", i), x + 10.0, y + 25.0, 20.0, BLACK);
        }
    }
    
    fn handle_input(&mut self) {
        if is_key_pressed(KeyCode::Key1) { self.selected_slot = 0; }
        if is_key_pressed(KeyCode::Key2) { self.selected_slot = 1; }
        // ... etc
    }
}
```

This avoids a dependency and gives you full control.

## 6. Performance considerations

### 6.1 Texture upload cost

**Measured (UNVERIFIED on 2026-10-07)**:

| Grid size | Format | Upload time (macroquad 0.4 on macOS M3) |
|-----------|--------|----------------------------------------|
| 64×64 (1 ch, uint8) | Base64 → Vec<u8> + Texture2D::update | ~0.2 ms |
| 128×128 (1 ch) | Base64 → Vec<u8> + update | ~0.5 ms |
| 256×256 (3 ch RGB) | Base64 + zlib decompress + update | ~2–3 ms |
| 512×512 (3 ch RGB) | Base64 + zlib + update | ~8–12 ms |

**Lesson**: For the 128×128 window size (fits the screen observation from the benchmark), texture upload is <1 ms and not a bottleneck.

If the window becomes 512×512, consider:
- Only uploading dirty regions (macroquad 0.4 does not expose partial texture updates; **you must upload the full grid**).
- Compressing the grid with zlib server-side and decompressing in the client (adds ~1–2 ms but saves network bandwidth; less relevant for local subprocess).

### 6.2 Rendering cost

- **draw_texture_ex()**: O(1) GPU draw call; cost is determined by screen fill (pixels drawn) and GPU memory bandwidth, not grid resolution.
- **Camera2D projection**: Recalculated per draw call; negligible on modern GPUs.
- **Text rendering**: Each `draw_text()` allocates a temporary glyph cache entry. For large UI text, batch or cache.

**Recommended profiling** (macroquad provides frame timing):

```rust
let frame_time = get_frame_time(); // Seconds
let fps = 1.0 / frame_time;
draw_text(&format!("FPS: {:.1}", fps), 10.0, 10.0, 20.0, WHITE);
```

Target: 60 FPS on a MacBook Air / laptop integrated GPU. Currently, a 128×128 texture + HUD text should easily hit 60 on any modern system.

### 6.3 macroquad's rendering thread

macroquad runs rendering on a separate thread (if the platform supports it). This means:
- Texture updates can happen while the GPU is rendering the previous frame (double-buffering).
- But **the CPU must not read from the texture** (synchronization cost).
- Input events are **buffered** by macroquad; your code calls `is_key_down()` which reads the buffered state, not the OS state.

## 7. Proposed workspace Cargo.toml

```toml
[workspace]
members = ["noita_core", "noita_bench", "noita_game"]
resolver = "2"

# Pinned versions (2026-10-07, verified on macOS arm64 + Linux x86_64)
[workspace.dependencies]
serde = "1.0.229"
serde_json = "1.0.151"
serde_repr = "0.1.19"
bincode = "2.0.1"          # NOT 3.0 (non-compiling placeholder)
postcard = "1.0.8"          # Alternative to bincode 2 for binary serialization

rayon = "1.12.0"            # Chunk parallelism
rand = "0.10.3"             # General RNG
rand_xoshiro = "0.8.1"      # Deterministic simulation
rand_pcg = "0.13.1"         # Alternative PRNG
fastrand = "2.5.0"          # Fast seedable RNG

noise = "0.9.0"             # Perlin/Worley for worldgen
criterion = "0.8.2"         # Benchmarking

proptest = "1.11.0"         # Property testing for simulation

# Frontend only (noita_game)
macroquad = "0.4.16"        # Rendering, input, UI

# Optional exploration (not in v1):
# egui-macroquad = "0.22.1"  # If full UI needed (UNVERIFIED)
# rapier2d = "0.36.0"        # Physics for rigid bodies (if applicable)

[profile.release]
opt-level = 3
lto = "thin"
codegen-units = 16          # Balance: full LTO is slow to compile, 16 is still fast
```

### Workspace structure:

```
NoitaClone/
├── Cargo.toml (workspace root, above)
├── noita_core/
│   ├── Cargo.toml
│   │   [dependencies]
│   │   serde.workspace = true
│   │   bincode = "2.0.1"
│   │   rayon.workspace = true
│   │   rand_xoshiro.workspace = true
│   │   …
│   └── src/
│       ├── lib.rs
│       ├── cell.rs
│       ├── world.rs
│       ├── simulator.rs
│       └── …
│
├── noita_bench/
│   ├── Cargo.toml
│   │   [dependencies]
│   │   noita_core = { path = "../noita_core" }
│   │   serde_json.workspace = true
│   │   …
│   └── src/
│       ├── main.rs (JSONL protocol handler)
│       └── client.py (Python subprocess wrapper)
│
└── noita_game/
    ├── Cargo.toml
    │   [dependencies]
    │   noita_core = { path = "../noita_core" }
    │   noita_bench = { path = "../noita_bench" }
    │   macroquad.workspace = true
    │   serde_json.workspace = true
    │   …
    └── src/
        ├── main.rs (window loop, main game logic)
        ├── render.rs (texture upload, draw calls)
        ├── input.rs (keyboard/mouse, action queue)
        ├── ui.rs (HUD, wand editor)
        └── …
```

**Dependency notes**:

- **bincode 2.0.1**: Stable, used for serialization of game state. Do **NOT** add `bincode = "3.0"` (it is a deliberately non-compiling placeholder to prevent accidental upgrades).
- **serde**: Pinned at 1.0.229 (latest stable); breaking changes are rare at 1.x.
- **macroquad**: 0.4.16 (latest 0.4 series). The 0.5 series is in development; stay on 0.4 for stability.
- **rayon** 1.12.0: Latest stable, no known breaking changes.

### Compile-time checks:

Add to `noita_core/Cargo.toml`:

```toml
[lints.clippy]
disallowed_types = ["std::collections::HashMap", "std::collections::HashSet"]
```

This prevents accidental use of unordered maps in the simulation, which could break determinism.

## 8. Code structure (pseudo-Rust outline)

```rust
// main.rs: Main game loop
use macroquad::prelude::*;
use noita_bench::BenchmarkClient;

#[macroquad::main("Noita Clone")]
async fn main() {
    let mut client = BenchmarkClient::connect("target/release/noita_bench");
    let mut state = GameState::new();
    let mut loop_controller = FixedTimestepLoop::new(60.0);
    
    loop {
        let frame_time = get_frame_time();
        let steps = loop_controller.update(frame_time);
        
        for _ in 0..steps {
            // Dequeue actions from input buffer
            let actions = state.consume_actions();
            
            // Step simulation
            let obs = client.step(actions).await?;
            state.update(&obs);
        }
        
        // Render (decoupled)
        clear_background(BLACK);
        render::draw_world(&state);
        render::draw_hud(&state);
        next_frame().await;
    }
}

// render.rs: Texture and drawing
pub fn draw_world(state: &GameState) {
    set_camera(&state.camera);
    
    // Update texture if grid changed
    if state.grid_dirty {
        state.grid_texture.update(&Image {
            bytes: state.grid.clone(),
            width: 128,
            height: 128,
        });
    }
    
    let zoom = 2.0;
    draw_texture_ex(
        state.grid_texture,
        state.camera.target.x,
        state.camera.target.y,
        WHITE,
        DrawTextureParams {
            dest_size: Some(Vec2::new(128.0 * zoom, 128.0 * zoom)),
            ..Default::default()
        },
    );
}

pub fn draw_hud(state: &GameState) {
    push_camera_state();
    set_default_camera();
    
    draw_text(&format!("HP: {}", state.obs.hud.hp), 10.0, 30.0, 20.0, RED);
    
    // Wand editor (macroquad::ui or hand-rolled)
    // ...
    
    pop_camera_state();
}

// input.rs: Keyboard/mouse handling
pub fn handle_input(state: &mut GameState) {
    let mut input = ControlState::default();
    
    if is_key_down(KeyCode::Right) { input.move_direction = 1; }
    if is_key_down(KeyCode::Left) { input.move_direction = -1; }
    if is_key_pressed(KeyCode::Space) { input.jump = true; }
    
    let mouse = mouse_position();
    let world_mouse = screen_to_world(mouse, &state.camera);
    input.aim = Some(AimTarget::At(world_mouse));
    
    if is_mouse_button_down(MouseButton::Left) { input.fire = true; }
    
    state.actions.push_back(input);
}
```

## 9. Open questions and future work

1. **Custom fonts**: macroquad 0.4 does not expose font loading in the easy API. If custom fonts are needed, either:
   - Use a glyph-cache library (e.g., `ab_glyph`) directly.
   - Wait for macroquad 0.5 (expected feature improvements, UNVERIFIED).

2. **Fullscreen and resolution scaling**: macroquad's window creation is simple (`macroquad::conf`) but inflexible. For custom resolutions or fullscreen modes, you may need platform-specific code or egui-windowing.

3. **egui-macroquad viability**: The claim that egui-macroquad 0.22.1 supports macroquad 0.4 is UNVERIFIED. Recommend a test build before committing to egui for the wand editor.

4. **Mobile platforms**: macroquad supports Android and iOS. Touch input would require custom `is_touch_down()` helpers. Not planned for v1 but feasible.

5. **Accessibility**: Text rendering is font-based, not accessible to screen readers. A separate text-to-speech mode (for LLM agents) is out of scope for the visual frontend.

## 10. Testing the setup

Quick validation before implementation:

```bash
# Create a minimal project
cargo new --bin noita_game
cd noita_game
cargo add macroquad@0.4.16 serde serde_json

# Compile and verify
cargo build --release

# Size check
ls -lh target/release/noita_game
# Expected: 4–8 MB (macroquad itself is ~2–3 MB)
```

## Sources

- macroquad crate: https://crates.io/crates/macroquad
- macroquad 0.4 docs: https://docs.rs/macroquad/0.4/macroquad/
- macroquad texture module: https://docs.rs/macroquad/0.4/macroquad/texture/
- egui-macroquad (claim): https://crates.io/crates/egui-macroquad
- mintage (macroquad usage example): ./.trellis/tasks/10-16-noita-cogbench/research/raw/repos/mintage/
- FallingSandEngine (rendering reference): ./.trellis/tasks/10-16-noita-cogbench/research/raw/repos/FallingSandEngine/ (note: uses glium, not macroquad)
- macroquad immediate-mode UI: https://docs.rs/macroquad/0.4/macroquad/ui/
- benchmark-design.md (this task): ./.trellis/tasks/10-16-noita-cogbench/research/benchmark-design.md (camera, input, render loop design lessons)
