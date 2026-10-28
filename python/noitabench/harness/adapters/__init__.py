"""Model adapters: one per provider, all behind `ModelAdapter` / `Conversation`.

The SDKs are imported only when an adapter is built, so the rest of the harness (and its tests)
works without them. `make_adapter` is the one place that maps a provider name to a class.
"""

from __future__ import annotations

from typing import Any

from ..errors import ConfigError
from ..model import ModelAdapter, ModelConfig

PROVIDERS = ("anthropic", "openai", "gemini", "fake")


def make_adapter(
    config: ModelConfig, *, client: Any | None = None, mode: str = "tools"
) -> ModelAdapter:
    """The adapter for `config.provider`. `client` is an SDK client to use instead of building
    one (tests pass one with a mocked transport); `mode` is only used by the `fake` provider."""
    provider = config.provider
    if provider == "anthropic":
        from .anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(config, client)
    if provider == "openai":
        from .openai_adapter import OpenAIAdapter

        return OpenAIAdapter(config, client)
    if provider == "gemini":
        from .gemini_adapter import GeminiAdapter

        return GeminiAdapter(config, client)
    if provider == "fake":
        from .scripted import ScriptedAdapter, demo_policy

        return ScriptedAdapter(demo_policy(mode), model=config.model)
    raise ConfigError(f"unknown provider `{provider}`; choose from {', '.join(PROVIDERS)}")
