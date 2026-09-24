from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..controller_service import ControllerService
from ..widgets.common import muted_label, status_label
from ..widgets.controller_row import ControllerRow


class OverviewView(QWidget):
    controller_open_requested = Signal(str)

    def __init__(self, service: ControllerService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.rows: dict[str, ControllerRow] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(13)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title = QLabel("Controller Overview")
        title.setObjectName("pageTitle")
        subtitle = muted_label(
            "Monitoring lima lokasi persimpangan · Full HD layout"
        )
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch()
        self.summary_label = status_label("● 5/5 CONTROLLER ONLINE")
        header.addWidget(self.summary_label)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        self.rows_layout = QVBoxLayout(content)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(10)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.service.snapshot_updated.connect(self._update_controller)
        self.service.controllers_changed.connect(self._rebuild_rows)
        self.flash_timer = QTimer(self)
        self.flash_timer.setInterval(100)
        self.flash_timer.timeout.connect(self._refresh_signal_animation)
        self.flash_timer.start()
        self._rebuild_rows()

    def _refresh_signal_animation(self) -> None:
        now = monotonic()
        for row in self.rows.values():
            row.refresh_signal_animation(now)

    def _rebuild_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.rows.clear()
        for snapshot in self.service.controllers:
            row = ControllerRow(snapshot)
            row.open_requested.connect(self.controller_open_requested)
            self.rows[snapshot.controller_id] = row
            self.rows_layout.addWidget(row)
        self.rows_layout.addStretch()
        self._update_summary()

    def _update_controller(self, controller_id: str) -> None:
        snapshot = self.service.get_controller(controller_id)
        row = self.rows.get(controller_id)
        if snapshot and row:
            row.update_snapshot(snapshot)

        self._update_summary()

    def _update_summary(self) -> None:
        total = len(self.service.controllers)
        online_count = sum(item.online for item in self.service.controllers)
        if total:
            text = f"● {online_count}/{total} CONTROLLER ONLINE"
            status = "online" if online_count == total else "warning"
        else:
            text = "NO CONTROLLER CONFIGURED"
            status = "offline"
        self.summary_label.setText(text)
        self.summary_label.setProperty("status", status)
        self.summary_label.style().unpolish(self.summary_label)
        self.summary_label.style().polish(self.summary_label)
