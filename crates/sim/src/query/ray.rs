//! Rays and projectile sweeps over cells (SIM-R60, SIM-R62, SIM-R63).

use super::QueryMask;
use crate::material::Kind;
use crate::world::World;

/// The first obstacle on a line of cells.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Hit {
    /// The blocking cell. Outside the world when the line left it (`material` is then 255).
    pub x: i32,
    pub y: i32,
    pub material: u8,
    pub kind: Kind,
    /// The cell visited just before the hit; `None` when the line starts inside an obstacle.
    pub last_free: Option<(i32, i32)>,
    /// Cells walked from the first cell of the line: 0 means the origin itself blocks.
    pub step: u32,
    /// Length of the whole line in steps (`max(|dx|, |dy|)`).
    pub steps: u32,
}

impl Hit {
    /// How far along the line the hit lies, as Q16.16 in `0..=65536` (SIM-R62's `t`).
    pub fn t_q16(&self) -> u32 {
        if self.steps == 0 {
            return 0;
        }
        (u64::from(self.step) * 65_536 / u64::from(self.steps)) as u32
    }
}

/// `round(num / den)` for `0 <= num`, half up, in `i64`.
fn rounded_div(num: i64, den: i64) -> i64 {
    (2 * num + den) / (2 * den)
}

impl World {
    /// Walk the cells on the line from `from` to `to` (both included, an integer DDA) and return
    /// the first one `mask` stops on (SIM-R60, SIM-R62).
    ///
    /// The line runs through whole cells, so a projectile that moved from `p0` to `p1` in a frame
    /// calls this with the cells of both. The origin cell is tested like any other: a projectile
    /// spawned inside rock hits at step 0. The line ends at the first cell outside the world,
    /// which counts as a hit on the boundary material. `None` means the whole line is free.
    pub fn raycast(
        &self,
        from: (i32, i32),
        to: (i32, i32),
        mask: impl Into<QueryMask>,
    ) -> Option<Hit> {
        let mask = mask.into();
        let (x0, y0) = (i64::from(from.0), i64::from(from.1));
        let (dx, dy) = (i64::from(to.0) - x0, i64::from(to.1) - y0);
        let n = dx.abs().max(dy.abs());
        let steps = n.min(i64::from(u32::MAX)) as u32;
        let mut last_free = None;
        for i in 0..=n {
            // Round-half-up interpolation along the major axis: both ends are exact, and the
            // product stays far from overflow because the walk stops at the world edge.
            let (cx, cy) = if n == 0 {
                (x0, y0)
            } else {
                (
                    x0 + dx.signum() * rounded_div(dx.abs() * i, n),
                    y0 + dy.signum() * rounded_div(dy.abs() * i, n),
                )
            };
            let (cx, cy) = (cx as i32, cy as i32);
            let mat = self.grid.get(cx, cy).mat;
            if mask.blocks(&self.content.mats, mat) {
                return Some(Hit {
                    x: cx,
                    y: cy,
                    material: mat,
                    kind: self.content.mats.rt(mat).kind,
                    last_free,
                    step: i as u32,
                    steps,
                });
            }
            last_free = Some((cx, cy));
        }
        None
    }

    /// Whether anything in `mask` lies on the line (line of sight is `!line_blocked`).
    pub fn line_blocked(
        &self,
        from: (i32, i32),
        to: (i32, i32),
        mask: impl Into<QueryMask>,
    ) -> bool {
        self.raycast(from, to, mask).is_some()
    }

    /// Direction away from the obstacles around `(x, y)` (SIM-R63): the negated sum of the
    /// vectors from the cell to every blocked cell in its 7×7 neighbourhood. `(0, 0)` when
    /// nothing around blocks, or the obstacles cancel out. Cells outside the world count as
    /// blocked.
    pub fn surface_normal(&self, x: i32, y: i32, mask: impl Into<QueryMask>) -> (i32, i32) {
        let mask = mask.into();
        let (mut nx, mut ny) = (0i32, 0i32);
        for dy in -3..=3i32 {
            for dx in -3..=3i32 {
                let c = self.grid.get(x.saturating_add(dx), y.saturating_add(dy));
                if mask.blocks(&self.content.mats, c.mat) {
                    nx -= dx;
                    ny -= dy;
                }
            }
        }
        (nx, ny)
    }

    /// Whether the cell is stopped by `mask` (outside the world always is).
    pub fn blocked_at(&self, x: i32, y: i32, mask: impl Into<QueryMask>) -> bool {
        let mat = self.grid.get(x, y).mat;
        mask.into().blocks(&self.content.mats, mat)
    }
}

/// Unit vector of `(x, y)` in Q16.16, rounded toward zero; `(0, 0)` for the zero vector.
/// Integer square root, so every platform agrees (SIM-R63, DET-R06).
pub fn unit_q16(v: (i32, i32)) -> (i32, i32) {
    let (x, y) = (i64::from(v.0), i64::from(v.1));
    let len = isqrt((x * x) as u64 + (y * y) as u64) as i64;
    if len == 0 {
        return (0, 0);
    }
    ((x * 65_536 / len) as i32, (y * 65_536 / len) as i32)
}

/// Floor of the square root of `n` (Newton's method on integers).
fn isqrt(n: u64) -> u64 {
    let mut x = n;
    let mut y = n / 2 + n % 2;
    while y < x {
        x = y;
        y = (x + n / x) / 2;
    }
    x
}
