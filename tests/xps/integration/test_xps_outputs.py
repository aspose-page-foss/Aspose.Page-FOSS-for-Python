import os
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from aspose.page.ps.output import ImageSaveOptions
from aspose.page.common.render_model import RenderModelBuilder
from aspose.page.xps.document import XpsDocument
from aspose.page.xps.images import XpsImageStore
from aspose.page.xps.parser import XpsParser
from aspose.page.xps.render import XpsRenderer

from tests.common.compare_utils import (
    baseline_path_for,
    compare_images_on_fail,
    compare_pdfs_on_fail,
    artifact_dir_for,
    resolve_image_baseline,
)
from tests.common.output_utils import write_output
from tests.common.pdf_validator import validate_pdf
from tests.common.render_model_dump import dump_render_model


XPS_INTEGRATION_ROOT = Path("testdata/xps/integration")
XPS_INTEGRATION_FILES = sorted(
    [path for path in XPS_INTEGRATION_ROOT.rglob("*.xps")]
)
TIMING_ENABLED = os.getenv("TEST_TIMING") == "1"
XPS_IMAGE_DPI = 300


def _log_timing(label: str, seconds: float) -> None:
    if TIMING_ENABLED:
        print(f"TIMING {label}: {seconds:.3f}s")


@unittest.skipUnless(os.getenv("RUN_INTEGRATION") == "1", "Integration tests disabled")
class TestXpsOutputs(unittest.TestCase):
    pass


def _baseline_pdf_available(baseline_pdf: Path) -> bool:
    if baseline_pdf.exists():
        return True
    if baseline_pdf.with_suffix(".png").exists():
        return True
    if baseline_pdf.with_name(baseline_pdf.name + ".png").exists():
        return True
    return baseline_pdf.with_name(f"{baseline_pdf.name}.page-1.png").exists()


def _build_render_model(doc: XpsDocument):
    builder = RenderModelBuilder()
    store = XpsImageStore()
    renderer = XpsRenderer(builder, store)
    renderer.set_package(doc.package)
    parser = XpsParser(doc.package)
    for part in parser.fixed_page_parts():
        renderer.set_current_part(part)
        renderer.render_fixed_page(doc.package.read(part))
    return builder.document()


def _run_xps_case(path: Path) -> None:
    total_start = time.perf_counter()
    load_start = time.perf_counter()
    doc = XpsDocument.from_file(str(path))
    _log_timing(f"{path.name} load", time.perf_counter() - load_start)
    render_doc = None

    def ensure_render_doc():
        nonlocal render_doc
        if render_doc is None:
            render_doc = _build_render_model(doc)
        return render_doc

    pdf_start = time.perf_counter()
    pdf_bytes = doc.to_pdf()
    _log_timing(f"{path.name} xps->pdf", time.perf_counter() - pdf_start)
    relative = path.relative_to(XPS_INTEGRATION_ROOT)
    pdf_key = Path("testdata/xps/xps2pdf/integration") / relative
    pdf_output = write_output(pdf_key, ".pdf", pdf_bytes)
    try:
        validate_start = time.perf_counter()
        validate_pdf(pdf_output)
        _log_timing(f"{path.name} pdf validate", time.perf_counter() - validate_start)
    except unittest.SkipTest as exc:
        print(f"SKIP PDF validation: {exc}")

    pdf_baseline = baseline_path_for(pdf_key, ".pdf")
    errors: list[AssertionError] = []
    if _baseline_pdf_available(pdf_baseline):
        try:
            compare_start = time.perf_counter()
            compare_pdfs_on_fail(
                pdf_baseline,
                pdf_output,
                artifact_dir=artifact_dir_for(pdf_output),
            )
            _log_timing(f"{path.name} pdf compare", time.perf_counter() - compare_start)
        except unittest.SkipTest as exc:
            print(f"SKIP PDF compare: {exc}")
        except AssertionError as exc:
            dump_render_model(
                ensure_render_doc(),
                artifact_dir_for(pdf_output) / "render_model.json",
            )
            errors.append(exc)

    image_start = time.perf_counter()
    image_bytes = doc.to_image(ImageSaveOptions(format="png", dpi=XPS_IMAGE_DPI))
    _log_timing(f"{path.name} xps->image", time.perf_counter() - image_start)
    image_key = Path("testdata/xps/xps2image/integration") / relative
    image_output = write_output(image_key, ".png", image_bytes)
    image_baseline = resolve_image_baseline(baseline_path_for(image_key, ".png"))
    if image_baseline is not None:
        try:
            compare_start = time.perf_counter()
            compare_images_on_fail(
                image_baseline,
                image_output,
                artifact_dir=artifact_dir_for(image_output),
            )
            _log_timing(
                f"{path.name} image compare", time.perf_counter() - compare_start
            )
        except unittest.SkipTest as exc:
            print(f"SKIP image compare: {exc}")
        except AssertionError as exc:
            dump_render_model(
                ensure_render_doc(),
                artifact_dir_for(image_output) / "render_model.json",
            )
            errors.append(exc)
    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise AssertionError(
            f"{len(errors)} comparisons failed for {path.name}: "
            + "; ".join(str(err) for err in errors)
        )
    _log_timing(f"{path.name} total", time.perf_counter() - total_start)


def _sanitize_test_name(path: Path, prefix: str) -> str:
    relative = str(path.relative_to(XPS_INTEGRATION_ROOT))
    safe = re.sub(r"[^A-Za-z0-9]+", "_", relative).strip("_").lower()
    return f"{prefix}_{safe}"


def _make_test(path: Path):
    def _test(self):
        _run_xps_case(path)

    return _test


for _index, _path in enumerate(XPS_INTEGRATION_FILES, start=1):
    _name = f"test_xps_{_sanitize_test_name(_path, 'case')}_{_index}"
    setattr(TestXpsOutputs, _name, _make_test(_path))


if __name__ == "__main__":
    unittest.main()
