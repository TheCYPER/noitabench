"""What macOS tells any program of a user about the other programs of that user.

`sysctl KERN_PROCARGS2` returns the arguments and the start-up environment of a process to any
other process of the same user, except for programs that Apple ships. The box of `sandbox.py`
cannot be kept from asking (no sandbox rule covers it), so this module asks the same question the
same way, to learn what the box could learn: `sandbox.py` blanks the start-up environment of this
process and warns about keys held elsewhere, `redact.py` hides every such value from what leaves
the box.

Nothing here keeps or prints a value: the callers decide what to do with them.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

_KERN_PROCARGS2 = (1, 49)  # CTL_KERN, KERN_PROCARGS2
_PROC_ALL_PIDS = 1


@lru_cache(maxsize=1)
def libproc() -> Any:
    lib = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib")
    lib.proc_pidinfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    return lib


def all_pids() -> list[int]:
    lib = libproc()
    lib.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
    size = lib.proc_listpids(_PROC_ALL_PIDS, 0, None, 0)
    if size <= 0:
        return []
    pids = (ctypes.c_int * (size // ctypes.sizeof(ctypes.c_int) + 64))()
    got = lib.proc_listpids(_PROC_ALL_PIDS, 0, pids, ctypes.sizeof(pids))
    return [p for p in pids[: max(got, 0) // ctypes.sizeof(ctypes.c_int)] if p > 1]


def procargs(libc: Any, pid: int) -> bytes:
    """What `sysctl KERN_PROCARGS2` says about a process: argc, program, arguments, environment."""
    mib = (ctypes.c_int * 3)(*_KERN_PROCARGS2, pid)
    size = ctypes.c_size_t(0)
    if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
        raise OSError("sysctl KERN_PROCARGS2 failed")
    buffer = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
        raise OSError("sysctl KERN_PROCARGS2 failed")
    return buffer.raw[: size.value]


def startup_environment(raw: bytes) -> list[tuple[int, bytes]]:
    """`(offset, "NAME=value")` of every environment string in `raw[4:]` (see `procargs`)."""
    rest = raw[4:]
    argc = int.from_bytes(raw[:4], "little")
    at = rest.index(b"\0")  # the program path...
    while at < len(rest) and rest[at] == 0:  # ...and the padding after it
        at += 1
    for _ in range(argc):
        at = rest.index(b"\0", at) + 1
    found: list[tuple[int, bytes]] = []
    while at < len(rest):
        end = rest.index(b"\0", at)
        if end == at:
            break
        found.append((at, rest[at:end]))
        at = end + 1
    return found


def other_environments(own_pid: int) -> Iterator[tuple[int, list[tuple[str, bytes]]]]:
    """`(pid, [(name, value), ...])` for every other program whose environment can be read, the
    way the box could read it. Programs that are gone by the time they are asked, or that do not
    give theirs away, are left out. Nothing on other systems."""
    if sys.platform != "darwin":
        return
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        pids = all_pids()
    except (OSError, AttributeError):
        return
    for pid in pids:
        if pid == own_pid:
            continue
        try:
            entries = startup_environment(procargs(libc, pid))
        except (OSError, ValueError):  # not ours to read, or gone
            continue
        pairs: list[tuple[str, bytes]] = []
        for _, entry in entries:
            name, _, value = entry.partition(b"=")
            pairs.append((name.decode("latin-1"), value))
        yield pid, pairs
