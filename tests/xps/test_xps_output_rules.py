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
from aspose.page.xps.output import to_image, to_images
from aspose.page.xps.output import to_pdf
from aspose.page.image.skia_raster_writer import SkiaRasterWriter


MB03_PATH = Path("testdata/xps/integration/mb03.xps")


class _FakeSkiaWriter(SkiaRasterWriter):
    def write(self, document, options):  # type: ignore[override]
        return b"png"


class _CountingFakeSkiaWriter(SkiaRasterWriter):
    def __init__(self) -> None:
        super().__init__()
        self.page_widths: list[float] = []

    def write(self, document, options):  # type: ignore[override]
        self.page_widths.append(document.pages[0].width)
        return f"png-{len(self.page_widths)}".encode("ascii")


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

    def test_to_images_writes_one_image_per_fixed_page(self) -> None:
        doc = XpsDocument.from_file("testdata/xps/integration/BadColor.xps")
        writer = _CountingFakeSkiaWriter()
        options = ImageSaveOptions(format="png", dpi=96, raster_writer=writer)
        with patch("aspose.page.xps.output.skia_available", return_value=True):
            data = to_images(doc, options)
        self.assertEqual(data, [b"png-1", b"png-2", b"png-3"])
        self.assertEqual(len(writer.page_widths), 3)
        self.assertTrue(all(width == writer.page_widths[0] for width in writer.page_widths))

    def test_xps_embedded_font_uses_type0_when_character_set_exceeds_simple_font_limit(self) -> None:
        doc = XpsDocument.from_file("testdata/xps/integration/OSHARED-36877.xps")

        from aspose.page.common.render_model import RenderModelBuilder
        from aspose.page.xps.images import XpsImageStore
        from aspose.page.xps.parser import XpsParser
        from aspose.page.xps.render import XpsRenderer

        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(doc.package)
        for part in XpsParser(doc.package).fixed_page_parts():
            renderer.set_current_part(part)
            renderer.render_fixed_page(doc.package.read(part))
        render_doc = builder.document()
        resolver = _build_xps_font_resolver(doc.package, render_doc)

        target_ref = "/Resources/d4d6ef8f-9a15-4a9d-aea8-273954df915f.ODTTF"
        target_codes = set(range(0x21, 0x21 + 300))
        embedded = build_embedded_font(target_ref, target_codes, resolver)
        self.assertIsNotNone(embedded)
        assert embedded is not None
        self.assertEqual(embedded.subtype, "Type0")
        self.assertEqual(embedded.encoding, "Identity-H")
        self.assertEqual(embedded.code_byte_width, 2)
        self.assertIsNotNone(embedded.cid_to_gid_map)

    def test_xps_indices_glyph_ids_are_preserved_in_page_one_render_commands(self) -> None:
        doc = XpsDocument.from_file("testdata/xps/integration/OSHARED-36877.xps")

        from aspose.page.common.render_model import RenderModelBuilder
        from aspose.page.xps.images import XpsImageStore
        from aspose.page.xps.parser import XpsParser
        from aspose.page.xps.render import XpsRenderer

        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(doc.package)
        first_part = XpsParser(doc.package).fixed_page_parts()[0]
        renderer.set_current_part(first_part)
        renderer.render_fixed_page(doc.package.read(first_part))
        page = builder.document().pages[0]
        glyph_commands = [
            command for command in page.commands
            if getattr(command, "font_ref", "").startswith("/Resources/d4d6ef8f-9a15-4a9d-aea8-273954df915f.ODTTF#gid=")
        ]
        self.assertTrue(glyph_commands)
        self.assertTrue(any(command.glyph_id == 281 for command in glyph_commands))
        self.assertTrue(any(command.text == "T" for command in glyph_commands))


if __name__ == "__main__":
    unittest.main()
