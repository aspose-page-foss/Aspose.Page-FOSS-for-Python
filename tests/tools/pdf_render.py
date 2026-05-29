#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def _usage() -> None:
    print("Usage: pdf_render.py <input.pdf> <output_dir>", file=sys.stderr)


def main() -> int:
    if len(sys.argv) != 3:
        _usage()
        return 2

    input_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    if not input_path.exists():
        print(f"Input PDF not found: {input_path}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on environment
        print(f"pypdfium2 not installed: {exc}", file=sys.stderr)
        return 2

    try:
        import PIL  # noqa: F401  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on environment
        print(f"Pillow not installed: {exc}", file=sys.stderr)
        return 2

    pdf = pdfium.PdfDocument(str(input_path))
    page_count = len(pdf)
    pad = max(1, len(str(page_count)))

    scale = 96.0 / 72.0
    for index in range(page_count):
        page = pdf[index]
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        output_path = output_dir / f"page-{index + 1:0{pad}d}.png"
        image.save(output_path, dpi=(96, 96))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
