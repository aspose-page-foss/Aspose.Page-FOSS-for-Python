"""Build, verify, and upload the Aspose.Page FOSS wheel.

Usage:
    python package.py build
    python package.py verify
    python package.py publish-test
    python package.py publish
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
VENV = ROOT / ".package-venv"
REPOSITORIES = {
    "publish-test": ("https://test.pypi.org/legacy/", ROOT / "local" / "test.pypi.org.txt"),
    "publish": ("https://upload.pypi.org/legacy/", ROOT / "local" / "pypi.org.txt"),
}
INDEXES = {
    "publish-test": "https://test.pypi.org",
    "publish": "https://pypi.org",
}


def run(*args: str, env: dict[str, str] | None = None) -> None:
    environment = (env or os.environ).copy()
    environment.setdefault("UV_CACHE_DIR", str(ROOT / ".package-cache"))
    environment.setdefault("UV_TOOL_DIR", str(ROOT / ".package-tools"))
    environment.setdefault("UV_TOOL_BIN_DIR", str(ROOT / ".package-bin"))
    subprocess.run(args, cwd=ROOT, env=environment, check=True)


def version() -> str:
    value = (ROOT / "local" / "Version.txt").read_text(encoding="utf-8").strip()
    if not value or any(char.isspace() for char in value):
        raise ValueError("local/Version.txt must contain one package version")
    return value


def wheel() -> Path:
    path = DIST / f"aspose_page_foss-{version()}-py3-none-any.whl"
    if not path.is_file():
        raise FileNotFoundError(f"Build the current version first: {path}")
    return path


def venv_python(venv: Path) -> Path:
    for candidate in (venv / "Scripts" / "python.exe", venv / "bin" / "python"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No Python executable found in {venv}")


def build() -> None:
    DIST.mkdir(exist_ok=True)
    run("uv", "build", "--wheel", "--no-build-isolation", "--python", sys.executable,
        "--out-dir", str(DIST))
    print(f"Built {wheel()}")


SMOKE_CODE = """
import importlib.metadata
from pathlib import Path
import struct
import sys

from aspose.page.ps.document import PsDocument
from aspose.page.ps.output import ImageSaveOptions
from aspose.page.xps.document import XpsDocument
import skia

root = Path(sys.argv[1])
output = Path(sys.argv[2])
expected_version = sys.argv[3]
assert importlib.metadata.version('aspose-page-foss') == expected_version
assert any(requirement.startswith('skia-python') for requirement in
           importlib.metadata.requires('aspose-page-foss'))
assert 'site-packages' in str(Path(sys.modules['aspose'].__file__).resolve())
output.mkdir(parents=True, exist_ok=True)

ps = PsDocument.from_file(str(root / 'testdata/ps/integration/minimal.ps'))
xps = XpsDocument.from_file(str(root / 'testdata/xps/integration/Simple.xps'))
for name, data, signature in (
    ('ps.pdf', ps.to_pdf(), b'%PDF-1.4'),
    ('ps.png', ps.to_image(ImageSaveOptions(format='png', dpi=72)), b'\\x89PNG\\r\\n\\x1a\\n'),
    ('xps.pdf', xps.to_pdf(), b'%PDF-1.4'),
    ('xps.png', xps.to_image(ImageSaveOptions(format='png', dpi=72)), b'\\x89PNG\\r\\n\\x1a\\n'),
):
    assert data.startswith(signature), f'{name}: invalid signature'
    if name.endswith('.pdf'):
        assert b'%%EOF' in data[-128:], f'{name}: missing PDF trailer'
    else:
        width, height = struct.unpack('>II', data[16:24])
        assert width > 0 and height > 0, f'{name}: empty image'
    (output / name).write_bytes(data)
    print(f'{name}: {len(data)} bytes')
"""


def verify() -> None:
    artifact = wheel()
    run("uv", "venv", "--clear", "--python", sys.executable, str(VENV))
    python = venv_python(VENV)
    run("uv", "pip", "install", "--python", str(python), str(artifact))
    output = ROOT / "test-out" / "package-smoke"
    subprocess.run(
        [str(python), "-c", SMOKE_CODE, str(ROOT), str(output), version()],
        cwd=VENV,
        check=True,
    )
    print(f"Four conversions passed; output: {output}")


def credentials(path: Path) -> tuple[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip().lower()] = value.strip().strip('"\'')
    username = values.get("username") or values.get("user")
    password = values.get("password")
    if not username or not password:
        raise ValueError(f"{path} must contain username/user and password assignments")
    return username, password


def check_upload_available(command: str, artifact: Path) -> None:
    release_url = f"{INDEXES[command]}/pypi/aspose-page-foss/{version()}/json"
    request = Request(release_url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            release = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            return
        print(f"Warning: release lookup returned HTTP {exc.code}; trying upload.", file=sys.stderr)
        return
    except (URLError, TimeoutError) as exc:
        print(f"Warning: release lookup failed ({exc}); trying upload.", file=sys.stderr)
        return

    for uploaded in release.get("urls", []):
        if uploaded.get("filename") != artifact.name:
            continue
        local_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        same_file = local_hash == uploaded.get("digests", {}).get("sha256")
        detail = "already uploaded" if same_file else "already used for different content"
        raise SystemExit(
            "UPLOAD STOPPED: wheel filename already exists.\n"
            f"  File: {artifact.name}\n"
            f"  Index: {INDEXES[command]}\n"
            f"  Release: {INDEXES[command]}/project/aspose-page-foss/{version()}/\n"
            f"  Status: {detail}\n"
            "TestPyPI and PyPI do not allow replacing an uploaded filename.\n"
            "Choose a new version in local/Version.txt, then run build, verify, "
            "and publish again."
        )


def publish(command: str) -> None:
    artifact = wheel()
    check_upload_available(command, artifact)
    url, credentials_path = REPOSITORIES[command]
    username, password = credentials(credentials_path)
    environment = os.environ.copy()
    environment.update(TWINE_USERNAME=username, TWINE_PASSWORD=password)
    run("uvx", "--from", "twine", "twine", "check", str(artifact))
    run(
        "uvx", "--from", "twine", "twine", "upload", "--non-interactive",
        "--repository-url", url, str(artifact), env=environment,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify", *REPOSITORIES))
    args = parser.parse_args()
    if args.command == "build":
        build()
    elif args.command == "verify":
        verify()
    else:
        publish(args.command)


if __name__ == "__main__":
    main()
