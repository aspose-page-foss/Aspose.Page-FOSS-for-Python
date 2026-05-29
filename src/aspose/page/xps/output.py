"""XPS conversion output helpers."""

from __future__ import annotations

from datetime import datetime
import uuid

from ..common.render_model import RenderImageResource, RenderModelBuilder
from ..common.render_model import RenderDocument, TextCommand
from ..image.raster_writer import RasterWriter
from ..image.skia_raster_writer import SkiaRasterWriter, skia_available
from ..pdf.writer import ImageResource, PdfMetadata, PdfWriter
from ..ps.fonts import FontResolver, parse_ttf_metrics
from ..ps.output import ImageSaveOptions, PdfSaveOptions
from ..ps.pdf_font_embed import build_embedded_font
from .document import XpsDocument
from .images import XpsImageStore
from .parser import XpsParser
from .render import XpsRenderer


def to_pdf(document: XpsDocument, options: PdfSaveOptions | None = None) -> bytes:
    """Convert an XPS document to PDF bytes."""
    opts = options or PdfSaveOptions()
    builder = RenderModelBuilder()
    image_store = XpsImageStore()
    renderer = XpsRenderer(builder, image_store)
    renderer.set_package(document.package)
    parser = XpsParser(document.package)
    for part in parser.fixed_page_parts():
        renderer.set_current_part(part)
        renderer.render_fixed_page(document.package.read(part))
    render_doc = builder.document()
    _attach_image_resources(render_doc, image_store)
    font_resolver = _build_xps_font_resolver(
        document.package,
        render_doc,
        additional_fonts_folder=opts.additional_fonts_folder,
    )
    metadata = _build_pdf_metadata()

    def image_provider(image_id: str) -> ImageResource:
        image = image_store.get(image_id)
        return ImageResource(
            data=image.data,
            width=image.width,
            height=image.height,
            color_space=image.color_space,
            bits_per_component=image.bits_per_component,
            filter=image.filter,
        )

    def font_provider(font_ref: str, used_codes: set[int]):
        return build_embedded_font(font_ref, used_codes, font_resolver)

    writer = PdfWriter(
        metadata,
        no_compression=opts.no_compression,
        image_provider=image_provider,
        font_provider=font_provider,
    )
    return writer.write(render_doc)


def to_image(document: XpsDocument, options: ImageSaveOptions) -> bytes:
    """Convert an XPS document to raster image bytes."""
    if not skia_available():
        raise RuntimeError("Skia rasterizer is required for XPS image conversion")
    if options.raster_writer is not None and not isinstance(options.raster_writer, SkiaRasterWriter):
        raise ValueError("XPS image conversion requires SkiaRasterWriter")

    builder = RenderModelBuilder()
    image_store = XpsImageStore()
    renderer = XpsRenderer(builder, image_store)
    renderer.set_package(document.package)
    parser = XpsParser(document.package)
    for part in parser.fixed_page_parts():
        renderer.set_current_part(part)
        renderer.render_fixed_page(document.package.read(part))
    render_doc = builder.document()
    _attach_image_resources(render_doc, image_store)
    options.font_resolver = _build_xps_font_resolver(
        document.package,
        render_doc,
        additional_fonts_folder=options.additional_fonts_folder,
    )
    writer: RasterWriter = options.raster_writer or SkiaRasterWriter()
    return writer.write(render_doc, options)


def _build_pdf_metadata() -> PdfMetadata:
    timestamp = "D:" + datetime.now().strftime("%Y%m%d%H%M%S")
    return PdfMetadata(
        title="",
        creator="",
        producer="Aspose.Page FOSS for Python",
        creation_date=timestamp,
        mod_date=timestamp,
        trapped=False,
    )


def _build_xps_font_resolver(
    package,
    render_doc: RenderDocument,
    additional_fonts_folder: str | None = None,
) -> FontResolver:
    resolver = FontResolver(additional_fonts_folder=additional_fonts_folder)
    for font_ref in _used_font_refs(render_doc):
        if not font_ref:
            continue
        part_name = _normalize_part_name(font_ref)
        if not package.has_part(part_name):
            continue
        data = package.read(part_name)
        if part_name.lower().endswith(".odttf"):
            data = _deobfuscate_xps_odttf(part_name, data)
        try:
            units_per_em, code_widths = parse_ttf_metrics(data)
        except Exception:
            continue
        resolver.register_embedded_type42(font_ref, data, units_per_em, code_widths)
    return resolver


def _attach_image_resources(render_doc: RenderDocument, image_store: XpsImageStore) -> None:
    for image_id, resource in image_store._images.items():
        render_doc.resources.images[image_id] = RenderImageResource(
            data=resource.data,
            width=resource.width,
            height=resource.height,
            color_space=resource.color_space,
            bits_per_component=resource.bits_per_component,
            filter=resource.filter,
        )


def _used_font_refs(render_doc: RenderDocument) -> set[str]:
    font_refs: set[str] = set()
    for page in render_doc.pages:
        for command in page.commands:
            if isinstance(command, TextCommand) and command.font_ref:
                font_refs.add(command.font_ref)
    return font_refs


def _normalize_part_name(value: str) -> str:
    if "#" in value:
        value = value.split("#", 1)[0]
    if "?" in value:
        value = value.split("?", 1)[0]
    if not value.startswith("/"):
        return f"/{value}"
    return value


def _deobfuscate_xps_odttf(part_name: str, data: bytes) -> bytes:
    """Decode XPS obfuscated OpenType fonts.

    XPS `.odttf` resources XOR the first 32 bytes using a key derived from
    the GUID in the font file name.
    """
    if len(data) < 32:
        return data
    key = _odttf_guid_key(part_name)
    if key is None:
        return data
    result = bytearray(data)
    for index in range(32):
        result[index] ^= key[index % 16]
    return bytes(result)


def _odttf_guid_key(part_name: str) -> bytes | None:
    base = part_name.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0]
    stem = stem.strip("{}")
    try:
        guid = uuid.UUID(stem)
    except ValueError:
        return None
    raw = guid.bytes
    # XPS obfuscation uses bytes in reverse GUID-byte order.
    return raw[::-1]
