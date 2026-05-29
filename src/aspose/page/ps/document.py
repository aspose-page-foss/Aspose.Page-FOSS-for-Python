"""PostScript/EPS document loading utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .dsc import DscMetadata, parse_dsc_comments
from .editing import PsPage
from .page_geometry import page_size_from_dsc

if TYPE_CHECKING:
    from .output import ImageSaveOptions, PdfSaveOptions


@dataclass
class PsDocument:
    """Represents a loaded or editable PS/EPS document.

    Example:
        >>> doc = PsDocument.from_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n")
        >>> doc.is_eps
        True
    """

    data: bytes
    is_eps: bool
    dsc: DscMetadata | None = None
    source_path: str | None = None
    pages: list[PsPage] = field(default_factory=list)
    prolog: list[str] = field(default_factory=list)
    trailer: list[str] = field(default_factory=list)
    header: str | None = None
    dirty: bool = False

    @classmethod
    def create(
        cls, is_eps: bool = False, page_size: tuple[float, float] = (612.0, 792.0)
    ) -> "PsDocument":
        """Create a new PS/EPS document with a single empty page."""
        header = "%!PS-Adobe-3.0 EPSF-3.0" if is_eps else "%!PS-Adobe-3.0"
        page = PsPage(page_size[0], page_size[1])
        return cls(
            data=b"",
            is_eps=is_eps,
            dsc=None,
            source_path=None,
            pages=[page],
            prolog=[],
            trailer=[],
            header=header,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "PsDocument":
        """Create a document from bytes and detect EPS metadata.

        Example:
            >>> PsDocument.from_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\n").is_eps
            True
        """
        is_eps = _detect_eps(data)
        dsc = parse_dsc_comments(data)
        header, lines = _extract_header(data)
        pages, prolog, trailer = _parse_pages(lines, dsc, is_eps)
        return cls(
            data=data,
            is_eps=is_eps,
            dsc=dsc,
            pages=pages,
            prolog=prolog,
            trailer=trailer,
            header=header,
        )

    @classmethod
    def from_file(cls, path: str) -> "PsDocument":
        """Create a document from a file path.

        Example:
            >>> isinstance(PsDocument.from_bytes(b""), PsDocument)
            True
        """
        with open(path, "rb") as handle:
            data = handle.read()
        doc = cls.from_bytes(data)
        doc.source_path = path
        return doc

    def add_page(self, size: tuple[float, float] | None = None) -> PsPage:
        """Append a new page and return it."""
        page = PsPage(*(size or _default_page_size(self)))
        self.pages.append(page)
        self.dirty = True
        return page

    def insert_page(self, index: int, size: tuple[float, float] | None = None) -> PsPage:
        """Insert a new page at the provided index and return it."""
        if index < 0 or index > len(self.pages):
            raise IndexError("page index out of range")
        page = PsPage(*(size or _default_page_size(self)))
        self.pages.insert(index, page)
        self.dirty = True
        return page

    def remove_page(self, index: int) -> None:
        """Remove the page at the provided index."""
        if index < 0 or index >= len(self.pages):
            raise IndexError("page index out of range")
        self.pages.pop(index)
        self.dirty = True

    def get_page(self, index: int) -> PsPage:
        """Return the page at the provided index."""
        if index < 0 or index >= len(self.pages):
            raise IndexError("page index out of range")
        return self.pages[index]

    def save(self, path: str | None = None) -> bytes:
        """Serialize the document to bytes and optionally write to a file."""
        from .serializer import serialize_document
        from .xmp import extract_xmp, replace_xmp

        if self.pages and (self.dirty or any(page.dirty for page in self.pages) or not self.data):
            data = serialize_document(self)
            xmp_xml = extract_xmp(self.data)
            if xmp_xml:
                data = replace_xmp(data, xmp_xml)
            self.data = data
            self.dirty = False
            for page in self.pages:
                page.dirty = False
        else:
            data = self.data
        if path:
            with open(path, "wb") as handle:
                handle.write(data)
        return data

    def as_bytes(self) -> bytes:
        """Return the raw document bytes."""
        if self.pages and (self.dirty or any(page.dirty for page in self.pages) or not self.data):
            from .serializer import serialize_document
            from .xmp import extract_xmp, replace_xmp

            data = serialize_document(self)
            xmp_xml = extract_xmp(self.data)
            if xmp_xml:
                data = replace_xmp(data, xmp_xml)
            return data
        return self.data

    def get_xmp(self) -> str | None:
        """Return XMP metadata from an EPS document, if present."""
        from .xmp import extract_xmp

        data = self.data or self.as_bytes()
        return extract_xmp(data)

    def set_xmp(self, xmp_xml: str) -> None:
        """Set XMP metadata on an EPS document."""
        from .xmp import replace_xmp

        if not self.is_eps and not _detect_eps(self.data):
            raise ValueError("EPS document required")
        data = self.data or self.as_bytes()
        self.data = replace_xmp(data, xmp_xml)

    def remove_xmp(self) -> None:
        """Remove XMP metadata from an EPS document."""
        from .xmp import remove_xmp

        if not self.is_eps and not _detect_eps(self.data):
            raise ValueError("EPS document required")
        data = self.data or self.as_bytes()
        self.data = remove_xmp(data)

    def to_pdf(self, options: "PdfSaveOptions | None" = None) -> bytes:
        """Convert the document to PDF bytes."""
        from .output import to_pdf

        return to_pdf(self, options)

    def to_image(self, options: "ImageSaveOptions") -> bytes:
        """Convert the document to raster image bytes."""
        from .output import to_image

        return to_image(self, options)


def _detect_eps(data: bytes) -> bool:
    if not data:
        return False
    header_text = data[:2048].decode("latin-1", errors="ignore")
    first_line = header_text.splitlines()[0] if header_text else ""
    if first_line.startswith("%!PS-Adobe-") and "EPSF" in first_line:
        return True
    return "%%BoundingBox" in header_text


def _extract_header(data: bytes) -> tuple[str, list[str]]:
    text = data.decode("latin-1", errors="ignore")
    lines = text.splitlines()
    if lines and lines[0].startswith("%!"):
        return lines[0], lines[1:]
    return "%!PS-Adobe-3.0", lines


def _parse_pages(
    lines: list[str], dsc: DscMetadata | None, is_eps: bool
) -> tuple[list[PsPage], list[str], list[str]]:
    page_size = page_size_from_dsc(dsc)
    pages: list[PsPage] = []
    prolog: list[str] = []
    trailer: list[str] = []
    current_content: list[str] = []
    in_page = False
    in_trailer = False

    for line in lines:
        if line.startswith("%%Page:") and not in_trailer:
            if in_page:
                pages.append(PsPage(page_size[0], page_size[1], current_content))
                current_content = []
            in_page = True
            continue
        if line.startswith("%%Trailer"):
            if in_page:
                pages.append(PsPage(page_size[0], page_size[1], current_content))
                current_content = []
                in_page = False
            in_trailer = True
            trailer.append(line)
            continue
        if in_trailer:
            trailer.append(line)
        elif in_page:
            current_content.append(line)
        else:
            prolog.append(line)

    if in_page:
        pages.append(PsPage(page_size[0], page_size[1], current_content))

    if not pages:
        split_index = None
        for idx, line in enumerate(lines):
            if line.startswith("%%EndComments"):
                split_index = idx
                break
        if split_index is not None:
            prolog = lines[: split_index + 1]
            content = lines[split_index + 1 :]
        else:
            prolog = []
            content = lines
        pages.append(PsPage(page_size[0], page_size[1], content))
        trailer = []

    return pages, _filter_prolog(prolog, is_eps), _filter_trailer(trailer)


def _filter_prolog(lines: list[str], is_eps: bool) -> list[str]:
    filtered: list[str] = []
    for line in lines:
        if line.startswith("%%Pages:"):
            continue
        if line.startswith("%%Page:"):
            continue
        if is_eps and (line.startswith("%%BoundingBox:") or line.startswith("%%HiResBoundingBox:")):
            continue
        filtered.append(line)
    return filtered


def _filter_trailer(lines: list[str]) -> list[str]:
    return [line for line in lines if not line.startswith("%%Pages:")]


def _default_page_size(doc: PsDocument) -> tuple[float, float]:
    if doc.pages:
        page = doc.pages[0]
        return (page.width, page.height)
    return page_size_from_dsc(doc.dsc)
