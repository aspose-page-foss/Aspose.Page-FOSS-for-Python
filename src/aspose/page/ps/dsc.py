"""DSC (Document Structuring Conventions) parsing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DscMetadata:
    """Container for DSC metadata extracted from PS/EPS comments.

    Example:
        >>> meta = DscMetadata(bounding_box=(0, 0, 10, 20))
        >>> meta.bounding_box
        (0, 0, 10, 20)
    """

    bounding_box: tuple[int, int, int, int] | None = None
    hires_bounding_box: tuple[float, float, float, float] | None = None
    crop_box: tuple[int, int, int, int] | None = None
    document_media_size: tuple[float, float] | None = None
    orientation: str | None = None
    page_transform: str | None = None
    viewing_orientation: str | None = None
    title: str | None = None
    creator: str | None = None
    creation_date: str | None = None
    language_level: int | None = None
    extensions: list[str] = None

    def __post_init__(self) -> None:
        if self.extensions is None:
            self.extensions = []


def _parse_int_tuple(value: str) -> tuple[int, int, int, int] | None:
    parts = value.strip().split()
    if len(parts) != 4:
        return None
    try:
        return tuple(int(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _parse_float_tuple(value: str) -> tuple[float, float, float, float] | None:
    parts = value.strip().split()
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def parse_dsc_comments(data: bytes) -> DscMetadata:
    """Parse DSC comments from a PS/EPS byte stream.

    Example:
        >>> parse_dsc_comments(b\"%%BoundingBox: 0 0 10 20\\n\").bounding_box
        (0, 0, 10, 20)
    """
    text = data.decode("latin-1", errors="ignore")
    metadata = DscMetadata()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("%%"):
            continue
        if line.startswith("%%BoundingBox:"):
            value = line.split(":", 1)[1].strip()
            if value.lower() == "atend":
                continue
            bbox = _parse_int_tuple(value)
            if bbox:
                metadata.bounding_box = bbox
        elif line.startswith("%%HiResBoundingBox:"):
            value = line.split(":", 1)[1].strip()
            if value.lower() == "atend":
                continue
            bbox = _parse_float_tuple(value)
            if bbox:
                metadata.hires_bounding_box = bbox
        elif line.startswith("%%CropBox:"):
            value = line.split(":", 1)[1].strip()
            crop = _parse_int_tuple(value)
            if crop:
                metadata.crop_box = crop
        elif line.startswith("%%DocumentMedia:"):
            value = line.split(":", 1)[1].strip()
            media_size = _parse_document_media(value)
            if media_size is not None:
                metadata.document_media_size = media_size
        elif line.startswith("%%Orientation:"):
            metadata.orientation = line.split(":", 1)[1].strip() or None
        elif line.startswith("%%PageTransform:"):
            metadata.page_transform = line.split(":", 1)[1].strip() or None
        elif line.startswith("%%ViewingOrientation:"):
            metadata.viewing_orientation = line.split(":", 1)[1].strip() or None
        elif line.startswith("%%Title:"):
            metadata.title = line.split(":", 1)[1].strip() or None
        elif line.startswith("%%Creator:"):
            metadata.creator = line.split(":", 1)[1].strip() or None
        elif line.startswith("%%CreationDate:"):
            metadata.creation_date = line.split(":", 1)[1].strip() or None
        elif line.startswith("%%LanguageLevel:"):
            value = line.split(":", 1)[1].strip()
            try:
                metadata.language_level = int(value)
            except ValueError:
                pass
        elif line.startswith("%%Extensions:"):
            value = line.split(":", 1)[1].strip()
            if value:
                metadata.extensions.extend(value.split())
    return metadata


def _parse_document_media(value: str) -> tuple[float, float] | None:
    parts = value.strip().split()
    if len(parts) >= 3:
        try:
            width = float(parts[1])
            height = float(parts[2])
            if width > 0 and height > 0:
                return (width, height)
        except ValueError:
            pass
    numeric: list[float] = []
    for part in parts:
        try:
            numeric.append(float(part))
        except ValueError:
            continue
    if len(numeric) >= 2 and numeric[0] > 0 and numeric[1] > 0:
        return (numeric[0], numeric[1])
    return None
