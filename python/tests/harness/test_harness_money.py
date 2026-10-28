"""Prices, cost of a call, the budget, the estimate."""

from __future__ import annotations

import pytest
from noitabench.harness import Budget, ConfigError, Usage
from noitabench.harness.estimate import estimate_run, measure_inputs
from noitabench.harness.prices import (
    PRICES,
    custom_price,
    default_context_limit,
    resolve_price,
)

HAIKU = PRICES["claude-haiku-5-5"]


def test_haiku_cost_on_the_cheap_card() -> None:
    usage = Usage(
        input_tokens=1_000, cache_read_tokens=40_000, cache_write_tokens=2_000, output_tokens=500
    )
    # $0.10 in, cache read 0.1x, cache write 1.25x, $0.50 out, per million tokens
    expected = (1_000 * 0.10 + 40_000 * 0.01 + 2_000 * 0.125 + 500 * 0.50) / 1e6
    assert HAIKU.cost(usage) == pytest.approx(expected)


def test_haiku_cost_changes_card_above_100k_prompt_tokens() -> None:
    cheap = Usage(input_tokens=100_000, output_tokens=1_000)
    dear = Usage(input_tokens=100_001, output_tokens=1_000)
    assert HAIKU.cost(cheap) == pytest.approx((100_000 * 0.10 + 1_000 * 0.50) / 1e6)
    assert HAIKU.cost(dear) == pytest.approx((100_001 * 0.50 + 1_000 * 2.50) / 1e6)
    # the whole prompt counts, cached tokens too
    mixed = Usage(input_tokens=1, cache_read_tokens=100_000, output_tokens=0)
    assert HAIKU.cost(mixed) == pytest.approx((1 * 0.50 + 100_000 * 0.05) / 1e6)


def test_haiku_cache_traffic_is_priced_by_the_card_of_the_whole_prompt() -> None:
    # 99,000 cached + 1,000 fresh = exactly 100,000 tokens: still the cheap card
    edge = Usage(input_tokens=1_000, cache_read_tokens=99_000, output_tokens=100)
    assert HAIKU.cost(edge) == pytest.approx((1_000 * 0.10 + 99_000 * 0.01 + 100 * 0.50) / 1e6)
    # one more token and every token of the call, cached ones too, is on the dear card
    over = Usage(input_tokens=1_001, cache_read_tokens=99_000, output_tokens=100)
    assert HAIKU.cost(over) == pytest.approx((1_001 * 0.50 + 99_000 * 0.05 + 100 * 2.50) / 1e6)
    # a cache write counts towards the length, and costs 1.25x of the card's input rate
    wrote = Usage(cache_write_tokens=100_001, output_tokens=0)
    assert HAIKU.cost(wrote) == pytest.approx(100_001 * 0.50 * 1.25 / 1e6)


def test_thinking_tokens_are_part_of_the_output_and_not_charged_twice() -> None:
    plain = Usage(input_tokens=1_000, output_tokens=500)
    thinking = Usage(input_tokens=1_000, output_tokens=500, thinking_tokens=400)
    assert HAIKU.cost(plain) == HAIKU.cost(thinking)
    total = thinking + Usage(output_tokens=100)
    assert total.output_tokens == 600 and total.thinking_tokens == 400


def test_an_empty_call_costs_nothing_and_the_fake_model_is_free() -> None:
    assert HAIKU.cost(Usage()) == 0.0
    assert PRICES["fake"].cost(Usage(10**9, 10**9, 10**9, 10**9)) == 0.0


def test_other_claude_prices() -> None:
    sonnet = PRICES["claude-sonnet-5-5"].cost(
        Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    )
    assert sonnet == pytest.approx(12.0)
    opus = PRICES["claude-opus-5-5"].cost(Usage(cache_read_tokens=1_000_000))
    assert opus == pytest.approx(0.20)  # reads at 0.05x of $4
    assert all(p.source for p in PRICES.values())


def test_unpriced_models_are_refused_unless_allowed() -> None:
    with pytest.raises(ConfigError, match="no price"):
        resolve_price("gpt-9")
    assert resolve_price("gpt-9", allow_unpriced=True) is None
    mine = custom_price(0.2, 0.6)
    assert resolve_price("gpt-9", override=mine) is mine
    assert mine.cost(Usage(input_tokens=1_000_000, cache_read_tokens=1_000_000)) == pytest.approx(
        0.4
    )
    with pytest.raises(ConfigError):
        custom_price(-1, 1)


def test_context_limit_stays_under_the_dear_card() -> None:
    assert default_context_limit(HAIKU) == 90_000
    assert default_context_limit(PRICES["claude-opus-5-5"]) == 120_000
    assert default_context_limit(None) == 120_000


# -- budget ---------------------------------------------------------------------------------------


def test_budget_stops_before_the_cap_using_the_dearest_recent_call() -> None:
    b = Budget(max_usd=1.0)
    assert b.exhausted() is None
    b.charge(0.40)
    assert b.exhausted() is None  # 0.40 + 0.40 <= 1.0
    b.charge(0.35)
    assert b.exhausted() == "budget_usd"  # 0.75 + 0.40 > 1.0: the next call might not fit
    assert b.remaining_usd() == pytest.approx(0.25)


def test_budget_counts_calls_and_unpriced_calls() -> None:
    b = Budget(max_model_calls=2)
    b.charge(None)
    assert b.exhausted() is None and b.unpriced_calls == 1
    b.charge(0.0)
    assert b.exhausted() == "budget_calls"
    assert b.as_dict()["model_calls"] == 2


def test_zero_budget_allows_no_call() -> None:
    assert Budget(max_usd=0.0).exhausted() == "budget_usd"


def test_a_call_that_just_fits_is_allowed_and_one_that_does_not_is_not() -> None:
    b = Budget(max_usd=1.0)
    b.charge(0.5)
    b.charge(0.25)
    assert b.next_call_estimate() == 0.5
    assert b.exhausted() == "budget_usd"  # 0.75 spent + 0.5 for the dearest recent call > 1.0
    c = Budget(max_usd=1.0)
    c.charge(0.25)
    c.charge(0.25)
    assert c.exhausted() is None  # 0.5 + 0.25 <= 1.0
    c.charge(0.25)
    assert c.exhausted() is None  # 0.75 + 0.25 == 1.0 exactly: it fits
    c.charge(0.25)
    assert c.exhausted() == "budget_usd"  # nothing left


def test_float_noise_does_not_stop_a_run_that_fits() -> None:
    b = Budget(max_usd=1.0)
    for _ in range(9):
        b.charge(0.1)
    assert b.spent_usd + 0.1 > 1.0 - 1e-12  # the sum is 1.0 up to float noise
    assert b.exhausted() is None


def test_only_the_last_five_calls_set_the_estimate_of_the_next() -> None:
    b = Budget(max_usd=100.0)
    b.charge(9.0)  # one expensive call, long ago
    for _ in range(5):
        b.charge(0.01)
    assert b.next_call_estimate() == pytest.approx(0.01)
    assert b.remaining_usd() == pytest.approx(100.0 - 9.05)


def test_unpriced_calls_never_spend_money_and_a_cap_of_none_never_stops() -> None:
    b = Budget(max_usd=None)
    for _ in range(100):
        b.charge(None)
    assert b.exhausted() is None and b.remaining_usd() is None and b.spent_usd == 0.0


# -- estimate -------------------------------------------------------------------------------------


def test_estimate_for_haiku_is_small_and_ordered() -> None:
    inputs = measure_inputs()
    assert 4_000 < inputs.tools_tokens < 20_000  # the tool schemas are most of the prefix
    est = estimate_run(HAIKU, inputs, decisions=1_000)
    assert est.low_usd < est.cost_usd < est.high_usd
    assert est.cost_usd < est.without_cache_usd
    assert est.peak_prompt_tokens < 100_000  # compacted before the dear card
    assert est.summaries >= 5 and est.calls == 1_150
    assert 0.2 < est.cost_usd < 8.0
    assert est.as_dict()["per_decision_usd"] == pytest.approx(est.cost_usd / 1_000, rel=1e-3)


def test_estimate_text_mode_has_no_tool_tokens() -> None:
    assert measure_inputs(mode="text").tools_tokens == 0
    assert measure_inputs(mode="text").system_tokens > measure_inputs().system_tokens
