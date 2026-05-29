import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalPATHS02(unittest.TestCase):
    def test_ps_functional_case_paths02_cube_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/CUBE.PS"))

    def test_ps_functional_case_paths02_fill1_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FILL1.PS"))

    def test_ps_functional_case_paths02_fill2_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FILL2.PS"))

    def test_ps_functional_case_paths02_fill3_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FILL3.PS"))

    def test_ps_functional_case_paths02_fill4_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FILL4.PS"))

    def test_ps_functional_case_paths02_fill5_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FILL5.PS"))

    def test_ps_functional_case_paths02_fill6_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FILL6.PS"))

    def test_ps_functional_case_paths02_fill7_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FILL7.PS"))

    def test_ps_functional_case_paths02_fill8_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FILL8.PS"))

    def test_ps_functional_case_paths02_fllrule1_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FLLRULE1.PS"))

    def test_ps_functional_case_paths02_fllrule2_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FLLRULE2.PS"))

    def test_ps_functional_case_paths02_fllrule3_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FLLRULE3.PS"))

    def test_ps_functional_case_paths02_fllrule4_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/FLLRULE4.PS"))

    def test_ps_functional_case_paths02_hitdetct_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/HITDETCT.PS"))

    def test_ps_functional_case_paths02_order1_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/ORDER1.PS"))

    def test_ps_functional_case_paths02_order2_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/ORDER2.PS"))

    def test_ps_functional_case_paths02_rect1_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECT1.PS"))

    def test_ps_functional_case_paths02_rect2_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECT2.PS"))

    def test_ps_functional_case_paths02_rect3_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECT3.PS"))

    def test_ps_functional_case_paths02_rect4_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECT4.PS"))

    def test_ps_functional_case_paths02_rect5_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECT5.PS"))

    def test_ps_functional_case_paths02_rect6_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECT6.PS"))

    def test_ps_functional_case_paths02_rect7_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECT7.PS"))

    def test_ps_functional_case_paths02_rectem1_ps_24(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECTEM1.PS"))

    def test_ps_functional_case_paths02_rectem2_ps_25(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECTEM2.PS"))

    def test_ps_functional_case_paths02_rectem3_ps_26(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECTEM3.PS"))

    def test_ps_functional_case_paths02_rectem4_ps_27(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECTEM4.PS"))

    def test_ps_functional_case_paths02_rectfll1_ps_28(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECTFLL1.PS"))

    def test_ps_functional_case_paths02_rectfll2_ps_29(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECTFLL2.PS"))

    def test_ps_functional_case_paths02_rectfll3_ps_30(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECTFLL3.PS"))

    def test_ps_functional_case_paths02_rectfll4_ps_31(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECTFLL4.PS"))

    def test_ps_functional_case_paths02_rectfll5_ps_32(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/RECTFLL5.PS"))

    def test_ps_functional_case_paths02_square_ps_33(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/SQUARE.PS"))

    def test_ps_functional_case_paths02_stroke1_ps_34(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/STROKE1.PS"))

    def test_ps_functional_case_paths02_triangl1_ps_35(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/TRIANGL1.PS"))

    def test_ps_functional_case_paths02_triangl2_ps_36(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/TRIANGL2.PS"))

    def test_ps_functional_case_paths02_triangl3_ps_37(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/TRIANGL3.PS"))

    def test_ps_functional_case_paths02_usrpath1_ps_38(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/USRPATH1.PS"))

    def test_ps_functional_case_paths02_usrpath2_ps_39(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/USRPATH2.PS"))

    def test_ps_functional_case_paths02_usrpath3_ps_40(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/USRPATH3.PS"))

    def test_ps_functional_case_paths02_usrpath4_ps_41(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/USRPATH4.PS"))

    def test_ps_functional_case_paths02_usrpath5_ps_42(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/USRPATH5.PS"))

    def test_ps_functional_case_paths02_usrpath6_ps_43(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/USRPATH6.PS"))

    def test_ps_functional_case_paths02_usrpath7_ps_44(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/USRPATH7.PS"))

    def test_ps_functional_case_paths02_usrpath8_ps_45(self):
        run_ps_functional_case(Path("testdata/ps/functional/PATHS02/USRPATH8.PS"))


if __name__ == "__main__":
    unittest.main()
