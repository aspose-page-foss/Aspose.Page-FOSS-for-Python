"""XPS conversion output helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import tempfile
from xml.etree import ElementTree as ET
import uuid

from ..common.render_model import RenderImageResource, RenderModelBuilder
from ..common.render_model import RenderDocument, RenderPage, TextCommand, ImageCommand
from ..image.raster_writer import RasterWriter
from ..image.skia_raster_writer import SkiaRasterWriter, _page_pixel_size, skia_available
from ..pdf.writer import ImageResource, PdfMetadata, PdfWriter
from ..ps.fonts import FontResolver, parse_ttf_metrics
from ..ps.output import ImageSaveOptions, PdfSaveOptions
from ..ps.pdf_font_embed import build_embedded_font
from .document import XpsDocument
from .images import XpsImageStore
from .parser import XpsParser
from .print_tickets import read_print_tickets, PrintTicketScope
from .relationships import read_rels
from .render import XpsRenderer


def to_pdf(
    document: XpsDocument,
    options: PdfSaveOptions | None = None,
    max_pages: int | None = None,
) -> bytes:
    """Convert an XPS document to PDF bytes."""
    opts = options or PdfSaveOptions()
    builder = RenderModelBuilder()
    image_store = XpsImageStore()
    renderer = XpsRenderer(
        builder,
        image_store,
        media_fit_size=None,
        rasterize_solid_strokes=True,
    )
    renderer.set_package(document.package)
    parser = XpsParser(document.package)
    media_fit_sizes = _media_fit_sizes_by_part(document)
    for part in _fixed_page_parts(parser, max_pages):
        renderer.set_current_part(part)
        renderer.set_media_fit_size(media_fit_sizes.get(part))
        renderer.render_fixed_page(document.package.read(part))
    render_doc = builder.document()
    _quantize_xps_pdf_page_sizes(render_doc)
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
            soft_mask=image.soft_mask,
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


def to_image(
    document: XpsDocument,
    options: ImageSaveOptions,
    max_pages: int | None = None,
) -> bytes:
    pages = to_images(document, options, max_pages=max_pages)
    if not pages:
        raise ValueError("document has no pages")
    return pages[0]


def to_images(
    document: XpsDocument,
    options: ImageSaveOptions,
    max_pages: int | None = None,
) -> list[bytes]:
    """Convert an XPS document to raster image bytes."""
    if not skia_available():
        raise RuntimeError("Skia rasterizer is required for XPS image conversion")
    if options.raster_writer is not None and not isinstance(options.raster_writer, SkiaRasterWriter):
        raise ValueError("XPS image conversion requires SkiaRasterWriter")

    render_doc, image_store = _build_xps_render_document(document, max_pages=max_pages)
    _attach_image_resources(render_doc, image_store)
    options.opaque_background = True
    options.preserve_fractional_page_size = True
    options.font_resolver = _build_xps_font_resolver(
        document.package,
        render_doc,
        additional_fonts_folder=options.additional_fonts_folder,
    )
    writer: RasterWriter = options.raster_writer or SkiaRasterWriter()
    font_resolver = options.font_resolver
    outputs: list[bytes] = []
    for page in render_doc.pages:
        page_doc = RenderDocument(pages=[page], resources=render_doc.resources)
        fallback = _rasterize_page_via_pdf(
            page_doc,
            image_store,
            font_resolver,
            dpi=options.dpi,
            expected_size=_page_pixel_size(
                page.width,
                page.height,
                options.dpi / 72.0,
                preserve_fractional=True,
            ),
        ) if (
            _page_requires_pdf_raster_fallback(page)
            or _page_has_jpegxr_image(page, image_store)
            or _page_has_many_jpeg_images(page, image_store)
            or _page_has_very_large_image(page, image_store)
        ) else None
        outputs.append(fallback if fallback is not None else writer.write(page_doc, options))
    return outputs


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


def _build_xps_render_document(
    document: XpsDocument,
    max_pages: int | None = None,
) -> tuple[RenderDocument, XpsImageStore]:
    builder = RenderModelBuilder()
    image_store = XpsImageStore()
    renderer = XpsRenderer(builder, image_store, media_fit_size=None)
    renderer.set_package(document.package)
    parser = XpsParser(document.package)
    media_fit_sizes = _media_fit_sizes_by_part(document)
    for part in _fixed_page_parts(parser, max_pages):
        renderer.set_current_part(part)
        renderer.set_media_fit_size(media_fit_sizes.get(part))
        renderer.render_fixed_page(document.package.read(part))
    return builder.document(), image_store


def _fixed_page_parts(parser: XpsParser, max_pages: int | None = None) -> list[str]:
    parts = parser.fixed_page_parts()
    if max_pages is not None:
        return parts[:max_pages]
    return parts


def _media_fit_sizes_by_part(document: XpsDocument) -> dict[str, tuple[float, float] | None]:
    tickets = read_print_tickets(document.package)
    default_size: tuple[float, float] | None = None
    page_sizes: dict[str, tuple[float, float] | None] = {}
    for ticket in tickets:
        size = _print_ticket_media_size_points(ticket.xml)
        if size is None:
            continue
        if ticket.scope == PrintTicketScope.JOB:
            default_size = size
    for part in XpsParser(document.package).fixed_page_parts():
        ticket_xml = _page_print_ticket_xml(document.package, part)
        if ticket_xml is None:
            continue
        size = _print_ticket_media_size_points(ticket_xml)
        if size is not None:
            page_sizes[part] = size
    if not page_sizes and default_size is None:
        return {}
    result: dict[str, tuple[float, float] | None] = {}
    for part in XpsParser(document.package).fixed_page_parts():
        result[part] = page_sizes.get(part, default_size)
    return result


def _job_media_size_points(document: XpsDocument) -> tuple[float, float] | None:
    tickets = read_print_tickets(document.package)
    for ticket in tickets:
        if ticket.scope != PrintTicketScope.JOB:
            continue
        size = _print_ticket_media_size_points(ticket.xml)
        if size is not None:
            return size
    return None


def _print_ticket_media_size_points(xml: str) -> tuple[float, float] | None:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    parameter_values: dict[str, float] = {}
    for parameter in root.findall('.//{*}ParameterInit'):
        name = parameter.get('name') or ''
        value = parameter.find('{*}Value')
        if value is None or value.text is None:
            continue
        try:
            parameter_values[name] = float(value.text)
        except ValueError:
            continue
    landscape = False
    width_um = None
    height_um = None
    for feature in root.findall('.//{*}Feature'):
        name = feature.get('name') or ''
        if name.endswith('PageOrientation'):
            option = feature.find('{*}Option')
            if option is not None:
                option_name = option.get('name') or ''
                landscape = option_name.endswith('Landscape')
            try:
                continue
            except Exception:
                continue
        if not name.endswith('PageMediaSize'):
            continue
        option = feature.find('{*}Option')
        if option is None:
            continue
        for scored in option.findall('{*}ScoredProperty'):
            scored_name = scored.get('name') or ''
            parsed = None
            value = scored.find('{*}Value')
            if value is not None and value.text is not None:
                try:
                    parsed = float(value.text)
                except ValueError:
                    parsed = None
            if parsed is None:
                ref = scored.find('{*}ParameterRef')
                if ref is not None:
                    parsed = parameter_values.get(ref.get('name') or '')
            if parsed is None:
                continue
            if scored_name.endswith('MediaSizeWidth'):
                width_um = parsed
            elif scored_name.endswith('MediaSizeHeight'):
                height_um = parsed
    if width_um and height_um:
        width_pt = (width_um / 25400.0) * 72.0
        height_pt = (height_um / 25400.0) * 72.0
        if landscape and height_pt > width_pt:
            width_pt, height_pt = height_pt, width_pt
        return (width_pt, height_pt)
    return None


def _page_print_ticket_xml(package, page_part: str) -> str | None:
    for rel in read_rels(package, page_part):
        if rel.type != "http://schemas.microsoft.com/xps/2005/06/printticket":
            continue
        ticket_part = _resolve_related_part(page_part, rel.target)
        if not package.has_part(ticket_part):
            continue
        data = package.read(ticket_part)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1", errors="ignore")
    return None


def _resolve_related_part(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target
    base = base_part.rsplit("/", 1)[0]
    if base == "":
        return "/" + target
    return f"{base}/{target}"


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
            soft_mask=resource.soft_mask,
        )


def _page_requires_pdf_raster_fallback(page: RenderPage) -> bool:
    total_text = 0
    gid_text = 0
    gid_rotated = 0
    for command in page.commands:
        if not isinstance(command, TextCommand):
            continue
        total_text += 1
        if "#gid=" not in command.font_ref and "#gmap=" not in command.font_ref:
            continue
        gid_text += 1
        if abs(command.matrix.b) > 1.0e-6 or abs(command.matrix.c) > 1.0e-6:
            gid_rotated += 1
    if gid_rotated > 0:
        return True
    # Some XPS pages are emitted almost entirely as one-glyph explicit gid runs
    # with horizontal transforms. Rasterizing those pages through the PDF path
    # avoids corrupted embedded-font outlines while keeping the fallback narrow.
    return total_text > 0 and gid_text == total_text and gid_text >= 500


def _page_has_jpegxr_image(page: RenderPage, image_store: XpsImageStore) -> bool:
    for command in page.commands:
        if not isinstance(command, ImageCommand):
            continue
        try:
            image = image_store.get(command.image_id)
        except Exception:
            continue
        if getattr(image, "source_format", None) == "JPEGXR":
            return True
    return False


def _page_has_many_jpeg_images(page: RenderPage, image_store: XpsImageStore) -> bool:
    jpeg_images = 0
    for command in page.commands:
        if not isinstance(command, ImageCommand):
            continue
        try:
            image = image_store.get(command.image_id)
        except Exception:
            continue
        if image.filter == "DCTDecode":
            jpeg_images += 1
            if jpeg_images >= 20:
                return True
    return False


def _page_has_very_large_image(page: RenderPage, image_store: XpsImageStore) -> bool:
    for command in page.commands:
        if not isinstance(command, ImageCommand):
            continue
        try:
            image = image_store.get(command.image_id)
        except Exception:
            continue
        if image.width * image.height >= 3_000_000:
            return True
    return False


def _rasterize_page_via_pdf(
    render_doc: RenderDocument,
    image_store: XpsImageStore,
    font_resolver: FontResolver,
    dpi: int,
    expected_size: tuple[int, int],
) -> bytes | None:
    if shutil.which("pdftoppm") is None:
        return None
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
            soft_mask=image.soft_mask,
        )

    def font_provider(font_ref: str, used_codes: set[int]):
        return build_embedded_font(font_ref, used_codes, font_resolver)

    writer = PdfWriter(
        metadata,
        image_provider=image_provider,
        font_provider=font_provider,
    )
    pdf_bytes = writer.write(render_doc)
    with tempfile.TemporaryDirectory(prefix="xps-page-pdf-") as tmpdir:
        pdf_path = Path(tmpdir) / "page.pdf"
        out_prefix = Path(tmpdir) / "page"
        pdf_path.write_bytes(pdf_bytes)
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-singlefile",
                    "-r",
                    str(dpi),
                    "-scale-to-x",
                    str(expected_size[0]),
                    "-scale-to-y",
                    str(expected_size[1]),
                    str(pdf_path),
                    str(out_prefix),
                ],
                check=True,
                capture_output=True,
            )
        except Exception:
            return None
        png_path = out_prefix.with_suffix(".png")
        if not png_path.exists():
            return None
        return png_path.read_bytes()


def _quantize_xps_pdf_page_sizes(render_doc: RenderDocument) -> None:
    for page in render_doc.pages:
        page.width = _nearest_half_point(page.width)
        page.height = _nearest_half_point(page.height)


def _nearest_half_point(value: float) -> float:
    return round(value * 2.0) / 2.0


def _used_font_refs(render_doc: RenderDocument) -> set[str]:
    font_refs: set[str] = set()
    for page in render_doc.pages:
        for command in page.commands:
            if isinstance(command, TextCommand) and command.font_ref:
                font_refs.add(command.font_ref)
    for pattern in render_doc.resources.patterns.values():
        commands = getattr(pattern, "commands", None)
        if not commands:
            continue
        for command in commands:
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
