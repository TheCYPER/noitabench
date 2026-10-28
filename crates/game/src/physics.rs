//! Moving bodies through the pixel world: the collision step of the player, enemies, items and
//! barrels (SIM-R65), plus the small geometry helpers shared by projectiles and enemies.
//!
//! A [`Body`] is a box of cells with a continuous position and a velocity in px/s. Each frame it
//! moves by `v / 60`; whole cells are handed to `World::sweep_box`, which stops at static and
//! powder cells. Only `+ - * /` and `floor` are used on floats, and angles go through
//! `cogbench_sim::detmath::sin_cos`, so every platform computes the same bits (DET-R06).

use cogbench_sim::detmath::sin_cos;
use cogbench_sim::{Aabb, KindMask, World};
use serde::{Deserialize, Serialize};

pub const FPS: f32 = 60.0;
/// Speeds below this (px/s) after a bounce stop the body.
const REST_SPEED: f32 = 15.0;

/// Unit vector of an aim angle in degrees: 0 is right, 90 is up (y grows downward).
pub fn aim_vector(degrees: f32) -> (f32, f32) {
    let (s, c) = sin_cos(f64::from(degrees).to_radians());
    (c as f32, -(s as f32))
}

/// `v` turned by `degrees` (the direction of a spread offset); keeps the length.
pub fn rotate(v: (f32, f32), degrees: f32) -> (f32, f32) {
    let (s, c) = sin_cos(f64::from(degrees).to_radians());
    let (s, c) = (s as f32, c as f32);
    (v.0 * c - v.1 * s, v.0 * s + v.1 * c)
}

/// `v` scaled to length 1, or `fallback` when it is (nearly) zero.
pub fn unit(v: (f32, f32), fallback: (f32, f32)) -> (f32, f32) {
    let len = (v.0 * v.0 + v.1 * v.1).sqrt();
    if len < 1e-3 {
        fallback
    } else {
        (v.0 / len, v.1 / len)
    }
}

/// Whole-cell part of a coordinate (`floor`), saturating for absurd values.
pub fn cell_of(v: f32) -> i32 {
    v.floor() as i32
}

/// What a move did to the body.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Moved {
    pub hit_x: bool,
    pub hit_y: bool,
    pub climbed: i32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Body {
    /// Top-left corner of the collision box, continuous.
    pub x: f32,
    pub y: f32,
    /// Velocity in px/s.
    pub vx: f32,
    pub vy: f32,
    pub w: i32,
    pub h: i32,
}

impl Body {
    pub fn new(x: i32, y: i32, w: i32, h: i32) -> Body {
        Body {
            x: x as f32,
            y: y as f32,
            vx: 0.0,
            vy: 0.0,
            w,
            h,
        }
    }

    pub fn cell(&self) -> (i32, i32) {
        (cell_of(self.x), cell_of(self.y))
    }

    pub fn aabb(&self) -> Aabb {
        let (x, y) = self.cell();
        Aabb::new(x, y, self.w, self.h)
    }

    pub fn center(&self) -> (f32, f32) {
        (self.x + self.w as f32 / 2.0, self.y + self.h as f32 / 2.0)
    }

    /// Whether a solid cell lies directly under the box.
    pub fn grounded(&self, world: &World) -> bool {
        let (x, y) = self.cell();
        world.box_blocked(Aabb::new(x, y + self.h, self.w, 1), KindMask::BLOCKING)
    }

    /// Move by one frame of the current velocity. A blocked axis loses its velocity, or bounces
    /// it back scaled by `bounce` when that is positive (items); `step_up` lifts the box over
    /// ledges of that many cells while walking.
    pub fn integrate(&mut self, world: &World, step_up: i32, bounce: f32) -> Moved {
        let nx = self.x + self.vx / FPS;
        let ny = self.y + self.vy / FPS;
        let (cx, cy) = self.cell();
        let dx = cell_of(nx) - cx;
        let dy = cell_of(ny) - cy;
        let sweep = world.sweep_box(
            Aabb::new(cx, cy, self.w, self.h),
            dx,
            dy,
            KindMask::BLOCKING,
            step_up,
        );
        let mut moved = Moved {
            hit_x: sweep.blocked_x.is_some(),
            hit_y: sweep.blocked_y.is_some(),
            climbed: sweep.climbed,
        };
        self.x = if moved.hit_x { sweep.x as f32 } else { nx };
        self.y = if moved.hit_y {
            sweep.y as f32
        } else {
            ny - sweep.climbed as f32
        };
        if moved.hit_x {
            self.vx = bounced(self.vx, bounce);
        }
        if moved.hit_y {
            self.vy = bounced(self.vy, bounce);
        }
        // A climb only counts when the horizontal move went on.
        moved.climbed = sweep.climbed;
        moved
    }
}

fn bounced(v: f32, bounce: f32) -> f32 {
    let out = -v * bounce;
    if bounce > 0.0 && out.abs() >= REST_SPEED {
        out
    } else {
        0.0
    }
}

/// The cells a segment from `(x0, y0)` to `(x1, y1)` passes through, in order, as a 4-connected
/// path (it never steps diagonally, so a projectile cannot slip between two cells that touch at a
/// corner, v1-scope section 5a). The first cell is the one containing the start. `limit` cuts
/// the walk short.
pub fn supercover(x0: f32, y0: f32, x1: f32, y1: f32, limit: usize) -> Vec<(i32, i32)> {
    let (mut cx, mut cy) = (cell_of(x0), cell_of(y0));
    let (ex, ey) = (cell_of(x1), cell_of(y1));
    let mut out = vec![(cx, cy)];
    let (dx, dy) = (x1 - x0, y1 - y0);
    let sx = if dx > 0.0 { 1 } else { -1 };
    let sy = if dy > 0.0 { 1 } else { -1 };
    let inf = f32::INFINITY;
    let next_x = if dx > 0.0 { (cx + 1) as f32 } else { cx as f32 };
    let next_y = if dy > 0.0 { (cy + 1) as f32 } else { cy as f32 };
    let mut t_x = if dx == 0.0 { inf } else { (next_x - x0) / dx };
    let mut t_y = if dy == 0.0 { inf } else { (next_y - y0) / dy };
    let step_x = if dx == 0.0 { inf } else { 1.0 / dx.abs() };
    let step_y = if dy == 0.0 { inf } else { 1.0 / dy.abs() };
    while (cx, cy) != (ex, ey) && out.len() < limit {
        if t_x < t_y {
            cx += sx;
            t_x += step_x;
        } else {
            cy += sy;
            t_y += step_y;
        }
        // Past the end cell on one axis can only happen by rounding; stay on the segment.
        if (sx > 0 && cx > ex) || (sx < 0 && cx < ex) {
            cx = ex;
        }
        if (sy > 0 && cy > ey) || (sy < 0 && cy < ey) {
            cy = ey;
        }
        out.push((cx, cy));
    }
    out
}

/// A rectangle of cells: `(x, y)` top-left, `w` by `h`.
pub fn contains(b: Aabb, x: i32, y: i32) -> bool {
    x >= b.x && y >= b.y && x < b.x + b.w && y < b.y + b.h
}

/// Whether two boxes share a cell.
pub fn overlaps(a: Aabb, b: Aabb) -> bool {
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
}

/// Distance from a point to the nearest cell centre-ish point of a box (0 inside).
pub fn distance_to_box(px: f32, py: f32, b: Aabb) -> f32 {
    let cx = px.clamp(b.x as f32, (b.x + b.w) as f32);
    let cy = py.clamp(b.y as f32, (b.y + b.h) as f32);
    let (dx, dy) = (px - cx, py - cy);
    (dx * dx + dy * dy).sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aim_vector_axes() {
        let (x, y) = aim_vector(0.0);
        assert!((x - 1.0).abs() < 1e-6 && y.abs() < 1e-6);
        let (x, y) = aim_vector(90.0);
        assert!(x.abs() < 1e-6 && (y + 1.0).abs() < 1e-6, "up is -y");
        let (x, y) = aim_vector(-90.0);
        assert!(x.abs() < 1e-6 && (y - 1.0).abs() < 1e-6, "down is +y");
        let (x, y) = rotate((1.0, 0.0), 90.0);
        assert!(x.abs() < 1e-6 && (y - 1.0).abs() < 1e-6);
        assert_eq!(unit((0.0, 0.0), (0.0, -1.0)), (0.0, -1.0));
    }

    #[test]
    fn supercover_is_four_connected() {
        let path = supercover(0.5, 0.5, 5.5, 3.5, 100);
        assert_eq!(path.first(), Some(&(0, 0)));
        assert_eq!(path.last(), Some(&(5, 3)));
        for w in path.windows(2) {
            let step = (w[1].0 - w[0].0).abs() + (w[1].1 - w[0].1).abs();
            assert_eq!(step, 1, "{path:?}");
        }
        assert_eq!(supercover(2.2, 2.2, 2.2, 2.2, 10), vec![(2, 2)]);
        assert_eq!(supercover(3.5, 1.5, -1.5, 1.5, 100).len(), 6);
    }
}
