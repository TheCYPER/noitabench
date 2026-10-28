//! The reaction step (SIM-R38, RXN-R04, RXN-R05): a visited cell examines one random
//! 4-neighbour, tries the pair's candidates in file order, and the first roll that succeeds wins.

use super::NEIGHBOURS;
use crate::content::Content;
use crate::event::Event;
use crate::grid::{Cell, BURNING, UPDATED};
use crate::reaction::{Candidate, Out};
use crate::rng::CellRng;
use crate::world::World;

/// Could `visited` react with `other` right now (some candidate with a chance, conditions met)?
fn live(ct: &Content, visited: Cell, other: Cell) -> bool {
    other.mat != 0
        && ct.table.may_react(visited.mat, other.mat)
        && ct.table.candidates(visited.mat, other.mat).iter().any(|c| {
            c.threshold > 0
                && (!c.visited_must_burn || visited.burning())
                && (!c.other_must_burn || other.burning())
        })
}

impl World {
    /// Returns `true` if the visited cell itself was rewritten.
    pub(crate) fn react(&mut self, ct: &Content, x: i32, y: i32, rng: &mut CellRng) -> bool {
        let visited = self.grid.get(x, y);
        // Which neighbours could this cell react with at all? Most cells (terrain) have none, and
        // then nothing is drawn: the pick below only matters when a partner is adjacent.
        let mut eligible = [false; 4];
        let mut any = false;
        for (i, &(dx, dy)) in NEIGHBOURS.iter().enumerate() {
            eligible[i] = live(ct, visited, self.grid.get(x + dx, y + dy));
            any |= eligible[i];
        }
        if !any {
            return false;
        }
        let pick = rng.below(4) as usize;
        if eligible[pick] {
            let (dx, dy) = NEIGHBOURS[pick];
            let other = (x + dx, y + dy);
            if let Some(cand) =
                self.roll_candidates(ct, visited, self.grid.get(other.0, other.1), rng)
            {
                self.apply_reaction(&cand, (x, y), other);
                if self.grid.get(x, y).flags & UPDATED != 0 {
                    return true;
                }
            }
        }
        // A partner is adjacent: this cell can still react later (SIM-R12 c).
        self.grid.keep_awake(x, y);
        false
    }

    /// Candidates in file order; the first whose roll succeeds wins (RXN-R05).
    fn roll_candidates(
        &self,
        ct: &Content,
        visited: Cell,
        other: Cell,
        rng: &mut CellRng,
    ) -> Option<Candidate> {
        for cand in ct.table.candidates(visited.mat, other.mat) {
            if cand.visited_must_burn && !visited.burning()
                || cand.other_must_burn && !other.burning()
            {
                continue;
            }
            if rng.below(10_000) < u32::from(cand.threshold) {
                return Some(*cand);
            }
        }
        None
    }

    fn apply_reaction(&mut self, cand: &Candidate, visited: (i32, i32), other: (i32, i32)) {
        let a = self.apply_out(cand.out_visited, visited);
        let b = self.apply_out(cand.out_other, other);
        if a || b {
            let (pa, pb) = if cand.visited_is_a {
                (visited, other)
            } else {
                (other, visited)
            };
            self.emit(Event::Reaction {
                frame: self.frame,
                row: cand.row,
                x: pa.0,
                y: pa.1,
                bx: pb.0,
                by: pb.1,
            });
        }
    }

    /// Apply one output to a cell; `true` if it changed.
    fn apply_out(&mut self, out: Out, (x, y): (i32, i32)) -> bool {
        let current = self.grid.get(x, y);
        match out {
            Out::Set(m) if m == current.mat => false,
            Out::Set(m) => {
                let cell = self.make_cell(m, self.grid.idx(x, y) as u32);
                self.grid.set(x, y, cell);
                true
            }
            Out::Extinguish if !current.burning() => false,
            Out::Extinguish => {
                self.grid.modify(x, y, |c| c.flags &= !BURNING);
                self.emit(Event::Extinguish {
                    frame: self.frame,
                    x,
                    y,
                    material: current.mat,
                });
                true
            }
        }
    }
}
