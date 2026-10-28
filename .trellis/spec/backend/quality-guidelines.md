# Quality Guidelines

## Gates (every PR)

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
ruff check python && ruff format --check python
pytest python/tests
```

A PR that touches simulation code must also pass the reproducibility test (two runs, same seed, identical grid hash and event log; snapshot then restore then replay gives the same hash).

## Tests

- Write the test first for every rule; name it after the KB rule or vector it checks (`sim_r32_liquid_lateral_range`, `mv_17_mine_digs_rock`).
- Keep tests small and deterministic: fixed seed, tiny grids (for example 32×32), explicit frame counts.
- Every mechanic that a user reviews visually also gets a short recording under `runs/demo-*` produced by a script, so it can be watched in the web viewer.

## Forbidden

- Iterating a `HashMap`/`HashSet` in simulation code; wall-clock time or thread-dependent behaviour in simulation code.
- `unsafe` without a comment explaining why and a test covering it.
- Game logic outside `crates/sim` and `crates/game`.
- Hard-coded material numbers in code: read them from `content/materials.json`.
- Network access from anything an agent can call.

## Style

- Rust 2021 edition, stable toolchain. Small functions (under about 50 lines), no deep nesting.
- Python 3.10+ (the local interpreter is 3.10), type hints on public functions, `ruff` defaults.
- Prefer returning new values over mutating inputs in Python helpers; in Rust hot loops, in-place mutation of the grid is expected.
