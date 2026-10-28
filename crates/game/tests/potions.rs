//! The eight secret potions: what drinking each one does, how long it lasts, and that the seal
//! key stays out of random loot. Recipes (how the potions are made) are tested in
//! `crates/sim/tests/recipes.rs` and `crates/rules/tests/`; the world loader's use of them in
//! `world_recipes.rs`.

mod scene;

use scene::*;

use cogbench_game::entity::Owner;
use cogbench_game::{BlastSpec, Controls, EntityDefs, Game};

const W: i32 = 600;
const H: i32 = 200;
const FLOOR: i32 = 30;

fn arena() -> Game {
    with_player(W, H, FLOOR, 100)
}

/// Drink `cells` cells of `potion` from a bottle of its own.
fn drink(g: &mut Game, potion: &str, cells: u32) {
    g.give_bottle(Some(potion), Some(cells)).unwrap();
    let last = (g.player().unwrap().bottles.len() - 1) as u8;
    let frames = cells.div_ceil(10) + 1;
    run(
        g,
        frames,
        &hold(|c| {
            c.select_bottle = Some(last);
            c.drink = true;
        }),
    );
}

fn status(g: &Game, name: &str) -> u32 {
    g.player()
        .unwrap()
        .statuses
        .iter()
        .find(|(k, _)| k == name)
        .map_or(0, |(_, f)| *f)
}

fn hp(g: &Game) -> f64 {
    g.player().unwrap().hp
}

/// A blast of `damage` (internal units) on the player.
fn blast_player(g: &mut Game, damage: f32) {
    let p = g.player().unwrap();
    g.blast(BlastSpec {
        x: p.x + 2,
        y: p.y + 3,
        radius: 12,
        damage,
        ray_energy: 1000,
        max_durability: 0,
        fire_percent: 0,
        owner: Owner::World,
        spare_owner: false,
    });
}

const SECRET: [(&str, &str); 8] = [
    ("potion_lively", "regeneration"),
    ("potion_invulnerable", "invulnerable"),
    ("potion_mana_regen", "mana_regen"),
    ("potion_crit", "crit_boost"),
    ("potion_berserk", "berserk"),
    ("potion_levitation", "levitation"),
    ("potion_invisible", "invisible"),
    ("potion_fireproof", "fireproof"),
];

// ----- drinking -----------------------------------------------------------------------------

#[test]
fn a_full_bottle_gives_its_status_for_the_designed_time() {
    // frames per cell x 400 cells: 6.7 s, 10, 20, 15, 15, 10, 10, 15 seconds
    let seconds = [6.67, 10.0, 20.0, 15.0, 15.0, 10.0, 10.0, 15.0];
    for ((potion, name), secs) in SECRET.iter().zip(seconds) {
        let mut g = arena();
        drink(&mut g, potion, 400);
        let total = (secs * 60.0) as u32;
        let left = status(&g, name);
        // 41 frames of drinking have gone by, one frame of status each
        assert!(
            left <= total && left + 60 >= total,
            "{potion}: {left} frames left, expected about {total}"
        );
        let ev = events(&mut g);
        assert!(
            ev.iter()
                .any(|(k, f)| k == "status" && text(f, "status") == *name),
            "{potion}: no status event"
        );
    }
}

#[test]
fn a_full_bottle_gives_exactly_the_designed_number_of_frames() {
    // drinking is 10 cells a frame; the share of each frame is a difference of floors, so the
    // fractional rates (2.25 frames a cell) add up to the round numbers of entities.json
    let frames = [400, 600, 1200, 900, 900, 600, 600, 900];
    for ((potion, name), want) in SECRET.iter().zip(frames) {
        let mut g = arena();
        g.give_bottle(Some(potion), Some(400)).unwrap();
        let mut elapsed = 0;
        while g.player().unwrap().bottles[0].1 > 0 {
            run(
                &mut g,
                1,
                &hold(|c| {
                    c.select_bottle = Some(0);
                    c.drink = true;
                }),
            );
            elapsed += 1;
        }
        while status(&g, name) > 0 {
            run(&mut g, 1, &Controls::default());
            elapsed += 1;
        }
        assert_eq!(elapsed, want, "{potion}");
    }
}

#[test]
fn a_sip_lasts_in_proportion() {
    let mut a = arena();
    drink(&mut a, "potion_invulnerable", 100);
    let mut b = arena();
    drink(&mut b, "potion_invulnerable", 200);
    let (sa, sb) = (status(&a, "invulnerable"), status(&b, "invulnerable"));
    assert!(sb > sa + 50, "{sa} vs {sb}");
    assert!(
        (100..=150).contains(&sa),
        "100 cells = 150 frames, got {sa}"
    );
}

#[test]
fn a_secret_potion_is_never_a_stain() {
    // standing in it gives nothing: they work by drinking only
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    for (potion, name) in SECRET {
        g.world_mut().fill_rect(80, y - 6, 40, 7, potion).unwrap();
        run(&mut g, 30, &Controls::default());
        assert_eq!(status(&g, name), 0, "{potion}");
        g.world_mut().fill_rect(80, y - 6, 40, 7, "air").unwrap();
    }
}

// ----- invulnerable -------------------------------------------------------------------------

#[test]
fn invulnerable_stops_every_kind_of_damage() {
    let mut g = arena();
    drink(&mut g, "potion_invulnerable", 100);
    assert!(status(&g, "invulnerable") > 60);
    let before = hp(&g);
    blast_player(&mut g, 1.0);
    run(&mut g, 1, &Controls::default());
    // poison, drowning and contact damage go through the same gate
    g.world_mut()
        .fill_rect(0, ground_y(H, FLOOR) - 20, W, 21, "acid")
        .unwrap();
    run(&mut g, 20, &Controls::default());
    assert_eq!(hp(&g), before, "nothing hurt");
    assert!(!g.player().unwrap().dead);
}

/// Something that hurts a plain player: sets the scene up before the frames run.
type Trouble = Box<dyn Fn(&mut Game)>;

/// Hit points after `frames` frames of `trouble`, with and without the potion.
fn hp_after(potion: bool, frames: u32, trouble: impl Fn(&mut Game)) -> f64 {
    let mut g = arena();
    if potion {
        drink(&mut g, "potion_invulnerable", 400);
    }
    trouble(&mut g);
    run(&mut g, frames, &Controls::default());
    hp(&g)
}

#[test]
fn invulnerable_beats_melee_ranged_fire_poison_acid_and_drowning() {
    let y = ground_y(H, FLOOR);
    let troubles: Vec<(&str, u32, Trouble)> = vec![
        (
            "melee",
            200,
            Box::new(move |g| {
                g.spawn_enemy("longleg", 106, y).unwrap();
            }),
        ),
        (
            "ranged",
            250,
            Box::new(move |g| {
                g.spawn_enemy("shotgunner", 200, y).unwrap();
            }),
        ),
        (
            "fire",
            200,
            Box::new(move |g| {
                g.world_mut().fill_rect(96, y - 16, 12, 18, "fire").unwrap();
                g.world_mut().ignite(100, y - 4);
            }),
        ),
        (
            "poison",
            300,
            Box::new(|g| {
                g.give_bottle(Some("toxic_sludge"), Some(100)).unwrap();
                let last = (g.player().unwrap().bottles.len() - 1) as u8;
                run(
                    g,
                    12,
                    &hold(|c| {
                        c.select_bottle = Some(last);
                        c.drink = true;
                    }),
                );
            }),
        ),
        (
            "acid",
            100,
            Box::new(move |g| {
                g.world_mut().fill_rect(90, y - 20, 24, 21, "acid").unwrap();
            }),
        ),
        (
            "drowning",
            480,
            Box::new(move |g| {
                g.world_mut().fill_rect(0, y - 40, W, 41, "water").unwrap();
            }),
        ),
    ];
    for (name, frames, trouble) in &troubles {
        let hurt = hp_after(false, *frames, trouble);
        assert!(
            hurt < 100.0,
            "{name}: the trouble itself must hurt ({hurt})"
        );
        let safe = hp_after(true, *frames, trouble);
        assert_eq!(safe, 100.0, "{name}: nothing may get through");
    }
}

#[test]
fn invulnerable_ends_and_damage_returns() {
    let mut g = arena();
    drink(&mut g, "potion_invulnerable", 20);
    run(&mut g, 60, &Controls::default());
    assert_eq!(status(&g, "invulnerable"), 0);
    let before = hp(&g);
    blast_player(&mut g, 1.0);
    run(&mut g, 1, &Controls::default());
    assert!(hp(&g) < before - 5.0, "{} -> {}", before, hp(&g));
}

// ----- mana ---------------------------------------------------------------------------------

/// Mana of wand `index` after casting once and waiting `frames` frames without holding fire.
fn mana_after(g: &mut Game, index: u8, frames: u32) -> f32 {
    run(g, 1, &fire(index, 90.0));
    let low = g.player().unwrap().wands[usize::from(index)].mana;
    run(g, frames, &Controls::default());
    g.player().unwrap().wands[usize::from(index)].mana - low
}

fn slow_charge_wand(g: &mut Game) -> u8 {
    // two bombs per click cost 50 mana, more than the potion can win back in a second
    let stats = cogbench_game::wand::WandStats {
        mana_max: 1000.0,
        mana_charge_speed: 12.0,
        spells_per_cast: 2,
        cast_delay: 0,
        recharge: 0,
        ..stats()
    };
    let bombs = [Some("BOMB".to_string()), Some("BOMB".to_string())];
    g.give_wand(stats, &bombs, &[]).unwrap();
    (g.player().unwrap().wands.len() - 1) as u8
}

#[test]
fn mana_regen_makes_held_wands_regain_mana_three_times_as_fast() {
    let mut plain = arena();
    let w = slow_charge_wand(&mut plain);
    let gain_plain = mana_after(&mut plain, w, 60);
    let mut potion = arena();
    let w = slow_charge_wand(&mut potion);
    drink(&mut potion, "potion_mana_regen", 100);
    assert!(status(&potion, "mana_regen") > 100);
    let gain = mana_after(&mut potion, w, 60);
    assert!((gain_plain - 12.0).abs() < 0.5, "plain: {gain_plain}");
    assert!((gain - 36.0).abs() < 1.0, "with the potion: {gain}");
}

#[test]
fn mana_regen_does_not_speed_up_the_cooldown() {
    let mut g = arena();
    let stats = cogbench_game::wand::WandStats {
        cast_delay: 60,
        recharge: 60,
        ..stats()
    };
    g.give_wand(stats, &[Some("LIGHT_BULLET".to_string())], &[])
        .unwrap();
    let w = (g.player().unwrap().wands.len() - 1) as u8;
    drink(&mut g, "potion_mana_regen", 100);
    run(&mut g, 1, &fire(w, 90.0));
    run(&mut g, 30, &Controls::default());
    let cooldown = g.player().unwrap().wands[usize::from(w)].cooldown;
    assert!(cooldown >= 25, "30 frames later {cooldown} of 60 are left");
}

// ----- crit and berserk ---------------------------------------------------------------------

/// Shoot a fresh Hämis (one hit kills) `trials` times and return the `(damage, crit)` of each hit.
fn shoot_dummies(g: &mut Game, trials: usize) -> Vec<(f64, bool)> {
    let w = give(g, &["LIGHT_BULLET"]);
    let mut out = Vec::new();
    for _ in 0..trials {
        g.spawn_enemy("longleg", 150, ground_y(H, FLOOR)).unwrap();
        run(g, 1, &fire(w, 0.0));
        run(g, 12, &Controls::default());
        for (kind, f) in events(g) {
            if kind == "hit" && text(&f, "target") == "longleg" {
                out.push((
                    match f.iter().find(|(k, _)| k == "damage") {
                        Some((_, cogbench_sim::Value::Float(d))) => *d,
                        other => panic!("no damage: {other:?}"),
                    },
                    int(&f, "crit") == 1,
                ));
            }
        }
        // clear the field: whatever is left of the enemy and its bite
        let ids: Vec<u32> = g
            .entities()
            .into_iter()
            .filter(|e| e.kind == "longleg")
            .map(|e| e.id)
            .collect();
        assert!(ids.is_empty(), "one bolt kills Hämis");
    }
    out
}

#[test]
fn crit_boost_adds_fifty_points_of_critical_chance() {
    let mut plain = arena();
    let base = shoot_dummies(&mut plain, 100);
    let mut boosted = arena();
    // two bottles: 1800 frames of potion cover the 100 x 13 frames of shooting
    drink(&mut boosted, "potion_crit", 400);
    drink(&mut boosted, "potion_crit", 400);
    let more = shoot_dummies(&mut boosted, 100);
    let crits = |v: &[(f64, bool)]| v.iter().filter(|(_, c)| *c).count();
    assert_eq!(base.len(), 100);
    assert_eq!(more.len(), 100);
    // spark bolt: 5 % crit; with the potion 55 %
    assert!(crits(&base) < 15, "without: {} crits", crits(&base));
    assert!(crits(&more) > 40, "with: {} crits", crits(&more));
    // a crit deals five times the damage
    let plain_hit = base.iter().find(|(_, c)| !*c).unwrap().0;
    let crit_hit = more.iter().find(|(_, c)| *c).unwrap().0;
    assert!((crit_hit / plain_hit - 5.0).abs() < 0.01);
}

#[test]
fn crit_boost_does_not_help_enemies() {
    // the bonus is the player's: an enemy projectile keeps its own chance
    let mut g = arena();
    drink(&mut g, "potion_crit", 400);
    let defs = EntityDefs::embedded().unwrap();
    assert_eq!(defs.statuses.crit_boost.bonus_percent, 50.0);
    g.spawn_enemy("shotgunner", 260, ground_y(H, FLOOR))
        .unwrap();
    run(&mut g, 200, &Controls::default());
    let ev = events(&mut g);
    assert!(count(&ev, "hit") > 0, "the shotgunner hit the player");
    assert!(
        ev.iter()
            .filter(|(k, f)| k == "hit" && text(f, "target") == "player")
            .all(|(_, f)| int(f, "crit") == 0),
        "nobody crits the player"
    );
}

#[test]
fn berserk_doubles_the_damage_of_the_players_hits() {
    let mut plain = arena();
    let base = shoot_dummies(&mut plain, 12);
    let mut mad = arena();
    drink(&mut mad, "potion_berserk", 400);
    let more = shoot_dummies(&mut mad, 12);
    let first = |v: &[(f64, bool)]| v.iter().find(|(_, c)| !*c).unwrap().0;
    assert!((first(&more) / first(&base) - 2.0).abs() < 0.01);
}

fn explosion_damage(g: &mut Game) -> f64 {
    // the EXPLOSION spell on a Stendari-free field: hurt a shotgunner next to the muzzle
    let w = give(g, &["EXPLOSION"]);
    let y = ground_y(H, FLOOR);
    g.spawn_enemy("shotgunner", 118, y).unwrap();
    run(g, 1, &fire(w, 0.0));
    run(g, 3, &Controls::default());
    events(g)
        .iter()
        .filter(|(k, f)| k == "damage" && text(f, "target") == "shotgunner")
        .map(|(_, f)| match f.iter().find(|(k, _)| k == "amount") {
            Some((_, cogbench_sim::Value::Float(a))) => *a,
            other => panic!("no amount: {other:?}"),
        })
        .fold(0.0, f64::max)
}

#[test]
fn berserk_doubles_the_players_explosions() {
    let mut plain = arena();
    let base = explosion_damage(&mut plain);
    let mut mad = arena();
    drink(&mut mad, "potion_berserk", 400);
    let more = explosion_damage(&mut mad);
    assert!(base > 20.0, "the spell hurts: {base}");
    assert!((more / base - 2.0).abs() < 0.01, "{base} -> {more}");
}

#[test]
fn berserk_leaves_enemy_and_world_blasts_alone() {
    let mut g = arena();
    drink(&mut g, "potion_berserk", 400);
    let mut plain = arena();
    let hit = |g: &mut Game| {
        let before = hp(g);
        run(g, 61, &Controls::default()); // let the opening invincibility pass either way
        blast_player(g, 1.0);
        run(g, 1, &Controls::default());
        before - hp(g)
    };
    // a world blast (barrels, scenes) hurts the same, berserk or not
    assert!((hit(&mut g) - hit(&mut plain)).abs() < 0.01);
}

// ----- levitation ---------------------------------------------------------------------------

#[test]
fn levitation_lets_the_player_fly_without_draining_the_meter() {
    let mut g = with_player(W, 900, FLOOR, 200);
    drink(&mut g, "potion_levitation", 400);
    let y0 = py(&g);
    run(&mut g, 120, &hold(|c| c.fly = true));
    // 3 s of meter would be gone; the potion keeps it full (10 s)
    let p = g.player().unwrap();
    assert!(p.fly > 0.95, "meter {}", p.fly);
    assert!(status(&g, "levitation") > 100);
    let high = py(&g);
    assert!(high < y0 - 60, "rose from {y0} to {high}");
    // longer than the 180 frames the meter allows: still rising
    run(&mut g, 120, &hold(|c| c.fly = true));
    assert!(py(&g) < high - 40, "still climbing at frame 240");
    assert!(g.player().unwrap().fly > 0.95);
}

#[test]
fn without_the_potion_the_meter_runs_out() {
    let mut g = with_player(W, 900, FLOOR, 200);
    run(&mut g, 240, &hold(|c| c.fly = true));
    assert!(g.player().unwrap().fly < 0.05);
}

#[test]
fn tapping_levitate_costs_nothing_under_the_potion() {
    let mut g = with_player(W, 900, FLOOR, 200);
    drink(&mut g, "potion_levitation", 400);
    run(&mut g, 30, &hold(|c| c.fly = true));
    for _ in 0..10 {
        run(&mut g, 1, &Controls::default());
        run(&mut g, 1, &hold(|c| c.fly = true));
    }
    assert!(g.player().unwrap().fly > 0.95, "taps cost nothing");
}

// ----- invisible ----------------------------------------------------------------------------

fn attacks(g: &mut Game) -> usize {
    count(&events(g), "enemy_attack")
}

#[test]
fn enemies_do_not_notice_an_invisible_player() {
    let mut g = arena();
    g.spawn_enemy("shotgunner", 240, ground_y(H, FLOOR))
        .unwrap();
    drink(&mut g, "potion_invisible", 400);
    events(&mut g);
    run(&mut g, 300, &Controls::default());
    assert_eq!(attacks(&mut g), 0, "the shotgunner never fired");
    assert_eq!(hp(&g), 100.0);
    // the same enemy does fire at a visible player
    let mut seen = arena();
    seen.spawn_enemy("shotgunner", 240, ground_y(H, FLOOR))
        .unwrap();
    run(&mut seen, 300, &Controls::default());
    assert!(attacks(&mut seen) >= 2);
}

#[test]
fn a_hunting_enemy_loses_an_invisible_player_at_once() {
    let mut g = arena();
    g.spawn_enemy("longleg", 200, ground_y(H, FLOOR)).unwrap();
    run(&mut g, 60, &Controls::default()); // it has noticed the player and is on its way
    drink(&mut g, "potion_invisible", 400);
    events(&mut g);
    let x_before = g.player().unwrap().x;
    run(&mut g, 300, &Controls::default());
    assert_eq!(g.player().unwrap().x, x_before);
    assert_eq!(hp(&g), 100.0, "not bitten");
}

#[test]
fn casting_or_kicking_shows_an_invisible_player_for_a_while() {
    let mut g = arena();
    g.spawn_enemy("shotgunner", 240, ground_y(H, FLOOR))
        .unwrap();
    let w = give(&mut g, &["LIGHT_BULLET"]);
    // two bottles: 1200 frames of invisibility cover the whole story
    drink(&mut g, "potion_invisible", 400);
    drink(&mut g, "potion_invisible", 400);
    run(&mut g, 120, &Controls::default());
    events(&mut g);
    assert_eq!(attacks(&mut g), 0);
    // fire straight up: the shot goes nowhere near the enemy, but the player shows
    run(&mut g, 1, &fire(w, 90.0));
    run(&mut g, 150, &Controls::default());
    assert!(attacks(&mut g) >= 1, "revealed by casting");
    // 180 frames after the cast the player is hidden again and the enemy loses the trail
    run(&mut g, 150, &Controls::default());
    events(&mut g);
    run(&mut g, 250, &Controls::default());
    assert_eq!(attacks(&mut g), 0, "hidden again");
    assert!(
        status(&g, "invisible") > 200,
        "still invisible by the potion"
    );
    // kicking reveals as well
    run(&mut g, 1, &hold(|c| c.kick = true));
    run(&mut g, 150, &Controls::default());
    assert!(attacks(&mut g) >= 1, "revealed by kicking");
}

// ----- fireproof ----------------------------------------------------------------------------

/// Fire cells all around the player, renewed every frame.
fn stand_in_fire(g: &mut Game, frames: u32) {
    for _ in 0..frames {
        let p = g.player().unwrap();
        g.world_mut()
            .fill_rect(p.x - 4, p.y - 12, 12, 24, "fire")
            .unwrap();
        run(g, 1, &Controls::default());
    }
}

#[test]
fn fire_sets_a_plain_player_alight_and_hurts() {
    let mut g = arena();
    stand_in_fire(&mut g, 40);
    assert!(status(&g, "on_fire") > 0);
    assert!(hp(&g) < 100.0);
}

#[test]
fn fireproof_keeps_the_player_from_catching_fire() {
    let mut g = arena();
    drink(&mut g, "potion_fireproof", 100);
    stand_in_fire(&mut g, 60);
    assert_eq!(status(&g, "on_fire"), 0);
    assert_eq!(hp(&g), 100.0);
}

#[test]
fn fireproof_puts_out_a_burning_player() {
    let mut g = arena();
    stand_in_fire(&mut g, 40);
    assert!(status(&g, "on_fire") > 0);
    drink(&mut g, "potion_fireproof", 100);
    run(&mut g, 2, &Controls::default());
    assert_eq!(status(&g, "on_fire"), 0, "put out");
    let ev = events(&mut g);
    assert!(ev
        .iter()
        .any(|(k, f)| k == "status" && text(f, "status") == "on_fire" && int(f, "active") == 0));
}

#[test]
fn fireproof_does_not_stop_lava_or_blasts() {
    // Noita: fire immunity does not stop lava contact damage; the rule is about fire only
    let mut g = arena();
    drink(&mut g, "potion_fireproof", 400);
    let y = ground_y(H, FLOOR);
    g.world_mut().fill_rect(80, y - 12, 60, 13, "lava").unwrap();
    run(&mut g, 10, &Controls::default());
    assert_eq!(status(&g, "on_fire"), 0, "not alight");
    assert!(hp(&g) < 100.0, "lava still burns the skin: {}", hp(&g));
}

// ----- random loot never holds the seal key -------------------------------------------------

#[test]
fn explosive_projectile_is_not_in_the_exclusion_by_accident() {
    let defs = EntityDefs::embedded().unwrap();
    assert_eq!(defs.spell_pickup_exclude, ["EXPLOSIVE_PROJECTILE"]);
}

#[test]
fn a_random_spell_pickup_never_is_explosive_projectile() {
    let mut g = world(1200, 100, 10, 77);
    let y = ground_y(100, 10);
    let mut seen = std::collections::BTreeSet::new();
    for i in 0..3000 {
        let id = g
            .spawn_item(
                &cogbench_game::ItemSpec::Spell { key: None },
                5 + (i % 1100),
                y,
            )
            .unwrap();
        let e = g.entities().into_iter().find(|e| e.id == id).unwrap();
        seen.insert(e.detail);
    }
    assert!(!seen.contains("EXPLOSIVE_PROJECTILE"));
    // while the rest of the book is still handed out, bombs included
    assert!(seen.contains("BOMB") && seen.contains("DAMAGE") && seen.contains("BURST_2"));
    assert!(seen.len() >= 20, "{} different spells", seen.len());
}

#[test]
fn the_marker_still_places_the_explosive_projectile() {
    let mut g = world(100, 100, 10, 5);
    let id = g
        .spawn_item(
            &cogbench_game::ItemSpec::Spell {
                key: Some("EXPLOSIVE_PROJECTILE".into()),
            },
            20,
            ground_y(100, 10),
        )
        .unwrap();
    let e = g.entities().into_iter().find(|e| e.id == id).unwrap();
    assert_eq!(e.detail, "EXPLOSIVE_PROJECTILE");
}
