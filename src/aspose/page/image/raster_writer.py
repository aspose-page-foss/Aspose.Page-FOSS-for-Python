"""Raster output interface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..common.render_model import RenderDocument
import os
from .encoders import encode_bmp, encode_jpeg, encode_png, encode_tiff
from .raster_renderer import RasterRenderer
from ..ps.fonts import FontResolver
if TYPE_CHECKING:
    from ..ps.output import ImageSaveOptions


class RasterWriter(Protocol):
    def write(self, document: RenderDocument, options: "ImageSaveOptions") -> bytes:
        """Render a document to raster bytes."""


class RenderModelRasterWriter:
    def write(self, document: RenderDocument, options: "ImageSaveOptions") -> bytes:
        """Render a document to raster bytes using the render model.

        Example:
            >>> from aspose.page.common.render_model import RenderDocument, RenderPage
            >>> from aspose.page.ps.output import ImageSaveOptions
            >>> doc = RenderDocument(pages=[RenderPage(width=10, height=10)])
            >>> RenderModelRasterWriter().write(doc, ImageSaveOptions(format=\"png\", dpi=72))[:8]
            b\"\\x89PNG\\r\\n\\x1a\\n\"
        """
        if options.dpi <= 0:
            raise ValueError("dpi must be positive")
        fmt = options.format.lower()
        font_resolver = options.font_resolver or FontResolver(
            additional_fonts_folder=options.additional_fonts_folder
        )
        background = (0, 0, 0, 0) if fmt == "png" else (255, 255, 255, 255)
        renderer = RasterRenderer(
            dpi=options.dpi,
            font_resolver=font_resolver,
            background=background,
        )
        surface = renderer.render(document, page_index=0)
        if fmt == "png":
            return encode_png(surface, dpi=options.dpi)
        if fmt in ("jpeg", "jpg"):
            return encode_jpeg(surface)
        if fmt == "tiff":
            return encode_tiff(surface)
        if fmt == "bmp":
            return encode_bmp(surface)
        raise ValueError(f"unsupported format {options.format}")


class DefaultRasterWriter(RenderModelRasterWriter):
    pass


def select_raster_writer(options: "ImageSaveOptions") -> RasterWriter:
    """Choose the raster writer based on environment configuration."""
    if options.raster_writer is not None:
        return options.raster_writer
    mode = os.getenv("ASPOSE_PAGE_RASTERIZER", "").strip().lower()
    # Default to the fastest available rasterizer (Skia) unless explicitly disabled.
    if mode not in ("python", "render", "slow", "0", "false", "off"):
        from .skia_raster_writer import SkiaRasterWriter, skia_available

        if skia_available():
            return SkiaRasterWriter()
    return RenderModelRasterWriter()
