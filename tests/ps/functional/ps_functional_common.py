import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from aspose.page.ps.document import PsDocument
from aspose.page.ps.output import ImageSaveOptions, PdfSaveOptions

from tests.common.compare_utils import (
    _baseline_pdf_images,
    artifact_dir_for,
    baseline_path_for,
    compare_images_on_fail,
    compare_pdfs_on_fail,
    resolve_image_baseline,
)
from tests.common.output_utils import write_output
from tests.common.pdf_validator import validate_pdf
from tests.common.render_model_dump import dump_render_model
from tests.ps.integration.test_ps_eps_outputs import _build_render_model


PS_FUNCTIONAL_ROOT = Path("testdata/ps/functional")
ADDITIONAL_FONTS = "testdata/ps/necessary_fonts"
FUNCTIONAL_RUN_ENABLED = os.getenv("RUN_FUNCTIONAL") == "1"

# Explicitly excluded by user request.
_EXCLUDED_FONTS10_STEMS = {
    "DECK1",
    "DECK2",
    "DIAMOND",
    "EMPTY",
    "HEART",
    "SPADE",
    "SPADE2",
    "SCRABBLE",
    "SUITFONT",
    "SUPERFNT",
}


def run_ps_functional_case(path: Path) -> None:
    if (
        path.parent.name.upper() == "FONTS10"
        and path.stem.upper() in _EXCLUDED_FONTS10_STEMS
    ):
        raise unittest.SkipTest(f"{path.name} is excluded from functional conversion tests")

    doc = PsDocument.from_file(str(path))
    render_doc = None

    def ensure_render_doc():
        nonlocal render_doc
        if render_doc is None:
            render_doc = _build_render_model(doc)
        return render_doc

    image_compare_kwargs = {}
    if path.name.lower() == "intersct.ps":
        image_compare_kwargs = {"ignore_border": (1, 1, 1, 1)}

    pdf_failure: AssertionError | None = None
    image_failure: AssertionError | None = None

    pdf_bytes = doc.to_pdf(
        PdfSaveOptions(
            additional_fonts_folder=ADDITIONAL_FONTS,
            no_compression=True,
        )
    )
    relative = path.relative_to(PS_FUNCTIONAL_ROOT)
    pdf_key = Path("testdata/ps/ps2pdf/functional") / relative
    pdf_output = write_output(pdf_key, ".pdf", pdf_bytes)
    try:
        validate_pdf(pdf_output)
    except unittest.SkipTest as exc:
        print(f"SKIP PDF validation: {exc}")

    pdf_baseline = baseline_path_for(pdf_key, ".pdf")
    if not _baseline_pdf_available(pdf_baseline):
        raise AssertionError(f"{path}: baseline PDF images not found for {pdf_baseline}")
    try:
        compare_pdfs_on_fail(
            pdf_baseline,
            pdf_output,
            artifact_dir=artifact_dir_for(pdf_output),
            image_compare_kwargs=image_compare_kwargs,
        )
    except unittest.SkipTest as exc:
        print(f"SKIP PDF compare: {exc}")
    except AssertionError:
        print(f"FAIL PDF compare: {path}")
        dump_render_model(
            ensure_render_doc(),
            artifact_dir_for(pdf_output) / "render_model.json",
        )
        pdf_failure = AssertionError(f"PDF compare failed: {path}")

    image_bytes = doc.to_image(
        ImageSaveOptions(
            format="png",
            dpi=96,
            additional_fonts_folder=ADDITIONAL_FONTS,
        )
    )
    image_key = Path("testdata/ps/ps2image/functional") / relative
    image_output = write_output(image_key, ".png", image_bytes)
    image_baseline = resolve_image_baseline(baseline_path_for(image_key, ".png"))
    if image_baseline is None:
        raise AssertionError(
            f"{path}: baseline image not found for {baseline_path_for(image_key, '.png')}"
        )
    try:
        compare_images_on_fail(
            image_baseline,
            image_output,
            artifact_dir=artifact_dir_for(image_output),
            **image_compare_kwargs,
        )
    except unittest.SkipTest as exc:
        print(f"SKIP image compare: {exc}")
    except AssertionError:
        print(f"FAIL image compare: {path}")
        dump_render_model(
            ensure_render_doc(),
            artifact_dir_for(image_output) / "render_model.json",
        )
        image_failure = AssertionError(f"Image compare failed: {path}")

    if pdf_failure is not None and image_failure is not None:
        raise AssertionError(
            f"PDF compare failed and image compare failed: {path}"
        )
    if pdf_failure is not None:
        raise pdf_failure
    if image_failure is not None:
        raise image_failure


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
