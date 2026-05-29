from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
import unittest
from pathlib import Path


def validate_pdf(path: Path) -> None:
    raw_cmd = os.getenv("PDF_VALIDATOR_CMD")
    cmd = _normalize_command(raw_cmd)
    if cmd is None and raw_cmd is None:
        cmd = _default_pdf_validator_cmd()
    if not cmd:
        raise unittest.SkipTest("PDF_VALIDATOR_CMD not set")
    args = shlex.split(cmd)
    result = subprocess.run(
        args + [str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"PDF validator failed ({result.returncode}): {result.stderr.strip()}"
        )


def _normalize_command(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _default_pdf_validator_cmd() -> str | None:
    if not _module_available("pypdf"):
        return None
    script = Path("tests") / "tools" / "pdf_validate.py"
    if script.exists():
        return f"{_preferred_python()} {script}"
    return None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _preferred_python() -> str:
    venv_python = Path(".venv") / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python3"
