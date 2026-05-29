import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.font_types import load_type1_font, load_type42_font
from aspose.page.ps.ttf_outline import load_ttf_font
from aspose.page.ps.objects import PsArray, PsDict, PsName, PsString


class TestFontTypes(unittest.TestCase):
    @staticmethod
    def _encrypt_type1_eexec(plain: bytes) -> bytes:
        r = 55665
        out = bytearray()
        for value in plain:
            cipher = value ^ (r >> 8)
            out.append(cipher)
            r = ((cipher + r) * 52845 + 22719) & 0xFFFF
        return bytes(out)

    @staticmethod
    def _encrypt_type1_charstring(plain: bytes) -> bytes:
        r = 4330
        out = bytearray()
        for value in plain:
            cipher = value ^ (r >> 8)
            out.append(cipher)
            r = ((cipher + r) * 52845 + 22719) & 0xFFFF
        return bytes(out)

    def test_load_type1_with_embedded_program_widths(self):
        # lenIV(4) + hsbw(0, 500) + endchar
        char_plain = bytes([0, 0, 0, 0, 139, 248, 136, 13, 14])
        char_encrypted = self._encrypt_type1_charstring(char_plain)
        private_plain = (
            b"/lenIV 4 def\n"
            + b"/CharStrings 1 dict dup begin\n"
            + b"/A "
            + str(len(char_encrypted)).encode("ascii")
            + b" RD "
            + char_encrypted
            + b" ND\n"
            + b"end\n"
        )
        eexec_payload = self._encrypt_type1_eexec(b"\x00\x00\x00\x00" + private_plain)
        encoding = [PsName(".notdef", literal=True) for _ in range(256)]
        encoding[65] = PsName("A", literal=True)
        font_dict = PsDict(
            {
                "FontName": PsName("EmbeddedType1", literal=True),
                "FontMatrix": PsArray([0.001, 0.0, 0.0, 0.001, 0.0, 0.0]),
                "Encoding": PsArray(encoding),
                "__type1_program__": PsString(eexec_payload),
            }
        )
        font = load_type1_font(font_dict)
        self.assertIn(65, font.code_widths or {})
        self.assertEqual((font.code_widths or {}).get(65), 500.0)

    def test_load_type42_from_sfnts(self):
        resources = Path(__file__).resolve().parents[2] / "resources"
        data = (resources / "LiberationSerif-Regular.ttf").read_bytes()
        font_dict = PsDict(
            {
                "FontName": "TestType42",
                "sfnts": PsArray([PsString(data)]),
            }
        )
        font = load_type42_font(font_dict)
        self.assertGreater(font.units_per_em, 0)
        self.assertTrue(font.code_widths)

    def test_load_type42_fallback_uses_embedded_hmtx_and_charstrings(self):
        resources = Path(__file__).resolve().parents[2] / "resources"
        data = (resources / "LiberationSerif-Regular.ttf").read_bytes()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "font.ttf"
            path.write_bytes(data)
            ttf = load_ttf_font(path)
        gid_a = ttf.glyph_id_for_code(ord("A"))
        encoding = [PsName(".notdef", literal=True) for _ in range(256)]
        encoding[65] = PsName("A", literal=True)
        font_dict = PsDict(
            {
                "FontName": "TestType42",
                "sfnts": PsArray([PsString(data)]),
                "Encoding": PsArray(encoding),
                "CharStrings": PsDict(
                    {
                        ".notdef": 0,
                        "A": gid_a,
                    }
                ),
            }
        )
        with patch("aspose.page.ps.font_types.parse_ttf_metrics", side_effect=RuntimeError("forced")):
            font = load_type42_font(font_dict)
        self.assertGreater(font.units_per_em, 0)
        self.assertIn(65, font.code_widths or {})
        self.assertGreater((font.code_widths or {}).get(65, 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
