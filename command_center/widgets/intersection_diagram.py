from __future__ import annotations

from copy import deepcopy
from math import atan2, cos, pi, sin
from time import monotonic

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..display_layout import (
    IntersectionLayoutConfig,
    RoadArm,
    SignalPlacement,
    default_road_arms,
    default_signal_placements,
    effective_arm_angle,
)
from ..models import SignalGroupState


class IntersectionDiagram(QWidget):
    """Configurable road diagram with draggable SG indicators."""

    placement_changed = Signal(int, float, float)
    label_offset_changed = Signal(int, float, float)
    signal_selected = Signal(int)

    ASPECT_COLORS = {
        "RED": QColor("#ef5a64"),
        "YELLOW": QColor("#f6c453"),
        "GREEN": QColor("#42d58b"),
        "OFF": QColor("#344353"),
    }
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._signal_groups: list[SignalGroupState] = []
        self._layout = IntersectionLayoutConfig()
        self._editable = False
        self._show_compass_labels = True
        self._selected_signal: int | None = None
        self._drag_number: int | None = None
        self._drag_label_number: int | None = None
        self._signal_rects: dict[int, QRectF] = {}
        self._label_rects: dict[int, QRectF] = {}
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(100)
        self._flash_timer.timeout.connect(self.update)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def set_editable(self, editable: bool) -> None:
        editable = bool(editable)
        if editable == self._editable:
            return
        self._editable = editable
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if editable
            else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def set_layout_config(self, layout: IntersectionLayoutConfig) -> None:
        updated = deepcopy(layout)
        if updated == self._layout:
            return
        self._layout = updated
        self.update()

    def set_compass_labels_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible == self._show_compass_labels:
            return
        self._show_compass_labels = visible
        self.update()

    def set_selected_signal(self, number: int | None) -> None:
        self._selected_signal = number
        self.update()

    def layout_config(self) -> IntersectionLayoutConfig:
        return deepcopy(self._layout)

    def reset_placements(self) -> None:
        previous = self._layout.placements
        updated = default_signal_placements(
            self._layout.diagram_type,
            self._layout.rotation,
            12,
        )
        for number, placement in updated.items():
            old = previous.get(number)
            if old is not None:
                placement.rotation = old.rotation
                placement.movements = list(old.movements)
                placement.flow_direction = old.flow_direction
                placement.road_arm_id = old.road_arm_id
                placement.lane_position = old.lane_position
                placement.destination_arm_ids = list(
                    old.destination_arm_ids
                )
        self._layout.placements = updated
        self.update()

    def set_signal_groups(self, signal_groups: list[SignalGroupState]) -> None:
        changed = signal_groups != self._signal_groups
        self._signal_groups = list(signal_groups)
        defaults = default_signal_placements(
            self._layout.diagram_type,
            self._layout.rotation,
            len(signal_groups),
        )
        for number, placement in defaults.items():
            self._layout.placements.setdefault(number, placement)
        flashing = any(
            item.aspect.upper().startswith("FLASH YELLOW")
            for item in signal_groups
        )
        if flashing and not self._flash_timer.isActive():
            self._flash_timer.start()
        elif not flashing:
            self._flash_timer.stop()
        if changed:
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0c2823"))
        canvas = self._canvas_rect()
        painter.save()
        painter.translate(canvas.left(), canvas.top())
        width = canvas.width()
        height = canvas.height()
        center_x = width / 2.0
        center_y = height / 2.0
        road_arms = self._layout.road_arms or default_road_arms(
            self._layout.diagram_type
        )
        road_width = min(width, height) * (
            0.245 if len(road_arms) >= 5 else 0.32
        )
        half_road = road_width / 2.0
        self._draw_arm_roads(
            painter,
            road_arms,
            center_x,
            center_y,
            half_road,
            road_width,
            width,
            height,
        )
        self._draw_arm_lane_markings(
            painter,
            road_arms,
            center_x,
            center_y,
            half_road,
            road_width,
            width,
            height,
        )
        if self._editable:
            self._draw_arm_labels(painter, road_arms, width, height)
        if self._show_compass_labels:
            self._draw_compass_labels(painter, width, height)
        self._draw_outbound_indicators(
            painter,
            road_arms,
            road_width,
            width,
            height,
        )

        defaults = default_signal_placements(
            self._layout.diagram_type,
            self._layout.rotation,
            len(self._signal_groups),
        )
        for signal_group in self._signal_groups:
            placement = self._layout.placements.get(
                signal_group.number,
                defaults.get(signal_group.number, SignalPlacement(0.5, 0.5)),
            )
            self._draw_vehicle_flow(
                painter,
                placement,
                signal_group,
                width,
                height,
                road_width,
            )

        self._signal_rects.clear()
        self._label_rects.clear()
        compact = len(self._signal_groups) > 8
        box_width = width * (0.155 if compact else 0.20)
        box_height = width * (0.061 if compact else 0.074)
        for signal_group in self._signal_groups:
            placement = self._layout.placements.get(
                signal_group.number,
                defaults.get(signal_group.number, SignalPlacement(0.5, 0.5)),
            )
            left = max(
                2.0,
                min(width - box_width - 2.0, placement.x * width - box_width / 2),
            )
            top = max(
                2.0,
                min(height - box_height - 2.0, placement.y * height - box_height / 2),
            )
            rect = QRectF(left, top, box_width, box_height)
            signal_rotation = self._signal_rotation(placement)
            if signal_rotation in {90, 270}:
                hit_rect = QRectF(
                    rect.center().x() - box_height / 2.0,
                    rect.center().y() - box_width / 2.0,
                    box_height,
                    box_width,
                )
            elif signal_rotation in {0, 180}:
                hit_rect = rect
            else:
                hit_size = max(box_width, box_height)
                hit_rect = QRectF(
                    rect.center().x() - hit_size / 2.0,
                    rect.center().y() - hit_size / 2.0,
                    hit_size,
                    hit_size,
                )
            self._signal_rects[signal_group.number] = hit_rect.translated(
                canvas.left(),
                canvas.top(),
            )
            self._draw_signal(
                painter,
                rect,
                signal_group,
                placement,
                compact,
            )
            self._draw_signal_name(
                painter,
                signal_group,
                placement,
                width,
                height,
                canvas,
            )

        painter.restore()

    def _canvas_rect(self) -> QRectF:
        available_height = max(
            1.0,
            float(self.height()),
        )
        size = max(1.0, min(float(self.width()), available_height))
        return QRectF(
            (float(self.width()) - size) / 2.0,
            (available_height - size) / 2.0,
            size,
            size,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._editable or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        position = event.position()
        for number, rect in reversed(tuple(self._label_rects.items())):
            if rect.contains(position):
                self._selected_signal = number
                self.signal_selected.emit(number)
                self._drag_label_number = number
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        for number, rect in reversed(tuple(self._signal_rects.items())):
            if rect.contains(position):
                self._selected_signal = number
                self.signal_selected.emit(number)
                self._drag_number = number
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_label_number is not None:
            canvas = self._canvas_rect()
            placement = self._layout.placements.get(self._drag_label_number)
            if placement is None:
                return
            label_x = (event.position().x() - canvas.left()) / canvas.width()
            label_y = (event.position().y() - canvas.top()) / canvas.height()
            placement.label_offset_x = max(
                -0.24,
                min(0.24, label_x - placement.x),
            )
            placement.label_offset_y = max(
                -0.24,
                min(0.24, label_y - placement.y),
            )
            self.label_offset_changed.emit(
                self._drag_label_number,
                placement.label_offset_x,
                placement.label_offset_y,
            )
            self.update()
            event.accept()
            return
        if self._drag_number is None:
            return super().mouseMoveEvent(event)
        canvas = self._canvas_rect()
        x = max(
            0.06,
            min(0.94, (event.position().x() - canvas.left()) / canvas.width()),
        )
        y = max(
            0.06,
            min(0.94, (event.position().y() - canvas.top()) / canvas.height()),
        )
        placement = self._layout.placements.setdefault(
            self._drag_number,
            SignalPlacement(x=x, y=y),
        )
        placement.x = x
        placement.y = y
        self.placement_changed.emit(self._drag_number, x, y)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_label_number is not None:
            self._drag_label_number = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if self._drag_number is not None:
            self._drag_number = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _draw_arm_roads(
        self,
        painter: QPainter,
        road_arms: dict[str, RoadArm],
        center_x: float,
        center_y: float,
        half_road: float,
        road_width: float,
        width: float,
        height: float,
    ) -> None:
        del road_width
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#303944"))
        center = QPointF(center_x, center_y)
        distance = max(width, height) * 0.78
        for arm in road_arms.values():
            outward, lateral = self._arm_vectors(arm)
            outer = QPointF(
                center.x() + outward.x() * distance,
                center.y() + outward.y() * distance,
            )
            painter.drawPolygon(
                QPolygonF(
                    [
                        self._offset_point(center, lateral, -half_road),
                        self._offset_point(outer, lateral, -half_road),
                        self._offset_point(outer, lateral, half_road),
                        self._offset_point(center, lateral, half_road),
                    ]
                )
            )
        painter.drawEllipse(
            center,
            half_road * 1.08,
            half_road * 1.08,
        )

    def _draw_arm_lane_markings(
        self,
        painter: QPainter,
        road_arms: dict[str, RoadArm],
        center_x: float,
        center_y: float,
        half_road: float,
        road_width: float,
        width: float,
        height: float,
    ) -> None:
        del road_width
        center = QPointF(center_x, center_y)
        distance = max(width, height) * 0.70
        dash_pen = QPen(QColor("#d9c66d"), 2)
        dash_pen.setStyle(Qt.PenStyle.DashLine)
        stop_pen = QPen(QColor("#edf3f8"), 3)
        for arm in road_arms.values():
            outward, lateral = self._arm_vectors(arm)
            lane_start = self._advance_point(
                center,
                outward,
                half_road + 10.0,
            )
            lane_end = self._advance_point(center, outward, distance)
            painter.setPen(dash_pen)
            painter.drawLine(lane_start, lane_end)

            stop_center = self._advance_point(
                center,
                outward,
                half_road + 6.0,
            )
            inset = 6.0
            painter.setPen(stop_pen)
            painter.drawLine(
                self._offset_point(
                    stop_center,
                    lateral,
                    -(half_road - inset),
                ),
                self._offset_point(
                    stop_center,
                    lateral,
                    half_road - inset,
                ),
            )

    def _draw_arm_labels(
        self,
        painter: QPainter,
        road_arms: dict[str, RoadArm],
        width: float,
        height: float,
    ) -> None:
        painter.setPen(QColor("#b8c9d8"))
        font = QFont("Segoe UI", 8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        center = QPointF(width / 2.0, height / 2.0)
        distance = min(width, height) * 0.43
        for arm in road_arms.values():
            outward, _ = self._arm_vectors(arm)
            point = self._advance_point(center, outward, distance)
            rect = QRectF(point.x() - 42.0, point.y() - 9.0, 84.0, 18.0)
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                arm.arm_id.upper(),
            )

    @staticmethod
    def _draw_compass_labels(
        painter: QPainter,
        width: float,
        height: float,
    ) -> None:
        painter.setPen(QColor("#79c7ff"))
        font = QFont("Segoe UI", 8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        labels = (
            ("NORTH", QRectF(width / 2.0 - 36.0, 3.0, 72.0, 18.0)),
            ("EAST", QRectF(width - 75.0, height / 2.0 - 9.0, 72.0, 18.0)),
            ("SOUTH", QRectF(width / 2.0 - 36.0, height - 21.0, 72.0, 18.0)),
            ("WEST", QRectF(3.0, height / 2.0 - 9.0, 72.0, 18.0)),
        )
        for text, rect in labels:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_outbound_indicators(
        self,
        painter: QPainter,
        road_arms: dict[str, RoadArm],
        road_width: float,
        width: float,
        height: float,
    ) -> None:
        color = QColor("#6f879b")
        color.setAlpha(145)
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        for arm in road_arms.values():
            if arm.flow_direction not in {"OUTBOUND", "TWO_WAY"}:
                continue
            start = self._arm_inner_point(
                arm,
                False,
                width,
                height,
                road_width * 0.22,
            )
            end = self._arm_edge_point(
                arm,
                False,
                width,
                height,
                road_width * 0.22,
            )
            path = QPainterPath(start)
            path.lineTo(end)
            self._draw_flow_path(painter, path, pen, color)

    def _arm_vectors(self, arm: RoadArm) -> tuple[QPointF, QPointF]:
        angle = effective_arm_angle(arm, self._layout.rotation) * pi / 180.0
        outward = QPointF(sin(angle), -cos(angle))
        lateral = QPointF(cos(angle), sin(angle))
        return outward, lateral

    @staticmethod
    def _advance_point(
        point: QPointF,
        vector: QPointF,
        distance: float,
    ) -> QPointF:
        return QPointF(
            point.x() + vector.x() * distance,
            point.y() + vector.y() * distance,
        )

    @staticmethod
    def _offset_point(
        point: QPointF,
        vector: QPointF,
        distance: float,
    ) -> QPointF:
        return QPointF(
            point.x() + vector.x() * distance,
            point.y() + vector.y() * distance,
        )

    def _arm_edge_point(
        self,
        arm: RoadArm,
        inbound: bool,
        width: float,
        height: float,
        lane_offset: float,
    ) -> QPointF:
        center = QPointF(width / 2.0, height / 2.0)
        outward, lateral = self._arm_vectors(arm)
        edge = self._advance_point(
            center,
            outward,
            min(width, height) * 0.44,
        )
        return self._offset_point(
            edge,
            lateral,
            lane_offset if inbound else -lane_offset,
        )

    def _arm_inner_point(
        self,
        arm: RoadArm,
        inbound: bool,
        width: float,
        height: float,
        lane_offset: float,
    ) -> QPointF:
        center = QPointF(width / 2.0, height / 2.0)
        outward, lateral = self._arm_vectors(arm)
        inner = self._advance_point(
            center,
            outward,
            min(width, height) * 0.075,
        )
        return self._offset_point(
            inner,
            lateral,
            lane_offset if inbound else -lane_offset,
        )

    def _draw_vehicle_flow(
        self,
        painter: QPainter,
        placement: SignalPlacement,
        signal_group: SignalGroupState,
        width: float,
        height: float,
        road_width: float,
    ) -> None:
        road_arms = self._layout.road_arms or default_road_arms(
            self._layout.diagram_type
        )
        source = road_arms.get(placement.road_arm_id)
        if source is None or source.flow_direction not in {"INBOUND", "TWO_WAY"}:
            return
        lane_offset = road_width * min(
            0.43,
            0.16 + 0.08 * max(0, placement.lane_position - 1),
        )
        color = self._flow_color(signal_group.aspect)
        pen = QPen(
            color,
            3
            if self._effective_aspect(signal_group.aspect)
            in {"GREEN", "YELLOW"}
            else 2,
        )
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        start = self._arm_edge_point(
            source,
            True,
            width,
            height,
            lane_offset,
        )
        destination_ids = [
            arm_id
            for arm_id in placement.destination_arm_ids
            if arm_id in road_arms and arm_id != source.arm_id
        ]
        source_heading = (
            effective_arm_angle(source, self._layout.rotation) + 180.0
        ) % 360.0
        routes: list[tuple[RoadArm, float, float]] = []
        for arm_id in destination_ids:
            destination = road_arms[arm_id]
            if destination.flow_direction not in {"OUTBOUND", "TWO_WAY"}:
                continue
            destination_heading = effective_arm_angle(
                destination,
                self._layout.rotation,
            )
            delta = self._signed_angle(
                destination_heading - source_heading
            )
            magnitude = abs(delta)
            branch_factor = (
                0.46
                if magnitude <= 25.0
                else 0.54
                if magnitude < 70.0
                else 0.48
                if delta < 0.0
                else 0.64
            )
            routes.append((destination, delta, branch_factor))

        if routes:
            trunk_factor = min(route[2] for route in routes)
            trunk_end = self._arm_lane_point(
                source,
                width,
                height,
                road_width * trunk_factor,
                lane_offset,
                True,
            )
            trunk = QPainterPath(start)
            trunk.lineTo(trunk_end)
            self._draw_flow_segment(painter, trunk, pen)

        for destination, delta, branch_factor in routes:
            magnitude = abs(delta)
            straight = magnitude <= 25.0
            branch_start = self._arm_lane_point(
                source,
                width,
                height,
                road_width * branch_factor,
                lane_offset,
                True,
            )
            destination_offset = (
                lane_offset if straight else road_width * 0.22
            )
            end = self._arm_edge_point(
                destination,
                False,
                width,
                height,
                destination_offset,
            )
            path = (
                self._straight_branch_path(branch_start, end)
                if straight
                else self._turn_branch_path(
                    branch_start,
                    end,
                    source,
                    destination,
                    road_width,
                    width,
                    height,
                )
            )
            self._draw_flow_path(painter, path, pen, color)
        if not routes:
            path = QPainterPath(start)
            path.lineTo(
                self._arm_inner_point(
                    source,
                    True,
                    width,
                    height,
                    lane_offset,
                )
            )
            self._draw_flow_path(painter, path, pen, color)

    @staticmethod
    def _signed_angle(value: float) -> float:
        return (value + 180.0) % 360.0 - 180.0

    @staticmethod
    def _straight_branch_path(
        start: QPointF,
        end: QPointF,
    ) -> QPainterPath:
        path = QPainterPath(start)
        path.lineTo(end)
        return path

    def _turn_branch_path(
        self,
        start: QPointF,
        end: QPointF,
        source: RoadArm,
        destination: RoadArm,
        road_width: float,
        width: float,
        height: float,
    ) -> QPainterPath:
        source_outward, _ = self._arm_vectors(source)
        destination_outward, _ = self._arm_vectors(destination)
        control_one = self._advance_point(
            start,
            source_outward,
            -road_width * 0.72,
        )
        control_two = self._advance_point(
            end,
            destination_outward,
            -min(width, height) * 0.22,
        )
        path = QPainterPath(start)
        path.cubicTo(control_one, control_two, end)
        return path

    def _arm_lane_point(
        self,
        arm: RoadArm,
        width: float,
        height: float,
        distance: float,
        lane_offset: float,
        inbound: bool,
    ) -> QPointF:
        center = QPointF(width / 2.0, height / 2.0)
        outward, lateral = self._arm_vectors(arm)
        point = self._advance_point(center, outward, distance)
        return self._offset_point(
            point,
            lateral,
            lane_offset if inbound else -lane_offset,
        )

    @staticmethod
    def _draw_flow_segment(
        painter: QPainter,
        path: QPainterPath,
        pen: QPen,
    ) -> None:
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _draw_flow_path(
        self,
        painter: QPainter,
        path: QPainterPath,
        pen: QPen,
        color: QColor,
    ) -> None:
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        self._draw_arrowhead(
            painter,
            path.pointAtPercent(1.0),
            path.pointAtPercent(0.94),
            color,
        )

    @staticmethod
    def _draw_arrowhead(
        painter: QPainter,
        tip: QPointF,
        previous: QPointF,
        color: QColor,
    ) -> None:
        angle = atan2(tip.y() - previous.y(), tip.x() - previous.x())
        length = 9.0
        left = QPointF(
            tip.x() - length * cos(angle - pi / 6),
            tip.y() - length * sin(angle - pi / 6),
        )
        right = QPointF(
            tip.x() - length * cos(angle + pi / 6),
            tip.y() - length * sin(angle + pi / 6),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([tip, left, right]))

    def _flow_color(self, aspect: str) -> QColor:
        effective = self._effective_aspect(aspect)
        color = {
            "GREEN": QColor("#42d58b"),
            "YELLOW": QColor("#f6c453"),
            "RED": QColor("#a64c55"),
            "RED + YELLOW": QColor("#d99055"),
        }.get(effective, QColor("#778899"))
        color.setAlpha(210)
        return color

    @staticmethod
    def _effective_aspect(aspect: str) -> str:
        value = aspect.upper()
        if value.startswith("FLASH YELLOW"):
            period_ms = 1000 if value.endswith("1000") else 500
            return (
                "YELLOW"
                if int(monotonic() * 1000 / period_ms) % 2 == 0
                else "OFF"
            )
        return value

    def _signal_rotation(self, placement: SignalPlacement) -> int:
        if placement.rotation in {0, 90, 180, 270}:
            return placement.rotation
        road_arms = self._layout.road_arms or default_road_arms(
            self._layout.diagram_type
        )
        arm = road_arms.get(placement.road_arm_id)
        if arm is not None:
            return int(round(effective_arm_angle(
                arm,
                self._layout.rotation,
            ))) % 360
        return (
            90
            if abs(placement.x - 0.5) > abs(placement.y - 0.5)
            else 0
        )

    def _draw_signal_name(
        self,
        painter: QPainter,
        signal_group: SignalGroupState,
        placement: SignalPlacement,
        width: float,
        height: float,
        canvas: QRectF,
    ) -> None:
        font = QFont("Segoe UI", 8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text = metrics.elidedText(
            signal_group.name or f"Signal Group {signal_group.number}",
            Qt.TextElideMode.ElideRight,
            122,
        )
        center_x = max(
            65.0,
            min(width - 65.0, (placement.x + placement.label_offset_x) * width),
        )
        center_y = max(
            11.0,
            min(height - 11.0, (placement.y + placement.label_offset_y) * height),
        )
        rect = QRectF(center_x - 65.0, center_y - 10.0, 130.0, 20.0)
        background = QColor("#102631")
        background.setAlpha(220)
        painter.setPen(
            QPen(
                QColor("#79c7ff")
                if signal_group.number == self._selected_signal
                else QColor("#526e7e"),
                1,
            )
        )
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor("#ffad5b" if self._editable else "#9bd8ff"))
        painter.drawText(rect.adjusted(4, 0, -4, 0), Qt.AlignmentFlag.AlignCenter, text)
        self._label_rects[signal_group.number] = rect.translated(
            canvas.left(),
            canvas.top(),
        )

    def _draw_signal(
        self,
        painter: QPainter,
        rect: QRectF,
        signal_group: SignalGroupState,
        placement: SignalPlacement,
        compact: bool,
    ) -> None:
        painter.save()
        painter.translate(rect.center())
        painter.rotate(self._signal_rotation(placement))
        local_rect = QRectF(
            -rect.width() / 2.0,
            -rect.height() / 2.0,
            rect.width(),
            rect.height(),
        )
        border = (
            QColor("#79c7ff")
            if signal_group.number == self._selected_signal
            else QColor("#7b91a6" if self._editable else "#516477")
        )
        painter.setPen(QPen(border, 2 if signal_group.number == self._selected_signal else 1))
        painter.setBrush(QColor("#071019"))
        painter.drawRoundedRect(local_rect, 6, 6)

        painter.setPen(QColor("#dce8f3"))
        font = QFont("Segoe UI", 7 if compact else 8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        label_width = 27 if compact else 33
        painter.drawText(
            QRectF(
                local_rect.x() + 2,
                local_rect.y(),
                label_width,
                local_rect.height(),
            ),
            Qt.AlignmentFlag.AlignCenter,
            f"SG{signal_group.number}",
        )

        active_aspect = self._effective_aspect(signal_group.aspect)
        available = local_rect.width() - label_width - 4
        spacing = available / 3
        radius = 4.5 if compact else 6.0
        for index, aspect in enumerate(("RED", "YELLOW", "GREEN")):
            active = active_aspect == aspect or (
                active_aspect == "RED + YELLOW" and aspect in {"RED", "YELLOW"}
            )
            color = self.ASPECT_COLORS[aspect] if active else QColor("#26313b")
            painter.setPen(QPen(QColor("#596775"), 1))
            painter.setBrush(color)
            painter.drawEllipse(
                QPointF(
                    local_rect.x() + label_width + spacing * (index + 0.5),
                    local_rect.center().y(),
                ),
                radius,
                radius,
            )
        painter.restore()
