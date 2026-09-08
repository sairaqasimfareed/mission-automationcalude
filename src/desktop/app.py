from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from src.browser.chromium_bootstrap import (
    INTERNAL_PLAYWRIGHT_INSTALL_FLAG,
    run_playwright_install_entrypoint,
)
from src.desktop import services
from src.desktop.icons import app_icon
from src.desktop.main_window import MainWindow
from src.desktop.theme import apply_theme


def main() -> int:
    """Launch the Mission Automation desktop application."""

    # Installer packaging: a frozen (PyInstaller) build re-invokes
    # ITSELF with this internal flag to run "playwright install
    # chromium" (see chromium_bootstrap.py's own docstring for why a
    # frozen build's sys.executable can't just take a plain "-m
    # playwright" argument the way a real python.exe can). This
    # branch must be checked before anything else in main() - it
    # never constructs a QApplication or shows any window, it just
    # runs the install and exits.
    if INTERNAL_PLAYWRIGHT_INSTALL_FLAG in sys.argv:
        return run_playwright_install_entrypoint()

    app = QApplication(sys.argv)
    app.setApplicationName("Mission Automation")
    app.setWindowIcon(app_icon())

    theme_mode = services.get_theme_preference_store().load()
    apply_theme(app, theme_mode)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
