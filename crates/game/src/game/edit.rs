//! Changing what the player carries between frames: moving spells in and out of wands (the wand
//! editor, ACT-R03) and handing out loot for scenes and tests. These take no game time.

use cogbench_sim::Value;

use crate::entity::EntityId;
use crate::error::Error;
use crate::wand::{Slot, WandStats};

use super::Game;

/// One wand-editor action.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WandEdit {
    /// Put the spell `from` of the spell inventory into a slot. A spell that was there goes back
    /// into the inventory.
    Place {
        wand: usize,
        slot: usize,
        from: usize,
    },
    /// Take the spell out of a slot into the inventory.
    Take { wand: usize, slot: usize },
    /// Swap two slots of a wand.
    Swap { wand: usize, a: usize, b: usize },
}

impl Game {
    fn editable_player(&mut self) -> Result<&mut crate::entity::Player, Error> {
        match self.state.player.as_mut() {
            Some(p) if !p.vitals.dead => Ok(p),
            _ => Err(Error::arg("there is no living player")),
        }
    }

    /// Apply a wand-editor action; the wand is re-equipped (deck rebuilt, WAND-R56).
    pub fn edit_wand(&mut self, edit: WandEdit) -> Result<(), Error> {
        let max_spells = self.defs.items.spell.max_held;
        let p = self.editable_player()?;
        let wand_index = match edit {
            WandEdit::Place { wand, .. }
            | WandEdit::Take { wand, .. }
            | WandEdit::Swap { wand, .. } => wand,
        };
        let count = p.wands.len();
        let held = p.wands.get_mut(wand_index).ok_or_else(|| {
            Error::arg(format!("wand {wand_index} does not exist ({count} held)"))
        })?;
        match edit {
            WandEdit::Place { slot, from, .. } => {
                if from >= p.spells.len() {
                    return Err(Error::arg(format!(
                        "spell {from} does not exist ({} carried)",
                        p.spells.len()
                    )));
                }
                let old = held.wand.slots().get(slot).copied().flatten();
                let spell = p.spells.remove(from);
                if let Err(e) = held.wand.set_slot(slot, Some(spell)) {
                    p.spells.insert(from, spell);
                    return Err(e);
                }
                if let Some(old) = old {
                    p.spells.push(old);
                }
            }
            WandEdit::Take { slot, .. } => {
                let old = held.wand.slots().get(slot).copied().flatten();
                let Some(old) = old else {
                    return Err(Error::arg(format!("slot {slot} is empty")));
                };
                if p.spells.len() >= max_spells {
                    return Err(Error::arg("the spell inventory is full"));
                }
                held.wand.set_slot(slot, None)?;
                p.spells.push(old);
            }
            WandEdit::Swap { a, b, .. } => held.wand.swap_slots(a, b)?,
        }
        self.world
            .log_event("edit_wand", vec![("wand", Value::Int(wand_index as i64))]);
        Ok(())
    }

    /// Give the player a new wand (spell keys; `None` leaves a slot empty).
    pub fn give_wand(
        &mut self,
        stats: WandStats,
        spells: &[Option<String>],
        always_cast: &[String],
    ) -> Result<EntityId, Error> {
        self.editable_player()?;
        let held = self.make_wand(stats, spells, always_cast)?;
        let id = held.id;
        self.editable_player()?.wands.push(held);
        Ok(id)
    }

    /// Give the player a spell card for the spell inventory.
    pub fn give_spell(&mut self, key: &str) -> Result<(), Error> {
        let id = self
            .book
            .id(key)
            .ok_or_else(|| Error::arg(format!("unknown spell {key:?}")))?;
        let slot = Slot {
            spell: id,
            uses: self.book.get(id).max_uses,
        };
        self.editable_player()?.spells.push(slot);
        Ok(())
    }

    /// Give the player a bottle holding `amount` cells of a liquid (`None` material = empty).
    pub fn give_bottle(
        &mut self,
        material: Option<&str>,
        amount: Option<u32>,
    ) -> Result<(), Error> {
        let bottle = self.single_bottle(material, amount)?;
        self.editable_player()?.bottles.push(bottle);
        Ok(())
    }

    /// Give the player a bottle holding a mixture: material keys with cells.
    pub fn give_mixed_bottle(&mut self, contents: &[(String, u32)]) -> Result<(), Error> {
        let bottle = self.mixed_bottle(contents)?;
        self.editable_player()?.bottles.push(bottle);
        Ok(())
    }
}
