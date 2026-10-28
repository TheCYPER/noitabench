# Entities, Damage, and Simple Enemy Combat

**Purpose**: Reference for damage calculations, status effects, knockback, material contact hazards, player combat mechanics (kick, levitation), and 8 MVP enemies with complete stat tables. Used by damage-handling code, projectile/explosion systems, enemy AI, and test-vector generation. Cite rule IDs (DAMAGE-R01, etc.) in code comments and test documentation.

**Frame rate**: 60 updates per second. All timers in frames (f); durations in seconds (s) where stated. **Unit conversion**: internal units × 25 = displayed (GUI_HP_MULTIPLIER); player 4.0 internal = 100 HP displayed. Speeds px/s, accelerations px/s², gravity px/s².

---

## Normative Rules

### Damage Pipeline (Per Hit)

**DAMAGE-R01: Immunity Check (First Gate)**
- If target has ANY `PROTECTION_*` or `PROTECTION_ALL` game effect that matches a **damage type flag** in this hit, the entire hit is nullified (all damage, knockback, and game effects are ignored).
- Example: Melee immunity (PROTECTION_MELEE) blocks all multitype hits that include MELEE (e.g., Melee-Bite, Melee-Ice).
- **Source**: DamageModelComponent, Immunity interactions

**DAMAGE-R02: Hitbox & Per-Type Multipliers (Applied in Order)**
1. Apply `HitboxComponent.damage_multiplier` if the hit location has one (e.g., Shotgunner head ×2.5).
2. Apply entity's `DamageModelComponent.damage_multipliers[type]` for each flagged type (default 1.0).
3. These do NOT apply to: Material damage, Fall damage, Drowning/Suffocation, Physics_Body_Damaged, or Bite damage (see DAMAGE-R07).
- **Source**: entities-damage.md §2.1-2.2, player-stats.json damage_multipliers

**DAMAGE-R03: Critical Hit Resolution (if crit_chance > 0)**
- Crit chance `c` (0..∞): if c ≤ 1, apply crit with probability c; if c > 1, always crit.
- Base crit multiplier is **5.0**. For c > 1, actual multiplier = 5.0 × c.
- Final crit bonus: `dmg_crit = base_dmg + (crit_multiplier × base_dmg - base_dmg) × (1 - crit_resist)`.
  - Simplified: `dmg_crit = base × (1 + (crit_mult - 1) × (1 - resist))`.
- Player: `crit_damage_resistance = 1.0` (immune to crit bonus; will still take base damage).
- **Source**: Damage Types wiki, damage-types.json

**DAMAGE-R04: Global Multipliers (Glass Cannon, Weakness, Stainless Armour)**
- `DAMAGE_MULTIPLIER` (Glass Cannon): ×5 on shooter's own projectiles only.
- `WEAKNESS`: ×10 to damage received (game effect on target).
- `STAINLESS_ARMOUR`: ÷2 per stack while target has no stains (no stain present = any liquid/fire stain at 0%).
- Applied after type multipliers; applied before HP subtraction.
- **Source**: perk_list.lua, magic_numbers.xml

**DAMAGE-R05: Special Cases - Non-Multiplied Damage Types**
- Material contact damage: no type multiplier applied (see DAMAGE-R11).
- Fall damage: no type multiplier (only Eväkäs/Suureväkäs and props take it).
- Drowning/Suffocation: no type multiplier (air_lack_of_damage per second).
- Physics_Body_Damaged: triggers on loss of a physics body; not subject to type multipliers.
- **Implication**: Reducing acid/lava damage via damage multipliers is impossible; only Stainless Armour and specific immunities (Ambrosia) work.
- **Source**: entities-damage.md §2.2, §4.4-4.5

**DAMAGE-R06: Explosion Damage Special Rule (Player Only)**
- Player `damage_multipliers.explosion = 0.35` (most entities default 1.0).
- This is a display/balance choice in vanilla; implement as-is for determinism.
- **Source**: player_base.xml, entities-damage.md §1.1

**DAMAGE-R07: Holy Damage Special Rule (Player & Some Enemies)**
- Player `damage_multipliers.holy = 1.5` (only non-1.0 multiplier besides explosion).
- Hurtta (zombie) `damage_multipliers.holy = 1.2`.
- Most entities no entry (default 1.0).
- **Source**: player-stats.json, enemies.json

**DAMAGE-R08: Multitype Damage (Melee-Bite, Fire-Explosion, Melee-Ice, etc.)**
- A hit can have multiple damage type flags OR'd together (bitwise).
- Immunity check (DAMAGE-R01) nullifies if ANY flagged type is protected.
- Type multipliers are applied to each flagged type independently, then summed.
- Bite damage: ignores multipliers entirely (applies only base damage); Melee immunity still blocks it.
- **DECISION-NEEDED (ED-D1)**: For MVP, support only single-type damage (simpler), or full multitype?
- **Source**: Modding: Enums wiki, damage-types.json bitflags

**DAMAGE-R09: HP Subtraction & Death**
- `entity.hp -= final_damage_amount` (internal units).
- Death at `hp <= 0` unless entity has `kill_now=false` or `wait_for_kill_flag_on_death` logic.
- On death: blood spray (count 20-40), ragdoll (velocity × 0.025), drop script (gold formula).
- **Source**: DamageModelComponent, drop_money.lua

**DAMAGE-R10: Invincibility Frames (I-Frames)**
- Field: `invincibility_frames` (countdown timer).
- Player starts with 60 frames (1 second at 60 fps).
- Vanilla does NOT refresh i-frames on hit; mods override this behavior.
- **UNVERIFIED**: Exact semantics of refresh. For determinism, assume no refresh unless explicitly modded.
- While `invincibility_frames > 0`, all damage is ignored (i-frames tick down every frame).
- **Source**: player-stats.json damage_model.invincibility_frames_initial, mod sources

**DAMAGE-R11: Material Contact Damage (Per-Pixel, Per-Frame, No Multipliers)**
- Every frame, overlapping cells of a damaging material are counted (hitbox contact area).
- Damage = sum of (material_damage_per_pixel × pixel_count) per frame.
- Minimum: entity must have ≥4 cells of material overlapping hitbox (default `material_damage_min_cell_count`), else no damage.
- **No type multipliers apply** (not multiplied by entity's damage_multipliers).
- Only mitigated by specific immunities (Ambrosia `PROTECTION_ALL`, Stainless Armour) or perk-based material-specific immunity.
- **Source**: player-stats.json materials_that_damage, entities-damage.md §4.5

**DAMAGE-R12: Knockback Calculation & Application**
- Projectile knockback: `final_kb = knockback_force × velocity_magnitude × (projectile_mass / target_mass)`.
- Explosion knockback: `final_kb = (explosion_radius × knockback_force(1)) × (1 / normalized_distance) / target_mass`.
- Applied as impulse to target's velocity; may apply `minimum_knockback_force` gate (Vault enemies use 100000 = immune).
- Ragdoll on kill: `velocity × ragdoll_force_multiplier(0.025)`, crits ×3.
- **Source**: entities-damage.md §2.4, Knockback wiki

**DAMAGE-R13: Dazed Status (KNOCKBACK Game Effect)**
- Triggered when target takes Projectile or Melee damage **while airborne** (velocity_y ≠ 0).
- Duration: 120 frames. While active: cannot levitate, movement input ignored.
- Cured by landing (velocity_y = 0) after duration expires OR by `NO_MORE_KNOCKBACK` perk (KNOCKBACK_IMMUNITY game effect).
- **Source**: status-effects.json, effect_knockback.xml

---

### Status Effects

**DAMAGE-R14: Fire (ON_FIRE Status)**
- Ignition: contact with fire/lava cell rolls `fire_probability_of_ignition` (player 1.0 = always, enemies 0.5, Stendari 0). Stains that `protect_from_fire` (Wet, Oiled when submerged, Bloody, Slimy, Toxic, Jarate) prevent ignition; fire burns the stain instead.
- Burning: damage scale `fire_damage_amount(0.2) × (1 + fire_multiplier_bonus)` internal units; the wiki states the effect as **2% of max HP per second**, with max HP clamped to >= 0.8 internal (= 20 displayed) in that formula. Whether `fire_damage_amount` is applied per frame or per second is UNVERIFIED; use the wiki's 2% of max HP per second. Creature emits fire cells (5/frame), moves 15% faster, AI panics. Extinguish on immersion in almost any liquid or Wet/Bloody/Slimy stains.
- Burning creature cannot put itself out by leaving fire; only liquid or stain extinguishes.
- Internal Fire (from ingesting lava): cannot be extinguished.
- **Source**: status-effects.json, player-stats.json fire_damage_amount, entities-damage.md §4.1

**DAMAGE-R15: Frozen (FROZEN Status)**
- Duration: 120 frames (short variant 50 frames).
- Effect: `disable_movement = 1` (no velocity input).
- **Melee hit on Frozen entity**: execute logic: if entity `hp > 0.25 × max_hp`, set `hp = 0.5 × current_hp`; else set `hp = 0`. Ignores armour/multipliers but not Melee immunity. All Melee becomes multitype Melee-Ice.
- This applies to player too (if player frozen and kicked/meleed, take 50% current HP or death if <25%).
- **Source**: status-effects.json, player-stats.json Frozen entry

**DAMAGE-R16: Electrocution (Stunned Status)**
- Triggered: stun applied when `rand[0, 1) < electricity_multiplier`.
- Duration: 40 frames per application (stacks with each hit).
- Effect: `disable_movement = 1`.
- Resistance window: 60 frames after shock ends (no further stuns during window).
- Conducts through liquids/metals (multiple entities in water take stun from one strike).
- **Source**: status-effects.json, damage-types.json electricity

**DAMAGE-R17: Wet, Oiled, Bloody, Slimy Stains (Material-Driven Status)**
- Wet: prevents ignition, extinguishes On_Fire, no i-frames from electric stun. Spell-applied 720 frames.
- Oiled: prevents ignition only while submerged; burns much longer once lit; ignites easily. No ground traction (slides). Spell-applied 720 frames.
- Bloody: prevents ignition, +5% crit chance per projectile cast. Spell-applied 720 frames.
- Slimy: prevents ignition, 15-40% movement slow. Spell-applied 720 frames.
- Stain amount normalized (1.0 = 60s); status active while stain ≥1% remaining. Drops faster while moving.
- **Source**: status-effects.json, entities-damage.md §4.2

**DAMAGE-R18: Toxic (Radioactive Status)**
- Damage: ~2% max HP per tick (wiki conflicts: 1.5s vs 1s tick cadence - **UNVERIFIED**).
- Cannot kill (floors at 5% max HP) unless target has `ALLERGY_RADIOACTIVE` (most Hiisi).
- Washed off by water or any other liquid.
- **Source**: status-effects.json, entities-damage.md §4.6

**DAMAGE-R19: Poisoned Status**
- Damage: 2% max HP per tick (same tick cadence ambiguity as Toxic).
- Cannot kill in NG (floors at 2% max HP); ×3 per NG+ cycle (NG+3 = 54% per tick = lethal).
- Poison liquid also does 0.001 internal/px/frame Material damage on top.
- **Source**: status-effects.json, entities-damage.md §4.6

---

### Knockback & Physics

**DAMAGE-R20: Projectile Collision & Hit Count**
- Default: hits once per entity in a list, dies after first collision.
- `penetrate_entities = 1`: projectile continues after hit, damages each entity **once** (tracked in `mDamagedEntities` list).
- `on_collision_die = 0` (Piercing Shot): keeps living, damages same entity every frame overlapping (limited by `damage_every_x_frames` if set, e.g., 10).
- Shooter is skipped unless `collide_with_shooter_frames` elapsed (Healing Bolt uses 4-5).
- Herd check: skip same-herd entities unless `friendly_fire = 1`.
- **Source**: entities-damage.md §3.1, ProjectileComponent docs

**DAMAGE-R21: Explosion Terrain Carving (Ray-Based)**
- Rays cast from explosion center spending `ray_energy` on each cell's hardness-HP.
- Cells with durability > `max_durability_to_destroy` are never destroyed (wiki thresholds: sand 4, concrete 8, steel 11-13; the clone uses the game-data values, in which `concrete_static` has durability 0: materials-reactions.md MAT-R12, D7).
- Crater removes: solids, liquids (unless `hole_destroy_liquid = 0`), physics_dynamic (if `hole_destroy_physics_dynamic = 1`).
- Fire cell conversion: `create_cell_probability` (Fireball 100%, Bomb 40%, Spark Bolt 0).
- Knockback effect: radius-scaled, inverse-distance-normalized.
- **Source**: entities-damage.md §3.2, ConfigExplosion docs

---

## Key Numbers (Constants & Units)

| Constant | Value | Units | Notes |
|---|---|---|---|
| **HP & Damage Display** | | | |
| `GUI_HP_MULTIPLIER` | 25 | ratio | internal × 25 = displayed |
| Player max HP (displayed) | 100 | HP | internal 4.0 |
| Player max HP (internal) | 4.0 | internal | stored value |
| Suffocation damage | 15 | HP/s | `air_lack_of_damage = 0.6` internal/s |
| **Movement (Player)** | | | |
| Gravity | 350 | px/s² | pixel_gravity; faster levitation stacks ×1.4 per level, cap 588 |
| Walk velocity (max x) | 57 | px/s | `velocity_max_x` clamp; ~0.95 px/frame |
| Fall velocity (max y) | 350 | px/s | terminal fall speed downward |
| Levitation velocity (up) | 95 | px/s | fly_speed_max_up |
| Levitation velocity (down) | 85 | px/s | fly_speed_max_down |
| Levitation horizontal | 52 | px/s | fly_velocity_x |
| **Levitation Meter (Player)** | | | |
| Max levitation time | 3.0 | s | fly_time_max; drains 1/s while held airborne |
| Air recharge (ground) | 6.0 | /s | full refill in 0.5s on solid ground |
| Air recharge (airborne) | 0.4 | /s | only after `flying_in_air_wait_frames = 38` (anti-tap) |
| Anti-tap delay | 38 | f | must be airborne this long before recharge starts |
| Recharge removal on fly-press | 8 | f | frames of charge removed per levitate key press (second anti-tap) |
| **Jump (Player)** | | | |
| Jump velocity (y) | -95 | px/s | upward impulse; apex ~13 px (v²/2g = 95²/700) |
| Jump velocity (x) | 56 | px/s | forward/backward impulse |
| Jump input buffer | 2 | f | frames of input buffering |
| **Kick (Player)** | | | |
| Kick radius | 3 | px | collision sphere radius |
| Kick damage (displayed) | 1 | HP | `kick_damage = 0.04` internal |
| Kick knockback | 3 | units | baseline knockback value |
| Parry window | 3 | f | entity component says 3f; wiki says 4f starting frame 20 |
| **Player Damage Multipliers** | | | |
| Explosion | 0.35 | × | unique to player; most entities 1.0 |
| Holy | 1.5 | × | player only (Hurtta zombies also 1.2 to holy) |
| All others | 1.0 | × | melee, projectile, fire, electricity, etc. |
| Critical resistance | 1.0 | ratio | player immune to crit bonus; still takes base |
| **Hitbox & Collision (Player)** | | | |
| Hitbox (projectile target) | 6 × 16 | px | min_x -3, max_x 3, min_y -12, max_y 4 (crouched min_y -8.5) |
| Collision AABB (world) | 4 × 6.6 | px | min_x -2, max_x 2, min_y -4.5, max_y 2.1 |
| Buoyancy check offset | -7 | px (y) | checked around chest for submerged detection |
| Max contact area (submerged) | 85 | px | material damage roll caps here |
| Material damage minimum | 4 | cells | must have ≥4 cells overlapping to take damage |
| Crush threshold | 6 | cells | stuck in solid this long triggers "Unstuck" UI |
| **Crit Multipliers & Formulas** | | | |
| Base crit multiplier | 5.0 | × | damage boost if crits |
| Crit chance formula | `1 + min(c,1) × (5×max(1,c) - 1) × (1-resist)` | ratio | c = crit_chance, resist = crit_damage_resistance |
| Glass Cannon multiplier | 5.0 | × | on shooter's own projectiles (perk effect) |
| Weakness multiplier | 10.0 | × | damage taken (game effect on target) |
| Stainless Armour | ÷2^n | × | per stack, only while stainless (0% stain) |
| **Status Effect Durations** | | | |
| Frozen | 120 | f | 2 seconds; short variant 50f |
| Electrocution (Stunned) | 40 | f / hit | per application; stacks with hits |
| Electrocution resistance | 60 | f | window after shock ends (no stun during) |
| Dazed (Knockback) | 120 | f | 2 seconds; triggered by damage while airborne |
| Fire (spell-applied) | 720 | f | 12 seconds; game effect `ON_FIRE` |
| Wet/Oiled/Bloody (spell) | 720 | f | 12 seconds; protects_from_fire |
| Slimy (spell) | 720 | f | 12 seconds |
| Regeneration (spell) | 150 | f | 2.5 seconds; 10% max HP per second |
| Berserk (spell) | 720 | f | 12 seconds; ×2 damage, ×2 radius |
| **Material Contact Damage (Per-Pixel Per-Frame, No Multipliers)** | | | |
| Acid | 0.005 | internal/px/f | 7.5 HP/s per pixel; 637.5 HP/s fully submerged (85 px) |
| Lava | 0.003 | internal/px/f | 4.5 HP/s per pixel; 382.5 HP/s fully submerged (+ On Fire) |
| Poison | 0.001 | internal/px/f | 1.5 HP/s per pixel; 127.5 HP/s fully submerged |
| Freezing Liquid | 0.0009 | internal/px/f | 1.35 HP/s per pixel; 114.75 HP/s fully submerged |
| Cursed Rock | 0.005 | internal/px/f | same as acid; 637.5 HP/s fully submerged |
| **Projectile Defaults** | | | |
| Spawn distance | 7-25 | px | from wand tip |
| Speed (typical) | 60-850 | px/s | Spark Bolt 750-850; magic spells 60 default |
| Gravity | 200-400 | px/s² | Spark Bolt 200; default 400 |
| Air friction | 0.55-1.7 | (per frame) | per-frame `v -= dt × v × friction` |
| Terminal velocity | 1000 | px/s | for most; Lightning Bolt 61440 (effectively no cap) |
| Mass | 0.05 | units | default |
| Lifetime | 40-750+ | f | random ±randomness, -1 = infinite |
| **Explosion Defaults** | | | |
| Radius (typical) | 15-60 | px | spell 20; Bomb 60; Nuke 250 |
| Damage (typical) | 2-10 | internal | 50-250 displayed; flat to all mortals in radius |
| Ray energy (terrain) | 20k-6.7M | units | Bomb 6M; Nuke 6.7M; Spark Bolt 400k |
| Max durability (destroy cap) | 8-12 | points | material hardness must be ≤ this to destroy |
| **Knockback** | | | |
| Projectile formula | `kb_force × velocity × (proj_mass / target_mass)` | units | see DAMAGE-R12 |
| Explosion formula | `(radius × kb_force) × (1 / distance) / target_mass` | units | radius-scaled, inverse-distance |
| Melee impulse (AI) | (1, 0.25) | vector | x, y direction; scaled by multiplier ~50 |
| **Enemy Base Defaults** | | | |
| Base gravity (enemies) | 600 | px/s² | faster fall than player |
| Base melee damage | 5-10 | HP | 0.2-0.4 internal |
| Base melee frequency | 20 | f | frames between melee attempts |
| Base melee reach | 10 | px | max distance to melee |
| Base dash damage | 6.25 | HP | 0.25 internal |
| Base dash speed | 200 | px/s | lunging speed |
| Base dash frequency | 120 | f | frames between dashes |
| Base detection | 300×300 | px | creature detection range |
| Base escape if damaged | 30% | prob | turn and flee if hit |
| Attack if damaged | 100% | prob | always retaliate (unless `dont_counter_attack_own_herd`) |
| Air capacity (enemies) | 5 | s | before suffocation damage (player 7s) |
| Aggressiveness roll | [1, 100] | random | per individual at spawn; attacks if > faction relation |

---

## Data Files & Loading

| File | Records | Key Fields | Purpose |
|---|---|---|---|
| `player-stats.json` | 1 | hp_internal, hp_displayed, movement (gravity, velocity clamps, fly times), levitation, damage_model (fire, air, materials), kick, hitbox, collision | Player entity constants and damage model; single authoritative source for all player numbers |
| `enemies.json` | 9 (8 MVP + details) | name, id, hp_internal/displayed, herd, attacks[], damage_multipliers, mass, movement params, detection, special flags (ALLERGY_RADIOACTIVE, picks_up_wands, can_fly) | Enemy definitions for MVP; each entry is loadable as-is; use `enemies[].attacks[].damage_internal/displayed` for stat reference |
| `damage-types.json` | 15 multiplier keys | bitflags (DAMAGE_MELEE=1, DAMAGE_PROJECTILE=2, etc.), multiplier_keys, player_multipliers, immunity_game_effects | Damage type registry; bitflags used in code; multiplier keys (e.g., "explosion", "holy") match DamageModelComponent entries |
| `status-effects.json` | 20 statuses | id, entity (effect XML name), frames (duration), harmful flag, effect description, sources | Status effect definitions; `frames` is GameEffectComponent duration; stain-driven statuses persist while stain remains (see DAMAGE-R17) |
| `factions-relations.json` | 28×28 table | relations[from_faction][to_faction] (0..100) | Faction relation matrix; creature attacks faction F when `aggressiveness > relations[creature_faction][F]` |

**Loading Strategy:**
- Load all JSON files at startup; cache in memory.
- Player entity: construct from `player-stats.json` (1 source of truth).
- Enemy entities: iterate `enemies.json[]`, construct DamageModel and attack lists.
- Projectile/explosion: read `damage-types.json` to validate type flags; apply multipliers from entity's damage_model table.
- Faction AI: lookup in `factions-relations.json[attacker_herd][target_herd]` each frame when evaluating target priority.

---

## Worked Examples & Test Vectors

### Example 1: Player Takes Explosion Damage (No Immunity)
```
Source: Stendari fireball (explosion 50 HP, radius 20 px)
Target: Player at 50 HP current, max 100, no stains, no effects
Distance from center: 10 px (within radius)

Step 1: Immunity check → none → proceed
Step 2: Hitbox multiplier → default 1.0 (no special hitbox) → 50 HP
Step 3: Type multiplier (explosion) → player_multipliers.explosion = 0.35 → 50 × 0.35 = 17.5 HP
Step 4: Crit → no crit (explosion is not crit-able) → 17.5 HP
Step 5: Global effects → no Glass Cannon, Weakness, Stainless Armour → 17.5 HP
Step 6: HP subtraction → 50 - 17.5 = 32.5 HP

Result: Player takes 17.5 HP damage (17 or 18 displayed depending on rounding).
```

### Example 2: Melee Critical Hit with Crit Resistance
```
Source: Magic Arrow (damage 10 HP, crit_chance 5% = 0.05)
Target: Shotgunner (45 HP, crit_damage_resistance 0 default = normal crits)

Step 1: Immunity check → none → proceed
Step 2: Hitbox multiplier → default 1.0 → 10 HP
Step 3: Type multiplier (projectile) → 1.0 (no modifier) → 10 HP
Step 4: Crit?
  - rand[0,1) < 0.05? → assume yes for this example
  - Crit multiplier = 5.0
  - Resistance = 0 (can be crit)
  - Damage bonus = (5.0 - 1.0) × 10 × (1 - 0) = 40 HP
  - Final damage = 10 + 40 = 50 HP
Step 5: Global effects → none → 50 HP
Step 6: HP subtraction → 45 - 50 = -5 (dead)

Result: Shotgunner dies to critical hit.

If crit missed (95% chance): 10 HP only, Shotgunner survives at 35 HP.
```

### Example 3: Frozen Enemy Execution by Melee
```
Source: Kick (damage 1 HP Melee) on Frozen target
Target: Hämis (2.75 HP, currently at 1.5 HP due to prior damage) in Frozen state (120 frames)

Step 1: Immunity check → no melee immunity → proceed
Step 2: Hitbox multiplier → 1.0 → 1 HP
Step 3: Type multiplier (melee) → 1.0 → 1 HP
Step 4: Crit → no (melee from kick doesn't roll crit) → 1 HP
Step 5: Global effects → none → 1 HP
Step 6: **Frozen execution logic** (DAMAGE-R15)
  - Current HP 1.5, max 2.75
  - 1.5 > 0.25 × 2.75 (0.6875)? → yes
  - Execute: new_hp = 0.5 × 1.5 = 0.75 HP
  - Melee hit becomes Melee-Ice

Result: Hämis takes 0.75 HP (1.5 → 0.75) but does NOT die. If current HP was 1.0, would die (≤ 25% max).
```

### Example 4: Material Damage Accumulation (Acid Contact)
```
Source: Player submerged in acid (contact area ~80 px of 85 max)
Acid: 0.005 internal/px/frame = 7.5 HP/s per pixel
Duration: 1 second (60 frames)

Step 1: Count acid cells overlapping hitbox → 80 px
Step 2: Check minimum → 80 ≥ 4 → proceed
Step 3: Damage per frame = 80 × 0.005 = 0.4 internal = 10 HP
Step 4: Damage over 1 second = 10 HP/frame × 60 frames = 600 HP (lethal; player dies)

Result: Player dies in 10 frames (~0.17 s): 100 HP / 10 HP per frame, assuming no stain protection (matches materials-reactions.md MV-18).

With Wet stain (protects_from_fire, but NOT acid): no mitigation; still lethal.
With Ambrosia (PROTECTION_ALL): immune; no damage.
```

### Example 5: Knockback from Sniper Bullet
```
Source: Snipuhiisi fires (bullet damage 25 HP, knockback_force 4.0, speed 1550 px/s at impact)
Target: Player (mass 1.0)
Projectile: mass 0.05

Formula: kb = knockback_force × velocity × (proj_mass / target_mass)
        = 4.0 × 1550 × (0.05 / 1.0)
        = 4.0 × 1550 × 0.05
        = 310 units of knockback

Interpretation: ~300 units of impulse applied to player's velocity (direction toward shooter).
If player was stationary: pushed back ~300 px/s (5 px/frame for 60 frames until drag kills velocity).
If player was flying: knockback may exceed velocity clamps; triggers Dazed (KNOCKBACK) status.

Result: Player gets ~310 units knockback (high enough to interrupt levitation if airborne).
```

---

## Pitfalls & Common Misreadings

1. **Explosion Multiplier is 0.35, Not 1.0**: Player takes only 35% of explosion damage; this is intentional for balance. Most entities default 1.0. Do NOT override the player's multiplier when testing.

2. **Holy Damage is 1.5x (Buff, Not Debuff)**: Player takes 50% MORE holy damage (not less). Holy Lance is weak vs other spells but strong vs player. Reverse the intuition!

3. **Material Damage Ignores ALL Type Multipliers**: Acid always deals 0.005/px/f regardless of target's `damage_multipliers.acid`. Only Ambrosia (PROTECTION_ALL) and Stainless Armour (÷2 while stainless) mitigate it. Fire Immunity does NOT stop lava contact damage.

4. **Crit Resist is NOT a Damage Reduction**: Crit_damage_resistance=1.0 (player) does NOT mean "take 100% damage"; it means "cancel 100% of the crit bonus". Player still takes base damage, just never the ×5 boost. Formula: `dmg_final = base + (crit_bonus × base) × (1 - resist)`. With resist=1.0: `dmg_final = base + 0 = base`.

5. **Frozen Execution Applies to Melee From Any Source**: Kicks, sword strikes, enemy melee—any Melee-type hit on a Frozen target triggers the execute logic. This is often a surprise mechanic used for trick kills.

6. **Status Duration: Frames vs. Stains**: Spell-applied statuses last N frames (e.g., Water spell 720f). Stain-driven statuses persist while stain amount ≥1% (normalized 1.0=60s). Stains drop faster while moving. A Water spell can keep status active even if the stain was washed off, and vice versa.

7. **Knockback Only Triggers Dazed If Airborne**: Projectile or melee damage on a grounded entity does NOT apply Dazed. Only damage taken while `velocity_y ≠ 0` (flying, falling, jumping) applies KNOCKBACK game effect. This prevents easy interruption of ground-based gameplay.

8. **Multitype Damage: Immunity Nullifies ALL Hits If ANY Type Matches**: Melee-Bite hits a target with Melee immunity? The entire hit (both Melee AND Bite) is nullified. Not partial; not just Melee. Check immunity flags with bitwise AND.

9. **Fall Damage Only for Specific Entities**: Eväkäs (fish) and props take fall damage. Player and all other creatures explicitly have `falling_damages = 0`. Do NOT implement a general fall damage system for all entities.

10. **Aggressiveness Roll is Per-Individual at Spawn**: Each creature's aggressiveness is rolled once at spawn (random in [min, max]), NOT re-rolled each frame. This determines which factions it will attack (if aggressiveness > relation value). Store this as an instance variable.

---

## MVP Simplifications

### DECISION-NEEDED ED-D1: Multitype Damage
**Current Status**: Vanilla supports Melee-Bite, Melee-Ice, Fire-Explosion, etc. via bitflags.
**MVP Simplification**: Support only single-type damage for first iteration (e.g., Melee, Projectile, Explosion, Fire, Ice). Multitype hits become single-type for simplicity.
**Trade-off**: Loses some mechanic nuance (e.g., Melee immunity still blocks multitype, frozen->melee-ice interaction), but simplifies damage pipeline.
**Recommendation**: Defer multitype to post-MVP. Implement single-type with clear flag for later extension.

### DECISION-NEEDED ED-D2: Projectile Piercing
**Current Status**: Penetrate-entities flag allows projectile to hit multiple entities once each; `damage_every_x_frames` for pierce-damage-per-frame.
**MVP Simplification**: Projectiles hit once, die (no penetrate). Pierce spells become single-hit.
**Trade-off**: Loses Piercing Shot, some spell tactics, multicast behavior.
**Recommendation**: Start single-hit; add penetration post-MVP if benchmarks need it.
**Conflict (found in KB finalisation)**: the MVP-50 of spells.md needs penetration (`LIGHTNING` and `LUMINOUS_DRILL` pierce, `PIERCING_SHOT` sets `on_collision_die = 0`, `DELAYED_SPELL` penetrates entities). Keep this decision open and see decisions-needed.md DN-ENT-02 (recommended default: implement the once-per-entity hit list now).

### Simple Status Effects (Not Stain-Driven)
**Current Status**: Vanilla has full stain system (persistent, drops over time, affects stain-driven effects).
**MVP Simplification**: Statuses are applied as game effects with fixed durations (e.g., Wet 720 frames from Water spell). No passive stain persistence—only spell-applied durations.
**Trade-off**: Loses depth of stain interactions (e.g., standing in water doesn't automatically apply Wet over time; only spells do). Simplifies state management.
**Recommendation**: Sufficient for MVP combat; defer stain physics to post-MVP.

### 8 Enemies Only (No Variants)
**Included**: Hämis, Hurtta, Haulikkohiisi, Snipuhiisi, Hämähäkki, Stendari, Nelikoipi, Konna.
**Excluded**: Weak variants (Heikkohurtta, Heikko shotgunner), other Lukki variants (Pikku, larger), Vault Sniper (155 HP), Lepakko, Rotta, Eväkäs.
**Rationale**: 8 core enemies cover melee (Hämis, Hurtta, Konna), ranged (Shotgunner, Sniper, Stendari), tank (Hämähäkki, id `lukki`), passive (Nelikoipi, id `deer`). Variants are cosmetic for MVP.

### No Faction Relation Modulation
**Current Status**: More Love (+25 to all), More Hatred (-25 to all) perks.
**MVP Simplification**: Fixed factions-relations.json entries; no dynamic perk-based modulation.
**Trade-off**: Cannot test perk effects on aggression.
**Recommendation**: Sufficient for MVP enemy AI; perks deferred.

### Levitation Anti-Tap Delays Included
**Included**: 38-frame air delay before recharge starts, 8-frame recharge removal on fly-press.
**Rationale**: Essential for determinism and AI difficulty; not optional.

---

## Open Questions

1. **Toxic/Poisoned Tick Cadence (UNVERIFIED)**: Wiki Damage Types page says "per 1.5 s"; Status Effects page says "per second". Which is authoritative? Reference: https://noita.wiki.gg/wiki/Damage_Types vs https://noita.wiki.gg/wiki/Status_Effects. **Action**: Verify in vanilla log or defer to 1s (conservative; more lethal).

2. **Invincibility Frame Refresh Semantics**: Vanilla does NOT refresh i-frames on hit; only mods override. Should the clone follow vanilla (no refresh) or mod behavior (refresh to 60 on each hit)? This affects difficulty tuning. **Action**: Implement vanilla semantics (no refresh); document for AI tuning.

3. **Stain Drop Formula Details**: Constants `VERLET_STAIN_DROP_CHANCE_DIV=200`, `GAMEEFFECT_STAINS_DROP_FASTER_DROP_CHANCE_MULTIPLIER=10` exist but quantitative formula is unclear. Does stain drop = base chance × (velocity / drop_div)? **Action**: Defer to post-MVP; simplify to fixed drop rate for MVP.

4. **Projectile Crit Resolution Timing**: When do crits apply relative to explosion generation? If a projectile with crit_chance 50% explodes, does the explosion inherit the crit bonus or roll independently? **Action**: Assume independent roll for each; document assumption.

5. **Multitype Damage Order**: When resolving Melee-Bite multitype, should type multipliers be summed or averaged? Bitflags suggest OR (both flags active), so sum each multiplier separately. **Action**: Sum independently; verify with test vector.

---

## Sources

- https://noita.wiki.gg/wiki/Minä (player stats, movement)
- https://noita.wiki.gg/wiki/Damage_Types (damage type registry, multipliers, global effects)
- https://noita.wiki.gg/wiki/Critical_hit (crit formula, chances)
- https://noita.wiki.gg/wiki/Status_Effects (status durations, effects)
- https://noita.wiki.gg/wiki/Knockback (knockback calculation)
- https://noita.wiki.gg/wiki/Frozen (execution logic)
- https://noita.wiki.gg/wiki/Creatures (enemy base defaults, AI)
- https://noita.wiki.gg/wiki/Factions/Relations (faction relation matrix)
- https://noita.wiki.gg/wiki/Documentation:_DamageModelComponent (damage model fields)
- https://noita.wiki.gg/wiki/Documentation:_ProjectileComponent (projectile fields)
- https://noita.wiki.gg/wiki/Documentation:_ConfigExplosion (explosion fields)
- https://github.com/NathanSnail/noitadata (vanilla beta-branch data dump, all entity XML files)
- ./.trellis/tasks/10-16-noita-cogbench/research/entities-damage.md (synthesis)
- ./.trellis/tasks/10-16-noita-cogbench/research/player-stats.json (player constants)
- ./.trellis/tasks/10-16-noita-cogbench/research/damage-types.json (damage type registry)
- ./.trellis/tasks/10-16-noita-cogbench/research/enemies.json (enemy stats and moves)
- ./.trellis/tasks/10-16-noita-cogbench/research/status-effects.json (status definitions)
- ./.trellis/tasks/10-16-noita-cogbench/research/factions-relations.json (faction relations)
