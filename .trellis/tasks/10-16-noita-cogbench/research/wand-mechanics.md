# Noita Wand Mechanics — implementation-grade reference

Status: researched 2026-10-07. Primary sources are (1) the noita.wiki.gg guides/pages (raw wikitext saved under `raw/`), and (2) the game's own Lua casting script `data/scripts/gun/gun.lua` plus the spell table `data/scripts/gun/gun_actions.lua` and the generator `data/scripts/gun/procedural/gun_procedural.lua`, read from the public mirror `NathanSnail/noitadata` (commit state 2025-10-21). The Lua files are Nolla Games' copyrighted game data and are **not** copied into this repo; everything below is a paraphrase / pseudocode. Where the wiki and the Lua disagree or where behaviour lives in the (closed) C++ engine, it is marked **UNVERIFIED** or **ENGINE**.

Everything marked VERIFIED(lua) was read directly from gun.lua / gun_actions.lua. VERIFIED(wiki) means stated on the wiki but not independently confirmed in source.

Conventions:
- Noita runs its simulation at **60 frames per second**; every time quantity in the Lua is in **frames**. The UI shows seconds = frames / 60. (VERIFIED: wiki "Spells" page footnote + gun_actions values, e.g. Spark Bolt `fire_rate_wait + 3` ↔ wiki "0.05 s".)
- Damage in the Lua / projectile XML is in **internal units**; the UI shows **internal × 25** (e.g. Damage Plus adds `0.4` internally ↔ "+10" on the wiki; Divide By 10 adds `-1.5` ↔ "-37.5"; Heavy Shot `+1.75` ↔ "+43.75"). VERIFIED by cross-checking three spells.
- Internally spells are called **actions**, the item you pick up is a **card**, the wand is a **gun**, multicasts are `ACTION_TYPE_DRAW_MANY`, Spells/Cast is `actions_per_round`, Cast Delay is `fire_rate_wait`, Recharge Time is `reload_time`, Capacity is `deck_capacity`, Shuffle is `shuffle_deck_when_empty`. (VERIFIED lua + wiki "Modding: Making a custom spell".)

---

## 1. Wand (gun) data model

### 1.1 Engine component fields (AbilityComponent) — VERIFIED(wiki docs page)

| Field | Type | Default | Meaning |
|---|---|---|---|
| `mana` | float | 0 | current mana |
| `mana_max` | float | 100 | Mana Max stat |
| `mana_charge_speed` | float | 10 | Mana Charge Speed stat, mana per second (regen is `mana_charge_speed/60` per frame; VERIFIED wiki) |
| `gun_config.actions_per_round` | int | 1 | Spells/Cast |
| `gun_config.shuffle_deck_when_empty` | bool | false | Shuffle |
| `gun_config.reload_time` | int (frames) | 40 | Recharge Time (base) |
| `gun_config.deck_capacity` | int | 2 | Capacity |
| `gunaction_config.fire_rate_wait` | int (frames) | 0 | Cast Delay (base; stored in the wand's *base shot state*) |
| `gunaction_config.spread_degrees` | float | 0 | Spread (base) |
| `gunaction_config.speed_multiplier` | float | 1.0 | hidden Speed Multiplier (base) |
| `gun_level` | int [1,10] | 1 | wand tier |
| `reload_time_frames`, `mReloadFramesLeft`, `mReloadNextFrameUsable`, `mNextChargeFrame` | int | 0 | engine-side timers (recharge countdown / next usable frame) |
| `item_recoil_*` | float | — | visual recoil of the held item |
| permanent actions ("Always Cast") | list of action ids | — | stored on the wand's inventory as *permanent* cards (`AddGunActionPermanent` in the generator) |

The Lua side receives the first eight of these through `ConfigGun_ReadToLua` (gun) and `ConfigGunActionInfo_Copy(state_from_game, c)` (base shot state). Defaults in `ConfigGun_Init`: `actions_per_round=1, shuffle=false, reload_time=40, deck_capacity=2`. (VERIFIED lua `gun_generated.lua`.)

### 1.2 Wand stats, units, and typical ranges

| UI stat | Internal | Unit | Generated range (normal wands) | Hard limits | Notes |
|---|---|---|---|---|---|
| Shuffle | `shuffle_deck_when_empty` | bool | ~61–90 % of wands are shuffle depending on tier (non-shuffle forced with prob `15+6·tier %`, else requires capacity ≤ 9 and cost `15+5·capacity`) | — | Non-shuffle is "better" and costs generation budget. VERIFIED(lua gun_procedural) |
| Spells/Cast | `actions_per_round` | int | 1–5 from distribution; forced ≥2 (often much higher) if `reload_time ≥ 60` frames; clamped to `[1, deck_capacity]` | 1..26 in practice | Cannot be modified by spells. VERIFIED(lua) |
| Cast Delay | `fire_rate_wait` | frames (UI: s) | distribution over −15..50, min = `16 − cost` | engine clamps result ≥ 1 frame per cast (ENGINE, wiki) | Spells add/subtract/set it on the *root* shot state only |
| Recharge Time | `reload_time` | frames (UI: s) | distribution over 1..240, min = `60 − 5·cost` | negative treated as 0 (wiki) | Spells add to the global `current_reload_time` from anywhere, incl. trigger payloads |
| Mana Max | `mana_max` | mana | `50 + 150·tier + 10·R(−5,5)`; ×3 for "slow" wands (17 %), ÷3 for "fast" wands (15 %); floor 50 | — | VERIFIED(lua) |
| Mana Charge Speed | `mana_charge_speed` | mana/s | `50·tier + R(−5, 5·tier)`; ÷5 slow, ×5 fast; floor 10 | — | VERIFIED(lua) |
| Capacity | `deck_capacity` | slots | distribution 1..20, then leftover budget → `+cost/5` (shuffle) or `+cost/10` (non-shuffle); clamp [2,26] with a 1/10001 chance to skip the clamp (max 62 NG / 66 Nightmare) | — | VERIFIED(lua) |
| Spread | `spread_degrees` | degrees | distribution −35..35 (91 % within −5..10) | total spread < 0 behaves as 0 (wiki) | Applies only to the root shot, not trigger payloads |
| Speed Multiplier (hidden) | `speed_multiplier` | × | 0.8–1.2 (96 %), 0.5–1 (2 %), 1–2 (2 %), 1–10 (0.05 %) | spells clamp product to [0, 20] | Starts the root shot state's `speed_multiplier` |
| Always Cast | permanent action(s) | 0–4 ids | 4 % natural chance (+ all "rare" 5 % wands); AC perk adds one, max 4 | 4 | see §8 |

Starter wands (wiki "Wands" page, VERIFIED wiki): combat wand = non-shuffle, 1 spell/cast, cast delay 0.15–0.25 s (9–15 frames), recharge 0.33–0.47 s (20–28 frames), mana max 80–130, charge 25–40 /s, capacity 2–3, spread 0, speed 1. Bomb wand = shuffle, 1/cast, cast delay 0.05–0.13 s, recharge 0.02–0.17 s, mana 80–110, charge 5–20, capacity 1.

Full generation algorithm with every distribution: see `wand-generation.md` and `wand-stats.json`.

---

## 2. Spell (action) data model — VERIFIED(lua)

Every spell is a Lua table in `gun_actions.lua` (491 entries incl. unlisted/debug; the wiki lists 422 player-obtainable). Fields that matter for casting:

| Field | Meaning |
|---|---|
| `id` | upper-case identifier, e.g. `LIGHT_BULLET` |
| `type` | one of `PROJECTILE(0)`, `STATIC_PROJECTILE(1)`, `MODIFIER(2)`, `DRAW_MANY(3)` (= UI "Multicast"), `MATERIAL(4)`, `OTHER(5)`, `UTILITY(6)`, `PASSIVE(7)` |
| `mana` | mana drain; **if absent the default is 10** (`ACTION_MANA_DRAIN_DEFAULT`); may be negative (Add Mana −30, Blood Magic −100, Mana −200) |
| `max_uses` | charges; absent or −1 = unlimited |
| `never_unlimited` | charges not removed by the Unlimited Spells perk (Black Hole etc.) |
| `recursive` | participates in the recursion limit (all Greek letters, Wand Refresh, Spell Duplication, random-spell spells, Giga Nuke, End of Everything) |
| `related_projectiles` | `{entity_xml[, count]}` — used by Add Trigger to build a trigger projectile |
| `custom_uses_logic` | if true, the normal charge decrement is skipped |
| `action()` | the function run when the spell is *called*; mutates the current shot state `c`, may call `draw_actions`, `add_projectile*`, touch `deck/hand/discarded`, `current_reload_time`, `mana` |

Per-card runtime fields added when the wand is loaded: `inventoryitem_id`, `uses_remaining` (−1 unlimited), `deck_index` (slot order), `is_identified`, `permanently_attached` (always-cast copies only).

Per-spell numeric effects for all 491 actions (draw counts, trigger type/payload draw/timer frames, cast-delay and recharge deltas, pattern angle, damage/radius penalties, uses, mana) are in `spell_behaviors_from_gun_actions.json`; wiki-displayed stats for 422 spells are in `spells.json`.

### 2.1 Spell categories by draw behaviour (what "draw" a spell has)

The number a spell *draws* is just how many times its `action()` calls `draw_actions(n, true)` (plus the payload draws of its triggers, which go into a *separate* shot). Statistics over gun_actions.lua (VERIFIED):

| Category | Draw | Count | Notes |
|---|---|---|---|
| Projectile / Static projectile / Material / Passive, no trigger | 0 | most | just `add_projectile` + stat deltas |
| Projectile with trigger (`…_TRIGGER`, `…_TIMER`, death-trigger) | 0 on the parent shot; payload shot draws **1** (Spark Bolt With Double Trigger: **2**, Delayed Spellcast: **3**) | 26 actions | payload = `draw_shot(create_shot(n), instant_reload=true)` |
| Modifier | 1 | 179 modifiers, of which 160 call `draw_actions(1,true)`; 19 do not (e.g. `HIGH_EXPLOSIVE`, `PENETRATE_WALLS`, `DAMAGE_FRIENDLY`, `GORE`, `BLINDNESS`, `TELEPORTATION`, `POLYMORPH`, `BERSERK`, `CHARM`, `ACID`, `DUCK`, `SHEEP`, `BEE`, `MISFIRE`, `RANDOM_MODIFIER`, …) | a modifier that draws 0 "ends" the chain |
| Multicast (`DRAW_MANY`) | 2 / 3 / 4 / 8 / `#deck` (Myriad) | 14 | Tuple 2,3,4,8,X; Scatter 2,3,4; Formations I=2, Y=2, T=3, W=3, Pentagon=5, Hexagon=6 |
| Utility / Other | varies | — | Add Mana is a MODIFIER (draw 1). Requirement spells draw 1. Greek letters: Alpha/Gamma/Tau/Omega/Phi draw 0, **Mu and Sigma draw 1 at the end**. Divide By: 0 (copies). Add Trigger: 0 (builds a payload shot that draws 1). Wand Refresh: 0. |

Net effect on the draw budget: a projectile costs 1 draw and gives 0 back; a modifier costs 1 and gives 1 (net 0); a Double Spell costs 1 and gives 2 (net +1). (VERIFIED wiki "Tuple Spell" + lua.)

---

## 3. Shot state — VERIFIED(lua `gunaction_generated.lua`)

A *shot state* (`ConfigGunActionInfo`, Lua global `c`) is a bag of modifiers that the engine applies to every projectile spawned while that state is current. Each wand click creates one **root** shot state initialised from the wand's `gunaction_config` (so it starts with the wand's `fire_rate_wait`, `spread_degrees`, `speed_multiplier`); every **trigger payload** creates a fresh shot state initialised to the *zero defaults below* (so wand spread/cast-delay/speed do **not** leak into payloads).

Defaults: `fire_rate_wait=0, speed_multiplier=1.0, child_speed_multiplier=1.0, dampening=1, explosion_radius=0, spread_degrees=0, pattern_degrees=0, screenshake=0, recoil=0, damage_melee_add=0, damage_projectile_add=0, damage_electricity_add=0, damage_fire_add=0, damage_explosion_add=0, damage_ice_add=0, damage_slice_add=0, damage_healing_add=0, damage_curse_add=0, damage_drill_add=0, damage_null_all=0, damage_critical_chance=0, damage_critical_multiplier=0, explosion_damage_to_materials=0, knockback_force=0, reload_time=0, lightning_count=0, material="", material_amount=0, trail_material="", trail_material_amount=0, bounces=0, gravity=0, light=0, blood_count_multiplier=1, gore_particles=0, ragdoll_fx=0, friendly_fire=false, physics_impulse_coeff=0, lifetime_add=0, sprite="", extra_entities="", game_effect_entities="", sound_loop_tag="", projectile_file=""` plus bookkeeping (`action_draw_many_count`, `state_cards_drawn`, …).

Global (not per shot state): `current_reload_time` (recharge), `mana`, `shot_effects.recoil_knockback` (recoil), `dont_draw_actions`, `force_stop_draws`, `recursion_limit = 2`. (VERIFIED lua; wiki "Global values".)

Projectile spawning order and formation: the engine spawns all projectiles registered to a shot state when that shot finishes (`SetProjectileConfigs`). If `pattern_degrees > 0` they are spread evenly over that arc (see §9.2).

---

## 4. The card game: Deck / Hand / Discard — VERIFIED(lua)

Three ordered lists of cards:

- **deck** — cards still available to draw, in cast order (slot order for non-shuffle; random for shuffle).
- **hand** — cards played during the *current* click. Cards stay in the hand for the whole click (so they cannot be drawn twice unless Wand Refresh moves them).
- **discarded** — cards already used (or skipped) this cycle.

Operations:

| Operation | What it does |
|---|---|
| **draw** (`draw_action`) | pop `deck[1]`; if mana insufficient or `uses_remaining == 0` → push to **discarded**, return *failure* (no mana spent); else subtract mana, push to **hand**, run `action()` (= *play*). |
| **play / call** (`play_action`) | push card to hand, set it current, run `action()`; if its type is PROJECTILE / STATIC_PROJECTILE / MATERIAL set `got_projectiles=true` and apply perk "extra modifiers" to `c`. |
| **call only** (`data.action(rec, iter)`) | used by copy spells (Divide, Greek letters, Add Trigger, Spell Duplication): runs the action **without** drawing, without mana, without going to the hand, without the mana/uses checks. |
| **wrap** (inside `draw_action`) | deck empty **and** the draw was requested by a spell (`instant_reload_if_empty=true`) **and** `force_stop_draws==false` → move **all discarded → deck** (append in discard order), `order_deck()` (sort by slot or shuffle), set `start_reload=true`, then continue drawing from the new deck. |
| **end of click** (`_handle_reload`) | move **hand → discarded** (decrementing uses, see §7); then if `not reloading and (deck empty or start_reload)` → move discarded → deck, `order_deck()`, **StartReload(current_reload_time)**, reset `current_reload_time = gun.reload_time`. |
| **order_deck** | non-shuffle: stable sort by `deck_index`; shuffle: uniform random permutation, RNG seeded with `(frame, frame)` (`SetRandomSeed(GameGetFrameNum(), GameGetFrameNum())`), so the shuffle is deterministic for a given world seed + frame. |

---

## 5. The draw algorithm, exactly — VERIFIED(lua)

```
draw_action(instant_reload_if_empty) -> bool:
    state_cards_drawn += 1
    if deck is empty:
        if instant_reload_if_empty and not force_stop_draws:
            move_discarded_to_deck(); order_deck(); start_reload = true      # WRAP
        else:
            reloading = true; return true                                   # root draw hit empty deck: stop
    if deck not empty:
        card = deck.pop_front()
        cost = card.mana ?? 10
        if cost > mana:            discarded.push(card); return false        # skip, no mana spent
        if card.uses_remaining == 0: discarded.push(card); return false      # skip
        mana -= cost                                                        # may go negative-cost → mana increases
    if card: play_action(card)     # push to hand, run action (which may recursively draw)
    return true

draw_actions(how_many, instant_reload_if_empty):
    if dont_draw_actions: return                     # copies made by Divide/Omega/Mu/Phi/Sigma/AddTrigger-modifiers
    c.action_draw_many_count = how_many
    if playing_permanent_card and how_many == 1: return      # ALWAYS-CAST RULE: an AC modifier draws nothing
    for i in 1..how_many:
        ok = draw_action(instant_reload_if_empty)
        if not ok:                                   # the drawn card was skipped: keep trying the next cards
            while deck not empty:
                if draw_action(instant_reload_if_empty): break
        if reloading: return
```

Consequences (all VERIFIED unless noted):
1. **Skipping costs no draw** — a card skipped for mana/charges is discarded and the *next* card is tried for the same draw — **except** when the skipped card was the last in the deck: then the draw is spent (the `while` loop ends with the deck empty, and the deck is *not* wrapped because the retry loop only runs while cards remain). This matches the wiki "draw_retry" note.
2. **The wand's own Spells/Cast never wraps** (root shot is drawn with `instant_reload_if_empty=false`); only draws requested by spells (`draw_actions(n, true)`) and trigger payloads can wrap. After a spell-triggered wrap, the remaining root draws continue from the refilled deck (wiki example: 3×Chainsaw + Spark Bolt + Light on a 3/cast wand).
3. A wrap can only pull in cards that are in **discarded** at that moment — normally cards from *previous* clicks (the current click's cards are in the hand). Divide By, Add Trigger and Requirement spells push cards straight to discarded, so they can be wrapped into within the same click.
4. A wrap always sets `start_reload`, so the click ends with a recharge even though the deck is no longer empty. Wand Refresh's wrap does **not** (it sets `force_stop_draws`, see §12).
5. Once the root shot has drained the deck (`reloading=true`), every further `draw_actions` loop returns after its first iteration. **ENGINE/UNVERIFIED:** in this specific case `_handle_reload`'s guard `not reloading` prevents the Lua from calling `StartReload`; the wiki states the wand *does* recharge after e.g. a 2/cast wand casts its single remaining spell ("alternates between two Spark Bolts and a single Spark Bolt"), so the C++ side must start the recharge itself when the deck is empty. **Recommended implementation: treat "deck empty at end of click" as a recharge regardless of how it became empty.**

---

## 6. Mana — VERIFIED(lua) unless noted

- Mana is checked and deducted **at draw time**, per card, in evaluation order: `if cost > mana → skip`, else `mana -= cost`. Zero-cost spells always pass. Negative-cost spells (Add Mana −30, Blood Magic −100, Mana −200) *add* mana (`mana -= (−30)`), and because `cost > mana` is false for any negative cost they are never skipped.
- Copies (Divide copies, Greek-letter calls, Add-Trigger-called modifiers, always casts) cost **nothing**; only the copying spell's own drain is paid. Exception: always casts with negative cost do add mana (`handle_mana_addition`).
- Trigger payload spells are drawn (and paid for) **at cast time**, before the projectile ever hits anything; the payload is cast at no extra cost each time a piercing trigger re-fires; if the trigger never fires the mana is lost (wiki).
- Insufficient-mana behaviour with a trigger: the trigger's own cost is checked first; if the trigger itself is too expensive it is skipped and the cheaper following spells are cast *without* the trigger. Wiki worked example Homing(70) → Spark Bolt(5): mana ≥ 75 both; 70 ≤ mana < 75 Homing only; 5 ≤ mana < 70 Spark Bolt only; < 5 nothing. (Follows directly from the per-card check.)
- `mana` can exceed `mana_max` *during* a click (Add Mana); at the start of each click the engine hands Lua `min(mana, mana_max)` (ENGINE, wiki "Global values").
- Regeneration: `+mana_charge_speed/60` per frame, every frame, even while the wand is not held, capped at `mana_max` (ENGINE, wiki).
- Mana To Damage (`DAMAGE_FOREVER`): if `mana > 50`: `damage_projectile_add += 0.025·(mana − 50)` (×25 → +0.625 dmg per mana), then `mana = 50`.
- Mu/Phi/Sigma snapshot `mana`, `c.fire_rate_wait`, `current_reload_time` before calling copies and restore them after (so copied Mana To Damage is free).

---

## 7. Charges ("uses") — VERIFIED(lua `move_hand_to_discarded`)

- A card with `uses_remaining == 0` is skipped at draw time (no mana spent, no draw spent unless last in deck) and goes to discarded, so it stays on the wand and is wrapped into harmlessly.
- Normal consumption happens **at end of click, when the hand is moved to discarded**, for each card in the hand with `uses_remaining > 0` and no `custom_uses_logic`, **only if** (`got_projectiles` is true for this click) **or** the card's type is OTHER or UTILITY. `got_projectiles` becomes true when any PROJECTILE / STATIC_PROJECTILE / MATERIAL card was *played via the hand* this click. Therefore a limited-use modifier (Matter Eater, Myriad Spell) cast alongside only Notes / Long-Distance Cast / copies is free (wiki "Discards from the Hand").
- The engine callback `ActionUsesRemainingChanged` can veto the decrement (Unlimited Spells perk); `never_unlimited` spells ignore the perk.
- Cards that reach 0 uses while in the hand are **removed** (not discarded) — they vanish from the cycle until the wand is re-equipped; always-cast copies (`permanently_attached`) are likewise never discarded.
- Divide By and Add Trigger decrement their **target's** uses manually (once per Divide instance, regardless of copy count) and check `uses_remaining ~= 0` before copying; Greek letters, Omega, Mu, Phi, Sigma, Spell Duplication and Copy Random Spell do not check or decrement (Copy Random Spell decrements manually per wiki).
- Always-cast copies are created with `uses_remaining = -1` (unlimited).

---

## 8. Always Cast — VERIFIED(lua `_play_permanent_card`) + wiki

- An always-cast spell is a wand-level permanent action id. On every click the engine calls `_play_permanent_card(id)` for each AC **before** the wand's own `actions_per_round` draws (wiki: "added to the front of the block"; call order ENGINE-side, UNVERIFIED but consistent with the `playing_permanent_card` logic).
- Mechanics: clone the action, mark `permanently_attached=true`, `uses_remaining=-1`, add its mana only if its cost is **negative** (`handle_mana_addition`), then `play_action` directly — **no** mana check, **no** deck involvement; the copy goes into the hand and is dropped (not discarded) at end of click.
- While `playing_permanent_card` is true, any `draw_actions(1, …)` is a no-op. So an AC modifier modifies the shot and draws nothing extra; an AC trigger projectile with payload draw 1 (`…_TRIGGER`) gets an **empty** payload; AC Spark Bolt With Double Trigger (draw 2) and AC Delayed Spellcast (draw 3) *do* draw, and inside that nested draw every draw-1 spell (modifiers, Mu, Sigma, Requirement…) draws 0 — exactly the wiki's description.
- AC spells apply to the root shot state only (never inside trigger payloads). Formation multicasts set `pattern_degrees` which also affects AC projectiles.
- Natural ACs come from generation (4 % chance, or every "rare" wand): 77 % modifier, 8 % modifier (counted as "good card"), 8 % static projectile, 7 % projectile, chosen one tier above the wand (VERIFIED lua `wand_add_random_cards`). The AC perk adds a random one (43 % random modifier, 6×8.33 % fixed modifiers, 3.5 % static, 3 % projectile, 0.5 % utility) up to 4 total (wiki).

---

## 9. Multicast, formations, Divide By

### 9.1 Multicast (`DRAW_MANY`) — VERIFIED(lua)

`action()` = `draw_actions(N, true)` (+ stat tweak). The N drawn cards share the *current* shot state, so every modifier drawn by (or before) the multicast applies to every projectile drawn by it. Cast delay of all of them sums into the same `c.fire_rate_wait`. Wrapping may occur during the N draws.

| Spell | id | draw | mana | extra |
|---|---|---|---|---|
| Double / Triple / Quadruple / Octuple | BURST_2/3/4/8 | 2/3/4/8 | 0/2/5/30 | — |
| Myriad | BURST_X | `#deck` (whatever is left) | 50, 30 uses | draws 0 if deck empty |
| Double/Triple/Quadruple Scatter | SCATTER_2/3/4 | 2/3/4 | 0/1/? | `spread_degrees += 10` each (wiki: +10°) |
| Formation Behind Your Back | I_SHAPE | 2 | 0 | `pattern=180`, spread −5 |
| Formation Bifurcated | Y_SHAPE | 2 | 2 | `pattern=45`, spread −8 |
| Formation Above And Below | T_SHAPE | 3 | 3 | `pattern=90`, spread −8 |
| Formation Trifurcated | W_SHAPE | 3 | 3 | `pattern=20`, spread −5 |
| Formation Pentagon | PENTAGRAM_SHAPE | 5 | 5 | `pattern=180`, spread −12 |
| Formation Hexagon | CIRCLE_SHAPE | 6 | 6 | `pattern=180`, spread −15 |

### 9.2 Formation angle (`pattern_degrees`) — VERIFIED(lua for who sets it; wiki for the geometry)

- It is a **set**, not add: the last writer wins. Formation multicasts set it **after** their draws return; Plicate spells set it after copying but **before** their draw; Divide By sets `5` after copying; Freezing Gaze sets 30 when cast.
- Geometry (ENGINE, wiki): with `n` projectiles in the shot state and formation angle `A` (an arc of ±A around the aim direction): spacing = `A/n` if `A ≥ 180°` (the first and last would coincide at ±180°, so they are spaced as if there were n+1), otherwise spacing = `A/(n−1)`. One projectile always fires straight ahead; otherwise projectiles are placed clockwise in evaluation order starting at the top of the arc. "Behind Your Back" with 2 projectiles = one ahead, one behind.
- Pattern 5 (Divide) = projectiles evenly over a 10° arc.

### 9.3 Divide By (`DIVIDE_2/3/4/10`) — VERIFIED(lua), the exact algorithm

Signature `action(recursion_level, iteration)`; `iter = iteration or 1`.

```
divide_N(rec_level, iteration):
    iter = iteration ?? 1 ; iter_max = iter
    c.fire_rate_wait += FRW_N                      # D2 +20, D3 +35, D4 +50, D10 +80 frames
    (D10 only) current_reload_time += 20
    target = deck[iter]  (nil if deck empty or shorter than iter)   # NOTE: the iter-th card, not the first
    count = N ; if iter >= LIMIT_N: count = 1      # LIMIT: D2 5, D3 4, D4 4, D10 3  → "Divide By 1"
    rec = check_recursion(target, rec_level)       # -1 if target is recursive and rec_level >= 2
    if target and rec > -1 and target.uses_remaining != 0:
        saved_frw = c.fire_rate_wait ; saved_reload = current_reload_time
        for i in 1..count:
            if i == 1: dont_draw_actions = true    # FIRST copy cannot draw
            imax = target.action(rec, iter + 1)    # call (no mana, no hand); nested Divide returns its depth
            dont_draw_actions = false              # (note: unconditionally re-enabled after every copy)
            if imax != nil: iter_max = imax
        if target.uses_remaining > 0: decrement uses (engine may veto)
        if iter == 1:                              # only the head of a chain
            c.fire_rate_wait = saved_frw ; current_reload_time = saved_reload   # copies' delays are discarded
            discard deck[1] iter_max times         # drops the whole chain + final target
    c.damage_projectile_add -= PEN_N               # D2 0.2(-5), D3 0.4(-10), D4 0.6(-15), D10 1.5(-37.5) — applied per Divide instance incl. copies
    c.explosion_radius = max(0, c.explosion_radius - RAD_N)    # 5 / 10 / 20 / 40
    c.pattern_degrees = 5
    return iter_max
```
Mana: 35 / 50 / 70 / 200; D10 has 5 uses. All are type OTHER, **not** recursive. Resulting facts (wiki + lua agree): `D10 D10 D4 D2 X` = 800 copies max; iteration limits make later Divides act as ×1 but with draw disabled on their single copy — the standard trick for dividing modifiers; a lone Divide on a modifier produces N+1 instances (the 2nd copy draws the real one) and *discard displacement*; cast delay / recharge of copied spells are discarded (only the chain head's own delta stays); damage penalty applies once per Divide instance evaluated (e.g. D10>D10>Spark Bolt = 11 penalties).

---

## 10. Triggers (hit / timer / death) — VERIFIED(lua)

`add_projectile_trigger_hit_world(entity, n)`, `add_projectile_trigger_timer(entity, delay_frames, n)`, `add_projectile_trigger_death(entity, n)` each do: `BeginProjectile(entity)`; `BeginTrigger…`; **`draw_shot(create_shot(n), instant_reload=true)`**; `EndTrigger`; `EndProjectile`. I.e. the payload is a brand-new shot state (zero defaults, see §3) and its `n` draws happen **immediately at cast time** from the same deck; the payload's cards go into the same hand; wrapping is allowed inside the payload; when the payload draw finishes the parent shot state becomes current again and the parent's remaining draws continue.

| Kind | Fires when | Repeats | Lua |
|---|---|---|---|
| Trigger (hit) | projectile collides with terrain or an entity | every hit for piercing projectiles | `trigger_hit_world` |
| Timer | after `delay_frames` **or** on collision, whichever first; then stops | per enemy hit while piercing within the timer | `trigger_timer(…, frames, n)` |
| Expiration (death) | when the projectile dies (lifetime end, collision death, destroyed) | once | `trigger_death` |

Timer delays (frames): Luminous Drill 4, Spark/Magic/Magic-Bolt timers 10, Add Timer 20, Tentacle 20, Spitter timers 40, Energy Orb timer 100, Energy Sphere timer 200. Payload draw counts: all 1 except Spark Bolt With Double Trigger 2 and Delayed Spellcast 3; Add Trigger/Timer/Expiration always create draw-1 payloads.

Isolation (wiki, consistent with the lua): everything in `c` is per shot state (cast delay, spread, speed, damage adds, crit, pattern…). Shared across payloads: `current_reload_time`, `mana`, `shot_effects.recoil_knockback`. The payload's `fire_rate_wait` is passed to the engine but ignored for the wand's cast delay (ENGINE, wiki). If the trigger projectile's speed is ~0 the payload speed is set to 0 (ENGINE, wiki).

Chain Spell (`CHAIN_SHOT`) is **not** a trigger: it is a modifier (mana 70, draw 1) that appends `chain_shot.xml` to `extra_entities`, `lifetime_add −30`, damage −5 (×25), radius −5, spread +10. The engine-side entity re-spawns the projectile up to 5 times on expiry, each copy **without** any of the modifiers and with the projectile's default lifetime (ENGINE, wiki).

### 10.1 Add Trigger / Add Timer / Add Expiration Trigger — VERIFIED(lua)

```
add_trigger_kind():                               # mana 10 / 20 / 20, type OTHER
    how_many = 1 ; data = deck[1]
    # 1. scan for a target, calling modifiers for free on the way
    while deck.len >= how_many and data.type in {MODIFIER, PASSIVE, OTHER, DRAW_MANY}:
        if data.uses_remaining != 0 and data.id not in {ADD_TRIGGER, ADD_TIMER, ADD_DEATH_TRIGGER}:
            if data.type == MODIFIER: dont_draw_actions = true; data.action(); dont_draw_actions = false
        how_many += 1 ; data = deck[how_many]
    # 2. validate target (PROJECTILE / STATIC / MATERIAL / UTILITY by exclusion)
    if data and data.related_projectiles and data.uses_remaining != 0:
        target = data.related_projectiles[1] ; count = data.related_projectiles[2] or 1
        discard the first how_many cards of the deck (everything scanned + the target)
        valid = any(card.type in {PROJECTILE, STATIC_PROJECTILE, MATERIAL, UTILITY} for card in deck)   # a payload candidate exists
        decrement target uses (engine may veto)
        if valid: for i in 1..count: add_projectile_trigger_hit_world(target, 1)   # (timer: delay 20; death)
        else:     dont_draw_actions = true; data.action(); dont_draw_actions = false   # no payload: call the projectile plainly
    # else: failure — nothing discarded (modifiers were still applied to c)
```
Consequences: modifiers between Add Trigger and its target are applied for free and without draw; the trigger projectile built from `related_projectiles` carries none of the target's cast delay / recharge / crit / spread deltas; multi-projectile targets (`count`>1) get one payload each; failure modes (no target, invalid target — see wiki list of spells with no related projectile — or no payload candidate) are the basis of many "free modifier" builds.

---

## 11. Copy spells and recursion — VERIFIED(lua)

`check_recursion(card, rec)`: if `card.recursive` → return −1 if `rec >= 2` else `rec + 1`; non-recursive cards return `rec` unchanged. A drawn spell starts at 0. All copy spells pass their `rec` to the callee's `action(rec[, iter])`.

| Spell | mana | frw (frames) | Behaviour |
|---|---|---|---|
| Alpha | 40 | +15 | call first of `discarded`, else first of `hand`, else first of `deck` |
| Gamma | 40 | +15 | call last of `deck`, else last of `hand` |
| Tau | 90 | +35 | remember `deck[1]`, `deck[2]` (both looked up before either is called), call each (if recursion ok). Copies *can* draw. |
| Omega | 320 | +50 | with draw disabled: call every card in discarded (rec ok, not `RESET`), then every **non-recursive** card in hand, then every card in deck (rec ok, not `RESET`) |
| Mu | 120 | +50 | snapshot frw/reload/mana; with draw disabled call every MODIFIER in discarded, hand, deck; restore snapshot; then **`draw_actions(1,true)`** (unconditional — cannot be draw-cancelled) |
| Phi | 120 | +50 | same as Mu for PROJECTILE type, no trailing draw |
| Sigma | 120 | +30 | same as Mu for STATIC_PROJECTILE type, **with** trailing `draw_actions(1,true)` |
| Spell Duplication | 250 | +20, reload +20 | call every card in hand (except DUPLICATE) up to the hand size at entry, draw enabled; then draw 1 |
| Zeta, Copy Random Spell, Random Spell… | — | — | recursive; details on wiki pages, not needed for the core |

Copied calls never pay mana, never check or consume uses (except where noted), still add their own cast delay / recharge deltas (unless the caller snapshots them), and can draw unless `dont_draw_actions` is set.

---

## 12. Wand Refresh (`RESET`) — VERIFIED(lua)

```
reset():                               # UTILITY, recursive, mana 20
    current_reload_time -= 25          # (wiki: −0.42 s)
    move all of hand and all of deck → discarded (in that order)
    if not force_stop_draws:           # first Refresh this click
        force_stop_draws = true
        move discarded → deck ; order_deck()      # full wand available again, in slot/shuffled order
    # second Refresh in the same click: everything stays in discarded ⇒ deck empty ⇒ recharge at end of click
```
Because `force_stop_draws` is true afterwards, no further **wrap** can happen this click; and because the hand was emptied by Refresh (not by the normal end-of-click move), **uses are not consumed** and always-cast copies are not dropped (wiki: discarded AC copies stack). If, at end of click, the deck is non-empty and no `start_reload` was set, no recharge happens: this is how Refresh "skips" recharge. Omega never calls RESET.

---

## 13. Requirement spells (`IF_*`) — VERIFIED(lua)

All cost 0 mana, type OTHER, and end with `draw_actions(1, true)`. `IF_ELSE` and `IF_END` do nothing else. `IF_HALF` toggles a **global** flag (`GUN_ACTION_IF_HALF_STATUS`, shared by all wands); `IF_ENEMY` counts `homing_target` entities within 240 px (skip if < 15); `IF_PROJECTILE` counts projectiles (skip if < 20); `IF_HP` skips if HP > 25 %. Scan the deck from the top: stop at the first other `IF_` (endpoint = none), remember the last `IF_ELSE` index, stop at `IF_END`. If skipping: discard deck cards from the top up to the else-point (or the endpoint, or just 1 card if neither). If not skipping and an else-point exists: discard from the else-point to the endpoint (or end of deck). Then draw 1.

---

## 14. Cast delay and recharge timing — VERIFIED(lua) + ENGINE(wiki)

- `c.fire_rate_wait` of the **root** shot state after all draws = wand base cast delay (frames) + Σ deltas of every spell played on the root state (modifiers, multicasts, projectiles, Divide heads, Greek letters…). Spells inside trigger payloads modify the payload's own `fire_rate_wait` and are **ignored** for the wand (wiki). Some spells **set** it: Chainsaw `=0`, Nuke `=20`, Giga Nuke `=50` (they discard everything accumulated so far, so order matters).
- `current_reload_time` starts at the wand's `reload_time` after each recharge, and every spell that touches it (from anywhere, including payloads and copies) adds to it during the whole cycle; it is reported to the engine with every shot and used when `StartReload` fires. After the recharge starts it resets to the base value.
- The recharge starts at the end of a click when the deck is empty or a wrap happened (`start_reload`), unless suppressed by a single Wand Refresh (§12).
- ENGINE (wiki "Wands"): cast delay and recharge run **concurrently**; the wand is usable again after `max(cast_delay, recharge)` — they do not add. A click whose root shot produced **no projectiles** does not wait for the cast delay (it still takes 1 frame). Negative total cast delay ⇒ 1 frame (max 60 casts/s); negative total recharge ⇒ 0. Switching items resets the deck (re-equip ⇒ `_clear_deck`, `first_shot=true` ⇒ reorder/shuffle) but does not cancel a running recharge (wiki).
- `ACTION_DRAW_RELOAD_TIME_INCREASE = 0` (each played card adds 0 recharge frames); "digger"-type spells subtract 10 recharge frames.

---

## 15. Shuffle semantics — VERIFIED(lua)

`order_deck()` shuffles (if `shuffle_deck_when_empty`) or sorts by slot. It is called: (a) on the first shot after the wand was (re)loaded/equipped (`first_shot`), (b) on every wrap, (c) on every recharge, (d) on the first Wand Refresh of a click. It is **not** called per draw — a shuffle wand draws sequentially through one random permutation until the next event. Shuffle permutes every card type (multicasts/modifiers/triggers included). With `actions_per_round ≥ #cards` and no triggers a shuffle wand behaves like a non-shuffle wand. The wand editor always shows slot order, never the current permutation.

---

## 16. Full click pseudocode (what the engine + gun.lua do for one mouse click)

```
on_click(wand, frame):
    if frame < mReloadNextFrameUsable or mReloadFramesLeft > 0: return          # ENGINE: cast delay / recharge
    mana = min(wand.mana, wand.mana_max)                                        # ENGINE snapshot
    # _start_shot(mana)
    dont_draw_actions = false ; force_stop_draws = false
    root = Shot{ state = copy(wand.gunaction_config) ,  draws = wand.actions_per_round }   # base cast delay/spread/speed
    shot_effects.recoil_knockback = 0
    if first_shot: order_deck(); current_reload_time = wand.reload_time; first_shot = false
    got_projectiles = false
    # always casts (ENGINE calls _play_permanent_card for each)
    for ac in wand.always_casts: play_permanent(ac)      # §8
    # _draw_actions_for_shot(true)
    c = root.state ; draw_actions(root.draws, instant_reload=false) ; register(root.state) ; spawn projectiles of root (ENGINE)
    # _handle_reload()
    move_hand_to_discarded()                              # uses consumed here (§7); AC copies & 0-use cards dropped
    if not reloading and (deck.empty or start_reload):
        move discarded → deck ; order_deck()
        StartReload(current_reload_time)                   # ENGINE: mReloadFramesLeft = max(0, current_reload_time)
        current_reload_time = wand.reload_time ; start_reload = false
    [UNVERIFIED engine rule: if reloading (root draw hit an empty deck) also StartReload]
    reloading = false
    wand.mana = mana
    # ENGINE: cast delay
    if root had projectiles: mReloadNextFrameUsable = frame + max(1, root.state.fire_rate_wait) else frame + 1
```
Every frame: `wand.mana = min(mana_max, mana + mana_charge_speed/60)`; `mReloadFramesLeft -= 1`.

---

## 17. Worked example with numbers

Wand: non-shuffle, Spells/Cast 1, Cast Delay 0.17 s (**10 frames**), Recharge 0.50 s (**30 frames**), Mana Max 100, Mana Charge 50/s (0.8333/frame), Capacity 5, Spread 0°, Speed ×1.0, no always cast. Slots: `[BURST_2, DAMAGE, LIGHT_BULLET, LIGHT_BULLET_TRIGGER, SPITTER]`. Mana full (100) at frame 0.

Click 1 (frame 0): deck = slots in order (first_shot ⇒ order_deck).
1. Root draw 1 → `BURST_2` (cost 0, mana 100). hand=[B2]. action: `draw_actions(2, true)`.
   1. draw → `DAMAGE` (5 ≤ 100 → mana 95). c: `damage_projectile_add +0.4` (+10 dmg), `fire_rate_wait +5`, recoil +10. action draws 1:
      - draw → `LIGHT_BULLET` (5 → mana 90). projectile #1; `fire_rate_wait +3`, `spread −1`, crit +5.
   2. draw → `LIGHT_BULLET_TRIGGER` (10 → mana 80). `fire_rate_wait +3`, crit +5; projectile #2 with hit-trigger; **payload shot** (fresh state) draws 1:
      - draw → `SPITTER` (5 → mana 75). payload projectile; payload state `fire_rate_wait −1`, `spread +6` (ignored by the wand).
2. Root draws exhausted. Root state: `fire_rate_wait = 10 + 5 + 3 + 3 = 21 frames` (0.35 s); `spread = 0 − 1 = −1°` (acts as 0); crit +10 %; +10 projectile damage applied to **both** projectile #1 and #2 (not to the Spitter — different state); recoil 10. Engine spawns Spark Bolt (3+10 dmg) and Spark Bolt With Trigger (3+10 dmg), the latter carrying a Spitter (7.5 dmg, its own −1 frame/+6° state) payload.
3. End of click: hand `[B2, DAMAGE, LB, LBT, SPITTER]` → discarded; `got_projectiles` true but none has limited uses. Deck is empty ⇒ **recharge**: `StartReload(30)`; deck rebuilt in slot order.
4. Timing: cast delay 21 frames and recharge 30 frames run concurrently ⇒ next click possible at frame **30** (0.50 s). Mana: 75 + 30·0.8333 = 100 (capped) by frame 30. Total mana spent: 0+5+5+10+5 = **25**.

Variant showing a wrap: same wand but slots `[LIGHT_BULLET, BURST_2, SPITTER, DAMAGE]` (capacity 4).
- Click 1: root draws `LIGHT_BULLET` (mana 95) → 1 Spark Bolt; `fire_rate_wait = 10+3 = 13`; deck `[B2, SPITTER, DAMAGE]` not empty ⇒ **no recharge**; next click at frame 13.
- Click 2 (frame 13, mana 95 + 13·0.833 = 100 capped): root draws `BURST_2` → draws `SPITTER` (mana 95) and `DAMAGE` (mana 90) → Damage draws 1: deck empty, requested by a spell ⇒ **wrap**: discarded `[LIGHT_BULLET]` → deck, `start_reload=true`; draws `LIGHT_BULLET` (mana 85). Root state: `10 + (−1) + 5 + 3 = 17 frames`; projectiles: Spitter (7.5+10) and Spark Bolt (3+10) both with +10 dmg. End of click: `start_reload` ⇒ recharge 30 frames; next click at frame 13 + max(17, 30) = **43**.

---

## 18. Open questions / UNVERIFIED items (for the benchmark harness)

1. Engine behaviour when the **root** draw hits an empty deck (`reloading=true`): the Lua does not call `StartReload`; the wiki says the wand recharges. Implement "deck empty at end of click ⇒ recharge" and flag it.
2. Exact engine clamping of negative cast delay (wiki: ⇒ 1 frame) and of negative recharge (wiki: ⇒ 0), and the rule "no projectiles ⇒ no cast delay" — all wiki-only.
3. Whether always casts are played before or after `_start_shot`'s `order_deck` on the first shot — order of `_play_permanent_card` vs. root draws is engine-side (wiki says AC goes in front of the block).
4. Projectile formation geometry (`pattern_degrees`) is engine-side; the wiki formula is reproduced in §9.2.
5. Exact shuffle RNG: Lua `Random(1,i)` seeded by `(frame, frame)` through Noita's world-seeded RNG; the permutation algorithm (pick a random remaining card, append) yields a uniform permutation.
6. The wiki says "1 in 10,000" and the Lua says `Random(0,10000) <= 9999` (1/10001) for the capacity-clamp skip.

## Sources

- https://noita.wiki.gg/wiki/Guide:_Wand_Mechanics?action=raw
- https://noita.wiki.gg/wiki/Wands?action=raw
- https://noita.wiki.gg/wiki/Spells?action=raw
- https://noita.wiki.gg/wiki/Expert_Guide:_Draw?action=raw
- https://noita.wiki.gg/wiki/Expert_Guide:_Discards_from_the_Hand?action=raw
- https://noita.wiki.gg/wiki/Expert_Guide:_Calling_and_Recursion?action=raw
- https://noita.wiki.gg/wiki/Expert_Guide:_Divide_By_Spells?action=raw
- https://noita.wiki.gg/wiki/Expert_Guide:_Add_Trigger_Series?action=raw
- https://noita.wiki.gg/wiki/Expert_Guide:_Advanced_Spell_Specifics?action=raw
- https://noita.wiki.gg/wiki/Tuple_Spell?action=raw (target of the "Multicast" redirect)
- https://noita.wiki.gg/wiki/Trigger?action=raw
- https://noita.wiki.gg/wiki/Timer?action=raw
- https://noita.wiki.gg/wiki/Expiration_Trigger?action=raw
- https://noita.wiki.gg/wiki/Chain_Spell?action=raw
- https://noita.wiki.gg/wiki/Divide_By?action=raw
- https://noita.wiki.gg/wiki/Formation?action=raw
- https://noita.wiki.gg/wiki/Plicate_Spell?action=raw
- https://noita.wiki.gg/wiki/Wand_Refresh?action=raw
- https://noita.wiki.gg/wiki/Add_Mana?action=raw
- https://noita.wiki.gg/wiki/Add_Trigger?action=raw
- https://noita.wiki.gg/wiki/Requirement?action=raw
- https://noita.wiki.gg/wiki/Alpha?action=raw , /Gamma , /Tau , /Omega , /Mu , /Phi , /Sigma , /Greek_Spells
- https://noita.wiki.gg/wiki/Spell_Duplication?action=raw
- https://noita.wiki.gg/wiki/Delayed_Spellcast?action=raw
- https://noita.wiki.gg/wiki/Nolla?action=raw
- https://noita.wiki.gg/wiki/Always_Cast_(Perk)?action=raw ; https://noita.wiki.gg/wiki/Always_Cast?action=raw (disambiguation → Wands#Always Casts)
- https://noita.wiki.gg/wiki/Shuffle?action=raw (redirect → Wands#Shuffle)
- https://noita.wiki.gg/wiki/Spells_with_limited_uses?action=raw
- https://noita.wiki.gg/wiki/Recoil_(stat)?action=raw ; https://noita.wiki.gg/wiki/Speed?action=raw
- https://noita.wiki.gg/wiki/Guide:_Single_Cast_and_Instant_Recharge?action=raw
- https://noita.wiki.gg/wiki/Wand_Generation?action=raw ; https://noita.wiki.gg/wiki/Wand_and_Spell_Tiers?action=raw
- https://noita.wiki.gg/wiki/Modding:_Making_a_custom_spell?action=raw
- https://noita.wiki.gg/wiki/Documentation:_AbilityComponent?action=raw
- https://noita.wiki.gg/wiki/Tool:_Noita_Wand_Simulator?action=raw ; https://noita.wiki.gg/wiki/Tool:_Noita_Wand_Simulator/beta?action=raw
- https://noita.wiki.gg/wiki/Special:CargoExport?tables=Spells&fields=…&format=json&limit=2000 (saved as raw/cargo_spells_export.json)
- https://github.com/NathanSnail/noitadata — data/scripts/gun/gun.lua, gun_actions.lua, gun_enums.lua, gun_generated.lua, gunaction_generated.lua, gunshoteffects_generated.lua, gun_extra_modifiers.lua, procedural/gun_procedural.lua (read via the GitHub API, not stored here)
- https://github.com/salinecitrine/noita-wand-simulator — src/app/calc/gun.ts (TypeScript port of gun.lua), src/app/calc/eval/clickWand.ts
- Pages that were empty/non-existent under the titles given in the task: "Cast delay", "Recharge time", "Mana", "Spell Evaluation Order" (content lives in Wands#Wand Statistics and Expert Guide: Draw).
