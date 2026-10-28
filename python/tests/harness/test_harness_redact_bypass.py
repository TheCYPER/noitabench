"""Ways round the redactor that were found by attacking it, each kept as a test.

Only made-up secrets are used; no failure message shows a value. The tests that need the box
read a secret from a sleeping program that this test starts, as the box could read any other
program's start-up environment."""

from __future__ import annotations

import base64
import json
import secrets
import sys
import time
import urllib.parse
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from noitabench.harness import errors
from noitabench.harness.redact import HIDDEN, Redactor, set_default_redactor
from noitabench.harness.sandbox import Limits, Sandbox, sandbox_available
from test_harness_redact import fake_value, holder_process, leaked, only_values
from test_harness_redact_box import close, everything_in, read_code, recording_rig

needs_box = pytest.mark.skipif(
    not sandbox_available() or sys.platform != "darwin",
    reason="needs macOS sandbox-exec (the box reads other programs' environments there)",
)


def mixed_value(tag: str = "Mix") -> str:
    """A secret with upper and lower case letters but no key shape (words and hex)."""
    return f"{tag}-{secrets.token_hex(8)}-Alpha-{secrets.token_hex(8)}-Beta-{secrets.token_hex(6)}"


def read_code_of(pid_expression: str) -> str:
    """The box code that reads the secret (`secret`, `raw`) of the program whose number is the
    value of `pid_expression` in the box."""
    return read_code(0).replace("(1, 49, 0)", f"(1, 49, {pid_expression})")


@pytest.fixture
def shared() -> Iterator[Redactor]:
    mine = Redactor()
    previous = set_default_redactor(mine)
    yield mine
    set_default_redactor(previous)


# -- hostile text: the redactor must neither hang nor crash -------------------------------------------

HOSTILE = {
    "jwt starts": "eyJ" * 70_000,
    "jwt start and run": ("eyJ" + "a" * 500) * 400,
    "private key headers": "-----BEGIN PRIVATE KEY-----" * 12_000,
    "private key header, long run": "-----BEGIN " + "A " * 150_000,
    "bearer": "Bearer " + " " * 200_000 + "x",
    "url credentials": "://a:" * 40_000,
    "url credentials, long run": "://a:" + "b" * 200_000,
    "token boundary": "aB3_" * 60_000,
    "slashes": "a/" * 100_000,
    "key prefixes": "sk-" * 60_000,
    "key prefix, long": "sk-ant-" + "A1" * 100_000,
    "dashes": "-" * 200_000,
    "equals": "=" * 200_000,
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_hostile_text_is_hidden_or_left_alone_in_a_short_time(name: str) -> None:
    redactor = Redactor()
    redactor.add([fake_value("hostile") for _ in range(5)])
    text = HOSTILE[name]
    started = time.perf_counter()
    out = redactor.redact(text)
    assert time.perf_counter() - started < 2.0, (name, len(text))
    assert isinstance(out, str)


def test_a_private_key_without_an_end_is_hidden_up_to_a_limit_not_ignored() -> None:
    redactor = Redactor()
    body = "MIIEowIBAAKCAQEA" + "x" * 50
    head = "-----BEGIN " + "RSA PRIVATE KEY-----\n"
    out = redactor.redact(f"before\n{head}{body}\nafter {'y' * 20_000}")
    assert out.startswith("before\n") and body not in out and HIDDEN in out
    assert out.endswith("y" * 5_000)  # only a limited stretch goes: not the rest of the text
    # a text with an end keeps what follows the end
    whole = f"{head}{body}\n-----END " + "RSA PRIVATE KEY-----\nafter"
    assert redactor.redact(whole) == f"{HIDDEN}\nafter"
    # two keys in one text
    two = f"{whole} and {whole}"
    assert redactor.redact(two) == f"{HIDDEN}\nafter and {HIDDEN}\nafter"


# -- numbers and lists that are text spelled out ------------------------------------------------------


def test_byte_numbers_in_data_are_hidden_not_only_in_text() -> None:
    value = fake_value("nums")
    redactor = only_values(value)
    numbers = list(value.encode())
    cleaned = redactor.redact_value(
        {"x": numbers, "y": [numbers], "z": tuple(numbers), "n": [1, 2]}
    )
    assert json.dumps(cleaned).count(HIDDEN) == 3 and cleaned["n"] == [1, 2]
    assert leaked(json.dumps(cleaned), value) == []
    # as the JSON document that a program returned
    document = json.dumps({"bytes": numbers, "ok": True})
    assert leaked(redactor.redact_json_text(document), value) == []
    assert json.loads(redactor.redact_json_text(document))["ok"] is True
    # inside a longer list of bytes
    longer = [10, 20, 30, *numbers, 40, 50]
    assert leaked(json.dumps(redactor.redact_value(longer)), value) == []
    # a short list of ordinary numbers, or numbers above a byte, is not touched
    assert redactor.redact_value([1, 2, 3, 4, 5, 6, 7, 8, 9]) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert redactor.redact_value([1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000]) == [
        *range(1000, 10000, 1000)
    ]


def test_one_character_per_item_in_a_list_is_hidden() -> None:
    value = fake_value("chars")
    redactor = only_values(value)
    for spelled in (list(value), tuple(value), list(value[::-1])):
        cleaned = redactor.redact_value({"v": spelled})
        assert leaked(json.dumps(cleaned), value) == [] and HIDDEN in json.dumps(cleaned)
    assert redactor.redact_value(list("abcdefghij")) == list("abcdefghij")


def test_a_number_that_is_a_secret_is_hidden() -> None:
    value = "4815162342"  # a numeric password
    redactor = only_values(value)
    assert redactor.redact_value({"pin": int(value), "n": 7, "t": True}) == {
        "pin": HIDDEN,
        "n": 7,
        "t": True,
    }
    assert redactor.redact_json_text(json.dumps({"v": int(value)})) == json.dumps({"v": HIDDEN})
    assert redactor.redact_value(12345678) == 12345678  # an ordinary number stays
    assert redactor.redact_value(1.5) == 1.5 and redactor.redact_value(float("nan")) != HIDDEN
    decimal = only_values("48151623.42")
    assert decimal.redact_value({"v": 48151623.42}) == {"v": HIDDEN}


# -- more spellings of a value ------------------------------------------------------------------------


def test_case_changed_forms_are_hidden() -> None:
    value = mixed_value()
    redactor = only_values(value)
    raw = value.encode()
    forms = [
        value.swapcase(),
        value.title(),
        value.capitalize(),
        value.casefold(),
        base64.b64encode(raw).decode().lower(),
        base64.b64encode(raw).decode().upper(),
        raw.hex().upper(),
    ]
    for form in forms:
        out = redactor.redact(f"x {form} y")
        assert out == f"x {HIDDEN} y", form[:12]


def test_hex_and_numbers_with_other_separators_are_hidden() -> None:
    value = fake_value("sep")
    redactor = only_values(value)
    raw = value.encode()
    pairs = [f"{b:02x}" for b in raw]
    forms = {
        "bytes.hex(':')": raw.hex(":"),
        "bytes.hex(' ')": raw.hex(" "),
        "bytes.hex('-')": raw.hex("-"),
        "comma": ", ".join(pairs),
        "0x": " ".join("0x" + p for p in pairs),
        "0x, ": ", ".join("0x" + p for p in pairs),
        "backslash x": "".join("\\x" + p for p in pairs),
        "percent": "".join("%" + p for p in pairs),
        "numbers;": ";".join(str(b) for b in raw),
        "numbers lines": "\n".join(str(b) for b in raw),
        "numbers tab": "\t".join(str(b) for b in raw),
    }
    for name, form in forms.items():
        out = redactor.redact(f"x {form} y")
        # (a separator that follows the last byte may go with it when the same bytes occur
        # earlier in the value, so the end of the text is not compared)
        assert out.startswith(f"x {HIDDEN}"), name
        assert not any(form[i : i + 12] in out for i in range(len(form) - 11)), name
    # and the percent-encoded form of base64
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        text = urllib.parse.quote(encode(raw).decode(), safe="")
        assert redactor.redact(f"q={text}&z") == f"q={HIDDEN}&z"
    # ...with a character that quote() has to escape in the middle of base64
    plus = next(
        v
        for v in (fake_value("p") + "~" * n for n in range(40))
        if "+" in base64.b64encode(v.encode()).decode()
    )
    other = only_values(plus)
    shown = urllib.parse.quote(base64.b64encode(plus.encode()).decode(), safe="")
    assert "%2B" in shown and other.redact(shown) == HIDDEN


def test_invisible_characters_and_fullwidth_letters_do_not_hide_a_value() -> None:
    value = mixed_value()
    redactor = only_values(value)
    joined = "\u200d".join(value)
    zero_width = "\u200b".join(value)
    soft = "\u00ad".join(value)
    bom = value[:20] + "\ufeff" + value[20:]
    fullwidth = "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in value)
    for name, form in (
        ("zwj", joined),
        ("zwsp", zero_width),
        ("soft hyphen", soft),
        ("bom", bom),
        ("fullwidth", fullwidth),
    ):
        out = redactor.redact(f"before {form} after")
        assert out == f"before {HIDDEN} after", name
    # the text around is not damaged, non-ASCII text without a secret is left as it is
    text = "Zażółć gęślą jaźń — 日本語のテキスト, naïve café: ｆｕｌｌｗｉｄｔｈ ok"
    assert redactor.redact(text) == text
    # a secret in non-ASCII text: only the secret goes
    assert redactor.redact(f"日本語 {value} 日本語") == f"日本語 {HIDDEN} 日本語"
    # fullwidth key shapes
    shaped = "ｓｋ－ａｎｔ－" + "abcdefghijklmnopqrstuvwxyz0123456789"
    assert HIDDEN in Redactor().redact(f"key {shaped} end")


def test_a_big_text_with_other_alphabets_is_handled_quickly() -> None:
    redactor = Redactor()
    redactor.add([mixed_value() for _ in range(30)])
    text = ("Ünïcödé テキスト — ok. " * 2000) + "x" * 20
    started = time.perf_counter()
    assert redactor.redact(text) == text
    assert redactor.redact(text * 40) == text * 40  # past the size where it is unfolded
    assert time.perf_counter() - started < 3.0


# -- errors.scrub keeps working -----------------------------------------------------------------------


def test_scrub_is_still_short_and_hides_values(shared: Redactor, monkeypatch: pytest.MonkeyPatch):
    value = mixed_value()
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", value)
    assert errors.scrub(f"failed with {value.swapcase()}") == "failed with [redacted]"


# -- through the box -----------------------------------------------------------------------------------

DECIDE_ATTACKS = {
    "hex escapes": "text = ''.join('\\\\x%02x' % b for b in raw)\n"
    "r = game.decide(\"memory_write(path='notes/a.md', text='\" + text + \"')\")\n",
    "unicode escapes": "text = ''.join('\\\\u%04x' % b for b in raw)\n"
    "r = game.decide(\"memory_write(path='notes/a.md', text='\" + text + \"')\")\n",
    "octal escapes": "text = ''.join('\\\\%03o' % b for b in raw)\n"
    "r = game.decide(\"memory_write(path='notes/a.md', text='\" + text + \"')\")\n",
    "joined literals": "text = ' '.join(repr(secret[i:i + 8]) for i in range(0, len(secret), 8))\n"
    "r = game.decide('memory_write(path=\"notes/a.md\", text=' + text + ')')\n",
    "bytes literal": "r = game.decide('memory_write(path=\"notes/a.md\", text=' + repr(raw) + ')')\n",
    "in a list": "text = ''.join('\\\\x%02x' % b for b in raw)\n"
    'r = game.decide("inspect(x=[\'" + text + "\'])")\n',
    "fullwidth letters": "text = ''.join(chr(ord(c) + 0xFEE0) if '!' <= c <= '~' else c for c in secret)\n"
    "r = game.decide(\"memory_write(path='notes/a.md', text='\" + text + \"')\")\n",
    "an invalid command": "text = ''.join('\\\\x%02x' % b for b in raw)\n"
    'r = game.decide("walk_to(x=\'" + text + "\')")\n',
}


@pytest.fixture
def holder() -> Iterator[tuple[int, str]]:
    value = fake_value("elsewhere")
    child = holder_process(FAKE_SERVICE_API_KEY=value)
    yield child.pid, value
    child.kill()
    child.wait()


@needs_box
@pytest.mark.parametrize("name", sorted(DECIDE_ATTACKS))
def test_a_command_written_as_text_is_cleaned_after_python_has_read_it(
    name: str, tmp_path: Path, holder: tuple[int, str], shared: Redactor
) -> None:
    pid, value = holder
    rig = recording_rig(tmp_path)
    program = read_code(pid) + DECIDE_ATTACKS[name] + "print(r['text'][:400])\n"
    shown = rig.call("run_code", code=program).content
    assert leaked(shown, value) == []
    written = close(rig)
    assert leaked(written, value) == [], (name, leaked(written, value))
    assert (rig.folder / "decisions.jsonl").read_text()  # something was recorded


@needs_box
def test_a_numeric_secret_is_hidden_as_a_number_and_as_text(
    tmp_path: Path, shared: Redactor
) -> None:
    value = "48151623"
    child = holder_process(FAKE_SERVICE_API_KEY=value)
    try:
        rig = recording_rig(tmp_path)
        program = read_code(child.pid) + (
            "game.walk_to(x=int(secret))\n"
            "game.decide('walk_to(x=%d)' % int(secret))\n"
            "game.decide('walk_to(x=0x%x)' % int(secret))\n"
            "game.decide('walk_to(x=%s)' % secret)\n"
            "print(int(secret), [int(secret)], {'k': int(secret)})\n"
        )
        shown = rig.call("run_code", code=program).content
        written = close(rig)
    finally:
        child.kill()
        child.wait()
    assert value not in shown and value not in written
    assert hex(int(value)) not in shown + written
    assert written.count("walk_to") >= 4 and HIDDEN in written


@needs_box
def test_a_command_written_as_text_without_a_secret_is_run_as_it_was(
    tmp_path: Path, shared: Redactor
) -> None:
    rig = recording_rig(tmp_path)
    program = (
        "r = game.decide(\"memory_write(path='notes/a.md', text='line one\\\\nl\\\\x69ne two'); "
        'inspect(x=60, y=159)")\n'
        "print(r['ok'], [c['command'] for c in r['results']])\n"
    )
    shown = rig.call("run_code", code=program).content
    assert "True ['memory_write', 'inspect']" in shown
    assert rig.workspace.read("notes/a.md", 0)["text"] == "line one\nline two"


@needs_box
def test_a_secret_built_in_the_notebook_from_small_pieces_does_not_stay(
    tmp_path: Path, holder: tuple[int, str], shared: Redactor
) -> None:
    pid, value = holder
    rig = recording_rig(tmp_path)
    program = read_code(pid) + (
        "for i in range(0, len(secret), 10):\n"  # pieces shorter than a window
        "    notes.write('notes/pieces.md', secret[i:i + 10], append=True)\n"
        "notes.write('notes/edit.md', 'A' * 4 + '@@' + 'B' * 4)\n"
        "for i in range(0, len(secret), 10):\n"
        "    notes.edit('notes/edit.md', '@@', secret[i:i + 10] + '@@')\n"
        "print(notes.read('notes/pieces.md')['text'][:60])\n"
    )
    shown = rig.call("run_code", code=program).content
    assert leaked(shown, value) == []
    for name in ("pieces", "edit"):
        stored = (rig.workspace.root / "notes" / f"{name}.md").read_text()
        assert leaked(stored, value) == [], name
        assert HIDDEN in stored
    assert leaked(rig.call("workspace_read", path="notes/pieces.md").content, value) == []
    assert leaked(close(rig), value) == []


@needs_box
def test_the_secret_in_a_file_name_a_search_or_an_edit_is_hidden(
    tmp_path: Path, holder: tuple[int, str], shared: Redactor
) -> None:
    pid, value = holder
    rig = recording_rig(tmp_path)
    program = read_code(pid) + (
        "for name in ('notes/' + secret + '.md', secret + '.md', 'skills/x/' + secret[:30]):\n"
        "    try:\n"
        "        notes.write(name, 'x')\n"
        "    except Exception as e:\n"
        "        print(type(e).__name__, e)\n"
        "notes.write('notes/a.md', 'alpha beta')\n"
        "print(notes.search(secret))\n"
        "print(notes.search(secret.upper()))\n"
        "try:\n"
        "    notes.edit('notes/a.md', secret, secret[::-1])\n"
        "except Exception as e:\n"
        "    print(e)\n"
        "print(notes.list())\n"
    )
    shown = rig.call("run_code", code=program).content
    assert leaked(shown, value) == [] and "bad_path" in shown and HIDDEN in shown
    names = "\n".join(rig.workspace.file_names())
    assert leaked(names, value) == [] and names == "notes/a.md"
    assert leaked(close(rig), value) == []


@needs_box
def test_a_plugin_that_returns_bytes_or_digits_as_data_is_cleaned(
    tmp_path: Path, holder: tuple[int, str], shared: Redactor
) -> None:
    pid, value = holder
    rig = recording_rig(tmp_path)
    plugin = read_code(pid) + (
        "@tool('numbers')\n"
        "def numbers(args):\n"
        "    return {'bytes': list(raw), 'chars': list(secret), 'tuple': tuple(raw)}\n"
    )
    rig.write("plugins/numbers.py", plugin)
    shown = rig.call("plugin_call", name="numbers", args={}).content
    assert "The plugin tool finished." in shown and leaked(shown, value) == []
    assert shown.count(HIDDEN) >= 3
    assert leaked(close(rig), value) == []


@needs_box
def test_a_program_that_starts_during_a_job_is_known_by_the_end_of_it() -> None:
    """The secrets are looked for before the job, every few seconds while it runs, and once more
    when it is over: a program that starts after the first look is still found."""
    redactor = Redactor(shapes=False)
    started: list[Any] = []
    value = fake_value("during")

    def handler(message: dict[str, Any]) -> dict[str, Any]:
        if message["name"] == "start":
            child = holder_process(FAKE_SERVICE_API_KEY=value)
            started.append(child)
            return {"ok": True, "value": child.pid}
        return {"ok": True, "value": None}

    code = (
        "pid = game.start()\n"
        + read_code_of("pid")
        + "print('read', secret)\n"
        + "print('again', secret[::-1])\n"
    )
    commands = [{"name": "start", "summary": "s", "params": []}]
    try:
        result = Sandbox(limits=Limits(), redactor=redactor).run(
            {"kind": "code", "code": code, "limits": {}, "commands": commands}, handler
        )
    finally:
        for child in started:
            child.kill()
            child.wait()
    assert result.done is not None and result.done["ok"], result.done
    assert result.done["stdout"] == f"read {HIDDEN}\nagain {HIDDEN}\n"


@needs_box
def test_requests_of_a_long_job_are_cleaned_of_what_started_since(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While a job runs the secrets are looked up again every REFRESH_SECONDS, before the next
    request is cleaned (here every request, so as not to wait)."""
    from noitabench.harness import sandbox

    monkeypatch.setattr(sandbox, "REFRESH_SECONDS", 0.0)
    value = fake_value("longjob")
    started: list[Any] = []
    seen: list[dict[str, Any]] = []

    def handler(message: dict[str, Any]) -> dict[str, Any]:
        if message["name"] == "start":
            started.append(holder_process(FAKE_SERVICE_API_KEY=value))
            return {"ok": True, "value": started[0].pid}
        seen.append(message)
        return {"ok": True, "value": None}

    code = "pid = game.start()\n" + read_code_of("pid") + "game.record(text=secret)\n"
    commands = [
        {"name": "start", "summary": "s", "params": []},
        {
            "name": "record",
            "summary": "s",
            "params": [{"name": "text", "doc": "", "required": True}],
        },
    ]
    try:
        result = Sandbox(limits=Limits(), redactor=Redactor(shapes=False)).run(
            {"kind": "code", "code": code, "limits": {}, "commands": commands}, handler
        )
    finally:
        for child in started:
            child.kill()
            child.wait()
    assert result.done is not None and result.done["ok"], result.done
    assert [m["name"] for m in seen] == ["record"]
    assert seen[0]["args"] == {"text": HIDDEN} and result.learned >= 1


@needs_box
def test_what_a_job_wrote_before_a_secret_was_known_is_cleaned_when_it_is_known(
    tmp_path: Path, holder: tuple[int, str]
) -> None:
    """The redactor does not know the secret when the job starts (a program that started a
    moment before it, say) and learns it at the end: the notebook is cleaned then."""
    pid, value = holder

    class Late(Redactor):
        def __init__(self) -> None:
            super().__init__()
            self.looks = 0

        def refresh(self) -> int:
            self.looks += 1
            return 0 if self.looks == 1 else super().refresh()

    late = Late()
    previous = set_default_redactor(late)
    try:
        rig = recording_rig(tmp_path)
        program = read_code(pid) + "notes.write('notes/late.md', 'key: ' + secret)\nprint(secret)\n"
        shown = rig.call("run_code", code=program).content
        stored = (rig.workspace.root / "notes" / "late.md").read_text()
        written = close(rig)
    finally:
        set_default_redactor(previous)
    assert late.looks >= 2 and leaked(shown, value) == []
    assert stored == f"key: {HIDDEN}"
    assert leaked(written, value) == []  # (nothing but the notebook was asked in that moment)


@needs_box
def test_big_messages_from_the_box_are_cleaned_in_a_short_time(shared: Redactor) -> None:
    shared.add([fake_value("big") for _ in range(10)])
    seen: list[int] = []

    def handler(message: dict[str, Any]) -> dict[str, Any]:
        seen.append(len(json.dumps(message)))
        return {"ok": True, "value": None}

    code = (
        "notes.write('notes/a.md', 'eyJ' * 400_000)\n"
        "notes.write('notes/b.md', '-----BEGIN PRIVATE KEY-----' * 40_000)\n"
        "notes.write('notes/c.md', 'x' * 1_000_000)\n"
        "print('eyJ' * 6_000)\n"
    )
    started = time.perf_counter()
    result = Sandbox(limits=Limits(), redactor=shared).run(
        {"kind": "code", "code": code, "limits": {}}, handler
    )
    assert time.perf_counter() - started < 15.0
    assert result.done is not None and result.done["ok"], result.done
    assert len(seen) == 3


# -- a secret that is already in the notebook (learnt too late to be kept out) --------------------------


def stale_workspace(root: Path, value: str) -> None:
    """A notebook with a secret in a file name and in a file, written as if before it was known."""
    from noitabench.harness import Workspace

    ws = Workspace(root)
    ws.write(f"notes/{value}.md", f"remember {value} and {value[::-1]}", False)


def test_a_stale_secret_in_the_notebook_does_not_reach_the_model_or_the_run_folder(
    tmp_path: Path, shared: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_harness_layers_game import play, texts_shown

    value = fake_value("stale")
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", value)
    shared.sync_environment()
    stale_workspace(tmp_path / "workspaces" / "stale", value)
    from noitabench.harness.adapters.scripted import Say, call

    script = [
        Say.tools(call("workspace_list")),
        Say.tools(call("workspace_search", query="remember")),
        Say.tools(call("workspace_read", path=f"notes/{value}.md")),
        *[Say.tools(call("wait", ticks=5)) for _ in range(10)],
    ]
    cfg, adapter, _summary = play(
        tmp_path, script, family="stale", layers=("L0", "L1"), max_decisions=6, context_limit=1_000
    )
    shown = "\n".join(texts_shown(adapter))
    assert leaked(shown, value) == [] and HIDDEN in shown
    assert len(adapter.conversations) >= 2, "a briefing started a second conversation"
    written = everything_in(cfg.out)
    assert leaked(written, value) == [], leaked(written, value)
    # the notebook is cleaned when the game is over, and the copy in the run folder is made
    # from the cleaned notebook: the file whose name held the secret is gone
    assert not [p for p in (cfg.out / "workspace").rglob("*") if p.is_file()]
    assert leaked(everything_in(tmp_path / "workspaces"), value) == []
    assert not list((tmp_path / "workspaces" / "stale").rglob(f"*{value}*"))


def test_scrubbing_a_notebook_rewrites_what_holds_a_secret_and_nothing_else(tmp_path: Path) -> None:
    from noitabench.harness import Workspace

    value = fake_value("scrub")
    redactor = only_values(value)
    ws = Workspace(tmp_path / "ws")
    ws.write("notes/plain.md", "nothing to see here", False)
    ws.write("notes/has.md", f"first line\nkey {value}\nlast line", False)
    ws.write(f"skills/{value}.md", "named after it", False)
    before = {name: (tmp_path / "ws" / name).stat().st_mtime_ns for name in ("notes/plain.md",)}
    touched = ws.scrub(redactor.redact)
    assert sorted(touched) == sorted(["notes/has.md", f"skills/{value}.md"])
    assert ws.read("notes/has.md")["text"] == f"first line\nkey {HIDDEN}\nlast line"
    assert ws.file_names() == ["notes/has.md", "notes/plain.md"] or sorted(ws.file_names()) == [
        "notes/has.md",
        "notes/plain.md",
    ]
    assert (tmp_path / "ws" / "notes" / "plain.md").stat().st_mtime_ns == before["notes/plain.md"]
    assert ws.scrub(redactor.redact) == []  # nothing left to do


def test_what_a_new_conversation_starts_with_is_cleaned(
    tmp_path: Path, shared: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The briefing is the model's own words, so a secret can only be in it if the model was
    shown one; whatever the way, the conversation that follows does not start with it."""
    from noitabench.harness.adapters.scripted import Say, call
    from test_harness_layers_game import play, texts_shown

    value = fake_value("briefing")
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", value)
    shared.sync_environment()
    script = [
        Say.tools(call("wait", ticks=3)),
        Say(text=f"Briefing: my key is {value} and I am in the arena."),
        *[Say.tools(call("wait", ticks=3)) for _ in range(8)],
    ]
    cfg, adapter, _ = play(
        tmp_path, script, layers=("L0", "L1"), max_decisions=5, context_limit=1_000
    )
    assert len(adapter.conversations) >= 2
    shown = "\n".join(texts_shown(adapter))
    assert "my key is" in shown and leaked(shown, value) == []
    first = next(i for i in adapter.conversations[1].history[0]["items"])
    assert "my key is" in first.text and HIDDEN in first.text
    assert leaked(everything_in(cfg.out), value) == []


def test_text_mode_replies_are_cleaned_too(
    tmp_path: Path, shared: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from noitabench.harness.adapters.scripted import Say
    from test_harness_layers_game import play, texts_shown

    value = fake_value("text")
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", value)
    shared.sync_environment()
    stale_workspace(tmp_path / "workspaces" / "stale", value)
    script = [
        Say(text="Let me look at my notes.\nmemory_search(query='remember')"),
        *[Say(text="wait(ticks=5)") for _ in range(4)],
    ]
    cfg, adapter, _ = play(
        tmp_path, script, family="stale", mode="text", layers=("L0", "L1"), max_decisions=3
    )
    shown = "\n".join(texts_shown(adapter))
    assert "remember" in shown and HIDDEN in shown and leaked(shown, value) == []
    assert leaked(everything_in(cfg.out), value) == []


def test_a_helper_reading_a_stale_secret_is_shown_none(
    tmp_path: Path, shared: Redactor, monkeypatch: pytest.MonkeyPatch, make_game
) -> None:
    from layer_context import make_rig
    from noitabench.harness import ToolCall
    from noitabench.harness.adapters.scripted import Say, call
    from noitabench.harness.model import ToolResult
    from noitabench.harness.subagents import register_l4

    value = fake_value("helper")
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", value)
    shared.sync_environment()
    script = [
        Say.tools(call("workspace_search", query="remember"), call("workspace_list")),
        Say(text="Read the notes."),
    ]
    rig = make_rig(tmp_path, make_game(), script, register=register_l4)
    rig.workspace.write(f"notes/{value}.md", f"remember {value}", False)
    out = rig.toolbox.execute([ToolCall("s1", "spawn_agent", {"task": "Read the notes."})])
    assert "Read the notes." in out.results[0].content
    conversation = rig.adapter.conversations[0]
    shown = [conversation.system]
    for entry in conversation.history:
        for item in entry.get("items", []):
            shown.append(item.content if isinstance(item, ToolResult) else item.text)
    joined = "\n".join(shown)
    assert "remember" in joined and HIDDEN in joined  # the helper did read the notes
    assert leaked(joined, value) == []
    rig.logs.close()
    assert leaked(everything_in(tmp_path / "logs"), value) == []


# -- text that cannot be written -----------------------------------------------------------------------


def test_a_lone_surrogate_is_spelled_out_not_passed_on(tmp_path: Path) -> None:
    """A program can print one and a model can send one as `\\ud800`; written to a log it would
    stop the run."""
    from noitabench.harness.logs import RunLogs

    redactor = Redactor()
    assert redactor.redact("a\ud800b") == "a\\ud800b"
    assert redactor.redact_value({"k\udfff": ["x\ud800", 3]}) == {"k\\udfff": ["x\\ud800", 3]}
    assert json.loads(redactor.redact_json_text('{"a": "\\ud800 text"}')) == {"a": "\\ud800 text"}
    assert redactor.redact("Zażółć — 日本語") == "Zażółć — 日本語"  # other text is left alone
    previous = set_default_redactor(redactor)
    try:
        logs = RunLogs(tmp_path)
        logs.transcript("results", results=[{"content": "printed \ud800 and \udfff"}])
        logs.call({"error": "\ud800"})
        logs.close()
    finally:
        set_default_redactor(previous)
    assert "\\ud800" in (tmp_path / "transcript.jsonl").read_text(encoding="utf-8")


@needs_box
def test_a_program_that_prints_a_lone_surrogate_does_not_stop_the_run(
    tmp_path: Path, shared: Redactor
) -> None:
    rig = recording_rig(tmp_path)
    program = (
        "print('a\\ud800b')\ngame.walk_to(x='\\udfff')\ngame.decide(\"walk_to(x='\\\\ud800')\")\n"
    )
    shown = rig.call("run_code", code=program).content
    assert "a\\ud800b" in shown
    rig.logs.transcript("results", results=[{"content": shown}])
    assert close(rig)  # the recording and the logs were written and closed


def test_wand_range_arguments_do_not_come_back(
    tmp_path: Path, shared: Redactor, monkeypatch: pytest.MonkeyPatch, make_game
) -> None:
    from layer_context import make_rig
    from noitabench.harness import ToolCall
    from noitabench.harness.wandrange import register_wand_range

    value = fake_value("wand")
    monkeypatch.setenv("FAKE_GATEWAY_TOKEN", value)
    shared.sync_environment()
    rig = make_rig(tmp_path, make_game(), register=register_wand_range)
    calls = [
        ToolCall("w1", "wand_range", {"slots": [value], "stats": {"capacity": 3}}),
        ToolCall("w2", "wand_range", {"wand": 0, "slots": [value, value[::-1]]}),
        ToolCall("w3", "wand_range", {"stats": {value: 1}, "slots": ["x"]}),
    ]
    for result in rig.toolbox.execute(calls).results:
        assert leaked(result.content, value) == []
    rig.logs.close()
    assert leaked(everything_in(tmp_path / "logs"), value) == []
