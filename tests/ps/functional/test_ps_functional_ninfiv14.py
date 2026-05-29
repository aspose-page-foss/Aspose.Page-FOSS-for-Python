import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalNINFIV14(unittest.TestCase):
    def test_ps_functional_case_ninfiv14_bbox_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/BBOX.PS"))

    def test_ps_functional_case_ninfiv14_char_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/CHAR.PS"))

    def test_ps_functional_case_ninfiv14_eps1_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/EPS1.PS"))

    def test_ps_functional_case_ninfiv14_eps2_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/EPS2.PS"))

    def test_ps_functional_case_ninfiv14_eps3_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/EPS3.PS"))

    def test_ps_functional_case_ninfiv14_error1_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/ERROR1.PS"))

    def test_ps_functional_case_ninfiv14_error2_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/ERROR2.PS"))

    def test_ps_functional_case_ninfiv14_fonts1_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/FONTS1.PS"))

    def test_ps_functional_case_ninfiv14_fonts2_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/FONTS2.PS"))

    def test_ps_functional_case_ninfiv14_fonts3_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/FONTS3.PS"))

    def test_ps_functional_case_ninfiv14_fonts4_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/FONTS4.PS"))

    def test_ps_functional_case_ninfiv14_fonts5_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/FONTS5.PS"))

    def test_ps_functional_case_ninfiv14_fonts6_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/FONTS6.PS"))

    def test_ps_functional_case_ninfiv14_memusage_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/MEMUSAGE.PS"))

    def test_ps_functional_case_ninfiv14_metrics_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/METRICS.PS"))

    def test_ps_functional_case_ninfiv14_struct_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/STRUCT.PS"))

    def test_ps_functional_case_ninfiv14_triangle_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/TRIANGLE.PS"))

    def test_ps_functional_case_ninfiv14_test_atan_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/test_atan.ps"))

    def test_ps_functional_case_ninfiv14_test_transform_point_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/NINFIV14/test_transform_point.ps"))


if __name__ == "__main__":
    unittest.main()
