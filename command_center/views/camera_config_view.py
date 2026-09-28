from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..controller_service import ControllerService
from ..models import CameraConfiguration
from ..vlc_player import FullscreenCameraDialog, VlcRuntime, build_rtsp_url
from ..widgets.common import muted_label, status_label


class CameraConfigView(QWidget):
    def __init__(self, service: ControllerService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.current_controller_id = (
            service.controllers[0].controller_id if service.controllers else ""
        )
        self.current_camera: CameraConfiguration | None = None
        self.camera_buttons: list[QPushButton] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(13)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title = QLabel("Camera Configuration")
        title.setObjectName("pageTitle")
        self.subtitle = muted_label()
        title_column.addWidget(title)
        title_column.addWidget(self.subtitle)
        header.addLayout(title_column)
        header.addStretch()

        self.controller_selector = QComboBox()
        self.controller_selector.currentIndexChanged.connect(
            self._controller_changed
        )
        header.addWidget(self.controller_selector)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(12)

        camera_list_panel = QFrame()
        camera_list_panel.setObjectName("contentPanel")
        camera_list_panel.setFixedWidth(290)
        camera_list_layout = QVBoxLayout(camera_list_panel)
        camera_list_layout.setContentsMargins(11, 11, 11, 11)
        list_title = QLabel("Camera List")
        list_title.setObjectName("sectionTitle")
        camera_list_layout.addWidget(list_title)
        self.camera_button_layout = QVBoxLayout()
        self.camera_button_layout.setSpacing(6)
        camera_list_layout.addLayout(self.camera_button_layout)
        camera_list_layout.addStretch()
        body.addWidget(camera_list_panel)

        form_panel = QFrame()
        form_panel.setObjectName("formPanel")
        form_root = QVBoxLayout(form_panel)
        form_root.setContentsMargins(16, 14, 16, 14)
        form_root.setSpacing(12)

        form_header = QHBoxLayout()
        self.camera_title = QLabel("Camera")
        self.camera_title.setObjectName("sectionTitle")
        form_header.addWidget(self.camera_title)
        form_header.addStretch()
        self.camera_status = status_label("● CONNECTED")
        form_header.addWidget(self.camera_status)
        form_root.addLayout(form_header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.profile_input = QComboBox()
        self.profile_input.addItems(["Hikvision Standard", "Custom RTSP"])
        self.enabled_input = QCheckBox("Enable camera")
        self.name_input = QLineEdit()
        self.host_input = QLineEdit()
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.main_path_input = QLineEdit()
        self.sub_path_input = QLineEdit()
        self.rtsp_cache_input = QSpinBox()
        self.rtsp_cache_input.setRange(200, 3000)
        self.rtsp_cache_input.setSingleStep(100)
        self.rtsp_cache_input.setSuffix(" ms")
        self.rtsp_cache_input.setToolTip(
            "Nilai kecil mengurangi delay tetapi membutuhkan jaringan yang "
            "lebih stabil. Rekomendasi awal: 800 ms."
        )

        form.addRow("Camera profile", self.profile_input)
        form.addRow("Camera state", self.enabled_input)
        form.addRow("Camera name", self.name_input)
        form.addRow("Camera IP / hostname", self.host_input)
        form.addRow("RTSP port", self.port_input)
        form.addRow("Username", self.username_input)
        form.addRow("Password", self.password_input)
        form.addRow("Main stream path", self.main_path_input)
        form.addRow("Substream path", self.sub_path_input)
        form.addRow("RTSP cache / latency", self.rtsp_cache_input)
        form_root.addLayout(form)

        note = muted_label(
            "Preset Hikvision memakai /Streaming/Channels/101 dan 102. "
            "Custom RTSP dapat diisi sesuai kondisi lapangan. Cache kecil "
            "mengurangi delay; cache besar lebih stabil."
        )
        note.setWordWrap(True)
        form_root.addWidget(note)
        form_root.addStretch()

        actions = QHBoxLayout()
        actions.addStretch()
        test_button = QPushButton("TEST CONNECTION")
        test_button.clicked.connect(self._test_connection)
        preview_button = QPushButton("PREVIEW")
        preview_button.clicked.connect(self._preview_main_stream)
        save_button = QPushButton("SAVE CAMERA")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save_camera)
        actions.addWidget(test_button)
        actions.addWidget(preview_button)
        actions.addWidget(save_button)
        form_root.addLayout(actions)

        self.result_label = muted_label(
            "Password kamera tidak disimpan di file konfigurasi."
        )
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        form_root.addWidget(self.result_label)
        body.addWidget(form_panel, 1)
        root.addLayout(body, 1)

        self.service.controllers_changed.connect(self._controllers_changed)
        self.service.snapshot_updated.connect(self._snapshot_updated)
        self._controllers_changed()

    def _snapshot_updated(self, controller_id: str) -> None:
        if controller_id != self.current_controller_id:
            return
        snapshot = self.service.get_controller(controller_id)
        if snapshot and len(self.camera_buttons) != len(snapshot.cameras):
            self._load_controller(controller_id)
        elif self.current_camera:
            self._update_camera_status(self.current_camera.online)

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

        if not self.service.controllers:
            self.current_controller_id = ""
            self.subtitle.setText(
                "Tidak ada controller aktif. Buka halaman CONTROLLERS."
            )
            self._clear_camera_buttons()
            return

        available_ids = {
            item.controller_id for item in self.service.controllers
        }
        target = (
            previous
            if previous in available_ids
            else self.service.controllers[0].controller_id
        )
        index = self.controller_selector.findData(target)
        if index >= 0:
            self.controller_selector.setCurrentIndex(index)
        self._load_controller(target)

    def set_controller(self, controller_id: str) -> None:
        index = self.controller_selector.findData(controller_id)
        if index >= 0:
            self.controller_selector.setCurrentIndex(index)

    def _controller_changed(self) -> None:
        controller_id = self.controller_selector.currentData()
        if controller_id:
            self._load_controller(str(controller_id))

    def _clear_camera_buttons(self) -> None:
        while self.camera_button_layout.count():
            item = self.camera_button_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.camera_buttons.clear()

    def _load_controller(self, controller_id: str) -> None:
        snapshot = self.service.get_controller(controller_id)
        if not snapshot:
            return
        self.current_controller_id = controller_id
        enabled_count = sum(camera.enabled for camera in snapshot.cameras)
        self.subtitle.setText(
            f"{snapshot.name} · {enabled_count}/{len(snapshot.cameras)} cameras enabled · PTZ optional"
        )
        self._clear_camera_buttons()
        group = QButtonGroup(self)
        group.setExclusive(True)

        for index, camera in enumerate(snapshot.cameras):
            button = QPushButton(camera.name)
            button.setObjectName("cameraListButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, selected=camera: self._load_camera(selected)
            )
            group.addButton(button)
            self.camera_button_layout.addWidget(button)
            self.camera_buttons.append(button)
            if index == 0:
                button.setChecked(True)
                self._load_camera(camera)

        # Retain ownership for the lifetime of the generated button set.
        self.camera_button_group = group

    def _load_camera(self, camera: CameraConfiguration) -> None:
        self.current_camera = camera
        self.camera_title.setText(camera.name)
        self.profile_input.setCurrentText(camera.profile)
        self.enabled_input.setChecked(camera.enabled)
        self.name_input.setText(camera.name)
        self.host_input.setText(camera.host)
        self.port_input.setValue(camera.port)
        self.username_input.setText(camera.username)
        self.password_input.setText(camera.password)
        self.main_path_input.setText(camera.main_path)
        self.sub_path_input.setText(camera.sub_path)
        self.rtsp_cache_input.setValue(camera.rtsp_cache_ms)
        self._update_camera_status(camera.online)
        self.result_label.setText(
            "Ready · " + self.service.camera_repository.password_storage_message
        )

    def _save_camera(self) -> None:
        if not self.current_camera:
            return
        camera = self._apply_form_to_camera()
        if camera is None:
            return
        message = self.service.camera_repository.save_camera(camera)
        self.camera_title.setText(camera.name)
        snapshot = self.service.get_controller(self.current_controller_id)
        if snapshot:
            for index, item in enumerate(snapshot.cameras):
                if item.camera_id == camera.camera_id and index < len(self.camera_buttons):
                    self.camera_buttons[index].setText(camera.name)
                    break
        self.result_label.setText(message)
        if snapshot:
            self.service.camera_configuration_changed.emit(
                snapshot.controller_id,
                camera.camera_id,
            )
            self.service.snapshot_updated.emit(snapshot.controller_id)

    def _test_connection(self) -> None:
        camera = self._apply_form_to_camera()
        if camera is None:
            return
        if not VlcRuntime.instance():
            self.result_label.setText(
                "VLC tidak tersedia · " + VlcRuntime.error_message()
            )
            return
        self.result_label.setText(
            "Membuka substream untuk pengujian RTSP..."
        )
        dialog = FullscreenCameraDialog(
            camera,
            self,
            main_stream=False,
        )
        dialog.open_preview()
        self.result_label.setText(
            "Pengujian substream selesai. Simpan jika tampilannya sudah benar."
        )

    def _preview_main_stream(self) -> None:
        camera = self._apply_form_to_camera()
        if camera is None:
            return
        if not VlcRuntime.instance():
            self.result_label.setText(
                "VLC tidak tersedia · " + VlcRuntime.error_message()
            )
            return
        dialog = FullscreenCameraDialog(
            camera,
            self,
            main_stream=True,
        )
        dialog.open_fullscreen()
        self.result_label.setText("Preview main stream selesai.")

    def _apply_form_to_camera(self) -> CameraConfiguration | None:
        if not self.current_camera:
            return None
        host = self.host_input.text().strip()
        main_path = self.main_path_input.text().strip()
        sub_path = self.sub_path_input.text().strip()
        if not host:
            self.result_label.setText("Camera IP / hostname belum diisi.")
            return None
        if not main_path or not sub_path:
            self.result_label.setText(
                "Main stream path dan Substream path harus diisi."
            )
            return None

        camera = self.current_camera
        camera.enabled = self.enabled_input.isChecked()
        camera.profile = self.profile_input.currentText()
        camera.name = self.name_input.text().strip() or camera.name
        camera.host = host
        camera.port = self.port_input.value()
        camera.username = self.username_input.text()
        camera.password = self.password_input.text()
        camera.main_path = main_path
        camera.sub_path = sub_path
        camera.rtsp_cache_ms = self.rtsp_cache_input.value()
        # Build both URLs now so malformed values are caught before opening VLC.
        build_rtsp_url(camera, main_stream=True)
        build_rtsp_url(camera, main_stream=False)
        return camera

    def _update_camera_status(self, online: bool) -> None:
        self.camera_status.setText("● CONNECTED" if online else "● OFFLINE")
        self.camera_status.setProperty(
            "status",
            "online" if online else "offline",
        )
        self.camera_status.style().unpolish(self.camera_status)
        self.camera_status.style().polish(self.camera_status)
