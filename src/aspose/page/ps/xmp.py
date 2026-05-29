"""EPS XMP metadata helpers."""

from __future__ import annotations

from xml.etree import ElementTree as ET


def extract_xmp(data: bytes) -> str | None:
    """Extract an XMP packet from EPS bytes if present."""
    packet = _extract_between_markers(data, b"%%BeginXMP", b"%%EndXMP")
    if packet is not None:
        return _decode_xml(packet)
    packet = _extract_xmpmeta_block(data)
    if packet is not None:
        return _decode_xml(packet)
    return None


def replace_xmp(data: bytes, xmp_xml: str) -> bytes:
    """Replace or insert an XMP packet into EPS bytes."""
    _ensure_xml(xmp_xml)
    packet_bytes = _build_packet(xmp_xml)

    begin = data.find(b"%%BeginXMP")
    if begin != -1:
        end = data.find(b"%%EndXMP", begin)
        if end != -1:
            block_end = _line_end(data, end)
            return data[:begin] + packet_bytes + data[block_end:]

    xmp_start, xmp_end = _find_xmpmeta_bounds(data)
    if xmp_start != -1 and xmp_end != -1:
        return data[:xmp_start] + xmp_xml.encode("utf-8") + data[xmp_end:]

    insert_at = _find_insertion_index(data)
    return data[:insert_at] + packet_bytes + data[insert_at:]


def remove_xmp(data: bytes) -> bytes:
    """Remove any XMP packet from EPS bytes."""
    begin = data.find(b"%%BeginXMP")
    if begin != -1:
        end = data.find(b"%%EndXMP", begin)
        if end != -1:
            block_end = _line_end(data, end)
            return data[:begin] + data[block_end:]

    xmp_start, xmp_end = _find_xmpmeta_bounds(data)
    if xmp_start != -1 and xmp_end != -1:
        return data[:xmp_start] + data[xmp_end:]
    return data


def _ensure_xml(xmp_xml: str) -> None:
    try:
        ET.fromstring(xmp_xml)
    except ET.ParseError as exc:
        raise ValueError("invalid XMP XML") from exc


def _build_packet(xmp_xml: str) -> bytes:
    xml = xmp_xml.strip()
    return ("%%BeginXMP\n" + xml + "\n%%EndXMP\n").encode("utf-8")


def _extract_between_markers(data: bytes, start_marker: bytes, end_marker: bytes) -> bytes | None:
    start = data.find(start_marker)
    if start == -1:
        return None
    end = data.find(end_marker, start)
    if end == -1:
        return None
    content_start = data.find(b"\n", start)
    if content_start == -1:
        content_start = start + len(start_marker)
    else:
        content_start += 1
    content = data[content_start:end]
    return content.strip()


def _extract_xmpmeta_block(data: bytes) -> bytes | None:
    start, end = _find_xmpmeta_bounds(data)
    if start == -1 or end == -1:
        return None
    return data[start:end]


def _find_xmpmeta_bounds(data: bytes) -> tuple[int, int]:
    start_marker = b"<x:xmpmeta"
    end_marker = b"</x:xmpmeta>"
    start = data.find(start_marker)
    if start == -1:
        return -1, -1
    end = data.find(end_marker, start)
    if end == -1:
        return -1, -1
    return start, end + len(end_marker)


def _decode_xml(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("latin-1", errors="ignore")


def _find_insertion_index(data: bytes) -> int:
    text = data.decode("latin-1", errors="ignore")
    lines = text.splitlines(keepends=True)
    if not lines:
        return 0
    offset = len(lines[0])
    insert_at = None
    for line in lines[1:]:
        if line.startswith("%%EndComments"):
            insert_at = offset + len(line)
            break
        if line.startswith("%%Page:"):
            insert_at = offset
            break
        offset += len(line)
    if insert_at is None:
        insert_at = offset
    return insert_at


def _line_end(data: bytes, pos: int) -> int:
    end = data.find(b"\n", pos)
    if end == -1:
        return len(data)
    return end + 1
