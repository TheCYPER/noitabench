//! What an enemy does in one frame: look for the player, walk, jump, wind up and strike.
//!
//! The three enemies share one small state machine (windup, lunge, flee, combat, patrol) and
//! differ in the numbers of `entities.json`: Hämis leaps and bites, Haulikkohiisi keeps its
//! distance and fires buckshot, Stendari lobs fireballs. Every attack has a windup of 10 to 20
//! frames, so an agent deciding once per 10-frame tick can see it coming (the "re-tuned to the
//! tick" of v1-scope section 4). All choices are stateless hashes of `(frame, enemy id)`.

use cogbench_sim::{Aabb, KindMask, World};

use crate::defs::{AiKind, EnemyDef};
use crate::entity::{Enemy, Windup};
use crate::physics::{overlaps, FPS};
use crate::rng::HashRng;

/// Frames an enemy keeps hunting after it lost sight of the player.
const ALERT_FRAMES: u32 = 120;
/// How far below its feet an enemy looks for ground before it walks on, in cells.
const LEDGE_DEPTH: i32 = 14;
/// Fastest an enemy falls, in px/s.
const MAX_FALL_SPEED: f32 = 400.0;
/// Horizontal speed kept per frame during a windup, and when a lunge ends.
const WINDUP_DRAG: f32 = 0.5;
const LUNGE_END_DRAG: f32 = 0.3;
/// Closing speed toward the wanted horizontal velocity per frame.
const ACCEL: f32 = 0.2;
/// Patrol walks at this fraction of the run speed.
const PATROL_SPEED: f32 = 0.5;
/// Vertical reach of melee strikes and lunges, in cells.
const STRIKE_HEIGHT: f32 = 14.0;
/// Lunges only start from at least this far away.
const LUNGE_MIN_DISTANCE: f32 = 18.0;
/// A lunging enemy hops up a little.
const LUNGE_HOP: f32 = 40.0;
/// Extra reach beyond the melee range at which a strike still lands after its windup.
const STRIKE_SLACK: f32 = 6.0;

/// What the player looks like to an enemy.
pub(crate) struct PlayerInfo {
    pub center: (f32, f32),
    pub bbox: Aabb,
    pub alive: bool,
    /// False while the player is invisible (potion) and not revealed: enemies do not notice or
    /// target the player.
    pub visible: bool,
}

/// What an enemy wants done to the rest of the world.
pub(crate) enum Act {
    /// Fire its ranged attack at this point.
    Shoot { target: (f32, f32) },
    /// A melee hit or lunge reached the player.
    Strike { damage: f32 },
}

struct Ctx<'a> {
    world: &'a World,
    def: &'a EnemyDef,
    rng: &'a HashRng,
    frame: u64,
    id: u64,
}

fn sign(v: f32) -> i8 {
    if v >= 0.0 {
        1
    } else {
        -1
    }
}

/// What an enemy knows about the player this frame.
struct Sight {
    /// Offset from the enemy's centre to the player's centre.
    dx: f32,
    dy: f32,
    /// The player is alive, inside the detection box and not behind rock.
    sees: bool,
}

/// Run one frame of thought and movement for an awake enemy.
pub(crate) fn think(
    world: &World,
    e: &mut Enemy,
    def: &EnemyDef,
    player: Option<&PlayerInfo>,
    rng: &HashRng,
    frame: u64,
) -> Vec<Act> {
    let cx = Ctx {
        world,
        def,
        rng,
        frame,
        id: u64::from(e.id),
    };
    react_to_pain(&cx, e);
    let target = player.filter(|p| p.alive && p.visible);
    let sight = look(&cx, e, target);
    let (want_dir, speed, acts) = decide(&cx, e, target, &sight);
    if want_dir != 0 {
        e.facing = want_dir;
    }
    if e.lunging == 0 {
        let target_vx = f32::from(want_dir) * def.run_speed * speed;
        e.body.vx += (target_vx - e.body.vx) * ACCEL;
    }
    let grounded = e.body.grounded(world);
    let jump = want_dir != 0 && grounded && wall_ahead(world, e, want_dir);
    if grounded {
        e.body.vy = if jump { -def.jump_speed } else { 0.0 };
    } else {
        e.body.vy = (e.body.vy + def.gravity / FPS).min(MAX_FALL_SPEED);
    }
    e.body.integrate(world, def.step_up, 0.0);
    acts
}

/// Cooldowns tick down; being hurt makes an enemy alert and sometimes sends it running.
fn react_to_pain(cx: &Ctx<'_>, e: &mut Enemy) {
    e.melee_cooldown = e.melee_cooldown.saturating_sub(1);
    e.ranged_cooldown = e.ranged_cooldown.saturating_sub(1);
    e.lunge_cooldown = e.lunge_cooldown.saturating_sub(1);
    let hurt = e.vitals.hp < e.last_hp - 1e-6;
    if hurt && cx.rng.percent(cx.def.flee.chance, cx.frame, cx.id, 20) {
        e.flee = cx.def.flee.frames;
    }
    if hurt {
        e.alert = e.alert.max(ALERT_FRAMES);
    }
    e.last_hp = e.vitals.hp;
}

/// Look for the player and keep the alert timer: full while in sight, running down otherwise.
fn look(cx: &Ctx<'_>, e: &mut Enemy, target: Option<&PlayerInfo>) -> Sight {
    let (ex, ey) = e.body.center();
    let sight = match target {
        Some(p) => {
            let (dx, dy) = (p.center.0 - ex, p.center.1 - ey);
            let detect = cx.def.detect;
            let in_box = dx.abs() <= detect.w as f32 / 2.0 && dy.abs() <= detect.h as f32 / 2.0;
            let clear = !cx.world.line_blocked(
                (ex.floor() as i32, ey.floor() as i32),
                (p.center.0.floor() as i32, p.center.1.floor() as i32),
                KindMask::SURFACES,
            );
            Sight {
                dx,
                dy,
                sees: in_box && clear,
            }
        }
        None => Sight {
            dx: 0.0,
            dy: 0.0,
            sees: false,
        },
    };
    if sight.sees {
        e.alert = ALERT_FRAMES;
    } else {
        e.alert = e.alert.saturating_sub(1);
    }
    sight
}

/// What to do this frame: finish a windup or lunge, flee, hunt or wander. Returns the walking
/// direction, a speed factor and the effects on the rest of the world.
fn decide(
    cx: &Ctx<'_>,
    e: &mut Enemy,
    target: Option<&PlayerInfo>,
    sight: &Sight,
) -> (i8, f32, Vec<Act>) {
    let (dx, dy) = (sight.dx, sight.dy);
    let mut acts = Vec::new();
    if let Some((kind, left)) = e.windup {
        let left = left.saturating_sub(1);
        e.windup = (left > 0).then_some((kind, left));
        e.body.vx *= WINDUP_DRAG;
        if left == 0 {
            finish_windup(cx, e, kind, target, (dx, dy), &mut acts);
        }
        return (0, 1.0, acts);
    }
    if e.lunging > 0 {
        e.lunging -= 1;
        if let (Some(p), Some(l)) = (target, cx.def.lunge) {
            let b = e.body.aabb();
            let reach = Aabb::new(b.x - 2, b.y - 2, b.w + 4, b.h + 4);
            if overlaps(reach, p.bbox) {
                acts.push(Act::Strike { damage: l.damage });
                e.lunging = 0;
            }
        }
        if e.lunging == 0 {
            e.body.vx *= LUNGE_END_DRAG;
        }
        return (0, 1.0, acts);
    }
    if e.flee > 0 {
        e.flee -= 1;
        return (-sign(dx), 1.0, acts);
    }
    if let (true, Some(_)) = (e.alert > 0, target) {
        let (dir, spd, start) = combat(cx, e, (dx, dy), sight.sees);
        return match start {
            Some(w) => {
                e.windup = Some(w);
                e.facing = sign(dx);
                (0, spd, acts)
            }
            None => (dir, spd, acts),
        };
    }
    (patrol(cx, e), PATROL_SPEED, acts)
}

/// Decide what to do while hunting: the direction to walk, a speed factor, and maybe an attack
/// to wind up.
fn combat(
    cx: &Ctx<'_>,
    e: &mut Enemy,
    (dx, dy): (f32, f32),
    sees: bool,
) -> (i8, f32, Option<(Windup, u32)>) {
    let def = cx.def;
    let (adx, ady) = (dx.abs(), dy.abs());
    let toward = sign(dx);
    let melee_range = def.melee.range as f32 + STRIKE_SLACK;
    if e.melee_cooldown == 0 && adx <= melee_range && ady <= STRIKE_HEIGHT {
        return (0, 1.0, Some((Windup::Melee, def.melee.windup)));
    }
    if def.ai == AiKind::Leaper {
        if let Some(l) = def.lunge {
            if e.lunge_cooldown == 0
                && sees
                && (LUNGE_MIN_DISTANCE..=l.distance as f32).contains(&adx)
                && ady <= STRIKE_HEIGHT
            {
                return (0, 1.0, Some((Windup::Lunge, l.windup)));
            }
        }
        return (toward, 1.0, None);
    }
    let Some(r) = &def.ranged else {
        return (toward, 1.0, None);
    };
    if sees && adx <= r.range as f32 && e.ranged_cooldown == 0 {
        return (0, 1.0, Some((Windup::Shoot, r.windup)));
    }
    let keep = r.keep_distance as f32;
    if sees && adx < keep - 10.0 {
        (-toward, 1.0, None)
    } else if !sees || adx > r.range as f32 * 0.85 {
        (toward, 1.0, None)
    } else {
        (0, 1.0, None)
    }
}

/// The windup is over: strike, start the lunge, or ask for a shot.
fn finish_windup(
    cx: &Ctx<'_>,
    e: &mut Enemy,
    kind: Windup,
    target: Option<&PlayerInfo>,
    (dx, dy): (f32, f32),
    acts: &mut Vec<Act>,
) {
    let def = cx.def;
    match kind {
        Windup::Melee => {
            e.melee_cooldown = def.melee.interval;
            let in_reach =
                dx.abs() <= def.melee.range as f32 + STRIKE_SLACK && dy.abs() <= STRIKE_HEIGHT;
            if target.is_some() && in_reach {
                let m = &def.melee;
                let u = cx.rng.unit(cx.frame, cx.id, 30);
                acts.push(Act::Strike {
                    damage: m.damage_min + (m.damage_max - m.damage_min) * u,
                });
            }
        }
        Windup::Lunge => {
            if let Some(l) = def.lunge {
                e.lunge_cooldown = l.interval;
                e.lunging = (l.distance as f32 / (l.speed / FPS)).ceil() as u32;
                e.facing = sign(dx);
                e.body.vx = f32::from(e.facing) * l.speed;
                e.body.vy = -LUNGE_HOP;
            }
        }
        Windup::Shoot => {
            if let (Some(r), Some(p)) = (&def.ranged, target) {
                e.ranged_cooldown = r.interval;
                acts.push(Act::Shoot { target: p.center });
            }
        }
    }
}

/// Wander: stand or walk a little, turn at walls and ledges.
fn patrol(cx: &Ctx<'_>, e: &mut Enemy) -> i8 {
    if e.patrol_left == 0 {
        let roll = cx.rng.below(100, cx.frame, cx.id, 40);
        e.patrol_dir = match roll {
            0..=29 => 0,
            30..=64 => -1,
            _ => 1,
        };
        e.patrol_left = 40 + cx.rng.below(80, cx.frame, cx.id, 41);
    }
    e.patrol_left -= 1;
    if e.patrol_dir != 0 && (no_floor_ahead(cx.world, e, e.patrol_dir) || wall_too_high(cx, e)) {
        e.patrol_dir = -e.patrol_dir;
    }
    e.patrol_dir
}

/// The column just ahead of the feet, over the body's lower half, is blocked.
fn wall_ahead(world: &World, e: &Enemy, dir: i8) -> bool {
    let (cx, cy) = e.body.cell();
    let x = if dir > 0 { cx + e.body.w } else { cx - 1 };
    world.box_blocked(
        Aabb::new(x, cy + e.body.h / 2, 1, e.body.h - e.body.h / 2),
        KindMask::BLOCKING,
    )
}

/// A wall ahead that the enemy cannot hop over (blocked at head height too).
fn wall_too_high(cx: &Ctx<'_>, e: &Enemy) -> bool {
    let (x, y) = e.body.cell();
    let dir = e.patrol_dir;
    let front = if dir > 0 { x + e.body.w } else { x - 1 };
    let jump_cells = (cx.def.jump_speed * cx.def.jump_speed / (2.0 * cx.def.gravity)) as i32;
    cx.world
        .box_blocked(Aabb::new(front, y - jump_cells, 1, 2), KindMask::BLOCKING)
        && wall_ahead(cx.world, e, dir)
}

fn no_floor_ahead(world: &World, e: &Enemy, dir: i8) -> bool {
    let (cx, cy) = e.body.cell();
    let x = if dir > 0 { cx + e.body.w } else { cx - 1 };
    !world.box_blocked(
        Aabb::new(x, cy + e.body.h, 1, LEDGE_DEPTH),
        KindMask::BLOCKING,
    )
}
