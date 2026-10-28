"""What a model call costs: the price table, and the cost of a `Usage`.

Prices are US dollars per million tokens. The table holds only what is known; a model that is
not in it is refused unless the run says `--allow-unpriced` (then its calls cost 0 and the
summary says the cost is unknown) or gives its own prices (`--price-input`, `--price-output`).

Haiku 5.5 has two rate cards, chosen by the length of the whole prompt of a call (cached and
uncached tokens together): the cheap one up to 100,000 tokens and a five times dearer one
above. The harness therefore compacts its conversation before that (`default_context_limit`).
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ConfigError
from .usage import Usage

MILLION = 1_000_000
ANTHROPIC_SOURCE = "Anthropic pricing, model overview and prompt caching docs, retrieved 2026-10-06"
# DeepSeek charges less in its off-peak hours (half, outside weekday 01-04 and 06-10 UTC); the table
# holds the peak rates, so a budget set from it is an upper bound.
DEEPSEEK_SOURCE = "DeepSeek pricing page, peak-hour rates (off-peak is half), retrieved 2026-10-28"
DEFAULT_CONTEXT_LIMIT = 120_000
LIMIT_MARGIN = 0.9  # compact when the prompt reaches this share of a rate-card boundary


@dataclass(frozen=True)
class PriceTier:
    """Rates for calls whose prompt has at most `max_prompt_tokens` tokens (None: any)."""

    max_prompt_tokens: int | None
    input: float
    output: float


@dataclass(frozen=True)
class ModelPrice:
    tiers: tuple[PriceTier, ...]
    cache_read_factor: float = 0.1  # of the input rate
    cache_write_factor: float = 1.25  # five-minute cache writes, of the input rate
    source: str = ""

    def tier_for(self, prompt_tokens: int) -> PriceTier:
        for tier in self.tiers:
            if tier.max_prompt_tokens is None or prompt_tokens <= tier.max_prompt_tokens:
                return tier
        return self.tiers[-1]

    def cost(self, usage: Usage) -> float:
        tier = self.tier_for(usage.prompt_tokens)
        dollars = (
            usage.input_tokens * tier.input
            + usage.cache_read_tokens * tier.input * self.cache_read_factor
            + usage.cache_write_tokens * tier.input * self.cache_write_factor
            + usage.output_tokens * tier.output
        )
        return dollars / MILLION


PRICES: dict[str, ModelPrice] = {
    "claude-haiku-5-5": ModelPrice(
        (PriceTier(100_000, 0.10, 0.50), PriceTier(None, 0.50, 2.50)), source=ANTHROPIC_SOURCE
    ),
    "claude-sonnet-5-5": ModelPrice((PriceTier(None, 2.00, 10.00),), source=ANTHROPIC_SOURCE),
    # Cache reads on Opus 5.5 are 0.05x the input rate ($0.20 per million tokens), says the doc.
    "claude-opus-5-5": ModelPrice(
        (PriceTier(None, 4.00, 20.00),), cache_read_factor=0.05, source=ANTHROPIC_SOURCE
    ),
    # DeepSeek: a cache hit costs 0.02x (flash) and 1/30x (pro) of a miss; there is no cache write
    # fee, so a written token is a plain input token. Both models have a 1M context window; the
    # general compaction limit is kept so that runs stay comparable across providers.
    "deepseek-flash": ModelPrice(
        (PriceTier(None, 0.30, 1.20),),
        cache_read_factor=0.02,
        cache_write_factor=1.0,
        source=DEEPSEEK_SOURCE,
    ),
    "deepseek-v4-pro": ModelPrice(
        (PriceTier(None, 1.32, 3.96),),
        cache_read_factor=1 / 30,
        cache_write_factor=1.0,
        source=DEEPSEEK_SOURCE,
    ),
    # The scripted test model and the demo policy cost nothing.
    "fake": ModelPrice((PriceTier(None, 0.0, 0.0),), source="no real calls"),
}


def price_for(model: str) -> ModelPrice | None:
    """The price of `model` (exact id), or None when it is not known."""
    return PRICES.get(model)


def custom_price(input_per_mtok: float, output_per_mtok: float) -> ModelPrice:
    """A price given on the command line; cached tokens are charged like fresh ones."""
    if input_per_mtok < 0 or output_per_mtok < 0:
        raise ConfigError("prices must not be negative")
    return ModelPrice(
        (PriceTier(None, input_per_mtok, output_per_mtok),),
        cache_read_factor=1.0,
        cache_write_factor=1.0,
        source="given on the command line",
    )


def resolve_price(
    model: str,
    *,
    override: ModelPrice | None = None,
    allow_unpriced: bool = False,
) -> ModelPrice | None:
    """The price to use for a run. Raises `ConfigError` for an unpriced model unless allowed;
    returns None when the run goes on without a price."""
    if override is not None:
        return override
    found = price_for(model)
    if found is not None:
        return found
    if allow_unpriced:
        return None
    known = ", ".join(sorted(k for k in PRICES if k != "fake"))
    raise ConfigError(
        f"no price is known for model `{model}` (priced: {known}). Give --price-input and "
        "--price-output (USD per million tokens), or --allow-unpriced to run without a cost."
    )


def default_context_limit(price: ModelPrice | None) -> int:
    """Prompt length at which a conversation is compacted: under the first rate-card boundary
    when the model has one, else a general limit."""
    if price is not None:
        for tier in price.tiers:
            if tier.max_prompt_tokens is not None:
                return int(tier.max_prompt_tokens * LIMIT_MARGIN)
    return DEFAULT_CONTEXT_LIMIT
