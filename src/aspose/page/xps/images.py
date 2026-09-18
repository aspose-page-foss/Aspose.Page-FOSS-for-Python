"""XPS image decoding and storage."""

from __future__ import annotations

from dataclasses import dataclass
import io
import struct
import zlib

import numpy


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
    soft_mask: bytes | None = None
    source_format: str | None = None


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
                x_dpi=resource.x_dpi,
                y_dpi=resource.y_dpi,
                soft_mask=resource.soft_mask,
                source_format=resource.source_format,
            )
        self._images[image_id] = resource
        return image_id

    def get(self, image_id: str) -> XpsImageResource:
        """Return a previously registered image resource."""
        if image_id not in self._images:
            raise ValueError(f"unknown image resource {image_id}")
        return self._images[image_id]


def decode_png(data: bytes) -> XpsImageResource:
    """Decode a PNG into a raw RGB image resource with optional soft mask."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    width = height = 0
    bit_depth = color_type = None
    idat = bytearray()
    palette: bytes | None = None
    transparency: bytes | None = None
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
        elif chunk_type == b"PLTE":
            palette = bytes(chunk_data)
        elif chunk_type == b"tRNS":
            transparency = bytes(chunk_data)
        elif chunk_type == b"IEND":
            break
    if color_type not in (0, 2, 3, 6):
        raise ValueError("unsupported PNG format")
    if color_type == 0 and bit_depth not in (1, 2, 4, 8):
        raise ValueError("unsupported PNG format")
    if color_type in (2, 6) and bit_depth != 8:
        raise ValueError("unsupported PNG format")
    if color_type == 3 and bit_depth not in (1, 2, 4, 8):
        raise ValueError("unsupported PNG format")
    decompressed = zlib.decompress(bytes(idat))
    bytes_per_pixel = 3 if color_type == 2 else 4 if color_type == 6 else 1
    stride = _png_row_bytes(width, bit_depth, color_type)
    raw = bytearray()
    alpha = bytearray() if color_type in (0, 3, 6) and transparency is not None or color_type == 6 else None
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
                if alpha is not None:
                    alpha.extend(line[i + 3:i + 4])
        elif color_type == 2:
            raw.extend(line)
        elif color_type == 0:
            for sample in _unpack_png_samples(line, width, bit_depth):
                gray = _scale_png_sample(sample, bit_depth)
                raw.extend((gray, gray, gray))
                if alpha is not None:
                    alpha_value = 255
                    if transparency is not None:
                        transparent_sample = _png_grayscale_trns_sample(transparency)
                        if transparent_sample is not None and sample == transparent_sample:
                            alpha_value = 0
                    alpha.extend((alpha_value,))
        else:
            if palette is None:
                raise ValueError("palette PNG missing PLTE chunk")
            for sample in _unpack_png_samples(line, width, bit_depth):
                base = sample * 3
                if base + 3 > len(palette):
                    raise ValueError("palette PNG index out of range")
                raw.extend(palette[base:base + 3])
                alpha_value = 255
                if transparency is not None and sample < len(transparency):
                    alpha_value = transparency[sample]
                if alpha is not None:
                    alpha.extend((alpha_value,))
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
        soft_mask=bytes(alpha) if alpha is not None else None,
    )


def _png_row_bytes(width: int, bit_depth: int, color_type: int) -> int:
    if color_type in (0, 3):
        channels = 1
    elif color_type == 2:
        channels = 3
    elif color_type == 4:
        channels = 2
    else:
        channels = 4
    return (width * channels * bit_depth + 7) // 8


def _unpack_png_samples(line: bytes, width: int, bit_depth: int) -> list[int]:
    if bit_depth == 8:
        return list(line[:width])
    samples: list[int] = []
    mask = (1 << bit_depth) - 1
    for byte in line:
        bits_remaining = 8
        while bits_remaining >= bit_depth and len(samples) < width:
            bits_remaining -= bit_depth
            samples.append((byte >> bits_remaining) & mask)
        if len(samples) >= width:
            break
    return samples


def _scale_png_sample(sample: int, bit_depth: int) -> int:
    if bit_depth >= 8:
        return max(0, min(255, sample))
    max_sample = (1 << bit_depth) - 1
    if max_sample <= 0:
        return 0
    return max(0, min(255, int(round(sample * 255.0 / max_sample))))


def _png_grayscale_trns_sample(data: bytes) -> int | None:
    if len(data) < 2:
        return None
    return struct.unpack(">H", data[:2])[0]


def decode_jpeg(data: bytes) -> XpsImageResource:
    """Decode a JPEG image into a DCTDecode image resource."""
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
        length = struct.unpack(">H", data[offset:offset + 2])[0]
        if marker in (0xC0, 0xC2):
            height = struct.unpack(">H", data[offset + 3:offset + 5])[0]
            width = struct.unpack(">H", data[offset + 5:offset + 7])[0]
            components = data[offset + 7]
            break
        offset += length
    if width is None or height is None:
        raise ValueError("JPEG size not found")
    x_dpi, y_dpi = _jpeg_dpi(data)
    color_space = "DeviceGray" if components == 1 else "DeviceRGB"
    return XpsImageResource(
        image_id="",
        data=data,
        width=width,
        height=height,
        bits_per_component=8,
        color_space=color_space,
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


def decode_jpegxr(data: bytes) -> XpsImageResource:
    """Decode a JPEG-XR/WDP image into an RGB(A) image resource."""
    try:
        import imagecodecs  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on environment
        raise ValueError("JPEG-XR decoding requires imagecodecs") from exc
    try:
        array = imagecodecs.jpegxr_decode(data)
    except Exception as exc:  # pragma: no cover - invalid data path
        raise ValueError("invalid JPEG-XR") from exc
    if not isinstance(array, numpy.ndarray) or array.ndim not in (2, 3):
        raise ValueError("unsupported JPEG-XR format")
    if array.dtype != numpy.uint8:
        array = array.astype(numpy.uint8, copy=False)
    if array.ndim == 2:
        height, width = array.shape
        return XpsImageResource(
            image_id="",
            data=array.tobytes(),
            width=width,
            height=height,
            bits_per_component=8,
            color_space="DeviceGray",
            filter=None,
            source_format="JPEGXR",
        )
    height, width, channels = array.shape
    if channels == 3:
        return XpsImageResource(
            image_id="",
            data=array.tobytes(),
            width=width,
            height=height,
            bits_per_component=8,
            color_space="DeviceRGB",
            filter=None,
            source_format="JPEGXR",
        )
    if channels == 4:
        rgb = numpy.ascontiguousarray(array[:, :, :3])
        alpha = numpy.ascontiguousarray(array[:, :, 3])
        return XpsImageResource(
            image_id="",
            data=rgb.tobytes(),
            width=width,
            height=height,
            bits_per_component=8,
            color_space="DeviceRGB",
            filter=None,
            soft_mask=alpha.tobytes(),
            source_format="JPEGXR",
        )
    raise ValueError("unsupported JPEG-XR format")


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
