import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalPTRNS11(unittest.TestCase):
    def test_ps_functional_case_ptrns11_4inst_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/PTRNS11/4INST.PS"))

    def test_ps_functional_case_ptrns11_astroid_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/PTRNS11/ASTROID.PS"))

    def test_ps_functional_case_ptrns11_circle_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/PTRNS11/CIRCLE.PS"))

    def test_ps_functional_case_ptrns11_duck1_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/PTRNS11/DUCK1.PS"))

    def test_ps_functional_case_ptrns11_duck2_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/PTRNS11/DUCK2.PS"))

    def test_ps_functional_case_ptrns11_duck3_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/PTRNS11/DUCK3.PS"))

    def test_ps_functional_case_ptrns11_heart1_ps_7(self):
        run_ps_functional_case(Path("testdata/ps/functional/PTRNS11/HEART1.PS"))

    def test_ps_functional_case_ptrns11_heart2_ps_8(self):
        run_ps_functional_case(Path("testdata/ps/functional/PTRNS11/HEART2.PS"))


if __name__ == "__main__":
    unittest.main()
