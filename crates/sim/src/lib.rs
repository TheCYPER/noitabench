//! `cogbench-sim`: the deterministic falling-sand simulation of the cogbench environment.
//!
//! Layout follows `.trellis/spec/backend/directory-structure.md`. Game rules live here and in
//! `cogbench-game`; the Python module (`cogbench-py`) only wraps this crate.

pub mod consts;
pub mod content;
pub mod detmath;
pub mod error;
pub mod event;
pub mod grid;
pub mod material;
mod material_file;
pub mod query;
pub mod reaction;
pub mod recipe;
pub mod record;
pub mod rng;
mod rules;
mod snapshot;
pub mod world;
mod world_io;
pub mod worldfile;

pub use consts::Tuning;
pub use content::{embedded_reaction_defs, Content};
pub use error::{Error, Result};
pub use event::{Event, Value};
pub use grid::{Cell, Grid, Rect};
pub use material::{ExplosionParams, Kind, Material, MaterialSet};
pub use query::{
    unit_q16, Aabb, ContactDamage, ContactPart, ContactRules, Hit, KindMask, Overlap, QueryMask,
    Sweep,
};
pub use reaction::{ReactionDef, ReactionTable};
pub use recipe::{Recipe, RecipeDef, MAX_RECIPES};
pub use record::{RecordConfig, RecordSummary};
pub use rules::{ray_count, ExplosionSpec};
pub use world::{CellInfo, DirtyMode, Explosion, World};
