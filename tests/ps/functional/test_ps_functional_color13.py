import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalCOLOR13(unittest.TestCase):
    def test_ps_functional_case_color13_arrays_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/ARRAYS.PS"))

    def test_ps_functional_case_color13_bright_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/BRIGHT.PS"))

    def test_ps_functional_case_color13_cie_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/CIE.PS"))

    def test_ps_functional_case_color13_cmyk1_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/CMYK1.PS"))

    def test_ps_functional_case_color13_cmyk2_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/CMYK2.PS"))

    def test_ps_functional_case_color13_gray1_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/GRAY1.PS"))

    def test_ps_functional_case_color13_gray2_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/GRAY2.PS"))

    def test_ps_functional_case_color13_hilights_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/HILIGHTS.PS"))

    def test_ps_functional_case_color13_hsb_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/HSB.PS"))

    def test_ps_functional_case_color13_hsbcone_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/HSBCONE.PS"))

    def test_ps_functional_case_color13_hue_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/HUE.PS"))

    def test_ps_functional_case_color13_hueval_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/HUEVAL.PS"))

    def test_ps_functional_case_color13_midtones_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/MIDTONES.PS"))

    def test_ps_functional_case_color13_ovrprnt1_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/OVRPRNT1.PS"))

    def test_ps_functional_case_color13_ovrprnt2_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/OVRPRNT2.PS"))

    def test_ps_functional_case_color13_rgb1_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/RGB1.PS"))

    def test_ps_functional_case_color13_rgb2_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/RGB2.PS"))

    def test_ps_functional_case_color13_rgbcube_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/RGBCUBE.PS"))

    def test_ps_functional_case_color13_rosettes_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/ROSETTES.PS"))

    def test_ps_functional_case_color13_saturatn_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/SATURATN.PS"))

    def test_ps_functional_case_color13_separate_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/SEPARATE.PS"))

    def test_ps_functional_case_color13_shadows_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/SHADOWS.PS"))

    def test_ps_functional_case_color13_spot_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/SPOT.PS"))

    def test_ps_functional_case_color13_trap1_ps_24(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/TRAP1.PS"))

    def test_ps_functional_case_color13_trap2_ps_25(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/TRAP2.PS"))

    def test_ps_functional_case_color13_ucr1_ps_26(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/UCR1.PS"))

    def test_ps_functional_case_color13_ucr2_ps_27(self):
        run_ps_functional_case(Path("testdata/ps/functional/COLOR13/UCR2.PS"))


if __name__ == "__main__":
    unittest.main()
