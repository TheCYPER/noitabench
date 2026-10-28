//! Enemies (tick-design step 3): who is awake, and what the actions they ask for do to the world.

use crate::entity::{DamageSource, Target};
use crate::physics::unit;
use crate::projectile::shot_from_enemy;

use super::enemy_ai::{think, Act, PlayerInfo};
use super::Game;

impl Game {
    fn player_info(&self) -> Option<PlayerInfo> {
        let p = self.state.player.as_ref()?;
        let (cx, cy) = p.body.cell();
        let boxes: Vec<_> = self
            .defs
            .player
            .hitboxes
            .iter()
            .map(|h| cogbench_sim::Aabb::new(cx + h.dx, cy + h.dy, h.w, h.h))
            .collect();
        let b = boxes.first().copied()?;
        Some(PlayerInfo {
            center: (b.x as f32 + b.w as f32 / 2.0, b.y as f32 + b.h as f32 / 2.0),
            bbox: b,
            alive: !p.vitals.dead,
            visible: self.player_visible_to_enemies(),
        })
    }

    /// Every enemy within the active range of the player thinks and moves; the rest sleep.
    pub(crate) fn update_enemies(&mut self) {
        let defs = self.defs.clone();
        let frame = self.world.frame();
        let range = defs.sim.active_range;
        let info = self.player_info();
        let anchor = self.state.player.as_ref().map(|p| p.body.cell());
        for i in 0..self.state.enemies.len() {
            let acts = {
                let e = &mut self.state.enemies[i];
                let (ex, ey) = e.body.cell();
                let asleep = anchor
                    .is_some_and(|(px, py)| (ex - px).abs() > range || (ey - py).abs() > range);
                let Some(def) = defs.enemies.get(&e.kind) else {
                    continue;
                };
                if e.vitals.dead || asleep {
                    continue;
                }
                think(&self.world, e, def, info.as_ref(), &self.ai, frame)
            };
            for act in acts {
                self.enemy_act(i, act);
            }
        }
    }

    fn enemy_act(&mut self, index: usize, act: Act) {
        match act {
            Act::Strike { damage } => {
                self.hurt(Target::Player, damage, DamageSource::Melee);
            }
            Act::Shoot { target } => self.enemy_fire(index, target),
        }
    }

    /// The ranged attack: a volley at the player, aimed a little high to make up for the drop.
    fn enemy_fire(&mut self, index: usize, target: (f32, f32)) {
        let defs = self.defs.clone();
        let e = &self.state.enemies[index];
        let Some(r) = defs.enemies.get(&e.kind).and_then(|d| d.ranged.as_ref()) else {
            return;
        };
        let Some(proj) = defs.projectiles.get(&r.projectile) else {
            return;
        };
        let (id, frame) = (e.id, self.world.frame());
        let (ex, ey) = e.body.center();
        let origin = (ex + f32::from(e.facing) * 4.0, ey - 2.0);
        let (dx, dy) = (target.0 - origin.0, target.1 - origin.1);
        let dist = (dx * dx + dy * dy).sqrt();
        let speed = (proj.speed_min + proj.speed_max) / 2.0;
        let t = dist / speed.max(1.0);
        let drop = 0.5 * proj.gravity * t * t;
        let aim_at = (target.0, target.1 - drop);
        let dir = unit(
            (aim_at.0 - origin.0, aim_at.1 - origin.1),
            (f32::from(e.facing), 0.0),
        );
        let span = r.count_max - r.count_min + 1;
        let n = r.count_min + self.ai.below(span, frame, u64::from(id), 50);
        let shot = shot_from_enemy(&r.projectile, proj);
        for k in 0..n {
            self.enemy_shoot(id, origin, dir, &shot, r.spread_degrees, u64::from(k));
        }
        self.world.log_event(
            "enemy_attack",
            vec![
                (
                    "enemy",
                    cogbench_sim::Value::Str(self.state.enemies[index].kind.clone()),
                ),
                ("id", cogbench_sim::Value::Int(i64::from(id))),
                ("projectiles", cogbench_sim::Value::Int(i64::from(n))),
            ],
        );
    }
}
