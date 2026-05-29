from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parent


def _load_pyproject() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _find_packages() -> list[str]:
    src_root = ROOT / "src"
    packages: list[str] = []
    for init_file in src_root.rglob("__init__.py"):
        rel = init_file.parent.relative_to(src_root)
        if rel.parts:
            packages.append(".".join(rel.parts))
    return sorted(packages)


def build_setup_kwargs() -> dict[str, Any]:
    data = _load_pyproject()
    project = data["project"]
    return {
        "name": project["name"],
        "version": project["version"],
        "description": project.get("description", ""),
        "long_description": (ROOT / "README.md").read_text(encoding="utf-8"),
        "long_description_content_type": "text/markdown",
        "python_requires": project.get("requires-python", ">=3.10"),
        "package_dir": {"": "src"},
        "packages": _find_packages(),
        "include_package_data": True,
    }


def main() -> None:
    try:
        from setuptools import setup as setuptools_setup
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local env
        raise SystemExit(
            "setuptools is required for setup.py execution; use `uv build` or install setuptools."
        ) from exc
    setuptools_setup(**build_setup_kwargs())


if __name__ == "__main__":
    main()
