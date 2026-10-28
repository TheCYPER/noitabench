"""Minimal reader for Noita entity XML files (numbers only, as the KB licensing note allows).

Only what the spell generator needs: components and their attributes, one level of child elements
(`config_explosion`, `damage_by_type`), and `<Base file=...>` inheritance with attribute-wise
override (SPELL-R05: an absent attribute is the engine default; overrides inside `<Base>` merge over
the base file).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

# component name -> {"@": attributes, child tag: attributes}
Entity = dict[str, dict[str, dict[str, str]]]


_START_TAG = re.compile(
    r"<([A-Za-z_][\w.:-]*)((?:\s+[\w.:-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>"
)
_ATTRIBUTE = re.compile(r"([\w.:-]+)\s*=\s*(\"[^\"]*\"|'[^']*')")


def _dedupe_attributes(text: str) -> str:
    """Noita files may repeat an attribute on one tag (`bullet_slow.xml`); the last value wins,
    as in the research extractor and the KB numbers. Strict XML parsers reject such files."""

    def fix(match: re.Match[str]) -> str:
        latest = dict(_ATTRIBUTE.findall(match.group(2)))
        attrs = "".join(f" {name}={value}" for name, value in latest.items())
        return f"<{match.group(1)}{attrs}{match.group(3)}>"

    return _START_TAG.sub(fix, text)


def _component(element: ET.Element) -> dict[str, dict[str, str]]:
    """Attributes of a component and of its child elements. A child element that appears twice
    (`digger.xml` has two `damage_by_type`) counts once, with its *first* occurrence: that gives the
    wiki's Digging Bolt damage (drill 0.3 = 7.5 shown), the later one (0.01) is a leftover."""
    parts = {"@": dict(element.attrib)}
    for child in element:
        parts.setdefault(child.tag, dict(child.attrib))
    return parts


def _merge(base: dict[str, dict[str, str]], over: dict[str, dict[str, str]]):
    merged = {key: dict(value) for key, value in base.items()}
    for key, value in over.items():
        merged.setdefault(key, {}).update(value)
    return merged


def load_entity(game_root: Path, data_path: str) -> Entity:
    """Load `data/entities/....xml` from the extracted game files below `game_root`."""
    relative = data_path.removeprefix("data/")
    text = (game_root / relative).read_text(encoding="utf-8")
    root = ET.fromstring(_dedupe_attributes(text))
    entity: Entity = {}

    def add(tag: str, parts: dict[str, dict[str, str]]) -> None:
        entity[tag] = _merge(entity.get(tag, {}), parts)

    for child in root:
        if child.tag == "Base":
            for tag, parts in load_entity(game_root, child.attrib["file"]).items():
                add(tag, parts)
            for override in child:
                add(override.tag, _component(override))
        else:
            add(child.tag, _component(child))
    return entity


def number(attrs: dict[str, str], name: str, default: float) -> float:
    """Numeric attribute (XML values sometimes carry stray spaces) or the engine default."""
    raw = attrs.get(name)
    return default if raw is None else float(raw.strip())


def flag(attrs: dict[str, str], name: str, default: bool) -> bool:
    raw = attrs.get(name)
    return default if raw is None else raw.strip() not in ("0", "false", "")
