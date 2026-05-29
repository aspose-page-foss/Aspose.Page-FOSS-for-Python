"""XPS relationships helpers."""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .package import XpsPackage


_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", _RELS_NS)


@dataclass
class Relationship:
    """Represents a package relationship."""

    id: str
    type: str
    target: str


def read_rels(package: XpsPackage, part_name: str) -> list[Relationship]:
    """Read relationships for the given part name."""
    rels_part = _rels_part_name(part_name)
    if not package.has_part(rels_part):
        return []
    root = ET.fromstring(package.read(rels_part))
    rels: list[Relationship] = []
    for rel in root.findall(".//{*}Relationship"):
        rel_id = rel.get("Id") or ""
        rel_type = rel.get("Type") or ""
        target = rel.get("Target") or ""
        rels.append(Relationship(id=rel_id, type=rel_type, target=target))
    return rels


def write_rels(package: XpsPackage, part_name: str, rels: list[Relationship]) -> None:
    """Write relationships for the given part name."""
    rels_part = _rels_part_name(part_name)
    if not rels:
        package.parts.pop(rels_part, None)
        return
    root = ET.Element(_rels_qn("Relationships"))
    for rel in rels:
        ET.SubElement(
            root,
            _rels_qn("Relationship"),
            {"Id": rel.id, "Type": rel.type, "Target": rel.target},
        )
    package.parts[rels_part] = ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rels_part_name(part_name: str) -> str:
    if part_name in ("", "/"):
        return "/_rels/.rels"
    normalized = part_name.lstrip("/")
    if "/" in normalized:
        base_dir, filename = normalized.rsplit("/", 1)
        return f"/{base_dir}/_rels/{filename}.rels"
    return f"/_rels/{normalized}.rels"


def _rels_qn(tag: str) -> str:
    return f"{{{_RELS_NS}}}{tag}"
