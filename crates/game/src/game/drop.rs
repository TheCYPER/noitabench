//! Putting things down: the `drop` control moves a wand, a carried spell or a bottle from the
//! player's hands to the ground beside the player, where it is an ordinary item again (it falls,
//! can be kicked and picked up with `interact`). The contents of a bottle and the cards and
//! random stream of a wand go with it unchanged.

use cogbench_sim::{KindMask, Value};

use crate::control::DropItem;
use crate::entity::{Item, ItemKind};
use crate::physics::Body;

use super::Game;

/// What leaves the player's hands: the item, its size, its name in the event and its detail.
struct Dropped {
    kind: ItemKind,
    size: (i32, i32),
    name: &'static str,
    detail: String,
}

impl Game {
    /// Drop what `what` names; an index the player does not have does nothing.
    pub(crate) fn drop_item(&mut self, what: DropItem) {
        if matches!(what, DropItem::Bottle(_)) {
            self.flush_bottle_action(); // a drink or pour of the bottle ends here
        }
        let Some(Dropped {
            kind,
            size,
            name,
            detail,
        }) = self.take_from_hands(what)
        else {
            return;
        };
        // What was dropped, as the pickup event of the same thing tells it.
        let detail = match &kind {
            ItemKind::Bottle(b) if !b.is_empty() => self.contents_label(b),
            _ => detail,
        };
        let body = self.drop_body(size.0, size.1);
        let id = self.state.fresh_id();
        self.state.items.push(Item {
            id,
            body,
            kind,
            hp: 0.0,
            hp_max: 0.0,
            asleep: false,
            lit: 0,
            dead: false,
            logged_damage: 0.0,
        });
        self.world.log_event(
            "drop",
            vec![
                ("item", Value::Str(name.into())),
                ("detail", Value::Str(detail)),
                ("id", Value::Int(i64::from(id))),
            ],
        );
    }

    /// Take the thing out of the player's hands, keeping the held indices pointing at the same
    /// things. `None` when the player has no such thing.
    fn take_from_hands(&mut self, what: DropItem) -> Option<Dropped> {
        let defs = self.defs.clone();
        let items = &defs.items;
        let p = self.state.player.as_mut()?;
        Some(match what {
            DropItem::Wand(i) => {
                let i = usize::from(i);
                if i >= p.wands.len() {
                    return None;
                }
                let held = p.wands.remove(i);
                p.active_wand = shifted(p.active_wand, i, p.wands.len());
                Dropped {
                    kind: ItemKind::Wand(Box::new(held)),
                    size: (items.wand.w, items.wand.h),
                    name: "wand",
                    detail: String::new(),
                }
            }
            DropItem::Spell(i) => {
                let i = usize::from(i);
                if i >= p.spells.len() {
                    return None;
                }
                let slot = p.spells.remove(i);
                let detail = self.book.key(slot.spell).to_string();
                Dropped {
                    kind: ItemKind::Spell(slot),
                    size: (items.spell.w, items.spell.h),
                    name: "spell",
                    detail,
                }
            }
            DropItem::Bottle(i) => {
                let i = usize::from(i);
                if i >= p.bottles.len() {
                    return None;
                }
                let bottle = p.bottles.remove(i);
                p.active_bottle = shifted(p.active_bottle, i, p.bottles.len());
                Dropped {
                    kind: ItemKind::Bottle(bottle),
                    size: (items.bottle.w, items.bottle.h),
                    name: "bottle",
                    detail: String::new(),
                }
            }
        })
    }

    /// The body of a dropped item of size `w` x `h`: beside the player on the side it faces,
    /// else on the other side, else on the player; its bottom at the player's feet, free of
    /// terrain where possible.
    fn drop_body(&self, w: i32, h: i32) -> Body {
        let Some(p) = self.state.player.as_ref() else {
            return Body::new(0, 0, w, h);
        };
        let (px, py) = p.body.cell();
        let (mid, y) = (px + p.body.w / 2, py + p.body.h - h);
        let side = i32::from(p.facing);
        let offset = p.body.w / 2 + w / 2 + 1;
        [mid + side * offset, mid - side * offset, mid]
            .into_iter()
            .map(|cx| Body::new(cx - w / 2, y, w, h))
            .find(|b| !self.world.box_blocked(b.aabb(), KindMask::BLOCKING))
            .unwrap_or_else(|| Body::new(mid - w / 2, y, w, h))
    }
}

/// The index of the held thing after the one at `removed` left a list that now has `len`
/// entries: the same thing if it is still there, else the one that took its place (or the last).
fn shifted(active: usize, removed: usize, len: usize) -> usize {
    let moved = if removed < active { active - 1 } else { active };
    moved.min(len.saturating_sub(1))
}

#[cfg(test)]
mod tests {
    use super::shifted;

    #[test]
    fn the_held_index_follows_the_thing_it_pointed_at() {
        assert_eq!(shifted(2, 0, 2), 1, "an earlier one left: shift down");
        assert_eq!(shifted(0, 1, 2), 0, "a later one left: unchanged");
        assert_eq!(
            shifted(1, 1, 1),
            0,
            "the held one left from the end: the last"
        );
        assert_eq!(
            shifted(0, 0, 3),
            0,
            "the held one left: the next takes its place"
        );
        assert_eq!(shifted(0, 0, 0), 0, "nothing left");
    }
}
