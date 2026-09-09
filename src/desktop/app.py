from __future__ import annotations

import sys

# Lightweight - only subprocess/sys/playwright.sync_api.Error, none of
# PySide6/MainWindow's own heavy AI-SDK-pulling import graph. Safe to
# import at module level so the flag name below is the one real
# source of truth, never duplicated as a bare string literal.
from src.browser.chromium_bootstrap import (
    INTERNAL_PLAYWRIGHT_INSTALL_FLAG,
    run_playwright_install_entrypoint,
)


def main() -> int:
    """Launch the Mission Automation desktop application."""

    # Installer packaging: a frozen (PyInstaller) build re-invokes
    # ITSELF with this internal flag to run "playwright install
    # chromium" (see chromium_bootstrap.py's own docstring for why a
    # frozen build's sys.executable can't just take a plain "-m
    # playwright" argument the way a real python.exe can).
    #
    # Real-world finding: checking this flag first is not enough on
    # its own if the heavy imports below (PySide6, MainWindow, every
    # AI provider SDK MainWindow's own composition root pulls in)
    # happen at MODULE level - Python runs every top-level import the
    # moment this module is loaded, regardless of which branch main()
    # takes, so an earlier version of this file paid that same ~30-90s
    # import cost on EVERY invocation, including a pure install-and-
    # exit one, with zero visible progress - indistinguishable from a
    # genuine hang. Fixed: every import below is now local to the
    # branch that actually needs it, so this branch imports nothing
    # beyond chromium_bootstrap itself.
    if INTERNAL_PLAYWRIGHT_INSTALL_FLAG in sys.argv:
        return run_playwright_install_entrypoint()

    from PySide6.QtWidgets import QApplication

    from src.desktop import services
    from src.desktop.icons import app_icon
    from src.desktop.main_window import MainWindow
    from src.desktop.theme import apply_theme

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
