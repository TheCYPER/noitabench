# Noita Spell Catalogue - schema, extraction method, counts, MVP-50

Research deliverable for the Noita-like Rust project (task `10-07-noita-clone`).
Companion files (all under `.trellis/tasks/10-16-noita-cogbench/research/`):

| File | What it is |
|---|---|
| `spells.json` | **422 spells**, one object each, merged from the game's own `gun_actions.lua`, the wiki Cargo table, the wiki infobox wikitext and the projectile XMLs. ~1.6 MB. |
| `spell_actions_lua.json` | `{GAME_ID: "<exact Lua body of the spell's action()>"}` for all 422 spells. The authoritative behaviour for the 56 spells flagged `complex_logic`. |
| `mvp50.json` | Ordered list of the 50 spells recommended for the first implementation pass (ids, type, one-line rationale). |
| `validation_report.json` | Game-vs-wiki cross-checks: 44 mismatches (listed below), 0 ids missing on either side. |
| `scripts/extract_spells.py` | The extractor. Re-runnable: `cd research && python3 scripts/extract_spells.py`. |
| `raw/` | Everything fetched: wikitext, Cargo exports, the game data files, projectile XMLs and Lua scripts (see "Sources"). |

Everything below is quantitative and was produced mechanically unless marked **UNVERIFIED**.

---

## 1. Where the data comes from

### 1.1 Canonical: the game's own data files (`raw/game/`)

Noita's spells are defined in **`data/scripts/gun/gun_actions.lua`**, a Lua table `actions = { {...}, {...} }` with one entry per spell. The GitHub repository **NathanSnail/noitadata** mirrors the game's `data/` folder ("Up to date (hopefully) Noita beta branch data files"). The copy used here:

* `gun_actions.lua`: 410,637 bytes, 11,125 lines, **422 live entries** (491 `id =` lines, of which the rest are inside `--[[ ]]--` comment blocks). File last changed in that repo on **2024-04-05** (commit `67110c35`), i.e. the April 2024 beta. The wiki's own history note "Apr 8 2024: Spark Bolt With Timer tier-3 probability 0.5 -> 0.75" matches the value in this file (0.75), so wiki and game data are from the same era.
* `gun.lua` (671 lines): the casting engine (deck/hand/discard, mana, uses, reload, trigger helpers). Summarised in section 5.
* `gunaction_generated.lua`: `ConfigGunActionInfo_Init` = the **shot-state defaults** (section 5.2).
* `gun_enums.lua`: `ACTION_TYPE_PROJECTILE=0, STATIC_PROJECTILE=1, MODIFIER=2, DRAW_MANY=3, MATERIAL=4, OTHER=5, UTILITY=6, PASSIVE=7`.
* `gun_extra_modifiers.lua`: perk-driven extra modifiers applied to every projectile-type action (not spells, but same shot-state vocabulary).
* `data/translations/common.csv`: English names/descriptions for `$action_*` / `$actiondesc_*` keys (514 names, 517 descriptions).
* `data/entities/**` (417 files referenced by `gun_actions.lua` + 26 `<Base file=...>` parents) and `data/scripts/**` (134 Lua scripts referenced by those XMLs): per-projectile physics, damage, explosion configs and behaviour scripts.

Each `gun_actions.lua` entry has these metadata fields (counts over 422 entries): `id` 422, `name` 422, `description` 422, `sprite` 422, `type` 422, `spawn_level` 422, `spawn_probability` 422, `price` 422, `mana` 416 (default 10 when absent), `related_projectiles` 212, `related_extra_entities` 118, `custom_xml_file` 98, `max_uses` 142, `spawn_requires_flag` 109, `never_unlimited` 25, `recursive` 19, `ai_never_uses` 15, `sound_loop_tag` 10, `is_dangerous_blast` 9, `spawn_manual_unlock` 3 - plus the `action = function() ... end` body that mutates the shot state `c`.

### 1.2 Wiki: Cargo table `Spells` (noita.wiki.gg)

The wiki does **not** keep spell stats in a Lua module; every spell page carries one `{{Infobox spell}}` template call (up to 8 variants per page: `name`, `name2`, ... `name8`), and **`Template:Infobox spell` does `{{#cargo_store:_table=Spells ...}}`**, so the whole catalogue is queryable as one Cargo table.

* Table: `Spells` (also present: `SpellTags`, `Modspells`, `Materials`, `Perks`, `Enemies`, `Attacks`, `Reactions`).
* 55 declared fields (`Template:Infobox spell` `#cargo_declare`): `image, sortKey, tags (List), name, id, description, type, draw (Int), manaDrain (Float), castDelay (String), rechargeDelay (String), uses (Int), dmgEveryXFrames, hitShooterFrames, projectileCount, relatedProjCount, criticalChance, damageProjectile, damageMelee, damageElectric, damageFire, damageExplosion, radius (Float), damageIce, damageSlice, damageDrill, damageHealing, damageHoly, maxDuraToDestroy, rayEnergy, spread (Float), spreadMod, speedMin, speedMax, speedDie, speedMod, pattern, gravity, airFriction, mass, recoil, bounces, bouncesMod, lifetime, lifetimeRandom, lifetimeMod, altLifetimeMin, altLifetimeMax, timerLifetime, effect, spellTier (List), spawnProbability (List), unlockCondition, price`.
* Export used (saved as `raw/cargo_Spells_export_v2.json`, md5 `979c9a73b04fb3a5154ad339970c35f5`, **422 rows, 313 pages**):
  `https://noita.wiki.gg/wiki/Special:CargoExport?tables=Spells&fields=<all 55 fields>&format=json&limit=2000`
* The ids in the Cargo table are **exactly** the 422 ids in `gun_actions.lua` (0 missing either way).
* Fields that exist in the infobox but are **not** stored in Cargo (parsed from the raw wikitext of all 313 pages instead, `raw/all_spell_pages.json`): `damageCurse` (never used by any spell), `knockback`, `bounceAlways`, `bounceEnergy`, `destroyLiquid`, `health`, `hitbox`, `holeEnabled`, `homingCoeff`, `homingMultiplier`, `onCollisionDie`, `onDeathExplode`, `onLifeOutExplode`, `physicsImpulse`, `safeExplosion`, `terminalVelocity`, `damageMortals`, `hitEffect`, `aoeDmg*`. They are exposed under `wiki.infobox_extras`.
* `SpellTags` table (47 rows, `raw/cargo_SpellTags_export.json`) gives the meaning of every tag in `tags` (e.g. `piercing` = "can hit multiple targets multiple times", `penetrating` = "hit multiple targets, each only once", `projkiller`, `altlife`, `triggerfail`, ...).
* Category pages: the per-type categories are `Category:Spells of type Projectile` (86 pages), `Static projectile` (37), `Projectile modifier` (131), `Multicast` (3), `Material` (16), `Utility` (18), `Passive` (4), `Other` (18); these count **pages**, not variants - the Cargo row counts in section 4 are the real spell counts. The category names given in the task brief (`Projectile_Spells` etc.) do not exist (0 members).

### 1.3 Wiki prose pages used for mechanics (saved in `raw/*.wikitext`)

`Spells`, `Spell Information Table`, `Wand and Spell Tiers`, `Guide: Wand Mechanics`, `Expert Guide: Draw`, `Trigger`, `Timer`, `Expiration Trigger`, `Tuple Spell`, `Damage Types`, `Critical hit`, `Spells with limited uses`.

---

## 2. Extraction method (`scripts/extract_spells.py`)

1. **Parse `gun_actions.lua`**: strip `--[[ ]]--` blocks, split top-level `\t{ ... \t},` entries, read scalar/table metadata, isolate the `action = function(...) ... end` body.
2. **Parse each action body into shot-state effects** with line regexes after removing `-- comments` and the two boiler-plate clamps (`speed_multiplier` clamp to `[0,20]`, `explosion_radius >= 0`):
   * `c.X = c.X + N` / `- N` -> `c_add[X]`; `c.X = c.X * N` -> `c_mul[X]`; `c.X = N | true | "s"` -> `c_set[X]`; `c.X = c.X .. "s"` -> `c_append[X]`
   * `current_reload_time = current_reload_time +/- N` (with `ACTION_DRAW_RELOAD_TIME_INCREASE = 0`) -> `recharge_add`
   * `shot_effects.recoil_knockback = ... +/- N | = N` -> `recoil_add` / `recoil_set`
   * `draw_actions(N, true)` -> `draw` (N or `"all_remaining"` for `#deck`)
   * `add_projectile("path")`, `add_projectile_trigger_hit_world(path, draw)`, `add_projectile_trigger_timer(path, frames, draw)`, `add_projectile_trigger_death(path, draw)` -> `projectiles_added` / `triggers_added`
   * anything with `if/for/while/deck[...]/Random/...` -> `complex_logic = true` (56 spells). The parsed effects for those are the *unconditional* lines only; the full body is in `spell_actions_lua.json`.
3. **Join the wiki Cargo row by `id`** for projectile stats the wiki already derived from XMLs (damage by type, radius, speed, lifetime, bounces, innate spread, ...).
4. **Join the infobox variant by `id`** for the non-Cargo params above and the `tags` list.
5. **Parse the main projectile XML** (`related_projectiles[1]`, else the first `add_projectile` path) with `<Base file>` inheritance resolved (base components first, overrides inside `<Base>`, then the file's own components) and expose raw values under `projectile_xml`.
6. **Cross-validate** game vs wiki: mana, max_uses, price, type, spawn levels/probabilities, cast delay (frames/60 vs wiki seconds), modifier damage (x25 vs wiki) and XML damage x25 vs wiki -> `validation_report.json`.
7. Sort by type then name, write `spells.json`.

Decision rules worth knowing:

* `adds_projectile` = the action calls `add_projectile*` **or** the entry has `related_projectiles`. When **false**, the wiki's `damageProjectile`/`radius` columns are *modifier* amounts (Damage Plus = 10, Chain Spell radius = -5) and are placed in `damage_modifier` / `explosion_radius_modifier`, never in `damage`.
* `draw_count` + `draw_scope`: `same_cast` for `draw_actions(N)` (modifiers draw 1, multicasts draw N) and `trigger_payload` for trigger spells (the N drawn into the projectile's payload shot); projectiles that draw nothing have `0 / null`.
* Display damage = XML damage x **25** (`light_bullet.xml damage="0.12"` is shown as 3). `damage` and `damage_modifier` are in display units; `projectile_xml.*` are raw.
* Wiki `spread` (degrees) = XML `direction_random_rad` x 180/pi (0.01 rad -> 0.6 deg).

---

## 3. Schema of `spells.json`

Array of objects, sorted by `type` then `name`. Units: **frames = 1/60 s; px; px/s; degrees; display damage (= XML x 25)**. `null` = not applicable / not specified. Empty `{}` / `[]` are kept for fixed-shape fields.

| Field | Type | Meaning / source |
|---|---|---|
| `id` | string | snake_case of the game id (`spark_bolt` is `light_bullet`; **the game id is the stable key**) |
| `game_id` | string | `gun_actions.lua` id, e.g. `LIGHT_BULLET_TRIGGER` |
| `name` | string | wiki display name (Title Case); `name_ingame` is the exact `common.csv` string |
| `type` | enum | `projectile \| static_projectile \| modifier \| multicast \| material \| utility \| passive \| other` (from `ACTION_TYPE_*`; wiki `type` agrees for all 422) |
| `description` | string | in-game description (`actiondesc_*`) |
| `mana_drain` | number | `mana` (default 10). Negative = adds mana (Add Mana -30, Blood Magic -100) |
| `max_uses` | int or null | `max_uses`; null = unlimited. 142 limited spells |
| `never_unlimited` | bool | Unlimited Spells perk does not lift the limit (25 spells) |
| `damage` | object | base damage of the spell's projectile by type: keys among `projectile, explosion, fire, electricity, ice, slice, drill, melee, holy, healing` (zeros omitted; no spell has `curse` or `radioactive` damage in this data). From wiki Cargo. |
| `damage_modifier` | object | damage **added to the shot state** by the action (`c.damage_<type>_add` x25), plus `null_all` for Null Shot; wiki-only values are merged when the action applies them via script |
| `explosion_radius` | number | base explosion radius (px) of the projectile (`config_explosion.explosion_radius`) |
| `explosion_radius_modifier` | number | `c.explosion_radius +=` (clamped to >= 0 by the modifiers that reduce it) |
| `projectile_speed` | `{min,max}` | px/s, `speed_min/speed_max` |
| `lifetime` | object | `{frames, random_plus_minus, min, max, alt_component_lifetime?}`; `-1` means infinite |
| `lifetime_modifier` | number | `c.lifetime_add` frames |
| `spread_degrees` | number | innate projectile spread (deg) |
| `spread_modifier` | number or `{set}` | `c.spread_degrees +=` (deg); negative total spread behaves as 0 |
| `cast_delay_modifier` | `{frames, seconds, mode}` | `c.fire_rate_wait`; `mode` = `add` or **`set`** (Chainsaw sets 0, Nuke sets 20, Giga Nuke sets 50 - a set discards earlier accumulated delay in that shot state) |
| `recharge_time_modifier` | `{frames, seconds}` | `current_reload_time +=` (wand-wide, counted even inside trigger payloads) |
| `speed_multiplier` | number | `c.speed_multiplier *=` (clamped to [0, 20] after each modifier) |
| `child_speed_multiplier` | number | `c.child_speed_multiplier *=` (speed of spawned child projectiles) |
| `crit_chance` | number | `c.damage_critical_chance +=` (percent points) |
| `bounces` | int | innate `bounces_left` of the projectile |
| `bounces_modifier` | int | `c.bounces +=` |
| `knockback` | number | projectile `knockback_force` (infobox `knockback` if given) |
| `knockback_modifier` | number | `c.knockback_force +=` |
| `recoil` | number | `shot_effects.recoil_knockback` (set value if the action sets it, else the add) |
| `trigger` | object or null | `{type: collision\|timer\|death, timer_frames, draw_count, count}` - `count` = how many trigger projectiles are added per cast |
| `draw_count` | int or `"all_remaining"` | spells drawn (see rule above) |
| `draw_scope` | enum or null | `same_cast` / `trigger_payload` |
| `adds_projectile` | bool | see decision rule |
| `pattern_degrees`, `dampening`, `gravity_modifier`, `friendly_fire`, `lightning_count`, `screenshake`, `gore_particles`, `ragdoll_fx` | misc | the corresponding `c.*` effects |
| `material`, `material_amount` | | shot-state material spray (Nuke: fire 60) |
| `trail_material[]`, `trail_material_amount` | | trail modifiers (fire 10, water 20, oil 15, acid, poison, ...) |
| `extra_entities[]` | string[] | entity XMLs attached to every projectile of the shot (`homing.xml`, `piercing_shot.xml`, particle emitters, ...) |
| `game_effect_entities[]` | string[] | status-effect entities applied to anything hit (`effect_apply_wet.xml`, `effect_apply_on_fire.xml`, `effect_frozen.xml`, ...) |
| `projectiles_added[]`, `triggers_added[]` | | exact `add_projectile*` calls |
| `tier` | object | `{spawn_levels[], spawn_probabilities[], spawn_requires_flag, spawn_manual_unlock}`; levels are the wiki "tiers" 0-7 and 10; a flag means the spell only spawns after that progress flag is set |
| `price` | int | shop price base |
| `tags[]` | string[] | wiki tags (meanings in `raw/cargo_SpellTags_export.json`) |
| `related_projectiles[]`, `related_extra_entities[]`, `custom_xml_file`, `sprite`, `sound_loop_tag`, `ai_never_uses`, `recursive`, `is_dangerous_blast` | | raw metadata |
| `complex_logic` | bool | action body has branching/loops -> read `spell_actions_lua.json` |
| `action_effects_raw` | object | the parsed `c_add / c_mul / c_set / c_append / recharge / recoil / draw` |
| `projectile_xml` | object or null | `{path, entity_tags, components[], projectile{...}, explosion{...}, damage_by_type_raw, velocity{...}, other_components[], lua_scripts[], emits_real_materials[]}` raw XML values of the main projectile (219 spells) |
| `wiki` | object | Cargo columns not mapped above (`cast_delay_s`, `recharge_delay_s`, `spread_mod`, `speed_mod`, `lifetime_mod`, `bounces_mod`, `timer_lifetime`, `draw`, `pattern_degrees`, `speed_die_below`, `dmg_every_x_frames`, `hit_shooter_frames`, `projectile_count`, `related_proj_count`, `max_durability_to_destroy`, `ray_energy`, `gravity`, `air_friction`, `mass`, `spell_tier`, `spawn_probability`, `unlock_condition`, `effect`, `infobox_extras{}`) |
| `notes[]` | string[] | generated remarks (set-mode cast delay, never_unlimited, unlock condition, multi-projectile count, ...) |

Field coverage (non-empty, out of 422): `cast_delay_modifier` 279, `lifetime` 202, `projectile_speed` 151, `damage` 148, `max_uses` 142, `explosion_radius` 132, `knockback` 113, `recoil` 72, `spread_modifier` 69, `spread_degrees` 53, `recharge_time_modifier` 44, `bounces` 40, `trigger` 28, `damage_modifier` 23, `speed_multiplier` 21, `pattern_degrees` 18, `crit_chance` 13, `lifetime_modifier` 9, `bounces_modifier` 9.

Wiki `gravity` / `air_friction` values of 400 / 0.55 appear whenever the projectile XML does not set `VelocityComponent.gravity_y` / `air_friction`; these are the wiki's stated engine defaults (**UNVERIFIED** against the engine, consistent across all such rows).

---

## 4. Counts

### 4.1 By type (Cargo rows = game entries, identical)

| type | count | notes |
|---|---|---|
| projectile | 122 | 121 add a projectile; `FUNKY_SPELL` ("???") is scripted |
| static_projectile | 45 | 44 add an entity at the caster |
| modifier | 143 | 142 draw 1; `NULL_SHOT`-style oddities aside all are `draw_actions(1,true)` |
| multicast | 14 | draw 2 (x4: Double, Double Scatter, I-, Y-shape), 3 (x4), 4 (x2), 5, 6, 8, all-remaining |
| material | 26 | sprays (6), circles (4), seas (7), touch-of (8), Chunk of Soil |
| utility | 25 | 14 add projectiles (teleports, walls, wand ghost), 11 are pure draw/state |
| passive | 5 | Torch, Electric Torch, Energy Shield, Energy Shield Sector, Tiny Ghost |
| other | 42 | triggers x3, Divide x4, Greek x8, Requirement x6, Random x4, notes x13, Spell Duplication, Summon Portal, Cessation, All Spells |
| **total** | **422** | 313 wiki pages |

### 4.2 Other tallies

* Limited-use spells: 142 (max_uses from 1 to 250; 25 are `never_unlimited`). Mana drain range 0 ... 600 (plus -30, -100).
* Trigger spells: 28 = collision 8, timer 11 (4, 10, 10, 10, 20, 20, 40, 40, 40, 100, 200 frames), death/expiration 9. Payload draw counts: 1 everywhere except `LIGHT_BULLET_TRIGGER_2` (2) and `DELAYED_SPELL` (3).
* Spells needing a progress flag to spawn: 109 (37 distinct flags, e.g. `card_unlocked_pyramid` 9, `card_unlocked_paint` 8, `card_unlocked_duplicate` 8, `card_unlocked_ocarina` 8, ...).
* Tier usage (spell x tier pairs): tier 4: 300, 2: 287, 3: 272, 5: 268, 6: 189, 1: 184, 10: 126, 0: 77, 7: 8.
* Most common tags: friendlyfire 127, digging 116, mattergen 60, piercing 55, altlife 46, scripted 33, projkiller 32, penetrating 26, neverunlimited 25, speedmodify 22, recursive 19, triggerfail 19, transmutation 18, multi 17, pathmod 16.
* Damage types actually used by base projectiles: projectile 69 spells, explosion 58, fire 12, slice 7, melee 6, electricity 4, drill 3, ice 2, healing 2, holy 2. Modifier damage types: projectile 20, explosion 9, electricity 2, fire 1, ice 1, null_all 1. **Curse** and **radioactive** damage: no spell (the shot state has `damage_curse_add` but nothing sets it).
* `cast delay` set-mode spells: `CHAINSAW` (0), `NUKE` (20), `NUKE_GIGA` (50). Spells that *set* recoil instead of adding: 22 (Arrow 30, Magic Missile 120, Lightning 180, Firebolt 80, ...).

### 4.3 Game vs wiki cross-validation (44 mismatches, `validation_report.json`)

| Kind | Count | Explanation |
|---|---|---|
| `spawn_levels`/`spawn_probabilities` | 31 | Mostly the wiki dropping tiers whose probability is 0 (`TOUCH_*` tiers 1-4, `LIGHTNING_RAY` tier 1, ...). Real differences: `WHITE_HOLE_BIG` (0.05/0.05/0.1 vs 0.1/0.1/0.1), `BUCKSHOT` tier 4 (0.9 vs 0.6), `SPIRALING_SHOT` tier 4 (0.5 vs 0.1), `T_SHOT` levels (2,3,5 vs 1,2,3), `HITFX_CRITICAL_BLOOD`, `HITFX_TOXIC_CHARM`, `BOUNCE_LASER`, `TOUCH_PISS` (0.035 vs 0.01) - **game file wins**. |
| `damage_projectile` (XML x25 vs wiki) | 5 | `DISC_BULLET_BIGGER` (wiki 5, damage comes from a script), `GRENADE_LARGE` (50 vs wiki 95, wiki adds fire), `MAGIC_SHIELD`/`BIG_MAGIC_SHIELD` (per-shield-projectile), `GLUE_SHOT` (2.5 vs 3 rounding). |
| `cast_delay` | 4 | `TNTBOX`, `TNTBOX_BIG`: game +30 f, wiki blank; `PHASING_ARC` -12 f vs wiki -0.10 s; `SPELLS_TO_POWER` +40 f vs wiki 0.33 s (both wiki rounding/omissions). |
| `max_uses` | 2 | `PROJECTILE_THUNDER_FIELD`, `PROJECTILE_GRAVITY_FIELD`: game 6, wiki 3. **UNVERIFIED which is current** (game file is Apr-2024 beta). |
| `mana` | 1 | `VACUUM_POWDER`: game 40, wiki 50 (same caveat). |
| `price` | 1 | `COLOUR_YELLOW`: wiki has no price. |

Everything else (mana, uses, price, type, cast delay, tiers) agrees exactly for the remaining ~410 spells.

---

## 5. Casting engine facts needed to implement the catalogue (from `gun.lua`)

### 5.1 Card game loop

* Three piles: `deck`, `hand`, `discarded`. On the first shot (and every reload) `order_deck()` sorts by `deck_index` (non-shuffle) or Fisher-Yates shuffles (`shuffle_deck_when_empty`).
* `_start_shot`: `root_shot = create_shot(1)`; its state is **copied from the wand** (`ConfigGunActionInfo_Copy(state_from_game, c)` - wand cast delay / spread / speed), then `num_of_cards_to_draw = gun.actions_per_round` (spells/cast). `mana` = wand's current mana.
* `draw_actions(how_many, instant_reload_if_empty)`: repeat `how_many` times: `draw_action()`; if it returns `false` (card skipped), keep drawing until one succeeds or the deck is empty; stop if `reloading`.
* `draw_action()`:
  1. if the deck is empty: with `instant_reload_if_empty` (true for every draw made **by a spell**, false for the wand's root draw) and not `force_stop_draws`, move discard -> deck, re-order, `start_reload = true` (this is the **wrap**); otherwise `reloading = true`, return.
  2. pop `deck[1]`; cost = `action.mana` (default **10**); if `cost > mana` -> card goes straight to discard, return `false` (skipped); if `uses_remaining == 0` -> discard, return `false`; else `mana -= cost` (negative cost **adds** mana).
  3. `play_action`: push to `hand`, set `c.action_*`, run `action.action()`; if the type is projectile / static projectile / material -> `got_projectiles = true` and every active perk extra-modifier runs.
* After the root draw: `register_action(state)` passes the shot state to C++, `SetProjectileConfigs()` spawns the projectiles with the state applied.
* `_handle_reload` -> `move_hand_to_discarded()`: a card in hand **consumes one use** if (`got_projectiles` or its type is OTHER/UTILITY) and it is identified and has no `custom_uses_logic`; a card whose uses reach 0 is **not** returned to the discard (it leaves the cycle until a Spell Refresher). Then if the deck is empty or `start_reload`: discard -> deck, re-order, `StartReload(current_reload_time)`, and `current_reload_time` resets to the wand's `reload_time`.
* Cast delay: only the **root** shot state's `fire_rate_wait` is used for the real delay; recharge (`current_reload_time`) is global and accumulates from everywhere including payloads.
* Triggers: `add_projectile_trigger_hit_world / _timer(delay_frames) / _death(path, n)` = `BeginProjectile(path); BeginTrigger...; draw_shot(create_shot(n), true); EndTrigger(); EndProjectile()`. The payload gets a **fresh default shot state** (`reset_modifiers`, not the wand's stats) and its draws may wrap. Damage/speed/spread modifiers inside the payload do not leak out; recharge does.
* Always-cast cards (`_play_permanent_card`): `uses_remaining = -1`, negative mana is added, and a permanent modifier that `draw_actions(1)` on a 1-spell/cast wand does **not** draw (special rule).
* `recursion_limit = 2` for `recursive` cards when copied by Divide-By / Greek-letter spells (`check_recursion`).
* Wand slot durability table and `ACTION_DRAW_RELOAD_TIME_INCREASE = 0` are in the file but inert.

### 5.2 Shot-state defaults (`ConfigGunActionInfo_Init`)

`fire_rate_wait 0, speed_multiplier 1.0, child_speed_multiplier 1.0, dampening 1, explosion_radius 0, spread_degrees 0, pattern_degrees 0, screenshake 0, recoil 0, damage_{melee,projectile,electricity,fire,explosion,ice,slice,healing,curse,drill}_add 0.0, damage_null_all 0.0, damage_critical_chance 0, damage_critical_multiplier 0.0, explosion_damage_to_materials 0, knockback_force 0, reload_time 0, lightning_count 0, material "", material_amount 0, trail_material "", trail_material_amount 0, bounces 0, gravity 0, light 0, blood_count_multiplier 1.0, gore_particles 0, ragdoll_fx 0, friendly_fire false, physics_impulse_coeff 0, lifetime_add 0, sprite "", extra_entities "", game_effect_entities "", sound_loop_tag "", projectile_file ""`.

All 422 actions only touch this vocabulary: `fire_rate_wait` (286 assignments), `extra_entities` 122, `spread_degrees` 69, `speed_multiplier` 62, `screenshake` 60, `damage_projectile_add` 24, `game_effect_entities` 19, `pattern_degrees` 18, `explosion_radius` 16, `damage_critical_chance` 14, `child_speed_multiplier` 11, `bounces` 10, `lifetime_add` 9, `dampening` 8, `gore_particles` 8, `trail_material(_amount)` 7, `ragdoll_fx` 6, `damage_explosion_add` 5, `material(_amount)` 3, `knockback_force` 2, `gravity` 2, `friendly_fire` 2, `damage_electricity_add` 2, `damage_ice_add` 2, `rad_pattern_degrees_offset` 1, `pattern_pos_offset` 1, `damage_null_all` 1, `lightning_count` 1; plus `current_reload_time` (62) and `shot_effects.recoil_knockback` (126).

### 5.3 Formulas and constants (wiki, verified against data where possible)

* 60 frames = 1 s. Wiki cast delay / recharge seconds = frames / 60 (rounded to 2 dp).
* Displayed damage = XML `damage` x 25 (e.g. 0.12 -> 3, 0.4 -> 10, 1.75 -> 43.75).
* Critical hit: base multiplier **x5**; chance = sum of `damage_critical_chance` (percent); above 100 % every hit crits and the multiplier grows x5 per extra 100 % (`TotalDamage = Base * (1 + min(C,1) * (5*max(1,C) - 1) * (1 - CritResistance))`). Blood-stained targets +5 % per projectile-type spell in the same shot; Critical-On-X spells +100 % each.
* Spread: total = innate (`direction_random_rad` -> deg) + sum of `spread_degrees` + wand spread (+ perks/status outside payloads); negative = 0.
* `speed_multiplier` is clamped to [0, 20] after each modifier that changes it (boiler-plate in every such action). `explosion_radius` is clamped to >= 0 by Chain Spell, Light Shot, Divide-By.
* Mana is checked **before** the card runs; a card that needs more mana than available is skipped (discarded) and the next card is drawn instead, except as the last card in the deck where it still eats one draw.
* Trigger/Timer payloads: timer releases after `timer_frames` **or** on collision, whichever first; expiration (death) releases exactly once when the projectile dies; if a death trigger dies stationary its payload goes in a random direction.

---

## 6. MVP-50 - the spells to implement first

Selection: the iconic set asked for in the brief plus the minimum needed to exercise every engine feature (collision/timer/death triggers, multicast draw, modifiers for every shot-state field family, materials, deck surgery, mana negatives, set-mode cast delay, speed-scaled damage, physics-body projectiles, scripted projectiles). `mvp50.json` carries the same list. Requested spells that do not exist under that name: "Summon Lava" (closest: `SEA_LAVA` Sea of Lava, tier 10, flag `card_unlocked_sea_lava`) and "Slow Down" (closest real spells: `DECELERATING_SHOT`, or `HEAVY_SHOT`'s x0.3 speed). "Magic Bolt" is `HEAVY_BULLET` (not in the 50, Magic Arrow `BULLET` is); "Magic Missile" is `ROCKET`.

All numbers below: mana, uses, damage (display), radius px, speed px/s, lifetime frames, cast delay / recharge in frames (s), tiers = spawn levels. Flags quoted are raw XML attributes.

### 6.1 Projectiles (20)

1. **Spark Bolt** `LIGHT_BULLET` - mana 5, unlimited, 3 projectile dmg. Speed 750-850, lifetime 40 +/- 7, gravity_y 200, air_friction 1.7, mass 0.04, knockback 0. `on_collision_die=1`, explodes on death and on lifetime-out with radius 2, 0 dmg, `ray_energy 400000`, `max_durability_to_destroy 8` (chips a 2-px hole in soft terrain), `explosion_dont_damage_shooter=1`. Action: cast delay +3 f (0.05 s), spread -1 deg, crit +5 %, screenshake +0.5. Tiers 0,1,2 (p 2, 1, 0.5), price 100, tag `starter`.
2. **Spark Bolt With Trigger** `LIGHT_BULLET_TRIGGER` - mana 10, same projectile; action: cd +3 f, crit +5 (no spread bonus), `add_projectile_trigger_hit_world(light_bullet.xml, 1)`: on collision with world or entity, cast a payload of 1 drawn spell at the impact point with a fresh shot state. Tiers 0-3, price 140.
3. **Spark Bolt With Timer** `LIGHT_BULLET_TIMER` - mana 10, as above but `add_projectile_trigger_timer(light_bullet.xml, 10 frames, 1)`: payload after 10 f (0.17 s, ~25 % of lifetime) or on earlier collision. Tiers 1,2,3 (p 0.5, 0.5, 0.75), price 140.
4. **Magic Arrow** `BULLET` - mana 20, 10 dmg, speed 600-650, lifetime 40 +/- 7, innate spread 0.6 deg (0.01 rad), gravity 200, air_friction 1.2, mass 0.07, knockback 1.8, `physics_impulse_coeff 1500`, death explosion radius 2 (durability 8). Action: cd +4 f, spread +2 deg, crit +5, screenshake +2, recoil +23. Tiers 1-5, price 150.
5. **Magic Missile** `ROCKET` - mana 70, **10 uses**, 75 projectile + 105 explosion dmg, radius 15, `ray_energy 4,000,000`, `create_cell_probability 10`, physics explosion 1.0-1.4. Speed 70-100 with **air_friction -5.0 (accelerates)**, gravity 50, lifetime 360 +/- 7, knockback 3.0, `explosion_dont_damage_shooter=0` (hurts caster), emits real smoke. Action: cd +60 f (1.0 s), recoil **set 120**, ragdoll_fx 2. Tiers 1-5, price 220, tags starter/digging/friendlyfire.
6. **Energy Orb** `SLOW_BULLET` - mana 30, 11.25 projectile + 4.5 explosion, radius 15 (ray 350000), speed 180-240, lifetime 50 +/- 7, gravity 0, air_friction 1, mass 0.09, innate spread 1.7 deg, knockback 2.8, physics impulse 4000. Action: cd +6 f, spread +3.6 deg, screenshake +2, recoil +20. Tiers 1-4, price 160.
7. **Spitter Bolt** `SPITTER` - mana 5, 7.5 dmg, speed 400-600, lifetime 25 +/- 7, gravity 200, air_friction 2.7, mass 0.02, **bounces 10** (`bounce_always=1`, `bounce_energy 0.5`), knockback 1.0, death explosion radius 2 with `hole_enabled=0` (no digging). Action: cd **-1 f**, spread +6 deg. Tiers 0-3, price 110, starter.
8. **Bouncing Burst** `RUBBER_BALL` - mana 5, 3 dmg **scaled by speed** (`damage_scaled_by_speed=1`), speed 650-750, lifetime 750 +/- 7, bounces 10, `bounce_always`, `bounce_energy 0.9`, dies when speed < 5 (`die_on_low_velocity_limit 5`), gravity 250, air_friction 0.6, mass 0.03, knockback 0.4, no explosion. Action: cd -2 f, spread -1 deg. Tiers 0,1,6, price 60, starter.
9. **Energy Sphere** `BOUNCY_ORB` - mana 20, 5 projectile + 5 slice dmg, speed-scaled, speed 400-500, lifetime 750 +/- 7, bounces 5, dies below speed 20, gravity 250, air_friction 0.6, knockback 1.6, death explosion radius 2 (durability 8). Action: cd +10 f, recoil set 20. Tiers 0,2,4, price 120.
10. **Bomb** `BOMB` - mana 25, **3 uses**, physics-body projectile (`PhysicsBodyComponent is_bullet=1`, image shape material `fuse`, `DamageModelComponent hp 0.5`, takes lava damage). Lifetime 180 f (3 s fuse, no randomness), thrown at speed 60 (wiki). Explosion **125 dmg, radius 60**, `ray_energy 6,000,000`, `max_durability_to_destroy 11`, `create_cell_probability 40`, physics power 2.2-3.6. Action: cd +100 f (1.67 s). Tiers 0-6, price 200, friendly fire.
11. **Dynamite** `DYNAMITE` - mana 50, 16 uses, physics stick (`fuse_tnt`), speed 800, lifetime 50 f (0.83 s), explosion 62.5 dmg, radius 28, durability 11. Action: cd +50 f, spread +6 deg. Tiers 0-4, price 160.
12. **Firebolt** `GRENADE` - mana 50, 25 uses, 32.5 projectile + 12.5 fire + 47.5 explosion dmg, radius 7 (ray 350000, cell prob 30), speed 250-280, lifetime 500 +/- 7, **bounces 4**, innate spread 2.9 deg, friction 0.6, mass 0.065, knockback 1.0, hurts caster, emits real fire + smoke while flying. Action: cd +30 f, screenshake +4, child speed x0.75, recoil set 80. Tiers 0-4, price 170.
13. **Fireball** `FIREBALL` - mana 70, 15 uses, explosion 50 dmg radius 15 that **creates fire cells** (`create_cell_material fire`, prob 100), fire dmg 6.25; while flying a `MagicConvertMaterialComponent` (radius 15, `ignite_materials 99`, 5 steps/frame, loop) ignites flammables around it. Speed 160-170, lifetime 60, gravity 100, mass 0.09, `die_on_low_velocity`, `die_on_liquid_collision`, knockback 1.5, hurts caster. Action: spread +4 deg, cd +50 f, recoil +20. Tiers 0,3,4,6, price 220.
14. **Lightning Bolt** `LIGHTNING` - mana 70, unlimited. `LightningComponent is_projectile=1 explosion_type=1`: an instantaneous lightning ray (wiki speed 5400, lifetime 2 f, terminal velocity 61440) ending in an explosion of **125 dmg radius 35** + 25 electricity dmg, `create_cell_probability 1`, hurts caster, piercing. Action: cd +50 f, recoil set 180. Tiers 1,2,5,6, price 250.
15. **Digging Bolt** `DIGGER` - mana 0, unlimited, speed 0 (spawns at the muzzle), lifetime 2 f, drill dmg 7.5 (`damage_by_type drill 0.3`), explosion radius 6 with `ray_energy 100000`, `max_durability_to_destroy 10`, `hole_image explosion_hole.png`, `collect_materials_to_shooter=1`. Action: cd +1 f, recharge -10 f. Tiers 1,2, price 70.
16. **Chainsaw** `CHAINSAW` - mana 1, speed 0-400, lifetime 1 f, slice dmg 12.75 (0.51), explosion radius 3 (ray 20000) digs soft materials. Action: **`c.fire_rate_wait = 0` (set)**, spread +6 deg, recharge -10 f. Tiers 0,2, price 80.
17. **Luminous Drill** `LUMINOUS_DRILL` - mana 10, 10 dmg, speed 1400 (friction 0), lifetime 2 f (~47 px reach), no explosion, `ground_penetration_coeff 4`, `ground_penetration_max_durability_to_destroy 14` (drills nearly everything), mass 1.65. Action: cd **-35 f (-0.58 s)**, recharge -10 f. Tiers 0,2,10, price 150.
18. **Luminous Drill With Timer** `LASER_LUMINOUS_DRILL` - mana 30, same projectile, `add_projectile_trigger_timer(luminous_drill.xml, 4 f, 1)` (payload ~93 px out), cd -35 f, recharge -10 f. Tiers 0,2,6,10, price 220. (Classic "free cast delay" trigger.)
19. **Black Hole** `BLACK_HOLE` - mana 180, **3 uses, never_unlimited**. Speed 40 constant, gravity 0, air_friction -0.2, lifetime 120 +/- 7, `collide_with_world=0`, `collide_with_entities=0`, `penetrate_entities=1`, `friendly_fire=1`, knockback 0.1. `CellEaterComponent radius 12` deletes every non-`[indestructible]` cell and dynamic physics body it touches. `black_hole_gravity.lua` every frame: for every `projectile`-tagged entity within 150 px (excluding black holes and physics bodies) add velocity `196 * (150-d)/150` toward the hole; physics bodies get the same force x0.2 x mass over a 75 px half-size box. Action: cd +80 f, screenshake +20. Tiers 0,2,4,5, price 200.
20. **Nuke** `NUKE` - mana 200, **1 use**, needs flag `card_unlocked_nuke` ("Collect its Orb"). 75 projectile + **250 explosion dmg, radius 250**, `ray_energy 6,700,000`, durability 12, cell prob 5, physics power 4.5-9. Speed 300, lifetime 360 +/- 7, gravity 120, air_friction ~0, mass 0.2, knockback 1.5, hurts caster, emits `radioactive_liquid_fading` + smoke. Action: **cast delay set 20 f**, speed x0.75, shot material `fire` +60, ragdoll_fx 2, gore +10, screenshake +10.5, **recharge +600 f (10 s)**, recoil +300. Tiers 1,5,6,10, price 400.

### 6.2 Static projectiles (2)

21. **Explosion** `EXPLOSION` - mana 80, spawned at the caster (speed 0, lifetime 0): explosion 68.75 dmg, radius 15, ray 200000, creates fire cells (prob 80), hurts caster. Action: cd +3 f, screenshake +2.5. Tiers 0,2,4,5, price 160.
22. **Delayed Spellcast** `DELAYED_SPELL` - mana 20, a slow marker (speed 26, gravity 0, lifetime 100 f, `on_collision_die=0`, `penetrate_entities=1`, no explosion) with `add_projectile_trigger_death(..., 3)`: when it expires it casts a payload drawn with **draw count 3**. Action: cd +10 f. Tiers 0,1,2,4,5,6, price 240.

### 6.3 Materials (4)

23-25. **Water / Oil / Acid** `MATERIAL_WATER` / `MATERIAL_OIL` / `MATERIAL_ACID` - mana 0, unlimited. `projectile_type MATERIAL_PARTICLE`, speed 123-135, lifetime 360 +/- 7, `on_death_emit_particle=1` of that material (acid emits 6), `die_on_liquid_collision=1`, `on_collision_die=1`, no explosion. Action: cd **-15 f**, recharge -10 f; Water adds `effect_apply_wet.xml`, Oil `effect_apply_oiled.xml` to the shot's `game_effect_entities` (status applied by any projectile cast with it). Tiers 1-5 (acid 2-6), price 110/140/150. Acid is tagged digging + friendlyfire.
26. **Circle of Fire** `CIRCLE_FIRE` - mana 20, 15 uses. An entity at the caster with `ParticleEmitterComponent emitted_material fire, create_real_particles=1, image_animation_file circle_256.png, image_animation_raytrace_from_center=1, set_magic_creation=1` (fills an expanding circle shape with fire pixels, ray-traced so it stops at walls) and `LifetimeComponent 260`. Action: cd +20 f. Tiers 1-4, price 170.

### 6.4 Modifiers (17) - every one draws 1 spell in the same cast

27. **Speed Up** `SPEED` - mana 3; `speed_multiplier *= 2.5` (clamp [0,20]). Tiers 1-3, price 100.
28. **Decelerating Shot** `DECELERATING_SHOT` - mana 10; speed x1.68, cd -8 f, recoil -10, attaches `decelerating_shot.xml` whose script runs once and adds **+6 to the projectile's `air_friction`** (fast start, rapid slow-down). Tiers 2,3,4, price 80. (Accelerating Shot is the mirror: -3 air friction.)
29. **Damage Plus** `DAMAGE` - mana 5; projectile dmg **+10** (`+0.4`), cd +5 f, recoil +10, gore +5, yellow spark trail entity. Tiers 1-5, price 140.
30. **Heavy Shot** `HEAVY_SHOT` - mana 7; projectile dmg **+43.75** (`+1.75`), speed **x0.3**, cd +10 f, recoil +50, gore +10. Tiers 2-4, price 150.
31. **Critical Plus** `CRITICAL_HIT` - mana 5; crit +15 %. Tiers 1-5, price 140.
32. **Reduce Spread** `SPREAD_REDUCE` - mana 1; spread -60 deg. Tiers 1-6, price 100.
33. **Increase Lifetime** `LIFETIME` - mana 40; lifetime +75 f, cd +13 f. Tiers 3,4,5,6,10, price 250. (Reduce Lifetime `LIFETIME_DOWN`: -42 f, cd -15 f.)
34. **Homing** `HOMING` - mana 70; attaches `homing.xml` = `HomingComponent homing_targeting_coeff 130, homing_velocity_multiplier 0.86` (+ white spark particles). Tiers 1-6, price 220.
35. **Bounce** `BOUNCE` - mana 0; `bounces += 10`. Tiers 2,3,4,6, price 50.
36. **Piercing Shot** `PIERCING_SHOT` - mana 140; projectile dmg -15, `friendly_fire = true`, attaches `piercing_shot.xml` whose script runs once and sets `on_collision_die = 0` on the projectile (passes through creatures and can hit them repeatedly). Tiers 2-6, price 190.
37. **Ping-Pong Path** `PINGPONG_PATH` - mana 0; lifetime +25 f; attaches a Lua component executed every N frames with `N = clamp(map(|v|, 60..600 -> 50..4), 4, 50)` that **reflects velocity**: `vx = -vx*0.85; vy = -vy*0.85 - 0.1*|v|`; disables itself when `|v| < 60`. Tiers 1,3,5, price 20.
38. **Chain Spell** `CHAIN_SHOT` - mana 70; projectile dmg -5, explosion radius -5 (clamped >= 0), lifetime -30 f, spread +10 deg; attaches `chain_shot.xml`: on add, a `chain_shot` counter = 1; on removal, if counter < 5 and `projectile_file` is set (not `exploding_deer`/`pebble`), spawn the same projectile file from the death point with the old velocity +/- 10 (random +/- 400 if nearly stationary), copy the chain entity and set counter+1 -> up to **4 re-spawns**. Tiers 2,4,5, price 240.
39. **Explosive Projectile** `EXPLOSIVE_PROJECTILE` - mana 30; explosion radius +15, explosion dmg +5 (`+0.2`), cd +40 f, speed x0.75, recoil +30. Tiers 2-4, price 120.
40. **Fire Trail** `FIRE_TRAIL` - mana 10; `trail_material .. "fire"`, `trail_material_amount += 10`, `game_effect_entities .. effect_apply_on_fire.xml`. Tiers 0-4, price 130.
41. **Water Trail** `WATER_TRAIL` - mana 10; trail water +20, `effect_apply_wet.xml`. Tiers 1-4, price 160.
42. **Reduce Recharge Time** `RECHARGE` - mana 12; cd -10 f, **recharge -20 f**. Tiers 1-6, price 200.
43. **Add Mana** `MANA_REDUCE` - **mana -30** (the draw adds 30 mana to the wand; never skipped for lack of mana), cd +10 f. Tiers 1-6, price 250.

### 6.5 Multicasts (3)

44-46. **Double / Triple / Quadruple Spell** `BURST_2 / BURST_3 / BURST_4` - mana 0 / 2 / 5; `draw_actions(2 / 3 / 4, true)`; no other effect; all drawn projectiles share one shot state and spawn together. Tiers 0-6 / 1-6 / 2-6, price 140 / 160 / 180. (Octuple `BURST_8` mana 30 draw 8; Myriad `BURST_X` draws `#deck`, 30 uses.)

### 6.6 Other / utility (4)

47. **Add Trigger** `ADD_TRIGGER` - mana 10, flag `card_unlocked_mestari`. Deck surgery (full code in `spell_actions_lua.json`): walk the deck from the top; while the card is a modifier/passive/other/multicast (and not an Add-* card), **run modifiers' actions with `dont_draw_actions = true`** (their stat effects apply, they draw nothing) and advance; stop at the first card that has `related_projectiles`; discard all walked cards including that one; decrement its uses by 1; if any projectile/static/material/utility card remains in the deck, emit `add_projectile_trigger_hit_world(related_projectiles[1], 1)` x `related_projectiles[2] or 1` (the projectile becomes a collision trigger carrying the next spell); otherwise just run the projectile's action without draws. Tiers 3,4,5,10, price 100.
48. **Add Timer** `ADD_TIMER` - mana 20; identical, but `add_projectile_trigger_timer(target, 20 f, 1)`. Price 150. (Add Expiration Trigger `ADD_DEATH_TRIGGER`: `_death(target, 1)`, mana 20, price 150.)
49. **Divide By 2** `DIVIDE_2` - mana 35, flag `card_unlocked_musicbox`; cd +20 f. Takes `deck[1]`, checks `recursive` cards against `recursion_limit 2`, runs that card's action **twice** (first with `dont_draw_actions = true`; count drops to 1 from the 5th nested iteration), decrements its uses once, then **restores** `fire_rate_wait` and `current_reload_time` to their pre-copy values (the copied spell's delay/recharge is ignored), discards the consumed cards, and applies projectile dmg -5, explosion radius -5 (clamp >= 0), `pattern_degrees = 5` (the copies fan out). Tiers 3,5,6,10, price 200.
50. **Wand Refresh** `RESET` - mana 20, tier 10, flag `card_unlocked_mestari`; recharge -25 f; moves **every card in hand and deck to the discard**, then (once per cast, guarded by `force_stop_draws`) moves the discard back to the deck and re-orders it. Effect: the wand reloads mid-cast, the cards already cast are no longer in hand so they do not consume uses, and subsequent draws start again from the top. Tags `triggerfail`, `recursive`. Price 120.

### 6.7 Suggested "next 20" after the MVP

`HEAVY_BULLET` (Magic Bolt), `ARROW`, `BUCKSHOT` (Triplicate Bolt, 3 projectiles), `DISC_BULLET`, `DEATH_CROSS`, `POWERDIGGER`, `BLACK_HOLE_BIG`, `GRENADE_TRIGGER`, `FIRE_BLAST`, `TELEPORT_PROJECTILE`, `LONG_DISTANCE_CAST`, `TELEPORT_CAST`, `CIRCLE_SHAPE`/`SCATTER_3`, `LIGHT_SHOT`, `ELECTRIC_CHARGE`, `FREEZE`, `ACCELERATING_SHOT`, `LIFETIME_DOWN`, `ADD_DEATH_TRIGGER`, `BURST_8`, `SEA_LAVA`, `TORCH`, `ENERGY_SHIELD`.

---

## 7. Known gaps and caveats

* **Version skew**: game data = NathanSnail/noitadata as of 2025-10-21 (gun_actions.lua last touched 2024-04-05, "beta branch"); wiki fetched 2026-10-07. The 4 real numeric disagreements (`PROJECTILE_THUNDER_FIELD` / `PROJECTILE_GRAVITY_FIELD` uses 6 vs 3, `VACUUM_POWDER` mana 40 vs 50, a few spawn probabilities) are **UNVERIFIED** as to which side is current; `spells.json` uses the game file and records the wiki value in `validation_report.json`.
* 56 spells have `complex_logic` (Greek letters, Divide-By, Requirement, Random, Add-Trigger family, All-Spells, Wand Refresh, Summon Egg, Fireworks, Colour spells, etc.). Their `action_effects_raw` lists only unconditional lines; implement them from `spell_actions_lua.json`.
* `projectile_xml` covers the *main* projectile only (219 spells). Multi-projectile spells (`projectileCount` > 1, e.g. Triplicate Bolt x3, Fly Swarm) and spells whose entity is a loader/script (`SUMMON_EGG` picks a random egg at runtime, `FIREWORK` picks a random colour) need their secondary files from `raw/game/entities/`.
* XML attributes that are inherited from `base_projectile.xml` (`mass 0.05`, `affect_physics_bodies 1`) are merged; attributes the engine defaults in C++ (gravity 400, air friction 0.55 per the wiki) are not in the XML and are only present via `wiki.gravity` / `wiki.air_friction` - **UNVERIFIED engine defaults**.
* The wiki `effect`/`unlockCondition` strings were converted from wikitext to plain text; a few still contain template residue.
* `raw/cargo_Spells_export_v1_partial_UNRELIABLE.json` is an earlier export that came back with a different 40-field shape mid-session; do not use it (`_v2` is canonical, md5 above).
* Not covered here (separate research topics): wand generation stats, perks, enemy resistances per damage type, the exact C++ projectile integration (gravity/air-friction update order), and the per-material explosion durability table referenced by `max_durability_to_destroy`.

---

## Sources

Wiki (noita.wiki.gg), fetched 2026-10-07 via `?action=raw` / `api.php` / `Special:CargoExport`:

* https://noita.wiki.gg/wiki/Spell_Information_Table?action=raw
* https://noita.wiki.gg/wiki/Special:CargoTables and https://noita.wiki.gg/wiki/Special:CargoTables/Spells
* https://noita.wiki.gg/wiki/Special:CargoExport?tables=Spells&fields=_pageName,image,sortKey,tags,name,id,description,type,draw,manaDrain,castDelay,rechargeDelay,uses,dmgEveryXFrames,hitShooterFrames,projectileCount,relatedProjCount,criticalChance,damageProjectile,damageMelee,damageElectric,damageFire,damageExplosion,radius,damageIce,damageSlice,damageDrill,damageHealing,damageHoly,maxDuraToDestroy,rayEnergy,spread,spreadMod,speedMin,speedMax,speedDie,speedMod,pattern,gravity,airFriction,mass,recoil,bounces,bouncesMod,lifetime,lifetimeRandom,lifetimeMod,altLifetimeMin,altLifetimeMax,timerLifetime,effect,spellTier,spawnProbability,unlockCondition,price&format=json&limit=2000
* https://noita.wiki.gg/wiki/Special:CargoExport?tables=SpellTags&fields=_pageName,id,name,description,link,autoInclude&format=json&limit=500
* https://noita.wiki.gg/wiki/Template:Infobox_spell?action=raw (cargo_declare / cargo_store definition)
* https://noita.wiki.gg/wiki/Template:SpellTagDefinition?action=raw
* https://noita.wiki.gg/api.php?action=query&prop=revisions&rvprop=content&rvslots=main&format=json&formatversion=2&titles=<50 spell page titles> (7 batches; all 313 pages saved in `raw/pages/` and `raw/all_spell_pages.json`)
* https://noita.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Spells&cmlimit=500&cmnamespace=14&format=json (and `Category:Spells_of_type_*`, `Category:Spells_with_limited_uses`, `Category:Spells_with_Timer`, `Category:Spells_tagged_with_trigger|timer|expiration`)
* https://noita.wiki.gg/wiki/Spark_Bolt?action=raw
* https://noita.wiki.gg/wiki/Spells?action=raw
* https://noita.wiki.gg/wiki/Wand_and_Spell_Tiers?action=raw (redirect target of `Spell_Tiers`)
* https://noita.wiki.gg/wiki/Guide:_Wand_Mechanics?action=raw
* https://noita.wiki.gg/wiki/Expert_Guide:_Draw?action=raw
* https://noita.wiki.gg/wiki/Trigger?action=raw
* https://noita.wiki.gg/wiki/Timer?action=raw
* https://noita.wiki.gg/wiki/Expiration_Trigger?action=raw
* https://noita.wiki.gg/wiki/Tuple_Spell?action=raw (redirect target of `Multicast`)
* https://noita.wiki.gg/wiki/Damage_Types?action=raw
* https://noita.wiki.gg/wiki/Critical_hit?action=raw
* https://noita.wiki.gg/wiki/Spells_with_limited_uses?action=raw

Game data mirror (GitHub, repo NathanSnail/noitadata, branch `main`, latest commit 2025-08-29 `ce14ff00`, `gun_actions.lua` last commit 2024-04-05 `67110c35`):

* https://github.com/NathanSnail/noitadata
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/scripts/gun/gun_actions.lua
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/scripts/gun/gun.lua
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/scripts/gun/gun_enums.lua
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/scripts/gun/gunaction_generated.lua
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/scripts/gun/gun_extra_modifiers.lua
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/scripts/gun/procedural/gun_action_utils.lua
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/scripts/lib/utilities.lua
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/translations/common.csv
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/entities/... (417 entity XMLs listed in `raw/game/entity_paths.txt` + 26 base files in `raw/game/base_paths.txt`, saved under `raw/game/entities/`)
* https://raw.githubusercontent.com/NathanSnail/noitadata/main/data/scripts/... (134 Lua scripts listed in `raw/game/script_paths.txt`, saved under `raw/game/scripts_lua/`), notably `projectiles/black_hole_gravity.lua`, `projectiles/pingpong_path.lua`, `projectiles/piercing_shot.lua`, `projectiles/chain_shot_init.lua`, `projectiles/chain_shot_launch.lua`, `projectiles/decelerating_shot.lua`, `projectiles/accelerating_shot.lua`
* GitHub code search used to locate the mirror: `gh search code "gun_actions.lua"` (2025-10-07)
