from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
    default_road_arms,
    default_signal_placements,
    destination_ids_for_movements,
    effective_arm_angle,
    movement_name_between,
    automatic_camera_positions,
)
from ..models import CameraConfiguration, CameraRole, SignalGroupState
from ..widgets.common import muted_label, status_label
from ..widgets.intersection_diagram import IntersectionDiagram


def _direction_name(angle: float) -> str:
    names = (
        "North",
        "North-East",
        "East",
        "South-East",
        "South",
        "South-West",
        "West",
        "North-West",
    )
    return names[round((float(angle) % 360.0) / 45.0) % 8]


def _arm_number(arm, index: int) -> int:
    digits = "".join(character for character in arm.arm_id if character.isdigit())
    return int(digits) if digits else index + 1


def _arm_display(arm, index: int, rotation: int) -> str:
    number = _arm_number(arm, index)
    angle = effective_arm_angle(arm, rotation)
    angle_text = (
        str(int(round(angle)))
        if abs(angle - round(angle)) < 0.05
        else f"{angle:.1f}"
    )
    return f"Arm {number} — {_direction_name(angle)} ({angle_text}°)"


def _destination_movement(source, destination) -> str:
    movement = movement_name_between(source, destination)
    if "Left" in movement:
        return "Left"
    if "Right" in movement:
        return "Right"
    return "Straight"


def _destination_sort_key(
    source,
    destination,
    index: int,
) -> tuple[int, float, int]:
    movement = _destination_movement(source, destination)
    rank = {"Straight": 0, "Left": 1, "Right": 2}[movement]
    inbound_heading = (float(source.angle) + 180.0) % 360.0
    delta = (
        (float(destination.angle) - inbound_heading + 180.0) % 360.0
    ) - 180.0
    return rank, abs(delta), _arm_number(destination, index)


class IntersectionLayoutPreview(IntersectionDiagram):
    """Square editor preview that never stretches into a wide banner."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.set_compass_labels_visible(False)
        self.setMinimumSize(260, 260)
        self.setMaximumSize(520, 520)
        policy = QSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return max(260, min(520, int(width)))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(460, 460)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(260, 260)


class VerticalScrollArea(QScrollArea):
    """Vertical-only scroll area whose content always fits the viewport width."""

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        content = self.widget()
        if content is not None:
            content.setFixedWidth(max(0, self.viewport().width()))
        self.horizontalScrollBar().setValue(0)


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
    """Controller Intersection Layout and local Camera Layout editor."""

    intersection_saved = Signal(str, str)
    intersection_failed = Signal(str, str)

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
        self._destination_checks: dict[str, QCheckBox] = {}
        self._layout_schema = 0
        self._layout_revision = 0
        self._layout_source = "CACHE / OFFLINE"
        self._layout_busy = False
        self._intersection_dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        if self.section == "intersection":
            root.addWidget(self._build_intersection_panel(), 1)
            self.layout_service = service.intersection_layout_service
            self.layout_service.layout_loaded.connect(self._layout_loaded)
            self.layout_service.save_completed.connect(
                self._layout_save_completed
            )
            self.layout_service.request_failed.connect(
                self._layout_request_failed
            )
            self.layout_service.busy_changed.connect(self._layout_busy_changed)
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

        settings_scroll = VerticalScrollArea()
        settings_scroll.setObjectName("intersectionSettingsScroll")
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        settings_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        settings_scroll.horizontalScrollBar().valueChanged.connect(
            lambda _value: settings_scroll.horizontalScrollBar().setValue(0)
        )
        settings_scroll.setMinimumWidth(390)

        settings = QFrame()
        settings.setObjectName("summaryPanel")
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

        diagram_subtitle = muted_label("DIAGRAM / LAYOUT")
        diagram_subtitle.setObjectName("layoutSubgroupTitle")
        diagram_layout.addWidget(diagram_subtitle)

        diagram_controls = QGridLayout()
        diagram_controls.setHorizontalSpacing(8)
        diagram_controls.setVerticalSpacing(7)
        diagram_controls.addWidget(QLabel("Diagram Type"), 0, 0)
        self.intersection_type_input = QComboBox()
        self.intersection_type_input.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.intersection_type_input.setMinimumContentsLength(9)
        for key, name in INTERSECTION_TYPES.items():
            self.intersection_type_input.addItem(name, key)
        self.intersection_type_input.currentIndexChanged.connect(
            self._intersection_template_changed
        )
        diagram_controls.addWidget(self.intersection_type_input, 0, 1)
        diagram_controls.addWidget(QLabel("Diagram Rotation"), 1, 0)
        self.rotation_input = QComboBox()
        self.rotation_input.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.rotation_input.setMinimumContentsLength(9)
        for value, text in (
            (0, "0° — Original"),
            (90, "90° — Rotate Clockwise"),
            (180, "180° — Rotate Half Turn"),
            (270, "270° — Rotate Counterclockwise"),
        ):
            self.rotation_input.addItem(text, value)
        self.rotation_input.currentIndexChanged.connect(
            self._intersection_template_changed
        )
        diagram_controls.addWidget(self.rotation_input, 1, 1)
        diagram_controls.setColumnMinimumWidth(0, 165)
        diagram_controls.setColumnStretch(1, 1)
        diagram_layout.addLayout(diagram_controls)

        arm_subtitle = muted_label("ROAD ARM")
        arm_subtitle.setObjectName("layoutSubgroupTitle")
        diagram_layout.addWidget(arm_subtitle)
        arm_controls = QGridLayout()
        arm_controls.setHorizontalSpacing(8)
        arm_controls.setVerticalSpacing(7)
        arm_controls.addWidget(QLabel("Selected Road Arm"), 0, 0)
        self.road_arm_selector = QComboBox()
        self.road_arm_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.road_arm_selector.setMinimumContentsLength(9)
        self.road_arm_selector.currentIndexChanged.connect(
            self._selected_arm_changed
        )
        arm_controls.addWidget(self.road_arm_selector, 0, 1)
        arm_controls.addWidget(QLabel("Arm Angle"), 1, 0)
        self.arm_angle_input = QDoubleSpinBox()
        self.arm_angle_input.setRange(0.0, 359.9)
        self.arm_angle_input.setDecimals(1)
        self.arm_angle_input.setSingleStep(0.1)
        self.arm_angle_input.setSuffix("°")
        self.arm_angle_input.valueChanged.connect(self._road_arm_changed)
        arm_controls.addWidget(self.arm_angle_input, 1, 1)
        arm_controls.addWidget(QLabel("Flow Direction"), 2, 0)
        self.arm_flow_input = QComboBox()
        self.arm_flow_input.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.arm_flow_input.setMinimumContentsLength(9)
        for key, name in FLOW_DIRECTIONS.items():
            self.arm_flow_input.addItem(name, key)
        self.arm_flow_input.setToolTip(
            "Road arm dapat berupa One Way - Inbound, One Way - Outbound, "
            "Two Way, atau Hidden."
        )
        self.arm_flow_input.currentIndexChanged.connect(
            self._road_arm_changed
        )
        arm_controls.addWidget(self.arm_flow_input, 2, 1)
        arm_controls.setColumnMinimumWidth(0, 165)
        arm_controls.setColumnStretch(1, 1)
        diagram_layout.addLayout(arm_controls)
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
        self.sg_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.sg_selector.setMinimumContentsLength(9)
        self.sg_selector.currentIndexChanged.connect(
            self._selected_sg_changed
        )
        signal_controls.addWidget(self.sg_selector, 0, 1)
        signal_controls.addWidget(QLabel("Assigned Road Arm"), 1, 0)
        self.assigned_arm_input = QComboBox()
        self.assigned_arm_input.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.assigned_arm_input.setMinimumContentsLength(9)
        self.assigned_arm_input.currentIndexChanged.connect(
            self._sg_visual_changed
        )
        signal_controls.addWidget(self.assigned_arm_input, 1, 1)
        signal_controls.addWidget(QLabel("Lane Position"), 2, 0)
        self.lane_position_input = QSpinBox()
        self.lane_position_input.setRange(1, 4)
        self.lane_position_input.valueChanged.connect(
            self._sg_visual_changed
        )
        signal_controls.addWidget(self.lane_position_input, 2, 1)
        signal_controls.addWidget(QLabel("SG Rotation"), 3, 0)
        self.sg_rotation_input = QComboBox()
        self.sg_rotation_input.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.sg_rotation_input.setMinimumContentsLength(7)
        self.sg_rotation_input.addItem("Auto", -1)
        for value in (0, 90, 180, 270):
            self.sg_rotation_input.addItem(f"{value}°", value)
        self.sg_rotation_input.currentIndexChanged.connect(
            self._sg_visual_changed
        )
        signal_controls.addWidget(self.sg_rotation_input, 3, 1)
        movement_label = QLabel("Destination Road Arm:")
        movement_label.setToolTip(
            "Pilih satu atau beberapa road arm tujuan yang dikendalikan SG ini."
        )
        movement_label.setContentsMargins(0, 3, 0, 0)
        signal_controls.addWidget(
            movement_label,
            4,
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        movement_widget = QWidget()
        self.destination_layout = QGridLayout(movement_widget)
        self.destination_layout.setContentsMargins(0, 0, 0, 0)
        self.destination_layout.setVerticalSpacing(3)
        self.destination_layout.setColumnStretch(0, 1)
        signal_controls.addWidget(movement_widget, 4, 1)
        signal_controls.setColumnMinimumWidth(0, 165)
        signal_controls.setColumnStretch(1, 1)
        signal_layout.addLayout(signal_controls)
        settings_layout.addWidget(signal_frame)

        actions = QVBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        secondary_actions = QHBoxLayout()
        secondary_actions.setContentsMargins(0, 0, 0, 0)
        secondary_actions.setSpacing(6)
        self.reload_intersection_button = QPushButton(
            "RELOAD FROM CONTROLLER"
        )
        self.reload_intersection_button.setFixedHeight(30)
        self.reload_intersection_button.setStyleSheet(
            "font-size: 8pt; padding: 3px 5px;"
        )
        self.reload_intersection_button.clicked.connect(
            self._reload_intersection
        )
        self.reset_intersection_button = QPushButton("RESET SG POSITIONS")
        self.reset_intersection_button.setFixedHeight(30)
        self.reset_intersection_button.setStyleSheet(
            "font-size: 8pt; padding: 3px 5px;"
        )
        self.reset_intersection_button.clicked.connect(self._reset_intersection)
        self.save_intersection_button = QPushButton(
            "SAVE INTERSECTION LAYOUT"
        )
        self.save_intersection_button.setObjectName("primaryButton")
        self.save_intersection_button.setFixedHeight(30)
        self.save_intersection_button.setStyleSheet(
            "font-size: 9pt; padding: 3px 7px;"
        )
        self.save_intersection_button.clicked.connect(self._save_intersection)
        secondary_actions.addWidget(self.reload_intersection_button, 1)
        secondary_actions.addWidget(self.reset_intersection_button, 1)
        actions.addLayout(secondary_actions)
        actions.addWidget(self.save_intersection_button)
        settings_layout.addLayout(actions)
        settings_layout.addStretch(1)
        settings_scroll.setWidget(settings)
        layout.addWidget(settings_scroll, 33)

        preview_scroll = VerticalScrollArea()
        preview_scroll.setObjectName("intersectionPreviewScroll")
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        preview_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        preview_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        preview_scroll.horizontalScrollBar().valueChanged.connect(
            lambda _value: preview_scroll.horizontalScrollBar().setValue(0)
        )
        preview_scroll.setMinimumWidth(400)

        preview_panel = QFrame()
        preview_panel.setObjectName("summaryPanel")
        preview_panel.setMinimumWidth(0)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(12, 10, 12, 10)
        preview_layout.setSpacing(6)
        preview_header = QHBoxLayout()
        preview_title = QLabel("Live Preview")
        preview_title.setObjectName("sectionTitle")
        preview_header.addWidget(preview_title)
        preview_header.addStretch()
        self.layout_meta_label = muted_label("CACHE / OFFLINE · REV —")
        preview_header.addWidget(self.layout_meta_label)
        preview_layout.addLayout(preview_header)

        self.intersection_preview = IntersectionLayoutPreview()
        self.intersection_preview.set_editable(True)
        self.intersection_preview.placement_changed.connect(
            self._intersection_placement_changed
        )
        self.intersection_preview.label_offset_changed.connect(
            self._intersection_label_changed
        )
        self.intersection_preview.signal_selected.connect(
            self._preview_signal_selected
        )

        compass_frame = QFrame()
        compass_frame.setObjectName("externalCompassFrame")
        compass_layout = QGridLayout(compass_frame)
        compass_layout.setContentsMargins(2, 2, 2, 2)
        compass_layout.setHorizontalSpacing(6)
        compass_layout.setVerticalSpacing(3)

        north_label = QLabel("NORTH")
        south_label = QLabel("SOUTH")
        west_label = QLabel("WEST")
        east_label = QLabel("EAST")
        for label in (
            north_label,
            south_label,
            west_label,
            east_label,
        ):
            label.setObjectName("externalCompassLabel")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        compass_layout.addWidget(north_label, 0, 1)
        compass_layout.addWidget(west_label, 1, 0)
        compass_layout.addWidget(self.intersection_preview, 1, 1)
        compass_layout.addWidget(east_label, 1, 2)
        compass_layout.addWidget(south_label, 2, 1)
        compass_layout.setColumnStretch(1, 1)
        compass_layout.setRowStretch(1, 1)
        preview_layout.addWidget(
            compass_frame,
            0,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        )
        hint = muted_label(
            "Drag lampu SG untuk mengubah posisi lampu. Drag nama SG untuk "
            "mengubah posisi label secara terpisah."
        )
        hint.setWordWrap(True)
        preview_layout.addWidget(hint)

        names_frame = QFrame()
        names_frame.setObjectName("layoutSettingsGroup")
        names_layout = QVBoxLayout(names_frame)
        names_layout.setContentsMargins(8, 7, 8, 8)
        names_layout.setSpacing(4)
        names_title = QLabel("Signal Group Identification")
        names_title.setObjectName("layoutGroupTitle")
        names_layout.addWidget(names_title)
        names_grid = QGridLayout()
        names_grid.setHorizontalSpacing(6)
        names_grid.setVerticalSpacing(2)
        self.sg_name_inputs: list[QLineEdit] = []
        for index in range(12):
            label = QLabel(f"SG{index + 1}")
            field = QLineEdit()
            field.setFixedHeight(26)
            field.setMaxLength(40)
            field.setPlaceholderText(f"Signal Group {index + 1}")
            field.textChanged.connect(self._sg_name_preview_changed)
            self.sg_name_inputs.append(field)
            names_grid.addWidget(label, index, 0)
            names_grid.addWidget(field, index, 1)
        names_grid.setColumnStretch(1, 1)
        names_layout.addLayout(names_grid)
        self.save_sg_names_button = QPushButton("SAVE SG NAMES")
        self.save_sg_names_button.setProperty("systemAction", True)
        self.save_sg_names_button.setProperty("actionRole", "confirm")
        names_layout.addWidget(
            self.save_sg_names_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        preview_layout.addWidget(names_frame)
        preview_scroll.setWidget(preview_panel)
        layout.addWidget(preview_scroll, 67)
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
                self._intersection_dirty = False
                self._layout_schema = 0
                self._layout_revision = 0
                self._layout_source = "CACHE / OFFLINE"
                type_index = self.intersection_type_input.findData(
                    self._layout.intersection.diagram_type
                )
                self.intersection_type_input.setCurrentIndex(max(0, type_index))
                rotation_index = self.rotation_input.findData(
                    self._layout.intersection.rotation
                )
                self.rotation_input.setCurrentIndex(max(0, rotation_index))
                self._populate_road_arm_selectors()
                self.intersection_preview.set_layout_config(
                    self._layout.intersection
                )
                self.intersection_preview.set_signal_groups(
                    self._editor_signal_groups(snapshot)
                )
                self.sg_selector.clear()
                known = {item.number: item for item in snapshot.signal_groups}
                for number in range(
                    1,
                    max(1, snapshot.active_signal_groups) + 1,
                ):
                    signal_group = known.get(number)
                    name = (
                        signal_group.name
                        if signal_group is not None
                        else f"Signal Group {number}"
                    )
                    self.sg_selector.addItem(
                        f"SG{number} · {name}",
                        number,
                    )
                if self.sg_selector.count():
                    self.sg_selector.setCurrentIndex(0)
                self._update_layout_meta()
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
            self._selected_arm_changed()
            self._selected_sg_changed()
            self._update_intersection_controls()
            QTimer.singleShot(
                300,
                lambda key=controller_id: self.layout_service.refresh(
                    key,
                    force=True,
                    interactive=False,
                ),
            )
        else:
            self._camera_mode_changed()
            self._refresh_camera_preview()

    def _layout_loaded(
        self,
        controller_id: str,
        layout: object,
        schema_version: int,
        revision: int,
        source: str,
    ) -> None:
        if (
            self.section != "intersection"
            or controller_id != self.controller_id
            or not hasattr(layout, "placements")
        ):
            return
        snapshot = self.service.get_controller(controller_id)
        if snapshot is None:
            return
        if self._intersection_dirty:
            if revision == self._layout_revision:
                return
            self._set_message(
                "CONTROLLER LAYOUT CHANGED · UNSAVED EDITS PRESERVED · "
                "REOPEN CONTROLLER BEFORE SAVING",
                "warning",
            )
            return
        if (
            revision == self._layout_revision
            and layout == self._layout.intersection
        ):
            self._layout_schema = schema_version
            self._layout_source = source
            self._update_layout_meta()
            self._set_message(
                f"CONTROLLER LAYOUT VERIFIED · REV {revision}",
                "online",
            )
            return
        selected_arm = self.road_arm_selector.currentData()
        selected_sg = self.sg_selector.currentData()
        self._layout.intersection = deepcopy(layout)
        self._layout_schema = schema_version
        self._layout_revision = revision
        self._layout_source = source
        self._intersection_dirty = False
        self._loading = True
        try:
            type_index = self.intersection_type_input.findData(
                self._layout.intersection.diagram_type
            )
            self.intersection_type_input.setCurrentIndex(max(0, type_index))
            rotation_index = self.rotation_input.findData(
                self._layout.intersection.rotation
            )
            self.rotation_input.setCurrentIndex(max(0, rotation_index))
            self._populate_road_arm_selectors(str(selected_arm or ""))
            sg_index = self.sg_selector.findData(selected_sg)
            self.sg_selector.setCurrentIndex(sg_index if sg_index >= 0 else 0)
            self.intersection_preview.set_layout_config(
                self._layout.intersection
            )
            self.intersection_preview.set_signal_groups(
                self._editor_signal_groups(snapshot)
            )
        finally:
            self._loading = False
        self._selected_arm_changed()
        self._selected_sg_changed()
        self._update_layout_meta()
        self._update_intersection_controls()
        self._set_message(
            f"CONTROLLER LAYOUT LOADED · REV {revision}",
            "online",
        )

    def _layout_save_completed(
        self,
        controller_id: str,
        _layout: object,
        revision: int,
        message: str,
    ) -> None:
        if self.section != "intersection" or controller_id != self.controller_id:
            return
        if revision > 0:
            self._layout_revision = revision
        self._layout_source = "CONTROLLER · VERIFYING"
        self._intersection_dirty = False
        self._update_layout_meta()
        self._set_message(message, "online")
        self.intersection_saved.emit(controller_id, message)

    def _layout_request_failed(
        self,
        controller_id: str,
        action: str,
        message: str,
        code: int,
    ) -> None:
        if self.section != "intersection" or controller_id != self.controller_id:
            return
        if action == "load" and self._layout_revision <= 0:
            self._layout_source = "CACHE / OFFLINE"
        self._update_layout_meta()
        self._update_intersection_controls()
        suffix = " · CONFLICT 409" if code == 409 else ""
        self._set_message(f"{message}{suffix}", "offline")
        if action == "save":
            self.intersection_failed.emit(controller_id, message)
            QMessageBox.warning(self, "Intersection Layout", message)

    def _layout_busy_changed(self, controller_id: str, busy: bool) -> None:
        if self.section != "intersection" or controller_id != self.controller_id:
            return
        self._layout_busy = busy
        self._update_intersection_controls()

    def _update_layout_meta(self) -> None:
        if self.section != "intersection":
            return
        revision = str(self._layout_revision) if self._layout_revision > 0 else "—"
        schema = str(self._layout_schema) if self._layout_schema > 0 else "—"
        self.layout_meta_label.setText(
            f"{self._layout_source} · SCHEMA {schema} · REV {revision}"
        )

    def _update_intersection_controls(self) -> None:
        if self.section != "intersection":
            return
        snapshot = self.service.get_controller(self.controller_id)
        online = bool(snapshot and snapshot.online)
        editable = online and not self._layout_busy
        for widget in (
            self.intersection_type_input,
            self.rotation_input,
            self.road_arm_selector,
            self.arm_angle_input,
            self.arm_flow_input,
            self.sg_selector,
            self.assigned_arm_input,
            self.lane_position_input,
            self.sg_rotation_input,
            self.reload_intersection_button,
            self.reset_intersection_button,
        ):
            widget.setEnabled(editable)
        for checkbox in self._destination_checks.values():
            checkbox.setEnabled(editable)
        self.intersection_preview.set_editable(editable)
        self.save_intersection_button.setEnabled(
            bool(editable and self._layout_revision > 0)
        )

    def _editor_signal_groups(self, snapshot) -> list[SignalGroupState]:
        known = {item.number: item for item in snapshot.signal_groups}
        result: list[SignalGroupState] = []
        for number in range(
            1,
            max(1, snapshot.active_signal_groups) + 1,
        ):
            existing = known.get(number)
            typed_name = (
                self.sg_name_inputs[number - 1].text().strip()
                if hasattr(self, "sg_name_inputs")
                else ""
            )
            result.append(
                SignalGroupState(
                    number=number,
                    name=typed_name
                    or (existing.name if existing else f"Signal Group {number}"),
                    aspect=existing.aspect if existing else "OFF",
                )
            )
        return result

    def _sg_name_preview_changed(self, *_args) -> None:
        if self.section != "intersection" or self._loading:
            return
        snapshot = self.service.get_controller(self.controller_id)
        if snapshot is None:
            return
        selected = self.sg_selector.currentData()
        groups = self._editor_signal_groups(snapshot)
        self.intersection_preview.set_signal_groups(groups)
        self.sg_selector.blockSignals(True)
        for index, group in enumerate(groups):
            if index < self.sg_selector.count():
                self.sg_selector.setItemText(
                    index,
                    f"SG{group.number} · {group.name}",
                )
        selected_index = self.sg_selector.findData(selected)
        self.sg_selector.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.sg_selector.blockSignals(False)
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
                    12,
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
                self._populate_road_arm_selectors(
                    self.road_arm_selector.currentData()
                )
                self.intersection_preview.set_layout_config(
                    self._layout.intersection
                )
                self.intersection_preview.set_signal_groups(
                    self._editor_signal_groups(snapshot)
                )
                self.sg_selector.clear()
                known = {item.number: item for item in snapshot.signal_groups}
                for number in range(
                    1,
                    max(1, snapshot.active_signal_groups) + 1,
                ):
                    signal_group = known.get(number)
                    name = (
                        signal_group.name
                        if signal_group is not None
                        else f"Signal Group {number}"
                    )
                    self.sg_selector.addItem(
                        f"SG{number} · {name}",
                        number,
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
            self._selected_arm_changed()
            self._selected_sg_changed()
            self._update_intersection_controls()
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

    def _populate_road_arm_selectors(
        self,
        selected_arm_id: str | None = None,
    ) -> None:
        arms = self._layout.intersection.road_arms
        if not arms:
            arms = default_road_arms(
                self._layout.intersection.diagram_type
            )
            self._layout.intersection.road_arms = arms
        selected = str(
            selected_arm_id
            or self.road_arm_selector.currentData()
            or next(iter(arms), "")
        )
        assigned = str(
            self.assigned_arm_input.currentData()
            or selected
        )
        self.road_arm_selector.clear()
        self.assigned_arm_input.clear()
        for index, arm in enumerate(arms.values()):
            label = _arm_display(
                arm,
                index,
                self._layout.intersection.rotation,
            )
            self.road_arm_selector.addItem(label, arm.arm_id)
            self.assigned_arm_input.addItem(label, arm.arm_id)
        road_index = self.road_arm_selector.findData(selected)
        self.road_arm_selector.setCurrentIndex(max(0, road_index))
        assigned_index = self.assigned_arm_input.findData(assigned)
        self.assigned_arm_input.setCurrentIndex(max(0, assigned_index))

    def _selected_arm_changed(self) -> None:
        if self._loading:
            return
        arm_id = self.road_arm_selector.currentData()
        arm = self._layout.intersection.road_arms.get(str(arm_id))
        if arm is None:
            return
        self._loading = True
        try:
            self.arm_angle_input.setValue(
                effective_arm_angle(
                    arm,
                    self._layout.intersection.rotation,
                )
            )
            flow_index = self.arm_flow_input.findData(arm.flow_direction)
            self.arm_flow_input.setCurrentIndex(max(0, flow_index))
        finally:
            self._loading = False

    def _road_arm_changed(self, *_args) -> None:
        if self._loading:
            return
        arm_id = str(self.road_arm_selector.currentData() or "")
        arm = self._layout.intersection.road_arms.get(arm_id)
        if arm is None:
            return
        arm.angle = (
            float(self.arm_angle_input.value())
            - float(self._layout.intersection.rotation)
        ) % 360.0
        arm.flow_direction = str(
            self.arm_flow_input.currentData() or "TWO_WAY"
        )
        arm_index = list(self._layout.intersection.road_arms).index(arm_id)
        label = _arm_display(
            arm,
            arm_index,
            self._layout.intersection.rotation,
        )
        road_index = self.road_arm_selector.findData(arm_id)
        assigned_index = self.assigned_arm_input.findData(arm_id)
        if road_index >= 0:
            self.road_arm_selector.setItemText(road_index, label)
        if assigned_index >= 0:
            self.assigned_arm_input.setItemText(assigned_index, label)
        self.intersection_preview.set_layout_config(
            self._layout.intersection
        )
        self._intersection_dirty = True
        self._selected_sg_changed()
        self._set_message(
            f"{arm.name.upper()} ROAD ARM CHANGED · NOT SAVED",
            "warning",
        )

    def _rebuild_destination_checks(
        self,
        placement,
    ) -> None:
        while self.destination_layout.count():
            item = self.destination_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._destination_checks.clear()
        source = self._layout.intersection.road_arms.get(
            placement.road_arm_id
        )
        if source is None:
            return
        arm_order = list(self._layout.intersection.road_arms)
        destinations = sorted(
            (
                arm
                for arm in self._layout.intersection.road_arms.values()
                if arm.arm_id != source.arm_id
            ),
            key=lambda arm: _destination_sort_key(
                source,
                arm,
                arm_order.index(arm.arm_id),
            ),
        )
        for index, arm in enumerate(destinations):
            movement = _destination_movement(source, arm)
            arm_index = arm_order.index(arm.arm_id)
            arm_number = _arm_number(arm, arm_index)
            direction = _direction_name(
                effective_arm_angle(
                    arm,
                    self._layout.intersection.rotation,
                )
            )
            checkbox = QCheckBox(
                f"Arm {arm_number} – {direction} ({movement})"
            )
            checkbox.setChecked(
                arm.arm_id in placement.destination_arm_ids
            )
            checkbox.setToolTip(
                f"Vehicle from {source.name} exits through {arm.name}."
            )
            checkbox.toggled.connect(self._sg_visual_changed)
            self.destination_layout.addWidget(
                checkbox,
                index,
                0,
            )
            self._destination_checks[arm.arm_id] = checkbox
        if not destinations:
            label = muted_label("No destination road arm")
            self.destination_layout.addWidget(label, 0, 0)

    def _intersection_template_changed(self) -> None:
        if self._loading or not self.controller_id:
            return
        new_type = str(self.intersection_type_input.currentData())
        new_rotation = int(self.rotation_input.currentData())
        old_type = self._layout.intersection.diagram_type
        old_rotation = self._layout.intersection.rotation
        type_changed = new_type != old_type
        rotation_changed = new_rotation != old_rotation
        if not type_changed and not rotation_changed:
            return

        if type_changed:
            answer = QMessageBox.question(
                self,
                "Change Diagram Type",
                "Mengubah Diagram Type akan membuat ulang Road Arm dan posisi "
                "seluruh SG. Lanjutkan?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._loading = True
                try:
                    previous_index = self.intersection_type_input.findData(
                        old_type
                    )
                    self.intersection_type_input.setCurrentIndex(
                        max(0, previous_index)
                    )
                finally:
                    self._loading = False
                return
            self._layout.intersection.diagram_type = new_type
            self._layout.intersection.rotation = new_rotation
            self._layout.intersection.road_arms = default_road_arms(new_type)
            self._layout.intersection.placements = default_signal_placements(
                new_type,
                new_rotation,
                12,
            )
        else:
            delta = (new_rotation - old_rotation) % 360
            turns = (delta // 90) % 4
            for placement in self._layout.intersection.placements.values():
                x, y = placement.x, placement.y
                offset_x = placement.label_offset_x
                offset_y = placement.label_offset_y
                for _ in range(turns):
                    x, y = 1.0 - y, x
                    offset_x, offset_y = -offset_y, offset_x
                placement.x = round(x, 3)
                placement.y = round(y, 3)
                placement.label_offset_x = round(offset_x, 3)
                placement.label_offset_y = round(offset_y, 3)
                if placement.rotation in {0, 90, 180, 270}:
                    placement.rotation = (placement.rotation + delta) % 360
            self._layout.intersection.rotation = new_rotation
        self._intersection_dirty = True
        self._loading = True
        try:
            self._populate_road_arm_selectors()
        finally:
            self._loading = False
        self.intersection_preview.set_layout_config(
            self._layout.intersection
        )
        self._selected_arm_changed()
        self._selected_sg_changed()
        self._set_message(
            (
                f"{new_type.replace('_', ' ')} TEMPLATE CHANGED · "
                "CHECK ALL ROAD ARMS AND SG POSITIONS · NOT SAVED"
                if type_changed
                else "ROTATION, SG POSITION, SG ROTATION, AND LABEL POSITION "
                "ADJUSTED · NOT SAVED"
            ),
            "warning",
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
            assigned_index = self.assigned_arm_input.findData(
                placement.road_arm_id
            )
            self.assigned_arm_input.setCurrentIndex(
                max(0, assigned_index)
            )
            self.lane_position_input.setValue(placement.lane_position)
            rotation_index = self.sg_rotation_input.findData(
                placement.rotation
            )
            self.sg_rotation_input.setCurrentIndex(max(0, rotation_index))
            self._rebuild_destination_checks(placement)
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
        arm_id = str(self.assigned_arm_input.currentData() or "")
        source_changed = arm_id != placement.road_arm_id
        if arm_id not in self._layout.intersection.road_arms:
            return
        if source_changed:
            placement.road_arm_id = arm_id
            placement.destination_arm_ids = destination_ids_for_movements(
                arm_id,
                placement.movements,
                self._layout.intersection.road_arms,
            )
            self._loading = True
            try:
                self._rebuild_destination_checks(placement)
            finally:
                self._loading = False
        placement.lane_position = self.lane_position_input.value()
        placement.rotation = int(self.sg_rotation_input.currentData())
        destinations = [
            destination_id
            for destination_id, checkbox in self._destination_checks.items()
            if checkbox.isChecked() and checkbox.isEnabled()
        ]
        if not destinations:
            first_enabled = next(
                (
                    (destination_id, checkbox)
                    for destination_id, checkbox
                    in self._destination_checks.items()
                    if checkbox.isEnabled()
                ),
                None,
            )
            if first_enabled is not None:
                destination_id, checkbox = first_enabled
                self._loading = True
                checkbox.setChecked(True)
                self._loading = False
                destinations = [destination_id]
        placement.destination_arm_ids = destinations
        source = self._layout.intersection.road_arms[arm_id]
        movements: list[str] = []
        for destination_id in destinations:
            destination = self._layout.intersection.road_arms.get(
                destination_id
            )
            if destination is None:
                continue
            name = movement_name_between(source, destination).upper()
            movement = (
                "LEFT" if "LEFT" in name
                else "RIGHT" if "RIGHT" in name
                else "STRAIGHT"
            )
            if movement not in movements:
                movements.append(movement)
        placement.movements = movements or ["STRAIGHT"]
        self.intersection_preview.set_layout_config(
            self._layout.intersection
        )
        self.intersection_preview.set_selected_signal(int(number))
        self._intersection_dirty = True
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
        self._intersection_dirty = True
        self._set_message(
            f"SG{number} POSITION · X {x:.2f} · Y {y:.2f} · NOT SAVED",
            "warning",
        )

    def _intersection_label_changed(
        self,
        number: int,
        offset_x: float,
        offset_y: float,
    ) -> None:
        if self._loading:
            return
        self._layout.intersection = self.intersection_preview.layout_config()
        self._intersection_dirty = True
        self._set_message(
            f"SG{number} LABEL POSITION · X {offset_x:+.2f} · "
            f"Y {offset_y:+.2f} · NOT SAVED",
            "warning",
        )

    def _reset_intersection(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset SG Positions",
            "Kembalikan posisi seluruh SG dan nama SG ke susunan awal Diagram "
            "Type saat ini? Perubahan belum disimpan sampai SAVE ditekan.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.intersection_preview.reset_placements()
        self._layout.intersection = self.intersection_preview.layout_config()
        self._intersection_dirty = True
        self._set_message("SG POSITIONS RESET · NOT SAVED", "warning")

    def _reload_intersection(self) -> None:
        if not self.controller_id or self._layout_busy:
            return
        if self._intersection_dirty:
            answer = QMessageBox.question(
                self,
                "Reload Intersection Layout",
                "Perubahan Intersection Layout belum disimpan. Muat ulang dan "
                "buang perubahan tersebut?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._intersection_dirty = False
        self._set_message("LOADING INTERSECTION LAYOUT...", "warning")
        self.layout_service.refresh(
            self.controller_id,
            force=True,
            interactive=True,
        )

    def _save_intersection(self) -> None:
        if not self.controller_id:
            return
        self._layout.intersection = self.intersection_preview.layout_config()
        self.layout_service.save(
            self.controller_id,
            self._layout.intersection,
            self._layout_revision,
        )
        self._set_message("SAVING INTERSECTION LAYOUT...", "warning")

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
        self.repository.save_cameras(
            self.controller_id,
            self._layout.cameras,
        )
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
