"""Filter decoding utilities for PS/EPS streams."""

from __future__ import annotations

from dataclasses import dataclass
import zlib

from .errors import PsUndefinedError, PsRangeError


@dataclass(frozen=True)
class FilterResult:
    """Result of decoding a filter chain.

    Example:
        >>> result = FilterResult(b"data", None, None)
        >>> result.data
        b'data'
    """

    data: bytes
    remaining_filter: str | None
    params: dict | None


_DECODER_MAP = {
    "ASCIIHexDecode": "ascii_hex",
    "ASCII85Decode": "ascii85",
    "LZWDecode": "lzw",
    "FlateDecode": "flate",
    "RunLengthDecode": "run_length",
    "SubFileDecode": "subfile",
    "ReusableStreamDecode": "reusable",
}


def decode_filters(
    data: bytes, filters: list[tuple[str, dict | None]], allow_encoded: bool = False
) -> FilterResult:
    """Decode a list of PS/EPS filters.

    Example:
        >>> decode_filters(b"61 62 63", [("ASCIIHexDecode", None)]).data
        b'abc'
    """
    remaining_filter = None
    remaining_params = None
    current = data
    for name, params in filters:
        filter_name = _normalize_filter_name(name)
        if filter_name in ("DCTDecode", "CCITTFaxDecode"):
            if allow_encoded:
                remaining_filter = filter_name
                remaining_params = params
                break
            raise PsUndefinedError(f"unsupported filter {filter_name}")
        if filter_name == "ReusableStreamDecode":
            continue
        if filter_name == "SubFileDecode":
            count = None
            if params is not None:
                count = params.get("Count")
            current = subfile_decode(current, count)
            continue
        decoder_key = _DECODER_MAP.get(filter_name)
        if decoder_key is None:
            raise PsUndefinedError(f"unsupported filter {filter_name}")
        if decoder_key == "ascii_hex":
            current = ascii_hex_decode(current)
        elif decoder_key == "ascii85":
            current = ascii85_decode(current)
        elif decoder_key == "lzw":
            early_change = 1
            if params is not None:
                raw_early = params.get("EarlyChange")
                if isinstance(raw_early, (int, float)):
                    early_change = int(raw_early)
            current = lzw_decode(current, early_change=early_change)
        elif decoder_key == "flate":
            current = flate_decode(current)
        elif decoder_key == "run_length":
            current = run_length_decode(current)
        elif decoder_key == "subfile":
            current = subfile_decode(current, None)
    return FilterResult(current, remaining_filter, remaining_params)


def ascii_hex_decode(data: bytes) -> bytes:
    """Decode ASCIIHex encoded data."""
    hex_chars = []
    for ch in data:
        if ch in b" \t\r\n\f\0":
            continue
        if ch == ord(">"):
            break
        hex_chars.append(chr(ch))
    if len(hex_chars) % 2 == 1:
        hex_chars.append("0")
    try:
        return bytes.fromhex("".join(hex_chars))
    except ValueError as exc:
        raise PsRangeError("invalid ASCIIHex data") from exc


def ascii85_decode(data: bytes) -> bytes:
    """Decode ASCII85 encoded data."""
    text = data.decode("latin-1", errors="ignore")
    filtered = []
    index = 0
    while index < len(text):
        if text[index] == "~" and index + 1 < len(text) and text[index + 1] == ">":
            break
        char = text[index]
        if char.isspace():
            index += 1
            continue
        filtered.append(char)
        index += 1

    output = bytearray()
    group = []
    for char in filtered:
        if char == "z" and not group:
            output.extend(b"\x00\x00\x00\x00")
            continue
        group.append(char)
        if len(group) == 5:
            output.extend(_decode_ascii85_group(group))
            group = []
    if group:
        padding = 5 - len(group)
        group.extend(["u"] * padding)
        decoded = _decode_ascii85_group(group)
        output.extend(decoded[: 4 - padding])
    return bytes(output)


def _decode_ascii85_group(group: list[str]) -> bytes:
    value = 0
    for char in group:
        value = value * 85 + (ord(char) - 33)
    return value.to_bytes(4, byteorder="big")


def run_length_decode(data: bytes) -> bytes:
    """Decode RunLength encoded data."""
    output = bytearray()
    index = 0
    while index < len(data):
        length = data[index]
        index += 1
        if length == 128:
            break
        if length <= 127:
            count = length + 1
            output.extend(data[index : index + count])
            index += count
        else:
            count = 257 - length
            if index >= len(data):
                break
            output.extend(data[index : index + 1] * count)
            index += 1
    return bytes(output)


def flate_decode(data: bytes) -> bytes:
    """Decode Flate (zlib/deflate) data."""
    return zlib.decompress(data)


def lzw_decode(data: bytes, early_change: int = 1) -> bytes:
    """Decode LZW-compressed data (PostScript/PDF variant).

    Args:
        data: LZW-compressed bytes.
        early_change: ``LZWDecode`` EarlyChange parameter (default ``1``).
    """
    if not data:
        return b""
    data_bits = _BitReader(data)
    clear_code = 256
    end_code = 257
    code_size = 9
    dictionary = {i: bytes([i]) for i in range(256)}
    next_code = 258
    output = bytearray()

    prev = None
    while True:
        code = data_bits.read(code_size)
        if code is None:
            break
        if code == clear_code:
            dictionary = {i: bytes([i]) for i in range(256)}
            next_code = 258
            code_size = 9
            prev = None
            continue
        if code == end_code:
            break
        if code in dictionary:
            entry = dictionary[code]
        elif prev is not None and code == next_code:
            # KwKwK special case from the LZW spec.
            entry = prev + prev[:1]
        else:
            raise PsRangeError("invalid LZW stream")
        output.extend(entry)
        if prev is not None:
            dictionary[next_code] = prev + entry[:1]
            next_code += 1
            if code_size < 12:
                threshold = (1 << code_size) - max(0, min(1, int(early_change)))
                if next_code == threshold:
                    code_size += 1
        prev = entry
    return bytes(output)


def subfile_decode(data: bytes, count: int | None) -> bytes:
    """Decode SubFile data (truncate to Count)."""
    if count is None:
        return data
    if count < 0:
        raise PsRangeError("invalid SubFileDecode count")
    return data[:count]


class _BitReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._byte_pos = 0
        self._bit_pos = 0

    def read(self, bits: int) -> int | None:
        value = 0
        for _ in range(bits):
            if self._byte_pos >= len(self._data):
                return None
            value <<= 1
            byte = self._data[self._byte_pos]
            value |= (byte >> (7 - self._bit_pos)) & 1
            self._bit_pos += 1
            if self._bit_pos == 8:
                self._bit_pos = 0
                self._byte_pos += 1
        return value


def _normalize_filter_name(name: str) -> str:
    if name.startswith("/"):
        return name[1:]
    return name
