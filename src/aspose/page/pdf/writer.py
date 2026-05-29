"""PDF 1.4 writer for render model output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import zlib

from aspose.page.common.color_resources import (
    AxialShading,
    CieBasedColorSpace,
    ColorSpace,
    ColorSpacePaint,
    DeviceColorSpace,
    DeviceNColorSpace,
    ExponentialFunction,
    Function,
    IndexedColorSpace,
    Pattern,
    PatternColorSpace,
    PatternPaint,
    RadialShading,
    SampledFunction,
    SeparationColorSpace,
    ShadingPattern,
    StitchingFunction,
    TilingPattern,
)
from aspose.page.common.render_model import (
    ClipCommand,
    ImageCommand,
    Matrix,
    Paint,
    Path,
    PathCommand,
    PathSegment,
    RenderDocument,
    RenderPage,
    StateRestoreCommand,
    StateSaveCommand,
    StrokeStyle,
    TextCommand,
)
from aspose.page.ps.encodings import STANDARD_ENCODING, SYMBOL_ENCODING, ZAPF_DINGBATS_ENCODING
from aspose.page.pdf.fonts import PdfEmbeddedFont
from aspose.page.pdf.utils import escape_pdf_string, format_matrix, format_rect


_STANDARD_FONTS = {
    "Courier",
    "Courier-Bold",
    "Courier-Oblique",
    "Courier-BoldOblique",
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-Oblique",
    "Helvetica-BoldOblique",
    "Times-Roman",
    "Times-Bold",
    "Times-Italic",
    "Times-BoldItalic",
    "Symbol",
    "ZapfDingbats",
}

_GLYPH_NAME_UNICODE = {
    "space": " ",
    "ring": "˚",
    "lessequal": "≤",
    "mu": "μ",
    "afii61352": "№",
}


def _glyph_name_to_unicode(glyph_name: str | None) -> str | None:
    if not glyph_name:
        return None
    base = glyph_name.split(".", 1)[0]
    if base == ".notdef":
        return None
    if len(base) == 1:
        return base
    direct = _GLYPH_NAME_UNICODE.get(base)
    if direct is not None:
        return direct
    if base.startswith("uni") and len(base) > 3:
        hex_part = base[3:]
        if len(hex_part) % 4 == 0:
            chars: list[str] = []
            for idx in range(0, len(hex_part), 4):
                try:
                    chars.append(chr(int(hex_part[idx : idx + 4], 16)))
                except ValueError:
                    return None
            return "".join(chars)
    if base.startswith("u") and len(base) in (5, 6, 7):
        try:
            return chr(int(base[1:], 16))
        except ValueError:
            return None
    return None


def _build_unicode_to_code_map(encoding: dict[int, str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for code, glyph in encoding.items():
        uni = _glyph_name_to_unicode(glyph)
        if uni is None or len(uni) != 1:
            continue
        mapping.setdefault(uni, int(code) & 0xFF)
    return mapping


_STANDARD_UNICODE_TO_CODE = _build_unicode_to_code_map(STANDARD_ENCODING)
_SYMBOL_UNICODE_TO_CODE = _build_unicode_to_code_map(SYMBOL_ENCODING)
_ZAPF_UNICODE_TO_CODE = _build_unicode_to_code_map(ZAPF_DINGBATS_ENCODING)


@dataclass(frozen=True)
class PdfMetadata:
    """PDF metadata fields for the document info dictionary.

    Example:
        >>> PdfMetadata(\"\", \"\", \"Producer\", \"D:20260101\", \"D:20260101\", False).producer
        'Producer'
    """

    title: str
    creator: str
    producer: str
    creation_date: str
    mod_date: str
    trapped: bool


@dataclass(frozen=True)
class ImageResource:
    """Image resource payload for PDF XObject embedding.

    Example:
        >>> ImageResource(b\"data\", 1, 1, \"DeviceRGB\", 8, None).width
        1
    """

    data: bytes
    width: int
    height: int
    color_space: str
    bits_per_component: int
    filter: str | None
    filter_params: dict | None = None
    decode: tuple[float, ...] | None = None
    mask: bool = False
    mask_polarity: bool = True


class PdfWriter:
    """Serialize a render document into PDF 1.4 bytes.

    Example:
        >>> metadata = PdfMetadata(\"\", \"\", \"Aspose.Page FOSS for Python\", \"D:20260101\", \"D:20260101\", False)
        >>> writer = PdfWriter(metadata)
        >>> pdf_bytes = writer.write(RenderDocument())
        >>> pdf_bytes.startswith(b\"%PDF-1.4\")
        True
    """

    def __init__(
        self,
        metadata: PdfMetadata,
        no_compression: bool = False,
        image_provider: Callable[[str], ImageResource] | None = None,
        font_provider: Callable[[str, set[int]], PdfEmbeddedFont | None] | None = None,
    ) -> None:
        self._metadata = metadata
        self._no_compression = no_compression
        self._image_provider = image_provider
        self._font_provider = font_provider

    def write(self, document: RenderDocument) -> bytes:
        """Serialize a render document to PDF 1.4 bytes.

        Example:
            >>> metadata = PdfMetadata(\"\", \"\", \"Producer\", \"D:20260101\", \"D:20260101\", False)
            >>> PdfWriter(metadata).write(RenderDocument())[:8]
            b'%PDF-1.4'
        """
        (
            font_resources,
            font_map,
            embedded_fonts,
            font_base,
            image_map,
            image_resources,
            font_code_maps,
        ) = self._collect_resources(document)
        color_spaces = document.resources.color_spaces
        patterns = document.resources.patterns
        functions = document.resources.functions
        pdf_patterns, pattern_variants = _prepare_pdf_patterns(
            document, patterns, color_spaces
        )
        pattern_space_ids = _prepare_pattern_color_spaces(document, color_spaces)
        font_order = list(font_resources.keys())
        image_order = list(image_map.keys())
        color_space_order = list(color_spaces.keys())
        pattern_order = list(pdf_patterns.keys())
        function_order = list(functions.keys())

        ids = _ObjectIds(
            font_order,
            image_order,
            color_spaces,
            pdf_patterns,
            functions,
            len(document.pages),
            list(embedded_fonts.keys()),
        )

        objects: list[bytes] = []
        for font_key in font_order:
            embedded = embedded_fonts.get(font_key)
            if embedded is not None:
                objects.append(
                    _serialize_object(
                        ids.fonts[font_key],
                        _font_object_embedded(
                            embedded,
                            ids.font_descriptors[font_key],
                            ids.to_unicode[font_key],
                        ),
                    )
                )
            else:
                objects.append(
                    _serialize_object(
                        ids.fonts[font_key],
                        _font_object(font_base[font_key]),
                    )
                )
        for font_key in ids.embedded_fonts:
            embedded = embedded_fonts[font_key]
            objects.append(
                _serialize_object(
                    ids.font_descriptors[font_key],
                    _font_descriptor_object(embedded, ids.font_files[font_key]),
                )
            )
        for font_key in ids.embedded_fonts:
            embedded = embedded_fonts[font_key]
            objects.append(
                _serialize_object(
                    ids.font_files[font_key],
                    _font_file_object(embedded, self._no_compression),
                )
            )
        for font_key in ids.embedded_fonts:
            embedded = embedded_fonts[font_key]
            objects.append(
                _serialize_object(
                    ids.to_unicode[font_key],
                    _to_unicode_object(embedded, self._no_compression),
                )
            )
        for image_id in image_order:
            image_resource = image_resources[image_id]
            objects.append(
                _serialize_object(
                    ids.images[image_id],
                    _image_object(image_resource, self._no_compression),
                )
            )
        for func_id in function_order:
            function = functions[func_id]
            objects.append(
                _serialize_object(ids.functions[func_id], _function_object(function, ids, functions))
            )
        for cs_id in color_space_order:
            color_space = color_spaces[cs_id]
            icc_id = ids.icc_profiles.get(cs_id)
            if icc_id is not None:
                objects.append(_serialize_object(icc_id, _icc_profile_object(color_space)))
            objects.append(
                _serialize_object(
                    ids.color_spaces[cs_id],
                    _color_space_object(color_space, ids, functions, color_spaces),
                )
            )
        for pattern_id in pattern_order:
            pattern = pdf_patterns[pattern_id]
            objects.append(
                _serialize_object(
                    ids.patterns[pattern_id],
                    _pattern_object(pattern, ids, functions, color_spaces, image_map, image_resources),
                )
            )
        color_space_defs = {
            cs_id: _serialize_color_space(color_space, ids, functions, color_spaces)
            for cs_id, color_space in color_spaces.items()
        }
        page_extgstates: list[dict[str, tuple[float, float]]] = []
        for page_index, page in enumerate(document.pages):
            extgstates = _collect_page_extgstates(page)
            page_extgstates.append(extgstates)
            content_bytes = self._render_page(
                page,
                font_map,
                image_map,
                image_resources,
                color_space_defs,
                pattern_variants,
                pattern_space_ids,
                font_code_maps,
                extgstates,
            )
            objects.append(
                _serialize_object(
                    ids.contents[page_index],
                    _content_object(content_bytes, self._no_compression),
                )
            )
        for page_index, page in enumerate(document.pages):
            objects.append(
                _serialize_object(
                    ids.pages[page_index],
                    _page_object(
                        page,
                        ids.pages_tree,
                        ids.contents[page_index],
                        font_resources,
                        image_map,
                        ids.fonts,
                        ids.images,
                        ids.color_spaces,
                        ids.patterns,
                        page_extgstates[page_index],
                    ),
                )
            )

        objects.append(
            _serialize_object(
                ids.pages_tree,
                _pages_tree_object(ids.pages),
            )
        )
        objects.append(
            _serialize_object(
                ids.catalog,
                _catalog_object(ids.pages_tree),
            )
        )
        objects.append(_serialize_object(ids.info, _info_object(self._metadata)))

        objects.sort(key=_serialized_object_id)
        return _serialize_pdf(objects, ids.catalog, ids.info)

    def _collect_resources(
        self, document: RenderDocument
    ) -> tuple[
        dict[str, str],
        dict[str, str],
        dict[str, PdfEmbeddedFont],
        dict[str, str],
        dict[str, str],
        dict[str, ImageResource],
        dict[str, dict[int, int]],
    ]:
        font_resources: dict[str, str] = {}
        font_map: dict[str, str] = {}
        embedded_fonts: dict[str, PdfEmbeddedFont] = {}
        font_base: dict[str, str] = {}
        image_map: dict[str, str] = {}
        image_resources: dict[str, ImageResource] = {}
        used_codes: dict[str, set[int]] = {}
        font_code_maps: dict[str, dict[int, int]] = {}

        def _ensure_image(image_id: str) -> None:
            if self._image_provider is None:
                raise ValueError("image provider is required for image commands")
            if image_id not in image_resources:
                image_resource = self._image_provider(image_id)
                if image_resource is None:
                    raise ValueError("image provider returned no data")
                image_resources[image_id] = image_resource
            if image_id not in image_map:
                image_map[image_id] = f"Im{len(image_map) + 1}"

        for page in document.pages:
            for command in page.commands:
                if isinstance(command, TextCommand):
                    codes = used_codes.setdefault(command.font_ref, set())
                    for char in command.text:
                        code = ord(char)
                        if code in (10, 13):
                            continue
                        codes.add(code)
                if isinstance(command, ImageCommand):
                    _ensure_image(command.image_id)
        for pattern in document.resources.patterns.values():
            if not isinstance(pattern, TilingPattern):
                continue
            for command in pattern.commands:
                if isinstance(command, ImageCommand):
                    _ensure_image(command.image_id)

        for font_ref, codes in used_codes.items():
            embedded = None
            if self._font_provider is not None:
                embedded = self._font_provider(font_ref, codes)
            if embedded is not None:
                font_key = font_ref
                embedded_fonts[font_key] = embedded
                font_code_maps[font_ref] = dict(embedded.char_code_map)
            else:
                font_key = _resolve_font(font_ref)
                font_base[font_key] = font_key
            if font_key not in font_resources:
                font_resources[font_key] = f"F{len(font_resources) + 1}"
            font_map[font_ref] = font_resources[font_key]

        return (
            font_resources,
            font_map,
            embedded_fonts,
            font_base,
            image_map,
            image_resources,
            font_code_maps,
        )

    def _render_page(
        self,
        page: RenderPage,
        font_map: dict[str, str],
        image_map: dict[str, str],
        image_resources: dict[str, ImageResource],
        color_space_defs: dict[str, str],
        pattern_variants: dict[tuple[str, str, tuple[float, ...]], str],
        pattern_space_ids: dict[str, str],
        font_code_maps: dict[str, dict[int, int]],
        extgstates: dict[str, tuple[float, float]],
    ) -> bytes:
        lines: list[str] = []
        extgstate_by_values = {value: name for name, value in extgstates.items()}
        for command in page.commands:
            if isinstance(command, PathCommand):
                values = (
                    _clamp_opacity(command.fill_opacity),
                    _clamp_opacity(command.stroke_opacity),
                )
                if values in extgstate_by_values:
                    lines.append("q")
                    lines.append(f"/{extgstate_by_values[values]} gs")
                    lines.extend(
                        _render_path_command(
                            command, color_space_defs, pattern_variants, pattern_space_ids
                        )
                    )
                    lines.append("Q")
                else:
                    lines.extend(
                        _render_path_command(
                            command, color_space_defs, pattern_variants, pattern_space_ids
                        )
                    )
            elif isinstance(command, ClipCommand):
                lines.extend(_render_path(command.path))
                lines.append("W*" if command.fill_rule == "evenodd" else "W")
                lines.append("n")
            elif isinstance(command, StateSaveCommand):
                lines.append("q")
            elif isinstance(command, StateRestoreCommand):
                lines.append("Q")
            elif isinstance(command, TextCommand):
                values = (_clamp_opacity(command.fill_opacity), 1.0)
                if values in extgstate_by_values:
                    lines.append("q")
                    lines.append(f"/{extgstate_by_values[values]} gs")
                    lines.extend(
                        _render_text_command(
                            command,
                            font_map,
                            color_space_defs,
                            pattern_variants,
                            pattern_space_ids,
                            font_code_maps,
                        )
                    )
                    lines.append("Q")
                else:
                    lines.extend(
                        _render_text_command(
                            command,
                            font_map,
                            color_space_defs,
                            pattern_variants,
                            pattern_space_ids,
                            font_code_maps,
                        )
                    )
            elif isinstance(command, ImageCommand):
                resource = image_resources.get(command.image_id)
                is_ccitt_mask = bool(
                    resource is not None and resource.mask and resource.filter == "CCITTFaxDecode"
                )
                values = (_clamp_opacity(command.opacity), _clamp_opacity(command.opacity))
                if values in extgstate_by_values:
                    lines.append("q")
                    lines.append(f"/{extgstate_by_values[values]} gs")
                    lines.extend(_render_image_command(command, image_map, is_ccitt_mask))
                    lines.append("Q")
                else:
                    lines.extend(_render_image_command(command, image_map, is_ccitt_mask))

        return ("\n".join(lines) + "\n").encode("latin-1", "replace")


def _prepare_pdf_patterns(
    document: RenderDocument,
    patterns: dict[str, Pattern],
    color_spaces: dict[str, ColorSpace],
) -> tuple[dict[str, Pattern], dict[tuple[str, str, tuple[float, ...]], str]]:
    """Prepare pattern resources for PDF output.

    Some renderers ignore base color components on uncolored tiling patterns.
    We generate colored pattern variants per base color and reference those
    variants during painting to preserve the intended pattern color.
    """
    pdf_patterns: dict[str, Pattern] = dict(patterns)
    variants: dict[tuple[str, str, tuple[float, ...]], str] = {}
    counter = 1

    for page in document.pages:
        for command in page.commands:
            paints: list[Paint] = []
            if isinstance(command, PathCommand):
                if command.fill is not None:
                    paints.append(command.fill)
                if command.stroke_paint is not None:
                    paints.append(command.stroke_paint)
            elif isinstance(command, TextCommand):
                if command.fill is not None:
                    paints.append(command.fill)
            for paint in paints:
                if paint.kind != "Pattern" or not isinstance(paint.value, PatternPaint):
                    continue
                if paint.value.base_space_id is None or paint.value.base_components is None:
                    continue
                base_space = color_spaces.get(paint.value.base_space_id)
                if not isinstance(base_space, DeviceColorSpace):
                    continue
                raw_components = tuple(paint.value.base_components)
                base_components = _normalize_device_components(
                    base_space.name, paint.value.base_components
                )
                key = (paint.value.pattern_id, paint.value.base_space_id, raw_components)
                if key in variants:
                    continue
                base_pattern = patterns.get(paint.value.pattern_id)
                if not isinstance(base_pattern, TilingPattern) or base_pattern.paint_type != 2:
                    continue
                variant_id = f"{paint.value.pattern_id}C{counter}"
                counter += 1
                pdf_patterns[variant_id] = _colorize_tiling_pattern(
                    base_pattern, base_space.name, base_components
                )
                variants[key] = variant_id

    return pdf_patterns, variants


def _prepare_pattern_color_spaces(
    document: RenderDocument,
    color_spaces: dict[str, ColorSpace],
) -> dict[str, str]:
    """Ensure Pattern colorspaces for uncolored tiling patterns are registered.

    Returns a mapping from base color space id to Pattern colorspace id.
    """
    mapping: dict[str, str] = {}

    def register_color_space(value: ColorSpace) -> str:
        for key, existing in color_spaces.items():
            if existing == value:
                return key
        resource_id = f"CS{len(color_spaces) + 1}"
        color_spaces[resource_id] = value
        return resource_id

    for page in document.pages:
        for command in page.commands:
            paints: list[Paint] = []
            if isinstance(command, PathCommand):
                if command.fill is not None:
                    paints.append(command.fill)
                if command.stroke_paint is not None:
                    paints.append(command.stroke_paint)
            elif isinstance(command, TextCommand):
                if command.fill is not None:
                    paints.append(command.fill)
            for paint in paints:
                if paint.kind != "Pattern" or not isinstance(paint.value, PatternPaint):
                    continue
                base_id = paint.value.base_space_id
                if base_id is None:
                    continue
                if base_id in mapping:
                    continue
                base_space = color_spaces.get(base_id)
                if base_space is None:
                    continue
                pattern_space = PatternColorSpace(base=base_space)
                mapping[base_id] = register_color_space(pattern_space)
    return mapping


def _normalize_device_components(
    space_name: str, components: tuple[float, ...]
) -> tuple[float, ...]:
    target = 1
    if space_name == "DeviceRGB":
        target = 3
    elif space_name == "DeviceCMYK":
        target = 4
    values = list(components)
    while len(values) < target:
        values.append(0.0)
    return tuple(values[:target])


def _colorize_tiling_pattern(
    pattern: TilingPattern, space_name: str, components: tuple[float, ...]
) -> TilingPattern:
    colored_commands: list[object] = []
    paint_value: object = components[0] if len(components) == 1 else components
    paint = Paint(space_name, paint_value)
    for command in pattern.commands:
        if isinstance(command, PathCommand):
            fill = command.fill
            stroke = command.stroke
            if fill is not None and fill.kind == "PatternBase":
                fill = paint
            colored_commands.append(
                PathCommand(
                    command.path,
                    stroke,
                    fill,
                    command.fill_rule,
                    command.stroke_paint,
                    command.overprint,
                    command.fill_opacity,
                    command.stroke_opacity,
                )
            )
            continue
        if isinstance(command, TextCommand):
            fill = command.fill
            if fill is not None and fill.kind == "PatternBase":
                fill = paint
            colored_commands.append(
                TextCommand(
                    command.text,
                    command.font_ref,
                    command.font_size,
                    command.matrix,
                    fill,
                    command.fill_opacity,
                )
            )
            continue
        colored_commands.append(command)
    return TilingPattern(
        paint_type=1,
        tiling_type=pattern.tiling_type,
        bbox=pattern.bbox,
        x_step=pattern.x_step,
        y_step=pattern.y_step,
        matrix=pattern.matrix,
        commands=colored_commands,
    )


class _ObjectIds:
    def __init__(
        self,
        fonts: list[str],
        images: list[str],
        color_spaces: dict[str, ColorSpace],
        patterns: dict[str, Pattern],
        functions: dict[str, Function],
        page_count: int,
        embedded_fonts: list[str],
    ) -> None:
        current = 1
        self.fonts: dict[str, int] = {}
        for font in fonts:
            self.fonts[font] = current
            current += 1

        self.embedded_fonts: list[str] = list(embedded_fonts)
        self.font_descriptors: dict[str, int] = {}
        self.font_files: dict[str, int] = {}
        self.to_unicode: dict[str, int] = {}
        for font_key in self.embedded_fonts:
            self.font_descriptors[font_key] = current
            current += 1
            self.font_files[font_key] = current
            current += 1
            self.to_unicode[font_key] = current
            current += 1

        self.images: dict[str, int] = {}
        for image in images:
            self.images[image] = current
            current += 1

        self.functions: dict[str, int] = {}
        for func_id in functions.keys():
            self.functions[func_id] = current
            current += 1

        self.icc_profiles: dict[str, int] = {}
        self.color_spaces: dict[str, int] = {}
        for cs_id, color_space in color_spaces.items():
            if isinstance(color_space, CieBasedColorSpace):
                self.icc_profiles[cs_id] = current
                current += 1
            self.color_spaces[cs_id] = current
            current += 1

        self.patterns: dict[str, int] = {}
        for pattern_id in patterns.keys():
            self.patterns[pattern_id] = current
            current += 1

        self.contents: list[int] = []
        for _ in range(page_count):
            self.contents.append(current)
            current += 1

        self.pages: list[int] = []
        for _ in range(page_count):
            self.pages.append(current)
            current += 1

        self.pages_tree = current
        current += 1
        self.catalog = current
        current += 1
        self.info = current
        current += 1

        self.total_objects = current - 1


def _serialize_pdf(objects: list[bytes], catalog_id: int, info_id: int) -> bytes:
    header = b"%PDF-1.4\n"
    body = b"".join(objects)
    xref_offset = len(header) + len(body)
    xref = _xref_table(objects)
    trailer = _trailer(len(objects), catalog_id, info_id, xref_offset)
    return header + body + xref + trailer


def _xref_table(objects: list[bytes]) -> bytes:
    offsets: list[int] = []
    current = len(b"%PDF-1.4\n")
    for obj in objects:
        offsets.append(current)
        current += len(obj)

    lines = ["xref", f"0 {len(objects) + 1}", "0000000000 65535 f "]
    for offset in offsets:
        lines.append(f"{offset:010d} 00000 n ")

    return "\n".join(lines).encode("ascii") + b"\n"


def _trailer(size: int, catalog_id: int, info_id: int, xref_offset: int) -> bytes:
    trailer_dict = _pdf_dict(
        [
            f"/Size {size + 1}",
            f"/Root {catalog_id} 0 R",
            f"/Info {info_id} 0 R",
        ]
    )
    return (
        b"trailer\n" + trailer_dict.encode("ascii")
        + b"\nstartxref\n"
        + f"{xref_offset}\n".encode("ascii")
        + b"%%EOF\n"
    )


def _serialize_object(obj_id: int, body: bytes) -> bytes:
    return f"{obj_id} 0 obj\n".encode("ascii") + body + b"\nendobj\n"


def _serialized_object_id(obj: bytes) -> int:
    space = obj.find(b" ")
    if space <= 0:
        raise ValueError("invalid serialized PDF object")
    return int(obj[:space])


def _pdf_dict(lines: list[str]) -> str:
    if not lines:
        return "<<>>"
    return "<<\n" + "\n".join(lines) + "\n>>"


def _font_object(base_font: str) -> bytes:
    body = _pdf_dict(
        [
            "/Type /Font",
            "/Subtype /Type1",
            f"/BaseFont /{base_font}",
        ]
    )
    return body.encode("ascii")


def _font_object_embedded(embedded: PdfEmbeddedFont, desc_id: int, to_unicode_id: int) -> bytes:
    lines = [
        "/Type /Font",
        f"/Subtype /{embedded.subtype}",
        f"/BaseFont /{embedded.subset_name}",
        f"/FirstChar {embedded.first_char}",
        f"/LastChar {embedded.last_char}",
        f"/Widths {_pdf_array(embedded.widths)}",
        f"/FontDescriptor {desc_id} 0 R",
        f"/ToUnicode {to_unicode_id} 0 R",
    ]
    if embedded.encoding:
        lines.append(f"/Encoding /{embedded.encoding}")
    body = _pdf_dict(lines)
    return body.encode("ascii")


def _font_descriptor_object(embedded: PdfEmbeddedFont, font_file_id: int) -> bytes:
    bbox = _pdf_array(list(embedded.bbox))
    flags = 4 if embedded.symbolic else 32
    if embedded.italic_angle != 0:
        flags |= 64
    body = _pdf_dict(
        [
            "/Type /FontDescriptor",
            f"/FontName /{embedded.subset_name}",
            f"/Flags {flags}",
            f"/FontBBox {bbox}",
            f"/ItalicAngle {embedded.italic_angle}",
            f"/Ascent {embedded.ascent}",
            f"/Descent {embedded.descent}",
            f"/CapHeight {embedded.ascent}",
            f"/StemV {embedded.stem_v}",
            f"/{embedded.font_file_key} {font_file_id} 0 R",
        ]
    )
    return body.encode("ascii")


def _font_file_object(embedded: PdfEmbeddedFont, no_compression: bool) -> bytes:
    data = embedded.font_file
    dict_lines = [f"/Length1 {len(data)}"]
    if not no_compression:
        data = zlib.compress(data)
        dict_lines.append("/Filter /FlateDecode")
    return _stream_object(data, dict_lines)


def _to_unicode_object(embedded: PdfEmbeddedFont, no_compression: bool) -> bytes:
    data = embedded.to_unicode.encode("utf-8")
    if not no_compression:
        data = zlib.compress(data)
        return _stream_object(data, ["/Filter /FlateDecode"])
    return _stream_object(data, [])


def _image_object(resource: ImageResource, no_compression: bool) -> bytes:
    data = resource.data
    filter_name = resource.filter
    if filter_name is None and not no_compression:
        data = zlib.compress(data)
        filter_name = "FlateDecode"

    dict_lines = [
        "/Type /XObject",
        "/Subtype /Image",
        f"/Width {resource.width}",
        f"/Height {resource.height}",
    ]
    if resource.mask:
        dict_lines.append("/ImageMask true")
        dict_lines.append("/BitsPerComponent 1")
        # Stencil polarity differs across raw mask bytes vs CCITT-decoded mask
        # streams in real-world PS generators.
        # - Raw mask bytes (eg `$X` + `imagemask true`) need Decode [1 0].
        # - CCITT mask streams in this corpus already align without inversion.
        is_ccitt_mask = resource.filter == "CCITTFaxDecode"
        if (not is_ccitt_mask and resource.mask_polarity) or (
            is_ccitt_mask and not resource.mask_polarity
        ):
            dict_lines.append("/Decode [1 0]")
    else:
        dict_lines.append(f"/ColorSpace /{resource.color_space}")
        dict_lines.append(f"/BitsPerComponent {resource.bits_per_component}")
        decode_values = _normalize_decode_for_pdf(resource.decode, resource.bits_per_component)
        if decode_values is not None:
            dict_lines.append(f"/Decode {_pdf_array(list(decode_values))}")
    if filter_name is not None:
        dict_lines.append(f"/Filter /{filter_name}")
        decode_params = _pdf_decode_params(resource)
        if decode_params is not None:
            dict_lines.append(f"/DecodeParms {decode_params}")

    return _stream_object(data, dict_lines)


def _pdf_decode_params(resource: ImageResource) -> str | None:
    params = resource.filter_params
    if not params:
        return None
    params_dict = dict(params)
    if (
        resource.mask
        and resource.filter == "CCITTFaxDecode"
        and isinstance(params_dict.get("BlackIs1"), bool)
    ):
        params_dict["BlackIs1"] = not bool(params_dict["BlackIs1"])
    parts: list[str] = []
    for key in sorted(params_dict.keys()):
        value = params_dict[key]
        parts.append(f"/{key} {_pdf_object(value)}")
    return "<< " + " ".join(parts) + " >>"


def _pdf_object(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_number(value)
    if isinstance(value, bytes):
        return _hex_bytes(value)
    if isinstance(value, str):
        if value.startswith("/"):
            return value
        return f"/{value}"
    if isinstance(value, (list, tuple)):
        return "[" + " ".join(_pdf_object(item) for item in value) + "]"
    if isinstance(value, dict):
        entries = [f"/{k} {_pdf_object(v)}" for k, v in sorted(value.items())]
        return "<< " + " ".join(entries) + " >>"
    return _format_number(value)


def _normalize_decode_for_pdf(
    decode: tuple[float, ...] | None,
    bits_per_component: int,
) -> tuple[float, ...] | None:
    if decode is None:
        return None
    values = tuple(float(value) for value in decode)
    if not values:
        return None
    if max(abs(value) for value in values) <= 1.0:
        return values
    bpc = max(1, int(bits_per_component))
    max_sample = float((1 << bpc) - 1)
    if max_sample <= 0.0:
        return values
    return tuple(value / max_sample for value in values)


def _content_object(content: bytes, no_compression: bool) -> bytes:
    data = content
    dict_lines: list[str] = []
    if not no_compression:
        data = zlib.compress(content)
        dict_lines.append("/Filter /FlateDecode")
    return _stream_object(data, dict_lines)


def _stream_object(data: bytes, dict_lines: list[str]) -> bytes:
    stream_dict = _pdf_dict(dict_lines + [f"/Length {len(data)}"])
    return stream_dict.encode("ascii") + b"\nstream\n" + data + b"\nendstream"


def _page_object(
    page: RenderPage,
    parent_id: int,
    content_id: int,
    font_map: dict[str, str],
    image_map: dict[str, str],
    font_ids: dict[str, int],
    image_ids: dict[str, int],
    color_space_ids: dict[str, int],
    pattern_ids: dict[str, int],
    extgstates: dict[str, tuple[float, float]] | None = None,
) -> bytes:
    resources: list[str] = []
    if font_map:
        font_entries = [f"/{name} {font_ids[font]} 0 R" for font, name in font_map.items()]
        resources.append("/Font << " + " ".join(font_entries) + " >>")
    if image_map:
        image_entries = [
            f"/{name} {image_ids[image_id]} 0 R" for image_id, name in image_map.items()
        ]
        resources.append("/XObject << " + " ".join(image_entries) + " >>")
    if color_space_ids:
        cs_entries = [f"/{name} {obj_id} 0 R" for name, obj_id in color_space_ids.items()]
        resources.append("/ColorSpace << " + " ".join(cs_entries) + " >>")
    if pattern_ids:
        pattern_entries = [f"/{name} {obj_id} 0 R" for name, obj_id in pattern_ids.items()]
        resources.append("/Pattern << " + " ".join(pattern_entries) + " >>")
    if extgstates:
        gs_entries = [
            f"/{name} << /Type /ExtGState /ca {_format_number(values[0])} /CA {_format_number(values[1])} >>"
            for name, values in extgstates.items()
        ]
        resources.append("/ExtGState << " + " ".join(gs_entries) + " >>")

    resources_dict = "<< " + " ".join(resources) + " >>" if resources else "<<>>"
    body = _pdf_dict(
        [
            "/Type /Page",
            f"/Parent {parent_id} 0 R",
            f"/MediaBox [{format_rect(_page_rect(page))}]",
            f"/Resources {resources_dict}",
            f"/Contents {content_id} 0 R",
        ]
    )
    return body.encode("ascii")


def _clamp_opacity(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def _collect_page_extgstates(page: RenderPage) -> dict[str, tuple[float, float]]:
    values: list[tuple[float, float]] = []
    for command in page.commands:
        if isinstance(command, PathCommand):
            pair = (_clamp_opacity(command.fill_opacity), _clamp_opacity(command.stroke_opacity))
            if pair != (1.0, 1.0):
                values.append(pair)
        elif isinstance(command, TextCommand):
            pair = (_clamp_opacity(command.fill_opacity), 1.0)
            if pair != (1.0, 1.0):
                values.append(pair)
        elif isinstance(command, ImageCommand):
            pair = (_clamp_opacity(command.opacity), _clamp_opacity(command.opacity))
            if pair != (1.0, 1.0):
                values.append(pair)
    unique: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for pair in values:
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)
    return {f"GS{i+1}": pair for i, pair in enumerate(unique)}


def _pages_tree_object(page_ids: list[int]) -> bytes:
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    body = _pdf_dict(
        [
            "/Type /Pages",
            f"/Kids [{kids}]",
            f"/Count {len(page_ids)}",
        ]
    )
    return body.encode("ascii")


def _catalog_object(pages_tree_id: int) -> bytes:
    body = _pdf_dict([
        "/Type /Catalog",
        f"/Pages {pages_tree_id} 0 R",
    ])
    return body.encode("ascii")


def _info_object(metadata: PdfMetadata) -> bytes:
    body = _pdf_dict(
        [
            f"/Title ({escape_pdf_string(metadata.title)})",
            f"/Creator ({escape_pdf_string(metadata.creator)})",
            f"/Producer ({escape_pdf_string(metadata.producer)})",
            f"/CreationDate ({escape_pdf_string(metadata.creation_date)})",
            f"/ModDate ({escape_pdf_string(metadata.mod_date)})",
            f"/Trapped {'true' if metadata.trapped else 'false'}",
        ]
    )
    return body.encode("ascii")


def _function_object(function: Function, ids: _ObjectIds, functions: dict[str, Function]) -> bytes:
    if isinstance(function, SampledFunction):
        dict_lines = [
            "/FunctionType 0",
            f"/Domain {_pdf_array(function.domain)}",
            f"/Range {_pdf_array(function.range)}",
            f"/Size {_pdf_array(function.size)}",
            f"/BitsPerSample {function.bits_per_sample}",
        ]
        if function.order and function.order != 1:
            dict_lines.append(f"/Order {function.order}")
        if function.encode:
            dict_lines.append(f"/Encode {_pdf_array(function.encode)}")
        if function.decode:
            dict_lines.append(f"/Decode {_pdf_array(function.decode)}")
        return _stream_object(function.samples, dict_lines)
    if isinstance(function, ExponentialFunction):
        dict_lines = [
            "/FunctionType 2",
            f"/Domain {_pdf_array(function.domain)}",
            f"/Range {_pdf_array(function.range)}",
            f"/C0 {_pdf_array(function.c0)}",
            f"/C1 {_pdf_array(function.c1)}",
            f"/N {_format_number(function.n)}",
        ]
        return _pdf_dict(dict_lines).encode("ascii")
    if isinstance(function, StitchingFunction):
        function_refs = [
            _function_ref(entry, ids, functions) for entry in function.functions
        ]
        dict_lines = [
            "/FunctionType 3",
            f"/Domain {_pdf_array(function.domain)}",
            f"/Range {_pdf_array(function.range)}",
            f"/Functions [{' '.join(function_refs)}]",
            f"/Bounds {_pdf_array(function.bounds)}",
            f"/Encode {_pdf_array(function.encode)}",
        ]
        return _pdf_dict(dict_lines).encode("ascii")
    raise ValueError("unsupported function type")


def _color_space_object(
    color_space: ColorSpace,
    ids: _ObjectIds,
    functions: dict[str, Function],
    color_spaces: dict[str, ColorSpace],
) -> bytes:
    return _serialize_color_space(color_space, ids, functions, color_spaces).encode("ascii")


def _icc_profile_object(color_space: ColorSpace) -> bytes:
    if not isinstance(color_space, CieBasedColorSpace):
        raise ValueError("ICC profile only for CIEBased color spaces")
    dict_lines = [
        "/N {}".format(color_space.components),
    ]
    return _stream_object(color_space.icc_profile, dict_lines)


def _pattern_object(
    pattern: Pattern,
    ids: _ObjectIds,
    functions: dict[str, Function],
    color_spaces: dict[str, ColorSpace],
    image_map: dict[str, str],
    image_resources: dict[str, ImageResource],
) -> bytes:
    if isinstance(pattern, TilingPattern):
        content = _render_pattern_commands(pattern.commands, image_map, image_resources)
        # Some PDF renderers do not strictly confine image sampling to the
        # declared pattern BBox. Apply an explicit clip to avoid pattern paint
        # bleeding beyond the cell domain (notably for non-tiling ImageBrush).
        content = _clip_pattern_content_to_bbox(pattern, content)
        tiling_type, x_step, y_step = _pdf_pattern_tiling_params(pattern)
        pattern_image_ids = _pattern_image_ids(pattern.commands)
        xobject = ""
        if pattern_image_ids:
            refs = []
            for image_id in pattern_image_ids:
                name = image_map.get(image_id)
                obj_id = ids.images.get(image_id)
                if name is None or obj_id is None:
                    continue
                refs.append(f"/{name} {obj_id} 0 R")
            if refs:
                xobject = "/XObject << " + " ".join(refs) + " >> "
        dict_lines = [
            "/Type /Pattern",
            "/PatternType 1",
            f"/PaintType {pattern.paint_type}",
            f"/TilingType {tiling_type}",
            f"/BBox {_pdf_array(pattern.bbox)}",
            f"/XStep {_format_number(x_step)}",
            f"/YStep {_format_number(y_step)}",
            f"/Matrix {_pdf_array(pattern.matrix)}",
            f"/Resources << {xobject}>>",
        ]
        return _stream_object(content, dict_lines)
    if isinstance(pattern, ShadingPattern):
        shading_dict = _serialize_shading(pattern.shading, ids, functions, color_spaces)
        dict_lines = [
            "/Type /Pattern",
            "/PatternType 2",
            f"/Shading {shading_dict}",
            f"/Matrix {_pdf_array(pattern.matrix)}",
        ]
        return _pdf_dict(dict_lines).encode("ascii")
    raise ValueError("unsupported pattern type")


def _clip_pattern_content_to_bbox(pattern: TilingPattern, content: bytes) -> bytes:
    x0, y0, x1, y1 = pattern.bbox
    prefix = [
        "q",
        f"{_format_number(x0)} {_format_number(y0)} m",
        f"{_format_number(x1)} {_format_number(y0)} l",
        f"{_format_number(x1)} {_format_number(y1)} l",
        f"{_format_number(x0)} {_format_number(y1)} l",
        "h",
        "W",
        "n",
    ]
    suffix = ["Q"]
    body = content.decode("ascii")
    data = "\n".join(prefix) + "\n" + body
    if not data.endswith("\n"):
        data += "\n"
    data += "\n".join(suffix) + "\n"
    return data.encode("ascii")


def _pdf_pattern_tiling_params(pattern: TilingPattern) -> tuple[int, float, float]:
    # Internal render model uses tiling_type==0 as "non-tiling" tile brush
    # (XPS TileMode=None). PDF has only tiling types 1..3. Encode this mode as
    # type-1 with very large steps so only one cell appears on-page.
    if pattern.tiling_type <= 0:
        bbox_w = max(1.0, abs(pattern.bbox[2] - pattern.bbox[0]))
        bbox_h = max(1.0, abs(pattern.bbox[3] - pattern.bbox[1]))
        base = max(abs(pattern.x_step), abs(pattern.y_step), bbox_w, bbox_h, 1.0)
        huge_step = base * 4096.0
        return (1, huge_step, huge_step)
    return (pattern.tiling_type, pattern.x_step, pattern.y_step)


def _serialize_color_space(
    color_space: ColorSpace,
    ids: _ObjectIds,
    functions: dict[str, Function],
    color_spaces: dict[str, ColorSpace],
) -> str:
    if isinstance(color_space, DeviceColorSpace):
        return f"/{color_space.name}"
    if isinstance(color_space, PatternColorSpace):
        if color_space.base is None:
            return "/Pattern"
        base = _serialize_color_space(color_space.base, ids, functions, color_spaces)
        return f"[/Pattern {base}]"
    if isinstance(color_space, IndexedColorSpace):
        base = _serialize_color_space(color_space.base, ids, functions, color_spaces)
        lookup = _hex_bytes(color_space.lookup)
        return f"[/Indexed {base} {color_space.hival} {lookup}]"
    if isinstance(color_space, SeparationColorSpace):
        alternate = _serialize_color_space(color_space.alternate, ids, functions, color_spaces)
        tint_ref = _function_ref(color_space.tint, ids, functions)
        return f"[/Separation /{color_space.name} {alternate} {tint_ref}]"
    if isinstance(color_space, DeviceNColorSpace):
        names = " ".join(f"/{name}" for name in color_space.names)
        alternate = _serialize_color_space(color_space.alternate, ids, functions, color_spaces)
        tint_ref = _function_ref(color_space.tint, ids, functions)
        return f"[/DeviceN [{names}] {alternate} {tint_ref}]"
    if isinstance(color_space, CieBasedColorSpace):
        try:
            cs_id = _find_color_space_id(color_space, color_spaces)
        except ValueError:
            return "/DeviceRGB"
        icc_id = ids.icc_profiles.get(cs_id)
        if icc_id is None:
            return "/DeviceRGB"
        return f"[/ICCBased {icc_id} 0 R]"
    raise ValueError("unsupported color space type")


def _serialize_shading(
    shading: object,
    ids: _ObjectIds,
    functions: dict[str, Function],
    color_spaces: dict[str, ColorSpace],
) -> str:
    if isinstance(shading, AxialShading):
        cs = _serialize_color_space(shading.color_space, ids, functions, color_spaces)
        func_ref = _function_ref(shading.function, ids, functions)
        lines = [
            "/ShadingType 2",
            f"/ColorSpace {cs}",
            f"/Coords {_pdf_array(shading.coords)}",
            f"/Function {func_ref}",
            f"/Extend {_pdf_bool_array(shading.extend)}",
        ]
        if shading.domain is not None:
            lines.append(f"/Domain {_pdf_array(shading.domain)}")
        return _pdf_dict(lines)
    if isinstance(shading, RadialShading):
        cs = _serialize_color_space(shading.color_space, ids, functions, color_spaces)
        func_ref = _function_ref(shading.function, ids, functions)
        lines = [
            "/ShadingType 3",
            f"/ColorSpace {cs}",
            f"/Coords {_pdf_array(shading.coords)}",
            f"/Function {func_ref}",
            f"/Extend {_pdf_bool_array(shading.extend)}",
        ]
        if shading.domain is not None:
            lines.append(f"/Domain {_pdf_array(shading.domain)}")
        return _pdf_dict(lines)
    raise ValueError("unsupported shading type")


def _render_pattern_commands(
    commands: list[object],
    image_map: dict[str, str],
    image_resources: dict[str, ImageResource],
) -> bytes:
    lines: list[str] = []
    for command in commands:
        if isinstance(command, PathCommand):
            lines.extend(_render_path_command(command))
        elif isinstance(command, ClipCommand):
            lines.extend(_render_path(command.path))
            lines.append("W*" if command.fill_rule == "evenodd" else "W")
            lines.append("n")
        elif isinstance(command, StateSaveCommand):
            lines.append("q")
        elif isinstance(command, StateRestoreCommand):
            lines.append("Q")
        elif isinstance(command, TextCommand):
            lines.extend(_render_text_command(command, {}))
        elif isinstance(command, ImageCommand):
            resource = image_resources.get(command.image_id)
            is_ccitt_mask = bool(
                resource is not None and resource.mask and resource.filter == "CCITTFaxDecode"
            )
            lines.extend(_render_image_command(command, image_map, is_ccitt_mask))
    return ("\n".join(lines) + "\n").encode("ascii")


def _pattern_image_ids(commands: list[object]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for command in commands:
        if isinstance(command, ImageCommand) and command.image_id not in seen:
            ordered.append(command.image_id)
            seen.add(command.image_id)
    return ordered


def _function_ref(function: Function, ids: _ObjectIds, functions: dict[str, Function]) -> str:
    func_id = _find_function_id(function, functions)
    return f"{ids.functions[func_id]} 0 R"


def _find_function_id(function: Function, functions: dict[str, Function]) -> str:
    for key, value in functions.items():
        if value == function:
            return key
    raise ValueError("function not registered")


def _find_color_space_id(color_space: ColorSpace, color_spaces: dict[str, ColorSpace]) -> str:
    for key, value in color_spaces.items():
        if value == color_space:
            return key
    raise ValueError("color space not registered")


def _pdf_array(values: list[object] | tuple[object, ...]) -> str:
    return "[" + " ".join(_format_number(value) for value in values) + "]"


def _pdf_bool_array(values: tuple[bool, bool]) -> str:
    return "[" + " ".join("true" if value else "false" for value in values) + "]"


def _hex_bytes(data: bytes) -> str:
    return "<" + data.hex() + ">"


def _render_path_command(
    command: PathCommand,
    color_space_defs: dict[str, str] | None = None,
    pattern_variants: dict[tuple[str, str, tuple[float, ...]], str] | None = None,
    pattern_space_ids: dict[str, str] | None = None,
) -> list[str]:
    lines = _render_path(command.path)
    needs_stroke = command.stroke is not None
    needs_fill = command.fill is not None

    stroke_paint = command.stroke_paint or command.fill
    if needs_stroke:
        lines.extend(_render_stroke_style(command.stroke))
    if command.overprint:
        if needs_fill:
            lines.append("true op")
        if needs_stroke:
            lines.append("true OP")
    if needs_fill:
        lines.extend(
            _render_paint(
                command.fill,
                is_stroke=False,
                color_space_defs=color_space_defs,
                pattern_variants=pattern_variants,
                pattern_space_ids=pattern_space_ids,
            )
        )
    if needs_stroke and stroke_paint is not None:
        lines.extend(
            _render_paint(
                stroke_paint,
                is_stroke=True,
                color_space_defs=color_space_defs,
                pattern_variants=pattern_variants,
                pattern_space_ids=pattern_space_ids,
            )
        )

    if needs_stroke and needs_fill:
        lines.append("B*" if command.fill_rule == "evenodd" else "B")
    elif needs_stroke:
        lines.append("S")
    elif needs_fill:
        lines.append("f*" if command.fill_rule == "evenodd" else "f")
    else:
        lines.append("n")
    if command.overprint:
        if needs_fill:
            lines.append("false op")
        if needs_stroke:
            lines.append("false OP")
    return lines


def _render_text_command(
    command: TextCommand,
    font_map: dict[str, str],
    color_space_defs: dict[str, str] | None = None,
    pattern_variants: dict[tuple[str, str, tuple[float, ...]], str] | None = None,
    pattern_space_ids: dict[str, str] | None = None,
    font_code_maps: dict[str, dict[int, int]] | None = None,
) -> list[str]:
    text = "".join(char for char in command.text if ord(char) not in (10, 13))
    if not text:
        return []
    lines: list[str] = ["BT"]
    if command.fill is not None:
        lines.extend(
            _render_paint(
                command.fill,
                is_stroke=False,
                color_space_defs=color_space_defs,
                pattern_variants=pattern_variants,
                pattern_space_ids=pattern_space_ids,
            )
        )
    font_name = font_map.get(command.font_ref, "F1")
    lines.append(f"/{font_name} {_format_number(command.font_size)} Tf")
    lines.append(f"{format_matrix(command.matrix)} Tm")
    code_map = (font_code_maps or {}).get(command.font_ref, {})
    text_bytes = _encode_text_bytes(text, code_map, command.font_ref)
    lines.append(f"<{text_bytes.hex().upper()}> Tj")
    lines.append("ET")
    return lines


def _standard_unicode_to_code(font_ref: str) -> dict[str, int]:
    if font_ref == "Symbol":
        return _SYMBOL_UNICODE_TO_CODE
    if font_ref == "ZapfDingbats":
        return _ZAPF_UNICODE_TO_CODE
    return _STANDARD_UNICODE_TO_CODE


def _encode_text_bytes(text: str, code_map: dict[int, int], font_ref: str) -> bytes:
    payload = bytearray()
    standard_map = _standard_unicode_to_code(font_ref) if font_ref in _STANDARD_FONTS else {}
    for char in text:
        code = ord(char)
        mapped = code_map.get(code)
        if mapped is None:
            mapped = standard_map.get(char)
        if mapped is None:
            mapped = code if 0 <= code <= 0xFF else ord("?")
        payload.append(int(mapped) & 0xFF)
    return bytes(payload)


def _render_image_command(
    command: ImageCommand,
    image_map: dict[str, str],
    is_ccitt_mask: bool = False,
) -> list[str]:
    name = image_map[command.image_id]
    lines = ["q"]
    if command.mask and command.mask_paint is not None:
        lines.extend(_render_paint(command.mask_paint, False, {}, {}, {}))
    matrix = command.matrix
    if command.mask and is_ccitt_mask:
        # PostScript imagemask sample space is vertically inverted relative to
        # PDF image space. Apply a unit-space Y flip before painting.
        matrix = _mul_image_matrix(
            (
                command.matrix.a,
                command.matrix.b,
                command.matrix.c,
                command.matrix.d,
                command.matrix.e,
                command.matrix.f,
            ),
            (1.0, 0.0, 0.0, -1.0, 0.0, 1.0),
        )
    lines.extend(
        [
            f"{format_matrix(matrix)} cm",
            f"/{name} Do",
            "Q",
        ]
    )
    return lines


def _mul_image_matrix(
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


def _render_path(path: Path) -> list[str]:
    lines: list[str] = []
    for segment in path.segments:
        lines.extend(_render_segment(segment))
    return lines


def _render_segment(segment: PathSegment) -> list[str]:
    if segment.kind == "move":
        _validate_points(segment, 1)
        point = segment.points[0]
        return [f"{_format_number(point.x)} {_format_number(point.y)} m"]
    if segment.kind == "line":
        _validate_points(segment, 1)
        point = segment.points[0]
        return [f"{_format_number(point.x)} {_format_number(point.y)} l"]
    if segment.kind == "curve":
        _validate_points(segment, 3)
        points = segment.points
        return [
            f"{_format_number(points[0].x)} {_format_number(points[0].y)} "
            f"{_format_number(points[1].x)} {_format_number(points[1].y)} "
            f"{_format_number(points[2].x)} {_format_number(points[2].y)} c"
        ]
    if segment.kind == "close":
        _validate_points(segment, 0)
        return ["h"]
    raise ValueError(f"unsupported path segment: {segment.kind}")


def _render_stroke_style(style: StrokeStyle) -> list[str]:
    lines = [
        f"{_format_number(style.line_width)} w",
        f"{style.line_cap} J",
        f"{style.line_join} j",
        f"{_format_number(style.miter_limit)} M",
    ]
    dash_array = " ".join(_format_number(value) for value in style.dash)
    lines.append(f"[{dash_array}] {_format_number(style.dash_phase)} d")
    return lines


def _render_paint(
    paint: Paint,
    is_stroke: bool,
    color_space_defs: dict[str, str] | None = None,
    pattern_variants: dict[tuple[str, str, tuple[float, ...]], str] | None = None,
    pattern_space_ids: dict[str, str] | None = None,
) -> list[str]:
    if paint.kind == "PatternBase":
        return []
    if paint.kind == "DeviceRGB":
        try:
            r, g, b = paint.value
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid DeviceRGB paint value") from exc
        r = _quantize_color_component(float(r))
        g = _quantize_color_component(float(g))
        b = _quantize_color_component(float(b))
        op = "RG" if is_stroke else "rg"
        return [f"{_format_number(r)} {_format_number(g)} {_format_number(b)} {op}"]
    if paint.kind == "DeviceGray":
        value = paint.value
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise ValueError("invalid DeviceGray paint value")
            value = value[0]
        value = _quantize_color_component(float(value))
        op = "G" if is_stroke else "g"
        return [f"{_format_number(value)} {op}"]
    if paint.kind == "DeviceCMYK":
        try:
            c, m, y, k = paint.value
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid DeviceCMYK paint value") from exc
        # Keep PDF output visually aligned with PS->Image baselines by using
        # the same naive CMYK->RGB conversion as the raster path.
        r = 1.0 - min(1.0, float(c) + float(k))
        g = 1.0 - min(1.0, float(m) + float(k))
        b = 1.0 - min(1.0, float(y) + float(k))
        r = _quantize_color_component(r)
        g = _quantize_color_component(g)
        b = _quantize_color_component(b)
        op = "RG" if is_stroke else "rg"
        return [f"{_format_number(r)} {_format_number(g)} {_format_number(b)} {op}"]
    if paint.kind == "ColorSpace":
        if not isinstance(paint.value, ColorSpacePaint):
            raise ValueError("invalid ColorSpace paint value")
        op = "CS" if is_stroke else "cs"
        comp_op = "SCN" if is_stroke else "scn"
        components = " ".join(_format_number(value) for value in paint.value.components)
        return [f"/{paint.value.space_id} {op}", f"{components} {comp_op}"]
    if paint.kind == "Pattern":
        if not isinstance(paint.value, PatternPaint):
            raise ValueError("invalid Pattern paint value")
        if paint.value.base_space_id is None:
            op = "CS" if is_stroke else "cs"
            comp_op = "SCN" if is_stroke else "scn"
            return [f"/Pattern {op}", f"/{paint.value.pattern_id} {comp_op}"]
        op = "CS" if is_stroke else "cs"
        comp_op = "SCN" if is_stroke else "scn"
        if (
            pattern_variants is not None
            and paint.value.base_components is not None
        ):
            key = (
                paint.value.pattern_id,
                paint.value.base_space_id,
                tuple(paint.value.base_components),
            )
            variant_id = pattern_variants.get(key)
            if variant_id is not None:
                return [f"/Pattern {op}", f"/{variant_id} {comp_op}"]
        if pattern_space_ids is not None:
            pattern_space = pattern_space_ids.get(paint.value.base_space_id)
            if pattern_space is not None:
                components = " ".join(
                    _format_number(value) for value in (paint.value.base_components or tuple())
                )
                if components:
                    return [f"/{pattern_space} {op}", f"{components} /{paint.value.pattern_id} {comp_op}"]
                return [f"/{pattern_space} {op}", f"/{paint.value.pattern_id} {comp_op}"]
        base_components = paint.value.base_components or tuple()
        components = " ".join(_format_number(value) for value in base_components)
        base_space = None
        if color_space_defs is not None:
            base_space = color_space_defs.get(paint.value.base_space_id)
        if base_space is None:
            base_space = f"/{paint.value.base_space_id}"
        if components:
            return [
                f"[/Pattern {base_space}] {op}",
                f"{components} /{paint.value.pattern_id} {comp_op}",
            ]
        return [
            f"[/Pattern {base_space}] {op}",
            f"/{paint.value.pattern_id} {comp_op}",
        ]
    raise ValueError(f"unsupported paint kind: {paint.kind}")


def _resolve_font(font_ref: str) -> str:
    if font_ref in _STANDARD_FONTS:
        return font_ref
    return "Helvetica"


def _page_rect(page: RenderPage) -> RectWrapper:
    return RectWrapper(page.width, page.height)


def _format_number(value: float) -> str:
    if abs(value) < 1e-12:
        return "0"
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return str(int(rounded))
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text


def _quantize_color_component(value: float) -> float:
    value = max(0.0, min(1.0, float(value)))
    byte = int(value * 255.0)
    return byte / 255.0


@dataclass(frozen=True)
class RectWrapper:
    width: float
    height: float

    @property
    def x_min(self) -> float:
        return 0.0

    @property
    def y_min(self) -> float:
        return 0.0

    @property
    def x_max(self) -> float:
        return self.width

    @property
    def y_max(self) -> float:
        return self.height


def _validate_points(segment: PathSegment, expected: int) -> None:
    if len(segment.points) != expected:
        raise ValueError(f"invalid path segment '{segment.kind}' points")
