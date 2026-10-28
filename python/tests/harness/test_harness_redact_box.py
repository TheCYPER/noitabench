"""A secret that the box can really read must not leave it.

The secret sits in the start-up environment of another program (a sleeping Python that this test
starts), which is exactly what `sysctl KERN_PROCARGS2` lets the box read, or in the environment
of this process. The programs below read it, print it in all kinds of forms, return it, write
it to the notebook, hand it to the game, build plugins and hook scripts out of it, and none of
that may reach the model, the notebook, the logs or the recording. Only made-up secrets are used
and no failure message shows a value."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from agent_worlds import GROUND, START_X
from noitabench.agent import AgentSession, SessionConfig
from noitabench.harness import Budget, Workspace, build_toolbox
from noitabench.harness.layers import DEFAULT_LAYERS
from noitabench.harness.logs import RunLogs
from noitabench.harness.redact import HIDDEN, Redactor, set_default_redactor
from noitabench.harness.sandbox import Limits, Sandbox, sandbox_available
from rig import Rig, arena_game
from test_harness_redact import fake_value, holder_process, leaked

pytestmark = [
    pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec"),
    pytest.mark.skipif(sys.platform != "darwin", reason="reads other programs on macOS"),
]

# Box code that reads the secret of the holder program the way any program of the user could.
# The name of the variable is put together so that this text is not itself what is looked for.
READ = """
import base64, codecs, ctypes, ctypes.util
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
mib = (ctypes.c_int * 3)(1, 49, __PID__)
size = ctypes.c_size_t(0)
assert libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) == 0
buffer = ctypes.create_string_buffer(size.value)
assert libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) == 0
data = buffer.raw[: size.value]
name = b"FAKE_SERVICE" + b"_API_KEY="
start = data.index(name) + len(name)
raw = data[start : data.index(b"\\0", start)]
secret = raw.decode()
"""

SHOW = """
def show(v):
    r = v.encode()
    print("plain", v)
    print("reversed", v[::-1])
    print("upper", v.upper(), "rot13", codecs.encode(v, "rot13"))
    print("b64", base64.b64encode(r).decode(), base64.urlsafe_b64encode(r).decode())
    print("b64 bare", base64.b64encode(r).decode().rstrip("="))
    print("b64 inside", base64.b64encode(b"HOME=/Users/x;KEY=" + r + b";PATH=/bin").decode())
    print("hex", r.hex(), r.hex().upper())
    print("repr", repr(r), repr(v))
    print("numbers", list(r))
    print("b32", base64.b32encode(r).decode())
    print("start", v[:24], "end", v[-16:])
"""


def read_code(pid: int) -> str:
    return READ.replace("__PID__", str(pid))


@pytest.fixture
def holder() -> Iterator[tuple[int, str]]:
    value = fake_value("elsewhere")
    child = holder_process(FAKE_SERVICE_API_KEY=value)
    yield child.pid, value
    child.kill()
    child.wait()


@pytest.fixture
def shared() -> Iterator[Redactor]:
    """The shared redactor of this test only (so that nothing learnt here outlives it)."""
    mine = Redactor()
    previous = set_default_redactor(mine)
    yield mine
    set_default_redactor(previous)


def refuse(_message: dict[str, Any]) -> dict[str, Any]:
    return {"ok": False, "error": {"type": "RuntimeError", "message": "no"}}


def run_box(code: str, redactor: Redactor, handler: Any = refuse, **job: Any):
    job = {"kind": "code", "code": code, "limits": {}, **job}
    return Sandbox(limits=Limits(), redactor=redactor).run(job, handler)


def everything_in(*folders: Path) -> str:
    parts = []
    for folder in folders:
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file() and path.stat().st_size < 20_000_000:
                parts.append(path.read_bytes().decode("utf-8", errors="ignore"))
    return "\n".join(parts)


# -- the box itself -------------------------------------------------------------------------------


def test_the_box_really_can_read_it_and_its_forms_do_not_come_out(holder) -> None:
    pid, value = holder
    code = read_code(pid) + SHOW + "show(secret)\n"
    control = run_box(code, Redactor(enabled=False))
    assert control.done is not None and control.done["ok"], control.done
    shown = control.done["stdout"]
    # without redaction the box prints it in every form: this is what the rest is up against
    assert {"plain", "reversed", "hex", "base64", "numbers"} <= set(leaked(shown, value))

    result = run_box(code, Redactor(shapes=False))  # only known values, no key shapes
    assert result.done is not None and result.done["ok"], result.done
    out = result.done["stdout"]
    assert leaked(out, value) == [], leaked(out, value)
    assert out.count(HIDDEN) >= 10 and "plain" in out and "numbers" in out  # printed, but hidden
    assert len(out.splitlines()) == len(shown.splitlines())  # nothing else was lost


def test_what_the_code_asks_of_the_game_and_the_notebook_is_cleaned_first(holder) -> None:
    pid, value = holder
    code = read_code(pid) + (
        "game.say(x=secret)\n"
        "game.say(x=secret[::-1])\n"
        "game.say(x='ok-' + base64.b64encode(raw).decode())\n"
        "notes.write('notes/a.md', 'key: ' + secret)\n"
        "notes.write('notes/' + secret[:8] + '.md', raw.hex())\n"
        "game.say(x='plain words')\n"
    )
    commands = [
        {"name": "say", "summary": "s", "params": [{"name": "x", "doc": "", "required": True}]}
    ]
    seen: list[dict[str, Any]] = []

    def handler(message: dict[str, Any]) -> dict[str, Any]:
        seen.append(message)
        return {"ok": True, "value": {}}

    result = run_box(code, Redactor(shapes=False), handler, commands=commands)
    assert result.done is not None and result.done["ok"], result.done
    assert len(seen) == 6
    text = json.dumps(seen)
    assert leaked(text, value) == []
    assert [m["id"] for m in seen] == [1, 2, 3, 4, 5, 6]  # the messages themselves are intact
    assert seen[0]["args"] == {"x": HIDDEN} and seen[1]["args"] == {"x": HIDDEN}
    assert seen[3]["args"]["text"] == f"key: {HIDDEN}"
    assert seen[5]["args"] == {"x": "plain words"}  # what holds no secret is passed on as it was


def test_the_report_the_error_stderr_and_a_plugin_returning_it_are_cleaned(holder) -> None:
    pid, value = holder
    redactor = Redactor(shapes=False)
    code = read_code(pid) + "import os\nos.write(2, secret.encode())\nraise RuntimeError(secret)\n"
    result = run_box(code, redactor)
    assert result.done is not None and result.done["ok"] is False
    assert leaked(json.dumps(result.done), value) == [] and HIDDEN in result.done["error"]
    assert leaked(result.stderr, value) == [] and HIDDEN in result.stderr

    plugin = read_code(pid) + (
        "prompt_fragment = 'remember ' + secret\n"
        "@tool('knows ' + secret, {'type': 'object', 'properties': {'a': {'description': secret}}})\n"
        "def leaky(args):\n"
        "    print(secret)\n"
        "    return {'v': secret, 'r': secret[::-1], 'h': raw.hex(), 'n': [1, 2], secret: 3}\n"
    )
    described = run_box("", redactor, kind="describe", plugins={"leak": plugin})
    assert described.done is not None and described.done["ok"], described.done
    assert leaked(json.dumps(described.done), value) == []
    tool = described.done["described"]["tools"][0]
    assert tool["name"] == "leaky" and tool["description"].startswith("knows ")
    assert described.done["described"]["prompts"]["leak"].startswith("remember ")

    called = run_box("", redactor, kind="plugin_call", plugins={"leak": plugin}, tool="leaky")
    assert called.done is not None and called.done["ok"], called.done
    assert leaked(json.dumps(called.done), value) == []
    returned = json.loads(called.done["value_json"])  # still a valid document
    assert returned["n"] == [1, 2] and returned["v"] == HIDDEN and returned[HIDDEN] == 3


def test_a_job_without_a_secret_comes_back_exactly_as_it_was() -> None:
    code = "print('hello', 1.5, [1, 2])\nprint('x' * 5000)\n"
    on = run_box(code, Redactor())
    off = run_box(code, Redactor(enabled=False))
    assert on.done is not None and off.done is not None
    assert on.done["stdout"] == off.done["stdout"] and on.stderr == off.stderr
    assert {k: v for k, v in on.done.items()} == {k: v for k, v in off.done.items()}


# -- a game with the layers on -----------------------------------------------------------------------


def recording_rig(tmp_path: Path, *, enemy: bool = False) -> Rig:
    """The arena with every layer, its recording and `decisions.jsonl` in `logs/`."""
    folder = tmp_path / "rig"
    folder.mkdir()
    game = arena_game(folder / "arena", START_X)
    if enemy:
        game.spawn_enemy("longleg", START_X + 18, GROUND)
    workspace = Workspace(folder / "ws")
    session = AgentSession(
        game,
        config=SessionConfig(max_decisions=300),
        memory=workspace,
        recording_dir=folder / "logs",
    )
    logs = RunLogs(folder / "logs")
    toolbox = build_toolbox(
        session, workspace, Budget(), layers=DEFAULT_LAYERS, decisions_cap=300, logs=logs
    )
    return Rig(session, workspace, toolbox, logs, game, folder / "logs")


def close(rig: Rig) -> str:
    """Close the run and return everything it wrote (logs, recording, notebook)."""
    rig.session.close()
    rig.logs.close()
    return everything_in(rig.folder, rig.workspace.root)


def test_a_program_that_leaks_every_way_reaches_neither_model_nor_files(
    tmp_path: Path, holder, shared: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, elsewhere = holder
    ours = fake_value("harness")
    monkeypatch.setenv("FAKE_HARNESS_API_KEY", ours)  # a secret of this very process
    rig = recording_rig(tmp_path)
    half = len(ours) // 2
    program = (
        read_code(pid)
        + SHOW
        + (
            f"mine = {ours[:half]!r} + {ours[half:]!r}\n"
            "for n, v in enumerate((secret, mine)):\n"
            "    show(v)\n"
            "    notes.write('notes/leak%d.md' % n, 'key: ' + v + ' ' + v[::-1])\n"
            "    notes.write('notes/leak%d.md' % n, ' ' + raw.hex(), append=True)\n"
            "    game.walk_to(x=v)\n"  # an invalid command, with the secret as its argument
            "game.decide('walk_to(x=' + secret + '); inspect(x=' + mine + ')')\n"
            "game.inspect(x=60, y=159)\n"  # and a command that is fine
            "raise RuntimeError('failed with ' + secret + ' and ' + mine)\n"
        )
    )
    result = rig.call("run_code", code=program)
    shown = result.content
    for value in (elsewhere, ours):
        assert leaked(shown, value) == [], leaked(shown, value)
    assert HIDDEN in shown and "RuntimeError: failed with" in shown
    assert "Game commands run: 4" in shown  # the program went on until it failed itself

    # the notebook has what was written, minus the secret
    leak0 = rig.call("workspace_read", path="notes/leak0.md").content
    assert f"key: {HIDDEN} {HIDDEN}" in leak0
    listing = rig.call("workspace_list").content
    for value in (elsewhere, ours):
        assert (
            leaked(listing + leak0 + rig.call("workspace_search", query="key").content, value) == []
        )

    written = close(rig)
    for value in (elsewhere, ours):
        assert leaked(written, value) == [], leaked(written, value)
    decisions = (rig.folder / "decisions.jsonl").read_text()
    assert "walk_to" in decisions and HIDDEN in decisions  # the commands are logged, cleaned
    transcript = (rig.folder / "transcript.jsonl").read_text()
    assert '"kind":"code_run"' in transcript


def test_plugins_hooks_and_what_they_say_to_the_model_are_cleaned(
    tmp_path: Path, holder, shared: Redactor
) -> None:
    pid, value = holder
    rig = recording_rig(tmp_path, enemy=True)
    plugin = (
        read_code(pid)
        + SHOW
        + (
            "prompt_fragment = 'remember ' + secret\n"
            "@tool('tool that knows ' + secret,\n"
            "      {'type': 'object', 'properties': {'a': {'type': 'string', 'description': secret}}})\n"
            "def leaky(args):\n"
            "    show(secret)\n"
            "    return {'v': secret, 'r': secret[::-1], 'h': raw.hex()}\n"
            "@hook('damage')\n"
            "def on_damage(event):\n"
            "    print('plugin hook saw', secret)\n"
        )
    )
    broken = read_code(pid) + "raise RuntimeError('cannot start: ' + secret)\n"
    script = (
        read_code(pid) + "print('hook script saw', secret)\nnotes.write('notes/h.md', secret)\n"
    )
    rig.write("plugins/leak.py", plugin)
    rig.write("plugins/broken.py", broken)
    rig.write("scripts/leak.py", script)

    listing = rig.call("plugin_list").content
    assert leaked(listing, value) == [] and "tool that knows" in listing and "broken" in listing
    assert "cannot start" in listing  # the problem is reported, without the secret
    suffix = rig.toolbox.system_suffix()  # what joins the system prompt of a new conversation
    assert "NOTES YOU LEFT IN YOUR PLUGINS" in suffix and "remember" in suffix
    assert leaked(suffix, value) == [] and HIDDEN in suffix
    called = rig.call("plugin_call", name="leaky", args={"a": "x"}).content
    assert leaked(called, value) == [] and "The plugin tool finished." in called

    rig.call("hook_set", event="damage", action="run", script="leak")
    waited = rig.call("wait", ticks=25).content  # the enemy hurts: the script and the plugin hook
    assert "Hook h1 (damage" in waited and "hook script saw" in waited
    assert "plugin hook saw" in waited
    assert leaked(waited, value) == [], leaked(waited, value)
    assert leaked(rig.call("hook_list").content, value) == []
    assert leaked(rig.call("workspace_read", path="notes/h.md").content, value) == []

    written = close(rig)
    assert leaked(written, value) == [], leaked(written, value)
