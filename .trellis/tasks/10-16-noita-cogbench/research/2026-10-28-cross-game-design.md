# Cross-game growth: design (2026-10-28, approved)

Status: approved by the user on 2026-10-28 (all three open choices as proposed); being built. Replaces the `not_measured` entry `cross_game_gain` in
`eval/metrics/unmeasured.py`.

## Sources

- Capability graph section 4: N2 cross-game is "the same kind of encounter does better in later
  games"; C4 is "games 2 and 3 of a rule-seed family against game 1: depth, harm, decision
  efficiency".
- PRD 2.5: memory across games is only the workspace; the map changes every game, the rules do not.
- PRD AC8: a control family empties the workspace before every game.

## Where it is computed

In the profile of every game `k >= 2` of a family folder (`runs/<name>/run-NN/`), against game 1
of the same folder (the lowest `run-NN`). Game 1 and single runs: `not_measured` ("no earlier game
of the family"). Game 1's encounter results are recomputed from its recording by the same
evaluator (never read from an old `profile.json`). Refused (`not_measured` with the reason) when
the two games differ in rule seed or model, or game 1 is missing or unreadable.

## Shared rule: from two numbers to a value

For a score bounded by 0..1 (a scene, the depth score / 100), with `a` = game 1 and `b` = game k:

- `b >= a`: `g = (b - a) / (1 - a)`, the share of the room to improve that was used;
- `b < a`: `g = (b - a) / a`, the share of game 1's score that was lost;
- `a = b = 1` is skipped (nothing to gain, nothing lost); `a = b = 0` gives `g = 0`.

For an unbounded cost where less is better (HP lost, decisions spent), `g = (a - b) / max(a, b)`,
0 when both are 0.

`g` lies in -1..1. The metric value is `(1 + mean g) / 2`: 0.5 = no change, 1 = all the room
used, 0 = everything lost. Mapping no change to 0.5 (not 0) keeps map noise from looking like
growth: on new maps a scene goes up or down by chance, and clamping losses to 0 would turn that
chance into a positive score.

## Metrics

1. `cross_game_gain` (N2, weight 1). One opportunity per encounter id scored in both games (the
   mean of its scored visits in each game; any variant). Scenes game 1 never reached are not
   compared (depth covers them).
2. `growth_depth` (C4). Depth score of game k against game 1. One opportunity.
3. `growth_harm` (C4). HP lost (player `damage` events) from the start until the player first
   reached the shared depth `d* = min(depth_1, depth_k)`. Less is better. One opportunity; not
   measured when `d*` < 5 (no shared stretch worth comparing).
4. `growth_pace` (C4). Decisions spent until first reaching `d*`. Fewer is better. One
   opportunity, same condition.

C4 = mean of the three growth metrics (the usual capability mean); C = mean of C1..C4 as today.
Comparing over the shared stretch keeps a game that died early from looking efficient (few
decisions) or careful (little harm).

## Family view

`python -m noitabench eval runs/<family>` (a family folder) evaluates every `run-NN`, writes each
`profile.json` and a `family_profile.json` (`cogbench-family-profile/0`): per game the composite,
depth, HP lost, decisions, end reason; per encounter id its score in each game; the four metrics
of each later game and their mean. `--control runs/<control family>` adds, for a control family
with the same model, rule seed and world seeds (so the same caves), the paired difference
`memory effect = growth(family) - growth(control)` per metric. Display only, not scored: a control
doubles the cost and is not always run. The report page shows it later; the command prints a table.

## Example

Game 1: E02 0.40, E16 1.00, E08 0.60, depth 30, 80 HP lost and 200 decisions to depth 30.
Game 3: E02 0.85, E16 1.00, E08 0.30, depth 65, 40 HP lost and 120 decisions to depth 30.

- `cross_game_gain`: E02 g = 0.45 / 0.60 = 0.75; E16 skipped (1.00 both times); E08 g = -0.30 /
  0.60 = -0.5; mean 0.125 -> value 0.5625 (2 opportunities).
- `growth_depth`: g = 35 / 70 = 0.5 -> 0.75. `growth_harm`: g = 40 / 80 = 0.5 -> 0.75.
  `growth_pace`: g = 80 / 200 = 0.4 -> 0.70. C4 = 73.

## Effects

- Game 1 and every single run: unchanged composites (C4 stays unscored).
- Games 2+: N2 gains one metric, C4 gets a score, so C and the composite move.
- No new recording fields: depth, damage events, decisions and encounter results already exist.

## User decisions (2026-10-28)

1. No change = 0.5.
2. The baseline is game 1 only.
3. A control family is supported in the family view and run only when the budget allows.
