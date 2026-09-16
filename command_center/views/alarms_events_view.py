from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..controller_service import ControllerService
from ..event_service import EventRecord, EventService
from ..widgets.common import MetricCell, muted_label


class AlarmsEventsView(QWidget):
    def __init__(
        self,
        event_service: EventService,
        controller_service: ControllerService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.event_service = event_service
        self.controller_service = controller_service

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(11)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title = QLabel("Alarms & Events")
        title.setObjectName("pageTitle")
        title_column.addWidget(title)
        title_column.addWidget(
            muted_label(
                "Alarm aktif, pemulihan, dan audit tersimpan lokal di SQLite"
            )
        )
        header.addLayout(title_column)
        header.addStretch()
        self.acknowledge_all_button = QPushButton("ACKNOWLEDGE ALL ACTIVE")
        self.acknowledge_all_button.clicked.connect(self._acknowledge_all)
        header.addWidget(self.acknowledge_all_button)
        root.addLayout(header)

        summary_frame = QFrame()
        summary_frame.setObjectName("summaryPanel")
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(8, 8, 8, 8)
        summary_layout.setSpacing(7)
        self.critical_metric = MetricCell("Active Critical")
        self.warning_metric = MetricCell("Active Warning")
        self.unacknowledged_metric = MetricCell("Unacknowledged")
        self.today_metric = MetricCell("Events Today")
        for metric in (
            self.critical_metric,
            self.warning_metric,
            self.unacknowledged_metric,
            self.today_metric,
        ):
            summary_layout.addWidget(metric, 1)
        root.addWidget(summary_frame)

        filter_frame = QFrame()
        filter_frame.setObjectName("contentPanel")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(7)

        self.controller_filter = QComboBox()
        self.controller_filter.addItem("ALL CONTROLLERS", "")
        self.severity_filter = QComboBox()
        for text, value in (
            ("ALL SEVERITY", ""),
            ("CRITICAL", "CRITICAL"),
            ("WARNING", "WARNING"),
            ("INFO", "INFO"),
            ("AUDIT", "AUDIT"),
        ):
            self.severity_filter.addItem(text, value)
        self.state_filter = QComboBox()
        for text, value in (
            ("ALL EVENTS", "all"),
            ("ACTIVE ALARMS", "active"),
            ("UNACKNOWLEDGED", "unacknowledged"),
            ("RESOLVED", "resolved"),
        ):
            self.state_filter.addItem(text, value)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search event...")
        self.search_input.setClearButtonEnabled(True)
        self.refresh_button = QPushButton("REFRESH")
        self.refresh_button.setObjectName("compactButton")
        self.export_button = QPushButton("EXPORT CSV")
        self.acknowledge_button = QPushButton("ACKNOWLEDGE SELECTED")

        filter_layout.addWidget(self.controller_filter, 2)
        filter_layout.addWidget(self.severity_filter, 1)
        filter_layout.addWidget(self.state_filter, 1)
        filter_layout.addWidget(self.search_input, 2)
        filter_layout.addWidget(self.refresh_button)
        filter_layout.addWidget(self.export_button)
        filter_layout.addWidget(self.acknowledge_button)
        root.addWidget(filter_frame)

        self.table = QTableWidget(0, 7)
        self.table.setObjectName("eventTable")
        self.table.setHorizontalHeaderLabels(
            [
                "TIME",
                "CONTROLLER",
                "SEVERITY",
                "CATEGORY",
                "EVENT",
                "STATUS",
                "ACK",
            ]
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.result_label = muted_label()
        root.addWidget(self.result_label)

        self.controller_filter.currentIndexChanged.connect(self.refresh)
        self.severity_filter.currentIndexChanged.connect(self.refresh)
        self.state_filter.currentIndexChanged.connect(self.refresh)
        self.search_input.textChanged.connect(self.refresh)
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button.clicked.connect(self._export_csv)
        self.acknowledge_button.clicked.connect(self._acknowledge_selected)
        self.event_service.events_changed.connect(self.refresh)
        self.controller_service.controllers_changed.connect(
            self._rebuild_controller_filter
        )

        self._rebuild_controller_filter()
        self.refresh()

    def refresh(self, *_args) -> None:
        records = self.event_service.query_events(**self._current_filters())
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            self._populate_row(row, record)
        self.table.setUpdatesEnabled(True)
        self.table.resizeRowsToContents()

        summary = self.event_service.summary()
        self.critical_metric.set_value(str(summary["critical"]))
        self.warning_metric.set_value(str(summary["warning"]))
        self.unacknowledged_metric.set_value(
            str(summary["unacknowledged"])
        )
        self.today_metric.set_value(str(summary["today"]))
        self.result_label.setText(
            f"Showing {len(records)} most recent matching events · "
            "retention 90 days"
        )

    def _populate_row(self, row: int, record: EventRecord) -> None:
        timestamp = self._display_time(record.occurred_at)
        controller = f"{record.controller_id} · {record.controller_name}"
        status = (
            "ACTIVE"
            if record.is_active
            else "RESOLVED"
            if record.resolved_at
            else "LOG"
        )
        acknowledged = "YES" if record.acknowledged else "—"
        values = [
            timestamp,
            controller,
            record.severity,
            record.category,
            record.message,
            status,
            acknowledged,
        ]
        severity_color = {
            "CRITICAL": QColor("#ff7c85"),
            "WARNING": QColor("#ffd77b"),
            "INFO": QColor("#8de0b1"),
            "AUDIT": QColor("#76b7ee"),
        }.get(record.severity, QColor("#dce8f5"))
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setData(Qt.ItemDataRole.UserRole, record.event_id)
            item.setToolTip(record.details or record.message)
            if column in {2, 5, 6}:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if column == 2:
                item.setForeground(severity_color)
            self.table.setItem(row, column, item)

    def _rebuild_controller_filter(self) -> None:
        selected = self.controller_filter.currentData()
        self.controller_filter.blockSignals(True)
        self.controller_filter.clear()
        self.controller_filter.addItem("ALL CONTROLLERS", "")
        for controller in self.controller_service.controllers:
            self.controller_filter.addItem(
                f"{controller.controller_id} · {controller.name}",
                controller.controller_id,
            )
        index = self.controller_filter.findData(selected)
        self.controller_filter.setCurrentIndex(max(0, index))
        self.controller_filter.blockSignals(False)

    def _acknowledge_selected(self) -> None:
        event_ids: list[int] = []
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item:
                event_ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
        count = self.event_service.acknowledge(event_ids)
        self.result_label.setText(
            f"{count} event acknowledged"
            if count
            else "Pilih alarm CRITICAL/WARNING yang belum di-acknowledge."
        )

    def _acknowledge_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "Acknowledge Active Alarms",
            "Acknowledge seluruh alarm aktif?\n\n"
            "Acknowledge tidak menghapus atau menyelesaikan alarm.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        count = self.event_service.acknowledge_all_active()
        self.result_label.setText(f"{count} active alarm acknowledged")

    def _export_csv(self) -> None:
        default_name = (
            "TLC_Events_"
            + datetime.now().strftime("%Y-%m-%d_%H%M%S")
            + ".csv"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Events",
            str(Path.home() / default_name),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            count = self.event_service.export_csv(
                path,
                **self._current_filters(),
            )
        except OSError as error:
            QMessageBox.critical(self, "Export Failed", str(error))
            return
        self.result_label.setText(f"{count} events exported to {path}")

    def _current_filters(self) -> dict[str, str]:
        return {
            "controller_id": str(self.controller_filter.currentData() or ""),
            "severity": str(self.severity_filter.currentData() or ""),
            "state": str(self.state_filter.currentData() or "all"),
            "search": self.search_input.text().strip(),
        }

    @staticmethod
    def _display_time(value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            return value
