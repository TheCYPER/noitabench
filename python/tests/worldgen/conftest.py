"""Shared fixtures for the world generator tests (generating a world takes ~1.5 s)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parents[2]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from noitabench.worldgen import generate_world
from noitabench.worldgen.config import load_biome_map, load_materials


@pytest.fixture(scope="session")
def mats():
    return load_materials()


@pytest.fixture(scope="session")
def bm():
    return load_biome_map()


@pytest.fixture(scope="session")
def world_a():
    return generate_world(3)


@pytest.fixture(scope="session")
def world_b():
    return generate_world(4)
