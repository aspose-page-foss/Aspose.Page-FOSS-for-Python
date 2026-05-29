import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalARCS07(unittest.TestCase):
    def test_ps_functional_case_arcs07_arc_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/ARC.PS"))

    def test_ps_functional_case_arcs07_arct_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/ARCT.PS"))

    def test_ps_functional_case_arcs07_arcto1_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/ARCTO1.PS"))

    def test_ps_functional_case_arcs07_arcto2_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/ARCTO2.PS"))

    def test_ps_functional_case_arcs07_arcto3_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/ARCTO3.PS"))

    def test_ps_functional_case_arcs07_arcto4_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/ARCTO4.PS"))

    def test_ps_functional_case_arcs07_arcto5_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/ARCTO5.PS"))

    def test_ps_functional_case_arcs07_bigarcs1_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/BIGARCS1.PS"))

    def test_ps_functional_case_arcs07_bigarcs2_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/BIGARCS2.PS"))

    def test_ps_functional_case_arcs07_bigarcs3_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/BIGARCS3.PS"))

    def test_ps_functional_case_arcs07_circle1_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CIRCLE1.PS"))

    def test_ps_functional_case_arcs07_circle2_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CIRCLE2.PS"))

    def test_ps_functional_case_arcs07_clock1_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CLOCK1.PS"))

    def test_ps_functional_case_arcs07_clock2_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CLOCK2.PS"))

    def test_ps_functional_case_arcs07_clock3_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CLOCK3.PS"))

    def test_ps_functional_case_arcs07_clock4_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CLOCK4.PS"))

    def test_ps_functional_case_arcs07_clock5_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CLOCK5.PS"))

    def test_ps_functional_case_arcs07_clock6_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CLOCK6.PS"))

    def test_ps_functional_case_arcs07_curveto1_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CURVETO1.PS"))

    def test_ps_functional_case_arcs07_curveto2_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CURVETO2.PS"))

    def test_ps_functional_case_arcs07_curveto3_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CURVETO3.PS"))

    def test_ps_functional_case_arcs07_curveto4_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CURVETO4.PS"))

    def test_ps_functional_case_arcs07_cusp1_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CUSP1.PS"))

    def test_ps_functional_case_arcs07_cusp2_ps_24(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CUSP2.PS"))

    def test_ps_functional_case_arcs07_cusp3_ps_25(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/CUSP3.PS"))

    def test_ps_functional_case_arcs07_family_ps_26(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/FAMILY.PS"))

    def test_ps_functional_case_arcs07_heart1_ps_27(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/HEART1.PS"))

    def test_ps_functional_case_arcs07_heart2_ps_28(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/HEART2.PS"))

    def test_ps_functional_case_arcs07_hull_ps_29(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/HULL.PS"))

    def test_ps_functional_case_arcs07_pacman_ps_30(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/PACMAN.PS"))

    def test_ps_functional_case_arcs07_piechart_ps_31(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/PIECHART.PS"))

    def test_ps_functional_case_arcs07_rcurveto_ps_32(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/RCURVETO.PS"))

    def test_ps_functional_case_arcs07_spots1_ps_33(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/SPOTS1.PS"))

    def test_ps_functional_case_arcs07_spots2_ps_34(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/SPOTS2.PS"))

    def test_ps_functional_case_arcs07_spots3_ps_35(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/SPOTS3.PS"))

    def test_ps_functional_case_arcs07_vary1_ps_36(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/VARY1.PS"))

    def test_ps_functional_case_arcs07_vary2_ps_37(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/VARY2.PS"))

    def test_ps_functional_case_arcs07_vary3_ps_38(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/VARY3.PS"))

    def test_ps_functional_case_arcs07_vary4_ps_39(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/VARY4.PS"))

    def test_ps_functional_case_arcs07_vary5_ps_40(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/VARY5.PS"))

    def test_ps_functional_case_arcs07_vary6_ps_41(self):
        run_ps_functional_case(Path("testdata/ps/functional/ARCS07/VARY6.PS"))


if __name__ == "__main__":
    unittest.main()
