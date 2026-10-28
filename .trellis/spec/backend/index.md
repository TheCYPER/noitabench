# Engine and Harness Guidelines (Rust + Python)

> This directory was the `trellis init` "backend" template. For this project it holds the conventions for the Rust simulation crates and the Python package (env wrapper, worldgen tools, harness, eval, server). There is no web backend and no database.

| Guide | Covers | Status |
|---|---|---|
| [Contracts](./contracts.md) | Repo layout, content data files, world files, recording format, sim Python API, reproducibility | **Read first** |
| [Directory Structure](./directory-structure.md) | Where code goes inside `crates/` and `python/` | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Tests, lint, review gates, forbidden patterns | Filled |
| [Error Handling](./error-handling.md) | Rust and Python error conventions | Filled |
| [Logging Guidelines](./logging-guidelines.md) | Logs versus the event log | Filled |
| [Database Guidelines](./database-guidelines.md) | Not applicable; data files instead | Filled |

Game rules and numbers live in `.trellis/spec/game-design/` (start with `v1-scope.md`). Product decisions live in `.trellis/tasks/10-16-noita-cogbench/`.
