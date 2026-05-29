"""XPS creation and editing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from .package import XpsPackage


@dataclass
class XpsFixedPage:
    """Editable XPS fixed page.

    Example:
        >>> XpsFixedPage(100, 200).width
        100
    """

    width: float
    height: float
    elements: list[object] = field(default_factory=list)


@dataclass
class XpsCanvas:
    """XPS canvas element for grouping content."""

    elements: list[object] = field(default_factory=list)
    transform: str | None = None
    clip: str | None = None


@dataclass
class XpsPath:
    """XPS path element."""

    data: str
    fill: str | None = None
    stroke: str | None = None
    stroke_thickness: float | None = None


@dataclass
class XpsGlyphs:
    """XPS glyphs element."""

    font_uri: str
    font_size: float
    origin_x: float
    origin_y: float
    unicode_string: str
    fill: str | None = None


@dataclass
class XpsImage:
    """XPS image element."""

    source: str
    width: float
    height: float
    transform: str | None = None


class XpsDocumentBuilder:
    """Builder for XPS document creation/editing.

    Example:
        >>> builder = XpsDocumentBuilder()
        >>> page = builder.add_page(100, 200)
        >>> page.width
        100
    """

    def __init__(self, title: str | None = None) -> None:
        self.title = title
        self.pages: list[XpsFixedPage] = []

    def add_page(self, width: float, height: float) -> XpsFixedPage:
        """Append a new fixed page and return it."""
        page = XpsFixedPage(width=width, height=height)
        self.pages.append(page)
        return page

    def insert_page(self, index: int, page: XpsFixedPage) -> None:
        """Insert a fixed page at the given index."""
        if index < 0 or index > len(self.pages):
            raise IndexError("page index out of range")
        self.pages.insert(index, page)

    def remove_page(self, index: int) -> None:
        """Remove a fixed page at the given index."""
        if index < 0 or index >= len(self.pages):
            raise IndexError("page index out of range")
        self.pages.pop(index)

    def to_package(self) -> XpsPackage:
        """Serialize the current pages into a new XPS package."""
        from .serializer import serialize_document_sequence, serialize_fixed_page

        parts: dict[str, bytes] = {}
        page_parts: list[str] = []
        for idx, page in enumerate(self.pages, start=1):
            part_name = f"/Documents/1/Pages/{idx}.fpage"
            parts[part_name] = serialize_fixed_page(page)
            page_parts.append(part_name)
        parts.update(serialize_document_sequence(page_parts))
        return XpsPackage(parts=parts)
