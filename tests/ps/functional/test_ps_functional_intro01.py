import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalINTRO01(unittest.TestCase):
    def test_ps_functional_case_intro01_circle_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/CIRCLE.PS"))

    def test_ps_functional_case_intro01_clipping_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/CLIPPING.PS"))

    def test_ps_functional_case_intro01_color_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/COLOR.PS"))

    def test_ps_functional_case_intro01_crest_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/CREST.PS"))

    def test_ps_functional_case_intro01_ellipse1_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/ELLIPSE1.PS"))

    def test_ps_functional_case_intro01_ellipse2_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/ELLIPSE2.PS"))

    def test_ps_functional_case_intro01_filledz_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/FILLEDZ.PS"))

    def test_ps_functional_case_intro01_fonts_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/FONTS.PS"))

    def test_ps_functional_case_intro01_gstates_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/GSTATES.PS"))

    def test_ps_functional_case_intro01_halftone_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/HALFTONE.PS"))

    def test_ps_functional_case_intro01_opaque_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/OPAQUE.PS"))

    def test_ps_functional_case_intro01_path1_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/PATH1.PS"))

    def test_ps_functional_case_intro01_path2_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/PATH2.PS"))

    def test_ps_functional_case_intro01_path3_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/PATH3.PS"))

    def test_ps_functional_case_intro01_path4_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/PATH4.PS"))

    def test_ps_functional_case_intro01_pattern_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/PATTERN.PS"))

    def test_ps_functional_case_intro01_ps_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/PS.PS"))

    def test_ps_functional_case_intro01_pscube_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/PSCUBE.PS"))

    def test_ps_functional_case_intro01_ps_sign_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/PS_SIGN.PS"))

    def test_ps_functional_case_intro01_showmsg1_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/SHOWMSG1.PS"))

    def test_ps_functional_case_intro01_showmsg2_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/SHOWMSG2.PS"))

    def test_ps_functional_case_intro01_showmsg3_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/SHOWMSG3.PS"))

    def test_ps_functional_case_intro01_triangl1_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/TRIANGL1.PS"))

    def test_ps_functional_case_intro01_triangl2_ps_24(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/TRIANGL2.PS"))

    def test_ps_functional_case_intro01_triangl3_ps_25(self):
        run_ps_functional_case(Path("testdata/ps/functional/INTRO01/TRIANGL3.PS"))


if __name__ == "__main__":
    unittest.main()
