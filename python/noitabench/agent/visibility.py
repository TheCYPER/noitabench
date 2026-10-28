"""What an agent may never see (contracts section 11), and a check for it.

The layer builds every observation from the player, the entity list and filtered events - never
from `Game.markers()` or the rules. These names are the fields that would give the solution
away; `leaks` finds them in any nested structure, and a session raises if one of its answers
contains one (a bug in this layer, not an agent's mistake).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# Marker fields of the world file that name the solution, the rules and the seeds.
FORBIDDEN_KEYS = frozenset(
    {
        "role",
        "params",
        "regions",
        "encounter_id",
        "placeholder",
        "must_pass",
        "footprint",
        "trigger",
        "strength",
        "rule_seed",
        "recipe",
        "recipes",
        "reaction",
        "reactions",
        "row",
        "ingredients",
        "markers",
        "perturbation",
        "content_hash",
        "seed",
    }
)


def leaks(obj: Any, path: str = "$") -> list[str]:
    """Paths in `obj` whose key is a forbidden name (only keys: text the agent itself wrote,
    such as notes, is not scanned)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                found.append(f"{path}.{k}")
            found.extend(leaks(v, f"{path}.{k}"))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            found.extend(leaks(v, f"{path}[{i}]"))
    return found


def check_clean(obj: Any) -> None:
    bad = leaks(obj)
    if bad:
        raise AssertionError(f"hidden fields in an agent-facing answer: {', '.join(bad)}")


def strings(obj: Any) -> Iterable[str]:
    """Every string in a nested structure, keys and values (for tests that scan the text)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from strings(v)
