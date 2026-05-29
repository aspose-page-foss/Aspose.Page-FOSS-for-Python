"""Core graphics operators for PostScript/EPS."""

from __future__ import annotations

import math
from math import cos, radians, sin, tan

from .clipper import EndType, IntPoint, JoinType, offset_paths

from .context import ExecutionContext, GraphicsState, _clone_path
from .errors import PsRangeError, PsTypeError
from .interpreter import PsInterpreter
from .operators import OperatorRegistry
from .stack import PsStack
from .vm import PsSaveState, restore_state, save_state
from ..common.render_model import (
    Path,
    PathSegment,
    Point,
    StrokeStyle,
    RenderModelBuilder,
    StateRestoreCommand,
    StateSaveCommand,
)
from .objects import PsArray, PsDict, PsName, PsProcedure


def register_core_graphics_operators(
    registry: OperatorRegistry, builder: RenderModelBuilder
) -> None:
    """Register core graphics and state operators.

    Example:
        >>> registry = OperatorRegistry()
        >>> register_core_graphics_operators(registry, RenderModelBuilder())
        >>> registry.get("moveto") is not None
        True
    """

    registry.register("newpath", lambda ctx: _op_newpath(ctx))
    registry.register("moveto", lambda ctx: _op_moveto(ctx), min_operands=2)
    registry.register("lineto", lambda ctx: _op_lineto(ctx), min_operands=2)
    registry.register("curveto", lambda ctx: _op_curveto(ctx), min_operands=6)
    registry.register("rmoveto", lambda ctx: _op_rmoveto(ctx), min_operands=2)
    registry.register("rlineto", lambda ctx: _op_rlineto(ctx), min_operands=2)
    registry.register("rcurveto", lambda ctx: _op_rcurveto(ctx), min_operands=6)
    registry.register("closepath", lambda ctx: _op_closepath(ctx))
    registry.register("rectpath", lambda ctx: _op_rectpath(ctx), min_operands=4)
    registry.register("arc", lambda ctx: _op_arc(ctx, clockwise=False), min_operands=5)
    registry.register("arcn", lambda ctx: _op_arc(ctx, clockwise=True), min_operands=5)
    registry.register("arcto", lambda ctx: _op_arcto(ctx), min_operands=5)
    registry.register("arct", lambda ctx: _op_arct(ctx), min_operands=5)

    interpreter = PsInterpreter(registry)

    registry.register("stroke", lambda ctx: _op_stroke(ctx, builder))
    registry.register("fill", lambda ctx: _op_fill(ctx, builder, even_odd=False))
    registry.register("eofill", lambda ctx: _op_fill(ctx, builder, even_odd=True))
    registry.register("clip", lambda ctx: _op_clip(ctx, builder, even_odd=False))
    registry.register("eoclip", lambda ctx: _op_clip(ctx, builder, even_odd=True))
    registry.register("initclip", lambda ctx: _op_initclip(ctx, builder))
    registry.register("clippath", lambda ctx: _op_clippath(ctx, builder))
    registry.register("rectclip", lambda ctx: _op_rectclip(ctx, builder, interpreter), min_operands=1)
    registry.register("strokepath", lambda ctx: _op_strokepath(ctx))
    registry.register("flattenpath", lambda ctx: _op_flattenpath(ctx))
    registry.register("reversepath", lambda ctx: _op_reversepath(ctx))
    registry.register("pathbbox", lambda ctx: _op_pathbbox(ctx))
    registry.register("pathforall", lambda ctx: _op_pathforall(ctx, interpreter), min_operands=4)
    registry.register("showpage", lambda ctx: _op_showpage(ctx, builder))
    registry.register("setpagedevice", lambda ctx: _op_setpagedevice(ctx, builder), min_operands=1)

    registry.register("setlinewidth", lambda ctx: _op_setlinewidth(ctx), min_operands=1)
    registry.register("currentpoint", lambda ctx: _op_currentpoint(ctx))
    registry.register("setlinecap", lambda ctx: _op_setlinecap(ctx), min_operands=1)
    registry.register("setlinejoin", lambda ctx: _op_setlinejoin(ctx), min_operands=1)
    registry.register("setmiterlimit", lambda ctx: _op_setmiterlimit(ctx), min_operands=1)
    registry.register("setdash", lambda ctx: _op_setdash(ctx, interpreter), min_operands=2)
    registry.register("setflat", lambda ctx: _op_setflat(ctx), min_operands=1)
    registry.register("currentflat", lambda ctx: ctx.operand_stack.push(_state(ctx).flatness))
    registry.register("setstrokeadjust", lambda ctx: _op_setstrokeadjust(ctx), min_operands=1)

    registry.register("translate", lambda ctx: _op_translate(ctx), min_operands=2)
    registry.register("scale", lambda ctx: _op_scale(ctx), min_operands=2)
    registry.register("rotate", lambda ctx: _op_rotate(ctx), min_operands=1)
    registry.register("concat", lambda ctx: _op_concat(ctx, interpreter), min_operands=1)
    registry.register("transform", lambda ctx: _op_transform(ctx), min_operands=2)
    registry.register("dtransform", lambda ctx: _op_dtransform(ctx), min_operands=2)
    registry.register("itransform", lambda ctx: _op_itransform(ctx), min_operands=2)
    registry.register("idtransform", lambda ctx: _op_idtransform(ctx), min_operands=2)
    registry.register("concatmatrix", lambda ctx: _op_concatmatrix(ctx, interpreter), min_operands=3)
    registry.register("currentmatrix", lambda ctx: _op_currentmatrix(ctx), min_operands=1)
    registry.register("setmatrix", lambda ctx: _op_setmatrix(ctx, interpreter), min_operands=1)
    registry.register("rectfill", lambda ctx: _op_rectfill(ctx, builder, interpreter), min_operands=1)
    registry.register("rectstroke", lambda ctx: _op_rectstroke(ctx, builder, interpreter), min_operands=1)

    registry.register("gsave", lambda ctx: _op_gsave(ctx, builder))
    registry.register("grestore", lambda ctx: _op_grestore(ctx, builder))
    registry.register("save", lambda ctx: _op_save(ctx))
    registry.register("restore", lambda ctx: _op_restore(ctx))


def _op_newpath(ctx: ExecutionContext) -> None:
    _state(ctx).current_path = Path([])
    _state(ctx).current_point = None
    _state(ctx).subpath_start = None


def _op_moveto(ctx: ExecutionContext) -> None:
    y = _pop_number(ctx)
    x = _pop_number(ctx)
    _update_text_position(ctx, x, y)
    _update_current_point(ctx, x, y)
    _state(ctx).subpath_start = (x, y)
    point = _apply_ctm(_state(ctx).ctm, x, y)
    _append_segment(ctx, "move", [point])


def _op_lineto(ctx: ExecutionContext) -> None:
    y = _pop_number(ctx)
    x = _pop_number(ctx)
    _update_text_position(ctx, x, y)
    _update_current_point(ctx, x, y)
    point = _apply_ctm(_state(ctx).ctm, x, y)
    _append_segment(ctx, "line", [point])


def _op_curveto(ctx: ExecutionContext) -> None:
    y3 = _pop_number(ctx)
    x3 = _pop_number(ctx)
    y2 = _pop_number(ctx)
    x2 = _pop_number(ctx)
    y1 = _pop_number(ctx)
    x1 = _pop_number(ctx)
    _update_text_position(ctx, x3, y3)
    _update_current_point(ctx, x3, y3)
    points = [
        _apply_ctm(_state(ctx).ctm, x1, y1),
        _apply_ctm(_state(ctx).ctm, x2, y2),
        _apply_ctm(_state(ctx).ctm, x3, y3),
    ]
    _append_segment(ctx, "curve", points)


def _op_rmoveto(ctx: ExecutionContext) -> None:
    dy = _pop_number(ctx)
    dx = _pop_number(ctx)
    current = _state(ctx).current_point
    if current is None:
        raise PsRangeError("no current point")
    x = current[0] + dx
    y = current[1] + dy
    _update_text_position(ctx, x, y)
    _update_current_point(ctx, x, y)
    _state(ctx).subpath_start = (x, y)
    point = _apply_ctm(_state(ctx).ctm, x, y)
    _append_segment(ctx, "move", [point])


def _op_rlineto(ctx: ExecutionContext) -> None:
    dy = _pop_number(ctx)
    dx = _pop_number(ctx)
    current = _state(ctx).current_point
    if current is None:
        raise PsRangeError("no current point")
    x = current[0] + dx
    y = current[1] + dy
    _update_text_position(ctx, x, y)
    _update_current_point(ctx, x, y)
    point = _apply_ctm(_state(ctx).ctm, x, y)
    _append_segment(ctx, "line", [point])


def _op_rcurveto(ctx: ExecutionContext) -> None:
    dy3 = _pop_number(ctx)
    dx3 = _pop_number(ctx)
    dy2 = _pop_number(ctx)
    dx2 = _pop_number(ctx)
    dy1 = _pop_number(ctx)
    dx1 = _pop_number(ctx)
    current = _state(ctx).current_point
    if current is None:
        raise PsRangeError("no current point")
    x0, y0 = current
    x1 = x0 + dx1
    y1 = y0 + dy1
    x2 = x0 + dx2
    y2 = y0 + dy2
    x3 = x0 + dx3
    y3 = y0 + dy3
    _update_text_position(ctx, x3, y3)
    _update_current_point(ctx, x3, y3)
    points = [
        _apply_ctm(_state(ctx).ctm, x1, y1),
        _apply_ctm(_state(ctx).ctm, x2, y2),
        _apply_ctm(_state(ctx).ctm, x3, y3),
    ]
    _append_segment(ctx, "curve", points)


def _op_closepath(ctx: ExecutionContext) -> None:
    _append_segment(ctx, "close", [])
    state = _state(ctx)
    if state.subpath_start is not None:
        _update_current_point(ctx, state.subpath_start[0], state.subpath_start[1])


def _op_rectpath(ctx: ExecutionContext) -> None:
    height = _pop_number(ctx)
    width = _pop_number(ctx)
    y = _pop_number(ctx)
    x = _pop_number(ctx)
    ctm = _state(ctx).ctm
    points = [
        _apply_ctm(ctm, x, y),
        _apply_ctm(ctm, x + width, y),
        _apply_ctm(ctm, x + width, y + height),
        _apply_ctm(ctm, x, y + height),
    ]
    path = Path(
        [
            PathSegment("move", [points[0]]),
            PathSegment("line", [points[1]]),
            PathSegment("line", [points[2]]),
            PathSegment("line", [points[3]]),
            PathSegment("close", []),
        ]
    )
    _state(ctx).current_path = path


def _op_arc(ctx: ExecutionContext, clockwise: bool) -> None:
    angle2 = _pop_number(ctx)
    angle1 = _pop_number(ctx)
    radius = _pop_number(ctx)
    cy = _pop_number(ctx)
    cx = _pop_number(ctx)
    if clockwise:
        if angle2 > angle1:
            angle2 -= 360.0
    else:
        if angle2 < angle1:
            angle2 += 360.0
    _update_text_position(
        ctx,
        cx + radius * cos(radians(angle2)),
        cy + radius * sin(radians(angle2)),
    )
    _update_current_point(
        ctx,
        cx + radius * cos(radians(angle2)),
        cy + radius * sin(radians(angle2)),
    )
    _append_arc(ctx, cx, cy, radius, angle1, angle2)


def _op_arcto(ctx: ExecutionContext) -> None:
    radius = _pop_number(ctx)
    y2 = _pop_number(ctx)
    x2 = _pop_number(ctx)
    y1 = _pop_number(ctx)
    x1 = _pop_number(ctx)
    current = _state(ctx).current_point
    if current is None:
        raise PsRangeError("no current point")
    x0, y0 = current
    t1, t2, center, start_angle, end_angle, clockwise = _arcto_geometry(
        (x0, y0), (x1, y1), (x2, y2), radius
    )
    _update_text_position(ctx, t2[0], t2[1])
    _update_current_point(ctx, t2[0], t2[1])
    if clockwise:
        if end_angle > start_angle:
            end_angle -= 360.0
    else:
        if end_angle < start_angle:
            end_angle += 360.0
    _append_arc(ctx, center[0], center[1], radius, start_angle, end_angle)
    ctx.operand_stack.push(t1[0])
    ctx.operand_stack.push(t1[1])
    ctx.operand_stack.push(t2[0])
    ctx.operand_stack.push(t2[1])


def _op_arct(ctx: ExecutionContext) -> None:
    _op_arcto(ctx)
    ctx.operand_stack.pop()
    ctx.operand_stack.pop()
    ctx.operand_stack.pop()
    ctx.operand_stack.pop()


def _op_stroke(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    if ctx.charpath_mode:
        return
    state = _state(ctx)
    if (
        not ctx.in_type3_glyph
        and not state.dash[0]
        and _has_nonuniform_axis_aligned_stroke_scale(state.ctm)
    ):
        if _emit_nonuniform_stroke_outline(state, builder):
            state.current_path = Path([])
            return
    stroke_scale = _stroke_scale_from_ctm(state.ctm)
    line_width = state.line_width * stroke_scale
    dash = [value * stroke_scale for value in state.dash[0]]
    dash_phase = state.dash[1] * stroke_scale
    style = StrokeStyle(
        line_width=line_width,
        line_cap=state.line_cap,
        line_join=state.line_join,
        miter_limit=state.miter_limit,
        dash=dash,
        dash_phase=dash_phase,
    )
    builder.add_path(
        state.current_path,
        style,
        None,
        stroke_paint=state.stroke_paint,
        overprint=state.overprint,
    )
    state.current_path = Path([])


def _emit_nonuniform_stroke_outline(state: GraphicsState, builder: RenderModelBuilder) -> bool:
    inverse = _invert_ctm(state.ctm)
    if inverse is None:
        return False
    user_path = _transform_path(state.current_path, inverse)
    if not user_path.segments:
        return False
    curve_steps = _curve_steps_from_flatness(state.flatness)
    subpaths = _flatten_to_points(user_path, curve_steps)
    if not subpaths:
        return False
    temp_state = state.clone()
    temp_state.line_width = state.line_width
    temp_state.line_cap = state.line_cap
    temp_state.line_join = state.line_join
    temp_state.miter_limit = state.miter_limit
    stroke_paint = state.stroke_paint
    emitted = False
    for points, closed in subpaths:
        outlines = _stroke_outline(points, closed, temp_state)
        if not outlines:
            continue
        combined_segments: list[PathSegment] = []
        for outline in outlines:
            transformed = [_apply_ctm(state.ctm, pt.x, pt.y) for pt in outline]
            path_segments = _points_to_path(transformed)
            if not path_segments:
                continue
            combined_segments.extend(path_segments)
        if combined_segments:
            builder.add_path(
                Path(combined_segments),
                None,
                stroke_paint,
                fill_rule="nonzero",
                overprint=state.overprint,
            )
            emitted = True
    return emitted


def _effective_line_width_in_device_space(
    line_width: float,
    ctm: tuple[float, float, float, float, float, float],
) -> float:
    return line_width * _stroke_scale_from_ctm(ctm)


def _stroke_scale_from_ctm(ctm: tuple[float, float, float, float, float, float]) -> float:
    a, b, c, d, _, _ = ctm
    sx = math.hypot(a, b)
    sy = math.hypot(c, d)
    if sx <= 1e-12 and sy <= 1e-12:
        return 1.0
    if sx <= 1e-12:
        scale = sy
    elif sy <= 1e-12:
        scale = sx
    else:
        scale = (sx + sy) * 0.5
    return scale


def _has_nonuniform_axis_aligned_stroke_scale(
    ctm: tuple[float, float, float, float, float, float]
) -> bool:
    a, b, c, d, _, _ = ctm
    sx = math.hypot(a, b)
    sy = math.hypot(c, d)
    if sx <= 1e-12 or sy <= 1e-12:
        return False
    if abs(sx - sy) <= 1e-9:
        return False
    return abs(b) <= 1e-9 and abs(c) <= 1e-9


def _op_fill(ctx: ExecutionContext, builder: RenderModelBuilder, even_odd: bool) -> None:
    if ctx.charpath_mode:
        return
    state = _state(ctx)
    fill_rule = "evenodd" if even_odd else "nonzero"
    builder.add_path(
        state.current_path,
        None,
        state.fill_paint,
        fill_rule=fill_rule,
        overprint=state.overprint,
    )
    state.current_path = Path([])


def _op_strokepath(ctx: ExecutionContext) -> None:
    state = _state(ctx)
    if not state.current_path.segments:
        return
    curve_steps = _curve_steps_from_flatness(state.flatness)
    subpaths = _flatten_to_points(state.current_path, curve_steps)
    outline_segments: list[PathSegment] = []
    for points, closed in subpaths:
        outlines = _stroke_outline(points, closed, state)
        if not outlines:
            continue
        for outline in outlines:
            outline_segments.extend(_points_to_path(outline))
    state.current_path = Path(outline_segments)
    _reset_current_point(state)


def _op_flattenpath(ctx: ExecutionContext) -> None:
    state = _state(ctx)
    if not state.current_path.segments:
        return
    curve_steps = _curve_steps_from_flatness(state.flatness)
    state.current_path = _flatten_path_segments(state.current_path, curve_steps)
    _reset_current_point(state)


def _op_reversepath(ctx: ExecutionContext) -> None:
    state = _state(ctx)
    if not state.current_path.segments:
        return
    state.current_path = _reverse_path(state.current_path)
    _reset_current_point(state)


def _op_pathbbox(ctx: ExecutionContext) -> None:
    state = _state(ctx)
    path = state.current_path
    inverse = _invert_ctm(state.ctm)
    if inverse is not None:
        path = _transform_path(path, inverse)
    bounds = _path_bounds(path)
    if bounds is None:
        raise PsRangeError("no current point")
    llx, lly, urx, ury = bounds
    ctx.operand_stack.push(llx)
    ctx.operand_stack.push(lly)
    ctx.operand_stack.push(urx)
    ctx.operand_stack.push(ury)


def _op_pathforall(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    close_proc = ctx.operand_stack.pop()
    curve_proc = ctx.operand_stack.pop()
    line_proc = ctx.operand_stack.pop()
    move_proc = ctx.operand_stack.pop()
    if not all(isinstance(proc, PsProcedure) for proc in (move_proc, line_proc, curve_proc, close_proc)):
        raise PsTypeError("pathforall expects procedures")
    state = _state(ctx)
    segments = list(state.current_path.segments)
    current: Point | None = None
    start: Point | None = None
    for segment in segments:
        if segment.kind == "move":
            current = segment.points[0]
            start = current
            ctx.operand_stack.push(current.x)
            ctx.operand_stack.push(current.y)
            interpreter.execute_procedure(move_proc, ctx)
        elif segment.kind == "line":
            point = segment.points[0]
            current = point
            ctx.operand_stack.push(point.x)
            ctx.operand_stack.push(point.y)
            interpreter.execute_procedure(line_proc, ctx)
        elif segment.kind == "curve":
            p1, p2, p3 = segment.points
            current = p3
            ctx.operand_stack.push(p1.x)
            ctx.operand_stack.push(p1.y)
            ctx.operand_stack.push(p2.x)
            ctx.operand_stack.push(p2.y)
            ctx.operand_stack.push(p3.x)
            ctx.operand_stack.push(p3.y)
            interpreter.execute_procedure(curve_proc, ctx)
        elif segment.kind == "close":
            if start is not None:
                current = start
            interpreter.execute_procedure(close_proc, ctx)
    state.current_point = (current.x, current.y) if current is not None else None
    state.subpath_start = (start.x, start.y) if start is not None else None


def _op_clip(ctx: ExecutionContext, builder: RenderModelBuilder, even_odd: bool) -> None:
    if ctx.charpath_mode:
        return
    state = _state(ctx)
    fill_rule = "evenodd" if even_odd else "nonzero"
    clip_path = _clone_path(state.current_path)
    builder.clip(clip_path, fill_rule=fill_rule)
    # Preserve the current path (PostScript clip does not clear it) but
    # snapshot the clip path to avoid later mutations.
    state.clip_path = clip_path


def _op_clippath(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    if ctx.charpath_mode:
        return
    state = _state(ctx)
    if state.clip_path is not None:
        state.current_path = _clone_path(state.clip_path)
        state.current_point = None
        state.subpath_start = None
        return
    if ctx.default_page_size is None:
        state.current_path = Path([])
        state.current_point = None
        state.subpath_start = None
        return
    width, height = ctx.default_page_size
    # Render-model paths are already flattened in transformed coordinates.
    # For the default clip path fallback, emit the device page box directly.
    points = [
        Point(0.0, 0.0),
        Point(width, 0.0),
        Point(width, height),
        Point(0.0, height),
    ]
    state.current_path = Path(
        [
            PathSegment("move", [points[0]]),
            PathSegment("line", [points[1]]),
            PathSegment("line", [points[2]]),
            PathSegment("line", [points[3]]),
            PathSegment("close", []),
        ]
    )
    state.current_point = None
    state.subpath_start = None


def _op_initclip(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    if ctx.charpath_mode:
        return
    if ctx.default_page_size is None:
        return
    width, height = ctx.default_page_size
    # `initclip` resets clipping to the full page in device space.
    # Do not apply the current CTM here; otherwise scaled/rotated CTMs shrink
    # or displace the page clip incorrectly.
    points = [
        Point(0.0, 0.0),
        Point(width, 0.0),
        Point(width, height),
        Point(0.0, height),
    ]
    path = Path(
        [
            PathSegment("move", [points[0]]),
            PathSegment("line", [points[1]]),
            PathSegment("line", [points[2]]),
            PathSegment("line", [points[3]]),
            PathSegment("close", []),
        ]
    )
    builder.clip(path)
    _state(ctx).clip_path = path
    _state(ctx).current_path = Path([])


def _op_showpage(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    if ctx.charpath_mode:
        return
    builder.document()


def _op_setpagedevice(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    value = ctx.operand_stack.pop()
    if not isinstance(value, PsDict):
        return
    page_size = value.items.get("PageSize")
    if isinstance(page_size, PsArray):
        items = page_size.items
    elif isinstance(page_size, (list, tuple)):
        items = list(page_size)
    else:
        return
    if len(items) < 2:
        return
    width_raw = items[0]
    height_raw = items[1]
    if not isinstance(width_raw, (int, float)) or not isinstance(height_raw, (int, float)):
        return
    width = float(width_raw)
    height = float(height_raw)
    if width <= 0 or height <= 0:
        return
    orientation = ""
    if ctx.dsc is not None and ctx.dsc.orientation is not None:
        orientation = ctx.dsc.orientation.strip().lower()
    has_viewing_orientation = bool(getattr(ctx.dsc, "viewing_orientation", None))
    if orientation == "landscape" and width < height and not has_viewing_orientation:
        width, height = height, width
    ctx.default_page_size = (width, height)
    builder.set_default_page_size(width, height)
    active_page = getattr(builder, "_active_page", None)
    if active_page is None:
        return
    # Some printer prologs emit save/restore around page-device setup before
    # any drawable marks. In that case, keep the already-open page in sync
    # with the updated page size to avoid stale dimensions.
    if all(isinstance(command, (StateSaveCommand, StateRestoreCommand)) for command in active_page.commands):
        active_page.width = width
        active_page.height = height


def _op_setlinewidth(ctx: ExecutionContext) -> None:
    _state(ctx).line_width = _pop_number(ctx)


def _op_currentpoint(ctx: ExecutionContext) -> None:
    point = _state(ctx).current_point
    if point is None:
        raise PsRangeError("no current point")
    ctx.operand_stack.push(point[0])
    ctx.operand_stack.push(point[1])


def _op_setlinecap(ctx: ExecutionContext) -> None:
    _state(ctx).line_cap = int(_pop_number(ctx))


def _op_setlinejoin(ctx: ExecutionContext) -> None:
    _state(ctx).line_join = int(_pop_number(ctx))


def _op_setmiterlimit(ctx: ExecutionContext) -> None:
    _state(ctx).miter_limit = _pop_number(ctx)


def _op_setdash(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    phase = _pop_number(ctx)
    array_obj = ctx.operand_stack.pop()
    values = _resolve_array_numbers(ctx, interpreter, array_obj)
    _state(ctx).dash = (values, phase)


def _op_setflat(ctx: ExecutionContext) -> None:
    value = _pop_number(ctx)
    if value < 0:
        raise PsRangeError("flatness must be non-negative")
    _state(ctx).flatness = value


def _op_setstrokeadjust(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, bool):
        setattr(_state(ctx), "stroke_adjust", value)
        return
    if isinstance(value, (int, float)):
        setattr(_state(ctx), "stroke_adjust", bool(value))
        return
    raise PsTypeError("setstrokeadjust expects boolean")


def _op_rectclip(ctx: ExecutionContext, builder: RenderModelBuilder, interpreter: PsInterpreter) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, (PsArray, list)):
        numbers = _resolve_array_numbers(ctx, interpreter, value)
    else:
        height = _coerce_number(value)
        width = _pop_number(ctx)
        y = _pop_number(ctx)
        x = _pop_number(ctx)
        numbers = [x, y, width, height]
    if len(numbers) % 4 != 0:
        raise PsRangeError("rectclip expects 4n numbers")
    ctm = _state(ctx).ctm
    segments: list[PathSegment] = []
    for idx in range(0, len(numbers), 4):
        x, y, width, height = numbers[idx : idx + 4]
        points = [
            _apply_ctm(ctm, x, y),
            _apply_ctm(ctm, x + width, y),
            _apply_ctm(ctm, x + width, y + height),
            _apply_ctm(ctm, x, y + height),
        ]
        segments.extend(
            [
                PathSegment("move", [points[0]]),
                PathSegment("line", [points[1]]),
                PathSegment("line", [points[2]]),
                PathSegment("line", [points[3]]),
                PathSegment("close", []),
            ]
        )
    path = Path(segments)
    builder.clip(path)
    state = _state(ctx)
    state.clip_path = path
    state.current_path = Path([])
    state.current_point = None
    state.subpath_start = None


def _op_translate(ctx: ExecutionContext) -> None:
    ty = _pop_number(ctx)
    tx = _pop_number(ctx)
    _concat_ctm(ctx, (1.0, 0.0, 0.0, 1.0, tx, ty))


def _op_scale(ctx: ExecutionContext) -> None:
    sy = _pop_number(ctx)
    sx = _pop_number(ctx)
    _concat_ctm(ctx, (sx, 0.0, 0.0, sy, 0.0, 0.0))


def _op_rotate(ctx: ExecutionContext) -> None:
    angle = _pop_number(ctx)
    radians_value = radians(angle)
    c = cos(radians_value)
    s = sin(radians_value)
    _concat_ctm(ctx, (c, s, -s, c, 0.0, 0.0))


def _op_concat(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    matrix = _pop_matrix(ctx, interpreter)
    _concat_ctm(ctx, matrix)


def _op_transform(ctx: ExecutionContext) -> None:
    y = _pop_number(ctx)
    x = _pop_number(ctx)
    point = _apply_ctm(_state(ctx).ctm, x, y)
    ctx.operand_stack.push(point.x)
    ctx.operand_stack.push(point.y)


def _op_dtransform(ctx: ExecutionContext) -> None:
    matrix = _state(ctx).ctm
    maybe_matrix = ctx.operand_stack.peek()
    if isinstance(maybe_matrix, (PsArray, list)):
        matrix = _pop_matrix(ctx)
    dy = _pop_number(ctx)
    dx = _pop_number(ctx)
    a, b, c, d, _, _ = matrix
    ctx.operand_stack.push(a * dx + c * dy)
    ctx.operand_stack.push(b * dx + d * dy)


def _op_itransform(ctx: ExecutionContext) -> None:
    y = _pop_number(ctx)
    x = _pop_number(ctx)
    inverse = _invert_ctm(_state(ctx).ctm)
    if inverse is None:
        raise PsRangeError("non-invertible matrix")
    point = _apply_ctm(inverse, x, y)
    ctx.operand_stack.push(point.x)
    ctx.operand_stack.push(point.y)


def _op_idtransform(ctx: ExecutionContext) -> None:
    matrix = _state(ctx).ctm
    maybe_matrix = ctx.operand_stack.peek()
    if isinstance(maybe_matrix, (PsArray, list)):
        matrix = _pop_matrix(ctx)
    dy = _pop_number(ctx)
    dx = _pop_number(ctx)
    inverse = _invert_ctm(matrix)
    if inverse is None:
        raise PsRangeError("non-invertible matrix")
    a, b, c, d, _, _ = inverse
    ctx.operand_stack.push(a * dx + c * dy)
    ctx.operand_stack.push(b * dx + d * dy)


def _op_concatmatrix(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    target = ctx.operand_stack.pop()
    matrix2 = _pop_matrix(ctx, interpreter)
    matrix1 = _pop_matrix(ctx, interpreter)
    if isinstance(target, PsArray):
        items = target.items
    elif isinstance(target, list):
        items = target
    else:
        raise PsTypeError("matrix array expected")
    if len(items) != 6:
        raise PsRangeError("matrix must have 6 elements")
    a1, b1, c1, d1, e1, f1 = matrix1
    a2, b2, c2, d2, e2, f2 = matrix2
    result = (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )
    items[0], items[1], items[2], items[3], items[4], items[5] = result
    if isinstance(target, PsArray):
        target.items = items
        ctx.operand_stack.push(target)
    else:
        ctx.operand_stack.push(items)


def _op_currentmatrix(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsArray):
        items = value.items
    elif isinstance(value, list):
        items = value
    else:
        raise PsTypeError("matrix array expected")
    if len(items) != 6:
        raise PsRangeError("matrix must have 6 elements")
    a, b, c, d, e, f = _state(ctx).ctm
    items[0] = float(a)
    items[1] = float(b)
    items[2] = float(c)
    items[3] = float(d)
    items[4] = float(e)
    items[5] = float(f)
    if isinstance(value, PsArray):
        value.items = items
        ctx.operand_stack.push(value)
    else:
        ctx.operand_stack.push(items)


def _op_setmatrix(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    matrix = _pop_matrix(ctx, interpreter)
    state = _state(ctx)
    old_ctm = state.ctm
    inverse = _invert_ctm(matrix)
    if inverse is not None:
        if state.current_point is not None:
            device_point = _apply_ctm(old_ctm, state.current_point[0], state.current_point[1])
            user_point = _apply_ctm(inverse, device_point.x, device_point.y)
            state.current_point = (user_point.x, user_point.y)
        if state.subpath_start is not None:
            device_point = _apply_ctm(old_ctm, state.subpath_start[0], state.subpath_start[1])
            user_point = _apply_ctm(inverse, device_point.x, device_point.y)
            state.subpath_start = (user_point.x, user_point.y)
        state.text_matrix = _rebase_text_translation(state.text_matrix, old_ctm, inverse)
        state.text_line_matrix = _rebase_text_translation(state.text_line_matrix, old_ctm, inverse)
    state.ctm = matrix


def _op_rectfill(ctx: ExecutionContext, builder: RenderModelBuilder, interpreter: PsInterpreter) -> None:
    numbers = _rect_numbers_from_operand(ctx, interpreter)
    state = _state(ctx)
    original_path = _clone_path(state.current_path)
    original_point = state.current_point
    original_subpath = state.subpath_start
    try:
        for idx in range(0, len(numbers), 4):
            x, y, width, height = numbers[idx : idx + 4]
            ctx.operand_stack.push(x)
            ctx.operand_stack.push(y)
            ctx.operand_stack.push(width)
            ctx.operand_stack.push(height)
            _op_rectpath(ctx)
            _op_fill(ctx, builder, even_odd=False)
    finally:
        state.current_path = original_path
        state.current_point = original_point
        state.subpath_start = original_subpath


def _op_rectstroke(ctx: ExecutionContext, builder: RenderModelBuilder, interpreter: PsInterpreter) -> None:
    numbers = _rect_numbers_from_operand(ctx, interpreter)
    state = _state(ctx)
    original_path = _clone_path(state.current_path)
    original_point = state.current_point
    original_subpath = state.subpath_start
    try:
        for idx in range(0, len(numbers), 4):
            x, y, width, height = numbers[idx : idx + 4]
            ctx.operand_stack.push(x)
            ctx.operand_stack.push(y)
            ctx.operand_stack.push(width)
            ctx.operand_stack.push(height)
            _op_rectpath(ctx)
            _op_stroke(ctx, builder)
    finally:
        state.current_path = original_path
        state.current_point = original_point
        state.subpath_start = original_subpath


def _op_gsave(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    ctx.graphics_state_stack.push(_state(ctx).clone())
    builder.save_state()


def _op_grestore(ctx: ExecutionContext, builder: RenderModelBuilder) -> None:
    if len(ctx.graphics_state_stack) <= 1:
        raise PsRangeError("graphics state stack underflow")
    ctx.graphics_state_stack.pop()
    builder.restore_state()


def _op_save(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(save_state(ctx))


def _op_restore(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if not isinstance(value, PsSaveState):
        raise PsTypeError("restore expects save state")
    restore_state(ctx, value)


def _append_arc(ctx: ExecutionContext, cx: float, cy: float, radius: float, angle1: float, angle2: float) -> None:
    segments = _arc_segments(cx, cy, radius, angle1, angle2)
    if not segments:
        return
    ctm = _state(ctx).ctm
    start_point = _apply_ctm(ctm, segments[0][0].x, segments[0][0].y)
    if _state(ctx).current_path.segments:
        _append_segment(ctx, "line", [start_point])
    else:
        _append_segment(ctx, "move", [start_point])
    for _, c1, c2, end in segments:
        _append_segment(
            ctx,
            "curve",
            [
                _apply_ctm(ctm, c1.x, c1.y),
                _apply_ctm(ctm, c2.x, c2.y),
                _apply_ctm(ctm, end.x, end.y),
            ],
        )


def _arc_segments(cx: float, cy: float, radius: float, angle1: float, angle2: float) -> list[tuple[Point, Point, Point, Point]]:
    delta = angle2 - angle1
    if delta == 0:
        return []
    steps = max(1, int(abs(delta) / 90.0) + (1 if abs(delta) % 90.0 > 1e-6 else 0))
    step = delta / steps
    segments: list[tuple[Point, Point, Point, Point]] = []
    for index in range(steps):
        a0 = angle1 + step * index
        a1 = a0 + step
        segments.append(_arc_to_bezier(cx, cy, radius, a0, a1))
    return segments


def _arc_to_bezier(
    cx: float, cy: float, radius: float, angle1: float, angle2: float
) -> tuple[Point, Point, Point, Point]:
    theta1 = radians(angle1)
    theta2 = radians(angle2)
    delta = theta2 - theta1
    k = 4.0 / 3.0 * tan(delta / 4.0)

    x0 = cx + radius * cos(theta1)
    y0 = cy + radius * sin(theta1)
    x3 = cx + radius * cos(theta2)
    y3 = cy + radius * sin(theta2)

    x1 = x0 - radius * sin(theta1) * k
    y1 = y0 + radius * cos(theta1) * k
    x2 = x3 + radius * sin(theta2) * k
    y2 = y3 - radius * cos(theta2) * k

    return (
        Point(x0, y0),
        Point(x1, y1),
        Point(x2, y2),
        Point(x3, y3),
    )


def _arcto_geometry(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    radius: float,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], float, float, bool]:
    x0, y0 = p0
    x1, y1 = p1
    x2, y2 = p2
    v1x = x0 - x1
    v1y = y0 - y1
    v2x = x2 - x1
    v2y = y2 - y1
    len1 = (v1x * v1x + v1y * v1y) ** 0.5
    len2 = (v2x * v2x + v2y * v2y) ** 0.5
    if len1 == 0 or len2 == 0:
        raise PsRangeError("invalid arcto geometry")
    u1x = v1x / len1
    u1y = v1y / len1
    u2x = v2x / len2
    u2y = v2y / len2
    dot = max(-1.0, min(1.0, u1x * u2x + u1y * u2y))
    angle = math.acos(dot)
    if abs(angle) < 1e-9:
        raise PsRangeError("invalid arcto angle")
    offset = radius / math.tan(angle / 2.0)
    t1 = (x1 + u1x * offset, y1 + u1y * offset)
    t2 = (x1 + u2x * offset, y1 + u2y * offset)
    bis_x = u1x + u2x
    bis_y = u1y + u2y
    bis_len = (bis_x * bis_x + bis_y * bis_y) ** 0.5
    if bis_len == 0:
        raise PsRangeError("invalid arcto geometry")
    bis_x /= bis_len
    bis_y /= bis_len
    dist = radius / math.sin(angle / 2.0)
    center = (x1 + bis_x * dist, y1 + bis_y * dist)
    cross = u1x * u2y - u1y * u2x
    clockwise = cross > 0
    start_angle = math.degrees(math.atan2(t1[1] - center[1], t1[0] - center[0]))
    end_angle = math.degrees(math.atan2(t2[1] - center[1], t2[0] - center[0]))
    return t1, t2, center, start_angle, end_angle, clockwise


def _append_segment(ctx: ExecutionContext, kind: str, points: list[Point]) -> None:
    state = _state(ctx)
    state.current_path.segments.append(PathSegment(kind, points))


def _state(ctx: ExecutionContext) -> GraphicsState:
    return ctx.graphics_state_stack.peek()


def _update_text_position(ctx: ExecutionContext, x: float, y: float) -> None:
    state = _state(ctx)
    state.text_matrix = (1.0, 0.0, 0.0, 1.0, x, y)
    state.text_line_matrix = state.text_matrix


def _update_current_point(ctx: ExecutionContext, x: float, y: float) -> None:
    _state(ctx).current_point = (x, y)


def _apply_ctm(ctm: tuple[float, float, float, float, float, float], x: float, y: float) -> Point:
    a, b, c, d, e, f = ctm
    return Point(a * x + c * y + e, b * x + d * y + f)


def _concat_ctm(ctx: ExecutionContext, matrix: tuple[float, float, float, float, float, float]) -> None:
    state = _state(ctx)
    old_ctm = state.ctm
    a1, b1, c1, d1, e1, f1 = state.ctm
    a2, b2, c2, d2, e2, f2 = matrix
    new_ctm = (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )
    inverse = _invert_ctm(new_ctm)
    if inverse is not None:
        if state.current_point is not None:
            device_point = _apply_ctm(old_ctm, state.current_point[0], state.current_point[1])
            user_point = _apply_ctm(inverse, device_point.x, device_point.y)
            state.current_point = (user_point.x, user_point.y)
        if state.subpath_start is not None:
            device_point = _apply_ctm(old_ctm, state.subpath_start[0], state.subpath_start[1])
            user_point = _apply_ctm(inverse, device_point.x, device_point.y)
            state.subpath_start = (user_point.x, user_point.y)
        state.text_matrix = _rebase_text_translation(state.text_matrix, old_ctm, inverse)
        state.text_line_matrix = _rebase_text_translation(state.text_line_matrix, old_ctm, inverse)
    state.ctm = new_ctm


def _invert_ctm(matrix: tuple[float, float, float, float, float, float]) -> tuple[float, float, float, float, float, float] | None:
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


def _rebase_text_translation(
    text_matrix: tuple[float, float, float, float, float, float],
    old_ctm: tuple[float, float, float, float, float, float],
    inverse_new_ctm: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    a, b, c, d, e, f = text_matrix
    device_point = _apply_ctm(old_ctm, e, f)
    user_point = _apply_ctm(inverse_new_ctm, device_point.x, device_point.y)
    return (a, b, c, d, user_point.x, user_point.y)


def _pop_number(ctx: ExecutionContext) -> float:
    value = ctx.operand_stack.pop()
    return _coerce_number(value)


def _coerce_number(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise PsTypeError("number expected")


def _pop_matrix(
    ctx: ExecutionContext,
    interpreter: PsInterpreter | None = None,
) -> tuple[float, float, float, float, float, float]:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsArray):
        items = value.items
    elif isinstance(value, list):
        items = value
    else:
        raise PsTypeError("matrix array expected")
    if len(items) == 6 and all(isinstance(item, (int, float)) for item in items):
        numbers = [float(item) for item in items]
        return (numbers[0], numbers[1], numbers[2], numbers[3], numbers[4], numbers[5])
    if interpreter is not None:
        # Some real-world inputs use executable names/procedures in matrix
        # arrays (eg x_squash in COLOR13). Resolve via interpreter semantics.
        numbers = _resolve_array_numbers(ctx, interpreter, value)
    else:
        numbers = _evaluate_array_numbers(items)
    if len(numbers) != 6:
        raise PsRangeError("matrix must have 6 elements")
    return (numbers[0], numbers[1], numbers[2], numbers[3], numbers[4], numbers[5])


def _evaluate_array_numbers(items: list[object]) -> list[float]:
    stack: list[float] = []
    for item in items:
        if isinstance(item, (int, float)):
            stack.append(float(item))
            continue
        if isinstance(item, PsName):
            if item.literal:
                raise PsTypeError("number expected")
            name = item.value
            if name == "sin":
                stack.append(math.sin(math.radians(stack.pop())))
                continue
            if name == "cos":
                stack.append(math.cos(math.radians(stack.pop())))
                continue
            if name == "atan":
                x = stack.pop()
                y = stack.pop()
                stack.append(math.degrees(math.atan2(y, x)))
                continue
            if name == "add":
                b = stack.pop()
                a = stack.pop()
                stack.append(a + b)
                continue
            if name == "sub":
                b = stack.pop()
                a = stack.pop()
                stack.append(a - b)
                continue
            if name == "mul":
                b = stack.pop()
                a = stack.pop()
                stack.append(a * b)
                continue
            if name == "div":
                b = stack.pop()
                a = stack.pop()
                stack.append(a / b)
                continue
            if name == "neg":
                stack.append(-stack.pop())
                continue
            if name == "abs":
                stack.append(abs(stack.pop()))
                continue
            if name == "dup":
                stack.append(stack[-1])
                continue
            if name == "exch":
                stack[-1], stack[-2] = stack[-2], stack[-1]
                continue
            raise PsTypeError(f"unsupported array operator: {name}")
        raise PsTypeError("number expected")
    return stack


def _resolve_array_numbers(
    ctx: ExecutionContext,
    interpreter: PsInterpreter,
    array_obj: object,
) -> list[float]:
    if isinstance(array_obj, PsArray):
        items = array_obj.items
    elif isinstance(array_obj, list):
        items = array_obj
    else:
        raise PsTypeError("array expected")
    if all(isinstance(item, (int, float)) for item in items):
        return [float(item) for item in items]

    temp_ctx = ExecutionContext(
        operand_stack=PsStack(),
        execution_stack=PsStack(),
        dictionary_stack=ctx.dictionary_stack.clone(),
        graphics_state_stack=PsStack([_state(ctx).clone()]),
        userdict=ctx.userdict,
        systemdict=ctx.systemdict,
        dsc=ctx.dsc,
        default_page_size=ctx.default_page_size,
        image_store=ctx.image_store,
        font_resolver=ctx.font_resolver,
        charpath_mode=ctx.charpath_mode,
    )
    for item in items:
        interpreter.execute_object(item, temp_ctx)
    values: list[float] = []
    for item in temp_ctx.operand_stack.to_list():
        values.append(_coerce_number(item))
    return values


def _rect_numbers_from_operand(
    ctx: ExecutionContext,
    interpreter: PsInterpreter,
) -> list[float]:
    value = ctx.operand_stack.pop()
    if isinstance(value, (PsArray, list)):
        numbers = _resolve_array_numbers(ctx, interpreter, value)
    else:
        height = _coerce_number(value)
        width = _pop_number(ctx)
        y = _pop_number(ctx)
        x = _pop_number(ctx)
        numbers = [x, y, width, height]
    if len(numbers) % 4 != 0:
        raise PsRangeError("rect operator expects 4n numbers")
    return numbers


def _curve_steps_from_flatness(flatness: float) -> int:
    if flatness <= 0:
        return 36
    steps = int(12 / flatness)
    return max(4, min(200, steps))


def _flatten_to_points(path: Path, curve_steps: int) -> list[tuple[list[Point], bool]]:
    subpaths: list[tuple[list[Point], bool]] = []
    current: list[Point] = []
    start: Point | None = None
    current_point: Point | None = None
    closed = False
    for segment in path.segments:
        if segment.kind == "move":
            if current:
                subpaths.append((current, closed))
            current = [segment.points[0]]
            start = segment.points[0]
            current_point = segment.points[0]
            closed = False
        elif segment.kind == "line":
            point = segment.points[0]
            if current_point is None:
                current = [point]
                start = point
            else:
                current.append(point)
            current_point = point
        elif segment.kind == "curve":
            if current_point is None:
                continue
            p0 = current_point
            p1, p2, p3 = segment.points
            steps = _curve_steps(p0, p1, p2, p3, curve_steps)
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
                if current[-1] != start:
                    current.append(start)
            if current:
                closed = True
                subpaths.append((current, closed))
            current = []
            start = None
            current_point = None
            closed = False
    if current:
        subpaths.append((current, closed))
    return subpaths


def _curve_steps(p0: Point, p1: Point, p2: Point, p3: Point, base_steps: int) -> int:
    length = (
        math.hypot(p1.x - p0.x, p1.y - p0.y)
        + math.hypot(p2.x - p1.x, p2.y - p1.y)
        + math.hypot(p3.x - p2.x, p3.y - p2.y)
    )
    adaptive = int(length / 30)
    if adaptive < base_steps:
        return base_steps
    return min(200, adaptive)


def _points_to_path(points: list[Point]) -> list[PathSegment]:
    if not points:
        return []
    segments = [PathSegment("move", [points[0]])]
    for point in points[1:]:
        segments.append(PathSegment("line", [point]))
    segments.append(PathSegment("close", []))
    return segments


class _IntPoint:
    __slots__ = ("x", "y")

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _IntPoint):
            return False
        return self.x == other.x and self.y == other.y


class _DoublePoint:
    __slots__ = ("x", "y")

    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self.x = x
        self.y = y

    def copy(self) -> "_DoublePoint":
        return _DoublePoint(self.x, self.y)


def _clipper_round(value: float) -> int:
    return int(value - 0.5) if value < 0 else int(value + 0.5)


def _clipper_orientation(path: list[_IntPoint]) -> bool:
    high = len(path) - 1
    if high < 2:
        return True
    area = (path[high].x + path[0].x) * (path[0].y - path[high].y)
    for idx in range(1, high + 1):
        area += (path[idx - 1].x + path[idx].x) * (path[idx].y - path[idx - 1].y)
    return area >= 0


def _clipper_reverse_paths(paths: list[list[_IntPoint]]) -> None:
    for path in paths:
        path.reverse()


def _clipper_distance_sqrd(pt1: _IntPoint, pt2: _IntPoint) -> float:
    dx = float(pt1.x - pt2.x)
    dy = float(pt1.y - pt2.y)
    return dx * dx + dy * dy


def _clipper_closest_point_on_line(
    pt: _IntPoint, line_pt1: _IntPoint, line_pt2: _IntPoint
) -> _DoublePoint:
    dx = float(line_pt2.x - line_pt1.x)
    dy = float(line_pt2.y - line_pt1.y)
    if dx == 0.0 and dy == 0.0:
        return _DoublePoint(float(line_pt1.x), float(line_pt1.y))
    q = ((pt.x - line_pt1.x) * dx + (pt.y - line_pt1.y) * dy) / (dx * dx + dy * dy)
    return _DoublePoint((1 - q) * line_pt1.x + q * line_pt2.x, (1 - q) * line_pt1.y + q * line_pt2.y)


def _clipper_slopes_near_collinear(
    pt1: _IntPoint, pt2: _IntPoint, pt3: _IntPoint, dist_sqrd: float
) -> bool:
    if _clipper_distance_sqrd(pt1, pt2) > _clipper_distance_sqrd(pt1, pt3):
        return False
    cpol = _clipper_closest_point_on_line(pt2, pt1, pt3)
    dx = pt2.x - cpol.x
    dy = pt2.y - cpol.y
    return (dx * dx + dy * dy) < dist_sqrd


def _clipper_points_are_close(pt1: _IntPoint, pt2: _IntPoint, dist_sqrd: float) -> bool:
    dx = float(pt1.x - pt2.x)
    dy = float(pt1.y - pt2.y)
    return (dx * dx + dy * dy) <= dist_sqrd


def _clipper_clean_polygon(path: list[_IntPoint], distance: float = 1.415) -> list[_IntPoint]:
    dist_sqrd = distance * distance
    high = len(path) - 1
    result: list[_IntPoint] = []
    while high > 0 and _clipper_points_are_close(path[high], path[0], dist_sqrd):
        high -= 1
    if high < 2:
        return result
    pt = path[high]
    i = 0
    while True:
        while i < high and _clipper_points_are_close(pt, path[i], dist_sqrd):
            i += 2
        i2 = i
        while i < high and (
            _clipper_points_are_close(path[i], path[i + 1], dist_sqrd)
            or _clipper_slopes_near_collinear(pt, path[i], path[i + 1], dist_sqrd)
        ):
            i += 1
        if i >= high:
            break
        if i != i2:
            continue
        pt = path[i]
        result.append(pt)
        i += 1
    if i <= high:
        result.append(path[i])
    if len(result) > 2 and _clipper_slopes_near_collinear(result[-2], result[-1], result[0], dist_sqrd):
        result.pop()
    if len(result) < 3:
        result = []
    return result


def _clipper_get_unit_normal(pt1: _IntPoint, pt2: _IntPoint) -> _DoublePoint:
    dx = pt2.x - pt1.x
    dy = pt2.y - pt1.y
    if dx == 0 and dy == 0:
        return _DoublePoint()
    inv = 1.0 / math.sqrt(dx * dx + dy * dy)
    dx *= inv
    dy *= inv
    return _DoublePoint(dy, -dx)


def _clipper_strip_dups_and_get_bot_pt(
    in_path: list[_IntPoint], closed: bool
) -> tuple[list[_IntPoint], _IntPoint] | None:
    if not in_path:
        return None
    path = list(in_path)
    if closed:
        while path and path[0] == path[-1]:
            path.pop()
    if not path:
        return None
    out_path: list[_IntPoint] = [path[0]]
    bot_pt = path[0]
    for pt in path[1:]:
        if pt == out_path[-1]:
            continue
        out_path.append(pt)
        if pt.y > bot_pt.y or (pt.y == bot_pt.y and pt.x < bot_pt.x):
            bot_pt = pt
    if len(out_path) < 2 or (closed and len(out_path) == 2):
        return None
    return out_path, bot_pt


class _PolyOffsetBuilder:
    def __init__(
        self,
        polys: list[list[_IntPoint]],
        delta: float,
        join_type: str,
        end_type: str,
        miter_limit: float,
    ) -> None:
        self._polys = polys
        self._join_type = join_type
        self._end_type = end_type
        self._solution: list[list[_IntPoint]] = []
        self._normals: list[_DoublePoint] = []
        self._current_poly: list[_IntPoint] = []
        self._i = 0
        self._j = 0
        self._k = 0
        self._sin_a = 0.0
        self._sin = 0.0
        self._cos = 0.0
        self._steps360 = 0.0
        if abs(delta) < 1e-12:
            self._solution = polys
            return
        if end_type != "closed" and delta < 0:
            delta = -delta
        self._delta = delta
        limit = miter_limit
        if join_type == "miter":
            if miter_limit > 2:
                self._miter_lim = 2.0 / (miter_limit * miter_limit)
            else:
                self._miter_lim = 0.5
            if end_type == "round":
                limit = 0.25
        else:
            self._miter_lim = 0.0
        if join_type == "round" or end_type == "round":
            if limit <= 0:
                limit = 0.25
            elif limit > abs(delta) * 0.25:
                limit = abs(delta) * 0.25
            self._steps360 = math.pi / math.acos(1.0 - limit / abs(delta))
            self._sin = math.sin(2 * math.pi / self._steps360)
            self._cos = math.cos(2 * math.pi / self._steps360)
            self._steps360 /= math.pi * 2.0
            if delta < 0:
                self._sin = -self._sin
        self._build()

    @property
    def solution(self) -> list[list[_IntPoint]]:
        return self._solution

    def _add_point(self, pt: _IntPoint) -> None:
        self._current_poly.append(pt)

    def _do_square(self) -> None:
        dot = self._normals[self._k].x * self._normals[self._j].x + self._normals[self._k].y * self._normals[self._j].y
        dx = math.tan(math.atan2(self._sin_a, dot) / 4.0)
        p = self._polys[self._i][self._j]
        self._add_point(
            _IntPoint(
                _clipper_round(p.x + self._delta * (self._normals[self._k].x - self._normals[self._k].y * dx)),
                _clipper_round(p.y + self._delta * (self._normals[self._k].y + self._normals[self._k].x * dx)),
            )
        )
        self._add_point(
            _IntPoint(
                _clipper_round(p.x + self._delta * (self._normals[self._j].x + self._normals[self._j].y * dx)),
                _clipper_round(p.y + self._delta * (self._normals[self._j].y - self._normals[self._j].x * dx)),
            )
        )

    def _do_miter(self, r: float) -> None:
        q = self._delta / r
        p = self._polys[self._i][self._j]
        self._add_point(
            _IntPoint(
                _clipper_round(p.x + (self._normals[self._k].x + self._normals[self._j].x) * q),
                _clipper_round(p.y + (self._normals[self._k].y + self._normals[self._j].y) * q),
            )
        )

    def _do_round(self) -> None:
        dot = self._normals[self._k].x * self._normals[self._j].x + self._normals[self._k].y * self._normals[self._j].y
        a = math.atan2(self._sin_a, dot)
        steps = int(_clipper_round(self._steps360 * abs(a)))
        x = self._normals[self._k].x
        y = self._normals[self._k].y
        p = self._polys[self._i][self._j]
        for _ in range(steps):
            self._add_point(
                _IntPoint(
                    _clipper_round(p.x + x * self._delta),
                    _clipper_round(p.y + y * self._delta),
                )
            )
            x2 = x
            x = x * self._cos - self._sin * y
            y = x2 * self._sin + y * self._cos
        self._add_point(
            _IntPoint(
                _clipper_round(p.x + self._normals[self._j].x * self._delta),
                _clipper_round(p.y + self._normals[self._j].y * self._delta),
            )
        )

    def _offset_point(self) -> None:
        self._sin_a = (
            self._normals[self._k].x * self._normals[self._j].y
            - self._normals[self._j].x * self._normals[self._k].y
        )
        if self._sin_a > 1.0:
            self._sin_a = 1.0
        elif self._sin_a < -1.0:
            self._sin_a = -1.0
        p = self._polys[self._i][self._j]
        if self._sin_a * self._delta < 0:
            self._add_point(
                _IntPoint(
                    _clipper_round(p.x + self._normals[self._k].x * self._delta),
                    _clipper_round(p.y + self._normals[self._k].y * self._delta),
                )
            )
            self._add_point(_IntPoint(p.x, p.y))
            self._add_point(
                _IntPoint(
                    _clipper_round(p.x + self._normals[self._j].x * self._delta),
                    _clipper_round(p.y + self._normals[self._j].y * self._delta),
                )
            )
        else:
            if self._join_type == "miter":
                r = 1.0 + (
                    self._normals[self._j].x * self._normals[self._k].x
                    + self._normals[self._j].y * self._normals[self._k].y
                )
                if r >= self._miter_lim:
                    self._do_miter(r)
                else:
                    self._do_square()
            elif self._join_type == "square":
                self._do_square()
            else:
                self._do_round()
        self._k = self._j

    def _build(self) -> None:
        for self._i, poly in enumerate(self._polys):
            length = len(poly)
            if length == 0 or (length < 3 and self._delta <= 0):
                continue
            if length == 1:
                self._current_poly = []
                if self._join_type == "round":
                    x = 1.0
                    y = 0.0
                    for _ in range(1, _clipper_round(self._steps360 * 2 * math.pi) + 1):
                        self._add_point(
                            _IntPoint(
                                _clipper_round(poly[0].x + x * self._delta),
                                _clipper_round(poly[0].y + y * self._delta),
                            )
                        )
                        x2 = x
                        x = x * self._cos - self._sin * y
                        y = x2 * self._sin + y * self._cos
                else:
                    x = -1.0
                    y = -1.0
                    for _ in range(4):
                        self._add_point(
                            _IntPoint(
                                _clipper_round(poly[0].x + x * self._delta),
                                _clipper_round(poly[0].y + y * self._delta),
                            )
                        )
                        if x < 0:
                            x = 1.0
                        elif y < 0:
                            y = 1.0
                        else:
                            x = -1.0
                self._solution.append(self._current_poly)
                continue
            self._normals = []
            for j in range(length - 1):
                self._normals.append(_clipper_get_unit_normal(poly[j], poly[j + 1]))
            if self._end_type == "closed":
                self._normals.append(_clipper_get_unit_normal(poly[length - 1], poly[0]))
            else:
                self._normals.append(self._normals[length - 2].copy())
            self._current_poly = []
            if self._end_type == "closed":
                self._k = length - 1
                for self._j in range(length):
                    self._offset_point()
                self._solution.append(self._current_poly)
            else:
                self._k = 0
                for self._j in range(1, length - 1):
                    self._offset_point()
                self._j = length - 1
                if self._end_type == "butt":
                    pt1 = _IntPoint(
                        _clipper_round(poly[self._j].x + self._normals[self._j].x * self._delta),
                        _clipper_round(poly[self._j].y + self._normals[self._j].y * self._delta),
                    )
                    self._add_point(pt1)
                    pt1 = _IntPoint(
                        _clipper_round(poly[self._j].x - self._normals[self._j].x * self._delta),
                        _clipper_round(poly[self._j].y - self._normals[self._j].y * self._delta),
                    )
                    self._add_point(pt1)
                else:
                    self._k = length - 2
                    self._sin_a = 0.0
                    self._normals[self._j].x = -self._normals[self._j].x
                    self._normals[self._j].y = -self._normals[self._j].y
                    if self._end_type == "square":
                        self._do_square()
                    else:
                        self._do_round()
                for j in range(length - 1, 0, -1):
                    self._normals[j].x = -self._normals[j - 1].x
                    self._normals[j].y = -self._normals[j - 1].y
                self._normals[0].x = -self._normals[1].x
                self._normals[0].y = -self._normals[1].y
                self._k = length - 1
                for self._j in range(self._k - 1, 0, -1):
                    self._offset_point()
                if self._end_type == "butt":
                    pt1 = _IntPoint(
                        _clipper_round(poly[0].x - self._normals[0].x * self._delta),
                        _clipper_round(poly[0].y - self._normals[0].y * self._delta),
                    )
                    self._add_point(pt1)
                    pt1 = _IntPoint(
                        _clipper_round(poly[0].x + self._normals[0].x * self._delta),
                        _clipper_round(poly[0].y + self._normals[0].y * self._delta),
                    )
                    self._add_point(pt1)
                else:
                    self._k = 1
                    self._sin_a = 0.0
                    if self._end_type == "square":
                        self._do_square()
                    else:
                        self._do_round()
                self._solution.append(self._current_poly)


def _clipper_offset_paths(
    polys: list[list[_IntPoint]],
    delta: float,
    join_type: str,
    end_type: str,
    miter_limit: float,
) -> list[list[_IntPoint]]:
    join_map = {
        "miter": JoinType.jtMiter,
        "round": JoinType.jtRound,
        "square": JoinType.jtSquare,
    }
    end_map = {
        "closed": EndType.etClosed,
        "butt": EndType.etButt,
        "square": EndType.etSquare,
        "round": EndType.etRound,
    }
    join = join_map.get(join_type, JoinType.jtMiter)
    end = end_map.get(end_type, EndType.etClosed)
    int_paths: list[list[IntPoint]] = [
        [IntPoint(pt.x, pt.y) for pt in path] for path in polys
    ]
    offset = offset_paths(int_paths, delta, join, end, miter_limit)
    return [
        [_IntPoint(pt.x, pt.y) for pt in path]
        for path in offset
        if path
    ]


def _stroke_outline(
    points: list[Point], closed: bool, state: GraphicsState
) -> list[list[Point]] | None:
    if len(points) < 2:
        return None
    half = max(0.0, state.line_width / 2.0)
    if half == 0:
        return None
    pts = points[:-1] if closed and points[0] == points[-1] else points
    count = len(pts)
    if count < 2:
        return None

    join = "miter"
    if state.line_join == 1:
        join = "round"
    elif state.line_join == 2:
        join = "square"
    end_type = "closed" if closed else "butt"
    if not closed:
        if state.line_cap == 1:
            end_type = "round"
        elif state.line_cap == 2:
            end_type = "square"

    scale = 10000.0
    width = half * scale
    if width == 0:
        return None

    path = [_IntPoint(int(round(p.x * scale)), int(round(p.y * scale))) for p in pts]
    outlines: list[list[Point]] = []
    miter_limit = state.miter_limit * scale
    if closed:
        outer = _clipper_offset_paths([path], width, join, "closed", miter_limit)
        inner = _clipper_offset_paths([path], -width, join, "closed", miter_limit)
        for result in outer:
            outlines.append([Point(pt.x / scale, pt.y / scale) for pt in result])
        for result in inner:
            outlines.append([Point(pt.x / scale, pt.y / scale) for pt in reversed(result)])
    else:
        outer = _clipper_offset_paths([path], width, join, end_type, miter_limit)
        for result in outer:
            outlines.append([Point(pt.x / scale, pt.y / scale) for pt in result])
    return outlines


def _flatten_path_segments(path: Path, curve_steps: int) -> Path:
    segments: list[PathSegment] = []
    current_point: Point | None = None
    start: Point | None = None
    for segment in path.segments:
        if segment.kind == "move":
            current_point = segment.points[0]
            start = current_point
            segments.append(PathSegment("move", [current_point]))
        elif segment.kind == "line":
            point = segment.points[0]
            if current_point is None:
                current_point = point
                start = point
                segments.append(PathSegment("move", [point]))
            else:
                segments.append(PathSegment("line", [point]))
            current_point = point
        elif segment.kind == "curve":
            if current_point is None:
                continue
            p0 = current_point
            p1, p2, p3 = segment.points
            steps = _curve_steps(p0, p1, p2, p3, curve_steps)
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
                point = Point(x, y)
                segments.append(PathSegment("line", [point]))
            current_point = p3
        elif segment.kind == "close":
            segments.append(PathSegment("close", []))
            if start is not None:
                current_point = start
    return Path(segments)


def _reverse_path(path: Path) -> Path:
    subpaths = _collect_subpaths(path)
    reversed_segments: list[PathSegment] = []
    for segments, closed in subpaths:
        if not segments:
            continue
        start_point = segments[-1][2]
        reversed_segments.append(PathSegment("move", [start_point]))
        for kind, seg_start, _, points in reversed(segments):
            if kind == "line":
                reversed_segments.append(PathSegment("line", [seg_start]))
            elif kind == "curve":
                p1, p2, _ = points
                reversed_segments.append(PathSegment("curve", [p2, p1, seg_start]))
        if closed:
            reversed_segments.append(PathSegment("close", []))
    return Path(reversed_segments)


def _collect_subpaths(path: Path) -> list[tuple[list[tuple[str, Point, Point, list[Point]]], bool]]:
    subpaths: list[tuple[list[tuple[str, Point, Point, list[Point]]], bool]] = []
    current: Point | None = None
    start: Point | None = None
    segments: list[tuple[str, Point, Point, list[Point]]] = []
    closed = False
    for segment in path.segments:
        if segment.kind == "move":
            if segments:
                subpaths.append((segments, closed))
            segments = []
            closed = False
            current = segment.points[0]
            start = current
        elif segment.kind == "line":
            if current is None:
                current = segment.points[0]
                start = current
            segments.append(("line", current, segment.points[0], segment.points))
            current = segment.points[0]
        elif segment.kind == "curve":
            if current is None:
                current = segment.points[-1]
                start = current
            segments.append(("curve", current, segment.points[-1], segment.points))
            current = segment.points[-1]
        elif segment.kind == "close":
            if current is not None and start is not None:
                segments.append(("close", current, start, []))
                current = start
                closed = True
    if segments:
        subpaths.append((segments, closed))
    return subpaths


def _path_bounds(path: Path) -> tuple[float, float, float, float] | None:
    # Expand a bit to align with PostScript pathbbox behavior for Bezier curves.
    # This matches reference outputs that include control-point extremes.
    tolerance = 1e-6
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    current: Point | None = None
    start: Point | None = None
    for segment in path.segments:
        if segment.kind == "move":
            current = segment.points[0]
            start = current
            min_x, min_y, max_x, max_y = _expand_bounds(min_x, min_y, max_x, max_y, current)
        elif segment.kind == "line":
            point = segment.points[0]
            if current is None:
                current = point
                start = point
            min_x, min_y, max_x, max_y = _expand_bounds(min_x, min_y, max_x, max_y, current)
            min_x, min_y, max_x, max_y = _expand_bounds(min_x, min_y, max_x, max_y, point)
            current = point
        elif segment.kind == "curve":
            if current is None:
                continue
            p1, p2, p3 = segment.points
            bounds = _bezier_bounds(current, p1, p2, p3)
            min_x = min(min_x, bounds[0], p1.x, p2.x)
            min_y = min(min_y, bounds[1], p1.y, p2.y)
            max_x = max(max_x, bounds[2], p1.x, p2.x)
            max_y = max(max_y, bounds[3], p1.y, p2.y)
            current = p3
        elif segment.kind == "close":
            if current is not None and start is not None:
                min_x, min_y, max_x, max_y = _expand_bounds(min_x, min_y, max_x, max_y, current)
                min_x, min_y, max_x, max_y = _expand_bounds(min_x, min_y, max_x, max_y, start)
                current = start
    if min_x == float("inf"):
        return None
    llx = min_x - tolerance
    lly = min_y - tolerance
    urx = max_x + tolerance
    ury = max_y + tolerance
    if abs(llx) < tolerance:
        llx = 0.0
    if abs(lly) < tolerance:
        lly = 0.0
    if abs(urx) < tolerance:
        urx = 0.0
    if abs(ury) < tolerance:
        ury = 0.0
    return llx, lly, urx, ury


def _expand_bounds(
    min_x: float, min_y: float, max_x: float, max_y: float, point: Point
) -> tuple[float, float, float, float]:
    return (
        min(min_x, point.x),
        min(min_y, point.y),
        max(max_x, point.x),
        max(max_y, point.y),
    )


def _bezier_bounds(p0: Point, p1: Point, p2: Point, p3: Point) -> tuple[float, float, float, float]:
    xs = [p0.x, p3.x]
    ys = [p0.y, p3.y]
    for t in _bezier_extrema(p0.x, p1.x, p2.x, p3.x):
        xs.append(_bezier_value(p0.x, p1.x, p2.x, p3.x, t))
    for t in _bezier_extrema(p0.y, p1.y, p2.y, p3.y):
        ys.append(_bezier_value(p0.y, p1.y, p2.y, p3.y, t))
    return min(xs), min(ys), max(xs), max(ys)


def _bezier_extrema(p0: float, p1: float, p2: float, p3: float) -> list[float]:
    a = -p0 + 3 * p1 - 3 * p2 + p3
    b = 3 * p0 - 6 * p1 + 3 * p2
    c = -3 * p0 + 3 * p1
    if abs(a) < 1e-12:
        if abs(b) < 1e-12:
            return []
        t = -c / (2 * b)
        return [t] if 0 < t < 1 else []
    A = 3 * a
    B = 2 * b
    C = c
    disc = B * B - 4 * A * C
    if disc < 0:
        return []
    root = math.sqrt(disc)
    t1 = (-B + root) / (2 * A)
    t2 = (-B - root) / (2 * A)
    result: list[float] = []
    if 0 < t1 < 1:
        result.append(t1)
    if 0 < t2 < 1:
        result.append(t2)
    return result


def _bezier_value(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    return (
        (1 - t) ** 3 * p0
        + 3 * (1 - t) ** 2 * t * p1
        + 3 * (1 - t) * t ** 2 * p2
        + t ** 3 * p3
    )


def _reset_current_point(state: GraphicsState) -> None:
    current: Point | None = None
    start: Point | None = None
    for segment in state.current_path.segments:
        if segment.kind == "move":
            current = segment.points[0]
            start = current
        elif segment.kind == "line":
            current = segment.points[0]
        elif segment.kind == "curve":
            current = segment.points[-1]
        elif segment.kind == "close":
            if start is not None:
                current = start
    state.current_point = (current.x, current.y) if current is not None else None
    state.subpath_start = (start.x, start.y) if start is not None else None


def _transform_path(path: Path, matrix: tuple[float, float, float, float, float, float]) -> Path:
    segments: list[PathSegment] = []
    for segment in path.segments:
        if segment.kind in ("move", "line", "curve"):
            points = [_apply_ctm(matrix, point.x, point.y) for point in segment.points]
            segments.append(PathSegment(segment.kind, points))
        else:
            segments.append(PathSegment(segment.kind, []))
    return Path(segments)
