import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import (
    Matrix,
    Paint,
    Rect,
    PathCommand,
    RenderDocument,
    RenderPage,
    StrokeStyle,
    TextCommand,
    rect_path,
)
from aspose.page.pdf.writer import PdfMetadata, PdfWriter


class TestPdfWriter(unittest.TestCase):
    def setUp(self):
        self.metadata = PdfMetadata(
            title="",
            creator="",
            producer="Aspose.Page FOSS for Python",
            creation_date="D:20260101000000",
            mod_date="D:20260101000000",
            trapped=False,
        )

    def test_pdf_header(self):
        doc = RenderDocument([RenderPage(100, 100, [])])
        pdf = PdfWriter(self.metadata).write(doc)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))

    def test_rect_path_serialization_uses_path_ops(self):
        path = rect_path(Rect(0, 0, 10, 20))
        stroke = StrokeStyle(1.0, 0, 0, 10.0, [], 0.0)
        paint = Paint("DeviceRGB", (0, 0, 0))
        page = RenderPage(100, 100, [PathCommand(path=path, stroke=stroke, fill=paint)])
        pdf = PdfWriter(self.metadata, no_compression=True).write(RenderDocument([page]))
        content = _first_stream(pdf)
        self.assertIn(b" m", content)
        self.assertIn(b" l", content)
        self.assertIn(b"\nh\n", content)
        self.assertNotIn(b" re", content)

    def test_no_compression_disables_filter(self):
        doc = RenderDocument([RenderPage(100, 100, [])])
        pdf = PdfWriter(self.metadata, no_compression=True).write(doc)
        self.assertNotIn(b"/Filter /FlateDecode", pdf)

    def test_trailer_keyword_present(self):
        doc = RenderDocument([RenderPage(100, 100, [])])
        pdf = PdfWriter(self.metadata).write(doc)
        self.assertIn(b"trailer\n<<", pdf)

    def test_text_rendering_emits_text_ops(self):
        text = TextCommand(
            text="Hi",
            font_ref="Helvetica",
            font_size=12.0,
            matrix=Matrix.identity(),
            fill=Paint("DeviceGray", 0.0),
        )
        page = RenderPage(100, 100, [text])
        pdf = PdfWriter(self.metadata, no_compression=True).write(RenderDocument([page]))
        content = _first_stream(pdf)
        self.assertIn(b"BT", content)
        self.assertIn(b"ET", content)
        self.assertIn(b"Tf", content)
        self.assertIn(b"Tj", content)

    def test_missing_image_provider_raises(self):
        from aspose.page.common.render_model import ImageCommand

        image = ImageCommand("img1", 10, 10, Matrix.identity())
        page = RenderPage(100, 100, [image])
        with self.assertRaises(ValueError):
            PdfWriter(self.metadata).write(RenderDocument([page]))

    def test_overprint_path_serialization(self):
        path = rect_path(Rect(0, 0, 10, 20))
        stroke = StrokeStyle(1.0, 0, 0, 10.0, [], 0.0)
        paint = Paint("DeviceCMYK", (0.0, 1.0, 0.0, 0.0))
        page = RenderPage(
            100,
            100,
            [
                PathCommand(
                    path=path,
                    stroke=stroke,
                    fill=paint,
                    overprint=True,
                )
            ],
        )
        pdf = PdfWriter(self.metadata, no_compression=True).write(RenderDocument([page]))
        content = _first_stream(pdf)
        self.assertIn(b"true op", content)
        self.assertIn(b"true OP", content)
        self.assertIn(b"false op", content)
        self.assertIn(b"false OP", content)

    def test_cmyk_paint_serializes_as_rgb_ops(self):
        path = rect_path(Rect(0, 0, 10, 20))
        page = RenderPage(
            100,
            100,
            [PathCommand(path=path, stroke=None, fill=Paint("DeviceCMYK", (1.0, 0.0, 1.0, 0.0)))],
        )
        pdf = PdfWriter(self.metadata, no_compression=True).write(RenderDocument([page]))
        content = _first_stream(pdf)
        self.assertIn(b"0 1 0 rg", content)
        self.assertNotIn(b" k", content)


def _first_stream(pdf_bytes: bytes) -> bytes:
    marker = b"stream\n"
    start = pdf_bytes.find(marker)
    if start == -1:
        return b""
    start += len(marker)
    end = pdf_bytes.find(b"\nendstream", start)
    return pdf_bytes[start:end]


if __name__ == "__main__":
    unittest.main()
