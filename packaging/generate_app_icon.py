"""
Generates packaging/assets/mission_automation.ico from this app's own
real app_icon() (src/desktop/icons.py) - not a separately re-derived
copy of its SVG, so the packaged .exe's icon can never drift out of
sync with the actual in-app window/taskbar icon.

Run from the repo root:

    QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe packaging\\generate_app_icon.py

Requires Pillow (a one-time build-tooling need, not a runtime
dependency of the app itself - not added to any requirements*.txt).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.icons import app_icon  # noqa: E402

_SIZES = [16, 24, 32, 48, 64, 128, 256]
_OUTPUT_PATH = REPO_ROOT / "packaging" / "assets" / "mission_automation.ico"


def main() -> None:
    QApplication.instance() or QApplication([])

    icon = app_icon()
    tmp_dir = Path(tempfile.mkdtemp())
    pil_images = []

    for size in _SIZES:
        pixmap = icon.pixmap(QSize(size, size))
        tmp_png = tmp_dir / f"icon_{size}.png"
        pixmap.save(str(tmp_png), "PNG")
        pil_images.append(Image.open(tmp_png).convert("RGBA"))

    # Pillow's ICO writer resamples ONE source image down to each
    # requested size rather than combining separately-rendered
    # frames - use the largest (rendered directly from the vector
    # SVG at that size, not upscaled from a smaller raster) as that
    # one source for genuinely crisp results at every embedded size.
    largest = pil_images[-1]
    assert largest.size == (_SIZES[-1], _SIZES[-1])

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    largest.save(
        str(_OUTPUT_PATH),
        format="ICO",
        sizes=[(size, size) for size in _SIZES],
    )

    print(f"Wrote {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
