import os
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from aspose.page.ps.document import PsDocument
from aspose.page.ps.output import ImageSaveOptions, PdfSaveOptions
from aspose.page.ps.base_ops import register_base_operators
from aspose.page.ps.fonts import FontResolver
from aspose.page.ps.graphics_ops import register_core_graphics_operators
from aspose.page.ps.color_ops import register_color_operators
from aspose.page.ps.image_ops import register_image_operators
from aspose.page.ps.images import PsImageStore
from aspose.page.ps.operators import OperatorRegistry
from aspose.page.ps.interpreter import PsInterpreter
from aspose.page.ps.pipeline import PsConversionPipeline
from aspose.page.ps.text_ops import register_text_operators
from aspose.page.common.render_model import RenderModelBuilder

from tests.common.compare_utils import (
    baseline_path_for,
    compare_images_on_fail,
    compare_pdfs_on_fail,
    artifact_dir_for,
    _baseline_pdf_images,
    resolve_image_baseline,
)
from tests.common.output_utils import write_output
from tests.common.pdf_validator import validate_pdf
from tests.common.render_model_dump import dump_render_model


PS_INTEGRATION_ROOT = Path("testdata/ps/integration")
PS_INTEGRATION_FILES = sorted(
    [
        path
        for path in PS_INTEGRATION_ROOT.rglob("*")
        if path.suffix.lower() in (".ps", ".eps")
    ]
)
ADDITIONAL_FONTS = "testdata/ps/necessary_fonts"
TIMING_ENABLED = os.getenv("TEST_TIMING") == "1"


def _log_timing(label: str, seconds: float) -> None:
    if TIMING_ENABLED:
        print(f"TIMING {label}: {seconds:.3f}s")


@unittest.skipUnless(os.getenv("RUN_INTEGRATION") == "1", "Integration tests disabled")
class TestPsEpsOutputs(unittest.TestCase):
    pass


def _baseline_pdf_available(baseline_pdf: Path) -> bool:
    for candidate in (baseline_pdf, _lowercase_parent(baseline_pdf)):
        if candidate.exists():
            return True
        if _baseline_pdf_images(candidate):
            return True
    return False


def _lowercase_parent(path: Path) -> Path:
    parts = path.parts
    if len(parts) <= 1:
        return path
    lowered = [part.lower() for part in parts[:-1]] + [parts[-1]]
    return Path(*lowered)


def _build_render_model(doc: PsDocument):
    builder = RenderModelBuilder()
    registry = OperatorRegistry()
    image_store = PsImageStore()
    font_resolver = FontResolver(additional_fonts_folder=ADDITIONAL_FONTS)
    register_base_operators(registry)
    register_core_graphics_operators(registry, builder)
    register_color_operators(registry, builder)
    register_text_operators(registry, builder, font_resolver)
    register_image_operators(registry, builder, image_store)
    interpreter = PsInterpreter(registry)
    pipeline = PsConversionPipeline(interpreter, registry, builder)
    return pipeline.build_render_model(doc.as_bytes())


def _run_ps_eps_case(path: Path) -> None:
    total_start = time.perf_counter()
    render_doc = None
    try:
        load_start = time.perf_counter()
        doc = PsDocument.from_file(str(path))
        _log_timing(f"{path.name} load", time.perf_counter() - load_start)
    except Exception as exc:
        raise AssertionError(f"{path}: load failed ({exc})") from exc

    def ensure_render_doc():
        nonlocal render_doc
        if render_doc is None:
            render_doc = _build_render_model(doc)
        return render_doc

    pdf_start = time.perf_counter()
    pdf_bytes = doc.to_pdf(
        PdfSaveOptions(
            additional_fonts_folder=ADDITIONAL_FONTS,
            no_compression=True,
        )
    )
    _log_timing(f"{path.name} ps->pdf", time.perf_counter() - pdf_start)
    relative = path.relative_to(PS_INTEGRATION_ROOT)
    pdf_key = Path("testdata/ps/ps2pdf/integration") / relative
    pdf_output = write_output(pdf_key, ".pdf", pdf_bytes)
    try:
        validate_start = time.perf_counter()
        validate_pdf(pdf_output)
        _log_timing(f"{path.name} pdf validate", time.perf_counter() - validate_start)
    except unittest.SkipTest as exc:
        print(f"SKIP PDF validation: {exc}")

    pdf_baseline = baseline_path_for(pdf_key, ".pdf")
    if not _baseline_pdf_available(pdf_baseline):
        raise AssertionError(f"{path}: baseline PDF images not found for {pdf_baseline}")
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
    except AssertionError:
        print(f"FAIL PDF compare: {path}")
        dump_render_model(
            ensure_render_doc(),
            artifact_dir_for(pdf_output) / "render_model.json",
        )
        raise

    image_start = time.perf_counter()
    image_bytes = doc.to_image(
        ImageSaveOptions(
            format="png",
            dpi=96,
            additional_fonts_folder=ADDITIONAL_FONTS,
        )
    )
    _log_timing(f"{path.name} ps->image", time.perf_counter() - image_start)
    image_key = Path("testdata/ps/ps2image/integration") / relative
    image_output = write_output(image_key, ".png", image_bytes)
    image_baseline = resolve_image_baseline(baseline_path_for(image_key, ".png"))
    if image_baseline is None:
        raise AssertionError(
            f"{path}: baseline image not found for {baseline_path_for(image_key, '.png')}"
        )
    try:
        compare_start = time.perf_counter()
        compare_images_on_fail(
            image_baseline,
            image_output,
            artifact_dir=artifact_dir_for(image_output),
        )
        _log_timing(f"{path.name} image compare", time.perf_counter() - compare_start)
    except unittest.SkipTest as exc:
        print(f"SKIP image compare: {exc}")
    except AssertionError:
        print(f"FAIL image compare: {path}")
        dump_render_model(
            ensure_render_doc(),
            artifact_dir_for(image_output) / "render_model.json",
        )
        raise
    _log_timing(f"{path.name} total", time.perf_counter() - total_start)


def _sanitize_test_name(path: Path, prefix: str) -> str:
    relative = str(path.relative_to(PS_INTEGRATION_ROOT))
    safe = re.sub(r"[^A-Za-z0-9]+", "_", relative).strip("_").lower()
    return f"{prefix}_{safe}"


def _make_test(path: Path):
    def _test(self):
        _run_ps_eps_case(path)

    return _test


for _index, _path in enumerate(PS_INTEGRATION_FILES, start=1):
    _name = f"test_ps_eps_{_sanitize_test_name(_path, 'case')}_{_index}"
    setattr(TestPsEpsOutputs, _name, _make_test(_path))


if __name__ == "__main__":
    unittest.main()
