//! The deck / discard piles of a wand (the hand only exists while a click is being dealt).

use std::collections::VecDeque;

use serde::{Deserialize, Serialize};

use crate::spell::SpellId;

use super::Slot;

/// A card in a pile: a spell and the slot it came from (`None` for the copy an always-cast
/// plays, which is never in the deck).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Card {
    pub spell: SpellId,
    pub slot: Option<u16>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub(super) struct Cycle {
    /// Cards still to be dealt; the front is drawn first.
    pub deck: VecDeque<Card>,
    pub discarded: Vec<Card>,
    /// Recharge time accumulated this cycle: wand base plus every card played (WAND-R52).
    pub current_reload: i32,
    /// The next click is the first since the wand was equipped (WAND-R12).
    pub first_shot: bool,
}

impl Cycle {
    /// Deck := every non-empty slot in slot order; piles cleared; first shot pending (WAND-R10).
    pub fn rebuild(&mut self, slots: &[Option<Slot>], base_recharge: i32) {
        self.deck = slots
            .iter()
            .enumerate()
            .filter_map(|(i, slot)| {
                slot.map(|s| Card {
                    spell: s.spell,
                    slot: Some(i as u16),
                })
            })
            .collect();
        self.discarded.clear();
        self.current_reload = base_recharge;
        self.first_shot = true;
    }
}
