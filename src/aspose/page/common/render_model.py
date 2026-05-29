"""Render model shared across conversion outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import time
from typing import Union

from .color_resources import ColorSpace, Function, Pattern

@dataclass(frozen=True)
class Point:
    """2D point in the render model.

    Example:
        >>> Point(1.0, 2.0)
        Point(x=1.0, y=2.0)
    """

    x: float
    y: float


@dataclass(frozen=True)
class Matrix:
    """Affine transform matrix (a, b, c, d, e, f).

    Example:
        >>> Matrix.identity()
        Matrix(a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0)
    """

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @staticmethod
    def identity() -> "Matrix":
        return Matrix(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle with min/max coordinates.

    Example:
        >>> Rect(0, 0, 10, 20).x_max
        10
    """

    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True)
class PathSegment:
    """A path segment with a kind and control points.

    Example:
        >>> PathSegment("line", [Point(1, 2)]).kind
        'line'
    """

    kind: str
    points: list[Point]


@dataclass
class Path:
    """A sequence of path segments.

    Example:
        >>> Path([PathSegment("move", [Point(0, 0)])]).segments[0].kind
        'move'
    """

    segments: list[PathSegment]


@dataclass(frozen=True)
class StrokeStyle:
    """Stroke style settings for path rendering.

    Example:
        >>> StrokeStyle(1.0, 0, 0, 10.0, [], 0.0).line_width
        1.0
    """

    line_width: float
    line_cap: int
    line_join: int
    miter_limit: float
    dash: list[float]
    dash_phase: float


@dataclass(frozen=True)
class Paint:
    """Fill/stroke paint descriptor.

    Example:
        >>> Paint("DeviceRGB", (0, 0, 0)).kind
        'DeviceRGB'
    """

    kind: str
    value: object


@dataclass(frozen=True)
class PathCommand:
    """Render a path with optional stroke/fill.

    Example:
        >>> PathCommand(Path([]), None, None).path.segments
        []
    """

    path: Path
    stroke: StrokeStyle | None
    fill: Paint | None
    fill_rule: str = "nonzero"
    stroke_paint: Paint | None = None
    overprint: bool = False
    fill_opacity: float = 1.0
    stroke_opacity: float = 1.0


@dataclass(frozen=True)
class TextCommand:
    """Render text using a font reference and transform.

    Example:
        >>> TextCommand("Hi", "Helvetica", 12.0, Matrix.identity(), None).text
        'Hi'
    """

    text: str
    font_ref: str
    font_size: float
    matrix: Matrix
    fill: Paint | None
    fill_opacity: float = 1.0


@dataclass(frozen=True)
class ImageCommand:
    """Render an image resource with a transform.

    Example:
        >>> ImageCommand("img1", 10, 10, Matrix.identity()).image_id
        'img1'
    """

    image_id: str
    width: int
    height: int
    matrix: Matrix
    mask: bool = False
    mask_paint: Paint | None = None
    opacity: float = 1.0


@dataclass(frozen=True)
class ClipCommand:
    """Set the current clipping path.

    Example:
        >>> ClipCommand(Path([])).path.segments
        []
    """

    path: Path
    fill_rule: str = "nonzero"


@dataclass(frozen=True)
class StateSaveCommand:
    """Save the current graphics state."""

    pass


@dataclass(frozen=True)
class StateRestoreCommand:
    """Restore the previous graphics state."""

    pass


RenderCommand = Union[
    PathCommand,
    TextCommand,
    ImageCommand,
    ClipCommand,
    StateSaveCommand,
    StateRestoreCommand,
]


@dataclass
class RenderPage:
    """A single renderable page with commands.

    Example:
        >>> RenderPage(100, 200).width
        100
    """

    width: float
    height: float
    commands: list[RenderCommand] = field(default_factory=list)


@dataclass
class RenderDocument:
    """A collection of render pages.

    Example:
        >>> RenderDocument().pages
        []
    """

    pages: list[RenderPage] = field(default_factory=list)
    resources: "RenderResources" = field(default_factory=lambda: RenderResources())


@dataclass
class RenderResources:
    """Shared render resources for a document."""

    color_spaces: dict[str, ColorSpace] = field(default_factory=dict)
    patterns: dict[str, Pattern] = field(default_factory=dict)
    functions: dict[str, Function] = field(default_factory=dict)
    images: dict[str, "RenderImageResource"] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderImageResource:
    """Image payload used by raster backends."""

    data: bytes
    width: int
    height: int
    color_space: str
    bits_per_component: int
    filter: str | None = None
    filter_params: dict | None = None
    decode: tuple[float, ...] | None = None
    mask: bool = False
    mask_polarity: bool = True


def rect_path(rect: Rect) -> Path:
    """Create a rectangular path from a rectangle.

    Example:
        >>> rect_path(Rect(0, 0, 1, 1)).segments[-1].kind
        'close'
    """
    segments = [
        PathSegment("move", [Point(rect.x_min, rect.y_min)]),
        PathSegment("line", [Point(rect.x_max, rect.y_min)]),
        PathSegment("line", [Point(rect.x_max, rect.y_max)]),
        PathSegment("line", [Point(rect.x_min, rect.y_max)]),
        PathSegment("close", []),
    ]
    return Path(segments)

class RenderModelBuilder:
    """Build render documents incrementally.

    Example:
        >>> builder = RenderModelBuilder()
        >>> builder.set_default_page_size(100, 200)
        >>> builder.add_path(rect_path(Rect(0, 0, 1, 1)), None, None)
        >>> len(builder.document().pages)
        1
    """

    def __init__(self) -> None:
        self._document = RenderDocument()
        self._default_page_size: tuple[float, float] | None = None
        self._active_page: RenderPage | None = None
        self._color_space_prefix = "CS"
        self._pattern_prefix = "P"
        self._function_prefix = "F"

    def set_default_page_size(self, width: float, height: float) -> None:
        """Set the default page size for implicit page creation."""
        self._default_page_size = (width, height)

    def begin_page(self, width: float, height: float) -> None:
        """Begin a new page with explicit size."""
        if self._active_page is not None:
            raise ValueError("page already active")
        self._active_page = RenderPage(width=width, height=height)

    def end_page(self) -> None:
        """End the current page and append it to the document."""
        if self._active_page is None:
            raise ValueError("no active page")
        self._document.pages.append(self._active_page)
        self._active_page = None

    def add_path(
        self,
        path: Path,
        stroke: StrokeStyle | None,
        fill: Paint | None,
        fill_rule: str = "nonzero",
        stroke_paint: Paint | None = None,
        overprint: bool = False,
        fill_opacity: float = 1.0,
        stroke_opacity: float = 1.0,
    ) -> None:
        """Add a path render command to the current page."""
        self._ensure_page()
        trace_enabled = os.getenv("PS_TEXT_TRACE") == "1"
        trace_slow_ms = 0.0
        if trace_enabled:
            try:
                trace_slow_ms = float(os.getenv("PS_TEXT_TRACE_SLOW_MS", "0") or 0.0)
            except ValueError:
                trace_slow_ms = 0.0
        start_time = time.perf_counter() if (trace_enabled and trace_slow_ms) else 0.0
        self._active_page.commands.append(
            PathCommand(
                path=path,
                stroke=stroke,
                fill=fill,
                fill_rule=fill_rule,
                stroke_paint=stroke_paint,
                overprint=overprint,
                fill_opacity=fill_opacity,
                stroke_opacity=stroke_opacity,
            )
        )
        if trace_enabled and trace_slow_ms:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            if elapsed_ms >= trace_slow_ms:
                print(
                    "PS TEXT TRACE slow add_path ms={:.2f} segments={}".format(
                        elapsed_ms,
                        len(path.segments),
                    ),
                    flush=True,
                )

    def add_text(
        self,
        text: str,
        font_ref: str,
        font_size: float,
        matrix: Matrix,
        fill: Paint | None,
    ) -> None:
        """Add a text render command to the current page."""
        self._ensure_page()
        self._active_page.commands.append(
            TextCommand(text=text, font_ref=font_ref, font_size=font_size, matrix=matrix, fill=fill)
        )

    def add_image(
        self,
        image_id: str,
        width: int,
        height: int,
        matrix: Matrix,
        mask: bool = False,
        mask_paint: Paint | None = None,
    ) -> None:
        """Add an image render command to the current page."""
        self._ensure_page()
        self._active_page.commands.append(
            ImageCommand(
                image_id=image_id,
                width=width,
                height=height,
                matrix=matrix,
                mask=mask,
                mask_paint=mask_paint,
            )
        )

    def clip(self, path: Path, fill_rule: str = "nonzero") -> None:
        """Add a clipping path command to the current page."""
        self._ensure_page()
        self._active_page.commands.append(ClipCommand(path=path, fill_rule=fill_rule))

    def save_state(self) -> None:
        """Save the current graphics state."""
        self._ensure_page()
        self._active_page.commands.append(StateSaveCommand())

    def restore_state(self) -> None:
        """Restore the previous graphics state."""
        self._ensure_page()
        self._active_page.commands.append(StateRestoreCommand())

    def document(self) -> RenderDocument:
        """Return the current render document."""
        if self._active_page is not None:
            self._document.pages.append(self._active_page)
            self._active_page = None
        return self._document

    def register_color_space(self, color_space: ColorSpace) -> str:
        """Register a color space resource and return its ID."""
        return _register_resource(
            self._document.resources.color_spaces, color_space, self._color_space_prefix
        )

    def register_pattern(self, pattern: Pattern) -> str:
        """Register a pattern resource and return its ID."""
        return _register_resource(self._document.resources.patterns, pattern, self._pattern_prefix)

    def register_function(self, function: Function) -> str:
        """Register a function resource and return its ID."""
        return _register_resource(self._document.resources.functions, function, self._function_prefix)

    def _ensure_page(self) -> None:
        if self._active_page is not None:
            return
        if self._default_page_size is None:
            raise ValueError("default page size not set")
        width, height = self._default_page_size
        self.begin_page(width, height)


def _register_resource(mapping: dict[str, object], value: object, prefix: str) -> str:
    for key, existing in mapping.items():
        if existing == value:
            return key
    resource_id = f"{prefix}{len(mapping) + 1}"
    mapping[resource_id] = value
    return resource_id
