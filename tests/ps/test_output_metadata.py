import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.dsc import DscMetadata, parse_dsc_comments
from aspose.page.ps.document import PsDocument
from aspose.page.ps.output import ImageSaveOptions, PdfSaveOptions, build_pdf_metadata, to_image, to_pdf
from aspose.page.ps.page_geometry import page_size_from_dsc


class DummyRasterWriter:
    def __init__(self) -> None:
        self.last_document = None
        self.last_options = None

    def write(self, document, options):
        self.last_document = document
        self.last_options = options
        return b"dummy-image"


class TestMetadataOutput(unittest.TestCase):
    def test_parse_creator(self):
        data = b"%%Creator: ExampleApp\n"
        meta = parse_dsc_comments(data)
        self.assertEqual(meta.creator, "ExampleApp")

    def test_page_size_prefers_cropbox_and_orientation(self):
        dsc = DscMetadata(
            bounding_box=(0, 0, 100, 200),
            hires_bounding_box=(0.0, 0.0, 120.0, 240.0),
            crop_box=(0, 0, 50, 150),
            document_media_size=(612.0, 792.0),
            orientation="Landscape",
        )
        width, height = page_size_from_dsc(dsc)
        self.assertEqual((width, height), (150.0, 50.0))

    def test_page_size_uses_document_media_when_available(self):
        dsc = DscMetadata(
            bounding_box=(36, 61, 577, 757),
            document_media_size=(612.0, 792.0),
        )
        width, height = page_size_from_dsc(dsc)
        self.assertEqual((width, height), (612.0, 792.0))

    def test_build_pdf_metadata(self):
        dsc = DscMetadata(title="Title", creator="Creator")
        meta = build_pdf_metadata(dsc)
        self.assertEqual(meta.title, "Title")
        self.assertEqual(meta.creator, "Creator")
        self.assertEqual(meta.producer, "Aspose.Page FOSS for Python")
        self.assertFalse(meta.trapped)

    def test_no_compression_flag(self):
        doc = PsDocument.from_bytes(b"%!PS\n")
        pdf = to_pdf(doc, PdfSaveOptions(no_compression=True))
        self.assertNotIn(b"/Filter /FlateDecode", pdf)

    def test_to_image_uses_raster_writer(self):
        doc = PsDocument.from_bytes(b"%!PS\n")
        writer = DummyRasterWriter()
        options = ImageSaveOptions(format="png", raster_writer=writer)
        data = to_image(doc, options)
        self.assertEqual(data, b"dummy-image")
        self.assertIsNotNone(writer.last_document)

    def test_pdf_contains_title_creator(self):
        data = b"%!PS-Adobe-3.0 EPSF-3.0\n%%Title: Sample\n%%Creator: Tool\n"
        doc = PsDocument.from_bytes(data)
        pdf = to_pdf(doc, PdfSaveOptions(no_compression=True))
        self.assertIn(b"/Title (Sample)", pdf)
        self.assertIn(b"/Creator (Tool)", pdf)


if __name__ == "__main__":
    unittest.main()
