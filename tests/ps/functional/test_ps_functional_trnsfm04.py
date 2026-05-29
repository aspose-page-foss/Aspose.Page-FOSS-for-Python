import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalTRNSFM04(unittest.TestCase):
    def test_ps_functional_case_trnsfm04_ctm_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/CTM.PS"))

    def test_ps_functional_case_trnsfm04_cube1_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/CUBE1.PS"))

    def test_ps_functional_case_trnsfm04_cube2_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/CUBE2.PS"))

    def test_ps_functional_case_trnsfm04_cube3_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/CUBE3.PS"))

    def test_ps_functional_case_trnsfm04_cube4_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/CUBE4.PS"))

    def test_ps_functional_case_trnsfm04_cube5_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/CUBE5.PS"))

    def test_ps_functional_case_trnsfm04_cube6_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/CUBE6.PS"))

    def test_ps_functional_case_trnsfm04_cube7_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/CUBE7.PS"))

    def test_ps_functional_case_trnsfm04_diamond1_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/DIAMOND1.PS"))

    def test_ps_functional_case_trnsfm04_diamond2_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/DIAMOND2.PS"))

    def test_ps_functional_case_trnsfm04_flip1_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/FLIP1.PS"))

    def test_ps_functional_case_trnsfm04_flip2_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/FLIP2.PS"))

    def test_ps_functional_case_trnsfm04_intro_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/INTRO.PS"))

    def test_ps_functional_case_trnsfm04_order1_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/ORDER1.PS"))

    def test_ps_functional_case_trnsfm04_order2_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/ORDER2.PS"))

    def test_ps_functional_case_trnsfm04_order3_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/ORDER3.PS"))

    def test_ps_functional_case_trnsfm04_order4_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/ORDER4.PS"))

    def test_ps_functional_case_trnsfm04_rotate1_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/ROTATE1.PS"))

    def test_ps_functional_case_trnsfm04_rotate2_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/ROTATE2.PS"))

    def test_ps_functional_case_trnsfm04_rotate3_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/ROTATE3.PS"))

    def test_ps_functional_case_trnsfm04_scale_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/SCALE.PS"))

    def test_ps_functional_case_trnsfm04_shear1_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/SHEAR1.PS"))

    def test_ps_functional_case_trnsfm04_shear2_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/SHEAR2.PS"))

    def test_ps_functional_case_trnsfm04_shear3_ps_24(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/SHEAR3.PS"))

    def test_ps_functional_case_trnsfm04_shear4_ps_25(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/SHEAR4.PS"))

    def test_ps_functional_case_trnsfm04_shear5_ps_26(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/SHEAR5.PS"))

    def test_ps_functional_case_trnsfm04_strkadj1_ps_27(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/STRKADJ1.PS"))

    def test_ps_functional_case_trnsfm04_strkadj2_ps_28(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/STRKADJ2.PS"))

    def test_ps_functional_case_trnsfm04_strkadj3_ps_29(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/STRKADJ3.PS"))

    def test_ps_functional_case_trnsfm04_strkadj4_ps_30(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/STRKADJ4.PS"))

    def test_ps_functional_case_trnsfm04_translt1_ps_31(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/TRANSLT1.PS"))

    def test_ps_functional_case_trnsfm04_translt2_ps_32(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/TRANSLT2.PS"))

    def test_ps_functional_case_trnsfm04_translt3_ps_33(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/TRANSLT3.PS"))

    def test_ps_functional_case_trnsfm04_triangle_ps_34(self):
        run_ps_functional_case(Path("testdata/ps/functional/TRNSFM04/TRIANGLE.PS"))


if __name__ == "__main__":
    unittest.main()
