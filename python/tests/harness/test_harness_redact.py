"""The redactor: what it knows, what forms of a secret it recognises, what it leaves alone.

Only made-up secrets are used here (values built from words, a counter and the clock); the real
environment of the machine is never printed, and nothing in a failure message shows a value."""

from __future__ import annotations

import base64
import codecs
import json
import os
import pickle
import random
import secrets
import subprocess
import sys
import time
import urllib.parse

import pytest
from noitabench.harness import errors
from noitabench.harness.procenv import procargs, startup_environment
from noitabench.harness.redact import (
    HIDDEN,
    MIN_SECRET_LENGTH,
    WINDOW,
    Redactor,
    acceptable,
    default_redactor,
    derive,
    set_default_redactor,
)

DARWIN = sys.platform == "darwin"
_counter = iter(range(10_000))


def fake_value(tag: str = "svc") -> str:
    """A secret without a key shape (lower case and digits, no capitals): two values share
    nothing but their tag, which is shorter than a window."""
    return f"{tag}-{secrets.token_hex(10)}-{next(_counter)}-{secrets.token_hex(10)}"


def only_values(*values: str) -> Redactor:
    """A redactor that knows these values and nothing else (no key shapes)."""
    redactor = Redactor(shapes=False)
    redactor.add(values)
    return redactor


def forms_of(value: str) -> dict[str, str]:
    """The forms the redactor promises to recognise, worked out here independently."""
    raw = value.encode("utf-8")
    return {
        "plain": value,
        "reversed": value[::-1],
        "upper case": value.upper(),
        "rot13": codecs.encode(value, "rot13"),
        "hex": raw.hex(),
        "HEX": raw.hex().upper(),
        "base64": base64.b64encode(raw).decode(),
        "base64 unpadded": base64.b64encode(raw).decode().rstrip("="),
        "base64 url": base64.urlsafe_b64encode(raw).decode(),
        "base64 url unpadded": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        "base32": base64.b32encode(raw).decode(),
        "base85": base64.b85encode(raw).decode(),
        "ascii85": base64.a85encode(raw).decode(),
        "percent": urllib.parse.quote(value, safe=""),
        "numbers": ", ".join(str(b) for b in raw),
        "numbers, no space": ",".join(str(b) for b in raw),
        "numbers, spaces": " ".join(str(b) for b in raw),
    }


def leaked(text: str, value: str) -> list[str]:
    """Which forms of `value` (or long pieces of them) are in `text`."""
    found = [name for name, form in forms_of(value).items() if form in text]
    found += [f"piece of {n}" for n, f in forms_of(value).items() if _piece_in(f, text)]
    if repr(value.encode()) in text or json.dumps(value) in text:
        found.append("repr")
    return sorted(set(found))


def _piece_in(form: str, text: str) -> bool:
    if "numbers" in form[:7] or len(form) < WINDOW:
        return False
    return any(form[i : i + WINDOW] in text for i in range(0, len(form) - WINDOW + 1, 3))


@pytest.fixture
def own_default():
    """A shared redactor of this test only."""
    mine = Redactor()
    previous = set_default_redactor(mine)
    yield mine
    set_default_redactor(previous)


# -- which values are worth hiding -------------------------------------------------------------------


def test_only_values_that_are_secrets_and_not_words_are_hidden() -> None:
    assert acceptable("a1b2c3d4e5f6")
    assert acceptable("plain-words-with-no-key-shape")
    assert not acceptable("short")  # shorter than MIN_SECRET_LENGTH
    assert not acceptable("1234567") and acceptable("12345678") and MIN_SECRET_LENGTH == 8
    assert not acceptable("        ") and not acceptable("")  # blank
    assert not acceptable("xxxxxxxxxxxxxxxx")  # what a blanked start-up environment holds
    assert not acceptable("0000000000000000") and not acceptable("abababababababab")
    assert not acceptable("elephants") and not acceptable("Disabled")  # a word
    assert acceptable("elephants-and-castles")  # ...but not a phrase
    assert acceptable("a" * 5 + "bcdefghijklmnop")  # letters only, but 20 of them
    assert not acceptable("z9" * 5000)  # too long to be a secret of a program
    assert not acceptable("abc\udcff\udcfe-undecodable-bytes")  # not text


def test_a_redactor_that_knows_nothing_changes_nothing() -> None:
    quiet = Redactor(shapes=False)
    text = "The cave is dark. You hear water. status_change new_material"
    assert quiet.redact(text) == text
    value = fake_value()
    off = Redactor(enabled=False)
    off.add([value])
    assert off.redact(f"x {value} y") == f"x {value} y"  # switched off: nothing is touched
    assert off.refresh() == 0


# -- forms of a value --------------------------------------------------------------------------------


@pytest.mark.parametrize("form", sorted(forms_of("x" * 20)))
def test_every_form_of_a_value_is_hidden(form: str) -> None:
    value = fake_value()
    redactor = only_values(value)
    text = forms_of(value)[form]
    out = redactor.redact(f"before {text} after")
    assert out == f"before {HIDDEN} after", form


def test_text_forms_that_need_escapes_are_hidden_too() -> None:
    value = 'ten"gerine\\umbrella-é-' + str(next(_counter)) + "-lantern"
    redactor = only_values(value)
    for shown in (
        json.dumps(value),
        json.dumps(value, ensure_ascii=False),
        repr(value),
        repr(value.encode("utf-8")),
        f"{{'key': {value!r}}}",
        urllib.parse.quote_plus(value),
    ):
        out = redactor.redact(f"see {shown} here")
        assert HIDDEN in out and leaked(out, value) == [], shown
    document = json.dumps({"a": [value, 1], value: 2})
    assert value not in redactor.redact_json_text(document)
    parsed = json.loads(redactor.redact_json_text(document))
    assert parsed == {"a": [HIDDEN, 1], HIDDEN: 2}  # still the same document, minus the secret


@pytest.mark.parametrize("encode", [base64.b64encode, base64.urlsafe_b64encode])
@pytest.mark.parametrize("shift", [0, 1, 2])
def test_base64_of_a_longer_text_is_hidden_wherever_the_value_falls(shift: int, encode) -> None:
    value = fake_value()
    raw = value.encode()
    redactor = only_values(value)
    prefix = b"PATH=/usr/bin;HOME=/Users/someone;" + b"." * shift
    blob = encode(prefix + raw + b";OTHER=1;more text after the value").decode()
    out = redactor.redact(f"data: {blob}")
    assert HIDDEN in out and out.startswith("data: ")
    # the whole four-character groups that lie inside the value, worked out from the layout alone
    first, last = -(-len(prefix) // 3), (len(prefix) + len(raw)) // 3
    inside = blob[4 * first : 4 * last]
    assert len(inside) > 40
    assert not any(inside[i : i + 8] in out for i in range(len(inside) - 8))


def test_a_piece_of_a_secret_is_hidden_from_a_dozen_characters_on() -> None:
    value = fake_value()
    redactor = only_values(value)
    assert len(value) > 40
    for piece in (value[:WINDOW], value[:30], value[5:25], value[-WINDOW:], value[-20:]):
        out = redactor.redact(f"cut: {piece} ...")
        assert out == f"cut: {HIDDEN} ...", piece
    # what was printed next to it goes too, up to a space
    assert redactor.redact(f"cut: {value[:20]}abc123XYZ end") == f"cut: {HIDDEN} end"
    # the stated limit: a shorter piece is not recognised
    assert redactor.redact(f"cut: {value[: WINDOW - 1]} ...") == f"cut: {value[: WINDOW - 1]} ..."


def test_a_short_value_is_found_whole_and_reversed() -> None:
    value = "Qz8Lm2Xr"  # eight characters: above the floor, below a window
    redactor = only_values(value)
    assert redactor.redact(f"a {value} b {value[::-1]} c") == f"a {HIDDEN} b {HIDDEN} c"
    assert redactor.redact("a Qz8Lm2X b") == "a Qz8Lm2X b"


def test_several_secrets_and_overlapping_finds_are_hidden_once_each() -> None:
    first, second = fake_value("one"), fake_value("two")
    redactor = only_values(first, second)
    out = redactor.redact(f"{first} and {second} and {first[:20]}{second[:20]}")
    assert out == f"{HIDDEN} and {HIDDEN} and {HIDDEN}"


def test_nested_data_is_cleaned_in_keys_and_values() -> None:
    value = fake_value()
    redactor = only_values(value)
    data = {"ok": True, "n": 3, "list": [f"x {value}", (value, 1.5)], f"k-{value}": {"deep": value}}
    cleaned = redactor.redact_value(data)
    assert value not in json.dumps(cleaned)
    assert cleaned["ok"] is True and cleaned["n"] == 3
    assert cleaned["list"][1] == (HIDDEN, 1.5)  # a tuple stays a tuple
    assert cleaned["list"][0] == f"x {HIDDEN}"
    deep: object = value
    for _ in range(200):  # absurdly deep: cut off rather than crash
        deep = [deep]
    assert HIDDEN in json.dumps(redactor.redact_value(deep))
    assert redactor.redact_value(None) is None and redactor.redact_value(7) == 7


def test_the_marker_can_be_chosen() -> None:
    value = fake_value()
    assert only_values(value).redact(f"a {value}", "[redacted]") == "a [redacted]"


def test_a_redactor_never_shows_what_it_knows() -> None:
    value = fake_value()
    redactor = only_values(value)
    assert value not in repr(redactor) and value not in str(redactor)
    assert "1 secrets" in repr(redactor) and redactor.count() == 1
    with pytest.raises(TypeError):
        pickle.dumps(redactor)


def test_the_number_of_secrets_is_bounded() -> None:
    from noitabench.harness import redact

    values = [fake_value("bound") for _ in range(redact.MAX_SECRETS + 50)]
    redactor = Redactor(shapes=False)
    redactor.add(values)
    assert redactor.count() == redact.MAX_SECRETS
    assert redactor.redact(values[0]) == values[0]  # the oldest were dropped
    assert redactor.redact(values[-1]) == HIDDEN


def test_forms_of_a_very_long_value_are_limited_to_its_plain_forms() -> None:
    pem = "-----BEGIN-----\n" + "\n".join(f"line-{i:04d}-of-a-long-private-text" for i in range(60))
    assert len(pem) > 256
    forms = derive(pem)
    assert forms.exact == frozenset()  # no lists of numbers for it
    assert pem[100:112] in forms.grams
    redactor = only_values(pem)
    assert HIDDEN in redactor.redact(f"x {pem[200:400]} y")
    assert HIDDEN in redactor.redact(pem[::-1])


# -- shapes ------------------------------------------------------------------------------------------


def shaped_examples() -> dict[str, str]:
    pad = "AbCdEfGhIjKlMnOpQrStUvWx"
    return {
        "anthropic": "sk-" + "ant-api03-" + pad + "-_" + pad,
        "openai": "sk-" + "proj-" + pad + pad,
        "google": "AI" + "zaSy" + pad + "0123456789",
        "tavily": "tv" + "ly-dev-" + pad,
        "github": "gh" + "p_" + pad + "0123456789",
        "github fine": "github" + "_pat_" + pad + "_" + pad,
        "slack": "xo" + "xb-1234567890-" + pad,
        "aws": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
        "jwt": "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0.abcDEF123_-ghi",
        "bearer": "Bearer " + pad + "0123456789",
        "random token": "kF9aQ2xLm8ZpT4vN7bRc1WjYs6HdE3Gu",
        "hex token": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "base64 token": "q83FdkP0vL+x2TzR1mYbN7aW9cUe4HgJ6oIsXy5KpVtZ/A8Dn3Cw",
    }


@pytest.mark.parametrize("name", sorted(shaped_examples()))
def test_strings_shaped_like_keys_are_hidden_without_being_known(name: str) -> None:
    example = shaped_examples()[name]
    redactor = Redactor()
    out = redactor.redact(f"token was {example}, then more")
    assert out == f"token was {HIDDEN}, then more", name


def test_a_private_key_and_the_password_of_a_url_are_hidden() -> None:
    redactor = Redactor()
    key = (
        "-----BEGIN "
        + "RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\nabcdefghijkl\n-----END "
        + ("RSA PRIVATE KEY-----")
    )
    out = redactor.redact(f"file:\n{key}\nend")
    assert "MIIEow" not in out and out.startswith("file:\n") and out.endswith("\nend")
    url = "postgres://admin:hunter22-hunter@db.example.com:5432/app"
    assert redactor.redact(f"connect {url} now") == (
        f"connect postgres://{HIDDEN}@db.example.com:5432/app now"
    )


def test_random_tokens_are_found_and_ordinary_text_is_not() -> None:
    redactor = Redactor()
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    rng = random.Random(7)
    misses = 0
    for n in range(300):
        token = "".join(rng.choice(chars) for _ in range(rng.randint(32, 64)))
        misses += redactor.redact(f"x {token} y") == f"x {token} y"
    assert misses <= 6  # a token without digits or without a capital is not recognised

    ordinary = [
        "You are in a cave. A creature came into view. interrupted (new_enemy) after 12 ticks.",
        "status_change_new_material_entered_liquid_hp_below_damage_event_hook",
        "workspaces/family-01/notes/chemistry-and-materials-v2/crossing-the-lava-river.md",
        "/Users/someone/Projects/NoitaClone/python/noitabench/harness/redact.py",
        "ObservationDigestStatusChangeNewMaterialEnteredLiquid2Names",
        "#" * 64 + "\n" + "." * 64 + "\n" + "=" * 40 + "\n" + "-" * 40,
        "..####..~~~~~~~~..SS.oo..\n" * 20,
        "123e4567-e89b-12d3-a456-426614174000",  # a UUID
        "e3b0c44298fc1c14",  # a short digest
        "Decision 41 (frame 6112): completed (ticks) 12.5 14.25 -3.75 " * 5,
        "x = " + "0123456789" * 6,
        json.dumps({"observation": {"hp": 100, "map": ["#" * 40, "." * 40]}, "ok": True}),
    ]
    for text in ordinary:
        assert redactor.redact(text) == text, text[:60]


# -- finding secrets ---------------------------------------------------------------------------------


def test_the_key_like_variables_of_this_process_are_picked_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key, token = fake_value("env-key"), fake_value("env-token")
    monkeypatch.setenv("FAKE_HARNESS_API_KEY", key)
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", token)
    monkeypatch.setenv("FAKE_SHORT_KEY", "abc")
    monkeypatch.setenv("FAKE_NOTE", fake_value("plain"))  # no key-like name
    redactor = Redactor(shapes=False).sync_environment()
    assert redactor.redact(f"{key} {token}") == f"{HIDDEN} {HIDDEN}"
    assert redactor.redact("abc is short") == "abc is short"
    plain = os.environ["FAKE_NOTE"]
    assert redactor.redact(plain) == plain


def test_a_variable_with_an_odd_name_can_be_named(monkeypatch: pytest.MonkeyPatch) -> None:
    value = fake_value("odd")
    monkeypatch.setenv("FAKE_GATEWAY_PASSPHRASE", value)  # PASSPHRASE is not in the list of names
    redactor = Redactor(shapes=False).sync_environment()
    assert redactor.redact(value) == value
    redactor.track("FAKE_GATEWAY_PASSPHRASE")
    redactor.sync_environment()
    assert redactor.redact(value) == HIDDEN
    redactor.track(None)  # nothing to track is fine


def holder_process(**env: str) -> subprocess.Popen[bytes]:
    """A program that sleeps with the given start-up environment, once it can be read."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        env={"PATH": "/usr/bin:/bin", **env},
    )
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    wanted = next(iter(env.values())).encode()
    for _ in range(100):
        try:
            if wanted in b"\0".join(e for _, e in startup_environment(procargs(libc, child.pid))):
                return child
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    child.kill()
    raise AssertionError("the holder program did not start")


@pytest.mark.skipif(not DARWIN, reason="other programs' environments are read on macOS")
def test_the_environment_of_other_programs_is_read_like_the_box_would() -> None:
    key = fake_value("elsewhere")
    plain = fake_value("plain")
    child = holder_process(
        FAKE_SERVICE_API_KEY=key,
        FAKE_SHORT_KEY="abc",
        FAKE_WORD_TOKEN="elephants",
        FAKE_BLANKED_SECRET="x" * 30,
        FAKE_PLAIN_NOTE=plain,
    )
    try:
        redactor = Redactor(shapes=False)
        assert redactor.refresh() >= 1
        assert redactor.redact(f"is {key} here") == f"is {HIDDEN} here"
        for kept in ("abc is short", "elephants walk", "x" * 30, plain):
            assert redactor.redact(kept) == kept  # too short, a word, blanked, no key-like name
    finally:
        child.kill()
        child.wait()
    # a program that is gone does not make its value fair game again: what was learnt stays
    redactor.refresh()
    assert redactor.redact(key) == HIDDEN


@pytest.mark.skipif(not DARWIN, reason="other programs' environments are read on macOS")
def test_a_refresh_costs_little_even_with_many_programs() -> None:
    redactor = Redactor()
    started = time.perf_counter()
    redactor.refresh()
    redactor.refresh()
    assert time.perf_counter() - started < 3.0
    text = "A cave. " * 5000
    started = time.perf_counter()
    for _ in range(5):
        assert redactor.redact(text) == text
    assert (time.perf_counter() - started) / 5 < 0.25  # 40,000 characters


# -- the error messages ------------------------------------------------------------------------------


def test_errors_redact_is_not_shortened_and_scrub_still_is(
    monkeypatch: pytest.MonkeyPatch, own_default: Redactor
) -> None:
    value = fake_value("scrub")
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", value)
    long_text = ("padding " * 400) + value + (" more" * 100)
    cleaned = errors.redact(long_text)
    assert value not in cleaned and HIDDEN in cleaned and len(cleaned) > 3000
    assert cleaned.endswith(" more" * 100)
    scrubbed = errors.scrub(long_text)
    assert len(scrubbed) <= errors.MAX_MESSAGE and value not in scrubbed
    assert errors.scrub(f"401 for {value} here") == "401 for [redacted] here"
    # the looser shapes of error messages stay
    assert errors.scrub("api_key: abcdefghijkl1234") == "[redacted]"
    assert errors.scrub("Bearer abcdefghijklmnop") == "[redacted]"


def test_the_shared_redactor_can_be_replaced_for_a_test(own_default: Redactor) -> None:
    assert default_redactor() is own_default
    other = Redactor(shapes=False)
    previous = set_default_redactor(other)
    assert previous is own_default and default_redactor() is other
    set_default_redactor(previous)
