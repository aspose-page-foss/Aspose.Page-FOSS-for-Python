#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def _usage() -> None:
    print("Usage: pdf_validate.py <input.pdf>", file=sys.stderr)


def _read_header(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.readline().strip()


def main() -> int:
    if len(sys.argv) != 2:
        _usage()
        return 2

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Input PDF not found: {input_path}", file=sys.stderr)
        return 2

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on environment
        print(f"pypdf not installed: {exc}", file=sys.stderr)
        return 2

    header = _read_header(input_path)
    if not header.startswith(b"%PDF-"):
        print("Missing %PDF- header", file=sys.stderr)
        return 2

    version = header[5:].split()[0]
    if version != b"1.4":
        try:
            decoded = version.decode("latin-1")
        except Exception:
            decoded = repr(version)
        print(f"Expected PDF 1.4 header, got {decoded}", file=sys.stderr)
        return 2

    reader = PdfReader(str(input_path), strict=True)
    _ = len(reader.pages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
