#!/usr/bin/env python3
"""The app icon: a dark rounded square holding a page, with one line struck out by a
black bar and a red outline round it - a redaction that has been found out. Writes
packaging/icon.png (1024²), icon.ico, and on macOS icon.icns (via iconutil).

    python scripts/make_icon.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "packaging"
SLATE = (15, 23, 42)  # slate-900, the UI's ink
PAPER = (255, 255, 255)
LINE = (148, 163, 184)  # slate-400
BAR = (2, 6, 23)
FOUND = (220, 38, 38)  # red-600, the colour of a "recoverable" box in the app


def draw(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size * 0.22, fill=SLATE)
    left, top, right, bottom = size * 0.25, size * 0.17, size * 0.75, size * 0.83
    d.rounded_rectangle((left, top, right, bottom), radius=size * 0.03, fill=PAPER)
    x0, x1 = left + size * 0.07, right - size * 0.07
    h = size * 0.045
    for i, frac in enumerate((1.0, None, 1.0, 0.6)):
        y = top + size * 0.13 + i * size * 0.125
        if frac is None:  # the redacted line, and the box the checker draws round it
            pad = size * 0.022
            d.rectangle((x0, y - pad * 0.6, x1, y + h + pad * 0.6), fill=BAR)
            d.rounded_rectangle(
                (x0 - pad, y - pad * 1.6, x1 + pad, y + h + pad * 1.6),
                radius=size * 0.012,
                outline=FOUND,
                width=max(2, round(size * 0.016)),
            )
        else:
            d.rounded_rectangle((x0, y, x0 + (x1 - x0) * frac, y + h), radius=h / 2, fill=LINE)
    return img


def main() -> int:
    OUT.mkdir(exist_ok=True)
    icon = draw()
    icon.save(OUT / "icon.png")
    icon.save(
        OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    made = ["icon.png", "icon.ico"]
    if sys.platform == "darwin" and shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "icon.iconset"
            iconset.mkdir()
            for px in (16, 32, 64, 128, 256, 512):
                icon.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
                icon.resize((px * 2, px * 2), Image.LANCZOS).save(
                    iconset / f"icon_{px}x{px}@2x.png"
                )
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "icon.icns")], check=True
            )
        made.append("icon.icns")
    print("wrote", ", ".join(made), "->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
