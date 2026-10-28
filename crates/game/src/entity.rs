//! The things that live in the world besides cells: the player, enemies and items. Plain
//! serialisable data; the rules that move and hurt them are in `game/`.

use serde::{Deserialize, Serialize};

use cogbench_sim::Recipe;

use crate::physics::Body;
use crate::projectile::ProjectileDef;
use crate::rng::SpellRng;
use crate::status::Statuses;
use crate::wand::{Slot, Wand};

pub type EntityId = u32;

/// Who fired a projectile or set off a blast.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Owner {
    Player,
    Enemy(EntityId),
    World,
}

/// Something that can be hurt.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Target {
    Player,
    Enemy(EntityId),
    Item(EntityId),
}

/// Where damage comes from, for the per-source multipliers of entities (player: explosions
/// 0.35; Stendari: fire 0, explosions 0.4). There is a single damage type otherwise.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum DamageSource {
    Hit,
    Explosion,
    Fire,
    Melee,
    Contact,
}

impl DamageSource {
    pub const fn key(self) -> &'static str {
        match self {
            DamageSource::Hit => "hit",
            DamageSource::Explosion => "explosion",
            DamageSource::Fire => "fire",
            DamageSource::Melee => "melee",
            DamageSource::Contact => "contact",
        }
    }
}

/// Hit points, statuses and the bookkeeping every living thing shares.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Vitals {
    pub hp: f32,
    pub hp_max: f32,
    pub statuses: Statuses,
    /// Frames during which damage is ignored (the player starts with some).
    pub invincible: u32,
    pub dead: bool,
    /// Damage of the slow sources (contact, fire, poison, drowning) not yet logged.
    pub logged_damage: f32,
    pub logged_since: u64,
}

impl Vitals {
    pub fn new(hp: f32, invincible: u32) -> Vitals {
        Vitals {
            hp,
            hp_max: hp,
            statuses: Statuses::default(),
            invincible,
            dead: false,
            logged_damage: 0.0,
            logged_since: 0,
        }
    }
}

/// A share of one material in a bottle.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Part {
    /// Material index.
    pub material: u8,
    pub amount: u32,
}

/// What a bottle holds: a mixture of liquids and powders, like a flask of Noita. The parts are
/// sorted by material index, each material appears once and every amount is above zero, so equal
/// contents are equal values whatever order they were poured in.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Bottle {
    pub parts: Vec<Part>,
}

impl Bottle {
    /// A bottle of one material (`amount == 0` makes it empty).
    pub fn single(material: u8, amount: u32) -> Bottle {
        let mut b = Bottle::default();
        b.add(material, amount);
        b
    }

    /// A bottle holding the given materials; repeats are added up.
    pub fn of(parts: impl IntoIterator<Item = (u8, u32)>) -> Bottle {
        let mut b = Bottle::default();
        for (material, amount) in parts {
            b.add(material, amount);
        }
        b
    }

    pub fn is_empty(&self) -> bool {
        self.parts.is_empty()
    }

    /// Cells in the bottle, all materials together.
    pub fn total(&self) -> u32 {
        self.parts.iter().map(|p| p.amount).sum()
    }

    /// Cells of one material.
    pub fn amount_of(&self, material: u8) -> u32 {
        self.parts
            .iter()
            .find(|p| p.material == material)
            .map_or(0, |p| p.amount)
    }

    /// The material with the largest share (the lowest index among equals); `None` when empty.
    pub fn largest(&self) -> Option<u8> {
        self.parts
            .iter()
            .reduce(|best, p| if p.amount > best.amount { p } else { best })
            .map(|p| p.material)
    }

    /// Put `amount` cells of a material in.
    pub fn add(&mut self, material: u8, amount: u32) {
        if amount == 0 {
            return;
        }
        match self.parts.binary_search_by_key(&material, |p| p.material) {
            Ok(i) => self.parts[i].amount += amount,
            Err(i) => self.parts.insert(i, Part { material, amount }),
        }
    }

    /// Take `cells` cells out (at most what is in the bottle), the same share of every material:
    /// each gives `cells * its_amount / total` rounded down, and the cells left over go to the
    /// materials with the largest remainders (then the larger amount, then the lower index).
    /// Returns what was taken, sorted by material.
    pub fn take(&mut self, cells: u32) -> Vec<Part> {
        let total = self.total();
        let cells = cells.min(total);
        if cells == 0 {
            return Vec::new();
        }
        if cells == total {
            return std::mem::take(&mut self.parts);
        }
        let (n, t) = (u64::from(cells), u64::from(total));
        let mut shares: Vec<u32> = self
            .parts
            .iter()
            .map(|p| (n * u64::from(p.amount) / t) as u32)
            .collect();
        let mut spare = cells - shares.iter().sum::<u32>();
        let mut order: Vec<usize> = (0..self.parts.len()).collect();
        order.sort_by(|&a, &b| {
            let rem = |i: usize| n * u64::from(self.parts[i].amount) % t;
            rem(b)
                .cmp(&rem(a))
                .then(self.parts[b].amount.cmp(&self.parts[a].amount))
                .then(a.cmp(&b))
        });
        for i in order {
            if spare == 0 {
                break;
            }
            if shares[i] < self.parts[i].amount {
                shares[i] += 1;
                spare -= 1;
            }
        }
        let mut taken = Vec::new();
        for (part, share) in self.parts.iter_mut().zip(shares) {
            part.amount -= share;
            if share > 0 {
                taken.push(Part {
                    material: part.material,
                    amount: share,
                });
            }
        }
        self.parts.retain(|p| p.amount > 0);
        taken
    }

    /// Turn ingredients into potions: for each recipe (in order) whose three ingredients are all
    /// in the bottle, up to `most` cells of each become potion, cell for cell (like the grid rule:
    /// three cells in, three potion cells out). Returns the potions made and how many cells of
    /// each.
    pub fn mix(&mut self, recipes: &[Recipe], most: u32) -> Vec<(u8, u32)> {
        let mut made = Vec::new();
        for r in recipes {
            let k = r
                .inputs
                .iter()
                .map(|&m| self.amount_of(m))
                .min()
                .unwrap_or(0)
                .min(most);
            if k == 0 {
                continue;
            }
            for &m in &r.inputs {
                self.remove(m, k);
            }
            self.add(r.potion, 3 * k);
            made.push((r.potion, 3 * k));
        }
        made
    }

    fn remove(&mut self, material: u8, amount: u32) {
        if let Ok(i) = self.parts.binary_search_by_key(&material, |p| p.material) {
            self.parts[i].amount = self.parts[i].amount.saturating_sub(amount);
            if self.parts[i].amount == 0 {
                self.parts.remove(i);
            }
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum BottleOp {
    Drink,
    Pour,
    Fill,
}

/// A drink, pour or fill in progress; one event per material summarises it when it stops.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct BottleAction {
    pub op: BottleOp,
    /// Which bottle (index in the hand) it works on; another bottle is another action.
    pub bottle: usize,
    /// Cells moved so far, by material.
    pub moved: Bottle,
}

/// A wand together with its own card-dealing random stream (contract section 9).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct HeldWand {
    pub id: EntityId,
    pub wand: Wand,
    pub rng: SpellRng,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Player {
    pub id: EntityId,
    pub body: Body,
    pub vitals: Vitals,
    /// -1 or 1.
    pub facing: i8,
    /// Levitation meter in frames of flight left.
    pub fly_meter: f32,
    /// Frames spent in the air without flying (the recharge starts after a wait).
    pub air_wait: u32,
    /// Frames of breath left under liquid.
    pub breath: u32,
    pub kick_cooldown: u32,
    /// Last aim in degrees.
    pub aim: f32,
    pub wands: Vec<HeldWand>,
    pub active_wand: usize,
    /// Spells carried but not in a wand.
    pub spells: Vec<Slot>,
    pub bottles: Vec<Bottle>,
    pub active_bottle: usize,
    pub action: Option<BottleAction>,
    /// Frames an invisible player stays visible after casting or kicking.
    #[serde(default)]
    pub revealed: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Windup {
    Melee,
    Lunge,
    Shoot,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Enemy {
    pub id: EntityId,
    /// Key into `entities.json` `enemies` (`longleg`, `shotgunner`, `firemage_weak`).
    pub kind: String,
    pub body: Body,
    pub vitals: Vitals,
    pub facing: i8,
    /// Frames the enemy still remembers the player after losing sight.
    pub alert: u32,
    pub flee: u32,
    pub patrol_dir: i8,
    pub patrol_left: u32,
    pub melee_cooldown: u32,
    pub ranged_cooldown: u32,
    pub lunge_cooldown: u32,
    pub windup: Option<(Windup, u32)>,
    /// Frames of a lunge in progress.
    pub lunging: u32,
    pub last_hp: f32,
}

/// A thrown or lit bomb: its projectile definition, fuse and who threw it.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Bomb {
    pub def: ProjectileDef,
    pub fuse: i32,
    pub owner: Owner,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum ItemKind {
    Wand(Box<HeldWand>),
    Spell(Slot),
    Bottle(Bottle),
    /// A bottle in flight: it shatters on impact and spills.
    Thrown(Bottle),
    /// Key into `entities.json` `items.barrels`.
    Barrel(String),
    Bomb(Box<Bomb>),
}

impl ItemKind {
    /// The `kind` shown in recordings and Python dicts.
    pub fn label(&self) -> String {
        match self {
            ItemKind::Wand(_) => "wand".into(),
            ItemKind::Spell(_) => "spell".into(),
            ItemKind::Bottle(_) | ItemKind::Thrown(_) => "bottle".into(),
            ItemKind::Barrel(key) => key.clone(),
            ItemKind::Bomb(_) => "bomb".into(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Item {
    pub id: EntityId,
    pub body: Body,
    pub kind: ItemKind,
    /// Hit points; 0 for things that cannot be hurt (wands, spells, bottles).
    pub hp: f32,
    pub hp_max: f32,
    /// A resting item is not simulated until its floor goes away.
    pub asleep: bool,
    /// Frames of fuse (gunpowder barrel) or burning (oil barrel) left; 0 when not lit.
    pub lit: u32,
    pub dead: bool,
    pub logged_damage: f32,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bottle(parts: &[(u8, u32)]) -> Bottle {
        Bottle::of(parts.iter().copied())
    }

    fn amounts(b: &Bottle) -> Vec<(u8, u32)> {
        b.parts.iter().map(|p| (p.material, p.amount)).collect()
    }

    #[test]
    fn contents_are_sorted_merged_and_never_zero() {
        let b = bottle(&[(9, 5), (4, 0), (4, 7), (9, 3), (2, 1)]);
        assert_eq!(amounts(&b), [(2, 1), (4, 7), (9, 8)]);
        assert_eq!(b.total(), 16);
        assert_eq!(b.largest(), Some(9));
        assert_eq!(
            bottle(&[(4, 6), (2, 6)]).largest(),
            Some(2),
            "lowest index of equals"
        );
        assert!(Bottle::single(4, 0).is_empty());
        assert_eq!(Bottle::default().largest(), None);
    }

    #[test]
    fn taking_keeps_the_proportions_and_every_cell() {
        let mut b = bottle(&[(4, 300), (6, 100)]);
        let taken = b.take(8);
        assert_eq!(
            taken
                .iter()
                .map(|p| (p.material, p.amount))
                .collect::<Vec<_>>(),
            [(4, 6), (6, 2)]
        );
        assert_eq!(amounts(&b), [(4, 294), (6, 98)]);
        // The cells of a sip add up whatever the shares round to.
        let mut b = bottle(&[(1, 33), (2, 33), (3, 34)]);
        let mut total = 0;
        while !b.is_empty() {
            let before = b.total();
            let taken: u32 = b.take(7).iter().map(|p| p.amount).sum();
            assert_eq!(taken, 7.min(before));
            total += taken;
        }
        assert_eq!(total, 100);
    }

    #[test]
    fn the_cells_left_over_go_to_the_largest_remainders() {
        // 3 cells of 100/100: remainders tie, so the larger amount, then the lower index, wins.
        let mut b = bottle(&[(4, 100), (6, 100)]);
        let taken = b.take(3);
        assert_eq!(
            taken
                .iter()
                .map(|p| (p.material, p.amount))
                .collect::<Vec<_>>(),
            [(4, 2), (6, 1)]
        );
        // 1 cell out of 3:1 goes to the bigger share
        let mut b = bottle(&[(4, 75), (6, 25)]);
        assert_eq!(b.take(1)[0].material, 4);
        // Taking everything (or more) empties the bottle; taking nothing changes nothing.
        let mut b = bottle(&[(4, 5), (6, 2)]);
        assert!(b.take(0).is_empty());
        assert_eq!(b.take(99).len(), 2);
        assert!(b.is_empty());
    }

    #[test]
    fn a_complete_recipe_turns_into_the_potion_a_few_cells_at_a_time() {
        let recipe = Recipe {
            inputs: [4, 5, 6],
            potion: 29,
        };
        let mut b = bottle(&[(4, 10), (5, 3), (6, 8), (11, 5)]);
        assert_eq!(b.mix(&[recipe], 2), [(29, 6)]);
        assert_eq!(amounts(&b), [(4, 8), (5, 1), (6, 6), (11, 5), (29, 6)]);
        assert_eq!(b.mix(&[recipe], 2), [(29, 3)], "only one blood is left");
        assert_eq!(amounts(&b), [(4, 7), (6, 5), (11, 5), (29, 9)]);
        assert!(
            b.mix(&[recipe], 2).is_empty(),
            "two of three ingredients do nothing"
        );
        assert_eq!(b.total(), 26, "cell for cell");
    }
}
