import os
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

try:
    from aspose.page.xps.document import XpsDocument
except Exception:
    XpsDocument = None

from aspose.page.ps.output import ImageSaveOptions


@unittest.skipIf(XpsDocument is None, "XPS conversion not implemented (PAGE-22)")
class TestXpsRasterIntegration(unittest.TestCase):
    def test_xps_to_bmp_header(self) -> None:
        path = os.path.join("testdata", "xps", "integration", "Simple.xps")
        doc = XpsDocument.from_file(path)
        data = doc.to_image(ImageSaveOptions(format="bmp", dpi=72))
        self.assertTrue(data.startswith(b"BM"))


if __name__ == "__main__":
    unittest.main()
