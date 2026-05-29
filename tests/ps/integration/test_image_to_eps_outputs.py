import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from aspose.page.ps import convert_image_to_eps

from tests.common.output_utils import write_output


IMAGE_ROOT = Path("testdata/ps/images")
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


@unittest.skipUnless(os.getenv("RUN_INTEGRATION") == "1", "Integration tests disabled")
class TestImageToEpsOutputs(unittest.TestCase):
    def test_image_to_eps_outputs(self):
        for path in sorted(IMAGE_ROOT.iterdir()):
            if path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            with self.subTest(input=path.name):
                eps_bytes = convert_image_to_eps(str(path))
                write_output(path, ".eps", eps_bytes)


if __name__ == "__main__":
    unittest.main()
