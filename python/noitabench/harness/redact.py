"""Keeps secrets out of everything that leaves the box.

Code in the box can read the start-up environment of any non-Apple program of the same user
(`sysctl KERN_PROCARGS2`, see `sandbox.py`): the keys of other tools, and the key this very run
uses if a shell exported it. The box has no network, so the risk is that a program prints,
returns, writes or passes on a secret and that it then reaches the model (so its provider) or the
run's files. Nothing here changes what the box can read; it makes sure that no *known* secret
value leaves it as such.

What is hidden (replaced by `[hidden]`):

- **Values.** The value of every key-like variable (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`,
  `*PASSWD*`, `*CREDENTIAL*`; and any variable named with `track`, such as `--api-key-env`'s) in
  this process's environment and in the start-up environment of every other program the box could
  read. They are collected by `Redactor.refresh` (the sandbox calls it before every job) and kept
  in memory only: never logged, printed, written or put in an exception.
  A value is worth hiding when it has at least `MIN_SECRET_LENGTH` (8) characters and at least
  `MIN_DISTINCT` (4) different ones, and is not a plain word (letters only, under `WORD_LENGTH`
  (12) characters): shorter values and words would damage ordinary text, and a blanked value
  (`xxxxxxxx`, which is what `hide_startup_environment` leaves behind) is no secret.
- **Forms of a value.** Reversed; upper and lower case (texts are looked at in lower case, so
  any mixing of case is found too); ROT13; hex (also with a separator between the bytes:
  `73:6b`, `73 6b`, `73-6b`, `0x73, 0x6b`, and as the escapes `\\x73`, `%73`); base64 standard
  and URL-safe, with and without padding, also percent-encoded (`%2B`), also as it appears
  inside a longer base64 text (at each of the three alignments); base32; base85 and ascii85;
  percent-encoded; JSON- and Python-escaped; as a list of byte numbers (`115, 107, ...`
  separated by `, `, `,`, a space, `;`, a tab or a line end).
  Besides the whole form, any piece of `WINDOW` (12) or more characters of a text form is
  recognised, so a program that prints only part of a secret is hidden too; where a piece is
  found the whole word around it (letters, digits and `+/_-`) goes with it.
  Values over `HEAVY_LIMIT` (256) characters (private keys) are matched as they are, reversed,
  and in the other cases of the first line only.
- **Spelled out in data.** In lists and numbers (`redact_value`, which cleans the requests and
  reports of the box and the logs): a number that is itself a secret (a numeric password), a
  list of byte numbers and a list of one character per item (`list(secret)`) are replaced by
  their text with the secret hidden.
- **Unseen characters and look-alikes.** Before a text is searched, zero-width and other
  invisible characters (`\\u200b`, `\\u200d`, soft hyphens, byte order marks, variation
  selectors) are dropped and the look-alikes Unicode defines (fullwidth letters, ligatures,
  circled and mathematical letters: NFKC) are made plain (`_prepare`); texts of more than
  `FOLD_LIMIT` characters that are not plain ASCII are searched as they are.
- **Shapes**, whether or not the value is known: Anthropic and OpenAI style keys (`sk-ant-...`,
  `sk-...`), Google (`AIza...`), Tavily (`tvly-...`), GitHub (`ghp_...`, `github_pat_...`), Slack
  (`xox?-...`), AWS key ids, JSON web tokens, `Bearer ...`, PEM private keys (up to the end
  line, or `PEM_BODY` characters when there is none), the user and password of a URL, and long
  random-looking tokens (32 or more characters of letters, digits and `_-` with upper case,
  lower case and digits that change kind as often as random text does; hexadecimal strings of
  32 or more characters; long base64). These are tuned to leave ordinary game text (words,
  identifiers, paths, ASCII maps) alone: `tests/harness/test_harness_redact.py`
  checks that on whole games.
  The one place that skips the shapes is the `id` of a tool call or result in `transcript.jsonl`
  (`Redactor.redact_id`: known values only), because providers make ids that are as long and as
  random as a key and a recording must keep calls and results linked.

What is not covered: a secret that is cut into pieces shorter than `WINDOW` characters and sent
one piece at a time, or with anything put between its characters (spaces, one character per
line, one piece in each of several files or messages); look-alikes that Unicode does not define
(Cyrillic `а` for Latin `a`); any transformation not listed (encryption, compression before
encoding, XOR, base64 of base64, a character at a time through game commands, timing); secrets
whose variable name does not look like a key (and that have no recognisable shape); the
arguments of other programs (only the environment is read); a program that starts after the
last refresh and holds a key that is read in the meantime (the sandbox refreshes before a job,
every `REFRESH_SECONDS` while it asks for things, and again when it is over). The aim is to
stop a secret from showing up by accident or by a naive try, not to stop a determined program
from smuggling bits out.
"""

from __future__ import annotations

import base64
import codecs
import itertools
import json
import logging
import os
import re
import threading
import unicodedata
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .procenv import other_environments

log = logging.getLogger(__name__)

HIDDEN = "[hidden]"
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)
MIN_SECRET_LENGTH = 8  # shorter values are not worth hunting for
MAX_SECRET_LENGTH = 8192  # longer values are not secrets of a program
MIN_DISTINCT = 4  # a value of fewer different characters (`xxxxxxxx`, `00000000`) is no secret
WORD_LENGTH = 12  # a value of letters only and shorter than this is a word
WINDOW = 12  # a piece this long of a secret is recognised on its own
HEAVY_LIMIT = 256  # past this length only the plain forms of a value are matched
MAX_SECRETS = 2000
EXPAND = 64  # characters the hidden word may grow on each side
MAX_DEPTH = 64
FOLD_LIMIT = 300_000  # longer texts that are not plain ASCII are not unfolded (`_prepare`)
PEM_BODY = 12_000  # characters of a private key that are hidden after its header at most
_TOKEN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/_-")


def acceptable(value: str) -> bool:
    """Whether a value is worth hiding (see the module doc)."""
    if not (MIN_SECRET_LENGTH <= len(value) <= MAX_SECRET_LENGTH):
        return False
    if not value.strip() or len(set(value)) < MIN_DISTINCT:
        return False
    try:
        value.encode("utf-8")  # bytes the environment could not decode are no text to look for
    except UnicodeEncodeError:
        return False
    return not (value.isalpha() and len(value) < WORD_LENGTH)


# -- the forms of a value ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Forms:
    short: frozenset[str]  # forms shorter than WINDOW, searched for whole
    exact: frozenset[str]  # long forms that are only searched for whole (lists of numbers)
    grams: frozenset[str]  # every WINDOW-piece of the other forms


def _windows(needle: str) -> Iterable[str]:
    return (needle[i : i + WINDOW] for i in range(len(needle) - WINDOW + 1))


def _encodings(value: str, raw: bytes) -> set[str]:
    """The forms of `value` that are not just its characters changed."""
    out: set[str] = {raw.hex(), raw.hex().upper()}
    for shift in range(3):  # where in a base64 text the value may begin
        data = b"\0" * shift + raw
        lead = (0, 2, 3)[shift]  # characters that still depend on what precedes the value
        whole = (len(data) // 3) * 4  # after that, the last group depends on what follows
        for encode in (base64.b64encode, base64.urlsafe_b64encode):
            text = encode(data).decode("ascii")
            core = text[lead:whole]
            if len(core) >= WINDOW:
                out.add(core)
                out.add(urllib.parse.quote(core, safe=""))  # `+`, `/` and `=` as `%2B`...
            if shift == 0:
                out.update((text, text.rstrip("=")))
                out.add(urllib.parse.quote(text, safe=""))
    b32 = base64.b32encode(raw).decode("ascii")
    out.update((b32, b32.rstrip("="), b32.lower(), b32.rstrip("=").lower()))
    out.update((base64.b85encode(raw).decode("ascii"), base64.a85encode(raw).decode("ascii")))
    out.update(
        (
            urllib.parse.quote(value, safe=""),
            urllib.parse.quote_plus(value),
            json.dumps(value)[1:-1],
            json.dumps(value, ensure_ascii=False)[1:-1],
            repr(value)[1:-1],
        )
    )
    out |= _spelled_out(raw)
    return out


HEX_SEPARATORS = (" ", ":", "-", ", ")
NUMBER_SEPARATORS = (", ", ",", " ", ";", "\t", "\n")


def _spelled_out(raw: bytes) -> set[str]:
    """Hex with a separator between the bytes (`bytes.hex(":")`, `73 6b`, `0x73, 0x6b`), and the
    escapes `\\x73\\x6b` and `%73%6b`. (Every form costs memory for each secret, so only the
    ones a program writes without trying hard are here.)"""
    pairs = [f"{byte:02x}" for byte in raw]
    out = {sep.join(pairs) for sep in HEX_SEPARATORS}
    out |= {sep.join("0x" + p for p in pairs) for sep in (" ", ", ")}
    out.add("".join("\\x" + p for p in pairs))
    out.add("".join("%" + p for p in pairs))
    return out


def derive(value: str) -> _Forms:
    """Everything that stands for `value` in a text (see the module doc). Texts are searched in
    lower case (`Redactor.redact`), so the forms are in lower case too."""
    plain = {value, value[::-1], value.lower(), value.upper(), codecs.encode(value, "rot13")}
    forms: set[str] = set(plain)
    exact: set[str] = set()
    if len(value) <= HEAVY_LIMIT:
        raw = value.encode("utf-8")
        forms |= {f for f in _encodings(value, raw) if len(f) >= WINDOW}
        numbers = [str(byte) for byte in raw]
        exact |= {sep.join(numbers) for sep in NUMBER_SEPARATORS}
    folded = {_lower(f) for f in forms}
    short = {f for f in folded if MIN_SECRET_LENGTH <= len(f) < WINDOW}
    grams = {g for f in folded if len(f) >= WINDOW for g in _windows(f)}
    return _Forms(frozenset(short), frozenset(exact), frozenset(grams))


@dataclass(frozen=True)
class _Index:
    direct: tuple[str, ...] = ()  # searched for whole
    grams: frozenset[str] = frozenset()


# -- texts, as they are looked at -------------------------------------------------------------------


def _lower(text: str) -> str:
    """`text` in lower case, with every character still one character (a few letters have a lower
    case of two; those stay as they are, so that positions in the result are positions in `text`)."""
    low = text.lower()
    if len(low) == len(text):
        return low
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


_FOLDED: dict[str, str] = {}  # what a character that is not ASCII becomes (see `_prepare`)


def _fold_char(char: str) -> str:
    folded = _FOLDED.get(char)
    if folded is None:
        if unicodedata.category(char) == "Cf" or "\ufe00" <= char <= "\ufe0f":
            folded = ""
        else:
            folded = unicodedata.normalize("NFKC", char)
        if len(_FOLDED) < 20_000:
            _FOLDED[char] = folded
    return folded


def _prepare(text: str) -> tuple[str, list[int] | None]:
    """`text` as it is looked at for secrets, and where each of its characters stood in `text`
    (None: in the same place, which is so for all ASCII text).

    Characters that are not shown (zero-width joiners and spaces, soft hyphens, byte order marks,
    variation selectors) are dropped, and look-alikes that Unicode defines (fullwidth letters,
    ligatures, circled and mathematical letters) become the plain characters, so that putting
    them between or in place of the characters of a secret does not hide it. A text of more than
    `FOLD_LIMIT` characters that is not all ASCII is looked at as it is."""
    if text.isascii() or len(text) > FOLD_LIMIT:
        return text, None
    pieces = [c if c < "\x80" else _fold_char(c) for c in text]
    seen = "".join(pieces)
    if len(seen) == len(text) and all(len(piece) == 1 for piece in pieces):  # nothing moved
        return seen, None
    origin = [at for at, piece in enumerate(pieces) for _ in piece]
    return seen, origin


def _unfold(spans: list[tuple[int, int]], origin: list[int] | None) -> list[tuple[int, int]]:
    """Spans of a prepared text as spans of the text it came from."""
    if origin is None:
        return spans
    return [(origin[start], origin[end - 1] + 1) for start, end in spans if end > start]


# -- shapes ------------------------------------------------------------------------------------------

_B = r"(?<![A-Za-z0-9])"
_SHAPES: tuple[tuple[tuple[str, ...], re.Pattern[str]], ...] = (
    (("sk-",), re.compile(_B + r"sk-ant-[A-Za-z0-9_\-]{10,}")),
    (("sk-",), re.compile(_B + r"sk-[A-Za-z0-9_\-]{20,}")),
    (("AIza",), re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    (("tvly-",), re.compile(_B + r"tvly-[A-Za-z0-9_\-]{8,}")),
    (("ghp_", "gho_", "ghu_", "ghs_", "ghr_"), re.compile(_B + r"gh[pousr]_[A-Za-z0-9]{20,}")),
    (("github_pat_",), re.compile(_B + r"github_pat_[A-Za-z0-9_]{20,}")),
    (("xox",), re.compile(_B + r"xox[abprs]-[A-Za-z0-9\-]{10,}")),
    (
        ("AKIA", "ASIA", "AGPA", "AIDA", "AROA"),
        re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA|AGPA|AIDA|AROA)[A-Z0-9]{16}(?![A-Z0-9])"),
    ),
    (
        ("eyJ",),
        re.compile(
            r"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"
        ),
    ),
    (("earer", "EARER"), re.compile(r"[Bb][Ee][Aa][Rr][Ee][Rr]\s+[A-Za-z0-9._~+/\-]{16,}=*")),
    (("://",), re.compile(r"(?<=://)[^\s/:@]{1,64}:[^\s/@]{3,}(?=@)")),
)
_PEM_HEAD = re.compile(r"-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]{0,40}PRIVATE KEY-----")
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-+/=])[A-Za-z0-9_\-+/]{32,}={0,2}")
_CHANGE_FLOOR = 0.35  # random text changes kind (lower, upper, digit, other) every other character


def _kind(char: str) -> str:
    if char.islower():
        return "l"
    if char.isupper():
        return "U"
    return "d" if char.isdigit() else "s"


def _change_rate(text: str) -> float:
    """How often the next character is of another kind than this one. Random text of letters and
    digits changes about 6 times in 10; words, camel case and identifiers about 2 in 10."""
    kinds = [_kind(c) for c in text]
    return sum(a != b for a, b in itertools.pairwise(kinds)) / (len(text) - 1)


def _random_looking(token: str) -> bool:
    """Whether a long run of token characters looks like a random token rather than words, a
    path or a map."""
    body = token.rstrip("=")
    if not any(c.isdigit() for c in body) or len(set(body)) < 10:
        return False
    if all(c in "0123456789abcdefABCDEF" for c in body):  # hexadecimal: a hash or a key
        return any(c.isalpha() for c in body)
    if ("/" in body or "+" in body) and (body.count("/") * 20 > len(body) or len(body) < 40):
        return False  # base64 has few slashes (a path has many) and is not short
    lower = any(c.islower() for c in body)
    upper = any(c.isupper() for c in body)
    return lower and upper and _change_rate(body) >= _CHANGE_FLOOR


def _pem_spans(text: str) -> list[tuple[int, int]]:
    """Private keys: from the header to the end line, or, when there is none within `PEM_BODY`
    characters, to that limit (a key cut off by the cap on what is printed is still hidden).
    Found by hand rather than by one pattern, which takes time quadratic in the text for a text
    made of headers."""
    spans: list[tuple[int, int]] = []
    at = 0
    while (start := text.find("-----BEGIN ", at)) >= 0:
        head = _PEM_HEAD.match(text, start)
        if head is None:
            at = start + 1
            continue
        limit = head.end() + PEM_BODY
        tail = _PEM_END.search(text, head.end(), limit + 60)
        end = tail.end() if tail else min(len(text), limit)
        spans.append((start, end))
        at = end
    return spans


def _shape_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    if "-----BEGIN " in text:
        spans.extend(_pem_spans(text))
    for gates, pattern in _SHAPES:
        if any(gate in text for gate in gates):
            spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
    if len(text) >= 32:
        for match in _LONG_TOKEN.finditer(text):
            if _random_looking(match.group()):
                spans.append((match.start(), match.end()))
    return spans


# -- the redactor ------------------------------------------------------------------------------------


class Redactor:
    """The secrets known so far, and what hides them. Safe to share between threads."""

    def __init__(self, *, enabled: bool = True, shapes: bool = True) -> None:
        self.enabled = enabled  # off: nothing is hidden (tests compare with and without)
        self.shapes = shapes  # off: only known values are hidden, not key-shaped strings
        self._lock = threading.RLock()
        self._forms: dict[str, _Forms] = {}  # value -> forms, oldest first
        self._tracked: set[str] = set()
        self._index = _Index()

    def __repr__(self) -> str:  # never shows a value
        return f"Redactor({len(self._forms)} secrets)"

    def count(self) -> int:
        """How many secrets are known."""
        return len(self._forms)

    def __reduce__(self) -> Any:
        raise TypeError("a Redactor holds secrets and is never pickled")

    # -- learning secrets ---------------------------------------------------------------------------

    def track(self, name: str | None) -> None:
        """Always count the environment variable `name` as a secret (`--api-key-env`)."""
        if name:
            with self._lock:
                self._tracked.add(name)

    def add(self, values: Iterable[str]) -> int:
        """Add secret values; returns how many were new (values that are not worth hiding, see
        `acceptable`, are ignored)."""
        with self._lock:
            fresh = [v for v in dict.fromkeys(values) if v not in self._forms and acceptable(v)]
            if not fresh:
                return 0
            for value in fresh:
                self._forms[value] = derive(value)
            while len(self._forms) > MAX_SECRETS:
                del self._forms[next(iter(self._forms))]
            self._rebuild()
        return len(fresh)

    def _rebuild(self) -> None:
        direct: set[str] = set()
        grams: set[str] = set()
        for forms in self._forms.values():
            direct |= forms.short | forms.exact
            grams |= forms.grams
        self._index = _Index(tuple(sorted(direct, key=len, reverse=True)), frozenset(grams))

    def sync_environment(self) -> Redactor:
        """Take in the key-like variables of this process's environment (cheap)."""
        if self.enabled:
            self.add(self._environment_values())
        return self

    def refresh(self) -> int:
        """`sync_environment` plus the start-up environments of the other programs the box could
        read. Returns how many secrets were new. The sandbox calls this before every job."""
        if not self.enabled:
            return 0
        found = self._environment_values()
        with self._lock:
            tracked = set(self._tracked)
        try:
            for _pid, pairs in other_environments(os.getpid()):
                for name, raw in pairs:
                    if len(raw) >= MIN_SECRET_LENGTH and (
                        name in tracked or SECRET_NAME.search(name)
                    ):
                        try:
                            found.append(raw.decode("utf-8"))
                        except UnicodeDecodeError:
                            continue
        except Exception:  # noqa: BLE001 - a job must not fail because the scan did
            log.warning("could not read the environments of the other programs", exc_info=False)
        return self.add(found)

    def _environment_values(self) -> list[str]:
        with self._lock:
            tracked = set(self._tracked)
        return [
            value
            for name, value in os.environ.items()
            if name in tracked or SECRET_NAME.search(name)
        ]

    # -- hiding them --------------------------------------------------------------------------------

    def redact(self, text: str, marker: str = HIDDEN, *, shapes: bool = True) -> str:
        """`text` with every known secret, form of one and key-shaped string replaced by `marker`
        (and any character that cannot be written to a file spelled out: see `_encodable`).
        `shapes=False`: only the known secrets and their forms, not strings shaped like keys."""
        if not self.enabled or not isinstance(text, str):
            return text
        text = _encodable(text)
        if len(text) < MIN_SECRET_LENGTH:
            return text
        spans = self._spans(text, shapes)
        if not spans:
            return text
        spans.sort()
        merged = [spans[0]]
        for start, end in spans[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        pieces: list[str] = []
        at = 0
        for start, end in merged:
            pieces.append(text[at:start])
            pieces.append(marker)
            at = end
        pieces.append(text[at:])
        return "".join(pieces)

    def _spans(self, text: str, shapes: bool = True) -> list[tuple[int, int]]:
        """Where in `text` something has to be hidden, as `(start, end)`, unsorted."""
        seen, origin = _prepare(text)
        found = _unfold(self._known_spans(_lower(seen)), origin)
        spans = [_grow(text, start, end) for start, end in found]
        if self.shapes and shapes:
            spans.extend(_unfold(_shape_spans(seen), origin))
        return spans

    def _known_spans(self, text: str) -> list[tuple[int, int]]:
        """Where the known values and the pieces of their forms are in `text` (lower case)."""
        index = self._index
        found: list[tuple[int, int]] = []
        for needle in index.direct:
            at = text.find(needle)
            while at >= 0:
                found.append((at, at + len(needle)))
                at = text.find(needle, at + 1)
        if index.grams and len(text) >= WINDOW:
            grams = index.grams
            first = end = -1
            for i in range(len(text) - WINDOW + 1):
                if text[i : i + WINDOW] in grams:
                    if first >= 0 and i <= end:
                        end = i + WINDOW
                    else:
                        if first >= 0:
                            found.append((first, end))
                        first, end = i, i + WINDOW
            if first >= 0:
                found.append((first, end))
        return found

    def redact_id(self, value: Any, marker: str = HIDDEN) -> Any:
        """A tool-call id: hidden when it is, or holds, a known secret (or a form of one), but not
        for looking like a key. DeepSeek's `call_00_...` and the like are long and random by
        design; hiding them would unlink every call from its result."""
        if isinstance(value, str):
            return self.redact(value, marker, shapes=False)
        return self.redact_value(value, marker)

    def redact_value(self, value: Any, marker: str = HIDDEN, _depth: int = 0) -> Any:
        """`value` (text, numbers, or lists and dicts of them) with the secrets in it hidden.
        Besides the text in it: a number that is a secret (a numeric password) and a list that
        spells a secret out (byte numbers, or one character per item) are replaced by the
        text with the secret hidden. Anything else is returned as it is."""
        if not self.enabled:
            return value
        if isinstance(value, str):
            return self.redact(value, marker)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return self._number(value, marker)
        if isinstance(value, (dict, list, tuple)):
            if _depth >= MAX_DEPTH:
                return marker
            if isinstance(value, dict):
                return {
                    (self.redact(k, marker) if isinstance(k, str) else k): self.redact_value(
                        v, marker, _depth + 1
                    )
                    for k, v in value.items()
                }
            spelled = self._spelled(value, marker) if isinstance(value, (list, tuple)) else None
            if spelled is not None:
                return spelled
            items = [self.redact_value(v, marker, _depth + 1) for v in value]
            return tuple(items) if isinstance(value, tuple) else items
        return value

    def _number(self, value: float, marker: str) -> float | str:
        try:
            text = repr(value)
        except ValueError:  # more digits than Python shows
            return value
        if len(text) < MIN_SECRET_LENGTH:
            return value
        cleaned = self.redact(text, marker)
        return value if cleaned == text else cleaned

    def _spelled(self, items: list[Any] | tuple[Any, ...], marker: str) -> str | None:
        """The text a list spells when it holds a secret: byte numbers (`[115, 107, ...]`) or one
        character per item (`list(secret)`); None when it is neither or holds none."""
        if len(items) < MIN_SECRET_LENGTH:
            return None
        if type(items[0]) is int:
            if not all(type(n) is int and 0 <= n < 256 for n in items):
                return None
            numbers = [str(n) for n in items]
            texts: tuple[str, ...] = tuple(sep.join(numbers) for sep in (", ", ",", " "))
        elif type(items[0]) is str and len(items[0]) <= 1:
            if not all(type(c) is str and len(c) <= 1 for c in items):
                return None
            texts = ("".join(items),)
        else:
            return None
        for text in texts:
            cleaned = self.redact(text, marker)
            if cleaned != text:
                return cleaned
        return None

    def redact_json_text(self, raw: str, marker: str = HIDDEN) -> str:
        """A JSON document (as text) with the text inside it redacted. Anything that is not valid
        JSON is redacted as plain text."""
        if not self.enabled:
            return raw
        try:
            parsed = json.loads(raw)
        except (ValueError, RecursionError):
            return self.redact(raw, marker)
        cleaned = self.redact_value(parsed, marker)
        if cleaned == parsed:
            return raw
        try:
            return json.dumps(cleaned, ensure_ascii=False)
        except (TypeError, ValueError, RecursionError):
            return self.redact(raw, marker)


def _encodable(text: str) -> str:
    """`text`, with a character that cannot be written to a file (a lone surrogate, which a
    program can print and a model can send as `\\ud800`) spelled out instead: one such character
    would otherwise stop a log, a recording or the notebook from being written."""
    if text.isascii():
        return text
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-8", "backslashreplace").decode("utf-8")
    return text


def _grow(text: str, start: int, end: int) -> tuple[int, int]:
    """The word around a piece of a secret: what is glued to it goes too."""
    size = len(text)
    left = 0
    while start > 0 and left < EXPAND and text[start - 1] in _TOKEN_CHARS:
        start -= 1
        left += 1
    right = 0
    while end < size and right < EXPAND and text[end] in _TOKEN_CHARS:
        end += 1
        right += 1
    padding = 0
    while end < size and padding < 2 and text[end] == "=":
        end += 1
        padding += 1
    return start, end


# -- the shared redactor -----------------------------------------------------------------------------

_default: Redactor | None = None
_default_lock = threading.Lock()


def default_redactor() -> Redactor:
    """The redactor of this process: what the sandbox, the logs and the toolbox use unless they
    are given another."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Redactor().sync_environment()
        return _default


def set_default_redactor(redactor: Redactor | None) -> Redactor | None:
    """Replace the shared redactor (tests); returns the one that was there."""
    global _default
    with _default_lock:
        previous, _default = _default, redactor
        return previous
