//! What a box touches: counts of materials and kinds, and the contact damage they deal
//! (HAZ-R01..R03). Used for hazards, statuses from contact and submersion.

use super::Aabb;
use crate::consts::{CONTACT_MAX_CELLS, CONTACT_MIN_CELLS};
use crate::material::Kind;
use crate::world::World;

/// Cell counts under a box.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Overlap {
    /// Cells of the box that lie inside the world.
    pub inside: u32,
    /// Cells of the box beyond the world edge.
    pub outside: u64,
    kinds: [u32; 6],
    burning: u32,
    /// `(material index, cells)` in ascending material order, non-zero counts only; air included.
    materials: Vec<(u8, u32)>,
}

impl Overlap {
    /// Cells of material index `material`.
    pub fn count(&self, material: u8) -> u32 {
        self.materials
            .binary_search_by_key(&material, |&(m, _)| m)
            .map_or(0, |i| self.materials[i].1)
    }

    /// Cells of a kind (`Kind::Liquid` for submersion, `Kind::Fire` for flames).
    pub fn kind_count(&self, kind: Kind) -> u32 {
        self.kinds[kind.index()]
    }

    /// Cells that are in the burning state (burning wood, oil, ...).
    pub fn burning(&self) -> u32 {
        self.burning
    }

    /// Non-zero `(material index, cells)` pairs in ascending material order.
    pub fn materials(&self) -> &[(u8, u32)] {
        &self.materials
    }
}

/// The two numbers of the contact damage rule (HAZ-R01), per entity (HAZ-R03).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ContactRules {
    /// A material hurts only if at least this many of its cells touch the box.
    pub min_cells: u32,
    /// A material counts for at most this many cells.
    pub max_cells: u32,
}

impl Default for ContactRules {
    /// The player's values: 4 and 85 cells.
    fn default() -> Self {
        ContactRules {
            min_cells: CONTACT_MIN_CELLS,
            max_cells: CONTACT_MAX_CELLS,
        }
    }
}

/// What one damaging material did to a box.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ContactPart {
    pub material: u8,
    /// Cells of the material that overlap the box.
    pub cells: u32,
    /// Cells that count: `min(cells, max_cells)`.
    pub counted: u32,
    /// `counted` times the material's damage per cell.
    pub damage: f64,
}

/// Contact damage of one frame.
#[derive(Clone, Debug, PartialEq)]
pub struct ContactDamage {
    /// Sum over the damaging materials, in the unit of the damage table (raw, internal HP; the
    /// display value is 25 times this).
    pub raw: f64,
    /// The damaging materials that touched the box with at least `min_cells` cells, in ascending
    /// material order.
    pub parts: Vec<ContactPart>,
}

impl Overlap {
    /// Contact damage from the cell counts (HAZ-R01): for each material with a positive
    /// `per_px(material)` and at least `rules.min_cells` cells, `min(cells, max_cells) × per_px`.
    /// No type multiplier applies. Materials are summed in ascending index order, so the float
    /// sum is the same everywhere.
    pub fn contact_damage(&self, per_px: impl Fn(u8) -> f64, rules: ContactRules) -> ContactDamage {
        let mut out = ContactDamage {
            raw: 0.0,
            parts: Vec::new(),
        };
        for &(m, cells) in &self.materials {
            let rate = per_px(m);
            if rate > 0.0 && cells >= rules.min_cells {
                let counted = cells.min(rules.max_cells);
                let damage = f64::from(counted) * rate;
                out.raw += damage;
                out.parts.push(ContactPart {
                    material: m,
                    cells,
                    counted,
                    damage,
                });
            }
        }
        out
    }
}

impl World {
    /// Count what lies under the box (cells beyond the world edge are counted in `outside`).
    pub fn overlap(&self, b: Aabb) -> Overlap {
        let mut by_mat = [0u32; 256];
        let mut kinds = [0u32; 6];
        let mut burning = 0;
        let mut inside = 0u32;
        if !b.is_empty() {
            let x0 = i64::from(b.x).max(0);
            let y0 = i64::from(b.y).max(0);
            let x1 = (i64::from(b.x) + i64::from(b.w)).min(i64::from(self.width()));
            let y1 = (i64::from(b.y) + i64::from(b.h)).min(i64::from(self.height()));
            for y in y0..y1 {
                for x in x0..x1 {
                    let cell = self.grid.get(x as i32, y as i32);
                    by_mat[usize::from(cell.mat)] += 1;
                    kinds[self.content.mats.rt(cell.mat).kind.index()] += 1;
                    burning += u32::from(cell.burning());
                    inside += 1;
                }
            }
        }
        let area = if b.is_empty() {
            0
        } else {
            u64::from(b.w as u32) * u64::from(b.h as u32)
        };
        let materials = by_mat
            .iter()
            .enumerate()
            .filter(|(_, &n)| n > 0)
            .map(|(m, &n)| (m as u8, n))
            .collect();
        Overlap {
            inside,
            outside: area - u64::from(inside),
            kinds,
            burning,
            materials,
        }
    }

    /// Contact damage of one frame on a box, with the per-pixel values of `materials.json`
    /// (`contact_damage_per_px_frame`: the player's table). An entity with its own table calls
    /// [`Overlap::contact_damage`] on `overlap(box)` instead (HAZ-R03).
    pub fn contact_damage(&self, b: Aabb, rules: ContactRules) -> ContactDamage {
        let mats = &self.content.mats;
        self.overlap(b).contact_damage(
            |m| {
                mats.get(m)
                    .map_or(0.0, |mat| mat.contact_damage_per_px_frame)
            },
            rules,
        )
    }
}
