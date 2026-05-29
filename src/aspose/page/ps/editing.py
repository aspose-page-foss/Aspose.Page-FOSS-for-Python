"""PS/EPS creation and editing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PsImage:
    """Raster image container for embedding in PS/EPS.

    Example:
        >>> PsImage(1, 1, 8, "DeviceGray", b"\x00")
        PsImage(width=1, height=1, bits_per_component=8, color_space='DeviceGray', data=b'\x00', filter=None, decode=None)
    """

    width: int
    height: int
    bits_per_component: int
    color_space: str
    data: bytes
    filter: str | None = None
    decode: tuple[float, float] | None = None


@dataclass
class PsPage:
    """Editable PS/EPS page.

    Example:
        >>> page = PsPage(100, 200)
        >>> page.width
        100
    """

    width: float
    height: float
    content: list[str] = field(default_factory=list)
    dirty: bool = False
    canvas: "PsCanvas" = field(init=False)

    def __post_init__(self) -> None:
        self.canvas = PsCanvas(self)


class PsCanvas:
    """Canvas that appends PostScript operators to a page."""

    def __init__(self, page: PsPage) -> None:
        self._page = page

    def move_to(self, x: float, y: float) -> None:
        self._append(f"{_fmt(x)} {_fmt(y)} moveto")

    def line_to(self, x: float, y: float) -> None:
        self._append(f"{_fmt(x)} {_fmt(y)} lineto")

    def curve_to(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> None:
        self._append(
            f"{_fmt(x1)} {_fmt(y1)} {_fmt(x2)} {_fmt(y2)} {_fmt(x3)} {_fmt(y3)} curveto"
        )

    def close_path(self) -> None:
        self._append("closepath")

    def rect(self, x: float, y: float, w: float, h: float) -> None:
        self._append("newpath")
        self.move_to(x, y)
        self.line_to(x + w, y)
        self.line_to(x + w, y + h)
        self.line_to(x, y + h)
        self.close_path()

    def ellipse(self, x: float, y: float, w: float, h: float) -> None:
        cx = x + w / 2.0
        cy = y + h / 2.0
        rx = w / 2.0
        ry = h / 2.0
        self._append("matrix currentmatrix")
        self._append(f"{_fmt(cx)} {_fmt(cy)} translate")
        self._append(f"{_fmt(rx)} {_fmt(ry)} scale")
        self._append("0 0 1 0 360 arc")
        self._append("setmatrix")

    def stroke(self) -> None:
        self._append("stroke")

    def fill(self) -> None:
        self._append("fill")

    def fill_stroke(self) -> None:
        self._append("gsave")
        self._append("fill")
        self._append("grestore")
        self._append("stroke")

    def set_stroke_color(self, color: tuple[float, ...]) -> None:
        self._set_color(color)

    def set_fill_color(self, color: tuple[float, ...]) -> None:
        self._set_color(color)

    def set_line_width(self, width: float) -> None:
        self._append(f"{_fmt(width)} setlinewidth")

    def set_line_cap(self, cap: int) -> None:
        self._append(f"{cap} setlinecap")

    def set_line_join(self, join: int) -> None:
        self._append(f"{join} setlinejoin")

    def set_miter_limit(self, limit: float) -> None:
        self._append(f"{_fmt(limit)} setmiterlimit")

    def concat(self, matrix: tuple[float, float, float, float, float, float]) -> None:
        if len(matrix) != 6:
            raise ValueError("concat matrix must have 6 elements")
        values = " ".join(_fmt(value) for value in matrix)
        self._append(f"[{values}] concat")

    def save_state(self) -> None:
        self._append("gsave")

    def restore_state(self) -> None:
        self._append("grestore")

    def clip(self) -> None:
        self._append("clip")
        self._append("newpath")

    def init_clip(self) -> None:
        self._append("initclip")

    def draw_text(self, text: str, x: float, y: float, font_name: str, size: float) -> None:
        escaped = _escape_text(text)
        self._append(f"/{font_name} findfont {_fmt(size)} scalefont setfont")
        self._append(f"{_fmt(x)} {_fmt(y)} moveto")
        self._append(f"({escaped}) show")

    def draw_image(self, image: PsImage, x: float, y: float, w: float, h: float) -> None:
        components = _color_components(image.color_space)
        if image.bits_per_component % 8 != 0:
            raise ValueError("bits_per_component must be a multiple of 8")
        expected = image.width * image.height * components * (image.bits_per_component // 8)
        if len(image.data) != expected:
            raise ValueError("image data size mismatch")
        self._append("gsave")
        self._append(f"{_fmt(x)} {_fmt(y)} translate")
        self._append(f"{_fmt(w)} {_fmt(h)} scale")
        self._append(
            f"{image.width} {image.height} {image.bits_per_component} "
            f"[{image.width} 0 0 -{image.height} 0 {image.height}]"
        )
        hex_data = image.data.hex()
        if components == 1:
            self._append(f"{{<{hex_data}>}} image")
        else:
            self._append(f"{{<{hex_data}>}} false {components} colorimage")
        self._append("grestore")

    def _set_color(self, color: tuple[float, ...]) -> None:
        if len(color) == 1:
            self._append(f"{_fmt(color[0])} setgray")
        elif len(color) == 3:
            self._append(f"{_fmt(color[0])} {_fmt(color[1])} {_fmt(color[2])} setrgbcolor")
        elif len(color) == 4:
            self._append(
                f"{_fmt(color[0])} {_fmt(color[1])} {_fmt(color[2])} {_fmt(color[3])} setcmykcolor"
            )
        else:
            raise ValueError("unsupported color tuple length")

    def _append(self, line: str) -> None:
        self._page.dirty = True
        self._page.content.append(line)


def _color_components(color_space: str) -> int:
    if color_space == "DeviceGray":
        return 1
    if color_space == "DeviceRGB":
        return 3
    if color_space == "DeviceCMYK":
        return 4
    raise ValueError("unsupported color space")


def _fmt(value: float) -> str:
    if float(int(value)) == float(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _escape_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
