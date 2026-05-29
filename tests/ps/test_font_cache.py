import sys
from pathlib import Path
import shutil
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.font_cache import FontCache


class TestFontCache(unittest.TestCase):
    def test_find_font_prefers_additional_folder(self) -> None:
        resources = Path(__file__).resolve().parents[2] / "resources"
        regular_src = resources / "LiberationSerif-Regular.ttf"
        bold_italic_src = resources / "LiberationSerif-BoldItalic.ttf"
        if not regular_src.exists() or not bold_italic_src.exists():
            self.skipTest("font resources not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            regular = tmp / "UnitTestFont-Regular.ttf"
            bold_italic = tmp / "UnitTestFont-BoldItalic.ttf"
            optima_regular = tmp / "Optima.ttf"
            optima_bold = tmp / "Optima_B.ttf"
            shutil.copyfile(regular_src, regular)
            shutil.copyfile(bold_italic_src, bold_italic)
            shutil.copyfile(regular_src, optima_regular)
            shutil.copyfile(regular_src, optima_bold)

            cache = FontCache()
            cache.load(tmpdir)

            record = cache.find_font("UnitTestFont", None)
            self.assertIsNotNone(record)
            self.assertTrue(record.path.samefile(regular))
            self.assertEqual(record.style, "Regular")

            record_bi = cache.find_font("UnitTestFont-BoldItalic", None)
            self.assertIsNotNone(record_bi)
            self.assertTrue(record_bi.path.samefile(bold_italic))
            self.assertEqual(record_bi.style, "BoldItalic")

            optima_record = cache.find_font("Optima-Bold", None)
            self.assertIsNotNone(optima_record)
            self.assertTrue(optima_record.path.samefile(optima_bold))
            self.assertEqual(optima_record.style, "Bold")

            fallback = cache.find_font("UnitTestFontTypo", None)
            self.assertIsNotNone(fallback)

    def test_metrics_for_returns_widths(self) -> None:
        resources = Path(__file__).resolve().parents[2] / "resources"
        regular_src = resources / "LiberationSerif-Regular.ttf"
        if not regular_src.exists():
            self.skipTest("font resources not available")
        cache = FontCache()
        cache.load(None)
        metrics = cache.metrics_for(regular_src)
        self.assertGreater(metrics.units_per_em, 0)
        self.assertTrue(metrics.code_widths)


if __name__ == "__main__":
    unittest.main()
