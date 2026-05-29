import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalFORMS12(unittest.TestCase):
    def test_ps_functional_case_forms12_domino_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/FORMS12/DOMINO.PS"))

    def test_ps_functional_case_forms12_llabs1_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/FORMS12/LLABS1.PS"))

    def test_ps_functional_case_forms12_llabs2_ps_3(self):
        run_ps_functional_case(Path("testdata/ps/functional/FORMS12/LLABS2.PS"))

    def test_ps_functional_case_forms12_llabs3_ps_4(self):
        run_ps_functional_case(Path("testdata/ps/functional/FORMS12/LLABS3.PS"))

    def test_ps_functional_case_forms12_llabs4_ps_5(self):
        run_ps_functional_case(Path("testdata/ps/functional/FORMS12/LLABS4.PS"))

    def test_ps_functional_case_forms12_rolodex_ps_6(self):
        run_ps_functional_case(Path("testdata/ps/functional/FORMS12/ROLODEX.PS"))


if __name__ == "__main__":
    unittest.main()
