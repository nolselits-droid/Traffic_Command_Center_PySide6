from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .controller_service import ControllerService
from .event_service import EventService
from .views.alarms_events_view import AlarmsEventsView
from .views.backup_restore_view import BackupRestoreView
from .views.camera_config_view import CameraConfigView
from .views.controller_config_view import ControllerConfigView
from .views.live_view import LiveView
from .views.overview_view import OverviewView
from .views.placeholder_view import PlaceholderView
from .views.system_settings_view import SystemSettingsView
from .views.traffic_config_view import TrafficConfigView
from .widgets.common import muted_label, status_label


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Traffic Command Center V0.6.01 TEST1 FIX8")
        self.setMinimumSize(1180, 700)
        self.resize(1600, 900)

        self.service = ControllerService(self)
        self.event_service = EventService(self.service, self)
        self.ui_settings = QSettings(
            "Nolselits",
            "TrafficCommandCenter",
        )
        self._sidebar_visible = self.ui_settings.value(
            "ui/sidebarVisible",
            True,
            type=bool,
        )
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar())
        self.event_service.active_alarm_count_changed.connect(
            self._update_alarm_badge
        )
        counts = self.event_service.summary()
        self._update_alarm_badge(
            counts["critical"],
            counts["warning"],
            counts["unacknowledged"],
        )

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        self._create_pages()
        self._apply_sidebar_visibility(persist=False)
        self.stack.currentChanged.connect(self._stack_page_changed)
        self.service.snapshot_updated.connect(self._update_global_status)
        self.service.controllers_changed.connect(self._update_global_status)
        self._update_global_status()
        self.navigate("overview")
        self.statusBar().showMessage(
            "V0.6.01 TEST1 FIX8 · Destination Road Arm Layout"
        )
        self.event_service.record_audit(
            "SYSTEM",
            "Command Center",
            "Command Center V0.6.01 TEST1 FIX8 started",
        )

        fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        fullscreen_shortcut.activated.connect(self._toggle_fullscreen)
        escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        escape_shortcut.activated.connect(self._leave_fullscreen)
        sidebar_shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        sidebar_shortcut.activated.connect(self._toggle_sidebar)
        self.sidebar_shortcut = sidebar_shortcut

    def _build_top_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")
        frame.setFixedHeight(70)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(20, 9, 20, 9)

        self.sidebar_toggle_button = QPushButton("☰")
        self.sidebar_toggle_button.setObjectName("sidebarToggleButton")
        self.sidebar_toggle_button.setFixedSize(38, 38)
        self.sidebar_toggle_button.clicked.connect(self._toggle_sidebar)
        layout.addWidget(self.sidebar_toggle_button)
        layout.addSpacing(4)

        identity = QVBoxLayout()
        identity.setSpacing(1)
        title = QLabel("TRAFFIC COMMAND CENTER")
        title.setObjectName("appTitle")
        subtitle = muted_label(
            "Central Monitoring & Control · PySide6 V0.6.01 TEST1 FIX8"
        )
        identity.addWidget(title)
        identity.addWidget(subtitle)
        layout.addLayout(identity)
        layout.addStretch()

        self.global_status_label = status_label("● CONTROLLER STATUS")
        layout.addWidget(self.global_status_label)
        self.alarm_button = QPushButton("ALARM 0")
        self.alarm_button.setObjectName("alarmButton")
        self.alarm_button.clicked.connect(
            lambda checked=False: self.navigate("alarms")
        )
        layout.addWidget(self.alarm_button)
        layout.addSpacing(22)
        operator = QVBoxLayout()
        operator.setSpacing(1)
        self.clock_label = QLabel()
        self.clock_label.setObjectName("headerClock")
        self.clock_label.setFixedWidth(270)
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        operator_label = muted_label("Operator Pusat")
        operator_label.setFixedWidth(270)
        operator_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        operator.addWidget(self.clock_label)
        operator.addWidget(operator_label)
        layout.addLayout(operator)

        timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(self._update_clock)
        timer.start()
        self.clock_timer = timer
        self._update_clock()
        return frame

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sideBar")
        sidebar.setFixedWidth(235)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(5)

        group = QButtonGroup(self)
        group.setExclusive(True)
        definitions = [
            ("overview", "OVERVIEW"),
            ("live", "LIVE VIEW"),
            ("controllers", "CONTROLLERS"),
            ("traffic", "TRAFFIC CONFIGURATION"),
            ("camera", "CAMERA CONFIGURATION"),
            ("alarms", "ALARMS & EVENTS"),
            ("backup", "BACKUP & RESTORE"),
            ("system", "SYSTEM SETTINGS"),
            ("users", "USERS"),
        ]
        for key, text in definitions:
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, page_key=key: self.navigate(page_key)
            )
            group.addButton(button)
            layout.addWidget(button)
            self.nav_buttons[key] = button
        layout.addStretch()
        layout.addWidget(muted_label("Target: 1920×1080\nFallback: 1366×768"))
        self.nav_group = group
        return sidebar

    def _create_pages(self) -> None:
        overview = OverviewView(self.service)
        overview.controller_open_requested.connect(self.open_controller)
        live = LiveView(self.service, self.event_service)
        camera = CameraConfigView(self.service)
        controllers = ControllerConfigView(self.service, self.event_service)

        self._add_page("overview", overview)
        self._add_page("live", live)
        self._add_page("controllers", controllers)
        self._add_page(
            "traffic",
            TrafficConfigView(self.service, self.event_service),
        )
        self._add_page("camera", camera)
        self._add_page(
            "alarms",
            AlarmsEventsView(self.event_service, self.service),
        )
        self._add_page(
            "backup",
            BackupRestoreView(self.service, self.event_service),
        )
        self._add_page(
            "system",
            SystemSettingsView(self.service, self.event_service),
        )
        self._add_page(
            "users",
            PlaceholderView(
                "Users",
                "Role Monitor, Operator dan Engineer/Admin akan ditambahkan pada tahap keamanan.",
            ),
        )

    def _add_page(self, key: str, widget: QWidget) -> None:
        self.pages[key] = widget
        self.stack.addWidget(widget)

    def navigate(self, key: str) -> None:
        page = self.pages.get(key)
        if not page:
            return
        self.stack.setCurrentWidget(page)
        button = self.nav_buttons.get(key)
        if button:
            button.setChecked(True)

    def open_controller(self, controller_id: str) -> None:
        live_view = self.pages.get("live")
        if isinstance(live_view, LiveView):
            live_view.set_controller(controller_id)
        self.navigate("live")

    def _update_clock(self) -> None:
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S  %d/%m/%Y"))

    def _toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        self._apply_sidebar_visibility(persist=True)

    def _apply_sidebar_visibility(self, *, persist: bool) -> None:
        live_view = self.pages.get("live")
        if (
            not self._sidebar_visible
            and isinstance(live_view, LiveView)
        ):
            stored_width = self.ui_settings.value(
                "ui/liveControlPanelWidth",
                0,
                type=int,
            )
            fixed_width = live_view.freeze_control_panel_width(
                None if persist else stored_width
            )
            self.ui_settings.setValue(
                "ui/liveControlPanelWidth",
                fixed_width,
            )
        if hasattr(self, "sidebar"):
            self.sidebar.setVisible(self._sidebar_visible)
        if hasattr(self, "sidebar_toggle_button"):
            self.sidebar_toggle_button.setToolTip(
                "Hide navigation · Ctrl+B"
                if self._sidebar_visible
                else "Open navigation · Ctrl+B"
            )
            self.sidebar_toggle_button.setProperty(
                "sidebarOpen",
                self._sidebar_visible,
            )
            self.sidebar_toggle_button.style().unpolish(
                self.sidebar_toggle_button
            )
            self.sidebar_toggle_button.style().polish(
                self.sidebar_toggle_button
            )
        if persist:
            self.ui_settings.setValue(
                "ui/sidebarVisible",
                self._sidebar_visible,
            )
            self.ui_settings.sync()

    def _update_global_status(self, *_args) -> None:
        total = len(self.service.controllers)
        online = sum(item.online for item in self.service.controllers)
        if not total:
            text = "● NO CONTROLLER · LIVE"
            status = "offline"
        else:
            text = f"● {online}/{total} ONLINE · LIVE"
            status = "online" if online == total else "warning"
        self.global_status_label.setText(text)
        self.global_status_label.setProperty("status", status)
        self.global_status_label.style().unpolish(self.global_status_label)
        self.global_status_label.style().polish(self.global_status_label)

    def _stack_page_changed(self, _index: int) -> None:
        live_view = self.pages.get("live")
        if isinstance(live_view, LiveView):
            live_view.set_streaming_active(
                self.stack.currentWidget() is live_view
            )
        traffic_view = self.pages.get("traffic")
        if isinstance(traffic_view, TrafficConfigView):
            traffic_view.set_active(
                self.stack.currentWidget() is traffic_view
            )
        system_view = self.pages.get("system")
        if isinstance(system_view, SystemSettingsView):
            system_view.set_active(
                self.stack.currentWidget() is system_view
            )

    def _update_alarm_badge(
        self,
        critical: int,
        warning: int,
        unacknowledged: int,
    ) -> None:
        active = critical + warning
        self.alarm_button.setText(
            f"ALARM {active} · NEW {unacknowledged}"
            if active
            else "ALARM 0"
        )
        severity = "critical" if critical else "warning" if warning else "normal"
        self.alarm_button.setProperty("severity", severity)
        self.alarm_button.style().unpolish(self.alarm_button)
        self.alarm_button.style().polish(self.alarm_button)

    def closeEvent(self, event) -> None:  # noqa: N802
        traffic_view = self.pages.get("traffic")
        if (
            isinstance(traffic_view, TrafficConfigView)
            and not traffic_view.confirm_application_close()
        ):
            event.ignore()
            return
        live_view = self.pages.get("live")
        if isinstance(live_view, LiveView):
            live_view.set_streaming_active(False)
        self.event_service.record_audit(
            "SYSTEM",
            "Command Center",
            "Command Center closed",
        )
        super().closeEvent(event)

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def _leave_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
