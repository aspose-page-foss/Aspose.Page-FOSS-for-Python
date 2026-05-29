from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Callable


BASELINE_ROOT_DEFAULT = Path("testdata") / "expected"
TESTDATA_DIRNAME = "testdata"
DEFAULT_BASELINE_MAP: tuple[tuple[Path, Path], ...] = (
    (Path("ps") / "ps2pdf", Path("testdata") / "ps" / "baseline" / "ps2pdf"),
    (Path("ps") / "ps2image", Path("testdata") / "ps" / "baseline" / "ps2image"),
    (Path("xps") / "xps2pdf", Path("testdata") / "xps" / "baseline" / "xps2pdf"),
    (Path("xps") / "xps2image", Path("testdata") / "xps" / "baseline" / "xps2image"),
)


def baseline_path_for(input_path: Path, suffix: str) -> Path:
    relative = _relative_from_testdata(input_path)
    root, remainder = _resolve_baseline_root(relative)
    candidate = root / remainder
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    return candidate.with_suffix(suffix)


def compare_images(
    baseline: Path,
    actual: Path,
    delta: int = 8,
    ratio: float = 0.3,
    size_delta: int = 0,
    artifact_dir: Path | None = None,
    ignore_border: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> None:
    if _try_external_image_compare(
        baseline,
        actual,
        delta,
        ratio,
        size_delta,
        ignore_border,
    ):
        return
    _compare_images_internal(
        baseline,
        actual,
        delta=delta,
        ratio=ratio,
        size_delta=size_delta,
        artifact_dir=artifact_dir,
        ignore_border=ignore_border,
    )


def _compare_images_internal(
    baseline: Path,
    actual: Path,
    delta: int = 8,
    ratio: float = 0.3,
    size_delta: int = 0,
    artifact_dir: Path | None = None,
    ignore_border: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> None:
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on environment
        raise unittest.SkipTest("Pillow not installed") from exc

    with Image.open(baseline) as baseline_img, Image.open(actual) as actual_img:
        alpha_mask = _alpha_mask(baseline_img)
        base = _normalize_rgb(baseline_img)
        actual_rgb = _normalize_rgb(actual_img)

        if not _size_matches(base, actual_rgb, size_delta):
            _write_diff_artifacts(base, actual_rgb, artifact_dir, delta, ratio)
            raise AssertionError(
                f"Wrong image size ({size_delta}, {base.width}, {actual_rgb.width}, {base.height}, {actual_rgb.height})"
            )

        left, top, right, bottom = ignore_border
        x_start = max(0, left)
        y_start = max(0, top)
        x_end = min(actual_rgb.width, actual_rgb.width - max(0, right))
        y_end = min(actual_rgb.height, actual_rgb.height - max(0, bottom))
        if x_end <= x_start or y_end <= y_start:
            raise AssertionError("ignore_border excludes entire image")

        color_delta = int(ratio * 100)
        ok, fail_x, fail_y = _compare_bytes(
            base,
            actual_rgb,
            x_start,
            y_start,
            x_end,
            y_end,
            max(delta, 1),
            color_delta,
            alpha_mask,
        )
        if not ok:
            _write_diff_artifacts(base, actual_rgb, artifact_dir, delta, ratio)
            raise AssertionError(
                f"Image comparison failed at ({fail_x}, {fail_y}) with delta={delta} ratio={ratio}"
            )


def compare_images_on_fail(
    baseline: Path,
    actual: Path,
    delta: int = 8,
    ratio: float = 0.3,
    size_delta: int = 0,
    artifact_dir: Path | None = None,
    ignore_border: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> None:
    """Compare images and only write artifacts when a mismatch occurs."""
    try:
        compare_images(
            baseline,
            actual,
            delta=delta,
            ratio=ratio,
            size_delta=size_delta,
            artifact_dir=None,
            ignore_border=ignore_border,
        )
    except AssertionError as err:
        if artifact_dir is not None:
            try:
                _compare_images_internal(
                    baseline,
                    actual,
                    delta=delta,
                    ratio=ratio,
                    size_delta=size_delta,
                    artifact_dir=artifact_dir,
                    ignore_border=ignore_border,
                )
            except unittest.SkipTest:
                # Keep original mismatch result when local artifact generation
                # is unavailable (eg Pillow missing).
                pass
        raise err


def compare_pdfs(
    baseline: Path,
    actual: Path,
    artifact_dir: Path | None = None,
    image_compare_kwargs: dict | None = None,
) -> None:
    """Compare PDF by rendering pages to images and matching baseline PNGs.

    Baseline folders may contain only images (no baseline PDF is required).
    """
    raw_render = os.getenv("PDF_RENDER_CMD")
    render_cmd = _normalize_command(raw_render)
    if render_cmd is None and raw_render is None:
        render_cmd = _default_pdf_render_cmd()
    if not render_cmd:
        raise unittest.SkipTest("PDF_RENDER_CMD not set")

    baseline_images = _baseline_pdf_images(baseline)
    if not baseline_images:
        baseline_images = _baseline_pdf_images(_lowercase_parent(baseline))
    if not baseline_images:
        raise unittest.SkipTest("Baseline PDF images not found")

    with tempfile.TemporaryDirectory(prefix="pdf-render-") as tmpdir:
        render_dir = Path(tmpdir)
        _run_render(render_cmd, actual, render_dir)
        rendered = list(render_dir.glob("*.png"))
        if rendered:
            _cleanup_rendered_images(actual)
            rendered = _rename_rendered_images(sorted(rendered), actual)
    if len(rendered) != len(baseline_images):
        raise AssertionError(
            f"Rendered page count {len(rendered)} != baseline {len(baseline_images)}"
        )
    for index, (base_img, actual_img) in enumerate(zip(baseline_images, rendered), start=1):
        page_dir = None
        if artifact_dir is not None:
            page_dir = artifact_dir / f"page-{index}"
        compare_images(
            base_img,
            actual_img,
            artifact_dir=page_dir,
            **(image_compare_kwargs or {}),
        )


def compare_pdfs_on_fail(
    baseline: Path,
    actual: Path,
    artifact_dir: Path | None = None,
    image_compare_kwargs: dict | None = None,
) -> None:
    """Compare PDFs and only write artifacts when a mismatch occurs."""
    try:
        compare_pdfs(
            baseline,
            actual,
            artifact_dir=None,
            image_compare_kwargs=image_compare_kwargs,
        )
    except AssertionError:
        if artifact_dir is not None:
            compare_pdfs(
                baseline,
                actual,
                artifact_dir=artifact_dir,
                image_compare_kwargs=image_compare_kwargs,
            )
        raise


def _rename_rendered_images(rendered: list[Path], pdf_path: Path) -> list[Path]:
    _cleanup_rendered_images(pdf_path)
    if not rendered:
        return []
    if len(rendered) == 1:
        target = pdf_path.with_suffix(".png")
        if rendered[0] != target:
            shutil.move(str(rendered[0]), str(target))
        return [target]
    pad = max(1, len(str(len(rendered))))
    results: list[Path] = []
    for index, path in enumerate(rendered, start=1):
        target = pdf_path.with_name(f"{pdf_path.stem}.page-{index:0{pad}d}.png")
        if path != target:
            shutil.move(str(path), str(target))
        results.append(target)
    return results


def _cleanup_rendered_images(pdf_path: Path) -> None:
    single = pdf_path.with_suffix(".png")
    if single.exists():
        try:
            single.unlink()
        except OSError:
            pass
    for path in pdf_path.parent.glob(f"{pdf_path.stem}.page-*.png"):
        try:
            path.unlink()
        except OSError:
            pass


def _relative_from_testdata(input_path: Path) -> Path:
    parts = input_path.parts
    if TESTDATA_DIRNAME not in parts:
        raise ValueError("input path must be under testdata")
    index = parts.index(TESTDATA_DIRNAME)
    return Path(*parts[index + 1 :])


def _resolve_baseline_root(relative: Path) -> tuple[Path, Path]:
    for prefix, root in _load_baseline_map():
        if _path_starts_with(relative, prefix):
            remainder = relative.relative_to(prefix)
            return root, remainder
    root = Path(os.getenv("BASELINE_ROOT", str(BASELINE_ROOT_DEFAULT)))
    return root, relative


def _load_baseline_map() -> list[tuple[Path, Path]]:
    entries: list[tuple[Path, Path]] = []
    raw = os.getenv("BASELINE_MAP")
    if raw:
        for part in raw.split(";"):
            if not part.strip() or "=" not in part:
                continue
            left, right = part.split("=", 1)
            prefix = _normalize_mapping_prefix(left.strip())
            if not prefix:
                continue
            entries.append((prefix, Path(right.strip())))
    entries.extend(DEFAULT_BASELINE_MAP)
    entries.sort(key=lambda item: len(item[0].parts), reverse=True)
    return entries


def _normalize_mapping_prefix(raw: str) -> Path:
    if not raw:
        return Path()
    path = Path(raw)
    if path.parts and path.parts[0] == TESTDATA_DIRNAME:
        return Path(*path.parts[1:])
    return path


def _path_starts_with(path: Path, prefix: Path) -> bool:
    if not prefix.parts:
        return False
    return path.parts[: len(prefix.parts)] == prefix.parts


def _lowercase_parent(path: Path) -> Path:
    parts = path.parts
    if len(parts) <= 1:
        return path
    lowered = [part.lower() for part in parts[:-1]] + [parts[-1]]
    candidate = Path(*lowered)
    return candidate


def _baseline_pdf_images(baseline_pdf: Path) -> list[Path]:
    for candidate in (baseline_pdf, _lowercase_parent(baseline_pdf)):
        images = _baseline_pdf_images_for_path(candidate)
        if images:
            return images
    return []


def _try_external_image_compare(
    baseline: Path,
    actual: Path,
    delta: int,
    ratio: float,
    size_delta: int,
    ignore_border: tuple[int, int, int, int],
) -> bool:
    raw_cmd = os.getenv("IMAGE_COMPARE_CMD")
    if raw_cmd is None:
        raw_cmd = _default_image_compare_cmd()
    cmd = _normalize_command(raw_cmd)
    if not cmd:
        return False
    # Avoid a hang in subprocess by ensuring the tool exists first.
    if cmd and " " not in cmd and not Path(cmd).exists():
        return False
    # Allow bypassing external compare when no Pillow is available.
    if os.getenv("IMAGE_COMPARE_CMD_ONLY") == "1":
        return _run_external_compare(
            cmd,
            baseline,
            actual,
            delta,
            ratio,
            size_delta,
            ignore_border,
        )
    prepared = _prepare_external_compare_inputs(baseline, actual)
    baseline_path, actual_path, cleanup = prepared
    left, top, right, bottom = ignore_border
    ignore_arg = f"{left},{top},{right},{bottom}"
    args = [
        str(baseline_path),
        str(actual_path),
        "--delta",
        str(delta),
        "--ratio",
        str(ratio),
        "--size-delta",
        str(size_delta),
        "--ignore-border",
        ignore_arg,
    ]
    try:
        _run_command(cmd, args, "Image comparator failed")
    except AssertionError as exc:
        # If the external tool is unavailable, fall back to Python comparison.
        if "No such file or directory" in str(exc):
            cleanup()
            return False
        cleanup()
        raise
    cleanup()
    return True


def _prepare_external_compare_inputs(
    baseline: Path,
    actual: Path,
) -> tuple[Path, Path, Callable[[], None]]:
    """Prepare RGB-normalized temporary files for native comparator.

    The native comparator evaluates raw pixels and may treat alpha-channel
    differences as hard mismatches even when composited RGB content is identical.
    To align with Python fallback logic, normalize both inputs to RGB on white
    background before invoking the external tool.
    """

    try:
        from PIL import Image  # type: ignore
    except Exception:
        return baseline, actual, (lambda: None)

    tmpdir = Path(tempfile.mkdtemp(prefix="img-compare-"))
    base_rgb = tmpdir / "baseline.png"
    actual_rgb = tmpdir / "actual.png"
    try:
        with Image.open(baseline) as base_img:
            _normalize_rgb(base_img).save(base_rgb)
        with Image.open(actual) as actual_img:
            _normalize_rgb(actual_img).save(actual_rgb)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return baseline, actual, (lambda: None)

    def _cleanup() -> None:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return base_rgb, actual_rgb, _cleanup


def _run_external_compare(
    cmd: str,
    baseline: Path,
    actual: Path,
    delta: int,
    ratio: float,
    size_delta: int,
    ignore_border: tuple[int, int, int, int],
) -> bool:
    left, top, right, bottom = ignore_border
    ignore_arg = f"{left},{top},{right},{bottom}"
    args = [
        str(baseline),
        str(actual),
        "--delta",
        str(delta),
        "--ratio",
        str(ratio),
        "--size-delta",
        str(size_delta),
        "--ignore-border",
        ignore_arg,
    ]
    try:
        _run_command(cmd, args, "Image comparator failed")
    except AssertionError as exc:
        if "No such file or directory" in str(exc):
            return False
        raise
    return True


def _baseline_pdf_images_for_path(baseline_pdf: Path) -> list[Path]:
    stem = baseline_pdf.stem
    images: list[Path] = []
    index = 1
    while True:
        candidates = [
            baseline_pdf.with_name(f"{baseline_pdf.name}.page-{index}.png"),
            baseline_pdf.with_name(f"{stem}.page-{index}.png"),
            baseline_pdf.with_name(f"{stem}_{index}.png"),
            baseline_pdf.with_name(f"{stem}-{index}.png"),
            baseline_pdf.with_name(f"{stem} ({index}).png"),
            baseline_pdf.with_name(f"{stem}({index}).png"),
        ]
        found = next((item for item in candidates if item.exists()), None)
        if not found:
            break
        images.append(found)
        index += 1
    if images:
        return images

    # Common single-page naming conventions.
    single_variants = [
        baseline_pdf.with_suffix(".png"),  # <name>.png
        baseline_pdf.with_name(baseline_pdf.name + ".png"),  # <name>.pdf.png
        baseline_pdf.with_name(f"{stem} (1).png"),
        baseline_pdf.with_name(f"{stem}(1).png"),
        baseline_pdf.with_name(f"{stem}0.png"),
        baseline_pdf.with_name(f"{stem}_0.png"),
        baseline_pdf.with_name(f"{stem}-0.png"),
        baseline_pdf.with_name(f"{stem} (0).png"),
        baseline_pdf.with_name(f"{stem}(0).png"),
    ]
    for candidate in single_variants:
        if candidate.exists():
            return [candidate]
    return []


def artifact_dir_for(actual: Path) -> Path:
    return actual.parent / "diff" / actual.stem


def resolve_image_baseline(baseline: Path) -> Path | None:
    for candidate in _baseline_variants(baseline):
        if candidate.exists():
            return candidate
    lower = _lowercase_parent(baseline)
    if lower != baseline:
        for candidate in _baseline_variants(lower):
            if candidate.exists():
                return candidate
    # Fall back to case-insensitive stem match if only casing differs.
    stem_lower = baseline.stem.lower()
    for path in baseline.parent.glob(f"*{baseline.suffix}"):
        if path.stem.lower() == stem_lower:
            return path
    lower_parent = Path(*[part.lower() for part in baseline.parent.parts])
    if lower_parent.exists():
        for path in lower_parent.glob(f"*{baseline.suffix}"):
            if path.stem.lower() == stem_lower:
                return path
    return None


def _baseline_variants(baseline: Path) -> list[Path]:
    stem = baseline.stem
    suffix = baseline.suffix
    return [
        baseline,
        baseline.with_name(f"{stem}0{suffix}"),
        baseline.with_name(f"{stem}1{suffix}"),
        baseline.with_name(f"{stem}_0{suffix}"),
        baseline.with_name(f"{stem}_1{suffix}"),
        baseline.with_name(f"{stem}-0{suffix}"),
        baseline.with_name(f"{stem}-1{suffix}"),
        baseline.with_name(f"{stem} (0){suffix}"),
        baseline.with_name(f"{stem} (1){suffix}"),
    ]


def _size_matches(base, actual, size_delta: int) -> bool:
    if size_delta <= 0:
        return base.size == actual.size
    return (
        abs(base.width - actual.width) <= size_delta
        and abs(base.height - actual.height) <= size_delta
    )


def _normalize_rgb(image):
    from PIL import Image  # type: ignore

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, rgba)
    return image.convert("RGB")


def _alpha_mask(image) -> bytes | None:
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        data = alpha.tobytes()
        # Treat near-transparent pixels as background for comparison.
        return bytes(0 if value <= 128 else 1 for value in data)
    return None


def _compare_bytes(
    base_img,
    actual_img,
    x_start: int,
    y_start: int,
    x_end: int,
    y_end: int,
    delta: int,
    color_delta: int,
    alpha_mask: bytes | None,
) -> tuple[bool, int | None, int | None]:
    base_bytes = memoryview(base_img.tobytes())
    actual_bytes = memoryview(actual_img.tobytes())
    stride = base_img.width * 3
    cache1: dict[int, memoryview] = {}
    cache2: dict[int, memoryview] = {}

    for y in range(y_start, y_end):
        y_to = min(y + delta, y_end)
        for yi in range(y, y_to):
            if yi not in cache1:
                row_start = yi * stride
                row_end = row_start + stride
                cache1[yi] = base_bytes[row_start:row_end]
                cache2[yi] = actual_bytes[row_start:row_end]

        for x in range(x_start, x_end):
            if alpha_mask is not None:
                if alpha_mask[y * base_img.width + x] == 0:
                    continue
                row1 = cache1[y]
                idx = x * 3
                white_threshold = 255 - color_delta
                if (
                    row1[idx] >= white_threshold
                    and row1[idx + 1] >= white_threshold
                    and row1[idx + 2] >= white_threshold
                ):
                    continue
            x_to = min(x + delta, x_end)
            if not _almost_same_block_bytes(cache1, cache2, x, y, x_to, y_to, color_delta):
                return False, x, y

        cache1.pop(y, None)
        cache2.pop(y, None)

    return True, None, None


def _almost_same_block_bytes(
    base_rows: dict[int, memoryview],
    actual_rows: dict[int, memoryview],
    x: int,
    y: int,
    x_to: int,
    y_to: int,
    color_delta: int,
) -> bool:
    x_start = x * 3
    x_end = x_to * 3
    for y1 in range(y, y_to):
        row1 = base_rows[y1]
        row2 = actual_rows[y1]
        for idx in range(x_start, x_end, 3):
            r1 = row1[idx]
            g1 = row1[idx + 1]
            b1 = row1[idx + 2]
            r2 = row2[idx]
            g2 = row2[idx + 1]
            b2 = row2[idx + 2]
            if _channels_close(r1, r2, color_delta) and _channels_close(
                g1, g2, color_delta
            ) and _channels_close(b1, b2, color_delta):
                return True
    return False


def _channels_close(c1: int, c2: int, delta: int) -> bool:
    return c1 == c2 or (c1 > c2 - delta and c1 < c2 + delta)


def _write_diff_artifacts(
    baseline_img,
    actual_img,
    artifact_dir: Path | None,
    delta: int,
    ratio: float,
) -> None:
    if artifact_dir is None:
        return
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return

    artifact_dir.mkdir(parents=True, exist_ok=True)
    width = min(actual_img.width, baseline_img.width)
    height = min(actual_img.height, baseline_img.height)
    diff = Image.new("RGB", (width, height), (0, 0, 0))
    diff_px = diff.load()
    base_px = baseline_img.load()
    act_px = actual_img.load()
    color_delta = int(ratio * 100)
    mismatches = 0
    x_min = y_min = None
    x_max = y_max = None
    tile_size = 32
    tiles = {}

    for y in range(height):
        for x in range(width):
            r1, g1, b1 = base_px[x, y]
            r2, g2, b2 = act_px[x, y]
            dr = abs(r1 - r2)
            dg = abs(g1 - g2)
            db = abs(b1 - b2)
            diff_px[x, y] = (dr, dg, db)
            if dr > color_delta or dg > color_delta or db > color_delta:
                mismatches += 1
                if x_min is None or x < x_min:
                    x_min = x
                if y_min is None or y < y_min:
                    y_min = y
                if x_max is None or x > x_max:
                    x_max = x
                if y_max is None or y > y_max:
                    y_max = y
                tile_key = (x // tile_size, y // tile_size)
                tiles[tile_key] = tiles.get(tile_key, 0) + 1

    diff_path = artifact_dir / "diff.png"
    diff.save(diff_path)
    summary = {
        "delta": delta,
        "ratio": ratio,
        "color_delta": color_delta,
        "mismatches": mismatches,
        "total_pixels": width * height,
        "size": {
            "baseline": [baseline_img.width, baseline_img.height],
            "actual": [actual_img.width, actual_img.height],
        },
        "overall_bbox": (
            None
            if x_min is None
            else {"x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max}
        ),
        "tile_size": tile_size,
        "top_tiles": _top_tiles(tiles, tile_size),
    }
    (artifact_dir / "diff.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )


def _top_tiles(tiles: dict[tuple[int, int], int], tile_size: int) -> list[dict[str, int]]:
    ranked = sorted(tiles.items(), key=lambda item: item[1], reverse=True)[:10]
    results: list[dict[str, int]] = []
    for (tx, ty), count in ranked:
        results.append(
            {
                "tile_x": tx,
                "tile_y": ty,
                "count": count,
                "x_min": tx * tile_size,
                "y_min": ty * tile_size,
                "x_max": (tx + 1) * tile_size - 1,
                "y_max": (ty + 1) * tile_size - 1,
            }
        )
    return results


def _run_render(command: str, input_path: Path, output_dir: Path) -> None:
    if "{input}" in command or "{output}" in command:
        formatted = command.format(input=str(input_path), output=str(output_dir))
        _run_command(formatted, [], "PDF render failed")
        return
    _run_command(command, [str(input_path), str(output_dir)], "PDF render failed")


def _run_command(command: str, extra_args: list[str], error_prefix: str) -> None:
    args = shlex.split(command) + extra_args
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"{error_prefix} ({result.returncode}): {result.stderr.strip()}"
        )


def _normalize_command(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _default_pdf_render_cmd() -> str | None:
    if _command_available("pdftoppm"):
        # Poppler pdftoppm: renders to {output}/page-1.png, page-2.png, ...
        return "pdftoppm -png -r 96 {input} {output}/page"
    if not _module_available("pypdfium2"):
        return None
    if not _module_available("PIL"):
        return None
    script = Path("tests") / "tools" / "pdf_render.py"
    if script.exists():
        return f"{_preferred_python()} {script}"
    return None


def _default_image_compare_cmd() -> str | None:
    candidate = Path("tools") / "ImageComparer" / "build" / "image_compare"
    if candidate.exists():
        return str(candidate)
    return None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _command_available(name: str) -> bool:
    return shutil.which(name) is not None


def _preferred_python() -> str:
    venv_python = Path(".venv") / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python3"
