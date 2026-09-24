from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..controller_service import ControllerService
from ..event_service import EventService
from ..widgets.common import muted_label


class ControllerConfigView(QWidget):
    def __init__(
        self,
        service: ControllerService,
        event_service: EventService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.event_service = event_service
        self.enabled_inputs: list[QCheckBox] = []
        self.name_inputs: list[QLineEdit] = []
        self.url_inputs: list[QLineEdit] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(13)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title = QLabel("Controller Connections")
        title.setObjectName("pageTitle")
        subtitle = muted_label(
            "Pilih Mock Data atau hubungkan maksimal lima ESP32-S3 melalui GET /api/status"
        )
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch()
        root.addLayout(header)

        panel = QFrame()
        panel.setObjectName("contentPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 14, 16, 16)
        panel_layout.setSpacing(12)

        mode_row = QHBoxLayout()
        mode_label = QLabel("Data Source")
        mode_label.setObjectName("sectionTitle")
        self.mode_input = QComboBox()
        self.mode_input.addItem("MOCK DATA · simulasi lokal", "mock")
        self.mode_input.addItem("LIVE API · ESP32-S3", "live")
        self.mode_input.currentIndexChanged.connect(self._mode_changed)
        mode_row.addWidget(mode_label)
        mode_row.addStretch()
        mode_row.addWidget(self.mode_input)
        panel_layout.addLayout(mode_row)

        note = muted_label(
            "LIVE API hanya membaca status. Aplikasi tidak mengirim SKIP, HOLD, "
            "FLASHING, perubahan Plan, atau konfigurasi apa pun ke controller."
        )
        note.setWordWrap(True)
        panel_layout.addWidget(note)

        grid_frame = QFrame()
        grid_frame.setObjectName("controllerConfigGrid")
        grid = QGridLayout(grid_frame)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        headers = ["Enable", "Slot", "Nama sementara", "IP / Base URL"]
        for column, text in enumerate(headers):
            label = muted_label(text)
            grid.addWidget(label, 0, column)

        entries = self.service.registry_entries()
        for index, entry in enumerate(entries):
            enabled = QCheckBox()
            enabled.setChecked(bool(entry["enabled"]))
            enabled.setToolTip("Aktifkan controller ini pada LIVE API")
            slot = QLabel(entry["controllerId"])
            slot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_input = QLineEdit(str(entry["displayName"]))
            name_input.setPlaceholderText(f"Controller {index + 1}")
            url_input = QLineEdit(str(entry["baseUrl"]))
            url_input.setPlaceholderText("http://192.168.10.21")

            row = index + 1
            grid.addWidget(enabled, row, 0, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(slot, row, 1)
            grid.addWidget(name_input, row, 2)
            grid.addWidget(url_input, row, 3)
            self.enabled_inputs.append(enabled)
            self.name_inputs.append(name_input)
            self.url_inputs.append(url_input)

        grid.setColumnStretch(2, 2)
        grid.setColumnStretch(3, 4)
        panel_layout.addWidget(grid_frame)

        actions = QHBoxLayout()
        self.result_label = muted_label()
        self.result_label.setWordWrap(True)
        actions.addWidget(self.result_label, 1)
        self.connect_button = QPushButton("SAVE & CONNECT")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._save_and_connect)
        actions.addWidget(self.connect_button)
        panel_layout.addLayout(actions)
        panel_layout.addStretch()
        root.addWidget(panel, 1)

        mode_index = self.mode_input.findData(self.service.mode)
        self.mode_input.setCurrentIndex(max(0, mode_index))
        self._mode_changed()

    def _mode_changed(self) -> None:
        live = self.mode_input.currentData() == "live"
        for widget in [
            *self.enabled_inputs,
            *self.name_inputs,
            *self.url_inputs,
        ]:
            widget.setEnabled(live)
        self.connect_button.setText(
            "SAVE & CONNECT" if live else "USE MOCK DATA"
        )

    def _save_and_connect(self) -> None:
        mode = str(self.mode_input.currentData())
        previous_mode = self.service.mode
        entries = []
        active_count = 0
        active_urls: set[str] = set()
        for index in range(5):
            enabled = self.enabled_inputs[index].isChecked()
            url = self.url_inputs[index].text().strip()
            if mode == "live" and enabled and not url:
                self.result_label.setText(
                    f"TLC-{index + 1:03d}: IP atau Base URL belum diisi."
                )
                return
            comparable_url = url.lower().rstrip("/")
            if mode == "live" and enabled and comparable_url in active_urls:
                self.result_label.setText(
                    f"TLC-{index + 1:03d}: alamat controller digunakan lebih dari satu slot."
                )
                return
            if mode == "live" and enabled:
                active_urls.add(comparable_url)
            active_count += int(enabled)
            entries.append(
                {
                    "controllerId": f"TLC-{index + 1:03d}",
                    "displayName": self.name_inputs[index].text().strip()
                    or f"Controller {index + 1}",
                    "enabled": enabled,
                    "baseUrl": url,
                }
            )

        if mode == "live" and active_count == 0:
            self.result_label.setText(
                "Aktifkan minimal satu controller untuk menggunakan LIVE API."
            )
            return

        if self.event_service:
            self.event_service.reset_monitoring_state()
        self.service.apply_settings(mode, entries)
        if self.event_service:
            self.event_service.record_audit(
                "SYSTEM",
                "Command Center",
                "Controller connection settings updated",
                details=(
                    f"Source: {previous_mode.upper()} -> {mode.upper()}; "
                    f"enabled controllers: {active_count if mode == 'live' else 5}"
                ),
            )
        if mode == "live":
            self.result_label.setText(
                f"LIVE API aktif untuk {active_count} controller · polling 1 detik · Traffic Control guarded."
            )
        else:
            self.result_label.setText(
                "Mock Data aktif. Tidak ada koneksi jaringan ke controller."
            )
