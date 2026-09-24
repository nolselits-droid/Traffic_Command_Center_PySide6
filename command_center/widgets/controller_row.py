from __future__ import annotations

from time import monotonic

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import ControllerMode, ControllerSnapshot
from .common import MetricCell, muted_label, status_label


class SignalMiniTile(QFrame):
    def __init__(self, number: int, aspect: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("signalMiniTile")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 4, 5, 4)
        layout.setSpacing(4)
        self.name_label = QLabel(f"SG{number}")
        self.value_label = QLabel()
        self.value_label.setObjectName("signalMiniLamp")
        self.value_label.setFixedSize(14, 14)
        self._aspect = "OFF"
        self._displayed_aspect = ""
        layout.addWidget(self.name_label)
        layout.addWidget(self.value_label)
        self.set_aspect(aspect)

    def set_aspect(self, aspect: str) -> None:
        normalized = aspect.upper() if aspect else "OFF"
        if normalized not in {
            "GREEN", "YELLOW", "RED", "OFF", "RED + YELLOW",
            "FLASH YELLOW 500", "FLASH YELLOW 1000",
        }:
            normalized = "OFF"
        self._aspect = normalized
        self.value_label.setToolTip(normalized.title())
        self.refresh_animation()

    def refresh_animation(self, now: float | None = None) -> None:
        timestamp = monotonic() if now is None else now
        displayed = self._aspect
        if self._aspect.startswith("FLASH YELLOW"):
            period_ms = 1000 if self._aspect.endswith("1000") else 500
            displayed = (
                "YELLOW" if int(timestamp * 1000 / period_ms) % 2 == 0 else "OFF"
            )
        elif self._aspect == "RED + YELLOW":
            displayed = "YELLOW"
        if displayed == self._displayed_aspect:
            return
        self._displayed_aspect = displayed
        self.value_label.setProperty("aspect", displayed)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)


class ControllerRow(QFrame):
    open_requested = Signal(str)

    def __init__(self, snapshot: ControllerSnapshot, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("controllerRow")
        self.controller_id = snapshot.controller_id
        self.signal_tiles: list[SignalMiniTile] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(13, 10, 13, 10)
        root.setSpacing(13)

        identity = QVBoxLayout()
        identity.setSpacing(3)
        self.name_label = QLabel(snapshot.name)
        self.name_label.setObjectName("sectionTitle")
        self.identity_label = muted_label()
        identity.addWidget(self.name_label)
        identity.addWidget(self.identity_label)
        root.addLayout(identity, 3)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(7)
        metrics.setVerticalSpacing(0)
        self.mode_metric = MetricCell("Mode")
        self.safety_metric = MetricCell("Safety")
        self.current_plan_metric = MetricCell("Current Plan")
        self.stage_metric = MetricCell("Current Stage")
        self.scheduled_plan_metric = MetricCell("Scheduled Plan")
        self.remaining_metric = MetricCell("Remaining")
        for column, widget in enumerate(
            [
                self.mode_metric,
                self.safety_metric,
                self.current_plan_metric,
                self.stage_metric,
                self.scheduled_plan_metric,
                self.remaining_metric,
            ]
        ):
            metrics.addWidget(widget, 0, column)
            metrics.setColumnStretch(column, 1)
        root.addLayout(metrics, 7)

        signal_area = QVBoxLayout()
        signal_area.setSpacing(4)
        signal_title = muted_label("Signal Groups")
        signal_area.addWidget(signal_title)
        self.signal_grid = QGridLayout()
        self.signal_grid.setHorizontalSpacing(4)
        self.signal_grid.setVerticalSpacing(4)
        signal_area.addLayout(self.signal_grid)
        root.addLayout(signal_area, 4)

        action_panel = QWidget()
        action_panel.setFixedWidth(174)
        actions = QVBoxLayout(action_panel)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.connection_label = status_label("ONLINE")
        self.connection_label.setProperty("compact", True)
        self.camera_label = muted_label()
        self.health_label = muted_label()
        for label in (
            self.connection_label,
            self.camera_label,
            self.health_label,
        ):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedWidth(174)
        self.open_button = QPushButton("OPEN")
        self.open_button.setObjectName("compactButton")
        self.open_button.clicked.connect(
            lambda: self.open_requested.emit(self.controller_id)
        )
        actions.addWidget(self.connection_label)
        actions.addWidget(self.camera_label)
        actions.addWidget(self.health_label)
        actions.addWidget(self.open_button)
        root.addWidget(action_panel, 0)

        self.update_snapshot(snapshot)

    def update_snapshot(self, snapshot: ControllerSnapshot) -> None:
        self.name_label.setText(snapshot.name)
        identity = (
            f"ID {snapshot.reported_controller_id:03d}"
            if snapshot.reported_controller_id is not None
            else snapshot.controller_id
        )
        self.identity_label.setText(
            f"{identity} · {snapshot.ip_address} · "
            f"{snapshot.network_interface.value}"
        )
        self.mode_metric.set_value(snapshot.mode.value)
        self.safety_metric.set_value(snapshot.safety_status)
        self.current_plan_metric.set_value(f"Plan {snapshot.current_plan:02d}")
        self.stage_metric.set_value(
            f"{snapshot.current_stage} / {snapshot.total_stages}"
        )
        self.scheduled_plan_metric.set_value(
            f"Plan {snapshot.scheduled_plan:02d}"
        )
        self.remaining_metric.set_value(
            "HOLD"
            if snapshot.mode == ControllerMode.HOLD
            else f"{snapshot.remaining_seconds:02d} s"
        )
        self.camera_label.setText(
            f"Camera {snapshot.camera_online_count}/{snapshot.camera_enabled_count} online"
        )
        if snapshot.last_update_at == "MOCK":
            self.health_label.setText("MOCK DATA")
        elif snapshot.response_time_ms is not None:
            self.health_label.setText(
                f"API {snapshot.response_time_ms} ms · errors "
                f"{snapshot.consecutive_failures}"
            )
        elif snapshot.consecutive_failures:
            self.health_label.setText(
                f"API timeout · errors {snapshot.consecutive_failures}"
            )
        else:
            self.health_label.setText("API waiting" if not snapshot.online else "API ready")
        if snapshot.last_update_at:
            self.health_label.setToolTip(
                f"Last successful update: {snapshot.last_update_at}"
            )
        self._update_signal_groups(snapshot)

        if not snapshot.online:
            status, text = "offline", "OFFLINE"
        elif snapshot.mode in {ControllerMode.HOLD, ControllerMode.FLASHING}:
            status, text = "warning", snapshot.mode.value
        elif snapshot.mode == ControllerMode.SAFETY:
            status, text = "offline", "SAFETY"
        else:
            status, text = "online", "ONLINE"

        self.connection_label.setText(text)
        self.connection_label.setProperty("status", status)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

    def _update_signal_groups(self, snapshot: ControllerSnapshot) -> None:
        if len(self.signal_tiles) != len(snapshot.signal_groups):
            while self.signal_grid.count():
                item = self.signal_grid.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()
            self.signal_tiles.clear()
            for index, signal_group in enumerate(snapshot.signal_groups):
                tile = SignalMiniTile(signal_group.number, signal_group.aspect)
                self.signal_grid.addWidget(tile, index // 6, index % 6)
                self.signal_tiles.append(tile)

        for tile, signal_group in zip(self.signal_tiles, snapshot.signal_groups):
            tile.set_aspect(signal_group.aspect)

    def refresh_signal_animation(self, now: float | None = None) -> None:
        for tile in self.signal_tiles:
            tile.refresh_animation(now)
