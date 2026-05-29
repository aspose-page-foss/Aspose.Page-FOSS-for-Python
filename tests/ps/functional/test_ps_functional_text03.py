import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalTEXT03(unittest.TestCase):
    def test_ps_functional_case_text03_beethovn_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/BEETHOVN.PS"))

    def test_ps_functional_case_text03_bizcard_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/BIZCARD.PS"))

    def test_ps_functional_case_text03_centtext_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/CENTTEXT.PS"))

    def test_ps_functional_case_text03_chezpier_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/CHEZPIER.PS"))

    def test_ps_functional_case_text03_eggs_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/EGGS.PS"))

    def test_ps_functional_case_text03_fadein1_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/FADEIN1.PS"))

    def test_ps_functional_case_text03_fadein2_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/FADEIN2.PS"))

    def test_ps_functional_case_text03_fadeout_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/FADEOUT.PS"))

    def test_ps_functional_case_text03_fontres_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/FONTRES.PS"))

    def test_ps_functional_case_text03_gtnberg1_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/GTNBERG1.PS"))

    def test_ps_functional_case_text03_gtnberg2_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/GTNBERG2.PS"))

    def test_ps_functional_case_text03_gtnberg3_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/GTNBERG3.PS"))

    def test_ps_functional_case_text03_intro_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/INTRO.PS"))

    def test_ps_functional_case_text03_joplin_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/JOPLIN.PS"))

    def test_ps_functional_case_text03_lakewd1_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/LAKEWD1.PS"))

    def test_ps_functional_case_text03_lakewd2_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/LAKEWD2.PS"))

    def test_ps_functional_case_text03_lakewd3_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/LAKEWD3.PS"))

    def test_ps_functional_case_text03_lakewd4_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/LAKEWD4.PS"))

    def test_ps_functional_case_text03_lefttext_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/LEFTTEXT.PS"))

    def test_ps_functional_case_text03_marker1_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/MARKER1.PS"))

    def test_ps_functional_case_text03_marker2_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/MARKER2.PS"))

    def test_ps_functional_case_text03_marker3_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/MARKER3.PS"))

    def test_ps_functional_case_text03_p1_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/P1.PS"))

    def test_ps_functional_case_text03_p2_ps_24(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/P2.PS"))

    def test_ps_functional_case_text03_p3_ps_25(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/P3.PS"))

    def test_ps_functional_case_text03_pith_ps_26(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/PITH.PS"))

    def test_ps_functional_case_text03_planet_ps_27(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/PLANET.PS"))

    def test_ps_functional_case_text03_pscript1_ps_28(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/PSCRIPT1.PS"))

    def test_ps_functional_case_text03_pscript2_ps_29(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/PSCRIPT2.PS"))

    def test_ps_functional_case_text03_pscript3_ps_30(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/PSCRIPT3.PS"))

    def test_ps_functional_case_text03_pscript4_ps_31(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/PSCRIPT4.PS"))

    def test_ps_functional_case_text03_q1_ps_32(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/Q1.PS"))

    def test_ps_functional_case_text03_q2_ps_33(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/Q2.PS"))

    def test_ps_functional_case_text03_rttext_ps_34(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/RTTEXT.PS"))

    def test_ps_functional_case_text03_s1_ps_35(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/S1.PS"))

    def test_ps_functional_case_text03_s2_ps_36(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/S2.PS"))

    def test_ps_functional_case_text03_s3_ps_37(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/S3.PS"))

    def test_ps_functional_case_text03_s4_ps_38(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/S4.PS"))

    def test_ps_functional_case_text03_serpent_ps_39(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/SERPENT.PS"))

    def test_ps_functional_case_text03_strings_ps_40(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/STRINGS.PS"))

    def test_ps_functional_case_text03_supersub_ps_41(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/SUPERSUB.PS"))

    def test_ps_functional_case_text03_z1_ps_42(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/Z1.PS"))

    def test_ps_functional_case_text03_z2_ps_43(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/Z2.PS"))

    def test_ps_functional_case_text03_z3_ps_44(self):
        run_ps_functional_case(Path("testdata/ps/functional/TEXT03/Z3.PS"))


if __name__ == "__main__":
    unittest.main()
