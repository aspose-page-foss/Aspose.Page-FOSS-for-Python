"""Raster surface encoders for PNG, BMP, TIFF, and JPEG."""

from __future__ import annotations

import math
import struct
import zlib
from typing import Iterable

from .raster_renderer import RasterSurface


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def encode_png(surface: RasterSurface, dpi: int | None = None) -> bytes:
    """Encode a surface into PNG bytes.

    Example:
        >>> surface = RasterSurface.create(2, 2, (0, 0, 0, 255))
        >>> encode_png(surface).startswith(PNG_SIGNATURE)
        True
    """
    width = surface.width
    height = surface.height
    pixels = surface.pixels
    has_alpha = any(pixels[i + 3] != 255 for i in range(0, len(pixels), 4))
    color_type = 6 if has_alpha else 2
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        row_offset = y * width * 4
        if has_alpha:
            raw.extend(pixels[row_offset:row_offset + width * 4])
        else:
            for x in range(width):
                idx = row_offset + x * 4
                raw.extend(pixels[idx:idx + 3])
    compressed = zlib.compress(bytes(raw))
    ihdr = struct.pack(">IIBBBBB",
                       width,
                       height,
                       8,
                       color_type,
                       0,
                       0,
                       0)
    chunks = [
        _png_chunk(b"IHDR", ihdr),
        _png_chunk(b"IDAT", compressed),
        _png_chunk(b"IEND", b""),
    ]
    data = PNG_SIGNATURE + b"".join(chunks)
    if dpi is None:
        return data
    return add_png_dpi(data, dpi)


def add_png_dpi(data: bytes, dpi: int) -> bytes:
    """Insert or replace pHYs chunk with DPI metadata."""
    if dpi <= 0 or not data.startswith(PNG_SIGNATURE):
        return data
    ppm = int(round(dpi / 0.0254))
    phys = struct.pack(">IIB", ppm, ppm, 1)
    out = bytearray(PNG_SIGNATURE)
    idx = len(PNG_SIGNATURE)
    inserted = False
    while idx + 8 <= len(data):
        length = int.from_bytes(data[idx:idx + 4], "big")
        idx += 4
        ctype = data[idx:idx + 4]
        idx += 4
        chunk = data[idx:idx + length]
        idx += length
        crc = data[idx:idx + 4]
        idx += 4
        if ctype == b"pHYs":
            if not inserted:
                out += _png_chunk(b"pHYs", phys)
                inserted = True
            continue
        if ctype == b"IDAT" and not inserted:
            out += _png_chunk(b"pHYs", phys)
            inserted = True
        out += length.to_bytes(4, "big") + ctype + chunk + crc
    return bytes(out)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return length + tag + data + crc


def encode_bmp(surface: RasterSurface) -> bytes:
    """Encode a surface into 24-bit BMP bytes.

    Example:
        >>> surface = RasterSurface.create(1, 1, (255, 0, 0, 255))
        >>> encode_bmp(surface)[:2] == b\"BM\"
        True
    """
    width = surface.width
    height = surface.height
    row_stride = (width * 3 + 3) & ~3
    pixel_bytes = bytearray()
    for y in range(height - 1, -1, -1):
        row = bytearray()
        row_offset = y * width * 4
        for x in range(width):
            idx = row_offset + x * 4
            r, g, b = surface.pixels[idx:idx + 3]
            row.extend((b, g, r))
        padding = row_stride - width * 3
        if padding:
            row.extend(b"\x00" * padding)
        pixel_bytes.extend(row)
    file_size = 14 + 40 + len(pixel_bytes)
    header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
    dib = struct.pack(
        "<IIIHHIIIIII",
        40,
        width,
        height,
        1,
        24,
        0,
        len(pixel_bytes),
        2835,
        2835,
        0,
        0,
    )
    return header + dib + pixel_bytes


def encode_tiff(surface: RasterSurface) -> bytes:
    """Encode a surface into baseline uncompressed TIFF bytes.

    Example:
        >>> surface = RasterSurface.create(1, 1, (0, 0, 0, 255))
        >>> encode_tiff(surface)[:2] in (b\"II\", b\"MM\")
        True
    """
    width = surface.width
    height = surface.height
    rgb = bytearray()
    for y in range(height):
        row_offset = y * width * 4
        for x in range(width):
            idx = row_offset + x * 4
            rgb.extend(surface.pixels[idx:idx + 3])
    image_bytes = bytes(rgb)
    entries = []
    ifd_offset = 8
    entry_count = 12
    ifd_size = 2 + entry_count * 12 + 4
    bits_offset = ifd_offset + ifd_size
    xres_offset = bits_offset + 6
    yres_offset = xres_offset + 8
    image_offset = yres_offset + 8
    entries.append(_tiff_entry(256, 4, 1, width))
    entries.append(_tiff_entry(257, 4, 1, height))
    entries.append(_tiff_entry(258, 3, 3, bits_offset))
    entries.append(_tiff_entry(259, 3, 1, 1))
    entries.append(_tiff_entry(262, 3, 1, 2))
    entries.append(_tiff_entry(273, 4, 1, image_offset))
    entries.append(_tiff_entry(277, 3, 1, 3))
    entries.append(_tiff_entry(278, 4, 1, height))
    entries.append(_tiff_entry(279, 4, 1, len(image_bytes)))
    entries.append(_tiff_entry(282, 5, 1, xres_offset))
    entries.append(_tiff_entry(283, 5, 1, yres_offset))
    entries.append(_tiff_entry(296, 3, 1, 2))
    header = struct.pack("<2sHI", b"II", 42, ifd_offset)
    ifd = struct.pack("<H", entry_count) + b"".join(entries) + struct.pack("<I", 0)
    bits = struct.pack("<HHH", 8, 8, 8)
    xres = struct.pack("<II", 72, 1)
    yres = struct.pack("<II", 72, 1)
    return header + ifd + bits + xres + yres + image_bytes


def _tiff_entry(tag: int, field_type: int, count: int, value: int) -> bytes:
    return struct.pack("<HHII", tag, field_type, count, value)


def encode_jpeg(surface: RasterSurface, quality: int = 75) -> bytes:
    """Encode a surface into baseline color JPEG bytes.

    Example:
        >>> surface = RasterSurface.create(1, 1, (0, 255, 0, 255))
        >>> encode_jpeg(surface)[:2] == b\"\\xFF\\xD8\"
        True
    """
    width = surface.width
    height = surface.height
    pixels = surface.pixels
    y_plane, cb_plane, cr_plane = _to_ycbcr_planes(pixels, width, height)
    qt_luma = _scale_quant_table(_LUMA_QTABLE, quality)
    qt_chroma = _scale_quant_table(_CHROMA_QTABLE, quality)
    y_blocks = _jpeg_blocks_from_plane(y_plane, width, height)
    cb_blocks = _jpeg_blocks_from_plane(cb_plane, width, height)
    cr_blocks = _jpeg_blocks_from_plane(cr_plane, width, height)
    data = _encode_entropy_color(y_blocks, cb_blocks, cr_blocks, qt_luma, qt_chroma)
    return _jpeg_file(width, height, qt_luma, qt_chroma, data)


def _to_ycbcr_planes(pixels: bytearray, width: int, height: int) -> tuple[list[int], list[int], list[int]]:
    y_plane: list[int] = []
    cb_plane: list[int] = []
    cr_plane: list[int] = []
    for y in range(height):
        row_offset = y * width * 4
        for x in range(width):
            idx = row_offset + x * 4
            r = pixels[idx]
            g = pixels[idx + 1]
            b = pixels[idx + 2]
            y_val = 0.299 * r + 0.587 * g + 0.114 * b
            cb_val = -0.168736 * r - 0.331264 * g + 0.5 * b + 128
            cr_val = 0.5 * r - 0.418688 * g - 0.081312 * b + 128
            y_plane.append(_clamp_byte(y_val))
            cb_plane.append(_clamp_byte(cb_val))
            cr_plane.append(_clamp_byte(cr_val))
    return y_plane, cb_plane, cr_plane


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _jpeg_blocks_from_plane(plane: list[int], width: int, height: int) -> list[list[int]]:
    blocks: list[list[int]] = []
    padded_width = (width + 7) // 8 * 8
    padded_height = (height + 7) // 8 * 8
    for by in range(0, padded_height, 8):
        for bx in range(0, padded_width, 8):
            block: list[int] = []
            for y in range(8):
                for x in range(8):
                    sx = min(width - 1, bx + x)
                    sy = min(height - 1, by + y)
                    block.append(plane[sy * width + sx] - 128)
            blocks.append(block)
    return blocks


def _encode_entropy_color(
    y_blocks: list[list[int]],
    cb_blocks: list[list[int]],
    cr_blocks: list[list[int]],
    qt_luma: list[list[int]],
    qt_chroma: list[list[int]],
) -> bytes:
    dc_luma = _build_huffman_table(_DC_LUMA_BITS, _DC_LUMA_VALUES)
    ac_luma = _build_huffman_table(_AC_LUMA_BITS, _AC_LUMA_VALUES)
    dc_chroma = _build_huffman_table(_DC_CHROMA_BITS, _DC_CHROMA_VALUES)
    ac_chroma = _build_huffman_table(_AC_CHROMA_BITS, _AC_CHROMA_VALUES)
    bit_writer = _BitWriter()
    prev_dc = [0, 0, 0]
    total_blocks = len(y_blocks)
    for idx in range(total_blocks):
        prev_dc[0] = _write_block(bit_writer, y_blocks[idx], qt_luma, dc_luma, ac_luma, prev_dc[0])
        prev_dc[1] = _write_block(bit_writer, cb_blocks[idx], qt_chroma, dc_chroma, ac_chroma, prev_dc[1])
        prev_dc[2] = _write_block(bit_writer, cr_blocks[idx], qt_chroma, dc_chroma, ac_chroma, prev_dc[2])
    return bit_writer.finish()


def _write_block(
    bit_writer: "_BitWriter",
    block: list[int],
    qt: list[list[int]],
    dc_table: dict[int, tuple[int, int]],
    ac_table: dict[int, tuple[int, int]],
    prev_dc: int,
) -> int:
    coeffs = _dct_quantize(block, qt)
    zigzag = [_ZIGZAG[i] for i in range(64)]
    ordered = [coeffs[i] for i in zigzag]
    dc_diff = ordered[0] - prev_dc
    prev_dc = ordered[0]
    size, bits = _magnitude_bits(dc_diff)
    code, length = dc_table[size]
    bit_writer.write(code, length)
    if size:
        bit_writer.write(bits, size)
    zero_run = 0
    for coeff in ordered[1:]:
        if coeff == 0:
            zero_run += 1
            if zero_run == 16:
                code, length = ac_table[0xF0]
                bit_writer.write(code, length)
                zero_run = 0
            continue
        while zero_run > 15:
            code, length = ac_table[0xF0]
            bit_writer.write(code, length)
            zero_run -= 16
        size, bits = _magnitude_bits(coeff)
        symbol = (zero_run << 4) | size
        code, length = ac_table[symbol]
        bit_writer.write(code, length)
        bit_writer.write(bits, size)
        zero_run = 0
    if zero_run:
        code, length = ac_table[0]
        bit_writer.write(code, length)
    return prev_dc


def _dct_quantize(block: list[int], qt: list[list[int]]) -> list[int]:
    coeffs = [0] * 64
    cos_table = _COS_TABLE
    for v in range(8):
        for u in range(8):
            total = 0.0
            for y in range(8):
                for x in range(8):
                    total += block[y * 8 + x] * cos_table[u][x] * cos_table[v][y]
            cu = 1.0 / math.sqrt(2) if u == 0 else 1.0
            cv = 1.0 / math.sqrt(2) if v == 0 else 1.0
            value = 0.25 * cu * cv * total
            q = qt[v][u]
            coeffs[v * 8 + u] = int(round(value / q))
    return coeffs


def _build_huffman_table(bits: list[int], values: list[int]) -> dict[int, tuple[int, int]]:
    table: dict[int, tuple[int, int]] = {}
    code = 0
    idx = 0
    for length, count in enumerate(bits, start=1):
        for _ in range(count):
            table[values[idx]] = (code, length)
            code += 1
            idx += 1
        code <<= 1
    return table


def _magnitude_bits(value: int) -> tuple[int, int]:
    if value == 0:
        return 0, 0
    abs_value = abs(value)
    size = abs_value.bit_length()
    if value < 0:
        value = (1 << size) + value - 1
    return size, value


def _scale_quant_table(table: list[list[int]], quality: int) -> list[list[int]]:
    quality = max(1, min(100, quality))
    if quality < 50:
        scale = 5000 / quality
    else:
        scale = 200 - quality * 2
    scaled: list[list[int]] = []
    for row in table:
        scaled_row = []
        for value in row:
            scaled_value = int((value * scale + 50) / 100)
            scaled_row.append(max(1, min(255, scaled_value)))
        scaled.append(scaled_row)
    return scaled


def _jpeg_file(width: int, height: int, qt_luma: list[list[int]], qt_chroma: list[list[int]], entropy: bytes) -> bytes:
    stream = bytearray()
    stream.extend(b"\xFF\xD8")
    stream.extend(_jpeg_app0())
    stream.extend(_jpeg_dqt(qt_luma, qt_chroma))
    stream.extend(_jpeg_sof0(width, height))
    stream.extend(_jpeg_dht())
    stream.extend(_jpeg_sos())
    stream.extend(entropy)
    stream.extend(b"\xFF\xD9")
    return bytes(stream)


def _jpeg_app0() -> bytes:
    payload = b"JFIF\x00" + bytes([1, 1, 0, 0, 1, 0, 1, 0, 0])
    return _jpeg_segment(0xE0, payload)


def _jpeg_dqt(qt_luma: list[list[int]], qt_chroma: list[list[int]]) -> bytes:
    zigzag = [_ZIGZAG[i] for i in range(64)]
    flat_luma = [qt_luma[index // 8][index % 8] for index in zigzag]
    flat_chroma = [qt_chroma[index // 8][index % 8] for index in zigzag]
    payload = bytes([0]) + bytes(flat_luma) + bytes([1]) + bytes(flat_chroma)
    return _jpeg_segment(0xDB, payload)


def _jpeg_sof0(width: int, height: int) -> bytes:
    payload = struct.pack(">BHHB", 8, height, width, 3) + bytes(
        [
            1, 0x11, 0,
            2, 0x11, 1,
            3, 0x11, 1,
        ]
    )
    return _jpeg_segment(0xC0, payload)


def _jpeg_dht() -> bytes:
    dc_luma = bytes([0x00]) + bytes(_DC_LUMA_BITS) + bytes(_DC_LUMA_VALUES)
    ac_luma = bytes([0x10]) + bytes(_AC_LUMA_BITS) + bytes(_AC_LUMA_VALUES)
    dc_chroma = bytes([0x01]) + bytes(_DC_CHROMA_BITS) + bytes(_DC_CHROMA_VALUES)
    ac_chroma = bytes([0x11]) + bytes(_AC_CHROMA_BITS) + bytes(_AC_CHROMA_VALUES)
    return _jpeg_segment(0xC4, dc_luma + ac_luma + dc_chroma + ac_chroma)


def _jpeg_sos() -> bytes:
    payload = bytes([3, 1, 0, 2, 0x11, 3, 0x11, 0, 0x3F, 0])
    return _jpeg_segment(0xDA, payload)


def _jpeg_segment(marker: int, payload: bytes) -> bytes:
    length = len(payload) + 2
    return b"\xFF" + bytes([marker]) + struct.pack(">H", length) + payload


class _BitWriter:
    def __init__(self) -> None:
        self._buffer = 0
        self._bits = 0
        self._output = bytearray()

    def write(self, value: int, length: int) -> None:
        self._buffer = (self._buffer << length) | value
        self._bits += length
        while self._bits >= 8:
            self._bits -= 8
            byte = (self._buffer >> self._bits) & 0xFF
            self._output.append(byte)
            if byte == 0xFF:
                self._output.append(0x00)
        self._buffer &= (1 << self._bits) - 1 if self._bits else 0

    def finish(self) -> bytes:
        if self._bits:
            self.write((1 << self._bits) - 1, self._bits)
        return bytes(self._output)


_COS_TABLE = [[math.cos((2 * x + 1) * u * math.pi / 16) for x in range(8)] for u in range(8)]

_LUMA_QTABLE = [
    [16, 11, 10, 16, 24, 40, 51, 61],
    [12, 12, 14, 19, 26, 58, 60, 55],
    [14, 13, 16, 24, 40, 57, 69, 56],
    [14, 17, 22, 29, 51, 87, 80, 62],
    [18, 22, 37, 56, 68, 109, 103, 77],
    [24, 35, 55, 64, 81, 104, 113, 92],
    [49, 64, 78, 87, 103, 121, 120, 101],
    [72, 92, 95, 98, 112, 100, 103, 99],
]

_CHROMA_QTABLE = [
    [17, 18, 24, 47, 99, 99, 99, 99],
    [18, 21, 26, 66, 99, 99, 99, 99],
    [24, 26, 56, 99, 99, 99, 99, 99],
    [47, 66, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
]

_ZIGZAG = [
    0,
    1,
    8,
    16,
    9,
    2,
    3,
    10,
    17,
    24,
    32,
    25,
    18,
    11,
    4,
    5,
    12,
    19,
    26,
    33,
    40,
    48,
    41,
    34,
    27,
    20,
    13,
    6,
    7,
    14,
    21,
    28,
    35,
    42,
    49,
    56,
    57,
    50,
    43,
    36,
    29,
    22,
    15,
    23,
    30,
    37,
    44,
    51,
    58,
    59,
    52,
    45,
    38,
    31,
    39,
    46,
    53,
    60,
    61,
    54,
    47,
    55,
    62,
    63,
]

_DC_LUMA_BITS = [0, 0, 0, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
_DC_LUMA_VALUES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

_AC_LUMA_BITS = [0, 0, 0, 0, 0, 0, 0, 162, 0, 0, 0, 0, 0, 0, 0, 0]
_AC_LUMA_VALUES = [
    0x01,
    0x02,
    0x03,
    0x00,
    0x04,
    0x11,
    0x05,
    0x12,
    0x21,
    0x31,
    0x41,
    0x06,
    0x13,
    0x51,
    0x61,
    0x07,
    0x22,
    0x71,
    0x14,
    0x32,
    0x81,
    0x91,
    0xA1,
    0x08,
    0x23,
    0x42,
    0xB1,
    0xC1,
    0x15,
    0x52,
    0xD1,
    0xF0,
    0x24,
    0x33,
    0x62,
    0x72,
    0x82,
    0x09,
    0x0A,
    0x16,
    0x17,
    0x18,
    0x19,
    0x1A,
    0x25,
    0x26,
    0x27,
    0x28,
    0x29,
    0x2A,
    0x34,
    0x35,
    0x36,
    0x37,
    0x38,
    0x39,
    0x3A,
    0x43,
    0x44,
    0x45,
    0x46,
    0x47,
    0x48,
    0x49,
    0x4A,
    0x53,
    0x54,
    0x55,
    0x56,
    0x57,
    0x58,
    0x59,
    0x5A,
    0x63,
    0x64,
    0x65,
    0x66,
    0x67,
    0x68,
    0x69,
    0x6A,
    0x73,
    0x74,
    0x75,
    0x76,
    0x77,
    0x78,
    0x79,
    0x7A,
    0x83,
    0x84,
    0x85,
    0x86,
    0x87,
    0x88,
    0x89,
    0x8A,
    0x92,
    0x93,
    0x94,
    0x95,
    0x96,
    0x97,
    0x98,
    0x99,
    0x9A,
    0xA2,
    0xA3,
    0xA4,
    0xA5,
    0xA6,
    0xA7,
    0xA8,
    0xA9,
    0xAA,
    0xB2,
    0xB3,
    0xB4,
    0xB5,
    0xB6,
    0xB7,
    0xB8,
    0xB9,
    0xBA,
    0xC2,
    0xC3,
    0xC4,
    0xC5,
    0xC6,
    0xC7,
    0xC8,
    0xC9,
    0xCA,
    0xD2,
    0xD3,
    0xD4,
    0xD5,
    0xD6,
    0xD7,
    0xD8,
    0xD9,
    0xDA,
    0xE1,
    0xE2,
    0xE3,
    0xE4,
    0xE5,
    0xE6,
    0xE7,
    0xE8,
    0xE9,
    0xEA,
    0xF1,
    0xF2,
    0xF3,
    0xF4,
    0xF5,
    0xF6,
    0xF7,
    0xF8,
    0xF9,
    0xFA,
]

_DC_CHROMA_BITS = [0, 0, 0, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
_DC_CHROMA_VALUES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

_AC_CHROMA_BITS = [0, 0, 0, 0, 0, 0, 0, 162, 0, 0, 0, 0, 0, 0, 0, 0]
_AC_CHROMA_VALUES = [
    0x01,
    0x02,
    0x03,
    0x00,
    0x04,
    0x11,
    0x05,
    0x12,
    0x21,
    0x31,
    0x41,
    0x06,
    0x13,
    0x51,
    0x61,
    0x07,
    0x22,
    0x71,
    0x14,
    0x32,
    0x81,
    0x91,
    0xA1,
    0x08,
    0x23,
    0x42,
    0xB1,
    0xC1,
    0x15,
    0x52,
    0xD1,
    0xF0,
    0x24,
    0x33,
    0x62,
    0x72,
    0x82,
    0x09,
    0x0A,
    0x16,
    0x17,
    0x18,
    0x19,
    0x1A,
    0x25,
    0x26,
    0x27,
    0x28,
    0x29,
    0x2A,
    0x34,
    0x35,
    0x36,
    0x37,
    0x38,
    0x39,
    0x3A,
    0x43,
    0x44,
    0x45,
    0x46,
    0x47,
    0x48,
    0x49,
    0x4A,
    0x53,
    0x54,
    0x55,
    0x56,
    0x57,
    0x58,
    0x59,
    0x5A,
    0x63,
    0x64,
    0x65,
    0x66,
    0x67,
    0x68,
    0x69,
    0x6A,
    0x73,
    0x74,
    0x75,
    0x76,
    0x77,
    0x78,
    0x79,
    0x7A,
    0x83,
    0x84,
    0x85,
    0x86,
    0x87,
    0x88,
    0x89,
    0x8A,
    0x92,
    0x93,
    0x94,
    0x95,
    0x96,
    0x97,
    0x98,
    0x99,
    0x9A,
    0xA2,
    0xA3,
    0xA4,
    0xA5,
    0xA6,
    0xA7,
    0xA8,
    0xA9,
    0xAA,
    0xB2,
    0xB3,
    0xB4,
    0xB5,
    0xB6,
    0xB7,
    0xB8,
    0xB9,
    0xBA,
    0xC2,
    0xC3,
    0xC4,
    0xC5,
    0xC6,
    0xC7,
    0xC8,
    0xC9,
    0xCA,
    0xD2,
    0xD3,
    0xD4,
    0xD5,
    0xD6,
    0xD7,
    0xD8,
    0xD9,
    0xDA,
    0xE1,
    0xE2,
    0xE3,
    0xE4,
    0xE5,
    0xE6,
    0xE7,
    0xE8,
    0xE9,
    0xEA,
    0xF1,
    0xF2,
    0xF3,
    0xF4,
    0xF5,
    0xF6,
    0xF7,
    0xF8,
    0xF9,
    0xFA,
]
