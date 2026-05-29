import os
import tempfile
from pathlib import Path
import unittest

from tests.common.compare_utils import compare_images, compare_pdfs, baseline_path_for
from tests.common.output_utils import output_path_for
from tests.common.pdf_validator import validate_pdf


class EnvGuard:
    def __init__(self, **updates):
        self._updates = updates
        self._original = {}

    def __enter__(self):
        for key, value in self._updates.items():
            self._original[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, exc_type, exc, tb):
        for key, value in self._original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TestOutputUtils(unittest.TestCase):
    def test_output_path_for(self):
        input_path = Path("testdata/ps/integration/sample.ps")
        output = output_path_for(input_path, ".pdf")
        self.assertEqual(output.as_posix(), "test-out/ps/integration/sample.pdf")


class TestBaselineMapping(unittest.TestCase):
    def test_baseline_map(self):
        with EnvGuard(BASELINE_MAP="ps/images=/tmp/baselines"):
            baseline = baseline_path_for(Path("testdata/ps/images/foo.png"), ".eps")
            self.assertEqual(baseline.as_posix(), "/tmp/baselines/foo.eps")


class TestPdfValidator(unittest.TestCase):
    def test_skip_when_missing(self):
        with EnvGuard(PDF_VALIDATOR_CMD=""):
            with self.assertRaises(unittest.SkipTest):
                validate_pdf(Path("dummy.pdf"))


class TestCompareImages(unittest.TestCase):
    def test_compare_images(self):
        try:
            from PIL import Image  # type: ignore
        except Exception:
            with EnvGuard(IMAGE_COMPARE_CMD=""):
                with self.assertRaises(unittest.SkipTest):
                    compare_images(Path("missing.png"), Path("missing.png"))
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline = Path(tmpdir) / "base.png"
            actual = Path(tmpdir) / "actual.png"
            Image.new("RGB", (4, 4), color=(10, 20, 30)).save(baseline)
            Image.new("RGB", (4, 4), color=(10, 20, 30)).save(actual)
            compare_images(baseline, actual, delta=1, ratio=0.0)


class TestComparePdfs(unittest.TestCase):
    def test_skip_without_tools(self):
        with EnvGuard(PDF_COMPARE_CMD="", PDF_RENDER_CMD=""):
            with self.assertRaises(unittest.SkipTest):
                compare_pdfs(Path("baseline.pdf"), Path("actual.pdf"))


if __name__ == "__main__":
    unittest.main()
