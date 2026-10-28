"""Encounter ids and the capability node each one mainly measures (capability-graph.md 3.2)."""

from __future__ import annotations

# Primary node of each encounter template E01..E24 (N2a is reported as N2).
ENCOUNTER_NODE: dict[str, str] = {
    "E01": "N1", "E02": "N1", "E03": "N1", "E04": "N2", "E05": "N2", "E06": "N3",
    "E07": "N3", "E08": "N4", "E09": "N4", "E10": "N4", "E11": "N5", "E12": "N5",
    "E13": "N5", "E14": "N6", "E15": "N6", "E16": "N7", "E17": "N7", "E18": "N8",
    "E19": "N8", "E20": "N8", "E21": "N9", "E22": "N9", "E23": "N10", "E24": "N10",
}  # fmt: skip

BASE_NODES = tuple(f"N{i}" for i in range(1, 11))


def node_of(encounter_id: str) -> str:
    return ENCOUNTER_NODE.get(encounter_id, "?")
