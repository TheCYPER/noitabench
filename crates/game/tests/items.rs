//! Items and bottles: pickup, fill, pour, drink, throw, kick, the wand editor.

mod scene;

use scene::*;

use cogbench_game::{Controls, Game, ItemSpec, WandEdit};

const W: i32 = 500;
const H: i32 = 200;
const FLOOR: i32 = 30;

fn arena() -> Game {
    with_player(W, H, FLOOR, 100)
}

fn put(g: &mut Game, spec: ItemSpec, x: i32) -> u32 {
    g.spawn_item(&spec, x, ground_y(H, FLOOR)).unwrap()
}

fn bottle(material: &str) -> ItemSpec {
    ItemSpec::Bottle {
        material: Some(material.into()),
        amount: None,
    }
}

fn press(f: impl FnOnce(&mut Controls)) -> Controls {
    hold(f)
}

/// Rock walls so that a liquid stays in a 40 wide pit above the floor.
fn pool(g: &mut Game, x0: i32, material: &str, depth: i32) {
    let y = ground_y(H, FLOOR);
    g.world_mut()
        .fill_rect(x0 - 3, y - 60, 3, 61, "rock")
        .unwrap();
    g.world_mut()
        .fill_rect(x0 + 40, y - 60, 3, 61, "rock")
        .unwrap();
    g.world_mut()
        .fill_rect(x0, y - depth + 1, 40, depth, material)
        .unwrap();
}

#[test]
fn interact_picks_up_the_nearest_item_in_reach() {
    let mut g = arena();
    put(&mut g, bottle("water"), 104);
    put(
        &mut g,
        ItemSpec::Spell {
            key: Some("BOMB".into()),
        },
        110,
    );
    put(&mut g, ItemSpec::Wand { tier: 1 }, 300);
    run(&mut g, 5, &Controls::default());
    run(&mut g, 1, &press(|c| c.interact = true));
    run(&mut g, 1, &Controls::default());
    run(&mut g, 1, &press(|c| c.interact = true));
    let p = g.player().unwrap();
    assert_eq!(p.bottles, vec![("water".to_string(), 400)]);
    assert_eq!(p.spells, vec![("BOMB".to_string(), Some(3))]);
    assert_eq!(p.wands.len(), 2, "the far wand stays where it is");
    let ev = events(&mut g);
    assert_eq!(count(&ev, "pickup"), 2);
}

#[test]
fn picking_up_an_empty_bottle_reports_no_contents() {
    let mut g = arena();
    put(
        &mut g,
        ItemSpec::Bottle {
            material: None,
            amount: None,
        },
        104,
    );
    run(&mut g, 5, &Controls::default());
    run(&mut g, 1, &press(|c| c.interact = true));
    let ev = events(&mut g);
    let (_, fields) = ev.iter().find(|(k, _)| k == "pickup").expect("a pickup");
    assert_eq!(text(fields, "item"), "bottle");
    assert_eq!(text(fields, "detail"), "", "not the air it is full of");
    assert_eq!(
        g.player().unwrap().bottles,
        vec![(String::new(), 0)],
        "an empty bottle has no material"
    );
}

#[test]
fn holding_interact_picks_up_only_once_per_press() {
    let mut g = arena();
    put(&mut g, bottle("water"), 104);
    put(&mut g, bottle("oil"), 106);
    run(&mut g, 5, &Controls::default());
    run(&mut g, 20, &press(|c| c.interact = true));
    assert_eq!(g.player().unwrap().bottles.len(), 1);
}

#[test]
fn a_full_bottle_inventory_refuses_more() {
    let mut g = arena();
    for _ in 0..4 {
        g.give_bottle(Some("water"), None).unwrap();
    }
    put(&mut g, bottle("oil"), 104);
    run(&mut g, 5, &Controls::default());
    run(&mut g, 1, &press(|c| c.interact = true));
    let ev = events(&mut g);
    assert_eq!(count(&ev, "pickup_failed"), 1);
    assert_eq!(g.player().unwrap().bottles.len(), 4);
}

#[test]
fn filling_scoops_liquid_out_of_the_ground() {
    let mut g = arena();
    pool(&mut g, 80, "water", 6);
    g.give_bottle(None, None).unwrap();
    let before = count_cells(&g, 0, 0, W, H, "water");
    run(&mut g, 30, &press(|c| c.fill = true));
    run(&mut g, 1, &Controls::default());
    let p = g.player().unwrap();
    assert_eq!(p.bottles[0].0, "water");
    let taken = before - count_cells(&g, 0, 0, W, H, "water");
    assert_eq!(p.bottles[0].1 as usize, taken);
    assert!(taken >= 100, "scooped {taken} cells");
    let ev = events(&mut g);
    let f = ev.iter().find(|(k, _)| k == "fill").unwrap();
    assert_eq!(text(&f.1, "material"), "water");
}

#[test]
fn a_bottle_takes_a_second_liquid_in_with_the_first() {
    let mut g = arena();
    pool(&mut g, 80, "water", 6);
    g.give_bottle(Some("oil"), Some(100)).unwrap();
    run(&mut g, 20, &press(|c| c.fill = true));
    let p = g.player().unwrap();
    let (water, oil) = (&p.bottle_contents[0][0], &p.bottle_contents[0][1]);
    assert_eq!(water.0, "water");
    assert!(water.1 >= 100, "scooped {}", water.1);
    assert_eq!(oil, &("oil".to_string(), 100));
    assert_eq!(p.bottles, vec![("water".to_string(), water.1 + 100)]);
}

#[test]
fn pouring_puts_the_liquid_in_front_of_the_player() {
    let mut g = arena();
    g.give_bottle(Some("oil"), Some(80)).unwrap();
    let pour = press(|c| {
        c.pour = true;
        c.aim = 0.0;
    });
    run(&mut g, 1, &pour);
    assert_eq!(count_cells(&g, 0, 0, W, H, "oil"), 8, "8 cells a frame");
    assert_eq!(
        count_cells(&g, 0, 0, 102, H, "oil"),
        0,
        "nothing at or behind the player"
    );
    assert_eq!(
        count_cells(&g, 104, 0, 20, H, "oil"),
        8,
        "a hand's length in front"
    );
    run(&mut g, 29, &pour);
    run(&mut g, 1, &Controls::default());
    let p = g.player().unwrap();
    assert_eq!(p.bottles, vec![(String::new(), 0)], "emptied");
    assert_eq!(count_cells(&g, 0, 0, W, H, "oil"), 80);
    let ev = events(&mut g);
    let pour_event = ev.iter().find(|(k, _)| k == "pour").unwrap();
    assert_eq!(int(&pour_event.1, "cells"), 80);
}

#[test]
fn drinking_a_heal_potion_heals() {
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    for _ in 0..2 {
        g.blast(cogbench_game::BlastSpec {
            x: 100,
            y: y - 4,
            radius: 5,
            damage: 3.0,
            ray_energy: 1000,
            max_durability: 4,
            fire_percent: 0,
            owner: cogbench_game::entity::Owner::World,
            spare_owner: false,
        });
    }
    let hurt = g.player().unwrap().hp;
    assert!(hurt < 60.0, "{hurt}");
    g.give_bottle(Some("potion_heal"), None).unwrap();
    run(&mut g, 10, &press(|c| c.drink = true));
    let hp = g.player().unwrap().hp;
    // 100 cells x 0.01 internal = 1.0 = 25 displayed
    assert!((hp - hurt - 25.0).abs() < 1.0, "{hurt} -> {hp}");
    assert_eq!(g.player().unwrap().bottles[0].1, 300);
    run(&mut g, 1, &Controls::default());
    let ev = events(&mut g);
    let d = ev.iter().find(|(k, _)| k == "drink").unwrap();
    assert_eq!(int(&d.1, "cells"), 100);
}

#[test]
fn a_full_heal_potion_never_heals_past_the_maximum() {
    let mut g = arena();
    g.give_bottle(Some("potion_heal"), None).unwrap();
    run(&mut g, 60, &press(|c| c.drink = true));
    assert_eq!(g.player().unwrap().hp, 100.0);
}

#[test]
fn a_mana_potion_refills_the_wands() {
    let mut g = arena();
    let mut st = stats();
    st.mana_max = 200.0;
    st.mana_charge_speed = 0.0;
    st.cast_delay = 5;
    g.give_wand(st, &[Some("BOMB".to_string())], &[]).unwrap();
    run(&mut g, 1, &fire(2, 0.0));
    run(&mut g, 120, &Controls::default());
    let low = g.player().unwrap().wands[2].mana;
    assert_eq!(low, 175.0, "a bomb costs 25 mana");
    g.give_bottle(Some("potion_mana"), None).unwrap();
    run(&mut g, 10, &press(|c| c.drink = true));
    let now = g.player().unwrap().wands[2].mana;
    assert_eq!(now, 200.0, "100 cells x 0.5 mana, capped at the maximum");
}

#[test]
fn a_haste_potion_makes_the_player_faster() {
    let mut g = arena();
    let x0 = px(&g);
    run(&mut g, 60, &press(|c| c.move_x = 1));
    let normal = px(&g) - x0;
    let mut g = arena();
    g.give_bottle(Some("potion_haste"), None).unwrap();
    run(&mut g, 10, &press(|c| c.drink = true));
    assert!(g.player().unwrap().statuses.iter().any(|s| s.0 == "haste"));
    let x0 = px(&g);
    run(&mut g, 60, &press(|c| c.move_x = 1));
    let fast = px(&g) - x0;
    assert!(fast as f32 > normal as f32 * 1.3, "{normal} vs {fast}");
}

#[test]
fn drinking_acid_hurts() {
    let mut g = arena();
    g.give_bottle(Some("acid"), Some(100)).unwrap();
    run(&mut g, 10, &press(|c| c.drink = true));
    // 100 cells x 0.01 = 1.0 internal = 25 displayed, plus the first frames' worth of contact
    let hp = g.player().unwrap().hp;
    assert!((hp - 75.0).abs() < 2.0, "{hp}");
}

#[test]
fn drinking_oil_makes_the_player_oily() {
    let mut g = arena();
    g.give_bottle(Some("oil"), Some(100)).unwrap();
    run(&mut g, 2, &press(|c| c.drink = true));
    assert!(g.player().unwrap().statuses.iter().any(|s| s.0 == "oiled"));
}

#[test]
fn a_thrown_bottle_shatters_on_the_wall_and_spills() {
    let mut g = arena();
    g.world_mut().fill_rect(200, 0, 10, H, "rock").unwrap();
    g.give_bottle(Some("oil"), None).unwrap();
    run(
        &mut g,
        1,
        &press(|c| {
            c.throw = true;
            c.aim = 10.0;
        }),
    );
    assert!(
        g.player().unwrap().bottles.is_empty(),
        "the bottle left the hand"
    );
    run(&mut g, 90, &Controls::default());
    let ev = events(&mut g);
    assert_eq!(count(&ev, "throw"), 1);
    let s = ev.iter().find(|(k, _)| k == "shatter").expect("shattered");
    assert_eq!(int(&s.1, "cells"), 400);
    assert_eq!(count_cells(&g, 0, 0, W, H, "oil"), 400);
}

#[test]
fn a_thrown_bottle_of_water_puts_out_a_burning_enemy() {
    let mut g = arena();
    let y = ground_y(H, FLOOR);
    g.spawn_enemy("longleg", 160, y).unwrap();
    g.world_mut().fill_rect(190, y - 30, 3, 31, "rock").unwrap();
    g.give_bottle(Some("water"), None).unwrap();
    run(
        &mut g,
        1,
        &press(|c| {
            c.throw = true;
            c.aim = 15.0;
        }),
    );
    run(&mut g, 50, &Controls::default());
    let ev = events(&mut g);
    assert_eq!(count(&ev, "shatter"), 1, "{ev:?}");
}

#[test]
fn kicking_sends_a_bottle_flying() {
    let mut g = arena();
    let id = put(&mut g, bottle("water"), 108);
    run(&mut g, 5, &Controls::default());
    let x0 = g.entities().into_iter().find(|e| e.id == id).unwrap().x;
    run(&mut g, 1, &press(|c| c.kick = true));
    run(&mut g, 30, &Controls::default());
    let x1 = g.entities().into_iter().find(|e| e.id == id).unwrap().x;
    assert!(x1 > x0 + 20, "{x0} -> {x1}");
}

#[test]
fn the_wand_editor_moves_spells_between_inventory_and_wand() {
    let mut g = arena();
    g.give_spell("DAMAGE").unwrap();
    g.give_spell("BOMB").unwrap();
    // wand 0 is the spark wand with LIGHT_BULLET in slot 0
    g.edit_wand(WandEdit::Place {
        wand: 0,
        slot: 1,
        from: 0,
    })
    .unwrap();
    let p = g.player().unwrap();
    assert_eq!(p.wands[0].slots[1].as_ref().unwrap().0, "DAMAGE");
    assert_eq!(p.spells.len(), 1);
    // replacing a spell sends the old one back to the inventory
    g.edit_wand(WandEdit::Place {
        wand: 0,
        slot: 0,
        from: 0,
    })
    .unwrap();
    let p = g.player().unwrap();
    assert_eq!(p.wands[0].slots[0].as_ref().unwrap().0, "BOMB");
    assert_eq!(p.spells, vec![("LIGHT_BULLET".to_string(), None)]);
    g.edit_wand(WandEdit::Swap {
        wand: 0,
        a: 0,
        b: 1,
    })
    .unwrap();
    assert_eq!(
        g.player().unwrap().wands[0].slots[0].as_ref().unwrap().0,
        "DAMAGE"
    );
    g.edit_wand(WandEdit::Take { wand: 0, slot: 0 }).unwrap();
    assert!(g.player().unwrap().wands[0].slots[0].is_none());
    assert!(
        g.edit_wand(WandEdit::Take { wand: 0, slot: 0 }).is_err(),
        "slot is empty now"
    );
    assert!(g
        .edit_wand(WandEdit::Place {
            wand: 9,
            slot: 0,
            from: 0
        })
        .is_err());
}

#[test]
fn a_picked_up_wand_can_be_selected_and_fired() {
    let mut g = arena();
    put(&mut g, ItemSpec::Wand { tier: 2 }, 104);
    run(&mut g, 5, &Controls::default());
    run(&mut g, 1, &press(|c| c.interact = true));
    assert_eq!(g.player().unwrap().wands.len(), 3);
    run(
        &mut g,
        3,
        &press(|c| {
            c.select_wand = Some(2);
            c.fire = true;
            c.aim = 0.0;
        }),
    );
    assert_eq!(g.player().unwrap().active_wand, 2);
}

#[test]
fn switching_bottles_while_drinking_reports_each_liquid() {
    let mut g = arena();
    g.give_bottle(Some("potion_heal"), Some(30)).unwrap();
    g.give_bottle(Some("potion_haste"), Some(30)).unwrap();
    run(
        &mut g,
        3,
        &press(|c| {
            c.drink = true;
            c.select_bottle = Some(0);
        }),
    );
    run(
        &mut g,
        3,
        &press(|c| {
            c.drink = true;
            c.select_bottle = Some(1);
        }),
    );
    run(&mut g, 1, &Controls::default());
    let drinks: Vec<String> = events(&mut g)
        .iter()
        .filter(|(k, _)| k == "drink")
        .map(|(_, f)| text(f, "material"))
        .collect();
    assert_eq!(drinks, ["potion_heal", "potion_haste"]);
}

#[test]
fn thrown_bottles_are_not_in_the_hand_afterwards_and_empty_ones_shatter_harmlessly() {
    let mut g = arena();
    g.give_bottle(None, None).unwrap();
    run(&mut g, 1, &press(|c| c.throw = true));
    run(&mut g, 60, &Controls::default());
    let ev = events(&mut g);
    let s = ev.iter().find(|(k, _)| k == "shatter").unwrap();
    assert_eq!(int(&s.1, "cells"), 0);
}
