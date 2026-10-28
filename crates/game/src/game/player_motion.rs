//! How the player moves (`entities-damage.md` Key numbers): walking, jumping, levitation with a
//! 3 second meter, swimming and drowning. Pure functions of the world, the player and the keys.

use cogbench_sim::{Kind, World};

use crate::control::{Controls, Pressed};
use crate::defs::{PlayerDef, StatusDefs};
use crate::entity::Player;
use crate::physics::{aim_vector, FPS};
use crate::status::Status;

/// Fraction of the way a swimmer's vertical speed moves toward the swim-up speed per frame.
const SWIM_UP_BLEND: f32 = 0.15;

/// Walk speed after haste, burning and swimming.
fn speed_factor(p: &Player, pd: &PlayerDef, sd: &StatusDefs, submerged: bool) -> f32 {
    let mut f = 1.0;
    if p.vitals.statuses.has(Status::Haste) {
        f *= sd.haste.speed_mul;
    }
    if p.vitals.statuses.has(Status::OnFire) {
        f *= sd.on_fire.speed_mul;
    }
    if submerged {
        f *= pd.swim.speed_mul;
    }
    f
}

/// One frame of player movement.
pub(crate) fn move_player(
    world: &World,
    p: &mut Player,
    pd: &PlayerDef,
    sd: &StatusDefs,
    c: &Controls,
    pressed: Pressed,
) {
    let area = (p.body.w * p.body.h) as u32;
    let liquid = world.overlap(p.body.aabb()).kind_count(Kind::Liquid);
    let submerged = liquid * 100 >= area * pd.swim.min_submerged_percent as u32;
    let grounded = p.body.grounded(world);
    let fly = &pd.fly;
    // Secret potion: while it lasts the meter neither drains nor costs a press.
    let free_flight = p.vitals.statuses.has(Status::Levitation);

    if pressed.fly && !grounded && !submerged && !free_flight {
        p.fly_meter = (p.fly_meter - fly.press_cost_frames).max(0.0);
    }
    let flying = c.fly && !submerged && (p.fly_meter > 0.0 || free_flight);
    if flying {
        if !free_flight {
            p.fly_meter = (p.fly_meter - 1.0).max(0.0);
        }
        p.air_wait = 0;
    } else if grounded {
        p.fly_meter = (p.fly_meter + fly.recharge_ground).min(fly.meter_frames);
        p.air_wait = 0;
    } else {
        p.air_wait += 1;
        if p.air_wait >= fly.air_wait_frames {
            p.fly_meter = (p.fly_meter + fly.recharge_air).min(fly.meter_frames);
        }
    }

    let factor = speed_factor(p, pd, sd, submerged);
    let top_speed = if flying { fly.speed_x } else { pd.walk_speed } * factor;
    let target_vx = f32::from(c.move_x.signum()) * top_speed;
    let accel = if grounded {
        pd.accel_ground
    } else {
        pd.accel_air
    };
    p.body.vx += (target_vx - p.body.vx) * accel;

    let gravity = pd.gravity / FPS;
    if flying {
        p.body.vy += (-fly.speed_up - p.body.vy) * fly.change;
    } else if submerged {
        p.body.vy += gravity * pd.swim.gravity_mul;
        if c.fly || c.jump {
            p.body.vy += (-pd.swim.up_speed - p.body.vy) * SWIM_UP_BLEND;
        }
        p.body.vx *= pd.swim.drag;
        p.body.vy *= pd.swim.drag;
    } else if grounded {
        p.body.vy = if pressed.jump { -pd.jump_speed } else { 0.0 };
    } else {
        p.body.vy = (p.body.vy + gravity).min(pd.fall_speed_max);
    }
    p.body.integrate(world, pd.step_up, 0.0);

    if c.move_x != 0 {
        p.facing = c.move_x.signum();
    } else {
        let (ax, _) = aim_vector(c.aim);
        if ax.abs() > 0.2 {
            p.facing = if ax > 0.0 { 1 } else { -1 };
        }
    }
}

/// Is the head under a liquid you cannot breathe? Healing pools are fine.
pub(crate) fn head_underwater(world: &World, p: &Player, pd: &PlayerDef) -> bool {
    let hb = &pd.hitboxes[0];
    let (cx, cy) = p.body.cell();
    let (x, y) = (cx + p.body.w / 2, cy + hb.dy);
    let cell = world.grid().get(x, y);
    let mats = &world.content().mats;
    mats.rt(cell.mat).kind == Kind::Liquid
        && mats.get(cell.mat).is_some_and(|m| m.family != "potion")
}
