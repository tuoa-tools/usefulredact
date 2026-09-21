#!/usr/bin/env python3
"""Gather what the bundle needs before PyInstaller (or the Windows layout) runs:

packaging/models/   the three default RapidOCR models, copied out of the installed
                    rapidocr wheel (which carries 260 MB of models; we ship 32 MB).
                    The packaged launcher points USEFULREDACT_MODEL_DIR at them.
app/static/         checked, not built: run `npm run build` in frontend/ first.
en_core_web_sm      checked: the name model has to be importable to be bundled.

  python scripts/prepare_bundle.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS_OUT = ROOT / "packaging" / "models"
# The defaults usefulredact/ocr.py uses: PP-OCRv6 small detector and recogniser, the
# mobile angle classifier.
MODEL_FILES = (
    "PP-OCRv6_det_small.onnx",
    "PP-OCRv6_rec_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
)


def main() -> int:
    import rapidocr

    source = Path(rapidocr.__file__).resolve().parent / "models"
    MODELS_OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in MODEL_FILES:
        src = source / name
        if not src.exists():
            print(f"missing in the rapidocr wheel: {src}", file=sys.stderr)
            return 1
        shutil.copy2(src, MODELS_OUT / name)
        total += src.stat().st_size
    print(f"models: {len(MODEL_FILES)} files, {total / 1e6:.1f} MB -> {MODELS_OUT}")

    index = ROOT / "app" / "static" / "index.html"
    if not index.exists():
        print("app/static/index.html is missing: run `npm run build` in frontend/", file=sys.stderr)
        return 1
    print("ui: app/static present")

    try:
        import en_core_web_sm
    except ImportError:
        print("en_core_web_sm is not installed: pip install -e . first", file=sys.stderr)
        return 1
    print(f"name model: en_core_web_sm {en_core_web_sm.__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
