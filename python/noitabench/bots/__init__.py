"""Scripted bots that drive `noitabench.game.Game` with per-frame controls.

`descend` plays a generated world from the start to its deepest point, seal included (the CP2
recording):

    python -m noitabench.bots.descend --world-seed 42 --no-enemies --record runs/descend-42

The parts: `terrain` (what the bot knows of the grid), `navfield` (cost-to-goal field),
`pilot` (controls from the field), `gunner` (shooting), `wands` (which wand holds what),
`editing` (wands are edited only in rest areas and edit stations), `halls` (the rest halls),
`scenes` (the must-pass scenes and a log of the bot going through them), `chain` (E07),
`crossing` (a river of lava), `keys` and `seal` (finding the key items, using them, and the
logged fallback when there is none), `breaker` and `escape` (the bomb and where to run to).

Fair play. A bot is a test and recording tool, not an agent under evaluation. It drives the game
with per-frame controls (and the wand editor, only where a player may use it: `editing`), and it
may read what an agent never sees: the whole grid and the world file (`meta.main_path`, the
`seal`, `rest_area` and `edit_station` markers, the `encounter` markers with their footprints and
`regions`, the `item` markers with their `role`). It never reads the reaction table, the rule
seed or the recipes, and the only calls that change the world other than controls are the logged
seal fallback's `Game.blast` and `Game.give_spell` (`seal.py`, off with `--require-key`).
"""
