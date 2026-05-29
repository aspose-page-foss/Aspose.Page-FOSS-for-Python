"""XPS print ticket helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from xml.etree import ElementTree as ET

from .package import XpsPackage
from .parser import XpsParser
from .relationships import Relationship, read_rels, write_rels


_PRINT_TICKET_TYPE = "http://schemas.microsoft.com/xps/2005/06/printticket"


class PrintTicketScope(str, Enum):
    """Print ticket scopes supported by XPS."""

    JOB = "job"
    DOCUMENT = "document"
    PAGE = "page"


@dataclass
class PrintTicket:
    """Print ticket payload descriptor."""

    scope: PrintTicketScope
    part_name: str
    xml: str


def read_print_tickets(package: XpsPackage) -> list[PrintTicket]:
    """Read print tickets from the XPS package."""
    tickets: list[PrintTicket] = []
    fdseq = _find_fdseq(package)
    if fdseq:
        tickets.extend(_read_scope_tickets(package, PrintTicketScope.JOB, fdseq))
        for document in _document_parts(package, fdseq):
            tickets.extend(_read_scope_tickets(package, PrintTicketScope.DOCUMENT, document))
    for page_part in XpsParser(package).fixed_page_parts():
        tickets.extend(_read_scope_tickets(package, PrintTicketScope.PAGE, page_part))
    return tickets


def write_print_ticket(
    package: XpsPackage,
    scope: PrintTicketScope,
    xml: str,
    page_index: int | None = None,
) -> None:
    """Add or replace a print ticket in the XPS package."""
    _validate_xml(xml)
    base_part = _scope_part(package, scope, page_index)
    rels = read_rels(package, base_part)
    existing = [rel for rel in rels if rel.type == _PRINT_TICKET_TYPE]
    if existing:
        target = existing[0].target
        part_name = _resolve_part(base_part, target)
    else:
        part_name = _print_ticket_part_name(base_part, package)
    package.parts[part_name] = xml.encode("utf-8")
    rels = [rel for rel in rels if rel.type != _PRINT_TICKET_TYPE]
    rels.append(Relationship(id=_next_rel_id(rels), type=_PRINT_TICKET_TYPE, target=_relative_target(base_part, part_name)))
    write_rels(package, base_part, rels)


def remove_print_ticket(
    package: XpsPackage,
    scope: PrintTicketScope,
    page_index: int | None = None,
) -> None:
    """Remove print tickets for the given scope."""
    base_part = _scope_part(package, scope, page_index)
    rels = read_rels(package, base_part)
    remaining: list[Relationship] = []
    for rel in rels:
        if rel.type == _PRINT_TICKET_TYPE:
            part_name = _resolve_part(base_part, rel.target)
            package.parts.pop(part_name, None)
        else:
            remaining.append(rel)
    write_rels(package, base_part, remaining)


def _read_scope_tickets(
    package: XpsPackage, scope: PrintTicketScope, base_part: str
) -> list[PrintTicket]:
    rels = read_rels(package, base_part)
    tickets: list[PrintTicket] = []
    for rel in rels:
        if rel.type != _PRINT_TICKET_TYPE:
            continue
        part_name = _resolve_part(base_part, rel.target)
        if not package.has_part(part_name):
            continue
        xml = _decode_xml(package.read(part_name))
        tickets.append(PrintTicket(scope=scope, part_name=part_name, xml=xml))
    return tickets


def _scope_part(package: XpsPackage, scope: PrintTicketScope, page_index: int | None) -> str:
    fdseq = _find_fdseq(package)
    if scope == PrintTicketScope.JOB:
        if not fdseq:
            raise ValueError("missing FixedDocumentSequence")
        return fdseq
    if scope == PrintTicketScope.DOCUMENT:
        if not fdseq:
            raise ValueError("missing FixedDocumentSequence")
        documents = _document_parts(package, fdseq)
        if not documents:
            raise ValueError("missing FixedDocument")
        return documents[0]
    if scope == PrintTicketScope.PAGE:
        if page_index is None:
            raise ValueError("page_index required for page scope")
        pages = XpsParser(package).fixed_page_parts()
        if page_index < 0 or page_index >= len(pages):
            raise IndexError("page_index out of range")
        return pages[page_index]
    raise ValueError("unsupported scope")


def _find_fdseq(package: XpsPackage) -> str | None:
    for part in package.parts:
        if part.lower().endswith(".fdseq"):
            return part
    for rel in read_rels(package, "/"):
        if rel.target.lower().endswith(".fdseq"):
            return _resolve_part("/", rel.target)
    return None


def _document_parts(package: XpsPackage, fdseq_part: str) -> list[str]:
    try:
        root = ET.fromstring(package.read(fdseq_part))
    except Exception:
        return []
    documents: list[str] = []
    for doc_ref in root.findall(".//{*}DocumentReference"):
        source = doc_ref.get("Source")
        if source:
            documents.append(_resolve_part(fdseq_part, source))
    return documents


def _resolve_part(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target
    base = base_part.rsplit("/", 1)[0]
    if base == "":
        return "/" + target
    return f"{base}/{target}"


def _relative_target(base_part: str, part_name: str) -> str:
    base_dir = base_part.rsplit("/", 1)[0]
    if base_dir == "":
        return part_name.lstrip("/")
    prefix = base_dir + "/"
    if part_name.startswith(prefix):
        return part_name[len(prefix) :]
    return part_name.lstrip("/")


def _print_ticket_part_name(base_part: str, package: XpsPackage) -> str:
    base_dir = base_part.rsplit("/", 1)[0]
    if base_dir == "":
        base_dir = ""
    candidate = f"{base_dir}/PrintTicket.xml" if base_dir else "/PrintTicket.xml"
    if candidate not in package.parts:
        return candidate
    index = 1
    while True:
        candidate = f"{base_dir}/PrintTicket{index}.xml" if base_dir else f"/PrintTicket{index}.xml"
        if candidate not in package.parts:
            return candidate
        index += 1


def _next_rel_id(rels: list[Relationship]) -> str:
    used = {rel.id for rel in rels}
    index = 1
    while True:
        candidate = f"rIdPT{index}"
        if candidate not in used:
            return candidate
        index += 1


def _validate_xml(xml: str) -> None:
    try:
        ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("invalid print ticket XML") from exc


def _decode_xml(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="ignore")
