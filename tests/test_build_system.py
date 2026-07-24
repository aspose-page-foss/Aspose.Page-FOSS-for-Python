from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestBuildSystemArtifacts(unittest.TestCase):
    def test_pyproject_has_required_sections(self) -> None:
        pyproject_path = PROJECT_ROOT / "pyproject.toml"
        self.assertTrue(pyproject_path.exists())
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        self.assertIn("build-system", data)
        self.assertIn("project", data)
        self.assertIn("tool", data)
        self.assertIn("setuptools", data["tool"])
        self.assertIn("uv", data["tool"])

        build_system = data["build-system"]
        self.assertEqual(build_system["build-backend"], "setuptools.build_meta")
        self.assertIn("setuptools>=68", build_system["requires"])

        project = data["project"]
        self.assertEqual(project["name"], "aspose-page-foss")
        self.assertGreaterEqual(len(project["version"]), 1)
        self.assertEqual(project["requires-python"], ">=3.10")

    def test_makefile_exposes_uv_targets(self) -> None:
        makefile_path = PROJECT_ROOT / "Makefile"
        self.assertTrue(makefile_path.exists())
        content = makefile_path.read_text(encoding="utf-8")
        for target in (
            "help:",
            "sync:",
            "test:",
            "build:",
            "clean:",
            "check:",
            "post-metrics:",
            "post-metrics-dry-run:",
            "post-metrics-from-file:",
            "post-metrics-from-file-dry-run:",
        ):
            self.assertIn(target, content)
        self.assertIn("uv is required but was not found", content)
        self.assertIn("$(UV) build", content)
        self.assertIn("tools/metrics_api_v1.py", content)

    def test_setup_py_compatibility_api(self) -> None:
        setup_path = PROJECT_ROOT / "setup.py"
        self.assertTrue(setup_path.exists())

        spec = importlib.util.spec_from_file_location("project_setup", setup_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["project_setup"] = module
        spec.loader.exec_module(module)

        kwargs = module.build_setup_kwargs()
        for key in ("name", "version", "python_requires", "package_dir", "packages"):
            self.assertIn(key, kwargs)
        self.assertEqual(kwargs["package_dir"], {"": "src"})
        self.assertIn("aspose", kwargs["packages"])
        self.assertIn("aspose.page", kwargs["packages"])


if __name__ == "__main__":
    unittest.main()
