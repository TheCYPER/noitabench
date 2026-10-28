//! Liquid motion: fall like a powder, then hop sideways (SIM-R32, SIM-R33).

use super::powder::Fall;
use crate::content::Content;
use crate::grid::DIR;
use crate::material::{Kind, MatRt};
use crate::rng::CellRng;
use crate::world::World;

impl World {
    pub(crate) fn move_liquid(
        &mut self,
        ct: &Content,
        x: i32,
        y: i32,
        rt: &MatRt,
        rng: &mut CellRng,
    ) {
        if self.fall(ct, x, y, rt, false, rng) != Fall::Stayed {
            return;
        }
        self.hop(ct, x, y, rt, rng);
    }

    /// Length of the run of passable cells starting next to `(x, y)` in direction `d`, up to the
    /// hop range.
    ///
    /// A slow liquid (lava: less than one fall step per frame) does not throw itself into the
    /// air: the run ends at the first cell with nothing under it. The liquid steps off the edge
    /// and falls in its own column, so a pour stays one piece instead of fanning out into a
    /// spray whose cells each wait for their own column's turn to fall.
    fn free_run(&self, ct: &Content, x: i32, y: i32, d: i32, slow: bool) -> i32 {
        let mut k = 0;
        while k < i32::from(ct.tuning.liquid_hop) && self.passable(ct, x + d * (k + 1), y) {
            k += 1;
            if slow && self.passable(ct, x + d * k, y + 1) {
                break;
            }
        }
        k
    }

    fn hop(&mut self, ct: &Content, x: i32, y: i32, rt: &MatRt, rng: &mut CellRng) {
        let cell = self.grid.get(x, y);
        let pref = if cell.flags & DIR != 0 { 1 } else { -1 };
        for d in [pref, -pref] {
            let k = self.free_run(ct, x, y, d, rt.fall_int == 0);
            if k == 0 {
                continue;
            }
            let nx = x + d * k;
            self.grid.swap(x, y, nx, y);
            // Remember the direction we went, flipping it now and then (SIM-R32).
            let right = (d == 1) != rng.chance_q8(ct.tuning.dir_flip_q8);
            let flags = self.grid.get(nx, y).flags & !DIR;
            self.grid.cell_mut(nx, y).flags = flags | if right { DIR } else { 0 };
            return;
        }
        self.mix(ct, x, y, rt, pref, rng);
    }

    /// Equal-density liquids interpenetrate sideways, rarely (SIM-R33).
    fn mix(&mut self, ct: &Content, x: i32, y: i32, rt: &MatRt, pref: i32, rng: &mut CellRng) {
        let me = self.grid.get(x, y).mat;
        for d in [pref, -pref] {
            let other = self.grid.get(x + d, y);
            if other.mat == me || other.mat == 0 {
                continue;
            }
            let ort = ct.mats.rt(other.mat);
            if ort.kind != Kind::Liquid || ort.density_x10000 != rt.density_x10000 {
                continue;
            }
            if ct.tuning.mix_q8 == 0 {
                return;
            }
            if rng.chance_q8(ct.tuning.mix_q8) {
                self.grid.swap(x, y, x + d, y);
                return;
            }
            self.grid.keep_awake(x, y);
        }
    }
}
