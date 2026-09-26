from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..controller_service import ControllerService
from ..display_layout import (
    FLOW_DIRECTIONS,
    INTERSECTION_TYPES,
    CameraTilePlacement,
    ControllerDisplayLayout,
    default_signal_placements,
    automatic_camera_positions,
)
from ..models import CameraConfiguration, CameraRole
from ..widgets.common import muted_label, status_label
from ..widgets.intersection_diagram import IntersectionDiagram


class CameraPreviewTile(QLabel):
    moved = Signal(str, int, int)

    def __init__(
        self,
        camera_id: str,
        text: str,
        draggable: bool,
        parent=None,
    ) -> None:
        super().__init__(text, parent)
        self.camera_id = camera_id
        self.draggable = draggable
        self._pressed = False
        if draggable:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.draggable and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.draggable and self._pressed:
            self._pressed = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            parent = self.parentWidget()
            if parent is not None:
                point = parent.mapFromGlobal(event.globalPosition().toPoint())
                row = max(0, min(3, int(point.y() * 4 / max(1, parent.height()))))
                column = max(0, min(3, int(point.x() * 4 / max(1, parent.width()))))
                self.moved.emit(self.camera_id, row, column)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CameraLayoutPreview(QFrame):
    camera_moved = Signal(str, int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("layoutPreview")
        self.setMinimumHeight(285)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setSpacing(6)

    def show_layout(
        self,
        cameras: list[CameraConfiguration],
        layout: ControllerDisplayLayout,
    ) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        visible = [
            camera
            for camera in cameras
            if camera.enabled
            and layout.cameras.tiles.get(
                camera.camera_id,
                CameraTilePlacement(),
            ).visible
        ]
        if not visible:
            label = muted_label("No camera selected for Live View")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(label, 0, 0, 3, 4)
            return

        if layout.cameras.mode == "AUTO":
            positions = automatic_camera_positions(
                visible,
                layout.cameras.primary_camera_id,
            )
        else:
            positions = {
                camera.camera_id: (
                    layout.cameras.tiles[camera.camera_id].row,
                    layout.cameras.tiles[camera.camera_id].column,
                    layout.cameras.tiles[camera.camera_id].row_span,
                    layout.cameras.tiles[camera.camera_id].column_span,
                )
                for camera in visible
            }

        for camera in visible:
            row, column, row_span, column_span = positions[camera.camera_id]
            tile = CameraPreviewTile(
                camera.camera_id,
                f"{camera.name}\n"
                + (
                    f"SG{camera.signal_group} CAMERA"
                    if camera.role == CameraRole.SIGNAL_GROUP
                    and camera.signal_group is not None
                    else "PTZ / OVERVIEW"
                ),
                layout.cameras.mode == "CUSTOM",
            )
            tile.setObjectName("cameraLayoutTile")
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setWordWrap(True)
            tile.moved.connect(self.camera_moved)
            self.grid.addWidget(
                tile,
                row,
                column,
                row_span,
                column_span,
            )
        for row in range(4):
            self.grid.setRowStretch(row, 1)
        for column in range(4):
            self.grid.setColumnStretch(column, 1)


class DisplayLayoutEditor(QWidget):
    """Local presentation editor shared by System Settings and Live View."""

    def __init__(
        self,
        service: ControllerService,
        section: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if section not in {"intersection", "camera"}:
            raise ValueError("section must be 'intersection' or 'camera'")
        self.service = service
        self.section = section
        self.repository = service.display_layout_repository
        self.controller_id = ""
        self._layout = ControllerDisplayLayout()
        self._loading = False
        self._camera_rows: dict[str, dict[str, QWidget]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            "Layout disimpan lokal untuk setiap controller. Pengaturan ini hanya "
            "mengubah tampilan Command Center dan tidak mengubah Plan, Stage, "
            "Schedule, output SG, atau safety controller."
        )
        intro.setObjectName("readOnlyNote")
        intro.setWordWrap(True)
        root.addWidget(intro)

        if self.section == "intersection":
            root.addWidget(self._build_intersection_panel(), 1)
        else:
            root.addWidget(self._build_camera_panel(), 1)

        self.message_label = status_label(
            "INTERSECTION LAYOUT READY"
            if self.section == "intersection"
            else "CAMERA LAYOUT READY",
            "online",
        )
        root.addWidget(self.message_label)

    def _build_intersection_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("contentPanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(12)

        settings = QFrame()
        settings.setObjectName("summaryPanel")
        settings.setMinimumWidth(330)
        settings.setMaximumWidth(420)
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(12, 10, 12, 12)
        settings_layout.setSpacing(9)
        diagram_frame = QFrame()
        diagram_frame.setObjectName("layoutSettingsGroup")
        diagram_layout = QVBoxLayout(diagram_frame)
        diagram_layout.setContentsMargins(10, 8, 10, 10)
        diagram_layout.setSpacing(7)
        diagram_title = QLabel("INTERSECTION DIAGRAM")
        diagram_title.setObjectName("layoutGroupTitle")
        diagram_layout.addWidget(diagram_title)

        diagram_controls = QGridLayout()
        diagram_controls.setHorizontalSpacing(8)
        diagram_controls.setVerticalSpacing(7)
        diagram_controls.addWidget(QLabel("Diagram Type"), 0, 0)
        self.intersection_type_input = QComboBox()
        for key, name in INTERSECTION_TYPES.items():
            self.intersection_type_input.addItem(name, key)
        self.intersection_type_input.currentIndexChanged.connect(
            self._intersection_template_changed
        )
        diagram_controls.addWidget(self.intersection_type_input, 0, 1)
        diagram_controls.addWidget(QLabel("Rotation"), 1, 0)
        self.rotation_input = QComboBox()
        for value in (0, 90, 180, 270):
            self.rotation_input.addItem(f"{value}°", value)
        self.rotation_input.currentIndexChanged.connect(
            self._intersection_template_changed
        )
        diagram_controls.addWidget(self.rotation_input, 1, 1)
        diagram_controls.setColumnStretch(1, 1)
        diagram_layout.addLayout(diagram_controls)
        settings_layout.addWidget(diagram_frame)

        signal_frame = QFrame()
        signal_frame.setObjectName("layoutSettingsGroup")
        signal_layout = QVBoxLayout(signal_frame)
        signal_layout.setContentsMargins(10, 8, 10, 10)
        signal_layout.setSpacing(7)
        signal_title = QLabel("SIGNAL GROUP CONFIGURATION")
        signal_title.setObjectName("layoutGroupTitle")
        signal_layout.addWidget(signal_title)

        signal_controls = QGridLayout()
        signal_controls.setHorizontalSpacing(8)
        signal_controls.setVerticalSpacing(7)
        signal_controls.addWidget(QLabel("Selected SG"), 0, 0)
        self.sg_selector = QComboBox()
        self.sg_selector.currentIndexChanged.connect(
            self._selected_sg_changed
        )
        signal_controls.addWidget(self.sg_selector, 0, 1)
        signal_controls.addWidget(QLabel("SG Rotation"), 1, 0)
        self.sg_rotation_input = QComboBox()
        self.sg_rotation_input.addItem("Auto", -1)
        for value in (0, 90, 180, 270):
            self.sg_rotation_input.addItem(f"{value}°", value)
        self.sg_rotation_input.currentIndexChanged.connect(
            self._sg_visual_changed
        )
        signal_controls.addWidget(self.sg_rotation_input, 1, 1)
        movement_label = QLabel("Vehicle Movement")
        movement_label.setToolTip(
            "Straight, Left, dan Right dapat dipilih bersamaan untuk SG yang sama."
        )
        signal_controls.addWidget(movement_label, 2, 0)
        movement_widget = QWidget()
        movement_row = QHBoxLayout(movement_widget)
        movement_row.setContentsMargins(0, 0, 0, 0)
        movement_row.setSpacing(12)
        self.movement_straight_input = QCheckBox("Straight")
        self.movement_left_input = QCheckBox("Left")
        self.movement_right_input = QCheckBox("Right")
        for checkbox in (
            self.movement_straight_input,
            self.movement_left_input,
            self.movement_right_input,
        ):
            checkbox.toggled.connect(self._sg_visual_changed)
            movement_row.addWidget(checkbox)
        movement_row.addStretch()
        signal_controls.addWidget(movement_widget, 2, 1)
        flow_label = QLabel("Flow Direction")
        flow_tooltip = (
            "Pilih One Way menuju intersection, One Way meninggalkan "
            "intersection, Two Way, atau Hidden."
        )
        flow_label.setToolTip(flow_tooltip)
        signal_controls.addWidget(flow_label, 3, 0)
        self.flow_direction_input = QComboBox()
        for key, name in FLOW_DIRECTIONS.items():
            self.flow_direction_input.addItem(name, key)
        self.flow_direction_input.setToolTip(flow_tooltip)
        self.flow_direction_input.currentIndexChanged.connect(
            self._sg_visual_changed
        )
        signal_controls.addWidget(self.flow_direction_input, 3, 1)
        signal_controls.setColumnStretch(1, 1)
        signal_layout.addLayout(signal_controls)
        settings_layout.addWidget(signal_frame)
        settings_layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        reset = QPushButton("RESET SG POSITIONS")
        reset.setFixedHeight(30)
        reset.setStyleSheet("font-size: 9pt; padding: 3px 7px;")
        reset.clicked.connect(self._reset_intersection)
        save = QPushButton("SAVE INTERSECTION LAYOUT")
        save.setObjectName("primaryButton")
        save.setFixedHeight(30)
        save.setStyleSheet("font-size: 9pt; padding: 3px 7px;")
        save.clicked.connect(self._save_intersection)
        actions.addWidget(reset, 4)
        actions.addWidget(save, 5)
        settings_layout.addLayout(actions)
        layout.addWidget(settings, 0)

        preview_panel = QFrame()
        preview_panel.setObjectName("summaryPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(12, 10, 12, 10)
        preview_layout.setSpacing(6)
        preview_title = QLabel("Intersection Diagram")
        preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(preview_title)

        self.intersection_preview = IntersectionDiagram()
        self.intersection_preview.setMinimumSize(380, 380)
        self.intersection_preview.set_editable(True)
        self.intersection_preview.placement_changed.connect(
            self._intersection_placement_changed
        )
        self.intersection_preview.signal_selected.connect(
            self._preview_signal_selected
        )
        preview_layout.addWidget(self.intersection_preview, 1)
        hint = muted_label(
            "Drag SG1–SG12 directly in the preview. Rotation also supports all "
            "four T-junction orientations."
        )
        hint.setWordWrap(True)
        preview_layout.addWidget(hint)
        layout.addWidget(preview_panel, 1)
        return panel

    def _build_camera_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("contentPanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(12)

        settings = QFrame()
        settings.setObjectName("summaryPanel")
        settings.setMinimumWidth(470)
        settings.setMaximumWidth(620)
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(12, 10, 12, 12)
        settings_layout.setSpacing(8)
        title = QLabel("Camera Settings")
        title.setObjectName("sectionTitle")
        settings_layout.addWidget(title)

        controls = QGridLayout()
        controls.addWidget(QLabel("Layout Mode"), 0, 0)
        self.camera_mode_input = QComboBox()
        self.camera_mode_input.addItem("Auto Layout", "AUTO")
        self.camera_mode_input.addItem("Custom Grid", "CUSTOM")
        self.camera_mode_input.currentIndexChanged.connect(
            self._camera_mode_changed
        )
        controls.addWidget(self.camera_mode_input, 0, 1)
        controls.addWidget(QLabel("Primary Camera"), 1, 0)
        self.primary_camera_input = QComboBox()
        self.primary_camera_input.currentIndexChanged.connect(
            self._camera_form_changed
        )
        controls.addWidget(self.primary_camera_input, 1, 1)
        controls.setColumnStretch(1, 1)
        settings_layout.addLayout(controls)

        header = QGridLayout()
        for column, text in enumerate(
            ("SHOW", "CAMERA", "ROW", "COL", "W", "H")
        ):
            label = muted_label(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if text == "W":
                label.setToolTip("Width")
            elif text == "H":
                label.setToolTip("Height")
            header.addWidget(label, 0, column)
            if column == 0 or column >= 2:
                header.setColumnMinimumWidth(column, 42)
        header.setColumnStretch(1, 1)
        settings_layout.addLayout(header)

        camera_list_scroll = QScrollArea()
        camera_list_scroll.setWidgetResizable(True)
        camera_list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        camera_rows_body = QWidget()
        self.camera_rows_layout = QVBoxLayout(camera_rows_body)
        self.camera_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.camera_rows_layout.setSpacing(1)
        self.camera_rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        camera_list_scroll.setWidget(camera_rows_body)
        settings_layout.addWidget(camera_list_scroll, 1)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        reset = QPushButton("AUTO ARRANGE CUSTOM GRID")
        reset.setFixedHeight(30)
        reset.setStyleSheet("font-size: 9pt; padding: 3px 7px;")
        reset.clicked.connect(self._reset_camera_grid)
        save = QPushButton("SAVE CAMERA LAYOUT")
        save.setObjectName("primaryButton")
        save.setFixedHeight(30)
        save.setStyleSheet("font-size: 9pt; padding: 3px 7px;")
        save.clicked.connect(self._save_camera)
        actions.addWidget(reset, 1)
        actions.addWidget(save, 1)
        settings_layout.addLayout(actions)
        layout.addWidget(settings, 0)

        preview_panel = QFrame()
        preview_panel.setObjectName("summaryPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(12, 10, 12, 10)
        preview_layout.setSpacing(6)
        preview_title = QLabel("Camera Layout Preview")
        preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(preview_title)
        self.camera_preview = CameraLayoutPreview()
        self.camera_preview.setMinimumHeight(400)
        self.camera_preview.camera_moved.connect(
            self._camera_tile_moved
        )
        preview_layout.addWidget(self.camera_preview, 1)
        preview_hint = muted_label(
            "Custom Grid: drag camera tiles directly in this preview."
        )
        preview_hint.setWordWrap(True)
        preview_layout.addWidget(preview_hint)
        layout.addWidget(preview_panel, 1)
        return panel

    def set_controller(self, controller_id: str) -> None:
        snapshot = self.service.get_controller(controller_id)
        if snapshot is None:
            return
        self.controller_id = controller_id
        self._layout = self.repository.get(
            controller_id,
            snapshot.active_signal_groups,
            snapshot.cameras,
        )
        self._loading = True
        try:
            if self.section == "intersection":
                type_index = self.intersection_type_input.findData(
                    self._layout.intersection.diagram_type
                )
                self.intersection_type_input.setCurrentIndex(max(0, type_index))
                rotation_index = self.rotation_input.findData(
                    self._layout.intersection.rotation
                )
                self.rotation_input.setCurrentIndex(max(0, rotation_index))
                self.intersection_preview.set_layout_config(
                    self._layout.intersection
                )
                self.intersection_preview.set_signal_groups(snapshot.signal_groups)
                self.sg_selector.clear()
                for signal_group in snapshot.signal_groups:
                    self.sg_selector.addItem(
                        f"SG{signal_group.number} · {signal_group.name}",
                        signal_group.number,
                    )
                if self.sg_selector.count():
                    self.sg_selector.setCurrentIndex(0)
            else:
                mode_index = self.camera_mode_input.findData(
                    self._layout.cameras.mode
                )
                self.camera_mode_input.setCurrentIndex(max(0, mode_index))
                self.primary_camera_input.clear()
                self.primary_camera_input.addItem("Automatic / None", "")
                for camera in snapshot.cameras:
                    self.primary_camera_input.addItem(
                        camera.name,
                        camera.camera_id,
                    )
                primary_index = self.primary_camera_input.findData(
                    self._layout.cameras.primary_camera_id
                )
                self.primary_camera_input.setCurrentIndex(max(0, primary_index))
                self._rebuild_camera_rows(snapshot.cameras)
        finally:
            self._loading = False
        if self.section == "intersection":
            self._selected_sg_changed()
        else:
            self._camera_mode_changed()
            self._refresh_camera_preview()
        self._set_message(
            f"{self.section.upper()} LAYOUT LOADED · {snapshot.name}",
            "online",
        )

    def sync_controller_data(self, controller_id: str) -> None:
        """Refresh SG/camera topology while preserving unsaved layout edits."""
        snapshot = self.service.get_controller(controller_id)
        if snapshot is None:
            return
        if controller_id != self.controller_id:
            self.set_controller(controller_id)
            return

        stored_layout = self.repository.get(
            controller_id,
            snapshot.active_signal_groups,
            snapshot.cameras,
        )
        self._loading = True
        try:
            if self.section == "intersection":
                selected_number = self.sg_selector.currentData()
                defaults = default_signal_placements(
                    self._layout.intersection.diagram_type,
                    self._layout.intersection.rotation,
                    snapshot.active_signal_groups,
                )
                for number, placement in defaults.items():
                    self._layout.intersection.placements.setdefault(
                        number,
                        deepcopy(
                            stored_layout.intersection.placements.get(
                                number,
                                placement,
                            )
                        ),
                    )
                self._layout.intersection.placements = {
                    number: placement
                    for number, placement
                    in self._layout.intersection.placements.items()
                    if 1 <= number <= snapshot.active_signal_groups
                }
                self.intersection_preview.set_layout_config(
                    self._layout.intersection
                )
                self.intersection_preview.set_signal_groups(
                    snapshot.signal_groups
                )
                self.sg_selector.clear()
                for signal_group in snapshot.signal_groups:
                    self.sg_selector.addItem(
                        f"SG{signal_group.number} · {signal_group.name}",
                        signal_group.number,
                    )
                selected_index = self.sg_selector.findData(selected_number)
                self.sg_selector.setCurrentIndex(
                    selected_index if selected_index >= 0 else 0
                )
            else:
                for order, camera in enumerate(snapshot.cameras):
                    self._layout.cameras.tiles.setdefault(
                        camera.camera_id,
                        CameraTilePlacement(order=order),
                    )
                self.primary_camera_input.clear()
                self.primary_camera_input.addItem("Automatic / None", "")
                for camera in snapshot.cameras:
                    self.primary_camera_input.addItem(
                        camera.name,
                        camera.camera_id,
                    )
                primary_index = self.primary_camera_input.findData(
                    self._layout.cameras.primary_camera_id
                )
                self.primary_camera_input.setCurrentIndex(
                    max(0, primary_index)
                )
                self._rebuild_camera_rows(snapshot.cameras)
        finally:
            self._loading = False

        if self.section == "intersection":
            self._selected_sg_changed()
        else:
            self._camera_mode_changed()
            self._refresh_camera_preview()

    def _rebuild_camera_rows(
        self,
        cameras: list[CameraConfiguration],
    ) -> None:
        while self.camera_rows_layout.count():
            item = self.camera_rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._camera_rows.clear()
        for order, camera in enumerate(cameras):
            placement = self._layout.cameras.tiles.setdefault(
                camera.camera_id,
                CameraTilePlacement(order=order),
            )
            row_widget = QWidget()
            row_widget.setFixedHeight(26)
            row = QGridLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setHorizontalSpacing(5)
            row.setVerticalSpacing(0)
            visible = QCheckBox()
            visible.setChecked(placement.visible)
            name = QLabel(camera.name)
            name.setToolTip(camera.camera_id)
            row_input = self._spin(1, 4, placement.row + 1)
            column_input = self._spin(1, 4, placement.column + 1)
            width_input = self._spin(1, 4, placement.column_span)
            height_input = self._spin(1, 4, placement.row_span)
            widgets = (
                visible, name, row_input, column_input, width_input, height_input
            )
            for column, widget in enumerate(widgets):
                alignment = (
                    Qt.AlignmentFlag.AlignCenter
                    if column == 0 or column >= 2
                    else Qt.AlignmentFlag.AlignVCenter
                )
                row.addWidget(widget, 0, column, alignment)
                if column == 0 or column >= 2:
                    row.setColumnMinimumWidth(column, 42)
            row.setColumnStretch(1, 1)
            self.camera_rows_layout.addWidget(row_widget)
            self._camera_rows[camera.camera_id] = {
                "visible": visible,
                "row": row_input,
                "column": column_input,
                "width": width_input,
                "height": height_input,
            }
            visible.toggled.connect(self._camera_form_changed)
            for spin in (row_input, column_input, width_input, height_input):
                spin.valueChanged.connect(self._camera_form_changed)

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setObjectName("cameraGridSpin")
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spin.setFixedSize(42, 24)
        return spin

    def _intersection_template_changed(self) -> None:
        if self._loading or not self.controller_id:
            return
        snapshot = self.service.get_controller(self.controller_id)
        if snapshot is None:
            return
        self._layout.intersection.diagram_type = str(
            self.intersection_type_input.currentData()
        )
        self._layout.intersection.rotation = int(
            self.rotation_input.currentData()
        )
        previous = self._layout.intersection.placements
        updated = default_signal_placements(
            self._layout.intersection.diagram_type,
            self._layout.intersection.rotation,
            snapshot.active_signal_groups,
        )
        for number, placement in updated.items():
            old = previous.get(number)
            if old is not None:
                placement.rotation = old.rotation
                placement.movements = list(old.movements)
                placement.flow_direction = old.flow_direction
        self._layout.intersection.placements = updated
        self.intersection_preview.set_layout_config(
            self._layout.intersection
        )

    def _selected_sg_changed(self) -> None:
        if self._loading:
            return
        number = self.sg_selector.currentData()
        if number is None:
            return
        number = int(number)
        placement = self._layout.intersection.placements.get(number)
        if placement is None:
            return
        self._loading = True
        try:
            rotation_index = self.sg_rotation_input.findData(
                placement.rotation
            )
            self.sg_rotation_input.setCurrentIndex(max(0, rotation_index))
            self.movement_straight_input.setChecked(
                "STRAIGHT" in placement.movements
            )
            self.movement_left_input.setChecked("LEFT" in placement.movements)
            self.movement_right_input.setChecked("RIGHT" in placement.movements)
            flow_index = self.flow_direction_input.findData(
                placement.flow_direction
            )
            self.flow_direction_input.setCurrentIndex(max(0, flow_index))
        finally:
            self._loading = False
        self.intersection_preview.set_selected_signal(number)

    def _preview_signal_selected(self, number: int) -> None:
        index = self.sg_selector.findData(number)
        if index >= 0:
            self.sg_selector.setCurrentIndex(index)

    def _sg_visual_changed(self) -> None:
        if self._loading:
            return
        number = self.sg_selector.currentData()
        if number is None:
            return
        placement = self._layout.intersection.placements.get(int(number))
        if placement is None:
            return
        placement.rotation = int(self.sg_rotation_input.currentData())
        movements = [
            key
            for key, widget in (
                ("STRAIGHT", self.movement_straight_input),
                ("LEFT", self.movement_left_input),
                ("RIGHT", self.movement_right_input),
            )
            if widget.isChecked()
        ]
        if not movements:
            self._loading = True
            self.movement_straight_input.setChecked(True)
            self._loading = False
            movements = ["STRAIGHT"]
        placement.movements = movements
        placement.flow_direction = str(
            self.flow_direction_input.currentData()
        )
        self.intersection_preview.set_layout_config(
            self._layout.intersection
        )
        self.intersection_preview.set_selected_signal(int(number))
        self._set_message(
            f"SG{number} VISUAL SETTINGS CHANGED · NOT SAVED",
            "warning",
        )

    def _intersection_placement_changed(
        self,
        number: int,
        x: float,
        y: float,
    ) -> None:
        if self._loading:
            return
        self._layout.intersection = self.intersection_preview.layout_config()
        self._set_message(
            f"SG{number} POSITION · X {x:.2f} · Y {y:.2f} · NOT SAVED",
            "warning",
        )

    def _reset_intersection(self) -> None:
        self.intersection_preview.reset_placements()
        self._layout.intersection = self.intersection_preview.layout_config()
        self._set_message("SG POSITIONS RESET · NOT SAVED", "warning")

    def _save_intersection(self) -> None:
        if not self.controller_id:
            return
        self._layout.intersection = self.intersection_preview.layout_config()
        snapshot = self.service.get_controller(self.controller_id)
        if snapshot is None:
            return
        latest = self.repository.get(
            self.controller_id,
            snapshot.active_signal_groups,
            snapshot.cameras,
        )
        latest.intersection = self._layout.intersection
        self._layout = latest
        self.repository.save(self.controller_id, latest)
        self._set_message("INTERSECTION LAYOUT SAVED", "online")

    def _camera_mode_changed(self) -> None:
        custom = self.camera_mode_input.currentData() == "CUSTOM"
        for widgets in self._camera_rows.values():
            for key in ("row", "column", "width", "height"):
                widgets[key].setEnabled(custom)
        self._camera_form_changed()

    def _camera_form_changed(self, *_args) -> None:
        if self._loading:
            return
        self._read_camera_form()
        self._refresh_camera_preview()

    def _read_camera_form(self) -> None:
        self._layout.cameras.mode = str(
            self.camera_mode_input.currentData() or "AUTO"
        )
        self._layout.cameras.primary_camera_id = str(
            self.primary_camera_input.currentData() or ""
        )
        for order, (camera_id, widgets) in enumerate(self._camera_rows.items()):
            self._layout.cameras.tiles[camera_id] = CameraTilePlacement(
                visible=widgets["visible"].isChecked(),
                row=widgets["row"].value() - 1,
                column=widgets["column"].value() - 1,
                row_span=widgets["height"].value(),
                column_span=widgets["width"].value(),
                order=order,
            )

    def _refresh_camera_preview(self) -> None:
        snapshot = self.service.get_controller(self.controller_id)
        if snapshot is None:
            return
        self.camera_preview.show_layout(snapshot.cameras, self._layout)

    def _camera_tile_moved(
        self,
        camera_id: str,
        row: int,
        column: int,
    ) -> None:
        if self.camera_mode_input.currentData() != "CUSTOM":
            return
        widgets = self._camera_rows.get(camera_id)
        if not widgets:
            return
        width = widgets["width"].value()
        height = widgets["height"].value()
        widgets["row"].setValue(min(row, 4 - height) + 1)
        widgets["column"].setValue(min(column, 4 - width) + 1)
        self._read_camera_form()
        self._refresh_camera_preview()
        self._set_message(
            f"{camera_id} MOVED · ROW {widgets['row'].value()} · "
            f"COLUMN {widgets['column'].value()} · NOT SAVED",
            "warning",
        )

    def _reset_camera_grid(self) -> None:
        snapshot = self.service.get_controller(self.controller_id)
        if snapshot is None:
            return
        visible = [
            camera
            for camera in snapshot.cameras
            if self._layout.cameras.tiles[camera.camera_id].visible
        ]
        self._loading = True
        try:
            for index, camera in enumerate(visible):
                widgets = self._camera_rows[camera.camera_id]
                widgets["row"].setValue(index // 4 + 1)
                widgets["column"].setValue(index % 4 + 1)
                widgets["height"].setValue(1)
                widgets["width"].setValue(1)
        finally:
            self._loading = False
        self._read_camera_form()
        self._refresh_camera_preview()
        self._set_message("CUSTOM GRID AUTO-ARRANGED · NOT SAVED", "warning")

    def _save_camera(self) -> None:
        if not self.controller_id:
            return
        self._read_camera_form()
        if self._layout.cameras.mode == "CUSTOM":
            error = self._validate_camera_grid()
            if error:
                self._set_message(error, "offline")
                return
        snapshot = self.service.get_controller(self.controller_id)
        if snapshot is None:
            return
        latest = self.repository.get(
            self.controller_id,
            snapshot.active_signal_groups,
            snapshot.cameras,
        )
        latest.cameras = self._layout.cameras
        self._layout = latest
        self.repository.save(self.controller_id, latest)
        self._set_message("CAMERA LAYOUT SAVED", "online")

    def _validate_camera_grid(self) -> str:
        snapshot = self.service.get_controller(self.controller_id)
        enabled_ids = {
            camera.camera_id
            for camera in snapshot.cameras
            if camera.enabled
        } if snapshot else set()
        occupied: dict[tuple[int, int], str] = {}
        for camera_id, tile in self._layout.cameras.tiles.items():
            if not tile.visible or camera_id not in enabled_ids:
                continue
            if tile.row + tile.row_span > 4 or tile.column + tile.column_span > 4:
                return f"INVALID GRID · {camera_id} EXCEEDS 4 × 4 BOUNDARY"
            for row in range(tile.row, tile.row + tile.row_span):
                for column in range(tile.column, tile.column + tile.column_span):
                    previous = occupied.get((row, column))
                    if previous:
                        return (
                            f"GRID CONFLICT · {previous} AND {camera_id} OVERLAP"
                        )
                    occupied[(row, column)] = camera_id
        return ""

    def _set_message(self, text: str, state: str) -> None:
        self.message_label.setText(text)
        self.message_label.setProperty("status", state)
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)
