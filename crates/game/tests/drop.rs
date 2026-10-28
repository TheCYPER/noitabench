//! The `drop` control: wands, carried spells and bottles go on the ground beside the player;
//! ground wands show what they are.

mod scene;

use scene::*;

use cogbench_game::{Controls, DropItem, Game, ItemSpec};

const W: i32 = 500;
const H: i32 = 200;
const FLOOR: i32 = 30;

fn arena() -> Game {
    with_player(W, H, FLOOR, 100)
}

fn drop_now(g: &mut Game, what: DropItem) {
    run(g, 1, &hold(|c| c.drop = Some(what)));
    run(g, 1, &Controls::default());
}

fn on_ground(g: &Game, kind: &str) -> Vec<cogbench_game::EntityView> {
    g.entities()
        .into_iter()
        .filter(|e| e.kind == kind)
        .collect()
}

fn mix(parts: &[(&str, u32)]) -> Vec<(String, u32)> {
    parts.iter().map(|(k, n)| ((*k).to_string(), *n)).collect()
}

#[test]
fn dropping_a_wand_puts_it_on_the_ground_beside_the_player() {
    let mut g = arena();
    assert_eq!(g.player().unwrap().wands.len(), 2, "the two starter wands");
    let second = g.player().unwrap().wands[1].id;
    drop_now(&mut g, DropItem::Wand(1));
    let p = g.player().unwrap();
    assert_eq!(p.wands.len(), 1);
    assert_ne!(p.wands[0].id, second);
    let wands = on_ground(&g, "wand");
    assert_eq!(wands.len(), 1);
    let w = &wands[0];
    let wand = w
        .wand
        .as_ref()
        .expect("a wand on the ground shows its stats");
    assert_eq!(wand.id, second, "the same wand, not a copy");
    assert_eq!(wand.stats.capacity, 1, "the digger wand");
    assert!(w.detail.contains("DIGGER"), "{}", w.detail);
    // beside the player, on the floor
    let (cx, floor) = (p.x + p.w / 2, p.y + p.h);
    assert!(
        (w.x + w.w / 2 - cx).abs() <= 8,
        "dropped at {} from {cx}",
        w.x
    );
    assert!(
        w.y + w.h <= floor + 1 && w.y + w.h >= floor - 2,
        "{} vs {floor}",
        w.y + w.h
    );
    let ev = events(&mut g);
    let d = ev.iter().find(|(k, _)| k == "drop").expect("an event");
    assert_eq!(text(&d.1, "item"), "wand");
}

#[test]
fn a_dropped_wand_can_be_picked_up_again_with_its_spells() {
    let mut g = arena();
    drop_now(&mut g, DropItem::Wand(0));
    assert_eq!(g.player().unwrap().wands.len(), 1);
    run(&mut g, 10, &Controls::default());
    run(&mut g, 1, &hold(|c| c.interact = true));
    let p = g.player().unwrap();
    assert_eq!(p.wands.len(), 2);
    let spark = &p.wands[1];
    assert_eq!(
        spark.slots[0].as_ref().map(|s| s.0.as_str()),
        Some("LIGHT_BULLET")
    );
}

#[test]
fn the_active_wand_stays_the_same_wand_when_an_earlier_one_goes() {
    let mut g = arena();
    run(&mut g, 1, &hold(|c| c.select_wand = Some(1)));
    let held = g.player().unwrap().wands[1].id;
    drop_now(&mut g, DropItem::Wand(0));
    let p = g.player().unwrap();
    assert_eq!(p.wands[p.active_wand].id, held);
    // dropping the held one leaves a valid index
    drop_now(&mut g, DropItem::Wand(0));
    let p = g.player().unwrap();
    assert!(p.wands.is_empty() && p.active_wand == 0);
    // firing without any wand is quiet
    run(&mut g, 5, &hold(|c| c.fire = true));
    assert_eq!(count(&events(&mut g), "cast"), 0);
}

#[test]
fn dropping_a_carried_spell_and_a_bottle() {
    let mut g = arena();
    g.give_spell("BOMB").unwrap();
    g.give_spell("DAMAGE").unwrap();
    g.give_mixed_bottle(&mix(&[("water", 30), ("oil", 20)]))
        .unwrap();
    g.give_bottle(Some("blood"), Some(10)).unwrap();
    drop_now(&mut g, DropItem::Spell(0));
    drop_now(&mut g, DropItem::Bottle(0));
    let p = g.player().unwrap();
    assert_eq!(p.spells.len(), 1);
    assert_eq!(p.spells[0].0, "DAMAGE");
    assert_eq!(p.bottles, vec![("blood".to_string(), 10)]);
    let spell = &on_ground(&g, "spell")[0];
    assert_eq!(spell.detail, "BOMB");
    let bottle = &on_ground(&g, "bottle")[0];
    assert_eq!(bottle.contents, Some(mix(&[("water", 30), ("oil", 20)])));
    // and the mixed bottle comes back with its contents
    run(&mut g, 10, &Controls::default());
    let before = g.player().unwrap().bottles.len();
    run(&mut g, 1, &hold(|c| c.interact = true));
    let p = g.player().unwrap();
    assert_eq!(p.bottles.len(), before + 1);
    assert_eq!(
        p.bottle_contents.last().unwrap(),
        &mix(&[("water", 30), ("oil", 20)])
    );
    let ev = events(&mut g);
    let kinds: Vec<String> = ev
        .iter()
        .filter(|(k, _)| k == "drop")
        .map(|(_, f)| text(f, "item"))
        .collect();
    assert_eq!(kinds, ["spell", "bottle"]);
}

#[test]
fn holding_the_drop_control_drops_once_and_a_new_value_drops_again() {
    let mut g = arena();
    g.give_spell("BOMB").unwrap();
    g.give_spell("DAMAGE").unwrap();
    g.give_spell("SPEED").unwrap();
    run(&mut g, 10, &hold(|c| c.drop = Some(DropItem::Spell(0))));
    assert_eq!(
        g.player().unwrap().spells.len(),
        2,
        "held for 10 frames: one drop"
    );
    // let go, then press the same index again: another drop
    run(&mut g, 1, &Controls::default());
    run(&mut g, 1, &hold(|c| c.drop = Some(DropItem::Spell(0))));
    assert_eq!(g.player().unwrap().spells.len(), 1);
    // changing the value while it stays held also counts
    g.give_spell("BOMB").unwrap();
    g.give_spell("DAMAGE").unwrap();
    run(&mut g, 1, &Controls::default());
    run(&mut g, 1, &hold(|c| c.drop = Some(DropItem::Spell(0))));
    run(&mut g, 1, &hold(|c| c.drop = Some(DropItem::Spell(1))));
    assert_eq!(g.player().unwrap().spells.len(), 1);
}

#[test]
fn an_index_the_player_does_not_have_drops_nothing() {
    let mut g = arena();
    drop_now(&mut g, DropItem::Wand(7));
    drop_now(&mut g, DropItem::Spell(0));
    drop_now(&mut g, DropItem::Bottle(0));
    assert_eq!(g.player().unwrap().wands.len(), 2);
    assert_eq!(count(&events(&mut g), "drop"), 0);
    assert!(g.entities().iter().all(|e| e.kind == "player"));
}

#[test]
fn a_dead_player_drops_nothing() {
    let mut g = arena();
    g.give_spell("BOMB").unwrap();
    for _ in 0..20 {
        g.blast(cogbench_game::BlastSpec {
            x: 100,
            y: ground_y(H, FLOOR) - 4,
            radius: 10,
            damage: 3.0,
            ray_energy: 1000,
            max_durability: 4,
            fire_percent: 0,
            owner: cogbench_game::entity::Owner::World,
            spare_owner: false,
        });
    }
    assert!(g.player().unwrap().dead);
    drop_now(&mut g, DropItem::Spell(0));
    assert_eq!(g.player().unwrap().spells.len(), 1);
}

#[test]
fn a_dropped_bottle_ends_the_drink_in_progress() {
    let mut g = arena();
    g.give_bottle(Some("potion_heal"), None).unwrap();
    run(&mut g, 3, &hold(|c| c.drink = true));
    run(&mut g, 1, &hold(|c| c.drop = Some(DropItem::Bottle(0))));
    let ev = events(&mut g);
    assert_eq!(count(&ev, "drink"), 1);
    assert_eq!(count(&ev, "drop"), 1);
}

#[test]
fn a_wand_lying_on_the_ground_shows_its_stats_and_spells() {
    let mut g = arena();
    let id = g
        .spawn_item(&ItemSpec::Wand { tier: 2 }, 300, ground_y(H, FLOOR))
        .unwrap();
    let e = g.entities().into_iter().find(|e| e.id == id).unwrap();
    let wand = e.wand.expect("stats");
    assert!(wand.stats.capacity >= 1 && wand.stats.mana_max > 0.0);
    let spells: Vec<String> = wand
        .slots
        .iter()
        .map(|s| s.as_ref().map_or("-".to_string(), |(k, _)| k.clone()))
        .collect();
    assert_eq!(e.detail, spells.join(","));
    // other items have no wand view
    let b = g
        .spawn_item(
            &ItemSpec::Bottle {
                material: Some("water".into()),
                amount: Some(5),
            },
            320,
            ground_y(H, FLOOR),
        )
        .unwrap();
    assert!(g
        .entities()
        .into_iter()
        .find(|e| e.id == b)
        .unwrap()
        .wand
        .is_none());
}

#[test]
fn dropping_is_deterministic_and_survives_a_snapshot() {
    let play = |g: &mut Game| {
        g.give_mixed_bottle(&mix(&[("water", 30), ("oil", 20)]))
            .unwrap();
        drop_now(g, DropItem::Wand(0));
        drop_now(g, DropItem::Bottle(0));
        run(g, 30, &Controls::default());
    };
    let (mut a, mut b) = (arena(), arena());
    play(&mut a);
    play(&mut b);
    assert_eq!(a.state_hash(), b.state_hash());
    let blob = a.snapshot().unwrap();
    run(&mut a, 20, &Controls::default());
    let h = a.state_hash();
    b.restore(&blob).unwrap();
    run(&mut b, 20, &Controls::default());
    assert_eq!(b.state_hash(), h);
}

fn shuffle_stats() -> cogbench_game::wand::WandStats {
    cogbench_game::wand::WandStats {
        shuffle: true,
        mana_max: 1000.0,
        ..stats()
    }
}

/// The spells of the `cast` events so far, in order.
fn cast_spells(g: &mut Game) -> Vec<String> {
    events(g)
        .iter()
        .filter(|(k, _)| k == "cast")
        .map(|(_, f)| text(f, "spells"))
        .collect()
}

#[test]
fn a_wand_that_was_dropped_and_picked_up_deals_the_same_cards_and_keeps_its_mana() {
    let keys = [
        "LIGHT_BULLET",
        "BULLET",
        "RUBBER_BALL",
        "SLOW_BULLET",
        "DAMAGE",
        "SPEED",
    ];
    let spells: Vec<Option<String>> = keys.iter().map(|k| Some((*k).to_string())).collect();
    let casts = |drop_it: bool| {
        let mut g = arena();
        g.give_wand(shuffle_stats(), &spells, &[]).unwrap();
        let mine = (g.player().unwrap().wands.len() - 1) as u8;
        if drop_it {
            run(&mut g, 1, &hold(|c| c.select_wand = Some(mine)));
            let before = g.player().unwrap().wands[usize::from(mine)].clone();
            drop_now(&mut g, DropItem::Wand(mine));
            run(&mut g, 30, &Controls::default()); // it lies there; its mana does not move
            run(&mut g, 1, &hold(|c| c.interact = true));
            run(&mut g, 1, &Controls::default());
            let after = g.player().unwrap().wands.last().unwrap().clone();
            assert_eq!(after.id, before.id);
            assert_eq!(after.mana, before.mana, "no regeneration on the ground");
            assert_eq!(after.cooldown, before.cooldown);
            assert_eq!(after.slots, before.slots);
        }
        let held = g.player().unwrap().wands.len() as u8 - 1;
        let mut seen = Vec::new();
        for _ in 0..8 {
            run(&mut g, 1, &fire(held, 0.0));
            run(&mut g, 1, &hold(|c| c.select_wand = Some(held)));
            run(&mut g, 60, &Controls::default());
            seen.extend(cast_spells(&mut g));
        }
        seen
    };
    let (plain, moved) = (casts(false), casts(true));
    assert!(plain.len() >= 6, "{plain:?}");
    assert_eq!(plain, moved, "the shuffle goes on where it was");
}

#[test]
fn dropping_in_a_one_cell_corridor_still_drops_something_sane() {
    let mut g = arena();
    let p = g.player().unwrap();
    let floor = p.y + p.h;
    // walls right against the player on both sides, a roof above
    g.world_mut()
        .fill_rect(p.x - 6, floor - 20, 6, 20, "rock")
        .unwrap();
    g.world_mut()
        .fill_rect(p.x + p.w, floor - 20, 6, 20, "rock")
        .unwrap();
    g.give_mixed_bottle(&mix(&[("water", 30), ("oil", 20)]))
        .unwrap();
    drop_now(&mut g, DropItem::Wand(0));
    drop_now(&mut g, DropItem::Bottle(0));
    run(&mut g, 120, &Controls::default());
    assert_eq!(g.player().unwrap().wands.len(), 1);
    assert!(g.player().unwrap().bottles.is_empty());
    let p = g.player().unwrap();
    for e in g
        .entities()
        .iter()
        .filter(|e| e.kind == "wand" || e.kind == "bottle")
    {
        // within a few cells of the player, not in the rock, not fallen through the floor
        assert!((e.x - p.x).abs() <= 12, "{} vs {}", e.x, p.x);
        assert!(
            e.y + e.h <= floor + 1,
            "{} below the floor {floor}",
            e.y + e.h
        );
        assert!(e.y + e.h >= floor - 8, "{} up in the air", e.y + e.h);
    }
    // and both can be picked up again with their contents
    run(&mut g, 1, &hold(|c| c.interact = true));
    run(&mut g, 1, &Controls::default());
    run(&mut g, 1, &hold(|c| c.interact = true));
    let p = g.player().unwrap();
    assert_eq!(p.wands.len() + p.bottles.len(), 3);
}

#[test]
fn the_held_bottle_keeps_its_action_state_straight_when_an_earlier_bottle_goes() {
    let mut g = arena();
    g.give_bottle(Some("potion_heal"), Some(300)).unwrap();
    g.give_bottle(Some("oil"), Some(100)).unwrap();
    run(&mut g, 1, &hold(|c| c.select_bottle = Some(1)));
    run(&mut g, 3, &hold(|c| c.drink = true));
    // drop bottle 0 while the key stays down: the drink of the oil bottle goes on at index 0
    run(
        &mut g,
        1,
        &hold(|c| {
            c.drink = true;
            c.drop = Some(DropItem::Bottle(0));
        }),
    );
    let p = g.player().unwrap();
    assert_eq!(p.active_bottle, 0);
    assert_eq!(p.bottle_contents.len(), 1);
    assert_eq!(
        p.bottle_contents[0][0].0, "oil",
        "the held bottle is still the oil"
    );
    let before: u32 = p.bottle_contents[0].iter().map(|c| c.1).sum();
    run(&mut g, 2, &hold(|c| c.drink = true));
    let after: u32 = g.player().unwrap().bottle_contents[0]
        .iter()
        .map(|c| c.1)
        .sum();
    assert!(
        after < before,
        "{after} < {before}: it keeps drinking the same bottle"
    );
}
