"""Utilities for parsing embedded Type1 font metrics."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .encodings import STANDARD_ENCODING
from .objects import PsArray, PsDict, PsName


@dataclass(frozen=True)
class Type1Metrics:
    font_name: str
    units_per_em: int
    glyph_widths: dict[str, float]
    code_widths: dict[int, float]
    encoding: dict[int, str]
    font_bbox: tuple[int, int, int, int] | None
    font_program_type1: bytes | None


def parse_embedded_type1(font_dict: PsDict, program_bytes: bytes | None) -> Type1Metrics | None:
    """Parse an embedded Type1 font dictionary/program and return metrics."""
    font_name = _font_name_from_dict(font_dict)
    if not font_name:
        return None
    encoding = _encoding_from_dict(font_dict)
    units_per_em = _units_per_em_from_dict(font_dict)
    font_bbox = _font_bbox_from_dict(font_dict)

    glyph_widths: dict[str, float] = {}
    if program_bytes:
        try:
            decrypted = decrypt_eexec(program_bytes)
            glyph_widths = parse_type1_widths_from_private_dict(decrypted)
        except Exception:
            glyph_widths = {}

    code_widths: dict[int, float] = {}
    for code, glyph_name in encoding.items():
        width = glyph_widths.get(glyph_name)
        if width is not None:
            code_widths[code] = width

    return Type1Metrics(
        font_name=font_name,
        units_per_em=units_per_em,
        glyph_widths=glyph_widths,
        code_widths=code_widths,
        encoding=encoding,
        font_bbox=font_bbox,
        # Keep this optional payload for future Type1 PDF embedding work.
        font_program_type1=program_bytes if program_bytes else None,
    )


def parse_type1_resource_block(block: bytes) -> Type1Metrics | None:
    """Parse a full %%BeginResource/%%EndResource Type1 block."""
    if b"/FontType 1" not in block or b"currentfile eexec" not in block:
        return None

    font_name = _extract_font_name(block)
    if not font_name:
        return None

    font_dict = PsDict(
        {
            "FontName": PsName(font_name, literal=True),
            "Encoding": _encoding_array_from_block(block),
        }
    )
    matrix = _extract_font_matrix(block)
    if matrix is not None:
        font_dict.items["FontMatrix"] = PsArray(matrix)
    bbox = _extract_font_bbox(block)
    if bbox is not None:
        font_dict.items["FontBBox"] = PsArray([float(v) for v in bbox])

    program = _extract_eexec_bytes(block)
    return parse_embedded_type1(font_dict, program)


def decrypt_eexec(cipher_bytes: bytes) -> bytes:
    """Decrypt eexec bytes using the Type1 algorithm."""
    r = 55665
    plain = bytearray(len(cipher_bytes))
    for idx, value in enumerate(cipher_bytes):
        plain[idx] = value ^ (r >> 8)
        r = ((value + r) * 52845 + 22719) & 0xFFFF
    # eexec has a random warm-up prefix (typically 4 bytes).
    if len(plain) <= 4:
        return b""
    return bytes(plain[4:])


def parse_type1_widths_from_private_dict(decrypted_program: bytes) -> dict[str, float]:
    """Extract glyph widths from decrypted Private/CharStrings section."""
    charstrings_pos = decrypted_program.find(b"/CharStrings")
    if charstrings_pos < 0:
        return {}

    len_iv = _extract_leniv(decrypted_program)
    widths: dict[str, float] = {}
    cursor = charstrings_pos
    data_len = len(decrypted_program)

    while cursor < data_len:
        name_start = decrypted_program.find(b"/", cursor)
        if name_start < 0:
            break
        name_end = _scan_token_end(decrypted_program, name_start + 1)
        if name_end <= name_start + 1:
            cursor = name_start + 1
            continue
        glyph_name = decrypted_program[name_start + 1:name_end].decode("latin-1", errors="ignore")

        length_info = _parse_int_token(decrypted_program, name_end)
        if length_info is None:
            cursor = name_end
            continue
        char_len, token_pos = length_info
        if char_len <= 0:
            cursor = token_pos
            continue

        token_pos = _skip_ws(decrypted_program, token_pos)
        rd_end = _match_rd_token(decrypted_program, token_pos)
        if rd_end is None:
            cursor = token_pos + 1
            continue

        data_start = _skip_one_ws(decrypted_program, rd_end)
        data_end = data_start + char_len
        if data_end > data_len:
            break

        charstring = decrypted_program[data_start:data_end]
        width = parse_type1_charstring_width(charstring, len_iv=len_iv)
        if width is not None:
            widths[glyph_name] = width

        cursor = data_end

    return widths


def parse_type1_charstring_width(charstring_bytes: bytes, len_iv: int = 4) -> float | None:
    """Decrypt a Type1 charstring and return the nominal width if present."""
    if not charstring_bytes:
        return None

    decrypted = _decrypt_charstring(charstring_bytes)
    if len_iv > 0:
        if len(decrypted) <= len_iv:
            return None
        decrypted = decrypted[len_iv:]

    stack: list[int] = []
    idx = 0
    size = len(decrypted)

    while idx < size:
        b0 = decrypted[idx]
        idx += 1

        if 32 <= b0 <= 246:
            stack.append(b0 - 139)
            continue
        if 247 <= b0 <= 250:
            if idx >= size:
                return None
            b1 = decrypted[idx]
            idx += 1
            stack.append((b0 - 247) * 256 + b1 + 108)
            continue
        if 251 <= b0 <= 254:
            if idx >= size:
                return None
            b1 = decrypted[idx]
            idx += 1
            stack.append(-(b0 - 251) * 256 - b1 - 108)
            continue
        if b0 == 255:
            if idx + 4 > size:
                return None
            value = int.from_bytes(decrypted[idx:idx + 4], byteorder="big", signed=True)
            idx += 4
            stack.append(value)
            continue

        if b0 == 12:
            if idx >= size:
                return None
            b1 = decrypted[idx]
            idx += 1
            if b1 == 7 and len(stack) >= 4:  # sbw
                return float(stack[2])
            stack.clear()
            continue

        if b0 == 13 and len(stack) >= 2:  # hsbw
            return float(stack[-1])

        # Regular operators consume the current operand stack.
        stack.clear()

    return None


def _decrypt_charstring(cipher_bytes: bytes) -> bytes:
    r = 4330
    plain = bytearray(len(cipher_bytes))
    for idx, value in enumerate(cipher_bytes):
        plain[idx] = value ^ (r >> 8)
        r = ((value + r) * 52845 + 22719) & 0xFFFF
    return bytes(plain)


def _extract_font_name(block: bytes) -> str | None:
    match = re.search(rb"/FontName\s+/([^\s]+)\s+def", block)
    if match is None:
        return None
    return match.group(1).decode("latin-1", errors="ignore")


def _extract_font_matrix(block: bytes) -> list[float] | None:
    match = re.search(rb"/FontMatrix\s*\[([^\]]+)\]", block)
    if match is None:
        return None
    values: list[float] = []
    for part in match.group(1).split():
        try:
            values.append(float(part))
        except ValueError:
            return None
    if len(values) != 6:
        return None
    return values


def _extract_font_bbox(block: bytes) -> tuple[int, int, int, int] | None:
    match = re.search(rb"/FontBBox\s*\{([^\}]+)\}", block)
    if match is None:
        return None
    values: list[int] = []
    for part in match.group(1).split():
        try:
            values.append(int(float(part)))
        except ValueError:
            return None
    if len(values) != 4:
        return None
    return values[0], values[1], values[2], values[3]


def _encoding_array_from_block(block: bytes) -> PsArray:
    values = [PsName(".notdef", literal=True) for _ in range(256)]
    for match in re.finditer(rb"dup\s+(\d+)\s+/([^\s]+)\s+put", block):
        code = int(match.group(1))
        if 0 <= code < 256:
            glyph_name = match.group(2).decode("latin-1", errors="ignore")
            values[code] = PsName(glyph_name, literal=True)
    return PsArray(values)


def _extract_eexec_bytes(block: bytes) -> bytes | None:
    marker = re.search(rb"currentfile\s+eexec", block)
    if marker is None:
        return None
    start = marker.end()
    end = block.find(b"cleartomark", start)
    if end < 0:
        end = len(block)
    chunk = block[start:end]
    hex_chars = re.sub(rb"[^0-9A-Fa-f]", b"", chunk)
    if not hex_chars:
        return None
    if len(hex_chars) % 2 == 1:
        hex_chars = hex_chars[:-1]
    if not hex_chars:
        return None
    try:
        return bytes.fromhex(hex_chars.decode("ascii"))
    except ValueError:
        return None


def _font_name_from_dict(font_dict: PsDict) -> str | None:
    value = font_dict.items.get("FontName")
    if isinstance(value, PsName):
        return value.value
    if isinstance(value, str):
        return value
    return None


def _encoding_from_dict(font_dict: PsDict) -> dict[int, str]:
    encoding_value = font_dict.items.get("Encoding")
    if isinstance(encoding_value, PsArray):
        mapping: dict[int, str] = {}
        for index, item in enumerate(encoding_value.items):
            if isinstance(item, PsName):
                mapping[index] = item.value
            elif isinstance(item, str):
                mapping[index] = item
        if mapping:
            return mapping
    return dict(STANDARD_ENCODING)


def _units_per_em_from_dict(font_dict: PsDict) -> int:
    value = font_dict.items.get("FontMatrix")
    if isinstance(value, PsArray) and len(value.items) >= 4:
        sx = _safe_float(value.items[0])
        sy = _safe_float(value.items[3])
        for scale in (sx, sy):
            if scale is not None and abs(scale) > 1e-12:
                units = int(round(1.0 / abs(scale)))
                if units > 0:
                    return units
    return 1000


def _font_bbox_from_dict(font_dict: PsDict) -> tuple[int, int, int, int] | None:
    value = font_dict.items.get("FontBBox")
    if not isinstance(value, PsArray) or len(value.items) < 4:
        return None
    try:
        return tuple(int(float(value.items[idx])) for idx in range(4))  # type: ignore[return-value]
    except Exception:
        return None


def _extract_leniv(decrypted_program: bytes) -> int:
    match = re.search(rb"/lenIV\s+(-?\d+)\s+def", decrypted_program)
    if match is None:
        return 4
    try:
        return int(match.group(1))
    except ValueError:
        return 4


def _scan_token_end(data: bytes, index: int) -> int:
    size = len(data)
    while index < size:
        if data[index] in b" \t\r\n\f\0[]{}()<>/%":
            break
        index += 1
    return index


def _skip_ws(data: bytes, index: int) -> int:
    size = len(data)
    while index < size and data[index] in b" \t\r\n\f\0":
        index += 1
    return index


def _skip_one_ws(data: bytes, index: int) -> int:
    if index < len(data) and data[index] in b" \t\r\n\f\0":
        return index + 1
    return index


def _parse_int_token(data: bytes, index: int) -> tuple[int, int] | None:
    index = _skip_ws(data, index)
    if index >= len(data):
        return None
    start = index
    if data[index] in (ord("+"), ord("-")):
        index += 1
    has_digit = False
    while index < len(data) and 48 <= data[index] <= 57:
        has_digit = True
        index += 1
    if not has_digit:
        return None
    try:
        value = int(data[start:index].decode("ascii", errors="ignore"))
    except ValueError:
        return None
    return value, index


def _match_rd_token(data: bytes, index: int) -> int | None:
    if data[index:index + 2] in (b"RD", b"-|"):
        return index + 2
    return None


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return None
