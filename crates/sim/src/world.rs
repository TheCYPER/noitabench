//! The world: grid, content, frame counter, event log and the frame pipeline (SIM-R80).

use crate::consts::MAX_WORLD_EDGE;
use crate::content::Content;
use crate::error::{Error, Result};
use crate::event::Event;
use crate::grid::{Cell, Grid, LiveRect};
use crate::record::Recorder;
use crate::rng::{frame_key, stream_seed, CellRng};
use std::sync::Arc;

/// Pass index used for random draws that create a cell (timer jitter).
pub(crate) const PASS_CREATE: u8 = 8;

/// Test switch: normal operation visits dirty rectangles only.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DirtyMode {
    Normal,
    /// Visit every cell every frame (used to check that sleeping cells really have nothing to do).
    AllDirty,
}

/// An explosion waiting for the explosion phase of the next frame.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Explosion {
    pub id: u64,
    pub x: i32,
    pub y: i32,
    pub radius: u32,
    pub ray_energy: u32,
    pub max_durability: u8,
    pub fire_percent: u8,
}

/// Description of one cell for inspection.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CellInfo {
    pub material: u8,
    pub key: String,
    pub burning: bool,
    /// Remaining timer in frames (0 when the material has none).
    pub lifetime: u32,
}

pub struct World {
    pub(crate) content: Arc<Content>,
    pub(crate) grid: Grid,
    pub(crate) seed: u64,
    pub(crate) rule_seed: u64,
    pub(crate) cell_seed: u64,
    pub(crate) frame: u64,
    /// `frame_key(cell_seed, frame)`, kept in sync with `frame`.
    pub(crate) fkey: u64,
    pub(crate) events: Vec<Event>,
    pub(crate) events_dropped: u64,
    pub(crate) queue: Vec<Explosion>,
    pub(crate) next_explosion_id: u64,
    pub(crate) recorder: Option<Recorder>,
    pub(crate) dirty_mode: DirtyMode,
}

impl World {
    /// An empty (all air) world.
    pub fn new(width: i32, height: i32, seed: u64, content: Arc<Content>) -> Result<World> {
        if !(1..=MAX_WORLD_EDGE).contains(&width) || !(1..=MAX_WORLD_EDGE).contains(&height) {
            return Err(Error::arg(format!(
                "world size must be 1..={MAX_WORLD_EDGE} cells per side, got {width}x{height}"
            )));
        }
        let cell_seed = stream_seed(seed, "cells");
        Ok(World {
            content,
            grid: Grid::new(width, height),
            seed,
            rule_seed: 0,
            cell_seed,
            frame: 0,
            fkey: frame_key(cell_seed, 0),
            events: Vec::new(),
            events_dropped: 0,
            queue: Vec::new(),
            next_explosion_id: 0,
            recorder: None,
            dirty_mode: DirtyMode::Normal,
        })
    }

    /// A world from raw material indices (row-major, `width * height` bytes).
    pub fn from_indices(
        width: i32,
        height: i32,
        seed: u64,
        indices: &[u8],
        content: Arc<Content>,
    ) -> Result<World> {
        let mut w = World::new(width, height, seed, content)?;
        if indices.len() != (width * height) as usize {
            return Err(Error::arg(format!(
                "expected {} material indices for {width}x{height}, got {}",
                width * height,
                indices.len()
            )));
        }
        let n = w.content.mats.len();
        for (i, &m) in indices.iter().enumerate() {
            if usize::from(m) >= n {
                return Err(Error::arg(format!(
                    "material index {m} at cell ({}, {}) is not in the content set ({n} materials)",
                    i as i32 % width,
                    i as i32 / width
                )));
            }
        }
        for y in 0..height {
            for x in 0..width {
                let m = indices[(y * width + x) as usize];
                let cell = w.make_cell(m, (y * width + x) as u32);
                w.grid.put_quiet(x, y, cell);
            }
        }
        w.grid.set_all_dirty();
        Ok(w)
    }

    pub fn width(&self) -> i32 {
        self.grid.width()
    }

    pub fn height(&self) -> i32 {
        self.grid.height()
    }

    pub fn frame(&self) -> u64 {
        self.frame
    }

    pub fn seed(&self) -> u64 {
        self.seed
    }

    pub fn rule_seed(&self) -> u64 {
        self.rule_seed
    }

    pub fn set_rule_seed(&mut self, rule_seed: u64) {
        self.rule_seed = rule_seed;
    }

    pub fn content(&self) -> &Arc<Content> {
        &self.content
    }

    pub fn grid(&self) -> &Grid {
        &self.grid
    }

    pub fn set_dirty_mode(&mut self, mode: DirtyMode) {
        self.dirty_mode = mode;
        if mode == DirtyMode::AllDirty {
            self.grid.set_all_dirty();
        }
    }

    pub fn pending_explosions(&self) -> &[Explosion] {
        &self.queue
    }

    /// A new cell of material `mat` with its timer set up (SIM-R35). `index` only feeds the
    /// stateless jitter draw.
    pub(crate) fn make_cell(&self, mat: u8, index: u32) -> Cell {
        let rt = self.content.mats.rt(mat);
        let mut life = 0;
        if rt.life_unit != 0 {
            let mut rng = CellRng::new(self.fkey, PASS_CREATE, index);
            life = if rt.kind == crate::material::Kind::Fire {
                let t = &self.content.tuning;
                let span = u32::from(t.fire_life_max - t.fire_life_min) + 1;
                (u32::from(t.fire_life_min) + rng.below(span)) as u8
            } else {
                let l0 = u32::from(rt.life0);
                let d = l0 * u32::from(self.content.tuning.life_jitter_pct) / 100;
                let jitter = if d == 0 { 0 } else { rng.below(2 * d + 1) };
                (l0 + jitter - d).clamp(1, 255) as u8
            };
        }
        Cell {
            mat,
            life,
            burn: 0,
            flags: 0,
        }
    }

    // ----- frame pipeline ---------------------------------------------------------------------

    /// Advance one frame: explosion phase, four cell passes, end-of-frame bookkeeping.
    pub fn step(&mut self) -> Result<()> {
        let content = Arc::clone(&self.content);
        if self.dirty_mode == DirtyMode::AllDirty {
            self.grid.set_all_dirty();
        }
        self.run_explosion_phase();
        for (pass, class) in pass_order(self.frame).into_iter().enumerate() {
            self.run_pass(&content, pass as u8, class);
        }
        self.grid.end_frame();
        self.frame += 1;
        self.fkey = frame_key(self.cell_seed, self.frame);
        self.record_after_step()
    }

    pub fn step_frames(&mut self, n: u32) -> Result<()> {
        for _ in 0..n {
            self.step()?;
        }
        Ok(())
    }

    fn run_pass(&mut self, ct: &Content, pass: u8, class: (i32, i32)) {
        let (cw, ch) = self.grid.chunk_dims();
        let mut cy = class.1;
        while cy < ch {
            let mut cx = class.0;
            while cx < cw {
                self.visit_chunk(ct, pass, cx, cy);
                cx += 2;
            }
            cy += 2;
        }
    }

    /// Rows bottom-up, columns in a direction that alternates with `(frame + cx + cy)` (SIM-R20).
    ///
    /// The visit rectangle is the chunk's live rectangle (`Grid::live_rect`), read again before
    /// every row (so a row that wrote near the top edge makes the rows above it count, the last
    /// row included) and whenever a row runs past its end, so that a cascade of moves which
    /// starts inside the rectangle and runs out of it is followed (SIM-R72). Cells behind the
    /// scan position are never revisited: with every cell awake they would not be either.
    fn visit_chunk(&mut self, ct: &Content, pass: u8, cx: i32, cy: i32) {
        let mut live = LiveRect::new(&self.grid, cx, cy);
        let first = live.get(&self.grid);
        if first.is_empty() {
            return;
        }
        let left_to_right = scan_left_to_right(self.frame, cx, cy);
        let mut y = first.y1;
        loop {
            let r = live.get(&self.grid);
            if y < r.y0 {
                break;
            }
            if left_to_right {
                let (mut x, mut end) = (r.x0, r.x1);
                while x <= end {
                    self.visit(ct, x, y, pass);
                    x += 1;
                    if x > end {
                        end = live.get(&self.grid).x1; // the row may have grown
                    }
                }
            } else {
                let (mut x, mut end) = (r.x1, r.x0);
                while x >= end {
                    self.visit(ct, x, y, pass);
                    x -= 1;
                    if x < end {
                        end = live.get(&self.grid).x0;
                    }
                }
            }
            y -= 1;
        }
    }
}

/// Pass order of a frame: the classes rotate so no class is always first (SIM-R21).
pub fn pass_order(frame: u64) -> [(i32, i32); 4] {
    const CLASSES: [(i32, i32); 4] = [(0, 0), (1, 0), (0, 1), (1, 1)];
    let k = (frame % 4) as usize;
    [
        CLASSES[k % 4],
        CLASSES[(k + 1) % 4],
        CLASSES[(k + 2) % 4],
        CLASSES[(k + 3) % 4],
    ]
}

/// Column direction inside a chunk for this frame (SIM-R20): `true` = left to right.
pub fn scan_left_to_right(frame: u64, cx: i32, cy: i32) -> bool {
    (frame as i64 + i64::from(cx) + i64::from(cy)) & 1 == 0
}
