//! Gas and fire motion: act with some chance, go up, else sideways (SIM-R34, SIM-R36).

use crate::content::Content;
use crate::grid::{Cell, DIR};
use crate::material::{Kind, MatRt};
use crate::rng::CellRng;
use crate::world::World;

impl World {
    pub(crate) fn move_gas(&mut self, ct: &Content, x: i32, y: i32, rt: &MatRt, rng: &mut CellRng) {
        if rt.life_unit == 0 {
            // No timer keeps this cell awake, but it may still drift (SIM-R12).
            self.grid.keep_awake(x, y);
        }
        if !rng.chance_q8(ct.tuning.gas_act_q8) {
            return;
        }
        let is_fire = rt.kind == Kind::Fire;
        if self.gas_enter(ct, rt, is_fire, self.grid.get(x, y - 1)) {
            self.grid.swap(x, y, x, y - 1);
            return;
        }
        let dir = if self.grid.get(x, y).flags & DIR != 0 {
            1
        } else {
            -1
        };
        for (i, d) in [dir, -dir].into_iter().enumerate() {
            if self.gas_enter(ct, rt, is_fire, self.grid.get(x + d, y)) {
                self.grid.swap(x, y, x + d, y);
                return;
            }
            if i == 0 {
                // The preferred side is blocked: remember to prefer the other one.
                self.grid.cell_mut(x, y).flags ^= DIR;
            }
        }
    }

    /// Gas enters Air, and swaps with a heavier gas (the lighter one rises). Fire enters Air only.
    fn gas_enter(&self, ct: &Content, mover: &MatRt, is_fire: bool, target: Cell) -> bool {
        if target.mat == 0 {
            return true;
        }
        if is_fire {
            return false;
        }
        let t = ct.mats.rt(target.mat);
        t.kind == Kind::Gas && t.density_x10000 > mover.density_x10000
    }
}
