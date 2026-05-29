"""Page size derivation from DSC metadata."""

from __future__ import annotations

from .dsc import DscMetadata


_DEFAULT_PAGE_SIZE = (595.0, 842.0)


def page_size_from_dsc(dsc: DscMetadata | None) -> tuple[float, float]:
    """Derive page size from DSC metadata."""
    if dsc is None:
        return _DEFAULT_PAGE_SIZE
    width: float
    height: float
    if dsc.crop_box is not None:
        width = float(dsc.crop_box[2] - dsc.crop_box[0])
        height = float(dsc.crop_box[3] - dsc.crop_box[1])
    elif dsc.document_media_size is not None:
        width, height = dsc.document_media_size
    else:
        bbox = dsc.hires_bounding_box or dsc.bounding_box
        if bbox is None:
            return _DEFAULT_PAGE_SIZE
        width = float(bbox[2] - bbox[0])
        height = float(bbox[3] - bbox[1])
    if width <= 0 or height <= 0:
        return _DEFAULT_PAGE_SIZE
    orientation = (dsc.orientation or "").strip().lower()
    if orientation == "landscape":
        return (height, width)
    return (width, height)
