//! The cell grid, 64×64 chunks and their dirty rectangles (SIM-R03, SIM-R10..R15).

use crate::consts::{BOUNDARY, CHUNK, WAKE};

pub const UPDATED: u8 = 1;
pub const BURNING: u8 = 2;
/// Lateral preference of liquids and gases: set = right, clear = left.
pub const DIR: u8 = 4;

/// One grid cell. Four bytes: material index, remaining lifetime, remaining fuel, flags.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
#[repr(C)]
pub struct Cell {
    pub mat: u8,
    /// Remaining lifetime in `life_unit` frames; 0 = no timer.
    pub life: u8,
    /// Remaining fuel in `burn_unit` frames; only meaningful while `BURNING`.
    pub burn: u8,
    pub flags: u8,
}

impl Cell {
    pub const AIR: Cell = Cell {
        mat: 0,
        life: 0,
        burn: 0,
        flags: 0,
    };
    pub const OUTSIDE: Cell = Cell {
        mat: BOUNDARY,
        life: 0,
        burn: 0,
        flags: 0,
    };

    #[inline]
    pub fn burning(self) -> bool {
        self.flags & BURNING != 0
    }
}

/// Inclusive rectangle of cells; empty when `x0 > x1`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rect {
    pub x0: i32,
    pub y0: i32,
    pub x1: i32,
    pub y1: i32,
}

impl Rect {
    pub const EMPTY: Rect = Rect {
        x0: i32::MAX,
        y0: i32::MAX,
        x1: i32::MIN,
        y1: i32::MIN,
    };

    #[inline]
    pub fn is_empty(&self) -> bool {
        self.x0 > self.x1 || self.y0 > self.y1
    }

    #[inline]
    pub fn add_point(&mut self, x: i32, y: i32) {
        self.x0 = self.x0.min(x);
        self.y0 = self.y0.min(y);
        self.x1 = self.x1.max(x);
        self.y1 = self.y1.max(y);
    }

    pub fn union(&mut self, o: &Rect) {
        if o.is_empty() {
            return;
        }
        self.x0 = self.x0.min(o.x0);
        self.y0 = self.y0.min(o.y0);
        self.x1 = self.x1.max(o.x1);
        self.y1 = self.y1.max(o.y1);
    }

    pub fn dilate(&self, d: i32) -> Rect {
        Rect {
            x0: self.x0 - d,
            y0: self.y0 - d,
            x1: self.x1 + d,
            y1: self.y1 + d,
        }
    }

    pub fn intersect(&self, o: &Rect) -> Rect {
        Rect {
            x0: self.x0.max(o.x0),
            y0: self.y0.max(o.y0),
            x1: self.x1.min(o.x1),
            y1: self.y1.min(o.y1),
        }
    }

    pub fn contains(&self, x: i32, y: i32) -> bool {
        x >= self.x0 && x <= self.x1 && y >= self.y0 && y <= self.y1
    }
}

/// A chunk's live rectangle ([`Grid::live_rect`]), recomputed only when something was written
/// since the last look.
pub(crate) struct LiveRect {
    cx: i32,
    cy: i32,
    rect: Rect,
    seen: u64,
}

impl LiveRect {
    pub(crate) fn new(grid: &Grid, cx: i32, cy: i32) -> LiveRect {
        LiveRect {
            cx,
            cy,
            rect: grid.live_rect(cx, cy),
            seen: grid.writes,
        }
    }

    pub(crate) fn get(&mut self, grid: &Grid) -> Rect {
        if self.seen != grid.writes {
            self.rect = grid.live_rect(self.cx, self.cy);
            self.seen = grid.writes;
        }
        self.rect
    }
}

#[derive(Clone, Debug)]
pub(crate) struct ChunkState {
    /// Cells to visit this frame (world coordinates, inside the chunk).
    pub dirty: Rect,
    /// Bounding box of cells written during this frame's passes.
    pub wbox: Rect,
    /// Bounding box of cells that asked to stay awake.
    pub abox: Rect,
}

/// The world grid. All writes go through `set`, `swap`, `modify` (inside a frame) or the
/// `put_*` functions (between frames) so the dirty bookkeeping cannot be bypassed.
#[derive(Clone, Debug)]
pub struct Grid {
    w: i32,
    h: i32,
    cw: i32,
    ch: i32,
    cells: Vec<Cell>,
    pub(crate) chunks: Vec<ChunkState>,
    next: Vec<Rect>,
    /// Number of `set`, `swap` and `modify` calls so far: lets a scan notice that nothing has
    /// been written since it last looked (see [`LiveRect`]).
    writes: u64,
}

impl Grid {
    pub fn new(w: i32, h: i32) -> Grid {
        let cw = (w + CHUNK - 1) / CHUNK;
        let ch = (h + CHUNK - 1) / CHUNK;
        let n = (cw * ch) as usize;
        Grid {
            w,
            h,
            cw,
            ch,
            cells: vec![Cell::AIR; (w * h) as usize],
            chunks: vec![
                ChunkState {
                    dirty: Rect::EMPTY,
                    wbox: Rect::EMPTY,
                    abox: Rect::EMPTY,
                };
                n
            ],
            next: vec![Rect::EMPTY; n],
            writes: 0,
        }
    }

    #[inline]
    pub fn width(&self) -> i32 {
        self.w
    }

    #[inline]
    pub fn height(&self) -> i32 {
        self.h
    }

    /// Chunk grid size.
    #[inline]
    pub fn chunk_dims(&self) -> (i32, i32) {
        (self.cw, self.ch)
    }

    #[inline]
    pub fn in_bounds(&self, x: i32, y: i32) -> bool {
        (x as u32) < (self.w as u32) && (y as u32) < (self.h as u32)
    }

    #[inline]
    pub fn idx(&self, x: i32, y: i32) -> usize {
        (y * self.w + x) as usize
    }

    #[inline]
    pub fn get(&self, x: i32, y: i32) -> Cell {
        if self.in_bounds(x, y) {
            self.cells[(y * self.w + x) as usize]
        } else {
            Cell::OUTSIDE
        }
    }

    /// Direct access for in-place counter updates that need no wake-up (timers, fuel).
    #[inline]
    pub(crate) fn cell_mut(&mut self, x: i32, y: i32) -> &mut Cell {
        let i = (y * self.w + x) as usize;
        &mut self.cells[i]
    }

    pub fn cells(&self) -> &[Cell] {
        &self.cells
    }

    pub(crate) fn cells_mut_raw(&mut self) -> &mut [Cell] {
        &mut self.cells
    }

    #[inline]
    fn chunk_of(&self, x: i32, y: i32) -> usize {
        ((y / CHUNK) * self.cw + x / CHUNK) as usize
    }

    /// Rectangle of cells a chunk covers (clipped to the world).
    pub fn chunk_rect(&self, cx: i32, cy: i32) -> Rect {
        Rect {
            x0: cx * CHUNK,
            y0: cy * CHUNK,
            x1: ((cx + 1) * CHUNK).min(self.w) - 1,
            y1: ((cy + 1) * CHUNK).min(self.h) - 1,
        }
    }

    pub fn dirty_rect(&self, cx: i32, cy: i32) -> Rect {
        self.chunks[(cy * self.cw + cx) as usize].dirty
    }

    /// The cells chunk `(cx, cy)` has to visit *now*: its dirty rectangle plus the `WAKE`
    /// neighbourhood of every write made so far this frame, in the chunk itself and in the eight
    /// chunks around it (SIM-R11, SIM-R72).
    ///
    /// The dirty rectangle is fixed at the start of the frame, but a visit can change what a
    /// later visit finds: a liquid hopping left leaves a gap for its right-hand neighbour, which
    /// hops in turn, and so on along the row, and a whole column of sand falls as a train. Such a
    /// cascade can run past the rectangle. A cell it reaches would have been visited with every
    /// cell awake, so it must be visited here too, or the two modes diverge.
    pub(crate) fn live_rect(&self, cx: i32, cy: i32) -> Rect {
        let me = self.chunk_rect(cx, cy);
        let mut r = self.chunks[(cy * self.cw + cx) as usize].dirty;
        for ny in (cy - 1).max(0)..=(cy + 1).min(self.ch - 1) {
            for nx in (cx - 1).max(0)..=(cx + 1).min(self.cw - 1) {
                let written = self.chunks[(ny * self.cw + nx) as usize].wbox;
                if !written.is_empty() {
                    r.union(&written.dilate(WAKE).intersect(&me));
                }
            }
        }
        r
    }

    // ----- writes inside a frame -------------------------------------------------------------

    /// Write a cell during a frame: raises `UPDATED` and records the write (SIM-R13, SIM-R15).
    #[inline]
    pub fn set(&mut self, x: i32, y: i32, mut cell: Cell) {
        debug_assert!(self.in_bounds(x, y));
        cell.flags |= UPDATED;
        self.writes += 1;
        let i = (y * self.w + x) as usize;
        self.cells[i] = cell;
        let c = self.chunk_of(x, y);
        self.chunks[c].wbox.add_point(x, y);
    }

    /// Exchange two cells (matter is conserved); both are marked `UPDATED`.
    #[inline]
    pub fn swap(&mut self, x1: i32, y1: i32, x2: i32, y2: i32) {
        debug_assert!(self.in_bounds(x1, y1) && self.in_bounds(x2, y2));
        self.writes += 1;
        let (i1, i2) = ((y1 * self.w + x1) as usize, (y2 * self.w + x2) as usize);
        self.cells.swap(i1, i2);
        self.cells[i1].flags |= UPDATED;
        self.cells[i2].flags |= UPDATED;
        let (c1, c2) = (self.chunk_of(x1, y1), self.chunk_of(x2, y2));
        self.chunks[c1].wbox.add_point(x1, y1);
        self.chunks[c2].wbox.add_point(x2, y2);
    }

    /// Change a cell in place during a frame (flags, counters) and record the write.
    #[inline]
    pub fn modify(&mut self, x: i32, y: i32, f: impl FnOnce(&mut Cell)) {
        self.writes += 1;
        let i = (y * self.w + x) as usize;
        f(&mut self.cells[i]);
        self.cells[i].flags |= UPDATED;
        let c = self.chunk_of(x, y);
        self.chunks[c].wbox.add_point(x, y);
    }

    /// The cell at `(x, y)` could still change by itself: visit it again next frame (SIM-R12).
    #[inline]
    pub fn keep_awake(&mut self, x: i32, y: i32) {
        let c = self.chunk_of(x, y);
        self.chunks[c].abox.add_point(x, y);
    }

    // ----- writes between frames -------------------------------------------------------------

    /// Write a cell outside the frame passes: no `UPDATED`, no dirty bookkeeping. Follow a batch
    /// of these with [`Grid::wake_rect`].
    #[inline]
    pub fn put_quiet(&mut self, x: i32, y: i32, cell: Cell) {
        debug_assert!(self.in_bounds(x, y));
        let i = (y * self.w + x) as usize;
        self.cells[i] = cell;
    }

    /// Make every chunk overlapping `rect` dilated by `WAKE` visit that area in the coming frame.
    pub fn wake_rect(&mut self, rect: Rect) {
        if rect.is_empty() {
            return;
        }
        let world = Rect {
            x0: 0,
            y0: 0,
            x1: self.w - 1,
            y1: self.h - 1,
        };
        let r = rect.dilate(WAKE).intersect(&world);
        if r.is_empty() {
            return;
        }
        for cy in r.y0 / CHUNK..=r.y1 / CHUNK {
            for cx in r.x0 / CHUNK..=r.x1 / CHUNK {
                let piece = r.intersect(&self.chunk_rect(cx, cy));
                self.chunks[(cy * self.cw + cx) as usize]
                    .dirty
                    .union(&piece);
            }
        }
    }

    /// Mark the whole world dirty (restore into a fresh state, test mode).
    pub fn set_all_dirty(&mut self) {
        for cy in 0..self.ch {
            for cx in 0..self.cw {
                let r = self.chunk_rect(cx, cy);
                self.chunks[(cy * self.cw + cx) as usize].dirty = r;
            }
        }
    }

    /// End of frame: clear `UPDATED`, turn this frame's write and awake boxes into the next
    /// frame's dirty rectangles (SIM-R13).
    pub fn end_frame(&mut self) {
        self.next.fill(Rect::EMPTY);
        let world = Rect {
            x0: 0,
            y0: 0,
            x1: self.w - 1,
            y1: self.h - 1,
        };
        for c in 0..self.chunks.len() {
            let wbox = self.chunks[c].wbox;
            let abox = self.chunks[c].abox;
            if !wbox.is_empty() {
                self.clear_updated(&wbox);
                let r = wbox.dilate(WAKE).intersect(&world);
                for cy in r.y0 / CHUNK..=r.y1 / CHUNK {
                    for cx in r.x0 / CHUNK..=r.x1 / CHUNK {
                        let piece = r.intersect(&self.chunk_rect(cx, cy));
                        self.next[(cy * self.cw + cx) as usize].union(&piece);
                    }
                }
            }
            self.next[c].union(&abox);
        }
        for (chunk, next) in self.chunks.iter_mut().zip(&self.next) {
            chunk.dirty = *next;
            chunk.wbox = Rect::EMPTY;
            chunk.abox = Rect::EMPTY;
        }
    }

    fn clear_updated(&mut self, r: &Rect) {
        for y in r.y0..=r.y1 {
            let row = (y * self.w) as usize;
            for cell in &mut self.cells[row + r.x0 as usize..=row + r.x1 as usize] {
                cell.flags &= !UPDATED;
            }
        }
    }
}
