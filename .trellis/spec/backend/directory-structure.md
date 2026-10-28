# Directory Structure

Top-level layout is fixed by [contracts.md](./contracts.md) section 1. Inside it:

## Rust (`crates/`)

```
crates/sim/src/
  lib.rs          public API re-exports only
  material.rs     loading content/materials.json, index <-> key
  grid.rs         cells, chunks, dirty rectangles
  rules/          one file per behaviour: powder.rs, liquid.rs, gas.rs, fire.rs, reactions.rs, explode.rs
  query/          read-only grid queries for entities and projectiles: ray.rs, sweep.rs, overlap.rs (SIM-R60..R65, HAZ-R01)
  rng.rs          stateless cell hash and named streams
  record.rs       recording writer (cogbench-rec/0)
  snapshot.rs     serialise / restore
crates/sim/tests/ integration tests, one file per rule family, named after KB rule ids where possible
crates/sim/benches/ criterion benches
crates/game/src/  entities, items, wands, potions, perturbation, commands (from week 2)
crates/py/src/    PyO3 wrappers only: no game logic
```

- One module per mechanic; keep files under about 400 lines.
- Game logic never lives in `crates/py`, `python/` or `web/`.

## Python (`python/noitabench/`)

```
env.py        thin wrapper over noitabench_core.Env
worldgen/     biome map, Wang tile templates, pixel scenes, checks, preview (week 1 prototype in pure Python, later moved into Rust if slow)
obs/  harness/  eval/  protocol/  server/   (later weeks)
__main__.py   CLI: python -m noitabench <command>
```

Tests in `python/tests/`, mirroring the package layout.
