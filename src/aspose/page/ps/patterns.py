"""Pattern construction helpers for PostScript."""

from __future__ import annotations

from .color_spaces import parse_color_space
from .errors import PsRangeError, PsTypeError
from .functions import parse_function
from .objects import PsArray, PsDict, PsProcedure
from .pipeline import create_default_context
from .operators import OperatorRegistry
from .base_ops import register_base_operators
from .interpreter import PsInterpreter
from .graphics_ops import register_core_graphics_operators
from .text_ops import register_text_operators
from .image_ops import register_image_operators
from .images import PsImageStore
from .context import ExecutionContext
from ..common.color_resources import (
    AxialShading,
    Pattern,
    RadialShading,
    Shading,
    ShadingPattern,
    TilingPattern,
)
from ..common.render_model import Paint, RenderModelBuilder


def build_tiling_pattern(
    pattern_dict: PsDict,
    matrix: tuple[float, float, float, float, float, float],
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
) -> TilingPattern:
    paint_type = _require_int(pattern_dict, "PaintType")
    tiling_type = _require_int(pattern_dict, "TilingType")
    bbox = _require_bbox(pattern_dict)
    x_step = _require_number(pattern_dict, "XStep")
    y_step = _require_number(pattern_dict, "YStep")
    paint_proc = pattern_dict.items.get("PaintProc")
    if not isinstance(paint_proc, PsProcedure):
        raise PsRangeError("PaintProc missing")

    pattern_builder = RenderModelBuilder()
    width = float(bbox[2] - bbox[0])
    height = float(bbox[3] - bbox[1])
    if width <= 0 or height <= 0:
        width, height = 1.0, 1.0
    pattern_builder.set_default_page_size(width, height)

    registry = OperatorRegistry()
    register_base_operators(registry)
    register_core_graphics_operators(registry, pattern_builder)
    from .color_ops import register_color_operators

    register_color_operators(registry, pattern_builder)
    register_text_operators(registry, pattern_builder, ctx.font_resolver or _default_resolver())
    register_image_operators(
        registry, pattern_builder, ctx.image_store or PsImageStore()
    )
    interpreter = PsInterpreter(registry)

    pattern_ctx = create_default_context()
    pattern_ctx.font_resolver = ctx.font_resolver
    pattern_ctx.image_store = ctx.image_store
    pattern_ctx.default_page_size = (width, height)
    pattern_ctx.charpath_mode = ctx.charpath_mode
    pattern_ctx.operand_stack.push(pattern_dict)
    interpreter.execute_procedure(paint_proc, pattern_ctx)
    document = pattern_builder.document()
    commands = document.pages[0].commands if document.pages else []

    if paint_type == 2:
        commands = _strip_pattern_colors(commands)

    return TilingPattern(
        paint_type=paint_type,
        tiling_type=tiling_type,
        bbox=bbox,
        x_step=x_step,
        y_step=y_step,
        matrix=matrix,
        commands=commands,
    )


def build_shading_pattern(
    pattern_dict: PsDict,
    matrix: tuple[float, float, float, float, float, float],
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
) -> ShadingPattern:
    shading_obj = pattern_dict.items.get("Shading")
    if not isinstance(shading_obj, PsDict):
        raise PsRangeError("Shading dictionary missing")
    shading = build_shading(shading_obj, ctx, builder)
    return ShadingPattern(shading=shading, matrix=matrix)


def build_shading(
    shading_dict: PsDict,
    ctx: ExecutionContext,
    builder: RenderModelBuilder,
) -> Shading:
    shading_type = _require_int(shading_dict, "ShadingType")
    color_space_obj = shading_dict.items.get("ColorSpace")
    if color_space_obj is None:
        raise PsRangeError("Shading ColorSpace missing")
    color_space = parse_color_space(color_space_obj, builder)
    coords = shading_dict.items.get("Coords")
    if not isinstance(coords, PsArray):
        raise PsTypeError("Coords must be array")
    coords_list = _array_numbers(coords)
    domain = _optional_domain(shading_dict)
    extend = _optional_extend(shading_dict)
    function_obj = shading_dict.items.get("Function")
    if not isinstance(function_obj, PsDict):
        raise PsTypeError("Function must be dictionary")
    func = parse_function(function_obj, builder)

    if shading_type == 2:
        if len(coords_list) != 4:
            raise PsRangeError("Axial shading requires 4 coords")
        return AxialShading(
            color_space=color_space,
            coords=tuple(coords_list),  # type: ignore[arg-type]
            domain=domain,
            function=func,
            extend=extend,
        )
    if shading_type == 3:
        if len(coords_list) != 6:
            raise PsRangeError("Radial shading requires 6 coords")
        return RadialShading(
            color_space=color_space,
            coords=tuple(coords_list),  # type: ignore[arg-type]
            domain=domain,
            function=func,
            extend=extend,
        )
    raise PsRangeError(f"unsupported ShadingType {shading_type}")


def _strip_pattern_colors(commands: list[object]) -> list[object]:
    stripped: list[object] = []
    for command in commands:
        if hasattr(command, "path"):
            fill = getattr(command, "fill", None)
            stroke = getattr(command, "stroke", None)
            if fill is not None:
                command = type(command)(command.path, stroke, Paint("PatternBase", None))
            stripped.append(command)
            continue
        if hasattr(command, "text"):
            fill = getattr(command, "fill", None)
            if fill is not None:
                command = type(command)(
                    command.text,
                    command.font_ref,
                    command.font_size,
                    command.matrix,
                    Paint("PatternBase", None),
                )
            stripped.append(command)
            continue
        stripped.append(command)
    return stripped


def _require_int(data: PsDict, key: str) -> int:
    value = data.items.get(key)
    if not isinstance(value, (int, float)):
        raise PsTypeError(f"{key} must be numeric")
    return int(value)


def _require_number(data: PsDict, key: str) -> float:
    value = data.items.get(key)
    if not isinstance(value, (int, float)):
        raise PsTypeError(f"{key} must be numeric")
    return float(value)


def _require_bbox(data: PsDict) -> tuple[float, float, float, float]:
    bbox = data.items.get("BBox")
    if not isinstance(bbox, PsArray):
        raise PsTypeError("BBox must be array")
    values = _array_numbers(bbox)
    if len(values) != 4:
        raise PsRangeError("BBox must have 4 values")
    return (values[0], values[1], values[2], values[3])


def _array_numbers(array: PsArray) -> list[float]:
    values: list[float] = []
    for item in array.items:
        if not isinstance(item, (int, float)):
            raise PsTypeError("array must be numeric")
        values.append(float(item))
    return values


def _optional_domain(data: PsDict) -> tuple[float, float] | None:
    domain = data.items.get("Domain")
    if domain is None:
        return None
    if not isinstance(domain, PsArray):
        raise PsTypeError("Domain must be array")
    values = _array_numbers(domain)
    if len(values) != 2:
        raise PsRangeError("Domain must have 2 values")
    return (values[0], values[1])


def _optional_extend(data: PsDict) -> tuple[bool, bool]:
    extend = data.items.get("Extend")
    if extend is None:
        return (False, False)
    if not isinstance(extend, PsArray):
        raise PsTypeError("Extend must be array")
    values = []
    for item in extend.items:
        if isinstance(item, bool):
            values.append(item)
        elif isinstance(item, (int, float)):
            values.append(bool(item))
        else:
            raise PsTypeError("Extend must be boolean array")
    if len(values) != 2:
        raise PsRangeError("Extend must have 2 values")
    return (values[0], values[1])


def _default_resolver():
    from .fonts import FontResolver

    return FontResolver()
