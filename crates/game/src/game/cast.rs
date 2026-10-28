//! Casting with the player's active wand (tick-design step 4): one click of the wand engine
//! becomes projectiles, bombs and blasts in the world.

use cogbench_sim::Value;

use crate::control::Controls;
use crate::entity::Owner;
use crate::error::Error;
use crate::physics::{aim_vector, rotate};
use crate::projectile::{shot_from_spawn, Shot};
use crate::status::Status;

use super::Game;

impl Game {
    /// The aim of this frame in degrees, wobbled when the player is drunk.
    pub(crate) fn effective_aim(&self, aim: f32, salt: u64) -> f32 {
        let Some(p) = self.state.player.as_ref() else {
            return aim;
        };
        if !p.vitals.statuses.has(Status::Drunk) {
            return aim;
        }
        let jitter = self.defs.statuses.drunk.aim_jitter_degrees;
        let u = self.ai.unit(self.world.frame(), u64::from(p.id), salt);
        aim + (2.0 * u - 1.0) * jitter
    }

    /// The unit vector of the (possibly wobbling) aim.
    pub(crate) fn aim_dir(&self, controls: &Controls, salt: u64) -> (f32, f32) {
        aim_vector(self.effective_aim(controls.aim, salt))
    }

    /// Where a shot leaves the player: the hand, moved out along the aim.
    pub(crate) fn muzzle(&self, dir: (f32, f32)) -> (f32, f32) {
        let pd = &self.defs.player;
        let Some(p) = self.state.player.as_ref() else {
            return (0.0, 0.0);
        };
        let (cx, cy) = p.body.cell();
        (
            (cx + pd.hand.dx) as f32 + 0.5 + dir.0 * pd.muzzle_distance,
            (cy + pd.hand.dy) as f32 + 0.5 + dir.1 * pd.muzzle_distance,
        )
    }

    /// Fire the active wand if the key is held and the wand is ready.
    pub(crate) fn cast_player_wand(&mut self, controls: &Controls) {
        if !controls.fire || !self.player_alive() {
            return;
        }
        let book = self.book.clone();
        let defs = self.defs.clone();
        let (aim_dir, shots, event) = {
            let aim = self.effective_aim(controls.aim, 3);
            let Some(p) = self.state.player.as_mut() else {
                return;
            };
            let Some(hw) = p.wands.get_mut(p.active_wand) else {
                return;
            };
            if !hw.wand.is_ready() {
                return;
            }
            let result = match hw.wand.cast(&book, &mut hw.rng) {
                Ok(r) => r,
                Err(Error::NotReady { .. }) => return,
                Err(e) => {
                    let message = e.to_string();
                    self.world
                        .log_event("error", vec![("message", Value::Str(message))]);
                    return;
                }
            };
            let mats = &self.world.content().mats;
            let shots: Result<Vec<Shot>, Error> = result
                .projectiles
                .iter()
                .map(|s| shot_from_spawn(&book, mats, &defs, s))
                .collect();
            let played: Vec<&str> = result.played.iter().map(|s| book.key(*s)).collect();
            let event = (
                hw.id,
                played.join("+"),
                result.projectiles.len(),
                result.mana_spent,
                result.ready_in,
            );
            (aim_vector(aim), shots, event)
        };
        let shots = match shots {
            Ok(s) => s,
            Err(e) => {
                let message = e.to_string();
                self.world
                    .log_event("error", vec![("message", Value::Str(message))]);
                return;
            }
        };
        let origin = self.muzzle(aim_dir);
        if !shots.is_empty() {
            self.reveal_player();
        }
        for shot in &shots {
            self.launch_shot(shot, Owner::Player, origin, aim_dir);
        }
        let (wand, spells, n, mana, ready_in) = event;
        if !spells.is_empty() {
            self.world.log_event(
                "cast",
                vec![
                    ("wand", Value::Int(i64::from(wand))),
                    ("spells", Value::Str(spells)),
                    ("projectiles", Value::Int(n as i64)),
                    ("mana", Value::Float(f64::from(mana))),
                    ("ready_in", Value::Int(i64::from(ready_in))),
                ],
            );
        }
    }

    /// Fire a shot from an enemy: a spread-rotated copy of the aim.
    pub(crate) fn enemy_shoot(
        &mut self,
        enemy: u32,
        origin: (f32, f32),
        dir: (f32, f32),
        shot: &Shot,
        spread: f32,
        salt: u64,
    ) {
        let u = self
            .ai
            .unit(self.world.frame(), u64::from(enemy), 100 + salt);
        let aimed = rotate(dir, (2.0 * u - 1.0) * spread);
        self.launch_shot(shot, Owner::Enemy(enemy), origin, aimed);
    }
}
