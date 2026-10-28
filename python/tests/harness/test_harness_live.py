"""A real call to a real model. Costs money, so it only runs when asked for:

    NOITABENCH_LIVE=1 ANTHROPIC_API_KEY=... pytest python/tests/harness/test_harness_live.py

It plays three steps with Claude Haiku 5.5 on a small world, capped at 25 cents.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from noitabench.harness import ModelConfig, RunConfig, run_family

pytestmark = pytest.mark.skipif(
    os.environ.get("NOITABENCH_LIVE") != "1", reason="live calls need NOITABENCH_LIVE=1"
)


def test_haiku_plays_three_steps(tmp_path: Path, make_game) -> None:
    config = RunConfig(
        model=ModelConfig("anthropic", "claude-haiku-5-5", effort="low"),
        out=tmp_path / "live",
        workspaces_dir=tmp_path / "workspaces",
        max_decisions=3,
        budget_usd=0.25,
    )
    summary = run_family(config, game_factory=make_game)[0]
    result = summary["result"]
    assert result["over"] in {"decision_limit", "dead", "budget_usd"}
    assert result["model_calls"] >= 1 and result["cost_usd"] > 0
    rows = [json.loads(x) for x in (config.out / "harness.jsonl").read_text().splitlines()]
    assert rows[0]["prompt_tokens"] > 0
    if len(rows) > 1:  # the second call reads the prompt of the first from the cache
        assert rows[1]["cache_read_tokens"] > 0
