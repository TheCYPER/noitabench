//! Moving a box through the grid (SIM-R65): the collision step of players, enemies and items.

use super::{Aabb, QueryMask};
use crate::consts::{BOUNDARY, MAX_SWEEP};
use crate::world::World;

/// Where a box ended up after a sweep.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Sweep {
    /// Top-left corner of the box at the end.
    pub x: i32,
    pub y: i32,
    /// Material (255 = world edge) that cut the horizontal move short, if it was cut short.
    pub blocked_x: Option<u8>,
    /// Same for the vertical move.
    pub blocked_y: Option<u8>,
    /// Cells the box was lifted over ledges while moving sideways (`step_up`).
    pub climbed: i32,
}

impl World {
    /// Material at a cell, with everything beyond the `i32` range counted as the world edge.
    fn mat_at(&self, x: i64, y: i64) -> u8 {
        match (i32::try_from(x), i32::try_from(y)) {
            (Ok(x), Ok(y)) => self.grid.get(x, y).mat,
            _ => BOUNDARY,
        }
    }

    /// First blocking material in the column `x`, rows `y .. y + h`, scanning downward.
    fn column_blocker(&self, x: i64, y: i64, h: i64, mask: &QueryMask) -> Option<u8> {
        (y..y + h)
            .map(|yy| self.mat_at(x, yy))
            .find(|&m| mask.blocks(&self.content.mats, m))
    }

    /// First blocking material in the row `y`, columns `x .. x + w`, scanning rightward.
    fn row_blocker(&self, x: i64, y: i64, w: i64, mask: &QueryMask) -> Option<u8> {
        (x..x + w)
            .map(|xx| self.mat_at(xx, y))
            .find(|&m| mask.blocks(&self.content.mats, m))
    }

    /// Whether any cell of the box stops `mask` (a box standing in rock is "stuck").
    pub fn box_blocked(&self, b: Aabb, mask: impl Into<QueryMask>) -> bool {
        let mask = mask.into();
        let (x, y, w, h) = (
            i64::from(b.x),
            i64::from(b.y),
            i64::from(b.w),
            i64::from(b.h),
        );
        !b.is_empty() && (y..y + h).any(|yy| self.row_blocker(x, yy, w, &mask).is_some())
    }

    /// Move `b` by `(dx, dy)` one cell at a time, first sideways, then vertically, and stop each
    /// move at the first cell its leading edge cannot enter (SIM-R65).
    ///
    /// Only the cells the leading edge would enter are tested, so a box that starts inside rock
    /// can still move out of it, and never deeper in. With `step_up > 0`, a sideways move that
    /// is blocked tries to lift the box by 1 to `step_up` cells first and goes on if the space
    /// above and the new leading column are free (ledges of up to `climb_over_y` = 4 cells for
    /// the player). Cells outside the world block. Moves longer than [`MAX_SWEEP`] cells per axis
    /// are cut to that length; an empty box does not move.
    pub fn sweep_box(
        &self,
        b: Aabb,
        dx: i32,
        dy: i32,
        mask: impl Into<QueryMask>,
        step_up: i32,
    ) -> Sweep {
        let mask = mask.into();
        let mut out = Sweep {
            x: b.x,
            y: b.y,
            blocked_x: None,
            blocked_y: None,
            climbed: 0,
        };
        if b.is_empty() {
            return out;
        }
        let (w, h) = (i64::from(b.w), i64::from(b.h));
        let (mut x, mut y) = (i64::from(b.x), i64::from(b.y));
        let step_up = i64::from(step_up.clamp(0, MAX_SWEEP));
        let (sx, sy) = (i64::from(dx.signum()), i64::from(dy.signum()));
        let (nx_steps, ny_steps) = (
            i64::from(dx.clamp(-MAX_SWEEP, MAX_SWEEP).abs()),
            i64::from(dy.clamp(-MAX_SWEEP, MAX_SWEEP).abs()),
        );
        for _ in 0..nx_steps {
            let next = x + sx;
            let lead = if sx > 0 { next + w - 1 } else { next };
            match self.column_blocker(lead, y, h, &mask) {
                None => x = next,
                Some(m) => match self.climb(x, y, (w, h), sx, step_up, &mask) {
                    Some(k) => {
                        x = next;
                        y -= k;
                        out.climbed += k as i32;
                    }
                    None => {
                        out.blocked_x = Some(m);
                        break;
                    }
                },
            }
        }
        for _ in 0..ny_steps {
            let next = y + sy;
            let lead = if sy > 0 { next + h - 1 } else { next };
            match self.row_blocker(x, lead, w, &mask) {
                None => y = next,
                Some(m) => {
                    out.blocked_y = Some(m);
                    break;
                }
            }
        }
        // Positions only moved away from `b` through free cells of the world, so they fit.
        out.x = x as i32;
        out.y = y as i32;
        out
    }

    /// The smallest lift `k` in `1..=step_up` that lets the box at `(x, y)` step sideways by
    /// `sx`: the strip above the box is free and so is the new leading column.
    ///
    /// The strip grows by one row per `k`, so each row is tested once and the search ends as
    /// soon as one of them is blocked: the cost is linear in `step_up`, however tall the wall.
    fn climb(
        &self,
        x: i64,
        y: i64,
        (w, h): (i64, i64),
        sx: i64,
        step_up: i64,
        mask: &QueryMask,
    ) -> Option<i64> {
        let next = x + sx;
        let lead = if sx > 0 { next + w - 1 } else { next };
        for k in 1..=step_up {
            if self.row_blocker(x, y - k, w, mask).is_some() {
                return None; // no lift of k or more rows has a free strip
            }
            if self.column_blocker(lead, y - k, h, mask).is_none() {
                return Some(k);
            }
        }
        None
    }
}
