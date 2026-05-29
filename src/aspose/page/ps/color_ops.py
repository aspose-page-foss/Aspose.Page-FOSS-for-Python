"""PS/EPS color space and pattern operators."""

from __future__ import annotations

import colorsys

from .color_spaces import parse_color_space
from .context import ExecutionContext, GraphicsState
from .errors import PsRangeError, PsTypeError
from .objects import PsArray, PsDict, PsName, PsObject, PsPattern, PsProcedure
from .operators import OperatorRegistry
from .patterns import build_shading, build_shading_pattern, build_tiling_pattern
from ..common.color_resources import (
    CieBasedColorSpace,
    ColorSpacePaint,
    DeviceNColorSpace,
    DeviceColorSpace,
    IndexedColorSpace,
    PatternColorSpace,
    PatternPaint,
    SeparationColorSpace,
    TilingPattern,
)
from ..common.render_model import Paint, Rect, RenderModelBuilder, rect_path


def register_color_operators(registry: OperatorRegistry, builder: RenderModelBuilder) -> None:
    """Register color space and pattern-related operators."""

    registry.register("setgray", lambda ctx: _op_setgray(ctx), min_operands=1)
    registry.register("currentgray", lambda ctx: _op_currentgray(ctx))
    registry.register("setrgbcolor", lambda ctx: _op_setrgb(ctx), min_operands=3)
    registry.register("sethsbcolor", lambda ctx: _op_sethsb(ctx), min_operands=3)
    registry.register("setcmykcolor", lambda ctx: _op_setcmyk(ctx), min_operands=4)
    registry.register("setscreen", _op_setscreen, min_operands=3)
    registry.register("settransfer", _op_settransfer, min_operands=1)
    registry.register("currenttransfer", _op_currenttransfer)
    registry.register("setoverprint", _op_setoverprint, min_operands=1)
    registry.register("setblackgeneration", _op_setblackgeneration, min_operands=1)
    registry.register("currentblackgeneration", _op_currentblackgeneration)
    registry.register("setundercolorremoval", _op_setundercolorremoval, min_operands=1)
    registry.register("currentundercolorremoval", _op_currentundercolorremoval)
    registry.register("setcolortransfer", _op_setcolortransfer, min_operands=4)
    registry.register("currentcolortransfer", _op_currentcolortransfer)
    registry.register("sethalftone", _op_sethalftone, min_operands=1)
    registry.register("currenthalftone", _op_currenthalftone)
    registry.register("setcolorspace", lambda ctx: _op_setcolorspace(ctx, builder), min_operands=1)
    registry.register("currentcolorspace", lambda ctx: _op_currentcolorspace(ctx))
    registry.register("setcolor", lambda ctx: _op_setcolor(ctx, builder), min_operands=1)
    registry.register("currentcolor", lambda ctx: _op_currentcolor(ctx))
    registry.register("makepattern", lambda ctx: _op_makepattern(ctx, builder), min_operands=2)
    registry.register("setpattern", lambda ctx: _op_setpattern(ctx, builder), min_operands=1)
    registry.register("shfill", lambda ctx: _op_shfill(ctx, builder), min_operands=1)


def _op_setgray(ctx: ExecutionContext) -> None:
    gray = _normalize01(_pop_number(ctx))
    state = _state(ctx)
    state.current_color_space = DeviceColorSpace("DeviceGray")
    state.current_color_components = (gray,)
    state.stroke_paint = Paint("DeviceGray", gray)
    state.fill_paint = Paint("DeviceGray", gray)


def _op_currentgray(ctx: ExecutionContext) -> None:
    state = _state(ctx)
    space = state.current_color_space
    if isinstance(space, DeviceColorSpace) and space.name == "DeviceGray":
        gray = state.current_color_components[0] if state.current_color_components else 0.0
        ctx.operand_stack.push(gray)
        return
    # Approximate current gray from RGB/CMYK where possible.
    if isinstance(space, DeviceColorSpace) and space.name == "DeviceRGB":
        r, g, b = _pad_components(state.current_color_components, 3)
        ctx.operand_stack.push(0.299 * r + 0.587 * g + 0.114 * b)
        return
    if isinstance(space, DeviceColorSpace) and space.name == "DeviceCMYK":
        c, m, y, k = _pad_components(state.current_color_components, 4)
        ctx.operand_stack.push(1.0 - min(1.0, 0.3 * c + 0.59 * m + 0.11 * y + k))
        return
    ctx.operand_stack.push(0.0)


def _op_setrgb(ctx: ExecutionContext) -> None:
    b = _normalize01(_pop_number(ctx))
    g = _normalize01(_pop_number(ctx))
    r = _normalize01(_pop_number(ctx))
    state = _state(ctx)
    state.current_color_space = DeviceColorSpace("DeviceRGB")
    state.current_color_components = (r, g, b)
    state.stroke_paint = Paint("DeviceRGB", (r, g, b))
    state.fill_paint = Paint("DeviceRGB", (r, g, b))


def _op_sethsb(ctx: ExecutionContext) -> None:
    b = _pop_number(ctx)
    s = _pop_number(ctx)
    h = _pop_number(ctx)
    r, g, v = _hsb_to_rgb_ps(h, s, b)
    state = _state(ctx)
    state.current_color_space = DeviceColorSpace("DeviceRGB")
    state.current_color_components = (r, g, v)
    state.stroke_paint = Paint("DeviceRGB", (r, g, v))
    state.fill_paint = Paint("DeviceRGB", (r, g, v))


def _op_setcmyk(ctx: ExecutionContext) -> None:
    k = _normalize01(_pop_number(ctx))
    y = _normalize01(_pop_number(ctx))
    m = _normalize01(_pop_number(ctx))
    c = _normalize01(_pop_number(ctx))
    state = _state(ctx)
    state.current_color_space = DeviceColorSpace("DeviceCMYK")
    state.current_color_components = (c, m, y, k)
    state.stroke_paint = Paint("DeviceCMYK", (c, m, y, k))
    state.fill_paint = Paint("DeviceCMYK", (c, m, y, k))


def _op_setscreen(ctx: ExecutionContext) -> None:
    proc = ctx.operand_stack.pop()
    angle = _pop_number(ctx)
    frequency = _pop_number(ctx)
    # Currently treated as a graphics-state hint with no raster effect.
    setattr(ctx, "_ps_screen", (frequency, angle, proc))


def _op_settransfer(ctx: ExecutionContext) -> None:
    setattr(ctx, "_ps_transfer", ctx.operand_stack.pop())


def _op_currenttransfer(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(getattr(ctx, "_ps_transfer", _identity_transfer_proc()))


def _op_setoverprint(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if not isinstance(value, bool):
        if isinstance(value, (int, float)):
            value = bool(value)
        else:
            raise PsTypeError("setoverprint expects boolean")
    flag = bool(value)
    setattr(ctx, "_ps_overprint", flag)
    _state(ctx).overprint = flag


def _op_setblackgeneration(ctx: ExecutionContext) -> None:
    setattr(ctx, "_ps_blackgeneration", ctx.operand_stack.pop())


def _op_currentblackgeneration(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(getattr(ctx, "_ps_blackgeneration", _identity_transfer_proc()))


def _op_setundercolorremoval(ctx: ExecutionContext) -> None:
    setattr(ctx, "_ps_undercolorremoval", ctx.operand_stack.pop())


def _op_currentundercolorremoval(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(getattr(ctx, "_ps_undercolorremoval", _identity_transfer_proc()))


def _op_setcolortransfer(ctx: ExecutionContext) -> None:
    transfer4 = ctx.operand_stack.pop()
    transfer3 = ctx.operand_stack.pop()
    transfer2 = ctx.operand_stack.pop()
    transfer1 = ctx.operand_stack.pop()
    setattr(ctx, "_ps_colortransfer", (transfer1, transfer2, transfer3, transfer4))


def _op_currentcolortransfer(ctx: ExecutionContext) -> None:
    colortransfer = getattr(ctx, "_ps_colortransfer", None)
    if colortransfer is None:
        identity = _identity_transfer_proc()
        colortransfer = (identity, identity, identity, identity)
    for proc in colortransfer:
        ctx.operand_stack.push(proc)


def _op_sethalftone(ctx: ExecutionContext) -> None:
    setattr(ctx, "_ps_halftone", ctx.operand_stack.pop())


def _op_currenthalftone(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(getattr(ctx, "_ps_halftone", None))


def _op_setcolorspace(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    space_obj = _resolve_colorspace_object(ctx.operand_stack.pop(), ctx)
    space = parse_color_space(space_obj, builder)
    state = _state(ctx)
    state.current_color_space = space
    state.current_color_components = tuple()
    state.current_pattern = None
    _sync_paints_from_state(state, builder)


def _op_currentcolorspace(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(_state(ctx).current_color_space)


def _op_setcolor(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    state = _state(ctx)
    space = state.current_color_space
    if isinstance(space, DeviceColorSpace):
        if space.name == "DeviceGray":
            gray = _normalize01(_pop_number(ctx))
            state.current_color_components = (gray,)
            state.stroke_paint = Paint("DeviceGray", gray)
            state.fill_paint = Paint("DeviceGray", gray)
            return
        if space.name == "DeviceRGB":
            b = _normalize01(_pop_number(ctx))
            g = _normalize01(_pop_number(ctx))
            r = _normalize01(_pop_number(ctx))
            state.current_color_components = (r, g, b)
            state.stroke_paint = Paint("DeviceRGB", (r, g, b))
            state.fill_paint = Paint("DeviceRGB", (r, g, b))
            return
        if space.name == "DeviceCMYK":
            k = _normalize01(_pop_number(ctx))
            y = _normalize01(_pop_number(ctx))
            m = _normalize01(_pop_number(ctx))
            c = _normalize01(_pop_number(ctx))
            state.current_color_components = (c, m, y, k)
            state.stroke_paint = Paint("DeviceCMYK", (c, m, y, k))
            state.fill_paint = Paint("DeviceCMYK", (c, m, y, k))
            return
    if isinstance(space, SeparationColorSpace):
        tint = _normalize01(_pop_number(ctx))
        state.current_color_components = (tint,)
        alt_components = _evaluate_tint(space.tint, [tint])
        if _apply_alternate_paint(state, space.alternate, alt_components):
            return
    if isinstance(space, DeviceNColorSpace):
        tint_values: list[float] = []
        for _ in range(len(space.names)):
            tint_values.append(_normalize01(_pop_number(ctx)))
        tint_values.reverse()
        state.current_color_components = tuple(tint_values)
        alt_components = _evaluate_tint(space.tint, tint_values)
        if _apply_alternate_paint(state, space.alternate, alt_components):
            return
    if isinstance(space, IndexedColorSpace):
        index = int(round(_pop_number(ctx)))
        index = max(0, min(space.hival, index))
        state.current_color_components = (float(index),)
        alt_components = _indexed_components(space, index)
        if _apply_alternate_paint(state, space.base, alt_components):
            return
    if isinstance(space, CieBasedColorSpace):
        components = []
        for _ in range(max(1, int(space.components))):
            components.append(_pop_number(ctx))
        components.reverse()
        state.current_color_components = tuple(components)
        r, g, b = _cie_to_rgb_fallback(components, space)
        state.stroke_paint = Paint("DeviceRGB", (r, g, b))
        state.fill_paint = Paint("DeviceRGB", (r, g, b))
        return
    if isinstance(space, PatternColorSpace):
        pattern_obj = None
        if len(ctx.operand_stack) > 0 and isinstance(ctx.operand_stack.peek(), PsPattern):
            pattern_obj = ctx.operand_stack.pop()
        components = _pop_components(ctx, space.base)
        if pattern_obj is None and len(ctx.operand_stack) > 0 and isinstance(ctx.operand_stack.peek(), PsPattern):
            pattern_obj = ctx.operand_stack.pop()
        if pattern_obj is not None:
            state.current_pattern = pattern_obj
        state.current_color_components = components
        _apply_pattern_paint(state, builder)
        return
    components = _pop_components(ctx, space)
    state.current_color_components = components
    _sync_paints_from_state(state, builder)


def _op_currentcolor(ctx: ExecutionContext) -> None:
    for value in _state(ctx).current_color_components:
        ctx.operand_stack.push(value)


def _op_makepattern(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    matrix = _pop_matrix(ctx)
    pattern_dict = ctx.operand_stack.pop()
    if not isinstance(pattern_dict, PsDict):
        raise PsTypeError("pattern dictionary expected")
    pattern_type = pattern_dict.items.get("PatternType")
    if not isinstance(pattern_type, (int, float)):
        raise PsRangeError("PatternType missing")
    pattern_type = int(pattern_type)
    if pattern_type == 1:
        pattern = build_tiling_pattern(pattern_dict, matrix, ctx, builder)
    elif pattern_type == 2:
        pattern = build_shading_pattern(pattern_dict, matrix, ctx, builder)
    else:
        raise PsRangeError(f"unsupported PatternType {pattern_type}")
    pattern_id = builder.register_pattern(pattern)
    ctx.operand_stack.push(PsPattern(pattern_id=pattern_id, pattern=pattern))


def _op_setpattern(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    pattern = ctx.operand_stack.pop()
    if not isinstance(pattern, PsPattern):
        raise PsTypeError("pattern expected")
    state = _state(ctx)
    state.current_pattern = pattern
    # In PostScript, setpattern also implies the Pattern colorspace. Uncolored
    # tiling patterns keep the current base colorspace; colored patterns (and
    # shading patterns) use Pattern with no base.
    base_space = None
    if isinstance(pattern.pattern, TilingPattern) and pattern.pattern.paint_type == 2:
        if isinstance(state.current_color_space, PatternColorSpace):
            base_space = state.current_color_space.base
        else:
            base_space = state.current_color_space
    state.current_color_space = PatternColorSpace(base=base_space)
    _apply_pattern_paint(state, builder)


def _op_shfill(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    shading_dict = ctx.operand_stack.pop()
    if not isinstance(shading_dict, PsDict):
        raise PsTypeError("shading dictionary expected")
    pattern = build_shading_pattern(
        PsDict({"Shading": shading_dict}), (1, 0, 0, 1, 0, 0), ctx, builder
    )
    pattern_id = builder.register_pattern(pattern)
    paint = Paint("Pattern", PatternPaint(pattern_id=pattern_id, base_space_id=None, base_components=None))
    state = _state(ctx)
    path = state.clip_path
    if path is None:
        if ctx.default_page_size is None:
            return
        width, height = ctx.default_page_size
        path = rect_path(Rect(0, 0, width, height))
    builder.add_path(path, None, paint, overprint=state.overprint)


def _apply_pattern_paint(state: GraphicsState, builder: RenderModelBuilder) -> None:
    pattern = state.current_pattern
    if pattern is None:
        return
    base_space_id = None
    base_components = None
    if isinstance(state.current_color_space, PatternColorSpace) and state.current_color_space.base is not None:
        base_space_id = builder.register_color_space(state.current_color_space.base)
        base_components = state.current_color_components
    paint = Paint(
        "Pattern",
        PatternPaint(pattern_id=pattern.pattern_id, base_space_id=base_space_id, base_components=base_components),
    )
    state.stroke_paint = paint
    state.fill_paint = paint


def _sync_paints_from_state(state: GraphicsState, builder: RenderModelBuilder) -> None:
    space = state.current_color_space
    if isinstance(space, PatternColorSpace):
        if state.current_pattern is not None:
            _apply_pattern_paint(state, builder)
        return
    if isinstance(space, DeviceColorSpace):
        if space.name == "DeviceGray":
            gray = (
                _normalize01(state.current_color_components[0])
                if state.current_color_components
                else 0.0
            )
            state.stroke_paint = Paint("DeviceGray", gray)
            state.fill_paint = Paint("DeviceGray", gray)
            return
        if space.name == "DeviceRGB":
            r, g, b = (_normalize01(v) for v in _pad_components(state.current_color_components, 3))
            state.stroke_paint = Paint("DeviceRGB", (r, g, b))
            state.fill_paint = Paint("DeviceRGB", (r, g, b))
            return
        if space.name == "DeviceCMYK":
            c, m, y, k = (_normalize01(v) for v in _pad_components(state.current_color_components, 4))
            state.stroke_paint = Paint("DeviceCMYK", (c, m, y, k))
            state.fill_paint = Paint("DeviceCMYK", (c, m, y, k))
            return
    space_id = builder.register_color_space(space)
    paint = Paint("ColorSpace", ColorSpacePaint(space_id=space_id, components=state.current_color_components))
    state.stroke_paint = paint
    state.fill_paint = paint


def _pop_number(ctx: ExecutionContext) -> float:
    value = ctx.operand_stack.pop()
    if isinstance(value, (int, float)):
        return float(value)
    raise PsTypeError("number expected")


def _identity_transfer_proc() -> PsProcedure:
    return PsProcedure([])


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


def _pop_components(ctx: ExecutionContext, space: object) -> tuple[float, ...]:
    if isinstance(space, PatternColorSpace) and space.base is None:
        return tuple()
    components: list[float] = []
    while len(ctx.operand_stack) > 0 and isinstance(ctx.operand_stack.peek(), (int, float)):
        components.append(float(ctx.operand_stack.pop()))
    components.reverse()
    return tuple(components)


def _pad_components(values: tuple[float, ...], count: int) -> tuple[float, ...]:
    padded = list(values)
    while len(padded) < count:
        padded.append(0.0)
    return tuple(padded[:count])


def _normalize01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _wrap_hue(value: float) -> float:
    wrapped = value % 1.0
    return wrapped if wrapped >= 0.0 else wrapped + 1.0


def _hsb_to_rgb_ps(h: float, s: float, b: float) -> tuple[float, float, float]:
    return colorsys.hsv_to_rgb(_wrap_hue(h), _normalize01(s), _normalize01(b))


def _state(ctx: ExecutionContext) -> GraphicsState:
    return ctx.graphics_state_stack.peek()


def _evaluate_tint(function: object, inputs: list[float]) -> list[float]:
    evaluator = getattr(function, "evaluate", None)
    if not callable(evaluator):
        return inputs
    values = evaluator(inputs)
    result: list[float] = []
    for value in values:
        if isinstance(value, (int, float)):
            result.append(float(value))
    return result


def _apply_alternate_paint(state: GraphicsState, alternate: object, components: list[float]) -> bool:
    if not isinstance(alternate, DeviceColorSpace):
        return False
    if alternate.name == "DeviceGray":
        gray = _normalize01(components[0] if components else 0.0)
        state.stroke_paint = Paint("DeviceGray", gray)
        state.fill_paint = Paint("DeviceGray", gray)
        return True
    if alternate.name == "DeviceRGB":
        padded = [0.0, 0.0, 0.0]
        for idx in range(min(3, len(components))):
            padded[idx] = _normalize01(components[idx])
        rgb = (padded[0], padded[1], padded[2])
        state.stroke_paint = Paint("DeviceRGB", rgb)
        state.fill_paint = Paint("DeviceRGB", rgb)
        return True
    if alternate.name == "DeviceCMYK":
        padded = [0.0, 0.0, 0.0, 0.0]
        for idx in range(min(4, len(components))):
            padded[idx] = _normalize01(components[idx])
        cmyk = (padded[0], padded[1], padded[2], padded[3])
        state.stroke_paint = Paint("DeviceCMYK", cmyk)
        state.fill_paint = Paint("DeviceCMYK", cmyk)
        return True
    return False


def _indexed_components(space: IndexedColorSpace, index: int) -> list[float]:
    component_count = 1
    if isinstance(space.base, DeviceColorSpace):
        if space.base.name == "DeviceRGB":
            component_count = 3
        elif space.base.name == "DeviceCMYK":
            component_count = 4
    start = index * component_count
    end = start + component_count
    chunk = space.lookup[start:end]
    if len(chunk) < component_count:
        chunk = chunk + bytes(component_count - len(chunk))
    return [byte / 255.0 for byte in chunk]


def _cie_to_rgb_fallback(
    components: list[float],
    space: CieBasedColorSpace,
) -> tuple[float, float, float]:
    padded = [0.0, 0.0, 0.0]
    ranges = space.ranges
    for idx in range(min(3, len(components))):
        value = components[idx]
        if ranges is not None and len(ranges) >= idx * 2 + 2:
            lo = ranges[idx * 2]
            hi = ranges[idx * 2 + 1]
            if hi != lo:
                value = (value - lo) / (hi - lo)
        padded[idx] = _normalize01(value)
    return padded[0], padded[1], padded[2]


def _resolve_colorspace_object(value: PsObject, ctx: ExecutionContext) -> PsObject:
    if isinstance(value, PsArray):
        return PsArray([_resolve_colorspace_object(item, ctx) for item in value.items])
    if isinstance(value, PsName) and not value.literal:
        resolved = _lookup_dict_entry(ctx, value.value)
        if resolved is not None:
            return _resolve_colorspace_object(resolved, ctx)
    return value


def _lookup_dict_entry(ctx: ExecutionContext, name: str) -> PsObject | None:
    for dictionary in reversed(ctx.dictionary_stack._items):
        if not isinstance(dictionary, PsDict):
            continue
        if name in dictionary.items:
            return dictionary.items[name]
    return None
