"""Reading content files: JSON with errors that name the file and the field."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTENT_DIR = REPO_ROOT / "content"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise ValueError(f"{path}: file not found") from err
    except json.JSONDecodeError as err:
        raise ValueError(f"{path}: invalid JSON ({err})") from err


def need(cond: bool, path: Path, field_name: str, message: str) -> None:
    """Raise ``ValueError`` naming the file and the field unless ``cond`` holds."""
    if not cond:
        raise ValueError(f"{path.name}: field '{field_name}' {message}")


def parse_section(parse, data: dict, path: Path, *args):
    """Run ``parse(data, path, *args)``; a missing or ill-typed field becomes a ``ValueError``."""
    try:
        return parse(data, path, *args)
    except KeyError as err:
        raise ValueError(f"{path.name}: missing field {err}") from err
    except (TypeError, IndexError, AttributeError) as err:
        raise ValueError(f"{path.name}: malformed content ({type(err).__name__}: {err})") from err
