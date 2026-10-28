//! Burning (FIRE-R03..R06, FIRE-R10, SIM-R37): fuel, ignition of neighbours, flames, detonation.

use super::NEIGHBOURS;
use crate::content::Content;
use crate::event::Event;
use crate::grid::{Cell, BURNING};
use crate::material::{Kind, MatRt};
use crate::rng::CellRng;
use crate::world::{Explosion, World};

impl World {
    /// One burning step for a BURNING cell or a fire cell. Returns `true` if the cell is gone.
    pub(crate) fn burn_step(
        &mut self,
        ct: &Content,
        x: i32,
        y: i32,
        rt: &MatRt,
        rng: &mut CellRng,
    ) -> bool {
        self.grid.keep_awake(x, y);
        if rt.kind == Kind::Fire {
            // Fire cells only ignite their surroundings; they expire through their timer.
            self.ignite_neighbour(ct, x, y, rt.fire_temperature, self.grid.get(x, y).mat, rng);
            return false;
        }
        if rt.requires_oxygen && !self.touches_oxygen(ct, x, y) {
            return false; // smothered: no progress, no flames
        }
        if self.consume_fuel(x, y, rt) {
            self.burn_out(x, y, rt);
            return true;
        }
        self.emit_flame(ct, x, y, rng);
        self.ignite_neighbour(ct, x, y, rt.fire_temperature, self.grid.get(x, y).mat, rng);
        false
    }

    /// Count one unit of fuel on its tick; `true` when the fuel is used up.
    fn consume_fuel(&mut self, x: i32, y: i32, rt: &MatRt) -> bool {
        let tick = self.frame.is_multiple_of(u64::from(rt.burn_unit));
        let cell = self.grid.cell_mut(x, y);
        if cell.burn == 0 {
            return true;
        }
        if tick {
            cell.burn -= 1;
            return cell.burn == 0;
        }
        false
    }

    /// The cell burned up: explosives detonate, everything else leaves no ash (FIRE-R04).
    fn burn_out(&mut self, x: i32, y: i32, rt: &MatRt) {
        self.grid.set(x, y, Cell::AIR);
        if let Some(e) = rt.explosion {
            let id = self.next_explosion_id;
            self.next_explosion_id += 1;
            self.queue.push(Explosion {
                id,
                x,
                y,
                radius: e.radius,
                ray_energy: e.ray_energy,
                max_durability: e.max_durability,
                fire_percent: e.fire_percent,
            });
        }
    }

    /// A burning cell throws a flame into a free neighbour now and then.
    fn emit_flame(&mut self, ct: &Content, x: i32, y: i32, rng: &mut CellRng) {
        if rng.below(100) >= u32::from(ct.tuning.flame_percent) {
            return;
        }
        let (dx, dy) = NEIGHBOURS[rng.below(4) as usize];
        let (nx, ny) = (x + dx, y + dy);
        if self.grid.in_bounds(nx, ny) && self.grid.get(nx, ny).mat == 0 {
            let cell = self.make_cell(ct.fire, self.grid.idx(nx, ny) as u32);
            self.grid.set(nx, ny, cell);
        }
    }

    /// Pick one random neighbour and try to set it alight (FIRE-R03): the source must be hotter
    /// than the target's ignition temperature, and the roll is `100 - autoignition` percent.
    ///
    /// Sources are fire cells and burning cells. Lava is not one: FIRE-R03 lists it, FIRE-R09
    /// ignites through reaction rows only, and the content file gives lava no burning state, so
    /// lava lights things through rows r05 and r06 alone.
    pub(crate) fn ignite_neighbour(
        &mut self,
        ct: &Content,
        x: i32,
        y: i32,
        source_temp: u8,
        source_mat: u8,
        rng: &mut CellRng,
    ) {
        let (dx, dy) = NEIGHBOURS[rng.below(4) as usize];
        let (nx, ny) = (x + dx, y + dy);
        let target = self.grid.get(nx, ny);
        if target.mat == 0 || !self.grid.in_bounds(nx, ny) || target.burning() {
            return;
        }
        let t = ct.mats.rt(target.mat);
        if !t.burnable || t.autoignition >= 100 || source_temp <= t.autoignition {
            return;
        }
        if rng.below(100) < 100 - u32::from(t.autoignition) {
            self.grid.modify(nx, ny, |c| {
                c.flags |= BURNING;
                c.burn = t.burn0;
            });
            self.emit(Event::Ignite {
                frame: self.frame,
                x: nx,
                y: ny,
                material: target.mat,
                by: source_mat,
            });
        }
    }

    /// Whether a 4-neighbour is Air, Gas or Fire (FIRE-R05: burning needs air).
    fn touches_oxygen(&self, ct: &Content, x: i32, y: i32) -> bool {
        NEIGHBOURS.iter().any(|&(dx, dy)| {
            let n = self.grid.get(x + dx, y + dy);
            n.mat == 0 || matches!(ct.mats.rt(n.mat).kind, Kind::Gas | Kind::Fire)
        })
    }
}
