from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QTime, QTimer, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ..controller_service import ControllerService
from ..event_service import EventService
from ..system_settings_service import (
    ControllerSystemSettings,
    ControllerTimeStatus,
    SystemActionResult,
    SystemSettingsService,
)
from ..widgets.common import MetricCell, muted_label, status_label
from .display_layout_editor import DisplayLayoutEditor


class SystemSettingsView(QWidget):
    def __init__(
        self,
        controller_service: ControllerService,
        event_service: EventService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("systemSettingsPage")
        self.controller_service = controller_service
        self.event_service = event_service
        self.settings_service = SystemSettingsService(controller_service, self)
        self.current_controller_id = ""
        self.current_settings: ControllerSystemSettings | None = None
        self.current_time: ControllerTimeStatus | None = None
        self._time_received_at: datetime | None = None
        self._active = False
        self._busy = False
        self._loading_form = False
        self._layout_data_signature: tuple[object, ...] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("System Settings")
        title.setObjectName("pageTitle")
        titles.addWidget(title)
        titles.addWidget(
            muted_label(
                "Controller identity, operational timing, startup pattern, SG names, RTC, dan network information"
            )
        )
        header.addLayout(titles)
        header.addStretch()
        self.refresh_button = QPushButton("REFRESH")
        self.refresh_button.setProperty("systemAction", True)
        self.refresh_button.clicked.connect(self._load_current)
        header.addWidget(self.refresh_button)
        self.controller_selector = QComboBox()
        self.controller_selector.setMinimumWidth(245)
        self.controller_selector.currentIndexChanged.connect(
            self._controller_changed
        )
        header.addWidget(self.controller_selector)
        self.connection_label = status_label("● WAITING", "offline")
        header.addWidget(self.connection_label)
        root.addLayout(header)

        summary = QFrame()
        summary.setObjectName("summaryPanel")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(10, 8, 10, 8)
        summary_layout.setSpacing(7)
        self.identity_metric = MetricCell("Controller")
        self.firmware_metric = MetricCell("Firmware")
        self.traffic_metric = MetricCell("Traffic Configuration")
        self.apply_metric = MetricCell("Safe Apply")
        self.storage_metric = MetricCell("System NVS")
        for column, metric in enumerate(
            (
                self.identity_metric,
                self.firmware_metric,
                self.traffic_metric,
                self.apply_metric,
                self.storage_metric,
            )
        ):
            summary_layout.addWidget(metric, 0, column)
        root.addWidget(summary)

        self.guard_label = status_label(
            "SELECT A LIVE CONTROLLER",
            "offline",
        )
        root.addWidget(self.guard_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("systemSettingsTabs")
        self.tabs.addTab(self._build_general_tab(), "IDENTITY & OPERATIONAL")
        self.tabs.addTab(self._build_startup_tab(), "STARTUP PATTERN")
        self.tabs.addTab(self._build_sg_names_tab(), "SIGNAL GROUP NAMES")
        self.tabs.addTab(self._build_time_network_tab(), "RTC & NETWORK")
        self.intersection_layout_editor = DisplayLayoutEditor(
            controller_service,
            "intersection",
            self,
        )
        self.camera_layout_editor = DisplayLayoutEditor(
            controller_service,
            "camera",
            self,
        )
        self.tabs.addTab(
            self.intersection_layout_editor,
            "INTERSECTION LAYOUT",
        )
        self.tabs.addTab(self.camera_layout_editor, "CAMERA LAYOUT")
        self.message_label = status_label("SYSTEM SETTINGS READY", "online")
        self.message_label.setProperty("compactStatus", True)
        self.message_label.setMinimumWidth(190)
        self.message_label.setMaximumWidth(300)
        self.message_label.setFixedHeight(25)
        self.tabs.setCornerWidget(
            self.message_label,
            Qt.Corner.TopRightCorner,
        )
        root.addWidget(self.tabs, 1)

        self.settings_service.system_loaded.connect(self._system_loaded)
        self.settings_service.time_loaded.connect(self._time_loaded)
        self.settings_service.action_completed.connect(self._action_completed)
        self.settings_service.request_failed.connect(self._request_failed)
        self.settings_service.busy_changed.connect(self._busy_changed)
        self.controller_service.controllers_changed.connect(
            self._rebuild_controllers
        )
        self.controller_service.snapshot_updated.connect(
            self._snapshot_updated
        )

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_time_display)
        self._clock_timer.start()
        self._rebuild_controllers()
        self._update_controls()

    def _build_general_tab(self) -> QWidget:
        container, layout = self._scroll_tab()

        identity_panel = self._panel("Controller Identity")
        identity_layout = identity_panel.layout()
        identity_layout.addWidget(
            muted_label(
                "Identitas ini ditampilkan pada dashboard, event log, backup, dan daftar controller."
            )
        )
        identity_form = QFormLayout()
        self.controller_id_input = QSpinBox()
        self.controller_id_input.setRange(1, 9999)
        self.controller_id_input.valueChanged.connect(self._form_changed)
        self.controller_name_input = QLineEdit()
        self.controller_name_input.setMaxLength(31)
        self.controller_name_input.textChanged.connect(self._form_changed)
        identity_form.addRow("Controller ID", self.controller_id_input)
        identity_form.addRow("Controller Name", self.controller_name_input)
        identity_layout.addLayout(identity_form)
        layout.addWidget(identity_panel)

        operation_panel = self._panel("Operational Timing")
        operation_layout = operation_panel.layout()
        operation_form = QFormLayout()
        self.safe_apply_all_red_input = QSpinBox()
        self.safe_apply_all_red_input.setRange(1, 10)
        self.safe_apply_all_red_input.setSuffix(" seconds")
        self.safe_apply_all_red_input.valueChanged.connect(self._form_changed)
        self.hold_duration_input = QSpinBox()
        self.hold_duration_input.setRange(5, 900)
        self.hold_duration_input.setSuffix(" seconds")
        self.hold_duration_input.valueChanged.connect(self._form_changed)
        self.min_green_input = QSpinBox()
        self.min_green_input.setRange(5, 120)
        self.min_green_input.setSuffix(" seconds")
        self.min_green_input.valueChanged.connect(self._form_changed)
        operation_form.addRow(
            "Safe Apply All Red",
            self.safe_apply_all_red_input,
        )
        operation_form.addRow("Hold Duration", self.hold_duration_input)
        operation_form.addRow(
            "Minimum Green Before Skip",
            self.min_green_input,
        )
        operation_layout.addLayout(operation_form)
        effect = QLabel(
            "Safe Apply All Red berlaku pada transisi berikutnya. Hold Duration "
            "berlaku pada HOLD berikutnya, sedangkan Minimum Green berlaku pada "
            "permintaan SKIP berikutnya. Tidak membutuhkan Safe Apply."
        )
        effect.setObjectName("readOnlyNote")
        effect.setWordWrap(True)
        operation_layout.addWidget(effect)
        layout.addWidget(operation_panel)

        action_row = QHBoxLayout()
        self.save_general_button = QPushButton("SAVE IDENTITY & OPERATIONAL")
        self.save_general_button.setProperty("systemAction", True)
        self.save_general_button.setProperty("actionRole", "confirm")
        self.save_general_button.clicked.connect(self._save_general)
        action_row.addWidget(self.save_general_button)
        action_row.addStretch()
        layout.addLayout(action_row)
        layout.addStretch()
        return container

    def _build_startup_tab(self) -> QWidget:
        container, layout = self._scroll_tab()
        panel = self._panel("Startup Pattern Duration")
        panel_layout = panel.layout()
        form = QFormLayout()
        self.startup_flashing_input = QSpinBox()
        self.startup_flashing_input.setRange(0, 999)
        self.startup_flashing_input.setSuffix(" seconds")
        self.startup_flashing_input.valueChanged.connect(self._form_changed)
        self.startup_all_red_input = QSpinBox()
        self.startup_all_red_input.setRange(0, 999)
        self.startup_all_red_input.setSuffix(" seconds")
        self.startup_all_red_input.valueChanged.connect(self._form_changed)
        form.addRow("Yellow Flashing 500 ms", self.startup_flashing_input)
        form.addRow("All Red", self.startup_all_red_input)
        panel_layout.addLayout(form)
        note = QLabel(
            "Urutan startup normal: Yellow Flashing 500 ms, kemudian All Red, "
            "lalu Schedule/Plan dimulai. Nilai 0 melewati phase tersebut. "
            "Perubahan berlaku pada startup controller berikutnya."
        )
        note.setObjectName("readOnlyNote")
        note.setWordWrap(True)
        panel_layout.addWidget(note)
        layout.addWidget(panel)
        self.save_startup_button = QPushButton("SAVE STARTUP PATTERN")
        self.save_startup_button.setProperty("systemAction", True)
        self.save_startup_button.setProperty("actionRole", "confirm")
        self.save_startup_button.clicked.connect(self._save_startup)
        layout.addWidget(
            self.save_startup_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        layout.addStretch()
        return container

    def _build_sg_names_tab(self) -> QWidget:
        container, layout = self._scroll_tab()
        panel = self._panel("Signal Group Identification")
        panel_layout = panel.layout()
        panel_layout.addWidget(
            muted_label(
                "Nama SG dipakai pada Overview, Live View, dan Traffic Configuration. Maksimum 40 karakter per SG."
            )
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.sg_name_inputs: list[QLineEdit] = []
        for index in range(12):
            label = QLabel(f"SG{index + 1}")
            field = QLineEdit()
            field.setMaxLength(40)
            field.setPlaceholderText(f"Signal Group {index + 1}")
            field.textChanged.connect(self._form_changed)
            self.sg_name_inputs.append(field)
            column = 0 if index < 6 else 2
            row = index if index < 6 else index - 6
            grid.addWidget(label, row, column)
            grid.addWidget(field, row, column + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        panel_layout.addLayout(grid)
        layout.addWidget(panel)
        self.save_sg_names_button = QPushButton("SAVE SG NAMES")
        self.save_sg_names_button.setProperty("systemAction", True)
        self.save_sg_names_button.setProperty("actionRole", "confirm")
        self.save_sg_names_button.clicked.connect(self._save_sg_names)
        layout.addWidget(
            self.save_sg_names_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        layout.addStretch()
        return container

    def _build_time_network_tab(self) -> QWidget:
        container, layout = self._scroll_tab()

        time_panel = self._panel("RTC Time Synchronization")
        time_layout = time_panel.layout()
        metrics = QGridLayout()
        self.controller_time_value = QLabel("--:--:--  --/--/----")
        self.pc_time_value = QLabel("--:--:--  --/--/----")
        self.time_difference_value = QLabel("—")
        for row, (title, value) in enumerate(
            (
                ("Controller RTC", self.controller_time_value),
                ("Command Center PC", self.pc_time_value),
                ("Difference", self.time_difference_value),
            )
        ):
            metrics.addWidget(muted_label(title), row, 0)
            metrics.addWidget(value, row, 1)
        metrics.setColumnStretch(1, 1)
        time_layout.addLayout(metrics)
        sync_row = QHBoxLayout()
        self.sync_pc_button = QPushButton("SYNC FROM PC")
        self.sync_pc_button.setProperty("systemAction", True)
        self.sync_pc_button.clicked.connect(self._sync_from_pc)
        sync_row.addWidget(self.sync_pc_button)
        sync_row.addStretch()
        time_layout.addLayout(sync_row)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Manual Date"))
        self.manual_date_input = QDateEdit()
        self.manual_date_input.setCalendarPopup(True)
        self.manual_date_input.setDisplayFormat("dd/MM/yyyy")
        self.manual_date_input.setMinimumDate(QDate(2000, 1, 1))
        self.manual_date_input.setMaximumDate(QDate(2099, 12, 31))
        manual_row.addWidget(self.manual_date_input)
        manual_row.addWidget(QLabel("Time"))
        self.manual_time_input = QTimeEdit()
        self.manual_time_input.setDisplayFormat("HH:mm:ss")
        manual_row.addWidget(self.manual_time_input)
        self.set_manual_time_button = QPushButton("SET MANUAL RTC")
        self.set_manual_time_button.setProperty("systemAction", True)
        self.set_manual_time_button.clicked.connect(self._set_manual_time)
        manual_row.addWidget(self.set_manual_time_button)
        manual_row.addStretch()
        time_layout.addLayout(manual_row)
        warning = QLabel(
            "Mengubah RTC dapat langsung mengubah Schedule dan Plan yang dipilih. "
            "Selisih 60 detik atau lebih selalu memerlukan konfirmasi khusus."
        )
        warning.setObjectName("readOnlyNote")
        warning.setWordWrap(True)
        time_layout.addWidget(warning)
        layout.addWidget(time_panel)

        network_panel = self._panel("Network Information · Read Only")
        network_layout = network_panel.layout()
        network_form = QFormLayout()
        self.interface_value = QLabel("—")
        self.address_mode_value = QLabel("—")
        self.current_ip_value = QLabel("—")
        self.subnet_value = QLabel("—")
        self.gateway_value = QLabel("—")
        self.dns_value = QLabel("—")
        network_form.addRow("Selected Interface", self.interface_value)
        network_form.addRow("Address Mode", self.address_mode_value)
        network_form.addRow("Current IP", self.current_ip_value)
        network_form.addRow("Subnet", self.subnet_value)
        network_form.addRow("Gateway", self.gateway_value)
        network_form.addRow("DNS", self.dns_value)
        network_layout.addLayout(network_form)
        network_note = QLabel(
            "Network tidak dapat diubah dari Command Center. Gunakan Network Setup "
            "Mode saat startup dengan GPIO38 aktif LOW untuk memilih Ethernet/Wi-Fi "
            "dan mengubah DHCP atau Static IP."
        )
        network_note.setObjectName("readOnlyNote")
        network_note.setWordWrap(True)
        network_layout.addWidget(network_note)
        layout.addWidget(network_panel)
        layout.addStretch()
        return container

    @staticmethod
    def _scroll_tab() -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        scroll.setWidget(body)
        return scroll, layout

    @staticmethod
    def _panel(title_text: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("contentPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(9)
        title = QLabel(title_text)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        return panel

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        if active:
            self._load_current()
        else:
            self.settings_service.cancel()

    def _rebuild_controllers(self) -> None:
        previous = self.current_controller_id
        self.controller_selector.blockSignals(True)
        self.controller_selector.clear()
        for controller in self.controller_service.controllers:
            self.controller_selector.addItem(
                f"{controller.controller_id} · {controller.name}",
                controller.controller_id,
            )
        index = self.controller_selector.findData(previous)
        self.controller_selector.setCurrentIndex(max(0, index))
        self.controller_selector.blockSignals(False)
        self.current_controller_id = str(
            self.controller_selector.currentData() or ""
        )
        if self.current_controller_id:
            self._set_layout_controller(self.current_controller_id)
        else:
            self._layout_data_signature = None
        self.current_settings = None
        self.current_time = None
        self._time_received_at = None
        self._clear_form()
        if self._active:
            self._load_current()
        self._update_controls()

    def _controller_changed(self) -> None:
        if self._busy:
            return
        self.current_controller_id = str(
            self.controller_selector.currentData() or ""
        )
        if self.current_controller_id:
            self._set_layout_controller(self.current_controller_id)
        else:
            self._layout_data_signature = None
        self.current_settings = None
        self.current_time = None
        self._time_received_at = None
        self._clear_form()
        self._load_current()

    def _snapshot_updated(self, controller_id: str) -> None:
        if controller_id == self.current_controller_id:
            snapshot = self.controller_service.get_controller(controller_id)
            index = self.controller_selector.findData(controller_id)
            if snapshot is not None and index >= 0:
                self.controller_selector.setItemText(
                    index,
                    f"{snapshot.controller_id} · {snapshot.name}",
                )
                signature = self._make_layout_data_signature(snapshot)
                if signature != self._layout_data_signature:
                    self.intersection_layout_editor.sync_controller_data(
                        controller_id
                    )
                    self.camera_layout_editor.sync_controller_data(
                        controller_id
                    )
                    self._layout_data_signature = signature
            self._update_summary()
            self._update_controls()

    def _set_layout_controller(self, controller_id: str) -> None:
        snapshot = self.controller_service.get_controller(controller_id)
        if snapshot is None:
            self._layout_data_signature = None
            return
        self.intersection_layout_editor.set_controller(controller_id)
        self.camera_layout_editor.set_controller(controller_id)
        self._layout_data_signature = self._make_layout_data_signature(
            snapshot
        )

    @staticmethod
    def _make_layout_data_signature(snapshot) -> tuple[object, ...]:
        return (
            snapshot.active_signal_groups,
            tuple(
                (signal.number, signal.name)
                for signal in snapshot.signal_groups
            ),
            tuple(
                (camera.camera_id, camera.name, camera.enabled)
                for camera in snapshot.cameras
            ),
        )

    def _load_current(self) -> None:
        if not self._active or not self.current_controller_id or self._busy:
            return
        snapshot = self.controller_service.get_controller(
            self.current_controller_id
        )
        if snapshot is None or not snapshot.online:
            self._set_message(
                "CONTROLLER OFFLINE · SYSTEM SETTINGS CANNOT BE LOADED",
                "offline",
            )
            self._update_controls()
            return
        self._set_message("LOADING SYSTEM SETTINGS...", "warning")
        self.settings_service.load_all(self.current_controller_id)

    def _system_loaded(self, controller_id: str, payload: object) -> None:
        if (
            controller_id != self.current_controller_id
            or not isinstance(payload, ControllerSystemSettings)
        ):
            return
        self.current_settings = payload
        self._populate_system(payload)
        self._update_summary()
        self._set_message("SYSTEM SETTINGS LOADED", "online")
        self._update_controls()

    def _time_loaded(self, controller_id: str, payload: object) -> None:
        if (
            controller_id != self.current_controller_id
            or not isinstance(payload, ControllerTimeStatus)
        ):
            return
        self.current_time = payload
        self._time_received_at = datetime.now()
        value = payload.as_datetime()
        if value is not None:
            self.manual_date_input.setDate(
                QDate(value.year, value.month, value.day)
            )
            self.manual_time_input.setTime(
                QTime(value.hour, value.minute, value.second)
            )
        self._update_time_display()
        self._update_controls()

    def _populate_system(self, settings: ControllerSystemSettings) -> None:
        self._loading_form = True
        try:
            self.controller_id_input.setValue(settings.controller_id)
            self.controller_name_input.setText(settings.controller_name)
            self.safe_apply_all_red_input.setValue(settings.all_red_seconds)
            self.hold_duration_input.setValue(settings.hold_duration)
            self.min_green_input.setValue(settings.min_green_before_skip)
            self.startup_flashing_input.setValue(settings.startup_flashing)
            self.startup_all_red_input.setValue(settings.startup_all_red)
            for index, field in enumerate(self.sg_name_inputs):
                field.setText(settings.sg_names[index])
            self.interface_value.setText(settings.selected_interface)
            self.address_mode_value.setText(
                "STATIC" if settings.network_mode == 1 else "DHCP"
            )
            self.current_ip_value.setText(settings.current_ip)
            self.subnet_value.setText(settings.static_subnet)
            self.gateway_value.setText(settings.static_gateway)
            self.dns_value.setText(settings.static_dns)
        finally:
            self._loading_form = False

    def _clear_form(self) -> None:
        self._loading_form = True
        try:
            self.controller_id_input.setValue(1)
            self.controller_name_input.clear()
            self.safe_apply_all_red_input.setValue(3)
            self.hold_duration_input.setValue(30)
            self.min_green_input.setValue(15)
            self.startup_flashing_input.setValue(0)
            self.startup_all_red_input.setValue(0)
            for field in self.sg_name_inputs:
                field.clear()
            for label in (
                self.interface_value,
                self.address_mode_value,
                self.current_ip_value,
                self.subnet_value,
                self.gateway_value,
                self.dns_value,
            ):
                label.setText("—")
            self.controller_time_value.setText("--:--:--  --/--/----")
            self.time_difference_value.setText("—")
        finally:
            self._loading_form = False

    def _form_changed(self, *_args) -> None:
        if not self._loading_form:
            self._update_controls()

    def _general_changes(self) -> list[tuple[str, str, str]]:
        current = self.current_settings
        if current is None:
            return []
        values = (
            ("Controller ID", str(current.controller_id), str(self.controller_id_input.value())),
            ("Controller Name", current.controller_name, self.controller_name_input.text().strip()),
            ("Safe Apply All Red", f"{current.all_red_seconds} s", f"{self.safe_apply_all_red_input.value()} s"),
            ("Hold Duration", f"{current.hold_duration} s", f"{self.hold_duration_input.value()} s"),
            ("Minimum Green Before Skip", f"{current.min_green_before_skip} s", f"{self.min_green_input.value()} s"),
        )
        return [item for item in values if item[1] != item[2]]

    def _startup_changes(self) -> list[tuple[str, str, str]]:
        current = self.current_settings
        if current is None:
            return []
        values = (
            ("Yellow Flashing", f"{current.startup_flashing} s", f"{self.startup_flashing_input.value()} s"),
            ("Startup All Red", f"{current.startup_all_red} s", f"{self.startup_all_red_input.value()} s"),
        )
        return [item for item in values if item[1] != item[2]]

    def _sg_name_changes(self) -> list[tuple[int, str, str]]:
        current = self.current_settings
        if current is None:
            return []
        changes: list[tuple[int, str, str]] = []
        for index, field in enumerate(self.sg_name_inputs):
            old = current.sg_names[index]
            new = field.text().strip()
            if old != new:
                changes.append((index + 1, old, new))
        return changes

    def _write_block_reason(self) -> str:
        snapshot = self.controller_service.get_controller(
            self.current_controller_id
        )
        if snapshot is None or not snapshot.online:
            return "CONTROLLER OFFLINE"
        if self._busy:
            return "CONTROLLER REQUEST IN PROGRESS"
        if snapshot.apply_state != "IDLE":
            return f"SAFE APPLY {snapshot.apply_state} · SAVE BLOCKED"
        if snapshot.editor_editing:
            return "TRAFFIC CONFIGURATION DRAFT OPEN · SAVE BLOCKED"
        if snapshot.config_dirty:
            return "TRAFFIC CONFIGURATION RAM MODIFIED · SAVE BLOCKED"
        if snapshot.safety_status != "OK":
            return f"SAFETY {snapshot.safety_status} · SAVE BLOCKED"
        return ""

    def _update_controls(self) -> None:
        snapshot = self.controller_service.get_controller(
            self.current_controller_id
        )
        online = bool(snapshot and snapshot.online)
        loaded = self.current_settings is not None
        editable = bool(online and loaded and not self._busy)
        block_reason = self._write_block_reason()
        can_write = editable and not block_reason

        self.controller_selector.setEnabled(not self._busy)
        self.refresh_button.setEnabled(bool(online and not self._busy))
        for widget in (
            self.controller_id_input,
            self.controller_name_input,
            self.safe_apply_all_red_input,
            self.hold_duration_input,
            self.min_green_input,
            self.startup_flashing_input,
            self.startup_all_red_input,
            *self.sg_name_inputs,
            self.manual_date_input,
            self.manual_time_input,
        ):
            widget.setEnabled(editable)

        valid_name = bool(self.controller_name_input.text().strip())
        self.save_general_button.setEnabled(
            can_write
            and valid_name
            and bool(
                self._general_changes()
                or (
                    self.current_settings
                    and self.current_settings.system_dirty
                )
            )
        )
        self.save_startup_button.setEnabled(
            can_write and bool(self._startup_changes())
        )
        self.save_sg_names_button.setEnabled(
            can_write
            and bool(
                self._sg_name_changes()
                or (
                    self.current_settings
                    and self.current_settings.sg_names_dirty
                )
            )
        )
        rtc_ready = bool(
            can_write
            and self.current_time
            and self.current_time.rtc_available
            and not self.current_time.apply_busy
        )
        self.sync_pc_button.setEnabled(rtc_ready)
        self.set_manual_time_button.setEnabled(rtc_ready)

        if block_reason:
            self.guard_label.setText(block_reason)
            self.guard_label.setProperty(
                "status",
                "warning" if online else "offline",
            )
        else:
            self.guard_label.setText("READY · CONTROLLER ACCEPTS SYSTEM CHANGES")
            self.guard_label.setProperty("status", "online")
        self.guard_label.style().unpolish(self.guard_label)
        self.guard_label.style().polish(self.guard_label)

        self.connection_label.setText(
            "● CONTROLLER ONLINE" if online else "● CONTROLLER OFFLINE"
        )
        self.connection_label.setProperty(
            "status",
            "online" if online else "offline",
        )
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)
        self._update_summary()

    def _update_summary(self) -> None:
        snapshot = self.controller_service.get_controller(
            self.current_controller_id
        )
        settings = self.current_settings
        if snapshot is None:
            self.identity_metric.set_value("—")
            self.firmware_metric.set_value("—")
            self.traffic_metric.set_value("—")
            self.apply_metric.set_value("—")
            self.storage_metric.set_value("—")
            return
        identity = (
            f"ID {settings.controller_id:03d} · {settings.controller_name}"
            if settings
            else f"{snapshot.controller_id} · {snapshot.name}"
        )
        self.identity_metric.set_value(identity)
        self.firmware_metric.set_value(snapshot.firmware_version)
        traffic = (
            "DRAFT MODIFIED"
            if snapshot.editor_editing and snapshot.editor_modified
            else "DRAFT OPEN"
            if snapshot.editor_editing
            else "RAM MODIFIED"
            if snapshot.config_dirty
            else "READY"
        )
        self.traffic_metric.set_value(traffic)
        self.apply_metric.set_value(snapshot.apply_state)
        storage = "MODIFIED" if settings and (
            settings.system_dirty or settings.sg_names_dirty
        ) else "SAVED / CLEAN"
        if settings and settings.restart_required:
            storage += " · RESTART REQUIRED"
        self.storage_metric.set_value(storage)

    def _save_general(self) -> None:
        changes = self._general_changes()
        name = self.controller_name_input.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                "System Settings",
                "Controller Name tidak boleh kosong.",
            )
            return
        if (
            not changes
            and self.current_settings
            and self.current_settings.system_dirty
        ):
            changes.append(
                ("Pending System Settings", "RAM MODIFIED", "SAVE TO NVS")
            )
        if not self._confirm_changes(
            "Save Identity & Operational",
            changes,
            "Perubahan disimpan langsung ke NVS dan tidak membutuhkan Safe Apply.",
        ):
            return
        self.settings_service.save_general(
            self.current_controller_id,
            self.controller_id_input.value(),
            name,
            self.safe_apply_all_red_input.value(),
            self.hold_duration_input.value(),
            self.min_green_input.value(),
        )

    def _save_startup(self) -> None:
        changes = self._startup_changes()
        if not self._confirm_changes(
            "Save Startup Pattern",
            changes,
            "Setting baru berlaku pada startup controller berikutnya.",
        ):
            return
        self.settings_service.save_startup(
            self.current_controller_id,
            self.startup_flashing_input.value(),
            self.startup_all_red_input.value(),
        )

    def _save_sg_names(self) -> None:
        changes = self._sg_name_changes()
        summary = [
            (f"SG{number}", old or "(empty)", new or "(empty)")
            for number, old, new in changes
        ]
        if (
            not summary
            and self.current_settings
            and self.current_settings.sg_names_dirty
        ):
            summary.append(
                ("Pending SG Names", "RAM MODIFIED", "SAVE TO NVS")
            )
        if not self._confirm_changes(
            "Save Signal Group Names",
            summary,
            "Nama baru langsung digunakan oleh dashboard dan editor. Safe Apply tidak diperlukan.",
        ):
            return
        self.settings_service.save_signal_group_names(
            self.current_controller_id,
            [(number, new) for number, _old, new in changes],
        )

    def _sync_from_pc(self) -> None:
        value = datetime.now().replace(microsecond=0)
        difference = self._time_difference_seconds()
        warning = (
            f"Selisih RTC dan PC adalah {difference:+d} detik. "
            if difference is not None
            else ""
        )
        if difference is not None and abs(difference) >= 60:
            warning += (
                "Perubahan ini dapat langsung mengganti Schedule/Plan aktif.\n\n"
            )
        warning += (
            f"Set RTC controller menjadi {value.strftime('%H:%M:%S  %d/%m/%Y')}?"
        )
        answer = QMessageBox.warning(
            self,
            "Synchronize Controller RTC",
            warning,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.settings_service.set_time(self.current_controller_id, value)

    def _set_manual_time(self) -> None:
        date_value = self.manual_date_input.date()
        time_value = self.manual_time_input.time()
        value = datetime(
            date_value.year(),
            date_value.month(),
            date_value.day(),
            time_value.hour(),
            time_value.minute(),
            time_value.second(),
        )
        answer = QMessageBox.warning(
            self,
            "Set Manual Controller RTC",
            "Set RTC controller menjadi "
            f"{value.strftime('%H:%M:%S  %d/%m/%Y')}?\n\n"
            "Perubahan waktu dapat langsung mengganti Schedule/Plan aktif.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.settings_service.set_time(self.current_controller_id, value)

    def _confirm_changes(
        self,
        title: str,
        changes: list[tuple[str, str, str]],
        effect: str,
    ) -> bool:
        if not changes:
            return False
        lines = [
            f"{name}:\n  {old}  →  {new}"
            for name, old, new in changes
        ]
        message = "\n\n".join(lines) + f"\n\n{effect}\n\nContinue?"
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _action_completed(
        self,
        controller_id: str,
        action: str,
        payload: object,
    ) -> None:
        if (
            controller_id != self.current_controller_id
            or not isinstance(payload, SystemActionResult)
        ):
            return
        self._set_message(payload.message, "online")
        snapshot = self.controller_service.get_controller(controller_id)
        self.event_service.record_audit(
            controller_id,
            snapshot.name if snapshot else controller_id,
            f"System Settings {action} updated",
            details=payload.message,
        )
        QTimer.singleShot(250, self._load_current)

    def _request_failed(
        self,
        controller_id: str,
        action: str,
        message: str,
    ) -> None:
        if controller_id != self.current_controller_id:
            return
        self._set_message(f"{action.upper()} FAILED · {message}", "offline")
        QMessageBox.warning(self, "System Settings", message)
        snapshot = self.controller_service.get_controller(controller_id)
        self.event_service.record_audit(
            controller_id,
            snapshot.name if snapshot else controller_id,
            f"System Settings {action} failed",
            details=message,
        )

    def _busy_changed(self, busy: bool) -> None:
        self._busy = busy
        self._update_controls()

    def _update_time_display(self) -> None:
        now = datetime.now()
        self.pc_time_value.setText(now.strftime("%H:%M:%S  %d/%m/%Y"))
        controller_time = self._estimated_controller_time()
        if controller_time is None:
            self.controller_time_value.setText("--:--:--  --/--/----")
            self.time_difference_value.setText("—")
            return
        self.controller_time_value.setText(
            controller_time.strftime("%H:%M:%S  %d/%m/%Y")
        )
        difference = round((controller_time - now).total_seconds())
        self.time_difference_value.setText(f"{difference:+d} seconds")
        self.time_difference_value.setProperty(
            "revisionState",
            "synced" if abs(difference) < 60 else "fault",
        )
        self.time_difference_value.style().unpolish(self.time_difference_value)
        self.time_difference_value.style().polish(self.time_difference_value)

    def _estimated_controller_time(self) -> datetime | None:
        if self.current_time is None:
            return None
        base = self.current_time.as_datetime()
        if base is None:
            return None
        if self._time_received_at is None:
            return base
        return base + (datetime.now() - self._time_received_at)

    def _time_difference_seconds(self) -> int | None:
        controller_time = self._estimated_controller_time()
        if controller_time is None:
            return None
        return round((controller_time - datetime.now()).total_seconds())

    def _set_message(self, text: str, status: str) -> None:
        self.message_label.setToolTip(text)
        metrics = QFontMetrics(self.message_label.font())
        self.message_label.setText(
            metrics.elidedText(
                text,
                Qt.TextElideMode.ElideRight,
                278,
            )
        )
        self.message_label.setProperty("status", status)
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)
