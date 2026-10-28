# Logging Guidelines

Two different streams; do not mix them.

| Stream | What | Where |
|---|---|---|
| Event log | Game facts used for replay and scoring: reactions, damage, deaths, pickups, decisions, harness actions | `events.jsonl` / `decisions.jsonl` in the recording (contracts section 5). Deterministic; part of reproducibility tests |
| Diagnostic log | Developer messages: timings, warnings, loader messages | Rust `tracing`, Python `logging`, to stderr. Never read by scoring |

- Default level INFO; per-frame messages only at TRACE/DEBUG.
- Never log API keys or full model prompts at INFO; prompts and model outputs belong in the run's decision records.
