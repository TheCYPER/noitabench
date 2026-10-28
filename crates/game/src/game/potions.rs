//! What the secret potions change besides the damage rules (`vitals.rs`, `environment.rs`) and
//! the player's movement (`player_motion.rs`): how much the player's hits are boosted and
//! whether enemies can see the player. The numbers are in `entities.json` `statuses`.

use crate::status::Status;

use super::Game;

impl Game {
    /// `(critical chance bonus in percentage points, damage multiplier)` of the player's own
    /// hits and explosions: the `crit_boost` and `berserk` statuses.
    pub(crate) fn player_boosts(&self) -> (f32, f32) {
        let sd = &self.defs.statuses;
        let Some(p) = self.state.player.as_ref() else {
            return (0.0, 1.0);
        };
        let st = &p.vitals.statuses;
        let crit = if st.has(Status::CritBoost) {
            sd.crit_boost.bonus_percent
        } else {
            0.0
        };
        let damage = if st.has(Status::Berserk) {
            sd.berserk.damage_mul
        } else {
            1.0
        };
        (crit, damage)
    }

    /// Casting a wand or kicking shows an invisible player for a while.
    pub(crate) fn reveal_player(&mut self) {
        let frames = self.defs.statuses.invisible.reveal_frames;
        if let Some(p) = self.state.player.as_mut() {
            if p.vitals.statuses.has(Status::Invisible) {
                p.revealed = p.revealed.max(frames);
            }
        }
    }

    /// Can enemies notice the player? Not while invisible and not revealed.
    pub(crate) fn player_visible_to_enemies(&self) -> bool {
        self.state
            .player
            .as_ref()
            .is_none_or(|p| !p.vitals.statuses.has(Status::Invisible) || p.revealed > 0)
    }
}
