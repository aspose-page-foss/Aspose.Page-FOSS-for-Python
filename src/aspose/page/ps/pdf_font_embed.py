"""Build embedded PDF fonts from PS font resolver data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
import struct
from typing import Iterable

from .fonts import FontResolver
from .ttf_subset import ensure_ttf_cmap, has_ttf_table, subset_ttf
from .objects import PsArray, PsDict, PsName
from ..pdf.fonts import PdfEmbeddedFont, build_to_unicode


_STANDARD_FONTS = {
    "Courier",
    "Courier-Bold",
    "Courier-Oblique",
    "Courier-BoldOblique",
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-Oblique",
    "Helvetica-BoldOblique",
    "Times-Roman",
    "Times-Bold",
    "Times-Italic",
    "Times-BoldItalic",
    "Symbol",
    "ZapfDingbats",
}


def build_embedded_font(
    font_name: str, used_codes: set[int], resolver: FontResolver
) -> PdfEmbeddedFont | None:
    if not used_codes:
        return None
    if font_name in _STANDARD_FONTS:
        return None
    candidate_names: list[str] = [font_name]
    allow_full_embed_on_subset_failure = False
    embedded = resolver.get_embedded_type42(font_name)
    type42_code_map = _extract_type42_code_to_gid(resolver, font_name)
    if embedded is not None:
        data = embedded.data
        units_per_em = embedded.units_per_em
        code_widths = embedded.code_widths
        allow_full_embed_on_subset_failure = True
    else:
        resolved = None
        try:
            resolved = resolver.resolve(font_name)
        except Exception:
            resolved = None

        source = resolved
        if source is not None and source.descendant is not None and source.font_program is None:
            source = source.descendant

        if (
            source is not None
            and source.font_program is not None
            and source.code_widths is not None
        ):
            data = source.font_program
            units_per_em = source.units_per_em
            code_widths = source.code_widths
            allow_full_embed_on_subset_failure = True
            base_name = _font_name_from_dict(source.font_dict)
            if base_name:
                candidate_names.append(base_name)
        else:
            loaded = _load_font_from_path(font_name, resolver)
            if loaded is None:
                return None
            data, units_per_em, code_widths = loaded

    if not has_ttf_table(data, b"cmap") and type42_code_map:
        try:
            data = ensure_ttf_cmap(data, type42_code_map)
        except Exception:
            pass

    unicode_codes = sorted(code for code in used_codes if 0 <= code <= 0x10FFFF)
    if not unicode_codes:
        return None

    pdf_to_unicode = _assign_pdf_codes(unicode_codes)
    if not pdf_to_unicode:
        return None

    try:
        subset_data, _code_to_gid = subset_ttf(data, set(pdf_to_unicode.keys()) | {0}, code_remap=pdf_to_unicode)
    except Exception:
        if allow_full_embed_on_subset_failure:
            subset_data = data if has_ttf_table(data, b"cmap") else None
        else:
            subset_data = None
        if subset_data is None:
            for candidate in candidate_names:
                loaded = _load_font_from_path(candidate, resolver)
                if loaded is None:
                    continue
                fallback_data, fallback_units, fallback_widths = loaded
                try:
                    subset_data, _code_to_gid = subset_ttf(
                        fallback_data,
                        set(pdf_to_unicode.keys()) | {0},
                        code_remap=pdf_to_unicode,
                    )
                except Exception:
                    continue
                data = fallback_data
                units_per_em = fallback_units
                code_widths = fallback_widths
                break
        if subset_data is None:
            return None

    first_char = min(pdf_to_unicode.keys())
    last_char = max(pdf_to_unicode.keys())
    widths = _build_widths_remapped(code_widths, units_per_em, first_char, last_char, pdf_to_unicode)
    metrics = _read_metrics(subset_data)
    tag = _subset_tag(font_name, unicode_codes)
    subset_name = f"{tag}+{_sanitize_pdf_font_name(font_name)}"
    to_unicode = build_to_unicode(pdf_to_unicode)
    char_code_map = {unicode_code: pdf_code for pdf_code, unicode_code in pdf_to_unicode.items()}
    return PdfEmbeddedFont(
        base_name=font_name,
        subset_name=subset_name,
        subtype="TrueType",
        encoding="WinAnsiEncoding",
        symbolic=False,
        first_char=first_char,
        last_char=last_char,
        widths=widths,
        font_file_key="FontFile2",
        font_file=subset_data,
        ascent=metrics.ascent,
        descent=metrics.descent,
        bbox=metrics.bbox,
        italic_angle=metrics.italic_angle,
        stem_v=metrics.stem_v,
        to_unicode=to_unicode,
        char_code_map=char_code_map,
    )


def _extract_type42_code_to_gid(
    resolver: FontResolver,
    font_name: str,
) -> dict[int, int]:
    defined = resolver._defined_fonts.get(font_name)
    if defined is None:
        aliased = resolver._aliases.get(font_name)
        if aliased:
            defined = resolver._defined_fonts.get(aliased)
    font_dict = defined.font_dict if defined is not None else None
    if not isinstance(font_dict, PsDict):
        return {}
    char_strings = font_dict.items.get("CharStrings")
    encoding = font_dict.items.get("Encoding")
    if not isinstance(char_strings, PsDict) or not isinstance(encoding, PsArray):
        return {}
    glyph_to_gid: dict[str, int] = {}
    for glyph_name, glyph_id_raw in char_strings.items.items():
        if isinstance(glyph_name, str) and isinstance(glyph_id_raw, (int, float)):
            glyph_to_gid[glyph_name] = int(glyph_id_raw)
    if not glyph_to_gid:
        return {}
    code_to_gid: dict[int, int] = {}
    for code, entry in enumerate(encoding.items):
        glyph_name: str | None = None
        if isinstance(entry, PsName):
            glyph_name = entry.value
        elif isinstance(entry, str):
            glyph_name = entry
        if glyph_name is None:
            continue
        gid = glyph_to_gid.get(glyph_name)
        if gid is None:
            continue
        code_to_gid[code] = gid
    return code_to_gid


def _load_font_from_path(
    font_name: str, resolver: FontResolver
) -> tuple[bytes, int, dict[int, float]] | None:
    path = resolver.resolve_ttf_path(font_name)
    if path is None:
        try:
            record = resolver._font_cache.find_font(font_name, None)
        except Exception:
            record = None
        if record is not None and record.path.exists():
            path = record.path
    if path is None or not path.exists():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    try:
        metrics = resolver._font_cache.metrics_for(path)
    except Exception:
        return None
    return data, metrics.units_per_em, metrics.code_widths


def _font_name_from_dict(font_dict: object) -> str | None:
    items = getattr(font_dict, "items", None)
    if not isinstance(items, dict):
        return None
    value = items.get("FontName")
    name = getattr(value, "value", None)
    if isinstance(name, str) and name:
        return name
    if isinstance(value, str) and value:
        return value
    return None


@dataclass(frozen=True)
class _FontMetrics:
    ascent: int
    descent: int
    bbox: tuple[int, int, int, int]
    italic_angle: int
    stem_v: int


def _build_widths(
    code_widths: dict[int, float],
    units_per_em: int,
    first_char: int,
    last_char: int,
) -> list[int]:
    widths: list[int] = []
    scale = 1000.0 / max(1, units_per_em)
    for code in range(first_char, last_char + 1):
        width_units = code_widths.get(code, 0.0)
        widths.append(int(round(width_units * scale)))
    return widths


def _build_widths_remapped(
    code_widths: dict[int, float],
    units_per_em: int,
    first_char: int,
    last_char: int,
    pdf_to_unicode: dict[int, int],
) -> list[int]:
    widths: list[int] = []
    scale = 1000.0 / max(1, units_per_em)
    for pdf_code in range(first_char, last_char + 1):
        unicode_code = pdf_to_unicode.get(pdf_code)
        if unicode_code is None:
            widths.append(0)
            continue
        width_units = code_widths.get(unicode_code, 0.0)
        widths.append(int(round(width_units * scale)))
    return widths


def _assign_pdf_codes(unicode_codes: list[int]) -> dict[int, int]:
    assigned: dict[int, int] = {}
    used_pdf_codes: set[int] = set()
    for code in unicode_codes:
        if 0 <= code <= 0xFF and code not in used_pdf_codes:
            assigned[code] = code
            used_pdf_codes.add(code)
    # Avoid control-character codes for remapped glyphs. Some PDF viewers
    # (notably Acrobat) may treat 0x00-0x1F text bytes inconsistently.
    next_pdf = 0x21
    for code in unicode_codes:
        if code in assigned.values():
            continue
        while next_pdf in used_pdf_codes and next_pdf <= 0xFF:
            next_pdf += 1
        if next_pdf > 0xFF:
            return {}
        assigned[next_pdf] = code
        used_pdf_codes.add(next_pdf)
    return assigned


def _read_metrics(data: bytes) -> _FontMetrics:
    tables = _parse_table_directory(data)
    head = tables.get(b"head")
    hhea = tables.get(b"hhea")
    post = tables.get(b"post")
    if head is None or hhea is None:
        raise ValueError("missing TrueType tables")
    units = _read_uint16(data, head + 18)
    scale = 1000.0 / max(1, units)
    x_min = _read_int16(data, head + 36)
    y_min = _read_int16(data, head + 38)
    x_max = _read_int16(data, head + 40)
    y_max = _read_int16(data, head + 42)
    ascent = _read_int16(data, hhea + 4)
    descent = _read_int16(data, hhea + 6)
    italic_angle = 0
    if post is not None and post + 8 <= len(data):
        italic_angle = int(round(_read_fixed(data, post + 4)))
    bbox = (
        int(round(x_min * scale)),
        int(round(y_min * scale)),
        int(round(x_max * scale)),
        int(round(y_max * scale)),
    )
    return _FontMetrics(
        ascent=int(round(ascent * scale)),
        descent=int(round(descent * scale)),
        bbox=bbox,
        italic_angle=italic_angle,
        stem_v=80,
    )


def _subset_tag(font_name: str, codes: Iterable[int]) -> str:
    seed = f"{font_name}:{','.join(str(c) for c in codes)}"
    value = abs(hash(seed))
    letters = []
    for _ in range(6):
        letters.append(chr(ord("A") + (value % 26)))
        value //= 26
    return "".join(letters)


def _sanitize_pdf_font_name(font_name: str) -> str:
    name = font_name.strip()
    if not name:
        return "EmbeddedFont"
    # XPS font refs are often package-like paths such as /Resources/mshei.ttf.
    # PDF Name values in /BaseFont and /FontName must avoid raw "/" tokens.
    path_name = PurePosixPath(name).name or name
    stem = path_name.rsplit(".", 1)[0] if "." in path_name else path_name
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")
    return safe or "EmbeddedFont"


def _parse_table_directory(data: bytes) -> dict[bytes, int]:
    if len(data) < 12:
        return {}
    num_tables = _read_uint16(data, 4)
    offset = 12
    tables: dict[bytes, int] = {}
    for _ in range(num_tables):
        tag = data[offset:offset + 4]
        table_offset = _read_uint32(data, offset + 8)
        tables[tag] = table_offset
        offset += 16
    return tables


def _read_uint16(data: bytes, offset: int) -> int:
    return struct.unpack(">H", data[offset:offset + 2])[0]


def _read_uint32(data: bytes, offset: int) -> int:
    return struct.unpack(">I", data[offset:offset + 4])[0]


def _read_int16(data: bytes, offset: int) -> int:
    return struct.unpack(">h", data[offset:offset + 2])[0]


def _read_fixed(data: bytes, offset: int) -> float:
    value = struct.unpack(">i", data[offset:offset + 4])[0]
    return value / 65536.0
