"""Fixtures for the bot tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from mini_world import write_world
from noitabench.bots.descend import WorldFiles
from noitabench.bots.terrain import Materials


@pytest.fixture(scope="session")
def mats() -> Materials:
    return Materials.load()


@pytest.fixture
def mini(tmp_path: Path, mats: Materials) -> WorldFiles:
    return write_world(tmp_path / "mini", mats)
