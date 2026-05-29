"""Execution context and graphics state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .dsc import DscMetadata
from .errors import PsError
from .objects import PsDict, PsObject
from .stack import PsStack
from .images import PsImageStore
from .fonts import FontResolver, FontResource
from .objects import PsPattern
from ..common.color_resources import DeviceColorSpace, ColorSpace
from ..common.render_model import Paint, Path, PathSegment


@dataclass
class GraphicsState:
    """Tracks current graphics state parameters.

    Example:
        >>> state = GraphicsState()
        >>> state.line_width
        1.0
    """

    ctm: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    line_width: float = 1.0
    line_cap: int = 0
    line_join: int = 0
    miter_limit: float = 10.0
    dash: tuple[list[float], float] = (None, 0.0)
    flatness: float = 1.0
    current_path: Path = field(default_factory=lambda: Path([]))
    current_point: tuple[float, float] | None = None
    subpath_start: tuple[float, float] | None = None
    clip_path: Path | None = None
    stroke_paint: Paint = field(default_factory=lambda: Paint("DeviceGray", 0.0))
    fill_paint: Paint = field(default_factory=lambda: Paint("DeviceGray", 0.0))
    image_interpolate: bool = False
    text_matrix: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    text_line_matrix: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    font: FontResource | None = None
    font_size: float = 0.0
    char_spacing: float = 0.0
    word_spacing: float = 0.0
    text_leading: float = 0.0
    text_rise: float = 0.0
    type3_char_width: tuple[float, float] | None = None
    type3_cache_bbox: tuple[float, float, float, float] | None = None
    current_color_space: ColorSpace = field(
        default_factory=lambda: DeviceColorSpace("DeviceGray")
    )
    current_color_components: tuple[float, ...] = (0.0,)
    current_pattern: PsPattern | None = None
    overprint: bool = False

    def __post_init__(self) -> None:
        if self.dash[0] is None:
            self.dash = ([], self.dash[1])

    def clone(self) -> "GraphicsState":
        return GraphicsState(
            ctm=self.ctm,
            line_width=self.line_width,
            line_cap=self.line_cap,
            line_join=self.line_join,
            miter_limit=self.miter_limit,
            dash=(self.dash[0].copy(), self.dash[1]),
            flatness=self.flatness,
            current_path=_clone_path(self.current_path),
            current_point=self.current_point,
            subpath_start=self.subpath_start,
            clip_path=_clone_path(self.clip_path) if self.clip_path is not None else None,
            stroke_paint=self.stroke_paint,
            fill_paint=self.fill_paint,
            image_interpolate=self.image_interpolate,
            text_matrix=self.text_matrix,
            text_line_matrix=self.text_line_matrix,
            font=self.font,
            font_size=self.font_size,
            char_spacing=self.char_spacing,
            word_spacing=self.word_spacing,
            text_leading=self.text_leading,
            text_rise=self.text_rise,
            type3_char_width=self.type3_char_width,
            type3_cache_bbox=self.type3_cache_bbox,
            current_color_space=self.current_color_space,
            current_color_components=self.current_color_components,
            current_pattern=self.current_pattern,
            overprint=self.overprint,
        )


@dataclass
class ExecutionContext:
    """Holds interpreter stacks, dictionaries, and metadata for execution.

    Example:
        >>> ctx = ExecutionContext(
        ...     operand_stack=PsStack(),
        ...     execution_stack=PsStack(),
        ...     dictionary_stack=PsStack(),
        ...     graphics_state_stack=PsStack(),
        ...     userdict=PsDict(),
        ...     systemdict=PsDict(),
        ... )
        >>> ctx.dsc is None
        True
    """

    operand_stack: PsStack[PsObject]
    execution_stack: PsStack[PsObject]
    dictionary_stack: PsStack[PsDict]
    graphics_state_stack: PsStack[GraphicsState]
    userdict: PsDict
    systemdict: PsDict
    dsc: DscMetadata | None = None
    error_handler: Callable[[PsError], None] | None = None
    default_page_size: tuple[float, float] | None = None
    image_store: PsImageStore | None = None
    font_resolver: FontResolver | None = None
    charpath_mode: bool = False
    in_type3_glyph: bool = False
    text_font_overrides: dict[str, str] = field(default_factory=dict)


def _clone_path(path: Path) -> Path:
    return Path(
        [
            PathSegment(segment.kind, list(segment.points))
            for segment in path.segments
        ]
    )
