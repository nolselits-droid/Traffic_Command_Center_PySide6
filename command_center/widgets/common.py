from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


def muted_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setProperty("muted", True)
    return label


def status_label(text: str, status: str = "online") -> QLabel:
    label = QLabel(text)
    label.setProperty("status", status)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


class MetricCell(QFrame):
    def __init__(self, title: str, value: str = "-", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCell")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(3)

        title_label = muted_label(title)
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
