//! `World` operations around the frame pipeline: the event log, editing between frames,
//! inspection and recording.

use crate::consts::{BOUNDARY, MAX_BUFFERED_EVENTS, MAX_PAINT_EXTENT};
use crate::error::{Error, Result};
use crate::event::Event;
use crate::grid::Rect;
use crate::record::{RecordConfig, RecordSummary, Recorder};
use crate::world::{CellInfo, World};

impl World {
    // ----- events -----------------------------------------------------------------------------

    pub(crate) fn emit(&mut self, ev: Event) {
        if let Some(rec) = self.recorder.as_mut() {
            rec.write_event(&ev.to_json_line(&self.content));
        }
        if self.events.len() < MAX_BUFFERED_EVENTS {
            self.events.push(ev);
        } else {
            self.events_dropped += 1;
        }
    }

    /// Log a fact of the game layer (`Event::Game`) at the current frame. `fields` must not use
    /// the names `frame` or `type`.
    pub fn log_event(
        &mut self,
        kind: &'static str,
        fields: Vec<(&'static str, crate::event::Value)>,
    ) {
        let frame = self.frame;
        self.emit(Event::Game {
            frame,
            kind,
            fields,
        });
    }

    /// Events since the last call, oldest first.
    pub fn drain_events(&mut self) -> Vec<Event> {
        let mut out = std::mem::take(&mut self.events);
        if self.events_dropped > 0 {
            out.push(Event::Overflow {
                frame: self.frame,
                dropped: self.events_dropped,
            });
            self.events_dropped = 0;
        }
        out
    }

    // ----- editing between frames -------------------------------------------------------------

    fn material_index(&self, key: &str) -> Result<u8> {
        self.content.mats.index_of(key).ok_or_else(|| {
            Error::arg(format!(
                "unknown material `{key}`; known: {}",
                self.known_keys()
            ))
        })
    }

    fn known_keys(&self) -> String {
        self.content
            .mats
            .iter()
            .map(|m| m.key.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    }

    /// Paint a filled disc (`dx² + dy² <= radius²`) of a material, clipped to the world.
    pub fn paint(&mut self, x: i32, y: i32, radius: i32, key: &str) -> Result<()> {
        let limit = MAX_PAINT_EXTENT as u32;
        if !(0..=MAX_PAINT_EXTENT).contains(&radius)
            || x.unsigned_abs() > limit
            || y.unsigned_abs() > limit
        {
            return Err(Error::arg(format!(
                "radius must be 0..={MAX_PAINT_EXTENT} and the centre within {MAX_PAINT_EXTENT} of the origin, got ({x}, {y}) r={radius}"
            )));
        }
        let mat = self.material_index(key)?;
        let mut touched = Rect::EMPTY;
        for yy in (y - radius).max(0)..=(y + radius).min(self.height() - 1) {
            for xx in (x - radius).max(0)..=(x + radius).min(self.width() - 1) {
                let (dx, dy) = (i64::from(xx - x), i64::from(yy - y));
                if dx * dx + dy * dy <= i64::from(radius) * i64::from(radius) {
                    self.put_material(xx, yy, mat);
                    touched.add_point(xx, yy);
                }
            }
        }
        self.grid.wake_rect(touched);
        Ok(())
    }

    /// Fill the rectangle `[x, x + w) × [y, y + h)` with a material, clipped to the world.
    pub fn fill_rect(&mut self, x: i32, y: i32, w: i32, h: i32, key: &str) -> Result<()> {
        let limit = MAX_PAINT_EXTENT as u32;
        if w < 0 || h < 0 || [x, y, w, h].iter().any(|v| v.unsigned_abs() > limit) {
            return Err(Error::arg(format!(
                "x, y, width, height must be within {MAX_PAINT_EXTENT} and width, height >= 0, got x={x} y={y} {w}x{h}"
            )));
        }
        let mat = self.material_index(key)?;
        let mut touched = Rect::EMPTY;
        for yy in y.max(0)..(y + h).min(self.height()) {
            for xx in x.max(0)..(x + w).min(self.width()) {
                self.put_material(xx, yy, mat);
                touched.add_point(xx, yy);
            }
        }
        self.grid.wake_rect(touched);
        Ok(())
    }

    fn put_material(&mut self, x: i32, y: i32, mat: u8) {
        let cell = self.make_cell(mat, (y * self.width() + x) as u32);
        self.grid.put_quiet(x, y, cell);
    }

    /// Put a cell of material index `mat` at `(x, y)` between frames (spills, trails, emitted
    /// particles). With `burning` a burnable material starts alight. Returns `false` when the
    /// position is outside the world or `mat` is not a material of the content set.
    pub fn set_cell(&mut self, x: i32, y: i32, mat: u8, burning: bool) -> bool {
        if !self.grid.in_bounds(x, y) || usize::from(mat) >= self.content.mats.len() {
            return false;
        }
        let mut cell = self.make_cell(mat, (y * self.width() + x) as u32);
        let rt = self.content.mats.rt(mat);
        if burning && mat != 0 && rt.burnable {
            cell.flags |= crate::grid::BURNING;
            cell.burn = rt.burn0;
        }
        self.grid.put_quiet(x, y, cell);
        self.grid.wake_rect(Rect {
            x0: x,
            y0: y,
            x1: x,
            y1: y,
        });
        true
    }

    /// Set a burnable cell alight from outside (a spark, a test). Returns `false` if the cell is
    /// empty, not burnable or already burning.
    pub fn ignite(&mut self, x: i32, y: i32) -> bool {
        if !self.grid.in_bounds(x, y) {
            return false;
        }
        let cell = self.grid.get(x, y);
        let rt = self.content.mats.rt(cell.mat);
        if cell.mat == 0 || !rt.burnable || cell.burning() {
            return false;
        }
        let mut c = cell;
        c.flags |= crate::grid::BURNING;
        c.burn = rt.burn0;
        self.grid.put_quiet(x, y, c);
        self.grid.wake_rect(Rect {
            x0: x,
            y0: y,
            x1: x,
            y1: y,
        });
        true
    }

    // ----- inspection -------------------------------------------------------------------------

    /// Material index of every cell, row-major.
    pub fn grid_bytes(&self) -> Vec<u8> {
        self.grid.cells().iter().map(|c| c.mat).collect()
    }

    pub fn cell_info(&self, x: i32, y: i32) -> Option<CellInfo> {
        if !self.grid.in_bounds(x, y) {
            return None;
        }
        let c = self.grid.get(x, y);
        debug_assert_ne!(c.mat, BOUNDARY);
        let rt = self.content.mats.rt(c.mat);
        Some(CellInfo {
            material: c.mat,
            key: self.content.mats.key_of(c.mat).to_string(),
            burning: c.burning(),
            lifetime: u32::from(c.life) * u32::from(rt.life_unit),
        })
    }

    /// FNV-1a over everything that defines the state: frame, seed, cells, pending explosions.
    pub fn state_hash(&self) -> u64 {
        let mut h = 0xcbf2_9ce4_8422_2325u64;
        let mut eat = |bytes: &[u8]| {
            for b in bytes {
                h ^= u64::from(*b);
                h = h.wrapping_mul(0x0000_0100_0000_01b3);
            }
        };
        eat(&self.frame.to_le_bytes());
        eat(&self.seed.to_le_bytes());
        for c in self.grid.cells() {
            eat(&[c.mat, c.life, c.burn, c.flags & !crate::grid::UPDATED]);
        }
        for e in &self.queue {
            eat(&e.id.to_le_bytes());
            eat(&e.x.to_le_bytes());
            eat(&e.y.to_le_bytes());
            eat(&e.radius.to_le_bytes());
        }
        h
    }

    // ----- recording --------------------------------------------------------------------------

    pub fn start_recording(&mut self, config: RecordConfig) -> Result<()> {
        if self.recorder.is_some() {
            return Err(Error::arg("a recording is already running; stop it first"));
        }
        let mut rec = Recorder::start(
            config,
            self.width(),
            self.height(),
            self.seed,
            self.rule_seed,
        )?;
        rec.write_frame(self.frame, &self.grid);
        rec.check()?;
        self.recorder = Some(rec);
        Ok(())
    }

    pub fn stop_recording(&mut self) -> Result<RecordSummary> {
        let mut rec = self
            .recorder
            .take()
            .ok_or_else(|| Error::arg("no recording is running"))?;
        if rec.last_frame() != Some(self.frame) {
            rec.write_frame(self.frame, &self.grid);
        }
        rec.finish()
    }

    pub fn is_recording(&self) -> bool {
        self.recorder.is_some()
    }

    pub(crate) fn record_after_step(&mut self) -> Result<()> {
        if let Some(rec) = self.recorder.as_mut() {
            if self.frame.is_multiple_of(u64::from(rec.stride())) {
                rec.write_frame(self.frame, &self.grid);
            }
            rec.check()?;
        }
        Ok(())
    }
}
