from __future__ import annotations

from math import ceil

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..controller_service import ControllerService
from ..control_service import ControlService
from ..event_service import EventService
from ..models import CameraConfiguration, CameraRole, ControllerMode, ControllerSnapshot
from ..vlc_player import (
    FullscreenCameraDialog,
    VlcPlayerController,
    VlcRuntime,
    build_rtsp_url,
)
from ..widgets.common import MetricCell, muted_label, status_label
from ..widgets.intersection_diagram import IntersectionDiagram


class CameraSurface(QFrame):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.double_clicked.emit()
        event.accept()


class CameraTile(QFrame):
    status_changed = Signal(str, bool)
    fullscreen_requested = Signal(object, object)

    def __init__(self, camera: CameraConfiguration, parent=None) -> None:
        super().__init__(parent)
        self.camera = camera
        self.player = VlcPlayerController()
        self._active = False
        self._last_online: bool | None = None
        self._connect_ticks = 0
        self._rebound = False
        self.stream_state = "STANDBY"
        self.setObjectName("cameraTile")
        self.setMinimumWidth(0)
        self.setMinimumHeight(150)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.screen = CameraSurface()
        self.screen.setObjectName("cameraScreen")
        self.screen.setMinimumSize(0, 0)
        self.screen.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        self.screen.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.screen.double_clicked.connect(
            lambda: self.fullscreen_requested.emit(self.camera, self)
        )
        screen_layout = QVBoxLayout(self.screen)
        self.placeholder = QLabel("RTSP STANDBY")
        self.placeholder.setObjectName("cameraPlaceholder")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setMinimumSize(0, 0)
        self.placeholder.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        screen_layout.addWidget(self.placeholder)

        caption_bar = QFrame()
        caption_bar.setObjectName("cameraCaptionBar")
        caption_bar.setFixedHeight(31)
        caption_bar.setMinimumWidth(0)
        caption_layout = QHBoxLayout(caption_bar)
        caption_layout.setContentsMargins(6, 3, 5, 3)
        caption_layout.setSpacing(4)

        self.camera_name_label = QLabel()
        self.camera_name_label.setObjectName("cameraCaption")
        self.camera_name_label.setMinimumWidth(0)
        self.camera_name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

        self.stream_status_label = QLabel()
        self.stream_status_label.setObjectName("cameraStreamStatus")
        self.stream_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stream_status_label.setFixedWidth(76)

        self.fullscreen_button = QPushButton("FULLSCREEN")
        self.fullscreen_button.setObjectName("cameraFullscreenButton")
        self.fullscreen_button.setFixedWidth(72)
        self.fullscreen_button.clicked.connect(
            lambda checked=False: self.fullscreen_requested.emit(
                self.camera,
                self,
            )
        )
        caption_layout.addWidget(self.camera_name_label, 1)
        caption_layout.addWidget(self.stream_status_label)
        caption_layout.addWidget(self.fullscreen_button)
        root.addWidget(self.screen, 1)
        root.addWidget(caption_bar)

        self.state_timer = QTimer(self)
        self.state_timer.setInterval(700)
        self.state_timer.timeout.connect(self._poll_state)
        self.retry_timer = QTimer(self)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.setInterval(5000)
        self.retry_timer.timeout.connect(self._retry)
        self.refresh()

    def start(self) -> None:
        self._active = True
        self._last_online = None
        self.retry_timer.stop()
        if not self.camera.enabled:
            self.placeholder.setText("CAMERA DISABLED")
            self.stream_state = "DISABLED"
            self._set_online(False)
            return
        if not self.player.available:
            self.placeholder.setText(
                "VLC TIDAK TERSEDIA\n" + VlcRuntime.error_message()
            )
            self.stream_state = "VLC UNAVAILABLE"
            self._set_online(False)
            return

        self.placeholder.show()
        self.placeholder.setText("CONNECTING SUBSTREAM...")
        self.stream_state = "CONNECTING"
        self._connect_ticks = 0
        self._rebound = False
        self.refresh()
        url = build_rtsp_url(
            self.camera,
            main_stream=False,
            include_credentials=False,
        )
        if self.player.play(
            self.screen,
            url,
            caching_ms=1400,
            username=self.camera.username,
            password=self.camera.password,
        ):
            self.state_timer.start()
        else:
            self._stream_failed(self.player.last_error_message())

    def stop(self, *, emit_status: bool = True) -> None:
        self._active = False
        self.state_timer.stop()
        self.retry_timer.stop()
        self.player.stop()
        self.placeholder.show()
        self.placeholder.setText("RTSP STANDBY")
        self.stream_state = "STANDBY"
        self._set_online(False, emit_status=emit_status)

    def _poll_state(self) -> None:
        state = self.player.state_name()
        if state == "Playing":
            if not self._rebound:
                self.player.rebind_video_target()
                self._rebound = True
            self.placeholder.hide()
            self.stream_state = "LIVE"
            self._set_online(True)
        elif state in {"Opening", "Buffering", "NothingSpecial"}:
            self._connect_ticks += 1
            self.placeholder.show()
            self.placeholder.setText("CONNECTING SUBSTREAM...")
            self.stream_state = (
                f"{state.upper()} · {self._connect_ticks * 0.7:.1f}s"
            )
            self.refresh()
            if self._connect_ticks >= 18:
                self._stream_failed("TIMEOUT 12s")
        elif state in {"Error", "Ended", "Stopped"}:
            self._stream_failed(state.upper())

    def _stream_failed(self, reason: str = "ERROR") -> None:
        self.state_timer.stop()
        self.player.stop()
        self.placeholder.show()
        self.placeholder.setText("STREAM OFFLINE\nRetry 5 seconds")
        self.stream_state = f"RETRY · {reason}"
        self._set_online(False)
        if self._active:
            self.retry_timer.start()

    def _retry(self) -> None:
        if self._active:
            self.start()

    def _set_online(self, online: bool, *, emit_status: bool = True) -> None:
        self.camera.online = online
        self.refresh()
        if self._last_online is online:
            return
        self._last_online = online
        if emit_status:
            self.status_changed.emit(self.camera.camera_id, online)

    def refresh(self) -> None:
        self.camera_name_label.setText(self.camera.name)
        self.camera_name_label.setToolTip(self.camera.name)
        state = self.stream_state.split(" · ", 1)[0]
        if state == "VLC UNAVAILABLE":
            state = "VLC ERROR"
        self.stream_status_label.setText(f"● {state}")
        self.stream_status_label.setToolTip(self.stream_state)


class LiveView(QWidget):
    def __init__(
        self,
        service: ControllerService,
        event_service: EventService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.event_service = event_service
        self.control_service = ControlService(service, self)
        self.current_controller_id = (
            service.controllers[0].controller_id if service.controllers else ""
        )
        self.camera_tiles: list[CameraTile] = []
        self.command_buttons: dict[str, QPushButton] = {}
        self._control_busy = False
        self.streaming_active = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 18)
        root.setSpacing(10)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        self.title = QLabel("Live View")
        self.title.setObjectName("pageTitle")
        self.subtitle = muted_label()
        title_column.addWidget(self.title)
        title_column.addWidget(self.subtitle)
        header.addLayout(title_column)
        header.addStretch()
        self.controller_selector = QComboBox()
        self.controller_selector.currentIndexChanged.connect(
            self._selector_changed
        )
        header.addWidget(self.controller_selector)
        self.connection_label = status_label("● CONTROLLER ONLINE")
        header.addWidget(self.connection_label)
        root.addLayout(header)

        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("summaryPanel")
        summary_layout = QHBoxLayout(self.summary_frame)
        summary_layout.setContentsMargins(8, 8, 8, 8)
        summary_layout.setSpacing(7)
        self.mode_metric = MetricCell("Mode")
        self.safety_metric = MetricCell("Safety")
        self.current_plan_metric = MetricCell("Current Plan")
        self.stage_metric = MetricCell("Current Stage")
        self.scheduled_plan_metric = MetricCell("Scheduled Plan")
        self.remaining_metric = MetricCell("Remaining Time")
        self.revision_metric = MetricCell("Config / Runtime Rev")
        for metric in [
            self.mode_metric,
            self.safety_metric,
            self.current_plan_metric,
            self.stage_metric,
            self.scheduled_plan_metric,
            self.remaining_metric,
        ]:
            summary_layout.addWidget(metric, 1)
        self.revision_metric.setMinimumWidth(168)
        self.revision_metric.value_label.setProperty(
            "revisionState",
            "unknown",
        )
        self.revision_metric.value_label.style().unpolish(
            self.revision_metric.value_label
        )
        self.revision_metric.value_label.style().polish(
            self.revision_metric.value_label
        )
        summary_layout.addWidget(self.revision_metric, 2)
        root.addWidget(self.summary_frame)

        body = QHBoxLayout()
        body.setSpacing(11)

        self.camera_panel = QFrame()
        self.camera_panel.setObjectName("contentPanel")
        self.camera_panel.setMinimumWidth(0)
        self.camera_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        camera_panel_layout = QVBoxLayout(self.camera_panel)
        camera_panel_layout.setContentsMargins(11, 10, 11, 11)
        camera_title_row = QHBoxLayout()
        camera_title = QLabel("Live Camera")
        camera_title.setObjectName("sectionTitle")
        camera_title_row.addWidget(camera_title)
        camera_title_row.addStretch()
        camera_hint = muted_label("SUBSTREAM · double-click untuk fullscreen")
        camera_hint.setMinimumWidth(0)
        camera_hint.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        camera_title_row.addWidget(camera_hint)
        camera_panel_layout.addLayout(camera_title_row)
        self.camera_grid_widget = QWidget()
        self.camera_grid_widget.setMinimumWidth(0)
        self.camera_grid_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        self.camera_grid = QGridLayout(self.camera_grid_widget)
        self.camera_grid.setContentsMargins(0, 0, 0, 0)
        self.camera_grid.setSpacing(7)
        camera_panel_layout.addWidget(self.camera_grid_widget, 1)
        body.addWidget(self.camera_panel)

        self.control_panel = QFrame()
        self.control_panel.setObjectName("contentPanel")
        self.control_panel.setMinimumWidth(340)
        self.control_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        control_layout = QVBoxLayout(self.control_panel)
        control_layout.setContentsMargins(11, 10, 11, 11)
        control_title = QLabel("Live Intersection Diagram")
        control_title.setObjectName("sectionTitle")
        control_layout.addWidget(control_title)
        self.intersection_diagram = IntersectionDiagram()
        control_layout.addWidget(self.intersection_diagram, 1)
        self.extra_signal_label = muted_label()
        self.extra_signal_label.setWordWrap(True)
        self.extra_signal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control_layout.addWidget(self.extra_signal_label)

        command_title = QLabel("Traffic Control")
        command_title.setObjectName("sectionTitle")
        control_layout.addWidget(command_title)
        command_row = QGridLayout()
        for column, command in enumerate(["SKIP", "HOLD", "FLASHING"]):
            button = QPushButton(command)
            if command == "FLASHING":
                button.setObjectName("dangerButton")
            button.clicked.connect(
                lambda checked=False, value=command: self._control_command(value)
            )
            command_row.addWidget(button, 0, column)
            self.command_buttons[command] = button
        control_layout.addLayout(command_row)
        self.command_message = muted_label("Traffic Control ready · MOCK MODE")
        self.command_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control_layout.addWidget(self.command_message)
        body.addWidget(self.control_panel)
        body.setStretch(0, 7)
        body.setStretch(1, 4)
        root.addLayout(body, 1)

        self.service.snapshot_updated.connect(self._snapshot_updated)
        self.service.controllers_changed.connect(self._controllers_changed)
        self.control_service.completed.connect(self._control_completed)
        self.control_service.failed.connect(self._control_failed)
        self.control_service.busy_changed.connect(self._control_busy_changed)
        self._controllers_changed()

    def _controllers_changed(self) -> None:
        previous = self.current_controller_id
        self.controller_selector.blockSignals(True)
        self.controller_selector.clear()
        for controller in self.service.controllers:
            self.controller_selector.addItem(
                f"{controller.controller_id} · {controller.name}",
                controller.controller_id,
            )
        self.controller_selector.blockSignals(False)

        for button in self.command_buttons.values():
            button.setEnabled(not self.service.is_live)
        self.command_message.setText(
            "Traffic Control menunggu status controller"
            if self.service.is_live
            else "Traffic Control ready · MOCK MODE"
        )

        if not self.service.controllers:
            self.current_controller_id = ""
            self.title.setText("No Controller Configured")
            self.subtitle.setText(
                "Buka CONTROLLERS untuk mengaktifkan koneksi ESP32-S3."
            )
            self.connection_label.setText("● OFFLINE")
            self.connection_label.setProperty("status", "offline")
            self.connection_label.style().unpolish(self.connection_label)
            self.connection_label.style().polish(self.connection_label)
            self.intersection_diagram.set_signal_groups([])
            self.revision_metric.set_value("— / — · OFFLINE")
            self._set_revision_state("offline")
            self._stop_all_cameras(emit_status=False)
            self._clear_layout(self.camera_grid)
            self.camera_tiles.clear()
            return

        available_ids = {
            item.controller_id for item in self.service.controllers
        }
        target = (
            previous
            if previous in available_ids
            else self.service.controllers[0].controller_id
        )
        self.set_controller(target)

    def set_controller(self, controller_id: str) -> None:
        snapshot = self.service.get_controller(controller_id)
        if not snapshot:
            return
        self.current_controller_id = controller_id
        index = self.controller_selector.findData(controller_id)
        if index >= 0 and index != self.controller_selector.currentIndex():
            self.controller_selector.blockSignals(True)
            self.controller_selector.setCurrentIndex(index)
            self.controller_selector.blockSignals(False)
        self._rebuild_cameras(snapshot)
        self.intersection_diagram.set_signal_groups(snapshot.signal_groups)
        self._update_extra_signal_text(snapshot)
        self._apply_snapshot(snapshot)

    def set_streaming_active(self, active: bool) -> None:
        self.streaming_active = active
        if active and self.service.is_live:
            for tile in self.camera_tiles:
                tile.start()
        else:
            self._stop_all_cameras(emit_status=False)

    def _selector_changed(self) -> None:
        controller_id = self.controller_selector.currentData()
        if controller_id:
            self.set_controller(str(controller_id))

    def _clear_layout(self, layout: QGridLayout | QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _rebuild_cameras(self, snapshot: ControllerSnapshot) -> None:
        self._stop_all_cameras(emit_status=False)
        self._clear_layout(self.camera_grid)
        self.camera_tiles.clear()
        fixed_cameras = [
            camera for camera in snapshot.cameras
            if camera.role == CameraRole.SIGNAL_GROUP and camera.enabled
        ]
        ptz = next(
            (
                camera for camera in snapshot.cameras
                if camera.role == CameraRole.PTZ and camera.enabled
            ),
            None,
        )

        if not fixed_cameras and ptz is None:
            empty_label = muted_label(
                "No camera enabled · buka CAMERA CONFIGURATION"
            )
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.camera_grid.addWidget(empty_label, 0, 0, 1, 4)

        rows = max(2, ceil(len(fixed_cameras) / 2))
        if ptz:
            tile = CameraTile(ptz)
            self._connect_camera_tile(tile)
            self.camera_grid.addWidget(tile, 0, 0, rows, 2)
            self.camera_tiles.append(tile)

        for index, camera in enumerate(fixed_cameras):
            row = index // 2
            column = 2 + (index % 2)
            tile = CameraTile(camera)
            self._connect_camera_tile(tile)
            self.camera_grid.addWidget(tile, row, column)
            self.camera_tiles.append(tile)

        for column in range(4):
            self.camera_grid.setColumnStretch(column, 1)
        for row in range(rows):
            self.camera_grid.setRowStretch(row, 1)
        if self.streaming_active and self.service.is_live:
            for tile in self.camera_tiles:
                tile.start()

    def _connect_camera_tile(self, tile: CameraTile) -> None:
        tile.status_changed.connect(self._camera_status_changed)
        tile.fullscreen_requested.connect(self._open_camera_fullscreen)

    def _stop_all_cameras(self, *, emit_status: bool = True) -> None:
        for tile in self.camera_tiles:
            tile.stop(emit_status=emit_status)

    def _camera_status_changed(self, camera_id: str, online: bool) -> None:
        snapshot = self.service.get_controller(self.current_controller_id)
        if snapshot and self.event_service:
            camera = next(
                (item for item in snapshot.cameras if item.camera_id == camera_id),
                None,
            )
            self.event_service.handle_camera_status(
                snapshot.controller_id,
                camera_id,
                camera.name if camera else camera_id,
                online,
            )
        if self.current_controller_id:
            self.service.snapshot_updated.emit(self.current_controller_id)

    def _open_camera_fullscreen(
        self,
        camera: CameraConfiguration,
        tile: CameraTile,
    ) -> None:
        tile.stop(emit_status=False)
        dialog = FullscreenCameraDialog(camera, self)
        dialog.open_fullscreen()
        if self.streaming_active and self.service.is_live:
            tile.start()

    def _apply_snapshot(self, snapshot: ControllerSnapshot) -> None:
        enabled_camera_count = sum(
            camera.enabled for camera in snapshot.cameras
        )
        if len(self.camera_tiles) != enabled_camera_count:
            self._rebuild_cameras(snapshot)
        self.title.setText(snapshot.name)
        identity = (
            f"ID {snapshot.reported_controller_id:03d}"
            if snapshot.reported_controller_id is not None
            else snapshot.controller_id
        )
        self.subtitle.setText(
            f"{identity} · {snapshot.network_interface.value} · "
            f"{snapshot.ip_address} · Firmware {snapshot.firmware_version}"
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
        self._update_revision_metric(snapshot)

        self.intersection_diagram.set_signal_groups(snapshot.signal_groups)
        self._update_extra_signal_text(snapshot)

        status = "online" if snapshot.online else "offline"
        self.connection_label.setText(
            "● CONTROLLER ONLINE" if snapshot.online else "● CONTROLLER OFFLINE"
        )
        self.connection_label.setProperty("status", status)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)
        self._update_control_buttons(snapshot)

    def _update_revision_metric(self, snapshot: ControllerSnapshot) -> None:
        apply_state = snapshot.apply_state.upper()
        if not snapshot.online:
            self.revision_metric.set_value("— / — · OFFLINE")
            self.revision_metric.value_label.setToolTip(
                "Controller offline. Revision tidak dapat diverifikasi."
            )
            self._set_revision_state("offline")
            return

        config_revision = snapshot.config_revision
        runtime_revision = snapshot.runtime_revision
        self.revision_metric.set_value(
            f"{config_revision} / {runtime_revision} · {apply_state}"
        )
        if snapshot.safety_status != "OK" or apply_state == "FAULT":
            state = "fault"
            tooltip = (
                "Safety tidak OK. Perubahan runtime dapat diblokir oleh controller."
            )
        elif apply_state not in {"IDLE", "UNKNOWN"}:
            state = "applying"
            tooltip = (
                f"Safe Apply sedang berjalan: {apply_state}. "
                "Runtime Revision akan menyamai Config Revision setelah selesai."
            )
        elif config_revision != runtime_revision:
            state = "pending"
            tooltip = (
                "Configuration sudah tersimpan tetapi belum aktif pada traffic "
                "runtime. Gunakan Apply Saved saat kondisi aman."
            )
        elif apply_state == "IDLE" and config_revision > 0:
            state = "synced"
            tooltip = "Configuration dan traffic runtime sudah sinkron."
        else:
            state = "unknown"
            tooltip = "Status revision belum tersedia."
        self.revision_metric.value_label.setToolTip(tooltip)
        self._set_revision_state(state)

    def _set_revision_state(self, state: str) -> None:
        label = self.revision_metric.value_label
        if label.property("revisionState") == state:
            return
        label.setProperty("revisionState", state)
        label.style().unpolish(label)
        label.style().polish(label)

    def _update_extra_signal_text(self, snapshot: ControllerSnapshot) -> None:
        if len(snapshot.signal_groups) <= 4:
            self.extra_signal_label.clear()
            return
        self.extra_signal_label.setText(
            "Additional SG · "
            + "  ".join(
                f"SG{item.number}:{item.aspect[0]}"
                for item in snapshot.signal_groups[4:]
            )
        )

    def _snapshot_updated(self, controller_id: str) -> None:
        if controller_id != self.current_controller_id:
            return
        snapshot = self.service.get_controller(controller_id)
        if snapshot:
            index = self.controller_selector.findData(controller_id)
            if index >= 0:
                self.controller_selector.setItemText(
                    index,
                    f"{snapshot.controller_id} · {snapshot.name}",
                )
            self._apply_snapshot(snapshot)

    def _mock_command(self, command: str) -> None:
        if self.service.is_live:
            self.command_message.setText(
                "Read-only monitoring · perintah tidak dikirim"
            )
            return
        self.command_message.setText(
            f"{command} selected · simulasi, tidak ada perintah dikirim"
        )

    def _update_control_buttons(self, snapshot: ControllerSnapshot) -> None:
        if not self.service.is_live:
            for button in self.command_buttons.values():
                button.setEnabled(not self._control_busy)
            return
        safe = snapshot.online and snapshot.safety_status == "OK"
        idle = snapshot.apply_state == "IDLE"
        wait = snapshot.apply_state == "WAIT"
        any_green = any(item.aspect == "GREEN" for item in snapshot.signal_groups)
        physical_hold = snapshot.hold_active and not snapshot.web_hold_active
        physical_flash = snapshot.local_flashing_active
        enabled = not self._control_busy
        self.command_buttons["SKIP"].setEnabled(
            enabled
            and safe
            and idle
            and snapshot.mode == ControllerMode.NORMAL
            and not snapshot.skip_pending
            and any_green
        )
        self.command_buttons["HOLD"].setEnabled(
            enabled
            and safe
            and not physical_hold
            and not physical_flash
            and (idle or (wait and snapshot.web_hold_active))
        )
        self.command_buttons["FLASHING"].setEnabled(
            enabled
            and safe
            and not (physical_flash and not snapshot.web_flashing_active)
            and (idle or (wait and snapshot.web_flashing_active))
        )
        self.command_buttons["SKIP"].setText(
            "SKIP PENDING" if snapshot.skip_pending else "SKIP"
        )
        self.command_buttons["HOLD"].setText(
            f"CANCEL HOLD {snapshot.hold_remaining_seconds}s"
            if snapshot.web_hold_active
            else "HOLD"
        )
        self.command_buttons["FLASHING"].setText(
            "STOP FLASHING" if snapshot.web_flashing_active else "FLASHING"
        )
        if not snapshot.online:
            message = "Traffic Control disabled · controller offline"
        elif snapshot.safety_status != "OK":
            message = f"Traffic Control disabled · SAFETY {snapshot.safety_status}"
        elif snapshot.web_flashing_active:
            message = "WEB FLASHING active · traffic timer paused"
        elif snapshot.local_flashing_active:
            message = "LOCAL FLASHING active · release from local input"
        elif snapshot.web_hold_active:
            message = f"WEB HOLD active · auto release {snapshot.hold_remaining_seconds}s"
        elif snapshot.hold_active:
            message = "LOCAL HOLD active · release from local input"
        elif snapshot.skip_pending:
            message = "SKIP pending · waiting Minimum Green"
        elif not idle:
            message = f"Traffic Control waiting · Safe Apply {snapshot.apply_state}"
        else:
            message = "Traffic Control ready"
        if not self._control_busy:
            self.command_message.setText(message)

    def _control_command(self, command: str) -> None:
        snapshot = self.service.get_controller(self.current_controller_id)
        if not snapshot:
            return
        if not self.service.is_live:
            self._mock_command(command)
            return
        action = command.lower()
        active: bool | None = None
        if command == "SKIP":
            prompt = (
                "Kirim perintah SKIP ke controller?\n\n"
                "Controller tetap memeriksa Minimum Green dan dapat menunda atau menolak SKIP."
            )
        elif command == "HOLD":
            active = not snapshot.web_hold_active
            prompt = (
                "Batalkan WEB HOLD dan lanjutkan countdown Stage?"
                if not active
                else "Aktifkan TIMED HOLD?\n\nStage countdown akan dibekukan sampai Hold Duration habis."
            )
        else:
            active = not snapshot.web_flashing_active
            prompt = (
                "Hentikan WEB FLASHING dan pulihkan Current Stage?"
                if not active
                else "Aktifkan WEB FLASHING?\n\nActive Signal Group akan Yellow Flashing 500 ms dan traffic timer dipause."
            )
        answer = QMessageBox.question(
            self,
            f"Confirm {command}",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.control_service.send(snapshot.controller_id, action, active)

    def _control_busy_changed(self, busy: bool) -> None:
        self._control_busy = busy
        if busy:
            self.command_message.setText("Sending Traffic Control command...")
            for button in self.command_buttons.values():
                button.setEnabled(False)
        else:
            snapshot = self.service.get_controller(self.current_controller_id)
            if snapshot:
                self._update_control_buttons(snapshot)

    def _control_completed(
        self,
        controller_id: str,
        action: str,
        payload: object,
    ) -> None:
        if controller_id != self.current_controller_id or not isinstance(payload, dict):
            return
        message = str(payload.get("message") or f"{action.upper()} completed.")
        self.command_message.setText(message)
        snapshot = self.service.get_controller(controller_id)
        if snapshot and self.event_service:
            self.event_service.record_audit(
                controller_id,
                snapshot.name,
                f"Traffic Control {action.upper()} accepted",
                details=message,
            )

    def _control_failed(self, controller_id: str, action: str, message: str) -> None:
        if controller_id != self.current_controller_id:
            return
        self.command_message.setText(f"{action.upper()} rejected · {message}")
        QMessageBox.warning(self, "Traffic Control Rejected", message)
        snapshot = self.service.get_controller(controller_id)
        if snapshot and self.event_service:
            self.event_service.record_audit(
                controller_id,
                snapshot.name,
                f"Traffic Control {action.upper()} rejected",
                details=message,
            )
