import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.document import PsDocument
from aspose.page.ps.xmp import extract_xmp


class TestEpsXmpMetadata(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = Path("testdata/ps/xmp/PAGENET-361-1.eps")

    def test_extract_xmp(self) -> None:
        doc = PsDocument.from_file(str(self.sample))
        xmp = doc.get_xmp()
        self.assertIsNotNone(xmp)
        self.assertIn("x:xmpmeta", xmp)

    def test_replace_xmp(self) -> None:
        doc = PsDocument.from_file(str(self.sample))
        new_xmp = "<x:xmpmeta xmlns:x='adobe:ns:meta/'></x:xmpmeta>"
        doc.set_xmp(new_xmp)
        data = doc.save()
        self.assertEqual(extract_xmp(data), new_xmp)

    def test_remove_xmp(self) -> None:
        doc = PsDocument.from_file(str(self.sample))
        doc.remove_xmp()
        data = doc.save()
        self.assertIsNone(extract_xmp(data))
        self.assertNotIn(b"x:xmpmeta", data)


if __name__ == "__main__":
    unittest.main()
