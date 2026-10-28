# Wand Casting Engine (wands, deck/hand/discard, shot states, generation)

**Purpose / when to read this.** Normative reference for how a wand turns one click into projectiles: wand stats, the deck/hand/discard card game, draw and wrap, shot states, multicast, triggers/timers/expiration payloads, recharge and cast-delay accumulation, mana and charges, always-cast, shuffle, Divide/Greek/Add-Trigger/Refresh/Requirement spells, plus a short wand-generation section. Read it before touching wand/spell code in `noita_core`, before writing casting tests or wand-building benchmark tasks, and when reviewing any change to draw order, mana, recharge or cast delay. Per-spell numbers live in `spells.json`; this page defines how those numbers are *used*. Cite rule IDs (`WAND-Rxx`) in code comments and tests.
**Evidence tags.** `LUA` = re-read in `raw/game/gun.lua` / `gun_actions.lua` for this page; `WIKI` = noita.wiki.gg only; `ENGINE` = closed C++ behaviour known only from the wiki; `SCRIPT` = cross-checked with a throw-away reference simulation of the pseudocode below (not in the repo); `UNVERIFIED` = no source. Units: frames at 60 fps; internal damage x25 = displayed.

## Normative rules

### A. Units and data model
- **WAND-R01** All durations (cast delay, recharge, timer delays, lifetimes) are integer frames at 60 fps; UI seconds = frames/60. Src: LUA (Spark Bolt +3 f = "0.05 s"); wand-mechanics.md (WM) conventions.
- **WAND-R02** Spell damage fields are internal units; displayed = internal x25 (DAMAGE +0.4 -> +10, HEAVY_SHOT +1.75 -> +43.75, DIVIDE_10 -1.5 -> -37.5, PIERCING_SHOT -0.6 -> -15). `spells.json` `damage_modifier` already stores the displayed value (+10 for DAMAGE), the Lua `c.damage_*_add` the internal one (SPELL-R03). Src: LUA; `spells.json` damage_modifier.
- **WAND-R03** Wand stats: `shuffle` bool; `actions_per_round` (UI Spells/Cast) int in 1..capacity; cast delay `fire_rate_wait` (int frames, may be negative); recharge `reload_time` (int frames, may be negative); `mana_max`; `mana_charge_speed` (mana/s); `deck_capacity` (slots); `spread_degrees`; hidden `speed_multiplier`; `always_casts` (0-4 spell ids); per-wand current `mana`. Spells can never change Spells/Cast, Shuffle, Capacity, Mana Max or Mana Charge Speed; they only change per-cast accumulators (R31-R33, R52). Src: WM §1; wiki Wands.
- **WAND-R04** Spell (card) fields: `type` in {PROJECTILE 0, STATIC_PROJECTILE 1, MODIFIER 2, DRAW_MANY 3 (UI "Multicast"), MATERIAL 4, OTHER 5, UTILITY 6, PASSIVE 7}; `mana` (default 10 if the source omits it; negative allowed: MANA_REDUCE -30, BLOOD_MAGIC -100); `max_uses` (absent = unlimited); `never_unlimited`; `recursive` (19 spells); `related_projectiles`; `custom_uses_logic`. A card instance adds `uses_remaining` (-1 = unlimited), `deck_index` (rank among non-empty slots), `permanently_attached`. Src: LUA gun.lua.
- **WAND-R05** A spell runs in one of two modes. *Drawn*: mana check, uses check, card enters the hand, action runs (R20). *Called* (copied): only the action runs - no mana, no uses check, no hand - except where a copy spell does extra work (Divide/Add Trigger decrement the target's uses, R64). A called spell still adds its own cast-delay/recharge deltas and may draw unless draw is disabled (R25). Src: LUA play vs direct action call; wiki Calling and Recursion.

### B. Piles and click start
- **WAND-R10** Three ordered piles: deck (drawn from the front), hand (cards played this click, in play order), discarded. Empty slots are not cards. The initial deck is every non-empty slot in slot order. Copies are calls, not cards. Src: LUA `_add_card_to_deck`; wiki Draw.
- **WAND-R11** `order_deck`: non-shuffle = sort the whole deck by `deck_index`; shuffle = replace it by a uniform random permutation (repeat: remove a uniformly random remaining card, append to the new deck). Called on: the first click after (re)equip, every wrap, every recharge start, the first Wand Refresh of a click. Never per draw or per click; a shuffle wand walks one permutation until the next such event. Shuffle permutes all card types. Src: LUA `order_deck`; wiki Wands#Shuffle.
- **WAND-R12** Click start (wand must be ready, R54): clear `dont_draw`, `force_stop_draws`, `got_projectiles`; `mana := min(wand.mana, mana_max)`; recoil accumulator := 0; root shot state := wand cast delay/spread/speed + defaults (R31); on the first click after (re)equip `order_deck()` and `current_reload_time := wand.reload_time`; then play always-casts (R70), then draw `actions_per_round` cards with `instant=false`. Src: LUA `_start_shot`; wiki Draw "Global values".

### C. Draw, skip, wrap
- **WAND-R20** Draw one card: take the front card. Skip it if `cost > mana` (strict: `cost == mana` passes; negative cost never skips) or `uses_remaining == 0`: it goes to *discarded*, costs nothing, does not enter the hand, and the draw reports failure. Otherwise `mana -= cost` (negative cost adds mana), the card enters the hand and its action runs. Src: LUA `draw_action`.
- **WAND-R21** After a failed draw the *same* draw retries with the next card, repeatedly, while the deck is non-empty; skipped cards cost no draw. If the deck empties during the retries the draw is lost and no wrap happens inside the retry loop (a later draw of the same multicast may wrap). A skipped card that was last in the deck therefore "eats one draw". Src: LUA `draw_actions`; wiki Draw `draw_retry`.
- **WAND-R22** Draw on an empty deck: if the draw was requested by a spell (`instant=true`) and `force_stop_draws` is false -> wrap (R23). Otherwise (the wand's own Spells/Cast draw, or after a Wand Refresh this click) set `reloading` and every enclosing draw loop of this click stops at once. Src: LUA `draw_action`.
- **WAND-R23** Wrap: append all of *discarded* (in discard order) to the empty deck, `order_deck()`, set `start_reload`, continue the draw with the new front card; if discarded was empty the draw is consumed without playing a card but `start_reload` is still set. Only a spell's draw on an empty deck wraps; Spells/Cast never wraps, but its remaining draws continue from the refilled deck. A wrap can only reach cards already in *discarded*: normally earlier clicks' cards (this click's cards are in the hand), plus cards sent straight to discarded by skips, Divide, Add Trigger, Requirement. Src: LUA; wiki Draw "Wrapping".
- **WAND-R24** Draw counts (a spell draws by calling `draw_actions(n, true)`): PROJECTILE/STATIC/MATERIAL 0; trigger/timer/expiration projectiles draw their payload (R40); MODIFIER 1 (142 of 143 catalogue modifiers; RANDOM_MODIFIER 0); DRAW_MANY n; Requirement 1; Add Trigger family 0 (builds a 1-draw payload); Divide 0; Alpha/Gamma/Tau/Omega/Phi 0, Mu/Sigma/Duplication 1; Wand Refresh 0. Net budget: projectile -1, modifier 0, Double +1. A modifier that draws 0 ends the chain. Src: `spells.json` draw_count; LUA.
- **WAND-R25** `dont_draw` makes every `draw_actions` a no-op. It is one global boolean, not a stack: each copy wrapper (Divide, Add Trigger, Omega, Mu, Phi, Sigma) sets it true before a call and unconditionally sets it false afterwards, even if an outer caller had set it. Src: LUA Divide/Add Trigger/Omega/Mu bodies.

### D. Shot state and multicast
- **WAND-R30** Each spell mutates only the *current* shot state (accumulators + projectile list); spells never modify other spells. Every projectile of a shot state receives its full accumulated modifiers regardless of evaluation order. Modifiers cannot cross shot states. Projectiles inside a shot state keep evaluation order (matters for Formation placement); the root shot's projectiles spawn when the click's draws finish, a payload's when its trigger fires. Src: wiki Draw "Shot state"; LUA.
- **WAND-R31** Root shot defaults: `fire_rate_wait`, `spread_degrees`, `speed_multiplier` copied from the wand; `child_speed_multiplier`, `dampening`, `blood_count_multiplier` 1; every other numeric field 0; strings empty; `friendly_fire` false (full list WM §3). A trigger payload starts from *all* defaults (cast delay 0, spread 0, speed 1): wand stats never leak into payloads. Src: LUA gunaction_generated; WM §3.
- **WAND-R32** Global (not per shot state): `current_reload_time`, `mana`, recoil accumulator. Any spell anywhere (payload, copy) changes them. Src: wiki Draw "Global values"; LUA.
- **WAND-R33** Most spells *add*; some *set*: CHAINSAW cast delay := 0, NUKE := 20, NUKE_GIGA := 50 (they erase everything accumulated before them: order matters); `pattern_degrees` is always set (last writer wins). `speed_multiplier` changes are multiplicative and clamped to [0, 20]; Divide clamps `explosion_radius` >= 0. Src: LUA; spells.md §4.2.
- **WAND-R34** DRAW_MANY: `draw_actions(N, true)` first, *then* its own deltas (Scatter spread, Formation spread/pattern; table in Key numbers). All N cards share the current shot state. Myriad draws `#deck` evaluated when it runs (0 if empty). Src: LUA BURST_*, SCATTER_*, *_SHAPE.

### E. Triggers, timers, expiration
- **WAND-R40** A trigger spell registers its trigger projectile plus a *new* payload shot state, performs the payload's draws immediately at cast time (`instant=true`, wrap allowed), pays their mana now, puts the drawn cards in the same hand, then resumes the parent shot state and its remaining draws. Src: LUA `add_projectile_trigger_*`; wiki Trigger "Payload Selection".
- **WAND-R41** Per shot state (isolated): cast delay, spread, speed, damage, crit, pattern, extra entities. Shared: `current_reload_time`, mana, recoil. A payload's cast delay does not count for the wand; its recharge deltas do, at cast time (DIGGER inside a payload still gives -10 recharge). Src: wiki Trigger/Timer; LUA; SCRIPT KV-10.
- **WAND-R42** Payload draw counts: 1 for every trigger/timer/expiration spell and for Add Trigger/Timer/Expiration; 2 for LIGHT_BULLET_TRIGGER_2; 3 for DELAYED_SPELL. Timer delays (frames): 4 (LASER_LUMINOUS_DRILL), 10 (LIGHT_BULLET/BULLET/HEAVY_BULLET timers), 20 (ADD_TIMER, TENTACLE_TIMER), 40 (3 SPITTER timers), 100 (SLOW_BULLET_TIMER), 200 (BOUNCY_ORB_TIMER). 28 trigger spells: 8 collision, 11 timer, 9 expiration. Src: `spells.json` trigger; wiki Timer.
- **WAND-R43** (ENGINE/WIKI) Collision trigger: payload released when the projectile hits terrain or an entity; a terrain hit consumes it; a piercing projectile re-releases per entity hit at no extra mana. Timer: after its delay or on collision, whichever first, then stops. Expiration: once when the projectile dies; random direction if it dies stationary; payload speed 0 if the trigger projectile's speed is ~0. Mana is spent at cast even if the trigger never fires. Src: wiki Trigger/Timer/Expiration Trigger.
- **WAND-R44** Mana is checked card by card (R20). [HOMING 70, SPARK_BOLT 5]: mana >= 75 both; 70-74 Homing only (Spark Bolt skipped, last card, draw spent); 5-69 Spark Bolt only; < 5 nothing. [trigger, payload card]: trigger affordable but payload not -> trigger with empty payload; trigger unaffordable but payload affordable -> payload cast without trigger. Src: wiki Wands#Mana Max, Trigger "Running out of Mana"; SCRIPT KV-07.

### F. End of click, recharge, cast delay, mana regen
- **WAND-R50** End of click: hand -> discarded in play order, applying R63. Always-cast copies and cards that reached 0 uses are dropped, not discarded. Wand mana := mana. Src: LUA `move_hand_to_discarded`.
- **WAND-R51** Recharge starts iff, at end of click, the deck is empty OR `start_reload` was set by a wrap (even though the wrap refilled the deck). Start = append discarded to the remaining deck, `order_deck()`, recharge timer := max(0, `current_reload_time`), `current_reload_time := wand.reload_time`, `start_reload := false`. A first Wand Refresh does not start one (R86); a deck left empty by a *second* Refresh does. ENGINE note: when the wand's own draw hits an empty deck (`reloading`), gun.lua skips its reload branch (so Lua alone would leave the wand stuck, SCRIPT); the game recharges (wiki Wands "Spells/Cast" example), so we treat "deck empty at end of click" as recharge however it became empty (DECISION WD1). Src: LUA `_handle_reload`; wiki Draw "Reload".
- **WAND-R52** `current_reload_time` starts at `wand.reload_time` (first click after equip, every recharge start); every evaluated spell effect adds its delta (payload spells, copies, clicks that do not recharge included); it persists across clicks of a cycle and is reset only by a recharge start (Refresh does not reset it, so un-recharged deltas pile up). Per-card draw recharge increment is 0. Src: LUA `register_action`/`_handle_reload`; wiki Wands#Recharge Time.
- **WAND-R53** (ENGINE/WIKI) Click cast delay = root `fire_rate_wait` after all draws = wand base + sum of deltas of every spell played or called on the root shot (not payload spells; set-spells per R33); effective value = max(1, total) frames, the clamp applying to the *total* (base -3.0 s + spells +2.5 s = -0.5 s -> 1 frame). A click whose root shot has no projectile has effective cast delay 1 frame. Src: wiki Wands#Cast Delay.
- **WAND-R54** (ENGINE/WIKI) Cast delay and recharge run concurrently: next click allowed at `click_frame + max(cast_delay_eff, recharge_frames)` (`recharge_frames = 0` if none started); at most one click per frame. Src: wiki Draw "Reload", Wands.
- **WAND-R55** Effective recharge = max(0, wand.reload_time + sum of deltas) (clamp on the total, like R53). Src: wiki Wands#Recharge Time.
- **WAND-R56** Re-equip (switch away and back): deck := full wand in slot/shuffle order, hand and discarded cleared, `first_shot` set, uses re-read from the cards; a recharge already running is not cancelled. Src: LUA `_clear_deck`; wiki Beginner's Guide.
- **WAND-R57** Mana regenerates +`mana_charge_speed`/60 per frame, every frame, also while the wand is not held; capped at `mana_max` (the cap is applied at click start; mana may exceed it inside a click). Src: wiki Wands#Mana Charge Speed; wiki Draw.

### G. Mana and charges
- **WAND-R60** Mana is deducted per card at draw time, in evaluation order (R20); payload cards are paid at cast; called copies are free; nothing is refunded when a trigger never fires. Always-casts are free unless their cost is negative (then it adds mana, R70). Src: LUA; wiki Wands.
- **WAND-R61** Mana To Damage (DAMAGE_FOREVER): if `mana > 50`: `damage_projectile_add += 0.025 x (mana - 50)` (= +0.625 displayed per mana), then `mana := 50`. Mu/Phi/Sigma snapshot and restore mana, cast delay and `current_reload_time` around their copies. Src: LUA.
- **WAND-R62** Mana gained inside a click (negative-cost spells) is available to every *later* card of that click only (evaluation order), may exceed `mana_max` until the click ends, is written back to the wand (R50) and is capped at the next click start (R12/R57). An Add Mana placed after an expensive card does not help that card. Src: LUA `draw_action`; wiki Wands#Mana Max, Draw "Global values"; test `mana_02`.
- **WAND-R63** Uses are consumed at end of click, for each hand card with `uses_remaining > 0` and no `custom_uses_logic`, iff `got_projectiles` OR the card's type is OTHER/UTILITY; `got_projectiles` becomes true when any PROJECTILE/STATIC/MATERIAL card is *played* this click (always-cast copies included). Limited-use modifiers cast next to only Notes, Long-Distance Cast or copies are therefore free. A card reaching 0 uses in the hand leaves the cycle; a 0-use card met in the deck is skipped to discarded (R20) and stays on the wand. The Unlimited Spells perk may veto a decrement (never for `never_unlimited` spells). Src: LUA `move_hand_to_discarded`; wiki Discards from the Hand.
- **WAND-R64** Divide (once per Divide instance, on its target) and the Add Trigger family (once, on the target) decrement uses and check `uses != 0` themselves. Alpha, Gamma, Tau, Omega, Mu, Phi, Sigma, Duplication neither check nor decrement (Copy Random Spell decrements, wiki). Always-cast clones have uses -1. Src: LUA.

### H. Always cast
- **WAND-R70** Before the wand's own draws, every click, for each always-cast id: clone it as a card (`permanently_attached`, uses -1), add its mana only if negative, play it directly (no mana check, not from the deck). It lands in the hand and is dropped (not discarded) at end of click. Src: LUA `_play_permanent_card`; wiki Wands#Always Casts.
- **WAND-R71** While an always-cast is being played, `draw_actions(1)` is a no-op: AC modifiers draw nothing and an AC LIGHT_BULLET_TRIGGER has an empty payload. Draws of 2+ proceed (AC LIGHT_BULLET_TRIGGER_2 fills 2 payload cards, AC DELAYED_SPELL 3) but inside those draws every draw-1 spell draws 0. Src: LUA `draw_actions`; wiki Wands.
- **WAND-R72** AC modifiers affect the root shot state only, never trigger payloads; an AC projectile sets `got_projectiles` (so limited-use modifiers are charged even if the root draws no projectile). Max 4 per wand. Src: wiki Wands; LUA.

### I. Copy spells, recursion, Refresh, Requirement (algorithms in the pseudocode below)
- **WAND-R80** Recursion: a drawn spell has level 0; calling a non-recursive spell keeps the caller's level; calling a recursive one gives level+1; a recursive target is not called when the caller's level is already >= 2 (`recursion_limit = 2`). Recursive spells (19): ALPHA GAMMA TAU OMEGA MU PHI SIGMA ZETA, DUPLICATE, RESET, 4 RANDOM_*, DRAW_RANDOM, DRAW_RANDOM_X3, DRAW_3_RANDOM, ALL_SPELLS, NUKE_GIGA. Divide is not recursive but forwards the level to its copies; Add Trigger calls its modifiers/target without a level (irrelevant: draw is disabled). Src: LUA `check_recursion`; wiki Calling and Recursion.
- **WAND-R81** Divide By N targets the *iter*-th deck card (iter = 1 for a drawn Divide, +1 per nested Divide), calls it N times (1 time if iter >= limit; limits D2 5, D3 4, D4 4, D10 3), the first copy with draw disabled; only the chain head (iter 1) restores cast delay/`current_reload_time` to their values right after its own delta and discards `iter_max` cards from the deck top (`iter_max` = the last non-nil depth returned by a copy). Every Divide instance, copies included, applies its damage/radius penalty and sets `pattern_degrees := 5`. A missing/0-use/recursion-blocked target: no copies, no discard, penalties still apply. Src: LUA DIVIDE_*; wiki Divide By Spells.
- **WAND-R82** Add Trigger/Timer/Expiration: scan the deck from the top over MODIFIER/PASSIVE/OTHER/DRAW_MANY cards, calling each MODIFIER with draw disabled (free, uses != 0 only; the Add family itself is skipped); the first other card is the target. Target needs `related_projectiles` and `uses != 0`, else nothing is discarded (the modifiers stay applied). On success: discard every scanned card plus the target, decrement target uses, then if any PROJECTILE/STATIC/MATERIAL/UTILITY card remains anywhere in the deck build one 1-draw trigger projectile per related projectile (timer delay 20 for ADD_TIMER) with the *base* projectile (no target cast delay/recharge/mana); otherwise call the target plainly with draw disabled. Src: LUA ADD_*; wiki Add Trigger Series.
- **WAND-R83** Greek letters (mana, cast delay in Key numbers): Alpha calls the first card of discarded, else hand, else deck; Gamma the last of deck, else hand; Tau the first two deck cards (both read before either runs); Omega calls (draw disabled) all discarded except RESET, then non-recursive hand cards, then all deck cards except RESET, iterating live piles; Mu/Phi/Sigma call every MODIFIER/PROJECTILE/STATIC_PROJECTILE card of discarded, hand, deck (draw disabled), then restore cast delay/recharge/mana to the values after their own delta; Mu and Sigma then draw 1. Alpha/Gamma/Tau do not disable draw. Src: LUA; wiki Greek spell pages.
- **WAND-R84** Spell Duplication: records `n = hand.len()`, calls hand cards `0..n` except DUPLICATE (recursion-checked, draw enabled), then +20 cast delay, +20 recharge, draws 1. Src: LUA DUPLICATE.
- **WAND-R85** Requirement spells (mana 0, draw 1): skip condition IF_ENEMY < 15 `homing_target` entities within 240 px, IF_PROJECTILE < 20 `projectile` entities within 160 px, IF_HP hp/max_hp > 0.25, IF_HALF alternating global flag (starts "do not skip"). Scan the deck: stop at another IF_* (not END/ELSE), remember IF_ELSE, stop at IF_END. Skip: discard deck cards 1..else (else exists) or ..end or just 1. No skip and an else exists: discard else..end (or to the deck end). Then `draw_actions(1,true)`. Src: LUA IF_*.
- **WAND-R86** Wand Refresh (RESET, UTILITY, recursive, mana 20): `current_reload_time -= 25`; hand then deck move to discarded (the hand is emptied, so uses are not consumed and always-cast copies land in discarded and later act as ordinary deck cards); the first Refresh of a click sets `force_stop_draws` and refills the deck (discarded -> deck, `order_deck`); a further Refresh the same click only empties hand+deck (-> recharge, R51). With `force_stop_draws` set no wrap is possible, an empty-deck draw just stops all drawing. Src: LUA RESET; wiki Wand Refresh.

### J. Wand generation (short; full distributions in `wand-stats.json`; evidence = wiki + earlier research of `gun_procedural.lua`, which is not stored locally and was not re-read)
- **WAND-R90** Budget ("cost") by tier: 1 -> 30 (+5 with 50 %), 2 -> 40, 3 -> 60, 4 -> 80, 5 -> 100, 6 -> 120, 10 (generated as 11) -> 180 (Limatoukka) / 200 (Nightmare Hell); then + Random(-3, 3). Rare wand (5 %): +65, purple glow, free always-cast; independently 4 % of wands get an always-cast. Src: wand-generation.md (WG) §1; wiki Wand Generation.
- **WAND-R91** Mana is independent of budget: charge = 50t + Random(-5, 5t); max = 50 + 150t + 10 Random(-5, 5); with probability 20/101 "slow" (charge /5, max x3) then 15/101 "fast" (charge x5, max /3; overrides slow); max >= 50, charge >= 10. Effective: fast 15 %, slow 17 %, normal 68 %. "Better" wands: no fast, 20 % slow (WIKI). Src: WG §2.
- **WAND-R92** Stats are bought from the budget in this order: {reload, cast delay, spread, speed} shuffled, then capacity, then {shuffle, spells/cast} (shuffle first with probability (15 + 6t) %, else 50/50). Each value is drawn from a weighted mixture of `RandomDistribution(min, max, mean, sharpness)`, clamped to what the remaining budget can pay, then paid. Prices: reload (60 - v)/5, cast delay 16 - v, spread 16 - v, speed 0, capacity (v - 6) x 5, non-shuffle 15 + 5 x capacity (only if capacity <= 9), spells/cast {1: 0, 2: 5 + 2c, 3: 15 + 3.5c, 4: 35 + 5c, 5: 45 + c^2}; a negative price refunds. Src: WG §3; `wand-stats.json` generation_prices.
- **WAND-R93** Post-processing: leftover budget (> 5, with probability 995/1001) -> capacity += cost/5 (shuffle) or cost/10 (non-shuffle); capacity clamped to [2, 26] except a 1/10001 chance (max 62 NG / 66 Nightmare); if reload >= 60 frames: spells/cast += 1, repeat with 70 % each, then with 50 % spells/cast := min of 6 draws of Random(spells/cast, capacity); finally clamp spells/cast to [1, capacity]; `mana := mana_max`. Hence recharge >= 1 s guarantees spells/cast >= 2. Src: WG §4; wiki Wands.
- **WAND-R94** Natural always-cast (4 % or rare): 77 % modifier, 8 % modifier, 8 % static projectile, 7 % projectile, from tier t (one above the wand's spells); never Multicast/Material/Other/Utility. Always Cast perk: +1 random AC, max 4 (43 % random modifier, 6 x 8.33 % named modifiers, 3.5 % static, 3 % projectile, 0.5 % utility). Src: WG §5; wiki Always Cast (Perk).
- **WAND-R95** Random wands hold only Projectile/Multicast/Modifier spells of tier t-1 (10 % repeating chance of one tier higher for the main projectile), `card_count = Random(0.51 cap, cap)` clamped to [1, cap-1] (at least one empty slot). Src: WG §5; wiki Wand and Spell Tiers.

### Reference pseudocode (language-neutral; mirrors the rules above, written for re-implementation)
```text
STATE per wand (hash it): deck, hand, discarded: list<Card>; c: ShotState (current); mana; cur_reload: int;
  flags dont_draw, force_stop, reloading, start_reload, got_projectiles, playing_ac; first_shot (true after equip)

click(wand, wand_mana):                                            // R12, R50-R54
  dont_draw = force_stop = got_projectiles = false
  root = ShotState{fire_rate_wait: wand.cast_delay, spread: wand.spread, speed: wand.speed, rest: default}
  mana = min(wand_mana, wand.mana_max); recoil = 0
  if first_shot { order_deck(); cur_reload = wand.reload_time; first_shot = false }
  for id in wand.always_casts { play_always_cast(id) }
  c = root; draw_actions(wand.spells_per_cast, instant=false)
  move_hand_to_discarded()
  recharge = none
  if reloading or deck.empty() or start_reload {                  // 'reloading' term: ENGINE rule, DECISION WD1
      deck.append(discarded.take_all()); order_deck()
      recharge = max(0, cur_reload); cur_reload = wand.reload_time; start_reload = false }
  reloading = false; wand_mana = mana
  cast_delay = root.projectiles.empty() ? 1 : max(1, root.fire_rate_wait)
  return (root, recharge, cast_delay)         // wand ready at frame + max(cast_delay, recharge or 0)

draw_actions(n, instant):                                          // R20-R25
  if dont_draw { return }
  if playing_ac and n == 1 { return }                              // R71
  repeat n { if !draw_action(instant) { while !deck.empty() { if draw_action(instant) { break } } }
             if reloading { return } }

draw_action(instant) -> bool:
  if deck.empty() {
      if instant and !force_stop { discarded -> deck (append); order_deck(); start_reload = true }   // wrap
      else { reloading = true; return true } }
  if deck.empty() { return true }                                  // wrap found nothing: draw consumed
  card = deck.pop_front()
  if card.mana > mana or card.uses == 0 { discarded.push(card); return false }
  mana -= card.mana; play(card); return true

play(card): hand.push(card); run(card, Drawn); if card.type in {PROJECTILE, STATIC, MATERIAL} { got_projectiles = true }
call(card, rec, iter) -> optional int: run(card, Called{rec, iter}) // no mana, no hand, no uses; only Divide returns a depth
check_recursion(card, rec): rec = rec or 0; if card and card.recursive { return rec >= 2 ? -1 : rec + 1 } return rec

move_hand_to_discarded():                                          // R50, R63
  for card in hand {
      if (got_projectiles or card.type in {OTHER, UTILITY}) and card.uses > 0 and !card.custom_uses
          { if perk_allows(card) { card.uses -= 1 } }
      if card.uses != 0 or card.custom_uses { if !card.permanently_attached { discarded.push(card) } } }
  hand.clear()

play_always_cast(id): card = clone(spell(id)); card.permanently_attached = true; card.uses = -1
  if card.mana < 0 { mana -= card.mana }; playing_ac = true; play(card); playing_ac = false     // R70

trigger_projectile(kind, entity, n, delay):                        // R40
  node = c.add_projectile(entity, trigger = kind, delay); parent = c
  c = ShotState::defaults(); draw_actions(n, instant=true); node.payload = c; c = parent

ACTIONS (deltas from spells.json; "add" unless R33 says set)
  Projectile : c.add_projectile(e); apply deltas                     Modifier : apply deltas; draw_actions(1, true)
  TriggerSpell: apply deltas; trigger_projectile(kind, e, n)         DrawMany(N): draw_actions(N, true); spread += s; pattern = p
  Divide(N, frw, limit, pen, rad)(rec, iter):                        // R81
    c.fire_rate_wait += frw; (D10: cur_reload += 20); it = iter or 1; it_max = it
    target = deck[it]  (1-based; none if deck shorter); copies = it >= limit ? 1 : N; r = check_recursion(target, rec)
    if target and r != -1 and target.uses != 0 {
        keep_cd = c.fire_rate_wait; keep_rl = cur_reload
        for i in 1..copies { if i == 1 { dont_draw = true }; ret = call(target, r, it + 1); dont_draw = false
                              if ret { it_max = ret } }
        if target.uses > 0 { target.uses -= 1 }
        if it == 1 { c.fire_rate_wait = keep_cd; cur_reload = keep_rl
                     repeat it_max { if !deck.empty() { discarded.push(deck.pop_front()) } } } }
    c.damage_projectile_add -= pen; c.explosion_radius = max(0, c.explosion_radius - rad); c.pattern = 5
    return it_max
  AddTrigger(kind, delay):                                           // R82
    i = 1; t = deck[1]
    while t and t.type in {MODIFIER, PASSIVE, OTHER, DRAW_MANY} {
        if t.uses != 0 and t.id not in {ADD_TRIGGER, ADD_TIMER, ADD_DEATH_TRIGGER} and t.type == MODIFIER
            { dont_draw = true; call(t); dont_draw = false }
        i += 1; t = deck[i] }
    if t and t.related and t.uses != 0 {
        discard deck[1..i]; ok = deck has any PROJECTILE/STATIC/MATERIAL/UTILITY card; if t.uses > 0 { t.uses -= 1 }
        if ok { repeat t.related.count { trigger_projectile(kind, t.related.entity, 1, delay) } }
        else  { dont_draw = true; call(t); dont_draw = false } }
  Alpha: cd += 15; s = discarded[1] or hand[1] or deck[1]; call(s, check_recursion(s, rec)) if allowed     // R83
  Gamma: cd += 15; s = deck.last or hand.last.   Tau: cd += 35; a = deck[1]; b = deck[2]; call a then b (levels computed first)
  Omega: cd += 50; with draw off: for s in discarded (not RESET), then hand (non-recursive only), then deck (not RESET): call(s, level)
  Mu/Phi/Sigma(type filter MODIFIER/PROJECTILE/STATIC; cd += 50/50/30): snapshot (c.fire_rate_wait, cur_reload, mana);
    for s in discarded, hand, deck with matching type: dont_draw = true; call(s, level); dont_draw = false
    restore snapshot; Mu and Sigma: draw_actions(1, true)
  Duplicate: n = hand.len(); for s in hand[0..n] except DUPLICATE: call(s, level) (draw enabled); cd += 20; cur_reload += 20; draw_actions(1, true)
  Reset: cur_reload -= 25; discarded += hand ++ deck; hand = deck = []                                         // R86
         if !force_stop { force_stop = true; discarded -> deck; order_deck() }
  Requirement(kind): per R85, then draw_actions(1, true)
```

## Key numbers

| Constant | Value | Unit / note |
|---|---|---|
| Frame rate | 60 | frames/s; 1 f = 16.667 ms |
| Damage display factor | 25 | displayed = internal x25 |
| Default mana drain if omitted | 10 | mana (`ACTION_MANA_DRAIN_DEFAULT`) |
| Per-card recharge increment | 0 | frames (inert) |
| Recursion limit | 2 | levels |
| Engine gun defaults | spc 1, shuffle false, reload 40 f, capacity 2 | `ConfigGun_Init` (from WM; `gun_generated.lua` is not stored locally) |
| Ability defaults | mana_max 100, charge 10/s, gun_level 1 | AbilityComponent |
| Base shot state | cast delay 0 f, spread 0 deg, speed x1.0 | wand overrides the three |
| `speed_multiplier` clamp | 0..20 | after each change |
| Mana regen | `mana_charge_speed`/60 | per frame |
| Capacity | 2..26 (1/10001 skip), absolute 62 NG / 66 Nightmare | slots; Spells/Cast practical 1..26 |
| Always casts | max 4 | per wand |
| Starter combat wand (wiki) | non-shuffle, spc 1, cast delay 9-15 f, recharge 20-28 f, mana 80-130, charge 25-40/s, cap 2-3 | |
| Starter bomb wand (wiki) | shuffle, spc 1, cast delay 3-8 f, recharge 1-10 f, mana 80-110, charge 5-20/s, cap 1 | |

Multicast spells (`draw_actions(N)` then deltas):

| Id | Draws | Mana | Spread add (deg) | Pattern set (deg) | Uses |
|---|---|---|---|---|---|
| BURST_2 / 3 / 4 / 8 | 2 / 3 / 4 / 8 | 0 / 2 / 5 / 30 | 0 | - | - |
| BURST_X (Myriad) | `#deck` | 50 | 0 | - | 30 |
| SCATTER_2 / 3 / 4 | 2 / 3 / 4 | 0 / 1 / 2 | +10 / +20 / +40 | - | - |
| I / Y / T / W shape | 2 / 2 / 3 / 3 | 0 / 2 / 3 / 3 | -5 / -8 / -8 / -5 | 180 / 45 / 90 / 20 | - |
| PENTAGRAM / CIRCLE shape | 5 / 6 | 5 / 6 | -12 / -15 | 180 / 180 | - |

Divide By (type OTHER, not recursive; all set `pattern_degrees` = 5):

| Id | Mana | Cast delay | Copies (iter < limit / >= limit) | Damage add (internal / shown) | Explosion radius add | Uses |
|---|---|---|---|---|---|---|
| DIVIDE_2 | 35 | +20 f | 2 / 1 (limit 5) | -0.2 / -5 | -5 | unlimited |
| DIVIDE_3 | 50 | +35 f | 3 / 1 (limit 4) | -0.4 / -10 | -10 | unlimited |
| DIVIDE_4 | 70 | +50 f | 4 / 1 (limit 4) | -0.6 / -15 | -20 | unlimited |
| DIVIDE_10 | 200 | +80 f, recharge +20 f | 10 / 1 (limit 3) | -1.5 / -37.5 | -40 | 5 |

Copy / utility spells: ALPHA 40 mana +15 f; GAMMA 40 +15 f; TAU 90 +35 f; OMEGA 320 +50 f; MU 120 +50 f; PHI 120 +50 f; SIGMA 120 +30 f; ZETA 10 (other wands' spells, UNVERIFIED here); DUPLICATE 250 +20 f +20 recharge; RESET 20 recharge -25 f; ADD_TRIGGER 10, ADD_TIMER 20 (timer 20 f), ADD_DEATH_TRIGGER 20; IF_* 0. Notable deltas: CHAINSAW cast delay set 0, recharge -10; DIGGER +1 f, -10; NUKE set 20 f, recharge +600, 1 use; NUKE_GIGA set 50 f, +800; MANA_REDUCE +10 f; BLOOD_MAGIC -20 f, -20 recharge; DAMAGE_FOREVER +15 f, +10 recharge. Catalogue extremes: cast delay -35 (LASER_LUMINOUS_DRILL) .. +600 (CESSATION); recharge -25 (RESET) .. +800; mana -100 .. 600.

Spells used by the vectors (type, mana, deltas): LIGHT_BULLET (P, 5, cd +3, crit +5, spread -1); LIGHT_BULLET_TRIGGER (P, 10, cd +3, crit +5, payload 1); LIGHT_BULLET_TRIGGER_2 (P, 15, cd +4, crit +5, payload 2); SPITTER (P, 5, cd -1, spread +6); RUBBER_BALL (P, 5, cd -2, spread -1); SLOW_BULLET (P, 30, cd +6, spread +3.6); DEATH_CROSS (P, 80, cd +40); ANTIHEAL (P, 20, 20 uses, cd +8); DAMAGE (M, 5, cd +5, dmg +0.4); HEAVY_SHOT (M, 7, cd +10, dmg +1.75, speed x0.3); SPEED (M, 3, speed x2.5); LIGHT (M, 1); HOMING (M, 70); HOMING_SHOOTER (M, 10); PIERCING_SHOT (M, 140, dmg -0.6); MANA_REDUCE (M, -30, cd +10).

Wand generation by tier t (R90-R91; normal archetype, jitter-free):

| Tier | Budget | Mana max | Charge /s | Slow archetype (max / charge) | Fast archetype (max / charge) |
|---|---|---|---|---|---|
| 1 | 30 or 35 | 150-250 | 45-55 | 450-750 / 10-11 | 50-83 / 225-275 |
| 2 | 40 | 300-400 | 95-110 | 900-1200 / 19-22 | 100-133 / 475-550 |
| 3 | 60 | 450-550 | 145-165 | 1350-1650 / 29-33 | 150-183 / 725-825 |
| 4 | 80 | 600-700 | 195-220 | 1800-2100 / 39-44 | 200-233 / 975-1100 |
| 5 | 100 | 750-850 | 245-275 | 2250-2550 / 49-55 | 250-283 / 1225-1375 |
| 6 | 120 | 900-1000 | 295-330 | 2700-3000 / 59-66 | 300-333 / 1475-1650 |
| 10 (as 11) | 180 / 200 | 1650-1750 | 545-605 | 4950-5250 / 109-121 | 550-583 / 2725-3025 |

Stat bounds that hold for any generated wand: capacity 2..26 (except 1/10001); spells/cast 1..capacity; cast delay -15..50 f; recharge 1..240 f; spread -35..35 deg; speed 0.5..10 (96 % in 0.8..1.2); recharge >= 60 f implies spells/cast >= 2. "Better" wand distributions (WIKI, min..max, mean, sharpness): speed 0.8..1.2 (1, 6); recharge 5..40 (20, 2); cast delay 1..35 (5, 2); spread -1..2 (0, 3); capacity 5..13 (8, 2); spells/cast 1..3 (1, 3).

## Data files

All under `.trellis/tasks/10-16-noita-cogbench/research/` (copy canonical ones to `crates/noita_core/data/` when the crate exists).

| File | Records | Key fields | Load | Canonical vs derived |
|---|---|---|---|---|
| `spells.json` | 422 (array) | `game_id` (UPPER = casting id; key on this), `id` (snake), `type` (lowercase string), `mana_drain` (int, default 10 already applied), `max_uses` (null = unlimited), `never_unlimited`, `recursive`, `draw_count` + `draw_scope` (`same_cast`/`trigger_payload`/null), `trigger` {type collision/timer/death, timer_frames, draw_count, count}, `cast_delay_modifier` {frames, mode add/set}, `recharge_time_modifier` {frames}, `spread_modifier`, `pattern_degrees`, `speed_multiplier`, `damage_modifier` (display units = internal x 25, SPELL-R03), `related_projectiles`, `complex_logic` (56) | `serde_json` into structs with `Option` fields | Canonical (from the game files): mana, uses, type, frames, recursive, draw, trigger. Derived: all `seconds` fields, `wiki`, `action_effects_raw`, `notes`. |
| `spell_behaviors_from_gun_actions.json` | 491 | `id`, `type` (UPPER), `mana`, `max_uses`, `recursive`, `draw_actions_calls` (ints or "#deck"), `triggers` [{kind hit_world/timer/death, entity, draw}], `fire_rate_wait` {ops, set}, `current_reload_time_ops`, `sets_dont_draw_actions` (12 spells) | cross-check only | Derived (static analysis of Lua). 69 ids are not in the 422 (debug/legacy: TESTBULLET, MANA -200, BUILDING_* (the only `custom_uses_logic` spells), BAAB_*, ...); ignore them. |
| `spell_actions_lua.json` | 422 | `{game_id: Lua action body}` | never loaded at runtime | Nolla's copyrighted code: authoritative reading for the 56 `complex_logic` spells; never paste into the repo. |
| `wand-stats.json` | 1 object | `config_gun_defaults`, `config_gunaction_base_defaults`, `ability_component_defaults`, `stats[]`, `tier_cost_budget`, `generation_mixtures` ({w, min, max, mean, sharp}; weights relative, not normalised), `generation_prices`, `starter_wands_wiki` | structs or `Value` | Canonical for defaults, units, prices. Mixtures come from earlier research of `gun_procedural.lua` (not stored locally: UNVERIFIED here, but they match the wiki tables to rounding). |
| `wand-cast-test-cases.json` | 32 cases (mana_01 has 4 variants, divide_02 has 6) | `_meta.default_wand` (cast delay 0, recharge 0, mana 100000, cap 26, all uses unlimited), `cases[]` {id, wand, slots (game ids), forced_permutation, clicks[] or variants[]} | test harness | Inputs canonical; 3 expected values are wrong (see Verification). |
| `mvp50.json` | 50 | rank, game_id, type, why | | MVP spell scope: includes BURST_2/3/4, triggers, DELAYED_SPELL, ADD_TRIGGER/TIMER, DIVIDE_2, RESET, MANA_REDUCE. |

## Worked examples / test vectors

### Verification of `wand-cast-test-cases.json` (every case hand-simulated against R10-R86, then re-run in a throw-away script)
| Case | Verdict |
|---|---|
| draw_02, draw_03, draw_05, draw_06, tuple_01, tuple_02, shuffle_01, mana_01 (75/72/30/4), mana_02, divide_01, divide_03, divide_04, divide_05 (9), greek_02, greek_03, addtrigger_01-04, refresh_01, always_cast_01, timing_01, timing_02 | OK |
| draw_04 | OK; recharge follows (deck empty at the end; SPEED's draw also wraps an empty discard, R23); the payload DIGGER adds -10 to `current_reload_time` (R41) |
| divide_02 (6 variants) | OK for unlimited uses (100, 100 with 111 penalties, 20, 200, 800, 80). With the real 5-use DIVIDE_10 variant 2 gives 50 (KV-05) |
| spc_01, refresh_02 | OK, but `recharge_after: true` exists only through the engine rule R51 (pure gun.lua would not recharge). refresh_02's `note` text is garbled; the result (2 Spitters, recharge) is right |
| always_cast_02, always_cast_03 | OK (wiki-only evidence) |
| **draw_01** | **CONTRADICTION**: `mana_spent` 10, algorithm gives 15 (DAMAGE 5 + 2 x SPARK_BOLT 5; BURST_2 is free). Other fields match (11 f, crit 10, +0.4) |
| **greek_01** | **CONTRADICTION**: `fire_rate_wait_frames` 105, algorithm gives 114 = 3 x TAU 35 + 3 x SPARK_BOLT 3. The wiki's "three Taus" counts only the Tau part. Deck [TAU, LB], mana 90, no recharge match |
| **refresh_03** | **CONTRADICTION**: `recharge_after: true`, algorithm gives false after click 1: only 3 root draws (MANA_REDUCE->SPITTER, RESET, MANA_REDUCE->SPITTER) so the second RESET is never drawn and the deck is [RESET]. The note's mechanism is wrong. See KV-01 for the corrected 2-click vector |

### Additional vectors (new; hand-checked and SCRIPT-verified; wand defaults as in `_meta.default_wand` unless stated)
Conventions: "net mana spent" = mana before - after (negative = gain); "recharge" = a recharge starts at the end of that click; cast delays are sums of spell deltas on a wand with base cast delay 0 unless stated; `LB` = LIGHT_BULLET, `D10` = DIVIDE_10.
- **KV-01** (replaces refresh_03) spc 3, [MANA_REDUCE, SPITTER, RESET]. Click 1: 2 SPITTER, no recharge, deck [RESET], net mana spent -30 (gains 30), cast delay 18, `current_reload_time` = base - 25. Click 2: RESET (refresh), MANA_REDUCE->SPITTER, RESET (second refresh empties everything): 1 SPITTER, recharge starts, `current_reload_time` = base - 75 (floor 0), net mana spent 15.
- **KV-02** spc 2, [RESET, RESET, LIGHT_BULLET]: no projectile, recharge starts (deck empty after the second RESET), mana 40, `current_reload_time` = base - 50.
- **KV-03** discard displacement (wiki): [BURST_2, DIVIDE_2, DAMAGE, LB, LB, RESET]: 1 LB, 3 DAMAGE instances, no recharge, mana 65, cast delay +20 (copies' and drawn spells' deltas are rolled back), damage +1.2 - 0.2 = +1.0, pattern 5.
- **KV-04** wrap inside one click (wiki): [BURST_4, D10, D10, D10, DAMAGE, LB], unlimited uses: 1 LB with 121 DAMAGE instances (100 + 21), recharge.
- **KV-05** (UNVERIFIED in-game, from the Lua) real uses, no perk: [D10, D10, D10, LB]: 50 LB (not 100), 61 damage penalties; the inner D10 runs out of uses after 5 of the middle D10's 10 calls; the last call reports depth 2, so only 2 cards are discarded and LB stays in the deck (one LB next click). With Unlimited Spells the decrement is vetoed and the result is 100 / 111.
- **KV-06** Alpha vs discard (wiki): spc 2, [SPITTER, BURST_3, ALPHA, DIVIDE_2, LB, ALPHA]: 2 SPITTER + 3 LB (the second Alpha copies Spark Bolt from the discard, not Spitter).
- **KV-07** [LIGHT_BULLET_TRIGGER, SPITTER] by mana: >= 15 trigger + payload (spent 15); 10-14 trigger with empty payload (10); 5-9 SPITTER alone (5); < 5 nothing.
- **KV-08** limited use drop-out: [DAMAGE (1 use), LB] x3 clicks: click 1 LB with +0.4 (DAMAGE reaches 0, leaves the cycle); clicks 2-3 plain LB; recharge every click.
- **KV-09** recharge accumulation: cast delay 10, recharge 40, [CHAINSAW x4], spc 1: each click 1 CHAINSAW (cast delay set 0 -> 1 f, mana 1); recharge starts only after click 4 with 40 - 4 x 10 = 0 f.
- **KV-10** payload recharge: recharge 30, [LB_TRIGGER, DIGGER, LB]: click 1 LB_TRIGGER with DIGGER payload (`current_reload_time` -10 at cast, mana 10); click 2 LB, recharge 20 f.
- **KV-11** set-mode cast delay: cast delay 10, recharge 30, [DAMAGE, NUKE]: cast delay 20 (NUKE overrides 10 + 5), recharge 630, mana 205.
- **KV-12** Myriad: [BURST_X, LB, LB, LB]: 3 LB, mana 65, recharge; [LB, BURST_X] click 2: no projectile, mana 50, recharge.
- **KV-13** always cast DAMAGE, spc 2, [LB, LB, LB]: click 1 both LB with +0.4 (mana 10); click 2 one LB with +0.4, recharge.
- **KV-14** wand cast delay -15, [LB]: total -12 -> effective 1 f; a click with no projectile also 1 f.
- **KV-15** generation properties: every generated wand satisfies the bounds under Key numbers; mana ranges per tier from the table; ~15 % fast / ~17 % slow over many samples; rare share ~5 % and AC share ~4 % + rare.

## Pitfalls and common misreadings
- Spells never modify spells; they edit a shot state. Separate clicks and every trigger payload are separate shot states (R30, R41).
- A trailing modifier/multicast with nothing left in the deck wraps the wand and forces a recharge (R23); the wand's own Spells/Cast never wraps (R22). Spells/Cast is not a Double Spell.
- A skipped card (no mana, 0 uses) is free and the next card is tried; only when it was the last card does it eat the draw (R21). Mana is a per-card check at draw time, not a total.
- Payload cards are drawn and paid at cast time, not when the trigger fires; payload cast delay is ignored but payload recharge deltas count (R41).
- Cast delay and recharge overlap (max, not sum); recharge deltas are cumulative over the whole cycle and survive clicks without recharge, so a Refresh wand that never recharges stockpiles them (R52, R54).
- Divide copies lose their cast delay and recharge, but their crit, spread, damage penalties and drawn side effects stay (D10 x LB: crit +50, spread -10). A lone Divide on a modifier draws and discards the wrong cards (11 DAMAGE, discard displacement); `dont_draw` is a global flag that any wrapper resets (R25, R81).
- Mu and Sigma re-enable draw as soon as they copied one card, so they cannot be draw-cancelled by Divide/Omega; with nothing to copy they inherit the outer flag. Phi never draws.
- Always-cast modifiers draw nothing and are free; an AC trigger has an empty payload; AC copies sent to discarded by a Refresh become ordinary deck cards (R70-R72, R86).
- Uses are charged at end of click and only if a projectile-type card was played (or the card is OTHER/UTILITY); Refresh skips the charge (R63, R86). Add Trigger's free modifiers and Greek copies are never charged.
- Add Trigger's payload check scans the whole remaining deck, not the next card; a failed target search discards nothing but the modifiers it called stay applied, so they run twice if drawn later (R82).
- The first Wand Refresh disables wrapping for the rest of the click and does not recharge; the second forces a recharge (R86). The Draw guide's "Refresh leaves the deck empty -> no reload" refers to the first one, whose deck is refilled.
- Negative cast delay/recharge/spread are clamped on the *total*; negative base stats offset spell additions (R53, R55). Mana can exceed `mana_max` inside a click (Add Mana), is capped at the next click start.
- Shuffle is per cycle, not per cast; it shuffles multicasts, modifiers and triggers too; the editor shows slot order, not the permutation (R11).
- Chain Spell is a modifier, not a trigger; Scatter adds +10/+20/+40 deg (not +10 each); `pattern_degrees` is set, not added, and Divide sets it to 5 (R33, R34).

### Source conflicts and which source we trust
| Topic | Source A | Source B | Decision |
|---|---|---|---|
| Scatter spread / mana | WM §9.1 "+10 each", mana "0/1/?" | gun_actions + spells.json: spread +10 / +20 / +40, mana 0 / 1 / 2 | Trust LUA |
| Formation geometry | WM §9.2 spacing A/(n-1) over +-A | Wiki: arc +-A, "Above and Below" = ahead, up, down; spaced as n+1 if A >= 180 | Spacing = 2A/(n-1) (A < 180) or 2A/n (A >= 180), first projectile on top (ENGINE, UNVERIFIED); WM's formula is a factor 2 off |
| Recharge when root draw hits an empty deck | gun.lua skips reload | Wiki: wand recharges | Trust wiki + stuck-wand argument (R51, WD1) |
| Mu "draws unconditionally" | WM §11 | Lua: re-enable only after >= 1 copy; wiki Omega page "if they copy at least one spell" | Trust LUA/wiki |
| Spells/Cast bump when recharge >= 60 f | Wiki Wand Generation: "70 % to +1" | WG (Lua) always +1, repeat 70 %; wiki Wands: guaranteed > 1 | Trust WG |
| Leftover-capacity roll | WG "99.5 %" | Wiki 0.5994006 % skip = 995/1001 | 995/1001 (UNVERIFIED) |
| Tier-3 mana example | WG "460 +-50" | Formula 50 + 450 +-50 = 500 +-50 | Formula (range 450-550) |
| IF_PROJECTILE | WM omits radius | Lua: 160 px radius | 160 px |
| Modifier / spell counts | WM 179 modifiers (491 Lua entries) | spells.json 143 (422 catalogue) | Catalogue for gameplay, Lua only for cross-checks |
| Distribution density | Wiki formula condition "abs(x-mean) > (max-min)/2" | Same wiki page, shape = pow(sin(pi((x-mean)/(max-min) + 0.5)), sharpness) | Inequality looks inverted: use a sine bump of half-width (max-min)/2 around `mean`, truncated to [min, max]; sharpness 0 = uniform (UNVERIFIED) |

## Our simplifications (MVP)
- **S1** All cards count as identified (no free first use); the identification system is out of scope. Decision: keep it that way.
- **S2** `order_deck` shuffle draws from the seeded `spells` RNG stream (benchmark.md DET-R04, spells.md SPELL-R43; never frame-number seeds) with the uniform algorithm of R11; Noita's exact permutations are not reproducible (engine RNG). Same seed + actions => same casts.
- **S3** Spells are data (`spells.json`) plus a small set of hand-coded kinds (Divide, Add Trigger family, Greek, Refresh, Duplicate, Requirement, Random). We never interpret Nolla's Lua. The card API must already support `call(card, level, iter)` and the single global `dont_draw` flag so Greek/Divide arrive later without refactoring.
- **S4** Stage 1 implements R01-R64, R70-R72, R80, R81 (all four Divides), R82 (three Add spells), R86; Greek letters, Duplication, Requirement, Zeta and the random-draw spells are stage 2. mvp50.json contains none of the stage-2 spells.
- **S5** Engine-side timing (R51 reloading rule, R53 clamp and no-projectile rule, R54 concurrency) follows the wiki. DECISION-NEEDED WD1: confirm "deck empty at end of click => recharge" for root-draw underflow.
- **S6** Always Cast perk, Unlimited Spells perk, Spell Refresher pickup: the perk hooks exist as booleans on the wand/player, the pickups come with the perk system. DECISION-NEEDED WD2: expose Unlimited Spells in benchmark tasks? (It changes Divide-chain counts, KV-05.)
- **S7** Requirement spells that read the world (IF_ENEMY, IF_PROJECTILE, IF_HP) must count entities in a deterministic order; IF_HALF is one global flag in Noita (shared by all wands): keep it global and include it in the state hash. DECISION-NEEDED WD3 (post-MVP): keep global or make it per-wand.
- **S8** Wand generation is implemented after the casting core; benchmark tasks may use fixed hand-made wands. DECISION-NEEDED WD4: use the "better wand" tables for early biomes or only the normal tables.
- **S9** The 69 Lua-only actions are ignored. Plicate spells (I/Y/T/W/QUAD/PENTA/HEXA_SHOT, utility, 1 draw, copies cost mana) are not specified here.
- **S10** Cast delay/recharge counters tick once per simulation frame; the wand is "ready" when both are <= 0; one click per frame at most.

## Open questions
1. Engine behaviour when the wand's own draw hits an empty deck, exact definition of "projectile" for the no-projectile cast-delay exemption (static/material/payload-only?), and whether the 1-frame clamp is applied by rounding. All wiki-only (R51, R53, WD1).
2. Order of always-cast play versus the first `order_deck`/mana snapshot (engine; assumed AC first).
3. Exact Formation/pattern geometry and projectile ordering for `pattern_degrees` (engine; see conflicts table). Needed once formations are rendered.
4. Local copy of `gun_procedural.lua` is missing: generation numbers (R90-R95, mixtures) rest on earlier research plus the wiki; re-fetch from NathanSnail/noitadata to verify the spells/cast bump, fast-archetype random terms, tier-10 mana level (does the 11 feed the mana formula?), RandomDistribution density.
5. In-game confirmation of finite-uses Divide chains (KV-05) and of the stale-`start_reload` edge (a wrap followed by `reloading` in the same click leaves `start_reload` set for the next click).
6. Which of the 69 Lua-only actions matter (none needed for the benchmark so far); Zeta, Copy Random/Random spells, Chain Spell re-spawn count (resolved in spells.md KN-1: 4 respawns = 5 generations; WM's 5 counts generations) are specified elsewhere or not at all.
7. Licence of the `salinecitrine/noita-wand-simulator` code is not recorded in `rust-prior-art.md`; treat as REF only. The hosted simulator (tinker-with-wands-online.vercel.app) is a usable black-box oracle for extra vectors.

## Sources
Research files (`.trellis/tasks/10-16-noita-cogbench/research/`): `wand-mechanics.md`, `wand-cast-test-cases.json`, `wand-stats.json`, `wand-generation.md`, `spells.md` (§4-§6), `spells.json`, `spell_behaviors_from_gun_actions.json`, `spell_actions_lua.json`, `mvp50.json`, `rust-prior-art.md`, `raw/game/gun.lua`, `raw/game/gun_actions.lua`, `raw/game/gun_enums.lua`, `raw/game/gunaction_generated.lua`, `raw/Guide_Wand_Mechanics.wikitext`, `raw/Expert_Guide:_Draw.wikitext`, `raw/Expert_Guide:_Calling_and_Recursion.wikitext`, `raw/Expert_Guide:_Divide_By_Spells.wikitext`, `raw/Expert_Guide:_Add_Trigger_Series.wikitext`, `raw/Expert_Guide:_Discards_from_the_Hand.wikitext`, `raw/Expert_Guide:_Advanced_Spell_Specifics.wikitext`, `raw/Wand_Refresh.wikitext`, `raw/Wands.wikitext`, `raw/Wand_Generation.wikitext`, `raw/Wand_and_Spell_Tiers.wikitext`, `raw/Trigger.wikitext`, `raw/Timer.wikitext`, `raw/Expiration_Trigger.wikitext`, `raw/Formation.wikitext`, `raw/Tuple_Spell.wikitext`, `raw/Plicate_Spell.wikitext`, `raw/Omega.wikitext`, `raw/Mu.wikitext`, `raw/Spell_Duplication.wikitext`, `raw/Requirement.wikitext`, `raw/Always_Cast_(Perk).wikitext`, `raw/Guide:_Single_Cast_and_Instant_Recharge.wikitext`, `raw/Tool:_Noita_Wand_Simulator.wikitext`.
Wiki (noita.wiki.gg, `?action=raw`): https://noita.wiki.gg/wiki/Guide:_Wand_Mechanics , /Expert_Guide:_Draw , /Expert_Guide:_Calling_and_Recursion , /Expert_Guide:_Divide_By_Spells , /Expert_Guide:_Add_Trigger_Series , /Expert_Guide:_Discards_from_the_Hand , /Expert_Guide:_Advanced_Spell_Specifics , /Wand_Refresh , /Wands , /Wand_Generation , /Wand_and_Spell_Tiers , /Trigger , /Timer , /Expiration_Trigger , /Formation , /Tuple_Spell , /Plicate_Spell , /Omega , /Mu , /Spell_Duplication , /Requirement , /Always_Cast_(Perk) , /Guide:_Single_Cast_and_Instant_Recharge , /Tool:_Noita_Wand_Simulator.
Game data (facts only, code not reproduced): NathanSnail/noitadata mirror, `data/scripts/gun/gun.lua`, `gun_actions.lua`, `gun_enums.lua`, `gunaction_generated.lua` (local copies under `research/raw/game/`).
