import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps import convert_image_to_eps
from aspose.page.ps.image_to_eps import (
    decode_bmp,
    decode_jpeg,
    decode_png,
    decode_tiff,
)

IMAGE_DIR = Path(__file__).resolve().parents[2] / "testdata" / "ps" / "images"
DECODERS = {
    ".png": decode_png,
    ".jpg": decode_jpeg,
    ".jpeg": decode_jpeg,
    ".tif": decode_tiff,
    ".tiff": decode_tiff,
    ".bmp": decode_bmp,
}


class TestImageToEps(unittest.TestCase):
    def test_convert_images(self):
        for path in sorted(IMAGE_DIR.iterdir()):
            decoder = DECODERS.get(path.suffix.lower())
            if decoder is None:
                continue
            with self.subTest(image=path.name):
                info = decoder(path.read_bytes())
                eps = convert_image_to_eps(str(path))
                text = eps.decode("latin-1")
                self.assertTrue(text.startswith("%!PS-Adobe-3.0 EPSF-3.0"))
                bbox = _parse_bbox(text)
                self.assertEqual(bbox, (0, 0, info.width, info.height))
                if info.color_space == "DeviceRGB":
                    self.assertIn("colorimage", text)
                else:
                    self.assertIn(" image", text)


def _parse_bbox(text: str) -> tuple[int, int, int, int]:
    for line in text.splitlines():
        if line.startswith("%%BoundingBox:"):
            parts = line.split()
            return tuple(int(float(value)) for value in parts[1:5])
    raise AssertionError("BoundingBox not found")


if __name__ == "__main__":
    unittest.main()
