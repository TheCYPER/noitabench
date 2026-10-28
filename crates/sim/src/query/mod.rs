//! Questions about the grid that entities and projectiles ask (SIM-R60..R65): rays, box sweeps,
//! overlap counts and contact damage.
//!
//! Everything here is a pure read of the world: no randomness, no writes, and the same answer
//! for the same grid on every platform (integer arithmetic only, apart from the contact damage
//! sum, which uses exactly rounded `f64` additions and products in a fixed order). Entity state
//! never lives in this crate; the game crate keeps positions and calls these functions with a box
//! or a segment in cell coordinates (origin top-left, y grows downward).
//!
//! Collision classes follow MVP-R05: static and powder cells block, liquid cells do not block but
//! are reported (by [`Overlap`]), gas, fire and air are passed. Cells outside the world are the
//! `boundary` material (SIM-R01): they block every query, whatever its mask.

mod overlap;
mod ray;
mod sweep;

pub use overlap::{ContactDamage, ContactPart, ContactRules, Overlap};
pub use ray::{unit_q16, Hit};
pub use sweep::Sweep;

use crate::consts::BOUNDARY;
use crate::material::{Kind, MaterialSet};

/// A set of cell kinds.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct KindMask(u8);

impl KindMask {
    pub const NONE: KindMask = KindMask(0);
    pub const AIR: KindMask = KindMask::of(Kind::Air);
    pub const GAS: KindMask = KindMask::of(Kind::Gas);
    pub const FIRE: KindMask = KindMask::of(Kind::Fire);
    pub const LIQUID: KindMask = KindMask::of(Kind::Liquid);
    pub const POWDER: KindMask = KindMask::of(Kind::Powder);
    pub const STATIC: KindMask = KindMask::of(Kind::Static);

    /// `Raytrace` (SIM-R60): stops on any cell that is not air.
    pub const RAYTRACE: KindMask = KindMask(
        KindMask::GAS.0
            | KindMask::FIRE.0
            | KindMask::LIQUID.0
            | KindMask::POWDER.0
            | KindMask::STATIC.0,
    );
    /// `RaytraceSurfaces`: stops on cells that are not liquid, gas or fire.
    pub const SURFACES: KindMask = KindMask(KindMask::POWDER.0 | KindMask::STATIC.0);
    /// `RaytraceSurfacesAndLiquiform`: stops on cells that are not gas or fire.
    pub const SURFACES_AND_LIQUIDS: KindMask =
        KindMask(KindMask::LIQUID.0 | KindMask::POWDER.0 | KindMask::STATIC.0);
    /// `RaytracePlatforms`: cells a character can stand on. Kind-based in v1 (SIM-R64), so the
    /// same set as [`KindMask::SURFACES`].
    pub const PLATFORMS: KindMask = KindMask::SURFACES;
    /// What entities collide with (MVP-R05): static and powder.
    pub const BLOCKING: KindMask = KindMask::SURFACES;

    pub const fn of(kind: Kind) -> KindMask {
        KindMask(1 << kind.index())
    }

    pub const fn contains(self, kind: Kind) -> bool {
        self.0 & (1 << kind.index()) != 0
    }

    pub const fn union(self, other: KindMask) -> KindMask {
        KindMask(self.0 | other.0)
    }

    pub const fn without(self, other: KindMask) -> KindMask {
        KindMask(self.0 & !other.0)
    }

    /// A preset by its name: `any`, `surfaces`, `surfaces_and_liquids`, `platforms`, `blocking`
    /// (the names the Python layer uses).
    pub fn preset(name: &str) -> Option<KindMask> {
        match name {
            "any" | "raytrace" => Some(KindMask::RAYTRACE),
            "surfaces" => Some(KindMask::SURFACES),
            "surfaces_and_liquids" => Some(KindMask::SURFACES_AND_LIQUIDS),
            "platforms" => Some(KindMask::PLATFORMS),
            "blocking" => Some(KindMask::BLOCKING),
            _ => None,
        }
    }
}

/// What a query treats as an obstacle: a set of kinds, minus one material it passes through
/// (SIM-R62: a projectile's `go_through_this_material`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct QueryMask {
    pub kinds: KindMask,
    pub pass: Option<u8>,
}

impl QueryMask {
    pub const fn new(kinds: KindMask) -> QueryMask {
        QueryMask { kinds, pass: None }
    }

    /// The same mask, except that cells of `material` are not obstacles.
    pub const fn passing(self, material: u8) -> QueryMask {
        QueryMask {
            pass: Some(material),
            ..self
        }
    }

    /// Whether a cell of material index `mat` stops a query with this mask.
    #[inline]
    pub(crate) fn blocks(&self, mats: &MaterialSet, mat: u8) -> bool {
        if mat == BOUNDARY {
            return true;
        }
        self.pass != Some(mat) && self.kinds.contains(mats.rt(mat).kind)
    }
}

impl From<KindMask> for QueryMask {
    fn from(kinds: KindMask) -> QueryMask {
        QueryMask::new(kinds)
    }
}

/// An axis-aligned box of cells: top-left corner and size (contract section 4). A box with
/// `w <= 0` or `h <= 0` is empty: it covers no cells, blocks nothing and does not move.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Aabb {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

impl Aabb {
    pub const fn new(x: i32, y: i32, w: i32, h: i32) -> Aabb {
        Aabb { x, y, w, h }
    }

    pub const fn is_empty(&self) -> bool {
        self.w <= 0 || self.h <= 0
    }
}
