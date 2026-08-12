from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from src.desktop.main_window import MainWindow


def main() -> int:
    """Launch the Mission Automation desktop application."""

    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
