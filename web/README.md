# web/ - replay, compare, report, world preview and the human play page

Static pages, plain ES modules, no build step, no third-party code. The pages only read files and draw them;
they contain no game logic. Data formats: `.trellis/spec/backend/contracts.md` sections 2, 4 and 5.

| Page | What it does |
|---|---|
| `index.html` | links, plus demo links to the synthetic fixtures |
| `replay.html` | open a run folder (`meta.json` + `frames.bin`, optional `entities.jsonl`, `events.jsonl`, `decisions.jsonl`, `transcript.jsonl`, `harness.jsonl`, `summary.json`); play, pause, scrub, 0.25x to 8x, zoom; entity and event overlays; a decision timeline and a decision panel (below) |
| `compare.html` | 2 to 4 run folders side by side, one canvas each, played in step by game frame or by decision, one shared timeline (below) |
| `report.html` | the evaluation of one run (`profile.json`): composite, capability profile, encounters, metrics, cost; or 2 to 4 profiles side by side (below) |
| `preview.html` | open a world pair (`name.png` + `name.json`); biome grid, markers, encounter trigger boxes (`must_pass` = solid gold with a star, optional = dashed cyan), optional `main_path` |
| `play.html` | the human baseline: plays one episode through the local play server (below), pause mode, same commands, interrupts, decision budget and recording as an agent |

## Open it

ES modules and `fetch` do not work from `file://`, so serve the **repository root** (the pages read
`../content/materials.json`):

```sh
.venv/bin/python -m http.server 8000      # from the repo root
```

Then open <http://localhost:8000/web/>. In `replay.html` / `preview.html` drop a folder or files on the page, or use
the buttons. A folder holding several runs (or worlds) gets a drop-down to choose one.

Shortcuts for the served files (the query is only an entry point; everything else stays in memory):

- `http://localhost:8000/web/replay.html?src=../runs/<run_id>/` - a recording written by the sim
- `http://localhost:8000/web/replay.html?src=tests/fixtures/rec_synthetic/` - synthetic fixture
- `http://localhost:8000/web/replay.html?src=tests/fixtures/rec_sim/` - a small recording written by the real simulation
- `http://localhost:8000/web/preview.html?world=tests/fixtures/world_synthetic` - synthetic world (path without extension)

`src` and `world` must point at the page's own origin; the pages never request files from other sites (a URL on
another host is refused with a message). If the pages are not served from the repo root, put a copy of
`materials.json` among the files you open.

Controls: drag = pan, wheel / pinch = zoom (steps 1/4, 1/2, 1, 2, 3, 4, 6, 8, 12, 16, 24), hover or tap = cell readout.
Keys: Space play/pause, left/right step, `+` `-` zoom, `0` fit.

## Replay and compare (`replay.html`, `compare.html`)

Both read the same run folder as before and, when they are there, the harness files next to the recording. Nothing is
required beyond `meta.json` and `frames.bin`: a scripted run shows just the map, a human run shows commands and stop
reasons, a harness run shows everything.

| File | Read for |
|---|---|
| `decisions.jsonl` | the timeline (one mark per decision, colour = the stop reason the player was shown, white post = death) and, per decision, the commands and what they did |
| `transcript.jsonl` | the view the player was shown (the `Decision N (frame F ...` text of the `opening` and `results` records), the model's thinking summary, text and tool calls, the tool results, programs and hooks (`code_run`), library installs, helpers (`helper` records and the records with an `agent` field; each helper's own turns are collapsed), briefings (`summary`: a triangle on the timeline, shown on the decision after it) |
| `harness.jsonl` | cost so far (dollars, model calls, helper calls) and the cost, latency and tokens of the model call behind a decision |
| `summary.json` | model, how the run ended and its total cost, in the recording panel (only those fields; the seeds in this file are never copied out) |
| `entities.jsonl` | the player's position, for "follow the player" (on by default: the camera sits on the player at about the zoom whose view is 256 cells wide; dragging the picture or "适应" turns it off) |

How decisions and game frames are tied: decision `i` was asked at frame `frame_i` and ran for `frames_i` frames. Picking a decision
moves the clock to `frame_i`; while it plays the panel follows the clock (the last decision asked at or before the clock; when two
decisions share a frame the picked one stays until the clock moves on). A model turn that runs a program owns all the decisions the
program made, so the panel says "程序的第 k/n 步" and only the last view of a program is printed in full (earlier ones are the truncated
`print` lines the program wrote, labelled as fragments). Keys: `[` and `]` previous and next decision, left and right arrow one recorded step
(or one decision while the timeline has focus).

`compare.html` keeps one shared position: by game frame every run shows the same moment of game time (a run that is over stays on its last
frame); by decision every run shows its n-th decision, however long it took (the n-th line of `decisions.jsonl`, not the `Decision N` the player was shown, which runs ahead of the line count once an `inspect` has cost extra; needs `decisions.jsonl` in every run; one decision lasts
0.5 s at 1x, so 8x is 16 decisions a second). Open runs by dropping 2 to 4 folders on the page, with the buttons, or as
`compare.html?src=../runs/a/&src=../runs/b/`. Each pane has its decision panel folded away ("这一步的内容").

What the pages do not show: the world and rule seeds (not in the recording panel, not in any decision text), the world file of the run
(`world/` is never read; the pages draw `frames.bin`), marker fields (`role`, `params`, `regions`, ...) and potion recipes. `mix` events (harness
side: they name the potion a recipe made) are dropped when a run loads, so they are not in the event list, the overlay rings or the event count
(`run.js` `HIDDEN_EVENT_TYPES`); `reaction` events stay. What the pages cannot hide: the picture itself (potion cells in the grid are drawn and
named on hover), other events that name materials (`fill`, `drink`, `pour`, `throw`), entity kinds such as `potion_heal`, and whatever the model wrote in
its own transcript.
A file that is listed above but cannot be read or parsed is a warning; only `meta.json` and `frames.bin` are required.
Size: a run is about 0.7 MB of `frames.bin` per decision (the Haiku game of 235 decisions is 163 MB, its `entities.jsonl` 37 MB), so a
1000-decision game is roughly 700 MB plus 150 MB of entities. Measured in Chrome: two such runs side by side (624 MB + 144 MB each) load in
about 3 s and the tab holds about 1.4 GB; four runs (two of them that size) load in about 3 s and hold about 1.1 to 1.4 GB. Every run keeps its
whole `frames.bin` in memory plus up to 64 MB of decoded frames.

## Report (`report.html`)

Reads the `profile.json` that `python -m noitabench eval <run folder>` writes (`cogbench-profile/0`, contracts.md section 19) and shows what the
evaluator measured. No score is computed here: every score is in the file. The only arithmetic is for display: 0..1 values times 100 (the decimal
point is moved in the digits, so a tie such as 0.0295 shows as 3, not 2.9), frames to game time (60 a second), the two shares of the composite
(0.8 x `ability_mean`, 0.2 x depth, shown with two decimals so they add up to the composite; hidden when they do not), and the mean of an
encounter's scored visits (one number per encounter in the comparison matrix and in an encounter's header). Open profiles by dropping them (or a run folder that holds
`profile.json`) on the page, with the buttons, or as `report.html?profile=../runs/a/profile.json&profile=../runs/b/profile.json` (same-origin
URLs only, at most 4). Drop more files later to add to the comparison; the `x` on a chip removes one.

One profile shows, top to bottom:

| Section | Content |
|---|---|
| headline | composite, the two parts (`ability_mean` and the depth score, each with its share, x 0.8 and x 0.2, when the shares add up to the composite), how the run ended, decisions and frames, cost (dollars, model calls) when `summary.json` was there, and the evaluator's warning when the composite is thin |
| 能力画像 | one bar per capability N1 to N10 and C. Pale bar = the capability's own score, solid bar = the discounted score (`discounted_score`, score x n/(n+2)), which is what the ability mean averages; hatching = fewer than 2 opportunities ("覆盖不足"); an empty track = never met (counts 0 in the discounted formula). Beside each bar: discounted score, raw score, factor, opportunities. A fold under each row lists the encounters and metrics the score was made of; C lists C1 to C4 |
| 遭遇点 | every implemented encounter: placed (must-pass), visits with layer, frame range, score 0 to 100 and the evaluator's reasons split into criterion, points earned / possible and detail; encounters never met are one line |
| 全局指标 | measured metrics with their value, the others with the reason they were not measured |
| 失败归因与评分说明 | `attribution` (a failed layer or seal traced to the encounter and nodes) and the evaluator's notes |
| 「这是测试」自查 | `test_awareness` (AC13): hits, categories, snippets folded away with the matched phrase marked. A count for a person to spot-check, not a score |

Two to four profiles show a headline table (composite, ability, depth, decisions, frames, dollars, model calls, how it ended), the capability
bars grouped by capability with one bar per profile (series A to D: colour **and** letter), an encounter matrix (mean score per profile; `—` =
placed but not met, `·` = not in that profile), a metric matrix (`未测` = not measured) and a fold per run with its own full detail.
A warning appears when the profiles were not scored by the same evaluator version (some have `discounted_score`, some do not).

Older profiles (before the discount, 2026-10-28) still open: they have no pale/solid pair, one solid bar per capability, and a note says the coverage rule was different.

Never shown: `world.seed`, `world.rule_seed`, the world file name (it carries the seed; `profile.js` drops the whole `world` object when it parses),
evaluator notes that quote a seed, the encounters' map positions, variants and `facts`. An attribution entry is cut down when it is parsed to the fields
`attribution.py` writes (capability, layer, outcome, frame, last harm, encounter, nodes, reason); anything else in it is dropped, not printed as `key=value`. All text from the profile (model snippets, reasons, run
names) is inserted as text. The run's name (`run_id`) is shown as it is: if you named a run after its seed, the name shows it.

Colours are CSS tokens (`--r-*` in `css/report.css`): dark by default like the other pages, light when the system asks for it; the four series
colours are the Okabe-Ito set. The page has no inline script or style attributes (bar widths are set through the CSSOM) and works down to 320 px.

On the replay page, if `<run folder>/profile.json` exists (a HEAD request on `?src=` runs), the header shows "本局报告", linking to this page. The replay page
does not read the profile.

## Browsers

Chrome/Edge 97+, Safari 16.4+, Firefox 113+ (needs `DecompressionStream`; the replay pages also use `findLast`, so Chrome 97; folder picking needs `webkitdirectory`,
available in all three). Layout works down to 320 px wide without horizontal scrolling.

## Tests and fixtures

```sh
node --test web/tests/                    # from the repo root (or: cd web && npm test)
.venv/bin/python web/tests/make_fixtures.py   # regenerate web/tests/fixtures/ (deterministic)
```

The fixtures follow the contracts exactly. Synthetic ones (a toy sand and water automaton that is **not** the game),
written by `make_fixtures.py`: `rec_synthetic/` (full frames, zlib and raw records, all optional files),
`rec_synthetic_delta/` (one keyframe, then partial rectangles, two records on one frame, no optional files, unknown
meta field), `world_synthetic.{png,json}` and a 4-bit indexed PNG. `expected.json` holds sha256 sums of the decoded
states that the Node tests compare against. `fixtures/rec_sim/` is a real recording written by `cogbench-sim`
(`rec_sim/HOWTO.md` says how); its `expected.json` comes from `make_sim_expected.py`, which decodes `frames.bin` in
Python without any viewer code. Regenerating the synthetic fixtures leaves `rec_sim/` alone. `harness_run/` and `human_run/`
are cut from a real Claude Haiku game and a real human game by `make_harness_fixture.py` (decisions, transcript, harness log and
summary; no frames, the tests pair them with the synthetic recording); the made-up seeds in its `summary.json` let a test check that no
page shows them. `profiles/{bot,agent,human}.profile.json` are the evaluator's output (`python -m noitabench eval`) for the scripted bot, the Claude Haiku
game and the human game, written by `make_profile_fixtures.py` with made-up seeds (424242 and 717171) and run names `fx-bot`, `fx-agent`, `fx-human`; the report
tests check that those seeds are on no page. Regenerate them after the evaluator's profile changes.

## Reading choices where the contract is silent

- `entities.jsonl`: `x`, `y` are the top-left corner of the `w` x `h` box, in cells (same convention as `trigger`).
- Frame records sharing one `frame` number form one step; a step that alone covers the whole viewed area is a key step.
  The viewed area is the bounding box of all records, so a rectangle recording shows just its rectangle.
- `world.json` may carry an optional `main_path` (list of `[x, y]` or `{x, y}`) at the top level or as
  `meta.main_path` (where the world generator writes it); it is drawn if present. Not in the contract yet.
- Unknown marker types are drawn as a grey `?`; marker discs shrink when zoomed out so a whole world stays readable.
- After a damaged frame record the picture goes blank, the page shows the error once and stays on that step (it does
  not retry in a loop); the next step that decodes clears the message.
- Seeds above 2^53 (u64) are shown with their exact digits taken from the raw text (the preview page; the replay and compare pages show no seeds at all).
- Damaged lines in optional `.jsonl` files become a warning, not an error.

## Play (`play.html`)

Unlike the other pages this one needs the local play server, which runs the game (the page itself still has no game
logic: it sends commands and draws what comes back):

```sh
.venv/bin/python -m noitabench play serve --world-seed 3 [--rule-seed R] [--port 8765] [--out runs/play-3] [--family F]
# prints:  play at http://127.0.0.1:8765/     ->  open it (it redirects to /web/play.html)
```

The server listens on 127.0.0.1 only, serves `web/` and a small JSON API (`python/noitabench/play/app.py`), and plays the
same `AgentSession` an agent plays. Pause mode: the world stands still until you decide. One key press or click is one
decision, and decisions are what the budget counts. The page shows only what an agent may see: the cells in a
256 x 192 window around you (the screenshot channel), creatures and items in view with kind, id and box (no health or
contents: right-click = `inspect`, which costs a decision as it does for an agent), your own health, wands, bottles
and notes. Fire is drawn from a separate burning mask. The colour key under the picture names only the materials an
agent's ASCII-map legend would name there (the map's smaller extent, its rule for what a block shows); those names come
with the picture (`view.legend`, `{index, name}` pairs), because the materials file the page loads (`/content/materials.json`)
has the colour of each index and nothing else: no key, name or kind. When you die or the decisions run out, the server ends the
session by itself, finishes the recording and the page shows the end state (more decisions are refused). The world file of
the level is written beside the recording, to `<out>-world/` (for `--out runs/play-3`: `runs/play-3-world/`), never into it, and
the server serves `web/` only; it refuses an `--out` under `web/`.

Walking does not stop for a drop (there is no fall damage: you walk off a ledge and fall, holding the direction until you land;
`walk_to` brakes at its column on the way down). It stops at a wall once you have pushed against it for a tick. In the command
box, `move(right, until=edge)` stops before a drop deeper than 8 cells. A held direction can carry you across a narrow shaft
(ledges of up to 4 cells are stepped up in the air too, and you are 4 cells wide): to drop in, stop over its middle first.

Keys (also listed on the page): arrows / A D walk (Shift: as far as a command may), **W or Up: tap (under 200 ms) = jump,
hold = levitate for as long as it is held** (one tick of game time, 10 frames, per 1/6 s of holding, at most 30 ticks = the 300 frames
of a decision; the decision is sent when the key comes up). Hold A/D while tapping W to jump to that side, or press A/D while W is
down to fly diagonally: those A/D presses steer the W gesture and are not steps of their own. Q E jump left or right,
S wait, Space cast, K kick, F pick up, B drink, P pour, L fill, T throw, X drop a bottle (Shift+X the wand in
hand), 1-9 hold a wand, Enter jumps to the command box (`walk_to(x=180); jump(right)`, up to 4 commands). Mouse: left
click = walk to that column, click a creature = aim and fire until it is dead, Shift+click = aim there and cast, right
click = inspect. `+` `-` `0` zoom. The wand panel edits wands only where the game allows it (rest area, edit station).
The notes panel is the harness workspace `workspaces/<family>/` (same 8,000 characters as an agent's notes); "End" stops
the recording. Open the recording afterwards with `replay.html?src=../runs/play-3/`.
