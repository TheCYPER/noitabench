"""The box that code written by the player runs in (Code Mode, hook scripts, plugins).

The code never runs in this process. Each job is a fresh interpreter, started under macOS
`sandbox-exec` with a profile that

- allows no network of any kind and no other program to be started (no fork, no exec),
- lets the code read only the Python it runs on (its standard library and the packages of this
  environment, minus the game itself), the libraries the player installed (`.libs`) and its own
  scratch folder,
- lets it write only in that scratch folder, which is emptied afterwards (the notebook is
  reached through requests, so its quotas apply).

Around that the interpreter gets an empty environment (no keys), a limit on processor time
(`RLIMIT_CPU`, in the interpreter itself), a limit on resident memory (polled from here: macOS
ignores `RLIMIT_AS` and `RLIMIT_DATA`), a limit on the time the code spends running without
asking this side for anything, a cap on what it prints and on the size of the scratch folder
(every file or folder counts for at least 4 KB). The limits that only this side can enforce are
watched by a thread of their own, so that the code cannot use the time in which the loop that
serves it is busy or blocked. Everything the code does with the game or the notebook is a request over a pipe (`sandbox_child`
describes the messages) that the caller answers; the code never sees the game object.

Where `sandbox-exec` does not exist (any other system) the layers that run code refuse to
start: there is no unsandboxed fallback.

What the profile cannot shut out: macOS lets any program of the same user read the arguments
and the environment of every other program of that user (`sysctl KERN_PROCARGS2`), and no
sandbox rule covers it. `hide_startup_environment` blanks the key-like values of this process's
own start-up environment before the first job, so that the code cannot read this process's keys;
what other programs of the user hold in their environment (a shell with an exported key, say)
stays readable, so keep keys out of the shell that starts a run (`check_sandbox` warns when it
finds the keys of this process in other programs: `secrets_held_elsewhere`). Since the box has no
network the harm would be a secret printed, returned or written and so reaching the model or the
run's files; so everything that comes out of the box (what it prints and returns, what it asks
of the game and the notebook, what its stderr says) is passed through the `Redactor` of
`redact.py` first, which knows the key-like values of this process and of every program the box
could read (`Redactor.refresh`: before each job, every `REFRESH_SECONDS` while the job
asks for things, and again when it is over). System V shared
memory, semaphores and queues are not covered by `deny default` either: their system calls are
refused one by one. What the profile still lets the code see is the metadata (existence, size,
dates) of any path, though not its contents or a listing.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import logging
import os
import selectors
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .procenv import libproc, other_environments, procargs, startup_environment
from .redact import MIN_SECRET_LENGTH, SECRET_NAME, Redactor, default_redactor

log = logging.getLogger(__name__)

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
CHILD_SOURCE = Path(__file__).with_name("sandbox_child.py")
POLL_SECONDS = 0.02
SCRATCH_CHECK_SECONDS = 0.25
MAX_LINE_BYTES = 8 * 1024 * 1024  # one message
MAX_TOTAL_BYTES = 64 * 1024 * 1024  # all messages of a job
MAX_CALLS = 20_000  # requests of one job
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
ENTRY_COST = 4096  # what an entry of the scratch folder counts for, even when it is empty
REFRESH_SECONDS = 2.0  # how often a running job has the secrets of other programs looked up again
SYSV_SYSCALLS = tuple(
    f"SYS_{name}"
    for name in (
        "semsys", "msgsys", "shmsys", "semctl", "semget", "semop", "msgctl", "msgget", "msgsnd",
        "msgrcv", "shmat", "shmctl", "shmdt", "shmget",
    )
)  # fmt: skip

# Why a job was stopped (`JobResult.limit`)
CPU_TIME = "cpu_time"
MEMORY = "memory"
WAIT_TIME = "wall_time"
TOTAL_TIME = "total_time"
SCRATCH = "scratch"
MESSAGES = "messages"
CRASH = "crash"


@dataclass(frozen=True)
class Limits:
    cpu_seconds: int = 10  # processor time of the code
    wall_seconds: float = 30.0  # time the code runs without asking for anything, in all
    total_seconds: float = 300.0  # the whole job, including the time the caller takes
    memory_mb: int = 512  # resident memory
    output_chars: int = 20_000  # what the program prints
    scratch_mb: int = 32  # files the code may leave in its scratch folder
    file_bytes: int = 8 * 1024 * 1024  # one file
    open_files: int = 256


@dataclass
class JobResult:
    """How a job ended. `done` is the code's own final message (None when it was stopped)."""

    done: dict[str, Any] | None
    limit: str | None = None
    detail: str = ""
    exit_code: int | None = None
    peak_mb: float = 0.0
    wall_seconds: float = 0.0
    calls: int = 0
    stderr: str = ""
    learned: int = 0  # secrets the redactor came to know while the job ran (after its start)


Handler = Callable[[dict[str, Any]], dict[str, Any]]


# -- availability ----------------------------------------------------------------------------------


def sandbox_available() -> bool:
    return sys.platform == "darwin" and os.access(SANDBOX_EXEC, os.X_OK)


@lru_cache(maxsize=1)
def check_sandbox() -> None:
    """Raise `ConfigError` unless a box can be started here and keeps its promises. Cached."""
    if not sandbox_available():
        raise ConfigError(
            "layers L2 (Code Mode), L3 (hooks) and L5 (plugins) run the player's code in a box "
            f"made with {SANDBOX_EXEC}, which this system does not have. Use --minimal or "
            "--layers L0,L1 here: the code is never run without the box."
        )
    probe = Sandbox().run(
        {"kind": "code", "code": "import socket\nprint('ok')", "limits": _as_dict(Limits())},
        lambda _m: {"ok": False, "error": {"type": "RuntimeError", "message": "no"}},
    )
    if probe.done is None or probe.done.get("stdout", "").strip() != "ok":
        raise ConfigError(
            f"the box for the player's code could not be started: {probe.detail or probe.stderr}"
        )
    exposed = secrets_held_elsewhere()
    if exposed:
        names = sorted({name for _, name in exposed})
        pids = sorted({pid for pid, _ in exposed})
        log.warning(
            "the value of %s is also in the environment of %d other program(s) of this user "
            "(pids %s). Code running in the box can read it from there, and the box cannot "
            "prevent that. What comes out of the box is scrubbed of it (redact.py), but not "
            "against every way of smuggling it out: start the run from a shell that does not "
            "export the key, for example `env %s=... python -m noitabench ...`.",
            ", ".join(names),
            len(pids),
            ", ".join(str(pid) for pid in pids[:5]),
            names[0],
        )


def _as_dict(limits: Limits) -> dict[str, Any]:
    return {
        "cpu_seconds": limits.cpu_seconds,
        "output_chars": limits.output_chars,
        "file_bytes": limits.file_bytes,
        "open_files": limits.open_files,
    }


# -- the profile -----------------------------------------------------------------------------------


def _real(path: str | Path) -> str:
    return os.path.realpath(path)


def readable_paths() -> list[str]:
    """What the interpreter needs to read to start and to import the packages of this
    environment."""
    paths = {
        _real(sysconfig.get_path("stdlib")),
        _real(sysconfig.get_path("platstdlib")),
        _real(sysconfig.get_path("purelib")),
        _real(sysconfig.get_path("platlib")),
        _real(Path(sys.base_prefix) / "lib"),
        _real(Path(sys.exec_prefix) / "lib"),
        _real(Path(sys.prefix) / "lib"),
    }
    return sorted(p for p in paths if os.path.isdir(p))


def hidden_paths() -> list[str]:
    """Parts of the readable paths that the code must not see: the game itself."""
    hidden: set[str] = set()
    for folder in {sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}:
        base = Path(_real(folder))
        for name in ("noitabench", "noitabench_core"):
            hidden.add(str(base / name))
        # the files that name or point to the game: its .pth, its dist-info (which records where
        # the checkout is), the editable-install stubs
        hidden.update(str(p) for p in base.glob("noitabench*"))
        hidden.update(str(p) for p in base.glob("__editable__*noitabench*"))
    return sorted(hidden)


def build_profile(read: int, hidden: int, libs: bool) -> str:
    """The sandbox profile; paths are given to `sandbox-exec` as parameters (`-D`), never
    spliced into the text."""
    rules = [
        "(version 1)",
        "(deny default)",
        '(import "system.sb")',
        '(allow process-exec (literal (param "PYTHON")) (literal (param "PYTHON_REAL")))',
        '(allow file-read* (literal (param "PYTHON_REAL")) (literal (param "PYVENV_CFG")))',
        "(allow file-read-metadata)",
    ]
    rules += [f'(allow file-read* (subpath (param "READ{i}")))' for i in range(read)]
    if libs:
        rules.append('(allow file-read* (subpath (param "LIBS")))')
    rules.append('(allow file-read* file-write* (subpath (param "SCRATCH")))')
    rules += [f'(deny file-read* file-write* (subpath (param "HIDDEN{i}")))' for i in range(hidden)]
    # system.sb lets a process look up any XPC service; nothing here needs one
    rules.append('(deny mach-lookup (xpc-service-name-prefix ""))')
    rules.append("(deny network*)")
    # `deny default` does not cover System V shared memory, semaphores and queues (and no
    # `ipc-sysv*` rule does): objects made by the code would outlive the job and use up the few
    # the system has. Only the system calls themselves can be refused.
    rules.append(f"(deny syscall-unix (syscall-number {' '.join(SYSV_SYSCALLS)}))")
    return "\n".join(rules) + "\n"


# -- measuring a process ---------------------------------------------------------------------------


class _TaskInfo(ctypes.Structure):
    _fields_ = [
        ("virtual", ctypes.c_uint64),
        ("resident", ctypes.c_uint64),
        ("user", ctypes.c_uint64),
        ("system", ctypes.c_uint64),
        ("threads_user", ctypes.c_uint64),
        ("threads_system", ctypes.c_uint64),
        ("policy", ctypes.c_int32),
        ("faults", ctypes.c_int32),
        ("pageins", ctypes.c_int32),
        ("cow_faults", ctypes.c_int32),
        ("messages_sent", ctypes.c_int32),
        ("messages_received", ctypes.c_int32),
        ("syscalls_mach", ctypes.c_int32),
        ("syscalls_unix", ctypes.c_int32),
        ("context_switches", ctypes.c_int32),
        ("threads", ctypes.c_int32),
        ("running", ctypes.c_int32),
        ("priority", ctypes.c_int32),
    ]


_PROC_PIDTASKINFO = 4


def resident_bytes(pid: int) -> int | None:
    """Resident memory of a process, or None when it cannot be read (it is gone)."""
    try:
        info = _TaskInfo()
        got = libproc().proc_pidinfo(
            pid, _PROC_PIDTASKINFO, 0, ctypes.byref(info), ctypes.sizeof(info)
        )
    except (OSError, AttributeError):  # pragma: no cover - no libproc: ask ps
        return _resident_from_ps(pid)
    return int(info.resident) if got == ctypes.sizeof(info) else None


def _resident_from_ps(pid: int) -> int | None:  # pragma: no cover
    try:
        out = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout.strip()
        return int(out) * 1024 if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


# -- the start-up environment -----------------------------------------------------------------------


@lru_cache(maxsize=1)
def hide_startup_environment() -> int:
    """Blank the key-like values (`*_KEY`, `*_TOKEN`...) in the memory where this process's
    start-up environment lives, and return how many were blanked.

    The kernel hands that memory to any program of the same user that asks for the arguments of
    this process (`ps eww`, `sysctl KERN_PROCARGS2`), and the sandbox profile cannot refuse the
    question: without this, code in the box would read the API keys of the run. Python's own
    `os.environ` is a copy and stays as it was, so the SDKs still find their keys (a program
    started later with `subprocess` and no `env=` inherits the C-level copy, and sees them
    blanked). Only the main thread knows where its stack starts; anywhere else (and wherever the
    layout is not the one checked here) nothing is touched and 0 is returned."""
    if sys.platform != "darwin":
        return 0
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if not libc.pthread_main_np():
            return 0
        libc.pthread_self.restype = ctypes.c_void_p
        libc.pthread_get_stackaddr_np.restype = ctypes.c_void_p
        libc.pthread_get_stackaddr_np.argtypes = [ctypes.c_void_p]
        top = libc.pthread_get_stackaddr_np(libc.pthread_self())
        raw = procargs(libc, os.getpid())
        rest = raw[4:]
        start = top - len(rest)
        if ctypes.string_at(start, len(rest)) != rest:  # the strings are not where we think
            return 0
        blanked = 0
        for offset, entry in startup_environment(raw):
            name, _, value = entry.partition(b"=")
            if value and SECRET_NAME.search(name.decode("latin-1")):
                ctypes.memset(start + offset + len(name) + 1, ord("x"), len(value))
                blanked += 1
        return blanked
    except (OSError, AttributeError, ValueError):
        return 0


@lru_cache(maxsize=1)
def secrets_held_elsewhere() -> tuple[tuple[int, str], ...]:
    """`(pid, our variable)` of every other program of this user whose start-up environment
    holds the value of one of this process's key-like variables, such as the shell that
    exported an API key before starting the run.

    Code in the box can read those environments (see the module doc) and nothing here can
    blank them, so a run that finds some is told. Programs that Apple ships (`/bin/zsh`) do not
    give their environment away; ones that do not come from Apple (a Homebrew shell, an editor,
    another Python) do. (What the box reads there is hidden from its output by `redact.py`; the
    warning is about everything the redactor cannot do.)"""
    if sys.platform != "darwin":
        return ()
    ours = {
        value.encode("utf-8", "replace"): name
        for name, value in os.environ.items()
        if SECRET_NAME.search(name) and len(value) >= MIN_SECRET_LENGTH
    }
    if not ours:
        return ()
    found: list[tuple[int, str]] = []
    for pid, pairs in other_environments(os.getpid()):
        for _name, value in pairs:
            if value in ours:
                found.append((pid, ours[value]))
    return tuple(found)


def _folder_cost(folder: str, limit: int) -> int:
    """What the files and folders under `folder` weigh: their sizes, with at least `ENTRY_COST`
    for every entry (so that a flood of empty files counts too). Stops counting past `limit`."""
    total = 0
    stack = [folder]
    while stack and total <= limit:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    total += max(info.st_size, info.st_blocks * 512, ENTRY_COST)
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    if total > limit:
                        return total
        except OSError:
            continue
    return total


def _remove_tree(folder: str) -> None:
    """Remove a scratch folder, also when the code locked it (no permissions, immutable flags),
    so that nothing it did can make a job leave files behind."""
    shutil.rmtree(folder, ignore_errors=True)
    if not os.path.lexists(folder):
        return
    stack = [folder]
    folders: list[str] = []
    while stack:
        here = stack.pop()
        _unlock(here)
        folders.append(here)
        try:
            with os.scandir(here) as entries:
                listing = list(entries)
        except OSError:
            continue
        for entry in listing:
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
            else:
                _unlock(entry.path)
                try:
                    os.unlink(entry.path)
                except OSError:
                    pass
    for here in reversed(folders):
        try:
            os.rmdir(here)
        except OSError:
            pass


def _unlock(path: str) -> None:
    try:
        os.chflags(path, 0, follow_symlinks=False)  # immutable flags
    except (OSError, AttributeError, NotImplementedError):
        pass
    try:
        os.chmod(path, 0o700, follow_symlinks=False)
    except (OSError, NotImplementedError):
        pass


# -- the box ---------------------------------------------------------------------------------------


class Sandbox:
    """Starts jobs in the box. One `Sandbox` may run many jobs, one after the other.

    Everything that comes out of the box passes through `redactor` (default: the shared one of
    `redact.py`) on its way to the caller: the requests of the code before the handler sees
    them, the final report (`JobResult.done`) and the box's stderr. The redactor learns the
    secrets that exist (`Redactor.refresh`) before each job, every `REFRESH_SECONDS` while the code
    sends requests, and once more when the job is over, before its report is cleaned."""

    def __init__(
        self,
        *,
        libs: Path | None = None,
        limits: Limits | None = None,
        python: str | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self.libs = libs
        self.limits = limits or Limits()
        self.python = python or sys.executable
        self.redactor = redactor

    # -- starting --------------------------------------------------------------------------------

    def _command(self, scratch: str) -> list[str]:
        read = readable_paths()
        hidden = hidden_paths()
        libs = self.libs is not None and self.libs.is_dir()
        python = self.python
        params: dict[str, str] = {
            "PYTHON": python,
            "PYTHON_REAL": _real(python),
            "PYVENV_CFG": str(Path(sys.prefix) / "pyvenv.cfg"),
            "SCRATCH": scratch,
        }
        params.update({f"READ{i}": p for i, p in enumerate(read)})
        params.update({f"HIDDEN{i}": p for i, p in enumerate(hidden)})
        if libs:
            params["LIBS"] = _real(str(self.libs))
        command = [SANDBOX_EXEC]
        for key, value in params.items():
            command += ["-D", f"{key}={value}"]
        command += ["-p", build_profile(len(read), len(hidden), libs)]
        command += [python, "-I", "-B", "-c", CHILD_SOURCE.read_text(encoding="utf-8")]
        return command

    def run(self, job: dict[str, Any], handler: Handler) -> JobResult:
        """Run `job`; `handler` answers each request of the code (it may take as long as it
        likes: that time is not counted against the code)."""
        if not sandbox_available():
            raise ConfigError("the box for the player's code needs sandbox-exec (macOS)")
        hide_startup_environment()
        redactor = self.redactor if self.redactor is not None else default_redactor()
        redactor.refresh()
        scratch = _real(tempfile.mkdtemp(prefix="cave-"))
        errors = tempfile.TemporaryFile()  # noqa: SIM115 - closed in the finally below
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                self._command(scratch),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=errors,
                env={**ENV, "TMPDIR": scratch, "HOME": scratch},
                cwd=scratch,
                start_new_session=True,
                close_fds=True,
            )
            if self.libs is not None and self.libs.is_dir():
                job = {**job, "libs": _real(self.libs)}
            guarded, late = _guarded(handler, redactor)
            result = _Session(process, scratch, self.limits, guarded).run(job)
        finally:
            if process is not None:
                _kill(process)
            errors.seek(0)
            text = errors.read(4000).decode("utf-8", errors="replace")
            errors.close()
            _remove_tree(scratch)
        # a program that started while the job ran may have been read by it: look again before
        # anything of the job's report is let out
        result.learned = late[0] + redactor.refresh()
        result.stderr = redactor.redact(text)
        result.done = _clean_done(redactor, result.done)
        return result


def _guarded(handler: Handler, redactor: Redactor) -> tuple[Handler, list[int]]:
    """`handler`, given the requests of the code with their secrets hidden, and a counter of the
    secrets learned on the way. A job that goes on for a while has the secrets looked up again now
    and then (`REFRESH_SECONDS`), so that what the code reads from a program that starts after the
    job did is hidden from the next request on."""
    looked = time.monotonic()
    late = [0]

    def guarded(message: dict[str, Any]) -> dict[str, Any]:
        nonlocal looked
        if time.monotonic() - looked >= REFRESH_SECONDS:
            late[0] += redactor.refresh()
            looked = time.monotonic()
        return handler(redactor.redact_value(message))

    return guarded, late


def _clean_done(redactor: Redactor, done: dict[str, Any] | None) -> dict[str, Any] | None:
    """The code's final report with its secrets hidden. `value_json` is a JSON document in a
    string: it is read, cleaned and written again, so that text that JSON had to escape is
    found too."""
    if done is None:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in done.items():
        if key == "value_json" and isinstance(value, str):
            cleaned[key] = redactor.redact_json_text(value)
        else:
            cleaned[key] = redactor.redact_value(value)
    return cleaned


def _kill(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:  # once it is reaped its number may belong to someone else
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.kill()
        except ProcessLookupError:
            pass
    for pipe in (process.stdin, process.stdout):
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass
    process.wait()


@dataclass
class _Session:
    """One job in flight: the loop that serves the code's requests, and a monitor thread that
    watches the limits only this side can enforce. The monitor runs on its own because the
    loop can be busy for a long time (answering a request, or writing to a program that does not
    read), and a program that waits for nothing must not be able to use that time."""

    process: subprocess.Popen[bytes]
    scratch: str
    limits: Limits
    handler: Handler
    buffer: bytearray = field(default_factory=bytearray)
    total: int = 0
    calls: int = 0
    peak: int = 0
    host_time: float = 0.0  # time spent answering, which is not the program's own
    serving_since: float | None = None  # when the answer that is being worked on began
    started: float = field(default_factory=time.monotonic)
    last_scratch_check: float = 0.0
    hit: tuple[str, str] | None = None  # the limit the monitor stopped the program for
    clock: threading.Lock = field(default_factory=threading.Lock)
    stdout_fd: int = -1

    def run(self, job: dict[str, Any]) -> JobResult:
        assert self.process.stdin is not None and self.process.stdout is not None
        job = {**job, "limits": {**job.get("limits", {}), **_as_dict(self.limits)}}
        stdout_fd = self.stdout_fd = self.process.stdout.fileno()
        stdin_fd = self.process.stdin.fileno()
        os.set_blocking(stdout_fd, False)
        os.set_blocking(stdin_fd, False)
        selector = selectors.DefaultSelector()
        selector.register(stdout_fd, selectors.EVENT_READ)
        done: dict[str, Any] | None = None
        stopped: tuple[str, str] | None = None
        finished = threading.Event()
        monitor = threading.Thread(target=self._monitor, args=(finished,), daemon=True)
        monitor.start()
        try:
            self._send(stdin_fd, job)
            while done is None and stopped is None:
                events = selector.select(POLL_SECONDS)
                if self.hit is not None:
                    break
                if not events:
                    continue
                if not self._take_input():
                    break  # the code is gone, or sent too much
                done, stopped = self._serve(stdin_fd)
        except (BrokenPipeError, TimeoutError):
            pass
        finally:
            finished.set()
            monitor.join()
            selector.close()
        if done is None and stopped is None:
            stopped = self.hit
        return self._result(done, stopped)

    # -- one step of the loop ----------------------------------------------------------------------

    def _take_input(self) -> bool:
        """Read what the code has sent so far into the buffer. False when it is gone, or when it
        has sent more than it may (then `hit` says so)."""
        chunk = _read(self.stdout_fd)
        if chunk is None:
            return False
        self.total += len(chunk)
        self.buffer += chunk
        if self.total > MAX_TOTAL_BYTES or len(self.buffer) > MAX_LINE_BYTES:
            self.hit = (MESSAGES, "it sent too much to the game")
            return False
        return True

    def _serve(self, stdin_fd: int) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
        while (end := self.buffer.find(b"\n")) >= 0:
            line = bytes(self.buffer[:end])
            del self.buffer[: end + 1]
            try:
                message = json.loads(line)
            except (ValueError, RecursionError):
                return None, (CRASH, "it sent something unreadable")
            if not isinstance(message, dict):
                return None, (CRASH, "it sent something unreadable")
            if message.get("op") == "done":
                return message, None
            if message.get("op") != "call":
                return None, (CRASH, "it sent something unexpected")
            self.calls += 1
            if self.calls > MAX_CALLS:
                return None, (MESSAGES, "it made too many requests")
            began = time.monotonic()
            with self.clock:
                self.serving_since = began
            try:
                reply = self.handler(message)
            except Exception as err:  # noqa: BLE001 - the handler must not break the box
                reply = {
                    "ok": False,
                    "error": {"type": "RuntimeError", "message": type(err).__name__},
                }
            with self.clock:
                self.host_time += time.monotonic() - began
                self.serving_since = None
            self._send(stdin_fd, {"id": message.get("id"), **reply})
        return None, None

    def _monitor(self, finished: threading.Event) -> None:
        """Watch the limits until the job is over; on a breach, record it and kill the program
        (the loop then finds the pipe closed)."""
        while not finished.wait(POLL_SECONDS):
            hit = self._watch()
            if hit is not None:
                self.hit = hit
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)  # not reaped before we are done
                except (ProcessLookupError, PermissionError):
                    pass
                return

    def _watch(self) -> tuple[str, str] | None:
        """Look at the limits that only this side can enforce."""
        now = time.monotonic()
        limits = self.limits
        rss = resident_bytes(self.process.pid)
        if rss is not None:
            self.peak = max(self.peak, rss)
            if rss > limits.memory_mb * 1024 * 1024:
                return MEMORY, f"it used more than {limits.memory_mb} MB of memory"
        if now - self.started > limits.total_seconds:
            return TOTAL_TIME, f"it ran for more than {limits.total_seconds:g} seconds in all"
        with self.clock:
            serving = 0.0 if self.serving_since is None else now - self.serving_since
            own = now - self.started - self.host_time - serving
        if own > limits.wall_seconds:
            return WAIT_TIME, f"it ran for more than {limits.wall_seconds:g} seconds"
        if now - self.last_scratch_check >= SCRATCH_CHECK_SECONDS:
            self.last_scratch_check = now
            if _folder_cost(self.scratch, limits.scratch_mb * 1024 * 1024) > (
                limits.scratch_mb * 1024 * 1024
            ):
                return SCRATCH, f"it wrote more than {limits.scratch_mb} MB of files"
        return None

    def _send(self, fd: int, message: dict[str, Any]) -> None:
        data = (json.dumps(message, ensure_ascii=True, default=repr) + "\n").encode("ascii")
        deadline = time.monotonic() + max(self.limits.wall_seconds, 5.0)
        view = memoryview(data)
        while view:
            try:
                written = os.write(fd, view)
            except BlockingIOError:
                if time.monotonic() > deadline or self.hit is not None:
                    raise TimeoutError from None
                # a program that sends without reading would block us as it blocks itself:
                # take what it has sent (to be answered afterwards) so that it can go on
                if not self._take_input():
                    raise BrokenPipeError from None
                time.sleep(0.001)
                continue
            view = view[written:]

    def _result(self, done: dict[str, Any] | None, stopped: tuple[str, str] | None) -> JobResult:
        wall = time.monotonic() - self.started
        limit, detail = stopped if stopped else (None, "")
        _kill(self.process)
        code = self.process.returncode
        if done is None and limit is None:
            if code == -signal.SIGXCPU:
                limit, detail = CPU_TIME, f"it used more than {self.limits.cpu_seconds} seconds"
                detail += " of processor time"
            elif code == -signal.SIGXFSZ:
                limit, detail = SCRATCH, "it wrote a file that was too large"
            else:
                limit, detail = CRASH, f"it ended unexpectedly (exit code {code})"
        return JobResult(
            done=done,
            limit=limit,
            detail=detail,
            exit_code=code,
            peak_mb=round(self.peak / 2**20, 1),
            wall_seconds=round(wall, 3),
            calls=self.calls,
        )


def _read(fd: int) -> bytes | None:
    """What is waiting on the pipe, b"" when nothing is, None when the other end is closed."""
    try:
        data = os.read(fd, 1 << 16)
    except BlockingIOError:
        return b""
    except OSError:
        return None
    return data if data else None
