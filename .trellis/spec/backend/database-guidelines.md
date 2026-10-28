# Database Guidelines

Not applicable: the project has no database. Persistent data are files:

- Content (materials, reactions, spells, enemies, biomes, tile templates, pixel scenes): `content/`, versioned in git, formats in [contracts.md](./contracts.md).
- Runs and recordings: `runs/` (git-ignored), format `cogbench-rec/0`.
- Agent workspaces (cross-run memory): `runs/<family>/workspace/` (from week 3).
