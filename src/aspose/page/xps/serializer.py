"""XPS serialization helpers."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from .editing import XpsCanvas, XpsFixedPage, XpsGlyphs, XpsImage, XpsPath


_XPS_NS = "http://schemas.microsoft.com/xps/2005/06"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

ET.register_namespace("", _XPS_NS)
ET.register_namespace("r", _RELS_NS)


def serialize_fixed_page(page: XpsFixedPage) -> bytes:
    """Serialize a fixed page to XML bytes."""
    root = ET.Element(_qn("FixedPage"), {"Width": _fmt(page.width), "Height": _fmt(page.height)})
    for element in page.elements:
        _append_element(root, element)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def serialize_document_sequence(pages: list[str]) -> dict[str, bytes]:
    """Serialize document sequence, fixed document, and relationships."""
    fdseq = ET.Element(_qn("FixedDocumentSequence"))
    ET.SubElement(fdseq, _qn("DocumentReference"), {"Source": "Documents/1/FixedDoc.fdoc"})
    fdseq_bytes = ET.tostring(fdseq, encoding="utf-8", xml_declaration=True)

    fixed_doc = ET.Element(_qn("FixedDocument"))
    for part in pages:
        ET.SubElement(fixed_doc, _qn("PageContent"), {"Source": _relative_page_source(part)})
    fixed_doc_bytes = ET.tostring(fixed_doc, encoding="utf-8", xml_declaration=True)

    rels = ET.Element(_rels_qn("Relationships"))
    ET.SubElement(
        rels,
        _rels_qn("Relationship"),
        {
            "Id": "rId1",
            "Type": "http://schemas.microsoft.com/xps/2005/06/fixedrepresentation",
            "Target": "FixedDocSeq.fdseq",
        },
    )
    rels_bytes = ET.tostring(rels, encoding="utf-8", xml_declaration=True)

    return {
        "/_rels/.rels": rels_bytes,
        "/FixedDocSeq.fdseq": fdseq_bytes,
        "/Documents/1/FixedDoc.fdoc": fixed_doc_bytes,
    }


def _append_element(parent: ET.Element, element: object) -> None:
    if isinstance(element, XpsPath):
        attrs = {"Data": element.data}
        if element.fill is not None:
            attrs["Fill"] = element.fill
        if element.stroke is not None:
            attrs["Stroke"] = element.stroke
        if element.stroke_thickness is not None:
            attrs["StrokeThickness"] = _fmt(element.stroke_thickness)
        ET.SubElement(parent, _qn("Path"), attrs)
        return
    if isinstance(element, XpsGlyphs):
        attrs = {
            "FontUri": element.font_uri,
            "FontRenderingEmSize": _fmt(element.font_size),
            "OriginX": _fmt(element.origin_x),
            "OriginY": _fmt(element.origin_y),
            "UnicodeString": element.unicode_string,
        }
        if element.fill is not None:
            attrs["Fill"] = element.fill
        ET.SubElement(parent, _qn("Glyphs"), attrs)
        return
    if isinstance(element, XpsImage):
        attrs = {
            "Source": element.source,
            "Width": _fmt(element.width),
            "Height": _fmt(element.height),
        }
        if element.transform is not None:
            attrs["RenderTransform"] = element.transform
        ET.SubElement(parent, _qn("Image"), attrs)
        return
    if isinstance(element, XpsCanvas):
        attrs: dict[str, str] = {}
        if element.transform is not None:
            attrs["RenderTransform"] = element.transform
        if element.clip is not None:
            attrs["Clip"] = element.clip
        canvas_el = ET.SubElement(parent, _qn("Canvas"), attrs)
        for child in element.elements:
            _append_element(canvas_el, child)
        return
    if isinstance(element, ET.Element):
        parent.append(_clone_element(element))
        return
    if isinstance(element, (str, bytes)):
        parsed = ET.fromstring(element)
        parent.append(parsed)
        return
    raise ValueError("unsupported XPS element type")


def _clone_element(element: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(element, encoding="utf-8"))


def _relative_page_source(part_name: str) -> str:
    if part_name.startswith("/Documents/1/"):
        return part_name[len("/Documents/1/") :]
    if part_name.startswith("/"):
        return part_name[1:]
    return part_name


def _qn(tag: str) -> str:
    return f"{{{_XPS_NS}}}{tag}"


def _rels_qn(tag: str) -> str:
    return f"{{{_RELS_NS}}}{tag}"


def _fmt(value: float) -> str:
    if float(int(value)) == float(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")
