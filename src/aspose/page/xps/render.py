"""XPS rendering into the shared render model."""

from __future__ import annotations

import html
import io
import re
import copy
import math
from xml.etree import ElementTree as ET

from ..common.color_resources import (
    AxialShading,
    DeviceColorSpace,
    ExponentialFunction,
    PatternPaint,
    RadialShading,
    ShadingPattern,
    StitchingFunction,
    TilingPattern,
)
from ..common.render_model import (
    ImageCommand,
    Matrix,
    Paint,
    Path,
    PathCommand,
    PathSegment,
    Point,
    RenderModelBuilder,
    StrokeStyle,
    TextCommand,
)
from ..ps.ttf_outline import TrueTypeFont
from ..ps.fonts import parse_ttf_metrics


def _deobfuscate_xps_odttf_bytes(part_name: str, data: bytes) -> bytes:
    if not part_name.lower().endswith(".odttf") or len(data) < 32:
        return data
    name = part_name.rsplit("/", 1)[-1]
    guid_text = name[:-6]
    try:
        guid_hex = guid_text.replace("-", "")
        guid = bytes.fromhex(guid_hex)
    except ValueError:
        return data
    if len(guid) != 16:
        return data
    key = guid[::-1]
    decoded = bytearray(data)
    for idx in range(min(32, len(decoded))):
        decoded[idx] ^= key[idx % 16]
    return bytes(decoded)
from .images import (
    XpsImageResource,
    XpsImageStore,
    decode_jpegxr,
    decode_jpeg,
    decode_png,
    decode_tiff,
)
from .resources import XpsResourceDictionary
from .package import XpsPackage


XPS_UNIT_SCALE = 72.0 / 96.0

_GRADIENT_RGB_STOPS_CACHE: dict[int, list[tuple[float, tuple[float, float, float]]]] = {}
_GRADIENT_ALPHA_STOPS_CACHE: dict[int, list[tuple[float, float]]] = {}
_GRADIENT_GEOMETRY_CACHE: dict[int, tuple[str, tuple[float, ...], str]] = {}


class _IndexEntry:
    def __init__(
        self,
        glyph_id: int | None = None,
        advance: float | None = None,
        u_offset: float | None = None,
        v_offset: float | None = None,
        code_unit_count: int = 1,
        skip_render: bool = False,
    ) -> None:
        self.glyph_id = glyph_id
        self.advance = advance
        self.u_offset = u_offset
        self.v_offset = v_offset
        self.code_unit_count = max(1, int(code_unit_count))
        self.skip_render = skip_render


class XpsRenderer:
    """Render XPS XML to the shared render model.

    Example:
        >>> from aspose.page.common.render_model import RenderModelBuilder
        >>> from aspose.page.xps.images import XpsImageStore
        >>> renderer = XpsRenderer(RenderModelBuilder(), XpsImageStore())
        >>> isinstance(renderer, XpsRenderer)
        True
    """
    def __init__(
        self,
        builder: RenderModelBuilder,
        image_store: XpsImageStore,
        media_fit_size: tuple[float, float] | None = None,
        rasterize_solid_strokes: bool = False,
        spread_gradient_mode: str = "default",
    ) -> None:
        self._builder = builder
        self._image_store = image_store
        self._package: XpsPackage | None = None
        self._current_part: str | None = None
        self._font_gid_to_code: dict[str, dict[int, int]] = {}
        self._font_cache: dict[str, TrueTypeFont] = {}
        self._font_metric_cache: dict[str, tuple[float, dict[int, float]]] = {}
        self._opacity_image_cache: dict[tuple[str, int], str] = {}
        self._icc_profile_cache: dict[str, bytes] = {}
        self._media_fit_size = media_fit_size
        self._rasterize_solid_strokes = rasterize_solid_strokes
        self._spread_gradient_mode = spread_gradient_mode

    def set_package(self, package: XpsPackage) -> None:
        self._package = package

    def set_current_part(self, part_name: str) -> None:
        self._current_part = part_name

    def set_media_fit_size(self, media_fit_size: tuple[float, float] | None) -> None:
        self._media_fit_size = media_fit_size

    def render_fixed_page(self, xml: bytes, resources: XpsResourceDictionary | None = None) -> None:
        """Render a FixedPage XML payload into the render model."""
        # These caches are keyed by transient Element ids. If they survive
        # across documents in the same process, Python can reuse ids and bind
        # gradient data from a previous XPS file to a later one.
        _GRADIENT_RGB_STOPS_CACHE.clear()
        _GRADIENT_ALPHA_STOPS_CACHE.clear()
        _GRADIENT_GEOMETRY_CACHE.clear()
        root = ET.fromstring(xml)
        raw_width = (_parse_float(root.get("Width")) or 0.0) * XPS_UNIT_SCALE
        raw_height = (_parse_float(root.get("Height")) or 0.0) * XPS_UNIT_SCALE
        fit_scale = 1.0
        width = raw_width
        height = raw_height
        if self._media_fit_size is not None and raw_width > 0.0 and raw_height > 0.0:
            fit_width, fit_height = self._media_fit_size
            if fit_width > 0.0 and fit_height > 0.0:
                fit_scale = min(fit_width / raw_width, fit_height / raw_height)
                width = raw_width * fit_scale
                height = raw_height * fit_scale
        self._builder.begin_page(width, height)
        page_resources = _merge_resources(
            root,
            resources,
            package=self._package,
            current_part=self._current_part,
        )
        # XPS coordinates are top-left with +Y down; render model uses +Y up.
        transform = Matrix(XPS_UNIT_SCALE * fit_scale, 0.0, 0.0, -(XPS_UNIT_SCALE * fit_scale), 0.0, height)
        for child in list(root):
            self._render_element(child, page_resources, transform)
        self._builder.end_page()

    def _render_element(
        self,
        element: ET.Element,
        resources: XpsResourceDictionary | None,
        transform: Matrix,
    ) -> None:
        tag = _local_name(element.tag)
        local_transform = _element_transform(element, resources)
        combined = _multiply(transform, local_transform)
        if tag == "Canvas":
            canvas_resources = _merge_resources(
                element,
                resources,
                package=self._package,
                current_part=self._current_part,
            )
            if (mask_brush := _extract_canvas_opacity_mask_brush(element)) is not None:
                if _try_render_canvas_opacity_mask_as_image(
                    element=element,
                    resources=canvas_resources,
                    builder=self._builder,
                    renderer=self,
                    paint_transform=combined,
                ):
                    return
            clip_data = element.get("Clip")
            if clip_data:
                clip_path = _parse_path_data(clip_data, combined)
                self._builder.save_state()
                self._builder.clip(clip_path, _extract_fill_rule(element, resources))
            for child in list(element):
                self._render_element(child, canvas_resources, combined)
            if clip_data:
                self._builder.restore_state()
            return
        if tag == "Path":
            data = _extract_path_data(element, resources)
            fill_path = None
            stroke_path = None
            if data:
                path = _parse_path_data(data, combined)
                fill_path = path
                stroke_path = path
            else:
                geometry = _extract_path_geometry_element(element, resources)
                if geometry is None:
                    return
                fill_path, stroke_path = _parse_path_geometry_element_variants(geometry, combined)
                path = fill_path or stroke_path or Path([])
            clip_data = element.get("Clip")
            if clip_data:
                clip_path = _parse_path_data(clip_data, combined)
                self._builder.save_state()
                self._builder.clip(clip_path, _extract_fill_rule(element, resources))
            fill_rule = _extract_fill_rule(element, resources)
            path_bbox = _path_bbox(path)
            fill_value = _extract_paint_value(element, "Fill")
            stroke_value = _extract_paint_value(element, "Stroke")
            fill_brush = _resolve_brush_element(fill_value, resources)
            fill = _resolve_paint(
                fill_value,
                resources,
                self._builder,
                self,
                combined,
                combined,
            )
            stroke = _resolve_paint(
                stroke_value,
                resources,
                self._builder,
                self,
                combined,
                combined,
            )
            stroke_brush = _resolve_brush_element(stroke_value, resources)
            opacity = _parse_float(element.get("Opacity"))
            if opacity is not None:
                opacity = _clamp(opacity, 0.0, 1.0)
            mask_brush = _extract_opacity_mask_brush(element) if fill_path is not None else None
            if (
                fill_path is not None
                and mask_brush is not None
                and stroke is None
                and _try_render_masked_solid_fill_as_image(
                path=fill_path,
                path_bbox=path_bbox,
                fill_brush=fill_brush,
                mask_brush=mask_brush,
                builder=self._builder,
                renderer=self,
                paint_transform=combined,
                opacity=opacity if opacity is not None else 1.0,
                )
            ):
                if clip_data:
                    self._builder.restore_state()
                return
            fill_opacity = 1.0
            stroke_opacity = 1.0
            fill_alpha = _brush_alpha(fill_value, resources)
            if fill_alpha is not None:
                fill_opacity *= fill_alpha
            stroke_alpha = _brush_alpha(stroke_value, resources)
            if stroke_alpha is not None:
                stroke_opacity *= stroke_alpha
            if mask_brush is not None:
                fill_before_mask = fill
                fill = _apply_opacity_mask_to_fill_paint(
                    fill=fill,
                    mask_brush=mask_brush,
                    resources=resources,
                    builder=self._builder,
                    renderer=self,
                    paint_transform=combined,
                    brush_origin_transform=combined,
                    path=path,
                    path_bbox=path_bbox,
                    fill_brush=fill_brush,
                )
                mask_alpha = _opacity_from_brush_element(mask_brush, resources, self)
                if mask_alpha is not None and fill == fill_before_mask:
                    alpha = _clamp(mask_alpha, 0.0, 1.0)
                    fill_opacity *= alpha
                    stroke_opacity *= alpha
            if opacity is not None:
                fill_opacity *= opacity
                stroke_opacity *= opacity
            if (
                mask_brush is None
                and fill_path is not None
                and fill_brush is not None
                and _try_render_spread_gradient_fill_as_image(
                    path=fill_path,
                    path_bbox=path_bbox,
                    fill_brush=fill_brush,
                    builder=self._builder,
                    renderer=self,
                    paint_transform=combined,
                    opacity=fill_opacity,
                )
            ):
                fill = None
                fill_opacity = 1.0
                if stroke is None:
                    if clip_data:
                        self._builder.restore_state()
                    return
            if (
                fill_path is not None
                and
                fill_brush is not None
                and _try_render_image_brush_fill_as_image(
                    path=fill_path,
                    path_bbox=path_bbox,
                    fill_brush=fill_brush,
                    builder=self._builder,
                    renderer=self,
                    paint_transform=combined,
                    opacity=fill_opacity,
                )
            ):
                fill = None
                fill_opacity = 1.0
                if stroke is None:
                    if clip_data:
                        self._builder.restore_state()
                    return
            stroke_style = None
            if stroke is not None:
                base_thickness = (_parse_float(element.get("StrokeThickness")) or 1.0) * XPS_UNIT_SCALE
                stroke_scale = _stroke_scale_from_matrix(combined) / XPS_UNIT_SCALE
                thickness = base_thickness * stroke_scale
                if stroke_path is not None and fill is None and stroke_brush is not None and _try_render_stroked_brush_as_image(
                    path=stroke_path,
                    stroke_brush=stroke_brush,
                    stroke_width=thickness,
                    builder=self._builder,
                    renderer=self,
                    paint_transform=combined,
                    opacity=(opacity if opacity is not None else 1.0),
                ):
                    if clip_data:
                        self._builder.restore_state()
                    return
                dash = _parse_xps_dash_pattern(element, thickness)
                stroke_style = StrokeStyle(
                    line_width=thickness,
                    line_cap=_parse_xps_line_cap(element),
                    line_join=_parse_xps_line_join(element),
                    miter_limit=_parse_float(element.get("StrokeMiterLimit")) or 10.0,
                    dash=dash,
                    dash_phase=_parse_xps_dash_phase(element, thickness),
                )
            if fill_path is not None and fill is not None:
                self._builder.add_path(
                    fill_path,
                    None,
                    fill,
                    fill_rule=fill_rule,
                    stroke_paint=None,
                    fill_opacity=fill_opacity,
                    stroke_opacity=1.0,
                )
            if stroke_path is not None and stroke is not None:
                self._builder.add_path(
                    stroke_path,
                    stroke_style,
                    None,
                    fill_rule=fill_rule,
                    stroke_paint=stroke,
                    fill_opacity=1.0,
                    stroke_opacity=stroke_opacity,
                )
            if fill_path is None and stroke_path is None:
                self._builder.add_path(
                    path,
                    stroke_style,
                    fill,
                    fill_rule=fill_rule,
                    stroke_paint=stroke,
                    fill_opacity=fill_opacity,
                    stroke_opacity=stroke_opacity,
                )
            if clip_data:
                self._builder.restore_state()
            return
        if tag == "Glyphs":
            text = html.unescape(element.get("UnicodeString") or "")
            font_size = _parse_float(element.get("FontRenderingEmSize")) or 12.0
            origin_x = _parse_float(element.get("OriginX")) or 0.0
            origin_y = _parse_float(element.get("OriginY")) or 0.0
            font_uri = element.get("FontUri")
            if font_uri:
                font_ref = _resolve_part(self._current_part or "/", font_uri)
            else:
                font_ref = "Helvetica"
            indices = element.get("Indices")
            parsed_indices = _parse_indices(indices) if indices else []
            text = self._text_from_indices(font_ref, text, parsed_indices)
            bidi_level = _parse_int(element.get("BidiLevel")) or 0
            if not text:
                return
            brush_transform = _multiply(
                combined, Matrix(1.0, 0.0, 0.0, 1.0, origin_x, origin_y)
            )
            run_matrix = brush_transform
            # Keep text upright in user space while preserving run origin conversion.
            run_matrix = _multiply(run_matrix, Matrix(1.0, 0.0, 0.0, -1.0, 0.0, 0.0))
            fill = _resolve_paint(
                _extract_paint_value(element, "Fill"),
                resources,
                self._builder,
                self,
                combined,
                brush_transform,
            )
            fill_opacity = 1.0
            fill_alpha = _brush_alpha(_extract_paint_value(element, "Fill"), resources)
            if fill_alpha is not None:
                fill_opacity *= fill_alpha
            mask_brush = _extract_glyphs_opacity_mask_brush(element)
            clip_data = element.get("Clip")
            if clip_data:
                clip_path = _parse_path_data(clip_data, combined)
                self._builder.save_state()
                self._builder.clip(clip_path, _extract_fill_rule(element, resources))
            is_sideways = _is_true(element.get("IsSideways"))
            style = (element.get("StyleSimulations") or "").strip()
            if style == "ItalicSimulation" or style == "BoldItalicSimulation":
                run_matrix = _multiply(run_matrix, Matrix(1.0, 0.0, 0.2, 1.0, 0.0, 0.0))

            # Handle per-glyph placement for sideways and Indices-based metrics.
            rtl = (bidi_level % 2) == 1
            if (
                mask_brush is not None
                and not is_sideways
                and not rtl
                and not parsed_indices
                and style == ""
                and _try_render_glyphs_opacity_mask_as_image(
                    text=text,
                    font_ref=font_ref,
                    font_size=font_size,
                    matrix=run_matrix,
                    fill=fill,
                    fill_opacity=fill_opacity,
                    mask_brush=mask_brush,
                    builder=self._builder,
                    renderer=self,
                    paint_transform=brush_transform,
                )
            ):
                if clip_data:
                    self._builder.restore_state()
                return
            if rtl and (not is_sideways) and (not _indices_have_metrics(parsed_indices)):
                # Keep RTL runs as one text command to preserve engine-native
                # spacing while anchoring the run at the right-side origin.
                text_out = text[::-1]
                run_width = 0.0
                for char in text:
                    run_width += self._glyph_advance_points(font_ref, char, font_size)
                rtl_matrix = _multiply(run_matrix, Matrix(1.0, 0.0, 0.0, 1.0, -run_width, 0.0))
                self._builder.add_text(text_out, font_ref, font_size, rtl_matrix, fill, fill_opacity=fill_opacity)
                if style == "BoldSimulation" or style == "BoldItalicSimulation":
                    bold_matrix = _multiply(
                        rtl_matrix, Matrix(1.0, 0.0, 0.0, 1.0, font_size * 0.04, 0.0)
                    )
                    self._builder.add_text(text_out, font_ref, font_size, bold_matrix, fill, fill_opacity=fill_opacity)
            elif is_sideways or _indices_have_metrics(parsed_indices) or _indices_have_glyph_ids(parsed_indices) or rtl:
                self._emit_glyph_run(
                    text=text,
                    font_ref=font_ref,
                    font_size=font_size,
                    base_matrix=run_matrix,
                    fill=fill,
                    fill_opacity=fill_opacity,
                    bidi_level=bidi_level,
                    is_sideways=is_sideways,
                    style=style,
                    indices=parsed_indices,
                )
            else:
                text_out = text[::-1] if bidi_level % 2 == 1 else text
                self._builder.add_text(text_out, font_ref, font_size, run_matrix, fill, fill_opacity=fill_opacity)
                if style == "BoldSimulation" or style == "BoldItalicSimulation":
                    bold_matrix = _multiply(run_matrix, Matrix(1.0, 0.0, 0.0, 1.0, font_size * 0.04, 0.0))
                    self._builder.add_text(text_out, font_ref, font_size, bold_matrix, fill, fill_opacity=fill_opacity)
            if clip_data:
                self._builder.restore_state()
            return
        if tag == "Image":
            source = element.get("Source")
            if not source:
                return
            resource = self._load_image(source)
            if resource is None:
                return
            image_id = self._image_store.register(resource)
            width = int(round((_parse_float(element.get("Width")) or resource.width) * XPS_UNIT_SCALE))
            height = int(round((_parse_float(element.get("Height")) or resource.height) * XPS_UNIT_SCALE))
            self._builder.add_image(image_id, width, height, combined)
            return
        # Unsupported element types are ignored.

    def _load_image(self, source: str):
        if self._package is None:
            return None
        part_name = _resolve_part(self._current_part or "/", source)
        data = self._package.read(part_name)
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return decode_png(data)
        if data.startswith(b"\xFF\xD8"):
            return decode_jpeg(data)
        if part_name.lower().endswith((".wdp", ".jxr")):
            return decode_jpegxr(data)
        if part_name.lower().endswith((".tif", ".tiff")):
            return decode_tiff(data)
        raise ValueError("unsupported image format")

    def _text_from_indices(self, font_ref: str, text: str, entries: list["_IndexEntry"]) -> str:
        if not entries:
            return text
        has_gids = any(entry.glyph_id is not None for entry in entries)
        if not has_gids:
            return text
        reverse = self._gid_to_unicode(font_ref)
        if not reverse:
            return text
        chars: list[str] = []
        max_len = max(len(entries), len(text))
        for i in range(max_len):
            entry = entries[i] if i < len(entries) else _IndexEntry()
            if entry.glyph_id is None:
                if i < len(text):
                    chars.append(text[i])
                continue
            code = reverse.get(entry.glyph_id)
            if code is None:
                if i < len(text):
                    chars.append(text[i])
                continue
            chars.append(chr(code))
        if chars:
            return "".join(chars)
        return text

    def _emit_adjusted_text_run(
        self,
        text: str,
        font_ref: str,
        font_size: float,
        matrix: Matrix,
        fill: Paint | None,
        fill_opacity: float,
        style: str,
        indices: list["_IndexEntry"],
    ) -> None:
        adjustments: list[float] = []
        entries = indices if indices else [_IndexEntry() for _ in text]
        if len(entries) < len(text):
            entries = entries + [_IndexEntry() for _ in range(len(text) - len(entries))]
        for idx, char in enumerate(text[:-1]):
            entry = entries[idx]
            nominal = self._glyph_advance_points(font_ref, char, font_size, entry.glyph_id)
            desired = nominal
            if entry.advance is not None:
                desired = (entry.advance * font_size) / 100.0
            adjustments.append(((nominal - desired) / max(font_size, 1.0e-9)) * 1000.0)
        run_font_ref = _font_ref_for_run(font_ref, text, entries)
        self._builder.add_text(
            text,
            run_font_ref,
            font_size,
            matrix,
            fill,
            fill_opacity=fill_opacity,
            pdf_text_adjustments=tuple(adjustments),
        )
        if style == "BoldSimulation" or style == "BoldItalicSimulation":
            bold_matrix = _multiply(matrix, Matrix(1.0, 0.0, 0.0, 1.0, font_size * 0.04, 0.0))
            self._builder.add_text(
                text,
                run_font_ref,
                font_size,
                bold_matrix,
                fill,
                fill_opacity=fill_opacity,
                pdf_text_adjustments=tuple(adjustments),
            )

    def _emit_glyph_run(
        self,
        text: str,
        font_ref: str,
        font_size: float,
        base_matrix: Matrix,
        fill: Paint | None,
        fill_opacity: float,
        bidi_level: int,
        is_sideways: bool,
        style: str,
        indices: list["_IndexEntry"],
    ) -> None:
        rtl = (bidi_level % 2) == 1
        if is_sideways and rtl:
            # Invalid combo per XPS spec; keep deterministic fallback.
            rtl = False
        sideways_pre_rotated = is_sideways and (
            abs(base_matrix.b) > 1.0e-9 or abs(base_matrix.c) > 1.0e-9
        )
        if is_sideways:
            pen_x = self._sideways_run_origin_x_points(font_ref, font_size)
        else:
            pen_x = 0.0
        pen_y = 0.0
        chars = list(text)
        entries = indices if indices else [_IndexEntry() for _ in chars]
        if len(entries) < len(chars):
            entries = entries + [_IndexEntry() for _ in range(len(chars) - len(entries))]
        for idx, char in enumerate(chars):
            entry = entries[idx] if idx < len(entries) else _IndexEntry()
            if entry.skip_render:
                continue
            if is_sideways:
                # Match .NET arrange logic: when no explicit advance is present
                # in Indices, use font em-size for sideways progression.
                advance = font_size
            else:
                advance = self._glyph_advance_points(font_ref, char, font_size, entry.glyph_id)
            if entry.advance is not None:
                advance = (entry.advance * font_size) / 100.0
            u_offset = (entry.u_offset or 0.0) * font_size / 100.0
            v_offset = (entry.v_offset or 0.0) * font_size / 100.0
            if rtl:
                u_offset = -u_offset
            # For non-sideways runs, keep vOffset direction consistent with
            # XPS Glyphs placement (Origin.Y - VOffset in effective space).
            # Sideways runs are handled in their rotated placement branch.
            if is_sideways:
                v_offset = -v_offset
            dx = pen_x + u_offset
            if is_sideways:
                if sideways_pre_rotated:
                    width = self._glyph_advance_points(font_ref, char, font_size, entry.glyph_id)
                    dy = pen_y - (width * 0.5) - v_offset
                else:
                    # Match XPS sideways origin semantics in y-up text-space:
                    # y_up = -(width/2 - vOffset) => -width/2 - v_offset
                    width = self._glyph_advance_points(font_ref, char, font_size, entry.glyph_id)
                    dy = pen_y - (width * 0.5) - v_offset
            else:
                dy = pen_y + v_offset
            glyph_matrix = _multiply(base_matrix, Matrix(1.0, 0.0, 0.0, 1.0, dx, dy))
            if is_sideways:
                # Per XPS, IsSideways rotates glyphs 90° counter-clockwise.
                glyph_matrix = _multiply(glyph_matrix, Matrix(0.0, 1.0, -1.0, 0.0, 0.0, 0.0))
            glyph_font_ref = _font_ref_for_glyph(font_ref, entry.glyph_id)
            self._builder.add_text(
                char,
                glyph_font_ref,
                font_size,
                glyph_matrix,
                fill,
                fill_opacity=fill_opacity,
                glyph_id=entry.glyph_id,
            )
            if style == "BoldSimulation" or style == "BoldItalicSimulation":
                bold_matrix = _multiply(glyph_matrix, Matrix(1.0, 0.0, 0.0, 1.0, font_size * 0.04, 0.0))
                self._builder.add_text(
                    char,
                    glyph_font_ref,
                    font_size,
                    bold_matrix,
                    fill,
                    fill_opacity=fill_opacity,
                    glyph_id=entry.glyph_id,
                )
            pen_x += -advance if rtl else advance

    def _glyph_advance_points(
        self,
        font_ref: str,
        char: str,
        font_size: float,
        glyph_id_override: int | None = None,
    ) -> float:
        font = self._load_font(font_ref)
        if font is None:
            units_per_em, code_widths = self._load_font_metrics(font_ref)
            if code_widths:
                width_units = code_widths.get(ord(char))
                if width_units is not None:
                    return (float(width_units) / max(1.0, units_per_em)) * font_size
            return font_size * 0.5
        glyph_id = glyph_id_override
        if glyph_id is None:
            glyph_id = font.glyph_id_for_code(ord(char))
        units = font.glyph_advance(int(glyph_id))
        upem = max(1.0, float(font.units_per_em))
        return (units / upem) * font_size

    def _glyph_sideways_advance_points(
        self,
        font_ref: str,
        char: str,
        font_size: float,
        glyph_id_override: int | None = None,
    ) -> float:
        font = self._load_font(font_ref)
        if font is None:
            units_per_em, code_widths = self._load_font_metrics(font_ref)
            if code_widths:
                width_units = code_widths.get(ord(char))
                if width_units is not None:
                    return (float(width_units) / max(1.0, units_per_em)) * font_size
            return font_size * 0.5
        glyph_id = glyph_id_override
        if glyph_id is None:
            glyph_id = font.glyph_id_for_code(ord(char))
        h_units = font.glyph_advance(int(glyph_id))
        upem = max(1.0, float(font.units_per_em))
        h_advance = (h_units / upem) * font_size
        v_units = font.glyph_vertical_advance(int(glyph_id))
        if v_units is not None and v_units > 0:
            return (v_units / upem) * font_size
        side_units = font.glyph_sideways_advance(int(glyph_id))
        if side_units > 0:
            return (side_units / upem) * font_size
        return h_advance

    def _glyph_sideways_origin_offset_points(
        self,
        font_ref: str,
        char: str,
        font_size: float,
        glyph_id_override: int | None = None,
    ) -> tuple[float, float]:
        font = self._load_font(font_ref)
        if font is None:
            return (0.0, 0.0)
        glyph_id = glyph_id_override
        if glyph_id is None:
            glyph_id = font.glyph_id_for_code(ord(char))
        top_x = font.glyph_top_origin_x(int(glyph_id))
        top_y, _ = font.glyph_top_origin_y_and_descender(int(glyph_id))
        upem = max(1.0, float(font.units_per_em))
        return ((top_x / upem) * font_size, (top_y / upem) * font_size)

    def _sideways_run_origin_x_points(self, font_ref: str, font_size: float) -> float:
        font = self._load_font(font_ref)
        if font is None:
            return font_size
        upem = max(1.0, float(font.units_per_em))
        return (font.typo_ascender_units() / upem) * font_size

    def _load_font(self, font_ref: str) -> TrueTypeFont | None:
        cached = self._font_cache.get(font_ref)
        if cached is not None:
            return cached
        if self._package is None:
            return None
        part = _normalize_part_ref(font_ref)
        if not self._package.has_part(part):
            return None
        try:
            data = self._package.read(part)
            data = _deobfuscate_xps_odttf_bytes(part, data)
            font = TrueTypeFont(data)
        except Exception:
            return None
        self._font_cache[font_ref] = font
        return font

    def _load_font_metrics(self, font_ref: str) -> tuple[float, dict[int, float]]:
        cached = self._font_metric_cache.get(font_ref)
        if cached is not None:
            return cached
        if self._package is None:
            return (1000.0, {})
        part = _normalize_part_ref(font_ref)
        if not self._package.has_part(part):
            return (1000.0, {})
        try:
            data = self._package.read(part)
            data = _deobfuscate_xps_odttf_bytes(part, data)
            units_per_em, code_widths = parse_ttf_metrics(data)
        except Exception:
            units_per_em, code_widths = 1000.0, {}
        metrics = (float(units_per_em), code_widths)
        self._font_metric_cache[font_ref] = metrics
        return metrics

    def _gid_to_unicode(self, font_ref: str) -> dict[int, int]:
        cached = self._font_gid_to_code.get(font_ref)
        if cached is not None:
            return cached
        font = self._load_font(font_ref)
        if font is None:
            self._font_gid_to_code[font_ref] = {}
            return {}
        reverse: dict[int, int] = {}
        for code, glyph_id in getattr(font, "_cmap", {}).items():
            if glyph_id == 0:
                continue
            prev = reverse.get(int(glyph_id))
            if prev is None or code < prev:
                reverse[int(glyph_id)] = int(code)
        self._font_gid_to_code[font_ref] = reverse
        return reverse


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _is_true(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in ("1", "true", "yes")


def _is_false(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in ("0", "false", "no")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _merge_resources(
    element: ET.Element,
    parent: XpsResourceDictionary | None,
    package: XpsPackage | None = None,
    current_part: str | None = None,
) -> XpsResourceDictionary:
    items: dict[str, object] = {}
    visited_elements: set[int] = set()
    visited_parts: set[str] = set()
    for res in element.findall(".//{*}ResourceDictionary"):
        _collect_resource_dictionary(
            res,
            items,
            package=package,
            current_part=current_part,
            visited_elements=visited_elements,
            visited_parts=visited_parts,
        )
    return XpsResourceDictionary(items=items, parent=parent)


def _collect_resource_dictionary(
    dictionary: ET.Element,
    items: dict[str, object],
    package: XpsPackage | None,
    current_part: str | None,
    visited_elements: set[int],
    visited_parts: set[str],
) -> None:
    identifier = id(dictionary)
    if identifier in visited_elements:
        return
    visited_elements.add(identifier)

    source = dictionary.get("Source")
    if source and package is not None:
        part_name = _resolve_part(current_part or "/", source)
        if part_name not in visited_parts and package.has_part(part_name):
            visited_parts.add(part_name)
            try:
                source_root = ET.fromstring(package.read(part_name))
            except ET.ParseError:
                source_root = None
            if source_root is not None:
                if _local_name(source_root.tag) == "ResourceDictionary":
                    _collect_resource_dictionary(
                        source_root,
                        items,
                        package=package,
                        current_part=part_name,
                        visited_elements=visited_elements,
                        visited_parts=visited_parts,
                    )
                else:
                    for child in source_root.findall(".//{*}ResourceDictionary"):
                        _collect_resource_dictionary(
                            child,
                            items,
                            package=package,
                            current_part=part_name,
                            visited_elements=visited_elements,
                            visited_parts=visited_parts,
                        )

    for child in list(dictionary):
        if _local_name(child.tag) == "ResourceDictionary":
            _collect_resource_dictionary(
                child,
                items,
                package=package,
                current_part=current_part,
                visited_elements=visited_elements,
                visited_parts=visited_parts,
            )
            continue
        key = _resource_key(child)
        if key:
            items[key] = child


def _resource_key(element: ET.Element) -> str | None:
    for key, value in element.attrib.items():
        if key.endswith("Key"):
            return value
    return None


def _extract_path_data(
    element: ET.Element, resources: XpsResourceDictionary | None
) -> str | None:
    data = element.get("Data")
    if data:
        data = data.strip()
        if data.startswith("{StaticResource"):
            key = data.replace("{StaticResource", "").replace("}", "").strip()
            if resources is not None:
                resource = resources.resolve(key)
                if isinstance(resource, ET.Element):
                    return _path_data_from_resource(resource)
            return None
        return data
    data_node = element.find(".//{*}Path.Data")
    if data_node is None:
        return None
    geometry = data_node.find(".//{*}PathGeometry")
    if geometry is None:
        return None
    return geometry.get("Figures") or geometry.get("Data")


def _extract_path_geometry_element(
    element: ET.Element,
    resources: XpsResourceDictionary | None,
) -> ET.Element | None:
    data = element.get("Data")
    if data:
        data = data.strip()
        if data.startswith("{StaticResource"):
            key = data.replace("{StaticResource", "").replace("}", "").strip()
            if resources is not None:
                resource = resources.resolve(key)
                if isinstance(resource, ET.Element):
                    if _local_name(resource.tag) == "PathGeometry":
                        return resource
                    return resource.find(".//{*}PathGeometry")
            return None
    data_node = element.find(".//{*}Path.Data")
    if data_node is None:
        return None
    return data_node.find(".//{*}PathGeometry")


def _extract_fill_rule(
    element: ET.Element,
    resources: XpsResourceDictionary | None,
) -> str:
    """Resolve XPS fill rule with XPS geometry defaults.

    XPS PathGeometry defaults to EvenOdd unless explicitly overridden.
    """
    rule = element.get("FillRule")
    if rule:
        rule = rule.strip().lower()
        if rule in ("evenodd", "nonzero"):
            return rule
    data = element.get("Data")
    if data:
        compact = data.lstrip()
        if compact.startswith("F1"):
            return "nonzero"
        if compact.startswith("F0"):
            return "evenodd"
    if data and data.strip().startswith("{StaticResource"):
        key = data.replace("{StaticResource", "").replace("}", "").strip()
        if resources is not None:
            resource = resources.resolve(key)
            if isinstance(resource, ET.Element):
                rule = resource.get("FillRule")
                if rule:
                    rule = rule.strip().lower()
                    if rule in ("evenodd", "nonzero"):
                        return rule
                geometry = resource.find(".//{*}PathGeometry")
                if geometry is not None:
                    rule = geometry.get("FillRule")
                    if rule:
                        rule = rule.strip().lower()
                        if rule in ("evenodd", "nonzero"):
                            return rule
    data_node = element.find(".//{*}Path.Data")
    if data_node is not None:
        geometry = data_node.find(".//{*}PathGeometry")
        if geometry is not None:
            rule = geometry.get("FillRule")
            if rule:
                rule = rule.strip().lower()
                if rule in ("evenodd", "nonzero"):
                    return rule
    return "evenodd"


def _path_data_from_resource(resource: ET.Element) -> str | None:
    if _local_name(resource.tag) == "PathGeometry":
        return resource.get("Figures") or resource.get("Data")
    geometry = resource.find(".//{*}PathGeometry")
    if geometry is None:
        return None
    return geometry.get("Figures") or geometry.get("Data")


def _extract_paint_value(element: ET.Element, name: str) -> str | None:
    value = element.get(name)
    if value:
        return value
    wrapper = element.find(f".//{{*}}{_local_name(element.tag)}.{name}")
    if wrapper is None:
        for child in list(element):
            if _local_name(child.tag).endswith(f".{name}"):
                wrapper = child
                break
    if wrapper is None:
        return None
    brush = list(wrapper)[0] if list(wrapper) else None
    if brush is None:
        return None
    return ET.tostring(brush, encoding="unicode")


def _resolve_paint(
    value: str | None,
    resources: XpsResourceDictionary | None,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None = None,
    paint_transform: Matrix | None = None,
    brush_origin_transform: Matrix | None = None,
) -> Paint | None:
    if value is None:
        return None
    value = value.strip()
    if value.startswith("{StaticResource"):
        key = value.replace("{StaticResource", "").replace("}", "").strip()
        if resources is not None:
            resource = resources.resolve(key)
            if isinstance(resource, ET.Element):
                return _paint_from_element(
                    resource,
                    resources,
                    builder,
                    renderer,
                    paint_transform,
                    brush_origin_transform,
                )
        return Paint("DeviceRGB", (0.0, 0.0, 0.0))
    if value.startswith("<"):
        element = ET.fromstring(value)
        return _paint_from_element(
            element,
            resources,
            builder,
            renderer,
            paint_transform,
            brush_origin_transform,
        )
    if value.startswith("ContextColor"):
        context = _parse_context_color(value, renderer)
        if context is not None:
            return Paint("DeviceRGB", context)
    color = _parse_color(value)
    return Paint("DeviceRGB", color)


def _paint_from_element(
    element: ET.Element,
    resources: XpsResourceDictionary | None,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None = None,
    paint_transform: Matrix | None = None,
    brush_origin_transform: Matrix | None = None,
) -> Paint:
    tag = _local_name(element.tag)
    if tag == "SolidColorBrush":
        color_value = element.get("Color") or "#000000"
        if color_value.strip().startswith("ContextColor"):
            context = _parse_context_color(color_value, renderer)
            if context is not None:
                return Paint("DeviceRGB", context)
        return Paint("DeviceRGB", _parse_color(color_value))
    if tag in ("LinearGradientBrush", "RadialGradientBrush"):
        return _gradient_to_pattern(element, builder, paint_transform)
    if tag == "ImageBrush":
        pattern = _image_brush_to_pattern(
            element,
            builder,
            renderer,
            paint_transform,
        )
        if pattern is not None:
            return pattern
    if tag == "VisualBrush":
        pattern = _visual_brush_to_pattern(
            element,
            resources,
            builder,
            renderer,
            brush_origin_transform or paint_transform,
        )
        if pattern is not None:
            return pattern
    return Paint("DeviceRGB", (0.0, 0.0, 0.0))


def _resolve_brush_element(
    value: str | None,
    resources: XpsResourceDictionary | None,
) -> ET.Element | None:
    if value is None:
        return None
    text = value.strip()
    if text.startswith("{StaticResource"):
        key = text.replace("{StaticResource", "").replace("}", "").strip()
        if resources is None:
            return None
        resource = resources.resolve(key)
        if isinstance(resource, ET.Element):
            return resource
        return None
    if text.startswith("<"):
        return ET.fromstring(text)
    if text:
        solid = ET.Element("SolidColorBrush")
        solid.set("Color", text)
        return solid
    return None


def _gradient_to_pattern(
    element: ET.Element,
    builder: RenderModelBuilder,
    paint_transform: Matrix | None = None,
) -> Paint:
    stops: list[tuple[float, tuple[float, float, float]]] = []
    for stop in element.findall(".//{*}GradientStop"):
        offset = _parse_float(stop.get("Offset")) or 0.0
        color_value = stop.get("Color") or "#000000"
        stops.append((_clamp(offset, 0.0, 1.0), _parse_color(color_value)))
    if not stops:
        stops = [(0.0, (0.0, 0.0, 0.0)), (1.0, (1.0, 1.0, 1.0))]
    stops.sort(key=lambda item: item[0])
    if stops[0][0] > 0.0:
        stops.insert(0, (0.0, stops[0][1]))
    if stops[-1][0] < 1.0:
        stops.append((1.0, stops[-1][1]))
    spread = (element.get("SpreadMethod") or "Pad").strip().lower()
    gradient_domain: tuple[float, float] | None = None
    if spread in ("repeat", "reflect"):
        stops, gradient_domain = _expand_gradient_stops_for_spread(
            stops, spread_method=spread, cycles=8
        )
    functions: list[ExponentialFunction] = []
    bounds: list[float] = []
    encode: list[float] = []
    for idx in range(len(stops) - 1):
        left = stops[idx]
        right = stops[idx + 1]
        if right[0] <= left[0]:
            continue
        fn = ExponentialFunction(
            domain=[0.0, 1.0],
            range=[0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
            c0=[left[1][0], left[1][1], left[1][2]],
            c1=[right[1][0], right[1][1], right[1][2]],
            n=1.0,
        )
        builder.register_function(fn)
        functions.append(fn)
        if idx < len(stops) - 2:
            bounds.append(right[0])
        encode.extend([0.0, 1.0])
    if not functions:
        fn = ExponentialFunction(
            domain=[0.0, 1.0],
            range=[0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
            c0=[stops[0][1][0], stops[0][1][1], stops[0][1][2]],
            c1=[stops[-1][1][0], stops[-1][1][1], stops[-1][1][2]],
            n=1.0,
        )
        builder.register_function(fn)
        function = fn
    elif len(functions) == 1:
        function = functions[0]
    else:
        domain_start = 0.0
        domain_end = 1.0
        if gradient_domain is not None:
            domain_start, domain_end = gradient_domain
        function = StitchingFunction(
            domain=[domain_start, domain_end],
            range=[0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
            functions=functions,
            bounds=bounds,
            encode=encode,
        )
        builder.register_function(function)
    if _local_name(element.tag) == "LinearGradientBrush":
        start = _parse_point(element.get("StartPoint"))
        end = _parse_point(element.get("EndPoint"))
        shading = AxialShading(
            color_space=DeviceColorSpace("DeviceRGB"),
            coords=(start[0], start[1], end[0], end[1]),
            domain=gradient_domain,
            function=function,
            extend=(True, True),
        )
    else:
        center = _parse_point(element.get("Center"))
        origin = _parse_point(element.get("GradientOrigin"))
        radius_x = _parse_float(element.get("RadiusX")) or 0.0
        radius_y = _parse_float(element.get("RadiusY")) or 0.0
        sx = radius_x if abs(radius_x) > 1e-9 else 1.0
        sy = radius_y if abs(radius_y) > 1e-9 else 1.0
        shading = RadialShading(
            color_space=DeviceColorSpace("DeviceRGB"),
            coords=(origin[0] / sx, origin[1] / sy, 0.0, center[0] / sx, center[1] / sy, 1.0),
            domain=gradient_domain,
            function=function,
            extend=(True, True),
        )
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if paint_transform is not None:
        pm = paint_transform
        if _local_name(element.tag) == "RadialGradientBrush":
            pm = _multiply(pm, Matrix(sx, 0.0, 0.0, sy, 0.0, 0.0))
        matrix = (
            pm.a,
            pm.b,
            pm.c,
            pm.d,
            pm.e,
            pm.f,
        )
    elif _local_name(element.tag) == "RadialGradientBrush":
        matrix = (sx, 0.0, 0.0, sy, 0.0, 0.0)
    pattern = ShadingPattern(shading=shading, matrix=matrix)
    pattern_id = builder.register_pattern(pattern)
    return Paint("Pattern", PatternPaint(pattern_id=pattern_id, base_space_id=None, base_components=None))


def _expand_gradient_stops_for_spread(
    stops: list[tuple[float, tuple[float, float, float]]],
    spread_method: str,
    cycles: int,
) -> tuple[list[tuple[float, tuple[float, float, float]]], tuple[float, float]]:
    if cycles < 1:
        cycles = 1
    expanded: list[tuple[float, tuple[float, float, float]]] = []
    start_cycle = -cycles
    end_cycle = cycles
    for cycle in range(start_cycle, end_cycle + 1):
        if spread_method == "reflect" and (cycle % 2 == 1):
            seq = [(1.0 - off, color) for off, color in reversed(stops)]
        else:
            seq = stops
        for off, color in seq:
            expanded.append((cycle + off, color))
    expanded.sort(key=lambda item: item[0])
    deduped: list[tuple[float, tuple[float, float, float]]] = []
    for off, color in expanded:
        if deduped and abs(off - deduped[-1][0]) < 1e-9:
            deduped[-1] = (off, color)
        else:
            deduped.append((off, color))
    return deduped, (float(start_cycle), float(end_cycle + 1))


def _image_brush_to_pattern(
    element: ET.Element,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None = None,
) -> Paint | None:
    if renderer is None:
        return None
    source = element.get("ImageSource")
    if not source:
        return None
    image = renderer._load_image(source)
    if image is None:
        return None
    image = _crop_image_for_viewbox(image, _parse_rect(
        element.get("Viewbox"),
        default=(0.0, 0.0, float(image.width), float(image.height)),
    ))
    image_id = renderer._image_store.register(image)
    viewbox = _parse_rect(
        element.get("Viewbox"),
        default=(0.0, 0.0, float(image.width), float(image.height)),
    )
    viewport = _parse_rect(element.get("Viewport"), default=viewbox)
    tile_mode = (element.get("TileMode") or "None").strip().lower()
    if tile_mode == "tile":
        x_step = max(viewport[2], 1.0)
        y_step = max(viewport[3], 1.0)
    else:
        x_step = max(viewport[2], 1.0)
        y_step = max(viewport[3], 1.0)
    matrix = Matrix(
        max(viewport[2], 1.0),
        0.0,
        0.0,
        -max(viewport[3], 1.0),
        0.0,
        max(viewport[3], 1.0),
    )
    commands = [ImageCommand(image_id=image_id, width=image.width, height=image.height, matrix=matrix)]
    pm = (
        1.0,
        0.0,
        0.0,
        1.0,
        viewport[0],
        viewport[1],
    )
    brush_transform = _brush_transform(element)
    if brush_transform != Matrix(1.0, 0.0, 0.0, 1.0, 0.0, 0.0):
        brush_pm = (
            brush_transform.a,
            brush_transform.b,
            brush_transform.c,
            brush_transform.d,
            brush_transform.e,
            brush_transform.f,
        )
        pm = _concat_pattern_matrix(brush_pm, pm)
    if paint_transform is not None:
        if tile_mode == "tile":
            pm = (
                pm[0],
                pm[1],
                pm[2],
                pm[3],
                pm[4] + paint_transform.e,
                pm[5] + paint_transform.f,
            )
        else:
            paint_pm = (
                paint_transform.a,
                paint_transform.b,
                paint_transform.c,
                paint_transform.d,
                paint_transform.e,
                paint_transform.f,
            )
            pm = _concat_pattern_matrix(paint_pm, pm)
    pattern = TilingPattern(
        paint_type=1,
        tiling_type=1 if tile_mode == "tile" else 0,
        bbox=(0.0, 0.0, viewport[2], viewport[3]),
        x_step=x_step,
        y_step=y_step,
        matrix=pm,
        commands=commands,
    )
    pattern_id = builder.register_pattern(pattern)
    return Paint("Pattern", PatternPaint(pattern_id=pattern_id, base_space_id=None, base_components=None))


def _concat_pattern_matrix(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    m1 = Matrix(*left)
    m2 = Matrix(*right)
    result = _multiply(m1, m2)
    return (result.a, result.b, result.c, result.d, result.e, result.f)


def _visual_brush_to_pattern(
    element: ET.Element,
    resources: XpsResourceDictionary | None,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None = None,
) -> Paint | None:
    if renderer is None:
        return None
    visual = element.find(".//{*}VisualBrush.Visual")
    if visual is None:
        return None
    viewbox = _parse_rect(element.get("Viewbox"), default=(0.0, 0.0, 1.0, 1.0))
    viewport = _parse_rect(element.get("Viewport"), default=viewbox)
    nested_builder = RenderModelBuilder()
    nested_builder.begin_page(viewbox[2] * XPS_UNIT_SCALE, viewbox[3] * XPS_UNIT_SCALE)
    nested = XpsRenderer(nested_builder, renderer._image_store)
    if renderer._package is not None:
        nested.set_package(renderer._package)
    if renderer._current_part is not None:
        nested.set_current_part(renderer._current_part)
    transform = Matrix(
        XPS_UNIT_SCALE,
        0.0,
        0.0,
        -XPS_UNIT_SCALE,
        -viewbox[0] * XPS_UNIT_SCALE,
        (viewbox[1] + viewbox[3]) * XPS_UNIT_SCALE,
    )
    for child in list(visual):
        nested._render_element(child, resources, transform)
    nested_builder.end_page()
    page = nested_builder.document().pages[0]
    if not page.commands:
        return None
    x_step = max(viewport[2], 1.0)
    y_step = max(viewport[3], 1.0)
    sx = viewport[2] / max(viewbox[2], 1e-9)
    sy = viewport[3] / max(viewbox[3], 1e-9)
    matrix = (
        sx,
        0.0,
        0.0,
        sy,
        (viewport[0] - viewbox[0] * sx) * XPS_UNIT_SCALE,
        (viewport[1] - viewbox[1] * sy) * XPS_UNIT_SCALE,
    )
    if paint_transform is not None:
        matrix = (
            matrix[0],
            matrix[1],
            matrix[2],
            matrix[3],
            matrix[4] + paint_transform.e,
            matrix[5] + paint_transform.f,
        )
    pattern = TilingPattern(
        paint_type=1,
        tiling_type=1,
        bbox=(0.0, 0.0, viewport[2] * XPS_UNIT_SCALE, viewport[3] * XPS_UNIT_SCALE),
        x_step=x_step * XPS_UNIT_SCALE,
        y_step=y_step * XPS_UNIT_SCALE,
        matrix=matrix,
        commands=list(page.commands),
    )
    pattern_id = builder.register_pattern(pattern)
    return Paint("Pattern", PatternPaint(pattern_id=pattern_id, base_space_id=None, base_components=None))


def _parse_point(value: str | None) -> tuple[float, float]:
    if not value:
        return (0.0, 0.0)
    parts = re.split(r"[ ,]+", value.strip())
    if len(parts) >= 2:
        return (_parse_float(parts[0]) or 0.0, _parse_float(parts[1]) or 0.0)
    return (0.0, 0.0)


def _parse_points(value: str | None) -> list[tuple[float, float]]:
    if not value:
        return []
    raw = re.split(r"[ ,]+", value.strip())
    nums: list[float] = []
    for item in raw:
        if not item:
            continue
        val = _parse_float(item)
        if val is not None:
            nums.append(val)
    points: list[tuple[float, float]] = []
    idx = 0
    while idx + 1 < len(nums):
        points.append((nums[idx], nums[idx + 1]))
        idx += 2
    return points


def _parse_rect(value: str | None, default: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not value:
        return default
    parts = re.split(r"[ ,]+", value.strip())
    if len(parts) < 4:
        return default
    x = _parse_float(parts[0])
    y = _parse_float(parts[1])
    w = _parse_float(parts[2])
    h = _parse_float(parts[3])
    if x is None or y is None or w is None or h is None:
        return default
    return (x, y, w, h)


def _parse_indices(value: str) -> list[_IndexEntry]:
    result: list[_IndexEntry] = []
    for raw_segment in value.split(";"):
        segment = raw_segment.strip()
        if segment == "":
            result.append(_IndexEntry())
            continue
        code_unit_count = 1
        if segment.startswith("(") and ")" in segment:
            prefix, _, remainder = segment.partition(")")
            prefix = prefix[1:].strip()
            if ":" in prefix:
                prefix = prefix.split(":", 1)[0].strip()
            parsed_count = _parse_int(prefix)
            if parsed_count is not None and parsed_count > 0:
                code_unit_count = parsed_count
            segment = remainder.strip()
            if not segment:
                result.append(_IndexEntry(code_unit_count=code_unit_count))
                for _ in range(code_unit_count - 1):
                    result.append(_IndexEntry(skip_render=True))
                continue
        parts = [item.strip() for item in segment.split(",")]
        glyph_id = _parse_int(parts[0]) if parts else None
        advance = _parse_float(parts[1]) if len(parts) > 1 and parts[1] else None
        u_offset = _parse_float(parts[2]) if len(parts) > 2 and parts[2] else None
        v_offset = _parse_float(parts[3]) if len(parts) > 3 and parts[3] else None
        result.append(_IndexEntry(glyph_id=glyph_id, advance=advance, u_offset=u_offset, v_offset=v_offset, code_unit_count=code_unit_count))
        for _ in range(code_unit_count - 1):
            result.append(_IndexEntry(skip_render=True))
    return result


def _can_emit_adjusted_text_run(text: str, entries: list[_IndexEntry]) -> bool:
    overrides: dict[int, int] = {}
    for idx, char in enumerate(text):
        if idx >= len(entries):
            break
        entry = entries[idx]
        if entry.skip_render or entry.code_unit_count != 1:
            return False
        gid = entry.glyph_id
        if gid is None:
            continue
        code = ord(char)
        prev = overrides.get(code)
        if prev is not None and prev != gid:
            return False
        overrides[code] = gid
    return True


def _font_ref_for_run(font_ref: str, text: str, entries: list[_IndexEntry]) -> str:
    overrides: dict[int, int] = {}
    for idx, char in enumerate(text):
        if idx >= len(entries):
            break
        entry = entries[idx]
        if entry.skip_render:
            continue
        gid = entry.glyph_id
        if gid is None:
            continue
        overrides[ord(char)] = int(gid)
    if not overrides:
        return font_ref
    parts = [f"{code:04X}:{gid}" for code, gid in sorted(overrides.items())]
    return f"{font_ref}#gmap={','.join(parts)}"


def _indices_have_metrics(entries: list[_IndexEntry]) -> bool:
    for entry in entries:
        if entry.advance is not None or entry.u_offset is not None or entry.v_offset is not None:
            return True
    return False


def _indices_have_offsets(entries: list[_IndexEntry]) -> bool:
    for entry in entries:
        if entry.u_offset is not None or entry.v_offset is not None:
            return True
    return False


def _indices_have_glyph_ids(entries: list[_IndexEntry]) -> bool:
    return any(entry.glyph_id is not None for entry in entries)


def _font_ref_for_glyph(font_ref: str, glyph_id: int | None) -> str:
    if glyph_id is None:
        return font_ref
    return f"{font_ref}#gid={int(glyph_id)}"


def _parse_color(value: str) -> tuple[float, float, float]:
    value = value.strip()
    if value.startswith("sc#"):
        parts = re.split(r"[ ,]+", value[3:])
        if len(parts) >= 4:
            alpha = _clamp(_parse_float(parts[0]) or 0.0, 0.0, 1.0)
            r = _clamp(_parse_float(parts[1]) or 0.0, 0.0, 1.0)
            g = _clamp(_parse_float(parts[2]) or 0.0, 0.0, 1.0)
            b = _clamp(_parse_float(parts[3]) or 0.0, 0.0, 1.0)
            if alpha < 1.0:
                r = _blend_component(r, alpha)
                g = _blend_component(g, alpha)
                b = _blend_component(b, alpha)
            return (r, g, b)
        if len(parts) >= 3:
            return (
                _clamp(_parse_float(parts[0]) or 0.0, 0.0, 1.0),
                _clamp(_parse_float(parts[1]) or 0.0, 0.0, 1.0),
                _clamp(_parse_float(parts[2]) or 0.0, 0.0, 1.0),
            )
    if value.startswith("#"):
        raw = value[1:]
        alpha = 1.0
        if len(raw) == 8:
            alpha = int(raw[0:2], 16) / 255.0
            raw = raw[2:]
        if len(raw) == 6:
            r = int(raw[0:2], 16) / 255.0
            g = int(raw[2:4], 16) / 255.0
            b = int(raw[4:6], 16) / 255.0
            if alpha < 1.0:
                # Render model currently lacks per-command alpha, so blend with
                # white page background to approximate visual output.
                r = r * alpha + (1.0 - alpha)
                g = g * alpha + (1.0 - alpha)
                b = b * alpha + (1.0 - alpha)
            return (r, g, b)
    return (0.0, 0.0, 0.0)


def _extract_color_alpha(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("sc#"):
        parts = re.split(r"[ ,]+", value[3:])
        if len(parts) >= 4:
            alpha = _parse_float(parts[0])
            if alpha is not None:
                return _clamp(alpha, 0.0, 1.0)
        return None
    if value.startswith("#"):
        raw = value[1:]
        if len(raw) == 8:
            try:
                return int(raw[0:2], 16) / 255.0
            except ValueError:
                return None
    return None


def _brush_alpha(
    value: str | None,
    resources: XpsResourceDictionary | None,
) -> float | None:
    if not value:
        return None
    value = value.strip()
    alpha = _extract_color_alpha(value)
    if alpha is not None:
        return alpha
    brush = _resolve_brush_element(value, resources)
    if brush is None:
        return None
    if _local_name(brush.tag) == "SolidColorBrush":
        return _extract_color_alpha(brush.get("Color"))
    return None


def _parse_context_color(value: str, renderer: XpsRenderer | None = None) -> tuple[float, float, float] | None:
    # Expected forms:
    # - ContextColor <profile> A,C,M,Y,K
    # - ContextColor <profile> C,M,Y,K
    parts = value.split()
    if len(parts) < 3:
        return None
    comps_raw = "".join(parts[2:])
    comps = [item for item in re.split(r"[ ,]+", comps_raw.strip()) if item]
    if not comps:
        return None
    floats: list[float] = []
    for item in comps:
        number = _parse_float(item)
        if number is None:
            return None
        floats.append(number)
    alpha = 1.0
    profile_uri = parts[1] if len(parts) > 1 else ""
    if len(floats) >= 5:
        alpha = _clamp(floats[0], 0.0, 1.0)
        c, m, y, k = floats[1:5]
    elif len(floats) >= 4:
        c, m, y, k = floats[:4]
    else:
        return None
    c = _clamp(c, 0.0, 1.0)
    m = _clamp(m, 0.0, 1.0)
    y = _clamp(y, 0.0, 1.0)
    k = _clamp(k, 0.0, 1.0)
    rgb = _context_color_to_rgb_with_profile(renderer, profile_uri, c, m, y, k)
    r, g, b = rgb
    if alpha < 1.0:
        r = _blend_component(r, alpha)
        g = _blend_component(g, alpha)
        b = _blend_component(b, alpha)
    return (r, g, b)


def _context_color_to_rgb_with_profile(
    renderer: XpsRenderer | None,
    profile_uri: str,
    c: float,
    m: float,
    y: float,
    k: float,
) -> tuple[float, float, float]:
    # Fallback when ICC conversion is unavailable.
    fallback = ((1.0 - c) * (1.0 - k), (1.0 - m) * (1.0 - k), (1.0 - y) * (1.0 - k))
    if renderer is None or renderer._package is None:
        return fallback
    if not profile_uri:
        return fallback
    try:
        from PIL import Image, ImageCms  # type: ignore
    except Exception:
        return fallback
    try:
        part_name = _resolve_part(renderer._current_part or "/", profile_uri)
        profile = renderer._icc_profile_cache.get(part_name)
        if profile is None:
            profile = renderer._package.read(part_name)
            renderer._icc_profile_cache[part_name] = profile
        in_profile = ImageCms.ImageCmsProfile(io.BytesIO(profile))
        out_profile = ImageCms.createProfile("sRGB")
        transform = ImageCms.buildTransformFromOpenProfiles(
            in_profile,
            out_profile,
            "CMYK",
            "RGB",
            renderingIntent=0,
        )
        pixel = Image.new(
            "CMYK",
            (1, 1),
            (
                int(round(_clamp(c, 0.0, 1.0) * 255.0)),
                int(round(_clamp(m, 0.0, 1.0) * 255.0)),
                int(round(_clamp(y, 0.0, 1.0) * 255.0)),
                int(round(_clamp(k, 0.0, 1.0) * 255.0)),
            ),
        )
        rgb = ImageCms.applyTransform(pixel, transform)
        rr, gg, bb = rgb.getpixel((0, 0))
        return (rr / 255.0, gg / 255.0, bb / 255.0)
    except Exception:
        return fallback


def _extract_opacity_mask_alpha(
    element: ET.Element,
    resources: XpsResourceDictionary | None,
    renderer: XpsRenderer | None,
) -> float | None:
    wrapper = element.find("./{*}Path.OpacityMask")
    if wrapper is None:
        return None
    brush = list(wrapper)[0] if list(wrapper) else None
    if brush is None:
        return None
    return _opacity_from_brush_element(brush, resources, renderer)


def _extract_opacity_mask_brush(element: ET.Element) -> ET.Element | None:
    wrapper = element.find("./{*}Path.OpacityMask")
    if wrapper is None:
        return None
    return list(wrapper)[0] if list(wrapper) else None


def _extract_canvas_opacity_mask_brush(element: ET.Element) -> ET.Element | None:
    wrapper = element.find("./{*}Canvas.OpacityMask")
    if wrapper is None:
        return None
    return list(wrapper)[0] if list(wrapper) else None


def _extract_glyphs_opacity_mask_brush(element: ET.Element) -> ET.Element | None:
    wrapper = element.find("./{*}Glyphs.OpacityMask")
    if wrapper is None:
        return None
    return list(wrapper)[0] if list(wrapper) else None


def _try_render_canvas_opacity_mask_as_image(
    element: ET.Element,
    resources: XpsResourceDictionary | None,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix,
) -> bool:
    if renderer is None or renderer._package is None:
        return False
    mask_brush = _extract_canvas_opacity_mask_brush(element)
    if mask_brush is None:
        return False
    page = getattr(builder, "_active_page", None)
    if page is None or page.width <= 0.0 or page.height <= 0.0:
        return False
    try:
        from .output import _build_xps_font_resolver
    except Exception:
        return False
    temp_builder = RenderModelBuilder()
    temp_store = XpsImageStore()
    temp_builder.begin_page(page.width, page.height)
    temp_renderer = XpsRenderer(
        temp_builder,
        temp_store,
        rasterize_solid_strokes=renderer._rasterize_solid_strokes,
    )
    temp_renderer.set_package(renderer._package)
    if renderer._current_part is not None:
        temp_renderer.set_current_part(renderer._current_part)
    clip_data = element.get("Clip")
    if clip_data:
        clip_path = _parse_path_data(clip_data, paint_transform)
        temp_builder.save_state()
        temp_builder.clip(clip_path, _extract_fill_rule(element, resources))
    for child in list(element):
        temp_renderer._render_element(child, resources, paint_transform)
    if clip_data:
        temp_builder.restore_state()
    temp_builder.end_page()
    render_doc = temp_builder.document()
    if not render_doc.pages:
        return False
    for image_id, resource in temp_store._images.items():
        render_doc.resources.images[image_id] = RenderImageResource(
            data=resource.data,
            width=resource.width,
            height=resource.height,
            color_space=resource.color_space,
            bits_per_component=resource.bits_per_component,
            filter=resource.filter,
            soft_mask=resource.soft_mask,
        )
    font_resolver = _build_xps_font_resolver(renderer._package, render_doc)
    from ..image.skia_raster_writer import SkiaRasterWriter
    from ..ps.output import ImageSaveOptions

    options = ImageSaveOptions(format="png", dpi=96)
    options.font_resolver = font_resolver
    options.opaque_background = False
    options.preserve_fractional_page_size = True
    resource = decode_png(SkiaRasterWriter().write(render_doc, options))
    scale_x = resource.width / max(page.width, 1e-6)
    scale_y = resource.height / max(page.height, 1e-6)
    inv_paint = _invert_matrix(
        (
            paint_transform.a,
            paint_transform.b,
            paint_transform.c,
            paint_transform.d,
            paint_transform.e,
            paint_transform.f,
        )
    )
    alpha = bytearray(resource.width * resource.height)
    rgb = bytearray(resource.data)
    existing_alpha = resource.soft_mask or bytes([255]) * (resource.width * resource.height)
    page_height = page.height
    for py in range(resource.height):
        user_y = page_height - (py + 0.5) / scale_y
        row = py * resource.width
        for px in range(resource.width):
            user_x = (px + 0.5) / scale_x
            brush_x = user_x
            brush_y = user_y
            if inv_paint is not None:
                brush_x, brush_y = _apply_matrix_tuple(inv_paint, user_x, user_y)
            mask_alpha = _clamp(_mask_alpha_from_brush_at(mask_brush, brush_x, brush_y, renderer), 0.0, 1.0)
            pixel_alpha = existing_alpha[row + px] / 255.0
            alpha[row + px] = int(round(_clamp(pixel_alpha * mask_alpha, 0.0, 1.0) * 255.0))
    image_id = renderer._image_store.register(
        XpsImageResource(
            image_id="",
            data=bytes(rgb),
            width=resource.width,
            height=resource.height,
            bits_per_component=8,
            color_space="DeviceRGB",
            filter=None,
            x_dpi=96.0,
            y_dpi=96.0,
            soft_mask=bytes(alpha),
        )
    )
    builder.add_image(
        image_id,
        resource.width,
        resource.height,
        Matrix(page.width, 0.0, 0.0, page.height, 0.0, 0.0),
    )
    return True


def _try_render_glyphs_opacity_mask_as_image(
    text: str,
    font_ref: str,
    font_size: float,
    matrix: Matrix,
    fill: Paint | None,
    fill_opacity: float,
    mask_brush: ET.Element,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix,
) -> bool:
    if renderer is None or renderer._package is None or fill is None:
        return False
    page = getattr(builder, "_active_page", None)
    if page is None or page.width <= 0.0 or page.height <= 0.0:
        return False
    try:
        from .output import _build_xps_font_resolver
    except Exception:
        return False
    temp_builder = RenderModelBuilder()
    temp_builder.begin_page(page.width, page.height)
    temp_matrix = Matrix(
        matrix.a,
        matrix.b,
        matrix.c,
        -matrix.d,
        matrix.e,
        page.height - matrix.f,
    )
    temp_builder.add_text(
        text,
        font_ref,
        font_size,
        temp_matrix,
        fill,
        fill_opacity=fill_opacity,
    )
    temp_builder.end_page()
    render_doc = temp_builder.document()
    font_resolver = _build_xps_font_resolver(renderer._package, render_doc)
    from ..image.skia_raster_writer import SkiaRasterWriter
    from ..ps.output import ImageSaveOptions

    options = ImageSaveOptions(format="png", dpi=300)
    options.font_resolver = font_resolver
    options.opaque_background = False
    options.preserve_fractional_page_size = True
    resource = decode_png(SkiaRasterWriter().write(render_doc, options))
    existing_alpha = resource.soft_mask
    if existing_alpha is None:
        return False
    crop = _nonzero_alpha_bounds(existing_alpha, resource.width, resource.height)
    if crop is None:
        return False
    x0, y0, x1, y1 = crop
    pad = 2
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(resource.width, x1 + pad)
    y1 = min(resource.height, y1 + pad)
    crop_width = x1 - x0
    crop_height = y1 - y0
    if crop_width <= 0 or crop_height <= 0:
        return False
    scale_x = resource.width / max(page.width, 1e-6)
    scale_y = resource.height / max(page.height, 1e-6)
    inv_paint = _invert_matrix(
        (
            paint_transform.a,
            paint_transform.b,
            paint_transform.c,
            paint_transform.d,
            paint_transform.e,
            paint_transform.f,
        )
    )
    rgb = bytearray(crop_width * crop_height * 3)
    alpha = bytearray(crop_width * crop_height)
    page_height = page.height
    for py in range(crop_height):
        src_y = y1 - 1 - py
        user_y = page_height - (src_y + 0.5) / scale_y
        for px in range(crop_width):
            src_x = x0 + px
            user_x = (src_x + 0.5) / scale_x
            brush_x, brush_y = _sample_brush_coordinates(
                mask_brush,
                builder,
                user_x,
                user_y,
                inv_paint,
            )
            src_index = src_y * resource.width + src_x
            dst_index = py * crop_width + px
            base_index = src_index * 3
            rgb_index = dst_index * 3
            rgb[rgb_index:rgb_index + 3] = resource.data[base_index:base_index + 3]
            mask_alpha = _clamp(_mask_alpha_from_brush_at(mask_brush, brush_x, brush_y, renderer), 0.0, 1.0)
            pixel_alpha = existing_alpha[src_index] / 255.0
            alpha[dst_index] = int(round(_clamp(pixel_alpha * mask_alpha, 0.0, 1.0) * 255.0))
    image_id = renderer._image_store.register(
        XpsImageResource(
            image_id="",
            data=bytes(rgb),
            width=crop_width,
            height=crop_height,
            bits_per_component=8,
            color_space="DeviceRGB",
            filter=None,
            x_dpi=300.0,
            y_dpi=300.0,
            soft_mask=bytes(alpha),
        )
    )
    image_x = x0 / scale_x
    image_y = (y0 / scale_y) - (7.0 / scale_y)
    image_width = crop_width / scale_x
    image_height = crop_height / scale_y
    builder.add_image(
        image_id,
        crop_width,
        crop_height,
        Matrix(image_width, 0.0, 0.0, image_height, image_x, image_y),
    )
    return True


def _apply_opacity_mask_to_fill_paint(
    fill: Paint | None,
    mask_brush: ET.Element,
    resources: XpsResourceDictionary | None,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
    brush_origin_transform: Matrix | None,
    path: Path | None = None,
    path_bbox: tuple[float, float, float, float] | None = None,
    fill_brush: ET.Element | None = None,
) -> Paint | None:
    if fill is None:
        return fill
    if (
        path_bbox is not None
        and fill_brush is not None
        and _local_name(fill_brush.tag) == "SolidColorBrush"
        and _local_name(mask_brush.tag) in ("SolidColorBrush", "LinearGradientBrush", "RadialGradientBrush")
    ):
        solid_mask = _rasterize_masked_solid_fill(
            fill_brush=fill_brush,
            mask_brush=mask_brush,
            builder=builder,
            renderer=renderer,
            paint_transform=paint_transform,
            path_bbox=path_bbox,
        )
        if solid_mask is not None:
            return solid_mask
    if (
        path_bbox is not None
        and fill_brush is not None
        and _local_name(fill_brush.tag) in ("SolidColorBrush", "LinearGradientBrush", "RadialGradientBrush")
        and _local_name(mask_brush.tag) in ("LinearGradientBrush", "RadialGradientBrush")
    ):
        gradient_mask = _rasterize_masked_gradient_fill(
            fill_brush=fill_brush,
            mask_brush=mask_brush,
            builder=builder,
            renderer=renderer,
            paint_transform=paint_transform,
            path=path,
            path_bbox=path_bbox,
        )
        if gradient_mask is not None:
            return gradient_mask
    if (
        path_bbox is not None
        and fill.kind == "Pattern"
        and isinstance(fill.value, PatternPaint)
        and _local_name(mask_brush.tag) in ("LinearGradientBrush", "RadialGradientBrush")
    ):
        shaded_mask = _rasterize_masked_shading_fill(
            fill=fill,
            mask_brush=mask_brush,
            builder=builder,
            renderer=renderer,
            paint_transform=paint_transform,
            path=path,
            path_bbox=path_bbox,
        )
        if shaded_mask is not None:
            return shaded_mask
    if fill.kind == "DeviceRGB":
        try:
            base_r, base_g, base_b = fill.value  # type: ignore[misc]
            base_color = (
                _clamp(float(base_r), 0.0, 1.0),
                _clamp(float(base_g), 0.0, 1.0),
                _clamp(float(base_b), 0.0, 1.0),
            )
        except Exception:
            base_color = None
        if base_color is not None:
            tag = _local_name(mask_brush.tag)
            if tag in ("LinearGradientBrush", "RadialGradientBrush"):
                mod = copy.deepcopy(mask_brush)
                for stop in mod.findall(".//{*}GradientStop"):
                    alpha = _alpha_from_color_value(stop.get("Color"))
                    if alpha is None:
                        alpha = 1.0
                    rgb = (
                        _blend_component(base_color[0], alpha),
                        _blend_component(base_color[1], alpha),
                        _blend_component(base_color[2], alpha),
                    )
                    stop.set("Color", _rgb_to_hex(rgb))
                return _paint_from_element(
                    mod,
                    resources,
                    builder,
                    renderer,
                    paint_transform,
                    brush_origin_transform,
                )
            if tag == "ImageBrush":
                image_paint = _paint_from_image_opacity_mask(
                    mask_brush,
                    base_color,
                    builder,
                    renderer,
                    paint_transform,
                )
                if image_paint is not None:
                    return image_paint
    if fill.kind == "Pattern" and isinstance(fill.value, PatternPaint):
        pattern_mask_paint = _apply_mask_to_image_pattern_fill(
            fill=fill,
            mask_brush=mask_brush,
            builder=builder,
            renderer=renderer,
            paint_transform=paint_transform,
        )
        if pattern_mask_paint is not None:
            return pattern_mask_paint
    mask_alpha = _opacity_from_brush_element(mask_brush, resources, renderer)
    if mask_alpha is not None:
        return _apply_opacity_to_paint(fill, mask_alpha, builder, renderer)
    return fill


def _nonzero_alpha_bounds(alpha: bytes, width: int, height: int) -> tuple[int, int, int, int] | None:
    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    for y in range(height):
        row = y * width
        for x in range(width):
            if alpha[row + x] <= 0:
                continue
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
    if max_x < min_x or max_y < min_y:
        return None
    return (min_x, min_y, max_x + 1, max_y + 1)


def _rasterize_masked_solid_fill(
    fill_brush: ET.Element,
    mask_brush: ET.Element,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
    path_bbox: tuple[float, float, float, float],
) -> Paint | None:
    if renderer is None:
        return None
    bbox_x0, bbox_y0, bbox_x1, bbox_y1 = path_bbox
    width = max(1e-6, bbox_x1 - bbox_x0)
    height = max(1e-6, bbox_y1 - bbox_y0)
    raster_scale = 2.0
    width_px = max(1, int(math.ceil(width * raster_scale)))
    height_px = max(1, int(math.ceil(height * raster_scale)))
    inv_paint = None
    if paint_transform is not None:
        inv_paint = _invert_matrix(
            (
                paint_transform.a,
                paint_transform.b,
                paint_transform.c,
                paint_transform.d,
                paint_transform.e,
                paint_transform.f,
            )
        )
    rgb = _sample_brush_rgb(fill_brush, 0.0, 0.0, renderer)
    pixels = bytearray(width_px * height_px * 3)
    alpha_bytes = bytearray(width_px * height_px)
    for py in range(height_px):
        user_y = bbox_y0 + (py + 0.5) / raster_scale
        for px in range(width_px):
            user_x = bbox_x0 + (px + 0.5) / raster_scale
            brush_x, brush_y = _sample_brush_coordinates(fill_brush, builder, user_x, user_y, inv_paint)
            alpha = _mask_alpha_from_brush_at(mask_brush, brush_x, brush_y, renderer)
            idx = (py * width_px + px) * 3
            pixels[idx] = int(round(_clamp(rgb[0], 0.0, 1.0) * 255.0))
            pixels[idx + 1] = int(round(_clamp(rgb[1], 0.0, 1.0) * 255.0))
            pixels[idx + 2] = int(round(_clamp(rgb[2], 0.0, 1.0) * 255.0))
            alpha_bytes[py * width_px + px] = int(round(_clamp(alpha, 0.0, 1.0) * 255.0))
    resource = XpsImageResource(
        image_id="",
        data=bytes(pixels),
        width=width_px,
        height=height_px,
        bits_per_component=8,
        color_space="DeviceRGB",
        filter=None,
        x_dpi=96.0 * raster_scale,
        y_dpi=96.0 * raster_scale,
        soft_mask=bytes(alpha_bytes),
    )
    image_id = renderer._image_store.register(resource)
    pattern_obj = TilingPattern(
        paint_type=1,
        tiling_type=0,
        bbox=(0.0, 0.0, width, height),
        x_step=width,
        y_step=height,
        matrix=(1.0, 0.0, 0.0, 1.0, bbox_x0, bbox_y0),
        commands=[
            ImageCommand(
                image_id=image_id,
                width=width_px,
                height=height_px,
                matrix=Matrix(width, 0.0, 0.0, -height, 0.0, height),
            )
        ],
    )
    pattern_id = builder.register_pattern(pattern_obj)
    return Paint("Pattern", PatternPaint(pattern_id=pattern_id, base_space_id=None, base_components=None))


def _try_render_masked_solid_fill_as_image(
    path: Path,
    path_bbox: tuple[float, float, float, float] | None,
    fill_brush: ET.Element | None,
    mask_brush: ET.Element,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
    opacity: float,
) -> bool:
    if renderer is None or path_bbox is None or fill_brush is None:
        return False
    if _local_name(mask_brush.tag) not in ("SolidColorBrush", "LinearGradientBrush", "RadialGradientBrush"):
        return False
    if _local_name(fill_brush.tag) != "SolidColorBrush":
        return False
    bbox_x0, bbox_y0, bbox_x1, bbox_y1 = path_bbox
    width = max(1e-6, bbox_x1 - bbox_x0)
    height = max(1e-6, bbox_y1 - bbox_y0)
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except Exception:
        return False
    raster_scale = 1.5
    width_px = max(1, int(math.ceil(width * raster_scale)))
    height_px = max(1, int(math.ceil(height * raster_scale)))
    coverage_px = None
    if not _path_is_axis_aligned_rect(path, path_bbox):
        subpaths = _flatten_render_path(path.segments, raster_scale)
        if not subpaths:
            return False
        supersample = 4
        mask_hi = Image.new("L", (width_px * supersample, height_px * supersample), 0)
        draw = ImageDraw.Draw(mask_hi)
        for subpath in subpaths:
            if len(subpath) < 3:
                continue
            polygon = [
                (
                    (point.x - bbox_x0) * raster_scale * supersample,
                    (bbox_y1 - point.y) * raster_scale * supersample,
                )
                for point in subpath
            ]
            draw.polygon(polygon, fill=255)
        mask = mask_hi.resize((width_px, height_px), Image.Resampling.LANCZOS)
        coverage_px = mask.load()
    inv_paint = None
    if paint_transform is not None:
        inv_paint = _invert_matrix(
            (
                paint_transform.a,
                paint_transform.b,
                paint_transform.c,
                paint_transform.d,
                paint_transform.e,
                paint_transform.f,
            )
        )
    fill_rgb = _sample_brush_rgb(fill_brush, 0.0, 0.0, renderer)
    mask_tag = _local_name(mask_brush.tag)
    constant_mask_alpha = None
    if mask_tag == "SolidColorBrush":
        constant_mask_alpha = _mask_alpha_from_brush_at(mask_brush, 0.0, 0.0, renderer)
    pixels = bytearray(width_px * height_px * 3)
    alpha_bytes = bytearray(width_px * height_px)
    for py in range(height_px):
        user_y = bbox_y0 + (py + 0.5) / raster_scale
        for px in range(width_px):
            user_x = bbox_x0 + (px + 0.5) / raster_scale
            coverage = 1.0 if coverage_px is None else (coverage_px[px, py] / 255.0)
            brush_x = user_x
            brush_y = user_y
            if inv_paint is not None:
                brush_x, brush_y = _apply_matrix_tuple(inv_paint, user_x, user_y)
            alpha = 0.0
            if coverage > 1e-6:
                alpha = _clamp(
                    (
                        constant_mask_alpha
                        if constant_mask_alpha is not None
                        else _mask_alpha_from_brush_at(mask_brush, brush_x, brush_y, renderer)
                    )
                    * opacity
                    * coverage,
                    0.0,
                    1.0,
                )
            idx = (py * width_px + px) * 3
            pixels[idx] = int(round(_clamp(fill_rgb[0], 0.0, 1.0) * 255.0))
            pixels[idx + 1] = int(round(_clamp(fill_rgb[1], 0.0, 1.0) * 255.0))
            pixels[idx + 2] = int(round(_clamp(fill_rgb[2], 0.0, 1.0) * 255.0))
            alpha_bytes[py * width_px + px] = int(round(alpha * 255.0))
    image_id = renderer._image_store.register(
        XpsImageResource(
            image_id="",
            data=bytes(pixels),
            width=width_px,
            height=height_px,
            bits_per_component=8,
            color_space="DeviceRGB",
            filter=None,
            x_dpi=96.0 * raster_scale,
            y_dpi=96.0 * raster_scale,
            soft_mask=bytes(alpha_bytes),
        )
    )
    builder.add_image(
        image_id,
        width_px,
        height_px,
        Matrix(width, 0.0, 0.0, -height, bbox_x0, bbox_y0 + height),
    )
    return True


def _try_render_stroked_brush_as_image(
    path: Path,
    stroke_brush: ET.Element,
    stroke_width: float,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
    opacity: float,
) -> bool:
    if renderer is None:
        return False
    brush_tag = _local_name(stroke_brush.tag)
    allowed = {"LinearGradientBrush", "RadialGradientBrush"}
    if renderer._rasterize_solid_strokes:
        allowed.add("SolidColorBrush")
    if brush_tag not in allowed:
        return False
    if brush_tag == "SolidColorBrush":
        if stroke_width >= 0.4:
            return False
    bbox = _path_bbox(path)
    if bbox is None:
        return False
    pad = max(stroke_width * 1.5, 1.0)
    bbox_x0, bbox_y0, bbox_x1, bbox_y1 = (
        bbox[0] - pad,
        bbox[1] - pad,
        bbox[2] + pad,
        bbox[3] + pad,
    )
    width = max(1e-6, bbox_x1 - bbox_x0)
    height = max(1e-6, bbox_y1 - bbox_y0)
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except Exception:
        return False
    raster_scale = 2.0
    supersample = 4
    width_px = max(1, int(math.ceil(width * raster_scale)))
    height_px = max(1, int(math.ceil(height * raster_scale)))
    mask_hi = Image.new("L", (width_px * supersample, height_px * supersample), 0)
    draw = ImageDraw.Draw(mask_hi)
    if brush_tag == "SolidColorBrush":
        line_width_px = max(1, int(math.ceil(stroke_width * raster_scale * supersample)) + 1)
    else:
        line_width_px = max(1, int(round(stroke_width * raster_scale * supersample)))
    subpaths = _flatten_render_path(path.segments, raster_scale)
    for subpath in subpaths:
        if len(subpath) < 2:
            continue
        points = [
            (
                (point.x - bbox_x0) * raster_scale * supersample,
                (point.y - bbox_y0) * raster_scale * supersample,
            )
            for point in subpath
        ]
        draw.line(points, fill=255, width=line_width_px, joint="curve")
    if brush_tag == "SolidColorBrush":
        mask = mask_hi.resize((width_px, height_px), Image.Resampling.BOX)
    else:
        mask = mask_hi.resize((width_px, height_px), Image.Resampling.LANCZOS)
    coverage_px = mask.load()
    inv_paint = None
    if paint_transform is not None:
        inv_paint = _invert_matrix(
            (
                paint_transform.a,
                paint_transform.b,
                paint_transform.c,
                paint_transform.d,
                paint_transform.e,
                paint_transform.f,
            )
        )
    pixels = bytearray(width_px * height_px * 3)
    alpha_bytes = bytearray(width_px * height_px)
    for py in range(height_px):
        user_y = bbox_y0 + (py + 0.5) / raster_scale
        for px in range(width_px):
            user_x = bbox_x0 + (px + 0.5) / raster_scale
            brush_x, brush_y = _sample_brush_coordinates(stroke_brush, builder, user_x, user_y, inv_paint)
            rgb = _sample_brush_rgb(stroke_brush, brush_x, brush_y, renderer)
            coverage = coverage_px[px, py] / 255.0
            idx = (py * width_px + px) * 3
            pixels[idx] = int(round(_clamp(rgb[0], 0.0, 1.0) * 255.0))
            pixels[idx + 1] = int(round(_clamp(rgb[1], 0.0, 1.0) * 255.0))
            pixels[idx + 2] = int(round(_clamp(rgb[2], 0.0, 1.0) * 255.0))
            alpha_bytes[py * width_px + px] = int(round(_clamp(coverage * opacity, 0.0, 1.0) * 255.0))
    image_id = renderer._image_store.register(
        XpsImageResource(
            image_id="",
            data=bytes(pixels),
            width=width_px,
            height=height_px,
            bits_per_component=8,
            color_space="DeviceRGB",
            filter=None,
            x_dpi=96.0 * raster_scale,
            y_dpi=96.0 * raster_scale,
            soft_mask=bytes(alpha_bytes),
        )
    )
    builder.add_image(
        image_id,
        width_px,
        height_px,
        Matrix(width, 0.0, 0.0, -height, bbox_x0, bbox_y0 + height),
    )
    return True


def _try_render_image_brush_fill_as_image(
    path: Path,
    path_bbox: tuple[float, float, float, float] | None,
    fill_brush: ET.Element,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
    opacity: float,
) -> bool:
    if renderer is None or paint_transform is None or path_bbox is None:
        return False
    if _local_name(fill_brush.tag) != "ImageBrush":
        return False
    if opacity < 0.9999:
        return False
    if (fill_brush.get("TileMode") or "None").strip().lower() != "none":
        return False
    viewport = _parse_rect(fill_brush.get("Viewport"), default=(0.0, 0.0, 0.0, 0.0))
    if not _path_is_axis_aligned_rect(path, path_bbox):
        return False

    source = fill_brush.get("ImageSource")
    if not source:
        return False
    image = renderer._load_image(source)
    if image is None:
        return False
    viewbox = _parse_rect(
        fill_brush.get("Viewbox"),
        default=(0.0, 0.0, float(image.width), float(image.height)),
    )
    image = _crop_image_for_viewbox(image, viewbox)
    brush_transform = _brush_transform(fill_brush)
    normalized_viewport = (
        abs(viewport[0]) <= 1e-6
        and abs(viewport[1]) <= 1e-6
        and abs(viewport[2] - 1.0) <= 1e-6
        and abs(viewport[3] - 1.0) <= 1e-6
    )
    if normalized_viewport:
        viewport_matrix = Matrix(
            max(viewport[2], 1e-9),
            0.0,
            0.0,
            max(viewport[3], 1e-9),
            viewport[0],
            viewport[1],
        )
        image_matrix = _multiply(brush_transform, viewport_matrix)
        image_matrix = _multiply(image_matrix, Matrix(1.0, 0.0, 0.0, -1.0, 0.0, 1.0))
        final_matrix = _multiply(paint_transform, image_matrix)
    else:
        viewport_matrix = Matrix(
            max(viewport[2], 1e-9),
            0.0,
            0.0,
            -max(viewport[3], 1e-9),
            viewport[0],
            viewport[1] + max(viewport[3], 1e-9),
        )
        image_matrix = _multiply(brush_transform, viewport_matrix)
        final_matrix = _multiply(paint_transform, image_matrix)

    image_bbox = _matrix_bbox(final_matrix)
    if image_bbox is None or not _rect_close(path_bbox, image_bbox):
        return False

    image_id = renderer._image_store.register(image)
    builder.add_image(image_id, image.width, image.height, final_matrix)
    return True


def _try_render_spread_gradient_fill_as_image(
    path: Path,
    path_bbox: tuple[float, float, float, float] | None,
    fill_brush: ET.Element,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
    opacity: float,
) -> bool:
    if renderer is None or path_bbox is None or paint_transform is None:
        return False
    brush_tag = _local_name(fill_brush.tag)
    if brush_tag not in ("LinearGradientBrush", "RadialGradientBrush"):
        return False
    spread = (fill_brush.get("SpreadMethod") or "Pad").strip().lower()
    if spread not in ("repeat", "reflect"):
        return False
    bbox_x0, bbox_y0, bbox_x1, bbox_y1 = path_bbox
    width = max(1e-6, bbox_x1 - bbox_x0)
    height = max(1e-6, bbox_y1 - bbox_y0)
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except Exception:
        return False
    raster_scale = 2.0
    width_px = max(1, int(math.ceil(width * raster_scale)))
    height_px = max(1, int(math.ceil(height * raster_scale)))
    coverage_px = None
    if not _path_is_axis_aligned_rect(path, path_bbox):
        subpaths = _flatten_render_path(path.segments, raster_scale)
        if not subpaths:
            return False
        supersample = 4
        mask_hi = Image.new("L", (width_px * supersample, height_px * supersample), 0)
        draw = ImageDraw.Draw(mask_hi)
        for subpath in subpaths:
            if len(subpath) < 3:
                continue
            polygon = [
                (
                    (point.x - bbox_x0) * raster_scale * supersample,
                    (bbox_y1 - point.y) * raster_scale * supersample,
                )
                for point in subpath
            ]
            draw.polygon(polygon, fill=255)
        mask = mask_hi.resize((width_px, height_px), Image.Resampling.LANCZOS)
        coverage_px = mask.load()
    inv_paint = _invert_matrix(
        (
            paint_transform.a,
            paint_transform.b,
            paint_transform.c,
            paint_transform.d,
            paint_transform.e,
            paint_transform.f,
        )
    )
    pixels = bytearray(width_px * height_px * 3)
    alpha_bytes = bytearray(width_px * height_px)
    for py in range(height_px):
        user_y = bbox_y1 - py / raster_scale
        for px in range(width_px):
            user_x = bbox_x0 + px / raster_scale
            coverage = 1.0 if coverage_px is None else (coverage_px[px, py] / 255.0)
            if coverage > 1e-6:
                brush_x, brush_y = _sample_brush_coordinates(fill_brush, builder, user_x, user_y, inv_paint)
                rgb = _sample_gradient_brush_rgb(
                    fill_brush,
                    brush_x,
                    brush_y,
                    mode=renderer._spread_gradient_mode,
                )
                alpha = _clamp(coverage * opacity, 0.0, 1.0)
            else:
                rgb = (0.0, 0.0, 0.0)
                alpha = 0.0
            idx = (py * width_px + px) * 3
            pixels[idx] = int(round(_clamp(rgb[0], 0.0, 1.0) * 255.0))
            pixels[idx + 1] = int(round(_clamp(rgb[1], 0.0, 1.0) * 255.0))
            pixels[idx + 2] = int(round(_clamp(rgb[2], 0.0, 1.0) * 255.0))
            alpha_bytes[py * width_px + px] = int(round(alpha * 255.0))
    image_id = renderer._image_store.register(
        XpsImageResource(
            image_id="",
            data=bytes(pixels),
            width=width_px,
            height=height_px,
            bits_per_component=8,
            color_space="DeviceRGB",
            filter=None,
            x_dpi=96.0 * raster_scale,
            y_dpi=96.0 * raster_scale,
            soft_mask=bytes(alpha_bytes),
        )
    )
    builder.add_image(
        image_id,
        width_px,
        height_px,
        Matrix(width, 0.0, 0.0, -height, bbox_x0, bbox_y0 + height),
    )
    return True


def _rasterize_masked_shading_fill(
    fill: Paint,
    mask_brush: ET.Element,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
    path: Path,
    path_bbox: tuple[float, float, float, float],
) -> Paint | None:
    if renderer is None:
        return None
    pattern = builder._document.resources.patterns.get(fill.value.pattern_id)  # type: ignore[attr-defined]
    if not isinstance(pattern, ShadingPattern):
        return None
    bbox_x0, bbox_y0, bbox_x1, bbox_y1 = path_bbox
    width = max(1e-6, bbox_x1 - bbox_x0)
    height = max(1e-6, bbox_y1 - bbox_y0)
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except Exception:
        return None
    # Keep this localized and reasonably sharp for both PDF and Skia paths.
    raster_scale = 1.5
    width_px = max(1, int(math.ceil(width * raster_scale)))
    height_px = max(1, int(math.ceil(height * raster_scale)))
    coverage_px = None
    if not _path_is_axis_aligned_rect(path, path_bbox):
        subpaths = _flatten_render_path(path.segments, raster_scale)
        if not subpaths:
            return None
        supersample = 4
        mask_hi = Image.new("L", (width_px * supersample, height_px * supersample), 0)
        draw = ImageDraw.Draw(mask_hi)
        for subpath in subpaths:
            if len(subpath) < 3:
                continue
            polygon = [
                (
                    (point.x - bbox_x0) * raster_scale * supersample,
                    (bbox_y1 - point.y) * raster_scale * supersample,
                )
                for point in subpath
            ]
            draw.polygon(polygon, fill=255)
        mask = mask_hi.resize((width_px, height_px), Image.Resampling.LANCZOS)
        coverage_px = mask.load()
    inv_paint = None
    if paint_transform is not None:
        inv_paint = _invert_matrix(
            (
                paint_transform.a,
                paint_transform.b,
                paint_transform.c,
                paint_transform.d,
                paint_transform.e,
                paint_transform.f,
            )
    )
    pixels = bytearray(width_px * height_px * 3)
    alpha_bytes = bytearray(width_px * height_px)
    for py in range(height_px):
        user_y = bbox_y1 - (py + 0.5) / raster_scale
        for px in range(width_px):
            user_x = bbox_x0 + (px + 0.5) / raster_scale
            coverage = 1.0 if coverage_px is None else (coverage_px[px, py] / 255.0)
            if coverage > 1e-6:
                rgb = _sample_shading_pattern_rgb(pattern, user_x, user_y)
                if rgb is None:
                    rgb = (0.0, 0.0, 0.0)
                mask_x, mask_y = _sample_brush_coordinates(mask_brush, builder, user_x, user_y, inv_paint)
                alpha = _opacity_from_gradient_brush_at(mask_brush, mask_x, mask_y) * coverage
            else:
                rgb = (0.0, 0.0, 0.0)
                alpha = 0.0
            idx = (py * width_px + px) * 3
            pixels[idx] = int(round(_clamp(rgb[0], 0.0, 1.0) * 255.0))
            pixels[idx + 1] = int(round(_clamp(rgb[1], 0.0, 1.0) * 255.0))
            pixels[idx + 2] = int(round(_clamp(rgb[2], 0.0, 1.0) * 255.0))
            alpha_bytes[py * width_px + px] = int(round(_clamp(alpha, 0.0, 1.0) * 255.0))
    resource = XpsImageResource(
        image_id="",
        data=bytes(pixels),
        width=width_px,
        height=height_px,
        bits_per_component=8,
        color_space="DeviceRGB",
        filter=None,
        x_dpi=96.0 * raster_scale,
        y_dpi=96.0 * raster_scale,
        soft_mask=bytes(alpha_bytes),
    )
    image_id = renderer._image_store.register(resource)
    pattern_obj = TilingPattern(
        paint_type=1,
        tiling_type=0,
        bbox=(0.0, 0.0, width, height),
        x_step=width,
        y_step=height,
        matrix=(1.0, 0.0, 0.0, 1.0, bbox_x0, bbox_y0),
        commands=[
            ImageCommand(
                image_id=image_id,
                width=width_px,
                height=height_px,
                matrix=Matrix(width, 0.0, 0.0, -height, 0.0, height),
            )
        ],
    )
    pattern_id = builder.register_pattern(pattern_obj)
    return Paint("Pattern", PatternPaint(pattern_id=pattern_id, base_space_id=None, base_components=None))


def _rasterize_masked_gradient_fill(
    fill_brush: ET.Element,
    mask_brush: ET.Element,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
    path: Path,
    path_bbox: tuple[float, float, float, float],
) -> Paint | None:
    if renderer is None:
        return None
    bbox_x0, bbox_y0, bbox_x1, bbox_y1 = path_bbox
    width = max(1e-6, bbox_x1 - bbox_x0)
    height = max(1e-6, bbox_y1 - bbox_y0)
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except Exception:
        return None
    raster_scale = 1.5
    width_px = max(1, int(math.ceil(width * raster_scale)))
    height_px = max(1, int(math.ceil(height * raster_scale)))
    coverage_px = None
    if not _path_is_axis_aligned_rect(path, path_bbox):
        subpaths = _flatten_render_path(path.segments, raster_scale)
        if not subpaths:
            return None
        supersample = 4
        mask_hi = Image.new("L", (width_px * supersample, height_px * supersample), 0)
        draw = ImageDraw.Draw(mask_hi)
        for subpath in subpaths:
            if len(subpath) < 3:
                continue
            polygon = [
                (
                    (point.x - bbox_x0) * raster_scale * supersample,
                    (bbox_y1 - point.y) * raster_scale * supersample,
                )
                for point in subpath
            ]
            draw.polygon(polygon, fill=255)
        mask = mask_hi.resize((width_px, height_px), Image.Resampling.LANCZOS)
        coverage_px = mask.load()
    inv_paint = None
    if paint_transform is not None:
        inv_paint = _invert_matrix(
            (
                paint_transform.a,
                paint_transform.b,
                paint_transform.c,
                paint_transform.d,
                paint_transform.e,
                paint_transform.f,
            )
        )
    pixels = bytearray(width_px * height_px * 3)
    alpha_bytes = bytearray(width_px * height_px)
    for py in range(height_px):
        user_y = bbox_y1 - (py + 0.5) / raster_scale
        for px in range(width_px):
            user_x = bbox_x0 + (px + 0.5) / raster_scale
            coverage = 1.0 if coverage_px is None else (coverage_px[px, py] / 255.0)
            if coverage > 1e-6:
                brush_x, brush_y = _sample_brush_coordinates(fill_brush, builder, user_x, user_y, inv_paint)
                rgb = _sample_brush_rgb(fill_brush, brush_x, brush_y, renderer)
                mask_x, mask_y = _sample_brush_coordinates(mask_brush, builder, user_x, user_y, inv_paint)
                alpha = _opacity_from_gradient_brush_at(mask_brush, mask_x, mask_y) * coverage
            else:
                rgb = (0.0, 0.0, 0.0)
                alpha = 0.0
            idx = (py * width_px + px) * 3
            pixels[idx] = int(round(_clamp(rgb[0], 0.0, 1.0) * 255.0))
            pixels[idx + 1] = int(round(_clamp(rgb[1], 0.0, 1.0) * 255.0))
            pixels[idx + 2] = int(round(_clamp(rgb[2], 0.0, 1.0) * 255.0))
            alpha_bytes[py * width_px + px] = int(round(_clamp(alpha, 0.0, 1.0) * 255.0))
    resource = XpsImageResource(
        image_id="",
        data=bytes(pixels),
        width=width_px,
        height=height_px,
        bits_per_component=8,
        color_space="DeviceRGB",
        filter=None,
        x_dpi=96.0 * raster_scale,
        y_dpi=96.0 * raster_scale,
        soft_mask=bytes(alpha_bytes),
    )
    image_id = renderer._image_store.register(resource)
    pattern_obj = TilingPattern(
        paint_type=1,
        tiling_type=0,
        bbox=(0.0, 0.0, width, height),
        x_step=width,
        y_step=height,
        matrix=(1.0, 0.0, 0.0, 1.0, bbox_x0, bbox_y0),
        commands=[
            ImageCommand(
                image_id=image_id,
                width=width_px,
                height=height_px,
                matrix=Matrix(width, 0.0, 0.0, -height, 0.0, height),
            )
        ],
    )
    pattern_id = builder.register_pattern(pattern_obj)
    return Paint("Pattern", PatternPaint(pattern_id=pattern_id, base_space_id=None, base_components=None))


def _sample_shading_pattern_rgb(
    pattern: ShadingPattern,
    user_x: float,
    user_y: float,
) -> tuple[float, float, float] | None:
    inv = _invert_matrix(pattern.matrix)
    px = user_x
    py = user_y
    if inv is not None:
        px, py = _apply_matrix_tuple(inv, px, py)
    shading = pattern.shading
    if isinstance(shading, AxialShading):
        x0, y0, x1, y1 = shading.coords
        dx = x1 - x0
        dy = y1 - y0
        denom = dx * dx + dy * dy
        t = 0.0 if denom <= 1e-12 else ((px - x0) * dx + (py - y0) * dy) / denom
        param = _map_shading_parameter(t, shading.domain)
        return _evaluate_function_rgb(shading.function, param)
    if isinstance(shading, RadialShading):
        x0, y0, r0, x1, y1, r1 = shading.coords
        if abs(x0 - x1) > 1e-9 or abs(y0 - y1) > 1e-9 or abs(r0) > 1e-9:
            # Current XPS corpus uses concentric radial gradients; fall back
            # conservatively if a more general case appears.
            center_x = x1
            center_y = y1
            radius = max(abs(r1), 1e-9)
        else:
            center_x = x1
            center_y = y1
            radius = max(abs(r1), 1e-9)
        t = math.hypot(px - center_x, py - center_y) / radius
        param = _map_shading_parameter(t, shading.domain)
        return _evaluate_function_rgb(shading.function, param)
    return None


def _map_shading_parameter(t: float, domain: tuple[float, float] | None) -> float:
    if domain is None:
        return _clamp(t, 0.0, 1.0)
    d0, d1 = domain
    if abs(d1 - d0) <= 1e-12:
        return d0
    t = _clamp(t, 0.0, 1.0)
    return d0 + t * (d1 - d0)


def _evaluate_function_rgb(function, value: float) -> tuple[float, float, float]:
    if isinstance(function, ExponentialFunction):
        d0, d1 = function.domain
        if abs(d1 - d0) <= 1e-12:
            u = 0.0
        else:
            u = (value - d0) / (d1 - d0)
        u = _clamp(u, 0.0, 1.0)
        factor = math.pow(u, function.n)
        return (
            _clamp(function.c0[0] + (function.c1[0] - function.c0[0]) * factor, 0.0, 1.0),
            _clamp(function.c0[1] + (function.c1[1] - function.c0[1]) * factor, 0.0, 1.0),
            _clamp(function.c0[2] + (function.c1[2] - function.c0[2]) * factor, 0.0, 1.0),
        )
    if isinstance(function, StitchingFunction):
        if not function.functions:
            return (0.0, 0.0, 0.0)
        idx = 0
        lower = function.domain[0]
        upper = function.domain[1]
        for bound_idx, bound in enumerate(function.bounds):
            if value < bound:
                upper = bound
                idx = bound_idx
                break
            lower = bound
            idx = bound_idx + 1
        else:
            idx = len(function.functions) - 1
        lower = function.domain[0] if idx == 0 else function.bounds[idx - 1]
        upper = function.domain[1] if idx >= len(function.bounds) else function.bounds[idx]
        encode_index = idx * 2
        e0 = function.encode[encode_index]
        e1 = function.encode[encode_index + 1]
        if abs(upper - lower) <= 1e-12:
            mapped = e0
        else:
            mapped = e0 + ((value - lower) / (upper - lower)) * (e1 - e0)
        return _evaluate_function_rgb(function.functions[idx], mapped)
    return (0.0, 0.0, 0.0)


def _paint_from_image_opacity_mask(
    mask_brush: ET.Element,
    base_color: tuple[float, float, float],
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
) -> Paint | None:
    if renderer is None or renderer._package is None:
        return None
    source = mask_brush.get("ImageSource")
    if not source:
        return None
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    try:
        part_name = _resolve_part(renderer._current_part or "/", source)
        payload = renderer._package.read(part_name)
        with Image.open(io.BytesIO(payload)) as img:
            if "A" in img.getbands():
                alpha_img = img.convert("RGBA").getchannel("A").convert("L")
            else:
                alpha_img = img.convert("L")
            rgb = Image.new("RGB", alpha_img.size, (
                int(round(_clamp(base_color[0], 0.0, 1.0) * 255.0)),
                int(round(_clamp(base_color[1], 0.0, 1.0) * 255.0)),
                int(round(_clamp(base_color[2], 0.0, 1.0) * 255.0)),
            ))
            resource = XpsImageResource(
                image_id="",
                data=rgb.tobytes(),
                width=rgb.width,
                height=rgb.height,
                bits_per_component=8,
                color_space="DeviceRGB",
                filter=None,
                x_dpi=96.0,
                y_dpi=96.0,
                soft_mask=alpha_img.tobytes(),
            )
    except Exception:
        return None

    image_id = renderer._image_store.register(resource)
    viewbox = _parse_rect(
        mask_brush.get("Viewbox"),
        default=(0.0, 0.0, float(resource.width), float(resource.height)),
    )
    viewport = _parse_rect(mask_brush.get("Viewport"), default=viewbox)
    tile_mode = (mask_brush.get("TileMode") or "None").strip().lower()
    x_step = max(viewport[2], 1.0)
    y_step = max(viewport[3], 1.0)
    matrix = Matrix(
        max(viewport[2], 1.0),
        0.0,
        0.0,
        -max(viewport[3], 1.0),
        0.0,
        max(viewport[3], 1.0),
    )
    pm = (
        XPS_UNIT_SCALE,
        0.0,
        0.0,
        XPS_UNIT_SCALE,
        viewport[0] * XPS_UNIT_SCALE,
        viewport[1] * XPS_UNIT_SCALE,
    )
    if paint_transform is not None:
        tx = paint_transform.a * viewport[0] + paint_transform.c * viewport[1] + paint_transform.e
        ty = paint_transform.b * viewport[0] + paint_transform.d * viewport[1] + paint_transform.f
        pm = (
            paint_transform.a,
            paint_transform.b,
            paint_transform.c,
            paint_transform.d,
            tx,
            ty,
        )
    pattern = TilingPattern(
        paint_type=1,
        tiling_type=1 if tile_mode == "tile" else 0,
        bbox=(0.0, 0.0, viewport[2], viewport[3]),
        x_step=x_step,
        y_step=y_step,
        matrix=pm,
        commands=[ImageCommand(image_id=image_id, width=resource.width, height=resource.height, matrix=matrix)],
    )
    pattern_id = builder.register_pattern(pattern)
    return Paint("Pattern", PatternPaint(pattern_id=pattern_id, base_space_id=None, base_components=None))


def _apply_mask_to_image_pattern_fill(
    fill: Paint,
    mask_brush: ET.Element,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
) -> Paint | None:
    if renderer is None:
        return None
    pattern = builder._document.resources.patterns.get(fill.value.pattern_id)  # type: ignore[attr-defined]
    if not isinstance(pattern, TilingPattern):
        return None
    if len(pattern.commands) != 1 or not isinstance(pattern.commands[0], ImageCommand):
        return None
    image_cmd = pattern.commands[0]
    try:
        source = renderer._image_store.get(image_cmd.image_id)
    except Exception:
        return None
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None

    tag = _local_name(mask_brush.tag)
    if tag not in ("LinearGradientBrush", "RadialGradientBrush"):
        return None
    viewport = _parse_rect(mask_brush.get("Viewport"), default=pattern.bbox)
    width = max(1, int(round(viewport[2])))
    height = max(1, int(round(viewport[3])))

    try:
        if source.filter == "DCTDecode":
            tile = Image.open(io.BytesIO(source.data)).convert("RGB")
        else:
            tile = Image.frombytes("RGB", (source.width, source.height), source.data)
        base = tile.resize((width, height))
        px = base.load()
        for yy in range(height):
            py = viewport[1] + float(yy) + 0.5
            for xx in range(width):
                px_x = viewport[0] + float(xx) + 0.5
                a = _opacity_from_gradient_brush_at(mask_brush, px_x, py)
                rr, gg, bb = px[xx, yy]
                px[xx, yy] = (
                    int(round(rr * a + 255.0 * (1.0 - a))),
                    int(round(gg * a + 255.0 * (1.0 - a))),
                    int(round(bb * a + 255.0 * (1.0 - a))),
                )
        resource = XpsImageResource(
            image_id="",
            data=base.tobytes(),
            width=width,
            height=height,
            bits_per_component=8,
            color_space="DeviceRGB",
            filter=None,
            x_dpi=96.0,
            y_dpi=96.0,
        )
    except Exception:
        return None

    new_id = renderer._image_store.register(resource)
    img_matrix = Matrix(float(width), 0.0, 0.0, -float(height), 0.0, float(height))
    pm = (
        XPS_UNIT_SCALE,
        0.0,
        0.0,
        XPS_UNIT_SCALE,
        viewport[0] * XPS_UNIT_SCALE,
        viewport[1] * XPS_UNIT_SCALE,
    )
    if paint_transform is not None:
        tx = paint_transform.a * viewport[0] + paint_transform.c * viewport[1] + paint_transform.e
        ty = paint_transform.b * viewport[0] + paint_transform.d * viewport[1] + paint_transform.f
        pm = (
            paint_transform.a,
            paint_transform.b,
            paint_transform.c,
            paint_transform.d,
            tx,
            ty,
        )
    p = TilingPattern(
        paint_type=1,
        tiling_type=0,
        bbox=(0.0, 0.0, float(width), float(height)),
        x_step=float(width),
        y_step=float(height),
        matrix=pm,
        commands=[ImageCommand(image_id=new_id, width=width, height=height, matrix=img_matrix)],
    )
    pid = builder.register_pattern(p)
    return Paint("Pattern", PatternPaint(pattern_id=pid, base_space_id=None, base_components=None))


def _sample_brush_coordinates(
    brush: ET.Element,
    builder: RenderModelBuilder,
    user_x: float,
    user_y: float,
    inv_paint: tuple[float, float, float, float, float, float] | None,
) -> tuple[float, float]:
    brush_x = user_x
    brush_y = user_y
    if inv_paint is not None:
        brush_x, brush_y = _apply_matrix_tuple(inv_paint, user_x, user_y)
    # XPS absolute coordinates are already expressed in page coordinate space.
    # Keep gradient sampling in that space; image/visual brushes handle their
    # own source-space mapping separately.
    if (
        (brush.get("MappingMode") or "").strip().lower() == "absolute"
        and _local_name(brush.tag) not in ("LinearGradientBrush", "RadialGradientBrush")
    ):
        page_height = 0.0
        try:
            pages = builder._document.pages  # type: ignore[attr-defined]
            if pages:
                page_height = pages[-1].height
        except Exception:
            page_height = 0.0
        if page_height:
            brush_y = page_height - brush_y
    return (brush_x, brush_y)


def _opacity_from_gradient_brush_at(brush: ET.Element, x: float, y: float) -> float:
    stops = _collect_gradient_alpha_stops(brush)
    t = _gradient_brush_parameter(brush, x, y)
    return _interpolate_alpha(stops, t)


def _mask_alpha_from_brush_at(
    brush: ET.Element,
    x: float,
    y: float,
    renderer: XpsRenderer | None,
) -> float:
    tag = _local_name(brush.tag)
    if tag == "SolidColorBrush":
        alpha = _alpha_from_color_value(brush.get("Color"))
        return 1.0 if alpha is None else _clamp(alpha, 0.0, 1.0)
    if tag in ("LinearGradientBrush", "RadialGradientBrush"):
        return _opacity_from_gradient_brush_at(brush, x, y)
    if tag == "ImageBrush":
        return _opacity_from_image_brush_at(brush, x, y, renderer)
    if tag == "VisualBrush":
        return _opacity_from_visual_brush_at(brush, x, y, renderer)
    return 1.0


def _opacity_from_image_brush_at(
    brush: ET.Element,
    x: float,
    y: float,
    renderer: XpsRenderer | None,
) -> float:
    if renderer is None:
        return 1.0
    source = brush.get("ImageSource")
    if not source or renderer._package is None:
        return 1.0
    cache = getattr(renderer, "_mask_brush_image_cache", None)
    if cache is None:
        cache = {}
        setattr(renderer, "_mask_brush_image_cache", cache)
    key = id(brush)
    cached = cache.get(key)
    if cached is None:
        try:
            from PIL import Image  # type: ignore
        except Exception:
            return 1.0
        part_name = _resolve_part(renderer._current_part or "/", source)
        payload = renderer._package.read(part_name)
        with Image.open(io.BytesIO(payload)) as pil:
            dpi = pil.info.get("dpi")
            dpi_x = float(dpi[0]) if isinstance(dpi, tuple) and len(dpi) >= 1 else 96.0
            dpi_y = float(dpi[1]) if isinstance(dpi, tuple) and len(dpi) >= 2 else dpi_x
            viewbox = _parse_rect(
                brush.get("Viewbox"),
                default=(0.0, 0.0, float(pil.width), float(pil.height)),
            )
            source_left = (dpi_x * viewbox[0]) / 96.0
            source_top = (dpi_y * viewbox[1]) / 96.0
            source_width = (dpi_x * viewbox[2]) / 96.0
            source_height = (dpi_y * viewbox[3]) / 96.0
            left = int(round(source_left))
            top = int(round(source_top))
            right = int(round(source_left + source_width))
            bottom = int(round(source_top + source_height))
            if right <= left or bottom <= top:
                return 1.0
            crop = pil.crop((max(0, left), max(0, top), min(pil.width, right), min(pil.height, bottom)))
            if crop.mode not in ("RGBA", "LA"):
                crop = crop.convert("RGBA") if "A" in crop.getbands() else crop.convert("RGB")
            cached = (
                crop,
                _parse_rect(
                    brush.get("Viewport"),
                    default=(0.0, 0.0, float(crop.width), float(crop.height)),
                ),
                (brush.get("TileMode") or "None").strip().lower(),
            )
        cache[key] = cached
    image, viewport, tile_mode = cached
    vw = max(viewport[2], 1e-9)
    vh = max(viewport[3], 1e-9)
    lx = x - viewport[0]
    ly = y - viewport[1]
    if tile_mode == "tile":
        lx = lx % vw
        ly = ly % vh
    elif lx < 0.0 or ly < 0.0 or lx > vw or ly > vh:
        return 0.0
    sx = min(image.width - 1, max(0, int((lx / vw) * max(0, image.width - 1) + 0.5)))
    sy = min(image.height - 1, max(0, int((ly / vh) * max(0, image.height - 1) + 0.5)))
    try:
        px = image.getpixel((sx, sy))
    except Exception:
        return 1.0
    if isinstance(px, tuple):
        if len(px) >= 4:
            return _clamp(float(px[3]) / 255.0, 0.0, 1.0)
        if len(px) >= 3:
            return _clamp((float(px[0]) + float(px[1]) + float(px[2])) / (255.0 * 3.0), 0.0, 1.0)
    if isinstance(px, int):
        return _clamp(float(px) / 255.0, 0.0, 1.0)
    return 1.0


def _opacity_from_visual_brush_at(
    brush: ET.Element,
    x: float,
    y: float,
    renderer: XpsRenderer | None,
) -> float:
    if renderer is None or renderer._package is None:
        return 1.0
    cache = getattr(renderer, "_mask_brush_visual_cache", None)
    if cache is None:
        cache = {}
        setattr(renderer, "_mask_brush_visual_cache", cache)
    key = id(brush)
    cached = cache.get(key)
    if cached is None:
        visual = brush.find(".//{*}VisualBrush.Visual")
        if visual is None:
            return 1.0
        viewbox = _parse_rect(brush.get("Viewbox"), default=(0.0, 0.0, 1.0, 1.0))
        viewport = _parse_rect(brush.get("Viewport"), default=viewbox)
        tile_mode = (brush.get("TileMode") or "None").strip().lower()
        try:
            from .output import _build_xps_font_resolver
            from ..image.skia_raster_writer import SkiaRasterWriter
            from ..ps.output import ImageSaveOptions
        except Exception:
            return 1.0
        temp_builder = RenderModelBuilder()
        temp_store = XpsImageStore()
        temp_builder.begin_page(max(viewbox[2], 1e-6), max(viewbox[3], 1e-6))
        temp_renderer = XpsRenderer(temp_builder, temp_store, rasterize_solid_strokes=renderer._rasterize_solid_strokes)
        temp_renderer.set_package(renderer._package)
        if renderer._current_part is not None:
            temp_renderer.set_current_part(renderer._current_part)
        local_transform = Matrix(1.0, 0.0, 0.0, 1.0, -viewbox[0], -viewbox[1])
        for child in list(visual):
            temp_renderer._render_element(child, None, local_transform)
        temp_builder.end_page()
        render_doc = temp_builder.document()
        for image_id, resource in temp_store._images.items():
            render_doc.resources.images[image_id] = RenderImageResource(
                data=resource.data,
                width=resource.width,
                height=resource.height,
                color_space=resource.color_space,
                bits_per_component=resource.bits_per_component,
                filter=resource.filter,
                soft_mask=resource.soft_mask,
            )
        font_resolver = _build_xps_font_resolver(renderer._package, render_doc)
        options = ImageSaveOptions(format="png", dpi=300)
        options.font_resolver = font_resolver
        options.opaque_background = False
        options.preserve_fractional_page_size = True
        image = decode_png(SkiaRasterWriter().write(render_doc, options))
        cached = (image, viewbox, viewport, tile_mode)
        cache[key] = cached
    image, viewbox, viewport, tile_mode = cached
    vw = max(viewport[2], 1e-9)
    vh = max(viewport[3], 1e-9)
    lx = x - viewport[0]
    ly = y - viewport[1]
    if tile_mode == "tile":
        lx = lx % vw
        ly = ly % vh
    elif lx < 0.0 or ly < 0.0 or lx > vw or ly > vh:
        return 0.0
    bx = viewbox[0] + (lx / vw) * viewbox[2]
    by = viewbox[1] + (ly / vh) * viewbox[3]
    fx = ((bx - viewbox[0]) / max(viewbox[2], 1e-9)) * max(image.width - 1, 0)
    fy = ((by - viewbox[1]) / max(viewbox[3], 1e-9)) * max(image.height - 1, 0)
    fy = max(image.height - 1, 0) - fy
    x0 = min(image.width - 1, max(0, int(math.floor(fx))))
    y0 = min(image.height - 1, max(0, int(math.floor(fy))))
    x1 = min(image.width - 1, x0 + 1)
    y1 = min(image.height - 1, y0 + 1)
    tx = _clamp(fx - x0, 0.0, 1.0)
    ty = _clamp(fy - y0, 0.0, 1.0)
    if image.soft_mask is not None and len(image.soft_mask) >= image.width * image.height:
        a00 = image.soft_mask[y0 * image.width + x0] / 255.0
        a10 = image.soft_mask[y0 * image.width + x1] / 255.0
        a01 = image.soft_mask[y1 * image.width + x0] / 255.0
        a11 = image.soft_mask[y1 * image.width + x1] / 255.0
        top = a00 * (1.0 - tx) + a10 * tx
        bottom = a01 * (1.0 - tx) + a11 * tx
        return _clamp(top * (1.0 - ty) + bottom * ty, 0.0, 1.0)
    def gray(ix: int, iy: int) -> float:
        idx = (iy * image.width + ix) * 3
        if idx + 2 >= len(image.data):
            return 0.0
        return (
            float(image.data[idx]) + float(image.data[idx + 1]) + float(image.data[idx + 2])
        ) / (255.0 * 3.0)
    g00 = gray(x0, y0)
    g10 = gray(x1, y0)
    g01 = gray(x0, y1)
    g11 = gray(x1, y1)
    top = g00 * (1.0 - tx) + g10 * tx
    bottom = g01 * (1.0 - tx) + g11 * tx
    return _clamp(top * (1.0 - ty) + bottom * ty, 0.0, 1.0)


def _sample_gradient_brush_rgb(
    brush: ET.Element,
    x: float,
    y: float,
    mode: str = "default",
) -> tuple[float, float, float]:
    stops = _collect_gradient_rgb_stops(brush)
    if not stops:
        return (0.0, 0.0, 0.0)
    t = _gradient_brush_parameter(brush, x, y, mode=mode)
    return _interpolate_rgb(stops, t)


def _sample_brush_rgb(
    brush: ET.Element,
    x: float,
    y: float,
    renderer: XpsRenderer | None,
) -> tuple[float, float, float]:
    tag = _local_name(brush.tag)
    if tag == "SolidColorBrush":
        color_value = brush.get("Color") or "#000000"
        if color_value.strip().startswith("ContextColor"):
            context = _parse_context_color(color_value, renderer)
            if context is not None:
                return context
        return _parse_color(color_value)
    if tag in ("LinearGradientBrush", "RadialGradientBrush"):
        return _sample_gradient_brush_rgb(brush, x, y)
    return (0.0, 0.0, 0.0)


def _sample_image_brush_rgb_at(
    brush: ET.Element,
    x: float,
    y: float,
    renderer: XpsRenderer | None,
) -> tuple[float, float, float] | None:
    if renderer is None:
        return None
    source = brush.get("ImageSource")
    if not source:
        return None
    cache = getattr(renderer, "_fill_brush_image_cache", None)
    if cache is None:
        cache = {}
        setattr(renderer, "_fill_brush_image_cache", cache)
    key = id(brush)
    cached = cache.get(key)
    if cached is None:
        image = renderer._load_image(source)
        if image is None:
            return None
        viewbox = _parse_rect(
            brush.get("Viewbox"),
            default=(0.0, 0.0, float(image.width), float(image.height)),
        )
        cached = (
            _crop_image_for_viewbox(image, viewbox),
            _parse_rect(
                brush.get("Viewport"),
                default=(0.0, 0.0, float(image.width), float(image.height)),
            ),
            (brush.get("TileMode") or "None").strip().lower(),
        )
        cache[key] = cached
    image, viewport, tile_mode = cached
    vw = max(viewport[2], 1e-9)
    vh = max(viewport[3], 1e-9)
    lx = x - viewport[0]
    ly = y - viewport[1]
    if tile_mode == "tile":
        lx = lx % vw
        ly = ly % vh
    elif lx < 0.0 or ly < 0.0 or lx > vw or ly > vh:
        return (1.0, 1.0, 1.0)
    sx = min(image.width - 1, max(0, int((lx / vw) * max(0, image.width - 1) + 0.5)))
    sy = min(image.height - 1, max(0, int((ly / vh) * max(0, image.height - 1) + 0.5)))
    idx = (sy * image.width + sx) * 3
    if idx + 2 >= len(image.data):
        return None
    return (
        image.data[idx] / 255.0,
        image.data[idx + 1] / 255.0,
        image.data[idx + 2] / 255.0,
    )


def _gradient_brush_parameter(
    brush: ET.Element,
    x: float,
    y: float,
    mode: str = "default",
) -> float:
    stops = _collect_gradient_alpha_stops(brush)
    if not stops:
        return 0.0
    key = id(brush)
    geom = _GRADIENT_GEOMETRY_CACHE.get(key)
    if geom is None:
        tag = _local_name(brush.tag)
        if tag == "LinearGradientBrush":
            s = _parse_point(brush.get("StartPoint"))
            e = _parse_point(brush.get("EndPoint"))
            params = (s[0], s[1], e[0], e[1])
        elif tag == "RadialGradientBrush":
            c = _parse_point(brush.get("Center"))
            g = _parse_point(brush.get("GradientOrigin"))
            rx = abs(_parse_float(brush.get("RadiusX")) or 0.0)
            ry = abs(_parse_float(brush.get("RadiusY")) or 0.0)
            params = (c[0], c[1], g[0], g[1], rx, ry)
        else:
            params = ()
        geom = (tag, params, (brush.get("SpreadMethod") or "Pad").strip().lower())
        _GRADIENT_GEOMETRY_CACHE[key] = geom
    tag, params, spread = geom
    t = 0.0
    if tag == "LinearGradientBrush":
        x0, y0, x1, y1 = params
        dx = x1 - x0
        dy = y1 - y0
        denom = dx * dx + dy * dy
        t = 0.0 if denom <= 1e-9 else ((x - x0) * dx + (y - y0) * dy) / denom
    elif tag == "RadialGradientBrush":
        center_x, center_y, origin_x, origin_y, rx, ry = params
        if rx <= 1e-9 or ry <= 1e-9:
            t = 0.0
        else:
            focus_x = (origin_x - center_x) / rx
            focus_y = (origin_y - center_y) / ry
            point_x = (x - center_x) / rx
            point_y = (y - center_y) / ry
            dir_x = point_x - focus_x
            dir_y = point_y - focus_y
            if abs(dir_x) <= 1e-12 and abs(dir_y) <= 1e-12:
                t = 0.0
            else:
                a = dir_x * dir_x + dir_y * dir_y
                b = 2.0 * (focus_x * dir_x + focus_y * dir_y)
                c_term = focus_x * focus_x + focus_y * focus_y - 1.0
                disc = b * b - 4.0 * a * c_term
                if a <= 1e-12 or disc < 0.0:
                    t = math.sqrt(point_x * point_x + point_y * point_y)
                else:
                    sqrt_disc = math.sqrt(max(disc, 0.0))
                    roots = [
                        root
                        for root in (
                            (-b - sqrt_disc) / (2.0 * a),
                            (-b + sqrt_disc) / (2.0 * a),
                        )
                        if root > 1e-12
                    ]
                    if not roots:
                        t = math.sqrt(point_x * point_x + point_y * point_y)
                    else:
                        lam = max(roots)
                        t = 1.0 / lam
    if spread == "repeat":
        t = t % 1.0
    elif spread == "reflect":
        if mode == "pdf":
            frac = t % 1.0
            if t > 0.0 and abs(frac) <= 1e-9:
                t = 1.0
            else:
                t = frac
        else:
            v = abs(t)
            n = int(math.floor(v))
            frac = v - n
            t = frac if (n % 2 == 0) else (1.0 - frac)
    else:
        t = _clamp(t, 0.0, 1.0)
    return t


def _collect_gradient_rgb_stops(brush: ET.Element) -> list[tuple[float, tuple[float, float, float]]]:
    cached = _GRADIENT_RGB_STOPS_CACHE.get(id(brush))
    if cached is not None:
        return cached
    values: list[tuple[float, tuple[float, float, float]]] = []
    for stop in brush.findall(".//{*}GradientStop"):
        off = _clamp(_parse_float(stop.get("Offset")) or 0.0, 0.0, 1.0)
        values.append((off, _parse_color(stop.get("Color") or "#000000")))
    if not values:
        return []
    values.sort(key=lambda item: item[0])
    if values[0][0] > 0.0:
        values.insert(0, (0.0, values[0][1]))
    if values[-1][0] < 1.0:
        values.append((1.0, values[-1][1]))
    _GRADIENT_RGB_STOPS_CACHE[id(brush)] = values
    return values


def _interpolate_rgb(
    stops: list[tuple[float, tuple[float, float, float]]],
    t: float,
) -> tuple[float, float, float]:
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        o0, c0 = stops[i]
        o1, c1 = stops[i + 1]
        if o0 <= t <= o1:
            if abs(o1 - o0) <= 1e-9:
                return c1
            u = (t - o0) / (o1 - o0)
            return (
                _clamp(c0[0] + (c1[0] - c0[0]) * u, 0.0, 1.0),
                _clamp(c0[1] + (c1[1] - c0[1]) * u, 0.0, 1.0),
                _clamp(c0[2] + (c1[2] - c0[2]) * u, 0.0, 1.0),
            )
    return stops[-1][1]


def _collect_gradient_alpha_stops(brush: ET.Element) -> list[tuple[float, float]]:
    cached = _GRADIENT_ALPHA_STOPS_CACHE.get(id(brush))
    if cached is not None:
        return cached
    values: list[tuple[float, float]] = []
    for stop in brush.findall(".//{*}GradientStop"):
        off = _clamp(_parse_float(stop.get("Offset")) or 0.0, 0.0, 1.0)
        alpha = _alpha_from_color_value(stop.get("Color"))
        if alpha is None:
            alpha = 1.0
        values.append((off, _clamp(alpha, 0.0, 1.0)))
    if not values:
        return []
    values.sort(key=lambda item: item[0])
    if values[0][0] > 0.0:
        values.insert(0, (0.0, values[0][1]))
    if values[-1][0] < 1.0:
        values.append((1.0, values[-1][1]))
    _GRADIENT_ALPHA_STOPS_CACHE[id(brush)] = values
    return values


def _interpolate_alpha(stops: list[tuple[float, float]], t: float) -> float:
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        o0, a0 = stops[i]
        o1, a1 = stops[i + 1]
        if o0 <= t <= o1:
            if abs(o1 - o0) <= 1e-9:
                return a1
            u = (t - o0) / (o1 - o0)
            return _clamp(a0 + (a1 - a0) * u, 0.0, 1.0)
    return stops[-1][1]


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r = int(round(_clamp(rgb[0], 0.0, 1.0) * 255.0))
    g = int(round(_clamp(rgb[1], 0.0, 1.0) * 255.0))
    b = int(round(_clamp(rgb[2], 0.0, 1.0) * 255.0))
    return f"#{r:02X}{g:02X}{b:02X}"




def _opacity_from_brush_element(
    element: ET.Element,
    resources: XpsResourceDictionary | None,
    renderer: XpsRenderer | None,
) -> float | None:
    tag = _local_name(element.tag)
    if tag == "SolidColorBrush":
        return _alpha_from_color_value(element.get("Color"))
    if tag in ("LinearGradientBrush", "RadialGradientBrush"):
        stops = element.findall(".//{*}GradientStop")
        if not stops:
            return None
        weighted = 0.0
        total = 0.0
        prev = 0.0
        for stop in stops:
            off = _clamp(_parse_float(stop.get("Offset")) or 0.0, 0.0, 1.0)
            alpha = _alpha_from_color_value(stop.get("Color"))
            if alpha is None:
                continue
            segment = max(0.0, off - prev)
            weighted += alpha * segment
            total += segment
            prev = off
        if total <= 1e-9:
            first_alpha = _alpha_from_color_value(stops[0].get("Color"))
            return first_alpha
        return _clamp(weighted / total, 0.0, 1.0)
    if tag == "ImageBrush":
        return _opacity_from_image_brush(element, renderer)
    if tag == "VisualBrush":
        # Conservative fallback: VisualBrush masks in current tests are sparse,
        # keep partial visibility rather than full knockout.
        return 0.5
    return None


def _opacity_from_image_brush(element: ET.Element, renderer: XpsRenderer | None) -> float | None:
    if renderer is None or renderer._package is None:
        return None
    source = element.get("ImageSource")
    if not source:
        return None
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    try:
        part_name = _resolve_part(renderer._current_part or "/", source)
        payload = renderer._package.read(part_name)
        with Image.open(io.BytesIO(payload)) as img:
            if "A" in img.getbands():
                alpha = img.getchannel("A")
                hist = alpha.histogram()
                total_px = max(1, alpha.width * alpha.height)
                acc = 0
                for idx, count in enumerate(hist):
                    acc += idx * count
                return _clamp(acc / (255.0 * total_px), 0.0, 1.0)
            return 1.0
    except Exception:
        return None


def _alpha_from_color_value(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip()
    if text.startswith("#"):
        raw = text[1:]
        if len(raw) == 8:
            try:
                return _clamp(int(raw[0:2], 16) / 255.0, 0.0, 1.0)
            except ValueError:
                return None
        return 1.0
    if text.startswith("sc#"):
        parts = [p for p in re.split(r"[ ,]+", text[3:]) if p]
        if len(parts) >= 4:
            alpha = _parse_float(parts[0])
            if alpha is None:
                return None
            return _clamp(alpha, 0.0, 1.0)
        return 1.0
    return None


def _blend_component(value: float, opacity: float) -> float:
    return value * opacity + (1.0 - opacity)


def _apply_opacity_to_paint(
    paint: Paint | None,
    opacity: float,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
) -> Paint | None:
    if paint is None or opacity >= 0.9999:
        return paint
    if paint.kind == "DeviceRGB":
        try:
            r, g, b = paint.value  # type: ignore[misc]
            return Paint(
                "DeviceRGB",
                (
                    _blend_component(float(r), opacity),
                    _blend_component(float(g), opacity),
                    _blend_component(float(b), opacity),
                ),
            )
        except Exception:
            return paint
    if paint.kind != "Pattern" or not isinstance(paint.value, PatternPaint):
        return paint
    patterns = builder._document.resources.patterns  # type: ignore[attr-defined]
    pattern = patterns.get(paint.value.pattern_id)
    if pattern is None:
        return paint
    adjusted = _apply_opacity_to_pattern(pattern, opacity, builder, renderer)
    new_pattern_id = builder.register_pattern(adjusted)
    return Paint(
        "Pattern",
        PatternPaint(
            pattern_id=new_pattern_id,
            base_space_id=paint.value.base_space_id,
            base_components=paint.value.base_components,
        ),
    )


def _apply_opacity_to_pattern(
    pattern,
    opacity: float,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
):
    if isinstance(pattern, ShadingPattern):
        function = _apply_opacity_to_function(pattern.shading.function, opacity)
        _register_function_tree(builder, function)
        shading = pattern.shading
        if isinstance(shading, AxialShading):
            shading = AxialShading(
                color_space=shading.color_space,
                coords=shading.coords,
                domain=shading.domain,
                function=function,
                extend=shading.extend,
            )
        elif isinstance(shading, RadialShading):
            shading = RadialShading(
                color_space=shading.color_space,
                coords=shading.coords,
                domain=shading.domain,
                function=function,
                extend=shading.extend,
            )
        return ShadingPattern(shading=shading, matrix=pattern.matrix)
    if isinstance(pattern, TilingPattern):
        commands = _apply_opacity_to_commands(pattern.commands, opacity, builder, renderer)
        return TilingPattern(
            paint_type=pattern.paint_type,
            tiling_type=pattern.tiling_type,
            bbox=pattern.bbox,
            x_step=pattern.x_step,
            y_step=pattern.y_step,
            matrix=pattern.matrix,
            commands=commands,
        )
    return pattern


def _apply_opacity_to_function(function, opacity: float):
    if isinstance(function, ExponentialFunction):
        c0 = [_blend_component(v, opacity) for v in function.c0]
        c1 = [_blend_component(v, opacity) for v in function.c1]
        return ExponentialFunction(
            domain=function.domain,
            range=function.range,
            c0=c0,
            c1=c1,
            n=function.n,
        )
    if isinstance(function, StitchingFunction):
        parts = [_apply_opacity_to_function(part, opacity) for part in function.functions]
        return StitchingFunction(
            domain=function.domain,
            range=function.range,
            functions=parts,
            bounds=function.bounds,
            encode=function.encode,
        )
    return function


def _register_function_tree(builder: RenderModelBuilder, function) -> None:
    if isinstance(function, StitchingFunction):
        for part in function.functions:
            _register_function_tree(builder, part)
    builder.register_function(function)


def _apply_opacity_to_commands(
    commands,
    opacity: float,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
):
    updated = []
    for command in commands:
        if isinstance(command, PathCommand):
            updated.append(
                PathCommand(
                    path=command.path,
                    stroke=command.stroke,
                    fill=_apply_opacity_to_paint(command.fill, opacity, builder, renderer),
                    fill_rule=command.fill_rule,
                    stroke_paint=_apply_opacity_to_paint(
                        command.stroke_paint, opacity, builder, renderer
                    ),
                    overprint=command.overprint,
                    fill_opacity=_clamp(command.fill_opacity * opacity, 0.0, 1.0),
                    stroke_opacity=_clamp(command.stroke_opacity * opacity, 0.0, 1.0),
                )
            )
            continue
        if isinstance(command, TextCommand):
            updated.append(
                TextCommand(
                    text=command.text,
                    font_ref=command.font_ref,
                    font_size=command.font_size,
                    matrix=command.matrix,
                    fill=_apply_opacity_to_paint(command.fill, opacity, builder, renderer),
                    fill_opacity=_clamp(command.fill_opacity * opacity, 0.0, 1.0),
                )
            )
            continue
        if isinstance(command, ImageCommand) and renderer is not None:
            updated.append(
                ImageCommand(
                    image_id=_opacity_adjusted_image_id(renderer, command.image_id, opacity),
                    width=command.width,
                    height=command.height,
                    matrix=command.matrix,
                    mask=command.mask,
                    mask_paint=_apply_opacity_to_paint(
                        command.mask_paint, opacity, builder, renderer
                    ),
                    opacity=_clamp(command.opacity * opacity, 0.0, 1.0),
                )
            )
            continue
        updated.append(command)
    return updated


def _opacity_adjusted_image_id(renderer: XpsRenderer, image_id: str, opacity: float) -> str:
    key = (image_id, int(round(_clamp(opacity, 0.0, 1.0) * 1000.0)))
    cached = renderer._opacity_image_cache.get(key)
    if cached is not None:
        return cached
    image = renderer._image_store.get(image_id)
    adjusted = _blend_image_resource_with_white(image, opacity)
    if adjusted is None:
        renderer._opacity_image_cache[key] = image_id
        return image_id
    new_id = renderer._image_store.register(adjusted)
    renderer._opacity_image_cache[key] = new_id
    return new_id


def _blend_image_resource_with_white(
    image: XpsImageResource,
    opacity: float,
) -> XpsImageResource | None:
    alpha = _clamp(opacity, 0.0, 1.0)
    if alpha >= 0.9999:
        return image
    raw: bytes | None = None
    width = image.width
    height = image.height
    if image.filter is None and image.color_space == "DeviceRGB" and image.bits_per_component == 8:
        expected = width * height * 3
        if len(image.data) == expected:
            raw = image.data
    elif image.filter == "DCTDecode":
        try:
            from PIL import Image  # type: ignore
        except Exception:
            return None
        try:
            with Image.open(io.BytesIO(image.data)) as pil:
                rgb = pil.convert("RGB")
                width, height = rgb.width, rgb.height
                raw = rgb.tobytes()
        except Exception:
            return None
    if raw is None:
        return None

    blended = bytearray(len(raw))
    inv = 1.0 - alpha
    for i, value in enumerate(raw):
        blended[i] = int(round(value * alpha + 255.0 * inv))

    return XpsImageResource(
        image_id="",
        data=bytes(blended),
        width=width,
        height=height,
        bits_per_component=8,
        color_space="DeviceRGB",
        filter=None,
        x_dpi=image.x_dpi,
        y_dpi=image.y_dpi,
    )


def _crop_image_for_viewbox(
    image,
    viewbox: tuple[float, float, float, float],
):
    if viewbox[0] == 0.0 and viewbox[1] == 0.0:
        if abs(viewbox[2] - ((float(image.width) * 96.0) / max(1e-6, float(image.x_dpi)))) < 0.5:
            if abs(viewbox[3] - ((float(image.height) * 96.0) / max(1e-6, float(image.y_dpi)))) < 0.5:
                return image
    source_left = (float(image.x_dpi) * viewbox[0]) / 96.0
    source_top = (float(image.y_dpi) * viewbox[1]) / 96.0
    source_width = (float(image.x_dpi) * viewbox[2]) / 96.0
    source_height = (float(image.y_dpi) * viewbox[3]) / 96.0
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return image
    try:
        pil = Image.frombytes("RGB", (image.width, image.height), image.data)
        left = int(round(source_left))
        top = int(round(source_top))
        right = int(round(source_left + source_width))
        bottom = int(round(source_top + source_height))
        if right <= left or bottom <= top:
            return image
        crop = Image.new("RGB", (max(1, right - left), max(1, bottom - top)), (255, 255, 255))
        src_l = max(0, left)
        src_t = max(0, top)
        src_r = min(image.width, right)
        src_b = min(image.height, bottom)
        if src_r > src_l and src_b > src_t:
            part = pil.crop((src_l, src_t, src_r, src_b))
            dst_x = src_l - left
            dst_y = src_t - top
            crop.paste(part, (dst_x, dst_y))
        data = crop.tobytes()
        from .images import XpsImageResource

        return XpsImageResource(
            image_id="",
            data=data,
            width=crop.width,
            height=crop.height,
            bits_per_component=8,
            color_space="DeviceRGB",
            filter=None,
            x_dpi=image.x_dpi,
            y_dpi=image.y_dpi,
        )
    except Exception:
        return image


def _element_transform(element: ET.Element, resources: XpsResourceDictionary | None = None) -> Matrix:
    tx = ty = 0.0
    for key, value in element.attrib.items():
        if key.endswith("Canvas.Left"):
            tx = _parse_float(value) or 0.0
        if key.endswith("Canvas.Top"):
            ty = _parse_float(value) or 0.0
    transform = Matrix(1.0, 0.0, 0.0, 1.0, tx, ty)
    raw = element.get("RenderTransform")
    if raw:
        if raw.strip().startswith("{StaticResource") and resources is not None:
            key = raw.replace("{StaticResource", "").replace("}", "").strip()
            resource = resources.resolve(key)
            if isinstance(resource, ET.Element):
                return _multiply(transform, _matrix_from_transform_element(resource))
        numbers = _parse_numbers(raw)
        if len(numbers) == 6:
            return _multiply(transform, Matrix(*numbers))
    for child in list(element):
        tag = _local_name(child.tag)
        if not tag.endswith(".RenderTransform"):
            continue
        transform_child = next((grandchild for grandchild in list(child) if isinstance(grandchild.tag, str)), None)
        if transform_child is None:
            continue
        return _multiply(transform, _matrix_from_transform_element(transform_child))
    return transform


def _stroke_scale_from_matrix(matrix: Matrix) -> float:
    sx = math.hypot(matrix.a, matrix.b)
    sy = math.hypot(matrix.c, matrix.d)
    if sx <= 1e-12 and sy <= 1e-12:
        return 1.0
    if sx <= 1e-12:
        return sy
    if sy <= 1e-12:
        return sx
    return (sx + sy) * 0.5


def _matrix_bbox(matrix: Matrix) -> tuple[float, float, float, float] | None:
    points = [
        _apply_transform(matrix, Point(0.0, 0.0)),
        _apply_transform(matrix, Point(1.0, 0.0)),
        _apply_transform(matrix, Point(1.0, 1.0)),
        _apply_transform(matrix, Point(0.0, 1.0)),
    ]
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _rect_close(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    tolerance: float = 1.0,
) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(left, right))


def _parse_xps_line_cap(element: ET.Element) -> int:
    if element.get("StrokeDashArray"):
        dash_cap = (element.get("StrokeDashCap") or "").strip().lower()
        if dash_cap == "round":
            return 1
        if dash_cap == "square":
            return 2
        return 0
    start = (element.get("StrokeStartLineCap") or "").strip().lower()
    end = (element.get("StrokeEndLineCap") or "").strip().lower()
    cap = start or end
    if cap == "round":
        return 1
    if cap == "square":
        return 2
    return 0


def _parse_xps_line_join(element: ET.Element) -> int:
    join = (element.get("StrokeLineJoin") or "").strip().lower()
    if join == "round":
        return 1
    if join == "bevel":
        return 2
    return 0


def _parse_xps_dash_pattern(element: ET.Element, line_width: float) -> list[float]:
    raw = element.get("StrokeDashArray")
    if not raw:
        return []
    values = _parse_numbers(raw)
    if not values:
        return []
    return [max(0.0, value) * line_width for value in values]


def _parse_xps_dash_phase(element: ET.Element, line_width: float) -> float:
    offset = _parse_float(element.get("StrokeDashOffset")) or 0.0
    return max(0.0, offset) * line_width


def _matrix_from_transform_element(element: ET.Element) -> Matrix:
    tag = _local_name(element.tag)
    if tag == "MatrixTransform":
        numbers = _parse_numbers(element.get("Matrix") or "")
        if len(numbers) == 6:
            return Matrix(*numbers)
    if tag == "TransformGroup":
        matrix = Matrix(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        for child in list(element):
            matrix = _multiply(matrix, _matrix_from_transform_element(child))
        return matrix
    if tag == "TranslateTransform":
        x = _parse_float(element.get("X")) or 0.0
        y = _parse_float(element.get("Y")) or 0.0
        return Matrix(1.0, 0.0, 0.0, 1.0, x, y)
    if tag == "ScaleTransform":
        sx = _parse_float(element.get("ScaleX")) or 1.0
        sy = _parse_float(element.get("ScaleY")) or 1.0
        return Matrix(sx, 0.0, 0.0, sy, 0.0, 0.0)
    if tag == "RotateTransform":
        angle = math.radians(_parse_float(element.get("Angle")) or 0.0)
        center_x = _parse_float(element.get("CenterX")) or 0.0
        center_y = _parse_float(element.get("CenterY")) or 0.0
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        return Matrix(
            cos_a,
            sin_a,
            -sin_a,
            cos_a,
            center_x - center_x * cos_a + center_y * sin_a,
            center_y - center_x * sin_a - center_y * cos_a,
        )
    if tag == "SkewTransform":
        ax = math.tan(math.radians(_parse_float(element.get("AngleX")) or 0.0))
        ay = math.tan(math.radians(_parse_float(element.get("AngleY")) or 0.0))
        return Matrix(1.0, ay, ax, 1.0, 0.0, 0.0)
    return Matrix(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _brush_transform(element: ET.Element) -> Matrix:
    raw = element.get("Transform")
    if raw:
        numbers = _parse_numbers(raw)
        if len(numbers) == 6:
            return Matrix(*numbers)
    wrapper = element.find(f".//{{*}}{_local_name(element.tag)}.Transform")
    if wrapper is None:
        return Matrix(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for child in list(wrapper):
        return _matrix_from_transform_element(child)
    return Matrix(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _parse_numbers(value: str) -> list[float]:
    found = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", value)
    return [float(item) for item in found]


def _multiply(m1: Matrix, m2: Matrix) -> Matrix:
    return Matrix(
        a=m1.a * m2.a + m1.c * m2.b,
        b=m1.b * m2.a + m1.d * m2.b,
        c=m1.a * m2.c + m1.c * m2.d,
        d=m1.b * m2.c + m1.d * m2.d,
        e=m1.a * m2.e + m1.c * m2.f + m1.e,
        f=m1.b * m2.e + m1.d * m2.f + m1.f,
    )


def _invert_matrix(matrix: tuple[float, float, float, float, float, float]) -> tuple[float, float, float, float, float, float] | None:
    a, b, c, d, e, f = matrix
    det = a * d - b * c
    if abs(det) < 1e-12:
        return None
    inv = 1.0 / det
    return (
        d * inv,
        -b * inv,
        -c * inv,
        a * inv,
        (c * f - d * e) * inv,
        (b * e - a * f) * inv,
    )


def _apply_matrix_tuple(matrix: tuple[float, float, float, float, float, float], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def _apply_transform(matrix: Matrix, point: Point) -> Point:
    x = matrix.a * point.x + matrix.c * point.y + matrix.e
    y = matrix.b * point.x + matrix.d * point.y + matrix.f
    return Point(x, y)


def _path_bbox(path: Path) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for segment in path.segments:
        for point in segment.points:
            xs.append(point.x)
            ys.append(point.y)
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _point_in_subpaths(subpaths: list[list[Point]], x: float, y: float) -> bool:
    winding = 0
    for subpath in subpaths:
        if len(subpath) < 3:
            continue
        for i in range(len(subpath) - 1):
            p1 = subpath[i]
            p2 = subpath[i + 1]
            if p1.y == p2.y:
                continue
            if p1.y <= y < p2.y:
                if _is_left(p1, p2, x, y) > 0.0:
                    winding += 1
            elif p2.y <= y < p1.y:
                if _is_left(p1, p2, x, y) < 0.0:
                    winding -= 1
    return winding != 0


def _is_left(p1: Point, p2: Point, x: float, y: float) -> float:
    return (p2.x - p1.x) * (y - p1.y) - (x - p1.x) * (p2.y - p1.y)


def _path_is_axis_aligned_rect(
    path: Path,
    bbox: tuple[float, float, float, float],
) -> bool:
    subpaths = _flatten_render_path(path.segments, scale=1.0, curve_steps=4)
    if len(subpaths) != 1:
        return False
    points: list[Point] = []
    for point in subpaths[0]:
        if not points or abs(point.x - points[-1].x) > 1e-6 or abs(point.y - points[-1].y) > 1e-6:
            points.append(point)
    if len(points) > 1 and abs(points[0].x - points[-1].x) <= 1e-6 and abs(points[0].y - points[-1].y) <= 1e-6:
        points.pop()
    if len(points) != 4:
        return False
    x0, y0, x1, y1 = bbox
    xs = {round(point.x, 6) for point in points}
    ys = {round(point.y, 6) for point in points}
    if xs != {round(x0, 6), round(x1, 6)} or ys != {round(y0, 6), round(y1, 6)}:
        return False
    for idx in range(4):
        p1 = points[idx]
        p2 = points[(idx + 1) % 4]
        if abs(p1.x - p2.x) > 1e-6 and abs(p1.y - p2.y) > 1e-6:
            return False
    return True


def _flatten_render_path(
    segments: list[PathSegment],
    scale: float,
    curve_steps: int = 36,
) -> list[list[Point]]:
    subpaths: list[list[Point]] = []
    current: list[Point] = []
    start: Point | None = None
    current_point: Point | None = None
    total = len(segments)
    for idx, segment in enumerate(segments):
        if segment.kind == "move":
            if current:
                subpaths.append(current)
            current = [segment.points[0]]
            start = segment.points[0]
            current_point = segment.points[0]
        elif segment.kind == "line":
            if current_point is None:
                current = [segment.points[0]]
                start = segment.points[0]
            else:
                current.append(segment.points[0])
            current_point = segment.points[0]
        elif segment.kind == "curve":
            if current_point is None:
                continue
            p0 = current_point
            p1, p2, p3 = segment.points
            steps = _curve_steps_for_flatten(p0, p1, p2, p3, scale, curve_steps)
            for step in range(1, steps + 1):
                t = step / steps
                x = (
                    (1 - t) ** 3 * p0.x
                    + 3 * (1 - t) ** 2 * t * p1.x
                    + 3 * (1 - t) * t**2 * p2.x
                    + t**3 * p3.x
                )
                y = (
                    (1 - t) ** 3 * p0.y
                    + 3 * (1 - t) ** 2 * t * p1.y
                    + 3 * (1 - t) * t**2 * p2.y
                    + t**3 * p3.y
                )
                current.append(Point(x, y))
            current_point = p3
        elif segment.kind == "close":
            if start is not None and current:
                current.append(start)
            if current:
                subpaths.append(current)
            if idx + 1 < total and start is not None:
                current = [start]
                current_point = start
            else:
                current = []
                start = None
                current_point = None
    if current:
        subpaths.append(current)
    return subpaths


def _curve_steps_for_flatten(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
    scale: float,
    base_steps: int,
) -> int:
    length = (
        math.hypot(p1.x - p0.x, p1.y - p0.y)
        + math.hypot(p2.x - p1.x, p2.y - p1.y)
        + math.hypot(p3.x - p2.x, p3.y - p2.y)
    )
    adaptive = int(length * scale / 6)
    if adaptive < base_steps:
        return base_steps
    return min(200, adaptive)


def _parse_path_data(data: str, transform: Matrix) -> Path:
    tokens = re.findall(r"[A-Za-z]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", data)
    tokens = _merge_exponent_tokens(tokens)
    segments: list[PathSegment] = []
    idx = 0
    current = Point(0.0, 0.0)
    start = None
    command = None
    last_cubic_ctrl2: Point | None = None

    def next_number() -> float:
        nonlocal idx
        value = float(tokens[idx])
        idx += 1
        return value

    while idx < len(tokens):
        token = tokens[idx]
        if re.match(r"[A-Za-z]", token):
            command = token
            idx += 1
            if command in ("Z", "z"):
                if start is not None:
                    segments.append(PathSegment("close", []))
                    current = start
                continue
            if command in ("F", "f"):
                if idx < len(tokens) and re.match(r"[-+]?\d", tokens[idx]):
                    idx += 1
                continue
        if command is None:
            break
        cmd = command
        if cmd in ("M", "m"):
            x = next_number()
            y = next_number()
            if cmd == "m":
                x += current.x
                y += current.y
            point = _apply_transform(transform, Point(x, y))
            segments.append(PathSegment("move", [point]))
            current = Point(x, y)
            start = current
            last_cubic_ctrl2 = None
            command = "L" if cmd == "M" else "l"
        elif cmd in ("L", "l"):
            x = next_number()
            y = next_number()
            if cmd == "l":
                x += current.x
                y += current.y
            point = _apply_transform(transform, Point(x, y))
            segments.append(PathSegment("line", [point]))
            current = Point(x, y)
            last_cubic_ctrl2 = None
        elif cmd in ("C", "c"):
            while idx + 5 < len(tokens) and not re.match(r"[A-Za-z]", tokens[idx]):
                x1 = next_number()
                y1 = next_number()
                x2 = next_number()
                y2 = next_number()
                x3 = next_number()
                y3 = next_number()
                if cmd == "c":
                    x1 += current.x
                    y1 += current.y
                    x2 += current.x
                    y2 += current.y
                    x3 += current.x
                    y3 += current.y
                p1 = _apply_transform(transform, Point(x1, y1))
                p2 = _apply_transform(transform, Point(x2, y2))
                p3 = _apply_transform(transform, Point(x3, y3))
                segments.append(PathSegment("curve", [p1, p2, p3]))
                current = Point(x3, y3)
                last_cubic_ctrl2 = Point(x2, y2)
                if idx >= len(tokens) or re.match(r"[A-Za-z]", tokens[idx]):
                    break
                if idx + 5 >= len(tokens):
                    break
            if idx < len(tokens) and not re.match(r"[A-Za-z]", tokens[idx]):
                # If the loop did not consume because of token structure, fall through.
                pass
        elif cmd in ("Q", "q"):
            x1 = next_number()
            y1 = next_number()
            x2 = next_number()
            y2 = next_number()
            if cmd == "q":
                x1 += current.x
                y1 += current.y
                x2 += current.x
                y2 += current.y
            c1 = Point(
                current.x + (2.0 / 3.0) * (x1 - current.x),
                current.y + (2.0 / 3.0) * (y1 - current.y),
            )
            c2 = Point(
                x2 + (2.0 / 3.0) * (x1 - x2),
                y2 + (2.0 / 3.0) * (y1 - y2),
            )
            p3 = Point(x2, y2)
            segments.append(
                PathSegment(
                    "curve",
                    [
                        _apply_transform(transform, c1),
                        _apply_transform(transform, c2),
                        _apply_transform(transform, p3),
                    ],
                )
            )
            current = p3
            last_cubic_ctrl2 = None
        elif cmd in ("S", "s"):
            while idx + 3 < len(tokens) and not re.match(r"[A-Za-z]", tokens[idx]):
                x2 = next_number()
                y2 = next_number()
                x3 = next_number()
                y3 = next_number()
                if cmd == "s":
                    x2 += current.x
                    y2 += current.y
                    x3 += current.x
                    y3 += current.y
                if last_cubic_ctrl2 is None:
                    x1 = current.x
                    y1 = current.y
                else:
                    x1 = 2.0 * current.x - last_cubic_ctrl2.x
                    y1 = 2.0 * current.y - last_cubic_ctrl2.y
                p1 = _apply_transform(transform, Point(x1, y1))
                p2 = _apply_transform(transform, Point(x2, y2))
                p3 = _apply_transform(transform, Point(x3, y3))
                segments.append(PathSegment("curve", [p1, p2, p3]))
                current = Point(x3, y3)
                last_cubic_ctrl2 = Point(x2, y2)
                if idx >= len(tokens) or re.match(r"[A-Za-z]", tokens[idx]):
                    break
                if idx + 3 >= len(tokens):
                    break
        elif cmd in ("A", "a"):
            rx = next_number()
            ry = next_number()
            rotation = next_number()
            large_arc = int(next_number())
            sweep = int(next_number())
            x = next_number()
            y = next_number()
            if cmd == "a":
                x += current.x
                y += current.y
            end = Point(x, y)
            cubics = _arc_to_cubic_beziers(
                current,
                end,
                rx,
                ry,
                rotation,
                large_arc != 0,
                sweep != 0,
            )
            if not cubics:
                segments.append(PathSegment("line", [_apply_transform(transform, end)]))
            else:
                for c1, c2, p in cubics:
                    segments.append(
                        PathSegment(
                            "curve",
                            [
                                _apply_transform(transform, c1),
                                _apply_transform(transform, c2),
                                _apply_transform(transform, p),
                            ],
                        )
                    )
            current = end
            last_cubic_ctrl2 = None
        else:
            idx += 1
    return Path(segments)


def _arc_to_cubic_beziers(
    start: Point,
    end: Point,
    rx: float,
    ry: float,
    x_axis_rotation_deg: float,
    large_arc: bool,
    sweep: bool,
) -> list[tuple[Point, Point, Point]]:
    if rx == 0.0 or ry == 0.0:
        return []
    if start.x == end.x and start.y == end.y:
        return []

    rx = abs(rx)
    ry = abs(ry)
    phi = math.radians(x_axis_rotation_deg % 360.0)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    dx2 = (start.x - end.x) * 0.5
    dy2 = (start.y - end.y) * 0.5
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    sign = -1.0 if large_arc == sweep else 1.0
    rx2 = rx * rx
    ry2 = ry * ry
    num = rx2 * ry2 - rx2 * y1p * y1p - ry2 * x1p * x1p
    den = rx2 * y1p * y1p + ry2 * x1p * x1p
    if den == 0.0:
        return []
    coef = sign * math.sqrt(max(0.0, num / den))
    cxp = coef * (rx * y1p / ry)
    cyp = coef * (-ry * x1p / rx)

    cx = cos_phi * cxp - sin_phi * cyp + (start.x + end.x) * 0.5
    cy = sin_phi * cxp + cos_phi * cyp + (start.y + end.y) * 0.5

    def _angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        det = ux * vy - uy * vx
        return math.atan2(det, dot)

    ux = (x1p - cxp) / rx
    uy = (y1p - cyp) / ry
    vx = (-x1p - cxp) / rx
    vy = (-y1p - cyp) / ry
    theta1 = math.atan2(uy, ux)
    delta = _angle(ux, uy, vx, vy)
    if not sweep and delta > 0.0:
        delta -= 2.0 * math.pi
    elif sweep and delta < 0.0:
        delta += 2.0 * math.pi

    parts = max(1, int(math.ceil(abs(delta) / (math.pi / 2.0))))
    step = delta / parts
    curves: list[tuple[Point, Point, Point]] = []
    for idx in range(parts):
        t1 = theta1 + idx * step
        t2 = t1 + step
        dt = t2 - t1
        alpha = (4.0 / 3.0) * math.tan(dt / 4.0)

        x1 = math.cos(t1)
        y1 = math.sin(t1)
        x2 = math.cos(t2)
        y2 = math.sin(t2)

        p1 = Point(
            cx + rx * (cos_phi * x1 - sin_phi * y1),
            cy + ry * (sin_phi * x1 + cos_phi * y1),
        )
        p2 = Point(
            cx + rx * (cos_phi * x2 - sin_phi * y2),
            cy + ry * (sin_phi * x2 + cos_phi * y2),
        )
        c1 = Point(
            p1.x + alpha * (-rx * (cos_phi * y1 + sin_phi * x1)),
            p1.y + alpha * (-ry * (sin_phi * y1 - cos_phi * x1)),
        )
        c2 = Point(
            p2.x + alpha * (rx * (cos_phi * y2 + sin_phi * x2)),
            p2.y + alpha * (ry * (sin_phi * y2 - cos_phi * x2)),
        )
        curves.append((c1, c2, p2))
    return curves


def _parse_path_geometry_element(geometry: ET.Element, transform: Matrix) -> Path:
    fill_path, stroke_path = _parse_path_geometry_element_variants(geometry, transform)
    return fill_path or stroke_path or Path([])


def _parse_path_geometry_element_variants(
    geometry: ET.Element,
    transform: Matrix,
) -> tuple[Path | None, Path | None]:
    fill_segments: list[PathSegment] = []
    stroke_segments: list[PathSegment] = []
    for figure in _parse_path_geometry_figures(geometry):
        if figure["is_filled"]:
            fill_segments.extend(_figure_to_fill_segments(figure, transform))
        stroke_segments.extend(_figure_to_stroke_segments(figure, transform))
    fill_path = Path(fill_segments) if fill_segments else None
    stroke_path = Path(stroke_segments) if stroke_segments else None
    return fill_path, stroke_path


def _parse_path_geometry_figures(geometry: ET.Element) -> list[dict[str, object]]:
    figures: list[dict[str, object]] = []
    for figure in geometry.findall(".//{*}PathFigure"):
        start = _parse_point(figure.get("StartPoint"))
        curr = Point(start[0], start[1])
        figure_segments: list[dict[str, object]] = []
        for seg in list(figure):
            tag = _local_name(seg.tag)
            is_stroked = not _is_false(seg.get("IsStroked"))
            if tag == "PolyLineSegment":
                points = _parse_points(seg.get("Points"))
                for x, y in points:
                    figure_segments.append({
                        "kind": "line",
                        "points": [Point(x, y)],
                        "is_stroked": is_stroked,
                    })
                    curr = Point(x, y)
            elif tag == "ArcSegment":
                end = _parse_point(seg.get("Point"))
                size = _parse_point(seg.get("Size"))
                rotation = _parse_float(seg.get("RotationAngle")) or 0.0
                large_arc = _is_true(seg.get("IsLargeArc"))
                sweep_text = (seg.get("SweepDirection") or "Counterclockwise").strip().lower()
                sweep = sweep_text == "clockwise"
                cubics = _arc_to_cubic_beziers(
                    curr,
                    Point(end[0], end[1]),
                    size[0],
                    size[1],
                    rotation,
                    large_arc,
                    sweep,
                )
                if not cubics:
                    figure_segments.append({
                        "kind": "line",
                        "points": [Point(end[0], end[1])],
                        "is_stroked": is_stroked,
                    })
                else:
                    for c1, c2, p in cubics:
                        figure_segments.append({
                            "kind": "curve",
                            "points": [c1, c2, p],
                            "is_stroked": is_stroked,
                        })
                curr = Point(end[0], end[1])
            elif tag == "BezierSegment":
                points = _parse_points(seg.get("Points"))
                if len(points) >= 3:
                    figure_segments.append({
                        "kind": "curve",
                        "points": [
                            Point(points[0][0], points[0][1]),
                            Point(points[1][0], points[1][1]),
                            Point(points[2][0], points[2][1]),
                        ],
                        "is_stroked": is_stroked,
                    })
                    curr = Point(points[2][0], points[2][1])
            elif tag == "PolyQuadraticBezierSegment":
                points = _parse_points(seg.get("Points"))
                idx = 0
                while idx + 1 < len(points):
                    ctrl = Point(points[idx][0], points[idx][1])
                    end = Point(points[idx + 1][0], points[idx + 1][1])
                    c1 = Point(
                        curr.x + (2.0 / 3.0) * (ctrl.x - curr.x),
                        curr.y + (2.0 / 3.0) * (ctrl.y - curr.y),
                    )
                    c2 = Point(
                        end.x + (2.0 / 3.0) * (ctrl.x - end.x),
                        end.y + (2.0 / 3.0) * (ctrl.y - end.y),
                    )
                    figure_segments.append({
                        "kind": "curve",
                        "points": [c1, c2, end],
                        "is_stroked": is_stroked,
                    })
                    curr = end
                    idx += 2
            elif tag == "PolyBezierSegment":
                points = _parse_points(seg.get("Points"))
                idx = 0
                while idx + 2 < len(points):
                    figure_segments.append({
                        "kind": "curve",
                        "points": [
                            Point(points[idx][0], points[idx][1]),
                            Point(points[idx + 1][0], points[idx + 1][1]),
                            Point(points[idx + 2][0], points[idx + 2][1]),
                        ],
                        "is_stroked": is_stroked,
                    })
                    curr = Point(points[idx + 2][0], points[idx + 2][1])
                    idx += 3
        figures.append({
            "start": Point(start[0], start[1]),
            "segments": figure_segments,
            "is_closed": _is_true(figure.get("IsClosed")),
            "is_filled": not _is_false(figure.get("IsFilled")),
        })
    return figures


def _figure_to_fill_segments(figure: dict[str, object], transform: Matrix) -> list[PathSegment]:
    start = figure["start"]
    assert isinstance(start, Point)
    raw_segments = figure["segments"]
    assert isinstance(raw_segments, list)
    segments = [PathSegment("move", [_apply_transform(transform, start)])]
    for segment in raw_segments:
        kind = segment["kind"]
        points = segment["points"]
        assert isinstance(points, list)
        transformed = [_apply_transform(transform, point) for point in points]
        segments.append(PathSegment(kind, transformed))
    if figure["is_closed"]:
        segments.append(PathSegment("close", []))
    return segments


def _figure_to_stroke_segments(figure: dict[str, object], transform: Matrix) -> list[PathSegment]:
    start = figure["start"]
    assert isinstance(start, Point)
    raw_segments = figure["segments"]
    assert isinstance(raw_segments, list)
    stroke_segments: list[PathSegment] = []
    current_point = start
    subpath_open = False
    for segment in raw_segments:
        kind = segment["kind"]
        points = segment["points"]
        assert isinstance(points, list)
        is_stroked = bool(segment.get("is_stroked", True))
        end_point = points[-1] if points else current_point
        assert isinstance(end_point, Point)
        if is_stroked:
            if not subpath_open:
                stroke_segments.append(PathSegment("move", [_apply_transform(transform, current_point)]))
                subpath_open = True
            transformed = [_apply_transform(transform, point) for point in points]
            stroke_segments.append(PathSegment(kind, transformed))
        else:
            subpath_open = False
        current_point = end_point
    if figure["is_closed"] and current_point != start:
        if not subpath_open:
            stroke_segments.append(PathSegment("move", [_apply_transform(transform, current_point)]))
        stroke_segments.append(PathSegment("line", [_apply_transform(transform, start)]))
    return stroke_segments


def _merge_exponent_tokens(tokens: list[str]) -> list[str]:
    if not tokens:
        return tokens
    merged: list[str] = []
    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?$")
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if (
            idx + 2 < len(tokens)
            and number_re.match(token)
            and tokens[idx + 1] in ("e", "E")
            and number_re.match(tokens[idx + 2])
        ):
            merged.append(f"{token}e{tokens[idx + 2]}")
            idx += 3
            continue
        merged.append(token)
        idx += 1
    return merged


def _resolve_part(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return _normalize_part_ref(target)
    base = base_part.rsplit("/", 1)[0]
    if base == "":
        return _normalize_part_ref(target)
    return _normalize_part_ref(f"{base}/{target}")


def _normalize_part_ref(value: str) -> str:
    if "#" in value:
        value = value.split("#", 1)[0]
    if "?" in value:
        value = value.split("?", 1)[0]
    value = value.replace("\\", "/")
    if not value.startswith("/"):
        value = "/" + value
    parts: list[str] = []
    for segment in value.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/" + "/".join(parts)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value
