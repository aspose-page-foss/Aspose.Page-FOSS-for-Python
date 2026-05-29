import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.type1_parser import (
    parse_type1_charstring_width,
    parse_type1_resource_block,
)


def _encrypt_charstring(plain: bytes) -> bytes:
    r = 4330
    out = bytearray()
    for value in plain:
        cipher = value ^ (r >> 8)
        out.append(cipher)
        r = ((cipher + r) * 52845 + 22719) & 0xFFFF
    return bytes(out)


class TestType1Parser(unittest.TestCase):
    def test_parse_type1_charstring_width_hsbw(self):
        # lenIV(4) + hsbw(0, 500) + endchar
        plain = bytes([0, 0, 0, 0, 139, 248, 136, 13, 14])
        encrypted = _encrypt_charstring(plain)
        width = parse_type1_charstring_width(encrypted, len_iv=4)
        self.assertEqual(width, 500.0)

    def test_parse_type1_resource_block_from_pagejava(self):
        path = Path("testdata/ps/functional/FONTS10/PAGEJAVA-295.ps")
        data = path.read_bytes()
        start = data.find(b"%%BeginResource: font (ArialMT)")
        end = data.find(b"%%EndResource", start)
        self.assertGreaterEqual(start, 0)
        self.assertGreater(end, start)
        block = data[start:end + len(b"%%EndResource")]
        metrics = parse_type1_resource_block(block)
        self.assertIsNotNone(metrics)
        assert metrics is not None
        self.assertEqual(metrics.font_name, "ArialMT")
        self.assertGreater(metrics.units_per_em, 0)
        self.assertIn(65, metrics.code_widths)
        self.assertGreater(metrics.code_widths[65], 0.0)


if __name__ == "__main__":
    unittest.main()
