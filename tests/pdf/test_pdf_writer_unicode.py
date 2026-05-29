import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import Matrix, RenderModelBuilder
from aspose.page.pdf.writer import PdfMetadata, PdfWriter


class TestPdfWriterUnicode(unittest.TestCase):
    def test_unicode_text_does_not_crash(self) -> None:
        builder = RenderModelBuilder()
        builder.begin_page(100, 100)
        builder.add_text("Привет 漢字", "Helvetica", 12, Matrix.identity(), None)
        builder.end_page()
        doc = builder.document()
        metadata = PdfMetadata(
            title="",
            creator="",
            producer="Aspose.Page FOSS for Python",
            creation_date="D:20240101000000",
            mod_date="D:20240101000000",
            trapped=False,
        )
        writer = PdfWriter(metadata)
        data = writer.write(doc)
        self.assertTrue(data.startswith(b"%PDF-1.4"))


if __name__ == "__main__":
    unittest.main()
