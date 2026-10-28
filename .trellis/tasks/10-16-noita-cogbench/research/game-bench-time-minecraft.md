# Research: How Minecraft-based agent benchmarks relate game time to agent decisions

- **Query**: How do existing Minecraft-based agent systems/benchmarks handle Minecraft's 20 TPS tick, and where do the AI's decisions sit relative to game time? (clock, action granularity, duration/interruption, decisions per episode, sources)
- **Scope**: external (papers, official docs, actual repo source files)
- **Date**: 2026-10-25
- **Evidence convention**: `[code]` = read from repo source at the cited path/line (default branch head on 2026-10-25); `[paper]` = paper text; `[docs]` = official docs; `[wiki]` = minecraft.wiki; `[inference]` = my reading of the evidence, not stated by the source; `UNVERIFIED` = not confirmed.
  Line numbers refer to the raw file as fetched on 2026-10-25 and can drift.
  Note: the GitHub REST API was rate-limited (403), so repo paths were checked by fetching `raw.githubusercontent.com` URLs directly (HTTP 200), not by directory listing.

---

## 0. Pattern summary (read this first)

Two families exist, and they answer "where does the decision sit relative to game time" in opposite ways.

1. **Lock-step / synchronous**: the world advances only when the agent calls `step`. The agent may take any wall-clock time to think. One step = one tick (or a fixed N ticks).
   Examples: MineRL / BASALT, MineDojo, VPT-style env used by STEVE-1 / JARVIS-1 / GITM / DEPS, Crafter, MineLand with `ticks_per_step` + `enable_auto_pause`.
2. **Real-time / asynchronous (with a pause hack or without)**: the server keeps ticking at 20 TPS; the agent issues high-level commands or whole programs that run for many seconds.
   - Voyager: the server is paused by a mod only while GPT-4 is thinking, then un-paused for the duration of each program.
   - Mindcraft / MineCollab: no pausing at all. An LLM call is wall-clock time in which the world keeps running, and a 300 ms reflex loop ("modes") can pre-empt actions.
   - Malmo (classic API): real-time server, agent polls asynchronously.

Action granularity follows the clock model:
- Lock-step systems use 1-tick, low-level input (keys + mouse delta) or a tiny fixed menu.
- Real-time LLM systems use macro commands (`!collectBlocks`) or generated programs that run seconds to minutes.
- Hierarchical systems (STEVE-1 / JARVIS-1 / DEPS / GITM) put an LLM planner at event granularity (plan start, failure) above a 20 Hz policy.

Reflexes: the LLM-in-real-time systems either have none (Voyager, except stuck-teleport) or hard-code them outside the LLM (Mindcraft modes). Lock-step systems rely on the policy itself (or, in Crafter, an engine rule that wakes a sleeping player when hurt).

---

## 1. Minecraft itself (Java Edition)

**Q1 Clock**
- The server game loop runs at a fixed 20 ticks/s = 50 ms/tick; an in-game day is 24,000 ticks (20 min). If the machine can't keep up, TPS drops and everything tick-based slows ("the vast majority of actions are timed based on tick count rather than on real time"). [wiki: https://minecraft.wiki/w/Tick, section "Game tick"]
- `/tick` (added in Java 1.20.3, snapshot 23w43a; `<time>` made optional in 23w44a; permission level 3; cannot be run from a command block). [wiki: https://minecraft.wiki/w/Commands/tick]
  - `tick rate <rate>`: set target TPS, float in [1.0, 10000.0], default 20.0. The game "still expects a constant tick rate of 20.0", so this scales relative game speed.
  - `tick freeze` / `tick unfreeze`: freezing stops ticking of "all gameplay elements ... except players and any entity a player is riding".
  - `tick step [<time>]`: unfreeze, run for `<time>` (default 1 gametick; units `t`, `s`=20 ticks, `d`=24000 ticks), then re-freeze. Only works while frozen. `tick step stop` aborts.
  - `tick sprint [<time>]`: run as fast as possible for `<time>` (+1) ticks, ignoring the target rate, then restore the previous status. `tick sprint stop` aborts.
  - `tick query`: target rate plus average/percentile ms per tick.
- `[inference]` Because players are still ticked while frozen, `/tick freeze` alone does not give a strict lock-step for a bot-controlled player. Benchmarks that need strict lock-step (MineRL, MineDojo, VPT) patch client and server instead (see sections 3, 4, 7a).

**Q2 Action granularity**: The game has no "action" abstraction. A human player supplies continuous input (keys held, mouse movement, clicks) every client tick. MineRL's dataset records "all of the keyboard presses on the client, the change in view pitch and yaw ..., all player GUI click and interaction events, chat messages sent, and agglomerative actions such as item crafting" sampled at every game tick, 20 per second. [paper: MineRL, arXiv 1907.13440, dataset section]

**Q3 Duration / interruption / reflex**: Not applicable at engine level. Damage, mob AI and hunger tick regardless of what the agent is doing. The only built-in "reflexes" are the ones a human has to supply.

**Q4 Decisions per episode**: N/A.

**Q5 Sources**
- https://minecraft.wiki/w/Tick
- https://minecraft.wiki/w/Commands/tick
- https://arxiv.org/abs/1907.13440

---

## 2. Project Malmo (Microsoft)

**Q1 Clock**
- The classic Malmo API is **asynchronous and real-time by default**. The Minecraft server ticks on its own. The Python agent starts a mission, then polls `agent_host.getWorldState()` in a `time.sleep(0.1)` loop and sends commands whenever it wants. [code: `Malmo/samples/Python_examples/tutorial_1.py` lines ~60-85]
- `ModSettings/MsPerTick` (int >= 1): "This sets the delay that Minecraft uses between world ticks, in milliseconds. The default is 50ms per tick (20Hz). Double-speed would be 25ms/tick (40Hz)." Its stated purpose is to "overclock Minecraft - to make Minecraft time run faster than normal". It is a global run-speed knob, not a synchronization mechanism. `PrioritiseOffscreenRendering` (boolean) is the companion option to raise frame rate. [docs: https://microsoft.github.io/malmo/0.30.0/Schemas/Mission.html, element `ModSettings`]
- Observation rate is expressed in ticks: `update_frequency` "is measured in Minecraft world ticks ... A value of 20, under normal Minecraft running conditions ... would return the entity list once per second". [docs: MissionHandlers.html, `ObservationFromNearbyEntities`]
- **Multi-agent turn scheduler** (only synchronization feature found): `<TurnBasedCommands>` wrapping a command handler means "each agent must take it in turns to send a discrete movement command"; the mod then adds `turn_number` and a one-shot `turn_key` that must be passed back in `sendCommand`. `UpdateSpeed` of some decorators can be `"turnbased"`. [docs: MissionHandlers.html, `TurnBasedCommands`, `ObservationFromTurnScheduler`]
- **MalmoEnv (gym-style wrapper)**: `env.step(action)` sends `<StepN>action</StepN>` over a socket, then blocks until the mod returns the latest video frame, reward, done flag and optional JSON info. [code: `MalmoEnv/malmoenv/core.py` `step`, lines 304-351]
  - On the Java side the frame buffer holds only the newest frame: `envState.obs = frame; // Replaces current.` (`MalmoEnvServer.java:727-733`).
  - Waits are bounded by `COND_WAIT_SECONDS = 3` (line 83).
  - `[inference]` A MalmoEnv step is therefore paced by "next rendered frame", not by a tick count, and intermediate frames can be dropped. I found no code in these files that freezes the server between steps. The strict `StepClient/StepServer` lock-step appears later in MineRL/MineDojo (sections 3-4).

**Q2 Action granularity**: Text commands per agent, in several families. [docs: MissionHandlers.html]
- Continuous (smooth): `move 0.5`, `turn 0.1`, `jump 1`, `attack 1` ... "start moving forward at 50% speed"; the effect persists until the agent sends `0`/another value.
- Discrete: `movenorth 1`, `move 1` (one block), `turn 1` (90 degrees), `attack 1`. Implemented as an immediate displacement inside the handler (`player.move(...)` followed by `player.onUpdate()`), so it resolves within the processing tick rather than as a multi-tick walk. [code: `Minecraft/.../MissionHandlers/DiscreteMovementCommandsImplementation.java` ~L470-500; `[inference]` on the "one tick" reading.]
- Absolute (`tp x y z`, `setYaw`), inventory, chat, and "simple craft" commands.

**Q3 Duration / interruption / reflex**
- Continuous commands run until the agent changes them. Discrete commands finish immediately. There is no automatic reflex; danger handling is entirely the agent's job.
- Mission-level limits: `ServerQuitFromTimeUp` (a time limit "that applies to all agents", in ms), `AgentQuitFromReachingCommandQuota` (ends the mission once a command-count quota is exceeded; groups of commands can share a quota), `ServerQuitWhenAnyAgentFinishes`. [docs: MissionHandlers.html]

**Q4 Decisions per episode**: Not specified by the platform (mission-dependent). Quotas can cap command counts.

**Q5 Sources**
- https://microsoft.github.io/malmo/0.30.0/Schemas/Mission.html
- https://microsoft.github.io/malmo/0.30.0/Schemas/MissionHandlers.html
- https://github.com/microsoft/malmo/blob/master/MalmoEnv/malmoenv/core.py
- https://github.com/microsoft/malmo/blob/master/Minecraft/src/main/java/com/microsoft/Malmo/Client/MalmoEnvServer.java
- https://github.com/microsoft/malmo/blob/master/Minecraft/src/main/java/com/microsoft/Malmo/MissionHandlers/DiscreteMovementCommandsImplementation.java
- https://github.com/microsoft/malmo/blob/master/Malmo/samples/Python_examples/tutorial_1.py

---

## 3. MineRL (incl. BASALT and ObtainDiamond competitions)

Source branch examined: `minerllabs/minerl` `dev` (the 1.x line; docs title "MineRL 0.4.0 documentation" is the readthedocs "latest" page). I did not read the Java side.

**Q1 Clock**
- **Synchronous, one tick per `env.step`.**
  - `_multiagent.py` `step()` sends `<StepClient{N}>action</StepClient{N} >` to each agent's client, receives obs/reward/done, then sends `<StepServer></StepServer>` with the comment `# STEP THE SERVER!`. [code: `minerl/env/_multiagent.py` lines 273-351; `_singleagent.py` wraps it]
  - Mission init token includes a `synchronous` flag set to true: `+ str(True).lower()  # synchronous` (line 597).
  - `TICK_LENGTH = 0.05` (line 32); `MS_PER_STEP = 50` in `minerl/herobraine/hero/mc.py:670`.
  - Real-time pacing exists only for human interaction: `make_interactive(..., realtime=True)` sleeps up to `TICK_LENGTH` per step; the default is `self._is_real_time = False` (line 119). [code: `_multiagent.py` L154-196, L366-370]
- The VPT paper (which uses a MineRL-derived env) states the design explicitly: "Unlike the regular Minecraft game, in which the server ... always runs at 20Hz and the client runs as fast as rendering can complete ..., in our version the client and server run in the same thread at the same frequency. This allows us to run the environment slower or faster than real time". [paper: VPT, arXiv 2206.11795, Appendix C]
- Consequence `[inference from the above]`: wall-clock thinking time between `step` calls does not advance the world.

**Q2 Action granularity**: One low-level human-style input state per tick: dict of keyboard binary actions (forward, back, left, right, jump, sneak, sprint, attack, use, drop, hotbar, `inventory`, `ESC`, `pickItem`, `swapHands`...) plus `camera` [pitch, yaw] deltas. [docs: https://minerl.readthedocs.io/en/latest/ "Action Space"; the BASALT/Diamond env specs]

**Q3 Duration / interruption / reflex**
- One action = one tick (50 ms of game time). Anything longer is the agent's own sequence of steps (e.g. VPT: 60 consecutive attack actions to break one log).
- No reflex. Agents can die; in BASALT `allow_spawning=True` and time is frozen with `TimeInitialCondition(allow_passage_of_time=False)` (`basalt_specs.py` ~L170-178), so hostile mobs can appear but there is no day/night progression.
- Episode caps, in ticks (= steps):

| Env | Max steps | Wall-game time | Source line |
|---|---|---|---|
| BasaltFindCave | 3*MINUTE = 3,600 | 3 min | `minerl/herobraine/env_specs/basalt_specs.py:259` |
| BasaltMakeWaterfall | 5*MINUTE = 6,000 | 5 min | `:293` |
| BasaltCreateVillageAnimalPen | 5*MINUTE = 6,000 | 5 min | `:338` |
| BasaltBuildVillageHouse | 12*MINUTE = 14,400 | 12 min | `:389` |
| ObtainDiamond(Shovel) | TIMEOUT = 18,000 | 15 min | `obtain_specs.py:11,103` |

  with `MINUTE = 20 * 60` (`basalt_specs.py:228`). BASALT also ends an episode when the agent presses `ESC` (`DoneOnESCWrapper`) and enforces the cap with `BasaltTimeoutWrapper`.

**Q4 Decisions per episode**: Equal to steps: 3,600 to 18,000 policy calls per episode at 20 Hz. The BASALT paper states trajectories are "contiguously sampled at every Minecraft game tick (20 game ticks per second)". [paper: BASALT, arXiv 2107.01969]

**Q5 Sources**
- https://github.com/minerllabs/minerl/blob/dev/minerl/env/_multiagent.py
- https://github.com/minerllabs/minerl/blob/dev/minerl/herobraine/env_specs/basalt_specs.py
- https://github.com/minerllabs/minerl/blob/dev/minerl/herobraine/env_specs/obtain_specs.py
- https://github.com/minerllabs/minerl/blob/dev/minerl/herobraine/hero/mc.py
- https://minerl.readthedocs.io/en/latest/
- https://arxiv.org/abs/2206.11795 (VPT, Appendix C), https://arxiv.org/abs/2107.01969 (BASALT), https://arxiv.org/abs/1907.13440 (MineRL)

---

## 4. MineDojo

**Q1 Clock**
- Built on MineRL/Malmo plumbing. `BridgeEnv.step()` sends `<StepClient0>action</StepClient0 >` to each client, reads obs, reward, done and JSON info, then sends `<StepServer></StepServer>` to instance 0 (the server). [code: `minedojo/sim/bridge/bridge_env/bridge_env.py` lines 85-135, `StepServer` at L127]
- `[inference]` This is the same lock-step protocol as MineRL (section 3): the world advances only when `env.step` is called, one server step per call. I did not find a sentence in the MineDojo paper or README that states "one step = one tick"; ticks-per-step is not documented there (UNVERIFIED).

**Q2 Action granularity**: Compound, 1-step action: "At each step the agent chooses one movement action (forward, backward, camera actions, etc.) and one optional functional action" (use, drop, attack, craft, equip, place, destroy; `craft` takes an argument). [paper: MineDojo, arXiv 2206.08853, Appendix B.2] `env.execute_cmd(cmd, action)` additionally runs a raw Minecraft command string (e.g. spawn mobs, teleport) alongside an action for task setup. [code: `minedojo/sim/sim.py` ~L440-470]

**Q3 Duration / interruption / reflex**: Per-step actions; no reflex. Episode length per task: UNVERIFIED (not found in paper text or README).

**Q4 Decisions per episode**: Not reported in the sources I read (UNVERIFIED). Paper protocol: 100 evaluation episodes per task for success rate.

**Q5 Sources**
- https://github.com/MineDojo/MineDojo/blob/main/minedojo/sim/sim.py (`step` at ~L424)
- https://github.com/MineDojo/MineDojo/blob/main/minedojo/sim/bridge/bridge_env/bridge_env.py
- https://arxiv.org/abs/2206.08853

---

## 5. Voyager (MineDojo team, 2023): code-as-action via Mineflayer

**Q1 Clock: the server is paused while GPT-4 thinks, and runs in real time while a program executes.**
- Installation doc lists a "Multi Server Pause" Fabric mod: "Used to pause the server when waiting for GPT-4 to reply." [code: `installation/fabric_mods_install.md`, step 3, 4th bullet] The mod (iChun, "Multiplayer Server Pause (Fabric)") "allows servers (including integrated servers) to pause when all connected clients are paused ... Also adds a /pause command for Ops to force a pause on the server regardless of the pause state of clients." [CurseForge page https://www.curseforge.com/minecraft/mc-mods/multiplayer-server-pause-fabric]
- `VoyagerEnv.step(code, programs)`: `self.unpause()` -> `requests.post(.../step, timeout=request_timeout)` -> `self.pause()`. `pause()`/`unpause()` both POST `/pause`, a toggle guarded by `server_paused`. [code: `voyager/env/bridge.py` L105-125, L175-189]
- Node side: `/pause` just runs `bot.chat("/pause")` and waits `waitTicks` before replying (`voyager/env/mineflayer/index.js` L408-417).
- `reset()` also unpauses, restarts mineflayer, and re-pauses (`bridge.py` L130-162).
- So between iterations, while GPT-4 (action, critic, curriculum calls) runs, the world is frozen. During `step()` the server ticks freely at ~20 TPS (not stepped).
- Padding: every `/step` does `await bot.waitForTicks(bot.waitTicks)` before running the code (index.js L238) and again after `returnItems()` (L246). `waitTicks` = `env_wait_ticks`, default **20 ticks (1 s)**, "how many ticks at the end each step will wait, if you found some chat log missing, you should increase this value" (`voyager/voyager.py` L24, L62-63). `bot.waitForTicks` runs on mineflayer's own physics timer (i.e. a client-side 20 Hz loop). [docs: mineflayer `docs/api.md`, `bot.waitForTicks(ticks)`]
- World tweaks set at spawn: `/gamerule keepInventory true`, `/gamerule doDaylightCycle false` (index.js L133-134), so in-game time of day stays fixed. `[code]` The README tells LAN users to set "Game Mode to Creative and Difficulty to Peaceful" (README, Azure-login section); the paper does not state which difficulty was used for the reported runs (UNVERIFIED).

**Q2 Action granularity: a JavaScript program (an async function) written by GPT-4**, evaluated by `eval("(async () => {" + programs + "\n" + code + "})()")` (index.js L253-261). Programs call high-level primitives (`mineBlock(bot, name, count)`, `craftItem`, `smeltItem`, `placeItem`, `killMob(bot, mobName, timeout=300)`, `exploreUntil(bot, direction, maxTime=60, callback)`) and previously learned skills from the skill library; the primitives call Mineflayer + pathfinder / collectblock / pvp plugins. [paper: Voyager arXiv 2305.16291, Sec 2.3 + Appendix A.4 (Skill Library prompt / primitives); code: `voyager/control_primitives/*.js`]

**Q3 Duration / interruption / reflex**
- **Duration**: not capped by the LLM; ends when the async function returns, throws, or the HTTP request times out. Hard cap: `env_request_timeout = 600` s (docstring: "if the code execution exceeds this time, python side will terminate the connection and need to be resumed", `voyager.py` L25, L64-66; `bridge.py` L25). That is 600 s wall-clock = up to ~12,000 ticks at 20 TPS.
  Primitive-level wall-clock timers (all `setTimeout` / `setInterval`, in real seconds, not ticks):
  - `killMob` timeout default **300 s** (`control_primitives/killMob.js` L1; `waitForMobRemoved.js` L6-9 uses `timeout * 1000` ms).
  - `exploreUntil` `maxTime` default **60 s**, hard-capped `Math.min(maxTime, 1200)` s; re-targets every **2000 ms** (`exploreUntil.js` L35, `setInterval(explore, 2000)`).
  - `bot.fish` 60 s timeout (`lib/skillLoader.js`).
  - The prompt's furnace example waits `12 * 20` ticks (paper Appendix A).
  No typical wall-clock or game-time per iteration is reported (UNVERIFIED).
- **Interruption**: none. The Python side blocks on the HTTP POST until the program ends. The LLM cannot pre-empt a running program, and nothing else inside the step can either, except thrown errors: `process.on("uncaughtException", otherError)` ends the step and returns an observation (index.js L166, L155-165).
- **Reflexes / safety nets in the harness** (not LLM-driven):
  - Stuck detector: `onTick` on `physicTick`; if `pathfinder.isMoving()` for 100 ticks it samples position; if after 5 samples (>= ~500 ticks) displacement < 1.5 blocks it `/tp`s the bot to a nearby air block (index.js L214-225, L263-298).
  - `bot.on("mount", () => bot.dismount())` (L48-50).
  - After each step the harness recycles the crafting table / furnace and re-gives a chest / iron pickaxe (`returnItems`, L300-336).
  - Death: "If the bot dies, it is resurrected near the closest ground, and its inventory is preserved" (paper Appendix B.1; mods "Better Respawn", `keepInventory`).
  - Danger is otherwise surfaced only as text feedback after the step (`health`, `nearby entities`, chat/error events) for the next LLM call. A zombie attacking mid-program is not handled automatically.

**Q4 Decisions per episode**
- Main benchmark: **160 prompting iterations** ("63 unique items within 160 prompting iterations"; tech-tree numbers "within the maximal prompting iterations (160)") [paper Sec 3.3, Fig. 1, Table 1]; zero-shot generalization tests: **50 iterations** [paper Sec 3.3, Table 2]. Code default `max_iterations = 160` (`voyager.py` L26).
- One "iteration" = one executed program: `Recorder.record()` does `self.iteration += 1` per call, from `Voyager.step()` after `env.step(code)` (and once more for unparseable output) [code: `voyager/utils/record_utils.py` L22-32; `voyager.py` L203-262].
- Each task gets at most **4** code-generation rounds: `action_agent_task_max_retries = 4` (L30); paper: "If the agent gets stuck after 4 rounds of code generation, then we query the curriculum for another task." [paper Sec 2.3]
- LLM calls per iteration: >= 2 (action agent `self.action_agent.llm(...)` at L206 + critic `check_task_success` at L221); plus curriculum calls per new task (L319) and skill-description call on success (`add_new_skill`, L354). Total GPT-4 calls per run not reported. The paper only notes the cost is high ("15x more expensive than GPT-3.5").

**Q5 Sources**
- https://github.com/MineDojo/Voyager/blob/main/voyager/env/bridge.py
- https://github.com/MineDojo/Voyager/blob/main/voyager/env/mineflayer/index.js
- https://github.com/MineDojo/Voyager/blob/main/voyager/voyager.py
- https://github.com/MineDojo/Voyager/blob/main/installation/fabric_mods_install.md
- https://github.com/MineDojo/Voyager/blob/main/voyager/control_primitives/ (`killMob.js`, `exploreUntil.js`, `mineBlock.js`, `waitForMobRemoved.js`)
- https://arxiv.org/abs/2305.16291 (Sec 2.3, 3.x, App. A.4, B.1)

---

## 6. Mindcraft (kolbytn/mindcraft, now `mindcraft-bots/mindcraft`) and MineCollab

**Q1 Clock: real time, asynchronous, no pausing.**
- A plain Minecraft server keeps ticking while the LLM call is awaited. I grepped all fetched agent files (`agent.js`, `action_manager.js`, `modes.js`, `commands/actions.js`, `library/skills.js`, `self_prompter.js`, `coder.js`, `settings.js`, README) for `/tick`, `/pause`, `waitForTicks`, `physicsTick` and found none. All timing is wall-clock `Date.now()` / `setTimeout` (e.g. `stay` loops on `Date.now() - start < seconds*1000`, skills.js ~L1492; modes use `Date.now()`).
- Only the multi-agent conversation manager throttles: "The conversation manager also helps limit the speed of agent responses to allow time for actions to occur in the environment ... if both agents are currently executing an action ..., the conversation is paused ... If one agent is acting, then the conversation is slowed." [paper: MineCollab arXiv 2504.17950, Sec 3.3 "Multi-agent Collaboration"]
- `[inference]` Because the agent loop awaits the LLM and the action sequentially, one agent has no LLM call in flight while its own action runs. The 300 ms reflex loop (below) is the only thing that runs concurrently with the LLM or an action.

**Q2 Action granularity: parameterized high-level commands ("47 parameterized tools"), plus optional free-form code.**
- Examples: `!collectBlocks(type, num)`, `!goToPlayer(name, closeness)`, `!goToCoordinates`, `!craftRecipe`, `!smeltItem`, `!attack`, `!givePlayer`, `!stay(seconds)`, `!searchForBlock`, `!followPlayer`, `!newAction(prompt)` (LLM writes a JS program; disabled unless `allow_insecure_coding`), `!stop`, `!setMode`. [code: `src/agent/commands/actions.js` (e.g. `!collectBlocks` L256-265, `!stay` L338-346, `!newAction` L30-52)]
- Paper contrast: MineRL-style "jump / look up / use"; Mineflayer high-level JS; Mindcraft adds a tool layer ("instead of generating Mineflayer code to 1) find the nearest player ..., the LLM can simply output `!givePlayer("randy", "oak log", 4)`"). [paper Sec 3.1 "State and Action Spaces", subsection "Action Space(s)"]

**Q3 Duration / interruption / reflex**
- **Duration**: a command runs until its skill function returns (path reached, blocks collected, ...). `runAsAction(actionFn, resume=false, timeout=-1)` wraps it in `ActionManager.runAction`. Timeout is in **minutes** and only applies if > 0: `!collectBlocks` uses 10 min; `!newAction` uses `settings.code_timeout_mins` (default `-1`, none); `ActionManager._startTimeout(TIMEOUT_MINS = 10)`. After a timeout, `stop()` is attempted. [code: `action_manager.js` L61-175; `settings.js`]
- **Interruption**: cooperative flag `bot.interrupt_code`. `ActionManager.stop()` loops `agent.requestInterrupt()` every 300 ms, which sets `interrupt_code = true` and calls `bot.stopDigging()`, `collectBlock.cancelTask()`, `pathfinder.stop()`, `pvp.stop()`. If the code does not exit within **10 s**, `agent.cleanKill(...)` terminates the process. Skills check `bot.interrupt_code` in their loops (skills.js L131, 246, 359, 402, 524, 1029, 1056, 1353, 1463, 1492). Starting a new action first interrupts the current one (`_executeAction` L87-90). `!stop` stops everything. [code: `action_manager.js` L26-37, L87-93; `agent.js` L233-239]
- **Reflex "modes"** (hard-coded, run outside the LLM): defined in `src/agent/modes.js` L24-304, in priority order; each has `on`, `active`, `paused`, `interrupts`, `update(agent)`:

| Mode | Behaviour | Interrupts |
|---|---|---|
| `self_preservation` | water: jump; falling sand/gravel: `moveAway(2)`; lava/fire: place water bucket or go to water or `moveAway(5)`; "dying" (damage within 3 s and health < 5 or last damage >= health): `moveAway(20)` | all |
| `unstuck` | if not moved > 2 blocks for `max_stuck_time = 20` s (x2 on obsidian): `moveAway(5)` | all |
| `cowardice` | hostile within 16 and clear path: `avoidEnemies(24)` | all |
| `self_defense` | hostile within 8 and clear path: `defendSelf(8)` | all |
| `hunting`, `item_collecting` (2 s delay), `torch_placing` (5 s cooldown), `elbow_room`, `idle_staring` | idle-only behaviours; `hunting`/`item_collecting`/`torch_placing`/`elbow_room` can interrupt `action:followPlayer` | followPlayer / none |
| `cheat` | `/tp` and instant placement; off by default | none |

  - Despite the comment "a mode is a function that is called every tick" (modes.js L13), the actual loop is **every 300 ms** of wall clock (~6 ticks): `const INTERVAL = 300; ... await this.update(start - last)` in `agent.js` L503-515, which calls `bot.modes.update()` (L520-524); update functions "should *not* be awaited longer than ~100ms" (modes.js L22).
  - A mode only runs if `mode.on && !mode.paused && !mode.active && (agent.isIdle() || interruptible)` (modes.js L399-410), so an `interrupts: ['all']` mode pre-empts any running action.
  - When a mode interrupts an action, `execute()` (L306-330) stops the self-prompt loop, runs the reflex as its own action, then (if the interrupted action had no resume function, self-prompting is off, and the mode itself was not interrupted) injects `(AUTO MESSAGE)Your previous action '<x>' was interrupted by <mode>. Your behavior log: ... Respond accordingly.` so the LLM is re-prompted with a log. Long-running resumable actions (`!followPlayer`, `resume=true`) are resumed 1 s after the agent goes idle.
  - `!stay` "Pauses all modes" for N seconds; `defendSelf` temporarily pauses `self_defense` and `cowardice`.
- **Auto-loop**: `SelfPrompter` (the `!goal` mechanism) re-prompts with `cooldown = 2000` ms; stops after `MAX_NO_COMMAND = 3` responses without a command (self_prompter.js).

**Q4 Decisions per episode**: Not reported as an LLM-call count. MineCollab states tasks need "on average over 20 steps" (abstract/Table 1 note: "Long horizon refers to the complex sequence of actions (on average over 20 steps)"). The prompt keeps `max_messages = 15` (settings.js) and the prompting ablation (Table 7 caption) says "summarizing past interactions in a goal oriented manner every 15 steps is critical". Episode time limits (wall-clock): crafting/techtree example task "Timeout: 300 seconds" (Appendix 11.1); construction "10 minute timeout, with 5 additional minutes per room complexity" (Appendix 8.2). Cooking timeout UNVERIFIED.

**Q5 Sources**
- https://github.com/mindcraft-bots/mindcraft/blob/main/src/agent/modes.js
- https://github.com/mindcraft-bots/mindcraft/blob/main/src/agent/action_manager.js
- https://github.com/mindcraft-bots/mindcraft/blob/main/src/agent/agent.js
- https://github.com/mindcraft-bots/mindcraft/blob/main/src/agent/commands/actions.js
- https://github.com/mindcraft-bots/mindcraft/blob/main/src/agent/self_prompter.js
- https://github.com/mindcraft-bots/mindcraft/blob/main/settings.js
- https://arxiv.org/abs/2504.17950 (MineCollab: "Collaborating Action by Action: A Multi-agent LLM Framework for Embodied Reasoning")

---

## 7. Extras

### 7a. "LLM planner + 20 Hz low-level policy" systems: STEVE-1, JARVIS-1, DEPS, GITM

All run in a MineRL/VPT-style lock-step env.

- **Env**: "Unlike the regular Minecraft game ... in our version the client and server run in the same thread at the same frequency" (VPT App. C, quoted verbatim in JARVIS-1 Appendix: "Our Minecraft environment is a hybrid between MineRL and the MCP-Reborn ... Minecraft modding package"). "The model operates at a speed of 20 frames per second" (JARVIS-1 Sec 4.1 "Environment setting").
- **STEVE-1** (arXiv 2306.00937): text-/visual-goal-conditioned VPT policy at 20 Hz. Hindsight goals are limited to "at most 200 timesteps in the future (~10 seconds)". Prompt chaining = "the prompts are given sequentially for a fixed number of steps" (e.g. 1500 steps "get dirt", then 1500 steps "build a tower"; App. Figs 18-19). No reflex; the goal is just swapped on a schedule. Short-horizon eval tasks are "achievable within the first 2.5 minutes" (= 3000 steps).
- **JARVIS-1** (arXiv 2311.05997): GPT/MLM planner emits K short-horizon text goals; the controller (STEVE-1 for mine goals; craft/smelt executed directly by the env, as in MineDojo) runs each. On execution failure, feedback goes back to the planner, which explains and re-plans ("usually only requires 2-3 rounds of re-planning" vs DEPS > 6; Sec 4.2). Per-task max step budgets "determined by the average time the human players need"; a skilled player takes >20 min (**24,000 steps**) for a diamond pickaxe; extended to 60 min (**72,000 steps**) [Sec 4.3]. Planner calls are event-driven (plan start, failure), not per tick. Subgoal timeout rule: UNVERIFIED.
- **DEPS** (arXiv 2302.01560): "Describe, Explain, Plan, Select"; planner called at start and on controller failure; episode caps **3,000-12,000 steps** depending on task difficulty; re-plan rounds limited by LLM context (Codex ~7-8 rounds, Table 4 caption).
- **GITM** (arXiv 2305.17144): LLM Decomposer -> Planner -> "structured actions" implemented as hand-written scripts over keyboard/mouse; time limit "10 minutes (12,000 steps at 20Hz control)" and a "query limit of 30 (each sub-goal)" (Sec 4.2 and 4.3; Table 3 caption). Feedback (success/fail + inventory, biome, etc.) returns to the planner after each structured action.
- Pattern: decision frequency is ~event-driven (seconds to minutes of game time), policy frequency is 20 Hz, and the clock is paused during planning because the env is lock-step.

### 7b. MineLand (arXiv 2403.19267, repo `cocacola-lab/MineLand`)

Multi-agent Minecraft simulator on Mineflayer; the only system found that exposes the time model as explicit knobs.

- **Q1 Clock**: `ticks_per_step` ("The number of ticks that pass per single step"; example `20` = "waiting 1 second per step") and `enable_auto_pause` (default **False**): "AUTO PAUSE mode automatically pauses the game when the `step` function is not running", and "if you want to pause the game while the agent is thinking, you must enable `enable_auto_pause`". With a remote server or without pause "the time will begin to pass". [docs: `docs/api.md` L38, L101-116]
- **Q2 Action**: gym-style low-level actions, or high-level actions as JS code (as Voyager). Each step carries a `RESUME` or `NEW` flag: code runs "only under NEW, and any previous code is interrupted"; `code_info` in the observation says whether the previous code finished (`running`, `ready`, exceptions). [docs: api.md L51-55; paper Sec 2.4-2.5]
- **Q3 Duration / interruption**: "the execution of the code is divided into several steps, with each step lasting 50-200 milliseconds" (footnote: "50 milliseconds is the minimum time unit in Minecraft ... a tick"); "the new message is allowed to interrupt the executing code ... even if an agent is working on a 5-minute extension (such as mining)". Events such as chat or being hurt can trigger interruption in the agent framework ("Upon a special event, Alex first decides in the associative memory whether the event requires high-priority processing; if so, it interrupts the current code"). Default "code execution time limit is 2000 ticks" (100 s of game time) and "FAILED TIMES LIMIT = 3". [paper Sec 2.5 + Appendix (Alex agent config)]
- **Q4**: Metrics include "the number of in-game ticks, and the number of code iterations" (App. benchmark text); no fixed decisions-per-episode number found (UNVERIFIED).
- **Q5**: https://arxiv.org/abs/2403.19267, https://github.com/cocacola-lab/MineLand/blob/main/docs/api.md

### 7c. Plancraft (arXiv 2412.21033)

- Not a real-time game: a crafting-GUI planning task in text or image. No clock; one LLM call per action ("the agent has to use the observations (text or image) to generate the next action"); episodes stop at a maximum of **n = 30** steps; tasks are filtered so the handcrafted planner's trajectory is <= 30 steps. Includes "impossible" tasks (agent must decide it cannot finish). No interruption, no danger. [paper Sec 3]

### 7d. Crafter (arXiv 2109.06780; repo `danijar/crafter`) and its LLM wrappers

Closest to a 2D, tile-based pixel-ish game.

- **Q1 Clock**: Pure step-based gym env; time only advances in `env.step(action)`. Each step increments `self._step`, updates daylight, applies the player's action, updates every object within `2*max(view)` of the player (zombies, cows, skeletons, arrows), and every 10th step rebalances spawns/despawns. Day/night: `progress = (self._step / 300) % 1 + 0.3` (a ~300-step cycle). [code: `crafter/env.py` L83-110, L135-139]
- **Q2 Action**: one of 17 discrete actions per step (noop, 4 moves, do, sleep, place x4, make x6...). `reward = (health delta)/10 + 1.0 per new achievement`. [code env.py L100; SmartPlay Table 1: action space 17]
- **Q3 Duration / interruption / reflex**: Every action lasts exactly 1 step, so a zombie attack never lands "mid-action". Zombies attack with a 5-step cooldown (`self.cooldown = 5`): damage 2 if awake, **7 if the player is sleeping** (`objects.py` L304-312). Engine-level reflex: `_wake_up_when_hurt()` forces `sleeping = False` when health drops (`objects.py` L169-172), and while asleep the player's chosen action is overridden to `sleep` until energy is full (L103-108). Episode `length = 10000` (env.py L29, L106); death also ends it. Benchmark budget: 1M env steps total over many episodes (paper Sec 3.3).
- **Q4 Decisions per episode**: up to 10,000 env steps. LLM wrappers: SmartPlay (arXiv 2310.01557) runs Crafter with "Rollout 10k", history length 5, action space 17, 10 trials (its Table 1), prompting the LLM at each environment step ("What is the next action to take, let's think step by step" then "Choose the best executable action"); i.e. up to 10k LLM decisions per episode, one per step `[inference from the interface description]`. SPRING (arXiv 2305.15486) also drives Crafter with an LLM per step (details not verified: the ar5iv rendering failed).
- **Q5**: https://github.com/danijar/crafter/blob/main/crafter/env.py, `.../objects.py`, https://arxiv.org/abs/2109.06780, https://arxiv.org/abs/2310.01557

---

## 8. Comparison table

| System | Clock paused during agent thinking? | Game ticks per agent step | Action type | Interruption / reflex mechanism | Source |
|---|---|---|---|---|---|
| Minecraft (vanilla, 1.20.3+) | No by default (20 TPS). `/tick freeze` pauses everything except players and ridden entities; `/tick step N` advances N ticks | n/a (`tick step` default 1; `tick rate` 1-10000 TPS) | Native per-tick key/mouse input | None built in | minecraft.wiki /Tick, /Commands/tick |
| Malmo (classic) | No: real time; `MsPerTick` default 50 ms can be lowered to overclock | Agent-driven async: polls `getWorldState()`; observations every `update_frequency` ticks | Text commands: continuous (persist until changed), discrete (instant 1-block displacement), absolute `tp`, inventory, chat | None; command quotas and `ServerQuitFromTimeUp` end missions; opt-in multi-agent turn scheduler | Malmo Mission.html, MissionHandlers.html, tutorial_1.py |
| MalmoEnv | No tick lock-step found: step returns the newest rendered frame (frames can be dropped) | ~1 frame per step (not tick-locked) `[inference]` | Same commands, one per step | None | MalmoEnv core.py L304-351, MalmoEnvServer.java L727-733 |
| MineRL / BASALT / ObtainDiamond (1.x) | Yes, lock-step (`StepClient` then `StepServer`; mission `synchronous=true`) | 1 tick (50 ms) | Per-tick keyboard dict + camera delta | None; episode caps 3,600-18,000 steps; BASALT `ESC` ends the episode | `_multiagent.py` L273-351, L597; `mc.py:670`; `basalt_specs.py` |
| MineDojo | Yes, same `StepClient`/`StepServer` bridge `[inference]` | 1 server step per `env.step` (ticks-per-step not documented: UNVERIFIED) | Compound multi-discrete: 1 movement + 1 functional action | None | `bridge_env.py` L85-135; paper App. B.2 |
| Voyager | Yes, while GPT-4 thinks (mod `/pause` toggled by `VoyagerEnv.step`); No, while a program runs (server ticks freely) | Variable: whole program, seconds to <= 600 s wall-clock, plus 2 x 20 wait ticks | LLM-written JS program calling Mineflayer-based primitives and skills | No pre-emption. Harness: stuck-teleport (>= ~500 ticks), dismount, inventory/table recycling, respawn + keepInventory; 600 s HTTP timeout; primitive timers (`killMob` 300 s, `exploreUntil` <= 1200 s) | `bridge.py` L105-189; `index.js`; `voyager.py` L24-30; Fabric mods doc |
| Mindcraft | No: real time, no pause; LLM latency is world time | Variable: until the command's skill returns (timeouts in minutes; `!collectBlocks` 10 min) | ~47 parameterized commands (`!collectBlocks`...), optional `!newAction` JS | Modes loop every 300 ms: `self_preservation`, `unstuck`, `cowardice`, `self_defense` (interrupt all) via `interrupt_code` flag; 10 s stop watchdog then process kill; AUTO MESSAGE re-prompts the LLM | `modes.js`, `action_manager.js`, `agent.js` L503-524 |
| MineCollab (on Mindcraft) | No (real time) | Variable; task time limits 300 s (crafting example) to 10+ min (construction) | Mindcraft commands | Mindcraft modes; conversation manager slows chat while agents act | arXiv 2504.17950 |
| MineLand | Configurable: `enable_auto_pause` (default False) | Configurable `ticks_per_step`; code runs in 50-200 ms slices per step; code limit 2000 ticks | Low-level gym actions or JS code with `NEW`/`RESUME` | `NEW` replaces running code; chat/hurt events interrupt; failed-times limit 3 | arXiv 2403.19267; `docs/api.md` |
| STEVE-1 / JARVIS-1 / DEPS / GITM | Yes (MineRL/VPT-style lock-step env) | 1 tick per policy step at 20 Hz; LLM planner at plan start / on failure | Low-level keys + mouse (policy); text goals / structured actions (planner) | Re-plan on failure feedback; fixed-step prompt switching (STEVE-1); caps 3,000-72,000 steps | VPT App. C; JARVIS-1 Sec 4; GITM Table 3 |
| Plancraft | n/a (no clock) | n/a (1 action per LLM call, max 30) | Crafting-GUI actions in text/image | None | arXiv 2412.21033 |
| Crafter (+ SmartPlay) | Yes (pure step-based) | 1 step (world update incl. mobs) | 1 of 17 discrete actions | Engine wake-up on damage; sleeping forces `sleep`; zombie cooldown 5 steps | `crafter/env.py`, `objects.py`; SmartPlay Table 1 |

---

## 9. Caveats / not found / UNVERIFIED

- MineRL: the Java side of `StepClient`/`StepServer` was not read; "exactly 1 tick per step" is supported by `MS_PER_STEP = 50`, the VPT description of a single-threaded client+server env, and the 20-steps-per-second convention in the MineRL/BASALT papers, but not by a Java-side quote.
- MineDojo: ticks-per-step, episode lengths, and decisions per episode are not stated in the paper/README text I read. Lock-step is inferred from `bridge_env.py`.
- Malmo/MalmoEnv: no statement was found that the server is paused between steps; absence of evidence in the files read, not proof. The IJCAI 2016 Malmo paper PDF could not be parsed as text.
- Voyager: no per-iteration wall-clock or game-time statistics in paper or repo. Which difficulty was used for the paper's runs is unclear (README says Peaceful for the Azure-login LAN world). Total GPT-4 calls per run are not reported.
- Mindcraft/MineCollab: "no pausing" is based on a negative grep of the fetched source files, plus the structure of the async loops. MineCollab's cooking-task timeout and the exact meaning of "steps" in "over 20 steps" are not stated precisely.
- JARVIS-1 / DEPS / GITM: per-subgoal timeout/failure-detection rules are not described in the text I searched (UNVERIFIED).
- SPRING (2305.15486): the ar5iv rendering failed and the PDF was not parsed; only the abstract was checked.
- GitHub paths are from default branch heads on 2026-10-25 (`MineDojo/Voyager@main`, `mindcraft-bots/mindcraft@main`, `minerllabs/minerl@dev`, `microsoft/malmo@master`, `MineDojo/MineDojo@main`, `cocacola-lab/MineLand@main`, `danijar/crafter@main`). Line numbers may drift.
