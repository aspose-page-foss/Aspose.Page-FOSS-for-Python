import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.xps.document import XpsDocument


class TestXpsIntegration(unittest.TestCase):
    def test_simple_xps_to_pdf(self) -> None:
        path = Path("testdata/xps/integration/Simple.xps")
        doc = XpsDocument.from_file(str(path))
        pdf = doc.to_pdf()
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
