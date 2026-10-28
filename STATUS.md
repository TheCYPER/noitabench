# Project status

*Written 2026-10-28 for collaborators joining the project. Maintainer: Percy ([@TheCYPER](https://github.com/TheCYPER)). This file is the running status report; update it at every checkpoint.*

## Summary

- **The whole loop works on a real model.** Generate a world, let a model play it through the harness, record everything, score the recording into a capability profile, look at the replay and the report in the browser. First real game: Claude Haiku 5.5 on 2026-10-27 (details below).
- **Where we are in the plan.** The first phase was planned as four "weeks" of work with a checkpoint each (CP1 to CP4). CP1, CP2 and CP3 are passed. Week 4 (evaluation, web report, more encounters, the knowledge base) is implemented; what remains of it is the **CP4 trial: one model from each of four providers plus a human, compared on composite score and profile.** The "weeks" are plan units: the implementation itself ran from 2026-10-26 to 2026-10-28 after three weeks of research and planning.
- **Tests are green** on macOS arm64 as of 2026-10-28: 498 Rust tests, 2,589 Python tests (1 skipped: live API calls), 304 web tests.
- **Biggest gaps.** No model other than Claude Haiku has played yet (the OpenAI, Gemini and DeepSeek adapters are only tested against mocked transports); no formal human baseline games yet; 7 of 24 encounters are not built; six global metrics are declared but not measured; the code sandbox is macOS-only; note extraction has not been tried with a real model.

## Timeline

| When | What | Result |
|---|---|---|
| 2026-10-07 | research of Noita mechanics, open-source falling-sand engines and agent benchmarks; knowledge base with rule ids; first plan report (`docs/plan-report.zh.md`) | plan reviewed; Rust core chosen, Godot dropped |
| 2026-10-16 to 10-26 | two questionnaires and a review round with the PI; PRD v1 → v3, technical design, time model, world design, capability graph, schedule | all decisions fixed, no open items in the PRD |
| 2026-10-26 | **week 1**: simulation core, world generator prototype, web viewer | **CP1** passed: material-behaviour recordings and world previews for five seeds judged "Noita-like" enough; feedback folded into week 2 |
| 2026-10-26/27 | **week 2**: wand engine and 25 spells, game layer (player, items, barrels, enemies, projectiles), rule crate, 12 encounter scenes, scripted descent bot | **CP2** passed: the bot walks from the start to the sealed bottom and breaks the seal with the real key; decisions listed below |
| 2026-10-27 | **week 3**: time model and commands, three observations, JSON Lines protocol, harness L0 to L5, three provider adapters, cost accounting, human play page | **CP3** passed: a cheap model played a whole game; the PI played a game in the browser |
| 2026-10-28 | **week 4**: evaluator and profile, replay/compare/report pages, five more encounters, knowledge base and note claims, walking and play-page fixes from the CP3 feedback | built; **CP4 (four models + human) not run yet** |

## The first real game (CP3)

Claude Haiku 5.5, tool-call mode, all six layers, notebook kept, world seed 42, rule seed 0.

| | |
|---|---|
| outcome | died on layer 2 (killed by an enemy) at y = 908 of 1664 (the seal is at y = 1574) |
| decisions / game frames | 235 / 16,580 (4.6 minutes of game time) |
| model calls | 47 (one call often issues several decisions through programs) |
| context compactions | 1 |
| tokens | 2.3 M cache reads, 111 k cache writes, 28 k output, 22 k thinking |
| cost | **$0.051** with prompt caching; 257 s wall time |
| notebook | empty at the end (the model used no workspace tools in this game) |

The run is `runs/cp3-haiku-42/` locally (not in the repository: 200 MB of frames); cut-down copies of its decisions, transcript and harness log are the test fixtures in `web/tests/fixtures/harness_run/`. The estimator says a full 1,000-decision Haiku game costs about $1.1 (range $1.0 to $2.2, $6.6 without caching).

## What is built

| Component | Where | State | Notes |
|---|---|---|---|
| Falling-sand core | `crates/sim` | done, tested | 34 materials, 14 reactions, fire, ray-cast explosions, chunk sleeping, grid queries for entities, recording to `frames.bin`, snapshot/restore, deterministic per seed |
| Rules and recipes | `crates/rules` | done, tested | the reaction table is fixed to the original (CP2 decision); each rule seed draws 8 secret potion recipes, 3 ingredients each from 12 |
| Game layer | `crates/game` | done, tested | player movement and levitation, bottles (fill/pour/drink/throw, mixtures, recipes in a bottle), wands with Noita-style deck casting and 25 spells, 3 enemies, 3 barrel kinds, kick, statuses, contact and drink effects, events |
| Python bindings | `crates/py`, `python/noitabench/{env,game}.py` | done | `Env` (sim), `Game`, `rules()`, `recipes(rule_seed)` |
| World generation | `python/noitabench/worldgen` | done, tested | fixed biome map (3 layers × 3 biomes, rest areas, seal), Wang tiles, prefab encounter placement with variants, must-pass corridors walled in brick, ingredient and bowl placement, post-generation checks (connectivity, encounter solvability, key reachability), previews, lab worlds for one scene |
| Encounters | `content/encounters`, `python/noitabench/eval/encounters` | 17 of 24 | built: E02 E03 E04 E05 E06 E07 E08 E09 E10 E12 E14 E16 E18 E21 E22 E23 E24 (all 9 must-pass ones among them). Not built: E01 E11 E13 E15 E17 E19 E20 |
| Scripted bot | `python/noitabench/bots` | done, tested | solves every must-pass encounter including the seal on several seeds; used to validate worlds and as a zero-cost player |
| Agent interface | `python/noitabench/agent` | done, tested | tick = 10 frames, a command runs ≤ 300 frames, ≤ 4 commands per decision, four default interrupts, `inspect` counts as a decision, text + ASCII + screenshot observations, JSON Lines protocol, MCP tool wrapper, `decisions.jsonl` |
| Harness | `python/noitabench/harness` | done, tested on macOS | L0 to L5, budget and price tables, cost estimate, compaction (loop briefing or Anthropic server-side), secret redaction of sandbox output, offline wheel whitelist; adapters: Anthropic (prompt caching), OpenAI-compatible, Gemini, DeepSeek (added 2026-10-28: thinking kept in the history, balance errors, per-provider output and timeout defaults, prices for `deepseek-flash` and `deepseek-v4-pro`), fake. `docs/running-models.md` is the per-provider guide |
| Human play | `python/noitabench/play`, `web/play.html` | done | pause mode, same commands and recording as an agent, notebook panel on the same workspace, auto-end on death or budget |
| Evaluator | `python/noitabench/eval` | done, v0.4.1 | encounter scorers, global metrics, 11 capability scores with the n/(n+2) discount, depth score, composite, failure attribution, "is this a test" phrase check, `profile.json` |
| Knowledge base and note claims | `python/noitabench/eval/knowledge`, `docs/knowledge-base.md` | done | 290 facts for rule seed 0 (8 recipes, 73 game-specific, 209 common Noita knowledge; 88 marked as told by the game); notes → claims by a model call, judged by code; metrics `notes_accuracy`, `notes_learned`, `notes_recall`, `notes_kept`, `notes_used`, `notes_corrected` |
| Web pages | `web/` | done, tested | replay (decision timeline, model transcript, harness actions, 0.25× to 8×), compare (2 to 4 runs), report (one profile or a comparison), world preview, play; no game logic in the browser |

Scale: about 28 k lines of Rust, 39 k of Python (plus 32 k of tests), 7 k of JavaScript (plus 4 k of tests). World: 768 × 1664 cells (6 × 13 biome cells of 128). Content: 34 materials, 14 reactions, 25 spells, 3 enemies, 9 biomes.

## Acceptance criteria of the first phase

From `prd.md` section 5. The status is my reading of the code and tests; it is not a formal sign-off.

| AC | Requirement | Status |
|---|---|---|
| AC1 | import the environment in Python and run a game headless; one command runs a scripted game | done (`noitabench.Env`, `python -m noitabench.bots.descend`, `harness run --provider fake`) |
| AC2 | same seed and commands → identical end state and event log; save, restore and replay agree | done (reproducibility and snapshot tests in `python/tests/sim`, `crates/sim/tests`) |
| AC3 | materials, reactions (including extinguishing), spells, potions, enemies, pickup, kick, statuses, each used by a test or an encounter | done for the first-version content |
| AC4 | the reaction table equals the original in every seed; recipes differ per seed; the agent has no way to the internet or external material | done (sandbox has no network; nothing in the prompt or tools reaches outside) |
| AC5 | time model B as specified; stop reasons and interim events in the observation and the log; `inspect` counts | done (`python/tests/agent`) |
| AC6 | every generated world passes the checks; previews show the layers, biomes, main path and encounters | done (`world check`, `docs/previews/`); "looks like Noita" judged by the PI at CP1 |
| AC7 | at least 12 encounters; per game a composite, 11 capability scores, depth and coverage; no score ever reaches the agent | done (17 encounters; secrecy guard tests) |
| AC8 | families: several games with the same rules and new maps; workspace kept, or cleared in the control | done (`--runs`, `--clear-workspace`) |
| AC9 | the six harness layers, two quotas, budget over all calls, no way to change the engine, scoring or budget; minimal setting | done on macOS; **L2/L3/L5 need `sandbox-exec`, so not on Linux** |
| AC10 | four providers run; tokens and dollars recorded; a default-size run on the reference model under $50 | **partly**: adapters for four providers plus fake, cost recorded; only Claude Haiku has actually played ($0.05 for a short game, about $1 estimated for a full one); GPT, Gemini, DeepSeek and open models untried; only the Claude 5.5 and DeepSeek models have built-in prices |
| AC11 | a human plays a whole game in the browser in pause mode; same recording, same scores | **partly**: the page and the pipeline work (the PI played one game at CP3); no participants recruited, no human profile published |
| AC12 | replay, speed control, side-by-side comparison, report, world preview; no game logic in the browser | done |
| AC13 | spot-check of model transcripts for "this is a test" remarks | **partly**: the evaluator flags phrases automatically (`test_awareness` in the profile); a systematic human spot-check over several models has not happened |

## Known gaps and limitations

- **Sandbox is macOS-only.** `run_code`, hooks and plugins run under `sandbox-exec`. On Linux use `--layers L0,L1,L4`. A Linux box (bubblewrap, seccomp or a container) is the obvious next engineering task if collaborators run on Linux.
- **Metrics declared but not measured** (reported as `not_measured` in every profile): `cross_game_gain`, `fire_and_buoyancy`, `experiment_value`, `inspect_result_used`, `wand_edit_gain`, `stop_when_unsure`. Capabilities whose metrics never fire are scored from encounters only; coverage is low in short games.
- **Encounters missing**: E01 (creature falls into liquid), E11 (shooter behind cover), E13 (floating platforms), E15 (alchemy bench), E17 (row of bottles), E19 (trap behind the corner), E20 (training dummy). The rest-area slots for E17 and E20 are placed but empty.
- **Coverage is thin per game.** With one short game most capabilities have 0 to 2 opportunities; the discount keeps them from dominating, but real conclusions need several games per model.
- **Only Claude and DeepSeek are priced.** Other models need `--price-input/--price-output` or `--allow-unpriced`. Prices were read on 2026-10-06 (Anthropic) and 2026-10-28 (DeepSeek, peak rates) and will go stale.
- **Note extraction with a real model is untried.** `notes-claims` has only run with `--claims-from` in tests (a Haiku extraction of one trial notebook was planned at $0.05).
- **The offline library whitelist** (`wheelhouse/`, not in the repo; `wheelhouse.lock` is) was downloaded for CPython 3.10 on macOS arm64. Other platforms must download their own wheels with the command in the lock file.
- **Big recordings.** About 0.7 MB of frames per decision; a 1,000-decision game is roughly 700 MB plus entities. The viewer holds whole runs in memory.
- **Mixed languages.** Agent-facing text, the knowledge base and code comments are English. The planning documents under `.trellis/tasks/` and parts of the web UI (labels, `name_zh` fields) are Chinese.
- `python -m noitabench serve` is listed by the dispatcher but has no implementation: the plain-HTTP play server replaced the planned WebSocket server.
- The repository has **no license yet**; see README.

## Decisions that shaped the current design

| Date | Decision |
|---|---|
| 2026-10-07 | Rust core + Python bindings; no Godot, no JavaScript game logic; the game rules live only in Rust |
| 2026-10-16/17 | LLM agents only, no RL; evaluation hidden from the agent; `inspect` as the active query; no "predict" action |
| 2026-10-21 | open world with scattered encounters instead of task levels; one composite score per game; human baseline through a web client; the agent may extend its own harness (DeepSeek Harness as the model) |
| 2026-10-26 | time model B (tick 10 frames, commands up to 300 frames); composite = 80 % capabilities + 20 % depth; goal "get as deep as you can"; metacognition judged from behaviour only; 4-week reduced schedule; water-family liquids extinguish fire (a deliberate deviation from Noita) |
| 2026-10-27 (CP2) | must-pass encounters are walled in brick that the starting wand cannot dig; wand editing only in rest areas and the hall before the seal; the reaction table is fixed to the original and the perturbation strengths dropped; anti-contamination comes from 8 secret potions whose recipes change per rule seed; alchemy bowls and a non-corrodible metal; the seal key is BOMB plus the EXPLOSIVE_PROJECTILE modifier in one wand, modifier first, and that modifier never appears in random drops |
| 2026-10-28 | capability scores discounted by n/(n+2) instead of excluding low-coverage ones (exclusion rewarded stopping early); depth counts only down to the seal unless the seal room is entered; walking no longer stops before a drop (no fall damage; `until=edge` is opt-in); E10 redesigned as a moat; everything the agent reads is English |

## Suggested next steps

1. **CP4 trial (F3).** One game each on a GPT model, a Gemini model, DeepSeek and an open model through an OpenAI-compatible endpoint, with Claude Haiku as the reference; same world and rule seeds; compare profiles on the report page. Needs keys and verified prices (`--price-input/--price-output`). Also the first real `notes-claims` extraction.
2. **Human baseline.** A few games by people who have and have not played Noita (the PRD plans 4 to 6 each), on seeds whose replays they have not seen. The play page is ready; a short participant instruction sheet is not.
3. **Review the scoring.** `python/noitabench/eval/encounters/*.py` and `eval/metrics/*.py` are where the capability claims become rules. A second pair of eyes on whether each rule measures what the capability graph says is the most valuable review right now.
4. **Remaining encounters and metrics.** The seven missing scenes and the six unmeasured metrics, in the order of which capabilities have the least coverage.
5. **Linux sandbox**, so the full harness runs outside macOS.
6. **Phase 2 items** (from the PRD): fork-scouting ablation, real-time human mode, an external-harness track over MCP, biome modifiers, shops and perks, the public release and the paper experiments.

## How to help

Clone it, build it, run the fake game and a Haiku game with your own key (README), then open an issue or a PR on this repository. Questions about intent are answered by the design documents in `.trellis/tasks/10-16-noita-cogbench/` (Chinese) and by `contracts.md` (English); everything else, ask Percy.
