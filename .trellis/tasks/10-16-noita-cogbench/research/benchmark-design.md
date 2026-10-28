# Benchmark design: the Noita clone as an agent benchmark

Research deliverable for task `10-07-noita-clone` (child `10-07-agent-benchmark`).
Written 2026-10-07. Everything quantitative below was taken from the sources in
the final section; raw copies of the READMEs / source files / extracted paper
text that were relied on are in `research/raw/`. Items that could not be
confirmed against a primary source are marked **UNVERIFIED**.

Companion structured files:

- `benchmark-survey.json` — the survey table in machine-readable form.
- `benchmark-protocol.json` — JSON Schema for the JSON-lines protocol, observation and action messages.
- `benchmark-tasks.json` — the proposed task suite with limits and scoring formulas.

---

## 1. Survey of existing game-based agent benchmarks

### 1.1 Survey table

Columns: what the agent observes, what it can do, how episodes are seeded /
reset, how long they last, how they are scored, and how results are validated.

| Benchmark (year) | Target agents | Observation modality | Action space | Reset / seed | Episode limits | Scoring | Leaderboard / validation |
|---|---|---|---|---|---|---|---|
| **NLE – NetHack Learning Environment** (2020; NetHack 3.6.7) | RL (LLM via `nle-language-wrapper`) | Dict of arrays: `glyphs` (21×79 ints), `chars`/`colors`/`specials` (21×79 uint8), `blstats` (int vector), `message` (256 uint8), `inv_glyphs`/`inv_strs`/`inv_letters`/`inv_oclasses`, `screen_descriptions`, `tty_chars`/`tty_colors` (24×80), `tty_cursor`, `misc` | Discrete. `NetHackScore` task uses 23 actions (`MORE` + 8 compass + 8 compass-longer + 3 misc directions + kick/eat/search); default `FULL_ACTIONS = nethack.USEFUL_ACTIONS`; `NetHackChallenge-v0` uses `nethack.ACTIONS` (121 actions per the challenge report, count **UNVERIFIED** from source) | `env.seed(core, disp, reseed=False, lgen)`: NetHack 3.6 has two RNGs (`core`, `disp`) as an anti-TAS measure; `reseed=True` re-seeds from true randomness ("trajectories won't be reproducible"); `lgen` gives level generation its own RNG so levels are "fixed and independent from the in-game choices"; `fix_moon_phase=True` derives moon phase / Friday-13th / night effects from the seed instead of wall clock | `max_episode_steps=5000` default (`info["end_status"]=ABORTED` on hit); `NetHackChallenge` default `1e6`; frozen-state penalty `penalty_step=-0.01` (modes constant/exp/square/linear/always), `penalty_time` | `NetHackScore`: in-game score delta + time penalty; `Staircase`: +1 on reaching stairs; `Gold`: gold delta; `Eat`: hunger delta (has a documented FIXME: penalises every other step); `Scout`: newly explored cells | ttyrec recording every N episodes (`save_ttyrec_every`); NetHack Learning Dataset (NLD-AA, NLD-NAO) loaders ship with NLE. NeurIPS 2021 NetHack Challenge: AIcrowd Docker eval, dev phase 512 rollouts in a 2-hour window, test phase 4,096 rollouts "over a day"; tie-break order: number of ascensions, then median score; agent containers ran on separate instances from the env container (organizer-controlled env + score tracking) |
| **MiniHack** (2021) | RL | Same NLE arrays, optionally cropped (e.g. 9×9 around the agent), plus pixel/text | NLE discrete, restrictable per task (e.g. 8 compass directions for navigation) | des-file DSL (`.des`) + `LevelGenerator` Python API; `RewardManager` with events (reach coordinate/location, message, inventory …) and repeatable/terminal flags | per-task `max_episode_steps`; BALROG uses 100 with `penalty_step=-0.01` | task-defined reward via RewardManager; task families Room, Corridor, MazeWalk, River, HideNSeek, Memento, Eat, Pray, Sink, Wear, LavaCross, WoD, Quest; ported MiniGrid & Boxoban | Gymnasium API; emphasis on controllable difficulty progression |
| **BALROG** (ICLR 2025) | LLM & VLM (zero-shot, CoT, few-shot agents) | Text via language wrappers (BabyAI templated text; Crafter "Your status / You see: - tree 3 steps to your north-west"; TextWorld native text; Baba Is AI rules + relative positions; MiniHack & NetHack via `nle-language-wrapper` + ASCII map) or text + image (`max_image_history>=1`) | Text string chosen from the listed action set with one-line descriptions (Crafter: 17 actions + Noop listed; BabyAI 6; Baba Is AI 5) ; invalid action feedback on (`feedback_on_invalid_action: True`) | `envs.env_kwargs.seed: null` → random seeds; episodes per env in `config.yaml`: nle 5, minihack 5 per task (8 tasks), babyai 10 per task (5 tasks), crafter 10, babaisai 3 per task (40 tasks), textworld 10 per task (3 tasks) | nle `max_episode_steps=100_000` + `no_progress_timeout=150`; minihack 100; crafter 2000; textworld 80 | Per-env progress 0–100%: BabyAI/Baba/MiniHack binary success; Crafter % of 22 achievements; TextWorld score/max_score; NetHack: data-informed progression from NLD-AA = probability that a human who reached a given Dlvl or Xlvl wins; Dlvl 1 / Xlvl 1 = 0%, ascension = 100%, episode progress = max(dlvl-progress, xlvl-progress). Paper: Claude 3.5 Sonnet 32.64±1.93, GPT-4o 32.34±1.49, Llama 3.1 70B 27.88±1.43 (text); NetHack best o1-preview 1.57±0.40%; std. error from 5 seeds | Public leaderboard balrogai.com with "Checked" = reproduced by BALROG team; trajectories saved (`save_trajectories: True`); default `temperature 1.0`, `max_tokens 8192`, `max_text_history 16`. Leaderboard as fetched 2026-10-07 lists top text entries at 68.3±2.0 / 63.4±1.8 / 60.0±2.0 (NetHack column 13.2 / 7.3 / 3.2) — numbers as displayed, not independently checked |
| **Crafter** (2021) | RL (later LLM agents, e.g. SPRING) | 64×64×3 RGB; 9×9 unit view of which 9×7 is the map and 2 rows are inventory ("agent needs to learn to read its inventory state out of the image"); world 64×64 cells | 17 discrete: noop, move_left/right/up/down, do, sleep, place_stone/table/furnace/plant, make_wood/stone/iron_pickaxe, make_wood/stone/iron_sword | `Env(seed=…)`; per-episode world seed = `hash((seed, episode)) % (2**31-1)`, i.e. "randomness … uniquely determined by an integer seed derived from the initial seed and the episode number" | `length=10000` steps; episode also ends on death | +1 on first unlock of each of 22 achievements per episode, ±0.1 per health point; **report success rates and score, not reward**; success rate = fraction of training episodes (within the 1M-step budget) unlocking achievement i; score `S = exp(1/N Σ ln(1+s_i)) − 1`, N=22, s_i in [0,100]; Human experts 50.5±6.8, DreamerV2 10.0±1.2, PPO 4.6±0.3, Rainbow 4.3±0.2, Plan2Explore 2.1, RND 2.0, Random 1.6; README scoreboard adds Curious Replay 19.4±1.6, PPO-ResNet 15.6, DreamerV3 14.5, SPRING (LLM + paper text) 27.3±1.2 | `crafter.Recorder` wrapper (stats/video/episode); `info` carries privileged `semantic` map, `inventory`, `achievements`, `player_pos` that the agent "is forbidden to observe"; scoreboard split into RL / Unsupervised / External-knowledge categories, PRs to add rows |
| **Craftax** (2024, JAX) | RL (massively parallel) | `Craftax-Symbolic` flat vector of 8268 floats (one-hot map view, inventory, intrinsics, direction, light…), `Craftax-Classic-Symbolic` 1345; pixels 110×130×3 / 63×63×3 | 43 discrete (Classic: 17) | gymnax API: `env.reset(rng_key, params)`, `env.step(rng_key, state, action, params)`; pure JAX functions, determinism via explicit PRNG keys | per-env params; `auto_reset` optional ("optimistic resets") | % of max achievable reward (max 226); budgets `Craftax-1B` and `Craftax-1M` | README scoreboard notes "scores from outside the original paper … have not been verified"; changelog documents reward-affecting bugs fixed in v1.5.0 and v1.6.0; 250× faster than Crafter, symbolic ≈10× faster than pixels, 405,618 steps/s on an RTX 4090 with 4096 envs |
| **MineRL** (v0.4 for 2021 comps; v1.0 for BASALT 2022 / VPT) | RL + imitation | v0.4: `pov` Box(64,64,3) uint8 + `inventory` dict (item counts 0–2304) + `equipped_items.mainhand` (damage, maxDamage, type); v1.0: only 640×360 pixels ("no more inventory observation by default") | v0.4 dict: attack, back, camera Box(2) in degrees [−180,180], craft, equip, forward, jump, left, nearbyCraft, nearbySmelt, place, right, sneak, sprint; v1.0: mouse/keyboard-like, no craft/smelt actions, GUI control | Gym `reset()`; Minecraft itself is not deterministic even with seeds (reproducibility caveat) | ObtainDiamond cap 18,000 steps (**UNVERIFIED** — not found in the v0.4.4 docs page fetched) | ObtainDiamond milestone rewards on first obtain: log 1, planks 2, stick 4, crafting_table 4, wooden_pickaxe 8, cobblestone 16, furnace 32, stone_pickaxe 32, iron_ore 64, iron_ingot 128, iron_pickaxe 256, diamond 1024 | Human demonstration dataset (MineRL-v0); original mirrors went offline 2024-06-17 and were re-hosted on Zenodo — a data-longevity lesson |
| **MineDojo** (2022) | RL / foundation-model agents | Dict: `rgb` (3,H,W) uint8; `equipment` (6 slots: name, quantity, variant, durability); `inventory` (36 slots); `voxels` 3×3×3 (block_name, is_collidable, is_liquid, can_burn …); `life_stats` (life 0–20, oxygen 0–300, armor, food, saturation, xp 0–1395); `location_stats` (pos, yaw, pitch, biome_id, rainfall, temperature, light_level 0–15, sea_level …); `nearby_tools`; `damage_source`; action `masks`; `delta_inv` | `MultiDiscrete([3,3,4,25,25,8,244,36])`: fwd/back, strafe, jump/sneak/sprint, camera pitch (25 bins ≈14.4°), camera yaw, functional (noop/use/drop/attack/craft/equip/place/destroy), craft arg (244 items), slot arg (36) | `minedojo.make(task_id, image_size)`; task prompt + GPT-3 guidance text per task | per task | 3,142 tasks: 1,581 programmatic ("automatically scored based on ground-truth simulator states": Survival / Harvest / Tech-tree / Combat), 1,560 creative (MineCLIP video-text reward; "no well-defined success criteria"), 1 playthrough (Ender Dragon) | Knowledge base: 730K+ YouTube videos (~300K h, 2.2B transcript words), ~7K wiki pages, 340K+ Reddit posts / 6.6M comments |
| **TextWorld** (2018) | RL / LLM text agents | Text feedback; optional `EnvInfos` fields: feedback, description, inventory, location, facts, last_action, last_command, game, won, lost, score, moves, max_score, objective, entities, verbs, command_templates, admissible_commands, intermediate_reward, policy_commands, extras | Free-text commands | `tw-make custom --world-size 5 --nb-objects 10 --quest-length 5 --seed 1234` → `.z8` game file; `textworld.gym.register_game(path, max_episode_steps=50)` | `max_episode_steps` per registration (BALROG uses 80) | score / max_score; `intermediate_reward` available; `won`/`lost` flags | challenge generators: `tw-coin_collector`, `tw-treasure_hunter`, `tw-simple`, `tw-cooking` |
| **TextArena** (2025) | LLM (single/multi-agent), RL-for-LLM (SPIRAL, UnstableBaselines) | Text observations with game-specific prompts; `(player_id, observation)` from `env.get_observation()` | Text with bracketed moves, e.g. `[A1]`; invalid moves get negative feedback without terminating | `ta.make(env_id)`, `env.reset(num_players=N, lang_mapping=…)`; 57+ envs at paper time (16 single / 47 two / 11 multi-player), 100+ now; 192 UI languages | per game | `+1` win / `0` draw / `−1` loss per player returned from `env.close()`; 10-skill taxonomy (Strategic Planning, Spatial Thinking, Pattern Recognition, Theory of Mind, Logical Reasoning, Memory Recall, Bluffing, Persuasion, Uncertainty Estimation, Adaptability), ≤5 skills tagged per game | Online play vs humans and models; TrueSkill (μ=25, σ=25/3) with "Humanity" baseline; 283 models tracked (64 official); "no clear upper limit" → relative ranking resists saturation |
| **SmartPlay** (2023) | LLM | Text (+ a human-written "manual" with rules and examples) | Text chosen from a list | fixed trial counts: Bandits 20, RPS 20, Hanoi 10, Messenger 100, Crafter 10, Minecraft 20 | per game | per-game score normalised against a human baseline; 9 capabilities rated 1–3 per game (long-text understanding, multi-hop reasoning, rule following, planning, generalisation, understanding odds, learning from interaction, error handling, spatial reasoning); GPT-4 gaps vs human ≈10% Hanoi, 40% Minecraft, 70% Crafter | — |
| **lmgame-Bench** (2025) | LLM / VLM, with or without harness | Frames → optional *perception module* that converts to symbolic text (grids) / dialogue; *memory module* (last N states + reflections); *reasoning module* | Game-specific text actions via Gymnasium-style envs (Retro/PyBoy) | Gymnasium; `--harness_mode true|false|both` | per game | Mario: x-distance; Sokoban: boxes/levels; 2048: log-sum of merged tiles; Tetris: lines/pieces; Candy Crush: candies; Ace Attorney: case progress. 13 models, ~3 runs per configuration | Found prompt variance "may exceed ±1 SD even among empirically optimised prompts" → two-stage prompt standardisation (manual + DSPy). Contamination checks: vision-level (shuffled-frame ordering ≈30% accuracy, no correlation with play), text-level (Ace Attorney output similarity correlated with score until entity masking / paraphrasing / enforced reasoning removed it) |
| **VideoGameBench** (2025) | VLM, real-time | Raw 640×400 screenshots only ("no parsed overlays or state") | `press_key [key]` with optional hold duration, mouse `move x,y` / `click` / `drag` | 10 test games (7 public: Doom II, Kirby's Dream Land, Zelda: Link's Awakening, Civilization, Need for Speed, The Incredible Machine, Pokémon Crystal; 3 **secret**) + 13 dev games | `--max-steps` default 15000; real-time by default; **Lite** pauses the emulator while the model thinks | % completion = position in a reference walkthrough of the last matched checkpoint; checkpoints are reference frames scraped from YouTube walkthroughs matched by perceptual hash + Hamming distance; best models (Gemini 2.5 Pro, Claude 3.7 Sonnet) 0.48% full / 1.6% Lite | Logs every screenshot, LLM call and button press under `logs/{game}/{model}/{run}`; secret games held out against memorised walkthroughs |
| **Orak** (2025) | LLM / VLM agents, fine-tuning | Text state description or text+image | Predefined discrete text actions; menu/dialogue choices (Ace Attorney, Her Story, Pokémon Red); JavaScript code via Mineflayer (Minecraft) | Each game and each agentic module runs as an **MCP server** exposing tools (`get state`, `step`, reflection, planning…) | 3–20 runs per game | 0–100 per game: Pokémon Red = 12 storyline flags; Mario = distance; Street Fighter III = stages; Stardew = profit over 13 in-game days; Minecraft binary; 2048 progress; Slay the Spire floors … Gemini-2.5-Pro avg rank 3.5, GPT-4o 3.6, GPT-5 3.6, Claude 3.7 5.1, Llama 3.3 70B 7.3 | Finding: image-only input causes "substantial drop"; text+image hurts narrative games (GPT-4o −31.8 on Ace Attorney) but helps action games (+16.6 Claude on SF III); fine-tuning dataset ≈11K samples |
| **PokéAgent Challenge** (NeurIPS 2025; paper 2026) | LLM harnesses and RL | Speedrun track (Pokémon Emerald on mGBA, real-time): frames + *limited* structured RAM state (party species/levels/HP/status) but deliberately **not** puzzle state, items, movesets "to maintain the perception challenge". Battle track: structured text battle state | Buttons (A, B, Up, Down, Left, Right, Start, Select); battle track ≈9 actions/turn | Headless FastAPI game server (`/state`, `/action`, `/mcp/*`), MCP proxy for CLI agents; `memory_reader.py` marked "DO NOT MODIFY for submissions"; `anticheat.py`; checkpoints / backups / `cumulative_metrics.json` (tokens, cost, actions) | Scoped to the first gym (Roxanne); real-time so "inference latency is a first-class cost" | Speedrun: milestone completion %, then wall-clock, then action count; 6 of 22 teams reached 100%; winner 40:13 vs ≈18 min human speedrunner vs 1:22:05 average human. Battle: Full-History Bradley–Terry rating, Bo99 finals (first to 50); 100K+ battles on the server | 100+ teams; results reported with wall-clock, steps, reasoning tokens and cost; harness differences dominate (see Claude/Gemini below) |
| **Claude Plays Pokémon / Gemini Plays Pokémon** (2025 livestream harnesses) | LLM | Screenshot (+ grid/overlay), RAM reads (coordinates), text minimap (Gemini), knowledge-base notes | `use_emulator` button presses; navigator/pathfinding tool to coordinates (Claude); dedicated pathfinder/critic model instances (Gemini) | Context summarisation when full; editable long/short-term note files | open-ended (hundreds of hours) | badges / milestones; Claude 3.7 Sonnet reached 2 badges (~140 h equiv); Gemini 2.5 Pro finished Blue in ~816 h / ~106,500 actions (run 1) and ~406 h / ~36,801 actions (run 2) | Failure modes: loops (78+ h in Mt. Moon), deleting correct notes after a white-out, false beliefs persisting in notes, poor screen reading. Lesson (Bradshaw): map labelling, specialised sub-instances and prompt iteration were the key factors → cross-model comparison invalid unless the harness is fixed |
| **Factorio Learning Environment** (2025) | LLM (code-as-action) | Text: stdout/stderr of the last program, inventory, entities, production stats, errors | Python programs against 23 API methods (`place_entity`, `connect_entities`, `craft_item`, `get_entities`, `production_stats`, `nearest` …) | Headless Factorio server, Docker, RCON (determinism concerns acknowledged but not detailed) | Lab-play: 24 tasks × 128 API calls; open-play 5,000 steps | Lab-play success = target throughput (16 items/s solids, 250/s fluids) held over a 60 s holdout; open-play Production Score (value-weighted output) + milestones; Claude 3.5 Sonnet 21.9±1.3%, GPT-4o 16.6±1.4%, Llama 3.3 70B 6.3±1.0%; 56% of steps raised execution errors | Public leaderboard; errors are observations; "degenerate debug loops" are a dominant failure mode |
| **Procgen** (2019) | RL | 64×64×3 RGB | `Discrete(15)` button combos | `start_level` + `num_levels` fully specify the level set (0 = unlimited); `distribution_mode` easy/hard/extreme/memory/exploration; `use_sequential_levels` | per game | Normalised return `R_norm = (R − R_min)/(R_max − R_min)` with per-env constants (e.g. CoinRun 5/10, StarPilot 1.5/35 hard, BigFish 0/40, Plunder 3/30); mean across 16 envs; budgets 25M steps (easy) / 200M (hard); generalisation protocol trains on 500 levels (hard) or 200 (easy) and tests on the full distribution; gap closes only with ~10,000 training levels | README documents known level bugs (`jumper` ~7% of levels end after one step, `caveflyer` ~0.5%) rather than silently changing the generator — important precedent for task versioning |
| **ALE revisited** (2018) | RL | Atari frames | 18 actions (full set recommended) | Atari 2600 is fully deterministic → "The Brute" can memorise action sequences; fix: **sticky actions** (repeat previous action with p=0.25) | 108,000 frames (≈30 min) cap; frame skip 4–5 | report training-time performance; no-op starts deprecated | — |
| **Gymnasium API** (Farama) | RL | `observation_space` | `action_space` | `reset(seed=None, options=None) → (obs, info)`: int seed re-seeds `np_random` "even if it already exists", `None` keeps the existing PRNG, first call without a seed draws from entropy; recommendation: "pass an integer right after the environment has been initialized and then never again" | `TimeLimit` wrapper sets `truncated`; `terminated` = MDP terminal state | `step(action) → (obs, reward, terminated, truncated, info)` | env ids versioned `-v0`, `-v1`; `env_checker.check_env` |
| **PettingZoo** (Farama) | multi-agent RL | per-agent `observation_space(agent)` | per-agent `action_space(agent)`; `info["action_mask"]` convention | AEC: `reset(seed, options)`, `agent_iter(max_iter)`, `last() → (obs, reward, termination, truncation, info)`, `step(action)` (dead agents must `step(None)`); Parallel: `step(actions: dict) → (obs, rewards, terminations, truncations, infos)` dicts | `max_cycles` convention | per-agent `rewards` dict | — |
| **SWE-bench / Verified / SWE-bench+** (2023–2024) | coding agents (non-game, included for determinism lessons) | repo + issue text | patch | Docker, instance-level images (≥120 GB disk, 16 GB RAM, 8 cores recommended; `max_workers ≤ min(0.75·cpus, 24)`) | — | resolved iff all `FAIL_TO_PASS` tests pass and `PASS_TO_PASS` keep passing; **Verified**: 93 developers annotated 1,699 samples, 3 annotators each, severity 0–3, 68.3% discarded → 500 kept; **SWE-bench+**: 32.67% of successful patches had the solution leaked in the issue/comments and 31.08% passed only because of weak tests; SWE-Agent+GPT-4 falls 12.47% → 3.97% after exclusion; Epoch AI excludes 16/500 instances for infra reasons (network, dependency drift) | Harness caches by `(run_id, instance_id)` only — re-running with a changed prediction but the same `run_id` silently reuses old results; `logs/evaluation/<run_id>/results.json`; `swebench report` can re-grade saved logs without containers |
| **Lux AI Challenge S3** (Kaggle, 2024–25) | scripted / RL bots | JSON string per step on stdin: `obs.units.position/energy`, `units_mask`, `sensor_mask`, `map_features`, `relic_nodes(_mask)`, `team_points`, `team_wins`, `steps`, `match_steps`, `remainingOverageTime`, `player`, `info.env_cfg`; invisible values are `-1` | `(N,3)` int array per team (0 noop, 1–4 move, 5 sap dx dy) | randomised hidden game parameters fixed within a game; 24×24 map; best-of-5 matches × 100 steps | 2 s per turn + overage budget | match points; game = most matches won | `luxai-s3 main.py main.py --output replay.json` produces a replay for the online visualiser; stderr reserved for logging |
| "Lightning Gym" | — | — | — | — | — | — | **UNVERIFIED / not found**: no benchmark with this name surfaced; closest matches are lmgame-Bench, VideoGameBench Lite (paused), GVGAI-LLM (118 GVGAI games via VGDL; search snippet only) and SmartPlay |

### 1.2 Lessons that shape our design

1. **Determinism is a property of the simulator, stochasticity is a wrapper.** Atari's full determinism allowed "The Brute" to memorise action sequences; the fix was sticky actions *inside the evaluation protocol*, not a non-deterministic emulator. NetHack takes the opposite stance (anti-TAS reseeding) and NLE had to add `reseed=False`, `lgen` and `fix_moon_phase` to get reproducible trajectories back. Craftax goes furthest: pure functions keyed by explicit PRNG keys. → Our core must be bit-deterministic given `(seed, action log)`; any randomness an RL user wants for robustness (sticky actions, seed sampling) lives in the client.
2. **Seeds are first-class and split.** Procgen's `start_level/num_levels`, Crafter's `hash((seed, episode))`, TextWorld's `--seed`, NLE's `lgen`. Generalisation gaps close only with ~10,000 Procgen levels; evaluation uses held-out levels. → Public seed lists for development, hidden seed lists for official evaluation, and a documented derivation `episode_seed = H(task_id, task_version, seed_index)`.
3. **Score what you mean.** The NetHack Challenge's in-game score "does not adequately reflect actual progression"; the winning bots optimised score "at the expense of progressing into the dungeon", and several entries showed "evidence of early episode termination". BALROG replaced score with a data-informed progression metric. Crafter reports success rates + geometric mean rather than reward, so hard achievements matter. → Every task needs a success criterion, a bounded partial-credit formula that cannot be improved by dying early, and separate efficiency metrics.
4. **Text beats pixels for today's LLMs; keep both.** BALROG: "models perform worse when visual representations … are provided"; Orak: image-only input causes a "substantial drop" although images help in action games; VideoGameBench (pixels only, real-time) tops out at 0.48%; lmgame's harness converts frames to symbolic grids; Gemini's Pokémon win depended on a labelled text minimap. → First-class compact ASCII/structured observation for LLMs, uint8 grids for RL, optional RGB for pixel agents, and the observation mode recorded in the run so leaderboards are split by modality.
5. **The harness is part of the result.** Claude vs Gemini Pokémon comparisons were invalid because harnesses differed; lmgame separates `harness_mode`; Crafter splits "external knowledge" rows; PokéAgent reports tokens/cost/wall-clock. → Record `assists` (pathfinding macros, admissible-action lists, oracle hints) and cost metrics in every run file; leaderboard tracks keyed by them.
6. **Turn-based by default, real-time as an explicit track.** VideoGameBench needed a "Lite" paused mode; PokéAgent made latency a first-class cost. → The engine only advances on `step`; an optional real-time track auto-advances with a per-decision wall-clock budget.
7. **Invalid actions are observations, not crashes.** BALROG feeds back invalid-action messages; TextArena penalises but continues; FLE agents see Python errors; 56% of FLE steps errored. → Protocol returns structured errors and the next observation carries them; invalid decisions count against the decision budget.
8. **Validation = re-execution.** NetHack Challenge ran the environment in an organiser container; Lux produces `replay.json`; SWE-bench keeps per-instance logs; SWE-bench+ shows that leaked solutions and weak checks inflate results by 3×. → Submissions are action logs; the validator replays them and recomputes hashes and scores; task text must never contain the solution.
9. **Version everything and document bugs instead of silently fixing them.** Procgen documents the `jumper` 7% bug; Craftax lists reward-affecting fixes by version; Gymnasium ids carry `-vN`; SWE-bench's cache-by-`run_id` pitfall is a cautionary tale. → `task_id@version`, engine semver + git hash, content hash of data files, golden replays per version.
10. **Budget both sim time and decisions.** NLE 5,000 steps + no-progress timeout; BALROG per-env step caps; FLE 128 API calls; Crafter 10,000 steps. → Each task has `frame_limit` (sim) and `decision_limit` (agent calls); both reported.
11. **Partial observability must be designed, not accidental.** Lux encodes invisible cells as `-1`; PokéAgent withholds puzzle state deliberately; MiniHack crops to 9×9. → Observation radius is a task parameter; unknown cells have a reserved id; v1 has no fog inside the window.

---

## 2. Recommended interface for the Rust core

### 2.1 Process model

`noita_bench` is a headless binary speaking **JSON Lines** on stdin/stdout
(one UTF-8 JSON object per `\n`-terminated line, no pretty printing; stderr is
for logs only, as in the Lux kits). The engine never advances time on its own:
only `step` advances frames (VideoGameBench-Lite semantics). A thin Python
client (`noita_bench/client.py`) wraps the subprocess and exposes a
Gymnasium-compatible `Env` plus a text façade for LLM agents.

```
python agent  ──JSONL──►  noita_bench --protocol jsonl [--dev] [--log run.jsonl]
   client     ◄──JSONL──      (noita_core linked statically; no renderer)
```

Design choices and rationale:

- **JSONL over stdio** rather than HTTP/MCP: zero dependencies, trivially sandboxed, works for subprocess vector envs, and is what Lux AI uses for Kaggle-scale evaluation. An MCP adapter (Orak/PokéAgent style) can be layered on the same message set later.
- **Request/response with ids**: every request has `"id"`; the response echoes it so the client can detect desync. The engine processes requests strictly in order.
- **Binary payloads**: `uint8` grids are sent as base64 of raw bytes with an explicit `shape`/`dtype`; optional `"codec":"zlib"`; arrays never appear as JSON number lists (a 128×128 grid would be ~60 KB as JSON numbers vs 22 KB base64, ~3 KB zlib).
- **Versioned handshake**: `hello` returns `protocol_version`, `engine_version`, `engine_git`, `content_hash` (blake3 of `materials.json`, `spells.json`, task generators), `suite_version`. The client refuses a protocol major mismatch.

### 2.2 Message set

| Request | Fields | Response (besides `id`, `ok`) | Notes |
|---|---|---|---|
| `hello` | — | `protocol_version`, `engine_version`, `engine_git`, `content_hash`, `suite_version`, `dev_mode`, `capabilities[]` | first message |
| `list_tasks` | — | `tasks: [{id, version, family, description, frame_limit, decision_limit, public_seeds, obs_modes}]` | |
| `info` | `what: "materials"\|"spells"\|"actions"\|"legend"\|"task"` | the requested static table | static for a given `content_hash` |
| `reset` | `seed: u64`, `task: "dig_to_depth@1"`, `config: {obs: {...}, assists: {...}, realtime: null\|{budget_ms}}` | `episode_id`, `obs`, `info: {task: {objective, limits, legend}, state_hash}` | `seed` is the *public* seed index or a raw u64; see §4.2 |
| `step` | `frames: u16 (1..=600)`, `actions: [ControlState] (len 1 or == frames)`, `oneshot: [OneShot]` | `obs`, `reward: f32`, `terminated`, `truncated`, `frame`, `state_hash`, `events[]`, `task: {score, progress, success}`, `error?` | advances `frames` frames; invalid → `ok:false`, no frame advance |
| `observe` | `obs?: {...override}` | `obs` | re-render without advancing (e.g. different radius) |
| `metrics` | — | `frames`, `decisions`, `wall_ms`, `invalid_actions`, per-task counters | |
| `replay` | `log: path` or inline `entries[]`, `until_frame?` | `verified: bool`, `first_divergence?: {frame, expected, got}`, `score` | re-executes a recorded log (see §5) |
| `save_state` / `load_state` | `path` | `state_hash` | **dev-mode only**; run is marked `dev` |
| `debug` | `op: "set_material"\|"spawn"\|"teleport"\|"reveal"`, … | | **dev-mode only** |
| `close` | — | | |

Error object: `{"code": "INVALID_ACTION"|"BAD_TASK"|"EPISODE_OVER"|"DEV_ONLY"|"PROTOCOL"|"LIMIT", "msg": "...", "hint": "..."}`. Errors are also echoed in the next observation's `events` so LLM agents see them (BALROG `feedback_on_invalid_action`).

### 2.3 Action schema

Two layers: a per-frame **control state** (what a human's keyboard/mouse does)
and **one-shot** actions (inventory operations). The LLM text grammar and the
RL vector both compile down to these.

```jsonc
// ControlState — held for the frames it covers
{
  "move": -1 | 0 | 1,          // left / none / right
  "jump": bool,                // edge-triggered on first frame it becomes true
  "fly": bool,                 // levitation (consumes the levitation meter)
  "aim": {"deg": -180.0..180.0} | {"dx": f32, "dy": f32} | {"at": [x, y]},   // 0° = right, positive = counter-clockwise (up)
  "fire": bool,                // hold to cast with the active wand (cast delay / recharge apply)
  "kick": bool,
  "interact": bool,            // pick up wand/spell, use portal
  "down": bool                 // crouch / drop through platforms if applicable
}
// OneShot — applied at the start of the step, 0 frames
{"swap_wand": 0..3}
{"edit_wand": {"wand": 0, "spells": ["DIGGER", null, "LIGHT_BULLET"]}}   // null = empty slot; ids from spells.json; length <= capacity
{"drop_spell": {"wand": 0, "slot": 2}}
{"pickup": {"entity": 17}}
{"wait": 30}   // sugar: equals a step with frames=30 and a neutral control state
```

Rules: `edit_wand` is allowed only when the task's `wand_edit` policy permits
(`anywhere` | `at_rest_zones` | `locked`) and the wand is not mid-cast; each
edit counts toward `max_wand_edits`. `frames` per step is capped (default 600
= 10 s) so a single decision cannot skip an episode. `actions` with length
`frames` gives per-frame control for RL/TAS-style agents; length 1 holds.

**LLM text grammar** (one decision = one line, `;`-separated macros executed sequentially; each macro expands to control states and frames; total frames per decision capped by `max_frames_per_decision`, default 120):

```
move left 30 | move right 30        # frames
jump | jump right 20                # jump then hold direction
fly 40 | fly left 40
aim -35 | aim at 120 -40            # degrees, or dx dy relative to player (px)
cast 12 | cast at 120 -40 12        # hold fire for N frames (aim first)
swap 1
edit 0: DIGGER, BURST_2, LIGHT_BULLET, _ , _
kick | interact | wait 60 | noop
```

Optional **assists** (recorded in the run header, default off for official tracks): `walk_to x y` (engine pathfinds on passable cells, like Claude's navigator), `admissible_actions` (engine lists currently valid one-shots), `hint` (task-provided natural-language hint). Assist-enabled runs go to a separate leaderboard track (lesson 5).

**RL vector action** (default `frame_skip=4`, i.e. one decision per 4 frames):

```
MultiDiscrete([3, 2, 2, A, 2, 2, 2, 5])
# move(3), jump(2), fly(2), aim bin (A=24 → 15° bins; or Box(2) continuous variant), fire(2), kick(2), interact(2), swap_wand (0 = none, 1..4)
```
`edit_wand` is exposed to RL only in tasks that require it, as a separate discrete head over a task-provided spell pool (`MultiDiscrete([pool_size+1] * capacity)` applied when `commit_edit=1`).

### 2.4 Observation schema — LLM mode (`obs.mode = "text"`)

Goal: ≤ ~2.5K tokens per decision, everything an expert human sees, nothing
privileged. Modelled on `nle-language-wrapper` sections (Stats / Inventory /
Observation / Message) and BALROG's Crafter wrapper (relative positions), plus
an ASCII map because our world is spatial at pixel scale.

```jsonc
{
  "frame": 1234, "t": 20.57,                       // 60 Hz
  "hud": {"hp": 84, "hp_max": 100, "levitation": 0.62, "mana": 230, "mana_max": 300,
          "gold": 12, "pos": [412, 1288], "vel": [0.0, 1.5], "depth": 1288,
          "on_ground": true, "in": "air", "burning": false, "wet": true,
          "active_wand": 0, "recharging": false, "cast_delay_left": 0},
  "map": {
    "origin": [316, 1224], "cell": 4, "w": 48, "h": 32,   // window = 192×128 px around player at 4 px/char
    "rows": ["############....................................", "..."],
    "legend": {"#": "rock", ".": "air", "~": "water", "L": "lava", "o": "oil", "s": "sand",
               "W": "wood", "c": "coal", "f": "fire", "%": "steam/smoke", "O": "obsidian",
               "a": "acid", "@": "you", "E": "enemy", "T": "target dummy", "P": "portal",
               "w": "wand", "$": "gold", "?": "unknown"},
    "near": {"cell": 1, "w": 24, "h": 16, "rows": ["..."]}   // optional 1 px/char inset around the player
  },
  "entities": [
    {"id": 17, "kind": "enemy", "name": "...", "pos": [460, 1270], "rel": [48, -18], "hp": 30, "hp_max": 30, "dist": 51},
    {"id": 21, "kind": "portal", "pos": [600, 1300], "rel": [188, 12], "dist": 188},
    {"id": 22, "kind": "wand_pickup", "pos": [...], "rel": [...]}
  ],
  "wands": [
    {"slot": 0, "active": true, "name": "wand", "stats": {"shuffle": false, "spells_per_cast": 1,
      "cast_delay_f": 10, "recharge_f": 30, "mana_max": 300, "mana_charge": 30,
      "capacity": 6, "spread_deg": 2.0, "always_cast": null},
     "spells": [{"slot": 0, "id": "DIGGER", "name": "Digging Bolt", "uses": null},
                {"slot": 1, "id": "LIGHT_BULLET", "name": "Spark Bolt", "uses": null}, {"slot": 2, "id": null}, ...]}
  ],
  "spell_pool": [{"id": "BURST_2", "name": "Double Spell", "count": 1, "type": "multicast",
                  "mana": 1, "cast_delay_f": 0, "recharge_f": 0, "damage": null}],   // task-provided loose spells, with stats
  "events": [{"frame": 1230, "type": "damage_taken", "amount": 6, "source": "fire"},
             {"frame": 1231, "type": "cast", "wand": 0, "spells": ["DIGGER"]},
             {"frame": 1232, "type": "invalid_action", "msg": "edit_wand: slot 7 exceeds capacity 6"}],
  "task": {"id": "cross_lava_pool@1", "objective": "Reach the portal on the far side of the lava without dying.",
           "progress": 0.42, "frames_left": 1366, "decisions_left": 38}
}
```

Rendering rules (deterministic, part of the task version):

- **Downsampling**: each char covers `cell×cell` pixels; the char is chosen by priority (player > entity > fire > liquid > powder > gas > solid > air) then by majority material within the block. The `near` inset is 1 px/char for precise digging/aiming.
- **Legend is fixed per `content_hash`** and sent in `reset.info` and in `info legend`; unknown/out-of-world cells are `?`.
- **Coordinates**: world pixels, y grows downward (depth = y); `rel` is `pos − player_pos`, so "rel [48, −18]" means 48 px right and 18 px up. The text façade can also emit BALROG-style sentences ("lava 12 px below you, 30 px wide") from the same data; both renderings are versioned.
- **Entities** sorted by distance, capped (default 16); the task may hide names (e.g. unknown enemies) but never hides the dummy/portal/goal.
- **Spell stats** are the wand-editor numbers (type, mana, cast delay, recharge, damage, spread, uses) — exactly what a human reads in the editor; no hidden oracle numbers.
- **History** is the client's job (BALROG keeps 16 text turns); the engine returns one observation per step and the last N events (default 32).

### 2.5 Observation schema — RL mode (`obs.mode = "grid"`)

```jsonc
{
  "frame": 1234,
  "grid": {"dtype": "uint8", "shape": [3, 128, 128], "codec": "zlib", "data": "<base64>"},
  // channel 0: material id (0 = air, 255 = unknown/out-of-world), 1 px per cell, centred on player
  // channel 1: flags bitfield (bit0 burning, bit1 wet, bit2 solid-static, bit3 passable, bit4 liquid, bit5 gas)
  // channel 2: entity class id (0 none, 1 player, 2 enemy, 3 projectile, 4 pickup, 5 portal, 6 dummy)
  "vec": {"dtype": "float32", "shape": [40], "data": "<base64>"},
  // hp/hp_max, mana/mana_max, levitation, vel/256, on_ground, in_liquid, burning, wet, recharging,
  // active wand stats (shuffle, spc, cast_delay/60, recharge/60, mana_max/1000, charge/100, capacity/26, spread/45),
  // task vector (e.g. goal rel x/y / 1024, progress, frames_left/limit) — layout published in `info actions`
  "spells": {"dtype": "uint16", "shape": [4, 26], "data": "<base64>"},   // spell id per wand slot (0 = empty)
  "rgb": {"dtype": "uint8", "shape": [64, 64, 3], "data": "<base64>"},   // optional, obs.rgb=true (nearest-filtered downsample)
  "task": {"progress": 0.42, "success": false}
}
```

Spaces are published by `info actions` as a JSON description the client turns into `gymnasium.spaces` (`Dict{grid: Box(0,255,(3,128,128),uint8), vec: Box(-inf,inf,(40,),f32), spells: Box(0,65535,(4,26),uint16)}`). Window size, downsample factor and channel set are `reset.config.obs` parameters and are part of the recorded run header. Reward in grid mode defaults to the task's shaped reward (`reward_mode: "shaped"|"sparse"`); sparse = score delta.

### 2.6 Python client

```python
import noita_bench as nb
env = nb.Env(task="dig_to_depth@1", obs="grid", seed=0, binary="target/release/noita_bench")  # gymnasium.Env
obs, info = env.reset(seed=0, options={"task": "dig_to_depth@1"})
obs, r, term, trunc, info = env.step(action)        # MultiDiscrete action, frame_skip from config
text_env = nb.TextEnv(task="wand_dps_optimization@1", seed=3, max_frames_per_decision=120)
obs_text = text_env.reset()                          # str (rendered JSON or prose template)
obs_text, done, info = text_env.act("aim -20; cast 30")   # parses grammar; invalid → error text, no frames consumed
nb.run(agent, task_list, seeds, out_dir="runs/...")  # writes run.jsonl + metrics.json + verify-able log
```

Vectorisation: N subprocesses, one per env (`nb.VectorEnv`), which also
gives thread-count-independent determinism per env. Sticky-action and
seed-sampling wrappers live here, not in the engine.

---

## 3. Proposed task suite (v1)

Conventions shared by all tasks:

- Episode score ∈ [0, 1]; `success` is a boolean; partial credit is monotone in progress and **cannot increase by dying or ending early** (lesson 3).
- Limits: `frame_limit` (60 Hz sim frames) and `decision_limit` (agent calls). Hitting either sets `truncated=true` and scores the partial credit.
- Seeds: each task has `public_seeds` (20, listed in `seeds/public-v1.json`) and `hidden_seeds` (20, held by maintainers; rotated per suite version). Episode generator seed = `blake3(task_id ‖ task_version ‖ seed_index)`.
- Tiers: `fixed` (one hand-authored map, tutorial / smoke test), `procedural` (seeded variants), `hidden`.
- Suite score = mean over tasks of mean over seeds; also report per-task success rate and a Crafter-style geometric mean `exp(mean ln(1+100·sr)) − 1` so hard tasks matter. Efficiency (`frames_to_success / frame_limit` on successes), decisions, tokens, wall-clock and USD cost are reported separately, never folded into the primary score.
- World for benchmark tasks: 512×512 cells (PRD R1 performance target), player spawned at a task-defined position, deterministic enemy AI.
- Spell ids below are illustrative; canonical ids/stats come from `research/spells.json` (wand/spell research deliverable).

| # | Task id | Family | Inputs (seeded) | Start loadout | Success | Partial credit | Limits (frames / decisions) | Difficulty knobs | Anti-exploit notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `dig_to_depth@1` | terrain manipulation | strata of rock / soft soil / sand with occasional water pockets; target depth `D` below spawn; no enemies | wand A: `DIGGER` (digging bolt) ×1; capacity 3, mana 200 | player `y − y0 ≥ D` while alive | `clamp(max_depth_reached / D, 0, 1)` (max over episode, so dying later cannot reduce it; dying before D caps credit at the depth reached) | 3600 / 60 | D ∈ {256, 512, 1024}; `hard` adds lava pockets and a 20% coal/oil vein density | depth measured from a fixed spawn; falling counts (it is a legitimate strategy); no credit for depth reached by being pushed outside the world (clamped to world bounds) |
| 2 | `cross_lava_pool@1` | hazard traversal | flat corridor with a lava pool of width `W` and depth 24 px between a start ledge and a portal; ceiling height 64 px | wand: `MATERIAL_WATER` (water spawner, 10 uses) + levitation meter 1.0 s; `hard`: water only | player touches portal with hp > 0 | `0.6 · (horizontal progress toward portal / total distance)` + `0.4 · success`; progress = max over episode of `x`-advance clamped to [0,1]; death freezes progress | 1800 / 40 | W ∈ {48, 96, 160}; `medium` adds a 2-cell-thick obsidian crust option (water on lava) | portal is indestructible and non-pushable; touching lava deals ≥ 10 hp/s so hovering strategies need levitation management; obsidian bridge (water→lava reaction) is the intended "chemistry" solution |
| 3 | `extinguish_fire@1` | reaction control | a burning oil pool (`F0` burning cells) beneath a wooden scaffold; fire spreads along wood at the material table's rate | wand: `MATERIAL_WATER` ×∞ (mana-limited) or `SEA_WATER`-class area water in `easy` | zero burning cells for 120 consecutive frames before the limit **and** wood burned ≤ 25% | `0.7 · (1 − burning_at_end / F0)` + `0.3 · (1 − wood_burned_fraction)` ; success → 1.0 | 2400 / 50 | F0 ∈ {40, 120, 300} cells; scaffold wood cells 400–2000 | no credit for removing fire by letting everything burn: the wood term caps it; steam from water+lava not present here; water must reach the fire (no "erase" debug ops) |
| 4 | `kill_targets@1` | combat / aiming | `N` target dummies (hp 100 each) at seeded positions (some behind 1–4 px thin rock, some airborne), optional `N_e` enemies that approach | wand: `LIGHT_BULLET` ×2 + `DIGGER`; `hard`: enemies shoot back | all N dummies destroyed, player alive | `killed / N` (+ `0` for enemies); success → 1.0 | 3600 / 60 | N ∈ {3, 6, 10}; N_e ∈ {0, 2, 4}; line-of-sight blockers | dummies are static and do not regenerate; friendly fire of walls is expected; killing yourself ends the episode with current partial credit |
| 5 | `survive_N_seconds@1` | survival | arena 256×192 with 3 entry tunnels; enemy waves every 10 s (seeded composition) ; a water pool and oil pool in the arena | wand: `LIGHT_BULLET` ×2, `BURST_2`; 1 health potion equivalent (`hp_max` 100) | alive at frame `N·60` | `frames_survived / (N·60)` | N·60 / N·2 (e.g. 60 s → 3600 / 120) | N ∈ {30, 60, 120}; wave size 2→6 | since reward is time alive, no early-termination exploit exists; hiding inside dug rock is legitimate but enemies dig/explode in `hard` |
| 6 | `wand_dps_optimization@1` | wand building (optimisation) | wand stats fixed (`spells_per_cast`, `cast_delay_f`, `recharge_f`, `mana_max`, `mana_charge`, `capacity` seeded from ranges); spell pool of `P` loose spells with counts (projectiles, modifiers, multicasts, triggers); a target dummy at 96 px with infinite hp; `T` = 600 frames of auto-fire per trial | the wand (empty) + pool; `max_wand_edits = 5` | `damage_dealt_best_trial ≥ 0.9 · reference_damage` | `clamp(damage_dealt_best / reference_damage, 0, 1)`; reference = best of (exhaustive search when `P ≤ 8` and `capacity ≤ 6`, else a fixed heuristic search budget of 20,000 evaluations run offline per seed and stored with the seed) | 5 trials × 600 + 600 slack = 3600 / 20 | P ∈ {5, 8, 12}; capacity 3–8; shuffle on/off; mana-limited vs recharge-limited regimes; `hard` requires a trigger payload to reach a dummy behind cover | `edit_wand` then `cast 600` is scripted by the harness after each `commit`; the reference is computed by the harness with the same engine and never exposed; score uses the **best** trial so later worse trials cannot hurt; damage counted only on the dummy (self-damage ignored) |
| 7 | `reach_portal@1` | navigation | cave system generated from seed with vertical shafts, water sumps and one guaranteed passable route; portal 300–600 px away (geodesic) | levitation meter 1.0 s; wand with `DIGGER` in `easy` only | player touches portal | `1 − d_final / d_0` where `d` = geodesic distance over passable cells (BFS on `passable` flag, recomputed at episode end) ; success → 1.0 | 5400 / 90 | route length; number of water sumps; `hard` has no digging and requires levitation timing | geodesic (not Euclidean) distance so digging shortcuts count when allowed; portal indestructible; `d_final` uses the player's last alive position |
| 8 | `chain_reaction@1` | reaction planning | an oil pool `O` cells (seeded shape) at the bottom of a chamber; a wooden structure `Wd` cells above it, not directly reachable by the fire spell (ceiling/rock lip blocks direct line); a narrow gap connects the pool to the structure | wand: `FIREBALL`-class short-range fire projectile ×∞ (mana-limited), range < distance to wood | ≥ `X = 60%` of `Wd` burned within the limit | `clamp(wood_burned_fraction / X, 0, 1)` | 3600 / 40 | pool/structure geometry; oil quantity (burn duration); `hard` requires moving oil (dig a channel) before igniting | wood is unreachable by direct fire by construction (verified by the generator with a ray test); burned fraction is monotone; igniting yourself is allowed but hp loss ends the episode early |
| 9 | `obsidian_bridge@1` (stretch) | chemistry + traversal | lava channel of width 64 px; water available only from a pool 40 px behind the player (must be carried via `MATERIAL_WATER` cast or dug channel) | wand: `DIGGER`; no water spell | reach portal | as task 2 | 2400 / 50 | — | tests the water+lava→obsidian+steam rule from PRD R1 |
| 10 | `collect_gold@1` (stretch) | exploration | `G` gold nuggets embedded in rock at seeded positions within 160 px | wand: `DIGGER` | collect all | `collected / G` | 3600 / 60 | G ∈ {5, 10} | nuggets do not respawn |

Scripted-agent baselines (PRD acceptance: "every task … with a scripted (non-AI) agent") should include, per task, (a) a random agent, (b) a no-op agent, (c) a hand-written heuristic that reaches `success` on the `fixed` tier — the three give the floor, the "dying-early" check and the ceiling sanity check respectively.

Suggested capability tags per task (SmartPlay / TextArena style, used for analysis not scoring): spatial reasoning (1,2,4,7,8), physics/chemistry knowledge (2,3,8,9), planning (6,7,8), reactivity/timing (4,5), optimisation/search (6), resource management (3,5).

---

## 4. Determinism and replay requirements

### 4.1 Requirements (testable)

| ID | Requirement | Test |
|---|---|---|
| D1 | Fixed timestep: 60 Hz; no wall-clock reads anywhere in `noita_core` | grep-gate in CI for `Instant`/`SystemTime` in core; moon-phase-style effects derive from seed (NLE `fix_moon_phase` lesson) |
| D2 | `(engine_version, content_hash, task@version, seed, action_log)` ⇒ bit-identical state and `state_hash` sequence | run twice, compare all hashes (PRD: 3,000 frames) |
| D3 | Thread-count independence: 1 vs 8 worker threads give identical hashes | CI runs the same log with `--threads 1` and `--threads 8` |
| D4 | Platform independence: macOS arm64 and Linux x86_64 produce identical hashes for golden logs | golden `expected_hashes.json` per task version checked in CI on both runners |
| D5 | RNG: seeded PCG/xoshiro (`rand_pcg` / `rand_xoshiro`), **separate streams per subsystem** derived as `stream_seed = blake3(seed ‖ "worldgen"|"cells"|"spells"|"ai"|"spawn")`, and per-chunk cell streams `blake3(seed ‖ frame ‖ chunk_id)` so that scheduling order cannot change results | unit test: adding an RNG call in `spells` does not change `worldgen` output |
| D6 | No iteration over `HashMap`/`HashSet` in simulation paths (`Vec`, `BTreeMap`, `IndexMap` with explicit sort); entity ids monotonic; cross-chunk cell moves resolved in a deterministic commit phase (checkerboard chunk phases) | clippy lint `disallowed_types` for `std::collections::HashMap` in `noita_core` |
| D7 | Floating point: integer/fixed-point for the cell automaton; `f32` allowed for projectiles/entities but transcendental functions only via the vendored `libm` crate or lookup tables (std `f32::sin/cos/exp/powf` are platform-dependent); no `fast-math`, no non-deterministic SIMD reductions; build with the same `target-cpu` policy as release | cross-platform golden hashes (D4) catch drift |
| D8 | Action log: JSONL with a header line `{engine_version, engine_git, content_hash, protocol_version, task, task_version, seed, config, dev_mode, started_at}` followed by every `reset`/`step`/one-shot request verbatim plus the returned `frame` and `state_hash` | `replay` reproduces the log |
| D9 | State hash: blake3 over a canonical serialisation of (frame counter, all RNG states, every active chunk's cells (material id + flags + colour variant), entity list sorted by id (type, pos, vel, hp, timers, wand/spell state), player state, task state); per-chunk Merkle leaves so cost scales with dirty chunks; a full-grid hash every 600 frames and at episode end; `episode_hash = blake3(concat(step_hashes))` | hashing a 512×512 grid is ~0.3 MB → sub-millisecond with blake3 SIMD |
| D10 | Replay verification tool: `noita_bench verify run.jsonl` → re-executes, compares each step hash, recomputes score, writes `verify.json {verified, first_divergence:{frame,expected,got}, score, score_claimed}`; in `--dev` mode dumps per-entity/per-chunk diffs at the first divergent frame (Age of Empires "sync log" practice) | integration test with a deliberately corrupted log |
| D11 | Stochastic wrappers (sticky actions, random frame skip) live in the Python client with their own seed and are recorded in the header | the engine log alone is sufficient to replay |

### 4.2 Seeds

- Public seed indices `0..19` per task version; hidden indices `20..39` map through a maintainer-held salt: `hidden_seed = blake3(salt ‖ task_id ‖ version ‖ index)`; the salt rotates with the suite version so published results stay reproducible for that version.
- A raw `u64` seed is also accepted (`reset.seed = {"raw": 12345}`) for research use; such runs are marked `seed_kind: "raw"` and are not leaderboard-eligible.

### 4.3 Real-time track (optional, v2)

`reset.config.realtime = {budget_ms: 500, on_timeout: "repeat"|"noop"}`: the engine advances `frame_skip` frames every `budget_ms` of wall-clock and auto-fills missing decisions. The *simulation* stays deterministic given the resulting action log (timeouts become explicit `repeat`/`noop` entries), so replays still verify; only the mapping from wall-clock to actions is non-reproducible. Mirrors VideoGameBench real-time vs Lite and PokéAgent's latency-as-cost.

---

## 5. Anti-cheat and validation

1. **Submission = action log.** A leaderboard entry is `run.jsonl` (header + requests + hashes) plus `metrics.json`. The validator replays it on the reference engine build (same `engine_git` + `content_hash`), compares hashes and recomputes scores; any divergence or score mismatch invalidates the run (NetHack Challenge, Lux replay, SWE-bench logs).
2. **Hidden seeds and secret tasks.** Official evaluation uses hidden seeds (§4.2); each suite release adds at least one new task whose generator is published only after the next release (VideoGameBench secret games; GVGAI-LLM "infinite games" idea).
3. **Dev-mode fence.** `save_state`, `load_state`, `debug *` and privileged observations exist only with `--dev`; the header records `dev_mode: true` and such runs are rejected by the validator. The engine binary refuses these commands otherwise (`DEV_ONLY` error) — no "just don't use it" conventions (MineDojo-style privileged obs is opt-in and recorded).
4. **No privileged information in observations.** The agent sees only the windowed map, listed entities, the wand editor numbers and events. Oracle values (e.g. the `wand_dps_optimization` reference damage, hidden-cell contents, enemy internals) never leave the harness. Crafter's `info['semantic']` mistake (privileged data in `info` the agent "is forbidden to observe") is avoided by keeping privileged data out of the protocol entirely unless `--dev`.
5. **Assists and modality are run attributes.** `assists`, `obs.mode`, `obs.radius`, `max_frames_per_decision`, `frame_skip` are in the header; leaderboards are partitioned by (`obs.mode`, `assists`, `realtime`) so a pathfinding-assisted LLM run is never ranked against an unassisted one (Claude/Gemini lesson; lmgame `harness_mode`; Crafter external-knowledge rows).
6. **Cost is reported, not hidden.** `metrics.json` carries decisions, frames, invalid actions, wall-clock, tokens in/out and estimated USD (PokéAgent practice). Leaderboard shows them next to the score.
7. **Task text cannot leak solutions.** Objectives are declarative ("reach the portal"); hints are an assist. Generators are reviewed for "solution in the prompt" (SWE-bench+ 32.67% leakage lesson) and for weak success checks (31.08% weak tests lesson): every task has negative tests — scripted degenerate agents (die immediately, stand still, spam actions, self-kill after partial progress) must score ≤ the documented floor.
8. **Early termination is never rewarded.** All partial-credit formulas are maxima over the episode of monotone progress; `terminated` by death yields the progress at death; there is no time bonus in the primary score (NetHack Challenge lesson).
9. **Frame/decision caps are enforced engine-side**, including `max_frames_per_decision`, so a client cannot fast-forward past hazards.
10. **Reproducibility of the evaluation harness itself.** Reference evaluations run in a pinned container (`Dockerfile` with the exact Rust toolchain and the engine git hash); results are cached by `(engine_git, content_hash, task@version, seed, log_hash)` — never by a user-supplied `run_id` alone (SWE-bench cache pitfall).
11. **Multiple seeds and reported variance.** Minimum 10 seeds per task for a leaderboard entry (BALROG uses 5–10 per task and reports standard error; lmgame found prompt variance larger than ±1 SD), mean ± standard error published.
12. **Contamination posture.** The game is new and has no walkthroughs online, so text-level contamination is low initially; as the repo and results spread, mitigation is hidden seeds, new tasks per release and paraphrased objective templates (lmgame entity-masking lesson).

---

## 6. Versioning tasks

| Thing | Identifier | Bump rule | Compatibility |
|---|---|---|---|
| Protocol | `protocol_version` semver (`1.0.0`) | major: incompatible message change; minor: new optional fields/commands; patch: docs | client checks major; `hello` advertises `capabilities` |
| Engine | `engine_version` semver + `engine_git` | any change that alters any golden `state_hash` → **minor** bump at least; pure performance/refactor with identical hashes → patch | golden-hash CI gate (D4) decides which bump is required |
| Content | `content_hash` = blake3 of `materials.json` + `spells.json` + task generator sources | changes are recorded in `CHANGELOG.md` with the hash | runs are only comparable at equal `content_hash` |
| Task | `task_id@N` (e.g. `dig_to_depth@1`), Gym-style | generator, loadout, limits, scoring or observation-rendering change → new `@N`; old version stays runnable (frozen generator module `tasks/dig_to_depth/v1.rs`) for at least one suite release, then deprecated with a notice | leaderboard rows carry `task@N` |
| Suite | `suite-vX` = pinned list of `task@N` + public/hidden seed lists + engine/content hashes | each release: add tasks, rotate hidden salt, re-run baselines (random / no-op / heuristic / reference LLM & RL agents) | results tables are per suite version |
| Seeds | `seeds/public-v1.json`, hidden salt per suite | never reuse a hidden index across suites | — |
| Golden replays | `golden/<task@N>/<seed>.jsonl` + `expected_hashes.json` + expected scores | updated only together with a version bump; CI fails otherwise | doubles as regression tests for the physics and spell systems |
| Known issues | `KNOWN_ISSUES.md` per task version (Procgen's `jumper` ~7% note; Craftax v1.5.0/v1.6.0 reward notes) | document instead of silently fixing within a version | — |

Run header (written by the engine, first line of `run.jsonl`):

```json
{"kind":"header","protocol_version":"1.0.0","engine_version":"0.3.1","engine_git":"a1b2c3d",
 "content_hash":"blake3:…","suite":"suite-v1","task":"cross_lava_pool","task_version":1,
 "seed":{"kind":"public","index":7},"config":{"obs":{"mode":"text","cell":4,"w":48,"h":32,"near":true},
 "assists":{},"frame_skip":4,"max_frames_per_decision":120,"realtime":null},"dev_mode":false,
 "agent":{"name":"my-agent","model":"…","harness_git":"…"},"started_at":"2026-10-07T12:00:00Z"}
```

---

## 7. Open questions for the implementation task

1. Whether `aim` should be quantised in text mode (integer degrees) to keep action logs small and the RL/LLM action spaces aligned — recommended: integer degrees in text, 24-bin or continuous in RL, both logged as `f32` degrees.
2. Hash cadence: every step (default) vs every N frames; every step is cheap with per-chunk Merkle leaves and gives exact divergence frames.
3. Whether the `near` inset should be on by default for LLMs (costs ~400 tokens); recommended on for digging/aiming tasks (1, 4, 6, 8), off for navigation (7).
4. The exact shaped-reward definitions for RL mode per task (sparse score delta is the safe default; shaping terms must be documented per task version because they change hashes of nothing but affect learning).

---

## Sources

Primary sources fetched 2026-10-07 (raw copies in `research/raw/` where noted):

- NLE README — https://github.com/NetHack-LE/nle and https://raw.githubusercontent.com/NetHack-LE/nle/main/README.md (`raw/nle_README.md`)
- NLE environment source: https://raw.githubusercontent.com/NetHack-LE/nle/main/nle/env/base.py (`raw/nle_env_base.py`), https://raw.githubusercontent.com/NetHack-LE/nle/main/nle/env/tasks.py (`raw/nle_env_tasks.py`)
- NLE paper (abstract page): https://arxiv.org/abs/2006.13760
- NeurIPS 2021 NetHack Challenge report: https://arxiv.org/pdf/2203.11889 (`raw/nethack_challenge_2021_report.txt`)
- NLE language wrapper: https://raw.githubusercontent.com/ngoodger/nle-language-wrapper/main/README.md (`raw/nle_language_wrapper_README.md`)
- MiniHack: https://raw.githubusercontent.com/facebookresearch/minihack/main/README.md (`raw/minihack_README.md`), paper https://arxiv.org/pdf/2109.13202
- BALROG: https://github.com/balrog-ai/BALROG ; https://raw.githubusercontent.com/balrog-ai/BALROG/main/README.md (`raw/balrog_README.md`); https://raw.githubusercontent.com/balrog-ai/BALROG/main/docs/evaluation.md (`raw/balrog_evaluation.md`); https://raw.githubusercontent.com/balrog-ai/BALROG/main/balrog/config/config.yaml (`raw/balrog_config.yaml`); https://raw.githubusercontent.com/balrog-ai/BALROG/main/balrog/environments/crafter/__init__.py (`raw/balrog_crafter_init.py`); paper https://arxiv.org/abs/2411.13543 , https://arxiv.org/html/2411.13543 , https://arxiv.org/html/2411.13543v1 (`raw/balrog_paper.html`, `raw/balrog_paper.txt`); leaderboard https://balrogai.com/
- Crafter: https://github.com/danijar/crafter ; https://raw.githubusercontent.com/danijar/crafter/main/README.md (`raw/crafter_README.md`); https://raw.githubusercontent.com/danijar/crafter/main/crafter/data.yaml (`raw/crafter_data.yaml`); https://raw.githubusercontent.com/danijar/crafter/main/crafter/env.py (`raw/crafter_env.py`); paper https://arxiv.org/pdf/2109.06780 (`raw/crafter_paper.txt`)
- Craftax: https://raw.githubusercontent.com/MichaelTMatthews/Craftax/main/README.md (`raw/craftax_README.md`); paper https://arxiv.org/html/2402.16801
- MineRL: https://github.com/minerllabs/minerl ; https://raw.githubusercontent.com/minerllabs/minerl/dev/README.md (`raw/minerl_README.md`); https://minerl.readthedocs.io/en/v0.4.4/environments/index.html (`raw/minerl_envs_v044.html`)
- MineDojo: https://github.com/MineDojo/MineDojo ; https://raw.githubusercontent.com/MineDojo/MineDojo/main/README.md (`raw/minedojo_README.md`); https://docs.minedojo.org/sections/core_api/action_space.html ; https://docs.minedojo.org/sections/core_api/obs_space.html
- TextWorld: https://github.com/microsoft/TextWorld ; https://raw.githubusercontent.com/microsoft/TextWorld/main/README.md (`raw/textworld_README.md`); https://textworld.readthedocs.io/en/stable/textworld.html
- TextArena: https://github.com/LeonGuertler/TextArena ; https://raw.githubusercontent.com/LeonGuertler/TextArena/main/README.md (`raw/textarena_README.md`); paper https://arxiv.org/abs/2504.11442 , https://arxiv.org/html/2504.11442
- SmartPlay: https://arxiv.org/abs/2310.01557 , https://arxiv.org/html/2310.01557
- lmgame-Bench: https://arxiv.org/abs/2505.15146 , https://arxiv.org/html/2505.15146 ; https://raw.githubusercontent.com/lmgame-org/GamingAgent/main/README.md (`raw/lmgame_README.md`)
- VideoGameBench: https://arxiv.org/abs/2505.18134 , https://arxiv.org/html/2505.18134 ; https://raw.githubusercontent.com/alexzhang13/videogamebench/main/README.md (`raw/videogamebench_README.md`)
- Orak: https://arxiv.org/abs/2506.03610 , https://arxiv.org/html/2506.03610v2
- PokéAgent Challenge: https://arxiv.org/abs/2603.15563 , https://arxiv.org/html/2603.15563 ; harness repo https://raw.githubusercontent.com/sethkarten/pokeagent-speedrun/main/README.md (`raw/pokeagent_README.md`)
- Pokémon LLM Agent Benchmark (community): https://raw.githubusercontent.com/CalebDeLeeuwMisfits/PokemonLLMAgentBenchmark/main/README.md (`raw/pokemon_llm_bench_README.md`)
- Claude Plays Pokémon analysis: https://www.greaterwrong.com/posts/HyD3khBjnBhvsp8Gb/so-how-well-is-claude-playing-pokemon
- Gemini Plays Pokémon run facts: https://www.lesswrong.com/posts/ekF2EDwKyZJNuxBTb/julian-bradshaw-s-shortform
- Factorio Learning Environment: https://arxiv.org/abs/2503.09617 , https://arxiv.org/html/2503.09617 ; https://raw.githubusercontent.com/JackHopkins/factorio-learning-environment/main/README.md (`raw/fle_README.md`)
- Procgen: https://arxiv.org/pdf/1912.01588 (`raw/procgen_paper.txt`); https://raw.githubusercontent.com/openai/procgen/master/README.md (`raw/procgen_README.md`)
- ALE revisited (sticky actions): https://arxiv.org/abs/1709.06009
- Gymnasium Env API: https://gymnasium.farama.org/api/env/
- PettingZoo AEC API: https://pettingzoo.farama.org/api/aec/
- SWE-bench: https://github.com/SWE-bench/SWE-bench ; https://raw.githubusercontent.com/SWE-bench/SWE-bench/main/README.md (`raw/swebench_README.md`); SWE-bench+ https://arxiv.org/abs/2410.06992 ; Epoch AI SWE-bench Verified notes https://epoch.ai/benchmarks/swe-bench-verified ; SWE-bench Verified summary (OpenAI page returned HTTP 403; numbers taken from the W&B report) https://wandb.ai/byyoung3/ml-news/reports/OpenAI-Releases-SWE-bench-Verified--Vmlldzo5MDI3NzU0
- Lux AI Challenge S3: https://raw.githubusercontent.com/Lux-AI-Challenge/Lux-Design-S3/main/README.md (`raw/luxai_s3_README.md`); https://raw.githubusercontent.com/Lux-AI-Challenge/Lux-Design-S3/main/docs/specs.md (`raw/luxai_s3_specs.md`); https://raw.githubusercontent.com/Lux-AI-Challenge/Lux-Design-S3/main/kits/README.md (`raw/luxai_s3_kits_README.md`); https://raw.githubusercontent.com/Lux-AI-Challenge/Lux-Design-S3/main/kits/python/README.md (`raw/luxai_s3_kit_python_README.md`)
- Deterministic lockstep / OOS checksums: https://www.gamedeveloper.com/programming/1500-archers-on-a-28-8-network-programming-in-age-of-empires-and-beyond
- Search-only (not fetched in full; used for the "Lightning Gym" negative result and GVGAI-LLM mention): https://arxiv.org/pdf/2508.08501 (GVGAI-LLM), https://noita.wiki.gg/wiki/Falling_Sand_Game
