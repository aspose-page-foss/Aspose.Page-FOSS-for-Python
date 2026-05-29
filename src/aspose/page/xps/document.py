"""XPS document entry point."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .editing import XpsDocumentBuilder, XpsFixedPage, XpsImage
from .package import XpsPackage
from .parser import XpsParser
from .serializer import serialize_document_sequence, serialize_fixed_page

if TYPE_CHECKING:
    from ..ps.output import ImageSaveOptions, PdfSaveOptions
    from .print_tickets import PrintTicket


@dataclass
class XpsDocument:
    """Represents a loaded or editable XPS document.

    Example:
        >>> isinstance(XpsDocument.from_bytes(b"PK\x03\x04"), XpsDocument)
        True
    """

    package: XpsPackage
    builder: XpsDocumentBuilder = field(default_factory=XpsDocumentBuilder)
    _page_parts: list[str | None] = field(default_factory=list)

    @classmethod
    def create(cls, title: str | None = None) -> "XpsDocument":
        """Create a new empty XPS document."""
        return cls(package=XpsPackage(parts={}), builder=XpsDocumentBuilder(title=title))

    @classmethod
    def from_bytes(cls, data: bytes) -> "XpsDocument":
        """Create an XPS document from bytes."""
        package = XpsPackage.from_bytes(data)
        builder = XpsDocumentBuilder()
        page_parts = XpsParser(package).fixed_page_parts()
        for part in page_parts:
            xml = package.read(part)
            builder.pages.append(_parse_fixed_page(xml))
        return cls(package=package, builder=builder, _page_parts=list(page_parts))

    @classmethod
    def from_file(cls, path: str) -> "XpsDocument":
        """Create an XPS document from a file path."""
        return cls.from_bytes(_read_file(path))

    def add_page(self, width: float, height: float) -> XpsFixedPage:
        """Append a new fixed page and return it."""
        page = self.builder.add_page(width, height)
        self._page_parts.append(None)
        return page

    def insert_page(self, index: int, page: XpsFixedPage) -> None:
        """Insert a fixed page at the given index."""
        self.builder.insert_page(index, page)
        self._page_parts.insert(index, None)

    def remove_page(self, index: int) -> None:
        """Remove a fixed page at the given index."""
        self.builder.remove_page(index)
        self._page_parts.pop(index)

    def save(self, path: str | None = None) -> bytes:
        """Serialize the document to bytes and optionally write to a file."""
        if len(self._page_parts) != len(self.builder.pages):
            missing = len(self.builder.pages) - len(self._page_parts)
            if missing > 0:
                self._page_parts.extend([None] * missing)
            else:
                self._page_parts = self._page_parts[: len(self.builder.pages)]
        parts = dict(self.package.parts)
        page_parts = _assign_page_parts(self._page_parts, parts)

        for part_name in list(parts.keys()):
            if _is_page_part(part_name) and part_name not in page_parts:
                parts.pop(part_name, None)

        for page, part_name in zip(self.builder.pages, page_parts):
            _validate_page_images(page, parts, part_name)
            parts[part_name] = serialize_fixed_page(page)

        parts.update(serialize_document_sequence(page_parts))

        data = _write_package(parts)
        self.package = XpsPackage(parts=parts)
        self._page_parts = list(page_parts)
        if path:
            with open(path, "wb") as handle:
                handle.write(data)
        return data

    def get_print_tickets(self) -> list["PrintTicket"]:
        """Return all print tickets in the document.

        Example:
            >>> isinstance(XpsDocument.create().get_print_tickets(), list)
            True
        """
        from .print_tickets import read_print_tickets

        return read_print_tickets(self.package)

    def set_print_ticket(self, scope: str, xml: str, page_index: int | None = None) -> None:
        """Add or replace a print ticket at the requested scope."""
        from .print_tickets import PrintTicketScope, write_print_ticket

        scope_enum = PrintTicketScope(scope)
        write_print_ticket(self.package, scope_enum, xml, page_index)

    def remove_print_ticket(self, scope: str, page_index: int | None = None) -> None:
        """Remove a print ticket at the requested scope."""
        from .print_tickets import PrintTicketScope, remove_print_ticket

        scope_enum = PrintTicketScope(scope)
        remove_print_ticket(self.package, scope_enum, page_index)

    def to_pdf(self, options: "PdfSaveOptions | None" = None) -> bytes:
        """Convert the document to PDF bytes."""
        from .output import to_pdf

        return to_pdf(self, options)

    def to_image(self, options: "ImageSaveOptions") -> bytes:
        """Convert the document to raster image bytes."""
        from .output import to_image

        return to_image(self, options)


def _parse_fixed_page(xml: bytes) -> XpsFixedPage:
    root = ET.fromstring(xml)
    width = _parse_float(root.get("Width")) or 0.0
    height = _parse_float(root.get("Height")) or 0.0
    elements = [_clone_element(child) for child in list(root)]
    return XpsFixedPage(width=width, height=height, elements=elements)


def _clone_element(element: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(element, encoding="utf-8"))


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _assign_page_parts(existing: list[str | None], parts: dict[str, bytes]) -> list[str]:
    used = {name for name in existing if name}
    result: list[str] = []
    for name in existing:
        if name:
            result.append(name)
        else:
            new_name = _next_page_part(used, parts)
            used.add(new_name)
            result.append(new_name)
    return result


def _next_page_part(used: set[str], parts: dict[str, bytes]) -> str:
    index = 1
    while True:
        candidate = f"/Documents/1/Pages/{index}.fpage"
        if candidate not in used and candidate not in parts:
            return candidate
        index += 1


def _is_page_part(part_name: str) -> bool:
    return part_name.startswith("/Documents/1/Pages/") and part_name.endswith(".fpage")


def _validate_page_images(page: XpsFixedPage, parts: dict[str, bytes], page_part: str) -> None:
    for element in _walk_elements(page.elements):
        if isinstance(element, XpsImage):
            part_name = _resolve_part(page_part, element.source)
            if part_name not in parts:
                raise ValueError(f"missing image part {part_name}")


def _walk_elements(elements: list[object]) -> list[object]:
    collected: list[object] = []
    for element in elements:
        collected.append(element)
        if hasattr(element, "elements"):
            try:
                children = element.elements  # type: ignore[attr-defined]
            except AttributeError:
                children = None
            if isinstance(children, list):
                collected.extend(_walk_elements(children))
    return collected


def _resolve_part(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target
    base = base_part.rsplit("/", 1)[0]
    if base == "":
        return "/" + target
    return f"{base}/{target}"


def _write_package(parts: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name.lstrip("/"), data)
    return buffer.getvalue()


def _read_file(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()
