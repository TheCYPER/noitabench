# Glossary

One-line definitions of the Noita and clone terms used across the knowledge base, with the page and rule that defines each. Entries are grouped by system and sorted alphabetically inside each group. Pages: `SIM` = [pixel-simulation.md](pixel-simulation.md), `MR` = [materials-reactions.md](materials-reactions.md), `WAND` = [wand-casting.md](wand-casting.md), `SP` = [spells.md](spells.md), `ED` = [entities-damage.md](entities-damage.md), `BEN` = [benchmark.md](benchmark.md). Conventions (units, names, ID prefixes) are in [index.md](index.md) section 1. Terms of the two pages that do not exist yet (world generation, frontend) are at the end and point to the unvetted research notes.

## 1. Simulation and grid

| Term | Definition | Defined in |
|---|---|---|
| active rectangle | Chunk-aligned part of the world that is stepped each frame; chunks outside it are frozen but stay readable. | SIM-R14 |
| boundary | Virtual indestructible material returned for reads outside the world; blocks everything and is never written. | SIM-R01 |
| BURNING flag | Cell flag bit 1: the cell is burning (a flammable material that was ignited, or an `on_fire` material at creation). | SIM-R03, SIM-R37 |
| cell | One grid pixel, a 6-byte record (`mat:u16, life, burn, var, flags`) with no velocity, temperature or wetness. | SIM-R03 |
| dirty rect | Per-chunk rectangle of cells that must be simulated this frame; cells outside it are not visited. | SIM-R10 |
| dirty-rect transparency | Property that the state after any number of frames is identical with dirty rects on, off, or after a snapshot restore. | SIM-R72 |
| DIR flag | Cell flag bit 2: lateral preference of a liquid or gas (0 = left). | SIM-R03, SIM-R32 |
| fall steps / lateral range | Derived per-material motion numbers: cells fallen per visit (about 2 x `liquid_gravity`, capped at 6) and the liquid hop distance `round(flow/(1-damping))` (cap 10). | SIM-R31, SIM-R32 |
| four-pass checkerboard | Scheduling in which chunks fall into 4 classes `(cx&1, cy&1)`; one class runs per pass, its chunks in parallel, with a barrier between passes. | SIM-R21 |
| frame / tick | One simulation step, 1/60 s; every duration in the simulation is an integer number of frames. | SIM-R01 |
| frame pipeline | Fixed order of phases per frame: inputs and casts, projectile sweeps, explosions, four cell passes, particles, flag clear and events. | SIM-R80 |
| kind | Motion class derived from material fields: Air, Static, Powder, Liquid, Gas, Fire, Solid. It gates motion before density does. | SIM-R04, MR MAT-R03 |
| keep-awake | Visit-time call that re-queues a cell that did not change but could still change later (timer, failed probabilistic roll, reactive neighbour). | SIM-R12 |
| OBJECT flag | Reserved cell flag bit 3, "occupied by a rigid body"; unused in the MVP. | SIM-R86 |
| particle | Free-flight pixel with Q16.16 position and velocity, used for thrown liquid and splashes; cells themselves have no velocity. | SIM-R45 |
| ray mask | One of four grid queries (`Raytrace`, `RaytraceSurfaces`, `RaytraceSurfacesAndLiquiform`, `RaytracePlatforms`) that decide what stops a ray. | SIM-R60 |
| reach (`MAX_REACH`, `RULE_REACH`) | Largest distance a chunk task may read or write from its chunk (32 = CHUNK/2, asserted) and the policy for rule authors (16). | SIM-R22, SIM-R23 |
| rule API | The only access path rules have to the grid: `get`, `set`, `swap`, `mat`, `rand`, `keep_awake`, `emit_particle`, `request_explosion`. | SIM-R25 |
| `SINK_CHANCE` / `MIX_CHANCE` | Calibration probabilities: a denser liquid mover sinks with 3/4 per attempt; equal-density liquids interpenetrate laterally with 1/16. | SIM-R30, SIM-R33 |
| simulation chunk | 64x64 cell block, the scheduling and dirty-rect unit. | SIM-R02 |
| broad (streaming) chunk | Noita's 512x512 px streaming and save unit (8x8 simulation chunks); informational, the clone does not stream. | SIM-R02 |
| stateless cell RNG | Per-visit hash of `(cell_seed, frame, pass, world cell index)` that replaces any shared or per-chunk RNG. | SIM-R70, BEN DET-R04 |
| state hash | blake3 over a canonical serialisation of frame, cells (with `UPDATED` cleared), particles, entities and wands, computed from per-chunk Merkle leaves. | SIM-R75, BEN DET-R02 |
| storage tile | 32x32 cell storage unit used to build disjoint mutable windows in safe Rust. | SIM-R02, SIM-R24 |
| swap (density swap) | Motion that exchanges two cells (matter conserved); a mover enters a lighter liquid or gas only if its density is strictly greater. | SIM-R30, MR MAT-R08 |
| timer units (`life_unit`, `burn_unit`) | Per-material tick units that fit lifetimes and fuel into the `u8` counters `life` and `burn`. | SIM-R35 |
| UPDATED flag | Transient cell flag bit 0: the cell was written this frame and is not visited again; cleared at frame end, never hashed. | SIM-R15 |
| wake margin (`WAKE`) | 12 px by which the bounding box of written cells is dilated when waking chunks, covering the largest read distance of any rule. | SIM-R11 |
| window | The 128x128 px region (4x4 storage tiles) that one chunk task may touch; windows of same-class chunks never overlap. | SIM-R22, SIM-R24 |

## 2. Materials, reactions, fire and explosions

| Term | Definition | Defined in |
|---|---|---|
| air | Material at index 0; a real material of kind liquid in the data but "empty" for the simulation; never `input_a` of a reaction. | MR MAT-R02, RXN-R02 |
| autoignition / `temperature_of_fire` | Ignition inputs: a burning source ignites a burnable neighbour only if its `temperature_of_fire` is strictly greater than the target's `autoignition` (defaults 10 and 100, so unconfigured materials never ignite). | MR FIRE-R03 |
| blob | Radius-based conversion of cells of the matched material around a reacting cell (`blob_radius`). | MR RXN-R10 |
| Box2D body | Rigid body built from `solid` pixels; out of MVP scope. | MR MAT-R16, SIM-R85 |
| burnable / `on_fire` / `[burnable]` / `[fire]` | Four different notions: the `burnable=1` attribute (can burn), the `on_fire=1` attribute (starts burning), the `[burnable]` tag (used by lava ignition), the `[fire]` tag (18 fire-kind materials). | MR FIRE-R02 |
| cell_type | XML class of a material (liquid, gas, fire, solid); with `liquid_sand` and `liquid_static` it determines the kind. Terrain is cell_type liquid + sand + static, not solid. | MR MAT-R03 |
| ConfigExplosion | Explosion parameter set: radius, `ray_energy`, `max_durability_to_destroy`, fire-cell material and probability, `hole_destroy_liquid`. | MR DUR-R03 |
| content hash | blake3 over `materials.json`, `spells.json` and the task generators; results are comparable only at equal hash. | BEN PROTO-R02, VER-R03 |
| contact damage | Per-pixel, per-frame damage from materials such as acid and lava, applied by the entity's damage model with a 4-cell minimum and no multipliers. | MR HAZ-R01, ED DAMAGE-R11 |
| density | Float 1 to 50 deciding which liquid, powder or gas sinks or rises; equal density never swaps vertically. | MR MAT-R08 |
| direction / `req_lifetime` / `fast_reaction` | Reaction side restriction (top, bottom, left, right), age gating of the input cell (cement), and an ordering flag of unknown meaning. | MR RXN-R09, RXN-R13, RXN-R12 |
| durability | Integer 0 to 16 compared with an explosion's `max_durability_to_destroy`; 0 means unset, not indestructible. | MR MAT-R12, DUR-R01 |
| engine tags | Tags the engine adds beyond the XML: `*` (every material), `any_liquid`, `any_powder`. | MR MAT-R07 |
| fire_hp | Fuel counter of a burning cell, in frames of fuel; -1 never burns out, 0 burns out in the same update. | MR FIRE-R04 |
| `hole_destroy_liquid` | If false (default), liquid cells inside a crater are thrown out as particles instead of being deleted. | MR DUR-R03, SIM-R52 |
| hp (hardness) | Per-cell cost an explosion ray pays to cross the cell (5 to 1,000,000, default 100); not entity HP and never multiplied by 25. | MR MAT-R11 |
| inheritance (`_parent`) | A child material copies every attribute of its parent then overrides; its `tags` replace the parent's; `_inherit_reactions` decides whether reactions naming the parent also match it. | MR MAT-R05, MAT-R06 |
| liquid_sand | Material flag that makes a cell_type liquid material behave as a powder; together with `liquid_static` it marks terrain. | SIM-R04, MR MAT-R03 |
| liquid_static | Material flag marking static terrain, which never moves and is never displaced. | SIM-R04 |
| material id | Lowercase `id` string of `materials.json` (466 materials); the numeric id is the rank by `xml_order`, `air` = 0, stored as `u16`. | MR MAT-R01 |
| MVP-40 / MVP reactions | The 40 materials and 39 reactions that the clone ships and tests first. | MR MVP-R01, MVP-R02 |
| positional output | In a reaction, `output_a` replaces the cell that matched `input_a` and `output_b` the cell that matched `input_b`. | MR RXN-R02 |
| powder | Kind of falling and sliding grains (cell_type liquid with `liquid_sand=1`, not static). | SIM-R04 |
| `platform_type` | Standing flag (1 can stand, 0 fall-through, -1 unset); the MVP derives entity collision from kind instead. | MR MAT-R13, SIM-R64 |
| `ray_energy` | Per-ray budget an explosion spends on the `hp` of each cell it crosses. | MR DUR-R02 |
| reaction | Table row `input_a + input_b (+ input_c) -> output_a + output_b (+ output_c)` with a percent probability, evaluated on adjacent cells. | MR RXN-R01..R05 |
| ReqReaction | Reaction that fires when a requirement is not met (plants and mushrooms turning to soil); not in the MVP. | MR RXN-R15 |
| `requires_oxygen` | In the reading used here, a cell with 1 burns only while at least one 4-neighbour is air or gas; 0 burns through its whole volume. | MR FIRE-R05 |
| solid | Kind for Box2D rigid-body materials (132); treated as Static in the MVP. | MR MAT-R03, SIM-R85 |
| spark | One of 15 `spark*` fire-kind materials: tagged `[fire]`, trigger fire reactions, ignite nothing. | MR FIRE-R07 |
| static (terrain) | Kind that never moves and is never displaced; it can be removed, burned or converted. | SIM-R39, MR MAT-R03 |
| tag | Plain string on a material used as a reaction input or output (`[fire]`, `[water]`); membership is listed in `tags_index.json`; a tag is not a kind and not a flag. | MR MAT-R07 |
| wang color | ARGB value unique to each material (the world-loading key used by Wang-tile images to place that material); not a render colour. | MR MAT-R15 |

## 3. Wands and casting

| Term | Definition | Defined in |
|---|---|---|
| Add Trigger / Timer / Expiration | Spells that scan the deck and turn the next projectile card into a trigger carrier by deck surgery. | WAND-R82 |
| always cast | Spell permanently attached to a wand (max 4); played free at every click before the draws and dropped, not discarded, at the end. | WAND-R70 |
| called (copied) spell | A spell run by another spell: only its action runs, with no mana, no hand and no uses check. Opposite of a drawn spell. | WAND-R05 |
| capacity (`deck_capacity`) | Number of spell slots of a wand (2 to 26 for generated wands). | WAND-R03, WAND-R93 |
| card | A spell instance in a slot or pile, with `uses_remaining`, `deck_index` and `permanently_attached`. | WAND-R04 |
| cast (click) | One firing of a wand: reset of per-click flags, always-casts, `actions_per_round` draws, then hand to discarded and the recharge check. | WAND-R12, WAND-R50 |
| cast delay (`fire_rate_wait`) | Frames before the next click: wand base plus the deltas of spells played on the root shot, clamped to at least 1 on the total. | WAND-R53 |
| deck / hand / discard(ed) | The three ordered piles: cards are drawn from the deck front, the hand holds the cards played this click, discarded holds used cards. | WAND-R10 |
| `dont_draw` | The single global boolean that turns every draw into a no-op while a copy spell runs; not a stack. | WAND-R25 |
| draw | Taking the front card of the deck, paying its mana and running its action. | WAND-R20 |
| Divide By | OTHER spells (`DIVIDE_2/3/4/10`) that call the next deck card N times with damage and radius penalties and a cast-delay penalty. | WAND-R81 |
| formation | Multicast that also sets spread and `pattern_degrees` (`T_SHAPE`, `Y_SHAPE`, `W_SHAPE`, `I_SHAPE`, `PENTAGRAM_SHAPE`, `CIRCLE_SHAPE`). | SP SPELL-R20, WAND-R34 |
| got_projectiles | Per-click flag set when a projectile, static or material card is played; decides which cards pay a use. | WAND-R63 |
| Greek letters | Copy spells Alpha, Gamma, Tau, Omega, Mu, Phi, Sigma (and Zeta, which reads other wands) that call cards from the piles. | WAND-R83, SP DF-4 |
| mana / mana max / mana charge speed | The wand's energy pool, its cap, and regeneration in mana per second (applied per frame, also while not held). | WAND-R57, WAND-R60 |
| multicast (`DRAW_MANY`) | Spell type that draws N further cards into the same shot state before its own spread and pattern changes. | WAND-R34, SP SPELL-R12 |
| Myriad (`BURST_X`) | Multicast that draws every card left in the deck (`#deck`). | WAND-R34 |
| negative mana cost | A spell that adds mana when drawn (`MANA_REDUCE` -30, `BLOOD_MAGIC` -100); it is never skipped for lack of mana. | WAND-R20, WAND-R62, SP SPELL-R06 |
| `order_deck` | Sorting the deck by `deck_index` (non-shuffle) or replacing it by a uniform permutation (shuffle); runs on first click, wrap, recharge start and first refresh. | WAND-R11 |
| payload | Shot state drawn at cast time for a trigger or timer and released when the trigger fires; it starts from default values. | WAND-R40, WAND-R41 |
| Plicate spells | Spells (`I_SHOT`, `Y_SHOT`, `T_SHOT`, `W_SHOT`, `QUAD_SHOT`, `PENTA_SHOT`, `HEXA_SHOT`) that peek at the next card and repeat its projectile. | SP DF-4 |
| recharge (`reload_time`) | Frames a wand needs after its deck is exhausted; the accumulator `current_reload_time` collects spell deltas over the whole cycle. | WAND-R51, WAND-R52, WAND-R55 |
| recursion level | Nesting counter of recursive spells; a recursive spell is not called at level 2 or more. | WAND-R80 |
| Requirement spells | `IF_ENEMY`, `IF_PROJECTILE`, `IF_HP`, `IF_HALF` with `IF_ELSE` and `IF_END`: conditionally discard deck cards, then draw 1. | WAND-R85 |
| shot state | The bundle of accumulated modifiers (`c.*`) and projectile list that spells edit; one root state per click and a fresh one per payload. | WAND-R30, SP SPELL-R15 |
| shuffle | Wand flag: the deck is a random permutation per cycle instead of slot order. | WAND-R03, WAND-R11 |
| skip | A card discarded unplayed because its cost exceeds mana or it has 0 uses; skipping is free and the same draw retries. | WAND-R20, WAND-R21 |
| Spells/Cast (`actions_per_round`) | Number of draws the wand performs per click; it never wraps the deck. | WAND-R03, WAND-R22 |
| Spell Duplication | Spell that calls every card in the hand once more, then adds +20 cast delay and recharge and draws 1. | WAND-R84 |
| tier | Spawn and generation level (0 to 7 and 10) of a spell or wand. | WAND-R90, SP SPELL-R44 |
| trigger / timer / expiration | Spell types that wrap a projectile with a payload released on collision, after a delay or collision, or when the projectile dies. | WAND-R40..R43, SP SPELL-R18 |
| uses (`max_uses`, `never_unlimited`) | Limited-use counter of a spell, charged at end of click under the R63 condition; a card at 0 is skipped and leaves the cycle. | WAND-R63, SP SPELL-R07 |
| Wand Refresh (`RESET`) | Moves hand and deck to discarded and re-deals; the first one per click disables wrapping, a second forces a recharge. | WAND-R86 |
| wand budget (cost) | Points by tier that wand generation spends on stats. | WAND-R90..R93 |
| wrap | Refilling an empty deck from discarded when a spell requests a draw; it sets `start_reload`. | WAND-R23 |

## 4. Spells and projectiles

| Term | Definition | Defined in |
|---|---|---|
| air friction / `gravity_y` | Projectile kinematics: per-frame velocity loss `v -= 0.016666567 * v * air_friction` and downward acceleration (defaults 0.55 and 400). | SP SPELL-R24 |
| bounce | Terrain bounce that multiplies velocity by `bounce_energy` and decrements `bounces_left`. | SP SPELL-R26 |
| crit chance | Sum of `c.damage_critical_chance` in percent points; base crit multiplier 5. | SP SPELL-R29, ED DAMAGE-R03 |
| D0 / D1 / D2 | Implementation classes: data only, data plus a reusable engine feature, spell-specific code (127, 110 and 185 of 422). | SP SPELL-R37 |
| `game_id` | UPPER_SNAKE key of a spell in `spells.json` (for example `LIGHT_BULLET`); the lowercase `id` is never a key. | SP SPELL-R01 |
| lifetime | Projectile life in frames, with a random +-r; -1 is infinite. | SP SPELL-R08 |
| MVP-50 | The 50 spells implemented first (35 D0, 6 D1, 9 D2). | SP SPELL-R45 |
| `on_collision_die` / `penetrate_entities` | Projectile flags: die on any hit (default), or pass through creatures hitting each once; `on_collision_die 0` re-hits every frame. | SP SPELL-R25, ED DAMAGE-R20 |
| primitive | One of 7 behaviour kinds every spell maps to (PROJ, TRIGGER, STATIC, MATERIAL, MODIFIER, MULTICAST, UTILITY). | SP SPELL-R36 |
| recoil | Push on the caster set or added by a spell; not cosmetic. | SP KN-1 |
| spread | Total aim error: innate plus shot-state spread plus wand spread (root shot only); negative acts as 0. | SP SPELL-R09 |
| spell type | One of 8 `type` values: projectile, static_projectile, modifier, multicast, material, other, utility, passive. | SP SPELL-R01, SPELL-R11 |
| terminal velocity | Cap of 1000 px/s on projectile speed (Lightning, Cursed Orb, Expanding Orb and Fly Up/Down are exceptions). | SP SPELL-R23 |
| trail material | Material left along a projectile's path (Fire Trail, Water Trail ...). | SP SPELL-R30 |

## 5. Entities and damage

| Term | Definition | Defined in |
|---|---|---|
| aggressiveness | Per-individual roll [1, 100] at spawn; a creature attacks a faction when it exceeds the relation value. | ED Key numbers, Pitfall 10 |
| Dazed | Status for 120 frames after Projectile or Melee damage taken while airborne: no levitation or movement input. | ED DAMAGE-R13 |
| critical resistance | Fraction of the crit bonus cancelled (player 1.0: never takes the x5, still takes base damage). | ED DAMAGE-R03 |
| Electrocution (Stunned) | Status of 40 frames per application, with a 60-frame resistance window afterwards. | ED DAMAGE-R16 |
| Frozen | Status of 120 frames: no movement; a Melee hit executes (half current HP, or 0 at or below 25 % of max). | ED DAMAGE-R15 |
| herd | Faction id of an entity (player, spider, orcs, slimes ...); same-herd hits are skipped unless `friendly_fire`, and the relation matrix decides who attacks whom. | ED DAMAGE-R20, Data Files |
| hitbox / collision AABB | Player damage hitbox 6x16 px versus the smaller 4x6.6 px box used for world collision (auto step-up 4 px). | ED Key numbers, SIM-R65 |
| i-frames | `invincibility_frames` countdown during which all damage is ignored; the player starts with 60 and vanilla does not refresh it on hit. | ED DAMAGE-R10 |
| immunity (`PROTECTION_*`) | Game effect that nullifies a whole hit if any damage type flag of the hit matches. | ED DAMAGE-R01 |
| kick | Player melee action: radius 3 px, 1 displayed HP. | ED Key numbers |
| knockback | Impulse from projectiles (force x speed x mass ratio) and explosions (radius-scaled, inverse distance). | ED DAMAGE-R12 |
| levitation | Meter-limited flight: 3.0 s maximum, drains 1/s, refills 6/s on the ground, 0.4/s in air after 38 frames. | ED Key numbers |
| multitype damage | A hit carrying several damage type flags (Melee-Bite, Fire-Explosion ...); immunity to any one nullifies the hit. | ED DAMAGE-R08 |
| On Fire | Status: 2 % of max HP per second, +15 % move speed; extinguished by liquids or wet-like stains. | ED DAMAGE-R14 |
| Poisoned / Toxic | Per-tick percent-of-max-HP statuses that cannot kill (floors at 2 % and 5 %); tick cadence UNVERIFIED. | ED DAMAGE-R18, DAMAGE-R19 |
| stain | Liquid coating on an entity (wet, oiled, bloody, slimy ...) that drives statuses; 1.0 = 60 s, active while at least 1 % remains. | ED DAMAGE-R17 |
| status (game effect) | Timed effect with a duration in frames (fire 720 from a spell, frozen 120 ...). | ED DAMAGE-R13..R19 |
| x25 rule | Internal HP and damage x 25 = displayed value (`GUI_HP_MULTIPLIER`); player 4.0 internal = 100 shown. Cell `hp` is excluded. | ED header, SP SPELL-R03, MR HAZ-R01 |

## 6. Benchmark

| Term | Definition | Defined in |
|---|---|---|
| action log | The recorded requests of an episode; with the state hashes it is the submission and the replay input. | BEN ANTI-R01 |
| assist | Aid such as `walk_to` or hints; recorded in the run header and ranked in a separate leaderboard partition. | BEN ANTI-R05 |
| decision | One agent turn: a line of actions advancing at most `max_frames_per_decision` (default 120) frames. | BEN ACT-R04 |
| dev mode | `--dev` flag enabling `save_state`, `load_state` and `debug *`; runs made with it are rejected. | BEN ANTI-R03 |
| episode seed | `blake3(task_id, task_version, seed_index)`; raw `u64` seeds are research-only. | BEN SEED-R01, SEED-R02 |
| golden hash | Reference per-frame state hashes of a task version checked in CI. | BEN Data files |
| JSON Lines protocol | One UTF-8 JSON object per line on stdin/stdout; requests echo their `id`. | BEN PROTO-R01 |
| observation modes | LLM text (ASCII map, legend, entity list, HUD, wands) and RL arrays (`grid`, `vec`, `spells`). | BEN OBS-R01..R09 |
| partial credit | Score that is a maximum over the episode of a monotone progress metric, so dying cannot raise it. | BEN SCORE-R01, SCORE-R03 |
| public / hidden seeds | Seed indices 0 to 19 are public per task version, 20 to 39 hidden behind a maintainer salt. | BEN SEED-R01 |
| stream seed | Per-subsystem seed `blake3(seed, "worldgen" / "cells" / "spells" / "ai" / "spawn")`. | BEN DET-R04 |
| suite / `task@N` | A suite pins a list of versioned tasks, seed lists and hashes; any change to a task generator, loadout, limits, scoring or rendering is a new `@N`. | BEN VER-R04, VER-R05 |
| terminated / truncated | Terminal by death or objective versus cut off by the frame or decision limit. | BEN SCORE-R02 |

## 7. World generation and frontend

| Term | Definition | Defined in |
|---|---|---|
| benchmark arena | Fixed deterministic 512×512 arena (zones: rest, cave, lava, abyss) generated from the seed for agent benchmark tasks. | WORLD-R11/R12 |
| BIOME_FILL | Material placeholder in Wang-tile images, resolved at generation time by noise-driven material components; unused in MVP (uses fBm instead). | research/worldgen.md section 5.3 (reference only) |
| biome | Vertical stratum of the world with its own materials, hazards and spawn tables (Mines, Snowy Depths, Hiisi Base, Underground Jungle, Holy Mountains). | WORLD-R02/R03 |
| fBm | Fractal Brownian motion noise; the clone's layered-fBm cave generator (WORLD-R07) replaces Noita's Wang tiling for determinism and simplicity. | WORLD-R07 |
| fixed timestep accumulator | Frontend loop that advances the core simulation at a fixed 60 Hz independent of rendering rate (FE-R01); prevents spiral-of-death on low frame rates. | FE-R01 |
| Holy Mountain | Safe chamber between biomes: shop, health pool, Spell Refresher, perk altar, brickwork of durability 14, exit tunnel with collapse trigger. | WORLD-R04 |
| integer zoom | Nearest-filtered texture scaling by a whole integer factor (2×, 4×, etc.) to preserve pixel-perfect rendering without interpolation artifacts. | FE-R03 |
| pixel scene | Predefined structure (chests, rooms, decorations) placed on marker pixels; used in Noita's Wang-tile generation; reference only in MVP. | research/worldgen.md section 5.2 (reference only) |
| spawn table | Weighted pools of enemies and items per biome, sampled seeded per chunk. | WORLD-R08 |
| Wang tile (herringbone) | Predrawn edge-matched tile piece whose pixel colours are `wang_color` keys; Noita's standard terrain algorithm; not used in MVP (fBm instead). | research/worldgen.md section 5.1 (reference); MR MAT-R15 |

## Sources

KB pages: `./.trellis/spec/game-design/{pixel-simulation,materials-reactions,wand-casting,spells,entities-damage,benchmark,worldgen,frontend,index}.md`.

Research files (`./.trellis/tasks/10-16-noita-cogbench/research/`): `pixel-sim-tech.md`, `materials.json`, `reactions.json`, `tags_index.json`, `spells.json`, `wand-mechanics.md`, `wand-stats.json`, `entities-damage.md`, `player-stats.json`, `damage-types.json`, `status-effects.json`, `factions-relations.json`, `benchmark-design.md`, `worldgen.md`, `frontend-tech.md`.

Wiki: https://noita.wiki.gg/wiki/Documentation:_Reaction , /Modding:_Making_a_custom_material , /Documentation:_ConfigExplosion , /Expert_Guide:_Draw , /Wands , /Spells , /Holy_Mountain , /Biomes .
