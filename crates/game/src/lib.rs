//! Game logic of the Noita-like cogbench environment.
//!
//! This crate holds the rules that sit above the pixel simulation (`cogbench-sim`): spells and
//! wands, the player, enemies, items, barrels, projectiles and statuses. A [`Game`] owns the
//! simulated world and steps it one frame at a time under the player's [`Controls`]. The wand
//! engine itself ([`wand`]) has no world: it turns a click into a list of projectile requests,
//! and [`trial`] runs it for a while outside any world (the wand practice range).

pub mod control;
pub mod defs;
pub mod entity;
pub mod error;
pub mod game;
pub mod physics;
pub mod projectile;
pub mod rng;
pub mod spell;
pub mod status;
pub mod trial;
pub mod wand;

pub use control::{Controls, DropItem};
pub use defs::EntityDefs;
pub use error::Error;
pub use game::{
    BlastSpec, EntityView, Game, ItemSpec, PlayerView, WandEdit, WandView, WorldOptions,
};
pub use rng::{HashRng, SpellRandom, SpellRng};
pub use spell::{Spell, SpellBook, SpellId};
pub use status::Status;
