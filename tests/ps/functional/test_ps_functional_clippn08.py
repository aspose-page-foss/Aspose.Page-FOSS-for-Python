import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalCLIPPN08(unittest.TestCase):
    def test_ps_functional_case_clippn08_bbox1_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/BBOX1.PS"))

    def test_ps_functional_case_clippn08_bbox2_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/BBOX2.PS"))

    def test_ps_functional_case_clippn08_bbox3_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/BBOX3.PS"))

    def test_ps_functional_case_clippn08_bbox4_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/BBOX4.PS"))

    def test_ps_functional_case_clippn08_bbox5_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/BBOX5.PS"))

    def test_ps_functional_case_clippn08_borro_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/BORRO.PS"))

    def test_ps_functional_case_clippn08_clip1_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/CLIP1.PS"))

    def test_ps_functional_case_clippn08_clip2_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/CLIP2.PS"))

    def test_ps_functional_case_clippn08_clip3_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/CLIP3.PS"))

    def test_ps_functional_case_clippn08_clip4_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/CLIP4.PS"))

    def test_ps_functional_case_clippn08_clip5_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/CLIP5.PS"))

    def test_ps_functional_case_clippn08_clip6_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/CLIP6.PS"))

    def test_ps_functional_case_clippn08_fill_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/FILL.PS"))

    def test_ps_functional_case_clippn08_flatten_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/FLATTEN.PS"))

    def test_ps_functional_case_clippn08_initial_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/INITIAL.PS"))

    def test_ps_functional_case_clippn08_intersct_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/INTERSCT.PS"))

    def test_ps_functional_case_clippn08_outside1_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/OUTSIDE1.PS"))

    def test_ps_functional_case_clippn08_outside2_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/OUTSIDE2.PS"))

    def test_ps_functional_case_clippn08_outside3_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/OUTSIDE3.PS"))

    def test_ps_functional_case_clippn08_pentagon_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/PENTAGON.PS"))

    def test_ps_functional_case_clippn08_plyback1_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/PLYBACK1.PS"))

    def test_ps_functional_case_clippn08_plyback2_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/PLYBACK2.PS"))

    def test_ps_functional_case_clippn08_rect_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/RECT.PS"))

    def test_ps_functional_case_clippn08_star_ps_24(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/STAR.PS"))

    def test_ps_functional_case_clippn08_stroke1_ps_25(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/STROKE1.PS"))

    def test_ps_functional_case_clippn08_stroke2_ps_26(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/STROKE2.PS"))

    def test_ps_functional_case_clippn08_stroke3_ps_27(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/STROKE3.PS"))

    def test_ps_functional_case_clippn08_zstep1_ps_28(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/ZSTEP1.PS"))

    def test_ps_functional_case_clippn08_zstep2_ps_29(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/ZSTEP2.PS"))

    def test_ps_functional_case_clippn08_zstep3_ps_30(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/ZSTEP3.PS"))

    def test_ps_functional_case_clippn08_zstep4_ps_31(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/ZSTEP4.PS"))

    def test_ps_functional_case_clippn08_zstep5_ps_32(self):
        run_ps_functional_case(Path("testdata/ps/functional/CLIPPN08/ZSTEP5.PS"))


if __name__ == "__main__":
    unittest.main()
