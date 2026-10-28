//! One click: dealing the cards (WAND-R12, R20..R25, R30..R34, R40..R44, R50..R55, R60..R63,
//! R70..R72). This follows the reference pseudocode of `wand-casting.md` for the stage-1 spells.

use crate::rng::SpellRandom;
use crate::spell::{Spell, SpellBook, SpellId, SpellType, TriggerSpec};

use super::cycle::{Card, Cycle};
use super::shot::{
    CastResult, Node, PendingPayload, ProjectileSpawn, ShotParams, ShotState, SkipReason, Skipped,
    Trigger,
};
use super::{Slot, Wand, WandStats};

/// Deal one click of `wand` and update its piles, mana and recharge accounting.
pub(super) fn click(wand: &mut Wand, book: &SpellBook, rng: &mut dyn SpellRandom) -> CastResult {
    let Wand {
        stats,
        slots,
        always_cast,
        mana,
        cycle,
        ..
    } = wand;
    let click = Click {
        book,
        rng,
        stats,
        slots,
        cycle,
        // WAND-R12: the cap applies at click start; mana may exceed it inside the click.
        mana: mana.min(stats.mana_max),
        hand: Vec::new(),
        root: ShotState::new(ShotParams::root(stats)),
        payloads: Vec::new(),
        got_projectiles: false,
        reloading: false,
        start_reload: false,
        wrapped: false,
        playing_always_cast: false,
        recoil: 0.0,
        skipped: Vec::new(),
    };
    let (result, mana_after) = click.run(always_cast);
    *mana = mana_after;
    result
}

struct Click<'a> {
    book: &'a SpellBook,
    rng: &'a mut dyn SpellRandom,
    stats: &'a WandStats,
    slots: &'a mut Vec<Option<Slot>>,
    cycle: &'a mut Cycle,
    mana: f32,
    hand: Vec<Card>,
    root: ShotState,
    /// Payload shot states being filled, innermost last.
    payloads: Vec<ShotState>,
    got_projectiles: bool,
    reloading: bool,
    start_reload: bool,
    wrapped: bool,
    playing_always_cast: bool,
    recoil: f32,
    skipped: Vec<Skipped>,
}

impl Click<'_> {
    fn run(mut self, always_cast: &[SpellId]) -> (CastResult, f32) {
        let mana_before = self.mana;
        if self.cycle.first_shot {
            self.order_deck();
            self.cycle.current_reload = self.stats.recharge;
            self.cycle.first_shot = false;
        }
        for &id in always_cast {
            self.play_always_cast(id);
        }
        self.draw_actions(self.stats.spells_per_cast, false);
        let played: Vec<SpellId> = self.hand.iter().map(|card| card.spell).collect();
        self.move_hand_to_discarded();
        let recharge = self.maybe_start_recharge();

        let has_projectile = !self.root.nodes.is_empty();
        let root_params = self.root.params.clone();
        // WAND-R53: the clamp applies to the total; a click without projectile waits one frame.
        let cast_delay = if has_projectile {
            root_params.cast_delay.max(1) as u32
        } else {
            1
        };
        let mana_after = self.mana;
        let result = CastResult {
            root: root_params,
            played,
            skipped: std::mem::take(&mut self.skipped),
            mana_before,
            mana_after,
            mana_spent: mana_before - mana_after,
            cast_delay,
            recharge,
            ready_in: cast_delay.max(recharge.unwrap_or(0)),
            wrapped: self.wrapped,
            recoil: self.recoil,
            projectiles: build_spawns(self.book, self.rng, self.root),
        };
        (result, mana_after)
    }

    fn current(&mut self) -> &mut ShotState {
        self.payloads.last_mut().unwrap_or(&mut self.root)
    }

    /// WAND-R70: always-casts are played before the wand's own draws, free unless their cost is
    /// negative, from no slot; their copy is dropped at the end of the click.
    fn play_always_cast(&mut self, id: SpellId) {
        let cost = self.book.get(id).mana;
        if cost < 0 {
            self.mana -= cost as f32;
        }
        self.playing_always_cast = true;
        self.play(Card {
            spell: id,
            slot: None,
        });
        self.playing_always_cast = false;
    }

    /// WAND-R20..R25: deal `n` cards. A draw that fails (card skipped) retries with the next card.
    fn draw_actions(&mut self, n: u32, instant: bool) {
        if self.playing_always_cast && n == 1 {
            return; // WAND-R71
        }
        for _ in 0..n {
            if !self.draw_action(instant) {
                while !self.cycle.deck.is_empty() {
                    if self.draw_action(instant) {
                        break;
                    }
                }
            }
            if self.reloading {
                return;
            }
        }
    }

    /// Draw one card; `false` means it was skipped and the draw must be retried.
    fn draw_action(&mut self, instant: bool) -> bool {
        if self.cycle.deck.is_empty() {
            if !instant {
                // The wand's own draw on an empty deck never wraps (WAND-R22).
                self.reloading = true;
                return true;
            }
            self.wrap();
        }
        let Some(card) = self.cycle.deck.pop_front() else {
            return true; // the wrap found nothing: the draw is consumed (WAND-R23)
        };
        let book = self.book;
        let spell = book.get(card.spell);
        let reason = if self.uses_left(card) == Some(0) {
            Some(SkipReason::NoUsesLeft)
        } else if spell.mana as f32 > self.mana {
            Some(SkipReason::NotEnoughMana)
        } else {
            None
        };
        if let Some(reason) = reason {
            self.cycle.discarded.push(card);
            self.skipped.push(Skipped {
                spell: card.spell,
                reason,
            });
            return false;
        }
        self.mana -= spell.mana as f32;
        self.play(card);
        true
    }

    /// WAND-R23: refill the empty deck from the discard pile.
    fn wrap(&mut self) {
        let discarded = std::mem::take(&mut self.cycle.discarded);
        self.cycle.deck.extend(discarded);
        self.order_deck();
        self.start_reload = true;
        self.wrapped = true;
    }

    /// Remaining uses of the slot a card came from; `None` is unlimited (and always-cast copies).
    fn uses_left(&self, card: Card) -> Option<u32> {
        let slot = self.slots.get(usize::from(card.slot?))?.as_ref()?;
        slot.uses
    }

    /// WAND-R11: slot order, or a uniform shuffle (remove a random remaining card, append it).
    fn order_deck(&mut self) {
        if !self.stats.shuffle {
            self.cycle
                .deck
                .make_contiguous()
                .sort_by_key(|card| card.slot);
            return;
        }
        let mut remaining: Vec<Card> = self.cycle.deck.drain(..).collect();
        while !remaining.is_empty() {
            let last = remaining.len() - 1;
            let pick = (self.rng.shuffle_index(remaining.len() as u32) as usize).min(last);
            self.cycle.deck.push_back(remaining.remove(pick));
        }
    }

    fn play(&mut self, card: Card) {
        let book = self.book;
        let spell = book.get(card.spell);
        self.hand.push(card);
        self.run_action(card.spell, spell);
        if spell.kind.adds_projectile() {
            self.got_projectiles = true;
        }
    }

    /// WAND-R30..R34: a multicast deals its cards first and then applies its own deltas; every
    /// other card applies its deltas first, then adds its projectile or draws.
    fn run_action(&mut self, id: SpellId, spell: &Spell) {
        if spell.kind == SpellType::Multicast {
            self.draw_actions(spell.draw, true);
            self.apply_deltas(id, spell);
            return;
        }
        self.apply_deltas(id, spell);
        match spell.kind {
            SpellType::Modifier => self.draw_actions(spell.draw, true),
            SpellType::Projectile | SpellType::StaticProjectile | SpellType::Material => {
                self.current().nodes.push(Node {
                    spell: id,
                    payload: None,
                });
                if let Some(trigger) = &spell.trigger {
                    self.fill_payload(trigger);
                }
            }
            SpellType::Multicast => {}
        }
    }

    /// Recharge, recoil and mana are global; everything else goes to the current shot state.
    fn apply_deltas(&mut self, id: SpellId, spell: &Spell) {
        self.cycle.current_reload += spell.recharge;
        self.recoil += spell.recoil;
        self.current().params.apply(id, spell);
    }

    /// WAND-R40: the payload is a fresh shot state, drawn (and paid) now, attached to the trigger
    /// projectile just added to the enclosing shot state.
    fn fill_payload(&mut self, trigger: &TriggerSpec) {
        self.payloads.push(ShotState::new(ShotParams::payload()));
        self.draw_actions(trigger.payload_draws, true);
        let Some(shot) = self.payloads.pop() else {
            return;
        };
        if let Some(node) = self.current().nodes.last_mut() {
            node.payload = Some(PendingPayload {
                kind: trigger.kind,
                timer_frames: trigger.timer_frames,
                shot,
            });
        }
    }

    /// WAND-R50 / R63: the hand goes to the discard pile in play order; limited cards pay one use
    /// if the click produced a projectile, and leave the cycle when they reach 0.
    fn move_hand_to_discarded(&mut self) {
        for card in std::mem::take(&mut self.hand) {
            let Some(index) = card.slot else { continue }; // always-cast copies are dropped
            let Some(Some(slot)) = self.slots.get_mut(usize::from(index)) else {
                continue;
            };
            if let (true, Some(uses)) = (self.got_projectiles, slot.uses) {
                slot.uses = Some(uses.saturating_sub(1));
            }
            if slot.uses != Some(0) {
                self.cycle.discarded.push(card);
            }
        }
    }

    /// WAND-R51: a recharge starts when the deck ran dry or a spell's draw wrapped it.
    fn maybe_start_recharge(&mut self) -> Option<u32> {
        if !(self.reloading || self.cycle.deck.is_empty() || self.start_reload) {
            return None;
        }
        let discarded = std::mem::take(&mut self.cycle.discarded);
        self.cycle.deck.extend(discarded);
        self.order_deck();
        let frames = self.cycle.current_reload.max(0) as u32; // WAND-R55
        self.cycle.current_reload = self.stats.recharge;
        Some(frames)
    }
}

/// Turn a finished shot state into projectile requests, rolling each one's spread angle.
fn build_spawns(
    book: &SpellBook,
    rng: &mut dyn SpellRandom,
    shot: ShotState,
) -> Vec<ProjectileSpawn> {
    let ShotState { params, nodes } = shot;
    let mut spawns = Vec::with_capacity(nodes.len());
    for node in nodes {
        let innate = book
            .get(node.spell)
            .projectile
            .as_ref()
            .map_or(0.0, |p| p.innate_spread);
        let spread = (params.spread + innate).max(0.0);
        let angle = if spread > 0.0 {
            (2.0 * rng.spread_unit() - 1.0) * spread
        } else {
            0.0
        };
        let trigger = node.payload.map(|p| Trigger {
            kind: p.kind,
            timer_frames: p.timer_frames,
            payload: build_spawns(book, rng, p.shot),
        });
        spawns.push(ProjectileSpawn {
            spell: node.spell,
            shot: params.clone(),
            spread_degrees: spread,
            angle_offset_degrees: angle,
            trigger,
        });
    }
    spawns
}
