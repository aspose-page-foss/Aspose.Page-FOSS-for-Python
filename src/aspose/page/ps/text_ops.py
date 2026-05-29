"""PS/EPS text operators."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
import os
import time

from .context import ExecutionContext
from .errors import PsRangeError, PsTypeError, PsUndefinedError
from .encodings import (
    ISO_LATIN1_ENCODING,
    STANDARD_ENCODING,
    SYMBOL_ENCODING,
    ZAPF_DINGBATS_ENCODING,
)
from .fonts import FontResolver, FontResource
from .ttf_outline import TrueTypeFont, load_ttf_font
from .interpreter import PsInterpreter
from .objects import PsArray, PsDict, PsName, PsProcedure, PsString
from .operators import OperatorRegistry
from ..common.render_model import Matrix, RenderModelBuilder, Path
from ..image.raster_renderer import _contours_to_path


_SKIP_TEXT_CODES = {10, 13}


def _is_skip_char(char: str) -> bool:
    return ord(char) in _SKIP_TEXT_CODES




@dataclass(frozen=True)
class _ScaledFont:
    font: FontResource
    size: float


def register_text_operators(
    registry: OperatorRegistry, builder: RenderModelBuilder, font_resolver: FontResolver
) -> None:
    """Register PS/EPS text operators.

    Example:
        >>> registry = OperatorRegistry()
        >>> register_text_operators(registry, RenderModelBuilder(), FontResolver())
        >>> registry.get("show") is not None
        True
    """

    interpreter = PsInterpreter(registry)

    registry.register("show", lambda ctx: _op_show(ctx, builder, interpreter), min_operands=1)
    registry.register("ashow", lambda ctx: _op_ashow(ctx, builder, interpreter), min_operands=3)
    registry.register("widthshow", lambda ctx: _op_widthshow(ctx, builder, interpreter), min_operands=4)
    registry.register("awidthshow", lambda ctx: _op_awidthshow(ctx, builder, interpreter), min_operands=6)
    registry.register("xshow", lambda ctx: _op_xyshow(ctx, builder, interpreter, mode="x"), min_operands=2)
    registry.register("yshow", lambda ctx: _op_xyshow(ctx, builder, interpreter, mode="y"), min_operands=2)
    registry.register("xyshow", lambda ctx: _op_xyshow(ctx, builder, interpreter, mode="xy"), min_operands=2)
    registry.register("kshow", lambda ctx: _op_kshow(ctx, builder, interpreter), min_operands=2)

    registry.register("stringwidth", lambda ctx: _op_stringwidth(ctx), min_operands=1)
    registry.register("charpath", lambda ctx: _op_charpath(ctx, interpreter), min_operands=2)

    registry.register("setfont", lambda ctx: _op_setfont(ctx), min_operands=1)
    registry.register("currentfont", lambda ctx: _op_currentfont(ctx))
    registry.register("findfont", lambda ctx: _op_findfont(ctx, font_resolver), min_operands=1)
    registry.register("definefont", lambda ctx: _op_definefont(ctx, font_resolver), min_operands=2)
    registry.register("scalefont", lambda ctx: _op_scalefont(ctx), min_operands=2)
    registry.register("makefont", lambda ctx: _op_makefont(ctx), min_operands=2)
    registry.register("selectfont", lambda ctx: _op_selectfont(ctx, font_resolver), min_operands=2)
    registry.register("composefont", lambda ctx: _op_composefont(ctx, font_resolver), min_operands=3)
    registry.register("glyphshow", lambda ctx: _op_glyphshow(ctx, builder, interpreter), min_operands=1)

    registry.register("begincmap", _op_begincmap)
    registry.register("endcmap", _op_endcmap)
    registry.register("begincodespacerange", _op_begincodespacerange, min_operands=1)
    registry.register("endcodespacerange", _op_endcodespacerange)
    registry.register("beginbfchar", _op_beginbfchar, min_operands=1)
    registry.register("endbfchar", _op_endbfchar)

    registry.register("settextmatrix", lambda ctx: _op_settextmatrix(ctx), min_operands=6)
    registry.register("settextline", lambda ctx: _op_settextline(ctx), min_operands=6)
    registry.register("setcharwidth", lambda ctx: _op_setcharwidth(ctx), min_operands=2)
    registry.register("setcachedevice", lambda ctx: _op_setcachedevice(ctx), min_operands=6)
    registry.register("setcachedevice2", lambda ctx: _op_setcachedevice2(ctx), min_operands=10)

    if registry.get("moveto") is None:
        registry.register("moveto", lambda ctx: _op_text_moveto(ctx), min_operands=2)
    if registry.get("rmoveto") is None:
        registry.register("rmoveto", lambda ctx: _op_text_rmoveto(ctx), min_operands=2)


def _op_show(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
) -> None:
    text = _pop_text(ctx)
    _emit_text(ctx, builder, interpreter, text)


def _op_ashow(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
) -> None:
    text = _pop_text(ctx)
    dy = _pop_number(ctx)
    dx = _pop_number(ctx)
    for char in text:
        _emit_glyph(ctx, builder, interpreter, char)
        _advance_text(ctx, dx, dy)


def _op_widthshow(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
) -> None:
    text = _pop_text(ctx)
    adjust_char = _pop_text(ctx)
    dy = _pop_number(ctx)
    dx = _pop_number(ctx)
    target = adjust_char[0] if adjust_char else ""
    for char in text:
        _emit_glyph(ctx, builder, interpreter, char)
        if char == target:
            _advance_text(ctx, dx, dy)


def _op_awidthshow(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
) -> None:
    text = _pop_text(ctx)
    ay = _pop_number(ctx)
    ax = _pop_number(ctx)
    adjust_char = _pop_text(ctx)
    cy = _pop_number(ctx)
    cx = _pop_number(ctx)
    target = adjust_char[0] if adjust_char else ""
    for char in text:
        _emit_glyph(ctx, builder, interpreter, char)
        _advance_text(ctx, ax, ay)
        if char == target:
            _advance_text(ctx, cx, cy)


def _op_xyshow(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
    mode: str,
) -> None:
    adjustments = ctx.operand_stack.pop()
    text = _pop_text(ctx)
    if not isinstance(adjustments, PsArray):
        raise PsTypeError("adjustment array expected")
    flat = _numeric_array_values(ctx, interpreter, adjustments)

    count = len(text)
    step = 2 if mode == "xy" else 1
    expected_full = count * step
    expected_between = max(0, (count - 1) * step)
    if len(flat) > expected_full:
        # Real-world PS often carries one or more redundant trailing widths.
        # Keep only the per-glyph adjustments and skip extra entries.
        flat = flat[:expected_full]
    elif len(flat) < expected_between:
        flat = flat + [0.0] * (expected_between - len(flat))
    has_trailing_adjust = len(flat) == expected_full

    index = 0
    for char_index, char in enumerate(text):
        if has_trailing_adjust:
            # x/y/xyshow with full adjustment arrays places each glyph at the
            # current point, then advances strictly by the supplied offsets.
            state = ctx.graphics_state_stack.peek()
            previous_matrix = state.text_matrix
            previous_point = state.current_point
            _emit_glyph(ctx, builder, interpreter, char)
            state = ctx.graphics_state_stack.peek()
            state.text_matrix = previous_matrix
            state.current_point = previous_point
            if mode == "x":
                dx = flat[index]
                dy = 0.0
                index += 1
            elif mode == "y":
                dx = 0.0
                dy = flat[index]
                index += 1
            else:
                dx = flat[index]
                dy = flat[index + 1]
                index += 2
            _advance_text(ctx, dx, dy)
            continue

        _emit_glyph(ctx, builder, interpreter, char)
        if char_index >= count - 1:
            continue
        if mode == "x":
            dx = flat[index]
            dy = 0.0
            index += 1
        elif mode == "y":
            dx = 0.0
            dy = flat[index]
            index += 1
        else:
            dx = flat[index]
            dy = flat[index + 1]
            index += 2
        _advance_text(ctx, dx, dy)



def _numeric_array_values(
    ctx: ExecutionContext,
    interpreter: PsInterpreter,
    values: PsArray,
) -> list[float]:
    if all(isinstance(item, (int, float)) for item in values.items):
        return [float(item) for item in values.items]

    baseline = len(ctx.operand_stack)
    try:
        for item in values.items:
            if isinstance(item, (int, float)):
                ctx.operand_stack.push(item)
            else:
                interpreter.execute_object(item, ctx)
        produced = ctx.operand_stack.to_list()[baseline:]
    finally:
        while len(ctx.operand_stack) > baseline:
            ctx.operand_stack.pop()

    result: list[float] = []
    for item in produced:
        if not isinstance(item, (int, float)):
            raise PsTypeError("number expected")
        result.append(float(item))
    return result


def _op_kshow(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
) -> None:
    _ = ctx.operand_stack.pop()  # procedure ignored
    text = _pop_text(ctx)
    for char in text:
        _emit_glyph(ctx, builder, interpreter, char)


def _op_stringwidth(ctx: ExecutionContext) -> None:
    text = _pop_text(ctx)
    width = _string_width(ctx, text, include_spacing=False)
    ctx.operand_stack.push(width)
    ctx.operand_stack.push(0.0)


def _op_charpath(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    _ = ctx.operand_stack.pop()  # bool for stroke
    text = _pop_text(ctx)
    for char in text:
        _append_charpath(ctx, interpreter, char)


def _op_setfont(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, _ScaledFont):
        ctx.graphics_state_stack.peek().font = value.font
        ctx.graphics_state_stack.peek().font_size = value.size
        return
    if isinstance(value, PsDict):
        ctx.graphics_state_stack.peek().font = _font_resource_from_dict(value, ctx.font_resolver)
        return
    if isinstance(value, FontResource):
        ctx.graphics_state_stack.peek().font = value
        return
    raise PsTypeError("font expected")


def _op_currentfont(ctx: ExecutionContext) -> None:
    font = ctx.graphics_state_stack.peek().font
    if font is None:
        raise PsUndefinedError("no current font")
    ctx.operand_stack.push(_font_resource_to_dict(font))


def _op_definefont(ctx: ExecutionContext, resolver: FontResolver) -> None:
    font_obj = ctx.operand_stack.pop()
    key = ctx.operand_stack.pop()
    if isinstance(key, PsName):
        name = key.value
    elif isinstance(key, str):
        name = key
    else:
        raise PsTypeError("definefont expects name key")
    if isinstance(font_obj, FontResource):
        resource = font_obj
    elif isinstance(font_obj, PsDict):
        resource = _font_resource_from_dict(font_obj, resolver, name_hint=name)
    else:
        raise PsTypeError("definefont expects dictionary")
    base_name = None
    if isinstance(font_obj, PsDict):
        marker = font_obj.items.get("__font_resource__")
        if isinstance(marker, FontResource):
            base_name = marker.name
    resource = _with_font_name(resource, name)
    font_dict = _font_resource_to_dict(resource)
    directory = ctx.systemdict.items.get("FontDirectory")
    if isinstance(directory, PsDict):
        directory.items[name] = font_dict
    # Alias derived fonts (eg re-encoded Type1 fonts) back to their base
    # typeface so raster text can resolve the correct physical font file.
    resolver._aliases[name] = base_name or resource.name
    resolver.register_defined_font(name, resource)
    ctx.operand_stack.push(font_dict)


def _op_findfont(ctx: ExecutionContext, resolver: FontResolver) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsName):
        font_name = value.value
    elif isinstance(value, str):
        font_name = value
    else:
        raise PsTypeError("font name expected")
    directory = ctx.systemdict.items.get("FontDirectory")
    if isinstance(directory, PsDict) and font_name in directory.items:
        existing = directory.items.get(font_name)
        if isinstance(existing, FontResource):
            existing = _font_resource_to_dict(existing)
            directory.items[font_name] = existing
        if isinstance(existing, PsDict):
            ctx.operand_stack.push(existing)
            return
    resource = resolver.resolve(font_name)
    font_dict = _font_resource_to_dict(resource)
    if isinstance(directory, PsDict):
        directory.items[font_name] = font_dict
    ctx.operand_stack.push(font_dict)


def _op_scalefont(ctx: ExecutionContext) -> None:
    size = _pop_number(ctx)
    font = ctx.operand_stack.pop()
    if isinstance(font, PsDict):
        font = _font_resource_from_dict(font, ctx.font_resolver)
    if isinstance(font, FontResource):
        ctx.operand_stack.push(_ScaledFont(font, size))
        return
    raise PsTypeError("font expected")


def _op_makefont(ctx: ExecutionContext) -> None:
    matrix = _pop_matrix(ctx)
    font = ctx.operand_stack.pop()
    if isinstance(font, PsDict):
        font = _font_resource_from_dict(font, ctx.font_resolver)
    if not isinstance(font, FontResource):
        raise PsTypeError("font expected")
    size = hypot(matrix[0], matrix[1]) or 1.0
    ctx.operand_stack.push(_ScaledFont(font, size))


def _op_selectfont(ctx: ExecutionContext, resolver: FontResolver) -> None:
    second = ctx.operand_stack.pop()
    first = ctx.operand_stack.pop()
    if isinstance(second, (int, float)):
        size = float(second)
        font_value = first
    else:
        matrix = _matrix_from_object(second)
        size = hypot(matrix[0], matrix[1]) or 1.0
        font_value = first
    font = _resolve_font_operand(font_value, resolver, ctx)
    ctx.graphics_state_stack.peek().font = font
    ctx.graphics_state_stack.peek().font_size = size


def _op_composefont(ctx: ExecutionContext, resolver: FontResolver) -> None:
    descendant_spec = ctx.operand_stack.pop()
    cmap_value = ctx.operand_stack.pop()
    font_value = ctx.operand_stack.pop()

    if isinstance(font_value, PsName):
        font_name = font_value.value
    elif isinstance(font_value, str):
        font_name = font_value
    else:
        raise PsTypeError("font name expected")

    base_font: FontResource | None = None
    if isinstance(descendant_spec, PsArray) and descendant_spec.items:
        base_font = _resolve_composite_descendant(descendant_spec.items[0], resolver, ctx)
    else:
        base_font = _resolve_composite_descendant(descendant_spec, resolver, ctx)

    if base_font is None:
        base_font = resolver.resolve(font_name)

    code_map = _resolve_cmap_mapping(cmap_value, ctx)
    resource = _compose_font_resource(base_font, font_name, code_map=code_map)
    font_dict = _font_resource_to_dict(resource)
    directory = ctx.systemdict.items.get("FontDirectory")
    if isinstance(directory, PsDict):
        directory.items[font_name] = font_dict
    resolver.register_defined_font(font_name, resource)
    ctx.operand_stack.push(font_dict)


def _op_begincmap(ctx: ExecutionContext) -> None:
    setattr(ctx, "_cmap_map", {})


def _op_endcmap(ctx: ExecutionContext) -> None:
    mapping = getattr(ctx, "_cmap_map", None)
    if isinstance(mapping, dict):
        ctx.dictionary_stack.peek().items["__CodeMap__"] = dict(mapping)


def _op_begincodespacerange(ctx: ExecutionContext) -> None:
    count = int(_pop_number(ctx))
    setattr(ctx, "_cmap_codespace_count", max(0, count))


def _op_endcodespacerange(ctx: ExecutionContext) -> None:
    count = int(getattr(ctx, "_cmap_codespace_count", 0))
    for _ in range(count):
        if len(ctx.operand_stack) < 2:
            break
        ctx.operand_stack.pop()
        ctx.operand_stack.pop()


def _op_beginbfchar(ctx: ExecutionContext) -> None:
    count = int(_pop_number(ctx))
    setattr(ctx, "_cmap_bfchar_count", max(0, count))


def _op_endbfchar(ctx: ExecutionContext) -> None:
    count = int(getattr(ctx, "_cmap_bfchar_count", 0))
    mapping = getattr(ctx, "_cmap_map", None)
    if not isinstance(mapping, dict):
        mapping = {}
        setattr(ctx, "_cmap_map", mapping)
    for _ in range(count):
        if len(ctx.operand_stack) < 2:
            break
        dst = ctx.operand_stack.pop()
        src = ctx.operand_stack.pop()
        src_code = _code_from_hex_object(src)
        dst_code = _code_from_hex_object(dst)
        if src_code is not None and dst_code is not None:
            mapping[src_code] = dst_code


def _op_glyphshow(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsName):
        glyph_name = value.value
    elif isinstance(value, str):
        glyph_name = value
    else:
        raise PsTypeError("glyphshow expects glyph name")
    state = ctx.graphics_state_stack.peek()
    font = state.font
    if font is None:
        raise PsUndefinedError("no current font")
    search_font = font.descendant or font
    code = None
    for k, v in search_font.encoding.items():
        if v == glyph_name:
            code = k
            break
    if code is None:
        char = glyph_name[0] if glyph_name else " "
    else:
        char = chr(code)
    _emit_glyph(ctx, builder, interpreter, char)


def _op_settextmatrix(ctx: ExecutionContext) -> None:
    matrix = _pop_matrix(ctx)
    ctx.graphics_state_stack.peek().text_matrix = matrix
    ctx.graphics_state_stack.peek().text_line_matrix = matrix


def _op_settextline(ctx: ExecutionContext) -> None:
    matrix = _pop_matrix(ctx)
    ctx.graphics_state_stack.peek().text_line_matrix = matrix


def _op_text_moveto(ctx: ExecutionContext) -> None:
    y = _pop_number(ctx)
    x = _pop_number(ctx)
    state = ctx.graphics_state_stack.peek()
    state.text_matrix = (1.0, 0.0, 0.0, 1.0, x, y)
    state.text_line_matrix = state.text_matrix


def _op_text_rmoveto(ctx: ExecutionContext) -> None:
    y = _pop_number(ctx)
    x = _pop_number(ctx)
    _advance_text(ctx, x, y)


def _op_setcharwidth(ctx: ExecutionContext) -> None:
    wy = _pop_number(ctx)
    wx = _pop_number(ctx)
    ctx.graphics_state_stack.peek().type3_char_width = (wx, wy)


def _op_setcachedevice(ctx: ExecutionContext) -> None:
    ury = _pop_number(ctx)
    urx = _pop_number(ctx)
    lly = _pop_number(ctx)
    llx = _pop_number(ctx)
    wy = _pop_number(ctx)
    wx = _pop_number(ctx)
    state = ctx.graphics_state_stack.peek()
    state.type3_char_width = (wx, wy)
    state.type3_cache_bbox = (llx, lly, urx, ury)


def _op_setcachedevice2(ctx: ExecutionContext) -> None:
    _ = _pop_number(ctx)  # vy
    _ = _pop_number(ctx)  # vx
    _ = _pop_number(ctx)  # w1y
    _ = _pop_number(ctx)  # w1x
    ury = _pop_number(ctx)
    urx = _pop_number(ctx)
    lly = _pop_number(ctx)
    llx = _pop_number(ctx)
    wy = _pop_number(ctx)
    wx = _pop_number(ctx)
    state = ctx.graphics_state_stack.peek()
    state.type3_char_width = (wx, wy)
    state.type3_cache_bbox = (llx, lly, urx, ury)


def _emit_text(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
    text: str,
) -> None:
    if not text:
        return
    trace_enabled = os.getenv("PS_TEXT_TRACE") == "1"
    trace_every = 0
    trace_slow_ms = 0.0
    if trace_enabled:
        try:
            trace_every = int(os.getenv("PS_TEXT_TRACE_EVERY", "0") or 0)
        except ValueError:
            trace_every = 0
        try:
            trace_slow_ms = float(os.getenv("PS_TEXT_TRACE_SLOW_MS", "0") or 0.0)
        except ValueError:
            trace_slow_ms = 0.0
    state = ctx.graphics_state_stack.peek()
    font = state.font
    if font is None:
        raise PsUndefinedError("no current font")
    if trace_enabled:
        print(
            "PS TEXT TRACE show font={} type={} len={} size={}".format(
                font.name,
                font.font_type,
                len(text),
                state.font_size,
            ),
            flush=True,
        )
    if font.font_type == "Type0" and font.fdep_vector:
        _emit_type0_text(ctx, builder, interpreter, text)
        return
    if any(_is_skip_char(char) for char in text):
        for char in text:
            _emit_glyph(ctx, builder, interpreter, char)
        return
    if font.font_type == "Type3":
        for char in text:
            if trace_enabled and trace_every and (ord(char) % trace_every == 0):
                print(f"PS TEXT TRACE type3 char={ord(char)}", flush=True)
            _render_type3_glyph(ctx, interpreter, char)
        return
    render_font = font.descendant or font
    font_size = state.font_size or 1.0
    matrix = _multiply_matrix(ctx.graphics_state_stack.peek().ctm, state.text_matrix)
    override = ctx.text_font_overrides.get(render_font.name)
    display_text = _display_text_for_font(render_font, text)
    if override:
        if display_text:
            builder.add_text(display_text, override, font_size, Matrix(*matrix), state.fill_paint)
        _advance_text(ctx, _string_width(ctx, text), 0.0)
        return
    if not _can_use_requested_text_font(ctx, render_font.name):
        _mark_text_fallback(ctx, render_font.name, state.font)
    override = ctx.text_font_overrides.get(render_font.name)
    font_name = override or render_font.name
    if display_text:
        builder.add_text(display_text, font_name, font_size, Matrix(*matrix), state.fill_paint)
    _advance_text(ctx, _string_width(ctx, text), 0.0)


def _emit_glyph(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
    char: str,
) -> None:
    if _is_skip_char(char):
        return
    trace_enabled = os.getenv("PS_TEXT_TRACE") == "1"
    trace_every = 0
    trace_slow_ms = 0.0
    if trace_enabled:
        try:
            trace_every = int(os.getenv("PS_TEXT_TRACE_EVERY", "0") or 0)
        except ValueError:
            trace_every = 0
        try:
            trace_slow_ms = float(os.getenv("PS_TEXT_TRACE_SLOW_MS", "0") or 0.0)
        except ValueError:
            trace_slow_ms = 0.0
    state = ctx.graphics_state_stack.peek()
    font = state.font
    if font is None:
        raise PsUndefinedError("no current font")
    if font.font_type == "Type0" and font.fdep_vector:
        _emit_type0_text(ctx, builder, interpreter, char)
        return
    if font.font_type == "Type3":
        _render_type3_glyph(ctx, interpreter, char)
        return
    render_font = font.descendant or font
    font_size = state.font_size or 1.0
    matrix = _multiply_matrix(ctx.graphics_state_stack.peek().ctm, state.text_matrix)
    override = ctx.text_font_overrides.get(render_font.name)
    display_char = _display_text_for_font(render_font, char)
    if override:
        if display_char:
            builder.add_text(display_char, override, font_size, Matrix(*matrix), state.fill_paint)
        _advance_text(ctx, _string_width(ctx, char), 0.0)
        return
    if not _can_use_requested_text_font(ctx, render_font.name):
        _mark_text_fallback(ctx, render_font.name, state.font)
    override = ctx.text_font_overrides.get(render_font.name)
    font_name = override or render_font.name
    if display_char:
        builder.add_text(display_char, font_name, font_size, Matrix(*matrix), state.fill_paint)
    _advance_text(ctx, _string_width(ctx, char), 0.0)


def _string_width(ctx: ExecutionContext, text: str, include_spacing: bool = True) -> float:
    state = ctx.graphics_state_stack.peek()
    font = state.font
    if font is None:
        raise PsUndefinedError("no current font")
    if font.font_type == "Type0" and font.fdep_vector:
        total = 0.0
        for descendant, run in _iter_type0_runs(font, text):
            total += _string_width_for_font(ctx, descendant, run, include_spacing=include_spacing)
        return total
    width = 0.0
    for char in text:
        width += _glyph_advance(ctx, char, include_spacing=include_spacing)
    return width


def _glyph_advance(ctx: ExecutionContext, char: str, include_spacing: bool = True) -> float:
    state = ctx.graphics_state_stack.peek()
    font = state.font
    if font is None:
        raise PsUndefinedError("no current font")
    return _glyph_advance_for_font(ctx, font, char, include_spacing=include_spacing)


def _string_width_for_font(
    ctx: ExecutionContext,
    font: FontResource,
    text: str,
    include_spacing: bool = True,
) -> float:
    width = 0.0
    for char in text:
        width += _glyph_advance_for_font(ctx, font, char, include_spacing=include_spacing)
    return width


def _glyph_advance_for_font(
    ctx: ExecutionContext,
    font: FontResource,
    char: str,
    include_spacing: bool = True,
) -> float:
    if _is_skip_char(char):
        return 0.0
    state = ctx.graphics_state_stack.peek()
    trace_enabled = os.getenv("PS_TEXT_TRACE") == "1"
    trace_slow_ms = 0.0
    if trace_enabled:
        try:
            trace_slow_ms = float(os.getenv("PS_TEXT_TRACE_SLOW_MS", "0") or 0.0)
        except ValueError:
            trace_slow_ms = 0.0
    if font.descendant is not None:
        font = font.descendant
    if ctx.font_resolver is None:
        raise PsUndefinedError("no font resolver")
    code = ord(char)
    width_units = None
    if font.code_widths is not None:
        width_units = font.code_widths.get(code)
    if width_units is None:
        glyph_name = font.encoding.get(code, ".notdef")
        t0 = time.perf_counter() if trace_slow_ms else 0.0
        width_units = ctx.font_resolver.get_glyph_width(font, glyph_name)
        if trace_slow_ms:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if elapsed_ms >= trace_slow_ms:
                print(
                    "PS TEXT TRACE slow glyph_width font={} glyph={} ms={:.2f}".format(
                        font.name,
                        glyph_name,
                        elapsed_ms,
                    ),
                    flush=True,
                )
    if width_units == 0.0:
        width_units = font.units_per_em * 0.5
    advance = width_units / font.units_per_em * state.font_size
    if include_spacing:
        advance += state.char_spacing
        if char == " ":
            advance += state.word_spacing
    return advance


def _emit_type0_text(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    interpreter: PsInterpreter,
    text: str,
) -> None:
    state = ctx.graphics_state_stack.peek()
    base_font = state.font
    if base_font is None:
        raise PsUndefinedError("no current font")
    for descendant, run in _iter_type0_runs(base_font, text):
        if not run:
            continue
        if descendant.font_type == "Type3":
            previous_font = state.font
            state.font = descendant
            try:
                for char in run:
                    # Type0 descendants frequently use low-byte character codes
                    # (eg 0x01..0x1F) as valid glyph selectors.
                    # Only skip NUL here to avoid dropping legitimate glyphs.
                    if char == "\x00":
                        continue
                    _render_type3_glyph(ctx, interpreter, char, root_font=base_font)
            finally:
                ctx.graphics_state_stack.peek().font = previous_font
            continue
        render_font = descendant.descendant or descendant
        visible = "".join(char for char in run if not _is_skip_char(char))
        display = _display_text_for_font(render_font, visible)
        matrix = _multiply_matrix(state.ctm, state.text_matrix)
        override = ctx.text_font_overrides.get(render_font.name)
        if override is None and not _can_use_requested_text_font(ctx, render_font.name):
            _mark_text_fallback(ctx, render_font.name, descendant)
            override = ctx.text_font_overrides.get(render_font.name)
        font_name = override or render_font.name
        if display:
            builder.add_text(display, font_name, state.font_size or 1.0, Matrix(*matrix), state.fill_paint)
        _advance_text(ctx, _string_width_for_font(ctx, descendant, run), 0.0)


def _iter_type0_runs(font: FontResource, text: str):
    descendants = font.fdep_vector or ([font.descendant] if font.descendant is not None else [])
    if not descendants:
        return
    data = text.encode("latin-1", "ignore")
    current_index = 0
    chunk: list[str] = []
    index = 0

    def _descendant_index(selector: int) -> int:
        mapped = selector
        if font.fmap_encoding and 0 <= selector < len(font.fmap_encoding):
            mapped = int(font.fmap_encoding[selector])
        if 0 <= mapped < len(descendants):
            return mapped
        return 0

    # FMapType 2 is an 8/8 mapping: one byte selects the descendant font,
    # the next byte is the character code in that descendant.
    if font.fmap_type == 2:
        while index < len(data):
            next_index = _descendant_index(data[index])
            index += 1
            if index >= len(data):
                break
            if chunk and next_index != current_index:
                yield descendants[current_index], "".join(chunk)
                chunk = []
            current_index = next_index
            code = data[index]
            if 0 <= code <= 0x10FFFF:
                chunk.append(chr(code))
            else:
                chunk.append("\uFFFD")
            index += 1
        if chunk:
            yield descendants[current_index], "".join(chunk)
        return

    while index < len(data):
        code = data[index]
        if font.esc_char is not None and code == font.esc_char and index + 1 < len(data):
            if chunk:
                yield descendants[current_index], "".join(chunk)
                chunk = []
            current_index = _descendant_index(data[index + 1])
            index += 2
            continue
        mapped_code, consumed = _decode_type0_code(font, data, index)
        if 0 <= mapped_code <= 0x10FFFF:
            chunk.append(chr(mapped_code))
        else:
            chunk.append("\uFFFD")
        index += consumed
    if chunk:
        yield descendants[current_index], "".join(chunk)


def _decode_type0_code(font: FontResource, data: bytes, start: int) -> tuple[int, int]:
    code_map = font.code_map
    if isinstance(code_map, dict) and code_map:
        lengths = sorted(
            {
                max(1, (int(key).bit_length() + 7) // 8)
                for key in code_map.keys()
                if isinstance(key, int) and key >= 0
            },
            reverse=True,
        )
        for length in lengths:
            end = start + length
            if end > len(data):
                continue
            src = int.from_bytes(data[start:end], byteorder="big", signed=False)
            dst = code_map.get(src)
            if isinstance(dst, int):
                return int(dst), length
    return data[start], 1


_GLYPH_NAME_UNICODE = {
    "space": " ",
    "exclam": "!",
    "quotedbl": '"',
    "numbersign": "#",
    "dollar": "$",
    "percent": "%",
    "ampersand": "&",
    "quotesingle": "'",
    "parenleft": "(",
    "parenright": ")",
    "asterisk": "*",
    "plus": "+",
    "comma": ",",
    "hyphen": "-",
    "period": ".",
    "slash": "/",
    "colon": ":",
    "semicolon": ";",
    "less": "<",
    "lessequal": "≤",
    "equal": "=",
    "greater": ">",
    "question": "?",
    "at": "@",
    "bracketleft": "[",
    "backslash": "\\",
    "bracketright": "]",
    "asciicircum": "^",
    "underscore": "_",
    "grave": "`",
    "braceleft": "{",
    "bar": "|",
    "braceright": "}",
    "asciitilde": "~",
    "exclamdown": "¡",
    "cent": "¢",
    "sterling": "£",
    "fraction": "⁄",
    "yen": "¥",
    "florin": "ƒ",
    "section": "§",
    "currency": "¤",
    "quotedblleft": "“",
    "quotedblright": "”",
    "quotesinglbase": "‚",
    "quotedblbase": "„",
    "guillemotleft": "«",
    "guillemotright": "»",
    "guilsinglleft": "‹",
    "guilsinglright": "›",
    "fi": "ﬁ",
    "fl": "ﬂ",
    "endash": "–",
    "emdash": "—",
    "dagger": "†",
    "daggerdbl": "‡",
    "periodcentered": "·",
    "paragraph": "¶",
    "bullet": "•",
    "ellipsis": "…",
    "perthousand": "‰",
    "questiondown": "¿",
    "macron": "¯",
    "breve": "˘",
    "dotaccent": "˙",
    "ring": "˚",
    "hungarumlaut": "˝",
    "ogonek": "˛",
    "caron": "ˇ",
    "ordfeminine": "ª",
    "ordmasculine": "º",
    "dotlessi": "ı",
    "germandbls": "ß",
    # Latin letters frequently used via custom encodings.
    "Agrave": "À",
    "Aacute": "Á",
    "Acircumflex": "Â",
    "Atilde": "Ã",
    "Adieresis": "Ä",
    "Aring": "Å",
    "AE": "Æ",
    "Ccedilla": "Ç",
    "Egrave": "È",
    "Eacute": "É",
    "Ecircumflex": "Ê",
    "Edieresis": "Ë",
    "Igrave": "Ì",
    "Iacute": "Í",
    "Icircumflex": "Î",
    "Idieresis": "Ï",
    "Eth": "Ð",
    "Ntilde": "Ñ",
    "Ograve": "Ò",
    "Oacute": "Ó",
    "Ocircumflex": "Ô",
    "Otilde": "Õ",
    "Odieresis": "Ö",
    "Oslash": "Ø",
    "Ugrave": "Ù",
    "Uacute": "Ú",
    "Ucircumflex": "Û",
    "Udieresis": "Ü",
    "Yacute": "Ý",
    "Thorn": "Þ",
    "agrave": "à",
    "aacute": "á",
    "acircumflex": "â",
    "atilde": "ã",
    "adieresis": "ä",
    "aring": "å",
    "ae": "æ",
    "ccedilla": "ç",
    "egrave": "è",
    "eacute": "é",
    "ecircumflex": "ê",
    "edieresis": "ë",
    "igrave": "ì",
    "iacute": "í",
    "icircumflex": "î",
    "idieresis": "ï",
    "eth": "ð",
    "ntilde": "ñ",
    "ograve": "ò",
    "oacute": "ó",
    "ocircumflex": "ô",
    "otilde": "õ",
    "odieresis": "ö",
    "oslash": "ø",
    "ugrave": "ù",
    "uacute": "ú",
    "ucircumflex": "û",
    "udieresis": "ü",
    "yacute": "ý",
    "thorn": "þ",
    "ydieresis": "ÿ",
    # Common math/greek names from Symbol and custom CMaps.
    # PostScript /mu in standard text encodings maps to micro sign (0xB5).
    # Using U+00B5 preserves expected glyph selection in Times-like fonts.
    "mu": "µ",
    "afii61352": "№",
}


def _display_text_for_font(font: FontResource, text: str) -> str:
    if not text:
        return text
    mapped: list[str] = []
    symbolic_fonts = {"symbol", "zapfdingbats", "wingdings", "webdings"}
    symbolic = font.name.lower() in symbolic_fonts
    for char in text:
        code = ord(char)
        if symbolic and code < 256:
            glyph_name = font.encoding.get(code)
            if glyph_name is None or glyph_name == ".notdef" or code < 32:
                mapped.append("")
            else:
                mapped.append(chr(code))
            continue
        if code < 256:
            glyph_name = font.encoding.get(code)
            glyph_char = _glyph_name_to_unicode(glyph_name)
            if glyph_char is not None:
                mapped.append(glyph_char)
                continue
            if glyph_name is None or glyph_name == ".notdef" or code < 32:
                mapped.append("")
                continue
        mapped.append(char)
    return "".join(mapped)


def _glyph_name_to_unicode(glyph_name: str | None) -> str | None:
    if not glyph_name:
        return None
    base = glyph_name.split(".", 1)[0]
    if base == ".notdef":
        return ""
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
    if "_" in base:
        parts = base.split("_")
        chars: list[str] = []
        for part in parts:
            part_char = _glyph_name_to_unicode(part)
            if part_char is None:
                return None
            chars.append(part_char)
        return "".join(chars)
    return None


def _advance_text(ctx: ExecutionContext, dx: float, dy: float) -> None:
    state = ctx.graphics_state_stack.peek()
    a, b, c, d, e, f = state.text_matrix
    new_e = e + a * dx + c * dy
    new_f = f + b * dx + d * dy
    state.text_matrix = (
        a,
        b,
        c,
        d,
        new_e,
        new_f,
    )
    state.current_point = (new_e, new_f)


def _append_glyph_rect(ctx: ExecutionContext, width: float) -> None:
    state = ctx.graphics_state_stack.peek()
    height = state.font_size
    a, b, c, d, e, f = _multiply_matrix(state.ctm, state.text_matrix)
    points = [
        (e, f),
        (e + a * width, f + b * width),
        (e + a * width + c * height, f + b * width + d * height),
        (e + c * height, f + d * height),
    ]
    path = state.current_path
    path.segments.append(_segment("move", points[0]))
    path.segments.append(_segment("line", points[1]))
    path.segments.append(_segment("line", points[2]))
    path.segments.append(_segment("line", points[3]))
    path.segments.append(_segment("close", None))


def _render_type3_glyph(
    ctx: ExecutionContext,
    interpreter: PsInterpreter,
    char: str,
    root_font: FontResource | None = None,
) -> None:
    trace_enabled = os.getenv("PS_TEXT_TRACE") == "1"
    state = ctx.graphics_state_stack.peek()
    font = state.font
    if font is None:
        _advance_text(ctx, _glyph_advance(ctx, char), 0.0)
        return
    font_dict = font.font_dict
    exec_font_dict = font_dict
    if isinstance(font_dict, PsDict):
        candidate_dict = font_dict.items.get("__font_dict__")
        if isinstance(candidate_dict, PsDict):
            exec_font_dict = candidate_dict
    glyph_name = font.encoding.get(ord(char), ".notdef")
    proc = None
    if trace_enabled:
        print(
            "PS TEXT TRACE type3 glyph={} char={}".format(glyph_name, ord(char)),
            flush=True,
        )
    font_matrix = _type3_font_matrix(font)
    font_size = state.font_size or 1.0
    scaled_font_matrix = (
        font_matrix[0] * font_size,
        font_matrix[1] * font_size,
        font_matrix[2] * font_size,
        font_matrix[3] * font_size,
        font_matrix[4] * font_size,
        font_matrix[5] * font_size,
    )
    outer_state = state.clone()
    state.type3_char_width = None
    state.type3_cache_bbox = None
    text_ctm = _multiply_matrix(outer_state.ctm, state.text_matrix)
    state.ctm = _multiply_matrix(text_ctm, scaled_font_matrix)
    build_glyph = None
    build_char = None
    if isinstance(exec_font_dict, PsDict):
        candidate = exec_font_dict.items.get("BuildGlyph")
        if isinstance(candidate, PsProcedure):
            build_glyph = candidate
        candidate = exec_font_dict.items.get("BuildChar")
        if isinstance(candidate, PsProcedure):
            build_char = candidate
    if build_glyph is None and build_char is None:
        proc = font.char_procs.get(glyph_name) if font.char_procs is not None else None
        if proc is None and isinstance(exec_font_dict, PsDict):
            proc = _resolve_type3_char_proc(exec_font_dict, ord(char), glyph_name)
    previous_type3_flag = ctx.in_type3_glyph
    ctx.in_type3_glyph = True
    pushed_root_scope = False
    root_dict = None
    if root_font is not None and isinstance(root_font.font_dict, PsDict):
        if "RootBuildChar" in root_font.font_dict.items:
            root_dict = root_font.font_dict
    if root_dict is None and isinstance(font_dict, PsDict) and "RootBuildChar" in font_dict.items:
        root_dict = font_dict
    if root_dict is None:
        for scope in reversed(ctx.dictionary_stack.to_list()):
            if isinstance(scope, PsDict) and "RootBuildChar" in scope.items:
                root_dict = scope
                break
    if root_dict is None:
        root_dict = _find_rootfont_dict(ctx)
    root_build_char = None
    if isinstance(root_dict, PsDict):
        candidate = root_dict.items.get("RootBuildChar")
        if isinstance(candidate, PsProcedure):
            root_build_char = candidate
    if build_glyph is None and build_char is None and proc is None and root_build_char is None:
        _advance_text(ctx, _glyph_advance(ctx, char), 0.0)
        return
    has_rootfont_binding = any(
        isinstance(scope, PsDict) and "rootfont" in scope.items
        for scope in reversed(ctx.dictionary_stack.to_list())
    )
    if root_dict is not None:
        ctx.dictionary_stack.push(PsDict({"rootfont": root_dict}))
        pushed_root_scope = True
    char_width = None
    try:
        if proc is not None:
            pushed_dict = False
            if isinstance(exec_font_dict, PsDict):
                ctx.dictionary_stack.push(exec_font_dict)
                pushed_dict = True
            try:
                interpreter.execute_procedure(proc, ctx)
            finally:
                if pushed_dict:
                    ctx.dictionary_stack.pop()
        elif build_glyph is not None and isinstance(exec_font_dict, PsDict):
            ctx.operand_stack.push(exec_font_dict)
            ctx.operand_stack.push(PsName(glyph_name, literal=True))
            interpreter.execute_procedure(build_glyph, ctx)
        elif (
            build_char is not None
            and isinstance(exec_font_dict, PsDict)
            and (pushed_root_scope or has_rootfont_binding)
        ):
            ctx.operand_stack.push(exec_font_dict)
            ctx.operand_stack.push(ord(char))
            interpreter.execute_procedure(build_char, ctx)
        elif (
            root_build_char is not None
            and isinstance(exec_font_dict, PsDict)
            and (pushed_root_scope or has_rootfont_binding)
        ):
            # Some composite Type0 descendants don't expose BuildChar directly.
            # In that case, call RootBuildChar from the composite root font.
            ctx.operand_stack.push(exec_font_dict)
            ctx.operand_stack.push(ord(char))
            interpreter.execute_procedure(root_build_char, ctx)
    finally:
        char_width = state.type3_char_width
        if pushed_root_scope:
            ctx.dictionary_stack.pop()
        ctx.in_type3_glyph = previous_type3_flag
        # Type3 char procedures must not leak modified text/path/graphics state.
        ctx.graphics_state_stack._items[-1] = outer_state
        state = ctx.graphics_state_stack.peek()
    if char_width is not None:
        wx, wy = char_width
        advance_x = font_size * (font_matrix[0] * wx + font_matrix[2] * wy)
        advance_y = font_size * (font_matrix[1] * wx + font_matrix[3] * wy)
        advance_x += state.char_spacing
        if char == " ":
            advance_x += state.word_spacing
        _advance_text(ctx, advance_x, advance_y)
        return
    _advance_text(ctx, _glyph_advance(ctx, char), 0.0)


def _type3_font_matrix(font: FontResource) -> tuple[float, float, float, float, float, float]:
    font_dict = font.font_dict
    if isinstance(font_dict, PsDict):
        raw = font_dict.items.get("FontMatrix")
        if isinstance(raw, PsArray):
            items = raw.items
        elif isinstance(raw, list):
            items = raw
        else:
            items = None
        if items is not None and len(items) == 6 and all(
            isinstance(item, (int, float)) for item in items
        ):
            return tuple(float(item) for item in items)  # type: ignore[return-value]
    return (0.001, 0.0, 0.0, 0.001, 0.0, 0.0)


def _resolve_type3_char_proc(
    font_dict: PsDict,
    code: int,
    glyph_name: str | int,
) -> PsProcedure | None:
    char_procs = font_dict.items.get("CharProcs")
    if not isinstance(char_procs, PsDict):
        return None
    if isinstance(glyph_name, str):
        candidate = char_procs.items.get(glyph_name)
        if isinstance(candidate, PsProcedure):
            return candidate
    encoding = font_dict.items.get("Encoding")
    mapped_name: str | None = None
    if isinstance(encoding, PsArray) and 0 <= code < len(encoding.items):
        entry = encoding.items[code]
        if isinstance(entry, PsName):
            mapped_name = entry.value
        elif isinstance(entry, str):
            mapped_name = entry
    if mapped_name is None:
        return None
    candidate = char_procs.items.get(mapped_name)
    if isinstance(candidate, PsProcedure):
        return candidate
    return None


def _find_rootfont_dict(ctx: ExecutionContext) -> PsDict | None:
    directory = ctx.systemdict.items.get("FontDirectory")
    if not isinstance(directory, PsDict):
        return None
    for value in directory.items.values():
        candidate: PsDict | None = None
        if isinstance(value, PsDict):
            candidate = value
        elif isinstance(value, FontResource) and isinstance(value.font_dict, PsDict):
            candidate = value.font_dict
        if candidate is None:
            continue
        if "RootBuildChar" not in candidate.items:
            continue
        if "CharProcs" not in candidate.items:
            continue
        return candidate
    return None


def _append_charpath(ctx: ExecutionContext, interpreter: PsInterpreter, char: str) -> None:
    state = ctx.graphics_state_stack.peek()
    font = state.font
    if font is not None and font.font_type == "Type3":
        original_path = state.current_path
        state.current_path = Path([])
        ctx.charpath_mode = True
        try:
            _render_type3_glyph(ctx, interpreter, char)
        finally:
            ctx.charpath_mode = False
        original_path.segments.extend(state.current_path.segments)
        state.current_path = original_path
        return
    render_font = font.descendant if font is not None and font.descendant is not None else font
    ttf_font = _resolve_ttf_font(ctx, render_font.name if render_font is not None else "")
    if ttf_font is not None and render_font is not None:
        matrix = _multiply_matrix(state.ctm, state.text_matrix)
        a, b, c, d, e, f = matrix
        size_scale = (state.font_size or 1.0) / max(1.0, ttf_font.units_per_em)
        glyph_id = ttf_font.glyph_id_for_code(ord(char))
        contours = ttf_font.glyph_outline(glyph_id)
        if contours:
            path = _contours_to_path(contours, size_scale, a, b, c, d, e, f)
            state.current_path.segments.extend(path.segments)
        advance = ttf_font.glyph_advance(glyph_id) * size_scale
        _advance_text(ctx, advance, 0.0)
        return
    width = _glyph_advance(ctx, char)
    _append_glyph_rect(ctx, width)
    _advance_text(ctx, width, 0.0)


def _segment(kind: str, point: tuple[float, float] | None):
    from ..common.render_model import PathSegment, Point

    if point is None:
        return PathSegment("close", [])
    return PathSegment(kind, [Point(point[0], point[1])])


def _mark_text_fallback(ctx: ExecutionContext, font_name: str, font: FontResource | None) -> None:
    if font_name in ctx.text_font_overrides:
        return
    lower = font_name.lower()
    is_bold = "bold" in lower
    is_italic = "italic" in lower or "oblique" in lower
    if "palatino" in lower:
        if is_bold and is_italic:
            ctx.text_font_overrides[font_name] = "Palatino-BoldItalic"
        elif is_bold:
            ctx.text_font_overrides[font_name] = "Palatino-Bold"
        elif is_italic:
            ctx.text_font_overrides[font_name] = "Palatino-Italic"
        else:
            ctx.text_font_overrides[font_name] = "Palatino-Roman"
        return
    if "times" in lower or "serif" in lower:
        base = "Times-Roman"
    elif "symbol" in lower:
        base = "Symbol"
    elif "dingbats" in lower:
        base = "ZapfDingbats"
    elif "courier" in lower or (font is not None and _is_monospaced(font)):
        base = "Courier"
    else:
        base = "Helvetica"
    if is_bold and is_italic:
        suffix = "-BoldOblique"
    elif is_bold:
        suffix = "-Bold"
    elif is_italic:
        suffix = "-Oblique"
    else:
        suffix = ""
    ctx.text_font_overrides[font_name] = f"{base}{suffix}"


def _is_monospaced(font: FontResource) -> bool:
    widths = []
    if font.code_widths:
        widths = [value for value in font.code_widths.values() if value > 0]
    elif font.glyph_widths:
        widths = [value for value in font.glyph_widths.values() if value > 0]
    if not widths:
        return False
    min_w = min(widths)
    max_w = max(widths)
    return abs(max_w - min_w) <= 1.0


_TTF_CACHE: dict[str, TrueTypeFont] = {}


_STANDARD_FONTS = {
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-Oblique",
    "Helvetica-BoldOblique",
    "Times-Roman",
    "Times-Bold",
    "Times-Italic",
    "Times-BoldItalic",
    "Courier",
    "Courier-Bold",
    "Courier-Oblique",
    "Courier-BoldOblique",
    "Symbol",
    "ZapfDingbats",
}



def _resolve_ttf_font(ctx: ExecutionContext, font_name: str) -> TrueTypeFont | None:
    if not font_name or ctx.font_resolver is None:
        return None
    path = ctx.font_resolver.resolve_ttf_path(font_name)
    if path is None or not path.exists():
        return None
    key = str(path)
    cached = _TTF_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        font = load_ttf_font(path)
    except Exception:
        return None
    _TTF_CACHE[key] = font
    return font


def _can_use_requested_text_font(ctx: ExecutionContext, font_name: str) -> bool:
    if not font_name:
        return False
    if font_name in _STANDARD_FONTS:
        return True
    if _resolve_ttf_font(ctx, font_name) is not None:
        return True
    resolver = ctx.font_resolver
    if resolver is None:
        return False
    if resolver.get_embedded_type42(font_name) is not None:
        return True
    try:
        resource = resolver.resolve(font_name)
    except Exception:
        return False
    if resource.font_program:
        return True
    if resource.descendant is not None and resource.descendant.font_program:
        return True
    return False


def _emit_text_as_path(
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
    text: str,
    font_name: str,
    trace_enabled: bool,
    trace_every: int,
    trace_slow_ms: float,
) -> bool:
    if font_name in ctx.text_font_overrides:
        return False
    ttf_font = _resolve_ttf_font(ctx, font_name)
    if ttf_font is None:
        return False
    state = ctx.graphics_state_stack.peek()
    size_scale = (state.font_size or 1.0) / max(1.0, ttf_font.units_per_em)
    try:
        segment_cap = int(os.getenv("PS_TEXT_SEGMENT_CAP", "2000") or 0)
    except ValueError:
        segment_cap = 2000
    if trace_enabled:
        print(
            "PS TEXT TRACE path font={} len={} size_scale={:.4f}".format(
                font_name,
                len(text),
                size_scale,
            ),
            flush=True,
        )
    for idx, char in enumerate(text):
        if trace_enabled and trace_every and idx % trace_every == 0:
            print(
                "PS TEXT TRACE path char_index={} code={}".format(idx, ord(char)),
                flush=True,
            )
        matrix = _multiply_matrix(state.ctm, state.text_matrix)
        a, b, c, d, e, f = matrix
        glyph_id = ttf_font.glyph_id_for_code(ord(char))
        t0 = time.perf_counter() if trace_slow_ms else 0.0
        contours = ttf_font.glyph_outline(glyph_id)
        if trace_slow_ms:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if elapsed_ms >= trace_slow_ms:
                print(
                    "PS TEXT TRACE slow glyph_outline font={} gid={} ms={:.2f}".format(
                        font_name,
                        glyph_id,
                        elapsed_ms,
                    ),
                    flush=True,
                )
        if contours:
            path = _contours_to_path(contours, size_scale, a, b, c, d, e, f)
            if segment_cap and len(path.segments) >= segment_cap:
                _mark_text_fallback(ctx, font_name, state.font)
                if trace_enabled:
                    print(
                        "PS TEXT TRACE fallback font={} cap={} segments={}".format(
                            font_name,
                            segment_cap,
                            len(path.segments),
                        ),
                        flush=True,
                    )
                return False
            builder.add_path(path, None, state.fill_paint)
        advance = ttf_font.glyph_advance(glyph_id) * size_scale
        _advance_text(ctx, advance, 0.0)
    return True


def _font_resource_to_dict(font: FontResource) -> PsDict:
    font_type = {
        "Type0": 0,
        "Type1": 1,
        "Type3": 3,
        "Type42": 42,
    }.get(font.font_type, font.font_type)
    data: dict[str, object] = {
        "FontName": PsName(font.name, literal=True),
        "FontType": font_type,
        "__font_resource__": font,
    }
    if font.font_dict is not None and "FontMatrix" in font.font_dict.items:
        data["FontMatrix"] = font.font_dict.items["FontMatrix"]
    else:
        units = float(font.units_per_em) if font.units_per_em else 1000.0
        if units == 0.0:
            units = 1000.0
        scale = 1.0 / units
        data["FontMatrix"] = PsArray([scale, 0.0, 0.0, scale, 0.0, 0.0])
    if font.fdep_vector:
        entries: list[object] = []
        for descendant in font.fdep_vector:
            entries.append(_font_resource_to_dict(descendant))
        data["FDepVector"] = PsArray(entries)
    if font.esc_char is not None:
        data["EscChar"] = int(font.esc_char)
    if font.fmap_type is not None:
        data["FMapType"] = int(font.fmap_type)
    if font.fmap_encoding:
        data["Encoding"] = PsArray([int(v) for v in font.fmap_encoding])
    elif font.encoding:
        data["Encoding"] = _encoding_array_from_mapping(font.encoding)
    if font.font_dict is not None:
        data["__font_dict__"] = font.font_dict
    if font.code_map:
        data["__CodeMap__"] = dict(font.code_map)
    return PsDict(data)  # type: ignore[arg-type]


def _encoding_array_from_mapping(mapping: dict[int, str]) -> PsArray:
    values: list[object] = [PsName(".notdef", literal=True) for _ in range(256)]
    for raw_code, raw_name in mapping.items():
        if not isinstance(raw_code, int):
            continue
        if raw_code < 0 or raw_code > 255:
            continue
        name = raw_name if isinstance(raw_name, str) and raw_name else ".notdef"
        values[raw_code] = PsName(name, literal=True)
    return PsArray(values)


def _font_resource_from_dict(
    font_dict: PsDict,
    resolver: FontResolver | None,
    name_hint: str | None = None,
) -> FontResource:
    if "FontName" not in font_dict.items:
        if name_hint is None:
            marker = font_dict.items.get("__font_resource__")
            if isinstance(marker, FontResource):
                name_hint = marker.name
            else:
                name_hint = "UnknownFont"
        font_dict.items["FontName"] = PsName(name_hint, literal=True)

    marker = font_dict.items.get("__font_resource__")
    if isinstance(marker, FontResource):
        name_value = font_dict.items.get("FontName")
        if isinstance(name_value, PsName):
            resolved_name = name_value.value
        elif isinstance(name_value, str):
            resolved_name = name_value
        else:
            resolved_name = marker.name
        encoding = _encoding_from_value(font_dict.items.get("Encoding"), marker.encoding)
        code_map = marker.code_map
        raw_code_map = font_dict.items.get("__CodeMap__")
        if isinstance(raw_code_map, dict):
            parsed: dict[int, int] = {}
            for key, value in raw_code_map.items():
                if isinstance(key, int) and isinstance(value, int):
                    parsed[int(key)] = int(value)
            if parsed:
                code_map = parsed
        fmap_type = marker.fmap_type
        raw_fmap_type = font_dict.items.get("FMapType")
        if isinstance(raw_fmap_type, (int, float)):
            fmap_type = int(raw_fmap_type)
        return FontResource(
            name=resolved_name,
            font_type=marker.font_type,
            units_per_em=marker.units_per_em,
            encoding=encoding,
            glyph_widths=marker.glyph_widths,
            substitute=marker.substitute,
            char_procs=marker.char_procs,
            code_widths=marker.code_widths,
            descendant=marker.descendant,
            esc_char=marker.esc_char,
            fdep_vector=marker.fdep_vector,
            fmap_encoding=marker.fmap_encoding,
            font_dict=marker.font_dict,
            code_map=code_map,
            font_program=marker.font_program,
            fmap_type=fmap_type,
        )

    if resolver is None:
        raise PsUndefinedError("no font resolver")
    return resolver.resolve_from_dict(font_dict)


def _encoding_from_value(
    value: object,
    fallback: dict[int, str],
) -> dict[int, str]:
    if isinstance(value, str):
        if value == "SymbolEncoding":
            return SYMBOL_ENCODING
        if value == "ZapfDingbatsEncoding":
            return ZAPF_DINGBATS_ENCODING
        if value in ("ISOLatin1Encoding", "ISOLatin1"):
            return ISO_LATIN1_ENCODING
        return STANDARD_ENCODING
    if isinstance(value, PsName):
        if value.value == "SymbolEncoding":
            return SYMBOL_ENCODING
        if value.value == "ZapfDingbatsEncoding":
            return ZAPF_DINGBATS_ENCODING
        if value.value in ("ISOLatin1Encoding", "ISOLatin1"):
            return ISO_LATIN1_ENCODING
        return STANDARD_ENCODING
    if isinstance(value, PsArray):
        mapping: dict[int, str] = {}
        for index, item in enumerate(value.items):
            if isinstance(item, PsName):
                mapping[index] = item.value
            elif isinstance(item, str):
                mapping[index] = item
        if mapping:
            return mapping
    return fallback


def _with_font_name(
    font: FontResource,
    name: str,
    code_map: dict[int, int] | None = None,
) -> FontResource:
    if font.name == name:
        if code_map is None or code_map == font.code_map:
            return font
    resolved_code_map = dict(code_map) if isinstance(code_map, dict) and code_map else font.code_map
    return FontResource(
        name=name,
        font_type=font.font_type,
        units_per_em=font.units_per_em,
        encoding=font.encoding,
        glyph_widths=font.glyph_widths,
        substitute=font.substitute,
        char_procs=font.char_procs,
        code_widths=font.code_widths,
        descendant=font.descendant,
        esc_char=font.esc_char,
        fdep_vector=font.fdep_vector,
        fmap_encoding=font.fmap_encoding,
        font_dict=font.font_dict,
        code_map=resolved_code_map,
        font_program=font.font_program,
        fmap_type=font.fmap_type,
    )


def _compose_font_resource(
    base_font: FontResource,
    composite_name: str,
    code_map: dict[int, int] | None = None,
) -> FontResource:
    resolved_code_map = dict(code_map) if isinstance(code_map, dict) and code_map else None
    return FontResource(
        name=composite_name,
        font_type="Type0",
        units_per_em=1000,
        encoding=base_font.encoding,
        glyph_widths=base_font.glyph_widths,
        substitute=base_font.substitute,
        code_widths=base_font.code_widths,
        descendant=base_font,
        fdep_vector=[base_font],
        esc_char=base_font.esc_char,
        fmap_encoding=base_font.fmap_encoding,
        font_dict=base_font.font_dict,
        code_map=resolved_code_map,
        fmap_type=base_font.fmap_type,
    )


def _matrix_from_object(
    value: object,
) -> tuple[float, float, float, float, float, float]:
    if isinstance(value, PsArray):
        items = value.items
    elif isinstance(value, list):
        items = value
    else:
        raise PsTypeError("matrix expected")
    if len(items) != 6:
        raise PsRangeError("matrix must have 6 elements")
    result: list[float] = []
    for item in items:
        if not isinstance(item, (int, float)):
            raise PsTypeError("matrix number expected")
        result.append(float(item))
    return tuple(result)  # type: ignore[return-value]


def _resolve_font_operand(
    value: object,
    resolver: FontResolver,
    ctx: ExecutionContext,
) -> FontResource:
    if isinstance(value, FontResource):
        return value
    if isinstance(value, PsDict):
        return _font_resource_from_dict(value, ctx.font_resolver or resolver)
    if isinstance(value, PsName):
        return _resolve_font_from_directory(value.value, resolver, ctx)
    if isinstance(value, str):
        return _resolve_font_from_directory(value, resolver, ctx)
    raise PsTypeError("font name expected")


def _resolve_composite_descendant(
    value: object,
    resolver: FontResolver,
    ctx: ExecutionContext,
) -> FontResource | None:
    if isinstance(value, FontResource):
        return value
    if isinstance(value, PsDict):
        return _font_resource_from_dict(value, ctx.font_resolver or resolver)
    if isinstance(value, PsName):
        return _resolve_font_from_directory(value.value, resolver, ctx)
    if isinstance(value, str):
        return _resolve_font_from_directory(value, resolver, ctx)
    return None


def _resolve_font_from_directory(
    font_name: str,
    resolver: FontResolver,
    ctx: ExecutionContext,
) -> FontResource:
    directory = ctx.systemdict.items.get("FontDirectory")
    if isinstance(directory, PsDict) and font_name in directory.items:
        value = directory.items.get(font_name)
        if isinstance(value, FontResource):
            return value
        if isinstance(value, PsDict):
            return _font_resource_from_dict(value, ctx.font_resolver or resolver)
    return resolver.resolve(font_name)


def _resolve_cmap_mapping(value: object, ctx: ExecutionContext) -> dict[int, int] | None:
    cmap_dict = _resolve_cmap_dict(value, ctx)
    if cmap_dict is None:
        return None
    raw = cmap_dict.items.get("__CodeMap__")
    if not isinstance(raw, dict):
        return None
    parsed: dict[int, int] = {}
    for key, dst in raw.items():
        if isinstance(key, int) and isinstance(dst, int):
            parsed[int(key)] = int(dst)
    return parsed or None


def _resolve_cmap_dict(value: object, ctx: ExecutionContext) -> PsDict | None:
    if isinstance(value, PsDict):
        return value
    name = None
    if isinstance(value, PsName):
        name = value.value
    elif isinstance(value, str):
        name = value
    if not name:
        return None

    resources = ctx.systemdict.items.get("__resources__")
    if isinstance(resources, dict):
        cmap_cat = resources.get("CMap")
        if isinstance(cmap_cat, PsDict):
            candidate = cmap_cat.items.get(name)
            if isinstance(candidate, PsDict):
                return candidate
    elif isinstance(resources, PsDict):
        cmap_cat = resources.items.get("CMap")
        if isinstance(cmap_cat, PsDict):
            candidate = cmap_cat.items.get(name)
            if isinstance(candidate, PsDict):
                return candidate

    for dictionary in reversed(ctx.dictionary_stack._items):
        if not isinstance(dictionary, PsDict):
            continue
        candidate = dictionary.items.get(name)
        if isinstance(candidate, PsDict):
            return candidate
    return None


def _code_from_hex_object(value: object) -> int | None:
    if isinstance(value, PsString):
        if len(value.value) == 0:
            return None
        if len(value.value) == 1:
            return value.value[0]
        return int.from_bytes(value.value, byteorder="big", signed=False)
    if isinstance(value, bytes):
        if len(value) == 0:
            return None
        if len(value) == 1:
            return value[0]
        return int.from_bytes(value, byteorder="big", signed=False)
    if isinstance(value, PsName):
        glyph_char = _glyph_name_to_unicode(value.value)
        if glyph_char and len(glyph_char) == 1:
            return ord(glyph_char)
        if value.value.startswith("uni") and len(value.value) > 3:
            try:
                return int(value.value[3:], 16)
            except ValueError:
                return None
        if len(value.value) == 1:
            return ord(value.value)
        return None
    if isinstance(value, str):
        glyph_char = _glyph_name_to_unicode(value)
        if glyph_char and len(glyph_char) == 1:
            return ord(glyph_char)
        if len(value) == 1:
            return ord(value)
    return None


def _pop_text(ctx: ExecutionContext) -> str:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsString):
        return value.value.decode("latin-1")
    if isinstance(value, bytes):
        return value.decode("latin-1")
    if isinstance(value, str):
        return value
    raise PsTypeError("string expected")


def _pop_number(ctx: ExecutionContext) -> float:
    value = ctx.operand_stack.pop()
    if isinstance(value, (int, float)):
        return float(value)
    raise PsTypeError("number expected")


def _pop_matrix(ctx: ExecutionContext) -> tuple[float, float, float, float, float, float]:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsArray):
        items = value.items
    elif isinstance(value, list):
        items = value
    else:
        raise PsTypeError("matrix array expected")
    if len(items) != 6:
        raise PsRangeError("matrix must have 6 elements")
    return tuple(float(item) for item in items)  # type: ignore[return-value]


def _multiply_matrix(
    ctm: tuple[float, float, float, float, float, float],
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    a1, b1, c1, d1, e1, f1 = ctm
    a2, b2, c2, d2, e2, f2 = matrix
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )
