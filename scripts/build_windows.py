#!/usr/bin/env python3
"""Assemble the Windows app folder WITHOUT PyInstaller: Windows Defender quarantines
PyInstaller exes, while python.org's pythonw.exe is signed by the PSF (the lesson is
UsefulText's, and its sibling's before it).

Layout produced under build/windows/:
    python/                 python.org "embeddable" runtime
    Lib/site-packages/      the usefulredact and app packages (with the built UI) and every
                            dependency as pip installs it, the spaCy name model included
    Lib/site-packages/models/  the three OCR models (the launcher finds them there)
    UsefulRedact.cmd        fallback launcher; the installer's shortcut runs pythonw.exe

Must run on Windows with the Python minor version we ship (wheels are platform-specific).
packaging/windows.iss then wraps the folder into an Inno Setup installer.

    python scripts/prepare_bundle.py && python scripts/build_windows.py
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "windows"
EMBED_URL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
PIP_TRIES = 4  # the name model comes from a GitHub release asset, which sometimes answers 504


def main() -> int:
    if sys.platform != "win32":
        print("this script assembles a Windows layout; run it on Windows", file=sys.stderr)
        return 1
    models = ROOT / "packaging" / "models"
    if not (models / "PP-OCRv6_det_small.onnx").exists():
        print("run scripts/prepare_bundle.py first", file=sys.stderr)
        return 1
    version = "{}.{}.{}".format(*sys.version_info[:3])
    tag = f"python{sys.version_info.major}{sys.version_info.minor}"
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)

    print(f"downloading embeddable Python {version}")
    with urllib.request.urlopen(EMBED_URL.format(v=version), timeout=300) as response:
        zipfile.ZipFile(io.BytesIO(response.read())).extractall(OUT / "python")
    # The ._pth file *is* sys.path for the embeddable runtime (relative to python/).
    (OUT / "python" / f"{tag}._pth").write_text(
        f"{tag}.zip\n.\n..\\Lib\\site-packages\n", encoding="utf-8"
    )

    site = OUT / "Lib" / "site-packages"
    print("installing usefulredact and its dependencies")
    command = [sys.executable, "-m", "pip", "install", "--quiet", "--no-compile",
               "--target", str(site), "-c", str(ROOT / "constraints.txt"), str(ROOT)]  # fmt: skip
    for attempt in range(1, PIP_TRIES + 1):
        if subprocess.run(command).returncode == 0:
            break
        if attempt == PIP_TRIES:
            print("pip install failed", file=sys.stderr)
            return 1
        print(f"pip install failed (try {attempt} of {PIP_TRIES}); waiting before the next")
        shutil.rmtree(site, ignore_errors=True)
        time.sleep(20 * attempt)
    assert (site / "app" / "static" / "index.html").exists(), "built UI missing - run npm run build"
    assert (site / "en_core_web_sm").is_dir(), "the name model did not install"
    # pip --target drops console-script wrappers (usefulredact.exe...) into <target>/bin;
    # they cannot work in this layout.
    shutil.rmtree(site / "bin", ignore_errors=True)
    shutil.copytree(models, site / "models")
    # The rapidocr wheel carries 260 MB of models. The app uses the three copied above, which
    # the launcher points the engine at, so the wheel's own copies are dead weight in an
    # installer. (The PyInstaller bundles leave them out the same way.)
    for unused in (site / "rapidocr" / "models").glob("*.onnx"):
        unused.unlink()

    (OUT / "UsefulRedact.cmd").write_text(
        '@start "" "%~dp0python\\pythonw.exe" -m app.launcher\r\n', encoding="utf-8"
    )
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"assembled {OUT.relative_to(ROOT)} ({size:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
