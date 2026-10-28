# Materials, Reactions, Fire and Durability

**Purpose / when to read this.** Normative reference for the material table (`materials.json`), the reaction table (`reactions.json`), tag/inheritance expansion, the fire/burning system, explosion/digging durability, and material contact damage. Read it before touching `noita_core::materials`, `sim::rules::{fire,reactions}`, `sim::explode`, or any test that cites a material number. Every rule has a stable ID (`MAT-`, `RXN-`, `FIRE-`, `DUR-`, `HAZ-`, `MVP-`). Entity-side damage (statuses, multipliers, i-frames) lives in `entities-damage.md`; movement/update-order formulas belong to `pixel-simulation.md` (`SIM-` rules) - this page only fixes the material-driven inputs.

**Conventions.** Time = frames at 60 Hz. Lengths = cell pixels. HP: internal x 25 = displayed (`GUI_HP_MULTIPLIER`; player 4.0 internal = 100 shown). **UNVERIFIED** = no primary source; **DECISION-NEEDED** = user choice, a default is stated. Source shorthand: `MJ` research/materials.json; `RJ` reactions.json; `TI` tags_index.json; `MX` raw/noitadata/data/materials.xml (Nolla data: facts/numbers only, never copy markup); `MXP` raw/materials_xml_parsed.json; `CE` Nolla projectile XML `config_explosion` numbers (raw/game/entities/projectiles); `EC` noita-engine-constants.json; `PS` player-stats.json; `W:<Page>` raw/<Page>.wikitext (noita.wiki.gg).

---

## Normative rules

### A. Material model

- **MAT-R01 Identity/size.** A material is one `<CellData>`/`<CellDataChild>`; id = its `name`. MX has 468 live elements (224 CellData + 244 CellDataChild) = **466 unique ids** (`rock_box2d`, `meat_pumpkin` are defined twice; MJ keeps the first; engine tie-break UNVERIFIED, wiki says "later overwrites" for mods; neither id is MVP). Engine cap is 1024 materials, so ids are `u16`. Numeric id = rank by `xml_order` (air = 0), frozen per `content_hash`. Source: MX, MJ, EC `CELLFACTORY_CELLDATA_MAX_COUNT`.
- **MAT-R02 Bound ids.** The sim binds by name at load and aborts if absent: `air` (empty cell), `fire` (only material the engine strictly requires; default flame), `smoke` (default burn smoke), `water`. Source: MX header, W:Fire (Trivia).
- **MAT-R03 Kind (derived).** `cell_type=fire`->`fire`; `gas`->`gas`; `solid`->`solid`; `liquid`+`liquid_static=1`->`static`; `liquid`+`liquid_sand=1`->`powder`; else `liquid`. Counts: solid 132, static 103, liquid 100 (incl. `air`), powder 87, gas 26, fire 18 = 466. **Terrain is `static` (cell_type liquid, sand+static); `solid` means Box2D rigid bodies.** Source: W:Modding: Making a custom material, MJ.
- **MAT-R04 Defaults.** Absent attribute -> default (Key numbers). `MJ` is already fully resolved (defaults and inheritance applied); loaders must not re-default. Default conductivity = 1 for non-sand liquids, else 0. Source: W:Modding: Making a custom material (Defaults), MJ.
- **MAT-R05 Inheritance.** `CellDataChild` copies every attribute from `_parent` (recursive) then overrides: 249 materials have a parent (243 `CellDataChild` + 6 vanilla `<CellData _parent=...>`: `vomit`, `plastic_grey`, `plastic_grey_molten`, `grass_ice`, `grass_dry`, `magic_liquid_hp_regeneration_unstable`; the wiki says only `CellDataChild` may). A child's `tags` **replaces** the parent's list (no merge): `poison` (child of `radioactive_liquid`) drops `[radioactive]`; `coal_static` (no `tags`) inherits all of `rock_static`'s. Source: MXP (`raw_attrs` vs `resolved`), W:Modding: Making a custom material.
- **MAT-R06 Reaction inheritance.** `_inherit_reactions`: explicit 1 on 165 children, explicit 0 on 23, unset on 61 (treat unset as 0, UNVERIFIED). Where 1, the child is also matched by reactions that name the **parent id** as an input (not by reactions naming the parent only as an output). Tag membership is independent of this flag (MAT-R05). Source: MJ `inherits_reactions`, W:Modding: Making a custom material.
- **MAT-R07 Tags.** Plain strings (`[a],[b]` in XML); membership of record = `TI` (76 XML tags + engine tags `*`, `any_liquid`, `any_powder`; 79 keys total). `any_liquid` = cell_type liquid and sand=0 (104: 100 kind-liquid + 4 static liquids `water_static`,`endslime_static`,`slime_static`,`spore_pod_stalk`); `any_powder` = sand=1 (186 = 87 powder + 99 static). `[*]` = every material. **A tag is not a kind and not a flag**: `[burnable]` (63) is not `burnable=1` (137), `[static]` (113) is not kind static (103), `[solid]` (237) is not cell_type solid. Source: TI, W:Documentation: Reaction (Engine Tags).
- **MAT-R08 Density.** Float (e.g. 4.1, 4.921, 14.5), range 1-50 overall (liquids 1-14.5, powders 2-10, gas 1/2/4.17, static 4-11). Denser liquid/powder cells sink through lighter liquids/gases; **equal density never swaps**; gases are the mirror image (lighter rises). `static`, `solid`, `fire` never swap. Source: W:Density, RJ `engine_density_swap`.
- **MAT-R09 Liquid/powder motion fields** (kinds liquid, powder; ignored elsewhere): `liquid_gravity` default 0.5 (range 0-5; 0 still falls slowly), `liquid_viscosity` 50 (0-150), `liquid_flow_speed` 0.9 (0.1-0.9), `liquid_damping` 0.8 (0.9 on 7 materials; other values glitch), `liquid_slime` (11 flow slower), `liquid_sticks_to_ceiling` (0 / 40-100 in data; only boolean in effect), `stickyness` (0-1.0, slows entities in it). The engine's formulas are UNVERIFIED; the clone maps them in `pixel-simulation.md` (SIM-R31..R34). Source: MJ, W:Modding: Making a custom material.
- **MAT-R10 Gas fields.** All 26 gases share `gas_speed` 50, `up` 100, `horizontal` 100, `down` 90 (no per-material variation). `lifetime` frames > 0 removes the cell (->air) when it expires (steam 1000, smoke 350, acid_gas/poison_gas/radioactive_gas 450, alcohol_gas 50). `*_static` gas emitters have lifetime 0 and emit via a reaction with air. Source: MJ, RJ `engine_lifetime`.
- **MAT-R11 hp ("hardness").** Per-cell HP consumed by explosion rays (DUR-R02); range 5-1,000,000, default 100 (167 materials). It is **not** a damage-to-entity value. Source: W:Materials (Hardness), MJ.
- **MAT-R12 durability.** Integer 0-16 (wiki says 0-14; 15 on one gem, 16 on three), default 0 = "unset: only hp matters" (329 of 466). Compared with a projectile's `max_durability_to_destroy` (DUR-R01). Source: W:Materials (Durability), MJ.
- **MAT-R13 Platform/collision.** `platform_type` 1 = can stand on (94/103 statics), 0 = fall-through (29 powders: plants/grass/fungi, `vine`), -1 = unset (liquids, gases, sand, most powders). Standing on sand works regardless: derive entity collision from **kind**, not platform_type (see MVP-R05). Source: MJ, W:Modding: Making a custom material.
- **MAT-R14 No temperature.** There is no temperature grid. Heat = discrete conversions: reactions (RXN), burning (FIRE), and spell/perk driven `freezes_to` / `melts_to` (`cold_freezes_chance_rev`/`warmth_melts_chance_rev` default 100; water uses 500 = 0.2%). Source: RJ `engine_cold_freeze`, `engine_warmth_melt`, MJ.
- **MAT-R15 Colour.** `wang_color` (ARGB hex) is the **world-loading key**, unique across all 466 (verified), not a render colour. Render colour: `palette_avg`/`palette` when `texture_file` is set (331 materials), else `graphics_color_argb`; `color_rgb` for textured materials is a placeholder (e.g. `rock_static_grey` is blue (18,68,164) but its texture average is #4c4c4c). Source: MJ, W:Modding: Making a custom material.
- **MAT-R16 Box2D solids.** The 132 `solid` materials (boxes, ice/glass shards, TNT, wood props) are rigid bodies in Noita and out of MVP scope (PRD non-goal). They stay in the data for completeness; conversions `break_into`/`convert_to_box2d_material` (ice_static->ice_glass, glass_static->glass_brittle, ...) are not simulated. Source: PRD, RJ `engine_convert_to_box2d`.

### B. Reactions

- **RXN-R01 Inventory.** `RJ` = 339 records = **330 XML reactions** (`xml_000`..`xml_329`: 325 `<Reaction>` + 5 `<ReqReaction>`; the number is file order) + **9 `engine_*` pseudo-records** (documentation of hard-coded engine systems: burning ignite/consume, cell explosion, cold freeze, warmth melt, lifetime, density swap, mimic, box2d conversion). Pseudo-records are not executable rows; filter by id prefix `xml_`. 162 of the 330 use a tag in an input. Source: RJ, MX.
- **RXN-R02 Roles and outputs are positional.** `(input_a, input_b[, input_c]) -> (output_a, output_b[, output_c])`; `output_a` replaces the cell that matched `input_a`, `output_b` the cell that matched `input_b`. `[fire]+water -> [fire]+steam` keeps the fire cell and turns the **water** into steam (water is consumed, fire is not). An output equal to its input is a no-op; output `air` deletes the cell. `air` is never `input_a` (0 of 330; the engine rewrites it to `unknown`, which is rejected) but is `input_b` in 54 and `input_c` in 11. Source: W:Documentation: Reaction, RJ.
- **RXN-R03 Probability.** `probability` is a **percent float**, stored by the engine as `int(p*100)` (0.01% resolution). Observed 0-100: 80 (x47), 50 (x43), 100 (x35), 10 (x30), 20 (x25), 70 (x24), 60 (x15), 1 (x15), 90, 40, 30, 5, 2, 15, 8, 25, 35 ..., one 0.3 (`xml_185`), one 0 (`xml_064`, disabled: lava does not smoke on air). >=100 = certain, 0 = never. Source: W:Documentation: Reaction, RJ.
- **RXN-R04 Cadence.** Probability is "per update that the pair is examined". How many neighbours the engine examines per cell per frame is UNVERIFIED -> **DECISION-NEEDED D2** (default in Simplifications). Our rule: reactions are matched on **unordered** adjacent cells (try both role assignments) except where `direction` is set; the engine's own handling of order is UNVERIFIED (both `cement+water` and `water+cement` are authored, with different `req_lifetime`). Source: W:Documentation: Reaction; RJ `probability_semantics`.
- **RXN-R05 Same pair, several reactions.** Candidates for a pair are evaluated in file order (`xml_` index); the first whose roll succeeds executes; later ones are not rolled. Whether `fast_reaction` reorders is UNVERIFIED (RXN-R12). Example `[fire]+snow`: xml_010 (20% steam) then xml_015 (80% water). `W:Table_of_Alchemical_Reactions` is sorted alphabetically, not by priority: use `RJ` ids for order. Source: RJ (file order = priority, UNVERIFIED), MX.
- **RXN-R06 Tag in an input** matches every material whose tag list contains it (`TI`), including all engine tags of MAT-R07. Both inputs may be tags (41 reactions). A `[tag]` that has zero members never fires. `[fire]` has 18 members (fire, fire_blue, flame and **15 sparks**); `[water]` has 37 (incl. whiskey, magic liquids, `pus`); `[lava]` 1; `[corrodible]` 279. Source: TI, RJ `tag_member_counts`.
- **RXN-R07 Tag in an output** means "the same material that matched that tag in the inputs" (`[fire]+water -> [fire]+steam` with a spark yields spark). **Quirk:** `xml_167` (`alcohol+[lava] -> [fire]+alcohol_gas`) has an output tag with no input tag in that slot; resolve to `fire` (D11). Source: RJ, MX.
- **RXN-R08 Suffix forms.** `[tag]_suffix` = member id + suffix. As **output** (10 reactions; e.g. `copper+[lava]` -> `copper_molten`; suffixes `_molten`, `_vapour`, `_rust`, `_oxide`) it names the material derived from the matched input. As **input** (xml_057, xml_062: `[meltable]_molten + water -> [meltable] + steam`) it matches every `<member>_molten`, and the bare `[meltable]` output then means that member. Every derived id must exist or the reaction is dropped with a load-time warning (all 27 distinct derived ids used by `RJ` resolve). `[meltable]_molten` is not a tag name (it is the 2 "unknown tags" a naive tag check reports). Source: W:Modding: Making a custom material, RJ, TI.
- **RXN-R09 `direction`** (18 reactions: top 8, bottom 6, left 2, right 2; default none = any side) restricts the reaction to when the **B cell lies on that side of the A cell** (growth/dripping: `vine+air -> vine+vine dir=top`). Directional reactions are not symmetric. Source: W:Documentation: Reaction (enum none/top/bottom/left/right), RJ. Side semantics UNVERIFIED.
- **RXN-R10 Blobs.** `blob_radius1/2` (54 reactions) converts every cell within that radius **of the reacting cell** to the output, restricted to cells of the same material as the matched input (`blob_restrict_*` = true on all 330). Pairs (r_a/r_b): 4/4 x18, 5/0 x8, 6/3 x7, 0/3 x5, 0/2 x5, 3/3 x3, 4/0 x2, 2/0, 2/2, 5/5, 40/40, 0/15, 15/15. Distance metric UNVERIFIED (D9). Source: W:Documentation: Reaction, RJ.
- **RXN-R11 `convert_all`** (0 uses) and `destroy_horizontally_lonely_pixels` (7 uses, all cement/concrete) are cosmetic or unused: ignore. Source: RJ.
- **RXN-R12 `fast_reaction`** (13 uses: acid x3, glue, poison+air, 3 static-gas emitters, midas x3, rock_eroding, magic_liquid+rock_magic_bottom). Wiki: "prioritises the reaction over others?" Semantics UNVERIFIED; only acid and `poison+air` matter for MVP and both work as ordinary reactions. Source: W:Documentation: Reaction, RJ.
- **RXN-R13 `req_lifetime`** (5 uses: cement x5: 300/50/600/600/300 frames) gates a reaction on the age of the input cell(s). Exact reading UNVERIFIED ("untested" on the wiki). Cell age does not fit the `life: u8` of design.md -> D8. Source: W:Documentation: Reaction, RJ.
- **RXN-R14 Third input/output.** 32 reactions have `input_c`, 15 have `output_c` (e.g. `cement+fire+cement`, `[fire]+water_salt+water_salt -> [fire]+salt+steam`, `meat+[fire]+oil -> meat_warm+[fire]+smoke`). Meaning (a third touching cell? same-cell multiplicity?) is UNVERIFIED: **MVP drops all of them** (MVP-R03). Source: RJ, W:Documentation: Reaction.
- **RXN-R15 `<ReqReaction>`** (5: `[requires_air]`, `ceiling_plant_material`, 3 mushrooms; all `X + air -> soil + air`) fires when the "requirement is not met" (plants/mushrooms die to soil when starved). UNVERIFIED; not MVP. Source: W:Modding: Making a custom material, MX.
- **RXN-R16 Side effects.** Only 3 reactions carry an `ExplosionConfig` (`sodium+[water]`, `[slime]+[magic_faster]`, `endslime+[magic_faster]`; ray_energy 50000, radius 5/5, power 30), 5 spawn an entity (`rat_powder`, `fungus_powder*`, `shock_powder`, `just_death` + air), 11 emit cosmetic particles. Source: RJ.
- **RXN-R17 Determinism.** A roll is `cell_rand.below(10000) < round(p*100)` on the stateless per-cell RNG (SIM-R70, decision SD1; `benchmark.md` DET-R04 delegates cell randomness to it); no float compare, no `HashMap` iteration. The compiled table is sorted by `xml_` index and expanded tags are sorted by material id (BTreeMap / sorted Vec). Source: pixel-simulation.md SIM-R70; benchmark.md DET-R04/R05.
- **RXN-R18 Load-time validation.** Fail the load if any referenced id/tag is unknown (the engine itself crashes on unknown input/output names), if `air` is `input_a`, or if a suffix output does not resolve. Assert counts: 466 materials, 330 xml reactions, 79 tag keys. Source: W:Documentation: Reaction.

### C. Fire and burning

- **FIRE-R01 Two mechanisms.** (1) Reactions between a cell and a `[fire]`/`[lava]` cell (RXN). (2) The engine **burning state** of a cell whose material has `burnable=1` or `on_fire=1`. They are independent: **no `<Reaction>` ignites oil, wood, or inert gunpowder from a fire cell**; the only rows that turn a fuel cell into fire are `xml_093/094/095/107/108/150` (+`xml_096`, rock -> fire). Source: RJ (all 330 inspected), `engine_burning_ignite`.
- **FIRE-R02 Four different "burnable/fire" notions.** `burnable=1` attribute (137 materials = `flammable` in MJ; drives FIRE-R03/04); `[burnable]` tag (63; used only by `xml_093` lava ignition; 56 overlap); `on_fire=1` (36: starts burning, e.g. molten metals, `liquid_fire`, `fire`); `[fire]` tag (18 materials). `gunpowder`, `acid_gas`, `meat*` are burnable=1 but not tagged `[burnable]`. Source: MJ, TI.
- **FIRE-R03 Ignition test.** A burning/fire/lava source cell inspects neighbours (GDC reportedly: one random direction per update; UNVERIFIED locally). A neighbour with `burnable=1` can ignite only if `temperature_of_fire(source) > autoignition_temperature(target)` (defaults 10 and 100, so unconfigured materials never ignite). Per-attempt chance is **UNVERIFIED**; proposal D4: `(100 - autoignition)%` (engine precomputes `100 - autoignition`): oil 90%, alcohol_gas 90%, acid_gas/gunpowder 99%, wood_static 15%, coal 6%, 99-autoignition metals/meat 1%. `fire` tof = 100, `lava` tof = 90 (so lava ignites wood (85) but not coal (94) by this test; coal relies on `xml_093`, 8%). Source: MJ, W:Modding: Making a custom material (Fire related), RJ `engine_burning_ignite`.
- **FIRE-R04 Burning and consumption.** A burning cell has a counter initialised to `fire_hp` and emits `fire` cells (`generates_flames`, default 30, 0 on 5 materials) and smoke (`generates_smoke`, default 0, 435 of 466 are 0; gunpowder 10, plants 20). At 0 the cell becomes `on_fire_convert_to_material` (only `wood_player_b2`) else **air - no ash, no charcoal**. `fire_hp=-1` never burns out (`meteorite`, `sulphur_box2d`); `fire_hp=0` is read as "burns out the same update" (gunpowder, alcohol_gas, brick; UNVERIFIED reading of an unset default). Decrement rate and flame/smoke units UNVERIFIED (D5). Source: MJ, W:Modding: Making a custom material, RJ `engine_burning_consume`.
- **FIRE-R05 requires_oxygen.** Default 1; 0 on 103 materials (gunpowder, lava, slime, honey, liquid_fire, gases that burn internally). Reading used here: **=1 -> a cell burns only while at least one 4-neighbour is air/gas; =0 -> burns through its whole volume.** The modding wiki states the opposite ("if 0 only exposed edges burn"); it contradicts the field name, W:Oil ("fire requires air"; submerging in oil douses you) and W:Fire (starve fires of air). Source: W:Fire, W:Oil vs W:Modding: Making a custom material.
- **FIRE-R06 Fuel table (frames of fuel, 60 fps; exact burn rate UNVERIFIED).** gunpowder/alcohol_gas 0; burning_powder 100; gunpowder_tnt 200; gunpowder_unstable 300; oil 500; wood_static 600 (most common: 37 materials); coal 1000; acid_gas/poison_gas 1000; molten metals 90,000; liquid_fire 1,000,000. If 1 fuel/frame: wood 10 s, oil 8.3 s, coal 16.7 s. Wiki: whiskey/flammable gas burn "almost instantly", coal is the slowest common fuel. Source: MJ, W:Fire, W:Oil.
- **FIRE-R07 Fire cells.** `fire` (tof 100, on_fire 1, glow 255) and `flame` (lifetime 5) ignite; the 15 `spark*` have tag `[fire]` but `on_fire=0`, tof 0 (`spark`): **they do not ignite anything but they do trigger `[fire]` reactions** (spark + water -> steam). Fire cell lifetime and motion are UNVERIFIED (render constants `RENDER_FIRE_LIFETIME_MIN/MAX` = 12/30 are cosmetic) -> D6. Source: MX, MJ, `magic_numbers.xml`.
- **FIRE-R08 Water does not put out burning cells.** `[fire]+water -> [fire]+steam` (20%) boils the water; no reaction clears a burning cell. Burning stops by fuel exhaustion, deletion, or losing air (FIRE-R05). W:Fire: spraying water douses creatures, not burning materials; slime extinguishes better. Source: RJ `xml_009`, W:Fire.
- **FIRE-R09 Lava.** Not burnable, `always_ignites_entities=1`, tof 90. Ignites via `[lava]+[burnable]` 8%, `[lava]+[burnable_fast]` 80%, `lava+gunpowder(_explosive)` 8%, `[lava]+alcohol` 60%. `[lava]+water -> rock_static + steam` (80%, blob 6/3) is the "water on lava" mechanic. Source: RJ, W:Lava.
- **FIRE-R10 Explosive materials.** Burning cells of materials with an `ExplosionConfig` detonate when accumulated fire damage reaches `cell_explosion_damage_required`: `gunpowder_explosive` (required 20, ray_energy 400000, power 40, radius_min 8), `gunpowder_tnt` (10, 400000), `gunpowder_unstable` (on_fire, so it detonates when created), `gunpowder_unstable_big` (ray 800000, power 100, radius_min 20), `sodium_unstable` (ray 50000). Destroyed cells become `fire` at `create_cell_probability`. Inert `gunpowder` has no ExplosionConfig. Source: MJ `explosion_config`, RJ `engine_cell_explosion`.
- **FIRE-R11 Always-burning materials** (`on_fire=1`, 36): molten metals/wax (fire_hp 90,000), `liquid_fire`, `gunpowder_unstable*`, `sodium_unstable`. Molten materials re-solidify in water (`[meltable]_molten + water`, 20%, xml_057). Out of MVP. Source: MJ, RJ.
- **FIRE-R12 Entity ignition** by `always_ignites_entities` (21 materials) and fire cells is an entity rule (`DAMAGE-R14`): fire status = 2% of max HP per second (max HP clamped to >= 0.8 internal for this formula), +15% move speed. Source: entities-damage.md, `DT`.

### D. Durability, explosions and digging

- **DUR-R01 Gate.** An explosion/digger may remove a cell only if `cell.durability <= max_durability_to_destroy` (default 10) **and** the ray still has energy (DUR-R02). A cell above the cap is never removed by that source, regardless of hp. Source: W:Documentation: ConfigExplosion, W:Materials (Durability).
- **DUR-R02 Ray model.** From the centre, rays of `ray_energy` (default 20,000) run to `explosion_radius` (default 20 px); each cell crossed consumes its `hp`; the cell is removed if energy was > 0 on arrival (UNVERIFIED but fits "2-3 px of rock" for Unstable Crystal and "20 hp, 100 energy = 5 cells"); the ray ends at energy <= 0 or radius. Ray count and jitter are UNVERIFIED (`RANDOMIZE_LARGE_EXPLOSION_RAYS=1`); cells blocked by the durability cap are assumed to stop the ray (D6). Cells removed per ray = `ceil(E / hp)` (E>0), capped by radius. Source: W:Materials (Hardness), W:Digging, `EC` explosions.
- **DUR-R03 Defaults** (`ConfigExplosion`): radius 20, damage 5, ray_energy 20,000, max_durability 10, hole_enabled true, `hole_destroy_liquid` **false** (liquids in the hole are thrown, not deleted), `hole_destroy_physics_dynamic` true, `create_cell_material` fire @ `create_cell_probability` 5%, knockback_force 1, stains_radius 0 (= 0.3 x radius). Source: W:Documentation: ConfigExplosion.
- **DUR-R04 Per-source values** (Nolla projectile data; `max_dur` = default 10 when not set): see Key numbers "Explosion/digger sources". The wiki durability table is derived from the same values (Spark Bolt 8, Digging Bolt 10, Bomb/TNT 11, Nuke 12, Giga Nuke/Lance/Luminous Drill 14). Source: CE, W:Materials.
- **DUR-R05 Projectile penetration** (not explosion): `ground_penetration_max_durability_to_destroy` (default 0) + `ground_penetration_coeff` let a projectile fly through cells (Luminous Drill: coeff 4, max 14, speed 1400 px/s, 2-frame life). Slowdown formula UNVERIFIED. Source: CE, `EC` projectiles.
- **DUR-R06 Never removable by Matter Eater:** tag `matter_eater_ignore_list` (5: `rock_static_cursed`, `poop_box2d_hard`, 3 `gem_box2d_*sun*`); tag `indestructible` (3 gems) marks the same gems. Black/White Hole dig through the hardest rock (spell rule). Source: TI, W:Digging.
- **DUR-R07 Acid is not durability-gated.** `[acid]+[corrodible] -> [acid]+acid_gas` ignores `durability`/`hp` (a reaction, 50%/update, blob 2/2). Not corrodible (MVP members): `glass_static`, `rock_hard` (Dense Rock), `alcohol`, `oil`, `lava`, `acid`, all gases and `fire`; also `wood_tree` outside MVP. Source: RJ `xml_052`, TI, W:Acid.
- **DUR-R08 Damage scaling by radius** (only when final `c.explosion_radius > 0`): min damage 325 for radius 32-63, 375 for 64-127, 500 for >=128; none below 32. Belongs to spells/damage; listed for cross-reference. Source: W:Explosion_interactions.
- **DUR-R09 Terrain-damage by cell explosions** (`concrete_collapsed`, meteorites) and Box2D breakage are out of MVP. Source: RJ `engine_cell_explosion`.

### E. Material contact damage (per pixel)

- **HAZ-R01 Formula.** Every frame, for each damaging material, `damage = raw_per_pixel x pixels_overlapping_hitbox`; ignored if fewer than `material_damage_min_cell_count` = 4 cells this frame. No type multiplier applies. Raw (internal) x 25 = displayed. Cap when fully submerged: 85 px. Source: W:Documentation: DamageModelComponent, `PS`, entities-damage.md DAMAGE-R11.
- **HAZ-R02 Values** (internal per pixel per frame): acid 0.005; rock_static_cursed 0.005; magic_gas_hp_regeneration -0.005 (heals); rock_static_cursed_green 0.004; lava 0.003; poison, radioactive_gas(_static), rock_static_radioactive, rock_static_poison, ice_radioactive_*, ice_acid_* 0.001; blood_cold 0.0009; blood_cold_vapour 0.0006; cursed_liquid 0.0005; gold_radioactive 0.0002; poo_gas 0.00001. Displayed DPS per pixel = raw x 25 x 60 (acid 7.5, lava 4.5, poison 1.5). Source: W:Materials (Player damage), `PS`.
- **HAZ-R03 Storage.** Damage is a property of the **entity's** damage model (`materials_that_damage` / `materials_how_much_damage`), not of the material; MJ `damage_to_entities` is a convenience copy for the player only. Enemies need their own tables. Source: W:Modding: Making a custom material.
- **HAZ-R04 Stains/status** (Toxic Sludge, oil, water, slime) are statuses, not contact damage: `radioactive_liquid` has no per-pixel entry. See DAMAGE-R17/R18. Source: MJ, entities-damage.md.
- **HAZ-R05 Mitigation** is by Ambrosia / Stainless Armour only; Fire Immunity does not stop lava contact damage. Source: W:Acid, W:Lava.

### F. MVP set (tables follow this list)

- **MVP-R01** The clone ships exactly the 40 materials of the MVP-40 table; stretch ids are listed there. Satisfies PRD R1 (>= 40 materials from the wiki).
- **MVP-R02** The clone executes the 39 reactions of the MVP reaction table (all inputs and outputs inside MVP-40, 2 inputs, p > 0) and the engine systems FIRE-R03..R10 and DUR-R01..R03. Everything else in `RJ` is data-only.
- **MVP-R03** Dropped by design: 3-input reactions (32), ReqReactions (5), entity-spawning (5), explosion reactions except `sodium+[water]` (kept as a simple explosion), Box2D conversions, `req_lifetime` gating (D8), reactions whose outputs are outside MVP-40.
- **MVP-R04** Content is immutable at runtime and hashed into `content_hash` (benchmark.md VER-R03); id->index mapping follows MAT-R01.
- **MVP-R05** Entity/projectile collision classes derive from kind: static, powder, solid = blocking; liquid = buoyant, non-blocking; gas, fire = pass-through. Projectiles ignore liquids (`die_on_liquid_collision` default false).

### MVP-40 materials (MVP-R01)

Columns: density, hp, durability, fuel = `fire_hp` ("-" not burnable; "on" = starts burning), aut = autoignition, tof = temperature_of_fire, life = lifetime frames, lg/visc = liquid_gravity/viscosity (liquids, powders), O2 = requires_oxygen. All from `MJ`.

| id | name | kind | dens | hp | dur | fuel | aut | tof | life | lg | visc | O2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `air` | Air | liquid | 1 | 100 | 0 | - | - | 10 | - | 0.5 | 50 | 1 |
| `fire` | Fire | fire | 1 | 100 | 0 | on | 100 | 100 | - | - | - | 1 |
| `smoke` | Smoke | gas | 1 | 100 | 0 | - | - | 60 | 350 | - | - | 0 |
| `steam` | Steam | gas | 1 | 100 | 0 | - | - | 60 | 1000 | - | - | 0 |
| `acid_gas` | Flammable Gas | gas | 2 | 100 | 0 | 1000 | 1 | 60 | 450 | - | - | 0 |
| `alcohol_gas` | Whiskey Fumes | gas | 1 | 100 | 0 | 0 | 10 | 80 | 50 | - | - | 1 |
| `poison_gas` | Poison Gas | gas | 2 | 100 | 0 | 1000 | 1 | 60 | 450 | - | - | 0 |
| `radioactive_gas` | Toxic Gas | gas | 2 | 100 | 0 | - | - | 10 | 450 | - | - | 1 |
| `water` | Water | liquid | 4 | 100 | 0 | - | - | 10 | - | 1.5 | 50 | 1 |
| `oil` | Oil | liquid | 1 | 100 | 0 | 500 | 10 | 95 | - | 0.5 | 50 | 1 |
| `alcohol` | Whiskey | liquid | 3.5 | 100 | 0 | - | - | 10 | - | 1.2 | 50 | 1 |
| `acid` | Acid | liquid | 2.9 | 100 | 0 | - | - | 10 | - | 0.6 | 50 | 1 |
| `lava` | Lava | liquid | 6 | 100 | 0 | - | - | 90 | - | 0.2 | 10 | 0 |
| `blood` | Blood | liquid | 4.1 | 100 | 0 | - | - | 10 | - | 0.7 | 50 | 1 |
| `cement` | Cement | liquid | 6 | 1000 | 0 | - | - | 10 | - | 0.5 | 15 | 1 |
| `poison` | Poison | liquid | 3 | 100 | 0 | - | - | 10 | - | 0.5 | 50 | 1 |
| `radioactive_liquid` | Toxic Sludge | liquid | 3 | 100 | 0 | - | - | 10 | - | 0.5 | 50 | 1 |
| `sand` | Sand | powder | 6 | 800 | 4 | - | - | 10 | - | 0.9 | 50 | 1 |
| `soil` | Soil | powder | 6 | 2000 | 10 | - | - | 10 | - | 0.5 | 75 | 1 |
| `mud` | Mud | powder | 6 | 2000 | 0 | - | - | 10 | - | 0.3 | 75 | 1 |
| `coal` | Coal | powder | 6 | 1000 | 8 | 1000 | 94 | 95 | - | 2 | 50 | 1 |
| `snow` | Snow | powder | 8 | 1000 | 0 | - | - | 10 | - | 0.6 | 50 | 1 |
| `gunpowder` | Gunpowder (inert) | powder | 7 | 1000 | 0 | 0 | 1 | 80 | - | 2 | 50 | 0 |
| `gunpowder_explosive` | Gunpowder | powder | 7 | 1000 | 0 | 0 | 1 | 50 | - | 2 | 50 | 0 |
| `sodium` | Sodium | powder | 6 | 1000 | 0 | - | - | 10 | - | 2 | 50 | 1 |
| `gold` | Gold | powder | 9 | 8000 | 12 | - | - | 10 | - | 3 | 50 | 1 |
| `rock_static` | Rock | static | 10 | 100000 | 10 | - | - | 10 | - | - | - | 1 |
| `rock_hard` | Dense Rock | static | 10 | 200000 | 10 | - | - | 10 | - | - | - | 1 |
| `sand_static` | Ground | static | 10 | 19000 | 10 | - | - | 10 | - | - | - | 1 |
| `coal_static` | Coal Vein | static | 8 | 25000 | 10 | - | - | 10 | - | - | - | 1 |
| `concrete_static` | Concrete | static | 10 | 30000 | 0 | - | - | 10 | - | - | - | 1 |
| `wood_static` | Wood | static | 11 | 2000 | 10 | 600 | 85 | 90 | - | - | - | 1 |
| `ice_static` | Ice | static | 10 | 30000 | 0 | - | - | 10 | - | - | - | 1 |
| `glass_static` | Glass | static | 10 | 30000 | 0 | - | - | 10 | - | - | - | 1 |
| `templebrick_static` | Brickwork | static | 10 | 1000000 | 14 | - | - | 10 | - | - | - | 1 |
| `steel_static` | Steel | static | 10 | 130000 | 12 | - | - | 10 | - | - | - | 1 |
| `lavarock_static` | Volcanic Rock | static | 10 | 90000 | 0 | - | - | 10 | - | - | - | 1 |
| `rock_static_grey` | Grey Rock | static | 10 | 150000 | 10 | - | - | 10 | - | - | - | 1 |
| `rock_static_poison` | Poisonous Rock | static | 10 | 20000 | 10 | - | - | 10 | - | - | - | 1 |
| `rock_static_radioactive` | Toxic Rock | static | 10 | 20000 | 10 | - | - | 10 | - | - | - | 1 |

Inclusion rule: covers every kind except Box2D `solid`; closes under the MVP reactions (no output id outside the set); includes the PRD hazards (acid, lava, poison, toxic), fuels (oil, coal, wood, gunpowder), terrain strata and the durability ladder 0/4/8/10/12/14. **Stretch (+12, each needs the listed output to keep closure):** `salt`+`water_salt` (xml_043), `water_ice` (xml_023/025/031), `slime`+`cloud_slime`+`endslime` (xml_078/171/172/292), `gold_molten` (xml_059), `water_swamp`+`swamp` (xml_036/176), `spark` (cosmetic, FIRE-R07), `grass`, `moss`.

### MVP reactions (MVP-R02)

Ids are `reactions.json` ids; `[tag]` expanded per RXN-R06/R07 over MVP-40. "blob a/b" per RXN-R10.

| id | A + B | -> out A + out B | p % | flags |
|---|---|---|---|---|
| xml_000 | cement + concrete_static | concrete_static + concrete_static | 70 | req_life 300 (ignored, D8) |
| xml_002 | cement + [lava] | rock_static_grey x2 | 80 | |
| xml_003 | cement + water | concrete_static + air | 100 | req_life 600 (ignored) |
| xml_005 | cement + air | concrete_static + air | 90 | req_life 300 (ignored) |
| xml_006 | water + cement | concrete_static + air | 100 | |
| xml_007 | steam + [static] | water + [static] | 3 | 14 MVP members incl. `snow` |
| xml_009 | [fire] + water | [fire] + steam | 20 | |
| xml_010 | [fire] + snow | [fire] + steam | 20 | tried before xml_015 |
| xml_013 | [fire] + ice_static | [fire] + water | 40 | |
| xml_015 | [fire] + snow | [fire] + water | 80 | |
| xml_016 | [fire] + [meltable_to_water] | [fire] + water | 60 | ice_static, snow |
| xml_021 | ice_static + air | water + air | 1 | |
| xml_035 | water + radioactive_liquid | water + water | 13 | |
| xml_041 | snow + radioactive_liquid | water + radioactive_liquid | 5 | |
| xml_046 | sodium + [water] | sodium + steam | 50 | explosion: power 30, radius 5/5, ray 50,000 |
| xml_052 | [acid] + [corrodible] | [acid] + acid_gas | 50 | fast, blob 2/2; 26 MVP corrodible members incl. water |
| xml_053 | [acid] + air | acid_gas + air | 10 | fast |
| xml_054 | [acid] + acid_gas | acid_gas + air | 12 | fast |
| xml_065 | [lava] + water | rock_static + steam | 80 | blob 6/3 |
| xml_067 | [lava] + mud | sand_static + steam | 80 | blob 4/4 |
| xml_079 | [lava] + blood | lavarock_static + steam | 70 | blob 4/4 |
| xml_086 | [lava] + [radioactive] | rock_static_radioactive + radioactive_gas | 70 | blob 4/4; only `radioactive_liquid` |
| xml_089 | [lava] + poison | rock_static_poison + poison_gas | 70 | blob 4/4 |
| xml_093 | [lava] + [burnable] | [lava] + fire | 8 | alcohol_gas, coal, oil, wood_static |
| xml_094 | [lava] + [burnable_fast] | [lava] + fire | 80 | acid_gas, poison_gas |
| xml_095 | [fire] + [burnable_fast] | [fire] + fire | 40 | |
| xml_096 | [lava] + [meltable_to_lava] | smoke + fire | 3 | lava cell -> smoke, rock cell -> fire (literal) |
| xml_097 | [lava] + [meltable_to_lava_fast] | smoke + lava | 80 | `sand` becomes lava |
| xml_098 | [lava] + [meltable_to_water] | [lava] + water | 60 | |
| xml_107 | [lava] + gunpowder | [lava] + fire | 8 | |
| xml_108 | [lava] + gunpowder_explosive | [lava] + fire | 8 | |
| xml_111 | [evaporable] + air | air + air | 15 | only `alcohol_gas` |
| xml_150 | coal + fire | fire + air | 20 | coal cell -> fire, old fire cell -> air (literal) |
| xml_166 | alcohol + [fire] | [fire] + alcohol_gas | 60 | literal: alcohol cell -> fire, fire cell -> gas (D11) |
| xml_167 | alcohol + [lava] | [fire] + alcohol_gas | 60 | literal: lava cell -> gas! (D11); output tag -> `fire` |
| xml_168 | alcohol + air | alcohol + alcohol_gas | 4 | |
| xml_169 | [fire] + alcohol_gas | alcohol_gas + alcohol_gas | 20 | fire cell -> gas (literal) |
| xml_179 | poison + air | poison_gas + air | 15 | fast |
| xml_183 | water + soil | air + mud | 5 | |

Dropped with reason (closure/3-input): xml_001, 184, 185 (3 inputs); xml_023/025/031 (`water_ice`); xml_036/176 (`water_swamp`); xml_043/044 (`water_salt`); xml_059/280 (molten); xml_064 (p = 0); xml_120/146 (grass/moss); xml_180 (rust); xml_292/293 (slime).

---

## Key numbers

| Constant | Value | Unit | Note / source |
|---|---|---|---|
| Frame rate | 60 | Hz | `EC`; all lifetimes below in frames |
| Materials in data / unique ids / engine cap | 468 / 466 / 1024 | count | MAT-R01 |
| Kinds (solid/static/liquid/powder/gas/fire) | 132/103/100/87/26/18 | count | MAT-R03 |
| Tag keys (incl. `*`, `any_liquid`, `any_powder`) | 79 | count | `TI` |
| Reactions: xml / ReqReaction / engine pseudo / total | 330 / 5 / 9 / 339 | count | RJ (325 `<Reaction>` + 5 `<ReqReaction>`) |
| Reactions with tag input / 3rd input / 3rd output | 162 / 32 / 15 | count | RJ |
| Reactions with blob / fast / direction / req_lifetime / explosion / entity | 54 / 13 / 18 / 5 / 3 / 5 | count | RJ |
| Probability resolution | 0.01 (percent) | % | `int(p*100)`; 0..100 observed |
| Default: density / durability / hp | 1 / 0 / 100 | - | MAT-R04 |
| Default: liquid_gravity / viscosity / flow_speed / damping | 0.5 / 50 / 0.9 / 0.8 | - | |
| Default: gas speed / up / horizontal / down | 50 / 100 / 100 / 90 | - | |
| Default fire: autoignition / temperature_of_fire / fire_hp | 100 / 10 / 0 | - | `generates_flames` 30, `generates_smoke` 0, `requires_oxygen` 1 |
| Default flame / smoke material | `fire` / `smoke` | id | `on_fire_flame_material`, `on_fire_smoke_material` |
| hp range / most common | 5-1,000,000 / 100 (167) | - | MAT-R11; rock_static 100,000, templebrick 1,000,000 |
| durability range / unset | 0-16 / 329 materials | - | 0:329, 2:1, 3:5, 4:9, 5:1, 8:7, 9:9, 10:47, 11:8, 12:15, 13:1, 14:30, 15:1, 16:3 |
| Durability examples | sand 4, cheese 5, coal 8, static meat 9, soil/rock/rock_hard 10, steel 12, brickwork 14 | - | W:Materials |
| fire_hp (frames of fuel) | wood_static 600, oil 500, coal 1000, gunpowder 0, molten metal 90,000 | frames | FIRE-R06 |
| autoignition / tof of key fuels | oil 10/95, alcohol_gas 10/80, gunpowder 1/80, wood 85/90, coal 94/95, fire -/100, lava -/90 | temp units | |
| Gas lifetime | steam 1000, smoke 350, acid/poison/toxic gas 450, alcohol_gas 50, flame 5 | frames | `lifetime_frames` |
| Density (liquids) | oil 1, acid 2.9, poison/toxic sludge 3, whiskey 3.5, water 4, blood 4.1, lava 6, cement 6 | - | W:Density, MJ |
| Density (powders) | sand/soil/coal/mud 6, gunpowder 7, snow 8, gold 9 | - | MJ |
| ConfigExplosion default | radius 20, ray_energy 20,000, max_dur 10, damage 5, fire 5% | px/-/-/-/% | DUR-R03 |
| Explosion/digger sources (radius px / ray_energy / max_dur / fire%) | see next table | | CE |
| Explosion damage floor by radius | 32-63: 325, 64-127: 375, >=128: 500 | displayed HP | DUR-R08 (W:Explosion_interactions quotes displayed values) |
| Contact damage raw (internal/px/frame) | acid 0.005, lava 0.003, poison 0.001 | x25 = display | HAZ-R02 |
| Contact damage display (per px per frame / per px per second) | acid 0.125 / 7.5; lava 0.075 / 4.5; poison 0.025 / 1.5 | HP | |
| Min cells for contact damage / max submerged px | 4 / 85 | count | HAZ-R01 |
| Player HP | 4.0 internal = 100 shown | x25 | `PS` |
| On Fire status | 2% max HP/s, +15% speed | | DAMAGE-R14 |

| Source (name, spell `GAME_ID`) | radius px | ray_energy | max_dur | fire % | Note |
|---|---|---|---|---|---|
| Spark Bolt (`LIGHT_BULLET`) | 2 | 400,000 | 8 | 0 | damage 0 |
| Magic Arrow (`BULLET`) | 2 | 400,000 | 8 | 0 | |
| Energy Sphere (`BOUNCY_ORB`) | 2 | 200,000 | 8 | 0 | |
| Energy Orb (`SLOW_BULLET`) | 15 | 350,000 | 10 (default) | 0 | |
| Digging Bolt (`DIGGER`) | 6 | 100,000 | 10 | 0 | `is_digger` |
| Digging Blast (`POWERDIGGER`) | 7 | 200,000 | 10 | 0 | |
| Fireball (`FIREBALL`) | 15 | 50,000 | 10 (default) | 100 | |
| Magic Missile (`ROCKET`) | 15 | 4,000,000 | 10 (default) | 10 | |
| Bomb (`BOMB`) | 60 | 6,000,000 | 11 | 40 | damage 5 |
| Dynamite (`DYNAMITE`) | 28 | 6,000,000 (not in `tnt.xml`: inherited from `base_projectile_physics.xml` via `<Base>`, checked in raw/game; spells.md TV-D5) | 11 | 0 (inherited) | damage 2.5 |
| Unstable Crystal (`MINE`) | 30 | 170,000 / 280,000 (two configs) | 10 (default) | 80 | |
| Nuke (`NUKE`) | 250 | 6,700,000 | 12 | 5 | |
| Giga Nuke / Giga Holy Bomb (`NUKE_GIGA` / `BOMB_HOLY_GIGA`) | 400 / 320 | 9,700,000 / 12,400,000 | 14 | 5 / 80 | |
| Luminous Drill (`LUMINOUS_DRILL`) | - | penetration: coeff 4, max 14 | 14 | - | DUR-R05 |
| Chainsaw (`CHAINSAW`) | 3 | 20,000 | 10 (default) | 0 | |

---

## Data files

| File (under `.trellis/tasks/10-16-noita-cogbench/research/`) | Records | Role |
|---|---|---|
| `materials.json` | 466 (array, sorted by `xml_order`) | **Canonical material table** (resolved defaults + inheritance). Index by `id`. |
| `reactions.json` | 339 (330 `xml_*` + 9 `engine_*`) | **Canonical reaction table**; load only `xml_*`; `engine_*` = docs (RXN-R01). Fields typed as in RXN-R02..R16. |
| `tags_index.json` | `{_note, tags{79}}` | **Canonical tag membership** (derived from resolved XML tags + engine tags). |
| `raw/materials_xml_parsed.json` | 468 elements | Per-element `raw_attrs`, `children` (Graphics, StatusEffects, ExplosionConfig), `parent_chain`, `resolved`. Debug/provenance only. |
| `raw/reactions_xml_parsed.json` | 330 | Raw attribute strings per reaction. Provenance only. |
| `materials_from_data_xml.json` | 469 | 20-field un-inherited subset incl. a duplicate; **do not use**. |
| `raw/cargo_Materials.json`, `materials_from_wiki.json` | 466 / 212 | Wiki Cargo / infobox rows (hardness, durability, notes). Cross-check only; wiki `durability` is null when unset. |
| `noita-engine-constants.json`, `player-stats.json`, `damage-types.json` | - | Engine/entity constants (explosion defaults, contact damage, x25). |
| `raw/noitadata/data/materials.xml`, `raw/game/entities/projectiles/**` | - | Nolla copyrighted data: numbers only; never paste markup or Lua. |

**Loading.** Parse `materials.json`, apply MAT-R01 numbering, build `tag -> sorted ids` from `tags_index.json`, compile `reactions.json` per RXN-R02..R08 into per-(idA,idB) candidate lists sorted by `xml_` index, then assert RXN-R18 counts and compute `content_hash`.

**`materials.json` fields** (C = canonical from XML, D = derived/curated, X = wiki/curated extra):

| Field | Type / observed range | Meaning | |
|---|---|---|---|
| `id`, `name`, `wiki_page`, `wiki_type` | string | id = XML name; `name` = display (two ids both named "Gunpowder": `gunpowder` inert, `gunpowder_explosive` explosive) | C/X |
| `kind`, `cell_type` | enum | MAT-R03 (`cell_type` is the XML value; liquid covers 290) | D / C |
| `parent`, `inherits_reactions` | id / 1,0,null | MAT-R05/R06 | C |
| `tags` | [string] | resolved tag list (child replaces parent) | C |
| `density` | float 1-50 | MAT-R08 | C |
| `durability`, `hp` | int 0-16 / 5-1e6 | MAT-R12, R11 | C |
| `flammable`, `fire_hp`, `fire_hp_is_engine_default`, `starts_on_fire` | bool / int -1..99,999,999 / bool / bool | `burnable`, fuel, `fire_hp` was unset (=0), `on_fire` | C |
| `burns_into`, `on_fire_convert_to_material_raw` | string | burn product; text "air (engine default...)" or "never consumed" is **prose, not an id** | D |
| `autoignition`, `temperature_of_fire`, `requires_oxygen` | 0-100 / 0-200 / bool | FIRE-R03/R05 | C |
| `generates_smoke`, `generates_flames`, `on_fire_flame_material`, `on_fire_smoke_material`, `always_ignites_entities` | 0-250 / 0-30 / id / id / bool | FIRE-R04 | C |
| `gravity{liquid_gravity,solid_gravity_scale,gas_*}` | floats or null | null where the kind does not use it | C |
| `dispersion{liquid_viscosity,flow_speed,damping,slime,sticks_to_ceiling,stickyness}` | numbers | MAT-R09 | C |
| `lifetime_frames` | 0-1350 | MAT-R10 (4.0 on the 4 entity-spawning powders `rat_powder`, `fungus_powder*`, `shock_powder`; not MVP) | C |
| `color_rgb`, `color_alpha`, `graphics_color_argb`, `texture_file`, `palette`, `palette_avg`, `wang_color_argb`, `gfx_glow`, `gfx_glow_color` | colour data | MAT-R15 | C / D (palette from PNG) |
| `electrical_conductivity`, `slippery`, `stainable`, `platform_type`, `liquid_stains` | 0-1 / bool / bool / -1..2 / 0-4 | MAT-R04, R13; conductivity 138 of 466 | C |
| `freezes_to`, `cold_freezes_chance_rev`, `melts_to`, `warmth_melts_chance_rev`, `break_into`, `convert_to_box2d_material` | id / int | MAT-R14/R16 | C |
| `solid{...}` | object (132 solids) | Box2D params: `solid_static_type` 0-5, crackability, friction, restitution | C |
| `explosion_config` | object (15 materials) | FIRE-R10 | C |
| `damage_to_entities`, `stain_effect`, `submerge_effect`, `ingest_effect`, `danger{}`, `biomes`, `notes`, `xml_order`, `xml_element`, `source` | misc | HAZ-R03; `danger` is AI-only; `notes` are curated prose (see Pitfalls for errors) | X / D |

**`reactions.json` xml-record fields:** `id`, `source`, `input_a/b/c`, `output_a/b/c` (ids, `[tag]`, `[tag]_suffix`), `probability` (percent), `fast_reaction`, `req_reaction`, `convert_all`, `blob_radius_a/b`, `blob_restrict_a/b`, `direction`, `req_lifetime`, `destroy_horizontally_lonely_pixels`, `entity`, `cosmetic_particle`, `audio_fx_volume_1`, `explosion{...}`, `is_tag_rule`, `tag_member_counts`, `notes`. `probability_semantics` is prose. Pseudo-records carry `mechanism` instead and have prose in `input_*`.

---

## Worked examples / test vectors

No material test-case JSON exists yet (`wand-cast-test-cases.json` is wands only). Vectors below get IDs `MV-nn`; implement them as unit tests, probabilistic ones as seeded frequency tests (10,000 trials, tolerance 4 sigma).

| ID | Input | Expected |
|---|---|---|
| MV-01 kind | `sand`, `rock_static`, `water`, `steam`, `fire`, `metal` | powder, static, liquid, gas, fire, solid (Box2D) |
| MV-02 counts | load `materials.json` / `reactions.json` / `tags_index.json` | 466 / 339 (330 `xml_` + 9 `engine_`) / 79 keys; kinds 132/103/100/87/26/18 |
| MV-03 tag size | `fire`, `water`, `lava`, `corrodible`, `any_liquid`, `any_powder` | 18, 37, 1, 279, 104, 186 members; `alcohol` in `water`; `spark` in `fire`; `air` in `any_liquid` |
| MV-04 child tags | `poison` tags; `coal_static` tags | no `radioactive` in `poison`; `coal_static` == `rock_static` tags |
| MV-05 positional | cells `[fire]` at (0,0), `water` at (1,0), run xml_009 | (0,0) stays fire, (1,0) -> steam; with `spark` at (0,0) result is spark + steam |
| MV-06 suffix | `copper` next to `lava`, xml_059 succeeds | copper cell -> `copper_molten`, lava unchanged (needs `copper_molten` to exist or the reaction is dropped with warning) |
| MV-07 sequential | `fire` next to `snow`, 100,000 examinations | steam 0.20, water 0.64, nothing 0.16 (+-0.01) under RXN-R05 |
| MV-08 probability | p=0.3, 70, 100, 0 | thresholds 30, 7000, 10000, 0 of 10000 |
| MV-09 blob | lava cell L, water cell W adjacent, xml_065 fires | all lava within r<=6 of L -> rock_static; all water within r<=3 of W -> steam; other materials untouched |
| MV-10 acid | acid next to sand, xml_052 fires | acid unchanged; sand cells within r<=2 of the sand cell -> acid_gas (13 cells for a disc) |
| MV-11 density | stack water over oil; oil over water; blood over water | oil rises above water; stays; blood sinks below water (4.1 > 4); equal densities never swap |
| MV-12 gas life | `steam` created at frame f, no condensation | removed at f+1000 (16.7 s); smoke f+350 (5.8 s); alcohol_gas f+50 |
| MV-13 gates | `LIGHT_BULLET` Spark Bolt (max_dur 8) on sand(4), coal(8), soil(10), rock_static(10) | removes sand, coal; leaves soil, rock |
| MV-14 digger | `DIGGER` Digging Bolt (ray 100,000, r 6, max_dur 10) on soil (hp 2000); rock_static (hp 100,000); steel_static (dur 12) | ray removes min(50, 6) = 6 cells deep (full radius); 1 cell per ray; nothing |
| MV-15 coal vs rock | `SLOW_BULLET` Energy Orb (ray 350,000, r 15) in coal_static (hp 25,000); in rock_static | ceil(350000/25000) = 14 cells per ray; ceil(3.5) = 4 cells (wiki figure caption: coal far deeper than rock) |
| MV-16 bomb | `BOMB` (ray 6,000,000, r 60, max_dur 11): rock_static; steel_static; templebrick_static | clears r=60 in rock (60 cells x 100,000 = 6,000,000); steel (12) and brickwork (14) untouched |
| MV-17 crystal | `MINE` Unstable Crystal (170,000): rock_static | 2 cells per ray (wiki: "2-3 px of rock") |
| MV-18 contact | player fully in acid (85 px) / in lava (20 px) / 3 px acid | acid 0.425 internal = 10.625 shown per frame (637.5/s; 100 HP gone in 10 frames); lava 0.06 = 1.5 shown; 3 px < 4 -> 0 |
| MV-19 ignition (D4) | `fire` adjacent to wood_static / oil / coal / sulphur | per-attempt 15% / 90% / 6% / never (aut 100) once the adjacency test passes |
| MV-20 burn out (D5) | ignite wood_static at frame 0, 1 fuel/frame, always air-exposed | becomes air at frame 600; no ash; burning gunpowder_explosive detonates after 20 fire damage |
| MV-21 oxygen | wood block, ignite one interior cell fully enclosed by wood | does not burn (requires_oxygen=1); gunpowder interior cell does burn (=0) |
| MV-22 cement | cement + water (xml_006) | cement cell -> concrete_static, water cell -> air, p=100 |
| MV-23 lava+water | pour water onto lava pool | a rock_static crust plus steam; steam later condenses on `[static]` at 3% per examination |

---

## Pitfalls and common misreadings

1. **`kind=solid` is not terrain.** Terrain is `static` (cell_type liquid + sand + static). `materials.md` calls solid "static platforms"; wrong (MAT-R03).
2. **There is no generic fire -> fuel reaction.** `materials.md` lists `oil+[fire] -> burning_powder+air`, `gunpowder+[fire] -> air+air`, `[burnable]+[fire] -> ...`, `blood+air -> pus`, `wood_static+air`, `coal+air`, `magic_liquid+water -> air`: none exists in `reactions.json`. Burning is the engine state (FIRE-R03/04); the only fuel->fire rows are xml_093/094/095/096/107/108/150.
3. **Reactions rewrite both cells.** In `[fire]+water -> [fire]+steam` the water is consumed; `materials.md`'s "fire does not consume inputs" is only true for the fire side.
4. **Probability is a float percent**, not an int 1-100 (0.3 exists, resolution 0.01 %).
5. **`[burnable]` tag != `burnable=1`** (63 vs 137); `[static]` != kind static; `[water]` != water (whiskey, magic liquids, `pus` match, so `sodium+[water]` explodes in whiskey); `[fire]` includes inert sparks.
6. **Tag outputs refer to the matched member**, not to a fixed material; `[x]_molten` is id + suffix.
7. **Child `tags` replace the parent's**; reaction inheritance needs `_inherit_reactions=1` (`water_fading` does not inherit water's reactions, which is why xml_069 exists).
8. **`air` is a real material** (id 0, kind liquid, `any_liquid` member); it is never `input_a` of a reaction (`input_b` in 54, `input_c` in 11).
9. **Same display name, two ids:** `gunpowder` (inert) vs `gunpowder_explosive`; `ice` (powder) vs `ice_static`; `water_ice` is "Chilly Water", not slush.
10. **`color_rgb` is not the render colour** for textured materials (MAT-R15).
11. **Durability 0 does not mean "indestructible".** It means unset; `concrete_static`, `ice_static`, `glass_static`, `lavarock_static`, `snow_static` (29 statics) are removable by anything with enough ray energy. The wiki durability table says "Concrete 8"; the XML has none (MX is the source of record, D7).
12. **hp is ray cost, not entity damage;** `hp` 100,000 means one cell eats a 100,000 ray (Digging Bolt removes 1 cell of rock per ray).
13. **Wiki durability range is 0-14**, data reaches 15-16 (gems with tag `indestructible`).
14. **`requires_oxygen` is documented backwards on the modding wiki** (FIRE-R05).
15. **Output order is positional**; several reactions look swapped (alcohol/lava, coal+fire, `[lava]+[meltable_to_lava]`). Implement literally, flag with D11.
16. **Contact damage lives on the entity**, applies per pixel per frame with a 4-cell floor and no multipliers; Toxic Sludge hurts through a status, not per pixel.
17. **No temperature, no ash:** wood burns to air; `temperature_of_fire` is an input of the ignition test (modding wiki), not cosmetic as `materials.md` states; `autoignition` is used.
18. **`alcohol_gas` is not `[burnable_fast]`** (`materials.json` note is wrong; `TI`: burnable_fast = acid_gas, acid_gas_static, fungal_gas, poison_gas).

### Source disagreements and rulings

| Topic | Source A | Source B | Ruling and why |
|---|---|---|---|
| Meaning of `solid` | `materials.md`: static platforms | W:Modding: Making a custom material + MJ: Box2D bodies | B: primary doc and 132 data rows (wood boxes, ice shards) |
| Reaction inventory | `materials.md`: 339 binary reactions + a "~30 MVP" list | RJ: 330 xml + 9 pseudo, 32 with a 3rd input; list items mostly absent | B: RJ is parsed from MX; the list was not checked against it |
| Fire spreads by reaction | `materials.md` (`X+[fire] -> fire+X`) | MX/RJ: no such row | B (FIRE-R01) |
| `autoignition`, `temperature_of_fire` | `materials.md`: unused / cosmetic | W:Modding (tof makes neighbours ignite easier), RJ `engine_burning_ignite` (precomputed `100-autoignition`) | B: defaults aut 100 / tof 10 make unconfigured materials inert, which only makes sense if the test exists; exact formula still UNVERIFIED |
| `requires_oxygen` | W:Modding: "if 0 only edges burn" | field name, W:Oil, W:Fire, RJ | B (FIRE-R05) |
| Probability type | `materials.md`: integer 1-100 | W:Documentation: Reaction (float x100) + `xml_185` = 0.3 | B |
| Concrete durability | W:Materials table + MJ note: 8 | MX: `concrete_static` unset (0); wiki table also lists `coal` 8 correctly | MX is the source of record; D7 |
| Durability range | W:Materials: 0-14 | MX: up to 16 | MX (gems tagged `indestructible`) |
| Duplicate ids | `build_materials_json.py`: first wins | W:Modding: later overwrites | keep first; irrelevant to MVP (`rock_box2d`, `meat_pumpkin` are Box2D) |
| `alcohol_gas` class | MJ note: `burnable_fast` | TI: tags are `burnable`, `evaporable` | TI (derived from XML) |
| Energy Orb ray energy | W:Materials caption: 350,000 | W:Energy Sphere infobox: 200,000 | different spells (`SLOW_BULLET` vs `BOUNCY_ORB`); both match CE |
| Fire cell lifetime | RJ note: render constants 12-30 frames | `magic_numbers.xml`: `RENDER_FIRE_*` are cosmetic | UNVERIFIED; D6 uses 12-30 as a tunable default only |
| Ignition quote | RJ: "GDC 2019 random direction" | not present in local sources | UNVERIFIED; D4 |

---

## Our simplifications (MVP)

| ID | Topic | Default (what the clone does) | Why / alternatives |
|---|---|---|---|
| D1 | Set size | MVP-40 + stretch list | PRD needs >= 40; DECISION-NEEDED: approve list (e.g. swap `poison`/toxic for `slime`) |
| D2 | Reaction cadence | each non-air cell examined this frame picks **one** random 4-neighbour and tries the candidate list; pair is symmetric (RXN-R04). Probability a given pair is examined in a frame = 1-(3/4)^2 = 0.4375, so effective rate ~ 0.44 p per frame | Engine cadence unknown; DECISION-NEEDED: all 4 neighbours (4x faster) or 8-neighbour. Calibrate by feel (water+lava crust forms in a few frames) |
| D3 | Fast/ordering | ignore `fast_reaction`; file order only | UNVERIFIED engine order |
| D4 | Ignition chance | `(100-autoignition)%` per attempt, test `tof > aut`, one random 4-neighbour per burning cell per frame | UNVERIFIED; alternative: flat 50% above threshold |
| D5 | Fuel/flames/smoke | 1 fuel per frame; the `u8` `burn` counter uses a per-material tick unit, `burn_unit = max(1, ceil(fire_hp/250))`, `fire_hp` -1 or >= 90,000 = endless (pixel-simulation.md SIM-R35, SD2, which supersedes the earlier global 8-frame quantum); flame spawn chance `generates_flames/100` per update into a random free neighbour; smoke `min(100,generates_smoke)%` | cell `burn` is u8; units unknown; tune visually |
| D6 | Fire cell life / explosion rays | fire cell life uniform 12-30 frames, moves like a gas; explosion uses `max(16, ceil(2*pi*r))` evenly spaced rays with seeded jitter; durability-blocked cell stops the ray; liquids in the hole are pushed out, not deleted | UNVERIFIED; matches `hole_destroy_liquid=false` |
| D7 | Durability 0 | use XML value (0), i.e. concrete/ice/glass weak; hp still protects | wiki says concrete 8: DECISION-NEEDED only if an MVP spell has max_dur < 8 (none does; `EXPLOSION_LIGHT` 2 is not MVP) |
| D8 | `req_lifetime`, gas lifetime | ignore `req_lifetime` (cement sets on first contact); the `u8` `life` counter uses a per-material tick unit `life_unit` (smallest `u >= 1` with `ceil(lifetime/u) <= 255`; steam 1000 f = unit 4 x 250), exact for all 15 lifetimes (pixel-simulation.md SIM-R35, SD2; supersedes the earlier global 8-frame quantum) | cell `life` is u8; alt. widen to `u16` per cell (+1 byte/cell) |
| D9 | Blob geometry | cells with `dx^2+dy^2 <= r^2` around the reacting cell, restricted to the matched material | metric UNVERIFIED; alt. Chebyshev square |
| D10 | 3-input / ReqReaction | dropped | semantics UNVERIFIED |
| D11 | Swapped-looking reactions | literal positional outputs; `[fire]` output with no input tag -> `fire` | alt. "intent" reading (alcohol -> gas, fire stays): DECISION-NEEDED, low impact |
| D12 | Numeric ids | rank by `xml_order`, stored `u16`, mapping hashed in `content_hash` | determinism |
| D13 | Box2D | none; all rigid-body materials absent; ice/glass are plain statics | PRD non-goal |

---

## Open questions

1. How many neighbours does the engine examine per cell per frame, and does it test reactions for both cells of a pair (RXN-R04, D2)?
2. Is `fast_reaction` an ordering flag, an extra-pass flag, or a no-op? Is XML order really the priority (RXN-R05, D3)?
3. Exact ignition roll and the role of `temperature_of_fire` vs `autoignition_temperature`; per-update `fire_hp` decrement; units of `generates_flames/smoke` (FIRE-R03/04).
4. Meaning of `input_cell3/output_cell3` and of `<ReqReaction>` (RXN-R14/R15).
5. Blob distance metric and whether blobs apply before/after the primary swap (RXN-R10).
6. `req_lifetime`: age of which cell, in frames? Do gases die exactly at `lifetime` or randomly before it (MAT-R10)?
7. Ray count/geometry of explosions; does a durability-blocked cell stop the ray (DUR-R02)?
8. Is the default of `_inherit_reactions` 0 when unset (MAT-R06)? Which of two duplicate definitions wins (MAT-R01)?
9. Why does the wiki list Concrete at durability 8 when `concrete_static` has none (D7)?
10. Do material contact-damage ticks run every frame (wiki: yes) or on a slower cadence (`mLastMaterialDamageFrame`)?
11. Which materials count as "air" for `requires_oxygen` (gases? steam? smoke?) (FIRE-R05)?

---

## Sources

Research files (`./.trellis/tasks/10-16-noita-cogbench/research/`):
- `materials.json`, `materials.md` (cross-checked; errors listed in Pitfalls), `reactions.json`, `tags_index.json`, `materials_from_data_xml.json`, `materials_from_wiki.json`, `noita-engine-constants.json`, `player-stats.json`, `damage-types.json`, `entities-damage.md`
- `raw/materials_xml_parsed.json`, `raw/reactions_xml_parsed.json`, `raw/cargo_Materials.json`
- `raw/noitadata/data/materials.xml`, `raw/noitadata/data/magic_numbers.xml` (Nolla data, numbers only)
- `raw/game/entities/projectiles/deck/*.xml`, `raw/game/entities/projectiles/bomb*.xml` (`config_explosion` numbers only)
- `raw/Documentation__Reaction.wikitext`, `raw/Modding__Making_a_custom_material.wikitext`, `raw/Documentation__ConfigExplosion.wikitext`, `raw/Documentation:_DamageModelComponent.wikitext`, `raw/Materials.wikitext`, `raw/Explosion_interactions.wikitext`, `raw/Digging.wikitext`, `raw/Density.wikitext`, `raw/Fire.wikitext`, `raw/Oil.wikitext`, `raw/Acid.wikitext`, `raw/Lava.wikitext`, `raw/Gunpowder.wikitext`, `raw/Steam.wikitext`, `raw/Smoke.wikitext`, `raw/Table_of_Alchemical_Reactions.wikitext`, `raw/Energy_Sphere.wikitext`, `raw/Spark_Bolt.wikitext`
- `scripts/build_materials_json.py`, `scripts/build_reactions_json.py` (derivation of `kind`, defaults, pseudo-records)
- Sibling KB: `.trellis/spec/game-design/entities-damage.md`, `benchmark.md`; task docs `prd.md`, `design.md`

Wiki URLs:
- https://noita.wiki.gg/wiki/Documentation:_Reaction
- https://noita.wiki.gg/wiki/Modding:_Making_a_custom_material
- https://noita.wiki.gg/wiki/Documentation:_ConfigExplosion
- https://noita.wiki.gg/wiki/Documentation:_DamageModelComponent
- https://noita.wiki.gg/wiki/Materials (Durability, Hardness, Player damage)
- https://noita.wiki.gg/wiki/Explosion_interactions
- https://noita.wiki.gg/wiki/Digging
- https://noita.wiki.gg/wiki/Density
- https://noita.wiki.gg/wiki/Fire , /wiki/Oil , /wiki/Acid , /wiki/Lava , /wiki/Gunpowder , /wiki/Steam , /wiki/Smoke
- https://noita.wiki.gg/wiki/Table_of_Alchemical_Reactions
- GDC 2019 "Exploring the Tech and Design of Noita" (Petri Purho): only the chunk/dirty-rect summary is available locally; the "random direction ignition" quote in `reactions.json` is not in local sources (UNVERIFIED).
