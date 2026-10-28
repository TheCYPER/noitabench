"""Errors of the harness, and a scrubber that keeps credentials out of every message."""

from __future__ import annotations

import re

from .redact import HIDDEN, default_redactor

REDACTED = "[redacted]"
# Looser shapes than `redact.py` hides everywhere: the text of an error message is the provider's
# and is read by nobody who needs it exact, so `key: value` pairs and short `sk-` words go too.
_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|Bearer\s+[A-Za-z0-9._\-]{12,}"
    r"|(?:api[_-]?key|token)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._\-]{12,})",
    re.IGNORECASE,
)
MAX_MESSAGE = 600


def redact(text: str, marker: str = HIDDEN) -> str:
    """`text` without any secret `redact.py` knows: the values of the key-like environment
    variables of this process (read now) and of what has been learned since, their forms, and
    strings shaped like keys. Not shortened."""
    return default_redactor().sync_environment().redact(str(text), marker)


def scrub(text: str) -> str:
    """`text` without anything that looks like an API key (by its shape, or because it is the
    value of a key-like environment variable), and not longer than a log line."""
    cleaned = _SECRET.sub(REDACTED, redact(text, REDACTED))
    return cleaned if len(cleaned) <= MAX_MESSAGE else cleaned[: MAX_MESSAGE - 3] + "..."


class HarnessError(Exception):
    """Base class of the errors the harness raises on purpose."""


class ConfigError(HarnessError, ValueError):
    """A run was configured in a way that cannot work (unknown model, unpriced model...)."""


class ModelError(HarnessError):
    """A model call failed. `kind` is one of: auth, permission, not_found, bad_request,
    rate_limit, overloaded, server, timeout, connection, unknown. `retryable` errors may
    work again after a pause (the SDK has already retried them `max_retries` times)."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(scrub(message))
        self.kind = kind
        self.status = status
        self.retryable = retryable
        self.request_id = request_id

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "status": self.status,
            "retryable": self.retryable,
            "request_id": self.request_id,
            "message": str(self),
        }


class StopRun(HarnessError):
    """Raised inside the loop to end a run with a reason (`budget_usd`, `refusal`...)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
