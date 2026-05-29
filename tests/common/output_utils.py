from __future__ import annotations

from pathlib import Path


TESTDATA_DIRNAME = "testdata"
OUTPUT_ROOT = Path("test-out")


def output_path_for(input_path: Path, suffix: str) -> Path:
    """Return output path under test-out mirroring testdata structure."""
    relative = _relative_from_testdata(input_path)
    output_path = OUTPUT_ROOT / relative
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    output_path = output_path.with_suffix(suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def write_output(input_path: Path, suffix: str, data: bytes) -> Path:
    """Write output bytes to test-out and return the path."""
    output_path = output_path_for(input_path, suffix)
    output_path.write_bytes(data)
    return output_path


def _relative_from_testdata(input_path: Path) -> Path:
    parts = input_path.parts
    if TESTDATA_DIRNAME not in parts:
        raise ValueError("input path must be under testdata")
    index = parts.index(TESTDATA_DIRNAME)
    return Path(*parts[index + 1 :])
