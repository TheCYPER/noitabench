//! The per-frame input of the player (tick-design section 4.2, step 1).
//!
//! Week 3 builds commands and interrupts on top of this; here a control state is just what a
//! person holds down in one frame. Keys that act on a press (jump, kick, interact, throw) fire
//! on the frame they go from released to held.

use serde::{Deserialize, Serialize};

/// What the `drop` control puts on the ground, by index into what the player carries.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum DropItem {
    /// The wand with this index in the hand.
    Wand(u8),
    /// The carried spell card with this index.
    Spell(u8),
    /// The bottle with this index.
    Bottle(u8),
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Controls {
    /// -1 left, 0 stand, 1 right.
    pub move_x: i8,
    pub jump: bool,
    /// Levitate (swim up in liquid).
    pub fly: bool,
    /// Aim in degrees: 0 is right, 90 is up, -90 is down.
    pub aim: f32,
    /// Cast with the active wand whenever it is ready.
    pub fire: bool,
    pub kick: bool,
    /// Pick up the nearest wand, spell or bottle.
    pub interact: bool,
    /// Drink from the active bottle.
    pub drink: bool,
    /// Pour the active bottle out in front of the player.
    pub pour: bool,
    /// Scoop liquid around the feet into the active bottle.
    pub fill: bool,
    /// Throw the active bottle along the aim.
    pub throw: bool,
    /// Make this wand (index into the held wands) the active one.
    pub select_wand: Option<u8>,
    /// Make this bottle the active one.
    pub select_bottle: Option<u8>,
    /// Put a wand, a carried spell or a bottle on the ground next to the player. It acts on the
    /// frame the control appears or changes (holding the same value drops nothing more); an index
    /// that is out of range is ignored.
    #[serde(default)]
    pub drop: Option<DropItem>,
}

impl Controls {
    /// Held keys of the last frame against this one: `true` only on the frame a key goes down.
    pub fn pressed(&self, previous: &Controls) -> Pressed {
        Pressed {
            jump: self.jump && !previous.jump,
            fly: self.fly && !previous.fly,
            kick: self.kick && !previous.kick,
            interact: self.interact && !previous.interact,
            throw: self.throw && !previous.throw,
            drop: self.drop.filter(|d| previous.drop != Some(*d)),
        }
    }

    /// The same controls with a finite aim (a NaN or infinite aim becomes straight ahead).
    pub fn sanitized(&self) -> Controls {
        Controls {
            aim: if self.aim.is_finite() { self.aim } else { 0.0 },
            ..self.clone()
        }
    }

    /// The same keys with nothing held (used for a dead player).
    pub fn idle(&self) -> Controls {
        Controls {
            aim: if self.aim.is_finite() { self.aim } else { 0.0 },
            ..Controls::default()
        }
    }
}

/// Keys that went down this frame (`drop`: the item named by a `drop` control that is new).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Pressed {
    pub jump: bool,
    pub fly: bool,
    pub kick: bool,
    pub interact: bool,
    pub throw: bool,
    pub drop: Option<DropItem>,
}
