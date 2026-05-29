"""PDF font embedding helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PdfEmbeddedFont:
    base_name: str
    subset_name: str
    subtype: str
    encoding: str | None
    symbolic: bool
    first_char: int
    last_char: int
    widths: list[int]
    font_file_key: str
    font_file: bytes
    ascent: int
    descent: int
    bbox: tuple[int, int, int, int]
    italic_angle: int
    stem_v: int
    to_unicode: str
    char_code_map: dict[int, int]


def build_to_unicode(codes: list[int] | dict[int, int]) -> str:
    if not codes:
        return ""
    if isinstance(codes, dict):
        mapping = {int(src): int(dst) for src, dst in codes.items()}
    else:
        mapping = {int(code): int(code) for code in sorted(set(codes))}
    ordered = sorted(mapping.keys())
    max_code = max(ordered)
    code_width = 2 if max_code <= 0xFF else 4
    hex_width = code_width
    high = 0xFF if code_width == 2 else 0xFFFF
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        f"<{0:0{hex_width}X}> <{high:0{hex_width}X}>",
        "endcodespacerange",
    ]
    chunk: list[tuple[int, int]] = []
    for code in ordered:
        chunk.append((code, mapping[code]))
        if len(chunk) == 100:
            lines.extend(_bfchar_block(chunk, hex_width))
            chunk = []
    if chunk:
        lines.extend(_bfchar_block(chunk, hex_width))
    lines.extend(
        [
            "endcmap",
            "CMapName currentdict /CMap defineresource pop",
            "end",
            "end",
        ]
    )
    return "\n".join(lines)


def _bfchar_block(codes: list[tuple[int, int]], width: int) -> list[str]:
    lines = [f"{len(codes)} beginbfchar"]
    for code, dst in codes:
        lines.append(
            f"<{code:0{width}X}> <{dst:04X}>"
        )
    lines.append("endbfchar")
    return lines
