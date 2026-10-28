//! Powder motion and the fall shared with liquids (SIM-R31).

use super::Enter;
use crate::consts::MAX_FALL_STEPS;
use crate::content::Content;
use crate::material::MatRt;
use crate::rng::CellRng;
use crate::world::World;

/// Pass index that separates the frame gate of slow liquids from cell-visit draws.
const PASS_GATE: u8 = 10;

/// What the fall phase did.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Fall {
    Moved,
    /// Tried and could not move: the cell is blocked.
    Stayed,
    /// Gravity is slower than one cell per frame and this frame is a rest frame.
    Skipped,
}

impl World {
    pub(crate) fn move_powder(
        &mut self,
        ct: &Content,
        x: i32,
        y: i32,
        rt: &MatRt,
        rng: &mut CellRng,
    ) {
        self.fall(ct, x, y, rt, true, rng);
    }

    /// Fall `steps` cells straight down, then try the two diagonals (SIM-R31).
    ///
    /// Gravity below one cell per frame (lava) is gated per *frame*: on a gate frame every slow
    /// cell in the world falls one cell, on the other frames none does. Adjacent columns thus
    /// move in step, and a stream, a curtain or a blob falls as one piece. Gating per column (or
    /// per cell) lets neighbours drift apart by up to a cell per frame and a pour turns to
    /// spray. On a rest frame the phase is skipped (`Fall::Skipped`); the cell then stays awake
    /// if it could have moved.
    pub(crate) fn fall(
        &mut self,
        ct: &Content,
        x: i32,
        y: i32,
        rt: &MatRt,
        is_powder: bool,
        rng: &mut CellRng,
    ) -> Fall {
        let extra = if rt.fall_int == 0 {
            let gate = crate::rng::hash_at(self.fkey, PASS_GATE, 0);
            u16::from(gate as u8) < rt.fall_frac_q8
        } else {
            rng.chance_q8(rt.fall_frac_q8)
        };
        let steps = (u32::from(rt.fall_int) + u32::from(extra)).min(MAX_FALL_STEPS);
        if steps == 0 {
            if self.could_move(ct, x, y, rt, is_powder) {
                self.grid.keep_awake(x, y);
            }
            return Fall::Skipped;
        }
        let mut cy = y;
        for _ in 0..steps {
            let target = self.grid.get(x, cy + 1);
            let go = match self.can_enter(ct, rt, is_powder, target) {
                Enter::No => break,
                Enter::Yes => true,
                Enter::Chance(p) => {
                    let ok = rng.chance_q8(p);
                    if !ok {
                        self.grid.keep_awake(x, cy);
                    }
                    ok
                }
            };
            if !go {
                break;
            }
            self.grid.swap(x, cy, x, cy + 1);
            cy += 1;
        }
        if cy != y {
            return Fall::Moved;
        }
        self.slide(ct, x, y, rt, is_powder, rng)
    }

    /// Diagonal step when straight down is blocked.
    fn slide(
        &mut self,
        ct: &Content,
        x: i32,
        y: i32,
        rt: &MatRt,
        is_powder: bool,
        rng: &mut CellRng,
    ) -> Fall {
        let first = if rng.bit() { -1 } else { 1 };
        let mut missed = false;
        for dx in [first, -first] {
            let target = self.grid.get(x + dx, y + 1);
            let enter = self.can_enter(ct, rt, is_powder, target);
            if enter == Enter::No {
                continue;
            }
            let mut ok = rng.chance_q8(rt.slide_q8);
            if ok {
                if let Enter::Chance(p) = enter {
                    ok = rng.chance_q8(p);
                }
            }
            if ok {
                self.grid.swap(x, y, x + dx, y + 1);
                return Fall::Moved;
            }
            missed = true;
        }
        if missed {
            self.grid.keep_awake(x, y);
        }
        Fall::Stayed
    }

    /// Could the cell enter any cell below or beside it, ignoring chances?
    fn could_move(&self, ct: &Content, x: i32, y: i32, rt: &MatRt, is_powder: bool) -> bool {
        [(0, 1), (-1, 1), (1, 1), (-1, 0), (1, 0)]
            .iter()
            .any(|&(dx, dy)| {
                self.can_enter(ct, rt, is_powder, self.grid.get(x + dx, y + dy)) != Enter::No
            })
    }
}
