"""Shared setup for the encounter tests: make the package importable."""

from __future__ import annotations

import sys
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parents[2]
for p in (PYTHON_DIR, PYTHON_DIR / "tests" / "encounters"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
