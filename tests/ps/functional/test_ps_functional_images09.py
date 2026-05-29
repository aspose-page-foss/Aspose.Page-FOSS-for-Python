import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalIMAGES09(unittest.TestCase):
    def test_ps_functional_case_images09_dict1_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/DICT1.PS"))

    def test_ps_functional_case_images09_dict2_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/DICT2.PS"))

    def test_ps_functional_case_images09_dict3_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/DICT3.PS"))

    def test_ps_functional_case_images09_filters1_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/FILTERS1.PS"))

    def test_ps_functional_case_images09_filters2_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/FILTERS2.PS"))

    def test_ps_functional_case_images09_imgmask1_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/IMGMASK1.PS"))

    def test_ps_functional_case_images09_imgmask2_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/IMGMASK2.PS"))

    def test_ps_functional_case_images09_imgmask3_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/IMGMASK3.PS"))

    def test_ps_functional_case_images09_imgmask4_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/IMGMASK4.PS"))

    def test_ps_functional_case_images09_imgmask5_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/IMGMASK5.PS"))

    def test_ps_functional_case_images09_shuimg1_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/SHUIMG1.PS"))

    def test_ps_functional_case_images09_shuimg2_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/SHUIMG2.PS"))

    def test_ps_functional_case_images09_sigma_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/SIGMA.PS"))

    def test_ps_functional_case_images09_pagejava_242_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/PAGEJAVA-242.ps"))

    def test_ps_functional_case_images09_pagejava_95_12_image_ps_15(self):
        run_ps_functional_case(
            Path("testdata/ps/functional/IMAGES09/PAGEJAVA-95-12-image.ps")
        )

    def test_ps_functional_case_images09_pagenet_673_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/PAGENET-673.ps"))

    def test_ps_functional_case_images09_testimages_eps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/TestImages.eps"))

    def test_ps_functional_case_images09_wired_06_eps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/IMAGES09/wired_06.eps"))

if __name__ == "__main__":
    unittest.main()
