"""Serialize PS/EPS documents for saving."""

from __future__ import annotations

from .document import PsDocument


def serialize_document(doc: PsDocument) -> bytes:
    """Serialize a PS/EPS document to bytes."""
    lines: list[str] = []
    header = doc.header or ("%!PS-Adobe-3.0 EPSF-3.0" if doc.is_eps else "%!PS-Adobe-3.0")
    lines.append(header)

    if doc.is_eps:
        bbox = _bbox_for_page(doc)
        lines.append(f"%%BoundingBox: {bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}")

    lines.append(f"%%Pages: {len(doc.pages)}")

    for line in doc.prolog:
        lines.append(line)

    for idx, page in enumerate(doc.pages, start=1):
        lines.append(f"%%Page: {idx} {idx}")
        for content_line in page.content:
            lines.append(content_line)
        if not doc.is_eps and not _has_showpage(page):
            lines.append("showpage")

    for line in doc.trailer:
        lines.append(line)

    output = "\n".join(lines) + "\n"
    return output.encode("latin-1")


def _bbox_for_page(doc: PsDocument) -> tuple[int, int, int, int]:
    if not doc.pages:
        return (0, 0, 612, 792)
    page = doc.pages[0]
    width = int(round(page.width))
    height = int(round(page.height))
    return (0, 0, width, height)


def _has_showpage(page) -> bool:
    for line in page.content:
        if line.strip() == "showpage":
            return True
    return False
