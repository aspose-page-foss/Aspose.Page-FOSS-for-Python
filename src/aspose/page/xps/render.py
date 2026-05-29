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
from .images import (
    XpsImageResource,
    XpsImageStore,
    decode_jpeg,
    decode_png,
    decode_tiff,
)
from .resources import XpsResourceDictionary
from .package import XpsPackage


XPS_UNIT_SCALE = 72.0 / 96.0


class _IndexEntry:
    def __init__(
        self,
        glyph_id: int | None = None,
        advance: float | None = None,
        u_offset: float | None = None,
        v_offset: float | None = None,
    ) -> None:
        self.glyph_id = glyph_id
        self.advance = advance
        self.u_offset = u_offset
        self.v_offset = v_offset


class XpsRenderer:
    """Render XPS XML to the shared render model.

    Example:
        >>> from aspose.page.common.render_model import RenderModelBuilder
        >>> from aspose.page.xps.images import XpsImageStore
        >>> renderer = XpsRenderer(RenderModelBuilder(), XpsImageStore())
        >>> isinstance(renderer, XpsRenderer)
        True
    """
    def __init__(self, builder: RenderModelBuilder, image_store: XpsImageStore) -> None:
        self._builder = builder
        self._image_store = image_store
        self._package: XpsPackage | None = None
        self._current_part: str | None = None
        self._font_gid_to_code: dict[str, dict[int, int]] = {}
        self._font_cache: dict[str, TrueTypeFont] = {}
        self._opacity_image_cache: dict[tuple[str, int], str] = {}
        self._icc_profile_cache: dict[str, bytes] = {}

    def set_package(self, package: XpsPackage) -> None:
        self._package = package

    def set_current_part(self, part_name: str) -> None:
        self._current_part = part_name

    def render_fixed_page(self, xml: bytes, resources: XpsResourceDictionary | None = None) -> None:
        """Render a FixedPage XML payload into the render model."""
        root = ET.fromstring(xml)
        width = (_parse_float(root.get("Width")) or 0.0) * XPS_UNIT_SCALE
        height = (_parse_float(root.get("Height")) or 0.0) * XPS_UNIT_SCALE
        self._builder.begin_page(width, height)
        page_resources = _merge_resources(root, resources)
        # XPS coordinates are top-left with +Y down; render model uses +Y up.
        transform = Matrix(XPS_UNIT_SCALE, 0.0, 0.0, -XPS_UNIT_SCALE, 0.0, height)
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
        local_transform = _element_transform(element)
        combined = _multiply(transform, local_transform)
        if tag == "Canvas":
            canvas_resources = _merge_resources(element, resources)
            clip_data = element.get("Clip")
            if clip_data:
                clip_path = _parse_path_data(clip_data, combined)
                self._builder.save_state()
                self._builder.clip(clip_path)
            for child in list(element):
                self._render_element(child, canvas_resources, combined)
            if clip_data:
                self._builder.restore_state()
            return
        if tag == "Path":
            data = _extract_path_data(element, resources)
            if data:
                path = _parse_path_data(data, combined)
            else:
                geometry = _extract_path_geometry_element(element, resources)
                if geometry is None:
                    return
                path = _parse_path_geometry_element(geometry, combined)
            fill = _resolve_paint(
                _extract_paint_value(element, "Fill"),
                resources,
                self._builder,
                self,
                combined,
                combined,
            )
            stroke = _resolve_paint(
                _extract_paint_value(element, "Stroke"),
                resources,
                self._builder,
                self,
                combined,
                combined,
            )
            fill_opacity = 1.0
            stroke_opacity = 1.0
            mask_brush = _extract_opacity_mask_brush(element)
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
                )
                mask_alpha = _opacity_from_brush_element(mask_brush, resources, self)
                if mask_alpha is not None and fill == fill_before_mask:
                    alpha = _clamp(mask_alpha, 0.0, 1.0)
                    fill_opacity *= alpha
                    stroke_opacity *= alpha
            opacity = _parse_float(element.get("Opacity"))
            if opacity is not None:
                opacity = _clamp(opacity, 0.0, 1.0)
                fill_opacity *= opacity
                stroke_opacity *= opacity
            stroke_style = None
            if stroke is not None:
                thickness = (_parse_float(element.get("StrokeThickness")) or 1.0) * XPS_UNIT_SCALE
                stroke_style = StrokeStyle(
                    line_width=thickness,
                    line_cap=0,
                    line_join=0,
                    miter_limit=10.0,
                    dash=[],
                    dash_phase=0.0,
                )
            self._builder.add_path(
                path,
                stroke_style,
                fill,
                stroke_paint=stroke,
                fill_opacity=fill_opacity,
                stroke_opacity=stroke_opacity,
            )
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
            is_sideways = _is_true(element.get("IsSideways"))
            style = (element.get("StyleSimulations") or "").strip()
            if style == "ItalicSimulation" or style == "BoldItalicSimulation":
                run_matrix = _multiply(run_matrix, Matrix(1.0, 0.0, 0.2, 1.0, 0.0, 0.0))

            # Handle per-glyph placement for sideways and Indices-based metrics.
            rtl = (bidi_level % 2) == 1
            if rtl and (not is_sideways) and (not _indices_have_metrics(parsed_indices)):
                # Keep RTL runs as one text command to preserve engine-native
                # spacing while anchoring the run at the right-side origin.
                text_out = text[::-1]
                run_width = 0.0
                for char in text:
                    run_width += self._glyph_advance_points(font_ref, char, font_size)
                rtl_matrix = _multiply(run_matrix, Matrix(1.0, 0.0, 0.0, 1.0, -run_width, 0.0))
                self._builder.add_text(text_out, font_ref, font_size, rtl_matrix, fill)
                if style == "BoldSimulation" or style == "BoldItalicSimulation":
                    bold_matrix = _multiply(
                        rtl_matrix, Matrix(1.0, 0.0, 0.0, 1.0, font_size * 0.04, 0.0)
                    )
                    self._builder.add_text(text_out, font_ref, font_size, bold_matrix, fill)
            elif is_sideways or _indices_have_metrics(parsed_indices) or rtl:
                self._emit_glyph_run(
                    text=text,
                    font_ref=font_ref,
                    font_size=font_size,
                    base_matrix=run_matrix,
                    fill=fill,
                    bidi_level=bidi_level,
                    is_sideways=is_sideways,
                    style=style,
                    indices=parsed_indices,
                )
            else:
                text_out = text[::-1] if bidi_level % 2 == 1 else text
                self._builder.add_text(text_out, font_ref, font_size, run_matrix, fill)
                if style == "BoldSimulation" or style == "BoldItalicSimulation":
                    bold_matrix = _multiply(run_matrix, Matrix(1.0, 0.0, 0.0, 1.0, font_size * 0.04, 0.0))
                    self._builder.add_text(text_out, font_ref, font_size, bold_matrix, fill)
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

    def _emit_glyph_run(
        self,
        text: str,
        font_ref: str,
        font_size: float,
        base_matrix: Matrix,
        fill: Paint | None,
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
            self._builder.add_text(char, font_ref, font_size, glyph_matrix, fill)
            if style == "BoldSimulation" or style == "BoldItalicSimulation":
                bold_matrix = _multiply(glyph_matrix, Matrix(1.0, 0.0, 0.0, 1.0, font_size * 0.04, 0.0))
                self._builder.add_text(char, font_ref, font_size, bold_matrix, fill)
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
            font = TrueTypeFont(self._package.read(part))
        except Exception:
            return None
        self._font_cache[font_ref] = font
        return font

    def _gid_to_unicode(self, font_ref: str) -> dict[int, int]:
        cached = self._font_gid_to_code.get(font_ref)
        if cached is not None:
            return cached
        if self._package is None:
            self._font_gid_to_code[font_ref] = {}
            return {}
        part = _normalize_part_ref(font_ref)
        if not self._package.has_part(part):
            self._font_gid_to_code[font_ref] = {}
            return {}
        try:
            font = TrueTypeFont(self._package.read(part))
        except Exception:
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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _merge_resources(element: ET.Element, parent: XpsResourceDictionary | None) -> XpsResourceDictionary:
    items: dict[str, object] = {}
    for res in element.findall(".//{*}ResourceDictionary"):
        for child in list(res):
            key = _resource_key(child)
            if key:
                items[key] = child
    return XpsResourceDictionary(items=items, parent=parent)


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
        radius = max(radius_x, radius_y)
        shading = RadialShading(
            color_space=DeviceColorSpace("DeviceRGB"),
            coords=(origin[0], origin[1], 0.0, center[0], center[1], radius),
            domain=gradient_domain,
            function=function,
            extend=(True, True),
        )
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if paint_transform is not None:
        matrix = (
            paint_transform.a,
            paint_transform.b,
            paint_transform.c,
            paint_transform.d,
            paint_transform.e,
            paint_transform.f,
        )
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
    for cycle in range(cycles):
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
    return deduped, (0.0, float(cycles))


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
        XPS_UNIT_SCALE,
        0.0,
        0.0,
        XPS_UNIT_SCALE,
        viewport[0] * XPS_UNIT_SCALE,
        viewport[1] * XPS_UNIT_SCALE,
    )
    if paint_transform is not None:
        tx = (
            paint_transform.a * viewport[0]
            + paint_transform.c * viewport[1]
            + paint_transform.e
        )
        ty = (
            paint_transform.b * viewport[0]
            + paint_transform.d * viewport[1]
            + paint_transform.f
        )
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
        commands=commands,
    )
    pattern_id = builder.register_pattern(pattern)
    return Paint("Pattern", PatternPaint(pattern_id=pattern_id, base_space_id=None, base_components=None))


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
    nested_builder = RenderModelBuilder()
    nested_builder.begin_page(1.0, 1.0)
    nested = XpsRenderer(nested_builder, renderer._image_store)
    if renderer._package is not None:
        nested.set_package(renderer._package)
    if renderer._current_part is not None:
        nested.set_current_part(renderer._current_part)
    transform = Matrix(XPS_UNIT_SCALE, 0.0, 0.0, XPS_UNIT_SCALE, 0.0, 0.0)
    for child in list(visual):
        nested._render_element(child, resources, transform)
    nested_builder.end_page()
    page = nested_builder.document().pages[0]
    if not page.commands:
        return None
    viewbox = _parse_rect(element.get("Viewbox"), default=(0.0, 0.0, 1.0, 1.0))
    viewport = _parse_rect(element.get("Viewport"), default=viewbox)
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
        if segment.startswith("(") and ")" in segment:
            segment = segment.split(")", 1)[1].strip()
            if not segment:
                result.append(_IndexEntry())
                continue
        parts = [item.strip() for item in segment.split(",")]
        glyph_id = _parse_int(parts[0]) if parts else None
        advance = _parse_float(parts[1]) if len(parts) > 1 and parts[1] else None
        u_offset = _parse_float(parts[2]) if len(parts) > 2 and parts[2] else None
        v_offset = _parse_float(parts[3]) if len(parts) > 3 and parts[3] else None
        result.append(_IndexEntry(glyph_id=glyph_id, advance=advance, u_offset=u_offset, v_offset=v_offset))
    return result


def _indices_have_metrics(entries: list[_IndexEntry]) -> bool:
    for entry in entries:
        if entry.advance is not None or entry.u_offset is not None or entry.v_offset is not None:
            return True
    return False


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


def _apply_opacity_mask_to_fill_paint(
    fill: Paint | None,
    mask_brush: ET.Element,
    resources: XpsResourceDictionary | None,
    builder: RenderModelBuilder,
    renderer: XpsRenderer | None,
    paint_transform: Matrix | None,
    brush_origin_transform: Matrix | None,
) -> Paint | None:
    if fill is None:
        return fill
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
                alpha_img = img.getchannel("A")
            else:
                alpha_img = img.convert("L")
            alpha_img = alpha_img.convert("L")
            rgb = Image.new("RGB", alpha_img.size, (255, 255, 255))
            px_alpha = alpha_img.load()
            px_rgb = rgb.load()
            br = int(round(_clamp(base_color[0], 0.0, 1.0) * 255.0))
            bg = int(round(_clamp(base_color[1], 0.0, 1.0) * 255.0))
            bb = int(round(_clamp(base_color[2], 0.0, 1.0) * 255.0))
            for yy in range(alpha_img.height):
                for xx in range(alpha_img.width):
                    a = px_alpha[xx, yy] / 255.0
                    rr = int(round(br * a + 255.0 * (1.0 - a)))
                    gg = int(round(bg * a + 255.0 * (1.0 - a)))
                    bbb = int(round(bb * a + 255.0 * (1.0 - a)))
                    px_rgb[xx, yy] = (rr, gg, bbb)
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


def _opacity_from_gradient_brush_at(brush: ET.Element, x: float, y: float) -> float:
    stops = _collect_gradient_alpha_stops(brush)
    if not stops:
        return 1.0
    tag = _local_name(brush.tag)
    t = 0.0
    if tag == "LinearGradientBrush":
        s = _parse_point(brush.get("StartPoint"))
        e = _parse_point(brush.get("EndPoint"))
        dx = e[0] - s[0]
        dy = e[1] - s[1]
        denom = dx * dx + dy * dy
        t = 0.0 if denom <= 1e-9 else ((x - s[0]) * dx + (y - s[1]) * dy) / denom
    elif tag == "RadialGradientBrush":
        c = _parse_point(brush.get("Center"))
        rx = abs(_parse_float(brush.get("RadiusX")) or 0.0)
        ry = abs(_parse_float(brush.get("RadiusY")) or 0.0)
        if rx <= 1e-9 or ry <= 1e-9:
            t = 0.0
        else:
            dx = (x - c[0]) / rx
            dy = (y - c[1]) / ry
            t = math.sqrt(dx * dx + dy * dy)
    spread = (brush.get("SpreadMethod") or "Pad").strip().lower()
    if spread == "repeat":
        t = t % 1.0
    elif spread == "reflect":
        v = abs(t)
        n = int(math.floor(v))
        frac = v - n
        t = frac if (n % 2 == 0) else (1.0 - frac)
    else:
        t = _clamp(t, 0.0, 1.0)
    return _interpolate_alpha(stops, t)


def _collect_gradient_alpha_stops(brush: ET.Element) -> list[tuple[float, float]]:
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
            if img.mode in ("L", "LA"):
                gray = img.convert("L")
                hist = gray.histogram()
                total_px = max(1, gray.width * gray.height)
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


def _element_transform(element: ET.Element) -> Matrix:
    tx = ty = 0.0
    for key, value in element.attrib.items():
        if key.endswith("Canvas.Left"):
            tx = _parse_float(value) or 0.0
        if key.endswith("Canvas.Top"):
            ty = _parse_float(value) or 0.0
    transform = Matrix(1.0, 0.0, 0.0, 1.0, tx, ty)
    raw = element.get("RenderTransform")
    if raw:
        numbers = _parse_numbers(raw)
        if len(numbers) == 6:
            return _multiply(transform, Matrix(*numbers))
    return transform


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


def _apply_transform(matrix: Matrix, point: Point) -> Point:
    x = matrix.a * point.x + matrix.c * point.y + matrix.e
    y = matrix.b * point.x + matrix.d * point.y + matrix.f
    return Point(x, y)


def _parse_path_data(data: str, transform: Matrix) -> Path:
    tokens = re.findall(r"[A-Za-z]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", data)
    tokens = _merge_exponent_tokens(tokens)
    segments: list[PathSegment] = []
    idx = 0
    current = Point(0.0, 0.0)
    start = None
    command = None

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
        elif cmd in ("C", "c"):
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
    segments: list[PathSegment] = []
    for figure in geometry.findall(".//{*}PathFigure"):
        start = _parse_point(figure.get("StartPoint"))
        start_pt = _apply_transform(transform, Point(start[0], start[1]))
        segments.append(PathSegment("move", [start_pt]))
        curr = Point(start[0], start[1])
        for seg in list(figure):
            tag = _local_name(seg.tag)
            if tag == "PolyLineSegment":
                points = _parse_points(seg.get("Points"))
                for x, y in points:
                    segments.append(PathSegment("line", [_apply_transform(transform, Point(x, y))]))
                    curr = Point(x, y)
            elif tag == "ArcSegment":
                end = _parse_point(seg.get("Point"))
                # Keep minimal support by approximating arc as a line segment.
                segments.append(PathSegment("line", [_apply_transform(transform, Point(end[0], end[1]))]))
                curr = Point(end[0], end[1])
            elif tag == "BezierSegment":
                points = _parse_points(seg.get("Points"))
                if len(points) >= 3:
                    p1 = _apply_transform(transform, Point(points[0][0], points[0][1]))
                    p2 = _apply_transform(transform, Point(points[1][0], points[1][1]))
                    p3 = _apply_transform(transform, Point(points[2][0], points[2][1]))
                    segments.append(PathSegment("curve", [p1, p2, p3]))
                    curr = Point(points[2][0], points[2][1])
            elif tag == "PolyBezierSegment":
                points = _parse_points(seg.get("Points"))
                idx = 0
                while idx + 2 < len(points):
                    p1 = _apply_transform(transform, Point(points[idx][0], points[idx][1]))
                    p2 = _apply_transform(transform, Point(points[idx + 1][0], points[idx + 1][1]))
                    p3 = _apply_transform(transform, Point(points[idx + 2][0], points[idx + 2][1]))
                    segments.append(PathSegment("curve", [p1, p2, p3]))
                    curr = Point(points[idx + 2][0], points[idx + 2][1])
                    idx += 3
        if _is_true(figure.get("IsClosed")):
            segments.append(PathSegment("close", []))
    return Path(segments)


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
        return target
    base = base_part.rsplit("/", 1)[0]
    if base == "":
        return "/" + target
    return f"{base}/{target}"


def _normalize_part_ref(value: str) -> str:
    if "#" in value:
        value = value.split("#", 1)[0]
    if "?" in value:
        value = value.split("?", 1)[0]
    if value.startswith("/"):
        return value
    return "/" + value


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value
