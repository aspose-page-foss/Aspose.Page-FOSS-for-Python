from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.output import ImageSaveOptions
from aspose.page.ps.pdf_font_embed import build_embedded_font
from aspose.page.xps.document import XpsDocument
from aspose.page.xps.output import _build_xps_font_resolver
from aspose.page.xps.output import to_image
from aspose.page.xps.output import to_pdf
from aspose.page.image.skia_raster_writer import SkiaRasterWriter


MB03_PATH = Path("testdata/xps/integration/mb03.xps")


class _FakeSkiaWriter(SkiaRasterWriter):
    def write(self, document, options):  # type: ignore[override]
        return b"png"


class TestXpsOutputRules(unittest.TestCase):
    def test_to_pdf_embeds_xps_embedded_fonts(self) -> None:
        doc = XpsDocument.from_file(str(MB03_PATH))
        pdf = to_pdf(doc)
        self.assertIn(b"/FontFile2", pdf)

    def test_xps_font_resolver_registers_embedded_fonts(self) -> None:
        doc = XpsDocument.from_file(str(MB03_PATH))
        pdf = to_pdf(doc)
        self.assertIn(b"/FontFile2", pdf)

        from aspose.page.common.render_model import RenderModelBuilder
        from aspose.page.xps.images import XpsImageStore
        from aspose.page.xps.parser import XpsParser
        from aspose.page.xps.render import XpsRenderer

        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(doc.package)
        parser = XpsParser(doc.package)
        for part in parser.fixed_page_parts():
            renderer.set_current_part(part)
            renderer.render_fixed_page(doc.package.read(part))
        render_doc = builder.document()
        resolver = _build_xps_font_resolver(doc.package, render_doc)

        embedded = resolver.get_embedded_type42("/Resources/arial.ttf")
        self.assertIsNotNone(embedded)
        font = build_embedded_font("/Resources/arial.ttf", {ord("A"), ord("r")}, resolver)
        self.assertIsNotNone(font)

    def test_to_image_requires_skia(self) -> None:
        doc = XpsDocument.from_file(str(MB03_PATH))
        with patch("aspose.page.xps.output.skia_available", return_value=False):
            with self.assertRaises(RuntimeError):
                to_image(doc, ImageSaveOptions(format="png", dpi=96))

    def test_to_image_uses_skia_writer_and_font_resolver(self) -> None:
        doc = XpsDocument.from_file(str(MB03_PATH))
        options = ImageSaveOptions(format="png", dpi=96, raster_writer=_FakeSkiaWriter())
        with patch("aspose.page.xps.output.skia_available", return_value=True):
            data = to_image(doc, options)
        self.assertEqual(data, b"png")
        self.assertIsNotNone(options.font_resolver)
        assert options.font_resolver is not None
        self.assertIsNotNone(options.font_resolver.get_embedded_type42("/Resources/arial.ttf"))


if __name__ == "__main__":
    unittest.main()
