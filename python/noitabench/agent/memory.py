"""The notes commands (`memory_*`): the interface the harness workspace plugs into.

The session does not store notes itself. It forwards the five commands to a `MemoryBackend`.
The harness (layer L1) supplies the real one, with its quota of characters and its folder that
survives between episodes. `NoMemory` is the default: it answers that there is no notebook.
`InMemoryNotes` is a small working backend for tests and for scripts that want notes without a
harness.
"""

from __future__ import annotations

from typing import Any, Protocol

from .errors import CommandError


class MemoryBackend(Protocol):
    """Five operations on named text files. Each raises `CommandError` to refuse."""

    def write(self, path: str, text: str, append: bool) -> dict[str, Any]: ...

    def read(self, path: str) -> dict[str, Any]: ...

    def search(self, query: str) -> dict[str, Any]: ...

    def edit(self, path: str, old: str, new: str) -> dict[str, Any]: ...

    def list(self) -> dict[str, Any]: ...


class NoMemory:
    """No notebook in this setting."""

    def _refuse(self) -> CommandError:
        return CommandError("no_notebook", "You have no notebook here.")

    def write(self, path: str, text: str, append: bool) -> dict[str, Any]:
        raise self._refuse()

    def read(self, path: str) -> dict[str, Any]:
        raise self._refuse()

    def search(self, query: str) -> dict[str, Any]:
        raise self._refuse()

    def edit(self, path: str, old: str, new: str) -> dict[str, Any]:
        raise self._refuse()

    def list(self) -> dict[str, Any]:
        raise self._refuse()


class InMemoryNotes:
    """Notes in a dict, with a limit on the total number of characters."""

    def __init__(self, max_chars: int = 8000) -> None:
        self.max_chars = max_chars
        self.files: dict[str, str] = {}

    def _used(self, without: str | None = None) -> int:
        return sum(len(t) for p, t in self.files.items() if p != without)

    def _check(self, path: str, text: str) -> None:
        if not path or len(path) > 80 or path.startswith("/") or ".." in path:
            raise CommandError("bad_path", f"`{path}` is not a usable note name.")
        if self._used(without=path) + len(text) > self.max_chars:
            raise CommandError(
                "notes_full", f"Your notes are limited to {self.max_chars} characters in total."
            )

    def write(self, path: str, text: str, append: bool) -> dict[str, Any]:
        new = self.files.get(path, "") + text if append else text
        self._check(path, new)
        self.files[path] = new
        return {"path": path, "chars": len(new), "chars_left": self.max_chars - self._used()}

    def read(self, path: str) -> dict[str, Any]:
        if path not in self.files:
            raise CommandError("no_such_note", f"There is no note called `{path}`.")
        return {"path": path, "text": self.files[path]}

    def search(self, query: str) -> dict[str, Any]:
        needle = query.lower()
        hits = [
            {"path": p, "line": i + 1, "text": line}
            for p, text in sorted(self.files.items())
            for i, line in enumerate(text.splitlines())
            if needle in line.lower()
        ]
        return {"query": query, "hits": hits[:20], "more": max(len(hits) - 20, 0)}

    def edit(self, path: str, old: str, new: str) -> dict[str, Any]:
        text = self.read(path)["text"]
        if text.count(old) != 1:
            raise CommandError(
                "edit_failed",
                f"`old` must occur exactly once in `{path}` (found {text.count(old)}).",
            )
        updated = text.replace(old, new)
        self._check(path, updated)
        self.files[path] = updated
        return {"path": path, "chars": len(updated), "chars_left": self.max_chars - self._used()}

    def list(self) -> dict[str, Any]:
        return {
            "files": [{"path": p, "chars": len(t)} for p, t in sorted(self.files.items())],
            "chars_left": self.max_chars - self._used(),
        }

    # -- snapshots (a session snapshot carries the notes) -----------------------------------------

    def snapshot(self) -> dict[str, str]:
        return dict(self.files)

    def restore(self, files: dict[str, str]) -> None:
        self.files = dict(files)
