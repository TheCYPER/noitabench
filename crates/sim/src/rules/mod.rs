//! Cell rules. `visit` is the per-cell dispatch (SIM-R30): timers, burning, reactions, motion.

mod explode;
mod fire;
mod gas;
mod liquid;
mod powder;
mod reactions;
mod recipe_mix;

pub use explode::{ray_count, ExplosionSpec};

use crate::content::Content;
use crate::grid::{Cell, UPDATED};
use crate::material::{Kind, MatRt};
use crate::rng::CellRng;
use crate::world::World;

/// Whether a moving cell may enter a neighbouring cell.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Enter {
    No,
    Yes,
    /// Only with this chance (`/256`): sinking into a lighter liquid.
    Chance(u16),
}

/// The four lateral and vertical neighbours, in the order random picks index them.
pub(crate) const NEIGHBOURS: [(i32, i32); 4] = [(0, -1), (1, 0), (0, 1), (-1, 0)];

impl World {
    /// Visit one cell: timers, burning, reaction step, motion (SIM-R30).
    pub(crate) fn visit(&mut self, ct: &Content, x: i32, y: i32, pass: u8) {
        let cell = self.grid.get(x, y);
        if cell.mat == 0 || cell.flags & UPDATED != 0 {
            return;
        }
        let rt = ct.mats.rt(cell.mat);
        let index = self.grid.idx(x, y) as u32;
        let mut rng = CellRng::new(self.fkey, pass, index);

        if rt.life_unit != 0 && self.tick_timer(x, y, rt) {
            return;
        }
        if (cell.burning() || rt.kind == Kind::Fire) && self.burn_step(ct, x, y, rt, &mut rng) {
            return;
        }
        if rt.reactive && self.react(ct, x, y, &mut rng) {
            return;
        }
        if rt.ingredient_of != 0 && self.mix_recipe(ct, x, y, rt, &mut rng) {
            return;
        }
        // The cell may have been rewritten or moved by the steps above.
        let now = self.grid.get(x, y);
        if now.flags & UPDATED != 0 || now.mat != cell.mat {
            return;
        }
        match rt.kind {
            Kind::Powder => self.move_powder(ct, x, y, rt, &mut rng),
            Kind::Liquid => self.move_liquid(ct, x, y, rt, &mut rng),
            Kind::Gas | Kind::Fire => self.move_gas(ct, x, y, rt, &mut rng),
            Kind::Air | Kind::Static => {}
        }
    }

    /// Decrement the timer on its tick; returns `true` if the cell expired and is gone.
    fn tick_timer(&mut self, x: i32, y: i32, rt: &MatRt) -> bool {
        self.grid.keep_awake(x, y);
        if !self.frame.is_multiple_of(u64::from(rt.life_unit)) {
            return false;
        }
        let cell = self.grid.cell_mut(x, y);
        cell.life = cell.life.saturating_sub(1);
        if cell.life == 0 {
            self.grid.set(x, y, Cell::AIR);
            return true;
        }
        false
    }

    /// Whether a mover of material `mover` may enter `target` (SIM-R30 table, Powder/Liquid rows).
    pub(crate) fn can_enter(
        &self,
        ct: &Content,
        mover: &MatRt,
        is_powder: bool,
        target: Cell,
    ) -> Enter {
        if target.mat == 0 {
            return Enter::Yes;
        }
        let t = ct.mats.rt(target.mat);
        match t.kind {
            Kind::Gas | Kind::Fire => Enter::Yes,
            Kind::Liquid if mover.density_x10000 > t.density_x10000 => {
                let p = if is_powder {
                    ct.tuning.sink_powder_q8
                } else {
                    ct.tuning.sink_liquid_q8
                };
                if p >= 256 {
                    Enter::Yes
                } else {
                    Enter::Chance(p)
                }
            }
            _ => Enter::No,
        }
    }

    /// Whether the cell is free to hop into sideways (Air, Gas or Fire).
    pub(crate) fn passable(&self, ct: &Content, x: i32, y: i32) -> bool {
        let c = self.grid.get(x, y);
        c.mat == 0 || matches!(ct.mats.rt(c.mat).kind, Kind::Gas | Kind::Fire)
    }
}
