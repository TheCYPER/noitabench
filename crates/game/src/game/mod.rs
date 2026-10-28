//! The game: a pixel world plus the player, enemies, items and projectiles that live in it,
//! stepped one frame at a time in the fixed order of `tick-design.md` section 4.2:
//!
//! 1. controls become the player's intent and the player moves (and acts on items),
//! 2. enemies think and items fall (bottles mix their secret recipes),
//! 3. wands cast and projectiles fly, hit and explode,
//! 4. the pixel world steps (sand, liquids, gas, fire, reactions),
//! 5. damage, statuses, deaths and wand mana are settled,
//! 6. events and the recording are written.
//!
//! The game owns the [`World`]; every rule about cells stays in `cogbench-sim`. All randomness is
//! either a stateless hash of `(seed, frame, entity id)` ([`HashRng`]) or a wand's own stream, so
//! the same seed and the same controls give the same game, and a snapshot restores it exactly.

mod barrels;
mod blast;
mod bottles;
mod cast;
mod drop;
mod edit;
mod enemies;
mod enemy_ai;
mod environment;
mod items;
mod player;
mod player_motion;
mod potions;
mod projectiles;
mod record;
mod snapshot;
mod spawn;
mod view;
mod vitals;
mod wandgen;
mod world_load;

use std::sync::Arc;

use cogbench_sim::World;
use serde::{Deserialize, Serialize};

use crate::control::Controls;
use crate::defs::EntityDefs;
use crate::entity::{Enemy, EntityId, Item, Player, Target};
use crate::error::Error;
use crate::projectile::Projectile;
use crate::rng::HashRng;
use crate::spell::SpellBook;

pub use blast::BlastSpec;
pub use edit::WandEdit;
pub use spawn::ItemSpec;
pub use view::{EntityView, PlayerView, WandView};
pub use world_load::WorldOptions;

/// Everything that is not the pixel grid, in one serialisable piece.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub(crate) struct State {
    pub next_id: EntityId,
    pub player: Option<Player>,
    pub enemies: Vec<Enemy>,
    pub items: Vec<Item>,
    pub projectiles: Vec<Projectile>,
    /// Controls of the previous frame, for edge detection.
    pub prev: Controls,
}

impl State {
    fn new() -> State {
        State {
            next_id: 1,
            player: None,
            enemies: Vec::new(),
            items: Vec::new(),
            projectiles: Vec::new(),
            prev: Controls::default(),
        }
    }

    pub fn fresh_id(&mut self) -> EntityId {
        let id = self.next_id;
        self.next_id += 1;
        id
    }
}

pub struct Game {
    pub(crate) world: World,
    pub(crate) book: Arc<SpellBook>,
    pub(crate) defs: Arc<EntityDefs>,
    /// The `ai` stream of the episode seed.
    pub(crate) ai: HashRng,
    pub(crate) state: State,
    pub(crate) recorder: Option<record::EntityRecorder>,
    /// Markers of the world file that are not spawns (encounters, rest areas, the seal).
    pub(crate) markers: Vec<serde_json::Value>,
    /// Projectiles taken out of the state while they fly one frame: new ones made on the way
    /// (payloads) still count against `max_projectiles`. Zero between frames, never serialised.
    pub(crate) flying: usize,
}

impl Game {
    /// A game on `world` with the content compiled into this crate.
    pub fn new(world: World) -> Result<Game, Error> {
        let book = Arc::new(SpellBook::embedded()?);
        let defs = Arc::new(EntityDefs::embedded()?);
        Game::with_content(world, book, defs)
    }

    /// An empty (all air) world of `width` x `height` cells with the embedded content.
    pub fn empty(width: i32, height: i32, seed: u64) -> Result<Game, Error> {
        let content = Arc::new(cogbench_sim::Content::embedded()?);
        Game::new(World::new(width, height, seed, content)?)
    }

    pub fn with_content(
        world: World,
        book: Arc<SpellBook>,
        defs: Arc<EntityDefs>,
    ) -> Result<Game, Error> {
        let game = Game {
            ai: HashRng::stream(world.seed(), "ai"),
            world,
            book,
            defs,
            state: State::new(),
            recorder: None,
            markers: Vec::new(),
            flying: 0,
        };
        game.check_content()?;
        Ok(game)
    }

    /// Every material and spell the entity numbers name must exist.
    fn check_content(&self) -> Result<(), Error> {
        let mats = &self.world.content().mats;
        self.book
            .check_materials(&|key| mats.index_of(key).is_some())?;
        let file = "content/entities.json";
        let known = |field: String, key: &str| match mats.index_of(key) {
            Some(_) => Ok(()),
            None => Err(Error::content(
                file,
                field,
                format!("unknown material {key:?}"),
            )),
        };
        let d = &self.defs;
        for key in d
            .contact
            .status
            .keys()
            .chain(d.contact.heal_per_px_frame.keys())
        {
            known(format!("contact.{key}"), key)?;
        }
        for key in &d.contact.ignite {
            known("contact.ignite".into(), key)?;
        }
        // Drinking looks the effect up by the material's `drink_effect`; "none" does nothing.
        for m in mats.iter() {
            let effect = m.drink_effect.as_str();
            if effect != "none" && !d.drink.contains_key(effect) {
                let message = format!(
                    "material {:?} has drink_effect {effect:?}, which entities.json lacks",
                    m.key
                );
                return Err(Error::content(file, "drink", message));
            }
        }
        for (key, barrel) in &d.items.barrels {
            if let Some(c) = &barrel.contents {
                known(format!("items.barrels.{key}.contents"), &c.material)?;
            }
        }
        for (key, enemy) in &d.enemies {
            for m in enemy.contact_damage.keys() {
                known(format!("enemies.{key}.contact_damage"), m)?;
            }
        }
        for key in &d.spell_pickup_exclude {
            if self.book.id(key).is_none() {
                let message = format!("unknown spell {key:?}");
                return Err(Error::content(file, "spell_pickup_exclude", message));
            }
        }
        for (key, effect) in &d.drink {
            if effect.frames_per_cell < 0.0 || !effect.frames_per_cell.is_finite() {
                let message = "frames_per_cell must be a number of 0 or more".to_string();
                return Err(Error::content(file, format!("drink.{key}"), message));
            }
        }
        for wand in &d.starter.wands {
            for spell in &wand.spells {
                if self.book.id(spell).is_none() {
                    let message = format!("unknown spell {spell:?}");
                    return Err(Error::content(file, "starter.wands", message));
                }
            }
        }
        Ok(())
    }

    // ----- reading ---------------------------------------------------------------------------

    pub fn world(&self) -> &World {
        &self.world
    }

    /// The pixel world, for painting scenes and igniting things between frames.
    pub fn world_mut(&mut self) -> &mut World {
        &mut self.world
    }

    pub fn book(&self) -> &SpellBook {
        &self.book
    }

    pub fn defs(&self) -> &EntityDefs {
        &self.defs
    }

    pub fn frame(&self) -> u64 {
        self.world.frame()
    }

    /// Markers of the loaded world that are not spawns: encounters, rest areas, the seal.
    pub fn markers(&self) -> &[serde_json::Value] {
        &self.markers
    }

    pub fn player_alive(&self) -> bool {
        self.state.player.as_ref().is_some_and(|p| !p.vitals.dead)
    }

    // ----- stepping --------------------------------------------------------------------------

    /// Advance one frame with `controls` held.
    pub fn step(&mut self, controls: &Controls) -> Result<(), Error> {
        let controls = &controls.sanitized();
        self.process_breaks();
        self.update_player(controls);
        self.update_enemies();
        self.update_items();
        self.mix_bottles();
        self.cast_player_wand(controls);
        self.update_projectiles();
        self.process_breaks();
        self.world.step()?;
        self.settle();
        self.state.prev = controls.clone();
        self.record_entities()?;
        Ok(())
    }

    /// Advance `frames` frames holding the same controls.
    pub fn step_frames(&mut self, frames: u32, controls: &Controls) -> Result<(), Error> {
        for _ in 0..frames {
            self.step(controls)?;
        }
        Ok(())
    }

    // ----- helpers shared by the modules -----------------------------------------------------

    /// Hash of the whole state: the pixel world, entities, wands and random streams.
    pub fn state_hash(&self) -> u64 {
        let mut h = self.world.state_hash();
        let bytes = serde_json::to_vec(&self.state).unwrap_or_default();
        for b in bytes {
            h ^= u64::from(b);
            h = h.wrapping_mul(0x0000_0100_0000_01b3);
        }
        h
    }

    pub(crate) fn mat_index(&self, key: &str) -> Option<u8> {
        self.world.content().mats.index_of(key)
    }

    /// Item and enemy lookups by id (the lists are short and ordered by creation).
    pub(crate) fn enemy_index(&self, id: EntityId) -> Option<usize> {
        self.state.enemies.iter().position(|e| e.id == id)
    }

    pub(crate) fn item_index(&self, id: EntityId) -> Option<usize> {
        self.state.items.iter().position(|i| i.id == id)
    }

    /// Is the target there and still alive?
    pub(crate) fn target_exists(&self, t: Target) -> bool {
        match t {
            Target::Player => self.player_alive(),
            Target::Enemy(id) => self
                .enemy_index(id)
                .is_some_and(|i| !self.state.enemies[i].vitals.dead),
            Target::Item(id) => self
                .item_index(id)
                .is_some_and(|i| !self.state.items[i].dead),
        }
    }
}
