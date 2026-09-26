from __future__ import annotations

from copy import deepcopy
from math import atan2, cos, pi, sin
from time import monotonic

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..display_layout import (
    IntersectionLayoutConfig,
    SignalPlacement,
    default_signal_placements,
)
from ..models import SignalGroupState


class IntersectionDiagram(QWidget):
    """Configurable road diagram with draggable SG indicators."""

    placement_changed = Signal(int, float, float)
    signal_selected = Signal(int)

    ASPECT_COLORS = {
        "RED": QColor("#ef5a64"),
        "YELLOW": QColor("#f6c453"),
        "GREEN": QColor("#42d58b"),
        "OFF": QColor("#344353"),
    }
    DIRECTION_ORDER = ("NORTH", "EAST", "SOUTH", "WEST")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._signal_groups: list[SignalGroupState] = []
        self._layout = IntersectionLayoutConfig()
        self._editable = False
        self._selected_signal: int | None = None
        self._drag_number: int | None = None
        self._signal_rects: dict[int, QRectF] = {}
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(100)
        self._flash_timer.timeout.connect(self.update)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if editable
            else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def set_layout_config(self, layout: IntersectionLayoutConfig) -> None:
        self._layout = deepcopy(layout)
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
            len(self._signal_groups),
        )
        for number, placement in updated.items():
            old = previous.get(number)
            if old is not None:
                placement.rotation = old.rotation
                placement.movements = list(old.movements)
                placement.flow_direction = old.flow_direction
        self._layout.placements = updated
        self.update()

    def set_signal_groups(self, signal_groups: list[SignalGroupState]) -> None:
        self._signal_groups = signal_groups
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
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        full_width = float(self.width())
        full_height = float(self.height())
        painter.fillRect(self.rect(), QColor("#0c2823"))
        canvas = self._canvas_rect()
        painter.save()
        painter.translate(canvas.left(), canvas.top())
        width = canvas.width()
        height = canvas.height()
        center_x = width / 2.0
        center_y = height / 2.0
        road_width = min(width, height) * 0.32
        half_road = road_width / 2.0

        directions = self._road_directions()
        self._draw_roads(
            painter, directions, center_x, center_y, half_road,
            road_width, width, height,
        )
        self._draw_lane_markings(
            painter, directions, center_x, center_y, half_road, width, height,
        )
        self._draw_direction_labels(painter, directions, width, height)

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
            )

        self._signal_rects.clear()
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
            if self._signal_rotation(placement) in {90, 270}:
                hit_rect = QRectF(
                    rect.center().x() - box_height / 2.0,
                    rect.center().y() - box_width / 2.0,
                    box_height,
                    box_width,
                )
            else:
                hit_rect = rect
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

        painter.restore()

        if self._editable:
            painter.setPen(QColor("#8fcdf8"))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(
                QRectF(8, full_height - 22, full_width - 16, 16),
                Qt.AlignmentFlag.AlignCenter,
                "Drag an SG indicator to change its display position",
            )

    def _canvas_rect(self) -> QRectF:
        available_height = max(
            1.0,
            float(self.height()) - (24.0 if self._editable else 0.0),
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
        if self._drag_number is not None:
            self._drag_number = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _road_directions(self) -> set[str]:
        base = {
            "FOUR_WAY": {"NORTH", "EAST", "SOUTH", "WEST"},
            "T_JUNCTION": {"NORTH", "EAST", "WEST"},
            "STRAIGHT_ROAD": {"NORTH", "SOUTH"},
            "SINGLE_APPROACH": {"NORTH"},
        }.get(
            self._layout.diagram_type,
            {"NORTH", "EAST", "SOUTH", "WEST"},
        )
        turns = (self._layout.rotation // 90) % 4
        rotated: set[str] = set()
        for direction in base:
            index = self.DIRECTION_ORDER.index(direction)
            rotated.add(self.DIRECTION_ORDER[(index + turns) % 4])
        return rotated

    @staticmethod
    def _draw_roads(
        painter: QPainter,
        directions: set[str],
        center_x: float,
        center_y: float,
        half_road: float,
        road_width: float,
        width: float,
        height: float,
    ) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#303944"))
        painter.drawRect(
            QRectF(
                center_x - half_road,
                center_y - half_road,
                road_width,
                road_width,
            )
        )
        if "NORTH" in directions:
            painter.drawRect(QRectF(center_x - half_road, 0, road_width, center_y))
        if "EAST" in directions:
            painter.drawRect(QRectF(center_x, center_y - half_road, width - center_x, road_width))
        if "SOUTH" in directions:
            painter.drawRect(QRectF(center_x - half_road, center_y, road_width, height - center_y))
        if "WEST" in directions:
            painter.drawRect(QRectF(0, center_y - half_road, center_x, road_width))

    @staticmethod
    def _draw_lane_markings(
        painter: QPainter,
        directions: set[str],
        center_x: float,
        center_y: float,
        half_road: float,
        width: float,
        height: float,
    ) -> None:
        margin = half_road + 8
        pen = QPen(QColor("#d9c66d"), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        if "NORTH" in directions:
            painter.drawLine(QPointF(center_x, 8), QPointF(center_x, center_y - margin))
        if "EAST" in directions:
            painter.drawLine(QPointF(center_x + margin, center_y), QPointF(width - 8, center_y))
        if "SOUTH" in directions:
            painter.drawLine(QPointF(center_x, center_y + margin), QPointF(center_x, height - 8))
        if "WEST" in directions:
            painter.drawLine(QPointF(8, center_y), QPointF(center_x - margin, center_y))

        painter.setPen(QPen(QColor("#edf3f8"), 3))
        inset = 6
        if "NORTH" in directions:
            painter.drawLine(QPointF(center_x - half_road + inset, center_y - half_road - 5), QPointF(center_x + half_road - inset, center_y - half_road - 5))
        if "EAST" in directions:
            painter.drawLine(QPointF(center_x + half_road + 5, center_y - half_road + inset), QPointF(center_x + half_road + 5, center_y + half_road - inset))
        if "SOUTH" in directions:
            painter.drawLine(QPointF(center_x - half_road + inset, center_y + half_road + 5), QPointF(center_x + half_road - inset, center_y + half_road + 5))
        if "WEST" in directions:
            painter.drawLine(QPointF(center_x - half_road - 5, center_y - half_road + inset), QPointF(center_x - half_road - 5, center_y + half_road - inset))

    @staticmethod
    def _draw_direction_labels(
        painter: QPainter,
        directions: set[str],
        width: float,
        height: float,
    ) -> None:
        painter.setPen(QColor("#b8c9d8"))
        font = QFont("Segoe UI", 8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        labels = {
            "NORTH": ("NORTH", QRectF(width / 2 - 42, 5, 84, 18)),
            "EAST": ("EAST", QRectF(width - 76, height / 2 - 25, 68, 18)),
            "SOUTH": ("SOUTH", QRectF(width / 2 - 42, height - 23, 84, 18)),
            "WEST": ("WEST", QRectF(8, height / 2 + 8, 68, 18)),
        }
        for direction in directions:
            text, rect = labels[direction]
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_vehicle_flow(
        self,
        painter: QPainter,
        placement: SignalPlacement,
        signal_group: SignalGroupState,
        width: float,
        height: float,
    ) -> None:
        flow = placement.flow_direction.upper()
        if flow == "HIDDEN":
            return
        approach = self._approach_index(placement)
        exits = self._movement_exits(approach, placement.movements)
        center = QPointF(width / 2.0, height / 2.0)
        lane_offset = min(width, height) * 0.32 * 0.22
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

        if flow in {"INBOUND", "TWO_WAY"}:
            for exit_direction in exits:
                inbound = self._route_path(
                    self._lane_edge_point(
                        approach,
                        True,
                        width,
                        height,
                        lane_offset,
                    ),
                    self._lane_edge_point(
                        exit_direction,
                        False,
                        width,
                        height,
                        lane_offset,
                    ),
                    center,
                    exit_direction == (approach + 2) % 4,
                )
                self._draw_flow_path(painter, inbound, pen, color)

        # Outbound describes the opposite lane on this road arm, not a
        # reversed copy of each selected inbound turn. Drawing it once avoids
        # Left/Right producing an unwanted reverse-turn flow in Two-Way mode.
        if flow in {"OUTBOUND", "TWO_WAY"}:
            outbound = QPainterPath(
                self._lane_inner_point(
                    approach,
                    width,
                    height,
                    lane_offset,
                )
            )
            outbound.lineTo(
                self._lane_edge_point(
                    approach,
                    False,
                    width,
                    height,
                    lane_offset,
                )
            )
            self._draw_flow_path(painter, outbound, pen, color)

    @staticmethod
    def _approach_index(placement: SignalPlacement) -> int:
        dx = placement.x - 0.5
        dy = placement.y - 0.5
        if abs(dx) > abs(dy):
            return 1 if dx > 0 else 3
        return 2 if dy > 0 else 0

    @staticmethod
    def _movement_exits(approach: int, movements: list[str]) -> list[int]:
        mapping = {
            "STRAIGHT": (approach + 2) % 4,
            "LEFT": (approach + 1) % 4,
            "RIGHT": (approach - 1) % 4,
        }
        selected = [
            mapping[item]
            for item in ("STRAIGHT", "LEFT", "RIGHT")
            if item in movements
        ]
        return selected or [mapping["STRAIGHT"]]

    @staticmethod
    def _lane_edge_point(
        direction: int,
        inbound: bool,
        width: float,
        height: float,
        offset: float,
    ) -> QPointF:
        center_x = width * 0.50
        center_y = height * 0.50
        return (
            QPointF(center_x + (offset if inbound else -offset), height * 0.11)
            if direction == 0
            else QPointF(width * 0.89, center_y + (offset if inbound else -offset))
            if direction == 1
            else QPointF(center_x + (-offset if inbound else offset), height * 0.89)
            if direction == 2
            else QPointF(width * 0.11, center_y + (-offset if inbound else offset))
        )

    @staticmethod
    def _lane_inner_point(
        direction: int,
        width: float,
        height: float,
        offset: float,
    ) -> QPointF:
        center_x = width * 0.50
        center_y = height * 0.50
        inner_distance = min(width, height) * 0.07
        return (
            QPointF(center_x - offset, center_y - inner_distance)
            if direction == 0
            else QPointF(center_x + inner_distance, center_y - offset)
            if direction == 1
            else QPointF(center_x + offset, center_y + inner_distance)
            if direction == 2
            else QPointF(center_x - inner_distance, center_y + offset)
        )

    @staticmethod
    def _route_path(
        start: QPointF,
        end: QPointF,
        center: QPointF,
        straight: bool,
    ) -> QPainterPath:
        path = QPainterPath(start)
        if straight:
            path.lineTo(end)
        else:
            path.quadTo(center, end)
        return path

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

    @staticmethod
    def _signal_rotation(placement: SignalPlacement) -> int:
        if placement.rotation in {0, 90, 180, 270}:
            return placement.rotation
        return (
            90
            if abs(placement.x - 0.5) > abs(placement.y - 0.5)
            else 0
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
