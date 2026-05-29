"""Font type loaders for PostScript fonts."""

from __future__ import annotations

import struct

from .fonts import FontResource, parse_ttf_metrics, _glyph_widths_from_encoding
from .type1_parser import parse_embedded_type1
from .objects import PsArray, PsDict, PsName, PsProcedure, PsString
from .encodings import STANDARD_ENCODING
from .errors import PsTypeError


def load_type1_font(font_dict: PsDict) -> FontResource:
    """Load a Type1 font from a dictionary."""
    font_name = _font_name(font_dict)
    program_bytes = _type1_program_bytes(font_dict)
    metrics = parse_embedded_type1(font_dict, program_bytes)
    if metrics is None:
        return FontResource(font_name, "Type1", 1000, {}, {}, False)
    return FontResource(
        metrics.font_name,
        "Type1",
        metrics.units_per_em,
        metrics.encoding,
        metrics.glyph_widths,
        False,
        code_widths=metrics.code_widths,
        font_program=metrics.font_program_type1,
    )


def load_type3_font(font_dict: PsDict) -> FontResource:
    """Load a Type3 font from a dictionary."""
    font_name = _font_name(font_dict)
    char_procs = font_dict.items.get("CharProcs")
    proc_map = None
    if isinstance(char_procs, PsDict):
        proc_map = {
            key: value for key, value in char_procs.items.items() if isinstance(value, PsProcedure)
        }
    return FontResource(font_name, "Type3", 1000, {}, {}, False, char_procs=proc_map)


def load_type42_font(font_dict: PsDict) -> FontResource:
    """Load a Type42 font from a dictionary."""
    font_name = _font_name(font_dict)
    sfnts = font_dict.items.get("sfnts")
    if not isinstance(sfnts, PsArray):
        raise PsTypeError("sfnts missing for Type42")
    data = _join_sfnts(sfnts)
    code_map: dict[int, int] | None = None
    try:
        units_per_em, code_widths = parse_ttf_metrics(data)
        glyph_widths = _glyph_widths_from_encoding(code_widths, STANDARD_ENCODING)
        fallback = _code_widths_from_type42_dict(font_dict, data)
        if fallback is not None:
            _, fallback_code_widths, _, fallback_code_map = fallback
            for code, width in fallback_code_widths.items():
                code_widths.setdefault(code, width)
            if fallback_code_map:
                code_map = fallback_code_map
    except Exception:
        fallback = _code_widths_from_type42_dict(font_dict, data)
        if fallback is not None:
            units_per_em, code_widths, glyph_widths, code_map = fallback
        else:
            units_per_em = 1000
            code_widths = {}
            glyph_widths = {}
    return FontResource(
        font_name,
        "Type42",
        units_per_em,
        STANDARD_ENCODING,
        glyph_widths,
        False,
        code_widths=code_widths,
        font_program=data,
        code_map=code_map,
    )


def _font_name(font_dict: PsDict) -> str:
    value = font_dict.items.get("FontName")
    if isinstance(value, PsName):
        return value.value
    if isinstance(value, str):
        return value
    raise PsTypeError("FontName missing")


def _join_sfnts(sfnts: PsArray) -> bytes:
    chunks: list[bytes] = []
    for item in sfnts.items:
        if isinstance(item, PsString):
            chunks.append(item.value)
        elif isinstance(item, bytes):
            chunks.append(item)
        else:
            raise PsTypeError("invalid sfnts entry")
    return b"".join(chunks)


def _type1_program_bytes(font_dict: PsDict) -> bytes | None:
    value = font_dict.items.get("__type1_program__")
    if isinstance(value, PsString):
        return value.value
    if isinstance(value, bytes):
        return value
    return None


def _code_widths_from_type42_dict(
    font_dict: PsDict,
    data: bytes,
) -> tuple[int, dict[int, float], dict[str, float], dict[int, int]] | None:
    widths_info = _ttf_hmtx_widths(data)
    if widths_info is None:
        return None
    units_per_em, widths_by_gid = widths_info
    char_strings = font_dict.items.get("CharStrings")
    if not isinstance(char_strings, PsDict):
        return None
    glyph_widths: dict[str, float] = {}
    glyph_ids: dict[str, int] = {}
    for glyph_name, glyph_id_raw in char_strings.items.items():
        if isinstance(glyph_id_raw, (int, float)):
            glyph_id = int(glyph_id_raw)
            if 0 <= glyph_id < len(widths_by_gid):
                glyph_widths[glyph_name] = float(widths_by_gid[glyph_id])
                glyph_ids[glyph_name] = glyph_id
    if not glyph_widths:
        return None
    code_widths: dict[int, float] = {}
    code_map: dict[int, int] = {}
    encoding = font_dict.items.get("Encoding")
    if isinstance(encoding, PsArray):
        for code, entry in enumerate(encoding.items):
            glyph_name: str | None
            if isinstance(entry, PsName):
                glyph_name = entry.value
            elif isinstance(entry, str):
                glyph_name = entry
            else:
                glyph_name = None
            if glyph_name is None:
                continue
            width = glyph_widths.get(glyph_name)
            if width is not None:
                code_widths[code] = width
            gid = glyph_ids.get(glyph_name)
            if gid is None:
                continue
            code_map[code] = gid
            if glyph_name.startswith("uni") and len(glyph_name) > 3:
                try:
                    code_map[int(glyph_name[3:], 16)] = gid
                except ValueError:
                    pass
            elif glyph_name.startswith("u") and len(glyph_name) in (5, 6, 7):
                try:
                    code_map[int(glyph_name[1:], 16)] = gid
                except ValueError:
                    pass
    return units_per_em, code_widths, glyph_widths, code_map


def _ttf_hmtx_widths(data: bytes) -> tuple[int, list[float]] | None:
    if len(data) < 12:
        return None
    num_tables = _read_uint16(data, 4)
    tables: dict[bytes, int] = {}
    for index in range(num_tables):
        entry = 12 + index * 16
        if entry + 16 > len(data):
            return None
        tag = data[entry:entry + 4]
        offset = _read_uint32(data, entry + 8)
        tables[tag] = offset
    head = tables.get(b"head")
    hhea = tables.get(b"hhea")
    maxp = tables.get(b"maxp")
    hmtx = tables.get(b"hmtx")
    if head is None or hhea is None or maxp is None or hmtx is None:
        return None
    if head + 20 > len(data) or hhea + 36 > len(data) or maxp + 6 > len(data):
        return None
    units_per_em = _read_uint16(data, head + 18)
    num_hmetrics = _read_uint16(data, hhea + 34)
    num_glyphs = _read_uint16(data, maxp + 4)
    widths: list[float] = []
    cursor = hmtx
    last_width = 0
    for _ in range(num_hmetrics):
        if cursor + 4 > len(data):
            return None
        width = _read_uint16(data, cursor)
        last_width = width
        widths.append(float(width))
        cursor += 4
    while len(widths) < num_glyphs:
        widths.append(float(last_width))
    return units_per_em, widths


def _read_uint16(data: bytes, offset: int) -> int:
    return struct.unpack(">H", data[offset:offset + 2])[0]


def _read_uint32(data: bytes, offset: int) -> int:
    return struct.unpack(">I", data[offset:offset + 4])[0]
