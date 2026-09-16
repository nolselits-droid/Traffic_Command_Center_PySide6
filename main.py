from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from command_center.main_window import MainWindow
from command_center.styles import DARK_THEME


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Traffic Command Center")
    app.setOrganizationName("TLC")
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_THEME)

    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
