"""L5, libraries: the player may install extra Python libraries, from a fixed local list only.

    lib_list()          the libraries that can be installed, and which are
    lib_install(name)   install one with what it needs

The list is the *wheelhouse*: a folder of wheel files that was downloaded once, before any game,
and a lock file next to it (`wheelhouse.lock`) that pins every name, version and sha256. Nothing
else can be installed and nothing is downloaded: a name that is not in the lock is refused, every
wheel is checked against its hash before it is unpacked, and the installer is told not to use any
index. Libraries go to `workspaces/<family>/.libs/`, where the box reads them (and nothing else
can write them), so they stay with the notebook between games and disappear with it in the
control setting. Every install is written to the run's `transcript.jsonl`.

`uv pip install --no-index --no-deps --offline --target` does the unpacking when `uv` is found;
without it a built-in unpacker does the same job (a wheel is a zip file).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from noitabench.agent import CommandError

from .model import ToolSpec
from .prompt import LIB_INSTALL_DESCRIPTION, LIB_LIST_DESCRIPTION
from .toolbox import FREE, ToolDef, object_schema

if TYPE_CHECKING:
    from .layers import LayerContext

BUILT_IN = ("numpy", "scipy")  # always importable: they are part of the environment
UNPACKED_LIMIT = 1_500_000_000  # bytes a single install may unpack
INSTALL_TIMEOUT = 300
_LOCK_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)\s+--hash=sha256:([0-9a-f]{64})")
_REQUIRES = re.compile(r"^Requires-Dist:\s*([A-Za-z0-9][A-Za-z0-9._-]*)(.*)$", re.IGNORECASE)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def default_wheelhouse() -> Path:
    """The wheelhouse of this checkout (`wheelhouse/` next to `python/`), else `./wheelhouse`."""
    beside = Path(__file__).resolve().parents[3] / "wheelhouse"
    return beside if beside.is_dir() else Path("wheelhouse")


@dataclass(frozen=True)
class Wheel:
    name: str
    version: str
    sha256: str
    path: Path | None  # None when the file is missing from the folder


class InstallError(Exception):
    """Something that stops an install; the message is for the player."""


class Wheelhouse:
    """The libraries that may be installed."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.lock = self.directory.with_name(self.directory.name + ".lock")
        self._wheels = self._read()

    def _read(self) -> dict[str, Wheel]:
        files: dict[tuple[str, str], Path] = {}
        if self.directory.is_dir():
            for path in sorted(self.directory.glob("*.whl")):
                parts = path.name.split("-")
                if len(parts) >= 3:
                    files[(normalize(parts[0]), parts[1])] = path
        wheels: dict[str, Wheel] = {}
        if self.lock.is_file():
            for line in self.lock.read_text(encoding="utf-8").splitlines():
                found = _LOCK_LINE.match(line.strip())
                if found:
                    name = normalize(found.group(1))
                    version = found.group(2)
                    wheels[name] = Wheel(name, version, found.group(3), files.get((name, version)))
        return wheels

    def names(self) -> list[str]:
        return sorted(self._wheels)

    def get(self, name: str) -> Wheel | None:
        return self._wheels.get(normalize(name))

    def closure(self, name: str) -> list[Wheel]:
        """The wheel for `name` and, first, the wheels it needs (found in its metadata)."""
        order: list[Wheel] = []
        seen: set[str] = set()

        def visit(key: str) -> None:
            if key in seen:
                return
            seen.add(key)
            wheel = self._wheels.get(key)
            if wheel is None:
                return
            for need in self._needs(wheel):
                visit(need)
            order.append(wheel)

        visit(normalize(name))
        return order

    def _needs(self, wheel: Wheel) -> list[str]:
        if wheel.path is None:
            return []
        needs: list[str] = []
        with zipfile.ZipFile(wheel.path) as archive:
            meta = next((n for n in archive.namelist() if n.endswith(".dist-info/METADATA")), None)
            if meta is None:
                return []
            for line in archive.read(meta).decode("utf-8", "replace").splitlines():
                found = _REQUIRES.match(line)
                if found and "extra ==" not in found.group(2):
                    needs.append(normalize(found.group(1)))
        return needs

    # -- what is there ---------------------------------------------------------------------------

    @staticmethod
    def installed_in(target: Path) -> dict[str, str]:
        """`{name: version}` of what an install put in `target`."""
        out: dict[str, str] = {}
        if target.is_dir():
            for info in target.glob("*.dist-info"):
                stem = info.name[: -len(".dist-info")]
                name, _, version = stem.rpartition("-")
                if name:
                    out[normalize(name)] = version
        return out

    @staticmethod
    def built_in(name: str) -> str | None:
        if normalize(name) not in BUILT_IN:
            return None
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    def status(self, target: Path) -> list[dict[str, str]]:
        have = self.installed_in(target)
        rows: list[dict[str, str]] = []
        for name in sorted({*self._wheels, *BUILT_IN}):
            built = self.built_in(name)
            wheel = self._wheels.get(name)
            if name in have:
                row = {"name": name, "version": have[name], "status": "installed"}
            elif built is not None and (wheel is None or wheel.version == built):
                row = {"name": name, "version": built, "status": "built in"}
            elif wheel is not None and wheel.path is not None:
                row = {"name": name, "version": wheel.version, "status": "available"}
            else:
                continue
            rows.append(row)
        return rows

    # -- installing -------------------------------------------------------------------------------

    def install(self, name: str, target: Path) -> dict[str, Any]:
        key = normalize(name)
        built = self.built_in(key)
        wheel = self._wheels.get(key)
        if wheel is None and built is None:
            raise InstallError(
                f"`{name}` is not one of the libraries you can install: "
                f"{', '.join(self.names()) or 'none'}."
            )
        if wheel is None or (built is not None and built == wheel.version):
            return {"name": key, "status": "already there", "version": built}
        chain = self.closure(key)
        have = self.installed_in(target)
        todo = [
            w for w in chain if have.get(w.name) != w.version and self.built_in(w.name) != w.version
        ]
        if not todo:
            return {"name": key, "status": "already installed", "version": wheel.version}
        for w in todo:
            if w.path is None:
                raise InstallError(f"the file for {w.name} {w.version} is missing from the list")
            if _sha256(w.path) != w.sha256:
                raise InstallError(f"{w.name} {w.version} does not match its hash; not installed")
        target.mkdir(parents=True, exist_ok=True)
        via = _unpack_with_uv(todo, target) or _unpack_builtin(todo, target)
        done = self.installed_in(target)
        missing = [w.name for w in todo if done.get(w.name) != w.version]
        if missing:
            raise InstallError(f"the install did not finish ({', '.join(missing)} is missing)")
        return {
            "name": key,
            "status": "installed",
            "version": wheel.version,
            "installed": [f"{w.name} {w.version}" for w in todo],
            "via": via,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _unpack_with_uv(wheels: list[Wheel], target: Path) -> str | None:
    """Unpack with uv, offline. None when uv is not there or did not manage."""
    uv = shutil.which("uv")
    if uv is None:
        return None
    command = [
        uv, "pip", "install", "--python", sys.executable, "--no-index", "--no-deps", "--offline",
        "--target", str(target), *[str(w.path) for w in wheels],
    ]  # fmt: skip
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "UV_OFFLINE": "1",
        "UV_NO_PROGRESS": "1",
    }
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=INSTALL_TIMEOUT, env=env, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return "uv" if done.returncode == 0 else None


def _unpack_builtin(wheels: list[Wheel], target: Path) -> str:
    root = target.resolve()
    for wheel in wheels:
        assert wheel.path is not None
        with zipfile.ZipFile(wheel.path) as archive:
            if sum(i.file_size for i in archive.infolist()) > UNPACKED_LIMIT:
                raise InstallError(f"{wheel.name} unpacks to more than it may")
            for info in archive.infolist():
                relative = _destination(info.filename)
                if relative is None or info.is_dir():
                    continue
                out = (root / relative).resolve()
                if not out.is_relative_to(root):
                    raise InstallError(f"{wheel.name} holds a file outside the folder")
                out.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, out.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    out.chmod(mode | 0o600)
    return "built-in unpacker"


def _destination(member: str) -> str | None:
    """Where a file of a wheel goes, relative to the target; None for files that are not
    libraries (scripts, headers, data)."""
    if member.startswith("/") or ".." in Path(member).parts:
        raise InstallError(f"unsafe file name in a wheel: {member}")
    head, _, rest = member.partition("/")
    if head.endswith(".data"):
        kind, _, tail = rest.partition("/")
        return tail if kind in ("purelib", "platlib") and tail else None
    return member


# -- the tools -----------------------------------------------------------------------------------


class LibraryTools:
    def __init__(self, ctx: LayerContext) -> None:
        self.ctx = ctx

    @property
    def house(self) -> Wheelhouse:
        return Wheelhouse(self.ctx.wheelhouse or default_wheelhouse())

    def list(self, _args: dict[str, Any]) -> dict[str, Any]:
        target = self.ctx.workspace.libs_dir
        out: dict[str, Any] = {"libraries": self.house.status(target)}
        if not self.house.names():
            out["note"] = "No extra libraries are available."
        return out

    def install(self, args: dict[str, Any]) -> dict[str, Any]:
        name = args["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("`name` must be the name of a library")
        try:
            report = self.house.install(name.strip(), self.ctx.workspace.libs_dir)
        except InstallError as err:
            self._log(name, ok=False, detail=str(err))
            raise CommandError("install_failed", str(err)) from None
        self._log(name, ok=True, detail=str(report.get("status")), report=report)
        return report

    def _log(
        self, name: str, *, ok: bool, detail: str, report: dict[str, Any] | None = None
    ) -> None:
        if self.ctx.logs is not None:
            self.ctx.logs.transcript(
                "lib_install",
                name=str(name)[:80],
                ok=ok,
                detail=detail[:300],
                installed=(report or {}).get("installed", []),
                via=(report or {}).get("via"),
            )


def register_libraries(ctx: LayerContext) -> None:
    tools = LibraryTools(ctx)
    name_schema = {"name": {"type": "string", "description": "A name from lib_list."}}
    for spec, handler in (
        (ToolSpec("lib_list", LIB_LIST_DESCRIPTION, object_schema({})), tools.list),
        (
            ToolSpec("lib_install", LIB_INSTALL_DESCRIPTION, object_schema(name_schema, ["name"])),
            tools.install,
        ),
    ):
        ctx.toolbox.register(ToolDef(spec, FREE, handler))
