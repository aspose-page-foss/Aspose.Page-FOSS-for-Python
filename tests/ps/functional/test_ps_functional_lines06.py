import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalLINES06(unittest.TestCase):
    def test_ps_functional_case_lines06_bevljn1_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/BEVLJN1.PS"))

    def test_ps_functional_case_lines06_bevljn2_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/BEVLJN2.PS"))

    def test_ps_functional_case_lines06_buttcap1_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/BUTTCAP1.PS"))

    def test_ps_functional_case_lines06_buttcap2_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/BUTTCAP2.PS"))

    def test_ps_functional_case_lines06_dasharc1_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/DASHARC1.PS"))

    def test_ps_functional_case_lines06_dasharc2_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/DASHARC2.PS"))

    def test_ps_functional_case_lines06_dashed1_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/DASHED1.PS"))

    def test_ps_functional_case_lines06_dashed2_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/DASHED2.PS"))

    def test_ps_functional_case_lines06_dashed3_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/DASHED3.PS"))

    def test_ps_functional_case_lines06_dashed4_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/DASHED4.PS"))

    def test_ps_functional_case_lines06_dashed5_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/DASHED5.PS"))

    def test_ps_functional_case_lines06_dashed6_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/DASHED6.PS"))

    def test_ps_functional_case_lines06_dashed7_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/DASHED7.PS"))

    def test_ps_functional_case_lines06_joincap_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/JOINCAP.PS"))

    def test_ps_functional_case_lines06_miterjn1_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/MITERJN1.PS"))

    def test_ps_functional_case_lines06_miterjn2_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/MITERJN2.PS"))

    def test_ps_functional_case_lines06_mtrlimit_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/MTRLIMIT.PS"))

    def test_ps_functional_case_lines06_rndcap1_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/RNDCAP1.PS"))

    def test_ps_functional_case_lines06_rndcap2_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/RNDCAP2.PS"))

    def test_ps_functional_case_lines06_rndjoin1_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/RNDJOIN1.PS"))

    def test_ps_functional_case_lines06_rndjoin2_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/RNDJOIN2.PS"))

    def test_ps_functional_case_lines06_scaling1_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/SCALING1.PS"))

    def test_ps_functional_case_lines06_scaling2_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/SCALING2.PS"))

    def test_ps_functional_case_lines06_scaling3_ps_24(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/SCALING3.PS"))

    def test_ps_functional_case_lines06_scaling4_ps_25(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/SCALING4.PS"))

    def test_ps_functional_case_lines06_sqrcap1_ps_26(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/SQRCAP1.PS"))

    def test_ps_functional_case_lines06_sqrcap2_ps_27(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/SQRCAP2.PS"))

    def test_ps_functional_case_lines06_tricks1_ps_28(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/TRICKS1.PS"))

    def test_ps_functional_case_lines06_tricks2_ps_29(self):
        run_ps_functional_case(Path("testdata/ps/functional/LINES06/TRICKS2.PS"))


if __name__ == "__main__":
    unittest.main()
