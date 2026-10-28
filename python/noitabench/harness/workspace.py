"""L1: the workspace, a folder of text files that outlives a game.

    workspaces/<family>/notes/...    what the player wants to remember        } together at most
    workspaces/<family>/skills/...   how-tos it wrote down for itself         } 8,000 characters
    workspaces/<family>/plugins/...  code that adds tools to the player       } together at most
    workspaces/<family>/scripts/...  scripts the player runs                  } 64,000 characters
    workspaces/<family>/.libs/       libraries the player installed (not counted, not listed;
                                     only the harness writes there: `libs.py`)

The workspace is the `MemoryBackend` of the agent layer (`memory_write` and friends) and also
the target of the `workspace_*` tools. A path without a folder goes to `notes/`. Writes that would
go over a quota are refused with a message that says how much room is left; nothing is cut off
silently. Paths cannot leave the folder: only plain names of at most `MAX_PATH` characters are
accepted, never `..`, a leading `/` or `.`, backslashes, control characters or a symlink.

`plugins/` and `scripts/` exist only for the layers that use them (Code Mode, plugins). Without
those layers (`code_area=False`) they are ordinary folder names like any other: `scripts/a.md`
is stored as `notes/scripts/a.md` and counts against the 8,000 characters, so the larger code
area cannot be used to stretch the notebook.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from noitabench.agent.errors import CommandError

from .errors import ConfigError

NOTES_AREAS = ("notes", "skills")
CODE_AREAS = ("plugins", "scripts")
AREAS = NOTES_AREAS + CODE_AREAS
DEFAULT_AREA = "notes"
NOTES_QUOTA = 8_000
CODE_QUOTA = 64_000
MAX_PATH = 80
MAX_DEPTH = 3  # folder inside the area, then the file
MAX_FILES = 64
READ_LIMIT = 20_000  # characters one read returns; `offset` reads on
SEARCH_HITS = 20
HIT_WIDTH = 200
TEMP_PREFIX = ".tmp-"  # files being written; never listed or counted
LIBS_FOLDER = ".libs"  # installed libraries: outside the quotas, removed by `clear`
_NAME = re.compile(r"^[\w][\w.\- ]*$")  # no leading dot or space, no separators
FAMILY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def family_name(text: str) -> str:
    """A safe folder name made from `text` (the name of a run family)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")[:64]
    if not cleaned:
        raise ConfigError(f"`{text}` cannot be made into a family name")
    return cleaned


@dataclass(frozen=True)
class Quota:
    used: int
    limit: int

    @property
    def left(self) -> int:
        return max(self.limit - self.used, 0)

    def as_dict(self) -> dict[str, int]:
        return {"used": self.used, "limit": self.limit, "left": self.left}


def _bad_path(path: str, why: str) -> CommandError:
    return CommandError(
        "bad_path",
        f"`{path[:MAX_PATH]}` is not a usable file name: {why}. Use names like "
        f"notes/chemistry.md or skills/crossing.md.",
    )


def normalize(path: str, areas: tuple[str, ...] = AREAS) -> tuple[str, str]:
    """`(relative path, area)` for a path an agent wrote. Raises `CommandError(bad_path)`.
    `areas` are the folders it may name; any other first part is taken as a folder inside
    `notes/`."""
    if not isinstance(path, str) or not path.strip():
        raise _bad_path(str(path), "it is empty")
    if len(path) > MAX_PATH:
        raise _bad_path(path, f"it is longer than {MAX_PATH} characters")
    if "\\" in path or "\x00" in path or any(ord(c) < 32 for c in path):
        raise _bad_path(path, "it has a backslash or a control character")
    if path.startswith(("/", "~")):
        raise _bad_path(path, "it must be a plain relative name")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise _bad_path(path, "it has an empty part, `.` or `..`")
    if any(not _NAME.match(p) for p in parts):
        raise _bad_path(path, "names start with a letter or digit and hold no odd characters")
    if parts[0] not in areas:
        parts = [DEFAULT_AREA, *parts]
    if len(parts) > MAX_DEPTH + 1:
        raise _bad_path(path, f"folders go at most {MAX_DEPTH} deep")
    if len(parts) < 2:
        raise _bad_path(path, "name a file, not a folder")
    return "/".join(parts), parts[0]


class Workspace:
    """A workspace folder. Implements the agent layer's `MemoryBackend`."""

    def __init__(
        self,
        root: Path | str,
        *,
        notes_quota: int = NOTES_QUOTA,
        code_quota: int = CODE_QUOTA,
        max_files: int = MAX_FILES,
        code_area: bool = True,
    ) -> None:
        self.root = Path(root)
        self.notes_quota = notes_quota
        self.code_quota = code_quota
        self.max_files = max_files
        self.code_area = code_area
        self.root.mkdir(parents=True, exist_ok=True)
        for area in AREAS:
            (self.root / area).mkdir(exist_ok=True)

    @property
    def areas(self) -> tuple[str, ...]:
        """The folders an agent may use."""
        return AREAS if self.code_area else NOTES_AREAS

    # -- paths and quotas -------------------------------------------------------------------------

    def _resolve(self, rel: str) -> Path:
        """The file of a normalised path, after checking that nothing on the way is a symlink
        and that the result stays inside the folder."""
        base = self.root.resolve()
        current = self.root
        parts = rel.split("/")
        for n, part in enumerate(parts):
            current = current / part
            if current.is_symlink():
                raise _bad_path(rel, "it passes through a link")
            if n < len(parts) - 1 and current.exists() and not current.is_dir():
                raise _bad_path(rel, f"`{'/'.join(parts[: n + 1])}` is a file, not a folder")
        target = current.resolve()
        if not target.is_relative_to(base):
            raise _bad_path(rel, "it leaves the workspace")
        return current

    def _files(self) -> Iterator[tuple[str, Path]]:
        """Every regular file as `(relative path, path)`, sorted; links are ignored."""
        for area in self.areas:
            folder = self.root / area
            if not folder.is_dir() or folder.is_symlink():
                continue
            found = sorted(
                p
                for p in folder.rglob("*")
                if p.is_file() and not p.is_symlink() and not p.name.startswith(TEMP_PREFIX)
            )
            for path in found:
                yield path.relative_to(self.root).as_posix(), path

    @staticmethod
    def _read(path: Path) -> str:
        # newline="": the text is read as it was written, so that what the quota counts is what
        # the player wrote (a CR LF pair is two characters, not one)
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            return handle.read()

    def _used(self, areas: tuple[str, ...], without: str | None = None) -> int:
        return sum(
            len(self._read(p))
            for rel, p in self._files()
            if rel.split("/", 1)[0] in areas and rel != without
        )

    def quota(self, area: str) -> Quota:
        if area in NOTES_AREAS:
            return Quota(self._used(NOTES_AREAS), self.notes_quota)
        return Quota(self._used(CODE_AREAS), self.code_quota)

    def usage(self) -> dict[str, dict[str, int]]:
        out = {"notes": self.quota("notes").as_dict()}
        if self.code_area:
            out["code"] = self.quota("plugins").as_dict()
        return out

    def _check_room(self, rel: str, area: str, text: str) -> None:
        if "\x00" in text:
            raise CommandError("bad_text", "Text cannot hold a null character.")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise CommandError("bad_text", "Text must be valid Unicode.") from None
        if (self.root / rel).is_dir():
            raise _bad_path(rel, "it is the name of a folder")
        notes = area in NOTES_AREAS
        areas = NOTES_AREAS if notes else CODE_AREAS
        limit = self.notes_quota if notes else self.code_quota
        used_by_others = self._used(areas, without=rel)
        if used_by_others + len(text) > limit:
            left = max(limit - used_by_others, 0)
            what = "notes and skills" if notes else "plugins and scripts"
            raise CommandError(
                "notes_full" if notes else "code_full",
                f"No room: {what} may hold {limit} characters in all, and this file would "
                f"need {len(text)} of the {left} that are left. Shorten it, or delete or "
                "shorten another file first.",
            )
        exists = (self.root / rel).exists()
        if not exists and sum(1 for _ in self._files()) >= self.max_files:
            raise CommandError(
                "too_many_files",
                f"The workspace holds {self.max_files} files already; delete one first.",
            )

    def _store(self, rel: str, area: str, text: str) -> dict[str, Any]:
        path = self._resolve(rel)
        self._check_room(rel, area, text)
        self._replace(path, text)
        return {"path": rel, "chars": len(text), "chars_left": self.quota(area).left}

    @staticmethod
    def _replace(path: Path, text: str) -> None:
        """Put `text` in the file, all at once (a file is never seen half written)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=TEMP_PREFIX)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- MemoryBackend ----------------------------------------------------------------------------

    def write(self, path: str, text: str, append: bool) -> dict[str, Any]:
        rel, area = normalize(path, self.areas)
        if not isinstance(text, str):
            raise CommandError("bad_text", "The text must be a string.")
        current = self._resolve(rel)
        if append and current.is_file():
            text = self._read(current) + text
        return self._store(rel, area, text)

    def read(self, path: str, offset: int = 0) -> dict[str, Any]:
        rel, _ = normalize(path, self.areas)
        target = self._resolve(rel)
        if not target.is_file():
            raise CommandError("no_such_note", f"There is no file called `{rel}`.")
        text = self._read(target)
        start = max(int(offset), 0)
        shown = text[start : start + READ_LIMIT]
        out: dict[str, Any] = {"path": rel, "chars": len(text), "text": shown}
        if start + READ_LIMIT < len(text):
            out["more_from"] = start + READ_LIMIT
        return out

    def search(self, query: str) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise CommandError("bad_query", "Give a word or phrase to look for.")
        needle = query.lower()
        hits = [
            {"path": rel, "line": number + 1, "text": line[:HIT_WIDTH]}
            for rel, path in self._files()
            for number, line in enumerate(self._read(path).splitlines())
            if needle in line.lower()
        ]
        return {"query": query, "hits": hits[:SEARCH_HITS], "more": max(len(hits) - SEARCH_HITS, 0)}

    def edit(self, path: str, old: str, new: str) -> dict[str, Any]:
        rel, area = normalize(path, self.areas)
        target = self._resolve(rel)
        if not target.is_file():
            raise CommandError("no_such_note", f"There is no file called `{rel}`.")
        text = self._read(target)
        count = text.count(old) if old else 0
        if count != 1:
            raise CommandError(
                "edit_failed", f"`old` must occur exactly once in `{rel}` (found {count})."
            )
        return self._store(rel, area, text.replace(old, new))

    def list(self) -> dict[str, Any]:
        files = [{"path": rel, "chars": len(self._read(p))} for rel, p in self._files()]
        return {"files": files, "chars_left": self.quota("notes").left, "quota": self.usage()}

    # -- beyond MemoryBackend ---------------------------------------------------------------------

    def delete(self, path: str) -> dict[str, Any]:
        rel, area = normalize(path, self.areas)
        target = self._resolve(rel)
        if not target.is_file():
            raise CommandError("no_such_note", f"There is no file called `{rel}`.")
        target.unlink()
        return {"path": rel, "deleted": True, "chars_left": self.quota(area).left}

    def clear(self) -> None:
        """Remove every file and every installed library (the control setting starts each game
        with an empty workspace)."""
        self._clear_files()
        libs = self.root / LIBS_FOLDER
        if libs.is_symlink():
            libs.unlink()
        elif libs.exists():
            shutil.rmtree(libs)

    def _clear_files(self) -> None:
        for area in AREAS:
            folder = self.root / area
            if folder.is_symlink():
                folder.unlink()
            elif folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(exist_ok=True)

    @property
    def libs_dir(self) -> Path:
        """Where installed libraries live (may not exist)."""
        return self.root / LIBS_FOLDER

    def read_text(self, path: str) -> str:
        """The whole of a file, for the harness itself (scripts and plugins that are run).
        Same names and refusals as `read`."""
        rel, _ = normalize(path, self.areas)
        target = self._resolve(rel)
        if not target.is_file():
            raise CommandError("no_such_note", f"There is no file called `{rel}`.")
        return self._read(target)

    def plugin_sources(self) -> dict[str, str]:
        """The plugins: every `plugins/<name>.py` directly in the folder, by name."""
        out: dict[str, str] = {}
        if not self.code_area:
            return out
        for rel, path in self._files():
            parts = rel.split("/")
            if len(parts) == 2 and parts[0] == "plugins" and parts[1].endswith(".py"):
                out[parts[1][: -len(".py")]] = self._read(path)
        return out

    def file_names(self) -> list[str]:
        return [rel for rel, _ in self._files()]

    def scrub(self, clean: Callable[[str], str]) -> list[str]:
        """Rewrite every file whose text `clean` changes (the redactor, once it knows a secret
        that was not known when the file was written); a file whose name it changes is removed.
        Returns the names of the files that were touched. The quotas are not checked."""
        touched: list[str] = []
        for rel, path in list(self._files()):
            if clean(rel) != rel:
                path.unlink()
                touched.append(rel)
                continue
            text = self._read(path)
            cleaned = clean(text)
            if cleaned != text:
                self._replace(path, cleaned)
                touched.append(rel)
        return touched

    def copy_to(self, destination: Path | str, clean: Callable[[str], str] | None = None) -> None:
        """A copy of the files in `destination` (for the run folder). `clean`, when given, is
        applied to the text of every file and every file name on the way (the redactor)."""
        dest = Path(destination)
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for rel, path in self._files():
            if clean is None:
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                continue
            target = dest / clean(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(clean(self._read(path)), encoding="utf-8", newline="")

    # -- snapshots (a session snapshot carries the notes) -----------------------------------------

    def snapshot(self) -> dict[str, str]:
        return {rel: self._read(p) for rel, p in self._files()}

    def restore(self, files: dict[str, str]) -> None:
        """Put the files back as a snapshot had them. The installed libraries are not files of
        the notebook (a snapshot does not hold them) and stay."""
        self._clear_files()
        for rel, text in files.items():
            norm, area = normalize(rel, self.areas)
            self._store(norm, area, text)
