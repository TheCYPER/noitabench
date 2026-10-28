# Error Handling

## Rust

- Library crates return `Result<T, Error>` with one `thiserror` enum per crate; no `unwrap()`/`expect()` outside tests and `main`, except on invariants that are documented in a comment.
- Loading content files validates everything up front (unknown material key, bad colour, unknown tag in a reaction) and fails with a message naming the file and the field.
- The simulation step itself never fails: invalid states are prevented at load time and by tests.
- PyO3 wrappers convert crate errors into Python `ValueError` (bad input) or `RuntimeError` (internal) with the original message.

## Python

- Validate inputs at the boundary (CLI arguments, files, agent commands) and raise `ValueError` with a message that says what was wrong and what is allowed.
- Agent-facing errors (an invalid command) are **returned to the agent as data** (`{ok: false, code, message}`) and logged as an event; they never crash a run.
- Never swallow exceptions silently; log with context and re-raise or convert.
