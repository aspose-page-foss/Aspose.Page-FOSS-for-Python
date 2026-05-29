import os
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.document import PsDocument
from aspose.page.ps.output import ImageSaveOptions


class TestPsRasterIntegration(unittest.TestCase):
    def test_ps_to_png_header(self) -> None:
        path = os.path.join("testdata", "ps", "integration", "minimal.ps")
        doc = PsDocument.from_file(path)
        data = doc.to_image(ImageSaveOptions(format="png", dpi=72))
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
