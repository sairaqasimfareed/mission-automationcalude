from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from src.desktop.icons import app_icon
from src.desktop.main_window import MainWindow
from src.desktop.theme import apply_theme


def main() -> int:
    """Launch the Mission Automation desktop application."""

    app = QApplication(sys.argv)
    app.setApplicationName("Mission Automation")
    app.setWindowIcon(app_icon())

    apply_theme(app)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
