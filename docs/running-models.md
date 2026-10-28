# Running models on NoitaBench

How to point the harness at a model, what is priced, how to keep an API key out of your shell
history, and a small three-game pilot from start to report. Run everything from the repository
root, with the project's virtual environment (`.venv/bin/python`, or activate it and write
`python`); it needs the provider SDKs of the `harness` extra of `pyproject.toml`.

The harness never takes the key on the command line and never writes it to disk: it reads it from
an environment variable. By default that is the provider's usual variable; `--api-key-env NAME`
names another one. `python -m noitabench harness run --help` lists every flag.

| Provider | `--provider` | Default key variable | Example `--model` | Priced |
|---|---|---|---|---|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | `claude-haiku-5-5` | `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5` |
| OpenAI | `openai` | `OPENAI_API_KEY` | the id on your account's model list | none |
| Gemini | `gemini` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | the id on your account's model list | none |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-flash` | `deepseek-flash`, `deepseek-v4-pro` |
| OpenAI-compatible server | `openai` + `--base-url` | none (`EMPTY` is sent) | whatever the server serves | none |

A model that is not priced is refused, with a message, unless you give its prices or say you do not
care (below). Prices live in `python/noitabench/harness/prices.py`, in US dollars per million
tokens, with the source and the date they were read.

A refused key (HTTP 401), a key that may not use the model (403) or, at DeepSeek, an empty balance
(402) ends the game with `model_error`, and the remaining games of a family are not started: they
would fail at their first call in the same way. Fix the key and run the family again into a new
folder (or with `--overwrite`).

## Pricing a model that is not in the table

- `--price-input X --price-output Y` (both, USD per million tokens). Cached tokens are then charged
  like fresh ones, so the cost is an upper bound.
- `--allow-unpriced` runs without a cost. `--budget-usd`, `--family-budget-usd` and `harness
  estimate` need a price, so they do not work with it.
- For a model on your own machine, `--price-input 0 --price-output 0` is a price too.

## Anthropic

```sh
python -m noitabench harness run --provider anthropic --model claude-haiku-5-5 \
    --world-seed 1 --rule-seed 7 --budget-usd 5 --out runs/haiku-1
```

`--thinking off` is accepted only by the Haiku line, and not with `--effort xhigh` or `max`.
`--context server` (Anthropic's own compaction) works only here. With a custom `--base-url` the key
must be named with `--api-key-env`.

## OpenAI

```sh
python -m noitabench harness run --provider openai --model <model id> \
    --price-input <usd per M> --price-output <usd per M> \
    --world-seed 1 --rule-seed 7 --budget-usd 5 --out runs/gpt-1
```

Chat Completions, the token limit goes as `max_completion_tokens`, `--effort` as
`reasoning_effort`. Nothing is priced yet: look the prices up on OpenAI's pricing page and pass
them, or use `--allow-unpriced`.

## Gemini

```sh
python -m noitabench harness run --provider gemini --model <model id> \
    --price-input <usd per M> --price-output <usd per M> \
    --world-seed 1 --rule-seed 7 --budget-usd 5 --out runs/gemini-1
```

Thought summaries are requested by default (`--thinking adaptive`); a model without thinking needs
`--thinking default`. Nothing is priced yet. With a custom `--base-url` the key must be named with
`--api-key-env`.

## DeepSeek

```sh
python -m noitabench harness run --provider deepseek --model deepseek-flash \
    --api-key-env NOITABENCH_DEEPSEEK_KEY \
    --world-seed 1 --rule-seed 7 --budget-usd 3 --out runs/ds-flash-1
```

- Endpoint `https://api.deepseek.com` (`--base-url` overrides it). The key is read from
  `DEEPSEEK_API_KEY` or `--api-key-env`. `DEEPSEEK_API_KEY` is used only for that exact https
  address (a path such as `/beta` is fine): for any other `--base-url` (another host, a
  look-alike, plain http, a port, user info) nothing but `--api-key-env` is read, and without it
  no key is sent.
- Models: `deepseek-flash` (reads pictures) and `deepseek-v4-pro` (text only: `--screenshot` is
  refused). Other names, such as the older `deepseek-v4-flash`, are not priced.
- **Prices** are DeepSeek's *peak-hour* rates, read on 2026-10-28: flash $0.30 in / $0.006 cached
  in / $1.20 out, pro $1.32 / $0.044 / $3.96, per million tokens. DeepSeek charges half off-peak
  (every hour except 01:00-04:00 and 06:00-10:00 UTC on weekdays that are not Chinese public
  holidays), so the harness's cost and budget are an upper bound. There is no cache-write fee.
- **Thinking** is on by default. `--thinking off` turns it off; `--effort` becomes DeepSeek's
  `reasoning_effort` (low is low, medium/high/xhigh are high, max is max) and is ignored when
  thinking is off. Reasoning tokens are billed as output and count against `--max-output-tokens`,
  so for DeepSeek the defaults are 32768 tokens (other providers: 8192) and a 600 s request
  timeout (other providers: 180 s): DeepSeek keeps a waiting request open for up to ten minutes.
  Lower `--max-output-tokens` only with `--thinking off`, or answers are cut off and the game
  stalls. `summary.json` records the values used (`model.max_output_tokens`,
  `model.request_timeout`).
- The harness sends the model's reasoning back with every request, which DeepSeek requires once
  tools are used (it answers 400 otherwise). Nothing to do on your side.
- `deepseek-flash` is a floating name: DeepSeek swapped the model behind it on 2026-10-17. Each
  game records the model the answers named (`result.models_seen` in `summary.json`, `model` in
  every line of `harness.jsonl`), so check that before comparing runs from different days.
- Context caching is best effort. `harness estimate` assumes the usual hits; its
  `without_cache_usd` is the ceiling if the cache never hits.
- A rejected balance (HTTP 402) ends the game with `model_error` and a message that says so, and
  the remaining games of a family are not started (as for a refused key). A server that gives up
  mid-answer (`insufficient_system_resource`) is retried like a 429 or 503.
- Compaction stays at 120,000 prompt tokens, as for every model without a rate-card boundary, though
  both models take 1M. Change it with `--context-limit` only if you accept less comparable runs.

## A model served by your own machine (vLLM, llama.cpp, ...)

```sh
python -m noitabench harness run --provider openai --base-url http://localhost:8000/v1 \
    --model <name the server uses> --price-input 0 --price-output 0 \
    --world-seed 1 --rule-seed 7 --out runs/local-1
```

The OpenAI key is not sent to another host: without `--api-key-env` the server gets `EMPTY`. The
token limit goes as `max_tokens`.

## Keeping a key without it landing in shell history

Type the key at a hidden prompt, so that it is in neither the screen nor the history.

fish, a universal variable (kept across sessions; fish stores it as plain text in
`~/.config/fish/fish_variables`):

```fish
read -s -P "key: " k; and set -Ux NOITABENCH_DEEPSEEK_KEY $k; set -e k
```

bash, for the current session:

```sh
read -s -p "key: " k; echo; export NOITABENCH_DEEPSEEK_KEY=$k; unset k
```

zsh, for the current session:

```sh
read -s "k?key: "; echo; export NOITABENCH_DEEPSEEK_KEY=$k; unset k
```

Then pass `--api-key-env NOITABENCH_DEEPSEEK_KEY`. For bash and zsh, put the `export` in a file only
you can read if it should survive the session. Variables with `KEY`, `TOKEN` or `SECRET` in their
name are hidden from everything an agent's code can send back, and the harness warns if other
programs hold the same value (the sandbox cannot stop code from reading a process's start-up
environment). To avoid that warning, keep the variable unexported (`set -U`, without `x`) and hand
it only to the harness: `env NOITABENCH_DEEPSEEK_KEY=$NOITABENCH_DEEPSEEK_KEY python -m noitabench
harness run ...`.

## Pilot: three games of one family, from estimate to report

A family is games with the same rule seed (same potion recipes) in a new cave each
(`--world-seed`, +1, +2); the notebook is kept between games. The family name is the output folder
name, so the notebook lives in `workspaces/ds-flash-pilot/`.

1. **Check the plumbing without a model** (free): `--provider fake` plays a scripted policy.

   ```sh
   python -m noitabench harness run --provider fake --world-seed 1 --rule-seed 7 \
       --max-decisions 20 --out runs/fake-check
   ```

2. **Estimate the cost** (no model call; no key needed). The default of 600 output tokens per call
   is low for a thinking model, so pass what you expect, thinking included:

   ```sh
   python -m noitabench harness estimate --provider deepseek --model deepseek-flash \
       --max-decisions 1000 --runs 3 --output-tokens 3000
   ```

   `typical_usd` is one game, `total_typical_usd` all three; `low_usd` and `high_usd` bracket it;
   `without_cache_usd` is the ceiling with no cache hits. On 2026-10-28 this printed $5.08 per
   game and $15.25 for the family (flash); `--output-tokens 600` gives $1.72 per game.

3. **Run the family.** `--budget-usd` caps one game (it ends with `budget_usd` when reached),
   `--family-budget-usd` all of them; set them from the estimate.

   ```sh
   python -m noitabench harness run --provider deepseek --model deepseek-flash \
       --api-key-env NOITABENCH_DEEPSEEK_KEY \
       --world-seed 1 --rule-seed 7 --runs 3 --max-decisions 1000 \
       --budget-usd 6 --family-budget-usd 15 --out runs/ds-flash-pilot -v
   ```

   Result: `runs/ds-flash-pilot/run-01` to `run-03`, each with the recording, `summary.json`
   (how it ended, tokens, dollars), `harness.jsonl`, `transcript.jsonl`, `workspace_start/` and
   `workspace/` (the notebook before and after), plus `family.json`. The command prints one line
   per game. Use `--overwrite` to write into a folder that already holds a run.

4. **Extract the claims in the notebooks.** This is the only step that calls a model: Claude Haiku
   reads each note file (about $0.001 per file). It needs an Anthropic key, by default in
   `NOITABENCH_ANTHROPIC_KEY` (say `--api-key-env ANTHROPIC_API_KEY` if that is where yours is).
   It stops spending at `--max-usd 0.25` and does not send a file twice. Do it before step 5;
   without `notes_claims.json` the notebook metrics are `not_measured`.

   ```sh
   python -m noitabench notes-claims runs/ds-flash-pilot
   ```

5. **Evaluate each game.** This calls no model and writes `profile.json` into the run folder.

   ```sh
   python -m noitabench eval runs/ds-flash-pilot/run-01
   python -m noitabench eval runs/ds-flash-pilot/run-02
   python -m noitabench eval runs/ds-flash-pilot/run-03
   ```

   Or the whole family at once: `python -m noitabench eval runs/ds-flash-pilot` writes the three
   `profile.json` files and a `family_profile.json` that lines the games up and shows how games 2
   and 3 compare with game 1 (the notes-and-learning effect). With a control family (the same
   model, rule seed and world seeds, run with `--clear-workspace`), add
   `--control runs/ds-flash-control` to see the memory effect next to it (shown, not scored).

6. **Open the report.** Serve the repository root and open the page with the profiles (one to
   four, side by side). The replay page reads a run folder.

   ```sh
   python -m http.server 8000
   ```

   - `http://localhost:8000/web/report.html?profile=../runs/ds-flash-pilot/run-01/profile.json&profile=../runs/ds-flash-pilot/run-02/profile.json&profile=../runs/ds-flash-pilot/run-03/profile.json`
   - `http://localhost:8000/web/replay.html?src=../runs/ds-flash-pilot/run-01/`

   A replay can give away the potion recipes of its rule seed: a human participant must not see one
   before playing that seed. See `web/README.md` for the pages.
