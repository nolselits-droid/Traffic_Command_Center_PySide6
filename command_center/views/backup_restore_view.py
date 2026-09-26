from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ..backup_restore_service import BackupRestoreService
from ..controller_service import ControllerService
from ..event_service import EventService
from ..widgets.common import MetricCell, muted_label, status_label


class BackupRestoreView(QWidget):
    def __init__(self, controller_service: ControllerService, event_service: EventService, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("backupRestorePage")
        self.controller_service = controller_service
        self.event_service = event_service
        self.backup_service = BackupRestoreService(controller_service, self)
        self.current_controller_id = ""
        self._busy = False
        self._staged = False
        self._selected_file: Path | None = None
        self._export_target: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 18)
        root.setSpacing(11)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Backup & Restore")
        title.setObjectName("pageTitle")
        titles.addWidget(title)
        titles.addWidget(muted_label("File JSON disimpan di PC · Network Setup selalu dipertahankan"))
        header.addLayout(titles)
        header.addStretch()
        self.controller_selector = QComboBox()
        self.controller_selector.currentIndexChanged.connect(self._controller_changed)
        header.addWidget(self.controller_selector)
        self.connection_label = status_label("● WAITING")
        header.addWidget(self.connection_label)
        root.addLayout(header)

        backup_panel = QFrame()
        backup_panel.setObjectName("contentPanel")
        backup_layout = QVBoxLayout(backup_panel)
        backup_title = QLabel("Create Backup File")
        backup_title.setObjectName("sectionTitle")
        backup_layout.addWidget(backup_title)
        backup_layout.addWidget(muted_label("Ambil seluruh konfigurasi tersimpan dari controller menjadi satu file di PC."))
        self.export_button = QPushButton("DOWNLOAD BACKUP TO PC")
        self.export_button.setObjectName("primaryButton")
        self.export_button.clicked.connect(self._export_backup)
        backup_layout.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(backup_panel)

        restore_panel = QFrame()
        restore_panel.setObjectName("contentPanel")
        restore_layout = QVBoxLayout(restore_panel)
        restore_title = QLabel("Validate & Restore From PC")
        restore_title.setObjectName("sectionTitle")
        restore_layout.addWidget(restore_title)
        file_row = QHBoxLayout()
        self.file_label = muted_label("No backup file selected")
        self.file_label.setWordWrap(True)
        self.choose_button = QPushButton("CHOOSE JSON FILE")
        self.choose_button.clicked.connect(self._choose_file)
        self.validate_button = QPushButton("VALIDATE FILE")
        self.validate_button.setObjectName("primaryButton")
        self.validate_button.clicked.connect(self._validate_file)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(self.choose_button)
        file_row.addWidget(self.validate_button)
        restore_layout.addLayout(file_row)

        preview = QFrame()
        preview.setObjectName("summaryPanel")
        preview_layout = QGridLayout(preview)
        self.source_metric = MetricCell("Source Controller")
        self.firmware_metric = MetricCell("Source Firmware")
        self.data_metric = MetricCell("Plans / Schedules / Holidays")
        self.traffic_metric = MetricCell("Active SG / Conflicts")
        self.checksum_metric = MetricCell("Checksum")
        for column, metric in enumerate((self.source_metric, self.firmware_metric, self.data_metric, self.traffic_metric, self.checksum_metric)):
            preview_layout.addWidget(metric, 0, column)
        restore_layout.addWidget(preview)

        mode_row = QHBoxLayout()
        self.traffic_mode = QRadioButton("Traffic & Operational Settings")
        self.traffic_mode.setChecked(True)
        self.full_mode = QRadioButton("Full Restore")
        mode_row.addWidget(self.traffic_mode)
        mode_row.addWidget(self.full_mode)
        mode_row.addStretch()
        restore_layout.addLayout(mode_row)
        warning = QLabel(
            "Traffic mode mengganti Plan, Stage, Schedule, Holiday dan setting operasional. "
            "Full mode mengganti seluruh konfigurasi dan identitas. Network Setup tidak berubah."
        )
        warning.setObjectName("readOnlyNote")
        warning.setWordWrap(True)
        restore_layout.addWidget(warning)
        action_row = QHBoxLayout()
        self.restore_button = QPushButton("RESTORE VALIDATED FILE")
        self.restore_button.setObjectName("dangerButton")
        self.restore_button.clicked.connect(self._restore)
        self.cancel_button = QPushButton("CANCEL VALIDATED FILE")
        self.cancel_button.clicked.connect(self._cancel_staged)
        action_row.addWidget(self.restore_button)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch()
        restore_layout.addLayout(action_row)
        root.addWidget(restore_panel)
        root.addStretch()
        self.message_label = status_label("SELECT A LIVE CONTROLLER")
        root.addWidget(self.message_label)

        self.backup_service.export_completed.connect(self._export_completed)
        self.backup_service.validated.connect(self._validated)
        self.backup_service.action_completed.connect(self._action_completed)
        self.backup_service.failed.connect(self._failed)
        self.backup_service.busy_changed.connect(self._busy_changed)
        self.backup_service.progress_changed.connect(self._progress_changed)
        self.controller_service.controllers_changed.connect(self._rebuild_controllers)
        self.controller_service.snapshot_updated.connect(self._snapshot_updated)
        self._rebuild_controllers()
        self._clear_preview()

    def _rebuild_controllers(self) -> None:
        previous = self.current_controller_id
        self.controller_selector.blockSignals(True)
        self.controller_selector.clear()
        for controller in self.controller_service.controllers:
            self.controller_selector.addItem(f"{controller.controller_id} · {controller.name}", controller.controller_id)
        index = self.controller_selector.findData(previous)
        self.controller_selector.setCurrentIndex(max(0, index))
        self.controller_selector.blockSignals(False)
        self.current_controller_id = str(self.controller_selector.currentData() or "")
        self._update_controls()

    def _controller_changed(self) -> None:
        if self._staged:
            return
        self.current_controller_id = str(self.controller_selector.currentData() or "")
        self._selected_file = None
        self.file_label.setText("No backup file selected")
        self._clear_preview()
        self._update_controls()

    def _snapshot_updated(self, controller_id: str) -> None:
        if controller_id == self.current_controller_id:
            self._update_controls()

    def _update_controls(self) -> None:
        snapshot = self.controller_service.get_controller(self.current_controller_id)
        online = bool(snapshot and snapshot.online)
        self.controller_selector.setEnabled(not self._busy and not self._staged)
        self.export_button.setEnabled(online and not self._busy and not self._staged)
        self.choose_button.setEnabled(online and not self._busy and not self._staged)
        self.validate_button.setEnabled(online and not self._busy and self._selected_file is not None and not self._staged)
        safe_restore = bool(online and snapshot and snapshot.safety_status == "OK" and snapshot.apply_state == "IDLE")
        self.restore_button.setEnabled(self._staged and safe_restore and not self._busy)
        self.cancel_button.setEnabled(self._staged and not self._busy)
        self.traffic_mode.setEnabled(self._staged and not self._busy)
        self.full_mode.setEnabled(self._staged and not self._busy)
        self.connection_label.setText("● CONTROLLER ONLINE" if online else "● CONTROLLER OFFLINE")
        self.connection_label.setProperty("status", "online" if online else "offline")
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

    def _choose_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Choose TLC Backup File", "", "TLC Backup (*.json);;JSON Files (*.json)")
        if not filename:
            return
        self._selected_file = Path(filename)
        self.file_label.setText(str(self._selected_file))
        self._set_message("FILE SELECTED · VALIDATE BEFORE RESTORE", "warning")
        self._update_controls()

    def _export_backup(self) -> None:
        default = f"TLC_Backup_{self.current_controller_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filename, _ = QFileDialog.getSaveFileName(self, "Save TLC Backup", default, "TLC Backup (*.json)")
        if not filename:
            return
        self._export_target = Path(filename)
        self.backup_service.export_backup(self.current_controller_id)

    def _export_completed(self, controller_id: str, content: bytes, _name: str) -> None:
        if controller_id != self.current_controller_id or self._export_target is None:
            return
        try:
            self._export_target.write_bytes(content)
        except OSError as exc:
            self._failed(controller_id, "export", f"File tidak dapat disimpan: {exc}")
            return
        self._set_message(f"BACKUP SAVED · {self._export_target}", "online")
        self._audit("Backup file exported", str(self._export_target))

    def _validate_file(self) -> None:
        if self._selected_file is None:
            return
        try:
            content = self._selected_file.read_bytes()
        except OSError as exc:
            self._failed(self.current_controller_id, "validate", f"File tidak dapat dibaca: {exc}")
            return
        self.backup_service.validate_backup(self.current_controller_id, content)

    def _validated(self, controller_id: str, payload: object) -> None:
        if controller_id != self.current_controller_id or not isinstance(payload, dict):
            return
        self._staged = True
        self.source_metric.set_value(f"ID {int(payload.get('sourceControllerId', 0)):03d} · {payload.get('sourceControllerName', '—')}")
        self.firmware_metric.set_value(str(payload.get("sourceFirmware") or "—"))
        self.data_metric.set_value(f"{payload.get('planCount', 0)} / {payload.get('scheduleCount', 0)} / {payload.get('holidayCount', 0)}")
        self.traffic_metric.set_value(f"{payload.get('activeSignalGroups', 0)} / {payload.get('conflictCount', 0)}")
        self.checksum_metric.set_value(str(payload.get("checksum") or "—"))
        self._set_message(str(payload.get("message") or "FILE VALID"), "online")
        self._audit("Backup file validated", self._selected_file.name if self._selected_file else "")
        self._update_controls()

    def _restore(self) -> None:
        mode = "full" if self.full_mode.isChecked() else "traffic"
        description = "FULL RESTORE mengganti seluruh konfigurasi dan identitas controller." if mode == "full" else "Traffic & Operational Settings mengganti Plan, Stage, Schedule, Holiday dan setting operasional."
        answer = QMessageBox.warning(
            self, "Confirm Controller Restore", f"{description}\n\nNetwork Setup tetap dipertahankan. Lanjutkan Restore?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.backup_service.restore(self.current_controller_id, mode)

    def _cancel_staged(self) -> None:
        self.backup_service.cancel(self.current_controller_id)

    def _action_completed(self, controller_id: str, action: str, payload: object) -> None:
        if controller_id != self.current_controller_id or not isinstance(payload, dict):
            return
        message = str(payload.get("message") or "Operation completed.")
        if action.startswith("restore-") or action == "cancel":
            self._staged = False
            self._selected_file = None
            self.file_label.setText("No backup file selected")
            self._clear_preview()
        self._set_message(message, "online")
        self._audit(f"Backup/Restore {action} completed", message)
        self._update_controls()

    def _failed(self, controller_id: str, action: str, message: str) -> None:
        if controller_id != self.current_controller_id:
            return
        self._set_message(f"{action.upper()} FAILED · {message}", "offline")
        QMessageBox.warning(self, "Backup & Restore", message)
        self._audit(f"Backup/Restore {action} failed", message)

    def _busy_changed(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self._set_message("CONTROLLER REQUEST IN PROGRESS...", "warning")
        self._update_controls()

    def _progress_changed(
        self,
        controller_id: str,
        action: str,
        received: int,
        total: int,
    ) -> None:
        if controller_id != self.current_controller_id or action != "export":
            return
        received_kb = max(0, received) / 1024
        if total > 0:
            self._set_message(
                f"DOWNLOADING BACKUP · {received_kb:.1f} / {total / 1024:.1f} KB",
                "warning",
            )
        else:
            self._set_message(
                f"DOWNLOADING BACKUP · {received_kb:.1f} KB",
                "warning",
            )

    def _clear_preview(self) -> None:
        for metric in (self.source_metric, self.firmware_metric, self.data_metric, self.traffic_metric, self.checksum_metric):
            metric.set_value("—")

    def _set_message(self, text: str, status: str) -> None:
        self.message_label.setText(text)
        self.message_label.setProperty("status", status)
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)

    def _audit(self, message: str, details: str) -> None:
        snapshot = self.controller_service.get_controller(self.current_controller_id)
        self.event_service.record_audit(
            self.current_controller_id,
            snapshot.name if snapshot else self.current_controller_id,
            message, details=details,
        )
