# Spells: Catalogue, Behaviour Primitives and the MVP-50

**Purpose / when to read this.** Normative reference for the 422-spell catalogue of the Noita clone: what every `spells.json` field means (units, canonical vs wiki-display), what each spell type does in the casting engine, how every spell maps onto 7 runtime behaviour primitives (and which spells need custom code), and the exact behaviour of the MVP-50.
Read it before touching the spell loader, shot-state/draw code, projectile or explosion code, or any spell test; cite rule IDs `SPELL-Rnn` from code and tests. Deck/wand algorithms in depth: `research/wand-mechanics.md`; damage pipeline, crit, status effects: sibling KB page `spec/game-design/entities-damage.md` (DAMAGE-Rnn); RNG streams: `benchmark.md` (DET-R04).
Legend: `UNVERIFIED` = not confirmed against the engine; `DECISION-NEEDED` = the user must choose; "display" = internal x 25 (SPELL-R03); `f` = frame (1/60 s); `*` after a number = engine default, not written in the XML.
Source keys: **S**=`research/spells.md`, **SJ**=`research/spells.json`, **TX**=`research/spell_taxonomy.json`, **GA**=`raw/game/gun_actions.lua`, **GL**=`raw/game/gun.lua`, **WM**=`research/wand-mechanics.md`, **ED**=`research/entities-damage.md`, **W:Page**=`https://noita.wiki.gg/wiki/Page` (local `raw/Page.wikitext`).

## Normative rules

### A. Data, units, provenance

**SPELL-R01 Catalogue identity.** Exactly 422 obtainable spells, key = `game_id` (UPPER_SNAKE, e.g. `LIGHT_BULLET`); `id` is its lowercase and is never the wiki name. Counts by `type`: projectile 122, static_projectile 45, modifier 143, multicast 14 (`DRAW_MANY`), material 26, utility 25, passive 5, other 42. `gun_actions.lua` holds 491 `id` rows; the 69 extra rows (68 distinct ids, `DUCK` twice) are commented-out/legacy (TESTBULLET, KNIFE, DECOY...) and appear only in `spell_behaviors_from_gun_actions.json`: never load them. Source: S §1.1, §4.1; SJ; behaviours json (cross-checked: 422 of 491 ids are in SJ).

**SPELL-R02 Units.** Time = frames at 60 fps (store frames, never seconds; `seconds` fields are derived, 4 dp, wiki seconds are 2 dp). Length px; speed px/s; angle degrees (XML `direction_random_rad` x 180/pi: 0.01 rad = 0.57 deg, wiki shows 0.6); +y points down. Source: ED §0; W:Spells.

**SPELL-R03 Damage unit.** internal = display / 25 (`GUI_HP_MULTIPLIER` 25): XML `damage="0.12"` <-> 3, player `hp=4` <-> 100. In SJ, `damage.*` and `damage_modifier.*` are display; `projectile_xml.*.damage`, `damage_by_type_raw`, `action_effects_raw.c_add.damage_*_add` are internal. Store one unit and convert at the boundary (DECISION-NEEDED, S2). Source: ED §0; extractor `DISPLAY_DAMAGE_MULTIPLIER`.

**SPELL-R04 Provenance precedence.** (1) Fields parsed from the spell's Lua (`mana`, `max_uses`, every `c.*` delta, draw, triggers, tiers, price, `recursive`) are canonical. (2) `projectile_xml` raw XML values plus SPELL-R05 defaults are canonical for projectile stats. (3) Wiki-Cargo fields (`damage`, `explosion_radius`, `projectile_speed`, `lifetime`, `spread_degrees`, `bounces`, `tags`, `wiki.*`) are display values: on conflict XML wins (conflict list in DF-3). For mana/uses/price/tiers the game file wins over the wiki. Source: S §3, §4.3; validation_report.json; DF-3.

**SPELL-R05 Absent XML attribute = engine default, not zero.** ProjectileComponent: speed 60..60 px/s, lifetime -1 (infinite), damage 1.0 (=25), on_collision_die 1, collide_with_world/entities 1, bounces_left 0, bounce_energy 0.5, die_on_low_velocity_limit 50, physics_impulse_coeff 300, friendly_fire 0, explosion_dont_damage_shooter 0. VelocityComponent: gravity_y 400, air_friction 0.55, mass 0.05, terminal_velocity 1000. ConfigExplosion: damage 5 (=125), explosion_radius 20, ray_energy 20000, max_durability_to_destroy 10, create_cell_probability 5 (material `fire`), hole_enabled 1, damage_mortals 1, knockback_force 1. Overrides written inside `<Base file=..>..</Base>` merge attribute-wise over the base file (8 spells use `base_projectile_physics.xml`: ray_energy 6,000,000, create_cell_probability 0, DamageModel hp 0.5, lifetime 60). An empty `projectile_xml.explosion` does not mean "no explosion" (LIGHTNING keeps `config_explosion` inside `LightningComponent`: radius 35, damage default 5). Source: W:Documentation:_ProjectileComponent, _VelocityComponent, _ConfigExplosion, _LightningComponent; `raw/game/entities/base_projectile_physics.xml`, `deck/lightning.xml`.

**SPELL-R06 Mana.** Absent `mana` in Lua = 10 (`ACTION_MANA_DRAIN_DEFAULT`). Range -100..600; 47 spells cost 0; only `MANA_REDUCE` (Add Mana, -30) and `BLOOD_MAGIC` (-100) are negative: drawing them adds mana, so they are never skipped for lack of mana. Source: GL `draw_action`; SJ.

**SPELL-R07 Uses.** `max_uses` null = unlimited; 142 spells are limited (1..250; most common 20 (x31), 3 (x18), 15 (x18), 10 (x14)); 25 are `never_unlimited` (the Unlimited Spells perk does not lift them). A card with 0 uses is skipped without spending mana and leaves the deck cycle until refreshed. Source: SJ; GL; W:Spells.

**SPELL-R08 Lifetime.** Frames. Final lifetime = `lifetime` + integer in [-r, +r], r = `lifetime_randomness` (Spark Bolt 40 +-7 = 33..47; rounding UNVERIFIED); -1 = infinite (10 spells, all physics/creature entities). `c.lifetime_add` (`lifetime_modifier`) is added to the projectile lifetime. Source: W:Documentation:_ProjectileComponent; SJ.

**SPELL-R09 Speed and spread.** Initial speed = uniform[speed_min, speed_max] x `c.speed_multiplier`, then capped by terminal velocity (SPELL-R23). Each speed modifier multiplies `c.speed_multiplier` and clamps it to [0, 20] (FLY_UPWARDS/FLY_DOWNWARDS skip the clamp). Total spread = innate + sum(`c.spread_degrees`) + wand spread (root shot only, not trigger payloads); negative total behaves as 0. Source: W:Speed, W:Spells, W:Terminal_Velocity; GA boilerplate.

**SPELL-R10 Version pin and skew.** Game data = NathanSnail/noitadata mirror (`gun_actions.lua` last changed 2024-04-05, beta branch); wiki fetched 2026-10-07. Game file wins. Four numeric disagreements are UNVERIFIED as to which is current: PROJECTILE_THUNDER_FIELD / PROJECTILE_GRAVITY_FIELD uses 6 (game) vs 3 (wiki), VACUUM_POWDER mana 40 vs 50, plus a few spawn probabilities (`validation_report.json`). Source: S §7; validation_report.json.

### B. Casting engine facts the spells rely on (full algorithm: WM §4-16)

**SPELL-R11 Types.** `ACTION_TYPE`: PROJECTILE 0, STATIC_PROJECTILE 1, MODIFIER 2, DRAW_MANY 3, MATERIAL 4, OTHER 5, UTILITY 6, PASSIVE 7. Playing a type 0, 1 or 4 card sets `got_projectiles` and runs the perk extra-modifiers. Roles: 0 = spawn projectile(s) at the muzzle; 1 = spawn an entity at the caster/target (field, explosion, cloud, summon); 4 = emit material (spray, circle, sea, touch, soil); 2 = edit the shot state then draw 1; 3 = draw N; 5/6 = deck/wand/world logic (OTHER: triggers-builders, Divide, Greek, Requirement, Random, notes; UTILITY: copy-k, teleport casts, walls, All-*); 7 = action only draws 1, the effect lives in the wand-attached card entity (`custom_xml_file`). Source: GL `play_action`; GA; SJ.

**SPELL-R12 Draw budget.** Projectile/static/material cost 1 draw and give 0 (a trigger spell gives its own payload draw, R18); a modifier gives 1 (142 of 143 call `draw_actions(1,true)`; `RANDOM_MODIFIER` draws through the modifier it calls); multicast gives N (2,3,4,8; Myriad `BURST_X` = all remaining deck, 30 uses; formations 2/3/5/6); passives give 1. A click ends when the draw counter reaches 0 or the deck is empty with no wrap allowed. Source: WM §2.1, §9.1; SJ `draw_count`.

**SPELL-R13 Mana check and skips.** On draw: cost > current wand mana, or `uses_remaining == 0` -> the card goes to discard unplayed (no mana spent) and drawing continues with the next card while the deck is non-empty; if it was the last card it still eats one draw. Negative cost adds mana. Mana may exceed the wand cap during a cast (cap is applied at cast start). Source: GL `draw_action`, `draw_actions`; W:Expert_Guide:_Draw.

**SPELL-R14 Use consumption.** At end of click every card in hand loses 1 use if (any type 0/1/4 card was played in the click) OR (card type is OTHER/UTILITY); only if the card is already identified (an unidentified card is identified free on its first played click; all benchmark spells are identified) and not `custom_uses_logic`. So limited modifiers/multicasts are charged on any click that produced a projectile, and limited OTHER/UTILITY cards are charged even on clicks with none. A card reaching 0 uses is not returned to the discard pile. Cards moved out of hand early (Wand Refresh) are not charged. Source: GL `move_hand_to_discarded`; WM §7, §12.

**SPELL-R15 Shot-state scope.** One root shot state per click, initialised from the wand (cast delay, spread, speed multiplier); every projectile registered during the click receives the final state, so modifier order matters only for set-mode fields and clamps. Each trigger payload and each Add-Trigger/Timer/Expiration payload starts from the zero defaults listed below; recharge (`current_reload_time`), mana and recoil are global, not per state. Defaults: `fire_rate_wait 0, speed_multiplier 1, child_speed_multiplier 1, dampening 1, explosion_radius 0, spread 0, pattern 0, bounces 0, gravity 0, damage_*_add 0, crit chance 0, lifetime_add 0, friendly_fire false, extra_entities "", game_effect_entities "", trail ""`. Source: GL; `gunaction_generated.lua`; WM §3.

**SPELL-R16 Cast delay.** Wand cast delay = root `c.fire_rate_wait` after all draws = wand base + deltas of spells played in the root scope; payload-scope deltas are ignored. Three spells SET it: CHAINSAW 0, NUKE 20, NUKE_GIGA 50 (discard everything accumulated before them in that state; later spells still add). Total <= 0 acts as 1 frame (max 60 casts/s). Cast delay and recharge run concurrently. A click producing no projectile does not wait the cast delay. Source: WM §14; W:Spells; SJ `cast_delay_modifier.mode`.

**SPELL-R17 Recharge.** `current_reload_time` is global; every spell played anywhere (root, payload, copy, Divide) adds its delta; 44 spells carry one (-25 RESET .. +800 NUKE_GIGA; NUKE and CESSATION +600). It is consumed only when a recharge starts (deck empty or a wrap happened) and then resets to the wand base. Negative total -> 0. Source: GL; W:Spells; SJ.

**SPELL-R18 Triggers.** 28 spells wrap a payload shot: collision 8 (fires on every terrain/entity hit; repeated while piercing), timer 11 (fires at the first of `timer_frames` / collision / projectile death, then stops), death 9 (once, when the projectile dies; a carrier that is stationary or killed by terrain releases in a random direction, one killed while moving by an entity hit, lifetime end, HP loss or Spells-To-X releases normally). Payload cards are drawn at cast time from the same deck into the same hand; wraps may occur inside the payload. Timer frames: 4, 10 (x3), 20 (x2), 40 (x3), 100, 200. Payload draw count 1 everywhere except `LIGHT_BULLET_TRIGGER_2` = 2 and `DELAYED_SPELL` = 3. Source: GL `add_projectile_trigger_*`; W:Trigger, W:Timer, W:Expiration_Trigger; SJ.

**SPELL-R19 Payload isolation.** Inside a payload: cast delay, spread, speed, damage, crit, pattern are isolated; recharge, mana, recoil are shared. If the carrier speed is ~0 the payload speed is set to 0. Payload spells never change the wand's cast delay. Source: W:Trigger; WM §10.

**SPELL-R20 Formations and pattern.** `pattern_degrees` is SET (last writer wins): formations set it after their draws (`T_SHAPE` 90, `W_SHAPE` 20, `Y_SHAPE` 45, `I_SHAPE`/`PENTAGRAM_SHAPE`/`CIRCLE_SHAPE` 180; wiki names Pentagon/Hexagon for the last two) with spread -8/-5/-8/-5/-12/-15; Scatter adds +10/+20/+40 spread (x2/x3/x4); Plicate spells set it before their draw (180,180,180,180,90,20,45); Divide By sets 5. Source: SJ `action_effects_raw`; WM §9.2.

**SPELL-R21 Copy spells and recursion.** 19 `recursive` spells (Greek, random family, Wand Refresh, Spell Duplication, All-Spells, Giga Nuke) are blocked at nesting level 2 (`recursion_limit`). Copies never pay mana or check uses (Divide/Random decrement the copied card's uses), may draw unless draw is suppressed, and add their own cast delay/recharge unless the caller restores them (Divide head, Mu, Phi, Sigma restore). Source: GL `check_recursion`; WM §9.3, §11.

**SPELL-R22 Passive cards.** Torch, Electric Torch, Energy Shield, Energy Shield Sector (effects) and Tiny Ghost (companion with 3 Lua scripts) act through `custom_xml_file`/card entities while the wand is held; their `action()` only draws 1. Source: GA; `raw/game/entities/misc/custom_cards/`.

### C. Projectile runtime

**SPELL-R23 Spawn and terminal velocity.** Projectiles never exceed terminal velocity 1000 px/s, even when spawned faster (excess initial speed is "absorbed" by speed-reducing modifiers). Exceptions: Lightning Bolt (`apply_terminal_velocity 0`, hard limit 61440), Cursed Orb 400, Expanding Orb 200; Fly Upwards/Downwards bypass the 20x cap. Reaching 1000 px/s needs <= 4 Speed Up for almost all projectiles. Source: W:Terminal_Velocity, W:Speed.

**SPELL-R24 Motion.** Per frame `v -= 0.016666567 * v * air_friction`; `gravity_y` accelerates along +y; negative friction accelerates (Magic Missile -5, Black Hole -0.2). `mass` scales knockback. Integration order and the unit of `gravity_y` (px/s^2 assumed) are UNVERIFIED. Source: ED §3 (wiki); W:Documentation:_VelocityComponent.

**SPELL-R25 Collision and death flags.** `on_collision_die` (default 1) kills on terrain or entity hit; `penetrate_entities` passes through creatures, damaging each once; `on_collision_die 0` (Piercing Shot) keeps the projectile alive and re-hits the same entity every frame unless `damage_every_x_frames` limits it; `collide_with_world 0` ignores terrain; `die_on_low_velocity` kills when speed < limit; `die_on_liquid_collision` kills in liquid. Explosion on death only if `on_death_explode`; on lifetime end only if `on_lifetime_out_explode` (default 0). Source: W:Documentation:_ProjectileComponent; W:Explosion_interactions; ED §3.

**SPELL-R26 Bounces.** `bounces_left` = XML bounces + `c.bounces`; each terrain/physics-body bounce multiplies velocity by `bounce_energy` (default 0.5, Rubber Ball 0.9) and decrements; `bounce_always` fakes a bounce when no proper reflection exists; creatures are never bounced off. Source: W:Documentation:_ProjectileComponent; ED §3.

**SPELL-R27 Speed-scaled damage.** With `damage_scaled_by_speed 1` (6 spells: ARROW, RUBBER_BALL, DISC_BULLET, BOUNCY_ORB, BOUNCY_ORB_TIMER, INFESTATION) projectile damage x= (speed now / initial speed); initial speed is recorded and the low-velocity check done at the end of the first frame; shot-state damage adds are scaled too. Source: W:Spells_With_Damage_Scaled_By_Speed.

**SPELL-R28 Shooter safety.** `explosion_dont_damage_shooter 1` protects the caster from the projectile's own blast (independent of friendly fire; default 0 = blast hurts); `collide_with_shooter_frames` (-1 default = never hits shooter) sets the grace period of friendly-fire shots; `friendly_fire` (Piercing Shot, Bloodlust set it) allows same-herd hits. Source: W:Documentation:_ProjectileComponent; ED §3.3.

**SPELL-R29 Damage composition.** Per type: projectile = `damage` + `c.damage_projectile_add`; explosion = config `damage` + `c.damage_explosion_add`; other types come from `damage_by_type` (+ `c.damage_*_add`); `damage_null_all` (Null Shot) zeroes them. Crit chance = sum `c.damage_critical_chance` (percent points; Spark Bolt/Magic Arrow +5, Critical Plus +15); multiplier 5, resolution per DAMAGE-R03. Pipeline, resistances and status effects: sibling KB `entities-damage.md` (DAMAGE-R01 ff.). Source: GA; ED §2.

**SPELL-R30 Material emission.** `c.trail_material`/`trail_material_amount` (Fire Trail fire 10, Water Trail water 20, Acid 5, Oil 20, Gunpowder 20, Poison 9, Rainbow 20) leave pixels along the path; `c.material`/`material_amount` spray (Nuke: fire 60; Firecrackers: gunpowder_unstable 10); `game_effect_entities` applies a status (wet, oiled, on fire, frozen, poison...) to anything hit; `projectile_type MATERIAL_PARTICLE` sprays (Water/Oil/Blood/Acid listed by the wiki; Cement presumably the same) die on liquid contact and emit their particle(s) on death (acid 6, water 1; others UNVERIFIED). Source: SJ; `deck/material_*.xml`.

### D. Explosions

**SPELL-R31 Explosion config.** `explosion_radius` (px) is the carve radius and the damage/knockback area; `ray_energy` is the per-ray carving budget spent on each cell's hardness; cells with durability > `max_durability_to_destroy` survive; `create_cell_material/probability` turns destroyed cells into fire; `hole_destroy_liquid 0` throws liquids instead of deleting; `damage_mortals 0` makes it purely cosmetic (mists, Burst of Air, walls). Damage inside the radius is not documented to fall off with distance (UNVERIFIED); knockback does (ED §2.4). Source: W:Documentation:_ConfigExplosion; ED §3.2; sibling KB DAMAGE-R21.

**SPELL-R32 Radius modifiers.** `c.explosion_radius` starts at 0 each shot; modifiers add: Explosive Projectile +15, Clusterbolt +4, Concentrated Explosion -30, Remove Explosion -30, Light Shot -10, Chain Spell -5, Divide By 2/3/4/10 -5/-10/-20/-40. After Light Shot, Chain Spell and Divide By the value is clamped to >= 0. If the final value is > 0 it is added to every projectile's own `explosion_radius` and `on_death_explode` is forced to 1. Source: W:Explosion_interactions; SJ.

**SPELL-R33 Minimum explosion damage.** Only when the final shot `c.explosion_radius` > 0: the projectile's explosion radius selects a floor (display units): 32-63 px -> 325, 64-127 -> 375, >= 128 -> 500; final explosion damage = max(config damage + `c.damage_explosion_add`, floor). Berserk/Glass Cannon radius boosts apply after the lookup. Source: W:Explosion_interactions.

**SPELL-R34 Self-damage.** Player explosion multiplier 0.35 (ED / DAMAGE-R06): Bomb 125 -> 43.75, Nuke 250 -> 87.5 to the caster unless protected. Spells whose blast hurts the caster (`explosion_dont_damage_shooter` 0): Magic Missile, Firebolt family, Fireball, Lightning, Bomb, Nuke, Explosion (full list: SJ `projectile_xml.projectile.explosion_dont_damage_shooter` absent or 0). Source: damage-types.json; SJ `projectile_xml`.

**SPELL-R35 Loose ground.** Big explosions load `loose_ground` / `loose_chunks` side entities that turn terrain around and above the crater into falling powder (Bomb, Holy Bombs, Nuke, Giga Nuke, Meteor, Thunder Charge). Entity XML is not in `raw/game`: behaviour UNVERIFIED. Source: `deck/bomb.xml`, `deck/nuke.xml`; W:Bomb.

### E. Behaviour primitives and implementation classes

**SPELL-R36 Seven primitives.** Every spell is exactly one of: **PROJ** (parametric projectile: ProjectileSpec + shot-state), **TRIGGER** (PROJ/STATIC wrapped by a collision/timer/death payload shot; 22 spells; plus the 3 Add-* builders and 3 utility casts = 28 trigger wrappers), **STATIC** (entity at caster/target), **MATERIAL** (spray, circle, sea, touch, soil), **MODIFIER** (edits shot state, draws 1), **MULTICAST** (draw N), **UTILITY** (deck/wand/world logic, passives, copies, random, requirements). Counts: KN-3. Source: TX `primitive`.

**SPELL-R37 Implementation classes.** **D0** data-only (a row interpreted by the core engine), **D1** data + a named reusable engine feature (no per-spell code), **D2** spell-specific code (Lua script in the original, deck/hand/discard logic, creature AI, caster-state access). Of 422 (KN-3): **D0 127 (30.1 %), D1 110 (26.1 %), D2 185 (43.8 %)**; covered without any per-spell code (D0+D1) = **237 (56.2 %)**. Source: TX; KN-3.

**SPELL-R38 Core engine (needed for D0).** shot state with all `c.*` fields; draw/wrap/mana/uses; trigger wrappers; ProjectileSpec (R05, R23-R28); explosion (R31-R33); material emission, trails and status effects (R30); multicast patterns (R20); crit; recoil; deterministic RNG. Anything outside this list is D1 or D2. Source: TX `_meta`; R05, R15-R33.

**SPELL-R39 `complex_logic` is not a custom-code flag.** It marks 56 spells whose `action()` has branches/loops: 44 are D2, 3 D1 (FIREWORK, SUMMON_EGG, INFESTATION), 9 are false positives (8 COLOUR_* screenshake clamps, BURST_X = draw `#deck`). 141 D2 spells are NOT flagged because their complexity is in entity scripts. Use TX `impl`. Source: TX; `spell_actions_lua.json`.

**SPELL-R40 Feature library (D1).** Implement each once: PROJ_HP (projectile with hit points, 18 spells), MATERIAL_CONVERT (convert/ignite materials in a radius, 19), HIT_EFFECT (on-hit conditional effect, 19), PHYS_BODY (rigid-body projectile, 13), SIDE_ENTITY (spawn data-defined entity on explosion/hit, 12), HOMING (10), AREA_EFFECT (field applying a game effect, 8), SEA_SPAWNER (8), EXPLODE_ON_DAMAGE (6), ARC (4), PASSIVE_CARD (4), LIGHTNING (3), TELEPORT_PROJ (3), AREA_DAMAGE (2), VERLET tentacle (2), PROXIMITY mine (2), SHIELD (2), RNG_PICK (2), LEVITATION, CELL_EATER (Matter Eater), SINE_WAVE (1 each). Source: TX `features`.

**SPELL-R41 D2 families and deferral.** D2 splits into engine-level logic (42: Add-Trigger/Timer/Expiration 3, Divide 4, Greek+Duplicate 8, Requirement 4, Random 8, Plicate 7, Refresh/Cessation/All-Spells 3, caster-state formulas 5) and entity scripts (143, mostly 20-60 Lua lines each). 13 Ocarina/Kantele note spells (song-matching easter egg) and 15 summoned-creature spells are DEFER candidates. Do not implement a D2 spell by approximating its script from the wiki text alone; read `spell_actions_lua.json` / `raw/game/scripts_lua/`. Source: TX `family`; DF-4.

**SPELL-R42 Classification caveat.** TX inspected the main projectile XML and each modifier's extra-entity XML saved in `raw/game`. Not saved: side entities (`load_this_entity`/`spawn_entity` targets) and the extra-entity XMLs of CLUSTERMOD, REMOVE_BOUNCE, CASTER_CAST, HITFX_PETRIFY: those 4 and the 12 SIDE_ENTITY spells are UNVERIFIED. Source: TX `_meta.caveat`.

**SPELL-R43 Determinism.** Spells that call the engine RNG (RANDOM_*, DRAW_RANDOM*, DAMAGE_RANDOM, ZETA, FIREWORK colour, SUMMON_EGG, Chain Spell scatter, shuffle) must draw from the seeded `spells` RNG stream (benchmark.md DET-R04), never from frame-number seeds (`GameGetFrameNum`). Source: GA; benchmark.md.

**SPELL-R44 Loader obligations.** Parse and keep: `spawn_requires_flag` (100 spells, 37 distinct flags), `spawn_manual_unlock` (3), spawn levels 0-7 and 10 with parallel probabilities (16 spells have all-zero probability: RAINBOW_TRAIL, SEA_SWAMP, 13 note spells, SUMMON_PORTAL; never random loot), `ai_never_uses` (6), `is_dangerous_blast` (6). Source: SJ `tier`.

### F. MVP scope

**SPELL-R45 MVP-50.** The 50 spells of KN-2 (`research/mvp50.json`, ranks 1-50) are implemented first: 35 D0, 6 D1 (BOMB, DYNAMITE, FIREBALL, LIGHTNING, NUKE, HOMING), 9 D2 (BLACK_HOLE, DECELERATING_SHOT, PIERCING_SHOT, PINGPONG_PATH, CHAIN_SHOT, ADD_TRIGGER, ADD_TIMER, DIVIDE_2, RESET). Together they exercise: all 3 trigger kinds, multicast, every modifier family, set-mode cast delay, negative mana, deck surgery, physics-body, scripted and ray projectiles. Tests cite SPELL-R ids and the TV-* vectors below. Source: `mvp50.json`; S §6; TX.

### G. Materials and multi-projectile spells

**SPELL-R46 Material spell kinds.** 26 spells: 5 sprays (MATERIAL_ACID/BLOOD/CEMENT/OIL/WATER: `MATERIAL_PARTICLE` projectile, v123-135, L360+-7, mana 0, cd-15, rc-10; Blood 250 uses), 1 chunk (SOILBALL, L1), 4 circles (CIRCLE_ACID/FIRE/OIL/WATER: emitter at the caster, `create_real_particles`, ray-traced circle image `circle_256`, L260), 8 seas (SEA_*: `MaterialSeaSpawnerComponent` area 300 x 256 px at offset (0,158), speed 10, L300, mana 140, 2-3 uses), 8 touches (TOUCH_*: `MagicConvertMaterialComponent` converts all materials in a circle (water: r20, gold: r10; steps 4 and 2 per frame) plus entities in r30, L4, mana 190-300, 1-5 uses). Source: `deck/material_*.xml`, `sea_water.xml`, `touch_water.xml`, `touch_gold.xml`, `circle_water.xml`.

**SPELL-R47 Multi-projectile spells.** `projectiles_added` has several entries for BALL_LIGHTNING 3, EXPLODING_DUCKS 3, FREEZING_GAZE 12, MEGALASER 6, BUCKSHOT 3, SWARM_FIREBUG 3, SWARM_FLY 4, SWARM_WASP 5, SUMMON_WANDGHOST 2; they share the shot state. Add-Trigger and Plicate copy `related_projectiles[0]` x (`related_projectiles[1]` or 1) and ignore the target's own cast delay, recharge, crit and spread. Source: SJ; GA.

## Key numbers

### KN-1 Constants

| Constant | Value | Unit | Rule / source |
|---|---|---|---|
| Frame rate | 60 | fps | R02 |
| HP / damage display multiplier | 25 (player hp 4.0 = 100) | x | R03 |
| Default mana cost | 10 | mana | R06 |
| Mana / uses range | -100..600 / 1..250 | mana / uses | R06, R07 |
| Recursion limit | 2 | nesting | R21 |
| Speed multiplier clamp | 0..20 (not for Fly Up/Down) | x | R09 |
| Terminal velocity | 1000 (Lightning 61440, Cursed Orb 400, Expanding Orb 200) | px/s | R23 |
| Default projectile speed / damage | 60..60 px/s / 1.0 (=25) | px/s, internal | R05 |
| Default gravity_y / air_friction / mass | 400 / 0.55 / 0.05 | px/s^2?, 1/s?, - | R05, R24 |
| Air friction per frame | v -= 0.016666567 v friction | px/s | R24 UNVERIFIED |
| Default explosion damage / radius | 5 (=125) / 20 | internal / px | R05 |
| Default ray_energy / max durability / cell prob | 20000 / 10 / 5 (fire) | - | R05, R31 |
| Explosion minimum damage by radius | 32-63: 325, 64-127: 375, >= 128: 500 | display dmg | R33 |
| Crit base multiplier / formula | 5 / `1 + min(c,1)(5 max(1,c) - 1)(1 - resist)` | x | R29, ED §2.3 |
| Player multipliers | explosion 0.35, holy 1.5, others 1.0 | x | R34 |
| Material durability | sand 4, coal 8, soil/dense rock 10, rusted steel 11, steel 12, dense steel 13, brickwork 14 (the wiki also lists concrete 8; the game data has `concrete_static` durability 0 and the clone follows the data: materials-reactions.md MAT-R12, D7) | level | ED, `noita-engine-constants.json` |
| Cast delay floor / max rate | 1 f / 60 casts/s | f | R16 |
| Set-mode cast delay | CHAINSAW 0, NUKE 20, NUKE_GIGA 50 | f | R16 |
| Trigger timer frames | 4, 10x3, 20x2, 40x3, 100, 200 | f | R18 |
| Pattern degrees | Y 45, T 90, W 20, I/Pentagon/Hexagon 180, Divide 5 | deg | R20 |
| Homing (spell) | targeting_coeff 130, velocity_multiplier 0.86 (component defaults 160 / 0.9, detect 150 px, tag `homing_target`) | - | `misc/homing.xml`, HomingComponent doc |
| Black hole | eat radius 12 px; pull radius 150; force 196(150-d)/150 added to velocity per frame, physics bodies x0.2 x mass | px, px/s | `black_hole.xml`, `black_hole_gravity.lua` |
| Ping-pong | execute every 13 f, then clamp(map(\|v\|, 60..600 -> 50..4), 4, 50); vx = -0.85 vx; vy = -0.85 vy - 0.1\|v\|; off if \|v\| < 60 | f, px/s | `pingpong_path.lua` |
| Decelerating / Accelerating shot | air_friction +6 / -3, applied once | 1/s | `decelerating_shot.lua`, `accelerating_shot.lua` |
| Chain Spell | up to 4 respawns (5 generations incl. original; wiki "5 times" counts generations); respawn at the death point with the old velocity +-10 per axis (+-400 if speed < 20); copies carry no modifiers | - | `chain_shot_launch.lua` |
| Requirement thresholds | IF_ENEMY >= 15 `homing_target` within 240 px; IF_PROJECTILE >= 20 projectiles within 160 px; IF_HP hp/max <= 0.25; IF_HALF alternates via a global toggle | - | GA |
| Plicate copies / mana / uses | Hexa 6/130/20, Penta 5/110/20, Quad 4/90/20, T 3/60/25, W 3/70/20, I 2/40/30, Y 2/40/30 | - | GA |
| Caster-state spells | BLOOD_MAGIC hp -0.16 (floor 0.04) +100 mana; BLOOD_TO_POWER costs 20 % hp as curse damage (needs hp >= 0.4 and 20 % of hp > 0.2, i.e. hp > 1.0 = 25 display) and adds min(0.44 hp, 960) damage; MONEY_MAGIC spends 5 % gold (cap 24000, min 10), damage = gold/25, /35 (>=120), /45 (>=300), /55 (>=500); DAMAGE_FOREVER mana above 50 -> +0.025 dmg per mana, mana set to 50; DAMAGE_RANDOM +0.4 x Random(-3,4) x Random(0,2) | internal | GA |
| Spawn tiers | 0-7 and 10; 100 flagged, 16 zero-probability; spell x tier pairs: tier 4 300, 2 287, 3 272, 5 268, 6 189, 1 184, 10 126, 0 77, 7 8 | - | R44 |
| Recoil SET (22 spells) | ARROW 30, CURSED_ORB 40, DISC_BULLET 20, BOUNCY_ORB(+_TIMER) 20, EXPANDING_ORB 20, BALL_LIGHTNING 120, FIREWORK 120, ROCKET 120, ROCKET_TIER_2 160, ROCKET_TIER_3 180, GRENADE(+_TRIGGER) 80, GRENADE_ANTI 80, GRENADE_LARGE 80, GRENADE_TIER_2 120, GRENADE_TIER_3 140, LANCE(+_HOLY) 60, LIGHTNING 180, MINE(+_DEATH_TRIGGER) 60 | recoil | SJ `action_effects_raw.recoil_set` |
| Lifetime modifiers | CHAIN_SHOT -30, LIFETIME +75, LIFETIME_DOWN -42, PINGPONG_PATH +25, ORBIT_SHOT +25, SPIRALING_SHOT +50, PHASING_ARC +80, TRUE_ORBIT +80, ZERO_DAMAGE +280 | f | SJ |
| Damage types in the catalogue | base projectiles: projectile 69, explosion 58, fire 12, slice 7, melee 6, electricity 4, drill 3, ice 2, healing 2, holy 2; modifiers: projectile 20, explosion 9, electricity 2, fire 1, ice 1, null_all 1; no spell uses curse or radioactive | spells | SJ |
| Frequent tags | friendlyfire 127, digging 116, mattergen 60, piercing 55, altlife 46, scripted 33, projkiller 32, penetrating 26, neverunlimited 25, speedmodify 22, recursive 19, triggerfail 19 | spells | SJ `tags` |

### KN-2 MVP-50 behaviour constants (damage in display units; `ray`/`dur`/`cell` = ConfigExplosion ray_energy / max_durability / create_cell_probability)

Kinematics: `v` px/s, `L` lifetime frames (+-random), `g/f/m` = gravity_y / air_friction / mass, `b` = bounces. Card effects are the spell's own `c.*` deltas (cd = cast delay, rc = recharge, rec = recoil; `=` marks SET).

| # | game_id (name) | mana / uses | Kinematics | Damage and explosion | Card effect on shot | Special |
|---|---|---|---|---|---|---|
| 1 | LIGHT_BULLET (Spark Bolt) | 5 / inf | v750-850 L40+-7 g200 f1.7 m.04 | proj 3; blast r2 dmg0 ray4e5 dur8 cell0, hole on | cd+3, spread-1, crit+5, shake+.5 | dies on hit; blast on death/lifetime-out; no self-dmg; kb0 |
| 2 | LIGHT_BULLET_TRIGGER | 10 / inf | as 1 | as 1 | cd+3, crit+5 | collision trigger, payload draw 1 |
| 3 | LIGHT_BULLET_TIMER | 10 / inf | as 1 | as 1 | cd+3, crit+5 | timer 10 f (25 % of L) or hit; payload draw 1 |
| 4 | BULLET (Magic Arrow) | 20 / inf | v600-650 L40+-7 g200 f1.2 m.07 spread.6 | proj 10; blast as 1 | cd+4, spread+2, crit+5, rec+23, shake+2 | kb1.8, impulse 1500 |
| 5 | ROCKET (Magic Missile) | 70 / 10 | v70-100 L360+-7 g50 f-5 m.05 (accelerates) | proj 75 + expl 105; r15 ray4e6 dur10* cell10; hurts caster | cd+60, rec=120, ragdoll2 | kb3, physics blast 1.0-1.4, emits smoke |
| 6 | SLOW_BULLET (Energy Orb) | 30 / inf | v180-240 L50+-7 g0 f1 m.09 spread1.7 | proj 11.25 + expl 4.5; r15 ray3.5e5 dur10* cell0 | cd+6, spread+3.6, rec+20, shake+2 | kb2.8, impulse 4000 |
| 7 | SPITTER (Spitter Bolt) | 5 / inf | v400-600 L25+-7 g200 f2.7 m.02 b10 (always, e.5) | proj 7.5; blast r2 dmg0 hole OFF | cd-1, spread+6 | kb1 |
| 8 | RUBBER_BALL (Bouncing Burst) | 5 / inf | v650-750 L750+-7 g250 f.6 m.03 b10 (always, e.9) spread.6 | proj 3 speed-scaled; no blast | cd-2, spread-1 | dies at v<5; kb.4 |
| 9 | BOUNCY_ORB (Energy Sphere) | 20 / inf | v400-500 L750+-7 g250 f.6 m.05 b5 (e.5*) spread.6 | proj 5 + slice 5 speed-scaled; blast on death only r2 ray2e5 dur8 | cd+10, rec=20 | dies at v<20; kb1.6 |
| 10 | BOMB | 25 / 3 | physics body (throw coeff .75), v60*, L180+-0 | expl 125 r60 ray6e6 dur11 cell40, phys 2.2-3.6; hurts caster | cd+100 | 3 s fuse; hp 12.5 (can be shot); loose_ground side entity; D1 |
| 11 | DYNAMITE | 50 / 16 | physics body (throw coeff 2.5), v800, L50 | expl 62.5 r28 dur11 ray6e6* cell0* | cd+50, spread+6 | smoke; D1 |
| 12 | GRENADE (Firebolt) | 50 / 25 | v250-280 L500+-7 g400* f.55* m.065 b4 (e.5*) spread2.9 | proj 32.5 + fire 12.5 + expl 47.5; r7 ray3.5e5 dur10* cell30; hurts caster | cd+30, shake+4, child speed x.75, rec=80 | kb1; emits fire+smoke |
| 13 | FIREBALL | 70 / 15 | v160-170 L60 g100 f.55* m.09 | expl 50 + fire 6.25; r15 ray5e4 dur10* cell100 (fire); hurts caster | cd+50, spread+4, rec+20 | ignites materials in r15 while flying (5 steps/frame); dies at low v; kb1.5; D1 |
| 14 | LIGHTNING (Lightning Bolt) | 70 / inf | ray: v5400 (wiki), L2, no terminal cap, on_collision_die 0 | expl 125 (default) + electricity 25; r35 cell1; hurts caster | cd+50, rec=180 | piercing; blast config in LightningComponent; D1 |
| 15 | DIGGER (Digging Bolt) | 0 / inf | v0 L2 | drill 7.5; blast r6 dmg0 ray1e5 dur10 cell0 | cd+1, rc-10 | collects materials to shooter |
| 16 | CHAINSAW | 1 / inf | v0-400 L1 | slice 12.75; blast r3 ray2e4 dur10* | cd=0 (SET), spread+6, rc-10 | digs soft material |
| 17 | LUMINOUS_DRILL | 10 / inf | v1400 (cap 1000?) L2 m1.65 f0 | proj 10; no blast; ground_penetration_coeff 4, max durability 14 | cd-35, rc-10 | drills almost everything |
| 18 | LASER_LUMINOUS_DRILL | 30 / inf | as 17 | as 17 | cd-35, rc-10 | timer 4 f > L2: payload at carrier end (UNVERIFIED; S says ~93 px) |
| 19 | BLACK_HOLE | 180 / 3 never_unlimited | v40 L120+-7 g0 f-.2 m.3; no world/entity collision; friendly fire | no damage, blast r1 ray0 | cd+80, shake+20 | eats all non-`[indestructible]` cells and dynamic bodies in r12; pulls projectiles in r150; D2 |
| 20 | NUKE | 200 / 1 (flag `card_unlocked_nuke`) | v300 L360+-7 g120 f1e-5 m.2 spread.6 | proj 75 + expl 250; r250 ray6.7e6 dur12 cell5, phys 4.5-9; hurts caster | cd=20 (SET), speed x.75, rc+600, rec+300, shot material fire 60, gore+10, shake+10.5 | kb1.5; loose_chunks; emits radioactive liquid + smoke; D1 |
| 21 | EXPLOSION | 80 / inf | static, v0 L0 | expl 68.75 r15 ray2e5 dur10* cell80 (fire); hurts caster | cd+3, shake+2.5 | spawned at caster |
| 22 | DELAYED_SPELL | 20 / inf | v26 L100 g0, penetrate entities, no collision death | none | cd+10 | death trigger, payload draw 3 |
| 23-25 | MATERIAL_WATER / OIL / ACID | 0 / inf | v123-135 L360+-7, dies on liquid or hit | none; emits 1 particle on death (acid 6) | cd-15, rc-10 | water adds status wet, oil oiled |
| 26 | CIRCLE_FIRE | 20 / 15 | emitter at caster, L260 | real fire pixels in a ray-traced circle (`circle_256`) | cd+20 | stops at walls |

| # | game_id (name) | mana | Card effect (modifier; all draw 1) | Special |
|---|---|---|---|---|
| 27 | SPEED | 3 | speed x2.5 | clamp [0,20] |
| 28 | DECELERATING_SHOT | 10 | speed x1.68, cd-8, rec-10 | script once: air_friction +6 (D2) |
| 29 | DAMAGE (Damage Plus) | 5 | proj dmg +10, cd+5, rec+10, gore+5 | cosmetic sparks |
| 30 | HEAVY_SHOT | 7 | proj dmg +43.75, speed x.3, cd+10, rec+50, gore+10 | |
| 31 | CRITICAL_HIT | 5 | crit +15 points | |
| 32 | SPREAD_REDUCE | 1 | spread -60 | |
| 33 | LIFETIME (Increase Lifetime) | 40 | lifetime +75, cd+13 | |
| 34 | HOMING | 70 | attaches homing.xml | HomingComponent 130 / 0.86 (D1) |
| 35 | BOUNCE | 0 | bounces +10 | |
| 36 | PIERCING_SHOT | 140 | proj dmg -15, friendly_fire = true | script once: on_collision_die = 0 (D2) |
| 37 | PINGPONG_PATH | 0 | lifetime +25 | reflect script (see KN-1) (D2) |
| 38 | CHAIN_SHOT (Chain Spell) | 70 | lifetime -30, proj dmg -5, radius -5 (clamp >= 0), spread +10 | respawn script (see KN-1) (D2) |
| 39 | EXPLOSIVE_PROJECTILE | 30 | radius +15, expl dmg +5, cd+40, speed x.75, rec+30 | triggers R33 floors |
| 40 | FIRE_TRAIL | 10 | trail fire +10, status on fire | |
| 41 | WATER_TRAIL | 10 | trail water +20, status wet | |
| 42 | RECHARGE (Reduce Recharge Time) | 12 | cd-10, rc-20 | |
| 43 | MANA_REDUCE (Add Mana) | -30 | cd+10 | wand gains 30 mana when drawn |
| 44-46 | BURST_2 / 3 / 4 | 0 / 2 / 5 | draw 2 / 3 / 4 | one shared shot state |
| 47 | ADD_TRIGGER | 10 | deck surgery (WM §10.1) | flag `card_unlocked_mestari`; payload draw 1 |
| 48 | ADD_TIMER | 20 | as 47 with timer 20 f | same flag; ADD_DEATH_TRIGGER is the death variant |
| 49 | DIVIDE_2 | 35 | cd+20, proj dmg -5, radius -5 (>= 0), pattern = 5 | runs next card twice; copies' cd/rc discarded; flag `card_unlocked_musicbox` |
| 50 | RESET (Wand Refresh) | 20 | rc-25 | moves hand+deck to discard, one re-deal per click; flag `card_unlocked_mestari` |

### KN-3 Catalogue counts: primitive x implementation class (TX)

| Primitive | D0 | D1 | D2 | Total | Notes |
|---|---|---|---|---|---|
| PROJ | 38 | 37 | 25 | 100 | |
| TRIGGER | 17 | 4 | 1 | 22 | + ADD_* (3) and TELEPORT_CAST, SUPER_TELEPORT_CAST, LONG_DISTANCE_CAST counted under UTILITY: `wraps_trigger` = 28 |
| STATIC | 5 | 8 | 30 | 43 | |
| MATERIAL | 10 | 15 | 1 | 26 | 5 sprays, 1 soil, 4 circles, 8 seas, 8 touches (S §4.1 mis-split this) |
| MODIFIER | 40 | 40 | 62 | 142 | RANDOM_MODIFIER counted under UTILITY |
| MULTICAST | 14 | 0 | 0 | 14 | |
| UTILITY | 3 | 6 | 66 | 75 | other 42 + utility 25 + passive 5 + RANDOM_PROJECTILE/STATIC_PROJECTILE/MODIFIER |
| **Total** | **127** | **110** | **185** | **422** | by raw `type`: projectile 54/41/27, static 6/8/31, modifier 40/40/63, multicast 14/0/0, material 10/15/1, utility 1/2/22, passive 0/4/1, other 2/0/40 (D0/D1/D2) |

### KN-4 Spell types in the engine

| `type` | Enum | Count | Draws | Charges a use when | Engine role |
|---|---|---|---|---|---|
| projectile | 0 | 122 | 0 (trigger: payload draws 1-3) | click had a projectile | `add_projectile*`; sets `got_projectiles`; perk extra-modifiers run |
| static_projectile | 1 | 45 | 0 | click had a projectile | entity at caster/target: explosion, field, cloud, summon, wall |
| modifier | 2 | 143 | 1 (142) | click had a projectile | edits the shot state `c`, then `draw_actions(1)` |
| multicast | 3 | 14 | 2,3,4,5,6,8, all remaining | click had a projectile | `draw_actions(N)` + spread/pattern tweak |
| material | 4 | 26 | 0 | click had a projectile | sets `got_projectiles`; emits material (R46) |
| other | 5 | 42 | 0 or 1 | always | deck/hand/discard logic, copies, requirements, random, notes |
| utility | 6 | 25 | 0 or 1 | always | teleport casts, walls, All-*, Plicate, Wand Refresh, caster-state formulas |
| passive | 7 | 5 | 1 | click had a projectile | card entity active while the wand is held |

## Data files

### DF-1 Files

| File (under `.trellis/tasks/10-16-noita-cogbench/research/`) | Records | Use |
|---|---|---|
| `spells.json` | 422 objects, 64 keys each, sorted by type then name | the catalogue (DF-2). Load: `Vec<SpellRecord>` keyed by `game_id`. |
| `spell_taxonomy.json` | 422 rows + `_meta` | `game_id, type, primitive, base_primitive, impl (D0/D1/D2), features[], scripts[], family, wraps_trigger, reason, notes[]`. Regenerate: `python3 scripts/classify_spells.py <out>`. |
| `mvp50.json` | 50 ordered rows | `rank, id, game_id, name, type, category, why`; join to `spells.json` by `game_id`. |
| `spell_actions_lua.json` | 422 `{GAME_ID: action() body}` | authoritative behaviour of all D2 code; do not paste into deliverables. |
| `spell_behaviors_from_gun_actions.json` | 491 rows (422 live) | independent regex parse: `fire_rate_wait` ops/set, `draw_actions_calls`, `triggers`, `sets_dont_draw_actions`, `touches_deck_hand_discard`, `uses_check_recursion`. Cross-check only: its `current_reload_time_ops` wrongly counts commented-out lines (10 spells: GRENADE*, ROCKET*, FIREWORK...). |
| `validation_report.json` | 44 mismatches | game-vs-wiki (31 tier, 5 damage, 4 cast delay, 2 uses, 1 mana, 1 price). |
| `wand-cast-test-cases.json` | 32 cases | casting fixtures (see "Casting fixtures and behaviour vectors"). |
| `raw/game/entities/**`, `raw/game/scripts_lua/**` | 442 XML, 135 Lua | projectile XML and scripts (Nolla data: facts only). |

### DF-2 `spells.json` fields (units; C = canonical game value, W = wiki display value, D = derived by the extractor)

| Field(s) | Type / unit | Prov. | Notes |
|---|---|---|---|
| `id`, `game_id` | string | C | key = `game_id`; `id` = lowercase |
| `name` / `name_ingame` | string | W / C | `name_ingame` from `common.csv`; null for FUNKY_SPELL ("???") |
| `type` | enum 8 values | C | R01 |
| `description` | string | C | translation |
| `mana_drain` | mana | C | default 10 (R06) |
| `max_uses`, `never_unlimited` | int or null, bool | C | R07 |
| `damage` | {type: display dmg} | W | keys projectile, explosion, fire, electricity, ice, slice, drill, melee, holy, healing; no curse/radioactive spell exists; = XML x 25 except 10 spells (DF-3) |
| `damage_modifier` | {type: display dmg} | C | `c.damage_*_add` x 25 + `null_all`; wiki-only values merged for script-applied cases |
| `explosion_radius` / `explosion_radius_modifier` | px | W / C | modifier = `c.explosion_radius` add; blank for non-projectiles |
| `projectile_speed` | {min,max} px/s | W | |
| `lifetime` / `lifetime_modifier` | {frames, random_plus_minus, min, max, alt_component_lifetime} / frames | W / C | -1 infinite |
| `spread_degrees` / `spread_modifier` | deg | W / C | modifier number or `{set}` |
| `cast_delay_modifier` | {frames, seconds, mode add/set} | C | 279 spells; mode set = 3 |
| `recharge_time_modifier` | {frames, seconds} | C | 44 spells |
| `speed_multiplier`, `child_speed_multiplier` | x | C | 21 / 11 spells |
| `crit_chance` | percent points | C | 13 spells |
| `bounces` / `bounces_modifier` | int | W / C | wiki omits XML bounces for 7 spells (DF-3) |
| `knockback` / `knockback_modifier` | - | W/XML / C | |
| `recoil` | - | C | SET value (22 spells) else add |
| `trigger`, `triggers_added`, `projectiles_added` | object / calls | C | `trigger = {type collision/timer/death, timer_frames, draw_count, count}` |
| `draw_count`, `draw_scope` | int or `"all_remaining"`; `same_cast` / `trigger_payload` | D | |
| `adds_projectile` | bool | D | false -> wiki damage/radius columns are modifier amounts |
| `pattern_degrees`, `dampening`, `gravity_modifier`, `friendly_fire`, `lightning_count`, `screenshake`, `gore_particles`, `ragdoll_fx`, `material(_amount)`, `trail_material(_amount)` | misc `c.*` | C | |
| `extra_entities`, `game_effect_entities`, `related_projectiles`, `related_extra_entities`, `custom_xml_file`, `sprite`, `sound_loop_tag` | paths | C | `related_projectiles[0]` is what Add-Trigger/Plicate copy; `[1]` = count (default 1) |
| `tier` | {spawn_levels[], spawn_probabilities[], spawn_requires_flag, spawn_manual_unlock} | C | R44 |
| `price` | gold | C | |
| `tags` | strings | W | 47 wiki tags; `scripted` marks only 33 spells: not a code flag |
| `recursive`, `ai_never_uses`, `is_dangerous_blast` | bool | C | |
| `complex_logic` | bool | D | R39 |
| `action_effects_raw` | {c_add, c_mul, c_set, c_append, recharge_*, recoil_*, draw}, internal units | D | unconditional lines only for complex spells |
| `projectile_xml` | raw XML summary of the MAIN projectile, internal units (219 spells) | C | defects: nested `config_explosion` of `<Base>` not merged (DYNAMITE misses ray 6e6, cell 0); `ground_penetration_coeff` dropped; `damage_by_type_raw` wrong for DIGGER (0.01, XML has 0.3); explosion in `LightningComponent` ignored |
| `wiki` | Cargo extras | W | gravity 400 / air_friction 0.55 shown when XML omits them (now confirmed defaults, R05) |
| `notes` | strings | D | |

### DF-3 Wiki-vs-XML conflicts (recomputed over the 184 spells with a ProjectileComponent; XML wins)

| Field | Count | Spells |
|---|---|---|
| projectile damage | 10 | DISC_BULLET_BIGGER (wiki 5, script), GRENADE_LARGE (XML 50, wiki 95), MAGIC_SHIELD / BIG_MAGIC_SHIELD (wiki 1.25 / 2.25, XML 0), GLUE_SHOT (2.5 vs 3), MEGALASER (125 vs 25), WORM_SHOT (2.5 vs 0), WALL_* x3 (0 vs 32.25, script) |
| bounces | 7 | wiki 0, XML >0: CURSED_ORB 2, PIPE_BOMB_DEATH_TRIGGER 4, EXPLODING_DEER 4, MISSILE 1, MINE 4, MINE_DEATH_TRIGGER 4; MEGALASER XML 0, wiki 10 |
| innate spread | 6 | ANTIHEAL, LANCE_HOLY, EXPLODING_DEER, FISH, MISSILE (wiki 0), WORM_SHOT (wiki 20, XML 0) |
| speed | 4 + 6 | HEAL_BULLET (625 vs 600), MISSILE (80 vs 80-160), TENTACLE(_TIMER) (8 vs 480); BOMB, BOMB_HOLY(_GIGA), TNTBOX(_BIG) show the default 60 and LIGHTNING 5400 with no XML speed |
| lifetime | 2 | MEGALASER (32 vs 180), METEOR_RAIN (120 vs 100) |
| damage attribute absent | 1 | CRUMBLING_EARTH (Earthquake) has no `damage` in its ProjectileComponent: engine default 1.0 (=25) vs wiki none (UNVERIFIED which is right) |
| rounding / omission | 3 | ICEBALL ice 6.25 vs 6, DISC_BULLET_BIGGER slice 37.5 vs 38, METEOR_RAIN fire 56.25 vs wiki 0 |

### DF-4 Taxonomy lists (TX; full rows in `spell_taxonomy.json`; effort = estimate from script length: S <= 30 Lua lines, M 30-70, L > 70 or creature AI)

**D2 engine-level logic (42)** lives in the casting engine, not in entities:

| Family | n | Members | What it does |
|---|---|---|---|
| add-trigger | 3 | ADD_DEATH_TRIGGER, ADD_TIMER, ADD_TRIGGER | Walk the deck from the top, run modifiers for free (draw suppressed), stop at the first card with `related_projectiles`, discard the walked cards, emit a trigger projectile (hit / timer 20 f / death) whose payload draws 1; no valid payload -> call the target plainly (WM §10.1). |
| divide | 4 | DIVIDE_10, DIVIDE_2, DIVIDE_3, DIVIDE_4 | Run the next card N times (first copy cannot draw), iteration limits per Divide, restore cast delay/recharge at the chain head, discard the consumed cards, apply damage/radius penalties and pattern 5 (WM §9.3). |
| greek-copy | 8 | ALPHA, GAMMA, MU, OMEGA, PHI, SIGMA, DUPLICATE, TAU | Call cards from discard/hand/deck by position or type (Alpha first discarded, Gamma last deck, Tau two next, Mu modifiers, Phi projectiles, Sigma statics, Omega everything except RESET, Duplicate the hand); recursion limit 2 (WM §11). |
| requirement | 4 | IF_ENEMY, IF_HALF, IF_HP, IF_PROJECTILE | Scan the deck for IF_ELSE/IF_END, discard the skipped branch, then draw 1; conditions: IF_ENEMY, IF_PROJECTILE, IF_HP, IF_HALF (global toggle). IF_END/IF_ELSE alone are D0 markers. |
| random | 8 | RANDOM_PROJECTILE, RANDOM_STATIC_PROJECTILE, RANDOM_MODIFIER, DRAW_RANDOM, DRAW_RANDOM_X3, DRAW_3_RANDOM, RANDOM_SPELL, ZETA | Pick a random card (any action, or from deck+discard) honouring recursion/flags and call it; DRAW_RANDOM_X3 calls it 3 times; ZETA copies a random spell from the other wands. Needs the seeded `spells` RNG (R43). |
| plicate | 7 | HEXA_SHOT, I_SHOT, PENTA_SHOT, QUAD_SHOT, T_SHOT, W_SHOT, Y_SHOT | Peek `deck[1]`; if it has `related_projectiles` and uses left, add its projectile k-1 more times paying its mana each (stop when short), set `pattern_degrees`, then draw 1. |
| deck-surgery | 3 | RESET, CESSATION, ALL_SPELLS | RESET: hand+deck to discard, one re-deal per click; CESSATION: +600 cast delay and recharge, 20 f stall; ALL_SPELLS: spawn the all-spells loader, +100 cast delay and recharge. |
| state-formula | 5 | DAMAGE_FOREVER, DAMAGE_RANDOM, BLOOD_MAGIC, BLOOD_TO_POWER, MONEY_MAGIC | Shot-state modifier reading/writing caster hp, gold or wand mana, or rolling RNG (constants in KN-1). |

**D2 entity-script families (143)** (`*` = extra-entity XML missing locally, UNVERIFIED):

| Family | n | Members | What the original script does | Effort |
|---|---|---|---|---|
| trajectory-script | 32 | ACCELERATING_SHOT, HOMING_ACCELERATING, HOMING_CURSOR, AUTOAIM, AVOIDING_ARC, LARPA_CHAOS, CHAOTIC_ARC, LARPA_CHAOS_2, DECELERATING_SHOT, ROCKET_DOWNWARDS, LARPA_DOWNWARDS, ORBIT_FIREBALLS, FIZZLE, FLOATING_ARC, FLY_DOWNWARDS, FLY_UPWARDS, HORIZONTAL_ARC, LINE_ARC, NOLLA, ORBIT_NUKES, ROCKET_OCTAGON, ORBIT_LARPA, ORBIT_SHOT, PHASING_ARC, PINGPONG_PATH, ORBIT_LASERS, HOMING_AREA, QUANTUM_SPLIT, ORBIT_DISCS, SPIRALING_SHOT, TRUE_ORBIT, LARPA_UPWARDS | per-frame or periodic velocity/position rewrite of the carrier (arcs, orbits, fly up/down, accelerate/decelerate, phasing, true orbit, Larpa splits, quantum split, scripted homing) | S-M |
| summoned-creature | 15 | BOMB_CART, TENTACLE_PORTAL, EXPLODING_DUCKS, EXPLODING_DEER, FISH, PEBBLE, WORM_RAIN, SWARM_FIREBUG, SWARM_FLY, FRIEND_FLY, SWARM_WASP, X_RAY, SUMMON_WANDGHOST, TINY_GHOST, SUMMON_PORTAL | spawns an AI entity (flies, ducks, worms, fish, deer, rock spirit, ghosts, cart, portals, X-ray) | L, DEFER |
| projectile-rewriter | 15 | CHAIN_SHOT, RANDOM_EXPLOSION, TRANSMUTATION, CLUSTERMOD*, EXPLOSION_TINY, CLIPPING_SHOT, CRUMBLING_EARTH_PROJECTILE, ESSENCE_TO_POWER, LARPA_DEATH, ZERO_DAMAGE, PIERCING_SHOT, LASER_EMITTER_WIDER, REMOVE_BOUNCE*, EXPLOSION_REMOVE, SPELLS_TO_POWER | one-shot edit of the carrier at spawn (damage, explosion, lifetime, bounce, collision) or at death (Chain Spell respawn, Larpa explosion) | S |
| easter-egg-notes | 13 | KANTELE_A, KANTELE_D, KANTELE_DIS, KANTELE_E, KANTELE_G, OCARINA_A, OCARINA_A2, OCARINA_B, OCARINA_C, OCARINA_D, OCARINA_E, OCARINA_F, OCARINA_GSHARP | note projectile + song-matching script (portal/bomb/worm/alchemy magic) | DEFER |
| on-bounce-spawner | 8 | BOUNCE_SPARK, BOUNCE_LASER, BOUNCE_EXPLOSION, BOUNCE_LARPA, BOUNCE_LIGHTNING, BOUNCE_LASER_EMITTER, BOUNCE_SMALL_EXPLOSION, BOUNCE_HOLE | spawns an effect at each bounce point (spark, laser, lightning, explosion, hole, Larpa) | S |
| black-white-hole | 7 | BLACK_HOLE, BLACK_HOLE_DEATH_TRIGGER, WHITE_HOLE, BLACK_HOLE_BIG, WHITE_HOLE_BIG, BLACK_HOLE_GIGA, WHITE_HOLE_GIGA | CellEater + pull/push of projectiles and physics bodies; Big/Giga add loose ground, area damage, polymorph | M |
| misc-projectile-script | 7 | CHAIN_BOLT, EXPANDING_ORB, GRENADE_ANTI, DARKFLAME, SPIRAL_SHOT, THUNDERBALL*, WORM_SHOT | one-off carrier scripts (Chain Bolt, Expanding Orb, Odd Firebolt, Dark Flame, Spiral Shot, Thunder Charge, Worm Launcher) | M |
| spells-to-x | 6 | ALL_ACID, ALL_BLACKHOLES, ALL_DEATHCROSSES, ALL_DISCS, ALL_ROCKETS, ALL_NUKES | replaces every other `projectile`-tagged entity in the world with the target projectile and kills the original without an explosion (the rocket variant picks tier 1/2/3 at random) | M |
| teleport-cast | 5 | TELEPORT_PROJECTILE_CLOSER, HOOK, CASTER_CAST*, TELEPORT_CAST, SUPER_TELEPORT_CAST | moves the cast or the carrier (teleport/warp/inner spell/hook) | M |
| cloud-emitter | 5 | CLOUD_ACID, CLOUD_BLOOD, CLOUD_OIL, CLOUD_WATER, CLOUD_THUNDER | cloud entity snapped to the surface (raycast 40 px up) emitting a material or lightning | S |
| ray-thrower | 5 | FIREBALL_RAY, LIGHTNING_RAY, LASER_EMITTER_RAY, TENTACLE_RAY, FIREBALL_RAY_LINE | modifier attaching a periodic ray/fireball emitter to the carrier | M |
| misc-world-script | 5 | DESTRUCTION, BOMB_DETONATOR, METEOR_RAIN, MASS_POLYMORPH, TOUCH_GRASS | one-off world edits (Destruction, Explosive Detonator, Meteor rain, Mass polymorph, Touch of Grass) | M |
| laser-beam | 4 | MEGALASER, LASER_EMITTER, LASER_EMITTER_FOUR, LASER_EMITTER_CUTTER | multi-ray laser emitters | M |
| electric-field-script | 3 | ELECTROCUTION_FIELD, THUNDER_BLAST, PURPLE_EXPLOSION_FIELD | periodic lightning / field scripts | S |
| wall-builder | 3 | WALL_HORIZONTAL, WALL_SQUARE, WALL_VERTICAL | builds a material wall or box | S |
| vacuum-field | 3 | VACUUM_LIQUID, VACUUM_POWDER, VACUUM_ENTITIES | sucks liquids, powders or entities to its centre | M |
| projectile-field | 3 | PROJECTILE_GRAVITY_FIELD, PROJECTILE_THUNDER_FIELD, PROJECTILE_TRANSMUTATION_FIELD | affects projectiles in a radius (gravity, thunder, transmutation) | M |
| orbiting-shield | 2 | BIG_MAGIC_SHIELD, MAGIC_SHIELD | shield projectiles orbiting the caster | M |
| sawblade-script | 2 | DISC_BULLET_BIG, DISC_BULLET_BIGGER | trajectory + damage + cell-eater scripts | M |

**D1 by feature (110 spells; a spell can need several features):**

| Feature | n | Spells | Meaning |
|---|---|---|---|
| MATERIAL_CONVERT | 19 | AIR_BULLET, FIREBALL, FREEZING_GAZE, ICEBALL, FREEZE_FIELD, BLOOD_TO_ACID, FREEZE, STATIC_TO_SAND, LAVA_TO_BLOOD, LIQUID_TO_EXPLOSION, TOXIC_TO_ACID, WATER_TO_POISON, TOUCH_BLOOD, TOUCH_GOLD, TOUCH_PISS, TOUCH_OIL, TOUCH_SMOKE, TOUCH_ALCOHOL, TOUCH_WATER | convert/ignite/freeze materials inside a radius (MagicConvertMaterialComponent) |
| HIT_EFFECT | 19 | HITFX_TOXIC_CHARM, HITFX_CRITICAL_BLOOD, HITFX_BURNING_CRITICAL_HIT, HITFX_CRITICAL_OIL, HITFX_CRITICAL_WATER, HITFX_EXPLOSION_ALCOHOL, HITFX_EXPLOSION_SLIME, HITFX_EXPLOSION_ALCOHOL_GIGA, HITFX_EXPLOSION_SLIME_GIGA, FIREBALL_RAY_ENEMY, GRAVITY_FIELD_ENEMY, LIGHTNING_RAY_ENEMY, TENTACLE_RAY_ENEMY, HITFX_PETRIFY, CURSE, CURSE_WITHER_ELECTRICITY, CURSE_WITHER_EXPLOSION, CURSE_WITHER_MELEE, CURSE_WITHER_PROJECTILE | on-hit conditional effect (crit on status, explosion on status, curses, personal rays) |
| PROJ_HP | 18 | ACIDSHOT, BOMB, PIPE_BOMB, PIPE_BOMB_DEATH_TRIGGER, DYNAMITE, BOMB_HOLY_GIGA, GLITTER_BOMB, BOMB_HOLY, POLLEN, PROPANE_TANK, SUMMON_ROCK, SLIMEBALL, SUMMON_EGG, TNTBOX, SUMMON_HOLLOW_EGG, TNTBOX_BIG, MINE, MINE_DEATH_TRIGGER | projectile entity with hit points that can be shot or burnt |
| PHYS_BODY | 13 | BOMB, DYNAMITE, BOMB_HOLY_GIGA, GLITTER_BOMB, BOMB_HOLY, PROPANE_TANK, SUMMON_ROCK, SUMMON_EGG, TNTBOX, SUMMON_HOLLOW_EGG, TNTBOX_BIG, TEMPORARY_PLATFORM, TEMPORARY_WALL | rigid-body projectile (throw coefficient, fuse, rolling) |
| SIDE_ENTITY | 12 | BOMB, CRUMBLING_EARTH, FLAMETHROWER, DEATH_CROSS_BIG, BOMB_HOLY_GIGA, NUKE_GIGA, GLITTER_BOMB, GLUE_SHOT, BOMB_HOLY, METEOR, NUKE, SPORE_POD | spawn a data-defined entity on explosion/hit (loose ground, glue, spore pod) |
| HOMING | 10 | DEATH_CROSS, DEATH_CROSS_BIG, POLLEN, MISSILE, ANTI_HOMING, HOMING_SHOOTER, HOMING, HOMING_ROTATE, HOMING_SHORT, HOMING_WAND | steering towards `homing_target` (HomingComponent) |
| AREA_EFFECT | 8 | LEVITATION_FIELD, TELEPORTATION_FIELD, BERSERK_FIELD, SHIELD_FIELD, FREEZE_FIELD, POLYMORPH_FIELD, CHAOS_POLYMORPH_FIELD, REGENERATION_FIELD | field applying a game effect to entities in a radius |
| SEA_SPAWNER | 8 | SEA_ACID, SEA_ALCOHOL, SEA_ACID_GAS, SEA_LAVA, SEA_MIMIC, SEA_OIL, SEA_WATER, SEA_SWAMP | fills a large area with a liquid over time |
| EXPLODE_ON_DAMAGE | 6 | PROPANE_TANK, SUMMON_ROCK, SUMMON_EGG, TNTBOX, SUMMON_HOLLOW_EGG, TNTBOX_BIG | explodes when its hit points run out |
| ARC | 4 | ARC_ELECTRIC, ARC_FIRE, ARC_GUNPOWDER, ARC_POISON | electric/fire/poison/gunpowder arc along the path |
| PASSIVE_CARD | 4 | TORCH_ELECTRIC, ENERGY_SHIELD, ENERGY_SHIELD_SECTOR, TORCH | effect carried by the wand-attached card entity (light, shield) |
| LIGHTNING | 3 | BALL_LIGHTNING, LIGHTNING, ARC_ELECTRIC | instant lightning ray / ball lightning |
| TELEPORT_PROJ | 3 | TELEPORT_PROJECTILE_STATIC, TELEPORT_PROJECTILE_SHORT, TELEPORT_PROJECTILE | teleports the caster to the carrier |
| RNG_PICK | 2 | FIREWORK, SUMMON_EGG | seeded pick of one of a fixed list of entity files |
| AREA_DAMAGE | 2 | INFESTATION, AREA_DAMAGE | periodic damage to entities in a box |
| VERLET | 2 | TENTACLE, TENTACLE_TIMER | rope-physics tentacle weapon |
| PROXIMITY | 2 | MINE, MINE_DEATH_TRIGGER | explodes when something comes near (mine) |
| SHIELD | 2 | SHIELD_FIELD, ENERGY_SHIELD_SHOT | energy shield component |
| LEVITATION | 1 | LEVITATION_FIELD | levitation field |
| CELL_EATER | 1 | MATTER_EATER | removes cells in a radius |
| SINE_WAVE | 1 | SINEWAVE | sinusoidal motion component |

**D0 by type (127):**

* projectile 54: FUNKY_SPELL, ARROW, MIST_BLOOD, RUBBER_BALL, BUBBLESHOT, BUBBLESHOT_TRIGGER, CHAINSAW, LASER, CURSED_ORB, ANTIHEAL, POWERDIGGER, DIGGER, DISC_BULLET, GRENADE_LARGE, SLOW_BULLET, SLOW_BULLET_TIMER, SLOW_BULLET_TRIGGER, BOUNCY_ORB, BOUNCY_ORB_TIMER, GRENADE, GRENADE_TRIGGER, FIREBOMB, GRENADE_TIER_3, ROCKET_TIER_3, SPITTER_TIER_3, SPITTER_TIER_3_TIMER, LANCE, HEAL_BULLET, LANCE_HOLY, GRENADE_TIER_2, ROCKET_TIER_2, SPITTER_TIER_2, SPITTER_TIER_2_TIMER, LUMINOUS_DRILL, LASER_LUMINOUS_DRILL, BULLET, BULLET_TIMER, BULLET_TRIGGER, HEAVY_BULLET, HEAVY_BULLET_TIMER, HEAVY_BULLET_TRIGGER, ROCKET, MIST_ALCOHOL, GLOWING_BOLT, MIST_SLIME, LIGHT_BULLET, LIGHT_BULLET_TRIGGER_2, LIGHT_BULLET_TIMER, LIGHT_BULLET_TRIGGER, SPITTER, SPITTER_TIMER, SWAPPER_PROJECTILE, MIST_RADIOACTIVE, BUCKSHOT
* static_projectile 6: DELAYED_SPELL, EXPLOSION, FIRE_BLAST, POISON_BLAST, ALCOHOL_BLAST, EXPLOSION_LIGHT
* material 10: MATERIAL_ACID, MATERIAL_BLOOD, MATERIAL_CEMENT, SOILBALL, CIRCLE_ACID, CIRCLE_FIRE, CIRCLE_OIL, CIRCLE_WATER, MATERIAL_OIL, MATERIAL_WATER
* modifier 40: ACID_TRAIL, MANA_REDUCE, GRAVITY_ANTI, BLOODLUST, COLOUR_BLUE, BOUNCE, BURN_TRAIL, CRITICAL_HIT, DAMAGE, ELECTRIC_CHARGE, EXPLOSIVE_PROJECTILE, FIRE_TRAIL, UNSTABLE_GUNPOWDER, GRAVITY, COLOUR_GREEN, GUNPOWDER_TRAIL, HEAVY_SHOT, HEAVY_SPREAD, LIFETIME, COLOUR_INVIS, KNOCKBACK, LIGHT, LIGHT_SHOT, NECROMANCY, OIL_TRAIL, COLOUR_ORANGE, POISON_TRAIL, COLOUR_PURPLE, COLOUR_RAINBOW, RAINBOW_TRAIL, RECOIL, RECOIL_DAMPER, COLOUR_RED, LIFETIME_DOWN, RECHARGE, SPREAD_REDUCE, SLOW_BUT_STEADY, SPEED, WATER_TRAIL, COLOUR_YELLOW
* multicast 14: SCATTER_2, BURST_2, T_SHAPE, I_SHAPE, Y_SHAPE, CIRCLE_SHAPE, PENTAGRAM_SHAPE, W_SHAPE, BURST_X, BURST_8, SCATTER_4, BURST_4, SCATTER_3, BURST_3
* utility 1: LONG_DISTANCE_CAST
* other 2: IF_END, IF_ELSE

### DF-5 Runtime shape the loader must produce per primitive

| Primitive | Runtime record | Fields (from `spells.json` / XML, internal units) |
|---|---|---|
| PROJ | `ProjectileSpec` + `CardDelta` | speed[min,max], lifetime(f,+-r), gravity_y, air_friction, mass, terminal_velocity, bounces{n,energy,always}, collide{world,entities,die_on_hit,penetrate}, die_on_low_velocity{limit}, damage{type: v}, scaled_by_speed, explosion?{radius, damage, ray_energy, max_durability, cell{material,prob}, hole, dont_damage_shooter, physics_power}, knockback, impulse, innate spread, emitters, features[] |
| TRIGGER | `Trigger{kind, timer_frames, draw_count, count}` + the PROJ/STATIC it wraps | payload = fresh `ShotState` filled by `draw_count` draws at cast time |
| STATIC | `StaticSpec` | entity ref, explosion?, field/emitter params, lifetime, features[] |
| MATERIAL | `MaterialSpec{kind spray/circle/sea/touch/soil, material, amount, lifetime, area/radius}` | R46 |
| MODIFIER | `CardDelta` | add/mul/set/append over every `c.*` field, recharge add, recoil add/set, draw 1, attached extra entities + game effects + trail |
| MULTICAST | `CardDelta` | draw N (or all remaining), spread add, pattern set |
| UTILITY | `Custom(handler_id)` + `CardDelta` | handler registry keyed by `game_id`/family (DF-4); D0 markers need none |

## Worked examples / test vectors

### Data derivation vectors (TV-D)

| ID | Input | Expected |
|---|---|---|
| TV-D1 | `LIGHT_BULLET` XML `damage 0.12` | display 3 = `damage.projectile`; explosion damage 0 |
| TV-D2 | `ROCKET` XML damage 3, explosion damage 4.2 | proj 75, expl 105 |
| TV-D3 | `LIGHTNING` has no explosion `damage` attribute | explosion 125 (ConfigExplosion default 5 x 25) + electricity 1.0 x 25 = 25 |
| TV-D4 | `BOMB` has no `speed_*` attribute | speed 60..60 (default); radius 60, ray 6,000,000, dur 11, cell 40 |
| TV-D5 | `DYNAMITE` (SJ `explosion` lacks ray_energy) | effective ray 6,000,000 and cell prob 0 from `base_projectile_physics.xml`; damage 2.5 x 25 = 62.5 |
| TV-D6 | `DIGGER` `damage_by_type_raw.drill` 0.01 in SJ | use `damage.drill` 7.5 (XML 0.3 x 25) |
| TV-D7 | any spell, `cast_delay_modifier.frames` | equals the sum of `+/-` ops in the behaviours json (verified 0 mismatches over 422) |

### Shot-state vectors (TV-S; wand cast delay 0, mana unlimited unless stated)

| ID | Slots | Expected |
|---|---|---|
| TV-S1 | [DAMAGE, LIGHT_BULLET] | proj damage 3 + 10 = 13; cast delay 5 + 3 = 8 f; crit 5 %; recoil +10; mana 5 + 5 = 10 |
| TV-S2 | [HEAVY_SHOT x2, LIGHT_BULLET] | damage 3 + 87.5 = 90.5; speed multiplier 0.09 -> 67..76 px/s; cast delay 20 + 3 |
| TV-S3 | [SPEED x4, LIGHT_BULLET] | multiplier 2.5, 6.25, 15.625, then 39.06 clamped to 20; initial speed 15000..17000 -> terminal cap 1000 px/s |
| TV-S4 | [BURST_2, LIGHT_BULLET, NUKE] | NUKE sets cast delay 20 after the +3 -> 20 f; order [BURST_2, NUKE, LIGHT_BULLET] -> 23 f |
| TV-S5 | [BURST_2, LIGHT_BULLET, CHAINSAW] | cast delay 0 (SET) -> acts as 1 f |
| TV-S6 | [EXPLOSIVE_PROJECTILE, BOMB] | final `c.explosion_radius` 15 > 0 -> radius 60 + 15 = 75 (floor 375); damage = max(125 + 5, 375) = 375; cast delay 40 + 100 |
| TV-S7 | [EXPLOSIVE_PROJECTILE, LIGHT_BULLET] | radius 2 + 15 = 17 < 32: no floor; damage 0 + 5 = 5; `on_death_explode` forced on |
| TV-S8 | [CRITICAL_HIT, LIGHT_BULLET] | crit 20 %; expected damage multiplier 1 + 0.2 (5 - 1) = 1.8 |
| TV-S9 | [CHAIN_SHOT, BULLET] | lifetime 40 - 30 = 10 (+-7); damage 10 - 5 = 5; `c.explosion_radius` -5 clamped to 0 (base radius 2 unchanged, no damage floor); up to 4 unmodified copies (L 40+-7, damage 10) spawned at the death point |
| TV-S10 | [DECELERATING_SHOT, LIGHT_BULLET] | speed x1.68 (1260..1428 -> cap 1000); air_friction 1.7 + 6 = 7.7 after frame 1; cast delay 3 - 8 = -5 -> 1 f |
| TV-S11 | [RANDOM_EXPLOSION (modifier, 30 uses), LIGHT_BULLET] | the click produced a projectile: RANDOM_EXPLOSION uses 30 -> 29 (modifier charged); wand [RANDOM_EXPLOSION] alone: no projectile, uses stay 30; [ROCKET] alone: 10 -> 9 per click |
| TV-S12 | [LIGHT_BULLET_TIMER, DAMAGE, SPITTER] | carrier Spark Bolt (L 40), timer 10 f; payload SPITTER with damage +10 in the payload state only; payload cast delay ignored |
| TV-S13 | [BOUNCE, SPITTER] | bounces 10 + 10 = 20 (energy 0.5 each); cast delay -1; mana 0 + 5 |
| TV-S14 | [LIFETIME, LIGHT_BULLET] | lifetime 40 + 75 = 115 (+-7); cast delay 13 + 3 = 16; mana 40 + 5 |
| TV-S15 | [FIRE_TRAIL, LIGHT_BULLET] | trail material fire x10, status on fire applied to hits; mana 10 + 5; cast delay 3 |
| TV-S16 | [SPREAD_REDUCE, BULLET] | spread 0.6 + 2 - 60 < 0 -> 0; recoil +23; cast delay 4 |
| TV-S17 | [RECHARGE, LIGHT_BULLET], wand recharge 30 | recharge 30 - 20 = 10 f; cast delay 3 - 10 = -7 -> 1 f; mana 12 + 5 |
| TV-S18 | [MANA_REDUCE, ROCKET], wand mana 50 | drawing Add Mana lifts mana 50 -> 80, ROCKET (70) is then affordable, 10 left; cast delay 10 + 60 = 70; without Add Mana ROCKET would be skipped |

### Casting fixtures and behaviour vectors (TV-B)

* Reuse `research/wand-cast-test-cases.json` (32 cases): draw_01-06, tuple_01-02, spc_01, shuffle_01, mana_01-02, divide_01-05, greek_01-03, addtrigger_01-04, refresh_01-03, always_cast_01-03, timing_01-02. Known defect: `draw_01_multicast_modifier.mana_spent` is 10 but the catalogue gives BURST_2 0 + DAMAGE 5 + 2 x LIGHT_BULLET 5 = 15; fix the fixture before using it.
* TV-B1 Black hole at pull distance d: velocity += 196 (150 - d) / 150 per frame toward the hole: d 0 -> 196, d 75 -> 98, d >= 150 -> 0; physics bodies get the same x0.2 x mass.
* TV-B2 Ping-pong at |v| 600 -> interval 4 f, 330 -> 27 f, 60 -> 50 f, < 60 -> script disabled; first run after 13 f; each run `vx' = -0.85 vx`, `vy' = -0.85 vy - 0.1 |v|`.
* TV-B3 Requirement spells: [IF_HP, X, IF_ELSE, Y, IF_END]: hp/max > 0.25 -> X dropped to discard up to the else-point, Y runs; hp/max <= 0.25 -> X runs, from else-point to end-point discarded. A nested `IF_*` met during the scan resets the end-point: a skip then discards only the next card.
* TV-B4 Classification: LIGHT_BULLET D0, BURST_X D0 (flag false positive), COLOUR_RED D0, HOMING D1, BOMB D1, DIVIDE_2 D2, BLACK_HOLE D2; counts D0 127, D1 110, D2 185.

## Pitfalls and common misreadings

1. **Display damage is not stored damage.** `damage.projectile 3` is XML 0.12; `c.damage_projectile_add 0.4` is "+10". Mixing units silently scales damage by 25.
2. **A missing XML attribute is the engine default, not 0**: no `damage` means 25 display, no `ray_energy` means 20000, no `create_cell_probability` means 5 % fire cells (Spark Bolt writes 0 explicitly). Empty `explosion` summaries hide `LightningComponent` and `<Base>` explosion settings.
3. **Names lie.** Spark Bolt = LIGHT_BULLET, Magic Arrow = BULLET, Magic Bolt = HEAVY_BULLET, Magic Missile = ROCKET, Firebolt = GRENADE, Energy Orb = SLOW_BULLET, Energy Sphere = BOUNCY_ORB, Bouncing Burst = RUBBER_BALL, Triplicate Bolt = BUCKSHOT, Add Mana = MANA_REDUCE (a modifier), Damage Plus = DAMAGE, Critical Plus = CRITICAL_HIT, Wand Refresh = RESET, Double Spell = BURST_2, Thunder Charge = THUNDERBALL, Concentrated Light = LASER, "Touch of Gold?" = TOUCH_PISS. "Summon Lava" does not exist (SEA_LAVA); "Slow Down" does not exist.
4. **Triggers are not a spell type.** The 28 trigger spells are projectiles/static/utility/other with a payload; `trigger.count`/`draw_count` come from the wrapper, not from `type`. The earlier draft `type` list of benchmark.md (projectile/modifier/multicast/trigger) was a simplification of this; benchmark.md Data files now points to this catalogue.
5. **Cast delay is not additive across the board**: set-mode spells overwrite it, payload deltas vanish, copy spells restore it, and the floor is 1 frame. Recharge is the opposite: everything counts, including payloads.
6. **Modifier order does not matter for arithmetic, but does for SET and clamps** (Nuke before/after Spark Bolt; `speed_multiplier` clamp after each modifier; radius clamps after Light Shot/Chain Spell/Divide By).
7. **Uses are charged to the whole hand**, including modifiers and multicasts, whenever the click produced a projectile; a limited OTHER/UTILITY card is charged even without one.
8. **A positive `c.explosion_radius` changes the damage model**: forced explosion on death and a 325/375/500 damage floor by radius range; Chain Spell/Light Shot/Divide By can zero it again.
9. **Terminal velocity eats speed**: 4 Speed Up already hit 1000 px/s; Luminous Drill (1400) and Spark Bolt (750-850 x 2.5) are capped; excess initial speed is "absorbed" by speed-reducing modifiers. Lightning Bolt and Fly Up/Down are the exceptions.
10. **Speed-scaled damage uses the speed at hit time vs the speed at end of frame 1**, and also scales added damage; Heavy Shot + Rubber Ball multiplies the bonus.
11. **Timers do not "fire at N frames" unconditionally**: they fire at the first of N frames, collision or death (LASER_LUMINOUS_DRILL timer 4 f exceeds its 2 f lifetime), once. Death triggers of stationary or terrain-killed carriers fire in a random direction.
12. **Chain Spell is a modifier, not a trigger.** "Up to 5 times" counts generations: 4 respawns; the copies carry no modifiers (no Chain, no Nuke delay...).
13. **`complex_logic` and `tags: scripted` are not "needs code" markers** (R39); count D2 from TX.
14. **Wiki fields are display values**: 30+ conflicts with XML (DF-3). `damage_by_type_raw` of DIGGER is wrong; DYNAMITE explosion misses base values.
15. **`ProjectileComponent.friction` is not `VelocityComponent.air_friction`.** spells.md calls Firebolt's `friction 0.6` air friction; air friction is the default 0.55. Semantics of `friction` UNVERIFIED.
16. **Physics-body projectiles (Bomb, Dynamite, boxes) are rigid bodies**: the XML/wiki speed (Bomb 60) is the default, not the throw speed; they have hit points (12.5 display) and can be shot or lava-damaged.
17. **Colours, screenshake, gore, ragdoll and sounds are cosmetic** (8 COLOUR_* spells are D0); recoil is not cosmetic (it moves the player) and `child_speed_multiplier` matters for triggers/Chain.
18. **Mana is checked before the spell runs and negative cost adds mana**, so Add Mana can enable later spells in the same cast; an unaffordable last card still eats a draw.
19. **Random spells are random per frame in the original** (frame-number seeds); the clone must use the seeded `spells` stream or replays diverge.
20. **Do not use `spell_behaviors_from_gun_actions.json` for recharge** (counts commented lines) and do not load its 69 non-live rows. S §4.1 mis-splits material counts (real: 5 sprays, 1 soil, 4 circles, 8 seas, 8 touches) and S §4.2 says 109 flagged spells while SJ has 100 (37 distinct flags; the difference is unexplained).

## Our simplifications (MVP)

* **S1 Scope ladder.** Implement MVP-50 (35 D0 + 6 D1 + 9 D2), then all D0 (127), then D1 features by spell count (PROJ_HP, MATERIAL_CONVERT, HIT_EFFECT, PHYS_BODY...), then D2 families by value for wand-building tasks (deck-ops 42 first: they create the combinatorial depth). benchmark.md plans ~300 spells: D0+D1 = 237, so ~60 D2 are needed. DECISION-NEEDED: which 60 (suggest deck-ops 42 + trajectory 12 + holes 6).
* **S2 Damage storage unit.** DECISION-NEEDED: store internal floats exactly as XML (bit-faithful to `damage_*_add`) or display values (agent-readable, benchmark.md OBS-R05 shows wand-editor numbers). Recommendation: internal in `noita_core`, display in observations.
* **S3 Physics bodies.** Bomb, Dynamite, boxes, rocks, eggs, crates as kinematic "rolling" bodies in the pixel sim (gravity, bounce, friction, fuse, hit points) instead of Box2D. DECISION-NEEDED: accept the divergence in rolling/throw behaviour.
* **S4 Terrain carving.** Use the sibling model (DAMAGE-R21: rays spend `ray_energy`, durability gate, fire cells) or a simplified disc carve with a durability cut-off. DECISION-NEEDED (depends on the materials KB); loose-ground collapse (R35) is optional in MVP.
* **S5 Progress flags.** All 422 spells are unlocked in the benchmark (ignore `spawn_requires_flag`); keep the field for fidelity. DECISION-NEEDED: gating by flag in a future "exploration" task variant.
* **S6 Cosmetics dropped.** Particles, sprites, sounds, screenshake, gore, ragdoll, light, colour spells: parsed, ignored. Recoil, knockback, status effects and material emission are kept.
* **S7 Deferred D2.** Easter-egg notes (13), summoned creatures (15), X-ray/portal/wand ghost, Zeta (needs other wands), Cessation/All-Spells until the wand KB is stable.
* **S8 Statuses.** Only a minimal status set (wet, oiled, bloody, on fire, frozen, poisoned/toxic, electricity stun) with the rules of `entities-damage.md`; `game_effect_entities` of other spells map to the nearest status or are ignored with a logged warning.
* **S9 Perks and extra modifiers** (`gun_extra_modifiers.lua`) are not modelled; always-cast cards follow WM §8.
* **S10 Source of truth.** Runtime `noita_core/data/spells.json` is generated from `research/spells.json` + `spell_taxonomy.json`, game file over wiki, version pinned (R10). benchmark.md's earlier draft spell schema (`type` with `trigger`, `requires_spells[]`, `inherits_velocity`, ~300 spells) was replaced in its Data files table by a pointer to this catalogue; the exact runtime schema stays DECISION-NEEDED. `content_hash` covers the file, so field renames bump benchmark versions.

## Open questions

1. Integrator: order of gravity, air friction and terminal velocity per frame; unit of `gravity_y` (R24). UNVERIFIED.
2. Whether `lifetime_randomness` is an inclusive integer uniform draw and how `lob_min/lob_max`, `ProjectileComponent.friction` act (R08, pitfall 15).
3. Spread semantics: +-spread or total arc; shot-state spread vs `direction_random_rad` composition (R09).
4. Does a 2-frame, 1400 px/s carrier (Luminous Drill) travel 47 px or 33 px (terminal cap at spawn), and where does its 4 f timer payload spawn (S says ~93 px; Timer wiki implies lifetime end)? (KN-2 rows 17-18)
5. Explosion damage falloff with distance inside the radius; interaction of the R33 floor with `damage_explosion_add` when a Divide By lowers the radius.
6. Negative projectile damage: Chain Spell (-5) or Piercing Shot (-15) on Spark Bolt (3): clamp at 0 or negative (heal)? Not stated anywhere read.
7. Side-entity XMLs (loose_ground, loose_chunks, glue, spore_pod_growing, thunderburst...) and 4 extra-entity XMLs not saved: classification and behaviour of 16 spells UNVERIFIED (R42).
8. Which side is current for PROJECTILE_THUNDER_FIELD/GRAVITY_FIELD uses (6 vs 3) and VACUUM_POWDER mana (40 vs 50) (R10).
9. Whether the unconditional `c.*` lines of the 44 genuinely complex spells are complete in `action_effects_raw` (only unconditional lines are parsed; read `spell_actions_lua.json` per spell).
10. What exactly `PROJ_HP` projectiles (Bomb hp 12.5) take damage from, and whether Explosive Detonator/Fizzle semantics (trick kills, explosions without shooter) are in scope.
11. `Fly Upwards/Downwards` clamp bypass magnitude (script not read).
12. `spells.json` schema for the runtime file (S10) and whether `draw_count`/`trigger` should be exposed to agents.
13. CRUMBLING_EARTH direct-hit damage: XML omits `damage` (default 25 display) while the wiki lists none (DF-3).

## Sources

Research files (all under `./.trellis/tasks/10-16-noita-cogbench/research/`): `spells.md`, `spells.json`, `spell_taxonomy.json` (new, derived), `scripts/classify_spells.py` (new), `scripts/extract_spells.py`, `mvp50.json`, `spell_behaviors_from_gun_actions.json`, `spell_actions_lua.json`, `validation_report.json`, `wand-cast-test-cases.json`, `wand-mechanics.md`, `wand-generation.md`, `entities-damage.md`, `damage-types.json`, `noita-engine-constants.json`; raw game data `raw/game/gun.lua`, `gun_actions.lua`, `gun_enums.lua`, `gunaction_generated.lua`, `entities/projectiles/**` (bomb, deck/*, base_projectile*.xml), `entities/misc/**`, `scripts_lua/projectiles/**`; sibling KB pages `./.trellis/spec/game-design/entities-damage.md`, `benchmark.md`.

Wiki (noita.wiki.gg, local copies `raw/<Page>.wikitext`): https://noita.wiki.gg/wiki/Spells, /Spell_Information_Table, /Explosion_interactions, /Terminal_Velocity, /Speed, /Trigger, /Timer, /Expiration_Trigger, /Chain_Spell, /Spells_With_Damage_Scaled_By_Speed, /Bomb, /Digging, /Expert_Guide:_Draw, /Tuple_Spell, /Documentation:_ProjectileComponent, /Documentation:_VelocityComponent, /Documentation:_ConfigExplosion, /Documentation:_LightningComponent, /Documentation:_HomingComponent, /Documentation:_ConfigDamagesByType; Cargo export `https://noita.wiki.gg/wiki/Special:CargoExport?tables=Spells&format=json` (via `raw/cargo_Spells_export_v2.json`).

Game data mirror: https://github.com/NathanSnail/noitadata (`data/scripts/gun/gun_actions.lua`, `gun.lua`, `data/entities/**`, `data/scripts/projectiles/**`).
