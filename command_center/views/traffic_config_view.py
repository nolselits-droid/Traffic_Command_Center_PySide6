from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QTime, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ..controller_service import ControllerService
from ..event_service import EventService
from ..traffic_config_service import (
    EditorActionResult,
    HolidayConfig,
    HolidaysConfig,
    PlanConfig,
    PlansIndex,
    ScheduleDayConfig,
    ScheduleEntryConfig,
    SIGNAL_STATE_NAMES,
    StageConfig,
    TrafficConfigService,
    TrafficEditorStatus,
    TrafficSystemConfig,
)
from ..widgets.common import MetricCell, muted_label, status_label


DAY_NAMES = (
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Holiday",
)


class StageEditDialog(QDialog):
    def __init__(
        self,
        plan_number: int,
        stage: StageConfig,
        active_sg: int,
        sg_names: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            f"Edit Plan {plan_number:02d} / Stage {stage.number:02d}"
        )
        self.setMinimumWidth(570)
        self._original_states = list(stage.signal_states[:12])
        self._original_states.extend([0] * (12 - len(self._original_states)))
        self._state_selectors: list[QComboBox] = []

        root = QVBoxLayout(self)
        note = QLabel(
            "Perubahan hanya ditulis ke Draft. Traffic runtime tidak berubah "
            "sampai Save & Safe Apply dilakukan."
        )
        note.setWordWrap(True)
        note.setObjectName("readOnlyNote")
        root.addWidget(note)

        form = QFormLayout()
        self.duration = QSpinBox()
        self.duration.setRange(1, 65535)
        self.duration.setSuffix(" seconds")
        self.duration.setValue(max(1, stage.duration_seconds))
        form.addRow("Duration", self.duration)
        root.addLayout(form)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for index in range(active_sg):
            label_text = f"SG{index + 1}"
            if index < len(sg_names) and sg_names[index]:
                label_text += f" · {sg_names[index]}"
            label = QLabel(label_text)
            selector = QComboBox()
            for state, name in SIGNAL_STATE_NAMES.items():
                selector.addItem(f"{state} · {name}", state)
            selected = selector.findData(self._original_states[index])
            selector.setCurrentIndex(max(0, selected))
            self._state_selectors.append(selector)
            column = 0 if index < 6 else 2
            row = index if index < 6 else index - 6
            grid.addWidget(label, row, column)
            grid.addWidget(selector, row, column + 1)
        root.addLayout(grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> tuple[int, list[int]]:
        states = list(self._original_states)
        for index, selector in enumerate(self._state_selectors):
            states[index] = int(selector.currentData())
        return self.duration.value(), states


class ScheduleEditDialog(QDialog):
    def __init__(
        self,
        day_name: str,
        entry: ScheduleEntryConfig,
        defined_plans: list[int],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit {day_name} / Slot {entry.slot:02d}")
        self.setMinimumWidth(390)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTime(QTime(entry.hour, entry.minute))
        form.addRow("Start time", self.time_edit)
        self.plan_selector = QComboBox()
        plans = sorted(set(defined_plans))
        if entry.plan > 0 and entry.plan not in plans:
            plans.append(entry.plan)
            plans.sort()
        for plan_number in plans:
            self.plan_selector.addItem(f"Plan {plan_number:02d}", plan_number)
        selected = self.plan_selector.findData(entry.plan)
        self.plan_selector.setCurrentIndex(max(0, selected))
        form.addRow("Plan", self.plan_selector)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> tuple[int, int, int]:
        selected_time = self.time_edit.time()
        return (
            int(self.plan_selector.currentData()),
            selected_time.hour(),
            selected_time.minute(),
        )


class HolidayEditDialog(QDialog):
    def __init__(self, holiday: HolidayConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Holiday Slot {holiday.slot:02d}")
        self.setMinimumWidth(390)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setMinimumDate(QDate(2000, 1, 1))
        self.date_edit.setMaximumDate(QDate(2099, 12, 31))
        selected = (
            QDate(holiday.year, holiday.month, holiday.day)
            if holiday.defined
            else QDate.currentDate()
        )
        self.date_edit.setDate(selected)
        form.addRow("Holiday date", self.date_edit)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> tuple[int, int, int]:
        value = self.date_edit.date()
        return value.day(), value.month(), value.year()


class TrafficConfigView(QWidget):
    def __init__(
        self,
        controller_service: ControllerService,
        event_service: EventService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("trafficConfigPage")
        self.controller_service = controller_service
        self.event_service = event_service
        self.config_service = TrafficConfigService(controller_service, self)
        self.current_controller_id = ""
        self.current_status: TrafficEditorStatus | None = None
        self.current_system: TrafficSystemConfig | None = None
        self.current_plans: PlansIndex | None = None
        self.current_plan: PlanConfig | None = None
        self.current_schedule: ScheduleDayConfig | None = None
        self.current_holidays: HolidaysConfig | None = None
        self._owned_draft_controller_id = ""
        self._pending_action = ""
        self._pending_context: dict[str, object] = {}
        self._changes: dict[str, None] = {}
        self._active = False
        self._busy = False
        self._read_errors: set[str] = set()
        self._status_retry_count = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 16)
        root.setSpacing(9)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title = QLabel("Traffic Configuration")
        title.setObjectName("pageTitle")
        title_column.addWidget(title)
        title_column.addWidget(
            muted_label(
                "Plan, Stage, Schedule, dan Holiday · transactional Draft editor"
            )
        )
        header.addLayout(title_column)
        header.addStretch()
        self.mode_label = status_label("VIEW ONLY")
        self.mode_label.setProperty("status", "online")
        header.addWidget(self.mode_label)
        self.controller_selector = QComboBox()
        self.controller_selector.currentIndexChanged.connect(
            self._controller_changed
        )
        header.addWidget(self.controller_selector)
        self.refresh_button = QPushButton("REFRESH")
        self.refresh_button.setObjectName("primaryButton")
        self._set_action_role(self.refresh_button, "primary")
        self.refresh_button.clicked.connect(
            lambda checked=False: self.refresh_configuration(manual=True)
        )
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.source_frame = QFrame()
        self.source_frame.setObjectName("sourceBanner")
        source_layout = QHBoxLayout(self.source_frame)
        source_layout.setContentsMargins(11, 7, 11, 7)
        self.source_label = QLabel("SOURCE: WAITING")
        self.source_label.setObjectName("sourceLabel")
        self.source_detail = muted_label(
            "Menunggu pembacaan konfigurasi dari controller."
        )
        source_layout.addWidget(self.source_label)
        source_layout.addWidget(self.source_detail, 1)
        root.addWidget(self.source_frame)

        root.addWidget(self._build_workflow_panel())

        summary = QFrame()
        summary.setObjectName("summaryPanel")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(8, 8, 8, 8)
        summary_layout.setSpacing(7)
        self.active_sg_metric = MetricCell("Active SG")
        self.plan_metric = MetricCell("Defined Plans")
        self.schedule_metric = MetricCell("Schedules")
        self.holiday_metric = MetricCell("Holidays")
        self.revision_metric = MetricCell("Config / Runtime")
        self.apply_metric = MetricCell("Apply / Safety")
        for metric in (
            self.active_sg_metric,
            self.plan_metric,
            self.schedule_metric,
            self.holiday_metric,
            self.revision_metric,
            self.apply_metric,
        ):
            summary_layout.addWidget(metric, 1)
        root.addWidget(summary)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("trafficConfigTabs")
        self.overview_tab = self._build_overview_tab()
        self.plans_tab = self._build_plans_tab()
        self.schedule_tab = self._build_schedule_tab()
        self.holidays_tab = self._build_holidays_tab()
        self.tabs.addTab(self.overview_tab, "OVERVIEW")
        self.tabs.addTab(self.plans_tab, "PLANS & STAGES")
        self.tabs.addTab(self.schedule_tab, "SCHEDULE")
        self.tabs.addTab(self.holidays_tab, "HOLIDAYS")
        self.tabs.currentChanged.connect(self._tab_changed)
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.message_label = status_label("WAITING FOR CONTROLLER")
        self.message_label.setProperty("status", "offline")
        self.last_read_label = muted_label("Last read: —")
        self.last_read_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        footer.addWidget(self.message_label)
        footer.addStretch()
        footer.addWidget(self.last_read_label)
        root.addLayout(footer)

        self.config_service.status_loaded.connect(self._status_loaded)
        self.config_service.system_loaded.connect(self._system_loaded)
        self.config_service.plans_loaded.connect(self._plans_loaded)
        self.config_service.plan_loaded.connect(self._plan_loaded)
        self.config_service.schedule_loaded.connect(self._schedule_loaded)
        self.config_service.holidays_loaded.connect(self._holidays_loaded)
        self.config_service.action_completed.connect(self._action_completed)
        self.config_service.request_failed.connect(self._request_failed)
        self.config_service.busy_changed.connect(self._busy_changed)
        self.controller_service.controllers_changed.connect(
            self._rebuild_controller_selector
        )
        self.controller_service.snapshot_updated.connect(
            self._controller_snapshot_updated
        )
        self._rebuild_controller_selector()
        self._update_controls()

    def _build_workflow_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("workflowPanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(7)
        self.edit_button = QPushButton("EDIT CONFIGURATION")
        self.edit_button.setObjectName("primaryButton")
        self.edit_button.clicked.connect(self._begin_edit)
        self.validate_button = QPushButton("VALIDATE")
        self.validate_button.clicked.connect(self._validate_edit)
        self.save_button = QPushButton("SAVE TO NVS")
        self.save_button.clicked.connect(self._save_edit)
        self.save_apply_button = QPushButton("SAVE & SAFE APPLY")
        self.save_apply_button.setObjectName("primaryButton")
        self.save_apply_button.clicked.connect(self._save_and_apply)
        self.apply_saved_button = QPushButton("APPLY SAVED")
        self.apply_saved_button.clicked.connect(self._apply_saved)
        self.cancel_button = QPushButton("CANCEL DRAFT")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.clicked.connect(self._cancel_edit)
        workflow_buttons = (
            (self.edit_button, "primary"),
            (self.validate_button, "confirm"),
            (self.save_button, "confirm"),
            (self.save_apply_button, "confirm"),
            (self.apply_saved_button, "confirm"),
            (self.cancel_button, "danger"),
        )
        for button, role in workflow_buttons:
            button.setProperty("workflow", True)
            self._set_action_role(button, role)
            layout.addWidget(button)
        layout.addStretch()
        self.change_label = muted_label("Draft changes: 0")
        layout.addWidget(self.change_label)
        return panel

    def _build_overview_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        note = QLabel(
            "Semua perubahan memakai ConfigEditor firmware. Draft tidak "
            "mengubah traffic runtime sampai Save & Safe Apply dijalankan."
        )
        note.setWordWrap(True)
        note.setObjectName("readOnlyNote")
        layout.addWidget(note)
        detail_frame = QFrame()
        detail_frame.setObjectName("contentPanel")
        detail_grid = QGridLayout(detail_frame)
        detail_grid.setContentsMargins(14, 12, 14, 12)
        detail_grid.setHorizontalSpacing(20)
        detail_grid.setVerticalSpacing(8)
        labels = (
            ("Controller", "controller_value"),
            ("Configuration Source", "configuration_source_value"),
            ("Draft State", "draft_value"),
            ("Validation", "validation_value"),
            ("Configuration Dirty", "dirty_value"),
            ("Apply State", "apply_value"),
            ("Safety", "safety_value"),
        )
        for row, (caption, attribute) in enumerate(labels):
            value_label = QLabel("—")
            value_label.setObjectName("configDetailValue")
            setattr(self, attribute, value_label)
            detail_grid.addWidget(muted_label(caption), row, 0)
            detail_grid.addWidget(value_label, row, 1)
        detail_grid.setColumnStretch(1, 1)
        layout.addWidget(detail_frame)
        sg_title = QLabel("Signal Group Names")
        sg_title.setObjectName("sectionTitle")
        layout.addWidget(sg_title)
        self.sg_table = self._new_table(["SG", "NAME", "ACTIVE"])
        self.sg_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.sg_table, 1)
        return tab

    def _build_plans_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        self.plan_caption = muted_label("Pilih Plan untuk melihat seluruh Stage.")
        toolbar.addWidget(self.plan_caption, 1)
        toolbar.addWidget(QLabel("Stage Count"))
        self.stage_count_spin = QSpinBox()
        self.stage_count_spin.setRange(1, 24)
        toolbar.addWidget(self.stage_count_spin)
        self.stage_count_button = QPushButton("UPDATE STAGE COUNT")
        self.stage_count_button.setObjectName("compactButton")
        self._set_action_role(self.stage_count_button)
        self.stage_count_button.clicked.connect(self._update_stage_count)
        toolbar.addWidget(self.stage_count_button)
        self.edit_stage_button = QPushButton("EDIT SELECTED STAGE")
        self.edit_stage_button.setObjectName("compactButton")
        self._set_action_role(self.edit_stage_button)
        self.edit_stage_button.clicked.connect(self._edit_selected_stage)
        toolbar.addWidget(self.edit_stage_button)
        self.clear_plan_button = QPushButton("CLEAR PLAN")
        self.clear_plan_button.setObjectName("dangerButton")
        self._set_action_role(self.clear_plan_button, "danger")
        self.clear_plan_button.clicked.connect(self._clear_selected_plan)
        toolbar.addWidget(self.clear_plan_button)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.plan_list = QListWidget()
        self.plan_list.setObjectName("planList")
        self.plan_list.setMinimumWidth(185)
        self.plan_list.setMaximumWidth(260)
        self.plan_list.currentItemChanged.connect(self._plan_selected)
        splitter.addWidget(self.plan_list)
        self.stage_table = self._new_table(
            ["STAGE", "DURATION"],
            stretch_last=False,
        )
        self.stage_table.itemSelectionChanged.connect(self._update_controls)
        self.stage_table.cellDoubleClicked.connect(
            lambda _row, _column: self._edit_selected_stage()
        )
        splitter.addWidget(self.stage_table)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        return tab

    def _build_schedule_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Day Group"))
        self.schedule_day_selector = QComboBox()
        for day, name in enumerate(DAY_NAMES):
            self.schedule_day_selector.addItem(f"{day} · {name}", day)
        self.schedule_day_selector.currentIndexChanged.connect(
            self._schedule_day_changed
        )
        toolbar.addWidget(self.schedule_day_selector)
        self.edit_schedule_button = QPushButton("SET SELECTED SLOT")
        self.edit_schedule_button.setObjectName("compactButton")
        self._set_action_role(self.edit_schedule_button)
        self.edit_schedule_button.clicked.connect(self._edit_schedule_slot)
        toolbar.addWidget(self.edit_schedule_button)
        self.clear_schedule_button = QPushButton("CLEAR SELECTED SLOT")
        self.clear_schedule_button.setObjectName("dangerButton")
        self._set_action_role(self.clear_schedule_button, "danger")
        self.clear_schedule_button.clicked.connect(self._clear_schedule_slot)
        toolbar.addWidget(self.clear_schedule_button)
        toolbar.addStretch()
        self.schedule_source_label = muted_label("Source: —")
        toolbar.addWidget(self.schedule_source_label)
        layout.addLayout(toolbar)
        self.schedule_table = self._new_table(["SLOT", "TIME", "PLAN", "STATE"])
        self.schedule_table.itemSelectionChanged.connect(self._update_controls)
        self.schedule_table.cellDoubleClicked.connect(
            lambda _row, _column: self._edit_schedule_slot()
        )
        layout.addWidget(self.schedule_table, 1)
        return tab

    def _build_holidays_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        self.holiday_caption = muted_label("Seluruh 32 slot Holiday.")
        toolbar.addWidget(self.holiday_caption, 1)
        self.edit_holiday_button = QPushButton("SET SELECTED HOLIDAY")
        self.edit_holiday_button.setObjectName("compactButton")
        self._set_action_role(self.edit_holiday_button)
        self.edit_holiday_button.clicked.connect(self._edit_holiday_slot)
        toolbar.addWidget(self.edit_holiday_button)
        self.clear_holiday_button = QPushButton("CLEAR SELECTED HOLIDAY")
        self.clear_holiday_button.setObjectName("dangerButton")
        self._set_action_role(self.clear_holiday_button, "danger")
        self.clear_holiday_button.clicked.connect(self._clear_holiday_slot)
        toolbar.addWidget(self.clear_holiday_button)
        layout.addLayout(toolbar)
        self.holiday_table = self._new_table(["SLOT", "DATE", "DAY", "STATE"])
        self.holiday_table.itemSelectionChanged.connect(self._update_controls)
        self.holiday_table.cellDoubleClicked.connect(
            lambda _row, _column: self._edit_holiday_slot()
        )
        layout.addWidget(self.holiday_table, 1)
        return tab

    def _new_table(
        self,
        headers: list[str],
        *,
        stretch_last: bool = True,
    ) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setObjectName("configTable")
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setStretchLastSection(stretch_last)
        return table

    @staticmethod
    def _set_action_role(button: QPushButton, role: str = "standard") -> None:
        button.setProperty("trafficAction", True)
        button.setProperty("actionRole", role)

    def _rebuild_controller_selector(self) -> None:
        previous = self.current_controller_id
        owned = self._owned_draft_controller_id
        self.controller_selector.blockSignals(True)
        self.controller_selector.clear()
        for controller in self.controller_service.controllers:
            self.controller_selector.addItem(
                f"{controller.controller_id} · {controller.name}",
                controller.controller_id,
            )
        preferred = owned or previous
        index = self.controller_selector.findData(preferred)
        self.controller_selector.setCurrentIndex(max(0, index))
        self.controller_selector.blockSignals(False)
        if not self.controller_service.controllers:
            self.current_controller_id = ""
            self._set_message("NO CONTROLLER CONFIGURED", "offline")
        else:
            self.current_controller_id = str(
                self.controller_selector.currentData() or ""
            )
            if self._active:
                self.refresh_configuration()
        self._update_controls()

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        if active:
            self.refresh_configuration()
        elif not self._busy:
            # Never abort an in-flight transaction request. The controller may
            # already have accepted it even if the page is no longer visible.
            self.config_service.cancel()

    def has_owned_draft(self) -> bool:
        return bool(self._owned_draft_controller_id)

    def confirm_application_close(self) -> bool:
        if not self.has_owned_draft() and not self._pending_action:
            return True
        target_controller = (
            self._owned_draft_controller_id or self.current_controller_id
        )
        pending = (
            f"\nAction yang masih menunggu respons: {self._pending_action}.\n"
            if self._pending_action
            else ""
        )
        result = QMessageBox.warning(
            self,
            "Draft configuration masih terbuka",
            "Command Center masih memiliki Draft atau transaksi configuration "
            f"pada {target_controller}.\n\n"
            f"{pending}"
            "Jika aplikasi ditutup, Draft tetap berada pada controller dan "
            "harus dilanjutkan atau dibatalkan melalui dashboard controller.\n\n"
            "Tetap tutup aplikasi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _controller_changed(self) -> None:
        requested = str(self.controller_selector.currentData() or "")
        if self._owned_draft_controller_id:
            owned_index = self.controller_selector.findData(
                self._owned_draft_controller_id
            )
            self.controller_selector.blockSignals(True)
            self.controller_selector.setCurrentIndex(owned_index)
            self.controller_selector.blockSignals(False)
            self._set_message(
                "FINISH OR CANCEL CURRENT DRAFT BEFORE CHANGING CONTROLLER",
                "warning",
            )
            return
        if not requested:
            return
        self.current_controller_id = requested
        if self._active:
            self.refresh_configuration()

    def _controller_snapshot_updated(self, controller_id: str) -> None:
        if controller_id == self.current_controller_id:
            self._update_controls()

    def refresh_configuration(
        self,
        *,
        manual: bool = False,
        preserve_status: bool = False,
    ) -> None:
        if not self.current_controller_id:
            return
        self._read_errors.clear()
        self._clear_data(preserve_status=preserve_status)
        self._set_message("READING CONFIGURATION...", "warning")
        snapshot = self.controller_service.get_controller(
            self.current_controller_id
        )
        self.controller_value.setText(
            f"{self.current_controller_id} · {snapshot.name}"
            if snapshot
            else self.current_controller_id
        )
        if manual:
            self._record_audit(
                "Traffic configuration refresh requested",
                "Manual refresh from Command Center V0.6.00 FIX1 TEST",
            )
        self.config_service.load_initial(self.current_controller_id)

    def _clear_data(self, *, preserve_status: bool = False) -> None:
        selected_plan = self._selected_plan_number()
        if not preserve_status:
            self.current_status = None
        self.current_system = None
        self.current_plans = None
        self.current_plan = None
        self.current_schedule = None
        self.current_holidays = None
        self.plan_list.clear()
        self.plan_list.setProperty("restorePlan", selected_plan)
        for table in (
            self.sg_table,
            self.stage_table,
            self.schedule_table,
            self.holiday_table,
        ):
            table.setRowCount(0)
        status_metrics = (
            self.active_sg_metric,
            self.plan_metric,
            self.schedule_metric,
            self.holiday_metric,
            self.revision_metric,
            self.apply_metric,
        )
        for metric in status_metrics:
            if preserve_status:
                continue
            metric.set_value("—")
        for label in (
            self.configuration_source_value,
            self.draft_value,
            self.validation_value,
            self.dirty_value,
            self.apply_value,
            self.safety_value,
        ):
            if not preserve_status:
                label.setText("—")
        if not preserve_status:
            self._set_source("WAITING", False)
        self._update_controls()

    def _status_loaded(self, controller_id: str, status: object) -> None:
        if controller_id != self.current_controller_id or not isinstance(
            status, TrafficEditorStatus
        ):
            return
        if (
            self._owned_draft_controller_id == controller_id
            and not status.editing
        ):
            self._owned_draft_controller_id = ""
        self.current_status = status
        self._status_retry_count = 0
        self.active_sg_metric.set_value(str(status.active_sg))
        self.plan_metric.set_value(str(status.plan_count))
        self.schedule_metric.set_value(str(status.schedule_count))
        self.holiday_metric.set_value(str(status.holiday_count))
        self.revision_metric.set_value(
            f"{status.config_revision} / {status.runtime_revision}"
        )
        self.apply_metric.set_value(f"{status.apply_state} / {status.safety}")
        self.draft_value.setText(
            "MODIFIED"
            if status.editing and status.modified
            else "OPEN"
            if status.editing
            else "CLOSED"
        )
        self.validation_value.setText(
            "VALID"
            if status.validation_checked and status.validation_valid
            else "INVALID"
            if status.validation_checked
            else "NOT CHECKED"
        )
        self.dirty_value.setText("YES" if status.config_dirty else "NO")
        self.apply_value.setText(status.apply_state)
        self.safety_value.setText(status.safety)
        self._set_source("DRAFT" if status.editing else "CONFIG RAM", status.editing)
        self._mark_read_success("status")
        self._update_controls()

    def _system_loaded(self, controller_id: str, system: object) -> None:
        if controller_id != self.current_controller_id or not isinstance(
            system, TrafficSystemConfig
        ):
            return
        self.current_system = system
        self.configuration_source_value.setText(system.source)
        self._set_source(system.source, system.editing)
        self._populate_signal_groups(system)
        self._mark_read_success("system")

    def _plans_loaded(self, controller_id: str, plans: object) -> None:
        if controller_id != self.current_controller_id or not isinstance(
            plans, PlansIndex
        ):
            return
        previous = self._selected_plan_number()
        if previous <= 0:
            previous = int(self.plan_list.property("restorePlan") or 0)
        self.current_plans = plans
        self._set_source(plans.source, plans.editing)
        self.plan_list.blockSignals(True)
        self.plan_list.clear()
        first_defined_row = -1
        selected_row = -1
        for row, plan in enumerate(plans.plans):
            suffix = f"{plan.stage_count} Stage" if plan.stage_count else "EMPTY"
            item = QListWidgetItem(f"Plan {plan.number:02d}  ·  {suffix}")
            item.setData(Qt.ItemDataRole.UserRole, plan.number)
            item.setData(Qt.ItemDataRole.UserRole + 1, plan.stage_count)
            if not plan.stage_count:
                item.setForeground(QColor("#6f8092"))
            elif first_defined_row < 0:
                first_defined_row = row
            if plan.number == previous:
                selected_row = row
            self.plan_list.addItem(item)
        self.plan_list.blockSignals(False)
        target = selected_row if selected_row >= 0 else first_defined_row
        if target < 0 and self.plan_list.count():
            target = 0
        if target >= 0:
            self.plan_list.setCurrentRow(target)
        self._mark_read_success("plans")
        self._update_controls()

    def _plan_selected(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        self.stage_table.setRowCount(0)
        self.current_plan = None
        if current is None or not self.current_controller_id:
            self._update_controls()
            return
        plan_number = int(current.data(Qt.ItemDataRole.UserRole))
        stage_count = int(current.data(Qt.ItemDataRole.UserRole + 1))
        self.stage_count_spin.setValue(max(1, stage_count))
        if stage_count <= 0:
            self.plan_caption.setText(
                f"Plan {plan_number:02d} EMPTY · set Stage Count untuk membuat Plan."
            )
            self._update_controls()
            return
        self.plan_caption.setText(
            f"Reading Plan {plan_number:02d} · {stage_count} Stage..."
        )
        self.config_service.load_plan(self.current_controller_id, plan_number)

    def _plan_loaded(
        self,
        controller_id: str,
        plan_number: int,
        plan: object,
    ) -> None:
        if controller_id != self.current_controller_id or not isinstance(
            plan, PlanConfig
        ):
            return
        if self._selected_plan_number() != plan_number:
            return
        self.current_plan = plan
        self.stage_count_spin.setValue(max(1, len(plan.stages)))
        self._set_source(plan.source, plan.editing)
        self._populate_plan(plan)
        self._mark_read_success(f"plan-{plan_number}")
        self._update_controls()

    def _populate_plan(self, plan: PlanConfig) -> None:
        active_sg = self.current_system.active_sg if self.current_system else 12
        names = self.current_system.sg_names if self.current_system else []
        header_items = [QTableWidgetItem("STAGE"), QTableWidgetItem("DURATION")]
        for index in range(1, active_sg + 1):
            name = names[index - 1] if index - 1 < len(names) else ""
            item = QTableWidgetItem(f"SG{index}\n{name}" if name else f"SG{index}")
            item.setToolTip(name or f"Signal Group {index}")
            header_items.append(item)
        self.stage_table.setColumnCount(len(header_items))
        self.stage_table.setHorizontalHeaderLabels(
            [item.text() for item in header_items]
        )
        for column, item in enumerate(header_items):
            self.stage_table.setHorizontalHeaderItem(column, item)
        header = self.stage_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.stage_table.setColumnWidth(0, 65)
        self.stage_table.setColumnWidth(1, 90)
        for column in range(2, len(header_items)):
            self.stage_table.setColumnWidth(column, 150)
        self.stage_table.setRowCount(len(plan.stages))
        for row, stage in enumerate(plan.stages):
            self.stage_table.setItem(row, 0, self._centered_item(str(stage.number)))
            self.stage_table.setItem(
                row, 1, self._centered_item(f"{stage.duration_seconds} s")
            )
            for sg in range(active_sg):
                state = stage.signal_states[sg] if sg < len(stage.signal_states) else 0
                item = self._centered_item(
                    SIGNAL_STATE_NAMES.get(state, f"STATE {state}")
                )
                item.setForeground(self._signal_color(state))
                self.stage_table.setItem(row, sg + 2, item)
        self.plan_caption.setText(
            f"Plan {plan.number:02d} · {len(plan.stages)} Stage · Source {plan.source}"
        )

    def _tab_changed(self, _index: int) -> None:
        if not self._active or not self.current_controller_id:
            return
        current = self.tabs.currentWidget()
        if current is self.schedule_tab:
            self._request_current_schedule()
        elif current is self.holidays_tab:
            self.config_service.load_holidays(self.current_controller_id)

    def _schedule_day_changed(self) -> None:
        if self._active and self.tabs.currentWidget() is self.schedule_tab:
            self._request_current_schedule()

    def _request_current_schedule(self) -> None:
        day = int(self.schedule_day_selector.currentData() or 0)
        self.schedule_table.setRowCount(0)
        self.current_schedule = None
        self.config_service.load_schedule(self.current_controller_id, day)

    def _schedule_loaded(
        self,
        controller_id: str,
        day: int,
        schedule: object,
    ) -> None:
        if controller_id != self.current_controller_id or not isinstance(
            schedule, ScheduleDayConfig
        ):
            return
        if int(self.schedule_day_selector.currentData() or 0) != day:
            return
        self.current_schedule = schedule
        self._set_source(schedule.source, schedule.editing)
        self.schedule_source_label.setText(
            f"{schedule.day_name} · Source: {schedule.source}"
        )
        self.schedule_table.setRowCount(len(schedule.entries))
        for row, entry in enumerate(schedule.entries):
            defined = entry.plan > 0
            values = (
                str(entry.slot),
                f"{entry.hour:02d}:{entry.minute:02d}" if defined else "—",
                f"Plan {entry.plan:02d}" if defined else "—",
                "DEFINED" if defined else "EMPTY",
            )
            for column, value in enumerate(values):
                item = self._centered_item(value)
                if not defined:
                    item.setForeground(QColor("#6f8092"))
                self.schedule_table.setItem(row, column, item)
        self._mark_read_success(f"schedule-{day}")
        self._update_controls()

    def _holidays_loaded(self, controller_id: str, holidays: object) -> None:
        if controller_id != self.current_controller_id or not isinstance(
            holidays, HolidaysConfig
        ):
            return
        self.current_holidays = holidays
        self._set_source(holidays.source, holidays.editing)
        self.holiday_table.setRowCount(len(holidays.entries))
        defined_count = 0
        for row, holiday in enumerate(holidays.entries):
            if holiday.defined:
                defined_count += 1
            values = (
                str(holiday.slot),
                self._holiday_date(holiday),
                self._holiday_day_name(holiday),
                "DEFINED" if holiday.defined else "EMPTY",
            )
            for column, value in enumerate(values):
                item = self._centered_item(value)
                if not holiday.defined:
                    item.setForeground(QColor("#6f8092"))
                self.holiday_table.setItem(row, column, item)
        self.holiday_caption.setText(
            f"{defined_count}/32 Holiday slots defined · Source {holidays.source}"
        )
        self._mark_read_success("holidays")
        self._update_controls()

    def _populate_signal_groups(self, system: TrafficSystemConfig) -> None:
        self.sg_table.setRowCount(12)
        for row in range(12):
            active = row < system.active_sg
            name = system.sg_names[row] if row < len(system.sg_names) else ""
            values = (
                f"SG{row + 1}",
                name or "—",
                "ACTIVE" if active else "INACTIVE",
            )
            for column, value in enumerate(values):
                item = self._centered_item(value)
                if not active:
                    item.setForeground(QColor("#6f8092"))
                self.sg_table.setItem(row, column, item)

    def _begin_edit(self) -> None:
        if not self._can_start_edit():
            return
        self._pending_context = {}
        self._pending_action = "START DRAFT"
        self.config_service.begin_edit(self.current_controller_id)

    def _cancel_edit(self) -> None:
        if not self._owns_current_draft():
            return
        answer = QMessageBox.question(
            self,
            "Cancel Draft",
            "Batalkan seluruh perubahan Draft pada controller ini?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._pending_action = "CANCEL DRAFT"
            self.config_service.cancel_edit(self.current_controller_id)

    def _validate_edit(self) -> None:
        if self._can_edit():
            self._pending_action = "VALIDATE DRAFT"
            self.config_service.validate_edit(self.current_controller_id)

    def _save_edit(self) -> None:
        if not self._can_save(apply=False):
            return
        if self._confirm_save(False):
            self._pending_action = "SAVE TO NVS"
            self.config_service.save_edit(self.current_controller_id)

    def _save_and_apply(self) -> None:
        if not self._can_save(apply=True):
            return
        if self._confirm_save(True):
            self._pending_action = "SAVE & SAFE APPLY"
            self.config_service.save_and_apply(self.current_controller_id)

    def _apply_saved(self) -> None:
        if not self._can_apply_saved():
            return
        status = self.current_status
        answer = QMessageBox.warning(
            self,
            "Apply Saved Configuration",
            f"Terapkan Config Revision {status.config_revision} ke traffic runtime?\n\n"
            "Controller akan menunggu batas akhir current Plan kemudian "
            "melakukan safe transition.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._pending_action = "APPLY SAVED"
            self.config_service.apply_saved(self.current_controller_id)

    def _update_stage_count(self) -> None:
        if not self._can_edit():
            return
        plan_number = self._selected_plan_number()
        if plan_number <= 0:
            return
        old_count = (
            len(self.current_plan.stages)
            if self.current_plan and self.current_plan.number == plan_number
            else self._selected_plan_stage_count()
        )
        new_count = self.stage_count_spin.value()
        if new_count == old_count:
            return
        if new_count < old_count:
            answer = QMessageBox.warning(
                self,
                "Reduce Stage Count",
                f"Plan {plan_number:02d} akan dikurangi dari {old_count} menjadi "
                f"{new_count} Stage. Stage setelah nomor {new_count} akan dihapus "
                "dari Draft.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._pending_context = {"plan": plan_number, "count": new_count}
        self._pending_action = "UPDATE STAGE COUNT"
        self.config_service.update_stage_count(
            self.current_controller_id, plan_number, new_count
        )

    def _clear_selected_plan(self) -> None:
        if not self._can_edit():
            return
        plan_number = self._selected_plan_number()
        if plan_number <= 0 or self.current_plan is None:
            return
        answer = QMessageBox.warning(
            self,
            "Clear Plan",
            f"Hapus seluruh Stage pada Plan {plan_number:02d} dari Draft?\n\n"
            "Schedule yang masih menunjuk ke Plan ini akan membuat validasi gagal.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._pending_context = {"plan": plan_number}
            self._pending_action = "CLEAR PLAN"
            self.config_service.clear_plan(self.current_controller_id, plan_number)

    def _edit_selected_stage(self) -> None:
        if not self._can_edit() or self.current_plan is None:
            return
        row = self.stage_table.currentRow()
        if not 0 <= row < len(self.current_plan.stages):
            return
        stage = self.current_plan.stages[row]
        active_sg = self.current_system.active_sg if self.current_system else 12
        names = self.current_system.sg_names if self.current_system else []
        dialog = StageEditDialog(
            self.current_plan.number,
            stage,
            active_sg,
            names,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        duration, states = dialog.values()
        self._pending_context = {
            "plan": self.current_plan.number,
            "stage": stage.number,
        }
        self._pending_action = "UPDATE STAGE"
        self.config_service.update_stage(
            self.current_controller_id,
            self.current_plan.number,
            stage.number,
            duration,
            states,
        )

    def _edit_schedule_slot(self) -> None:
        if not self._can_edit() or self.current_schedule is None:
            return
        row = self.schedule_table.currentRow()
        if not 0 <= row < len(self.current_schedule.entries):
            return
        defined_plans = self._defined_plan_numbers()
        if not defined_plans:
            QMessageBox.warning(
                self,
                "No Plan Available",
                "Buat minimal satu Plan sebelum mengisi Schedule.",
            )
            return
        entry = self.current_schedule.entries[row]
        dialog = ScheduleEditDialog(
            self.current_schedule.day_name,
            entry,
            defined_plans,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        plan, hour, minute = dialog.values()
        self._pending_context = {
            "day": self.current_schedule.day,
            "day_name": self.current_schedule.day_name,
            "slot": entry.slot,
        }
        self._pending_action = "UPDATE SCHEDULE"
        self.config_service.update_schedule(
            self.current_controller_id,
            self.current_schedule.day,
            entry.slot,
            plan,
            hour,
            minute,
        )

    def _clear_schedule_slot(self) -> None:
        if not self._can_edit() or self.current_schedule is None:
            return
        row = self.schedule_table.currentRow()
        if not 0 <= row < len(self.current_schedule.entries):
            return
        entry = self.current_schedule.entries[row]
        if entry.plan <= 0:
            return
        answer = QMessageBox.question(
            self,
            "Clear Schedule Slot",
            f"Kosongkan {self.current_schedule.day_name} Slot {entry.slot:02d}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._pending_context = {
                "day": self.current_schedule.day,
                "day_name": self.current_schedule.day_name,
                "slot": entry.slot,
            }
            self._pending_action = "CLEAR SCHEDULE"
            self.config_service.clear_schedule(
                self.current_controller_id,
                self.current_schedule.day,
                entry.slot,
            )

    def _edit_holiday_slot(self) -> None:
        if not self._can_edit() or self.current_holidays is None:
            return
        row = self.holiday_table.currentRow()
        if not 0 <= row < len(self.current_holidays.entries):
            return
        holiday = self.current_holidays.entries[row]
        dialog = HolidayEditDialog(holiday, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        day, month, year = dialog.values()
        self._pending_context = {"slot": holiday.slot}
        self._pending_action = "UPDATE HOLIDAY"
        self.config_service.update_holiday(
            self.current_controller_id,
            holiday.slot,
            day,
            month,
            year,
        )

    def _clear_holiday_slot(self) -> None:
        if not self._can_edit() or self.current_holidays is None:
            return
        row = self.holiday_table.currentRow()
        if not 0 <= row < len(self.current_holidays.entries):
            return
        holiday = self.current_holidays.entries[row]
        if not holiday.defined:
            return
        answer = QMessageBox.question(
            self,
            "Clear Holiday",
            f"Kosongkan Holiday Slot {holiday.slot:02d} "
            f"({self._holiday_date(holiday)})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._pending_context = {"slot": holiday.slot}
            self._pending_action = "CLEAR HOLIDAY"
            self.config_service.clear_holiday(
                self.current_controller_id, holiday.slot
            )

    def _action_completed(
        self,
        controller_id: str,
        resource: str,
        result: object,
    ) -> None:
        if controller_id != self.current_controller_id or not isinstance(
            result, EditorActionResult
        ):
            return
        self._pending_action = ""
        if self.current_status and resource in {
            "start",
            "cancel",
            "validate",
            "stage-count",
            "plan-clear",
            "stage-update",
            "schedule-update",
            "schedule-clear",
            "holiday-update",
            "holiday-clear",
        }:
            self.current_status.editing = result.editing
            self.current_status.modified = result.modified
            self.current_status.validation_checked = result.validation_checked
            self.current_status.validation_valid = result.validation_valid
            self.current_status.config_dirty = result.config_dirty
        if not result.ok:
            detail = self._action_error_text(result)
            self._set_message(f"ACTION FAILED · {detail}", "offline")
            QMessageBox.warning(self, "Configuration Action Failed", detail)
            self._pending_context = {}
            self.config_service.load_status(controller_id)
            return

        messages = {
            "start": "Draft dibuka oleh Command Center.",
            "cancel": "Draft dibatalkan. Configuration aktif tidak berubah.",
            "validate": "Draft VALID.",
            "save": "Configuration disimpan ke NVS. Runtime belum berubah.",
            "save-apply": "Configuration disimpan dan Safe Apply diminta.",
            "apply": "Safe Apply untuk configuration tersimpan sudah diminta.",
            "stage-count": "Stage Count diperbarui di Draft.",
            "plan-clear": "Plan dihapus dari Draft.",
            "stage-update": "Stage diperbarui di Draft.",
            "schedule-update": "Schedule diperbarui di Draft.",
            "schedule-clear": "Schedule Slot dikosongkan dari Draft.",
            "holiday-update": "Holiday diperbarui di Draft.",
            "holiday-clear": "Holiday Slot dikosongkan dari Draft.",
        }
        message = result.message or messages.get(resource, "Action completed.")

        if resource == "start":
            self._owned_draft_controller_id = controller_id
            self._changes.clear()
            self._record_audit("Traffic configuration edit started", message)
            # START already returned authoritative Draft state. Keep it while
            # the heavier configuration reads run so edit controls do not
            # fall back to disabled if a status read briefly contends with
            # the controller monitoring poll.
            self.refresh_configuration(preserve_status=True)
        elif resource == "cancel":
            self._record_audit(
                "Traffic configuration Draft cancelled",
                self._change_summary_text(),
            )
            self._owned_draft_controller_id = ""
            self._changes.clear()
            self.refresh_configuration()
        elif resource == "validate":
            self._record_audit(
                "Traffic configuration Draft validated",
                self._change_summary_text(),
            )
            self.config_service.load_status(controller_id)
        elif resource in {"save", "save-apply"}:
            self._record_audit(
                "Traffic configuration saved and Safe Apply requested"
                if resource == "save-apply"
                else "Traffic configuration saved to NVS",
                self._change_summary_text(),
            )
            self._owned_draft_controller_id = ""
            self._changes.clear()
            self.refresh_configuration()
        elif resource == "apply":
            self._record_audit("Saved traffic configuration apply requested", message)
            self.config_service.load_status(controller_id)
        else:
            self._record_mutation(resource)
            self.config_service.load_status(controller_id)
            self._reload_after_mutation(resource)

        self._set_message(message, "online")
        self._pending_context = {}
        self._update_change_label()
        self._update_controls()

    def _record_mutation(self, resource: str) -> None:
        context = self._pending_context
        if resource == "stage-count":
            label = f"Plan {int(context.get('plan', 0)):02d} Stage Count"
        elif resource == "plan-clear":
            label = f"Plan {int(context.get('plan', 0)):02d} cleared"
        elif resource == "stage-update":
            label = (
                f"Plan {int(context.get('plan', 0)):02d} / "
                f"Stage {int(context.get('stage', 0)):02d}"
            )
        elif resource.startswith("schedule-"):
            label = (
                f"Schedule {context.get('day_name', '')} / "
                f"Slot {int(context.get('slot', 0)):02d}"
            )
        elif resource.startswith("holiday-"):
            label = f"Holiday Slot {int(context.get('slot', 0)):02d}"
        else:
            label = resource
        self._changes[label] = None
        self._record_audit("Traffic configuration Draft updated", label)

    @staticmethod
    def _action_error_text(result: EditorActionResult) -> str:
        error = result.error
        location: list[str] = []
        if error.plan:
            location.append(f"Plan {error.plan}")
        if error.stage:
            location.append(f"Stage {error.stage}")
        if error.signal_group:
            location.append(f"SG{error.signal_group}")
        if error.conflict_a and error.conflict_b:
            location.append(f"Conflict SG{error.conflict_a}-SG{error.conflict_b}")
        base = result.message or "Controller menolak action."
        if error.code:
            base += f" (error {error.code})"
        return f"{base} · {' / '.join(location)}" if location else base

    def _reload_after_mutation(self, resource: str) -> None:
        if resource in {"stage-count", "plan-clear"}:
            self.config_service.load_plans(self.current_controller_id)
            plan_number = int(self._pending_context.get("plan", 0))
            if resource == "stage-count" and plan_number > 0:
                self.config_service.load_plan(
                    self.current_controller_id, plan_number
                )
        elif resource == "stage-update":
            plan_number = int(self._pending_context.get("plan", 0))
            self.config_service.load_plan(self.current_controller_id, plan_number)
        elif resource.startswith("schedule-"):
            day = int(self._pending_context.get("day", 0))
            self.config_service.load_schedule(self.current_controller_id, day)
        elif resource.startswith("holiday-"):
            self.config_service.load_holidays(self.current_controller_id)

    def _set_source(self, source: str, editing: bool) -> None:
        normalized = source.upper() if source else "UNKNOWN"
        owned = editing and self._owns_current_draft()
        self.source_frame.setProperty("draft", editing)
        self.source_frame.setProperty("owned", owned)
        self.source_frame.style().unpolish(self.source_frame)
        self.source_frame.style().polish(self.source_frame)
        if normalized == "WAITING":
            label = "SOURCE: WAITING"
            detail = "Menunggu pembacaan konfigurasi dari controller."
        elif owned:
            label = "SOURCE: DRAFT · COMMAND CENTER SESSION"
            detail = (
                "Perubahan berada di Draft dan belum memengaruhi NVS maupun "
                "traffic runtime."
            )
        elif editing:
            label = "SOURCE: DRAFT · EXTERNAL SESSION"
            detail = (
                "Draft sudah dibuka dari luar Command Center. Data dapat "
                "dilihat tetapi tidak diambil alih atau dibatalkan."
            )
        else:
            label = f"SOURCE: {normalized}"
            detail = "Data berasal dari ConfigManager RAM controller."
        self.source_label.setText(label)
        self.source_detail.setText(detail)
        self.configuration_source_value.setText(normalized)

    def _busy_changed(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            if self.current_controller_id:
                self.controller_service.suspend_polling(
                    self.current_controller_id,
                    owner="traffic-config",
                )
            self._set_message("CONTROLLER REQUEST IN PROGRESS...", "warning")
        elif self.current_controller_id:
            self.controller_service.resume_polling(
                self.current_controller_id,
                owner="traffic-config",
                refresh=True,
            )
        self._update_controls()

    def _request_failed(
        self,
        controller_id: str,
        resource: str,
        message: str,
    ) -> None:
        if controller_id != self.current_controller_id:
            return
        self._read_errors.add(resource)
        self._pending_context = {}
        if resource.startswith("action:"):
            self._pending_action = ""
            if self.current_status:
                self.current_status.validation_checked = False
                self.current_status.validation_valid = False
        self._set_message(f"REQUEST FAILED · {resource}: {message}", "offline")
        if (
            resource == "status"
            and self._owned_draft_controller_id == controller_id
            and self.current_status is not None
            and self._status_retry_count < 2
        ):
            self._status_retry_count += 1
            QTimer.singleShot(
                400 * self._status_retry_count,
                lambda key=controller_id: (
                    self.config_service.load_status(key)
                    if key == self.current_controller_id
                    else None
                ),
            )
        self._update_controls()

    def _mark_read_success(self, resource: str) -> None:
        self._read_errors.discard(resource)
        self.last_read_label.setText(
            f"Last read: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        if self._read_errors:
            failed = ", ".join(sorted(self._read_errors))
            self._set_message(f"PARTIAL READ · FAILED: {failed}", "warning")
        else:
            self._set_message("CONFIGURATION READ SUCCESS", "online")

    def _update_controls(self) -> None:
        status = self.current_status
        snapshot = self.controller_service.get_controller(self.current_controller_id)
        live_online = bool(snapshot and snapshot.online)
        owns = self._owns_current_draft()
        editing = bool(status and status.editing)
        can_edit = bool(owns and editing and live_online and not self._busy)
        self.controller_selector.setEnabled(not owns and not self._busy)
        self.refresh_button.setEnabled(
            bool(self.current_controller_id) and not self._busy
        )
        self.edit_button.setEnabled(
            live_online
            and not self._busy
            and bool(status)
            and not editing
            and not status.apply_busy
        )
        self.validate_button.setEnabled(
            can_edit and bool(status.modified if status else False)
        )
        valid = bool(
            status
            and status.modified
            and status.validation_checked
            and status.validation_valid
        )
        self.save_button.setEnabled(can_edit and valid and not status.apply_busy)
        self.save_apply_button.setEnabled(
            can_edit
            and valid
            and not status.apply_busy
            and status.safety == "OK"
        )
        self.apply_saved_button.setEnabled(self._can_apply_saved())
        self.cancel_button.setEnabled(can_edit)

        selected_plan = self._selected_plan_number() > 0
        self.stage_count_spin.setEnabled(can_edit and selected_plan)
        self.stage_count_button.setEnabled(can_edit and selected_plan)
        self.edit_stage_button.setEnabled(
            can_edit
            and self.current_plan is not None
            and self.stage_table.currentRow() >= 0
        )
        self.clear_plan_button.setEnabled(
            can_edit and self.current_plan is not None
        )
        schedule_selected = self.schedule_table.currentRow() >= 0
        self.edit_schedule_button.setEnabled(can_edit and schedule_selected)
        schedule_entry = self._selected_schedule_entry()
        self.clear_schedule_button.setEnabled(
            can_edit and schedule_entry is not None and schedule_entry.plan > 0
        )
        holiday_selected = self.holiday_table.currentRow() >= 0
        self.edit_holiday_button.setEnabled(can_edit and holiday_selected)
        holiday = self._selected_holiday()
        self.clear_holiday_button.setEnabled(
            can_edit and holiday is not None and holiday.defined
        )

        if owns:
            mode_text, mode_status = "EDITING DRAFT", "warning"
        elif editing:
            mode_text, mode_status = "EXTERNAL DRAFT", "warning"
        else:
            mode_text, mode_status = "VIEW MODE", "online"
        self.mode_label.setText(mode_text)
        self.mode_label.setProperty("status", mode_status)
        self.mode_label.style().unpolish(self.mode_label)
        self.mode_label.style().polish(self.mode_label)
        self._update_change_label()

    def _can_start_edit(self) -> bool:
        return self.edit_button.isEnabled()

    def _can_edit(self) -> bool:
        snapshot = self.controller_service.get_controller(self.current_controller_id)
        return bool(
            self._owns_current_draft()
            and self.current_status
            and self.current_status.editing
            and snapshot
            and snapshot.online
            and not self._busy
        )

    def _can_save(self, *, apply: bool) -> bool:
        button = self.save_apply_button if apply else self.save_button
        return button.isEnabled()

    def _can_apply_saved(self) -> bool:
        status = self.current_status
        snapshot = self.controller_service.get_controller(self.current_controller_id)
        return bool(
            status
            and snapshot
            and snapshot.online
            and not self._busy
            and not status.editing
            and not status.config_dirty
            and not status.apply_busy
            and status.apply_state == "IDLE"
            and status.safety == "OK"
            and status.config_revision != status.runtime_revision
        )

    def _owns_current_draft(self) -> bool:
        return self._owned_draft_controller_id == self.current_controller_id

    def _confirm_save(self, apply: bool) -> bool:
        snapshot = self.controller_service.get_controller(self.current_controller_id)
        action = "SAVE & SAFE APPLY" if apply else "SAVE TO NVS"
        summary = self._change_summary_text()
        box = QMessageBox(self)
        box.setIcon(
            QMessageBox.Icon.Warning if apply else QMessageBox.Icon.Question
        )
        box.setWindowTitle(action)
        box.setText(
            f"Controller: {self.current_controller_id} · "
            f"{snapshot.name if snapshot else self.current_controller_id}\n"
            f"Action: {action}\n"
            f"Safety: {self.current_status.safety if self.current_status else 'UNKNOWN'}\n"
            f"Draft changes: {len(self._changes)}"
        )
        box.setInformativeText(
            "Safe Apply akan menunggu batas akhir current Plan dan melakukan "
            "safe transition."
            if apply
            else "Configuration disimpan ke NVS tetapi traffic runtime belum berubah."
        )
        box.setDetailedText(summary)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _selected_plan_number(self) -> int:
        item = self.plan_list.currentItem() if hasattr(self, "plan_list") else None
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else 0

    def _selected_plan_stage_count(self) -> int:
        item = self.plan_list.currentItem() if hasattr(self, "plan_list") else None
        return int(item.data(Qt.ItemDataRole.UserRole + 1)) if item else 0

    def _defined_plan_numbers(self) -> list[int]:
        if not self.current_plans:
            return []
        return [plan.number for plan in self.current_plans.plans if plan.stage_count]

    def _selected_schedule_entry(self) -> ScheduleEntryConfig | None:
        if not self.current_schedule:
            return None
        row = self.schedule_table.currentRow()
        return (
            self.current_schedule.entries[row]
            if 0 <= row < len(self.current_schedule.entries)
            else None
        )

    def _selected_holiday(self) -> HolidayConfig | None:
        if not self.current_holidays:
            return None
        row = self.holiday_table.currentRow()
        return (
            self.current_holidays.entries[row]
            if 0 <= row < len(self.current_holidays.entries)
            else None
        )

    def _change_summary_text(self) -> str:
        return (
            "\n".join(f"• {item}" for item in self._changes)
            if self._changes
            else "No tracked Draft changes."
        )

    def _update_change_label(self) -> None:
        self.change_label.setText(f"Draft changes: {len(self._changes)}")
        self.change_label.setToolTip(self._change_summary_text())

    def _record_audit(self, message: str, details: str = "") -> None:
        snapshot = self.controller_service.get_controller(self.current_controller_id)
        self.event_service.record_audit(
            self.current_controller_id,
            snapshot.name if snapshot else self.current_controller_id,
            message,
            details=details,
        )

    def _set_message(self, text: str, status: str) -> None:
        self.message_label.setText(text)
        self.message_label.setProperty("status", status)
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)

    @staticmethod
    def _centered_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    @staticmethod
    def _signal_color(state: int) -> QColor:
        return {
            1: QColor("#ff7c85"),
            2: QColor("#ffd77b"),
            3: QColor("#8de0b1"),
            4: QColor("#ffd77b"),
            5: QColor("#ffd77b"),
            6: QColor("#ffb27b"),
        }.get(state, QColor("#8295a8"))

    @staticmethod
    def _holiday_date(holiday: HolidayConfig) -> str:
        return (
            f"{holiday.day:02d}/{holiday.month:02d}/{holiday.year:04d}"
            if holiday.defined
            else "—"
        )

    @staticmethod
    def _holiday_day_name(holiday: HolidayConfig) -> str:
        if not holiday.defined:
            return "—"
        try:
            return datetime(
                holiday.year, holiday.month, holiday.day
            ).strftime("%A")
        except ValueError:
            return "INVALID DATE"
