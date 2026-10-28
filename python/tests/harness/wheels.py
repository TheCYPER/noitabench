"""Tiny wheel files and a lock file for the tests of the offline library list."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path


def make_wheel(
    folder: Path,
    name: str,
    version: str,
    files: dict[str, str],
    requires: tuple[str, ...] = (),
) -> Path:
    """`<folder>/<name>-<version>-py3-none-any.whl` holding `files` and its metadata."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}-{version}-py3-none-any.whl"
    info = f"{name}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    metadata += "".join(f"Requires-Dist: {r}\n" for r in requires)
    metadata += "Requires-Dist: pytest; extra == 'tests'\n"
    with zipfile.ZipFile(path, "w") as archive:
        for member, text in files.items():
            archive.writestr(member, text)
        archive.writestr(f"{info}/METADATA", metadata)
        archive.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\n")
        archive.writestr(f"{info}/RECORD", "")
    return path


def write_lock(lock: Path, wheels: list[Path]) -> None:
    lines = ["# test lock"]
    for wheel in wheels:
        name, version = wheel.name.split("-")[:2]
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        lines.append(f"{name}=={version} --hash=sha256:{digest}")
    lock.write_text("\n".join(lines) + "\n", encoding="utf-8")


def toy_wheelhouse(root: Path) -> Path:
    """`<root>/wheelhouse` with toylib (which needs toydep) and tinylib, and its lock."""
    house = root / "wheelhouse"
    wheels = [
        make_wheel(house, "toydep", "1.0", {"toydep.py": "VALUE = 40\n"}),
        make_wheel(
            house,
            "toylib",
            "2.0",
            {"toylib/__init__.py": "import toydep\nANSWER = toydep.VALUE + 2\n"},
            requires=("toydep>=1.0", "numpy>=1; python_version < '3.8'"),
        ),
        make_wheel(house, "tinylib", "0.1", {"tinylib.py": "NAME = 'tiny'\n"}),
    ]
    write_lock(house.with_name("wheelhouse.lock"), wheels)
    return house
