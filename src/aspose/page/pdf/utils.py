"""PDF serialization helpers."""

from __future__ import annotations

from aspose.page.common.render_model import Matrix, Rect


def escape_pdf_string(text: str) -> str:
    """Escape special characters for a PDF literal string.

    Example:
        >>> escape_pdf_string("A (B)")
        'A \\(B\\)'
    """
    replacements = {
        "\\": "\\\\",
        "(": "\\(",
        ")": "\\)",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        "\b": "\\b",
        "\f": "\\f",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def format_matrix(matrix: Matrix) -> str:
    """Format a matrix for PDF content streams.

    Example:
        >>> format_matrix(Matrix.identity())
        '1 0 0 1 0 0'
    """
    return " ".join(_format_number(value) for value in (matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f))


def format_rect(rect: Rect) -> str:
    """Format a rectangle for PDF dictionaries.

    Example:
        >>> format_rect(Rect(0, 0, 10, 20))
        '0 0 10 20'
    """
    return " ".join(
        _format_number(value) for value in (rect.x_min, rect.y_min, rect.x_max, rect.y_max)
    )


def _format_number(value: float) -> str:
    if abs(value) < 1e-12:
        return "0"
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return str(int(rounded))
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text
