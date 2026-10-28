//! Ray explosions (SIM-R50..R54, DUR-R01..R03).
//!
//! From the centre, rays run out to radius `R`. Each ray carries `ray_energy`; every non-air
//! cell it crosses costs the cell's `hp`. A cell is removed only if it is no harder than
//! `max_durability` (durability 0 = unset, never blocks) and the ray still has energy on arrival;
//! a harder cell ends the ray. Every ray pays for the cells of the *original* grid, so the carved
//! depth in a uniform material is `min(R, ceil(E / hp))` per ray no matter how many rays overlap
//! (test vectors MV-14..MV-17); a bitmap only keeps a cell from being removed twice.
//!
//! Deliberate differences from `pixel-simulation.md`:
//! * SIM-R51 lets a cell destroyed by an earlier ray count as air for later rays. That would make
//!   every crater reach the full radius, contradicting the depth vectors above, so it is not done.
//! * SIM-R51 prescribes `max(16, ceil(2πR))` rays and a grid DDA. Jittered rays at that density
//!   leave gaps near the rim, so twice as many are traced (`RAY_OVERSAMPLE`; `ray_count` still
//!   reports the SIM-R51 number) and each ray is sampled four times per cell (`RAY_SUBSTEPS`).
//!   Energy is charged per unit of ray length, not per cell crossed, so energy-limited craters
//!   stay round instead of turning into diamonds.
//! * SIM-R52 throws destroyed liquid cells outward as particles. There are no particles in week
//!   1, so a destroyed liquid cell is simply removed (or turns to fire, like any other cell).

use crate::consts::{
    DEFAULT_CREATE_FIRE_PERCENT, MAX_EXPLOSIONS_PER_FRAME, MAX_EXPLOSION_R2_PER_FRAME,
    MAX_EXPLOSION_RADIUS, MIN_EXPLOSION_RAYS,
};
use crate::detmath::sin_cos;
use crate::error::{Error, Result};
use crate::event::Event;
use crate::grid::{Cell, Rect};
use crate::rng::{hash_at, mix64};
use crate::world::{Explosion, World};
use std::f64::consts::TAU;

/// Pass index that separates explosion draws from cell-visit draws.
const PASS_EXPLOSION: u8 = 9;
const Q: i64 = 1 << 16;
/// Samples per cell of ray length.
const RAY_SUBSTEPS: i64 = 4;
/// Rays traced per `ray_count(r)` (see `trace_rays`).
const RAY_OVERSAMPLE: u32 = 2;

/// Parameters of an explosion (`ConfigExplosion`, DUR-R03).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ExplosionSpec {
    pub x: i32,
    pub y: i32,
    pub radius: u32,
    pub ray_energy: u32,
    pub max_durability: u8,
    /// Chance in percent that a destroyed cell becomes fire (`create_cell_probability`).
    pub fire_percent: u8,
}

impl ExplosionSpec {
    pub fn new(x: i32, y: i32, radius: u32, ray_energy: u32, max_durability: u8) -> Self {
        ExplosionSpec {
            x,
            y,
            radius,
            ray_energy,
            max_durability,
            fire_percent: DEFAULT_CREATE_FIRE_PERCENT,
        }
    }
}

/// Number of rays of an explosion of radius `r` (SIM-R51, test vector SIM-T28).
pub fn ray_count(r: u32) -> u32 {
    ((TAU * f64::from(r)).ceil() as u32).max(MIN_EXPLOSION_RAYS)
}

/// Destroyed-cell bookkeeping of one explosion: a bitmap over the bounding square plus the list.
struct Carve {
    cx: i32,
    cy: i32,
    r: i32,
    side: i32,
    mask: Vec<bool>,
    cells: Vec<(i32, i32)>,
}

impl Carve {
    fn new(cx: i32, cy: i32, r: i32) -> Carve {
        let side = 2 * r + 1;
        Carve {
            cx,
            cy,
            r,
            side,
            mask: vec![false; (side * side) as usize],
            cells: Vec::new(),
        }
    }

    fn slot(&self, x: i32, y: i32) -> usize {
        ((y - self.cy + self.r) * self.side + (x - self.cx + self.r)) as usize
    }

    fn contains(&self, x: i32, y: i32) -> bool {
        (x - self.cx).abs() <= self.r && (y - self.cy).abs() <= self.r && self.mask[self.slot(x, y)]
    }

    fn insert(&mut self, x: i32, y: i32) {
        let s = self.slot(x, y);
        self.mask[s] = true;
        self.cells.push((x, y));
    }
}

impl World {
    /// Run an explosion now. Returns the number of cells destroyed.
    pub fn explode(&mut self, spec: ExplosionSpec) -> Result<u32> {
        if spec.radius == 0 || spec.radius > MAX_EXPLOSION_RADIUS {
            return Err(Error::arg(format!(
                "explosion radius must be 1..={MAX_EXPLOSION_RADIUS}, got {}",
                spec.radius
            )));
        }
        if spec.fire_percent > 100 {
            return Err(Error::arg("fire_percent must be 0..=100"));
        }
        let id = self.next_explosion_id;
        self.next_explosion_id += 1;
        Ok(self.run_explosion(&Explosion {
            id,
            x: spec.x,
            y: spec.y,
            radius: spec.radius,
            ray_energy: spec.ray_energy,
            max_durability: spec.max_durability,
            fire_percent: spec.fire_percent,
        }))
    }

    /// Explosion phase of the frame pipeline (SIM-R54): at most 32 explosions and 400,000 summed
    /// squared radii per frame, the rest waits for the next frame in queue order.
    pub(crate) fn run_explosion_phase(&mut self) {
        let mut take = 0;
        let mut r2_sum = 0u64;
        for e in &self.queue {
            let r2 = u64::from(e.radius) * u64::from(e.radius);
            if take >= MAX_EXPLOSIONS_PER_FRAME
                || (take > 0 && r2_sum + r2 > MAX_EXPLOSION_R2_PER_FRAME)
            {
                break;
            }
            r2_sum += r2;
            take += 1;
        }
        let batch: Vec<Explosion> = self.queue.drain(..take).collect();
        for e in &batch {
            self.run_explosion(e);
        }
    }

    fn run_explosion(&mut self, e: &Explosion) -> u32 {
        let carve = self.trace_rays(e);
        let destroyed = carve.cells.len() as u32;
        let base = hash_at(self.fkey, PASS_EXPLOSION, e.id as u32);
        let mut touched = Rect::EMPTY;
        for (i, &(x, y)) in carve.cells.iter().enumerate() {
            let roll =
                (mix64(base ^ (i as u64).wrapping_mul(0xD6E8_FEB8_6659_FD93) ^ 0xF1) >> 33) % 100;
            let cell = if roll < u64::from(e.fire_percent) {
                self.make_cell(self.content.fire, self.grid.idx(x, y) as u32)
            } else {
                Cell::AIR
            };
            self.grid.put_quiet(x, y, cell);
            touched.add_point(x, y);
        }
        self.ignite_explosives_beside(&carve, &mut touched);
        self.grid.wake_rect(touched);
        self.emit(Event::Explosion {
            frame: self.frame,
            x: e.x,
            y: e.y,
            radius: e.radius,
            destroyed,
        });
        destroyed
    }

    /// The blast front sets off explosive cells it touches but did not remove (FIRE-R10): packed
    /// gunpowder beyond the blast radius goes up in turn, one blast after another.
    fn ignite_explosives_beside(&mut self, carve: &Carve, touched: &mut Rect) {
        let fire = self.content.fire;
        for &(x, y) in &carve.cells {
            for (dx, dy) in super::NEIGHBOURS {
                let (nx, ny) = (x + dx, y + dy);
                let cell = self.grid.get(nx, ny);
                let rt = self.content.mats.rt(cell.mat);
                if !self.grid.in_bounds(nx, ny)
                    || carve.contains(nx, ny)
                    || rt.explosion.is_none()
                    || cell.burning()
                {
                    continue;
                }
                let lit = Cell {
                    flags: cell.flags | crate::grid::BURNING,
                    burn: rt.burn0,
                    ..cell
                };
                self.grid.put_quiet(nx, ny, lit);
                touched.add_point(nx, ny);
                self.emit(Event::Ignite {
                    frame: self.frame,
                    x: nx,
                    y: ny,
                    material: cell.mat,
                    by: fire,
                });
            }
        }
    }

    fn trace_rays(&self, e: &Explosion) -> Carve {
        let r = e.radius as i32;
        let mut carve = Carve::new(e.x, e.y, r);
        let n = ray_count(e.radius) * RAY_OVERSAMPLE;
        let base = hash_at(self.fkey, PASS_EXPLOSION, e.id as u32);
        for k in 0..n {
            let jitter = (mix64(base ^ u64::from(k).wrapping_mul(0x9E37_79B9_7F4A_7C15)) >> 40)
                as f64
                / f64::from(1u32 << 24);
            let theta = TAU * (f64::from(k) + jitter) / f64::from(n);
            let (s, c) = sin_cos(theta);
            let (dx, dy) = ((c * Q as f64).round() as i64, (s * Q as f64).round() as i64);
            self.trace_ray(e, dx, dy, &mut carve);
        }
        carve
    }

    /// Walk one ray, spending its energy (DUR-R01, DUR-R02).
    ///
    /// The ray is sampled every `1 / RAY_SUBSTEPS` of a cell so that no cell it crosses is
    /// skipped (a plain unit-step march leaves isolated uncarved cells inside the crater).
    /// Energy is charged once per whole cell of path length, so the carved depth in a uniform
    /// material stays `min(R, ceil(E / hp))` and the crater stays round; a cell entered between
    /// two charge points is carved for free if it is soft enough and energy is left.
    fn trace_ray(&self, e: &Explosion, dx: i64, dy: i64, carve: &mut Carve) {
        let mut energy = i64::from(e.ray_energy);
        let (ox, oy) = (i64::from(e.x) * Q + Q / 2, i64::from(e.y) * Q + Q / 2);
        let mut last = (i32::MIN, i32::MIN);
        for step in 0..=i64::from(e.radius) * RAY_SUBSTEPS {
            let x = ((ox + dx * step / RAY_SUBSTEPS) >> 16) as i32;
            let y = ((oy + dy * step / RAY_SUBSTEPS) >> 16) as i32;
            if !self.grid.in_bounds(x, y) {
                return;
            }
            // Rays read the original grid: writes are applied after all rays are traced.
            let cell = self.grid.get(x, y);
            if cell.mat == 0 {
                last = (x, y);
                continue;
            }
            let rt = self.content.mats.rt(cell.mat);
            if (x, y) != last {
                if rt.durability > e.max_durability || energy <= 0 {
                    return;
                }
                if !carve.contains(x, y) {
                    carve.insert(x, y);
                }
            }
            last = (x, y);
            if step % RAY_SUBSTEPS == 0 {
                energy -= i64::from(rt.hp);
            }
        }
    }
}
