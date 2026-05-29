import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import aspose.page.ps.output  # noqa: F401 - keep import order cycle-safe
from aspose.page.image.raster_renderer import GlyphPoint, _glyph_contours_need_even_odd


def _cw_square(x0: float, y0: float, x1: float, y1: float) -> list[GlyphPoint]:
    return [
        GlyphPoint(x0, y0, True),
        GlyphPoint(x1, y0, True),
        GlyphPoint(x1, y1, True),
        GlyphPoint(x0, y1, True),
    ]


def _ccw_square(x0: float, y0: float, x1: float, y1: float) -> list[GlyphPoint]:
    return [
        GlyphPoint(x0, y0, True),
        GlyphPoint(x0, y1, True),
        GlyphPoint(x1, y1, True),
        GlyphPoint(x1, y0, True),
    ]


class TestGlyphFillPolicy(unittest.TestCase):
    def test_same_winding_contours_enable_evenodd(self) -> None:
        contours = [
            _cw_square(0, 0, 1000, 1000),
            _cw_square(250, 250, 750, 750),
        ]
        self.assertTrue(_glyph_contours_need_even_odd(contours))

    def test_opposite_winding_contours_keep_nonzero(self) -> None:
        contours = [
            _cw_square(0, 0, 1000, 1000),
            _ccw_square(250, 250, 750, 750),
        ]
        self.assertFalse(_glyph_contours_need_even_odd(contours))

    def test_single_contour_keeps_nonzero(self) -> None:
        contours = [_cw_square(0, 0, 1000, 1000)]
        self.assertFalse(_glyph_contours_need_even_odd(contours))

if __name__ == "__main__":
    unittest.main()
