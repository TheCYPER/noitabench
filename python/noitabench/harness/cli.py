"""`python -m noitabench harness <run|estimate|prompt> ...`

    python -m noitabench harness run --provider anthropic --model claude-haiku-5-5 \\
        --world-seed 1 --rule-seed 7 --budget-usd 5 --max-decisions 1000 --out runs/h1
    python -m noitabench harness estimate --provider anthropic --model claude-haiku-5-5
    python -m noitabench harness prompt

`run` plays one game, or `--runs N` games of one family (same rules, a new cave each, the
workspace kept between games, or emptied before each with `--clear-workspace`). Credentials come
from the provider's usual environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`) or from the variable named by `--api-key-env`; nothing is
read from the command line and nothing is written to disk. `--provider fake` plays a harmless
scripted policy without network or cost, to check the plumbing. `--max-output-tokens` and
`--request-timeout` default per provider (`model.PROVIDER_LIMITS`: 8192 and 180 s, but 32768 and
600 s for DeepSeek). `docs/running-models.md` has one section per provider.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

from noitabench.agent import AgentSession, ViewConfig, render_text
from noitabench.agent.vocab import DEFAULT_MAX_DECISIONS

from .adapters import PROVIDERS
from .budget import Budget
from .errors import ConfigError, HarnessError
from .estimate import DEFAULT_OBSERVATION_CHARS, estimate_run, measure_inputs
from .layers import build_toolbox, resolve_layers
from .loop import NONE, SERVER, SUMMARY, TEXT, TOOLS
from .model import ModelConfig
from .prices import custom_price, default_context_limit, resolve_price
from .prompt import system_prompt
from .runner import RunConfig, run_family
from .workspace import Workspace

NEVER_COMPACTED = 10**12  # a context limit that is never reached (`--context none`)


def _add_model_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("model")
    g.add_argument("--provider", required=True, choices=PROVIDERS)
    g.add_argument(
        "--model",
        default=None,
        help="model id, exactly as the provider spells it (not needed for --provider fake)",
    )
    g.add_argument("--base-url", default=None, help="endpoint (default: the provider's public one)")
    g.add_argument("--api-key-env", default=None, help="name of the variable that holds the key")
    g.add_argument(
        "--effort",
        choices=("low", "medium", "high", "xhigh", "max"),
        default=None,
        help="reasoning effort (not sent when not given; DeepSeek: with --thinking off it is "
        "ignored)",
    )
    g.add_argument(
        "--thinking",
        choices=("adaptive", "off", "default"),
        default="adaptive",
        help="Anthropic and DeepSeek only; DeepSeek thinks unless this is off",
    )
    g.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="limit on one answer (default 8192; DeepSeek 32768, its thinking counts against it)",
    )
    g.add_argument(
        "--request-timeout",
        type=float,
        default=None,
        help="seconds to wait for one answer (default 180; DeepSeek 600, it holds requests open)",
    )
    g.add_argument("--max-retries", type=int, default=4, help="the SDK's own retries per call")
    g.add_argument("--allow-unpriced", action="store_true", help="run a model with no known price")
    g.add_argument("--price-input", type=float, default=None, help="USD per million input tokens")
    g.add_argument("--price-output", type=float, default=None, help="USD per million output tokens")
    h = p.add_argument_group("harness")
    h.add_argument("--mode", choices=(TOOLS, TEXT), default=TOOLS, help="tool calls or plain text")
    h.add_argument(
        "--context",
        choices=(SUMMARY, SERVER, NONE),
        default=SUMMARY,
        help="long games: the loop's briefing (default), Anthropic server-side compaction, none",
    )
    h.add_argument(
        "--context-limit", type=int, default=None, help="prompt tokens before compaction"
    )
    h.add_argument("--minimal", action="store_true", help="only the game tools and the workspace")
    h.add_argument("--layers", default=None, help="comma list of layers, like L0,L1")
    h.add_argument("--max-decisions", type=int, default=DEFAULT_MAX_DECISIONS)
    h.add_argument(
        "--wheelhouse", default=None, help="folder of the libraries that may be installed (L5)"
    )
    h.add_argument("--max-model-calls", type=int, default=None)
    h.add_argument("--budget-usd", type=float, default=None, help="cap on the cost of one game")
    h.add_argument("--no-text", action="store_true", help="switch the state channel off")
    h.add_argument("--no-ascii", action="store_true", help="switch the ASCII map off")
    h.add_argument("--screenshot", action="store_true", help="switch the screenshot on")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="noitabench harness", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="play one game or a family of games with a model")
    _add_model_args(run)
    run.add_argument("--world-seed", type=int, required=True, help="seed of the first cave")
    run.add_argument("--rule-seed", type=int, default=0, help="rule seed of the family")
    run.add_argument("--game-seed", type=int, default=None, help="seed of the simulation")
    run.add_argument("--out", required=True, help="run folder (runs/<id>)")
    run.add_argument("--family", default=None, help="workspace family (default: the folder name)")
    run.add_argument("--runs", type=int, default=1, help="games in the family")
    run.add_argument("--clear-workspace", action="store_true", help="control: empty it each game")
    run.add_argument("--workspaces-dir", default="workspaces")
    run.add_argument("--overwrite", action="store_true", help="write into a run folder in use")
    run.add_argument("--family-budget-usd", type=float, default=None, help="cap on all games")
    run.add_argument("-v", "--verbose", action="store_true", help="progress lines on stderr")
    est = sub.add_parser("estimate", help="what a run is going to cost (no model call)")
    _add_model_args(est)
    est.add_argument("--runs", type=int, default=1)
    est.add_argument("--output-tokens", type=int, default=None, help="assumed output per call")
    est.add_argument("--world-seed", type=int, default=None, help="measure a real first view")
    est.add_argument("--rule-seed", type=int, default=0)
    prompt = sub.add_parser("prompt", help="print the system prompt and the tool list")
    prompt.add_argument("--minimal", action="store_true", help="only the game tools and notebook")
    prompt.add_argument("--layers", default=None, help="comma list of layers, like L0,L1")
    return parser


def _model_id(args: argparse.Namespace) -> str:
    """The model id: given, or `fake` for the scripted provider (which has no real models)."""
    if args.model:
        return str(args.model)
    if args.provider == "fake":
        return "fake"
    raise ConfigError(f"--model is required for the {args.provider} provider")


def _model_config(args: argparse.Namespace) -> ModelConfig:
    return ModelConfig(
        provider=args.provider,
        model=_model_id(args),
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        effort=args.effort,
        max_output_tokens=args.max_output_tokens,
        request_timeout=args.request_timeout,
        max_retries=args.max_retries,
        thinking=args.thinking,
    )


def _price(args: argparse.Namespace) -> Any:
    given = [v is not None for v in (args.price_input, args.price_output)]
    if any(given) and not all(given):
        raise ConfigError("give both --price-input and --price-output, or neither")
    override = custom_price(args.price_input, args.price_output) if all(given) else None
    return resolve_price(
        _model_id(args), override=override, allow_unpriced=args.allow_unpriced
    ), override


def _view(args: argparse.Namespace) -> ViewConfig:
    view = ViewConfig(text=not args.no_text, ascii=not args.no_ascii, screenshot=args.screenshot)
    if not (view.text or view.ascii or view.screenshot):
        raise ConfigError("at least one of the state, map and screenshot channels must be on")
    return view


def _run_config(args: argparse.Namespace) -> RunConfig:
    _, override = _price(args)
    return RunConfig(
        model=_model_config(args),
        out=Path(args.out),
        world_seed=args.world_seed,
        rule_seed=args.rule_seed,
        game_seed=args.game_seed,
        budget_usd=args.budget_usd,
        family_budget_usd=args.family_budget_usd,
        max_decisions=args.max_decisions,
        max_model_calls=args.max_model_calls,
        mode=args.mode,
        context=args.context,
        context_limit=args.context_limit,
        layers=resolve_layers(minimal=args.minimal, requested=args.layers, mode=args.mode),
        family=args.family,
        workspaces_dir=Path(args.workspaces_dir),
        clear_workspace=args.clear_workspace,
        runs=args.runs,
        view=_view(args),
        allow_unpriced=args.allow_unpriced,
        price=override,
        wheelhouse=Path(args.wheelhouse) if args.wheelhouse else None,
    )


# -- commands -------------------------------------------------------------------------------------


def _print_estimate(
    args: argparse.Namespace, decisions: int, runs: int, *, measure: bool = False
) -> dict[str, Any] | None:
    price, _ = _price(args)
    if price is None:
        print("no price is known for this model: no estimate", file=sys.stderr)
        return None
    chars = DEFAULT_OBSERVATION_CHARS
    if measure and getattr(args, "world_seed", None) is not None:
        chars = _measure_observation(args)
    layers = resolve_layers(minimal=args.minimal, requested=args.layers, mode=args.mode)
    kwargs: dict[str, Any] = {"mode": args.mode, "observation_chars": chars, "layers": layers}
    if getattr(args, "output_tokens", None):
        kwargs["output_tokens"] = args.output_tokens
    inputs = measure_inputs(**kwargs)
    limit = args.context_limit or default_context_limit(price)
    if args.context == NONE:
        limit = NEVER_COMPACTED  # the conversation only grows
    est = estimate_run(price, inputs, decisions=decisions, context_limit=limit)
    data = est.as_dict()
    data["runs"] = runs
    data["total_typical_usd"] = round(est.cost_usd * runs, 4)
    data["context_limit_tokens"] = None if args.context == NONE else limit
    data["observation_chars"] = chars
    return data


def _measure_observation(args: argparse.Namespace) -> int:
    from noitabench.agent.cli import build_world, open_game

    with tempfile.TemporaryDirectory() as tmp:
        png, js = build_world(args.world_seed, args.rule_seed, Path(tmp))
        session = AgentSession(open_game(png, js, rule_seed=args.rule_seed), config=None)
        return len(render_text(session.observe()))


def cmd_estimate(args: argparse.Namespace) -> int:
    data = _print_estimate(args, args.max_decisions, args.runs, measure=True)
    if data is None:
        return 2
    print(json.dumps(data, indent=2))
    if args.budget_usd is not None and data["typical_usd"] > args.budget_usd:
        print(
            f"warning: the typical cost ${data['typical_usd']} is above the budget "
            f"${args.budget_usd}; the game will be stopped by the budget",
            file=sys.stderr,
        )
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    layers = resolve_layers(minimal=args.minimal, requested=args.layers)
    print("=== system prompt (tools mode, notebook kept) ===")
    print(system_prompt(mode=TOOLS, notes_kept=True, layers=layers))
    print("\n=== system prompt (tools mode, notebook not kept) ===")
    print(system_prompt(mode=TOOLS, notes_kept=False, layers=layers))
    with tempfile.TemporaryDirectory() as tmp:
        box = build_toolbox(
            None,  # type: ignore[arg-type]
            Workspace(Path(tmp)),
            Budget(),
            layers=layers,
            decisions_cap=1,
        )
        print("\n=== tools ===")
        for spec in box.specs():
            print(f"- {spec.name}: {spec.description}")
    return 0


def _check_out_folder(config: RunConfig, overwrite: bool) -> None:
    out = config.out
    if out.exists() and any(out.iterdir()) and not overwrite:
        raise ConfigError(f"{out} is not empty; choose another folder or pass --overwrite")


def _announce(config: RunConfig, data: dict[str, Any] | None) -> None:
    """Say, before the first call, what the run is going to cost and which notebook it uses."""
    if data is not None:
        print(
            f"estimate: about ${data['typical_usd']} per game (range ${data['low_usd']} to "
            f"${data['high_usd']}) for {config.max_decisions} decisions",
            file=sys.stderr,
        )
        if config.budget_usd is not None and data["typical_usd"] > config.budget_usd:
            print(
                f"warning: that is above the budget of ${config.budget_usd}; the budget will "
                "stop the game early",
                file=sys.stderr,
            )
    folder = config.workspaces_dir / config.family_name
    kept = Workspace(folder).file_names() if folder.exists() else []
    if kept and not config.clear_workspace:
        print(
            f"workspace {folder}: continuing with {len(kept)} file(s) from earlier", file=sys.stderr
        )


def cmd_run(args: argparse.Namespace) -> int:
    config = _run_config(args)
    _check_out_folder(config, args.overwrite)
    _announce(config, _print_estimate(args, args.max_decisions, args.runs))
    summaries = run_family(config)
    for s in summaries:
        r = s["result"]
        cost = "unknown" if r["cost_usd"] is None else f"${r['cost_usd']:.4f}"
        print(
            f"game {s['run_index']}/{s['runs']} (world seed {s['world_seed']}): {r['over']}"
            f"{' - ' + r['detail'] if r.get('detail') else ''}; {r['decisions']} decisions, "
            f"{r['model_calls']} model calls, cost {cost}"
        )
    bad = {"model_error", "refusal", "stalled", "aborted"}
    return 1 if any(s["result"]["over"] in bad for s in summaries) else 0


def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    try:
        if args.cmd == "run":
            return cmd_run(args)
        if args.cmd == "estimate":
            return cmd_estimate(args)
        return cmd_prompt(args)
    except ConfigError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except HarnessError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
