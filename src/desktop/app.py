from __future__ import annotations

import sys
from typing import TYPE_CHECKING

# Lightweight - only subprocess/sys/playwright.sync_api.Error, none of
# PySide6/MainWindow's own heavy AI-SDK-pulling import graph. Safe to
# import at module level so the flag name below is the one real
# source of truth, never duplicated as a bare string literal.
from src.browser.chromium_bootstrap import (
    INTERNAL_PLAYWRIGHT_INSTALL_FLAG,
    run_playwright_install_entrypoint,
)

if TYPE_CHECKING:
    # Type-checking only - never actually imported at runtime, so this
    # does not reintroduce the heavy PySide6/MainWindow import cost
    # main()'s own docstring below explicitly keeps out of the
    # playwright-install branch.
    from PySide6.QtWidgets import QApplication

    from src.desktop.main_window import MainWindow


def _install_ctrl_c_handler(app: QApplication, window: MainWindow) -> None:
    """
    Real-world finding, 2026-09-30: stopping this app with Ctrl+C in
    its own launching terminal never ran MainWindow.closeEvent() at
    all - Qt's C++ event loop (app.exec()) blocks Python bytecode
    execution, so Python's default SIGINT handler (and any handler
    installed the ordinary way) never gets a chance to fire until
    control returns to Python. The terminal/OS then tears down the
    whole process tree directly, orphaning both browser workers' real
    Playwright Node driver subprocesses rather than letting
    _shutdown_browser_workers() stop them cleanly - the confirmed real
    cause of a recurring, unrelated-looking Node.js "EPIPE: broken
    pipe" crash trace in that same terminal after Ctrl+C.

    window.close() re-enters the exact same closeEvent() cleanup a
    normal window-close already uses (pending-render wait, then
    browser-worker shutdown) - it only needs Python to actually run. A
    short, silent timer is the standard, documented way to force that:
    Qt calls into Python once per interval regardless of what the
    event loop is otherwise doing, which is enough for the signal
    handler installed here to actually be invoked promptly instead of
    waiting on the next real GUI event that may not come. Parented to
    `app` so Qt's own object tree keeps the timer alive for as long as
    the application itself runs, rather than relying on a Python-level
    reference this function's own return would otherwise drop.
    """

    import signal

    from PySide6.QtCore import QTimer

    signal.signal(signal.SIGINT, lambda *_: window.close())

    keep_alive_timer = QTimer(app)
    keep_alive_timer.timeout.connect(lambda: None)
    keep_alive_timer.start(200)


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

    _install_ctrl_c_handler(app, window)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
