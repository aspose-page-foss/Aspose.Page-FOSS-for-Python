"""XPS package structure parser."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from .package import XpsPackage


class XpsParser:
    """Parse XPS package relationships to locate pages.

    Example:
        >>> from io import BytesIO
        >>> from zipfile import ZipFile
        >>> buffer = BytesIO()
        >>> with ZipFile(buffer, "w") as zf:
        ...     _ = zf.writestr("FixedDocSeq.fdseq", "<FixedDocumentSequence/>")
        >>> package = XpsPackage.from_bytes(buffer.getvalue())
        >>> XpsParser(package).fixed_page_parts()
        []
    """
    def __init__(self, package: XpsPackage) -> None:
        self._package = package

    def fixed_page_parts(self) -> list[str]:
        """Return fixed page part names in document order."""
        fdseq = self._find_fdseq()
        if fdseq is None:
            return []
        fdseq_xml = ET.fromstring(self._package.read(fdseq))
        document_parts = []
        for doc_ref in fdseq_xml.findall(".//{*}DocumentReference"):
            source = doc_ref.get("Source")
            if source:
                document_parts.append(_resolve_part(fdseq, source))
        page_parts: list[str] = []
        for document in document_parts:
            doc_xml = ET.fromstring(self._package.read(document))
            for page_content in doc_xml.findall(".//{*}PageContent"):
                source = page_content.get("Source")
                if source:
                    page_parts.append(_resolve_part(document, source))
        return page_parts

    def _find_fdseq(self) -> str | None:
        for part in self._package.parts:
            if part.lower().endswith(".fdseq"):
                return part
        rels_part = "/_rels/.rels"
        if self._package.has_part(rels_part):
            root = ET.fromstring(self._package.read(rels_part))
            for rel in root.findall(".//{*}Relationship"):
                target = rel.get("Target")
                if target and target.lower().endswith(".fdseq"):
                    return _resolve_part(rels_part, target)
        return None


def _resolve_part(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target
    base = base_part.rsplit("/", 1)[0]
    if base == "":
        return "/" + target
    return f"{base}/{target}"
