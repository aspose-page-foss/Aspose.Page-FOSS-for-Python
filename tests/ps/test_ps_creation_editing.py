import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.document import PsDocument


class TestPsCreationEditing(unittest.TestCase):
    def test_create_eps_includes_bounding_box(self):
        doc = PsDocument.create(is_eps=True, page_size=(200.0, 100.0))
        data = doc.save()
        text = data.decode("latin-1")
        self.assertTrue(text.startswith("%!PS-Adobe-3.0 EPSF-3.0"))
        self.assertIn("%%BoundingBox: 0 0 200 100", text)
        self.assertIn("%%Pages: 1", text)

    def test_page_add_insert_remove_updates_pages(self):
        doc = PsDocument.create(is_eps=False)
        doc.add_page((100.0, 100.0))
        doc.insert_page(1, (50.0, 50.0))
        doc.remove_page(0)
        data = doc.save()
        text = data.decode("latin-1")
        self.assertIn("%%Pages: 2", text)
        self.assertEqual(text.count("%%Page:"), 2)

    def test_draw_path_and_text_appends_operators(self):
        doc = PsDocument.create(is_eps=True, page_size=(100.0, 100.0))
        page = doc.get_page(0)
        canvas = page.canvas
        canvas.move_to(0, 0)
        canvas.line_to(10, 0)
        canvas.stroke()
        canvas.draw_text("Hello", 5, 5, "Helvetica", 12)
        self.assertIn("moveto", page.content[0])
        self.assertTrue(any("show" in line for line in page.content))

    def test_edit_existing_eps_preserves_content(self):
        data = (
            b"%!PS-Adobe-3.0 EPSF-3.0\n"
            b"%%BoundingBox: 0 0 10 10\n"
            b"%%Pages: 1\n"
            b"%%Page: 1 1\n"
            b"10 10 moveto\n"
            b"%%Trailer\n"
            b"%%EOF\n"
        )
        doc = PsDocument.from_bytes(data)
        out = doc.save().decode("latin-1")
        self.assertIn("10 10 moveto", out)
        self.assertIn("%%Pages: 1", out)
        self.assertEqual(out.count("%%Page:"), 1)


if __name__ == "__main__":
    unittest.main()
