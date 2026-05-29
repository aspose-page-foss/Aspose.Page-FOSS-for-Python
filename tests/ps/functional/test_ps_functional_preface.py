import unittest
from pathlib import Path

from tests.ps.functional.ps_functional_common import (
    FUNCTIONAL_RUN_ENABLED,
    run_ps_functional_case,
)


@unittest.skipUnless(FUNCTIONAL_RUN_ENABLED, "Functional tests disabled")
class TestPsFunctionalPREFACE(unittest.TestCase):
    def test_ps_functional_case_preface_club_ps_1(self):
        run_ps_functional_case(Path("testdata/ps/functional/PREFACE/CLUB.PS"))

    def test_ps_functional_case_preface_supers_ps_2(self):
        run_ps_functional_case(Path("testdata/ps/functional/PREFACE/SUPERS.PS"))


if __name__ == "__main__":
    unittest.main()
