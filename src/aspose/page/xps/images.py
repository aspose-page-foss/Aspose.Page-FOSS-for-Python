"""XPS image decoding and storage."""

from __future__ import annotations

from dataclasses import dataclass
import io
import struct
import zlib


@dataclass
class XpsImageResource:
    """Decoded image resource.

    Example:
        >>> img = XpsImageResource("img1", b"\\x00", 1, 1, 8, "DeviceRGB", None)
        >>> img.width
        1
    """
    image_id: str
    data: bytes
    width: int
    height: int
    bits_per_component: int
    color_space: str
    filter: str | None
    x_dpi: float = 96.0
    y_dpi: float = 96.0


class XpsImageStore:
    def __init__(self) -> None:
        self._images: dict[str, XpsImageResource] = {}
        self._counter = 1

    def register(self, resource: XpsImageResource) -> str:
        """Register an image resource and return its ID."""
        image_id = resource.image_id or f"ximg{self._counter}"
        self._counter += 1
        if image_id != resource.image_id:
            resource = XpsImageResource(
                image_id=image_id,
                data=resource.data,
                width=resource.width,
                height=resource.height,
                bits_per_component=resource.bits_per_component,
                color_space=resource.color_space,
                filter=resource.filter,
            )
        self._images[image_id] = resource
        return image_id

    def get(self, image_id: str) -> XpsImageResource:
        """Return a previously registered image resource."""
        if image_id not in self._images:
            raise ValueError(f"unknown image resource {image_id}")
        return self._images[image_id]


def decode_png(data: bytes) -> XpsImageResource:
    """Decode an 8-bit RGB/RGBA PNG into a raw image resource."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    width = height = 0
    bit_depth = color_type = None
    idat = bytearray()
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk_data = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10])
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
        line = bytearray(decompressed[idx:idx + stride])
        idx += stride
        _apply_png_filter(filter_type, line, prev, bytes_per_pixel)
        if color_type == 6:
            for i in range(0, len(line), 4):
                raw.extend(line[i:i + 3])
        else:
            raw.extend(line)
        prev = line
    return XpsImageResource(
        image_id="",
        data=bytes(raw),
        width=width,
        height=height,
        bits_per_component=8,
        color_space="DeviceRGB",
        filter=None,
        x_dpi=_png_dpi(data) or 96.0,
        y_dpi=_png_dpi(data, vertical=True) or 96.0,
    )


def decode_jpeg(data: bytes) -> XpsImageResource:
    """Decode a JPEG image into a DCTDecode image resource."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("invalid JPEG")
    offset = 2
    width = height = None
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            break
        marker = data[offset + 1]
        offset += 2
        if marker in (0xD8, 0xD9):
            continue
        length = struct.unpack(">H", data[offset:offset + 2])[0]
        if marker in (0xC0, 0xC2):
            height = struct.unpack(">H", data[offset + 3:offset + 5])[0]
            width = struct.unpack(">H", data[offset + 5:offset + 7])[0]
            break
        offset += length
    if width is None or height is None:
        raise ValueError("JPEG size not found")
    x_dpi, y_dpi = _jpeg_dpi(data)
    return XpsImageResource(
        image_id="",
        data=data,
        width=width,
        height=height,
        bits_per_component=8,
        color_space="DeviceRGB",
        filter="DCTDecode",
        x_dpi=x_dpi,
        y_dpi=y_dpi,
    )


def decode_tiff(data: bytes) -> XpsImageResource:
    """Decode a TIFF image into an RGB image resource."""
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on environment
        raise ValueError("TIFF decoding requires Pillow") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            rgb = image.convert("RGB")
            dpi_info = image.info.get("dpi")
            x_dpi = 96.0
            y_dpi = 96.0
            if isinstance(dpi_info, tuple) and len(dpi_info) >= 2:
                try:
                    x_dpi = float(dpi_info[0]) or 96.0
                    y_dpi = float(dpi_info[1]) or 96.0
                except Exception:
                    x_dpi = 96.0
                    y_dpi = 96.0
            return XpsImageResource(
                image_id="",
                data=rgb.tobytes(),
                width=rgb.width,
                height=rgb.height,
                bits_per_component=8,
                color_space="DeviceRGB",
                filter=None,
                x_dpi=x_dpi,
                y_dpi=y_dpi,
            )
    except Exception as exc:  # pragma: no cover - invalid data path
        raise ValueError("invalid TIFF") from exc


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


def _png_dpi(data: bytes, vertical: bool = False) -> float | None:
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk_data = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"pHYs" and len(chunk_data) >= 9:
            x_ppm = struct.unpack(">I", chunk_data[0:4])[0]
            y_ppm = struct.unpack(">I", chunk_data[4:8])[0]
            unit = chunk_data[8]
            if unit == 1:
                ppm = y_ppm if vertical else x_ppm
                if ppm > 0:
                    return ppm * 0.0254
            return None
        if chunk_type == b"IEND":
            break
    return None


def _jpeg_dpi(data: bytes) -> tuple[float, float]:
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            break
        marker = data[offset + 1]
        offset += 2
        if marker in (0xD8, 0xD9):
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack(">H", data[offset:offset + 2])[0]
        if length < 2 or offset + length > len(data):
            break
        if marker == 0xE0 and length >= 14:
            payload = data[offset + 2:offset + length]
            if payload.startswith(b"JFIF\x00") and len(payload) >= 12:
                units = payload[7]
                x_density = struct.unpack(">H", payload[8:10])[0]
                y_density = struct.unpack(">H", payload[10:12])[0]
                if x_density > 0 and y_density > 0:
                    if units == 1:  # dots per inch
                        return float(x_density), float(y_density)
                    if units == 2:  # dots per cm
                        return float(x_density) * 2.54, float(y_density) * 2.54
        offset += length
    return 96.0, 96.0
