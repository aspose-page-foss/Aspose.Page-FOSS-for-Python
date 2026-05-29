"""Raster renderer for render model output."""

from __future__ import annotations

import io
import math
import os
import struct
import time

from dataclasses import dataclass
from typing import Iterable

from ..common.render_model import (
    ClipCommand,
    ImageCommand,
    Matrix,
    Paint,
    PathCommand,
    Path,
    PathSegment,
    RenderDocument,
    RenderPage,
    StateRestoreCommand,
    StateSaveCommand,
    TextCommand,
    Point,
)
from ..common.color_resources import (
    DeviceColorSpace,
    PatternPaint,
    ShadingPattern,
    TilingPattern,
)
from ..ps.ttf_outline import GlyphPoint, TrueTypeFont, load_ttf_font
from ..ps.fonts import FontResolver, FontResource


@dataclass
class RasterSurface:
    """In-memory RGBA pixel surface.

    Example:
        >>> surface = RasterSurface(2, 2, bytearray([255, 255, 255, 255] * 4))
        >>> surface.width
        2
    """

    width: int
    height: int
    pixels: bytearray
    clip_mask: bytearray | None = None

    @classmethod
    def create(cls, width: int, height: int, background: tuple[int, int, int, int]) -> "RasterSurface":
        pixel = bytes(background)
        return cls(width, height, bytearray(pixel * (width * height)))

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        if self.clip_mask is not None:
            if self.clip_mask[y * self.width + x] == 0:
                return
        idx = (y * self.width + x) * 4
        self.pixels[idx:idx + 4] = bytes(color)

    def get_pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return (0, 0, 0, 0)
        idx = (y * self.width + x) * 4
        return (
            self.pixels[idx],
            self.pixels[idx + 1],
            self.pixels[idx + 2],
            self.pixels[idx + 3],
        )


class RasterRenderer:
    """Render a RenderDocument to a raster surface.

    Example:
        >>> from aspose.page.common.render_model import RenderDocument, RenderPage
        >>> doc = RenderDocument(pages=[RenderPage(width=72, height=72)])
        >>> surface = RasterRenderer(dpi=72).render(doc)
        >>> surface.width
        72
    """

    def __init__(
        self,
        dpi: int = 72,
        font_resolver: FontResolver | None = None,
        background: tuple[int, int, int, int] = (255, 255, 255, 255),
    ) -> None:
        if dpi <= 0:
            raise ValueError("dpi must be positive")
        self._dpi = dpi
        self._font_resolver = font_resolver
        self._background = background
        self._font_cache: dict[str, TrueTypeFont] = {}
        self._trace_enabled = False
        self._trace_stats: dict[str, float] | None = None

    def render(self, document: RenderDocument, page_index: int = 0) -> RasterSurface:
        """Render a single page from a document.

        Example:
            >>> from aspose.page.common.render_model import RenderDocument, RenderPage
            >>> doc = RenderDocument(pages=[RenderPage(width=36, height=36)])
            >>> RasterRenderer(dpi=72).render(doc).height
            36
        """
        page = self._get_page(document, page_index)
        self._trace_enabled = os.getenv("RASTER_TRACE") == "1"
        self._trace_stats = (
            {
                "clip": 0.0,
                "path_fill": 0.0,
                "path_stroke": 0.0,
                "text": 0.0,
                "image": 0.0,
                "pattern_fill": 0.0,
                "pattern_tile": 0.0,
                "flatten": 0.0,
                "downsample": 0.0,
            }
            if self._trace_enabled
            else None
        )
        trace_every = 0
        trace_slow_ms = 0.0
        if self._trace_enabled:
            try:
                trace_every = int(os.getenv("RASTER_TRACE_EVERY", "0") or 0)
            except ValueError:
                trace_every = 0
            try:
                trace_slow_ms = float(os.getenv("RASTER_TRACE_SLOW_MS", "0") or 0.0)
            except ValueError:
                trace_slow_ms = 0.0
        processed = 0
        counts: dict[str, int] = {}
        total_start = time.perf_counter()
        scale = self._dpi / 72.0
        has_curve, min_stroke_px = _analyze_page_for_supersample(page, scale)
        supersample = _choose_supersample(has_curve, min_stroke_px)
        width_px, height_px = _page_pixel_size(page.width, page.height, scale)
        surface = RasterSurface.create(
            width_px * supersample,
            height_px * supersample,
            self._background,
        )
        resources = document.resources
        user_height_px = height_px
        clip_stack: list[bytearray | None] = []
        current_clip: bytearray | None = None
        for command in page.commands:
            cmd_start = time.perf_counter() if self._trace_enabled else 0.0
            if isinstance(command, StateSaveCommand):
                clip_stack.append(None if current_clip is None else current_clip[:])
                counts["save"] = counts.get("save", 0) + 1
                processed += 1
                if trace_every and processed % trace_every == 0:
                    self._trace_progress(processed, "save", counts)
                continue
            if isinstance(command, StateRestoreCommand):
                current_clip = clip_stack.pop() if clip_stack else None
                surface.clip_mask = current_clip
                counts["restore"] = counts.get("restore", 0) + 1
                processed += 1
                if trace_every and processed % trace_every == 0:
                    self._trace_progress(processed, "restore", counts)
                continue
            if isinstance(command, ClipCommand):
                clip_start = time.perf_counter()
                clip_mask = _build_clip_mask(
                    command.path.segments,
                    scale * supersample,
                    surface.width,
                    surface.height,
                    even_odd=command.fill_rule == "evenodd",
                )
                if self._trace_stats is not None:
                    self._trace_stats["clip"] += time.perf_counter() - clip_start
                if current_clip is None:
                    current_clip = clip_mask
                else:
                    current_clip = _intersect_masks(current_clip, clip_mask)
                surface.clip_mask = current_clip
                counts["clip"] = counts.get("clip", 0) + 1
                processed += 1
                if trace_every and processed % trace_every == 0:
                    self._trace_progress(processed, "clip", counts)
                if trace_slow_ms and self._trace_enabled:
                    cmd_elapsed = (time.perf_counter() - cmd_start) * 1000.0
                    if cmd_elapsed >= trace_slow_ms:
                        print(
                            f"RASTER SLOW op=clip ms={cmd_elapsed:.2f}",
                            flush=True,
                        )
                continue
            if isinstance(command, PathCommand):
                self._draw_path(
                    surface,
                    command,
                    scale * supersample,
                    resources,
                    user_height_px,
                )
                counts["path"] = counts.get("path", 0) + 1
            elif isinstance(command, TextCommand):
                text_start = time.perf_counter()
                self._draw_text(
                    surface,
                    command,
                    scale * supersample,
                    resources,
                    user_height_px,
                )
                if self._trace_stats is not None:
                    self._trace_stats["text"] += time.perf_counter() - text_start
                counts["text"] = counts.get("text", 0) + 1
            elif isinstance(command, ImageCommand):
                image_start = time.perf_counter()
                self._draw_image(surface, command, resources, scale * supersample)
                if self._trace_stats is not None:
                    self._trace_stats["image"] += time.perf_counter() - image_start
                counts["image"] = counts.get("image", 0) + 1
            else:
                counts["other"] = counts.get("other", 0) + 1
            processed += 1
            if trace_every and processed % trace_every == 0:
                self._trace_progress(processed, type(command).__name__, counts)
            if trace_slow_ms and self._trace_enabled:
                cmd_elapsed = (time.perf_counter() - cmd_start) * 1000.0
                if cmd_elapsed >= trace_slow_ms:
                    print(
                        f"RASTER SLOW op={type(command).__name__} ms={cmd_elapsed:.2f}",
                        flush=True,
                    )
        if supersample > 1:
            downsample_start = time.perf_counter()
            surface = _downsample(surface, supersample)
            if self._trace_stats is not None:
                self._trace_stats["downsample"] += time.perf_counter() - downsample_start
        if self._trace_stats is not None:
            total = time.perf_counter() - total_start
            stats = self._trace_stats
            min_stroke_label = "none" if min_stroke_px is None else f"{min_stroke_px:.2f}"
            print(
                "RASTER TRACE total={:.3f}s clip={:.3f}s fill={:.3f}s "
                "pattern_fill={:.3f}s stroke={:.3f}s text={:.3f}s image={:.3f}s "
                "pattern_tile={:.3f}s flatten={:.3f}s downsample={:.3f}s "
                "supersample={} curves={} min_stroke_px={}".format(
                    total,
                    stats["clip"],
                    stats["path_fill"],
                    stats["pattern_fill"],
                    stats["path_stroke"],
                    stats["text"],
                    stats["image"],
                    stats["pattern_tile"],
                    stats["flatten"],
                    stats["downsample"],
                    supersample,
                    "yes" if has_curve else "no",
                    min_stroke_label,
                ),
                flush=True,
            )
        return surface

    def _get_page(self, document: RenderDocument, page_index: int) -> RenderPage:
        if page_index < 0 or page_index >= len(document.pages):
            raise IndexError("page_index out of range")
        return document.pages[page_index]

    def _trace_progress(self, processed: int, op_name: str, counts: dict[str, int]) -> None:
        if self._trace_stats is None:
            return
        stats = self._trace_stats
        counts_str = " ".join(f"{name}={counts[name]}" for name in sorted(counts))
        print(
            "RASTER PROGRESS n={} op={} clip={:.3f}s fill={:.3f}s pattern_fill={:.3f}s "
            "stroke={:.3f}s text={:.3f}s image={:.3f}s pattern_tile={:.3f}s "
            "flatten={:.3f}s downsample={:.3f}s counts: {}".format(
                processed,
                op_name,
                stats["clip"],
                stats["path_fill"],
                stats["pattern_fill"],
                stats["path_stroke"],
                stats["text"],
                stats["image"],
                stats["pattern_tile"],
                stats["flatten"],
                stats["downsample"],
                counts_str,
            ),
            flush=True,
        )

    def _draw_path(
        self,
        surface: RasterSurface,
        command: PathCommand,
        scale: float,
        resources,
        user_height_px: int,
    ) -> None:
        rect = _axis_aligned_rect(command.path.segments)
        subpaths: list[list[Point]] | None = None
        if rect is None or command.stroke is not None:
            flatten_start = time.perf_counter()
            subpaths = _flatten_path(command.path.segments, scale)
            if self._trace_stats is not None:
                self._trace_stats["flatten"] += time.perf_counter() - flatten_start
        if command.fill is not None:
            fill_color = _paint_to_rgba(command.fill)
            if command.fill.kind == "Pattern" and isinstance(command.fill.value, PatternPaint):
                pattern = resources.patterns.get(command.fill.value.pattern_id)
                if isinstance(pattern, TilingPattern):
                    tile_start = time.perf_counter()
                    sampler = _pattern_sampler(
                        pattern,
                        resources,
                        command.fill.value,
                        scale,
                        surface.height,
                    )
                    if self._trace_stats is not None:
                        self._trace_stats["pattern_tile"] += time.perf_counter() - tile_start
                    fill_start = time.perf_counter()
                    _fill_paths_pattern(
                        surface,
                        subpaths or [],
                        scale,
                        sampler,
                        even_odd=command.fill_rule == "evenodd",
                    )
                    if self._trace_stats is not None:
                        self._trace_stats["pattern_fill"] += time.perf_counter() - fill_start
                elif isinstance(pattern, ShadingPattern):
                    if fill_color is not None:
                        fill_start = time.perf_counter()
                        if rect is not None:
                            _fill_rect(surface, rect, scale, fill_color)
                        else:
                            _fill_paths(
                                surface,
                                subpaths or [],
                                scale,
                                fill_color,
                                even_odd=command.fill_rule == "evenodd",
                            )
                        if self._trace_stats is not None:
                            self._trace_stats["path_fill"] += time.perf_counter() - fill_start
            elif fill_color is not None:
                fill_start = time.perf_counter()
                if rect is not None:
                    _fill_rect(surface, rect, scale, fill_color)
                else:
                    _fill_paths(
                        surface,
                        subpaths or [],
                        scale,
                        fill_color,
                        even_odd=command.fill_rule == "evenodd",
                    )
                if self._trace_stats is not None:
                    self._trace_stats["path_fill"] += time.perf_counter() - fill_start
        if command.stroke is not None:
            stroke_color = _paint_to_rgba(command.stroke_paint or command.fill) or (0, 0, 0, 255)
            stroke_width = max(1, int(round(command.stroke.line_width * scale)))
            dash_pattern = [value * scale for value in command.stroke.dash] if command.stroke.dash else []
            dash_phase = command.stroke.dash_phase * scale
            stroke_start = time.perf_counter()
            for subpath in subpaths or []:
                points = _to_pixels(subpath, scale, surface.height)
                if dash_pattern:
                    _draw_dashed_polyline(
                        surface,
                        points,
                        dash_pattern,
                        dash_phase,
                        stroke_width,
                        stroke_color,
                    )
                else:
                    for start, end in _iter_segments(points):
                        _draw_stroked_segment(surface, start, end, stroke_width, stroke_color)
            if self._trace_stats is not None:
                self._trace_stats["path_stroke"] += time.perf_counter() - stroke_start

    def _draw_text(
        self,
        surface: RasterSurface,
        command: TextCommand,
        scale: float,
        resources,
        user_height_px: int,
    ) -> None:
        trace_enabled = os.getenv("RASTER_TEXT_TRACE") == "1"
        trace_ms = 0.0
        if trace_enabled:
            try:
                trace_ms = float(os.getenv("RASTER_TEXT_TRACE_MS", "0") or 0.0)
            except ValueError:
                trace_ms = 0.0
        t0 = time.perf_counter() if trace_enabled else 0.0
        color = _paint_to_rgba(command.fill) or (0, 0, 0, 255)
        font = self._resolve_font(command.font_ref)
        if font is not None:
            metrics_font = None
            if self._font_resolver is not None:
                try:
                    metrics_font = self._font_resolver.resolve(command.font_ref)
                except Exception:
                    metrics_font = None
            self._draw_text_outline(
                surface,
                command,
                scale,
                resources,
                font,
                user_height_px,
                metrics_font,
            )
            if trace_enabled:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                if trace_ms <= 0 or elapsed_ms >= trace_ms:
                    print(
                        "RASTER TEXT TRACE outline font={} len={} ms={:.2f}".format(
                            command.font_ref,
                            len(command.text),
                            elapsed_ms,
                        ),
                        flush=True,
                    )
            return
        fallback_font = None
        if self._font_resolver is not None:
            try:
                fallback_font = self._font_resolver.resolve(command.font_ref)
            except Exception:
                fallback_font = None
        pattern_sampler = None
        if command.fill is not None and command.fill.kind == "Pattern" and isinstance(command.fill.value, PatternPaint):
            pattern = resources.patterns.get(command.fill.value.pattern_id)
            if isinstance(pattern, TilingPattern):
                pattern_sampler = _pattern_sampler(
                    pattern,
                    resources,
                    command.fill.value,
                    scale,
                    surface.height,
                )
        font_size = command.font_size
        origin_x, origin_y = _matrix_origin(command.matrix)
        shift = _palatino_baseline_shift(command.font_ref, font_size)
        if shift:
            origin_x -= command.matrix.c * shift
            origin_y -= command.matrix.d * shift
        a = command.matrix.a
        b = command.matrix.b
        x = origin_x
        y = origin_y
        for char in command.text:
            if char == " ":
                if fallback_font is not None:
                    advance_units = self._glyph_advance_units(fallback_font, char)
                    advance = advance_units / max(1.0, fallback_font.units_per_em) * font_size
                    x += a * advance
                    y += b * advance
                continue
            width = font_size * 0.5
            height = font_size
            if pattern_sampler is not None:
                _fill_rect_pattern(surface, x, y, width, height, scale, pattern_sampler)
            else:
                self._draw_rect(surface, x, y, width, height, scale, color)
            if fallback_font is None:
                x += font_size * 0.6
                continue
            advance_units = self._glyph_advance_units(fallback_font, char)
            advance = advance_units / max(1.0, fallback_font.units_per_em) * font_size
            x += a * advance
            y += b * advance
        if trace_enabled:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if trace_ms <= 0 or elapsed_ms >= trace_ms:
                print(
                    "RASTER TEXT TRACE fallback font={} len={} ms={:.2f}".format(
                        command.font_ref,
                        len(command.text),
                        elapsed_ms,
                    ),
                    flush=True,
                )

    def _resolve_font(self, font_ref: str) -> TrueTypeFont | None:
        if self._font_resolver is None:
            return None
        try:
            resource = self._font_resolver.resolve(font_ref)
        except Exception:
            resource = None
        embedded_data = resource.font_program if resource is not None else None
        if not embedded_data:
            embedded = self._font_resolver.get_embedded_type42(font_ref)
            if embedded is not None:
                embedded_data = embedded.data
        if embedded_data:
            key = f"embedded:{font_ref}"
            cached = self._font_cache.get(key)
            if cached is not None:
                return cached
            try:
                font = TrueTypeFont(embedded_data)
            except Exception:
                font = None
            if font is not None:
                self._font_cache[key] = font
                return font
        path = self._font_resolver.resolve_ttf_path(font_ref)
        if path is None:
            return None
        key = str(path)
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        try:
            font = load_ttf_font(path)
        except Exception:
            return None
        self._font_cache[key] = font
        return font

    def _glyph_advance_units(self, font: FontResource, char: str) -> float:
        code = ord(char)
        width_units = None
        if font.code_widths is not None:
            width_units = font.code_widths.get(code)
        if width_units is None:
            glyph_name = font.encoding.get(code, ".notdef")
            width_units = self._font_resolver.get_glyph_width(font, glyph_name) if self._font_resolver is not None else 0.0
        if width_units == 0.0:
            width_units = font.units_per_em * 0.5
        return float(width_units)

    def _draw_text_outline(
        self,
        surface: RasterSurface,
        command: TextCommand,
        scale: float,
        resources,
        font: TrueTypeFont,
        user_height_px: int,
        metrics_font: FontResource | None,
    ) -> None:
        a, b, c, d, e, f = (
            command.matrix.a,
            command.matrix.b,
            command.matrix.c,
            command.matrix.d,
            command.matrix.e,
            command.matrix.f,
        )
        shift = _palatino_baseline_shift(command.font_ref, command.font_size)
        if shift:
            e -= c * shift
            f -= d * shift
        trace_enabled = os.getenv("RASTER_TEXT_TRACE") == "1"
        glyph_trace_ms = 0.0
        if trace_enabled:
            try:
                glyph_trace_ms = float(os.getenv("RASTER_TEXT_GLYPH_MS", "0") or 0.0)
            except ValueError:
                glyph_trace_ms = 0.0
        size_scale = (command.font_size or 1.0) / max(1.0, font.units_per_em)
        fill = command.fill
        pattern_sampler = None
        fill_color = _paint_to_rgba(fill) if fill is not None else (0, 0, 0, 255)
        if fill is not None and fill.kind == "Pattern" and isinstance(fill.value, PatternPaint):
            pattern = resources.patterns.get(fill.value.pattern_id)
            if isinstance(pattern, TilingPattern):
                pattern_sampler = _pattern_sampler(
                    pattern,
                    resources,
                    fill.value,
                    scale,
                    surface.height,
                )
        for char in command.text:
            glyph_id = font.glyph_id_for_code(ord(char))
            glyph_t0 = time.perf_counter() if trace_enabled and glyph_trace_ms >= 0 else 0.0
            contours = font.glyph_outline(glyph_id)
            if trace_enabled and glyph_trace_ms >= 0:
                glyph_elapsed = (time.perf_counter() - glyph_t0) * 1000.0
                if glyph_trace_ms <= 0 or glyph_elapsed >= glyph_trace_ms:
                    print(
                        "RASTER TEXT TRACE glyph font={} char={} gid={} ms={:.2f}".format(
                            command.font_ref,
                            ord(char),
                            glyph_id,
                            glyph_elapsed,
                        ),
                        flush=True,
                    )
            if contours:
                # Always use even-odd for glyph fills in the Python rasterizer.
                # TrueType contour winding can vary across fonts/resources and
                # nonzero filling may close counters ("holes") in letters.
                use_even_odd = True
                path = _contours_to_path(contours, size_scale, a, b, c, d, e, f)
                subpaths = _flatten_path(path.segments, scale)
                if pattern_sampler is not None:
                    _fill_paths_pattern(
                        surface,
                        subpaths,
                        scale,
                        pattern_sampler,
                        even_odd=use_even_odd,
                    )
                elif fill_color is not None:
                    _fill_paths(
                        surface,
                        subpaths,
                        scale,
                        fill_color,
                        even_odd=use_even_odd,
                    )
            if metrics_font is not None:
                advance_units = self._glyph_advance_units(metrics_font, char)
                advance = advance_units / max(1.0, metrics_font.units_per_em) * command.font_size
            else:
                advance = font.glyph_advance(glyph_id) * size_scale
            e += a * advance
            f += b * advance

    def _draw_image_placeholder(self, surface: RasterSurface, command: ImageCommand, scale: float) -> None:
        x, y = _matrix_origin(command.matrix)
        color = (220, 220, 220, 255)
        self._draw_rect(surface, x, y, float(command.width), float(command.height), scale, color)

    def _draw_image(
        self,
        surface: RasterSurface,
        command: ImageCommand,
        resources,
        scale: float,
    ) -> None:
        resource = resources.images.get(command.image_id)
        if resource is None:
            self._draw_image_placeholder(surface, command, scale)
            return
        image_data, image_width, image_height, color_space, bits_per_component = _materialize_image_resource(
            resource
        )
        matrix = (
            command.matrix.a,
            command.matrix.b,
            command.matrix.c,
            command.matrix.d,
            command.matrix.e,
            command.matrix.f,
        )
        inv = _invert_matrix(matrix)
        if inv is None:
            self._draw_image_placeholder(surface, command, scale)
            return
        corners = [
            _apply_matrix(matrix, 0.0, 0.0),
            _apply_matrix(matrix, 1.0, 0.0),
            _apply_matrix(matrix, 0.0, 1.0),
            _apply_matrix(matrix, 1.0, 1.0),
        ]
        min_x = min(point[0] for point in corners)
        max_x = max(point[0] for point in corners)
        min_y = min(point[1] for point in corners)
        max_y = max(point[1] for point in corners)
        px0 = max(0, int(math.floor(min_x * scale)))
        px1 = min(surface.width - 1, int(math.ceil(max_x * scale)))
        py0 = max(0, int(math.floor((surface.height - 1) - max_y * scale)))
        py1 = min(surface.height - 1, int(math.ceil((surface.height - 1) - min_y * scale)))
        if px1 < px0 or py1 < py0:
            return

        mask_color = _paint_to_rgba(command.mask_paint) if command.mask_paint is not None else (0, 0, 0, 255)
        aa_samples = 2 if (resource.width <= 128 or resource.height <= 128) else 1
        projected_w = max(0.0, (max_x - min_x) * scale)
        tiny_mask_mode = (resource.mask or command.mask) and resource.width <= 32 and projected_w <= 3.0
        small_mask_x_bias = 0.5 if tiny_mask_mode else 0.0
        for py in range(py0, py1 + 1):
            for px in range(px0, px1 + 1):
                if resource.mask or command.mask:
                    mask_samples = 1 if tiny_mask_mode else (8 if aa_samples > 1 else 1)
                    # PostScript imagemask polarity semantics:
                    # True  => 1-bit samples paint.
                    # False => 0-bit samples paint.
                    invert_mask = not bool(getattr(resource, "mask_polarity", True))
                    coverage, total = _sample_mask_coverage(
                        inv,
                        px,
                        py,
                        scale,
                        surface.height,
                        mask_samples,
                        image_data,
                        image_width,
                        image_height,
                        invert_mask,
                        small_mask_x_bias,
                    )
                    if total == 0 or coverage <= 0.0:
                        continue
                    if tiny_mask_mode:
                        surface.set_pixel(px, py, mask_color)
                        continue
                    if coverage >= 0.999:
                        surface.set_pixel(px, py, mask_color)
                    else:
                        bg = surface.get_pixel(px, py)
                        alpha = coverage * (mask_color[3] / 255.0)
                        inv_alpha = 1.0 - alpha
                        out_a = int(round(bg[3] * inv_alpha + mask_color[3] * alpha))
                        blended = (
                            int(round(bg[0] * inv_alpha + mask_color[0] * alpha)),
                            int(round(bg[1] * inv_alpha + mask_color[1] * alpha)),
                            int(round(bg[2] * inv_alpha + mask_color[2] * alpha)),
                            max(0, min(255, out_a)),
                        )
                        surface.set_pixel(px, py, blended)
                    continue
                color = _sample_image_color_average(
                    inv,
                    px,
                    py,
                    scale,
                    surface.height,
                    aa_samples,
                    image_data,
                    image_width,
                    image_height,
                    color_space,
                    bits_per_component,
                    resource.decode,
                    0.0,
                )
                if color is not None:
                    if color[3] >= 255:
                        surface.set_pixel(px, py, color)
                    elif color[3] > 0:
                        bg = surface.get_pixel(px, py)
                        if bg[3] == 0:
                            surface.set_pixel(px, py, color)
                        else:
                            alpha = color[3] / 255.0
                            blended = (
                                int(round(bg[0] * (1.0 - alpha) + color[0] * alpha)),
                                int(round(bg[1] * (1.0 - alpha) + color[1] * alpha)),
                                int(round(bg[2] * (1.0 - alpha) + color[2] * alpha)),
                                255,
                            )
                            surface.set_pixel(px, py, blended)

    def _draw_rect(
        self,
        surface: RasterSurface,
        x: float,
        y: float,
        width: float,
        height: float,
        scale: float,
        color: tuple[int, int, int, int],
    ) -> None:
        x0 = int(round(x * scale))
        y0 = int(round((surface.height - 1) - y * scale - height * scale))
        x1 = int(round(x * scale + width * scale))
        y1 = int(round((surface.height - 1) - y * scale))
        for py in range(min(y0, y1), max(y0, y1) + 1):
            for px in range(min(x0, x1), max(x0, x1) + 1):
                surface.set_pixel(px, py, color)


def _matrix_origin(matrix: Matrix) -> tuple[float, float]:
    return matrix.e, matrix.f


def _materialize_image_resource(resource) -> tuple[bytes, int, int, str, int]:
    filter_name = getattr(resource, "filter", None)
    if filter_name == "CCITTFaxDecode":
        decoded = _decode_ccitt_image(
            resource.data,
            int(resource.width),
            int(resource.height),
            getattr(resource, "filter_params", None),
            getattr(resource, "mask", False),
        )
        if decoded is not None:
            data, width, height, color_space, bits = decoded
            return data, width, height, color_space, bits
        return (
            resource.data,
            resource.width,
            resource.height,
            resource.color_space,
            resource.bits_per_component,
        )
    if filter_name != "DCTDecode":
        return (
            resource.data,
            resource.width,
            resource.height,
            resource.color_space,
            resource.bits_per_component,
        )
    decoded = _decode_dct_image(resource.data, resource.color_space)
    if decoded is None:
        return (
            resource.data,
            resource.width,
            resource.height,
            resource.color_space,
            resource.bits_per_component,
        )
    data, width, height, color_space = decoded
    return data, width, height, color_space, 8


def _decode_dct_image(data: bytes, color_space: str) -> tuple[bytes, int, int, str] | None:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        try:
            import skia  # type: ignore
        except Exception:
            return None
        try:
            sk_data = (
                skia.Data.MakeWithoutCopy(data)
                if hasattr(skia.Data, "MakeWithoutCopy")
                else skia.Data.MakeWithCopy(data)
            )
            image = skia.Image.MakeFromEncoded(sk_data)
            if image is None:
                return None
            arr = image.toarray()
            if arr is None:
                return None
            height = int(arr.shape[0])
            width = int(arr.shape[1])
            if height <= 0 or width <= 0:
                return None
            # Skia returns RGBA; keep RGB for renderer sampling.
            rgb = arr[:, :, :3].astype("uint8", copy=False).tobytes()
            return rgb, width, height, "DeviceRGB"
        except Exception:
            return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            rgb = image.convert("RGB")
            return rgb.tobytes(), rgb.width, rgb.height, "DeviceRGB"
    except Exception:
        return None


def _decode_ccitt_image(
    data: bytes,
    width: int,
    height: int,
    params: dict | None,
    is_mask: bool,
) -> tuple[bytes, int, int, str, int] | None:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    params = params or {}
    columns = int(params.get("Columns", width or 1728) or (width or 1728))
    rows = int(params.get("Rows", height or 0) or (height or 0))
    k_value = int(params.get("K", 0) or 0)
    black_is_1 = bool(params.get("BlackIs1", False))
    compression = 4 if k_value < 0 else (3 if k_value == 0 else 2)
    image_width = max(1, columns)
    image_height = max(1, rows if rows > 0 else height)
    tif = _build_ccitt_tiff(
        data=data,
        width=image_width,
        height=image_height,
        compression=compression,
        black_is_1=black_is_1,
    )
    try:
        with Image.open(io.BytesIO(tif)) as image:
            mono = image.convert("1")
            decoded_bytes = mono.tobytes()
            # Keep CCITT polarity from decoder and only flip row order to align
            # with PS image sample space used by the renderer.
            decoded_bytes = _flip_mono_rows(decoded_bytes, mono.width, mono.height)
            return (
                decoded_bytes,
                mono.width,
                mono.height,
                "DeviceGray" if not is_mask else "DeviceGray",
                1,
            )
    except Exception:
        return None


def _build_ccitt_tiff(
    data: bytes,
    width: int,
    height: int,
    compression: int,
    black_is_1: bool,
) -> bytes:
    # Minimal little-endian TIFF with a single strip.
    ifd_entries: list[tuple[int, int, int, int]] = []

    def add_short(tag: int, value: int) -> None:
        ifd_entries.append((tag, 3, 1, value & 0xFFFF))

    def add_long(tag: int, value: int) -> None:
        ifd_entries.append((tag, 4, 1, value & 0xFFFFFFFF))

    add_long(256, width)   # ImageWidth
    add_long(257, height)  # ImageLength
    add_short(258, 1)      # BitsPerSample
    add_short(259, compression)  # Compression
    add_short(262, 1 if black_is_1 else 0)  # PhotometricInterpretation
    add_long(273, 8)       # StripOffsets (immediately after header)
    add_short(274, 1)      # Orientation
    add_short(277, 1)      # SamplesPerPixel
    add_long(278, height)  # RowsPerStrip
    add_long(279, len(data))  # StripByteCounts

    ifd = io.BytesIO()
    ifd.write(struct.pack("<H", len(ifd_entries)))
    for tag, typ, count, value in ifd_entries:
        ifd.write(struct.pack("<HHI", tag, typ, count))
        if typ == 3 and count == 1:
            ifd.write(struct.pack("<H", value))
            ifd.write(b"\x00\x00")
        else:
            ifd.write(struct.pack("<I", value))
    ifd.write(struct.pack("<I", 0))  # next IFD

    # Header points to IFD after the strip data.
    ifd_offset = 8 + len(data)
    header = b"II*\x00" + struct.pack("<I", ifd_offset)
    return header + data + ifd.getvalue()


def _flip_mono_rows(data: bytes, width: int, height: int) -> bytes:
    row_bytes = (max(1, width) + 7) // 8
    if row_bytes <= 0 or height <= 1:
        return data
    needed = row_bytes * height
    if len(data) < needed:
        return data
    rows = [data[idx : idx + row_bytes] for idx in range(0, needed, row_bytes)]
    flipped = b"".join(reversed(rows))
    if len(data) == needed:
        return flipped
    return flipped + data[needed:]
    try:
        with Image.open(io.BytesIO(data)) as image:
            if color_space == "DeviceGray":
                converted = image.convert("L")
                return converted.tobytes(), converted.width, converted.height, "DeviceGray"
            if color_space == "DeviceCMYK":
                converted = image.convert("CMYK")
                return converted.tobytes(), converted.width, converted.height, "DeviceCMYK"
            converted = image.convert("RGB")
            return converted.tobytes(), converted.width, converted.height, "DeviceRGB"
    except Exception:
        return None


def _palatino_baseline_shift(font_ref: str, font_size: float) -> float:
    lower_ref = font_ref.lower()
    if not lower_ref.startswith("palatino"):
        return 0.0
    # Palatino Bold Italic already aligns with baseline output and should not
    # receive the generic compatibility shift.
    if "bolditalic" in lower_ref or "bold-italic" in lower_ref:
        return 0.0
    if font_size <= 100.0:
        factor = 0.16
    elif font_size >= 250.0:
        factor = 0.19
    else:
        factor = 0.16 + (font_size - 100.0) * (0.03 / 150.0)
    return font_size * factor


def _page_pixel_size(width_pt: float, height_pt: float, scale: float) -> tuple[int, int]:
    width_px = max(1, int(round(_normalize_page_points(width_pt) * scale)))
    height_px = max(1, int(round(_normalize_page_points(height_pt) * scale)))
    return width_px, height_px


def _normalize_page_points(value: float) -> float:
    rounded = round(value)
    if abs(value - rounded) < 1e-6:
        return float(rounded)
    return float(int(value))


def _paint_to_rgba(paint: Paint) -> tuple[int, int, int, int] | None:
    if paint is None:
        return None
    kind = paint.kind
    value = paint.value
    if kind == "DeviceRGB" and isinstance(value, tuple):
        r, g, b = value
        return (_to_byte(r), _to_byte(g), _to_byte(b), 255)
    if kind == "DeviceGray":
        gray = value[0] if isinstance(value, tuple) else value
        g = _to_byte(gray)
        return (g, g, g, 255)
    if kind == "DeviceCMYK" and isinstance(value, tuple):
        c, m, y, k = value
        r = 1.0 - min(1.0, c + k)
        g = 1.0 - min(1.0, m + k)
        b = 1.0 - min(1.0, y + k)
        return (_to_byte(r), _to_byte(g), _to_byte(b), 255)
    return (0, 0, 0, 255)


def _to_byte(value: float) -> int:
    if value > 1.0:
        value = value / 255.0
    return max(0, min(255, int(value * 255)))


def _row_bytes(width: int, bits_per_component: int, components: int) -> int:
    row_bits = max(0, width) * max(1, bits_per_component) * max(1, components)
    return (row_bits + 7) // 8


def _sample_mask_bit(data: bytes, width: int, x: int, y: int) -> bool:
    row = _row_bytes(width, 1, 1)
    index = y * row + (x // 8)
    if index < 0 or index >= len(data):
        return False
    shift = 7 - (x % 8)
    return ((data[index] >> shift) & 1) == 1


def _sample_image_rgba(
    data: bytes,
    width: int,
    height: int,
    color_space: str,
    bits_per_component: int,
    decode: tuple[float, ...] | None,
    x: int,
    y: int,
) -> tuple[int, int, int, int] | None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return None
    if color_space == "DeviceGray":
        if bits_per_component == 1:
            bit = _sample_mask_bit(data, width, x, y)
            gray = _decoded_gray(1.0 if bit else 0.0, decode)
            return (gray, gray, gray, 255)
        if bits_per_component == 8:
            row = _row_bytes(width, bits_per_component, 1)
            index = y * row + x
            if index < 0 or index >= len(data):
                return None
            gray = _decoded_gray(data[index] / 255.0, decode)
            return (gray, gray, gray, 255)
        return None
    if color_space == "DeviceRGB" and bits_per_component == 8:
        row = _row_bytes(width, bits_per_component, 3)
        index = y * row + x * 3
        if index < 0 or index + 2 >= len(data):
            return None
        values = [data[index] / 255.0, data[index + 1] / 255.0, data[index + 2] / 255.0]
        values = _apply_decode(values, decode, 3)
        return (_to_byte(values[0]), _to_byte(values[1]), _to_byte(values[2]), 255)
    if color_space == "DeviceCMYK" and bits_per_component == 8:
        row = _row_bytes(width, bits_per_component, 4)
        index = y * row + x * 4
        if index < 0 or index + 3 >= len(data):
            return None
        values = [data[index] / 255.0, data[index + 1] / 255.0, data[index + 2] / 255.0, data[index + 3] / 255.0]
        c, m, yk, k = _apply_decode(values, decode, 4)
        r = _to_byte(1.0 - min(1.0, c + k))
        g = _to_byte(1.0 - min(1.0, m + k))
        b = _to_byte(1.0 - min(1.0, yk + k))
        return (r, g, b, 255)
    return None


def _sample_mask_coverage(
    inv_matrix: tuple[float, float, float, float, float, float],
    px: int,
    py: int,
    scale: float,
    surface_height: int,
    samples: int,
    data: bytes,
    width: int,
    height: int,
    invert_mask: bool,
    x_bias: float = 0.0,
) -> tuple[float, int]:
    painted = 0
    total = 0
    for sy_index in range(samples):
        for sx_index in range(samples):
            user_x = (px + x_bias + (sx_index + 0.5) / samples) / scale
            user_y = (surface_height - (py + (sy_index + 0.5) / samples)) / scale
            coords = _sample_source_coords(inv_matrix, user_x, user_y, width, height)
            if coords is None:
                continue
            sx, sy = coords
            bit = _sample_mask_bit(data, width, sx, sy)
            paint_bit = (not bit) if invert_mask else bit
            total += 1
            if paint_bit:
                painted += 1
    if total == 0:
        return 0.0, 0
    return painted / total, total


def _sample_image_color_average(
    inv_matrix: tuple[float, float, float, float, float, float],
    px: int,
    py: int,
    scale: float,
    surface_height: int,
    samples: int,
    data: bytes,
    width: int,
    height: int,
    color_space: str,
    bits_per_component: int,
    decode: tuple[float, ...] | None,
    x_bias: float = 0.0,
) -> tuple[int, int, int, int] | None:
    acc_r = 0
    acc_g = 0
    acc_b = 0
    total = 0
    for sy_index in range(samples):
        for sx_index in range(samples):
            user_x = (px + x_bias + (sx_index + 0.5) / samples) / scale
            user_y = (surface_height - (py + (sy_index + 0.5) / samples)) / scale
            coords = _sample_source_coords(inv_matrix, user_x, user_y, width, height)
            if coords is None:
                continue
            sx, sy = coords
            rgba = _sample_image_rgba(
                data,
                width,
                height,
                color_space,
                bits_per_component,
                decode,
                sx,
                sy,
            )
            if rgba is None:
                continue
            acc_r += rgba[0]
            acc_g += rgba[1]
            acc_b += rgba[2]
            total += 1
    if total == 0:
        return None
    coverage = total / float(samples * samples)
    alpha = int(round(255.0 * coverage))
    return (
        int(round(acc_r / total)),
        int(round(acc_g / total)),
        int(round(acc_b / total)),
        max(0, min(255, alpha)),
    )


def _sample_source_coords(
    inv_matrix: tuple[float, float, float, float, float, float],
    user_x: float,
    user_y: float,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    u, v = _apply_matrix(inv_matrix, user_x, user_y)
    if u < 0.0 or v < 0.0 or u >= 1.0 or v >= 1.0:
        return None
    sx = min(width - 1, max(0, int(u * (width - 1) + 0.5)))
    sy = min(height - 1, max(0, int((1.0 - v) * (height - 1) + 0.5)))
    return sx, sy


def _decoded_gray(value: float, decode: tuple[float, ...] | None) -> int:
    if decode is None or len(decode) < 2:
        return _to_byte(value)
    lo = float(decode[0])
    hi = float(decode[1])
    return _to_byte(lo + value * (hi - lo))


def _apply_decode(values: list[float], decode: tuple[float, ...] | None, components: int) -> list[float]:
    if decode is None or len(decode) < components * 2:
        return values
    result: list[float] = []
    for index, value in enumerate(values):
        lo = float(decode[index * 2])
        hi = float(decode[index * 2 + 1])
        result.append(lo + value * (hi - lo))
    return result


def _flatten_path(
    segments: Iterable[PathSegment],
    scale: float,
    curve_steps: int = 36,
) -> list[list[Point]]:
    subpaths: list[list[Point]] = []
    current: list[Point] = []
    start: Point | None = None
    current_point: Point | None = None
    items = list(segments)
    total = len(items)
    for idx, segment in enumerate(items):
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
            steps = _curve_steps(p0, p1, p2, p3, scale, curve_steps)
            for step in range(1, steps + 1):
                t = step / steps
                x = (
                    (1 - t) ** 3 * p0.x
                    + 3 * (1 - t) ** 2 * t * p1.x
                    + 3 * (1 - t) * t ** 2 * p2.x
                    + t ** 3 * p3.x
                )
                y = (
                    (1 - t) ** 3 * p0.y
                    + 3 * (1 - t) ** 2 * t * p1.y
                    + 3 * (1 - t) * t ** 2 * p2.y
                    + t ** 3 * p3.y
                )
                current.append(Point(x, y))
            current_point = p3
        elif segment.kind == "close":
            if start is not None and current:
                current.append(start)
            if current:
                subpaths.append(current)
            if idx + 1 < total and start is not None:
                # Keep the current point at the subpath start so a following lineto
                # connects correctly after closepath.
                current = [start]
                current_point = start
                start = start
            else:
                current = []
                start = None
                current_point = None
    if current:
        subpaths.append(current)
    return subpaths


def _curve_steps(
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


def _ensure_closed(points: list[Point]) -> list[Point]:
    if not points:
        return points
    if points[0] == points[-1]:
        return points
    return points + [points[0]]


def _axis_aligned_rect(segments: Iterable[PathSegment]) -> tuple[float, float, float, float] | None:
    points: list[Point] = []
    start: Point | None = None
    current: Point | None = None
    for segment in segments:
        if segment.kind == "move":
            if points:
                return None
            start = segment.points[0]
            current = start
            points.append(start)
        elif segment.kind == "line":
            if current is None:
                return None
            current = segment.points[0]
            points.append(current)
        elif segment.kind == "close":
            if start is None:
                return None
            points.append(start)
        else:
            return None
    if len(points) < 4:
        return None
    if points[0] == points[-1]:
        points = points[:-1]
    if len(points) != 4:
        return None
    xs = {round(pt.x, 6) for pt in points}
    ys = {round(pt.y, 6) for pt in points}
    if len(xs) != 2 or len(ys) != 2:
        return None
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    # Verify axis-aligned edges.
    for idx in range(4):
        a = points[idx]
        b = points[(idx + 1) % 4]
        if not (abs(a.x - b.x) < 1e-6 or abs(a.y - b.y) < 1e-6):
            return None
    return (x_min, y_min, x_max, y_max)


def _to_pixels(points: list[Point], scale: float, height_px: int) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for point in points:
        x = point.x * scale
        y = (height_px - 1) - point.y * scale
        result.append((x, y))
    return result


def _iter_segments(points: list[tuple[float, float]]) -> Iterable[tuple[tuple[float, float], tuple[float, float]]]:
    if len(points) < 2:
        return
    for idx in range(len(points) - 1):
        yield points[idx], points[idx + 1]


def _draw_line(
    surface: RasterSurface,
    start: tuple[float, float],
    end: tuple[float, float],
    width: int,
    color: tuple[int, int, int, int],
) -> None:
    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    steps = int(max(abs(dx), abs(dy))) + 1
    for step in range(steps + 1):
        t = step / steps if steps else 0.0
        x = x0 + dx * t
        y = y0 + dy * t
        _draw_square(surface, int(round(x)), int(round(y)), width, color)


def _draw_stroked_segment(
    surface: RasterSurface,
    start: tuple[float, float],
    end: tuple[float, float],
    width: int,
    color: tuple[int, int, int, int],
) -> None:
    if width <= 6:
        _draw_line(surface, start, end, width, color)
        return
    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        _draw_square(surface, int(round(x0)), int(round(y0)), width, color)
        return
    half = width / 2.0
    ux = dx / length
    uy = dy / length
    px = -uy * half
    py = ux * half
    polygon = [
        (x0 + px, y0 + py),
        (x0 - px, y0 - py),
        (x1 - px, y1 - py),
        (x1 + px, y1 + py),
    ]
    _fill_polygon_pixels(surface, polygon, color)


def _normalize_dash_pattern(pattern: list[float]) -> list[float]:
    cleaned = [abs(value) for value in pattern if abs(value) > 1e-6]
    if not cleaned:
        return []
    if len(cleaned) % 2 == 1:
        cleaned = cleaned * 2
    return cleaned


def _init_dash_state(pattern: list[float], phase: float) -> tuple[list[float], int, float]:
    normalized = _normalize_dash_pattern(pattern)
    if not normalized:
        return [], 0, 0.0
    total = sum(normalized)
    if total <= 1e-6:
        return [], 0, 0.0
    phase = phase % total
    index = 0
    while phase > normalized[index]:
        phase -= normalized[index]
        index = (index + 1) % len(normalized)
    remaining = normalized[index] - phase
    return normalized, index, remaining


def _draw_dashed_polyline(
    surface: RasterSurface,
    points: list[tuple[float, float]],
    pattern: list[float],
    phase: float,
    width: int,
    color: tuple[int, int, int, int],
) -> None:
    if width <= 1:
        # For thin strokes, fall back to solid segments.
        for start, end in _iter_segments(points):
            _draw_stroked_segment(surface, start, end, width, color)
        return
    normalized, index, remaining = _init_dash_state(pattern, phase)
    if not normalized:
        for start, end in _iter_segments(points):
            _draw_stroked_segment(surface, start, end, width, color)
        return
    on = index % 2 == 0
    # Avoid overlap while keeping visible dash length.
    cap = max(0.0, width / 2.0 - 0.5)
    for start, end in _iter_segments(points):
        x0, y0 = start
        x1, y1 = end
        dx = x1 - x0
        dy = y1 - y0
        total_len = math.hypot(dx, dy)
        if total_len <= 1e-6:
            continue
        remaining_len = total_len
        traveled = 0.0
        while remaining_len > 1e-6:
            step = min(remaining_len, remaining)
            t0 = traveled / total_len
            t1 = (traveled + step) / total_len
            if on:
                sx = x0 + dx * t0
                sy = y0 + dy * t0
                ex = x0 + dx * t1
                ey = y0 + dy * t1
                _draw_stroked_segment(surface, (sx, sy), (ex, ey), width, color)
            remaining_len -= step
            traveled += step
            remaining -= step
            if remaining <= 1e-6:
                index = (index + 1) % len(normalized)
                remaining = normalized[index]
                on = index % 2 == 0


def _draw_square(
    surface: RasterSurface,
    cx: int,
    cy: int,
    size: int,
    color: tuple[int, int, int, int],
) -> None:
    radius = max(0, size // 2)
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            surface.set_pixel(x, y, color)


def _fill_paths(
    surface: RasterSurface,
    subpaths: list[list[Point]],
    scale: float,
    color: tuple[int, int, int, int],
    even_odd: bool = False,
) -> None:
    intersections_by_row: dict[int, list[tuple[float, int]]] = {}
    for subpath in subpaths:
        if len(subpath) < 3:
            continue
        closed = _ensure_closed(subpath)
        points = _to_pixels(closed, scale, surface.height)
        for (x1, y1), (x2, y2) in _iter_segments(points):
            if y1 == y2:
                continue
            if y1 > y2:
                x1, y1, x2, y2 = x2, y2, x1, y1
                direction = -1
            else:
                direction = 1
            y_start = int(math.floor(y1))
            y_end = int(math.ceil(y2))
            if y_end < 0 or y_start >= surface.height:
                continue
            y_start = max(0, y_start)
            y_end = min(surface.height - 1, y_end)
            for y in range(y_start, y_end + 1):
                scan_y = y + 0.5
                if scan_y < y1 or scan_y >= y2:
                    continue
                t = (scan_y - y1) / (y2 - y1)
                x = x1 + t * (x2 - x1)
                intersections_by_row.setdefault(y, []).append((x, direction))
    if not intersections_by_row:
        return
    for y, intersections in intersections_by_row.items():
        intersections.sort(key=lambda item: item[0])
        if even_odd:
            for idx in range(0, len(intersections) - 1, 2):
                x_start = intersections[idx][0]
                x_end = intersections[idx + 1][0]
                fill_start = int(math.ceil(x_start))
                fill_end = int(math.floor(x_end))
                _fill_span(surface, y, fill_start, fill_end, color)
        else:
            winding = 0
            start_x: float | None = None
            for x, direction in intersections:
                prev_winding = winding
                winding += direction
                if prev_winding == 0 and winding != 0:
                    start_x = x
                elif prev_winding != 0 and winding == 0 and start_x is not None:
                    fill_start = int(math.ceil(start_x))
                    fill_end = int(math.floor(x))
                    _fill_span(surface, y, fill_start, fill_end, color)
                    start_x = None


def _fill_rect(
    surface: RasterSurface,
    rect: tuple[float, float, float, float],
    scale: float,
    color: tuple[int, int, int, int],
) -> None:
    x0, y0, x1, y1 = rect
    min_x = min(x0, x1)
    max_x = max(x0, x1)
    min_y = min(y0, y1)
    max_y = max(y0, y1)
    corners = _to_pixels([Point(min_x, min_y), Point(max_x, max_y)], scale, surface.height)
    xs = [corners[0][0], corners[1][0]]
    ys = [corners[0][1], corners[1][1]]
    x_start = int(math.floor(min(xs)))
    x_end = int(math.ceil(max(xs)))
    y_start = int(math.floor(min(ys)))
    y_end = int(math.ceil(max(ys)))
    for y in range(y_start, y_end + 1):
        _fill_span(surface, y, x_start, x_end, color)


def _fill_polygon_pixels(
    surface: RasterSurface,
    points: list[tuple[float, float]],
    color: tuple[int, int, int, int],
) -> None:
    if len(points) < 3:
        return
    closed = points + [points[0]] if points[0] != points[-1] else points
    edges = list(_iter_segments(closed))
    xs = []
    ys = []
    for x1, y1, x2, y2 in [(a[0], a[1], b[0], b[1]) for a, b in edges]:
        xs.extend([x1, x2])
        ys.extend([y1, y2])
    min_y = int(max(0, math.floor(min(ys))))
    max_y = int(min(surface.height - 1, math.ceil(max(ys))))
    for y in range(min_y, max_y + 1):
        scan_y = y + 0.5
        intersections: list[tuple[float, int]] = []
        for (x1, y1), (x2, y2) in edges:
            if y1 == y2:
                continue
            if scan_y < min(y1, y2) or scan_y >= max(y1, y2):
                continue
            t = (scan_y - y1) / (y2 - y1)
            x = x1 + t * (x2 - x1)
            direction = 1 if y2 > y1 else -1
            intersections.append((x, direction))
        intersections.sort(key=lambda item: item[0])
        winding = 0
        start_x: float | None = None
        for x, direction in intersections:
            prev_winding = winding
            winding += direction
            if prev_winding == 0 and winding != 0:
                start_x = x
            elif prev_winding != 0 and winding == 0 and start_x is not None:
                fill_start = int(max(0, math.ceil(start_x)))
                fill_end = int(min(surface.width - 1, math.floor(x)))
                _fill_span(surface, y, fill_start, fill_end, color)
                start_x = None


def _fill_span(
    surface: RasterSurface,
    y: int,
    x_start: int,
    x_end: int,
    color: tuple[int, int, int, int],
) -> None:
    if y < 0 or y >= surface.height:
        return
    if x_end < x_start:
        return
    x0 = max(0, x_start)
    x1 = min(surface.width - 1, x_end)
    if x1 < x0:
        return
    if surface.clip_mask is None:
        row = y * surface.width * 4
        start = row + x0 * 4
        end = row + (x1 + 1) * 4
        pixel = bytes(color)
        count = x1 - x0 + 1
        surface.pixels[start:end] = pixel * count
        return
    for px in range(x0, x1 + 1):
        surface.set_pixel(px, y, color)


def _analyze_page_for_supersample(page: RenderPage, scale: float) -> tuple[bool, float | None]:
    has_curve = False
    min_width: float | None = None
    for command in page.commands:
        if isinstance(command, PathCommand) and command.stroke is not None:
            width = command.stroke.line_width * scale
            min_width = width if min_width is None else min(min_width, width)
        if isinstance(command, PathCommand):
            for segment in command.path.segments:
                if segment.kind == "curve":
                    has_curve = True
                    break
    return has_curve, min_width


def _choose_supersample(has_curve: bool, min_stroke_px: float | None) -> int:
    # Supersample only when curves are present and strokes are thin.
    if not has_curve:
        return 1
    if min_stroke_px is None:
        return 1
    if min_stroke_px < 2.0:
        return 3
    if min_stroke_px < 6.0:
        return 2
    return 1


def _fill_paths_pattern(
    surface: RasterSurface,
    subpaths: list[list[Point]],
    scale: float,
    sampler,
    even_odd: bool = False,
) -> None:
    segments: list[tuple[float, float, float, float]] = []
    for subpath in subpaths:
        if len(subpath) < 3:
            continue
        closed = _ensure_closed(subpath)
        points = _to_pixels(closed, scale, surface.height)
        for (x1, y1), (x2, y2) in _iter_segments(points):
            segments.append((x1, y1, x2, y2))
    if not segments:
        return
    xs = []
    ys = []
    for x1, y1, x2, y2 in segments:
        xs.extend([x1, x2])
        ys.extend([y1, y2])
    min_y = int(max(0, math.floor(min(ys))))
    max_y = int(min(surface.height - 1, math.ceil(max(ys))))
    for y in range(min_y, max_y + 1):
        scan_y = y + 0.5
        intersections: list[tuple[float, int]] = []
        for x1, y1, x2, y2 in segments:
            if y1 == y2:
                continue
            if scan_y < min(y1, y2) or scan_y >= max(y1, y2):
                continue
            t = (scan_y - y1) / (y2 - y1)
            x = x1 + t * (x2 - x1)
            direction = 1 if y2 > y1 else -1
            intersections.append((x, direction))
        intersections.sort(key=lambda item: item[0])
        if even_odd:
            for idx in range(0, len(intersections) - 1, 2):
                x_start = intersections[idx][0]
                x_end = intersections[idx + 1][0]
                fill_start = int(math.ceil(x_start))
                fill_end = int(math.floor(x_end))
                for px in range(fill_start, fill_end + 1):
                    color = sampler(px, y)
                    if color is None:
                        continue
                    surface.set_pixel(px, y, color)
        else:
            winding = 0
            start_x: float | None = None
            for x, direction in intersections:
                prev_winding = winding
                winding += direction
                if prev_winding == 0 and winding != 0:
                    start_x = x
                elif prev_winding != 0 and winding == 0 and start_x is not None:
                    fill_start = int(math.ceil(start_x))
                    fill_end = int(math.floor(x))
                    for px in range(fill_start, fill_end + 1):
                        color = sampler(px, y)
                        if color is None:
                            continue
                        surface.set_pixel(px, y, color)
                    start_x = None


def _build_clip_mask(
    segments: Iterable[PathSegment],
    scale: float,
    width_px: int,
    height_px: int,
    even_odd: bool,
) -> bytearray:
    subpaths = _flatten_path(segments, scale)
    edges: list[tuple[float, float, float, float]] = []
    for subpath in subpaths:
        if len(subpath) < 3:
            continue
        closed = _ensure_closed(subpath)
        points = _to_pixels(closed, scale, height_px)
        for (x1, y1), (x2, y2) in _iter_segments(points):
            edges.append((x1, y1, x2, y2))
    mask = bytearray(width_px * height_px)
    if not edges:
        return mask
    xs = []
    ys = []
    for x1, y1, x2, y2 in edges:
        xs.extend([x1, x2])
        ys.extend([y1, y2])
    min_y = int(max(0, math.floor(min(ys))))
    max_y = int(min(height_px - 1, math.ceil(max(ys))))
    for y in range(min_y, max_y + 1):
        scan_y = y + 0.5
        intersections: list[tuple[float, int]] = []
        for x1, y1, x2, y2 in edges:
            if y1 == y2:
                continue
            if scan_y < min(y1, y2) or scan_y >= max(y1, y2):
                continue
            t = (scan_y - y1) / (y2 - y1)
            x = x1 + t * (x2 - x1)
            direction = 1 if y2 > y1 else -1
            intersections.append((x, direction))
        intersections.sort(key=lambda item: item[0])
        if even_odd:
            for idx in range(0, len(intersections) - 1, 2):
                x_start = intersections[idx][0]
                x_end = intersections[idx + 1][0]
                fill_start = int(max(0, math.ceil(x_start)))
                fill_end = int(min(width_px - 1, math.floor(x_end)))
                row = y * width_px
                for px in range(fill_start, fill_end + 1):
                    mask[row + px] = 1
        else:
            winding = 0
            start_x: float | None = None
            for x, direction in intersections:
                prev_winding = winding
                winding += direction
                if prev_winding == 0 and winding != 0:
                    start_x = x
                elif prev_winding != 0 and winding == 0 and start_x is not None:
                    fill_start = int(max(0, math.ceil(start_x)))
                    fill_end = int(min(width_px - 1, math.floor(x)))
                    row = y * width_px
                    for px in range(fill_start, fill_end + 1):
                        mask[row + px] = 1
                    start_x = None
    return mask


def _intersect_masks(left: bytearray, right: bytearray) -> bytearray:
    if len(left) != len(right):
        raise ValueError("clip mask size mismatch")
    merged = bytearray(len(left))
    for idx in range(len(left)):
        merged[idx] = 1 if left[idx] and right[idx] else 0
    return merged


def _pattern_sampler(
    pattern: TilingPattern,
    resources,
    paint: PatternPaint,
    scale: float,
    height_px: int,
):
    base_color = _pattern_base_color(resources, paint)
    pattern_scale = _matrix_scale(pattern.matrix)
    tile_scale = scale * pattern_scale
    tile = _render_pattern_tile(pattern, resources, tile_scale, base_color)
    if tile is None:
        return lambda _x, _y: None
    tile_surface, bbox, inv_matrix, x_step, y_step, tile_scale = tile
    x_min, y_min, x_max, y_max = bbox
    width = max(1e-6, x_max - x_min)
    height = max(1e-6, y_max - y_min)
    step_x = x_step if abs(x_step) > 1e-6 else width
    step_y = y_step if abs(y_step) > 1e-6 else height
    tile_w = tile_surface.width
    tile_h = tile_surface.height

    def sample(px: int, py: int):
        user_x = (px + 0.5) / scale
        user_y = (height_px - 1 - py + 0.5) / scale
        if inv_matrix is not None:
            user_x, user_y = _apply_matrix(inv_matrix, user_x, user_y)
        cell_x = (user_x - x_min) % step_x + x_min
        cell_y = (user_y - y_min) % step_y + y_min
        if cell_x < x_min or cell_y < y_min or cell_x >= x_max or cell_y >= y_max:
            return None
        local_x = cell_x - x_min
        local_y = cell_y - y_min
        tx = int(local_x * tile_scale)
        ty = int((tile_h - 1) - local_y * tile_scale)
        color = tile_surface.get_pixel(tx, ty)
        if color[3] == 0:
            return None
        return color

    return sample


def _pattern_base_color(resources, paint: PatternPaint) -> tuple[int, int, int, int]:
    if paint.base_space_id is None or paint.base_components is None:
        return (0, 0, 0, 255)
    space = resources.color_spaces.get(paint.base_space_id)
    if isinstance(space, DeviceColorSpace):
        if space.name == "DeviceGray":
            return _paint_to_rgba(Paint("DeviceGray", paint.base_components[0])) or (0, 0, 0, 255)
        if space.name == "DeviceRGB":
            return _paint_to_rgba(Paint("DeviceRGB", paint.base_components)) or (0, 0, 0, 255)
        if space.name == "DeviceCMYK":
            return _paint_to_rgba(Paint("DeviceCMYK", paint.base_components)) or (0, 0, 0, 255)
    return (0, 0, 0, 255)


def _render_pattern_tile(pattern: TilingPattern, resources, scale: float, base_color):
    x_min, y_min, x_max, y_max = pattern.bbox
    width = max(1.0, x_max - x_min)
    height = max(1.0, y_max - y_min)
    tile_w = max(1, int(round(width * scale)))
    tile_h = max(1, int(round(height * scale)))
    surface = RasterSurface.create(tile_w, tile_h, (255, 255, 255, 0))

    # Translate commands if bbox doesn't start at origin.
    translated = []
    if abs(x_min) > 1e-6 or abs(y_min) > 1e-6:
        for command in pattern.commands:
            translated.append(_translate_command(command, -x_min, -y_min))
    else:
        translated = pattern.commands

    for command in translated:
        if isinstance(command, PathCommand):
            _draw_pattern_path(surface, command, scale, resources, base_color)
        elif isinstance(command, TextCommand):
            fill = command.fill
            _draw_pattern_text(surface, command, scale, fill, base_color)
        elif isinstance(command, ImageCommand):
            # Images in patterns not supported yet.
            continue
    inv_matrix = _invert_matrix(pattern.matrix)
    return surface, pattern.bbox, inv_matrix, pattern.x_step, pattern.y_step, scale


def _draw_pattern_path(
    surface: RasterSurface,
    command: PathCommand,
    scale: float,
    resources,
    base_color,
) -> None:
    subpaths = _flatten_path(command.path.segments, scale)
    fill = command.fill
    fill_color = None
    if fill is not None and fill.kind == "PatternBase":
        fill_color = base_color
    elif fill is not None:
        fill_color = _paint_to_rgba(fill)
    if fill_color is not None:
        _fill_paths(surface, subpaths, scale, fill_color, even_odd=command.fill_rule == "evenodd")
    if command.stroke is not None:
        stroke_paint = command.stroke_paint or command.fill
        if stroke_paint is not None and getattr(stroke_paint, "kind", None) == "PatternBase":
            stroke_color = base_color
        elif stroke_paint is not None:
            stroke_color = _paint_to_rgba(stroke_paint)
        else:
            stroke_color = None
        stroke_color = stroke_color or fill_color or (0, 0, 0, 255)
        stroke_width = max(1, int(round(command.stroke.line_width * scale)))
        for subpath in subpaths:
            points = _to_pixels(subpath, scale, surface.height)
            for start, end in _iter_segments(points):
                _draw_line(surface, start, end, stroke_width, stroke_color)


def _draw_pattern_text(
    surface: RasterSurface,
    command: TextCommand,
    scale: float,
    fill: Paint | None,
    base_color: tuple[int, int, int, int],
) -> None:
    if fill is not None and fill.kind == "PatternBase":
        color = base_color
    else:
        color = _paint_to_rgba(fill) or (0, 0, 0, 255)
    origin_x, origin_y = _matrix_origin(command.matrix)
    font_size = command.font_size
    advance = font_size * 0.6
    for index, char in enumerate(command.text):
        if char == " ":
            continue
        x = origin_x + index * advance
        y = origin_y
        width = font_size * 0.5
        height = font_size
        _draw_rect(surface, x, y, width, height, scale, color)


def _translate_command(command, dx: float, dy: float):
    if isinstance(command, PathCommand):
        segments = []
        for segment in command.path.segments:
            points = [Point(p.x + dx, p.y + dy) for p in segment.points]
            segments.append(PathSegment(segment.kind, points))
        return PathCommand(
            Path(segments),
            command.stroke,
            command.fill,
            command.fill_rule,
            command.stroke_paint,
            command.overprint,
            command.fill_opacity,
            command.stroke_opacity,
        )
    if isinstance(command, TextCommand):
        m = command.matrix
        matrix = Matrix(m.a, m.b, m.c, m.d, m.e + dx, m.f + dy)
        return TextCommand(
            command.text,
            command.font_ref,
            command.font_size,
            matrix,
            command.fill,
            command.fill_opacity,
        )
    if isinstance(command, ImageCommand):
        m = command.matrix
        matrix = Matrix(m.a, m.b, m.c, m.d, m.e + dx, m.f + dy)
        return ImageCommand(
            command.image_id,
            command.width,
            command.height,
            matrix,
            command.mask,
            command.mask_paint,
            command.opacity,
        )
    return command


def _draw_rect(
    surface: RasterSurface,
    x: float,
    y: float,
    width: float,
    height: float,
    scale: float,
    color: tuple[int, int, int, int],
) -> None:
    x0 = int(round(x * scale))
    y0 = int(round((surface.height - 1) - y * scale - height * scale))
    x1 = int(round(x * scale + width * scale))
    y1 = int(round((surface.height - 1) - y * scale))
    for py in range(min(y0, y1), max(y0, y1) + 1):
        for px in range(min(x0, x1), max(x0, x1) + 1):
            surface.set_pixel(px, py, color)


def _fill_rect_pattern(
    surface: RasterSurface,
    x: float,
    y: float,
    width: float,
    height: float,
    scale: float,
    sampler,
) -> None:
    x0 = int(round(x * scale))
    y0 = int(round((surface.height - 1) - y * scale - height * scale))
    x1 = int(round(x * scale + width * scale))
    y1 = int(round((surface.height - 1) - y * scale))
    for py in range(min(y0, y1), max(y0, y1) + 1):
        for px in range(min(x0, x1), max(x0, x1) + 1):
            color = sampler(px, py)
            if color is None:
                continue
            surface.set_pixel(px, py, color)


def _contours_to_path(
    contours: list[list[GlyphPoint]],
    size_scale: float,
    a: float,
    b: float,
    c: float,
    d: float,
    e: float,
    f: float,
) -> Path:
    trace_enabled = os.getenv("PS_TEXT_TRACE") == "1"
    trace_slow_ms = 0.0
    trace_max_ms = 0.0
    trace_max_iter = 0
    simplify_px = 0.0
    segment_cap = 0
    if trace_enabled:
        try:
            trace_slow_ms = float(os.getenv("PS_TEXT_TRACE_SLOW_MS", "0") or 0.0)
        except ValueError:
            trace_slow_ms = 0.0
        try:
            trace_max_ms = float(os.getenv("PS_TEXT_TRACE_MAX_MS", "0") or 0.0)
        except ValueError:
            trace_max_ms = 0.0
        try:
            trace_max_iter = int(os.getenv("PS_TEXT_TRACE_MAX_ITER", "0") or 0)
        except ValueError:
            trace_max_iter = 0
    try:
        simplify_px = float(os.getenv("PS_TEXT_SIMPLIFY_PX", "0.25") or 0.0)
    except ValueError:
        simplify_px = 0.25
    try:
        segment_cap = int(os.getenv("PS_TEXT_SEGMENT_CAP", "2000") or 0)
    except ValueError:
        segment_cap = 2000
    start_time = time.perf_counter() if (trace_enabled and trace_slow_ms) else 0.0
    hard_deadline = (
        time.perf_counter() + (trace_max_ms / 1000.0) if (trace_enabled and trace_max_ms > 0) else None
    )
    segments: list[PathSegment] = []
    for contour in contours:
        if not contour:
            continue
        if simplify_px > 0:
            simplify_units = simplify_px / max(size_scale, 1e-6)
            contour = _simplify_contour(contour, simplify_units)
        expanded: list[GlyphPoint] = []
        count = len(contour)
        for idx, pt in enumerate(contour):
            expanded.append(pt)
            nxt = contour[(idx + 1) % count]
            if not pt.on_curve and not nxt.on_curve:
                mid = GlyphPoint((pt.x + nxt.x) / 2.0, (pt.y + nxt.y) / 2.0, True)
                expanded.append(mid)
        if not expanded:
            continue
        start_index = 0
        for idx, pt in enumerate(expanded):
            if pt.on_curve:
                start_index = idx
                break
        current = expanded[start_index]
        start_point = _transform_point(current, size_scale, a, b, c, d, e, f)
        segments.append(PathSegment("move", [start_point]))
        idx = (start_index + 1) % len(expanded)
        iter_count = 0
        while idx != start_index:
            iter_count += 1
            if segment_cap and len(segments) >= segment_cap:
                if trace_enabled:
                    print("PS TEXT TRACE segment cap reached in contours_to_path", flush=True)
                break
            if trace_enabled and trace_max_iter and iter_count > trace_max_iter:
                print(
                    "PS TEXT TRACE max iter reached in contours_to_path iter={}".format(iter_count),
                    flush=True,
                )
                break
            if hard_deadline is not None and time.perf_counter() > hard_deadline:
                print("PS TEXT TRACE max time reached in contours_to_path", flush=True)
                break
            pt = expanded[idx]
            if pt.on_curve:
                target = _transform_point(pt, size_scale, a, b, c, d, e, f)
                segments.append(PathSegment("line", [target]))
                current = pt
            else:
                nxt = expanded[(idx + 1) % len(expanded)]
                if not nxt.on_curve:
                    idx = (idx + 1) % len(expanded)
                    continue
                c1, c2, end = _quadratic_to_cubic(current, pt, nxt, size_scale, a, b, c, d, e, f)
                segments.append(PathSegment("curve", [c1, c2, end]))
                current = nxt
                idx = (idx + 1) % len(expanded)
            idx = (idx + 1) % len(expanded)
        segments.append(PathSegment("close", []))
    if trace_enabled and trace_slow_ms:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        if elapsed_ms >= trace_slow_ms:
            print(
                "PS TEXT TRACE slow contours_to_path ms={:.2f} contours={} segments={}".format(
                    elapsed_ms,
                    len(contours),
                    len(segments),
                ),
                flush=True,
            )
    return Path(segments)


def _glyph_contours_need_even_odd(contours: list[list[GlyphPoint]]) -> bool:
    """Use even-odd only for ambiguous TrueType contour winding.

    Normal TrueType glyphs use opposite windings for outer/inner contours and
    render correctly with nonzero fill. Some fonts/glyphs carry same-winding
    contours, which can close counters (holes) under nonzero. Detect that case
    and switch to even-odd just for that glyph.
    """
    if len(contours) < 2:
        return False
    signs: list[int] = []
    for contour in contours:
        sign = _expanded_contour_winding_sign(contour)
        if sign != 0:
            signs.append(sign)
    if len(signs) < 2:
        return False
    first = signs[0]
    # If all non-degenerate contours have the same winding, counters are likely
    # to be interpreted as fills under nonzero.
    return all(sign == first for sign in signs[1:])


def _expanded_contour_winding_sign(contour: list[GlyphPoint]) -> int:
    if len(contour) < 3:
        return 0
    expanded: list[GlyphPoint] = []
    count = len(contour)
    for idx, pt in enumerate(contour):
        expanded.append(pt)
        nxt = contour[(idx + 1) % count]
        if not pt.on_curve and not nxt.on_curve:
            expanded.append(GlyphPoint((pt.x + nxt.x) * 0.5, (pt.y + nxt.y) * 0.5, True))
    if len(expanded) < 3:
        return 0
    area2 = 0.0
    for idx in range(len(expanded)):
        p0 = expanded[idx]
        p1 = expanded[(idx + 1) % len(expanded)]
        area2 += (p0.x * p1.y) - (p1.x * p0.y)
    if abs(area2) < 1e-9:
        return 0
    return 1 if area2 > 0 else -1


def _simplify_contour(contour: list[GlyphPoint], epsilon: float) -> list[GlyphPoint]:
    if epsilon <= 0 or len(contour) <= 2:
        return contour
    keep = _rdp_indices(contour, epsilon)
    if len(keep) <= 2:
        return contour
    return [contour[i] for i in keep]


def _rdp_indices(points: list[GlyphPoint], epsilon: float) -> list[int]:
    n = len(points)
    if n <= 2:
        return list(range(n))
    eps_sq = epsilon * epsilon
    keep = {0, n - 1}
    stack: list[tuple[int, int]] = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        max_dist = -1.0
        max_idx = -1
        x1, y1 = points[start].x, points[start].y
        x2, y2 = points[end].x, points[end].y
        dx = x2 - x1
        dy = y2 - y1
        denom = dx * dx + dy * dy
        for i in range(start + 1, end):
            px, py = points[i].x, points[i].y
            if denom == 0:
                dist_sq = (px - x1) ** 2 + (py - y1) ** 2
            else:
                t = ((px - x1) * dx + (py - y1) * dy) / denom
                if t < 0:
                    cx, cy = x1, y1
                elif t > 1:
                    cx, cy = x2, y2
                else:
                    cx, cy = x1 + t * dx, y1 + t * dy
                dist_sq = (px - cx) ** 2 + (py - cy) ** 2
            if dist_sq > max_dist:
                max_dist = dist_sq
                max_idx = i
        if max_dist > eps_sq and max_idx != -1:
            keep.add(max_idx)
            stack.append((start, max_idx))
            stack.append((max_idx, end))
    return sorted(keep)


def _transform_point(
    pt: GlyphPoint,
    size_scale: float,
    a: float,
    b: float,
    c: float,
    d: float,
    e: float,
    f: float,
) -> Point:
    x = pt.x * size_scale
    y = pt.y * size_scale
    return Point(a * x + c * y + e, b * x + d * y + f)


def _quadratic_to_cubic(
    p0: GlyphPoint,
    p1: GlyphPoint,
    p2: GlyphPoint,
    size_scale: float,
    a: float,
    b: float,
    c: float,
    d: float,
    e: float,
    f: float,
) -> tuple[Point, Point, Point]:
    x0 = p0.x * size_scale
    y0 = p0.y * size_scale
    x1 = p1.x * size_scale
    y1 = p1.y * size_scale
    x2 = p2.x * size_scale
    y2 = p2.y * size_scale
    c1x = x0 + (2.0 / 3.0) * (x1 - x0)
    c1y = y0 + (2.0 / 3.0) * (y1 - y0)
    c2x = x2 + (2.0 / 3.0) * (x1 - x2)
    c2y = y2 + (2.0 / 3.0) * (y1 - y2)
    c1 = Point(a * c1x + c * c1y + e, b * c1x + d * c1y + f)
    c2 = Point(a * c2x + c * c2y + e, b * c2x + d * c2y + f)
    end = Point(a * x2 + c * y2 + e, b * x2 + d * y2 + f)
    return c1, c2, end


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


def _apply_matrix(matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def _matrix_scale(matrix: tuple[float, float, float, float, float, float]) -> float:
    a, b, c, d, _e, _f = matrix
    scale_x = math.hypot(a, b)
    scale_y = math.hypot(c, d)
    if scale_x == 0 and scale_y == 0:
        return 1.0
    if scale_x == 0:
        return scale_y
    if scale_y == 0:
        return scale_x
    return (scale_x + scale_y) / 2.0


def _downsample(surface: RasterSurface, factor: int) -> RasterSurface:
    if factor <= 1:
        return surface
    new_width = max(1, surface.width // factor)
    new_height = max(1, surface.height // factor)
    pixels = bytearray(new_width * new_height * 4)
    for y in range(new_height):
        for x in range(new_width):
            sum_r = sum_g = sum_b = 0
            for yy in range(factor):
                for xx in range(factor):
                    src_x = x * factor + xx
                    src_y = y * factor + yy
                    idx = (src_y * surface.width + src_x) * 4
                    sum_r += surface.pixels[idx]
                    sum_g += surface.pixels[idx + 1]
                    sum_b += surface.pixels[idx + 2]
            count = factor * factor
            dst_idx = (y * new_width + x) * 4
            pixels[dst_idx] = int(sum_r / count)
            pixels[dst_idx + 1] = int(sum_g / count)
            pixels[dst_idx + 2] = int(sum_b / count)
            pixels[dst_idx + 3] = 255
    return RasterSurface(new_width, new_height, pixels)
