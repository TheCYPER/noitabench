"""Token counts of one model call (or the sum of several)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    """What a call used. `input_tokens` is the part of the prompt that was neither read from
    nor written to the cache; the whole prompt is `prompt_tokens`. `output_tokens` includes the
    model's thinking (`thinking_tokens` is the part of it that is known to be thinking)."""

    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int | None = None

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: Usage) -> Usage:
        if self.thinking_tokens is None and other.thinking_tokens is None:
            thinking = None
        else:
            thinking = (self.thinking_tokens or 0) + (other.thinking_tokens or 0)
        return Usage(
            self.input_tokens + other.input_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.output_tokens + other.output_tokens,
            thinking,
        )

    def as_dict(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
        }
