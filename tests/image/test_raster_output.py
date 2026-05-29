import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import (
    Paint,
    PathCommand,
    RenderDocument,
    RenderPage,
    Rect,
    rect_path,
)
from aspose.page.image.encoders import encode_bmp, encode_jpeg, encode_png
from aspose.page.image.raster_renderer import RasterRenderer


class TestRasterRenderer(unittest.TestCase):
    def test_render_size_respects_dpi(self) -> None:
        doc = RenderDocument()
        page = RenderPage(width=72, height=72)
        page.commands.append(
            PathCommand(
                path=rect_path(Rect(0, 0, 72, 72)),
                stroke=None,
                fill=Paint("DeviceRGB", (1.0, 0.0, 0.0)),
            )
        )
        doc.pages.append(page)
        surface_72 = RasterRenderer(dpi=72).render(doc)
        surface_144 = RasterRenderer(dpi=144).render(doc)
        self.assertEqual(surface_72.width, 72)
        self.assertEqual(surface_72.height, 72)
        self.assertEqual(surface_144.width, 144)
        self.assertEqual(surface_144.height, 144)

    def test_encode_png_and_bmp_signatures(self) -> None:
        doc = RenderDocument()
        doc.pages.append(RenderPage(width=8, height=8))
        surface = RasterRenderer(dpi=72).render(doc)
        png = encode_png(surface)
        bmp = encode_bmp(surface)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(bmp.startswith(b"BM"))

    def test_encode_jpeg_non_empty(self) -> None:
        doc = RenderDocument()
        doc.pages.append(RenderPage(width=8, height=8))
        surface = RasterRenderer(dpi=72).render(doc)
        jpeg = encode_jpeg(surface)
        self.assertTrue(jpeg.startswith(b"\xFF\xD8"))
        self.assertGreater(len(jpeg), 4)


if __name__ == "__main__":
    unittest.main()
