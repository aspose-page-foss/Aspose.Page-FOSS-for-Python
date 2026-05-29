import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalFONTS10(unittest.TestCase):
    def test_ps_functional_case_fonts10_circle_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/CIRCLE.PS"))

    def test_ps_functional_case_fonts10_clock_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/CLOCK.PS"))

    def test_ps_functional_case_fonts10_cmposite_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/CMPOSITE.PS"))

    def test_ps_functional_case_fonts10_cmposite1_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/CMPOSITE1.PS"))

    def test_ps_functional_case_fonts10_cmap_with_ttf_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/CMap_with_TTF.ps"))

    def test_ps_functional_case_fonts10_cmap_with_ttf2_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/CMap_with_TTF2.ps"))

    def test_ps_functional_case_fonts10_hand1_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/HAND1.PS"))

    def test_ps_functional_case_fonts10_hand2_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/HAND2.PS"))

    def test_ps_functional_case_fonts10_kern1_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/KERN1.PS"))

    def test_ps_functional_case_fonts10_kern2_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/KERN2.PS"))

    def test_ps_functional_case_fonts10_kern3_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/KERN3.PS"))

    def test_ps_functional_case_fonts10_oneeach_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/ONEEACH.PS"))

    def test_ps_functional_case_fonts10_pscript_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/PSCRIPT.PS"))

    def test_ps_functional_case_fonts10_scrbble1_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/SCRBBLE1.PS"))

    def test_ps_functional_case_fonts10_scrbble2_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/SCRBBLE2.PS"))

    def test_ps_functional_case_fonts10_super1_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/SUPER1.PS"))

    def test_ps_functional_case_fonts10_super2_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/SUPER2.PS"))

    def test_ps_functional_case_fonts10_truetype_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/TrueType.ps"))

    def test_ps_functional_case_fonts10_symbol_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/symbol.ps"))

    def test_ps_functional_case_fonts10_zapfdingbats_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/zapfdingbats.ps"))

    def test_ps_functional_case_fonts10_pagejava_295_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/FONTS10/PAGEJAVA-295.ps"))


if __name__ == "__main__":
    unittest.main()
