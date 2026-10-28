# Noita: Player, Enemies, Damage and Projectile Rules

Research notes for implementing a player controller, simple enemies and damage resolution in the Noita-like core. Figures come from (a) noita.wiki.gg pages/Cargo tables and (b) the vanilla data files (`data/entities/*.xml`, `data/scripts/*.lua`, `data/magic_numbers.xml`) mirrored in the NathanSnail/noitadata GitHub repository (beta-branch dump; every HP/damage number in it matched the wiki, so it is treated as vanilla). Raw copies of everything used are under `research/raw/` (wikitext) and `research/raw/noitadata/` (game data). Anything not confirmed by one of these sources is marked **UNVERIFIED**.

Companion machine-readable files: `player-stats.json`, `enemies.json`, `damage-types.json`, `status-effects.json`, `factions-relations.json`, `raw/cargo_enemies.json` (all 203 wiki enemy rows), `raw/cargo_attacks.json`, `raw/cargo_perks.json`.

## 0. Units, frame rate and the x25 rule

| Thing | Value |
|---|---|
| Simulation rate | 60 updates per second; all timers are integer **frames** (`lifetime`, `frames_between`, effect `frames`). Scripts sometimes use `dt = 1/60` (`0.016666567` in `VelocityComponent` air-friction formula). |
| Length | 1 world pixel = 1 material cell. Speeds are **px/s**, accelerations **px/s^2** (gravity values like `pixel_gravity="350"`). Terminal velocity for projectiles 1000 px/s (16.67 px/frame). |
| HP / damage scale | Engine stores HP and damage in *internal* units; the UI multiplies by **`GUI_HP_MULTIPLIER = 25`**. Player `hp="4"` = 100 HP; Spark Bolt `damage="0.12"` = 3; Nuke `damage="10"` = 250; kick `kick_damage="0.04"` = 1. All tables below give displayed values unless marked *internal*. |
| Virtual resolution | 427 x 242 px screen. |
| Determinism notes (benchmark) | Melee damage is `rand[min,max]` per hit; dash/ranged use per-individual `aggressiveness = rand[min,max]`; projectile spread `direction_random_rad`, speed `rand[speed_min,speed_max]`, lifetime `+-lifetime_randomness`; explosions trace randomised rays (`RANDOMIZE_LARGE_EXPLOSION_RAYS=1`); scripts seed with `SetRandomSeed(x + GameGetFrameNum(), y)`. A clone must expose a seedable RNG for every one of these. |

## 1. Player (Minä)

Entity: `data/entities/player.xml` -> `data/entities/player_base.xml`. Tags `mortal,human,hittable,peasant,prey,player_unit,teleportable`; herd `player`.

### 1.1 Core stats

| Stat | Value | Source |
|---|---|---|
| Max HP | 100 (internal 4.0). +25 per Extra Max HP pickup (Large: +50; Holy Mountain full-heal also +10 max) | player_base.xml, Healing |
| Death | at HP <= 0, permanent (Extra Life perk aside) | Healing |
| Damage multipliers | explosion **0.35**, holy **1.5**, everything else 1.0 | player_base.xml, Minä |
| Critical resistance | `critical_damage_resistance="1"` -> player can never be crit | player_base.xml, Critical hit |
| Kinetic (physics object) damage | `physics_objects_damage="0"` -> immune unless polymorphed | Damage Types |
| Fall damage | `falling_damages="0"` -> **none** (see 4.4 for the formula the engine would use) | player_base.xml |
| Ignition | `fire_probability_of_ignition="1"` (always ignites on fire contact unless a fire-protecting stain is present); `fire_damage_amount="0.2"` | player_base.xml |
| Air | `air_in_lungs=7` s; after it hits 0, suffocation damage `air_lack_of_damage=0.6` internal/s = **15 HP/s**; refills when not submerged | player_base.xml, Damage Types |
| Invincibility | `invincibility_frames="60"` is a countdown field (damage ignored while > 0). Vanilla only starts it at 60; it is *not* refreshed on hit (mods add that) - **UNVERIFIED inference** | DamageModelComponent doc, mod sources |
| Hitbox (projectile/explosion target) | AABB x -3..3, y -12..4 (6 x 16 px). Crouched: y -8.5..4 | player_base.xml |
| Collision box (world) | `CharacterDataComponent` AABB x -2..2, y -4.5..2.1; `climb_over_y=4` (steps up to 4-px ledges automatically); `check_collision_max_size` 4x4; `platforming_type=2`; crush threshold 6 | player_base.xml |
| Gold | `MaterialSuckerComponent suck_gold=1 suck_health=1` - touching a nugget collects the whole nugget | player_base.xml |
| Camera/aim | reticle 60 px from character, camera lead up to 50 px toward aim | player_base.xml |

### 1.2 Movement constants (`CharacterPlatformingComponent`, px and px/s)

| Field | Player | Generic enemy default (`base_enemy_basic`) | Meaning |
|---|---|---|---|
| `pixel_gravity` | **350** | 600 | downward acceleration px/s^2 (Faster Levitation x1.4 per stack, capped 588; Gas Blood x0.75) |
| `velocity_min_x / max_x` | -57 / 57 | -50 / 50 | hard clamp on horizontal speed (walk tops out ~57 px/s ~ 0.95 px/frame) |
| `velocity_min_y / max_y` | -200 / 350 | -500 / 500 | clamp on vertical speed (350 px/s terminal fall) |
| `run_velocity` | 154 | 12 (Hämis 25, Hurtta 18, Shotgunner 20, Sniper 24, Stendari 18, Deer 30, Frog 0) | ground drive value; interaction with `accel_x` is engine-internal (**UNVERIFIED** mapping) |
| `accel_x` / `accel_x_air` | 0.15 / 0.1 (default) | 0.3 / 0.1 | acceleration factors |
| `jump_velocity_y` / `jump_velocity_x` | **-95** / 56 | -8 .. -140 | jump impulse; apex ~ v^2/2g = 95^2/700 ~ 13 px |
| `jump_keydown_buffer` | 2 frames | 2 | input buffering |
| `fly_velocity_x` | 52 | 28 | horizontal speed while levitating |
| `fly_speed_max_up` / `max_down` | **95** / 85 | 90 / 90 | levitation vertical speed clamps |
| `fly_speed_change_spd` | 0.25 | 1 | throttle ramp |
| swim | idle buoyancy 1.2, down 0.7, up 0.9, `swim_drag` 0.95, extra horizontal drag 0.9 (velocity *= drag each frame in liquid) | same | Breathless perk: x0.6 / x0.2 / x0.2 buoyancy, drag x1.2 |
| `turning_buffer` | 0.5 | 0.1 | mouse-look turn hysteresis |

Controls (default): A/D move, W/Space levitate, S eat (while submerged in food), F kick, LMB fire, RMB throw, E interact, 1-8 slots. "Unstuck": press Left+Levitate+Right together to carve out terrain around the player.

### 1.3 Levitation (jetpack) meter (`CharacterDataComponent`)

| Field | Value | Notes |
|---|---|---|
| `fly_time_max` | **3.0 s** | levitation energy (`mFlyingTimeLeft`, drains 1/s while the fly key is held and the player is airborne) |
| `fly_recharge_spd` (air) | 0.4 /s | only after `flying_in_air_wait_frames = 38` frames without flying (anti "tap-tap" cheese) |
| `fly_recharge_spd_ground` | 6 /s | full refill in 0.5 s on solid ground |
| `flying_recharge_removal_frames` | 8 | frames of charge removed on fly press (second anti-tap measure) |
| Strong Levitation (HOVER_BOOST) | max = 2^n + 2^(n-1) s for n stacks (3, 6, 12 ...); recharge takes correspondingly longer | angry_levitation_death.lua, wiki |
| Faster Levitation | +75 % levitation speed per stack; also `pixel_gravity *= 1.4` (cap 588 = 1.68x) | perk_list.lua, wiki |
| Rage-fueled Levitation | +1.2 s (40 % of default) per creature death within 240 px | wiki, script |
| Dazed | taking Projectile/Melee damage while flying applies KNOCKBACK (120 frames): no levitation, no movement input. No More Knockback = `KNOCKBACK_IMMUNITY` | Status Effects, effect_knockback.xml |
| Fast movement ("meteoring") | needs an impulse at least every 5 frames (recoil/teleport bolt); after 60-150 frames fast, impacts cause explosions (cooldown 90 frames, ground ray 30 px) | Minä, magic numbers |

### 1.4 Kick and parry

| Field | Default | With Never Skip Leg Day (per stack) |
|---|---|---|
| `kick_radius` | 3 px | - |
| `kick_damage` | 0.04 internal = **1 HP** Melee | +2.4 -> 61 HP |
| `kick_knockback` | 3 | +250 (~80x) |
| `max_force` (props) / `player_kickforce` | 12 / 28 | x1.7 each |
| `telekinesis_throw_speed` | 25 | +25 |
| Magic numbers | `PLAYER_KICK_FORCE=50`, `PLAYER_KICK_VERLET_RADIUS=3`, `PLAYER_KICK_VERLET_FORCE=4`, `PLAYER_KICK_FRAMES_IGNORE_COLLISION=35` | - |
| Parry | A kick grants `MELEE_COUNTER` (entity: 3 frames; wiki: 4 frames starting at kick frame 20). Incoming Melee (incl. multitype melee, tongues, tentacles) is reflected to the attacker as pure Melee and "BLOCK" is shown. | Parrying |
| Kicking a Frozen enemy | executes it (see Frozen) | Status Effects |
| Kicked hard props | kill enemies they hit (trick kill, 2x gold) | How to Play |

### 1.5 Player vs. pixel world

* Collision is per-cell against the `CharacterDataComponent` AABB (4 x 6.6 px); solids (static/powder cells with collision) block, liquids/gases do not. Ledges <= `climb_over_y` (4 px) are stepped over automatically; 1-2 px obstructions are climbed.
* `PlayerCollisionComponent` counts frames stuck in solid (`stuck_in_ground_counter`); crush threshold 6 cells. When stuck, the game offers the Unstuck key combo which explodes/warps nearby cells (powders get warped upward into a pile).
* Buoyancy is sampled at `buoyancy_check_offset_y=-7` (around the chest): submerged -> swim model (drag/buoyancy coefficients above). Liquids push the character with `liquid_velocity_coeff=9` (default).
* Material contact damage: every frame, cells of a damaging material overlapping the hitbox are counted; damage = sum(per-pixel value) per frame (see 4.5); ignored if fewer than `material_damage_min_cell_count=4` cells (engine default). Max contact area is 85 px when fully submerged.
* Breathing: any liquid, gas (smoke/flammable gas) or solid burying the head consumes air; `air_in_lungs` 7 s.
* Oiled stain narrows the effective hitbox slightly (wiki, amount unquantified).

## 2. Damage model

### 2.1 Pipeline (per hit)

1. Source produces `(amount_by_type, damage_type_bitflags, knockback, position, responsible_entity)`; Lua API `EntityInflictDamage(entity, amount, damage_type, description, ragdoll_fx, impulse_x, impulse_y, responsible, world_x, world_y, knockback_force)`.
2. Immunity game effects on the target (`PROTECTION_*`, `PROTECTION_ALL`) nullify the whole hit if **any** flagged type is protected (multitype rule).
3. Hitbox multiplier (`HitboxComponent.damage_multiplier`, e.g. Hiisi head 2.5x).
4. Per-type multiplier from `DamageModelComponent.damage_multipliers` (`ConfigDamagesByType`, default 1.0 each; negative heals - Ukko electricity = -1). Material, multitype, fall and suffocation damage ignore these multipliers.
5. Critical hit: `chance` and `damage_multiplier` already resolved on the projectile; applied unless `critical_damage_resistance` (0..1) cancels the bonus part: `dmg = base + (crit_dmg - base) * (1 - resist)`.
6. Global effects: Glass Cannon/`DAMAGE_MULTIPLIER` (x5 on the shooter's projectiles), `WEAKNESS` on target x10, `STAINLESS_ARMOUR` on target /2^n (only while no stain), Weakening curses set the type multiplier to 1.25 (Weakened status sets listed types to 1.2).
7. HP -= dmg (internal units). Death at <= 0 unless `kill_now`/`wait_for_kill_flag_on_death` logic; blood spray (`DAMAGE_BLOOD_AMOUNT_MIN/MAX` 20/40), ragdoll, drops, `script_death` (gold).
8. Side effects: knockback impulse, `damage_game_effect_entities` (e.g. electrocution, on-fire), Dazed if target was flying, AI reaction (`escape_if_damaged_probability`, `attack_if_damaged_probability`).

### 2.2 The 21 damage types

Bitflags (`DAMAGE_TYPES` enum; multitype hits OR several): NONE 0, MELEE 1, PROJECTILE 2, EXPLOSION 4, BITE 8, FIRE 16, MATERIAL 32, FALL 64, ELECTRICITY 128, DROWNING 256, PHYSICS_BODY_DAMAGED 512, DRILL 1024, SLICE 2048, ICE 4096, HEALING 8192, PHYSICS_HIT 16384; RADIOACTIVE, POISON, MATERIAL_WITH_FLASH, OVEREATING, CURSE, HOLY exist as later bits (values **UNVERIFIED**).

| Type | Multiplier key | Player mult | Typical source | Rules |
|---|---|---|---|---|
| Melee | melee | 1.0 | kicks, enemy melee/dash, tongues | Executes Frozen targets; parryable; Melee immunity blocks all multitype hits |
| Projectile | projectile | 1.0 | most spells, bullets | `PROTECTION_PROJECTILE` blocks; Weakening Curse +0.25 |
| Explosion | explosion | **0.35** | bombs, fireballs | radius-based (3.2); `PROTECTION_EXPLOSION` also blocks knockback/stun |
| Fire | fire | 1.0 | burning, Meteor | DOT while On Fire (3.1); `PROTECTION_FIRE` |
| Electricity | electricity | 1.0 | Ball Lightning, Ukko | stuns (`rand < electricity mult`), conducts through liquids/metals |
| Drill | drill | 1.0 | Digging Bolt | most enemies 0.7 |
| Slice | slice | 1.0 | Disc, Energy Sphere | - |
| Ice | ice | 1.0 | Freeze Charge (+5), Iceball | Frozen is applied separately; `PROTECTION_FREEZE` blocks damage+freeze, `STUN_PROTECTION_FREEZE` only freeze |
| Healing | healing | 1.0 | Healing Bolt (-8.75 i.e. heals) | always <= 0; needs friendly fire to hit self; crits can't boost it on the player |
| Radioactive (Toxic) | radioactive | 1.0 | Toxic stain | DOT, floors HP (3.4) |
| Poison | poison | 1.0 | Poisoned stain | DOT, x3 per NG+ |
| Curse | curse | 1.0 | Houre, collapsed Holy Mountain, Midas (100x current HP per instance) | universal 1.0; Stainless Armour still halves |
| Holy | holy | **1.5** | Holy Lance (43.75), Hohtava hyypiö | added Apr 2024 |
| Physics (PHYSICS_HIT) | physics_hit | 1.0 | black/white holes; sub-sources Kinetic (physics objects, player immune), Crush (collapsed concrete, hurts player), Velocity (props only) | enemies often 2.0 (`base_enemy_basic`?) - vanilla base has no physics_hit entry (1.0) |
| Overeating | overeating | 1.0 | satiation >150 % | player only |
| Bite | - | - | dragon bosses (Melee-Bite 3000/s) | ignores multipliers; Melee immunity blocks |
| Material | - | - | acid, lava, poison, toxic rock... | per-pixel per-frame, not multiplied (4.5) |
| Fall | - | - | only Eväkäs/Suureväkäs and props | 4.4 |
| Suffocation (DROWNING) | - | - | air 0 | `air_lack_of_damage` per second |
| Physics Body Damaged | - | - | loss of a physics body | kills physics entities |
| Material With Flash | - | - | Wet stain on fiery enemies (`wet_status_effect_damage`) | Stendari 0.3/10 frames = 45 HP/s |
| None | - | - | unused | "true" damage for mods |

### 2.3 Critical hits

* Base crit multiplier **x5** (`DAMAGE_CRITICAL_HIT_MULTIPLIER=5`). Crit chance c (0 = none): if c <= 1, probability c of x5; if c > 1 every hit crits with multiplier 5*c (200 % -> x10). `ConfigDamageCritical{chance, damage_multiplier}` must be pre-resolved on explosions.
* Average: `Total = Base * (1 + min(c,1) * (5*max(1,c) - 1) * (1 - CritResistance))`.
* Sources: Bloody stain +5 % per projectile cast, Critical Hit+ perk +10 %/stack (`CRITICAL_HIT_BOOST`), Close Call +40 %/proj, Critical Plus spell +15 %, Critical on Wet/Oiled/Bloody/Burning +100 % per copy (status from material spells lasts 720 frames even without an actual stain), many projectiles +5 % (Spark Bolt, Magic Arrow). Jarate: target takes +20 % crit chance.
* Resistances: player 1.0 (immune), Sätkymestari 0.4, Skoude 0.5, Ylialkemisti 0.8, several bosses 1.0; entities without AnimalAI/PhysicsAI/Worm/BossDragon components cannot be crit.

### 2.4 Knockback, impulses, ragdolls

| Source | Formula / value |
|---|---|
| Projectile | `final_knockback = ProjectileComponent.knockback_force * VelocityComponent.mVelocity * projectile.mass / target.mass`; `DamageModelComponent.minimum_knockback_force` (0 default; Vault enemies use 100000 = effectively immune) gates whether it applies. Extra Knockback perk +6. Spark Bolt 0, Magic Arrow 1.8, buckshot 1.0, sniper 4.0, fireball 1.5. |
| Explosion | `final_knockback = explosion_radius * knockback_force(1) * inv_normalized_distance / target.mass`; physics objects thrown with `physics_explosion_power` [min,max]. |
| Melee (AI) | impulse `attack_melee_impulse_vector (1, 0.25) * attack_melee_impulse_multiplier (50)`; `attack_knockback_multiplier=100` for melee/dash. |
| Physics bodies | projectile applies `physics_impulse_coeff (300 default) * velocity`. |
| Ragdoll on kill | `velocity * ragdoll_force_multiplier (0.025)`, crits x3 (`RAGDOLL_CRITICAL_HIT_FORCE_MULTIPLIER`). |
| Masses (`CharacterDataComponent.mass`) | player 1.0 (reference), Hämis 0.4, Hurtta 1.0, Shotgunner 1.3, Sniper 1.2, Stendari 1.6, Frog 0.6, Deer 2.4, Bat 0.6, Rat 0.4, Fish 0.2. |

## 3. Projectiles: collision and damage application

Key `ProjectileComponent` fields (defaults in parentheses) and behaviour:

| Rule | Detail |
|---|---|
| Spawn | position = wand tip (7-25 px from hand); speed `rand[speed_min, speed_max]` (60/60 default; Spark Bolt 750-850), direction +- `direction_random_rad`, lifetime `lifetime +- lifetime_randomness` frames (-1 = infinite). `VelocityComponent`: `gravity_y` (400 default; Spark Bolt 200), `air_friction` (0.55; per frame `v -= 0.016666567*v*air_friction`), `mass` (0.05), `terminal_velocity` 1000 px/s (Lightning Bolt unlimited to 61440), `liquid_drag` 1. |
| World collision | `collide_with_world` (1): the projectile dies on hitting a solid cell when `on_collision_die` (1) unless it has `bounces_left` (bounce: `velocity *= bounce_energy` (0.5), `bounce_at_any_angle`, `bounce_always` fake-bounces); `penetrate_world` passes through everything at `penetrate_world_velocity_coeff` (0.6) speed; `ground_penetration_coeff` with `ground_penetration_max_durability_to_destroy` lets bullets bury into soft material; `die_on_liquid_collision`; `go_through_this_material`. Bounces only on terrain/physics bodies, never on creatures. |
| Entity collision | `collide_with_entities` (1) against entities tagged `collide_with_tag` (`hittable`), skipping `dont_collide_with_tag`; herd check: a projectile does not hit its shooter's herd unless `friendly_fire`; the shooter itself is hit only after `collide_with_shooter_frames` (-1 = never; Healing Bolt 4, Piercing Shot/Twitchy 5) elapsed; `never_hit_player` overrides everything. |
| Hit count | Default: hit once, then die. `penetrate_entities=1`: continue, damage each entity **once** (`mDamagedEntities` list). `on_collision_die=0` (Piercing): keeps living and damages the same entity every frame it overlaps (`damage_every_x_frames` (-1) limits this, e.g. 10 F). Trigger payloads release once per hit (or every frame when piercing). |
| Damage | `damage` (Projectile type) plus `damage_by_type{...}`; `damage_scaled_by_speed` multiplies by `speed / mInitialSpeed` (or `damage_scale_max_speed`); crit from `damage_critical`; knockback as 2.4; `damage_game_effect_entities` applies statuses (e.g. `effect_apply_wet.xml` 720 f). |
| Death | `on_death_explode` -> `config_explosion`; `on_lifetime_out_explode` separately; `explosion_dont_damage_shooter` protects the caster from its own blast (independent of friendly fire); `die_on_low_velocity` (< `die_on_low_velocity_limit` 50); `on_death_duplicate_remaining`; `on_collision_spawn_entity`. |
| Terrain damage by projectile hit | the small `config_explosion` on normal bullets (`damage=0`, `ray_energy` 400000 for Spark Bolt, `max_durability_to_destroy` 8) carves cells on impact (see 3.2). |

Reference projectile rows (vanilla): Spark Bolt dmg 0.12 (3), 750-850 px/s, lifetime 40+-7, gravity 200, friction 1.7, knockback 0, crit +5 %. Magic Arrow 0.40 (10), 600-650, knockback 1.8, recoil +23. Bouncing Burst 0.12 (3) speed-scaled, lifetime 750, 10 bounces at 0.9 energy. Enemy buckshot 0.27 (6.75) x3-4, 500-600, 1 bounce. Sniper bullet 1.0 (25) speed-scaled, 1450-1650 accelerating (`air_friction -2`), friendly_fire 1, +explosion 0.4 (10). Enemy fireball: fire 0.25 (6.25) + explosion 2 (50) radius 20, ignites 15-px circle.

### 3.2 Explosions (`ConfigExplosion`)

| Field | Default | Role |
|---|---|---|
| `explosion_radius` | 20 (spell default; Bomb 60, Fireball 15, Nuke 250, Explosion 15) | radius in px used to find mortals/physics bodies and as hole radius |
| `damage` | 5 (Bomb 5 = 125, Fireball 2 = 50, Nuke 10 = 250) | Explosion-type damage to every `damage_mortals` entity within radius. No distance falloff is documented (knockback does scale with inverse normalised distance) - **UNVERIFIED** |
| `ray_energy` / `max_durability_to_destroy` | 20000 / 10 (Bomb 6,000,000 / 11; Nuke 6,700,000 / 12; Spark Bolt 400,000 / 8) | terrain carving: rays from the centre spend energy on each cell's hardness-HP until exhausted or radius reached; cells with durability > max are never destroyed |
| `hole_enabled`, `destroy_non_platform_solid_enabled`, `hole_destroy_liquid` (0 = liquids are thrown, not deleted), `hole_destroy_physics_dynamic` | 1/1/0/1 | what the crater removes |
| `create_cell_material` / `create_cell_probability` | fire / 5 (Fireball 100, Bomb 40) | destroyed cells may turn into fire |
| `knockback_force`, `physics_explosion_power` [0,0.2] (Bomb 2.2-3.6), `physics_throw_enabled` | 1 | throws entities/props |
| `damage_mortals` | 1 | 0 = purely cosmetic/terrain (Burst of Air, mists) |
| `explosion_dont_damage_shooter` (projectile) | 0 | caster safety (Bomb/Explosion spells hurt you; Spark Bolt's impact pop does not) |
| `delay`, `explosion_delay_id`, `never_cache` | - | delayed barrel chains / immediate for projectiles |
| `stains_radius` | 0 -> 0.3 * radius | soot staining |
| Min damage by radius (player spells with `c.explosion_radius > 0`) | radius 32-63 -> at least 325; 64-127 -> 375; >= 128 -> 500 | Explosion interactions |
| Berserk / Glass Cannon | x2 / x5 radius and damage (after the min-damage lookup) | - |
| Material durability thresholds | sand 4, coal/concrete 8, static meat 9, dense rock/soil 10, rusted steel 11, extremely dense rock/steel 12, dense steel 13, brickwork/cursed rock 14 | Materials |

### 3.3 Friendly fire and herds

* Every creature has `GenomeDataComponent.herd_id`; relations in `factions-relations.json` (0..100). An individual's `aggressiveness` is rolled once from `[aggressiveness_min, aggressiveness_max]` (enemies 1-100, snipers 80-100, helpless 0-20); it attacks members of faction F when aggressiveness > relation(self, F). Player row: 100 to player/helpless, 0 to all else; toward the player every faction is 0 except orcs = 2. More Love +25 / More Hatred -25 to every relation.
* Creatures always retaliate when damaged (`attack_if_damaged_probability=100`), even against friends unless `dont_counter_attack_own_herd`.
* Projectiles fired by an entity remember `mShooterHerdId`; same-herd entities are skipped unless `friendly_fire=1`. Piercing Shot / Bloodlust add friendly fire (and the caster becomes hittable after 5 frames).

## 4. Status effects, materials and environment

### 4.1 Fire

* Ignition: contact with a `fire`/`fire_strong`/molten cell rolls `fire_probability_of_ignition` (player 1.0, enemies 0.5, Hiisi gunners 5, Deer 0.05, 0 = immune). Stains with `protects_from_fire` (Wet, Oiled*, Bloody, Slimy, Toxic, Jarate) prevent ignition; fire burns the stain away instead. *Oiled alone makes you ignite easily and burn far longer; Oiled + Wet/Bloody lets you ignite but you extinguish on leaving the fire.
* Burning: ON_FIRE status. Damage per second = **2 % of max HP** (player 2 HP/s) with multiplier `fire`; engine flags `DESIGN_FIRE_DAMAGE_BASED_ON_MAX_HP=1`, `DAMAGE_FIRE_DAMAGE_MAX_HP_MIN_BOUND=0.8` (max HP treated as at least 0.8 internal = 20 HP for the burn rate - inference, **UNVERIFIED**) and `fire_damage_amount=0.2`. The burning creature emits 5 fire cells/frame (`effect_on_fire.xml`) so it spreads fire, moves 15 % faster, and (AI) enters `TakingFireDamage`/panic and stops attacking. Duration is engine-internal (`mFireFramesLeft`), refreshed while touching fire; the game-effect entity applied by spells lasts 100 frames (720 for `effect_apply_on_fire`).
* Extinguish: immersion in nearly any liquid (water, oil, slime, blood, toxic sludge...); Wet/Bloody/Slimy/Toxic stains; Fire Immunity/Freeze Field/Oil Blood perks (still ignite but no damage, burn out fast). Internal Fire (ingested lava/fire) cannot be put out.
* Water + lava -> rock; burning water -> steam.

### 4.2 Wet / Oiled / Bloody / Slimy stains

| Stain | Fire | Other effects | Removal |
|---|---|---|---|
| Wet | prevents ignition, puts fire out | no i-frames from electric stun; `wet_status_effect_damage` hurts fiery enemies (Stendari 45 HP/s) | dries while moving; burnt off by fire; replaced by any other liquid |
| Oiled | prevents ignition only while submerged; once lit burns much longer; ignites easily | no ground traction (slides on slopes), slightly narrower hitbox | wash with water |
| Bloody | prevents ignition | +5 % crit per projectile cast | same |
| Slimy | prevents ignition | 15-40 % slower movement | same |
| Status via spells | Water/Oil/Blood (Spell) and trails apply the effect for 720 frames (12 s) to anything hit by the multicast, even without real stain cells | - |

Stain amount is normalised (1.0 = 60 s); a status keeps full power while >= 1 % / 1 s of stain remains; stains drop faster while moving (`VERLET_STAIN_DROP_CHANCE_DIV=200`, `GAMEEFFECT_STAINS_DROP_FASTER_DROP_CHANCE_MULTIPLIER=10`).

### 4.3 Frozen, Stunned, Dazed

| Status | Duration | Effect |
|---|---|---|
| Frozen (`FROZEN`) | 120 frames (short 50) | `disable_movement`; applied by freeze spells when `rand < ice mult`. Any Melee hit on a Frozen target: HP -= 50 % of current if current > 25 % max, else set to 0 (player included); ignores armour/resistances but not Melee immunity; all Melee becomes multitype Melee-Ice. |
| Stunned (`ELECTROCUTION`) | 40 frames per application | `disable_movement`; probability `rand < electricity mult`; 60-frame electricity resistance window afterwards; `STUN_PROTECTION_ELECTRICITY` blocks stun only. Explosion of Thunder / Circle of Thunder stun even with Electricity Immunity. |
| Dazed (`KNOCKBACK`) | 120 frames | cannot levitate/move; triggered by Projectile/Melee damage while airborne; Knockback modifier makes fliers fall. |
| Weakened / Withered | 600 | main type multipliers set to 1.2 and immunity perks disabled / all main types take more |

### 4.4 Fall damage (`DamageModelComponent`, disabled for the player)

`falling_damages=1` only on Eväkäs/Suureväkäs (fish) and props. Formula: when landing after falling `h` px (tracked from `mFallHighestY`): if `h < falling_damage_height_min` nothing; damage ramps linearly from `falling_damage_damage_min` at `height_min` to `falling_damage_damage_max` at `height_max`, flat beyond. Defaults 70 px / 250 px, 0.1 / 1.2 internal (2.5 / 30 HP); fish use 250 / 450. `mFallCount` skips the very first fall. Props use `PhysicsBodyCollisionDamageComponent` (speed_threshold 60, damage_multiplier 0.016667) instead.

### 4.5 Material contact damage (per pixel, per frame; not multiplied by type multipliers)

| Material (id) | Internal / px / frame | HP/s per px | HP/s fully submerged (85 px) |
|---|---|---|---|
| Acid (`acid`), Cursed Rock (`rock_static_cursed`) | 0.005 | 7.5 | **637.5** |
| Greed-Cursed Rock (`rock_static_cursed_green`) | 0.004 | 6.0 | 510 |
| Lava (`lava`) | 0.003 | 4.5 | **382.5** (+ On Fire) |
| Poison (`poison`), Toxic Gas/Rock/Ice, Frozen Acid, Poisonous Rock | 0.001 | 1.5 | 127.5 (+ Poisoned/Toxic stain) |
| Freezing Liquid (`blood_cold`) | 0.0009 | 1.35 | 114.75 |
| Freezing Vapour (`blood_cold_vapour`) | 0.0006 | 0.9 | 76.5 |
| Greed-Cursed Liquid | 0.0005 | 0.75 | 63.75 |
| Toxic Gold | 0.0002 | 0.3 | 25.5 |
| Nauseating Gas (`poo_gas`) | 0.00001 | 0.015 | 1.275 |
| Healium gas (`magic_gas_hp_regeneration`) | -0.005 | heals 7.5 | heals 637.5 |

Enemies use a shorter list with larger per-pixel values (base enemies: acid/lava 0.004, poison 0.001, freezing 0.0008/0.0007, cursed rock 0.005). Lukki: acid 0.1. Stendari: water & co. 0.0005, acid 0.004. Only Ambrosia (`PROTECTION_ALL`) and Stainless Armour reduce material damage. Fire Immunity does not stop lava contact damage. Kills by material damage, fire or electricity are trick kills (2x gold).

### 4.6 Toxic / Poisoned

* Toxic (Toxic Sludge stain, `RADIOACTIVE`): Radioactive damage of ~2 % max HP per tick; wiki pages disagree on cadence (every 1.5 s on Damage Types, every 1 s on Status Effects/Healing) - **UNVERIFIED which**; never kills: stops at 5 % max HP (Damage Types) / <= 2 % (Toxic Sludge page). Hiisi with `ALLERGY_RADIOACTIVE` (shotgunner, sniper...) have no floor and can die. Washed off by water or any other liquid; Toxic Immunity/Gas Blood negate.
* Poisoned (`POISONED`, from Poison liquid, drinking acid/toxic/oil...): Poison damage 2 % max HP per tick, same floor in NG; x3 per New Game+ cycle (NG+3 = 54 %/s). Poison liquid additionally does 0.001/px/frame Material damage.
* Water converts Toxic Sludge to water (reaction rate 13).

### 4.7 Other liquids

Water: Wet, extinguishes, conducts electricity (lethal with Ukko/electric spells), drowning. Blood: Bloody (+crit). Slime: Slimy (slow). Oil: Oiled, floats on everything (density 1), burns slowly (fuel 500). Lava: ignites, converts to rock on water contact, kills almost everything. Acid: dissolves `corrodible` materials into flammable gas, instant-death tier damage. Whiskey/alcohol: Alcoholic (spread, more flammable). Berserkium: Berserk (x2 damage/radius, 720 f). Ambrosia: Protection from all (wears off fast while moving). Polymorphine: sheep.

## 5. Simple enemies (vanilla data, displayed units)

Shared defaults (`base_humanoid` -> `base_enemy_basic`): HP 12.5, hitbox 9 x 8.5, collision 4 x 6, gravity 600, melee 5-10 at <= 10 px every 20 frames (impulse (1,0.25) x50), dash 6.25 at speed 200 within 50 px every 120 frames, detection 300 x 300 px re-checked every 30 frames with 90 deg half-angle, aggressiveness 1-100, escape-if-damaged 30 %, drill mult 0.7, air needed (can drown), eats meat, `path_cleanup_explosion_radius` 6 (digs itself free when stuck). Flying base (`base_enemy_flying`): `can_fly`, drill 0.5, acid-spit ranged every 40 frames. Gold on death = 10 x max(1, floor(HP/25)) (script `drop_money.lua`), doubled for trick kills.

| Enemy (id) | HP | Attacks (displayed) | Speed / mobility | Detection | Damage multipliers | Hitbox (px) | Notes |
|---|---|---|---|---|---|---|---|
| **Hämis** (`longleg`), spider faction | 2.75 | Melee 5-10 (<=10 px, 20 f); lunge 6.25 (wiki lists 6) | run 25, jump -140 (leaps), mass 0.4 | 300x300 | drill 0.7 | 10 x 12 | flees 100 % when hurt; groups up to 8; eats corpses; 10 gold (0 if nest-spawned). Mines, Pyramid, Temple of the Art, Tower |
| **Hurtta** (`zombie`), zombie faction | 12.5 (Heikkohurtta 5) | Melee 5-10; lunge 6.25 w/ strong knockback | run 18, can jump (-12), swim/dive, mass 1.0 | 250x250 | drill 0.7, holy 1.2 | 9 x 9.5 | solitary wanderer, eats corpses, long horizontal leaps, poor vertical reach. 10 gold |
| **Haulikkohiisi** (`shotgunner`), orcs | 22.5 (weak 9; Hornahiisi 72.5) | Shotgun 3-4 pellets x 6.75 (500-600 px/s, 1 bounce, spread 0.04 rad) every 100 f at 0-180 px; melee 10-17.5 at <= 12 px | run 20, jump_speed 80, mass 1.3 | 400x200, 60 deg | drill 0.7; head hitbox x2.5 | 6 x 9 + head 5 x 6 | ignition prob 5 (burns easily); dies to Toxic stain; picks up wands; patrols/jumps/fires mid-air; escape 40 %. 10 gold |
| **Snipuhiisi** (`sniper`), orcs | 45 (Vault 155, knockback-resistant) | Sniper bullet 25 (speed-scaled, 1450-1650 px/s accelerating, hits own herd, +10 explosion, knockback 4) every 100 f at 10-800 px after laser telegraph (action frame 8); melee 10-17.5 | run 24, jump_speed 70, mass 1.2 | 700x700 | drill 0.7 | 10 x 15 | aggressiveness 80-100, escape 70 %; damaging it resets the shot; bullet buries 2x into soft ground. 10 gold (Vault 60) |
| **Hämähäkki** (`lukki`), slimes | 162.5 (Pikku 87.5, Lukki 200) | Leg jab Melee 12.5 (limb reach 40 px, targeting 120); leg contact 2.5 every 10 f | PhysicsAI circle r 8, ignores gravity, walks on background, tunnels (cell eater r 13) | - | melee 2.0, projectile 0.2, explosion 0.8, electricity 0.6, fire 1.2, slice 2.0, ice 1.2 | 20 x 20 weak spot | no air needed, glue-immune, acid 0.1/px; follows loosely, flees when badly hurt. 60 gold |
| **Stendari** (`firemage_weak`), mage | 80 | Weak Fireball: 50 explosion (radius 20, player takes 17.5) + 6.25 fire + ignites 15-px circle, 160-170 px/s, lifetime 60, dies in liquid; every 80 f, action frame 3; melee 10-17.5 | run 18, jump_speed 130 (high jumps), mass 1.6 | 300x300 | explosion 0.4, fire 0 (immune, never ignites), drill 0.7 | 9 x 17 | bleeds lava (x0.6); takes 45 HP/s while Wet and 0.0005/px/frame from water/snow/mud; passive while player holds Kiuaskivi. 30 gold |
| **Nelikoipi** (`deer`), helpless | 20 | none | run 30, jump -12, swims, mass 2.4 | 128x160 | - | 13 x 13 | aggressiveness 0-20, job Escaping; ignition prob 0.05; drops Meat of an Innocent Creature |
| **Konna** (`frog`), slimes | 7.5 | Lunge 10 (speed 200, 50 px, every 120 f), applied every frame of hitbox overlap | hop-only (`run_velocity 0`, `can_walk 0`, lob 2), mass 0.6 | 250x250 | drill 0.7 | 3 x 5.5 | ambush: motionless until close; low jump height; ignores being on fire. 10 gold |

Extra easy ones: Lepakko (bat) 12.5 HP flying lunge 6.25, drill 0.5; Rotta (rat) 5 HP melee 5-10, run 40, jump -30; Eväkäs (fish) 2.5 HP, takes fall damage (250-450 px).

AI state machine (`AnimalAIComponent.ai_state`, 1-21): RandomMove, Wandering, Eating, RaisingHead, PreparingJump, MoveNearTarget, Peeing, Defecating, Alert, Landing, TakingFireDamage, EscapingPrey, AttackingMelee, AttackingMeleeDash, AttackingRanged, AttackingRangedMulti, Escaping, JobDefault, JobGoto, JobHelpOtherEntity, GoNearHome. Pathfinding (`PathFindingComponent`): A* over a grid with `can_walk/can_fly/can_jump/can_dive/can_swim_on_surface`, `jump_trajectories` list, `frames_between_searches` 20-30, `frames_to_get_stuck` 20-120.

## 6. Healing and HP changes (for completeness)

Full Health Regeneration (Holy Mountain, +10 max), Extra Max HP +25 (x2-4 with Stronger Hearts; Large +50), Healing Bolt 8.75 per hit (20 charges), Circle of Vigour 10 % max HP/s, Regeneration status (Healthium/Lively Concoction) 10 %/s for 150 frames, blood healing with Vampirism (`blood_healing_speed` 0.0024/cell). Glass Cannon caps max HP at 50 (`max_hp_cap = 2`). Heartache halves current and max HP for its duration. Satiation: >100 % slow, >150 % choking damage (`overingestion_damage` 0.002 per excess cell), 200 % explode.

## 7. Perk categories (wiki Cargo `Perks` table, 117 rows, 103 in the Holy Mountain pool)

Utility 31, Defensive 29, Offensive 26, Mobility 14, Minion 11, Damage Immunity 11, Situational 10, Special 9, World State 9, Unique 8, HP 7, Passive 6, Detection 5, Retired 5, Blood 5, Evil 4, Good 4, Healing 4, Melee 3, Levitation 3, Greed 3, Relation 3, On-Kill 2, On-Hit 2 (a perk can be in several). Engine-side perks are either a `game_effect` (PROTECTION_*, CRITICAL_HIT_BOOST, DAMAGE_MULTIPLIER...) or a `func` that edits components (kick values, gravity, buoyancy, blood material). Damage-relevant ones: Fire/Explosion/Melee/Electricity/Toxic Immunity, Stainless Armour (/2 per stack while stainless), Glass Cannon (x5 damage, 50 HP cap), Critical Hit+ (+10 %), Close Call (+40 %/proj), Extra Knockback (+6), No More Knockback, Never Skip Leg Day, Oil/Gas/Slime Blood, Breathless, Strong/Faster/Rage-fueled Levitation, Extra HP (x1.5 max HP).

## 8. Implementation checklist derived from the above

1. Store HP/damage as floats in internal units and display x25 (or store displayed and divide spell data by 25 - pick one and document it).
2. Entity = {herd, aggressiveness, hitbox AABB(s) with multipliers, collision AABB, mass, DamageModel{hp, max_hp, multipliers[15], crit_resist, invincibility_frames, fire params, air, material damage table}, GameEffects[], StatusStains[]}.
3. Projectile = {owner, herd, hit list, lifetime, velocity+gravity+friction, bounces, penetrate/pierce flags, damage_by_type, crit, knockback, config_explosion, apply-effects list}; per frame: integrate, world collision (bounce/die/penetrate), entity collision (herd+shooter rules, once-per-entity or every N frames), on death explode.
4. Explosion = radius, flat damage to all mortals in radius (apply target multipliers), ray-based terrain carving with ray_energy vs cell hardness and durability cap, knockback ~ radius / distance / mass, fire cell conversion.
5. Status/stain system with per-frame tick for fire (2 %/s), toxic/poison (2 %/tick with floor), frozen/stun timers, Wet/Oiled interactions, extinguish-on-immersion.
6. Player: gravity 350, walk clamp 57 px/s, jump -95, fly meter 3 s with 38-frame air delay and 0.4/6 per-second recharge, fly speeds 95/85/52, kick 1 dmg radius 3 with 3-4 frame parry window, no fall damage, explosion x0.35, holy x1.5, crit immune, 7 s air then 15 HP/s.

## Sources

- https://noita.wiki.gg/wiki/Min%C3%A4?action=raw
- https://noita.wiki.gg/wiki/Damage_Types?action=raw
- https://noita.wiki.gg/wiki/Critical_hit?action=raw
- https://noita.wiki.gg/wiki/Status_Effects?action=raw
- https://noita.wiki.gg/wiki/Healing?action=raw
- https://noita.wiki.gg/wiki/Guide:_How_to_Play?action=raw
- https://noita.wiki.gg/wiki/Creatures?action=raw
- https://noita.wiki.gg/wiki/Materials?action=raw
- https://noita.wiki.gg/wiki/Explosion_interactions?action=raw
- https://noita.wiki.gg/wiki/Explosion?action=raw
- https://noita.wiki.gg/wiki/Knockback?action=raw
- https://noita.wiki.gg/wiki/Piercing_Shot?action=raw
- https://noita.wiki.gg/wiki/Piercing_and_Penetrating?action=raw
- https://noita.wiki.gg/wiki/Bounce?action=raw
- https://noita.wiki.gg/wiki/Bouncing_Spells?action=raw
- https://noita.wiki.gg/wiki/Recoil_(stat)?action=raw
- https://noita.wiki.gg/wiki/Never_Skip_Leg_Day?action=raw
- https://noita.wiki.gg/wiki/Parrying?action=raw
- https://noita.wiki.gg/wiki/Trick_kills?action=raw
- https://noita.wiki.gg/wiki/Friendly_Fire?action=raw
- https://noita.wiki.gg/wiki/Factions?action=raw
- https://noita.wiki.gg/wiki/Factions/Relations?action=raw
- https://noita.wiki.gg/wiki/Enemy_Immunities?action=raw
- https://noita.wiki.gg/wiki/Perks?action=raw
- https://noita.wiki.gg/wiki/Stainless_Armour?action=raw
- https://noita.wiki.gg/wiki/Glass_Cannon?action=raw
- https://noita.wiki.gg/wiki/Strong_Levitation?action=raw
- https://noita.wiki.gg/wiki/Faster_Levitation?action=raw
- https://noita.wiki.gg/wiki/Rage-fueled_Levitation?action=raw
- https://noita.wiki.gg/wiki/High_Gravity?action=raw
- https://noita.wiki.gg/wiki/Gas_Blood?action=raw
- https://noita.wiki.gg/wiki/Oil_Blood?action=raw
- https://noita.wiki.gg/wiki/Breathless?action=raw
- https://noita.wiki.gg/wiki/Fire_Immunity?action=raw
- https://noita.wiki.gg/wiki/Explosion_Immunity?action=raw
- https://noita.wiki.gg/wiki/Melee_Immunity?action=raw
- https://noita.wiki.gg/wiki/Toxic_Immunity?action=raw
- https://noita.wiki.gg/wiki/Electricity_Immunity?action=raw
- https://noita.wiki.gg/wiki/Freeze_Field?action=raw
- https://noita.wiki.gg/wiki/Extra_Knockback_on_Spells?action=raw
- https://noita.wiki.gg/wiki/No_More_Knockback?action=raw
- https://noita.wiki.gg/wiki/Extra_modifiers?action=raw
- https://noita.wiki.gg/wiki/H%C3%A4mis?action=raw
- https://noita.wiki.gg/wiki/Hurtta?action=raw
- https://noita.wiki.gg/wiki/Haulikkohiisi?action=raw
- https://noita.wiki.gg/wiki/Snipuhiisi?action=raw
- https://noita.wiki.gg/wiki/H%C3%A4m%C3%A4h%C3%A4kki?action=raw
- https://noita.wiki.gg/wiki/Stendari?action=raw
- https://noita.wiki.gg/wiki/Nelikoipi?action=raw
- https://noita.wiki.gg/wiki/Konna?action=raw
- https://noita.wiki.gg/wiki/Hiisi?action=raw
- https://noita.wiki.gg/wiki/Lepakko?action=raw
- https://noita.wiki.gg/wiki/Rotta?action=raw
- https://noita.wiki.gg/wiki/Ev%C3%A4k%C3%A4s?action=raw
- https://noita.wiki.gg/wiki/M%C3%A4t%C3%A4nev%C3%A4_ruumis?action=raw
- https://noita.wiki.gg/wiki/Water?action=raw
- https://noita.wiki.gg/wiki/Water_(Spell)?action=raw
- https://noita.wiki.gg/wiki/Oil?action=raw
- https://noita.wiki.gg/wiki/Lava?action=raw
- https://noita.wiki.gg/wiki/Acid?action=raw
- https://noita.wiki.gg/wiki/Fire?action=raw
- https://noita.wiki.gg/wiki/Toxic_Sludge?action=raw
- https://noita.wiki.gg/wiki/Poison_(Material)?action=raw
- https://noita.wiki.gg/wiki/Blood?action=raw
- https://noita.wiki.gg/wiki/Gold?action=raw
- https://noita.wiki.gg/wiki/Terminal_Velocity?action=raw
- https://noita.wiki.gg/wiki/Spark_Bolt?action=raw
- https://noita.wiki.gg/wiki/Magic_Arrow?action=raw
- https://noita.wiki.gg/wiki/Bomb?action=raw
- https://noita.wiki.gg/wiki/Fireball?action=raw
- https://noita.wiki.gg/wiki/Nuke?action=raw
- https://noita.wiki.gg/wiki/Documentation:_DamageModelComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_ProjectileComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_ConfigExplosion?action=raw
- https://noita.wiki.gg/wiki/Documentation:_ConfigDamagesByType?action=raw
- https://noita.wiki.gg/wiki/Documentation:_ConfigDamageCritical?action=raw
- https://noita.wiki.gg/wiki/Documentation:_CharacterPlatformingComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_CharacterDataComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_CharacterCollisionComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_PlayerCollisionComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_AnimalAIComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_AIAttackComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_PathFindingComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_HitboxComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_VelocityComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_KickComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_GameEffectComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_GenomeDataComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_AreaDamageComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_PhysicsBodyCollisionDamageComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_IngestionComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_PlatformShooterPlayerComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_SpriteStainsComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_IKLimbAttackerComponent?action=raw
- https://noita.wiki.gg/wiki/Documentation:_MaterialSuckerComponent?action=raw
- https://noita.wiki.gg/wiki/Modding:_Enums?action=raw
- https://noita.wiki.gg/wiki/Modding:_Magic_Numbers?action=raw
- https://noita.wiki.gg/wiki/Modding:_Lua_API?action=raw
- https://noita.wiki.gg/wiki/Modding:_Data.wak?action=raw
- https://noita.wiki.gg/wiki/Template:Infobox_enemy?action=raw
- https://noita.wiki.gg/api.php?action=cargoquery&tables=Enemies&fields=_pageName,name,alias,id,health,critResist,attackType,blood,corpse,spawnLocation,immunities,dmgMultMelee,dmgMultProjectile,dmgMultSlice,dmgMultExplosion,dmgMultElectricity,dmgMultFire,dmgMultIce,dmgMultDrill,dmgMultRadioactive,dmgMultHoly,dmgMultNotes,faction,category,chaosPolymorph,unstablePolymorph&limit=500&format=json
- https://noita.wiki.gg/api.php?action=cargoquery&tables=Attacks&fields=name,attackname,damagetype,damage,damagefreq,iter&limit=500&format=json
- https://noita.wiki.gg/api.php?action=cargoquery&tables=Perks&fields=_pageName,Name,id,Categories,Stackable,MaxStack,PerkPool,PoolMax,PlayerOnly,OneOff,Description,Unimplemented,NotAPerk&limit=500&format=json
- https://github.com/NathanSnail/noitadata (vanilla beta-branch data dump) - files used: data/entities/player.xml, data/entities/player_base.xml, data/entities/base_humanoid.xml, data/entities/base_enemy_basic.xml, data/entities/base_enemy_flying.xml, data/entities/base_helpless_animal.xml, data/entities/base_projectile.xml, data/entities/animals/{longleg,zombie,zombie_weak,shotgunner,shotgunner_weak,sniper,firemage,firemage_weak,deer,frog,bat,rat,fish}.xml, data/entities/animals/lukki/lukki.xml, data/entities/animals/lukki/lukki_feet/lukki_limb_attacker.xml, data/entities/projectiles/{buckshot,sniperbullet,fireball,fireball_ghostly,bomb}.xml, data/entities/projectiles/deck/{light_bullet,bullet,rubber_ball,explosion,fireball}.xml, data/entities/misc/effect_*.xml, data/scripts/status_effects/status_list.lua, data/scripts/perks/perk_list.lua, data/scripts/perks/angry_levitation_death.lua, data/scripts/items/drop_money.lua, data/magic_numbers.xml (raw URLs: https://raw.githubusercontent.com/NathanSnail/noitadata/main/<path>)
- https://gitea.moonside.games/MoonsideGames/Consistency (a *rebalance mod* mirror used only to locate file structure; its HP values differ from vanilla and were not used)
- https://github.com/gokiburikin/gkbrkn_noita/blob/master/files/gkbrkn/champion_types/invincibility_frames/damage_received.lua and https://github.com/Copious-Modding-Industries/copis_things/blob/main/files/scripts/perk/damage_received/invincibility_frames.lua (semantics of `invincibility_frames`)
