"""Image to EPS conversion helpers."""

from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib



@dataclass
class ImageInfo:
    """Decoded raster image data."""

    width: int
    height: int
    bits_per_component: int
    color_space: str
    pixels: bytes


def decode_png(data: bytes) -> ImageInfo:
    """Decode a PNG image into raw RGB pixels."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    width = height = 0
    bit_depth = color_type = None
    idat = bytearray()
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10]
            )
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    if bit_depth != 8 or color_type not in (2, 6):
        raise ValueError("unsupported PNG format")
    decompressed = zlib.decompress(bytes(idat))
    bytes_per_pixel = 3 if color_type == 2 else 4
    stride = width * bytes_per_pixel
    raw = bytearray()
    idx = 0
    prev = bytearray(stride)
    for _ in range(height):
        filter_type = decompressed[idx]
        idx += 1
        line = bytearray(decompressed[idx : idx + stride])
        idx += stride
        _apply_png_filter(filter_type, line, prev, bytes_per_pixel)
        if color_type == 6:
            for i in range(0, len(line), 4):
                raw.extend(line[i : i + 3])
        else:
            raw.extend(line)
        prev = line
    return ImageInfo(
        width=width,
        height=height,
        bits_per_component=8,
        color_space="DeviceRGB",
        pixels=bytes(raw),
    )


def decode_jpeg(data: bytes) -> ImageInfo:
    """Decode JPEG header and return encoded bytes for EPS embedding."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("invalid JPEG")
    offset = 2
    width = height = components = None
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            break
        marker = data[offset + 1]
        offset += 2
        if marker in (0xD8, 0xD9):
            continue
        length = struct.unpack(">H", data[offset : offset + 2])[0]
        if marker in (0xC0, 0xC2):
            height = struct.unpack(">H", data[offset + 3 : offset + 5])[0]
            width = struct.unpack(">H", data[offset + 5 : offset + 7])[0]
            components = data[offset + 7]
            break
        offset += length
    if width is None or height is None:
        raise ValueError("JPEG size not found")
    color_space = "DeviceRGB" if (components or 0) >= 3 else "DeviceGray"
    return ImageInfo(
        width=width,
        height=height,
        bits_per_component=8,
        color_space=color_space,
        pixels=data,
    )


def decode_bmp(data: bytes) -> ImageInfo:
    """Decode a 24-bit BMP image into raw RGB pixels."""
    if not data.startswith(b"BM"):
        raise ValueError("invalid BMP")
    offset = struct.unpack("<I", data[10:14])[0]
    header_size = struct.unpack("<I", data[14:18])[0]
    if header_size < 40:
        raise ValueError("unsupported BMP header")
    width = struct.unpack("<i", data[18:22])[0]
    height = struct.unpack("<i", data[22:26])[0]
    planes = struct.unpack("<H", data[26:28])[0]
    bpp = struct.unpack("<H", data[28:30])[0]
    compression = struct.unpack("<I", data[30:34])[0]
    if planes != 1 or compression != 0:
        raise ValueError("unsupported BMP format")
    abs_height = abs(height)
    rows = []
    if bpp == 24:
        row_size = ((width * 3 + 3) // 4) * 4
        for row_index in range(abs_height):
            start = offset + row_index * row_size
            row = data[start : start + width * 3]
            rgb = bytearray()
            for i in range(0, len(row), 3):
                b, g, r = row[i : i + 3]
                rgb.extend([r, g, b])
            rows.append(bytes(rgb))
        color_space = "DeviceRGB"
        bits_per_component = 8
    elif bpp == 1:
        palette_offset = 14 + header_size
        palette = data[palette_offset : palette_offset + 8]
        if len(palette) < 8:
            raise ValueError("invalid BMP palette")
        gray_map = []
        for index in range(2):
            b, g, r, _ = palette[index * 4 : index * 4 + 4]
            gray_map.append((r + g + b) // 3)
        row_size = ((width * bpp + 31) // 32) * 4
        for row_index in range(abs_height):
            start = offset + row_index * row_size
            row = data[start : start + row_size]
            gray_row = bytearray()
            for col in range(width):
                byte = row[col // 8]
                bit = (byte >> (7 - (col % 8))) & 1
                gray_row.append(gray_map[bit])
            rows.append(bytes(gray_row))
        color_space = "DeviceGray"
        bits_per_component = 8
    else:
        raise ValueError("unsupported BMP format")
    if height > 0:
        rows.reverse()
    raw = b"".join(rows)
    return ImageInfo(
        width=width,
        height=abs_height,
        bits_per_component=bits_per_component,
        color_space=color_space,
        pixels=raw,
    )


def decode_tiff(data: bytes) -> ImageInfo:
    """Decode uncompressed or PackBits TIFF into raw pixels."""
    endian = data[:2]
    if endian == b"II":
        order = "<"
    elif endian == b"MM":
        order = ">"
    else:
        raise ValueError("invalid TIFF header")
    if struct.unpack(order + "H", data[2:4])[0] != 42:
        raise ValueError("invalid TIFF marker")
    ifd_offset = struct.unpack(order + "I", data[4:8])[0]
    if ifd_offset >= len(data):
        raise ValueError("invalid TIFF offset")
    tags = _read_ifd(data, ifd_offset, order)
    width = tags.get(256)
    height = tags.get(257)
    bits = tags.get(258, 8)
    compression = tags.get(259, 1)
    photometric = tags.get(262, 2)
    samples_per_pixel = tags.get(277, 1)
    planar = tags.get(284, 1)
    strip_offsets = tags.get(273)
    strip_counts = tags.get(279)
    if width is None or height is None or strip_offsets is None or strip_counts is None:
        raise ValueError("missing TIFF fields")
    if planar != 1:
        raise ValueError("unsupported planar TIFF")
    if isinstance(bits, list):
        bits_per_component = bits[0]
    else:
        bits_per_component = bits
    if bits_per_component != 8:
        raise ValueError("unsupported TIFF bits per sample")
    offsets = strip_offsets if isinstance(strip_offsets, list) else [strip_offsets]
    counts = strip_counts if isinstance(strip_counts, list) else [strip_counts]
    raw = bytearray()
    for offset, count in zip(offsets, counts):
        chunk = data[offset : offset + count]
        if compression == 1:
            raw.extend(chunk)
        elif compression == 32773:
            raw.extend(_packbits_decode(chunk))
        elif compression == 5:
            raw.extend(_tiff_lzw_decode(chunk))
        else:
            raise ValueError("unsupported TIFF compression")
    expected = width * height * samples_per_pixel
    if len(raw) < expected:
        raise ValueError("TIFF data length mismatch")
    pixels = raw[:expected]
    if samples_per_pixel == 4:
        rgb = bytearray()
        for i in range(0, len(pixels), 4):
            rgb.extend(pixels[i : i + 3])
        pixels = bytes(rgb)
        samples_per_pixel = 3
    if photometric == 0 and samples_per_pixel == 1:
        pixels = bytes(255 - b for b in pixels)
    color_space = "DeviceRGB" if samples_per_pixel >= 3 else "DeviceGray"
    return ImageInfo(
        width=width,
        height=height,
        bits_per_component=bits_per_component,
        color_space=color_space,
        pixels=bytes(pixels),
    )


def image_to_eps(image: ImageInfo, bbox: tuple[int, int, int, int] | None = None) -> bytes:
    """Serialize ImageInfo into EPS bytes."""
    img_w = image.width
    img_h = image.height
    if img_w <= 0 or img_h <= 0:
        raise ValueError("invalid image dimensions")
    if bbox is None:
        bbox = (0, 0, img_w, img_h)
    bbox_w = bbox[2] - bbox[0]
    bbox_h = bbox[3] - bbox[1]
    if bbox_w <= 0 or bbox_h <= 0:
        raise ValueError("invalid bounding box")
    components = 1 if image.color_space == "DeviceGray" else 3
    expected = img_w * img_h * components * (image.bits_per_component // 8)
    use_dct = False
    if len(image.pixels) != expected:
        if image.pixels.startswith(b"\xff\xd8"):
            use_dct = True
        else:
            raise ValueError("image data length mismatch")
    scale_x = bbox_w / img_w
    scale_y = bbox_h / img_h
    lines = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%BoundingBox: {bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}",
        "%%LanguageLevel: 3",
        "%%Pages: 1",
        "%%EndComments",
        "gsave",
        f"{_fmt(bbox[0])} {_fmt(bbox[1])} translate",
        f"{_fmt(scale_x)} {_fmt(scale_y)} scale",
    ]
    if image.color_space == "DeviceGray":
        lines.append("/DeviceGray setcolorspace")
    else:
        lines.append("/DeviceRGB setcolorspace")
    matrix = f"[{img_w} 0 0 -{img_h} 0 {img_h}]"
    if use_dct:
        source = "{currentfile /ASCIIHexDecode filter /DCTDecode filter}"
        pixel_data = image.pixels
    else:
        source = "{currentfile /ASCIIHexDecode filter}"
        pixel_data = image.pixels
    if components == 1:
        lines.append(f"{img_w} {img_h} {image.bits_per_component} {matrix} {source} image")
    else:
        lines.append(
            f"{img_w} {img_h} {image.bits_per_component} {matrix} {source} false {components} colorimage"
        )
    lines.extend(_wrap_hex(pixel_data))
    lines.append("grestore")
    lines.append("%%EOF")
    return ("\n".join(lines) + "\n").encode("latin-1")


def convert_file(path: str, bbox: tuple[int, int, int, int] | None = None) -> bytes:
    """Convert an image file to EPS bytes."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        info = decode_png(data)
    elif data.startswith(b"\xff\xd8"):
        info = decode_jpeg(data)
    elif data.startswith(b"BM"):
        info = decode_bmp(data)
    elif data.startswith(b"II") or data.startswith(b"MM"):
        info = decode_tiff(data)
    else:
        raise ValueError("unsupported image format")
    return image_to_eps(info, bbox=bbox)


def _wrap_hex(data: bytes, width: int = 64) -> list[str]:
    hex_text = data.hex()
    hex_text += ">"
    return [hex_text[i : i + width] for i in range(0, len(hex_text), width)]


def _read_ifd(data: bytes, offset: int, order: str) -> dict[int, object]:
    tags: dict[int, object] = {}
    count = struct.unpack(order + "H", data[offset : offset + 2])[0]
    cursor = offset + 2
    for _ in range(count):
        tag, dtype, items, value = struct.unpack(order + "HHII", data[cursor : cursor + 12])
        cursor += 12
        tags[tag] = _read_ifd_value(data, order, dtype, items, value)
    return tags


def _read_ifd_value(data: bytes, order: str, dtype: int, count: int, value: int) -> object:
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}
    size = sizes.get(dtype)
    if size is None:
        raise ValueError("unsupported TIFF field type")
    total = size * count
    if total <= 4:
        raw = value.to_bytes(4, "little" if order == "<" else "big")[:total]
    else:
        raw = data[value : value + total]
    if dtype == 1:
        items = list(raw)
    elif dtype == 2:
        return raw.rstrip(b"\x00").decode("latin-1", errors="ignore")
    elif dtype == 3:
        items = list(struct.unpack(order + f"{count}H", raw))
    elif dtype == 5:
        items = []
        for idx in range(count):
            start = idx * 8
            num, den = struct.unpack(order + "II", raw[start : start + 8])
            items.append(0.0 if den == 0 else num / den)
    else:
        items = list(struct.unpack(order + f"{count}I", raw))
    if count == 1:
        return items[0]
    return items


def _packbits_decode(data: bytes) -> bytes:
    output = bytearray()
    index = 0
    length = len(data)
    while index < length:
        control = struct.unpack("b", data[index : index + 1])[0]
        index += 1
        if control >= 0:
            count = control + 1
            output.extend(data[index : index + count])
            index += count
        elif control >= -127:
            count = 1 - control
            if index >= length:
                break
            output.extend(data[index : index + 1] * count)
            index += 1
    return bytes(output)


def _tiff_lzw_decode(data: bytes) -> bytes:
    if not data:
        return b""
    reader = _MsbBitReader(data)
    clear_code = 256
    end_code = 257
    code_size = 9
    dictionary: list[bytes | None] = [None] * 4096
    for index in range(256):
        dictionary[index] = bytes([index])
    next_code = 258
    output = bytearray()
    prev: bytes | None = None
    while True:
        code = reader.read(code_size)
        if code is None:
            break
        if code == clear_code:
            dictionary = [None] * 4096
            for index in range(256):
                dictionary[index] = bytes([index])
            next_code = 258
            code_size = 9
            prev = None
            continue
        if code == end_code:
            break
        entry = dictionary[code] if 0 <= code < 4096 else None
        if entry is not None:
            pass
        elif prev is not None and code == next_code:
            entry = prev + prev[:1]
        else:
            raise ValueError("invalid TIFF LZW stream")
        output.extend(entry)
        if prev is not None and next_code < 4096:
            dictionary[next_code] = prev + entry[:1]
            next_code += 1
            if code_size < 12 and next_code == (1 << code_size) - 1:
                code_size += 1
        prev = entry
    return bytes(output)


class _MsbBitReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self._bit_buffer = 0
        self._bit_count = 0

    def read(self, bits: int) -> int | None:
        while self._bit_count < bits:
            if self._pos >= len(self._data):
                return None
            self._bit_buffer = (self._bit_buffer << 8) | self._data[self._pos]
            self._pos += 1
            self._bit_count += 8
        self._bit_count -= bits
        value = (self._bit_buffer >> self._bit_count) & ((1 << bits) - 1)
        self._bit_buffer &= (1 << self._bit_count) - 1
        return value


def _apply_png_filter(filter_type: int, line: bytearray, prev: bytearray, bpp: int) -> None:
    if filter_type == 0:
        return
    if filter_type == 1:
        for i in range(len(line)):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + left) & 0xFF
        return
    if filter_type == 2:
        for i in range(len(line)):
            line[i] = (line[i] + prev[i]) & 0xFF
        return
    if filter_type == 3:
        for i in range(len(line)):
            left = line[i - bpp] if i >= bpp else 0
            up = prev[i]
            line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
        return
    if filter_type == 4:
        for i in range(len(line)):
            left = line[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + _paeth(left, up, up_left)) & 0xFF
        return
    raise ValueError("unsupported PNG filter")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _fmt(value: float) -> str:
    if float(int(value)) == float(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")
