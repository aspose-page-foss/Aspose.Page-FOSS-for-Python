import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalLANG05(unittest.TestCase):
    def test_ps_functional_case_lang05_beach_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/BEACH.PS"))

    def test_ps_functional_case_lang05_binding1_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/BINDING1.PS"))

    def test_ps_functional_case_lang05_binding2_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/BINDING2.PS"))

    def test_ps_functional_case_lang05_binding3_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/BINDING3.PS"))

    def test_ps_functional_case_lang05_clrmark1_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/CLRMARK1.PS"))

    def test_ps_functional_case_lang05_clrmark2_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/CLRMARK2.PS"))

    def test_ps_functional_case_lang05_dictstk1_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/DICTSTK1.PS"))

    def test_ps_functional_case_lang05_dictstk2_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/DICTSTK2.PS"))

    def test_ps_functional_case_lang05_forall_ps_9(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/FORALL.PS"))

    def test_ps_functional_case_lang05_forloop1_ps_10(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/FORLOOP1.PS"))

    def test_ps_functional_case_lang05_forloop2_ps_11(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/FORLOOP2.PS"))

    def test_ps_functional_case_lang05_getintvl_ps_12(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/GETINTVL.PS"))

    def test_ps_functional_case_lang05_hanoi_ps_13(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/HANOI.PS"))

    def test_ps_functional_case_lang05_hello_ps_14(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/HELLO.PS"))

    def test_ps_functional_case_lang05_honk_ps_15(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/HONK.PS"))

    def test_ps_functional_case_lang05_if_ps_16(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/IF.PS"))

    def test_ps_functional_case_lang05_ifelse_ps_17(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/IFELSE.PS"))

    def test_ps_functional_case_lang05_known1_ps_18(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/KNOWN1.PS"))

    def test_ps_functional_case_lang05_known2_ps_19(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/KNOWN2.PS"))

    def test_ps_functional_case_lang05_names_ps_20(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/NAMES.PS"))

    def test_ps_functional_case_lang05_octagon1_ps_21(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/OCTAGON1.PS"))

    def test_ps_functional_case_lang05_octagon2_ps_22(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/OCTAGON2.PS"))

    def test_ps_functional_case_lang05_parmesan_ps_23(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/PARMESAN.PS"))

    def test_ps_functional_case_lang05_pop_ps_24(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/POP.PS"))

    def test_ps_functional_case_lang05_proc1_ps_25(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/PROC1.PS"))

    def test_ps_functional_case_lang05_proc2_ps_26(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/PROC2.PS"))

    def test_ps_functional_case_lang05_proc3_ps_27(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/PROC3.PS"))

    def test_ps_functional_case_lang05_proc4_ps_28(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/PROC4.PS"))

    def test_ps_functional_case_lang05_put_ps_29(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/PUT.PS"))

    def test_ps_functional_case_lang05_putintvl_ps_30(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/PUTINTVL.PS"))

    def test_ps_functional_case_lang05_reclaim1_ps_31(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/RECLAIM1.PS"))

    def test_ps_functional_case_lang05_reclaim2_ps_32(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/RECLAIM2.PS"))

    def test_ps_functional_case_lang05_repeat_ps_33(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/REPEAT.PS"))

    def test_ps_functional_case_lang05_roll_ps_34(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/ROLL.PS"))

    def test_ps_functional_case_lang05_shuimage_ps_35(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/SHUIMAGE.PS"))

    def test_ps_functional_case_lang05_trig_ps_36(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/TRIG.PS"))

    def test_ps_functional_case_lang05_weird_ps_37(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/WEIRD.PS"))

    def test_ps_functional_case_lang05_where_ps_38(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/WHERE.PS"))

    def test_ps_functional_case_lang05_whilelp_ps_39(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/WHILELP.PS"))

    def test_ps_functional_case_lang05_wines1_ps_40(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/WINES1.PS"))

    def test_ps_functional_case_lang05_wines2_ps_41(self):
        run_ps_functional_case(Path("testdata/ps/functional/LANG05/WINES2.PS"))


if __name__ == "__main__":
    unittest.main()
