//! Snapshot and restore of the full simulation state (SIM-R78, bit-exact).
//!
//! Layout (little endian): magic, content hash, seed, rule seed, width, height, frame, next
//! explosion id, the explosion queue, the dirty rectangle of every chunk, then the cells,
//! zlib-compressed. The dirty rectangles are part of the state: restoring them (instead of
//! waking everything) is what makes "snapshot, restore, continue" identical to an
//! uninterrupted run. The event buffer and a running recording are not state and are not saved.

use crate::consts::MAX_EXPLOSION_RADIUS;
use crate::error::{Error, Result};
use crate::grid::{Cell, Grid, Rect};
use crate::rng::{frame_key, stream_seed};
use crate::world::{Explosion, World};
use flate2::read::ZlibDecoder;
use flate2::write::ZlibEncoder;
use flate2::Compression;
use std::io::{Read, Write};

const MAGIC: &[u8; 8] = b"CGBSNAP1";

struct Reader<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        let end = self.pos.checked_add(n).filter(|&e| e <= self.buf.len());
        let end = end.ok_or_else(|| Error::Snapshot("truncated".into()))?;
        let s = &self.buf[self.pos..end];
        self.pos = end;
        Ok(s)
    }

    fn u8(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }

    fn u32(&mut self) -> Result<u32> {
        // `take(4)` returns exactly 4 bytes, so the conversion cannot fail.
        Ok(u32::from_le_bytes(
            self.take(4)?.try_into().expect("take(4) yields 4 bytes"),
        ))
    }

    fn i32(&mut self) -> Result<i32> {
        Ok(self.u32()? as i32)
    }

    fn u64(&mut self) -> Result<u64> {
        // `take(8)` returns exactly 8 bytes, so the conversion cannot fail.
        Ok(u64::from_le_bytes(
            self.take(8)?.try_into().expect("take(8) yields 8 bytes"),
        ))
    }
}

impl World {
    pub fn snapshot(&self) -> Result<Vec<u8>> {
        let mut out = Vec::new();
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(&self.content.hash.to_le_bytes());
        out.extend_from_slice(&self.seed.to_le_bytes());
        out.extend_from_slice(&self.rule_seed.to_le_bytes());
        out.extend_from_slice(&(self.width() as u32).to_le_bytes());
        out.extend_from_slice(&(self.height() as u32).to_le_bytes());
        out.extend_from_slice(&self.frame.to_le_bytes());
        out.extend_from_slice(&self.next_explosion_id.to_le_bytes());
        out.extend_from_slice(&(self.queue.len() as u32).to_le_bytes());
        for e in &self.queue {
            out.extend_from_slice(&e.id.to_le_bytes());
            out.extend_from_slice(&e.x.to_le_bytes());
            out.extend_from_slice(&e.y.to_le_bytes());
            out.extend_from_slice(&e.radius.to_le_bytes());
            out.extend_from_slice(&e.ray_energy.to_le_bytes());
            out.push(e.max_durability);
            out.push(e.fire_percent);
        }
        for chunk in &self.grid.chunks {
            for v in [
                chunk.dirty.x0,
                chunk.dirty.y0,
                chunk.dirty.x1,
                chunk.dirty.y1,
            ] {
                out.extend_from_slice(&v.to_le_bytes());
            }
        }
        let mut raw = Vec::with_capacity(self.grid.cells().len() * 4);
        for c in self.grid.cells() {
            raw.extend_from_slice(&[c.mat, c.life, c.burn, c.flags & !crate::grid::UPDATED]);
        }
        let mut enc = ZlibEncoder::new(Vec::new(), Compression::fast());
        enc.write_all(&raw)
            .and_then(|()| enc.finish())
            .map(|z| out.extend_from_slice(&z))
            .map_err(|e| Error::io("compressing snapshot", e))?;
        Ok(out)
    }

    /// Replace the whole state with the snapshot. Fails (leaving `self` untouched) if the blob is
    /// corrupt or was taken with different content.
    pub fn restore(&mut self, blob: &[u8]) -> Result<()> {
        if self.recorder.is_some() {
            // Frame numbers in a recording never decrease (contract section 5).
            return Err(Error::arg(
                "a recording is running: stop it before restoring a snapshot",
            ));
        }
        let mut r = Reader { buf: blob, pos: 0 };
        if r.take(8)? != MAGIC {
            return Err(Error::Snapshot(
                "not a cogbench snapshot (bad magic)".into(),
            ));
        }
        let hash = r.u64()?;
        if hash != self.content.hash {
            return Err(Error::Snapshot(
                "snapshot was taken with different materials, reactions, recipes or tuning".into(),
            ));
        }
        let (seed, rule_seed) = (r.u64()?, r.u64()?);
        let (w, h) = (r.u32()? as i32, r.u32()? as i32);
        if !(1..=crate::consts::MAX_WORLD_EDGE).contains(&w)
            || !(1..=crate::consts::MAX_WORLD_EDGE).contains(&h)
        {
            return Err(Error::Snapshot(format!("implausible world size {w}x{h}")));
        }
        let (frame, next_explosion_id) = (r.u64()?, r.u64()?);
        let queue = read_queue(&mut r)?;
        let mut grid = Grid::new(w, h);
        read_dirty_rects(&mut r, &mut grid)?;
        read_cells(&blob[r.pos..], &mut grid, self.content.mats.len())?;
        self.grid = grid;
        self.seed = seed;
        self.rule_seed = rule_seed;
        self.cell_seed = stream_seed(seed, "cells");
        self.frame = frame;
        self.fkey = frame_key(self.cell_seed, frame);
        self.queue = queue;
        self.next_explosion_id = next_explosion_id;
        self.events.clear();
        self.events_dropped = 0;
        Ok(())
    }
}

fn read_queue(r: &mut Reader<'_>) -> Result<Vec<Explosion>> {
    let n = r.u32()? as usize;
    let mut queue = Vec::new();
    for _ in 0..n {
        let e = Explosion {
            id: r.u64()?,
            x: r.i32()?,
            y: r.i32()?,
            radius: r.u32()?,
            ray_energy: r.u32()?,
            max_durability: r.u8()?,
            fire_percent: r.u8()?,
        };
        if e.radius == 0 || e.radius > MAX_EXPLOSION_RADIUS || e.fire_percent > 100 {
            return Err(Error::Snapshot(format!(
                "queued explosion {} has radius {} and fire chance {} %",
                e.id, e.radius, e.fire_percent
            )));
        }
        queue.push(e);
    }
    Ok(queue)
}

/// The per-chunk dirty rectangles. Each must be empty or lie inside its chunk: a corrupt blob
/// must not make the next frame visit cells outside the world.
fn read_dirty_rects(r: &mut Reader<'_>, grid: &mut Grid) -> Result<()> {
    let (cw, ch) = grid.chunk_dims();
    for cy in 0..ch {
        for cx in 0..cw {
            let rect = Rect {
                x0: r.i32()?,
                y0: r.i32()?,
                x1: r.i32()?,
                y1: r.i32()?,
            };
            let inside = rect.intersect(&grid.chunk_rect(cx, cy)) == rect;
            if !rect.is_empty() && !inside {
                return Err(Error::Snapshot(format!(
                    "dirty rectangle of chunk ({cx}, {cy}) lies outside the chunk"
                )));
            }
            grid.chunks[(cy * cw + cx) as usize].dirty =
                if rect.is_empty() { Rect::EMPTY } else { rect };
        }
    }
    Ok(())
}

/// Decompress the cell data (never more than the world needs) into `grid`.
fn read_cells(zlib: &[u8], grid: &mut Grid, material_count: usize) -> Result<()> {
    let expected = grid.cells().len() * 4;
    let mut raw = Vec::with_capacity(expected);
    ZlibDecoder::new(zlib)
        .take(expected as u64 + 1)
        .read_to_end(&mut raw)
        .map_err(|e| Error::Snapshot(format!("cells: {e}")))?;
    if raw.len() != expected {
        return Err(Error::Snapshot(format!(
            "cell data has {} bytes, expected {expected}",
            raw.len()
        )));
    }
    for (dst, src) in grid.cells_mut_raw().iter_mut().zip(raw.as_chunks::<4>().0) {
        if usize::from(src[0]) >= material_count {
            return Err(Error::Snapshot(format!(
                "material index {} out of range",
                src[0]
            )));
        }
        *dst = Cell {
            mat: src[0],
            life: src[1],
            burn: src[2],
            flags: src[3],
        };
    }
    Ok(())
}
