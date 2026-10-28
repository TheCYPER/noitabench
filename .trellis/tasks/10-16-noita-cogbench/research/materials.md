# Materials System

## Overview

Noita's materials system is the foundation of its physical simulation and alchemical interactions. All 466 materials are distributed across 4 cell types and 6 kinds, with each material defining properties for density, durability, flammability, color, and reaction behavior.

## Material Categories

### Cell Types (Physical Basis)

| Cell Type | Count | Purpose |
|-----------|-------|---------|
| `liquid` | 290 | Flows under gravity; includes water, oil, magic liquids, hazardous substances |
| `solid` | 132 | Static platforms, structures; includes rock, wood, metals, ice |
| `gas` | 26 | Flows upward/horizontally; includes smoke, steam, special gases |
| `fire` | 18 | Burn state; includes fire, flaming variants |

### Kinds (Behavioral Subtype)

| Kind | Count | Usage |
|------|-------|-------|
| `solid` | 132 | Rigid bodies; physics interactions, breakability |
| `static` | 103 | Immobile platforms; rock, concrete, ice variants |
| `liquid` | 100 | Flows; water, oil, alchemy liquids |
| `powder` | 87 | Granular; sand, coal, metal dust |
| `gas` | 26 | Rises/spreads; smoke, steam |
| `fire` | 18 | Burning states of other materials |

## Field Meanings and Ranges

### Physical Properties

| Field | Range | Notes |
|-------|-------|-------|
| `density` | 1–50 | Lower = lighter/floats; higher = sinks. Affects liquid settling, momentum transfer |
| `durability` | 0–16 | Resistance to destruction; higher = tougher; solids/statics only |
| `hp` | 5–1,000,000 | Hit points for solid/static blocks; higher = harder to break |
| `gravity.liquid_gravity` | 0.0–5.0 | Vertical speed for liquids (0 = floats, 5 = sinks fast); only liquids |
| `gravity.gas_speed` | 50 (fixed) | Gases move at fixed speed; all gases use this |

### Combustion & Fire

| Field | Range | Meaning |
|-------|-------|---------|
| `flammable` | bool | True = catches fire if exposed to fire/high temp |
| `fire_hp` | -1–99,999,999 | Hit points before burning out; -1 = burns forever |
| `starts_on_fire` | bool | True = material burns constantly from spawn |
| `autoignition` | 0–100 | Autoignition temp (unused in current engine, declared in materials) |
| `temperature_of_fire` | 0–200 | Used by fire visuals/particle effects; higher = hotter-looking |
| `burns_into` | string | Target material ID when burning; e.g., wood → ash |
| `generates_smoke` | 0–250 | Smoke particle count per burn tick |
| `generates_flames` | 0–30 | Flame particle count per burn tick |

### Liquid Dispersion

| Field | Range | Purpose |
|-------|-------|---------|
| `dispersion.liquid_viscosity` | 0–150 | Thickness; higher = thicker (e.g., slime) |
| `dispersion.liquid_flow_speed` | 0.1–0.9 | How fast liquid spreads horizontally |
| `dispersion.liquid_damping` | varies | Reduces momentum/velocity over time |
| `dispersion.liquid_slime` | bool | True = material sticks; affects flow |
| `dispersion.liquid_sticks_to_ceiling` | 0–1+ | 1 = sticks to ceiling; >1 = stiffer adhesion |

### Gas Behavior

| Field | Range | Notes |
|-------|-------|-------|
| `lifetime_frames` | 0–1,350 | Frames before gas dissolves to air; 0 = instant (air) |
| `gravity.gas_upwards_speed` | variable | Speed gas rises (if buoyant) |
| `gravity.gas_horizontal_speed` | variable | Sideways spread |

### Special Properties

| Field | Range | Purpose |
|-------|-------|---------|
| `electrical_conductivity` | 0–1 | Conducts lightning/electricity |
| `stickyness` | 0+ | Adhesion factor; higher = stickier |
| `stainable` | bool | Can be stained/colored by contact |
| `platform_type` | -1 / 0+ | Platform classification; -1 = not a platform |

### Color & Rendering

| Field | Format | Notes |
|-------|--------|-------|
| `wang_color_argb` | hex (ARGB) | Primary render color; parsed to RGB for clone |
| `palette` | array | Alternative colors (unused in most materials) |
| `gfx_glow` | 0–1 | Additive glow multiplier |

## Reaction System

### Overview

**339 reactions** govern all material transformations. Reactions are **binary** (2 inputs → 2 outputs); a few have 3 inputs but only 2 output slots are used.

### Reaction Fields

| Field | Meaning |
|-------|---------|
| `input_a`, `input_b`, `input_c` | Input materials; can be material ID or tag `[tag]` |
| `output_a`, `output_b`, `output_c` | Output materials (only 2 outputs stored) |
| `probability` | 1–100 (%); chance per-update-frame that two adjacent cells react |
| `fast_reaction` | bool; True = higher priority/faster convergence |
| `req_reaction` | bool; True = reaction requires some condition (UNVERIFIED) |
| `is_tag_rule` | bool; True = inputs use tags |
| `explosion` | object; if present, reaction triggers an explosion event |
| `direction` | string; "none" (default), directional constraints (UNVERIFIED) |

### Reaction Semantics

- **Probability:** Chance per update-frame that two horizontally/vertically adjacent cells of the correct types react. Values: 1, 2, 5, 8, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100 (% range).
- **Tag-based reactions:** 162 / 339 reactions use input tags (e.g., `[fire]`, `[water]`, `[burnable]`). Tags are defined in `tags_index.json`. **Example:** `[fire] + water → [fire] + steam` (any fire material + water produces steam; fire persists).
- **Parent/inheritance:** Materials can inherit reactions from a `parent` material (engine-side tag inheritance; UNVERIFIED in clone).

### Tag Expansion

Common tags and their material memberships:

| Tag | Member Count | Examples |
|-----|--------------|----------|
| `*` | 466 | All materials (catch-all) |
| `[alchemy]` | 297 | Alchemical materials; water, magic liquids, transmutation inputs |
| `[burnable]` | 63 | Wood, coal, gunpowder, oil, pus, meat |
| `[water]` | 37 | Water, ice variants, watery liquids (for reaction tagging) |
| `[lava]` | UNVERIFIED | Lava + variants |
| `[fire]` | UNVERIFIED | Fire and variants (matches hot burn states) |
| `[meltable_to_*]` | 46+ | Materials that melt into specific outputs |
| `[ice]` | UNVERIFIED | Ice, snow, ice_static |
| `[liquid]` | 92 | Flowing liquid materials |
| `[liquid_common]` | 66 | Common/safe liquids |
| `[corrodible]` | 279 | Materials damaged by acid/corrosion |

## Fire Propagation & Burning

### Fire Conversion Chain

When a material ignites:

1. Material → fire state (via reaction `X + [fire] → fire + X`)
2. On-fire material emits smoke/flame particles (fields: `generates_smoke`, `generates_flames`)
3. On-fire material burns into another material via `burns_into` field (e.g., wood → ash) OR persists if `fire_hp = -1` (infinite burn)
4. Burning materials can trigger reactions (e.g., `[fire] + water → [fire] + steam`)

### Burning Reactions (Sampled)

| Input | Fire Input | Output | Probability |
|-------|-----------|--------|------------|
| water | `[fire]` | steam | 20% |
| ice / ice_static | `[fire]` | water | 40–80% |
| snow / snow_static | `[fire]` | water | 80% |
| `[meltable_metal]` | `[fire_strong]` | `[*]_molten` | 30% |

### Temperature Modeling

**Noita models heat implicitly via state conversion, not numerical temperature:**
- No explicit "temperature" field in materials
- Heat is represented as material state transitions (e.g., ice → water, water → steam)
- `temperature_of_fire` is visual/cosmetic; does not drive heat physics
- **Autoignition** field (0–100) is declared in materials.xml but NOT actively used by the engine (UNVERIFIED; documentation suggests it was cut)

## MVP-40 Material List

Proposed minimal set for game-like behavior:

### Core / Physics

1. **air** – Empty cell; enables decay reactions; 133 involved reactions
2. **water** – Fundamental liquid; 54 reactions; freezes to ice, boils to steam

### Elementals

3. **oil** – Flammable liquid; viscous; 9 reactions; burns with fire
4. **fire** – Burning state; propagates to burnable materials
5. **steam** – Gas; condenses to water; 47 reactions
6. **ice** – Frozen water; melts back to water; 6 reactions

### Magic / Special

7. **radioactive_liquid** – Toxic hazard; 22 reactions; damages entities
8. **acid** – Corrosive; 5 reactions (but tags handle most)
9. **poison** – Toxic liquid; 8 reactions; can damage/mutate

### Structure & Solids

10. **sand** – Powder; flowable; 3 reactions
11. **soil** – Powder; 17 reactions; soil variant of earth
12. **rock_static** – Solid platform; 7 reactions
13. **concrete_static** – Solid; formed from cement + water; 8 reactions
14. **wood_static** – Solid; burns; flammable

### Combustion

15. **gunpowder** – Explosive powder; 1 reaction (but heavily used in spell/entity systems)
16. **coal** – Burnable powder; 3 reactions
17. **burning_powder** – Hot powder; emits particles
18. **smoke** – Gas byproduct; 42 reactions; dissipates over time

### Metals (Alchemy)

19. **gold** – Powder/ingot; transmutation target; 7 reactions
20. **silver** – Powder; 12 reactions
21. **copper** – Powder; 9 reactions
22. **brass** – Powder alloy; 10 reactions
23. **steel** – Solid; 0 direct reactions (but used in structures)

### Alchemy Liquids

24. **cement** – Binding liquid; reacts with water/fire to form concrete
25. **blood** – Organic liquid; 8 reactions; decays/transforms
26. **slime** – Viscous; 4 reactions; sticks to surfaces
27. **alcohol** – Whiskey; flammable liquid; 11 reactions

### Magic Liquids

28. **magic_liquid** – Gate-opener; 8 reactions
29. **magic_liquid_mana_regeneration** – Concentrated mana; 17 reactions
30. **magic_liquid_teleportation** – Teleportatium; 13 reactions

### Hazards

31. **pus** – Toxic/organic; 28 reactions; forms in corpses
32. **void_liquid** – Destructive void; 11 reactions; vaporizes materials
33. **diamond** – Hard mineral; 7 reactions (mostly alchemy)
34. **wax** – Solid; flammable; 3 reactions

### Extended (for ~50 target)

35. **water_ice** – Chilly water; 18 reactions; semi-frozen state

(Total: 35 materials; can extend to 40-50 by adding variants: ice_static, snow, lava, brass, etc.)

---

## Key Reactions (~30 for MVP)

### Core Liquid Reactions

1. **water + cement → concrete_static** (100%) – Cement solidifies with water
2. **[fire] + water → [fire] + steam** (20%) – Fire boils water to steam
3. **[fire] + ice / ice_static → [fire] + water** (40–80%) – Fire melts ice
4. **steam + [static] → water + [static]** (3%) – Steam condenses on surfaces
5. **ice / ice_static + air → water + air** (1%) – Ice slowly sublimes/melts
6. **water + ice → water + water_ice** (1%) – Cold water forms slush

### Oil & Flammable Reactions

7. **oil + [fire] → burning_powder + air** (UNVERIFIED; likely high prob) – Oil ignites
8. **gunpowder + [fire] → air + air** (UNVERIFIED; explosion) – Gunpowder detonates
9. **[burnable] + [fire] → [fire] + air** (50–80% typical) – Burnable materials ignite and consume

### Hazard Reactions

10. **water + radioactive_liquid → water** (13%) – Radioactivity dilutes/dissipates
11. **acid + [corrodible] → acid + air** (UNVERIFIED; high prob) – Acid eats through materials
12. **poison + [biological] → poison + [biological]** (UNVERIFIED) – Poison infects organics
13. **void_liquid + [alchemy] → void_liquid + void_liquid** (UNVERIFIED; spreads) – Void consumes

### Alchemy & Magic Reactions

14. **magic_liquid + water → magic_liquid + air** (8 reactions) – Magic liquid reacts with mundane
15. **magic_liquid_teleportation + [liquid] → magic_liquid_teleportation + [liquid]** (13 reactions) – Teleportium spreads via liquids
16. **magic_liquid_mana_regeneration + [alchemy] → magic_liquid_mana_regeneration** (17 reactions) – Mana spreads in alchemy

### Metal & Structure Reactions

17. **cement + concrete_static → concrete_static** (70%) – Cement fills concrete
18. **cement + fire → concrete_static + air** (80%) – Fire hardens cement
19. **cement + wood_player → concrete_static + wood_player** (100%) – Cement encases wood
20. **[fire_strong] + [meltable_metal] → [fire_strong] + [*]_molten** (30%) – Strong fire melts metals into molten state

### Decay & Transmutation

21. **blood + air → pus + air** (UNVERIFIED; slow) – Blood decays to pus
22. **pus + [corrodible] → pus + air** (slow decay) – Pus spreads corruption
23. **wood_static + air → air + air** (very low; slow rot) – Wood slowly rots
24. **coal + air → smoke + air** (slow oxidation) – Coal slowly oxidizes

### Water Reactions

25. **salt + water → air + water_salt** (5%) – Salt dissolves into brine
26. **[fire] + water_salt → [fire] + salt** (20%) – Fire boils brine, leaves salt
27. **water_swamp + [fire] → water_swamp + steam** (low prob) – Swamp water steams under fire
28. **water + [ice] → water + water_ice** (1%) – Water freezes into slush when cold

### Special / Rare

29. **sodium + [water] → sodium + steam** (50%) + **explosion** – Sodium violently reacts with water (ray_energy 50000; VERIFIED)
30. **magic_liquid_mana_regeneration + [liquid] → magic_liquid_mana_regeneration** (spreads) – Mana spreads through liquids

---

## Critical Design Notes

### Reactions Are Deterministic

- Probability values are **per-update-frame chances**, NOT per-cell-pair.
- Engine updates every frame, checking adjacent cells for reaction triggers.
- Probability stored as `int(float * 100)` (exact representation varies; UNVERIFIED in Noita; assume 1–100 integer).

### Fire Does NOT Consume Inputs

Most fire reactions preserve the fire material:
- `[fire] + water → [fire] + steam` (fire persists, water becomes steam)
- This is a design choice to allow fire to chain reactions across materials

### Tag Reactions Are Common

162 / 339 reactions use tags. Examples:
- `[fire] + [burnable] → [fire] + [ash-like]`
- `[water] + [meltable_to_water] → [water] + water` (metals melt)

For the clone, tag expansion is necessary to avoid hardcoding 162 rules.

### Explosion Config

3 reactions have `explosion` objects (sodium + water, likely 2 others). Explosions define:
- `cell_explosion_power`: Damage/force radius
- `cell_explosion_radius_min / max`: Blast size
- `ray_energy`: Ray-based damage (UNVERIFIED in materials.json; check explosion types)

### No Explicit Temperature Simulation

- Noita does **not** use a temperature grid or heat equation
- Heat is represented as **state changes** (ice ↔ water ↔ steam)
- `temperature_of_fire` is cosmetic/visual
- `autoignition` field is declared but **not actively used** (cut feature, UNVERIFIED)

---

## Sources

- `./.trellis/tasks/10-16-noita-cogbench/research/materials.json` – 466 material records with full property data
- `./.trellis/tasks/10-16-noita-cogbench/research/reactions.json` – 339 reaction rules with probability, inputs/outputs, tags
- `./.trellis/tasks/10-16-noita-cogbench/research/tags_index.json` – 79 material tags and their member materials
- `./.trellis/tasks/10-16-noita-cogbench/research/materials_from_data_xml.json` – Raw Noita materials.xml exports
- `./.trellis/tasks/10-16-noita-cogbench/research/materials_from_wiki.json` – Wiki-scraped material metadata
- `./.trellis/tasks/10-16-noita-cogbench/research/raw/Materials.wikitext` – Raw wiki page dump
- `./.trellis/tasks/10-16-noita-cogbench/research/raw/Material_Information_Table.wikitext` – Material properties table
- `./.trellis/tasks/10-16-noita-cogbench/research/raw/Table_of_Alchemical_Reactions.wikitext` – Reaction table
- Noita game data files (under `raw/game`, `raw/noitadata`) – License: Nolla Games; facts/identifiers only, not code
