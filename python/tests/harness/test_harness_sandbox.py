"""The box that the player's code runs in: it must keep every promise it makes.

Each test starts a real interpreter under `sandbox-exec` and asks it to do something that the
box forbids; the code reports what happened. The tests need macOS."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from dataclasses import replace
from pathlib import Path

import pytest
from noitabench.harness.errors import ConfigError
from noitabench.harness.sandbox import (
    CPU_TIME,
    CRASH,
    MEMORY,
    SCRATCH,
    TOTAL_TIME,
    WAIT_TIME,
    JobResult,
    Limits,
    Sandbox,
    build_profile,
    check_sandbox,
    sandbox_available,
)

pytestmark = pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")

REPO = Path(__file__).resolve().parents[3]


def refuse(_message: dict) -> dict:
    return {"ok": False, "error": {"type": "RuntimeError", "message": "no"}}


def run(code: str, *, limits: Limits | None = None, handler=refuse, libs: Path | None = None):
    return Sandbox(limits=limits or Limits(), libs=libs).run(
        {"kind": "code", "code": code, "limits": {}}, handler
    )


def stdout(result: JobResult) -> str:
    assert result.done is not None, (result.limit, result.detail, result.stderr)
    assert result.done["ok"], result.done.get("error")
    return str(result.done["stdout"])


def attempt_code(*snippets: str) -> str:
    """Code that tries each snippet and prints `name: ALLOWED` or `name: refused`."""
    lines = ["import os, socket, subprocess, sys"]
    for n, snippet in enumerate(snippets):
        lines += [
            "try:",
            f"    {snippet}",
            f"    print('{n}: ALLOWED')",
            "except BaseException as e:",
            f"    print('{n}: refused', type(e).__name__)",
        ]
    return "\n".join(lines)


def verdicts(result: JobResult) -> list[str]:
    return [line.split(":")[1].split()[0] for line in stdout(result).splitlines()]


# -- a job that does nothing special --------------------------------------------------------------


def test_a_plain_job_runs_and_reports_what_it_printed() -> None:
    check_sandbox()
    result = run("print('hello')\nimport numpy\nprint(int(numpy.arange(4).sum()))")
    assert stdout(result) == "hello\n6\n"
    assert result.limit is None and result.exit_code is not None and result.wall_seconds < 5


def test_errors_are_reported_with_the_players_own_lines_only() -> None:
    result = run("x = 1\n\ndef f():\n    return 1 / 0\n\nf()")
    assert result.done is not None and result.done["ok"] is False
    error = result.done["error"]
    assert "ZeroDivisionError: division by zero" in error
    assert 'File "<run_code>", line 6' in error and "return 1 / 0" in error
    assert "sandbox_child" not in error and "site-packages" not in error
    assert "SyntaxError" in run("def (:").done["error"]


# -- no network ----------------------------------------------------------------------------------


def test_no_network_of_any_kind() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        result = run(
            attempt_code(
                f"socket.create_connection(('127.0.0.1', {port}), timeout=2)",
                "socket.create_connection(('1.1.1.1', 80), timeout=2)",
                "socket.getaddrinfo('example.com', 80)",
                "socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'x', ('8.8.8.8', 53))",
                "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1)",
                "socket.socket(socket.AF_UNIX).connect('/var/run/syslog')",
            )
        )
        assert verdicts(result) == ["refused"] * 6
        server.settimeout(0.2)
        with pytest.raises(OSError):  # nothing ever reached the server
            server.accept()
    finally:
        server.close()


# -- files -----------------------------------------------------------------------------------------


def test_it_cannot_read_what_is_outside_the_box(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    result = run(
        attempt_code(
            f"open({str(secret)!r}).read()",
            f"os.listdir({str(tmp_path)!r})",
            f"open({str(Path.home() / '.ssh' / 'id_rsa')!r}).read()",
            f"os.listdir({str(Path.home())!r})",
            f"open({str(Path.home() / '.zshrc')!r}).read()",
            f"open({str(REPO / 'pyproject.toml')!r}).read()",
            f"os.listdir({str(REPO)!r})",
            f"open({str(REPO / 'content' / 'materials.json')!r}).read()",
            "open('/etc/hosts').read()",
        )
    )
    assert verdicts(result) == ["refused"] * 9


def test_the_libraries_folder_does_not_open_the_rest_of_the_workspaces(tmp_path: Path) -> None:
    families = tmp_path / "workspaces"
    mine, other = families / "mine", families / "other"
    (mine / ".libs").mkdir(parents=True)
    (mine / ".libs" / "mylib.py").write_text("VALUE = 7\n")
    (mine / "notes").mkdir()
    (mine / "notes" / "own.md").write_text("my notes")
    (other / "notes").mkdir(parents=True)
    (other / "notes" / "secret.md").write_text("another family's notes")
    runs = tmp_path / "runs" / "r1" / "world"
    runs.mkdir(parents=True)
    (runs / "world.json").write_text('{"seed": 7}')
    libs = mine / ".libs"
    result = run(
        attempt_code(
            f"open({str(other / 'notes' / 'secret.md')!r}).read()",
            f"open({str(libs / '..' / '..' / 'other' / 'notes' / 'secret.md')!r}).read()",
            f"open({str(mine / 'notes' / 'own.md')!r}).read()",
            f"os.listdir({str(families)!r})",
            f"os.listdir({str(mine)!r})",
            f"open({str(runs / 'world.json')!r}).read()",
            f"os.listdir({str(tmp_path / 'runs')!r})",
            f"open({str(libs / 'mylib.py')!r}).read()",  # the one thing it may read
        ),
        libs=libs,
    )
    assert verdicts(result) == ["refused"] * 7 + ["ALLOWED"]


def test_it_cannot_write_outside_its_scratch_folder(tmp_path: Path) -> None:
    target = tmp_path / "written.txt"
    result = run(
        attempt_code(
            f"open({str(target)!r}, 'w').write('x')",
            "open('/tmp/cave-test-write', 'w').write('x')",
            f"open({str(REPO / 'cave-test-write')!r}, 'w').write('x')",
            f"open({str(Path.home() / 'cave-test-write')!r}, 'w').write('x')",
            f"os.mkdir({str(tmp_path / 'dir')!r})",
            f"os.rename({str(REPO / 'pyproject.toml')!r}, {str(tmp_path / 'p')!r})",
            "open('scratch-ok.txt', 'w').write('x')",  # the working folder is the scratch folder
            "open('scratch-ok.txt').read()",
        )
    )
    verdict = verdicts(result)
    assert verdict[:6] == ["refused"] * 6 and verdict[6:] == ["ALLOWED", "ALLOWED"]
    assert not target.exists() and not (tmp_path / "dir").exists()
    assert not Path("/tmp/cave-test-write").exists()
    assert not (REPO / "cave-test-write").exists()


def test_the_scratch_folder_is_gone_afterwards() -> None:
    first = run("import os\nopen('left-behind.txt', 'w').write('x')\nprint(os.getcwd())")
    folder = Path(stdout(first).strip())
    assert not folder.exists()
    second = run("import os\nprint(os.listdir('.'))")
    assert stdout(second).strip() == "[]"


def test_it_cannot_start_other_programs() -> None:
    result = run(
        attempt_code(
            "os.fork()",
            "subprocess.run(['/bin/ls'], capture_output=True)",
            "os.execv('/bin/ls', ['ls'])",
            "assert os.system('/usr/bin/touch started-by-system') == 0",
            "os.posix_spawn('/bin/ls', ['ls'], {})",
        )
    )
    assert verdicts(result) == ["refused"] * 5


def test_it_cannot_start_programs_through_the_c_library_either() -> None:
    code = textwrap.dedent(
        """
        import ctypes, ctypes.util, os, sys
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        argv = (ctypes.c_char_p * 2)(b"ls", None)
        envp = (ctypes.c_char_p * 1)(None)
        python = (ctypes.c_char_p * 3)(sys.executable.encode(), b"-c", None)
        pid = ctypes.c_int()
        print(libc.fork(), libc.syscall(2), libc.execve(b"/bin/ls", argv, envp))
        print(libc.posix_spawn(ctypes.byref(pid), b"/bin/ls", None, None, argv, envp))
        print(libc.posix_spawn(ctypes.byref(pid), sys.executable.encode(), None, None, python, envp))
        print(libc.system(b"/usr/bin/touch started.txt"), os.path.exists("started.txt"))
        """
    )
    lines = stdout(run(code)).splitlines()
    assert lines[0] == "-1 -1 -1"
    assert lines[1] != "0" and lines[2] != "0"  # posix_spawn answers with an error number
    assert lines[3].endswith("False") and not lines[3].startswith("0 ")


def test_it_cannot_signal_other_processes() -> None:
    result = run(attempt_code("os.kill(os.getppid(), 0)", "os.kill(1, 0)"))
    assert verdicts(result) == ["refused", "refused"]


def test_it_cannot_signal_the_group_of_the_program_that_started_it() -> None:
    result = run(
        attempt_code(
            "os.killpg(os.getpgid(os.getppid()), 0)",
            "os.kill(os.getppid(), 0)",
            "os.killpg(1, 0)",
            "os.setpriority(os.PRIO_PROCESS, os.getppid(), 5)",
            "import ctypes; assert ctypes.CDLL(None).ptrace(10, os.getppid(), 0, 0) == 0",
        )
    )
    assert verdicts(result) == ["refused"] * 5


def test_it_cannot_make_files_of_others_its_own(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    code = textwrap.dedent(
        f"""
        import ctypes, ctypes.util, os, shutil
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        S = {str(secret)!r}
        def clone():
            assert libc.clonefile(S.encode(), b"c.txt", 0) == 0
        def copy():
            assert libc.copyfile(S.encode(), b"d.txt", None, 0xF) == 0
        tries = {{
            "hardlink": lambda: os.link(S, "h.txt"),
            "symlink": lambda: (os.symlink(S, "s.txt"), open("s.txt").read()),
            "clonefile": clone,
            "copyfile": copy,
            "shutil": lambda: shutil.copy(S, "e.txt"),
            "rename": lambda: os.rename(S, "r.txt"),
            "dlopen": lambda: ctypes.CDLL(S),
        }}
        for name, fn in tries.items():
            try:
                fn()
                print(name, "ALLOWED")
            except BaseException as e:
                print(name, "refused", type(e).__name__)
        """
    )
    out = stdout(run(code))
    assert "ALLOWED" not in out and out.count("refused") == 7, out
    assert secret.read_text() == "top secret"


def test_it_cannot_read_the_environment_of_the_program_that_started_it() -> None:
    """macOS lets any program of a user read the arguments and environment of every other one
    (`sysctl KERN_PROCARGS2`) and no sandbox rule covers it: the host blanks its own key-like
    values before the first job. Other values stay readable, which shows the question is real."""
    box_code = textwrap.dedent(
        """
        import ctypes, ctypes.util, os
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        mib = (ctypes.c_int * 3)(1, 49, os.getppid())
        size = ctypes.c_size_t(0)
        assert libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) == 0
        buffer = ctypes.create_string_buffer(size.value)
        assert libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) == 0
        data = buffer.raw[: size.value]
        # the needles are put together here: the host's command line holds this very text
        print("key" if b"FAKE" + b"KEY-0123456789" in data else "no key",
              "token" if b"fake-" + b"token-value" in data else "no token",
              "plain" if b"PLAIN_NOTE=" + b"visible" in data else "no plain")
        """
    )
    host = textwrap.dedent(
        f"""
        import json, os
        from noitabench.harness.sandbox import Limits, Sandbox
        job = {{"kind": "code", "code": {box_code!r}, "limits": {{}}}}
        result = Sandbox(limits=Limits()).run(job, lambda m: {{"ok": False}})
        print(json.dumps([result.done["stdout"].strip(), os.environ["ANTHROPIC_API_KEY"],
                          os.environ["MY_TOKEN"]]))
        """
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "ANTHROPIC_API_KEY": "sk-ant-FAKEKEY-0123456789",
        "MY_TOKEN": "fake-token-value",
        "PLAIN_NOTE": "visible",
    }
    done = subprocess.run(
        [sys.executable, "-c", host],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    seen, key, token = json.loads(done.stdout.splitlines()[-1])
    assert seen == "no key no token plain"
    assert key == "sk-ant-FAKEKEY-0123456789" and token == "fake-token-value"  # the host's own


def test_a_key_that_other_programs_hold_is_found_and_the_run_is_told(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The box can read the environment of the user's other programs (a shell that exported
    the key, say), which nothing in the profile can stop: the run is warned instead."""
    from noitabench.harness import sandbox

    value = f"sk-fake-{os.getpid()}-{time.monotonic_ns()}"
    monkeypatch.setenv("COGBENCH_FAKE_API_KEY", value)
    holder = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        env={"PATH": "/usr/bin:/bin", "SOME_OTHER_KEY": value},
    )
    try:
        time.sleep(0.5)
        sandbox.secrets_held_elsewhere.cache_clear()
        assert (holder.pid, "COGBENCH_FAKE_API_KEY") in sandbox.secrets_held_elsewhere()
        check_sandbox.cache_clear()
        with caplog.at_level("WARNING", logger=sandbox.log.name):
            check_sandbox()
        warning = " ".join(r.getMessage() for r in caplog.records)
        assert "COGBENCH_FAKE_API_KEY" in warning and value not in warning
    finally:
        holder.kill()
        holder.wait()
        sandbox.secrets_held_elsewhere.cache_clear()
        check_sandbox.cache_clear()


def test_system_v_shared_memory_semaphores_and_queues_are_refused() -> None:
    """They are not covered by `deny default`, and what the code made would outlive the job."""
    result = run(
        textwrap.dedent(
            """
            import ctypes, ctypes.util
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            made = [libc.shmget(0x7a11, 4096, 0o1600), libc.semget(0x7a12, 1, 0o1600),
                    libc.msgget(0x7a13, 0o1600)]
            print(made)
            """
        )
    )
    try:
        assert stdout(result).strip() == "[-1, -1, -1]"
    finally:  # if the box ever lets one through, do not leave it in the machine
        for kind, flag in (("m", "-m"), ("s", "-s"), ("q", "-q")):
            ran = subprocess.run(["ipcs", flag], capture_output=True, text=True, check=False)
            listing = ran.stdout
            for row in listing.splitlines():
                parts = row.split()
                if len(parts) > 2 and parts[0] == kind and parts[2].startswith("0x00007a1"):
                    subprocess.run(["ipcrm", flag, parts[1]], check=False)


def test_the_game_itself_cannot_be_imported_or_read() -> None:
    site = [p for p in sys.path if p.endswith("site-packages")]
    code = attempt_code(
        "import noitabench",
        "import noitabench_core",
        "import noitabench.game",
        *[f"open({str(Path(p) / 'noitabench.pth')!r}).read()" for p in site],
        *[f"os.listdir({str(Path(p) / 'noitabench_core')!r})" for p in site],
        *[
            f"open({str(info / 'direct_url.json')!r}).read()"
            for p in site
            for info in Path(p).glob("noitabench*.dist-info")
        ],
    )
    assert set(verdicts(run(code))) == {"refused"}


def test_the_hidden_paths_win_over_the_readable_ones() -> None:
    from noitabench.harness import sandbox

    hidden = sandbox.hidden_paths()
    assert hidden, "this environment has the game installed next to the packages it may read"
    profile = build_profile(read=3, hidden=len(hidden), libs=True)
    assert profile.index('(subpath (param "READ0"))') < profile.index('(param "HIDDEN0")')
    assert "(deny default)" in profile and "(deny network*)" in profile
    assert "(allow network" not in profile and "process-fork" not in profile


# -- the environment ---------------------------------------------------------------------------------


def test_it_gets_an_empty_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setenv(name, "sk-secret-value-0123456789")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.test")
    monkeypatch.setenv("MY_TOKEN", "abcdefghijklmnop")
    result = run("import os\nprint(json.dumps(sorted(os.environ)))".replace("json.dumps", "repr"))
    names = eval(stdout(result))
    assert set(names) <= {"PATH", "LANG", "LC_ALL", "TMPDIR", "HOME", "__CF_USER_TEXT_ENCODING"}
    assert not [n for n in names if "KEY" in n or "TOKEN" in n or "ANTHROPIC" in n]
    raw = stdout(run("import os\nprint(dict(os.environ))"))
    assert "sk-secret" not in raw and "abcdefghijklmnop" not in raw


# -- limits -----------------------------------------------------------------------------------------


def test_a_processor_loop_is_killed() -> None:
    began = time.monotonic()
    result = run("while True:\n    pass", limits=replace(Limits(), cpu_seconds=1))
    assert result.done is None and result.limit == CPU_TIME, result
    assert time.monotonic() - began < 6


def test_a_memory_bomb_is_killed() -> None:
    began = time.monotonic()
    result = run(
        "chunks = []\nwhile True:\n    chunks.append(bytearray(b'x' * 50_000_000))",
        limits=replace(Limits(), memory_mb=300),
    )
    assert result.done is None and result.limit == MEMORY, result
    assert 300 <= result.peak_mb < 900  # it was caught soon after the limit, not at the end
    assert time.monotonic() - began < 10


def test_waiting_is_limited_but_the_callers_time_is_not() -> None:
    result = run("import time\ntime.sleep(60)", limits=replace(Limits(), wall_seconds=1))
    assert result.limit == WAIT_TIME and result.done is None

    def slow(_message: dict) -> dict:
        time.sleep(1.5)  # the game taking its time
        return {"ok": True, "value": 7}

    code = "from_sandbox = None\nimport sys\nsys.modules['game'].decide('x')\nprint('done')"
    fine = run(code, limits=replace(Limits(), wall_seconds=1), handler=slow)
    assert fine.limit is None and stdout(fine) == "done\n", fine


def test_the_whole_job_has_a_limit_too() -> None:
    def slow(_message: dict) -> dict:
        time.sleep(0.6)
        return {"ok": True, "value": 1}

    code = "import sys\nwhile True:\n    sys.modules['game'].observe()"
    result = run(code, limits=replace(Limits(), total_seconds=1.5), handler=slow)
    assert result.limit == TOTAL_TIME and result.done is None


def test_what_it_prints_is_capped() -> None:
    result = run("print('x' * 100_000)", limits=replace(Limits(), output_chars=1_000))
    assert result.done is not None and result.done["stdout_truncated"] is True
    assert len(result.done["stdout"]) == 1_000


def test_a_flood_of_files_is_stopped() -> None:
    code = "i = 0\nwhile True:\n    open(f'f{i}', 'wb').write(b'x' * 4_000_000)\n    i += 1"
    result = run(code, limits=replace(Limits(), scratch_mb=10, file_bytes=4_000_000))
    assert result.limit == SCRATCH and result.done is None


def test_a_flood_of_empty_files_and_folders_is_stopped_too() -> None:
    code = "i = 0\nwhile True:\n    open(f'f{i}', 'w').close()\n    i += 1"
    began = time.monotonic()
    result = run(code, limits=replace(Limits(), scratch_mb=1))
    assert result.limit == SCRATCH and result.done is None, result
    assert time.monotonic() - began < 10
    folders = "import os\ni = 0\nwhile True:\n    os.mkdir(f'd{i}')\n    i += 1"
    assert run(folders, limits=replace(Limits(), scratch_mb=1)).limit == SCRATCH


def test_a_scratch_folder_the_code_locked_is_removed_all_the_same() -> None:
    code = textwrap.dedent(
        """
        import os
        os.makedirs("a/b")
        open("a/b/f", "wb").write(b"x" * 100_000)
        open("a/g", "wb").write(b"y")
        os.chflags("a/g", 0x2)  # immutable
        os.chmod("a/b", 0)      # no permissions
        os.chmod("a", 0o500)
        print(os.getcwd())
        """
    )
    folder = Path(stdout(run(code)).strip())
    assert not folder.exists()


def test_memory_is_watched_while_the_game_is_busy_and_while_the_pipe_is_full() -> None:
    """A program that sends requests and never reads the answers blocks the loop that serves
    it; another thread of the program that waits for a slow answer does the same. Neither may
    buy the program time to use memory."""
    flood = textwrap.dedent(
        """
        import sys, time
        chan = sys.modules["game"].decide.__closure__[0].cell_contents.channel
        for i in range(40):
            chan.send({"op": "call", "id": i, "target": "game", "name": "observe", "args": {}})
        time.sleep(0.3)
        chunks = [bytearray(b"z") * 100_000_000 for _ in range(30)]
        print("allocated 3 GB")
        """
    )
    big = {"ok": True, "value": "y" * 30_000}
    began = time.monotonic()
    result = run(flood, handler=lambda _m: big)
    assert result.limit == MEMORY and result.done is None, result
    assert result.peak_mb < 1500 and time.monotonic() - began < 15

    waiting = textwrap.dedent(
        """
        import sys, threading, time
        threading.Thread(target=sys.modules["game"].observe).start()
        chunks = [bytearray(b"z") * 100_000_000 for _ in range(30)]
        print("allocated 3 GB")
        """
    )

    def slow(_message: dict) -> dict:
        time.sleep(1.5)
        return {"ok": True, "value": 1}

    result = run(waiting, handler=slow)
    assert result.limit == MEMORY and result.done is None and result.peak_mb < 1500, result


def test_a_flood_of_small_requests_is_stopped_soon() -> None:
    code = textwrap.dedent(
        """
        import sys
        chan = sys.modules["game"].decide.__closure__[0].cell_contents.channel
        for i in range(100_000):
            chan.send({"op": "call", "id": i, "target": "game", "name": "observe", "args": {}})
        """
    )
    began = time.monotonic()
    result = run(code, handler=lambda _m: {"ok": True, "value": 1})
    assert result.limit is not None and result.done is None, result
    assert time.monotonic() - began < 30


def test_one_enormous_file_is_refused() -> None:
    result = run(
        "open('big', 'wb').write(b'x' * 50_000_000)", limits=replace(Limits(), file_bytes=1_000_000)
    )
    assert result.done is not None and "File too large" in result.done["error"]


def test_garbage_on_the_pipe_ends_the_job() -> None:
    code = (  # whichever descriptor is the pipe to the game gets the garbage
        "import os, time\n"
        "for fd in range(3, 12):\n"
        "    try:\n"
        "        os.write(fd, b'this is not json\\n')\n"
        "    except OSError:\n"
        "        pass\n"
        "time.sleep(5)"
    )
    result = run(code)
    assert result.done is None and result.limit == CRASH, result


def test_requests_are_answered_in_order_and_errors_do_not_reach_the_outside() -> None:
    seen: list[dict] = []

    def handler(message: dict) -> dict:
        seen.append(message)
        if message["name"] == "boom":
            raise ZeroDivisionError("internal detail that must not leak")
        return {"ok": True, "value": {"n": len(seen)}}

    code = (
        "import sys\n"
        "g = sys.modules['game']\n"
        "print(g.observe()['n'], g.decide('wait')['n'])\n"
        "try:\n"
        "    sys.modules['notes'].write('a', 'b')\n"
        "except Exception as e:\n"
        "    print(type(e).__name__)\n"
    )
    result = run(code, handler=handler)
    assert stdout(result).splitlines()[0] == "1 2"
    assert [m["target"] for m in seen] == ["game", "game", "notes"]
    assert [m["name"] for m in seen] == ["observe", "decide", "write"]
    assert result.calls == 3

    class Boom(Exception):
        pass

    def exploding(_m: dict) -> dict:
        raise Boom("internal detail that must not leak")

    leaked = run("import sys\nsys.modules['game'].observe()", handler=exploding)
    assert leaked.done is not None and "internal detail" not in json.dumps(leaked.done)
    assert "RuntimeError" in leaked.done["error"] or "Boom" not in leaked.done["error"]


# -- libraries ----------------------------------------------------------------------------------------


def test_installed_libraries_are_readable_and_importable(tmp_path: Path) -> None:
    libs = tmp_path / ".libs"
    libs.mkdir()
    (libs / "mylib.py").write_text("VALUE = 41\n")
    assert stdout(run("import mylib\nprint(mylib.VALUE + 1)", libs=libs)) == "42\n"
    assert run("import mylib", libs=None).done["ok"] is False  # not without the folder
    # and the folder is read-only
    result = run(attempt_code(f"open({str(libs / 'new.py')!r}, 'w').write('x')"), libs=libs)
    assert verdicts(result) == ["refused"]


def test_check_sandbox_refuses_where_there_is_no_box(monkeypatch: pytest.MonkeyPatch) -> None:
    from noitabench.harness import sandbox

    check_sandbox.cache_clear()
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: False)
    with pytest.raises(ConfigError, match="never run without the box"):
        check_sandbox()
    check_sandbox.cache_clear()
