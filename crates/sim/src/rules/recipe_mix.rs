//! The mixing step: secret recipes (`recipe.rs`).
//!
//! A recipe is three distinct ingredients (liquids or powders). Where the three meet they turn
//! into the potion, one potion cell for each ingredient cell. "Meet" has to survive how liquids
//! behave: they lie in flat layers by density, so the ingredient in the middle of three layers
//! touches only its two neighbours, never both ends of the stack at once. The rule is therefore:
//!
//! 1. An ingredient cell only mixes at a *contact*: some 4-neighbour is an ingredient of another
//!    material that shares a recipe with it. Every other visit ends here after four reads, so a
//!    lake of water costs nothing.
//! 2. At a contact it looks along the four axes through its own material (up to
//!    [`MIX_REACH`](crate::consts::MIX_REACH) cells) and notes the first cell that is not its own
//!    material in each direction.
//! 3. If, for some recipe it belongs to, the two other ingredients are both among those four
//!    cells, then with chance `Tuning::recipe_mix_q8` per visit the visited cell and those two
//!    cells all become the potion.
//!
//! A cell that sees a complete recipe and fails the roll stays awake (SIM-R12 c); a cell that
//! sees only part of one does not: the third ingredient can only arrive by a write within
//! `WAKE` of the cell, which wakes it. All randomness is the per-cell stateless hash, so dirty
//! rectangles and visit order cannot change a result (SIM-R72).
//!
//! The mix is not a reaction: it is not in `reactions.json`, it has no row id, and the log shows
//! only the potion that appeared.

use super::NEIGHBOURS;
use crate::consts::MIX_REACH;
use crate::content::Content;
use crate::event::Value;
use crate::material::MatRt;
use crate::rng::CellRng;
use crate::world::World;

/// The first cell along one axis that is not the visited material: its material and position.
type Seen = Option<(u8, i32, i32)>;

impl World {
    /// Returns `true` if the visited cell itself was rewritten.
    pub(crate) fn mix_recipe(
        &mut self,
        ct: &Content,
        x: i32,
        y: i32,
        rt: &MatRt,
        rng: &mut CellRng,
    ) -> bool {
        if ct.tuning.recipe_mix_q8 == 0 {
            return false; // mixing switched off: nothing to wait for either
        }
        let here = self.grid.get(x, y).mat;
        let mut shared = 0u16;
        for &(dx, dy) in &NEIGHBOURS {
            let n = self.grid.get(x + dx, y + dy).mat;
            if n != here {
                shared |= rt.ingredient_of & ct.mats.rt(n).ingredient_of;
            }
        }
        if shared == 0 {
            return false;
        }
        let seen = self.look_along_axes(x, y, here);
        let first = rng.below(4) as usize;
        let mut complete = false;
        let mut bits = shared;
        while bits != 0 {
            let r = bits.trailing_zeros() as usize;
            bits &= bits - 1;
            let recipe = ct.recipes[r];
            let mut others = recipe.inputs.iter().copied().filter(|&m| m != here);
            let (Some(a), Some(b)) = (others.next(), others.next()) else {
                continue;
            };
            let pick = |m: u8| (0..4).find_map(|j| seen[(first + j) % 4].filter(|s| s.0 == m));
            let (Some(pa), Some(pb)) = (pick(a), pick(b)) else {
                continue;
            };
            complete = true;
            if rng.chance_q8(ct.tuning.recipe_mix_q8) {
                self.turn_into_potion(ct, recipe.potion, [(x, y), (pa.1, pa.2), (pb.1, pb.2)]);
                return true;
            }
        }
        if complete {
            self.grid.keep_awake(x, y);
        }
        false
    }

    /// Walk each axis direction through cells of material `here` and note what ends the run.
    fn look_along_axes(&self, x: i32, y: i32, here: u8) -> [Seen; 4] {
        let mut seen: [Seen; 4] = [None; 4];
        for (slot, &(dx, dy)) in seen.iter_mut().zip(&NEIGHBOURS) {
            for k in 1..=MIX_REACH {
                let (nx, ny) = (x + k * dx, y + k * dy);
                let m = self.grid.get(nx, ny).mat;
                if m != here {
                    *slot = Some((m, nx, ny));
                    break;
                }
            }
        }
        seen
    }

    fn turn_into_potion(&mut self, ct: &Content, potion: u8, cells: [(i32, i32); 3]) {
        for (cx, cy) in cells {
            let cell = self.make_cell(potion, self.grid.idx(cx, cy) as u32);
            self.grid.set(cx, cy, cell);
        }
        let (x, y) = cells[0];
        self.log_event(
            "mix",
            vec![
                ("x", Value::Int(i64::from(x))),
                ("y", Value::Int(i64::from(y))),
                ("potion", Value::Str(ct.mats.key_of(potion).to_string())),
            ],
        );
    }
}
