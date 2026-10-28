#!/usr/bin/env python3
"""Mechanical behaviour-primitive classification of the 422 spells.
Reads research/spells.json + raw/game entity XMLs. Writes spell_taxonomy.json (to cwd arg) and prints counts.
"""
import json, os, re, sys, collections
import xml.etree.ElementTree as ET

R = './.trellis/tasks/10-16-noita-cogbench/research/'
G = R + 'raw/game/'
spells = json.load(open(R + 'spells.json'))
by = {x['game_id']: x for x in spells}

# ---------------------------------------------------------------- feature library
COMP2FEATURE = {
    'PhysicsBodyComponent': 'PHYS_BODY', 'PhysicsBody2Component': 'PHYS_BODY',
    'PhysicsImageShapeComponent': 'PHYS_BODY', 'PhysicsThrowableComponent': 'PHYS_BODY',
    'HomingComponent': 'HOMING', 'LightningComponent': 'LIGHTNING', 'LaserEmitterComponent': 'LASER',
    'CellEaterComponent': 'CELL_EATER', 'BlackHoleComponent': 'BLACK_HOLE',
    'AreaDamageComponent': 'AREA_DAMAGE', 'GameAreaEffectComponent': 'AREA_EFFECT',
    'MagicConvertMaterialComponent': 'MATERIAL_CONVERT', 'MaterialSeaSpawnerComponent': 'SEA_SPAWNER',
    'TeleportProjectileComponent': 'TELEPORT_PROJ', 'TeleportComponent': 'PORTAL',
    'ExplodeOnDamageComponent': 'EXPLODE_ON_DAMAGE', 'DamageModelComponent': 'PROJ_HP',
    'CollisionTriggerComponent': 'PROXIMITY', 'EnergyShieldComponent': 'SHIELD',
    'LevitationComponent': 'LEVITATION', 'MaterialSuckerComponent': 'MATERIAL_SUCKER',
    'VerletPhysicsComponent': 'VERLET', 'VerletWeaponComponent': 'VERLET',
    'LooseGroundComponent': 'LOOSE_GROUND', 'ArcComponent': 'ARC', 'SineWaveComponent': 'SINE_WAVE',
    'HitEffectComponent': 'HIT_EFFECT',
    'AnimalAIComponent': 'CREATURE_AI', 'WormAIComponent': 'CREATURE_AI', 'PhysicsAIComponent': 'CREATURE_AI',
    'AdvancedFishAIComponent': 'CREATURE_AI', 'CharacterDataComponent': 'CREATURE_AI',
    'ExplosionComponent': None,  # plain explosion on trigger, covered by ConfigExplosion
    'MagicXRayComponent': 'XRAY',
}
COSMETIC_SCRIPTS = {'colour_spell.lua', 'mine_animate_slow.lua', 'summon_portal_vibrate.lua'}
# note-playing easter egg scripts: gameplay-free in a benchmark, deferred
EASTER_SCRIPTS = {'ocarina.lua', 'kantele.lua'}

def parse_xml(path):
    p = G + path.replace('data/', '', 1)
    if not os.path.isfile(p):
        return None
    txt = open(p, encoding='utf-8', errors='replace').read()
    txt = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', txt)
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        # duplicate attributes etc: fall back to regex tag scan
        comps = re.findall(r'<([A-Za-z0-9_]+Component)\b', txt)
        scripts = re.findall(r'script_[a-z_]+="([^"]+)"', txt)
        return comps, [s.split('/')[-1] for s in scripts]
    comps, scripts = [], []
    for el in root.iter():
        if el.tag.endswith('Component'):
            comps.append(el.tag)
        for k, v in el.attrib.items():
            if k.startswith('script_') and v:
                scripts.append(v.split('/')[-1])
    return comps, scripts

def entity_info(path):
    r = parse_xml(path)
    return r if r else ([], [])

def classify(x):
    g = x['game_id']; t = x['type']
    feats = set(); scripts = set(); why = []
    px = x['projectile_xml'] or {}
    comps = set(px.get('components', []))
    for c in comps:
        f = COMP2FEATURE.get(c)
        if f:
            feats.add(f)
    for s in px.get('lua_scripts', []):
        scripts.add(s.split('/')[-1])
    # modifier extra entities: parse each referenced entity
    for e in x['extra_entities']:
        cs, ss = entity_info(e)
        for c in cs:
            f = COMP2FEATURE.get(c)
            if f:
                feats.add(f)
        for s in ss:
            scripts.add(s)
    # payload projectile XMLs of triggers / related projectiles (utility spells)
    for pth in (x['projectiles_added'] + [tr['projectile'] for tr in x['triggers_added'] if isinstance(tr, dict) and 'projectile' in tr]):
        if isinstance(pth, str) and pth.startswith('data/') and pth != (px.get('path')):
            cs, ss = entity_info(pth)
            for c in cs:
                f = COMP2FEATURE.get(c)
                if f:
                    feats.add(f)
            for s in ss:
                scripts.add(s)
    real_scripts = {s for s in scripts if s not in COSMETIC_SCRIPTS and s not in EASTER_SCRIPTS}
    easter = bool(scripts & EASTER_SCRIPTS)
    cosmetic_only = bool(scripts) and not real_scripts and not easter
    # ---- primitive
    trig = x['trigger']
    if t == 'multicast':
        prim = 'MULTICAST'
    elif t == 'modifier':
        prim = 'MODIFIER'
    elif t == 'material':
        prim = 'MATERIAL'
    elif t == 'static_projectile':
        prim = 'STATIC'
    elif t == 'projectile':
        prim = 'PROJ'
    else:
        prim = 'UTILITY'
    if trig and t in ('projectile', 'static_projectile'):
        prim_base = prim
        prim = 'TRIGGER'
    else:
        prim_base = prim
    if prim == 'PROJ' and 'PHYS_BODY' in feats:
        prim = 'PROJ'  # keep, feature flag marks physics body
    return prim, prim_base, feats, real_scripts, easter, cosmetic_only

# ---------------------------------------------------------------- manual overrides (documented)
# complex_logic flag false positives: logic is a clamp / loop of constants, no state outside shot state
FALSE_COMPLEX = {'COLOUR_BLUE', 'COLOUR_GREEN', 'COLOUR_INVIS', 'COLOUR_ORANGE', 'COLOUR_PURPLE', 'COLOUR_RAINBOW',
                 'COLOUR_RED', 'COLOUR_YELLOW',            # screenshake clamp only
                 'BURST_X',                                 # draw_actions(#deck)
                 'INFESTATION'}                             # loop of 6 add_projectile
# small seeded-RNG pick of a fixed list of entity files
RANDOM_PICK_FIXED = {'FIREWORK', 'SUMMON_EGG'}
# reads/writes caster state (hp, gold, wand mana) from a shot-state modifier -> needs engine hooks, tiny formula
STATE_FORMULA = {'BLOOD_MAGIC', 'BLOOD_TO_POWER', 'MONEY_MAGIC', 'DAMAGE_FOREVER', 'DAMAGE_RANDOM'}
# deck/hand/discard surgery
DECK_OPS = {'ADD_TRIGGER', 'ADD_TIMER', 'ADD_DEATH_TRIGGER', 'DIVIDE_2', 'DIVIDE_3', 'DIVIDE_4', 'DIVIDE_10',
            'ALPHA', 'GAMMA', 'TAU', 'MU', 'PHI', 'SIGMA', 'OMEGA', 'ZETA', 'DUPLICATE', 'RESET',
            'DRAW_RANDOM', 'DRAW_RANDOM_X3', 'DRAW_3_RANDOM', 'RANDOM_SPELL', 'RANDOM_PROJECTILE',
            'RANDOM_STATIC_PROJECTILE', 'RANDOM_MODIFIER',
            'IF_ENEMY', 'IF_HALF', 'IF_HP', 'IF_PROJECTILE', 'IF_END', 'IF_ELSE',
            'HEXA_SHOT', 'I_SHOT', 'PENTA_SHOT', 'QUAD_SHOT', 'T_SHOT', 'W_SHOT', 'Y_SHOT',
            'CESSATION', 'ALL_SPELLS'}
RANDOM_FAMILY = {'DRAW_RANDOM', 'DRAW_RANDOM_X3', 'DRAW_3_RANDOM', 'RANDOM_SPELL', 'RANDOM_PROJECTILE',
                 'RANDOM_STATIC_PROJECTILE', 'RANDOM_MODIFIER', 'ZETA'}
REQUIREMENT = {'IF_ENEMY', 'IF_HALF', 'IF_HP', 'IF_PROJECTILE', 'IF_END', 'IF_ELSE'}
PLICATE = {'HEXA_SHOT', 'I_SHOT', 'PENTA_SHOT', 'QUAD_SHOT', 'T_SHOT', 'W_SHOT', 'Y_SHOT'}
GREEK = {'ALPHA', 'GAMMA', 'TAU', 'MU', 'PHI', 'SIGMA', 'OMEGA', 'ZETA', 'DUPLICATE'}
DIVIDE = {'DIVIDE_2', 'DIVIDE_3', 'DIVIDE_4', 'DIVIDE_10'}
ADDTRIG = {'ADD_TRIGGER', 'ADD_TIMER', 'ADD_DEATH_TRIGGER'}
PASSIVE_IDS = {x['game_id'] for x in spells if x['type'] == 'passive'}


SCRIPT_FAMILY = [
    ('black-white-hole', {'black_hole_gravity.lua','white_hole_gravity.lua','black_hole_big.lua','white_hole_big.lua'}),
    ('trajectory-script', {'accelerating_shot.lua','decelerating_shot.lua','horizontal_arc.lua','line_arc.lua','floating_arc.lua',
        'avoiding_arc.lua','chaotic_arc.lua','fly_downwards.lua','fly_upwards.lua','fizzle.lua','phasing_arc.lua','pingpong_path.lua',
        'nolla.lua','quantum_split.lua','rocket_downwards.lua','rocket_octagon.lua','larpa_chaos.lua','larpa_chaos_2.lua',
        'larpa_downwards.lua','larpa_upwards.lua','orbit_projectile.lua','true_orbit.lua','spiraling_shot.lua','orbit_shot.lua',
        'homing_accelerating.lua','homing_cursor.lua','homing_area.lua','autoaim.lua'}),
    ('on-bounce-spawner', {'bounce_spark.lua','bounce_laser.lua','bounce_laser_emitter.lua','bounce_lightning.lua','bounce_explosion.lua',
        'bounce_small_explosion.lua','bounce_hole.lua','bounce_larpa.lua'}),
    ('ray-thrower', {'fireball_ray.lua','fireball_ray_line.lua','lightning_ray.lua','laser_emitter_ray.lua','tentacle_ray.lua'}),
    ('projectile-rewriter', {'zero_damage.lua','explosion_tiny.lua','explosion_remove.lua','clipping_shot.lua','crumbling_earth_projectile.lua',
        'laser_emitter_wider.lua','random_explosion.lua','transmutation.lua','chain_shot_init.lua','piercing_shot.lua','essence_to_power.lua',
        'spells_to_power.lua','larpa_death.lua'}),
    ('laser-beam', {'laser_emitter_start.lua','megalaser_init.lua','megalaser_launch.lua'}),
    ('spells-to-x', {'all_acid.lua','all_blackholes.lua','all_deathcrosses.lua','all_discs.lua','all_rockets.lua','all_nukes.lua'}),
    ('teleport-cast', {'teleport_cast.lua','super_teleport_cast.lua','teleport_projectile_closer_init.lua','hook.lua'}),
    ('world-builder', {'wall_horizontal.lua','wall_vertical.lua','wall_square.lua','cloud_position.lua','destruction.lua','mass_polymorph.lua',
        'vacuum_powder.lua','vacuum_entities.lua','meteor_rain.lua','meteor_collide.lua','touch_grass.lua','purple_explosion_field.lua',
        'projectile_gravity.lua','projectile_thunder.lua','projectile_transmutation.lua','electrocution_blast.lua','lightning_explosion_small.lua',
        'bomb_detonator.lua','rain_thunder.lua','orb_expanding.lua','darkflame.lua','grenade_anti_gravity.lua','spiral_shot.lua','chain_bolt.lua',
        'disc_bullet_big_trajectory.lua','disc_bullet_bigger_trajectory.lua','disc_bullet_big_damage.lua','worm_shot_homing.lua','magic_shield_start.lua','big_magic_shield_start.lua'}),
    ('summoned-creature', {'swarm_fly.lua','friend_fly.lua','pebble_player_spawn.lua','duck.lua','duck_init.lua','wand_ghost.lua','tentacle_portal.lua',
        'worm_rain.lua','bomb_cart.lua','bomb_cart_init.lua','xray_effect.lua'}),
]
def script_family(scripts):
    for name, ss in SCRIPT_FAMILY:
        if scripts & ss:
            return name
    return None

SIDE_ATTR = re.compile(r'(?:load_this_entity|spawn_entity)="(data/entities/[^"]+)"')
def side_entities(x):
    px = x['projectile_xml']
    if not px:
        return []
    p = G + px['path'].replace('data/', '', 1)
    if not os.path.isfile(p):
        return []
    txt = open(p, encoding='utf-8', errors='replace').read()
    out = []
    for m in re.findall(r'(?:load_this_entity|spawn_entity)="([^"]+)"', txt):
        for part in m.split(','):
            part = part.strip()
            if part.startswith('data/entities/') and 'particles/' not in part and 'explosion_was_here' not in part:
                out.append(part)
    return out

OVERRIDE_D2 = {
    'CASTER_CAST': 'wiki tag scripted; extra entity XML not in raw/game',
    'THUNDERBALL': 'wiki tag scripted; spawns thunderburst side entity (XML not in raw/game)',
    'CLUSTERMOD': 'extra entity clusterbomb.xml not in raw/game (UNVERIFIED, name suggests script)',
    'REMOVE_BOUNCE': 'extra entity remove_bounce.xml not in raw/game (UNVERIFIED, likely script setting bounces_left=0)',
    'TINY_GHOST': 'passive card with 3 Lua scripts (companion AI)',
}
OVERRIDE_D1 = {'HITFX_PETRIFY': 'HIT_EFFECT'}
OVERRIDE_D0 = {'IF_END': 'requirement-marker', 'IF_ELSE': 'requirement-marker'}


FAMILY_OVERRIDE = {
    'cloud-emitter': ['CLOUD_ACID','CLOUD_BLOOD','CLOUD_OIL','CLOUD_WATER','CLOUD_THUNDER'],
    'wall-builder': ['WALL_HORIZONTAL','WALL_VERTICAL','WALL_SQUARE'],
    'vacuum-field': ['VACUUM_LIQUID','VACUUM_POWDER','VACUUM_ENTITIES'],
    'projectile-field': ['PROJECTILE_GRAVITY_FIELD','PROJECTILE_THUNDER_FIELD','PROJECTILE_TRANSMUTATION_FIELD'],
    'orbiting-shield': ['MAGIC_SHIELD','BIG_MAGIC_SHIELD'],
    'sawblade-script': ['DISC_BULLET_BIG','DISC_BULLET_BIGGER'],
    'electric-field-script': ['ELECTROCUTION_FIELD','THUNDER_BLAST','PURPLE_EXPLOSION_FIELD'],
    'summoned-creature': ['EXPLODING_DUCKS','SUMMON_PORTAL','TINY_GHOST','SUMMON_WANDGHOST','X_RAY'],
    'teleport-cast': ['CASTER_CAST'],
    'misc-projectile-script': ['CHAIN_BOLT','EXPANDING_ORB','GRENADE_ANTI','DARKFLAME','SPIRAL_SHOT','WORM_SHOT','THUNDERBALL'],
    'misc-world-script': ['DESTRUCTION','MASS_POLYMORPH','METEOR_RAIN','BOMB_DETONATOR','TOUCH_GRASS'],
    'projectile-rewriter': ['CLUSTERMOD','REMOVE_BOUNCE'],
}
FAM_OF = {g: f for f, gs in FAMILY_OVERRIDE.items() for g in gs}

out = []
for x in spells:
    g = x['game_id']
    prim, prim_base, feats, scripts, easter, cosmetic = classify(x)
    notes = []
    family = None
    reason = ''
    sides = side_entities(x)
    if g in OVERRIDE_D0:
        prim = 'UTILITY'; impl = 'D0'; family = OVERRIDE_D0[g]; reason = 'draw 1, marker consulted by IF_* spells'
    elif g in DECK_OPS:
        prim = 'UTILITY'; impl = 'D2'; reason = 'deck/hand/discard or wand-state logic'
        if g in REQUIREMENT: family = 'requirement'
        elif g in RANDOM_FAMILY: family = 'random'
        elif g in PLICATE: family = 'plicate'
        elif g in GREEK: family = 'greek-copy'
        elif g in DIVIDE: family = 'divide'
        elif g in ADDTRIG: family = 'add-trigger'
        else: family = 'deck-surgery'
    elif x['type'] == 'passive' and g != 'TINY_GHOST':
        prim = 'UTILITY'; impl = 'D1'; family = 'passive-card'; feats.add('PASSIVE_CARD'); reason = 'effect lives in the wand-attached card entity'
    elif g in OVERRIDE_D2:
        impl = 'D2'; reason = OVERRIDE_D2[g]
        if x['type'] == 'passive': prim = 'UTILITY'; family = 'companion'
    elif g in STATE_FORMULA:
        impl = 'D2'; family = 'state-formula'; reason = 'shot-state modifier that reads/writes caster hp, gold or wand mana, or rolls RNG'
    elif g in RANDOM_PICK_FIXED:
        impl = 'D1'; family = 'random-pick-fixed'; feats.add('RNG_PICK'); reason = 'seeded pick among a fixed list of entity files'
    elif easter:
        impl = 'D2'; family = 'easter-egg-notes'; reason = 'note projectile + song-matching script (portal/bomb/worm/alchemy magic); DEFER'
    elif g in OVERRIDE_D1:
        impl = 'D1'; feats.add(OVERRIDE_D1[g]); reason = 'hit-effect entity (XML not in raw/game, sibling of other hitfx)'
    else:
        creature = 'CREATURE_AI' in feats
        complex_ = x['complex_logic'] and g not in FALSE_COMPLEX
        if scripts or creature or complex_ or feats & {'BLACK_HOLE', 'PORTAL', 'XRAY'}:
            impl = 'D2'
            family = script_family(scripts) or ('summoned-creature' if creature else ('random' if complex_ else None))
            reason = 'spell-specific Lua script(s)' if scripts else ('creature AI' if creature else 'branching action body')
        else:
            if sides:
                feats.add('SIDE_ENTITY')
            if feats:
                impl = 'D1'; reason = 'needs engine feature(s): ' + ','.join(sorted(feats))
            else:
                impl = 'D0'; reason = 'parametric data only'
    if cosmetic:
        notes.append('cosmetic-script-only (colour_spell/mine_animate)')
    if g in FALSE_COMPLEX:
        notes.append('complex_logic flag is a false positive (clamp/loop of constants)')
    if sides:
        notes.append('side entities: ' + ','.join(sorted({s.split('/')[-1] for s in sides})) + ' (XML not in raw/game: UNVERIFIED)')
    if g in ('HITFX_PETRIFY', 'CLUSTERMOD', 'REMOVE_BOUNCE', 'CASTER_CAST'):
        notes.append('extra-entity XML missing from raw/game: UNVERIFIED')
    if impl == 'D2' and g in FAM_OF:
        family = FAM_OF[g]
    out.append({
        'game_id': g, 'name': x['name'], 'type': x['type'], 'primitive': prim, 'base_primitive': prim_base,
        'impl': impl, 'features': sorted(feats), 'scripts': sorted(scripts), 'family': family, 'wraps_trigger': bool(x['trigger']) or g in ADDTRIG or g in ('LONG_DISTANCE_CAST','TELEPORT_CAST','SUPER_TELEPORT_CAST'), 'reason': reason, 'notes': notes,
    })

dest = sys.argv[1] if len(sys.argv) > 1 else 'spell_taxonomy_draft.json'
META = {
  'description': 'Behaviour-primitive and implementation-class taxonomy of the 422 spells in spells.json. Mechanically derived by scripts/classify_spells.py plus a short documented override table.',
  'primitive': 'PROJ | TRIGGER (projectile/static spell wrapped by a collision/timer/death trigger) | STATIC | MATERIAL | MODIFIER | MULTICAST | UTILITY',
  'impl': {'D0': 'data only: a row interpreted by the core engine (shot state, ProjectileSpec, draw, triggers, materials, status effects)',
           'D1': 'data + one or more reusable engine features listed in `features` (no per-spell code)',
           'D2': 'spell-specific code: Lua script(s) in the original, deck/hand/discard logic, creature AI or caster-state access'},
  'caveat': 'Only the MAIN projectile XML and the modifier extra-entity XMLs saved in raw/game were inspected. Side entities (load_this_entity/spawn_entity targets) and 4 extra-entity XMLs (clusterbomb, hitfx_petrify, remove_bounce, caster_cast) are not in raw/game: classification of those is UNVERIFIED.',
}
json.dump({'_meta': META, 'spells': out}, open(dest, 'w'), indent=1)
c = collections.Counter((o['type'], o['impl']) for o in out)
print('wraps_trigger', sum(o['wraps_trigger'] for o in out))
print('impl by type'); [print(' ', k, v) for k, v in sorted(c.items())]
print('impl totals', collections.Counter(o['impl'] for o in out))
print('primitive totals', collections.Counter(o['primitive'] for o in out))
print('family totals', collections.Counter(o['family'] for o in out if o['impl']=='D2'))
print('features', collections.Counter(f for o in out for f in o['features']))
