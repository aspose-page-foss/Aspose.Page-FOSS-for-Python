"""PS/EPS conversion output helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .document import PsDocument
from .base_ops import register_base_operators
from .fonts import FontResolver
from .image_ops import register_image_operators
from .images import PsImageStore
from .operators import OperatorRegistry
from .pipeline import PsConversionPipeline
from .interpreter import PsInterpreter
from .color_ops import register_color_operators
from .graphics_ops import register_core_graphics_operators
from .text_ops import register_text_operators
from .page_geometry import page_size_from_dsc
from ..common.render_model import (
    ClipCommand,
    ImageCommand,
    Matrix,
    Path,
    PathCommand,
    PathSegment,
    Point,
    RenderImageResource,
    RenderModelBuilder,
    RenderPage,
    TextCommand,
)
from .pdf_font_embed import build_embedded_font
from ..pdf.writer import PdfMetadata, PdfWriter, ImageResource
from ..image.raster_writer import DefaultRasterWriter, RasterWriter, RenderModelRasterWriter, select_raster_writer


@dataclass
class PdfSaveOptions:
    no_compression: bool = False
    additional_fonts_folder: str | None = None


@dataclass
class ImageSaveOptions:
    format: str
    dpi: int = 96
    raster_writer: RasterWriter | None = None
    additional_fonts_folder: str | None = None
    # Internal plumbing: reuse interpreter font resolver (with embedded Type42
    # registrations) during rasterization.
    font_resolver: FontResolver | None = None


def to_pdf(document: PsDocument, options: PdfSaveOptions | None = None) -> bytes:
    opts = options or PdfSaveOptions()
    builder = RenderModelBuilder()
    registry = OperatorRegistry()
    image_store = PsImageStore()
    font_resolver = FontResolver(additional_fonts_folder=opts.additional_fonts_folder)
    register_base_operators(registry)
    register_core_graphics_operators(registry, builder)
    register_color_operators(registry, builder)
    register_text_operators(registry, builder, font_resolver)
    register_image_operators(registry, builder, image_store)
    interpreter = PsInterpreter(registry)
    pipeline = PsConversionPipeline(
        interpreter,
        registry,
        builder,
        font_resolver=font_resolver,
        image_store=image_store,
    )
    render_doc = pipeline.build_render_model(document.as_bytes())
    _apply_viewing_orientation(render_doc, document.dsc)
    _ensure_non_empty_document(render_doc, document)
    metadata = build_pdf_metadata(document.dsc)

    def image_provider(image_id: str) -> ImageResource:
        image = image_store.get(image_id)
        return ImageResource(
            data=image.data,
            width=image.width,
            height=image.height,
            color_space=image.color_space,
            bits_per_component=image.bits_per_component,
            filter=image.filter,
            filter_params=image.filter_params,
            decode=image.decode,
            mask=image.mask,
            mask_polarity=image.mask_polarity,
        )

    def font_provider(font_name: str, used_codes: set[int]):
        return build_embedded_font(font_name, used_codes, font_resolver)

    writer = PdfWriter(
        metadata,
        no_compression=opts.no_compression,
        image_provider=image_provider,
        font_provider=font_provider,
    )
    return writer.write(render_doc)


def to_image(document: PsDocument, options: ImageSaveOptions) -> bytes:
    builder = RenderModelBuilder()
    registry = OperatorRegistry()
    image_store = PsImageStore()
    font_resolver = FontResolver(additional_fonts_folder=options.additional_fonts_folder)
    register_base_operators(registry)
    register_core_graphics_operators(registry, builder)
    register_color_operators(registry, builder)
    register_text_operators(registry, builder, font_resolver)
    register_image_operators(registry, builder, image_store)
    interpreter = PsInterpreter(registry)
    pipeline = PsConversionPipeline(
        interpreter,
        registry,
        builder,
        font_resolver=font_resolver,
        image_store=image_store,
    )
    render_doc = pipeline.build_render_model(document.as_bytes())
    _apply_viewing_orientation(render_doc, document.dsc)
    _ensure_non_empty_document(render_doc, document)
    for image_id, image in image_store.items():
        render_doc.resources.images[image_id] = RenderImageResource(
            data=image.data,
            width=image.width,
            height=image.height,
            color_space=image.color_space,
            bits_per_component=image.bits_per_component,
            filter=image.filter,
            filter_params=image.filter_params,
            decode=image.decode,
            mask=image.mask,
            mask_polarity=image.mask_polarity,
        )
    options.font_resolver = font_resolver
    writer = options.raster_writer or select_raster_writer(options)
    return writer.write(render_doc, options)


def build_pdf_metadata(dsc) -> PdfMetadata:
    title = dsc.title if dsc and dsc.title else ""
    creator = dsc.creator if dsc and dsc.creator else ""
    timestamp = _pdf_timestamp()
    return PdfMetadata(
        title=title,
        creator=creator,
        producer="Aspose.Page FOSS for Python",
        creation_date=timestamp,
        mod_date=timestamp,
        trapped=False,
    )


def _pdf_timestamp() -> str:
    return "D:" + datetime.now().strftime("%Y%m%d%H%M%S")


def _ensure_non_empty_document(render_doc, document: PsDocument) -> None:
    if render_doc.pages:
        return
    width, height = page_size_from_dsc(document.dsc)
    render_doc.pages.append(RenderPage(width=width, height=height))


def _apply_viewing_orientation(render_doc, dsc) -> None:
    if dsc is None:
        return
    raw = getattr(dsc, "viewing_orientation", None)
    if not raw:
        return
    parts = raw.split()
    if len(parts) != 4:
        return
    try:
        a, b, c, d = (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
    except ValueError:
        return
    # Common DSC orientation matrix used by PScript:
    # %%ViewingOrientation: 0 1 -1 0
    if not (abs(a) < 1e-9 and abs(b - 1.0) < 1e-9 and abs(c + 1.0) < 1e-9 and abs(d) < 1e-9):
        return
    for page in render_doc.pages:
        if page.width >= page.height:
            continue
        transform = (0.0, 1.0, 1.0, 0.0, 0.0, 0.0)
        page.commands = [_transform_command(command, transform) for command in page.commands]
        page.width, page.height = page.height, page.width


def _transform_command(command, matrix: tuple[float, float, float, float, float, float]):
    if isinstance(command, PathCommand):
        return PathCommand(
            path=_transform_path(command.path, matrix),
            stroke=command.stroke,
            fill=command.fill,
            fill_rule=command.fill_rule,
            stroke_paint=command.stroke_paint,
            overprint=command.overprint,
            fill_opacity=command.fill_opacity,
            stroke_opacity=command.stroke_opacity,
        )
    if isinstance(command, ClipCommand):
        return ClipCommand(path=_transform_path(command.path, matrix), fill_rule=command.fill_rule)
    if isinstance(command, TextCommand):
        return TextCommand(
            text=command.text,
            font_ref=command.font_ref,
            font_size=command.font_size,
            matrix=_mul_matrix(matrix, _matrix_to_tuple(command.matrix)),
            fill=command.fill,
            fill_opacity=command.fill_opacity,
        )
    if isinstance(command, ImageCommand):
        return ImageCommand(
            image_id=command.image_id,
            width=command.width,
            height=command.height,
            matrix=_mul_matrix(matrix, _matrix_to_tuple(command.matrix)),
            mask=command.mask,
            mask_paint=command.mask_paint,
            opacity=command.opacity,
        )
    return command


def _transform_path(path: Path, matrix: tuple[float, float, float, float, float, float]) -> Path:
    segments: list[PathSegment] = []
    for segment in path.segments:
        points = [Point(*_apply_matrix(matrix, point.x, point.y)) for point in segment.points]
        segments.append(PathSegment(segment.kind, points))
    return Path(segments)


def _matrix_to_tuple(matrix: Matrix) -> tuple[float, float, float, float, float, float]:
    return (matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f)


def _mul_matrix(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
) -> Matrix:
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return Matrix(
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _apply_matrix(
    matrix: tuple[float, float, float, float, float, float],
    x: float,
    y: float,
) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)
