"""Procedural world generator: fixed biome map, herringbone Wang tiles, global scenes, encounter scenes.

Pipeline (``generate.py``), all driven by named random streams derived from the seed:

1. each of the 9 biome regions gets its caves, either a herringbone Wang tiling (Sean
   Barrett's method, ``tiles.py``) varied by halls, shafts, ledges and cracks (``shapes.py``),
   or a layout of rooms and doors (``rooms.py``), then strata and veins (``fill.py``);
2. the global scenes are drawn: start surface, two small rest halls (each with a metal
   alchemy bowl sunk into its floor), the sealed chamber (``scenes.py``);
3. each layer's main biome gets full-width rock bands whose chambers are the must-pass
   encounter slots, the side biomes become dead-end pockets with one gate each
   (``layers.py``); shafts link everything along the main path. An encounter that has a
   scene in ``content/encounters/`` (``encounter_defs.py``) is stamped into its slot with
   the liquids the world's reaction table calls for (``table.py``,
   ``encounter_place.py``); any other id gets a bare placeholder chamber. Each must-pass
   chamber is a true chokepoint (CP2 decision, 2026-10-27): a brick **seam** (durability 14,
   which the starting digger cannot remove) across the whole middle biome with a hole exactly
   as wide as the scene's footprint, and a brick **shell** around every side biome with the
   pocket's single gate cut through it, so a digger cannot get round a scene. The scene itself
   is a closed brick box (2026-10-28): its outer wall is brick except the doors, and brick
   bulkheads wall the rock round each obstacle, so inside the footprint too the only ways from
   the top door to the exit lead through the scene's solution regions (``routes.py``). The
   order of a layer's must-pass bands is random, except that a layer may name a ``last`` scene
   (E12 in layer 3, ``biome_map.json``): it is always the deepest, because it holds the
   modifier that completes the seal key (``layers.band_order``, ``key_order.py``);
4. optional encounter slots (a scene with lava or acid in its art is never put where the hazard
   would lie within reach of the player's hit box from a must-pass corridor or of the key's
   blast, ``clearance.py``); pools, gas pockets and heaps (``features.py``) together with the
   ingredient deposits of the biome files (``alchemy.py``); the terrain is brought to rest
   (``settle.py``); biome structures (``structures.py``) and ambient hazards (``hazards.py``;
   lava pools and pockets keep out of the same zones); the metal alchemy bowls in caves
   (``alchemy.py``, ``bowls.py``; the rest halls get theirs in step 2); rest again; then bottles
   of every ingredient, enemy and item markers (``markers.py``); ``edit_station`` markers for
   the scenes that name one (the hall above the sealed deep);
5. ``checks.py`` verifies connectivity (the starting wand may dig, brick never), that the
   seal seals, that every must-pass scene is the only way down for a digger (the bypass
   check, with a positive control; and the gate check of every placed scene: with a gate's
   solution regions blocked no free or diggable route joins its doors, ``routes.py``), that every
   encounter slot can be walked to, must-pass
   chokepoints, marker counts, encounter coverage, no free acid, that nothing would move at
   frame 0 (``rest.py``: the simulation's own movement rules) and where barrels stand; every
   placed scene must be intact and solvable under the reaction table (``encounter_checks.py``);
   no lava, acid or fire lies within reach of the player's hit box from the free cells of a
   must-pass scene and its tunnels, nor within the blast radius of the seal key round the hall
   above the plug (``clearance_checks.py``); every ingredient of the recipes is obtainable, there are empty
   bottles, the bowls are whole and reachable, no secret potion lies about and no three
   ingredients touch where the simulation would mix them into one (``alchemy_checks.py``,
   ``mixing.py``); the ``last`` scene of a layer is the deepest must-pass scene and holds its
   part of the key (``key_order.py``); on failure the world is rebuilt with a sub-seed.

Command line: ``python -m noitabench.worldgen preview|check|generate|tiles|scene`` (``cli.py``).
Output is the world file pair of ``contracts.md`` section 4 (``world.py``).
"""

from .generate import generate_world
from .world import World, load_world

__all__ = ["World", "generate_world", "load_world"]
